"""Étape 1 — scénario : découpage d'un chapitre en pages → cases par le LLM.

1. contexte : série, personnages, bibliothèque (décors et objets, avec leurs ids), résumés des chapitres précédents (continuité), synopsis, bible de
   la série et passages du savoir-faire (`pipeline/knowledge.py`, enregistrés dans `llm_runs`) ;
2. prompt rendu depuis `presets/prompts/script.yaml` (aucun texte de prompt dans ce module) ; le scénario
   garde l'histoire, l'intention et ce que fait chaque personnage, mais ne compose pas : ni plan, ni place
   dans le cadre (« qui à gauche, qui à droite ») — c'est le travail de la direction artistique
   (`pipeline/art_direction.py`), appliqué aux cases avant la génération ;
3. réponse JSON validée par Pydantic, puis les ids de décor / d'objets contre la bibliothèque de la
   série ; invalide → nouvel essai avec l'erreur renvoyée au LLM
   (`max_retries` du preset, 2 au maximum) → sinon `ScriptError` lisible ;
   puis les règles de dialogue (`dialogue_rules` du preset, `pipeline/dialogues.py`) : densité, case
   d'action jamais réduite à son onomatopée, pensée / voix off / narration, place réelle des bulles une
   fois la page mise en page ; et la charte de la série (ADN, `pipeline/pre_direction.py`) : cases par
   planche, dialogue compté par planche ; enfreintes → même relance, puis le découpage est gardé avec des
   avertissements (écran Scénario). La charte arrive en clair dans le prompt (`$pre_direction`) ;
   Lieu de chaque case (`lieu`) : un lieu de la série par son id, ou un nouveau lieu par son nom (créé à
   l'enregistrement, `pipeline/locations.py`) ; `setting` n'est plus que la précision de cadrage ;
4. personnages de chaque case : « characters » = présents à l'image, « offscreen » = cités mais hors cadre ;
   un présent que la description ne cite pas passe hors cadre (`framing.settle_cast`) ;
5. enregistrement en Pages + Panels + Bubbles (remplace les pages « story » du chapitre) et
   du résumé du chapitre, puis découpage automatique des pages (étape 2) ;
6. scènes validées (étape « Scènes », `pipeline/scenes.py`) : la liste arrive en clair dans le prompt (`$scenes` :
   scène, type, pages, profil de tempo) ; chaque page rendue porte sa scène (`scene`), le nombre de pages de chaque
   scène est contrôlé (relance, puis avertissement) et chaque page enregistrée est rattachée à sa scène. Sans scènes
   validées (chapitre d'avant, ou étape passée outre), rien ne change ;
7. name scène par scène (`pipeline/scene_name.py`) : avec des scènes validées, une génération PAR SCÈNE
   (`presets/prompts/script-scene.yaml`, règles de name dans le preset) — la liste validée, le résumé des scènes déjà
   écrites et le profil de la scène en clair ; la charte de la scène (ADN de la série précisé par son profil) prime à
   l'intérieur de la scène : pages de la scène, cases et répliques par planche, cases muettes, encadrés de narration
   et « une action par case » contrôlés (relance, puis avertissement). Une seule scène se réécrit (`scene_id`) sans
   toucher aux pages des autres (`save_scene`).
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetError, PresetRegistry, PromptPreset
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.db import Database
from ..store.models import (
    Bubble,
    BubbleKind,
    Chapter,
    ChapterStatus,
    Character,
    LLMRun,
    Page,
    PageKind,
    Panel,
)
from ..validation import format_errors
from .dialogues import DialoguePanel, Reply, check_dialogues, dialogue_text, room_problems
from .framing import aliases_from, settle_cast, split_cast
from .knowledge import AgentKnowledge, KnowledgeBase
from .layout import LayoutError
from .library import SeriesLibrary, named_in_text, named_objects, split_named_objects
from .locations import resolve_location
from .names import CharacterMatcher, link_speakers, panel_ids
from .pages import layout_pages
from .pre_direction import Charter, dialogue_rules_for, panel_count_problems, script_text, series_charter
from .scene_name import (
    SCENE_PROMPT,
    SceneFrame,
    action_problems,
    fiches_text,
    frame_of,
    narration_limit,
    narration_problems,
    scene_frames,
)
from .scenes import assign_scenes, scene_page_problems, scenes_text, script_scenes
from .style import NO_GUIDELINES, style_brief, style_names

AGENT = "script"  # rôle de l'agent dans presets/knowledge.yaml

SHOT_TYPES = (
    "plan d'ensemble",
    "plan large",
    "plan moyen",
    "plan américain",
    "plan rapproché",
    "gros plan",
    "très gros plan",
    "plongée",
    "contre-plongée",
    "vue subjective",
    "insert",
)
ShotType = Literal[
    "plan d'ensemble",
    "plan large",
    "plan moyen",
    "plan américain",
    "plan rapproché",
    "gros plan",
    "très gros plan",
    "plongée",
    "contre-plongée",
    "vue subjective",
    "insert",
]
# Types de réplique proposés au LLM ; les onomatopées (sfx) ont leur propre liste par case.
BUBBLE_KINDS = tuple(k.value for k in BubbleKind if k != BubbleKind.sfx)
BubbleKindName = Literal["speech", "thought", "shout", "narration", "off"]
# Indices de direction artistique (facultatifs) lus par la grammaire de mise en page (layout_style.py).
INTENSITIES = ("calme", "normal", "choc")
RYTHMES = ("lent", "normal", "rapide")
IntensityName = Literal["calme", "normal", "choc"]
RythmeName = Literal["lent", "normal", "rapide"]
MAX_PANELS_PER_PAGE = 9
MAX_PAGES = 60
MAX_PANEL_OBJECTS = 8

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


def _hint(value: Any) -> Any:
    """« Choc », « CALME » → minuscules ; une chaîne vide ou null = non précisé."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        return v or None
    return value


def normalize_shot_type(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    v = " ".join(value.strip().lower().replace("’", "'").split())
    return v.replace("contre plongée", "contre-plongée") or None


class _LLMModel(BaseModel):
    # Les LLM ajoutent volontiers des champs : on les ignore plutôt que d'échouer.
    model_config = ConfigDict(extra="ignore")


class ScriptDialogue(_LLMModel):
    speaker: Short = ""
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    kind: BubbleKindName = "speech"

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v


class ScriptSfx(_LLMModel):
    """Onomatopée de la case (« VROUM ! », « CLIC ») : posée au lettrage, jamais dessinée par le modèle d'image."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    intensity: IntensityName | None = None

    _intensity = field_validator("intensity", mode="before")(_hint)


SceneText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1500)]


class ScriptPanel(_LLMModel):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    # Lieu (lieu, moment, éléments du décor) et mise en scène (qui fait quoi, où dans le cadre,
    # interactions) : repris tels quels dans le prompt image, même sans décor de la bibliothèque.
    setting: SceneText = ""
    staging: SceneText = ""
    # Présents À L'IMAGE (dessinés) ; `offscreen` : cités par la case mais hors cadre (jamais dessinés).
    characters: list[Short] = Field(default_factory=list, max_length=20)
    offscreen: list[Short] = Field(
        default_factory=list,
        max_length=20,
        validation_alias=AliasChoices("offscreen", "hors_cadre", "offscreen_characters"),
    )
    # Plus demandé au scénariste (la direction artistique cadre) ; accepté s'il est donné, comme dans les
    # chapitres déjà écrits : repli de la génération tant qu'aucune direction n'est appliquée.
    shot_type: ShotType | None = None
    dialogues: list[ScriptDialogue] = Field(default_factory=list, max_length=12)
    importance: int = Field(default=2, ge=1, le=3)
    intensity: IntensityName | None = None
    sfx: list[ScriptSfx] = Field(default_factory=list, max_length=4)
    # Bibliothèque de la série : id du décor (ou null) et ids des objets visibles.
    decor: int | None = None
    objets: list[int] = Field(default_factory=list, max_length=MAX_PANEL_OBJECTS)
    # Lieu de la série : id d'un lieu existant, ou nom d'un nouveau lieu (créé à l'enregistrement) ; null = aucun.
    lieu: int | Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None

    _shot = field_validator("shot_type", mode="before")(normalize_shot_type)
    _intensity = field_validator("intensity", mode="before")(_hint)

    @field_validator("setting", "staging", mode="before")
    @classmethod
    def _no_text(cls, v: Any) -> Any:
        return "" if v is None else v

    @field_validator("decor", mode="before")
    @classmethod
    def _no_decor(cls, v: Any) -> Any:
        return None if v in ("", "null", "aucun") else v

    @field_validator("lieu", mode="before")
    @classmethod
    def _lieu(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if v.isdigit():
                return int(v)
            return None if v.lower() in ("", "null", "aucun") else v
        return v

    @field_validator("objets", mode="before")
    @classmethod
    def _no_objects(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("objets")
    @classmethod
    def _unique_objects(cls, v: list[int]) -> list[int]:
        return list(dict.fromkeys(v))

    @field_validator("characters", "offscreen", mode="before")
    @classmethod
    def _no_names(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("characters", "offscreen")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for name in v:
            if name and name not in out:
                out.append(name)
        return out

    @model_validator(mode="after")
    def _present_wins(self) -> ScriptPanel:
        """Un nom à la fois présent et hors cadre est présent."""
        self.offscreen = split_cast(self.characters, self.offscreen)[1]
        return self


class ScriptPage(_LLMModel):
    panels: list[ScriptPanel] = Field(min_length=1, max_length=MAX_PANELS_PER_PAGE)
    rythme: RythmeName | None = None
    # Numéro de la scène validée de la page (1 = première scène) ; None sans liste de scènes.
    scene: int | None = Field(default=None, validation_alias=AliasChoices("scene", "scène"))

    _rythme = field_validator("rythme", mode="before")(_hint)

    @field_validator("scene", mode="before")
    @classmethod
    def _scene(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return int(v) if v.isdigit() else None
        return v if isinstance(v, int) and not isinstance(v, bool) else None


class ScriptOutput(_LLMModel):
    pages: list[ScriptPage] = Field(min_length=1, max_length=MAX_PAGES)
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


ERROR_LABELS = {
    "pages": "page",
    "panels": "case",
    "dialogues": "réplique",
    "characters": "personnage",
    "offscreen": "personnage hors cadre",
    "sfx": "onomatopée",
    "objets": "objet",
}


class ScriptError(Exception):
    """Échec de l'étape scénario, message lisible par l'utilisateur."""


class ScriptValidationError(ValueError):
    pass


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_script(text: str, library: SeriesLibrary | None = None) -> ScriptOutput:
    """Valide la réponse brute du LLM ; `ScriptValidationError` explique ce qui ne va pas.

    Avec `library`, chaque décor et objet cité doit exister dans la bibliothèque de la série.
    """
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScriptValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise ScriptValidationError("la racine doit être un objet JSON avec « pages » et « summary »")
    try:
        out = ScriptOutput.model_validate(data)
    except ValidationError as exc:
        raise ScriptValidationError(format_errors(exc, ERROR_LABELS)) from None
    if library is not None:
        problems = [
            f"page {p} › case {c} › {problem}"
            for p, page in enumerate(out.pages, start=1)
            for c, panel in enumerate(page.panels, start=1)
            for problem in [*library.check_refs(panel.decor, panel.objets), *library.check_location(panel.lieu)]
        ]
        if problems:
            extra = f" ; … et {len(problems) - 8} autre(s)" if len(problems) > 8 else ""
            raise ScriptValidationError(" ; ".join(problems[:8]) + extra)
    return out


# --- contexte -------------------------------------------------------------------
@dataclass
class ScriptContext:
    series: dict[str, Any]
    characters: list[dict[str, Any]]
    previous_chapters: list[dict[str, Any]]
    chapter: dict[str, Any]
    knowledge: AgentKnowledge | None = None
    library: SeriesLibrary = field(default_factory=SeriesLibrary)
    charter: Charter | None = None  # ADN de la série (presets/pre_direction.yaml)
    # Scènes validées (pipeline/scenes.py `script_scenes`) ; vide : découpage libre (ancien mode).
    scenes: list[dict[str, Any]] = field(default_factory=list)
    # Name scène par scène : la scène à écrire (sa charte est alors `charter`), ce qui est déjà écrit, et les fiches
    # du savoir-faire citées pour son type.
    focus: SceneFrame | None = None
    written: str = ""
    fiches: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "task": "script",
            "pre_direction": self.charter.as_json() if self.charter else None,
            "scenes": self.scenes,
            **({"scene": self.focus.as_json(), "written_scenes": self.written} if self.focus else {}),
            "series": self.series,
            "characters": self.characters,
            **self.library.as_json(),
            "previous_chapters": self.previous_chapters,
            "chapter": self.chapter,
            "bubble_kinds": list(BUBBLE_KINDS),
            "intensities": list(INTENSITIES),
            "rythmes": list(RYTHMES),
        }


DIRECTION_LABELS = {"rtl": "de droite à gauche (manga)", "ltr": "de gauche à droite (BD, comics)"}


def knowledge_query(presets: PresetRegistry, chapter: Chapter) -> str:
    """Requête de recherche du savoir-faire pour un chapitre : titre, synopsis, packs de style de la série."""
    style = style_names(presets, chapter.project)
    return "\n".join(p for p in (chapter.title, chapter.synopsis, style) if p and p.strip())


def build_context(
    session: Session,
    presets: PresetRegistry,
    chapter: Chapter,
    *,
    max_previous: int,
    knowledge: KnowledgeBase | None = None,
) -> ScriptContext:
    series = chapter.project
    brief = style_brief(presets, series)
    characters = session.scalars(
        select(Character).where(Character.project_id == series.id).order_by(Character.name)
    ).all()
    previous = session.scalars(
        select(Chapter)
        .where(Chapter.project_id == series.id, Chapter.number < chapter.number)
        .order_by(Chapter.number.desc())
        .limit(max_previous)
    ).all()
    return ScriptContext(
        series={
            "title": series.title,
            "style": brief.packs,
            "style_guidelines": brief.guidelines,
            "reading_direction": series.reading_direction.value,
        },
        characters=[
            {"name": c.name, "aliases": list(c.aliases or []), "description": c.visual_description} for c in characters
        ],
        previous_chapters=[
            {"number": c.number, "title": c.title, "summary": c.summary or "(pas encore de résumé)"}
            for c in reversed(previous)
        ],
        chapter={
            "number": chapter.number,
            "title": chapter.title,
            "synopsis": chapter.synopsis,
            "target_pages": chapter.target_page_count,
        },
        knowledge=knowledge.for_agent(
            session, AGENT, series.id, knowledge_query(presets, chapter), genre=series.style_genre
        )
        if knowledge
        else None,
        library=SeriesLibrary.load(session, series.id),
        charter=series_charter(presets, series),
        scenes=script_scenes(presets, chapter),
    )


def _render(template: str, values: dict[str, str], part: str) -> str:
    try:
        return string.Template(template).substitute(values)
    except KeyError as exc:
        raise PresetError(f"presets/prompts : variable inconnue ${exc.args[0]} dans « {part} »") from None
    except ValueError as exc:
        raise PresetError(f"presets/prompts : gabarit « {part} » invalide ({exc})") from None


def _aliases(character: dict[str, Any]) -> str:
    aliases = [a for a in character.get("aliases") or [] if a]
    return f" (aussi appelé : {', '.join(aliases)})" if aliases else ""


def scene_rules(prompt: PromptPreset, ctx: ScriptContext) -> Any:
    """Règles de dialogue d'une génération : celles du preset aux valeurs par planche de la charte (de la scène en
    name scène par scène, où la pensée / voix off / narration se compte sur le chapitre, pas dans chaque scène)."""
    rules = dialogue_rules_for(prompt.dialogue_rules, ctx.charter)
    if rules is not None and ctx.focus is not None:
        rules = rules.model_copy(update={"require_inner_voice": False})
    return rules


def render_messages(
    prompt: PromptPreset, ctx: ScriptContext, templates: PromptPreset | None = None
) -> list[ChatMessage]:
    """Messages du scénariste : gabarits de `templates` (prompts/script-scene.yaml pour une scène) ou du preset."""
    templates = templates or prompt
    chars = "\n".join(
        f"- {c['name']}{_aliases(c)} : {c['description'] or '(sans description)'}" for c in ctx.characters
    )
    prev = "\n".join(
        f"- Chapitre {c['number']}{' — ' + c['title'] if c['title'] else ''} : {c['summary']}"
        for c in ctx.previous_chapters
    )
    values = {
        "series_title": ctx.series["title"],
        # Packs de style de la série (genre, rendu, ton, réglages) et consignes du genre et du ton.
        "style_packs": ctx.series["style"] or "(non précisé)",
        "style_guidelines": ctx.series.get("style_guidelines") or NO_GUIDELINES,
        "series_style": ctx.series["style"] or "(non précisé)",  # ancien nom de $style_packs
        "reading_direction": DIRECTION_LABELS.get(ctx.series["reading_direction"], ctx.series["reading_direction"]),
        "characters": chars or "(aucun personnage enregistré)",
        # Noms exacts des fiches, à recopier tels quels dans « characters » et « speaker ».
        "character_names": ", ".join(f"« {c['name']} »" for c in ctx.characters) or "(aucune fiche personnage)",
        "decors": ctx.library.text("decors") or "(aucun décor enregistré : « decor » vaut null)",
        "objets": ctx.library.text("objets") or "(aucun objet enregistré : « objets » reste vide)",
        "lieux": ctx.library.text("lieux") or "(aucun lieu enregistré : donne à chaque lieu un nom court)",
        "previous_chapters": prev or "(premier chapitre de la série)",
        "chapter_number": str(ctx.chapter["number"]),
        "chapter_title": ctx.chapter["title"] or "sans titre",
        "synopsis": ctx.chapter["synopsis"],
        "target_pages": str(ctx.chapter["target_pages"]),
        "shot_types": ", ".join(SHOT_TYPES),  # plus dans le gabarit livré ; gardé pour les prompts personnalisés
        "bubble_kinds": ", ".join(BUBBLE_KINDS),
        "intensities": ", ".join(INTENSITIES),
        "rythmes": ", ".join(RYTHMES),
        "dialogue_rules": dialogue_text(scene_rules(prompt, ctx)),
        # Charte de la série (ADN) : cases par planche, dialogue par planche, courbe de rythme.
        "pre_direction": script_text(ctx.charter, int(ctx.chapter.get("target_pages") or 0)),
        # Scènes validées par l'auteur (étape Scènes) : scène, type, pages, profil de tempo.
        "scenes": scenes_text(ctx.scenes),
        "context_json": json.dumps(ctx.as_json(), ensure_ascii=False, indent=2),
        "savoir_faire": (ctx.knowledge.savoir_faire() if ctx.knowledge else "")
        or "(aucun savoir-faire pour cet agent)",
        "bible": (ctx.knowledge.bible_text() if ctx.knowledge else "") or "(pas encore de bible pour cette série)",
    }
    f = ctx.focus
    if f is not None:
        values.update(
            {
                "target_pages": str(f.pages),
                "scene_number": str(f.number),
                "scene_title": f.title or "sans titre",
                "scene_type": f.type,
                "scene_type_name": f.type_name,
                "scene_summary": f.summary,
                "scene_pages": str(f.pages),
                "scene_first_page": str(f.first_page),
                "scene_last_page": str(f.last_page),
                "scene_tempo": f.tempo,
                "scene_fiches": ctx.fiches or "(pas de fiche citée pour ce type de scène)",
                "written_scenes": ctx.written or "(rien encore : c'est la première scène écrite)",
            }
        )
    return [
        ChatMessage("system", _render(templates.system, values, "system")),
        ChatMessage("user", _render(templates.user, values, "user")),
    ]


# --- règles de dialogue ------------------------------------------------------------
def script_panels(output: ScriptOutput) -> list[DialoguePanel]:
    """Cases de la réponse du LLM, vues par les règles de dialogue."""
    return [
        DialoguePanel(
            page=p,
            index=i,
            panels_on_page=len(page.panels),
            characters=list(panel.characters),
            importance=panel.importance,
            intensity=panel.intensity,
            replies=[Reply(d.kind, d.text, d.speaker) for d in panel.dialogues],
            sfx=[fx.text for fx in panel.sfx],
        )
        for p, page in enumerate(output.pages, start=1)
        for i, panel in enumerate(page.panels, start=1)
    ]


# --- appel du LLM avec relances -------------------------------------------------
Progress = Callable[[int, str], None]
# Contrôle supplémentaire d'une réponse valide (place réelle des bulles) : problèmes lisibles, [] si rien.
Check = Callable[[ScriptOutput], list[str]]


@dataclass
class ScriptRun:
    output: ScriptOutput
    attempts: int
    messages: list[ChatMessage]
    # Règles de dialogue encore enfreintes après les relances (découpage gardé, avertissements).
    warnings: list[str] = field(default_factory=list)


def focus_problems(output: ScriptOutput, ctx: ScriptContext, templates: PromptPreset | None) -> list[str]:
    """Name d'une scène : nombre de pages de la scène, encadrés de narration par planche (profil) et « une action
    par case » (`one_action` de prompts/script-scene.yaml)."""
    f = ctx.focus
    if f is None:
        return []
    out = []
    if len(output.pages) != f.pages:
        got = len(output.pages)
        out.append(f"scène {f.number} ({f.type_name}) : {got} page{'s' if got > 1 else ''} au lieu de {f.pages}")
    counts = [sum(1 for pa in page.panels for d in pa.dialogues if d.kind == "narration") for page in output.pages]
    out += narration_problems(counts, narration_limit(f.profile))
    texts = [(p, c, pa.description) for p, page in enumerate(output.pages, 1) for c, pa in enumerate(page.panels, 1)]
    out += action_problems(texts, templates.one_action if templates is not None else None)
    return out


def run_script(
    llm: LLMProvider,
    prompt: PromptPreset,
    ctx: ScriptContext,
    progress: Progress,
    check: Check | None = None,
    *,
    templates: PromptPreset | None = None,
) -> ScriptRun:
    """Réponse validée du scénariste, avec relances. `templates` : gabarits d'une scène (name scène par scène,
    `ctx.focus`) ; le reste (essais, température, règles de dialogue) vient du preset `prompt`."""
    messages = render_messages(prompt, ctx, templates)
    retry_template = (templates or prompt).retry
    total = 1 + prompt.max_retries
    last_error = ""
    # Dernière réponse valide qui n'enfreint que les règles de dialogue : gardée si les relances échouent.
    fallback: ScriptRun | None = None
    for attempt in range(1, total + 1):
        progress(10 + (attempt - 1) * 25, f"Écriture du découpage par le LLM (essai {attempt}/{total})…")
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if fallback is not None and (not exc.retryable or attempt == total):
                return fallback  # relance des dialogues sans réponse : on garde le découpage valide
            if not exc.retryable or attempt == total:
                raise ScriptError(f"Le LLM n'a pas pu répondre : {exc}") from exc
            last_error = str(exc)
            progress(10 + attempt * 25, f"Le LLM n'a pas répondu ({exc}), nouvel essai…")
            continue
        try:
            output = parse_script(result.text, ctx.library)
            counts = panel_count_problems([len(p.panels) for p in output.pages], ctx.charter)
            if ctx.focus is not None:
                scene_pages = focus_problems(output, ctx, templates)
                profile = [p for p in scene_pages if not p.startswith(("scène ", "une action par case"))]
                actions = [p for p in scene_pages if p.startswith("une action par case")]
                scene_pages = [p for p in scene_pages if p.startswith("scène ")]
            else:
                scene_pages = scene_page_problems([p.scene for p in output.pages], ctx.scenes)
                profile, actions = [], []
            problems = check_dialogues(script_panels(output), scene_rules(prompt, ctx))
            if check is not None:
                problems += check(output)
            if problems or counts or scene_pages or profile or actions:
                fallback = ScriptRun(
                    output=output,
                    attempts=attempt,
                    messages=messages,
                    warnings=scene_pages + counts + profile + actions + problems,
                )
                where = "de la scène" if ctx.focus is not None else "de la série"
                parts = []
                if scene_pages:
                    parts.append("pages par scène hors de la liste validée : " + " ; ".join(scene_pages[:8]))
                if counts:
                    parts.append(f"cases par planche hors de la charte {where} : " + " ; ".join(counts[:8]))
                if profile:
                    parts.append("profil de la scène à respecter : " + " ; ".join(profile[:8]))
                if actions:
                    parts.append(" ; ".join(actions[:8]))
                if problems:
                    parts.append("dialogues à revoir : " + " ; ".join(problems[:12]))
                raise ScriptValidationError(" ; ".join(parts))
        except ScriptValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                progress(10 + attempt * 25, f"Réponse invalide ({last_error[:160]}), nouvel essai…")
                retry = _render(retry_template, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return ScriptRun(output=output, attempts=attempt, messages=messages)
    if fallback is not None:
        return fallback
    raise ScriptError(f"Le LLM a renvoyé un découpage invalide {total} fois de suite. Dernière erreur : {last_error}")


# --- enregistrement -------------------------------------------------------------
def save_script(
    session: Session,
    chapter: Chapter,
    output: ScriptOutput,
    scenes: list[dict[str, Any]] | None = None,
    *,
    scene_ids: Sequence[int | None] | None = None,
) -> list[Page]:
    """Remplace les pages « story » du chapitre ; les pages bonus / de garde sont conservées à la suite. Avec
    `scenes` (scènes validées), chaque page est rattachée à sa scène (`assign_scenes`), ou à celle de `scene_ids`
    (name scène par scène : la scène qui a écrit la page)."""
    if scene_ids is None:
        scene_ids = assign_scenes([p.scene for p in output.pages], scenes or [])
    # Sans autoflush : la cascade de `session.delete` charge les relations de la page (cases, direction
    # artistique) ; un autoflush à ce moment, page déjà retirée de `chapter.pages`, fait échouer la session
    # (« Failed to add object to the flush context ») et un second « Découper » n'était jamais enregistré.
    with session.no_autoflush:
        for page in list(chapter.pages):
            if page.kind == PageKind.story:
                chapter.pages.remove(page)
                session.delete(page)
    session.flush()
    kept = list(chapter.pages)
    for i, page in enumerate(kept):  # libère les numéros 1..n sans violer l'unicité
        page.number = -(i + 1)
    session.flush()

    created = _new_pages(session, chapter, output, list(scene_ids), first=1)
    for page in created:
        chapter.pages.append(page)
    for i, page in enumerate(kept):
        page.number = len(created) + i + 1
    chapter.summary = output.summary
    if chapter.status == ChapterStatus.draft:
        chapter.status = ChapterStatus.script
    session.flush()
    return created


def _new_pages(
    session: Session,
    chapter: Chapter,
    output: ScriptOutput,
    scene_ids: list[int | None],
    *,
    first: int,
    previous: Panel | None = None,
) -> list[Page]:
    """Pages, cases et bulles d'une réponse du scénariste, numérotées à partir de `first` (pas encore rattachées au
    chapitre). `previous` : dernière case avant ces pages (arbitrage des noms, pipeline/names.py)."""
    # Noms rapprochés des fiches (casse, accents, alias, nom partiel : pipeline/names.py) ; un nom sans
    # fiche reste dans `character_names` et l'API le signale à l'auteur.
    matcher = CharacterMatcher.for_project(session, chapter.project_id)
    aliases = aliases_from(matcher)
    # Un véhicule ou une créature de la bibliothèque cité parmi les personnages (« Momo » le chat) : rattaché à
    # la case par son nom, comme un objet — une créature n'entre pas dans la distribution du chapitre.
    named = named_objects(session, chapter.project_id, {" ".join(key) for card in matcher.cards for key in card.keys})
    created: list[Page] = []
    for p_index, sp in enumerate(output.pages):
        page = Page(
            chapter_id=chapter.id,
            number=first + p_index,
            kind=PageKind.story,
            rythme=sp.rythme,
            scene_id=scene_ids[p_index] if p_index < len(scene_ids) else None,
        )
        for i, sc in enumerate(sp.panels):
            cast_names, named_ids = split_named_objects(sc.characters, named)
            offscreen_names, _ = split_named_objects(sc.offscreen, named)
            present, offscreen = settle_cast(sc.description, cast_names, offscreen_names, aliases)
            panel = Panel(
                index=i,
                description=sc.description,
                setting=sc.setting,
                staging=sc.staging,
                character_names=present,
                offscreen_names=offscreen,
                shot_type=sc.shot_type,
                importance=sc.importance,
                intensity=sc.intensity,
                decor_id=sc.decor,
                object_ids=list(dict.fromkeys([*sc.objets, *named_ids, *named_in_text(sc.description, named)])),
            )
            panel.location = resolve_location(session, chapter.project_id, sc.lieu, decor_id=sc.decor)
            for j, d in enumerate(sc.dialogues):
                panel.bubbles.append(
                    Bubble(
                        order=j,
                        speaker_name=d.speaker,
                        text=d.text,
                        kind=BubbleKind(d.kind),
                    )
                )
            for k, fx in enumerate(sc.sfx):
                panel.bubbles.append(
                    Bubble(
                        order=len(sc.dialogues) + k,
                        text=fx.text,
                        kind=BubbleKind.sfx,
                        sfx={"intensity": fx.intensity} if fx.intensity else None,
                    )
                )
            # Fiches des présents et des locuteurs, arbitrage compris (names.py) ; un nom ambigu, sans fiche
            # ou cité sans être déclaré est signalé à l'auteur par l'API (`name_notes`).
            panel.character_ids = panel_ids(matcher, panel, previous)
            link_speakers(matcher, panel, previous)
            page.panels.append(panel)
            previous = panel
        created.append(page)
    return created


def save_scene(session: Session, chapter: Chapter, frame: SceneFrame, output: ScriptOutput) -> list[Page]:
    """Name d'UNE scène : remplace les seules pages de l'histoire rattachées à cette scène (les pages, cases, croquis
    et versions des autres scènes ne sont pas touchés), placées à la position de la scène ; les pages sont
    renumérotées dans l'ordre des scènes, les pages bonus / de garde à la suite."""
    order = {s.id: i for i, s in enumerate(chapter.scenes)}
    position = order.get(frame.id, len(order))
    with session.no_autoflush:
        for page in list(chapter.pages):
            if page.kind == PageKind.story and page.scene_id == frame.id:
                chapter.pages.remove(page)
                session.delete(page)
    session.flush()
    story = sorted(
        (p for p in chapter.pages if p.kind == PageKind.story),
        key=lambda p: (order.get(p.scene_id, len(order)) if p.scene_id is not None else len(order), p.number),
    )
    others = sorted((p for p in chapter.pages if p.kind != PageKind.story), key=lambda p: p.number)
    for i, page in enumerate([*story, *others]):  # libère les numéros sans violer l'unicité
        page.number = -(i + 1)
    session.flush()
    before = [
        p for p in story if (order.get(p.scene_id, len(order)) if p.scene_id is not None else len(order)) < position
    ]
    after = [p for p in story if p not in before]
    previous = before[-1].panels[-1] if before and before[-1].panels else None
    created = _new_pages(session, chapter, output, [frame.id] * len(output.pages), first=0, previous=previous)
    for i, page in enumerate([*before, *created, *after, *others], start=1):
        page.number = i
    for page in created:
        chapter.pages.append(page)
    if chapter.status == ChapterStatus.draft:
        chapter.status = ChapterStatus.script
    session.flush()
    return created


# --- job ------------------------------------------------------------------------
def record_run(
    session: Session, chapter: Chapter, knowledge: AgentKnowledge, *, job_id: int | None, model: str | None
) -> LLMRun:
    """Garde la trace de ce que l'agent a reçu (« Sources utilisées » de l'écran Scénario)."""
    run = LLMRun(
        job_id=job_id,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        agent=knowledge.role,
        model=model,
        query=knowledge.query,
        passages=[p.as_dict() for p in knowledge.passages],
        bible=knowledge.bible.as_dict() if knowledge.bible else None,
        collections=knowledge.collections,
    )
    session.add(run)
    return run


def script_job(
    db: Database,
    presets: PresetRegistry,
    llm: LLMProvider,
    chapter_id: int,
    *,
    knowledge: KnowledgeBase | None = None,
    job_id: int | None = None,
    scene_id: int | None = None,
) -> Callable[[Progress], str]:
    """Fonction exécutée par le `JobRunner` pour « Découper » un chapitre — scène par scène quand ses scènes sont
    validées — ou réécrire une seule scène (`scene_id`)."""

    def run(progress: Progress) -> str:
        prompt = presets.prompt("script")
        templates = presets.prompts.get(SCENE_PROMPT)
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ScriptError("Chapitre introuvable (supprimé pendant le découpage ?)")
            progress(5, "Préparation du contexte (série, personnages, décors et objets, chapitres précédents, bible…)…")
            ctx = build_context(
                session, presets, chapter, max_previous=prompt.max_previous_chapters, knowledge=knowledge
            )
            frames = scene_frames(presets, chapter) if templates is not None else []
            if scene_id is not None and frame_of(frames, scene_id) is None:
                raise ScriptError("Scène introuvable, ou liste des scènes pas validée : valide-la dans l'onglet Scènes")
            fiches = {f.id: fiches_text(session, f.fiches) for f in frames}
            others = _written_from_pages(chapter, frames, scene_id) if scene_id is not None else ""
            if ctx.knowledge is not None:
                record_run(session, chapter, ctx.knowledge, job_id=job_id, model=getattr(llm, "model", llm.name))
                session.commit()
        if frames and templates is not None:
            return _run_scenes(
                db, presets, llm, chapter_id, prompt, templates, ctx, frames, fiches, others, scene_id, progress
            )
        rules = prompt.dialogue_rules

        def room(output: ScriptOutput) -> list[str]:
            """Place réelle : découpage enregistré et mis en page à blanc (annulé), bulles lettrées."""
            if rules is None or not rules.check_room:
                return []
            with db.session_scope() as session:
                chapter = session.get(Chapter, chapter_id)
                if chapter is None:
                    return []
                try:
                    pages = save_script(session, chapter, output, ctx.scenes)
                    layout_pages(presets, pages)
                    return room_problems(presets, pages, rules=rules)
                except LayoutError:
                    return []  # l'erreur de mise en page sera signalée à l'enregistrement
                finally:
                    session.rollback()

        # Pas de session ouverte pendant l'appel au LLM (qui peut durer plusieurs minutes).
        run = run_script(llm, prompt, ctx, progress, room)
        # (aucun rapport de progression dans la transaction d'écriture : SQLite n'a qu'un écrivain)
        progress(85, "Enregistrement des pages, cases et bulles, puis mise en page automatique…")
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ScriptError("Chapitre introuvable (supprimé pendant le découpage ?)")
            pages = save_script(session, chapter, run.output, ctx.scenes)
            layout_pages(presets, pages)
            session.commit()
            n_panels = sum(len(p.panels) for p in pages)
        tries = f" en {run.attempts} essais" if run.attempts > 1 else ""
        if run.warnings:
            n = len(run.warnings)
            tries += f", avec {n} avertissement{'s' if n > 1 else ''} de dialogues"
        return f"{len(pages)} pages, {n_panels} cases{tries}"

    return run


def _excerpt(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def written_text(frames: Sequence[SceneFrame], summaries: Mapping[int, str], current: int) -> str:
    """Résumé de ce qui est déjà écrit, pour la scène `current` (numéro) : une ligne par scène écrite."""
    lines = []
    for f in frames:
        if f.number == current or f.id not in summaries:
            continue
        when = "avant" if f.number < current else "après"
        title = f" « {f.title} »" if f.title else ""
        lines.append(f"- scène {f.number}{title} ({f.type_name}, {when} cette scène) : {summaries[f.id]}")
    return "\n".join(lines)


def _written_from_pages(chapter: Chapter, frames: Sequence[SceneFrame], scene_id: int) -> str:
    """Ce que contiennent les autres scènes déjà écrites (réécriture d'une seule scène) : leur résumé validé et le
    début de leurs cases, page par page."""
    current = frame_of(frames, scene_id)
    summaries: dict[int, str] = {}
    for f in frames:
        pages = sorted((p for p in chapter.pages if p.scene_id == f.id and p.panels), key=lambda p: p.number)
        if f.id == scene_id or not pages:
            continue
        cases = " / ".join(_excerpt(p.panels[0].description, 90) for p in pages)
        summaries[f.id] = f"{f.summary} Écrite : {_excerpt(cases, 500)}"
    return written_text(frames, summaries, current.number if current else 0)


def _run_scenes(
    db: Database,
    presets: PresetRegistry,
    llm: LLMProvider,
    chapter_id: int,
    prompt: PromptPreset,
    templates: PromptPreset,
    ctx: ScriptContext,
    frames: Sequence[SceneFrame],
    fiches: Mapping[int, str],
    others: str,
    scene_id: int | None,
    progress: Progress,
) -> str:
    """Name scène par scène : une génération par scène, dans l'ordre (ou la seule scène `scene_id`), chacune avec la
    liste validée, le résumé des scènes déjà écrites et sa charte (ADN de la série précisé par son profil)."""
    rules = prompt.dialogue_rules
    todo = [f for f in frames if scene_id is None or f.id == scene_id]
    summaries: dict[int, str] = {}
    runs: list[tuple[SceneFrame, ScriptRun]] = []
    span = 75 / len(todo)

    for k, frame in enumerate(todo):
        low = 10 + k * span

        def step(pct: int, message: str, low: float = low, frame: SceneFrame = frame) -> None:
            progress(
                int(low + span * min(max(pct - 10, 0), 75) / 75), f"Scène {frame.number}/{len(frames)} — {message}"
            )

        def room(output: ScriptOutput, frame: SceneFrame = frame) -> list[str]:
            """Place réelle : la scène enregistrée et mise en page à blanc (annulé), bulles lettrées."""
            if rules is None or not rules.check_room:
                return []
            with db.session_scope() as session:
                chapter = session.get(Chapter, chapter_id)
                if chapter is None:
                    return []
                try:
                    pages = save_scene(session, chapter, frame, output)
                    layout_pages(presets, pages)
                    return room_problems(presets, pages)
                except LayoutError:
                    return []
                finally:
                    session.rollback()

        written = others if scene_id is not None else written_text(frames, summaries, frame.number)
        sctx = replace(ctx, charter=frame.charter, focus=frame, written=written, fiches=fiches.get(frame.id, ""))
        # Pas de session ouverte pendant l'appel au LLM.
        run = run_script(llm, prompt, sctx, step, room, templates=templates)
        summaries[frame.id] = run.output.summary
        runs.append((frame, run))

    warnings = [f"scène {f.number} : {w}" for f, r in runs for w in r.warnings]
    progress(88, "Enregistrement des pages, cases et bulles, puis mise en page automatique…")
    with db.session_scope() as session:
        chapter = session.get(Chapter, chapter_id)
        if chapter is None:
            raise ScriptError("Chapitre introuvable (supprimé pendant le découpage ?)")
        if scene_id is not None:
            frame, r = runs[0]
            pages = save_scene(session, chapter, frame, r.output)
        else:
            merged = ScriptOutput.model_construct(
                pages=[p for _f, r in runs for p in r.output.pages],
                summary=_excerpt(" ".join(r.output.summary for _f, r in runs), 4000),
            )
            ids = [f.id for f, r in runs for _p in r.output.pages]
            pages = save_script(session, chapter, merged, ctx.scenes, scene_ids=ids)
            # Pensée, voix off ou narration : comptée sur le chapitre entier (avertissement seulement).
            if rules is not None and rules.require_inner_voice:
                inner = check_dialogues(script_panels(merged), rules.model_copy(update={"max_mean_words": 100.0}))
                warnings += [w for w in inner if w.startswith("aucune pensée")]
        layout_pages(presets, pages)
        session.commit()
        n_panels = sum(len(p.panels) for p in pages)
    attempts = max(r.attempts for _f, r in runs)
    where = f"scène {runs[0][0].number} réécrite : " if scene_id is not None else ""
    scenes = "" if scene_id is not None else f", scène par scène ({len(runs)} scène{'s' if len(runs) > 1 else ''})"
    tries = f" en {attempts} essais" if attempts > 1 else ""
    if warnings:
        n = len(warnings)
        tries += f", avec {n} avertissement{'s' if n > 1 else ''} (profil des scènes, dialogues, une action par case)"
    return f"{where}{len(pages)} pages, {n_panels} cases{scenes}{tries}"
