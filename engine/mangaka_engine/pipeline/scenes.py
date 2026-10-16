"""Étape « Scènes » : la liste des scènes du chapitre, avant le scénario (méthode des mangakas : intrigue → scènes
avec leurs pages → name → relecture → dessin).

1. **types** : liste fermée de `presets/scene_types.yaml` (calme, dialogue, combat, poursuite, sport_collectif,
   revelation), chacun avec un profil de tempo écrit en curseurs de l'ADN (`pipeline/pre_direction.py` :
   `tempo_profile`, `apply_tempo`, `tempo_text`) ;
2. **agent « Découpage en scènes »** : à partir du synopsis, de la bible, des résumés des chapitres précédents et du
   savoir-faire du scénariste (kishōtenketsu, pic vers les 2/3, 3 premières pages fortes, tourne de page), il propose
   les scènes. Le nombre de pages du chapitre est fixe (`target_page_count`) : la somme des pages des scènes lui est
   égale ; ce qui ne rentre pas va dans `deferred` (« à reporter au chapitre suivant »), jamais tassé. Prompt rendu
   depuis `presets/prompts/scenes.yaml`, réponse JSON validée (`parse_scenes`), relance avec l'erreur (`max_retries`
   du preset, 2 au plus), puis `ScenesError` lisible ;
3. **validation par l'auteur** (le rôle de l'éditeur, écran Scènes) : `Chapter.scenes_validated_at` ; toute retouche
   de la liste la retire. L'étape `scenes` de la garde d'étapes (`pipeline/stage_gate.py`) l'exige avant le scénario ;
4. **scénariste** (`pipeline/script.py`) : il reçoit la liste validée en clair (`scenes_text` : scène, type, pages,
   profil), rattache chaque page à sa scène (`scene` de chaque page), et le nombre de pages de chaque scène est
   contrôlé (`scene_page_problems` : relance, puis avertissement ; `assign_scenes` rattache quand même chaque page).

Un chapitre sans scène mais déjà écrit (pages de l'histoire avec des cases) est en « ancien mode » : rien ne change
pour lui.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetError, PresetRegistry, PromptPreset
from ..presets.schemas import SCENE_TYPES, SceneTypesSettings
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.db import Database
from ..store.models import Chapter, ChapterScene, Character, PageKind, Project
from ..validation import format_errors
from .framing import plain
from .knowledge import AgentKnowledge, KnowledgeBase
from .library import SeriesLibrary
from .names import CharacterMatcher
from .pre_direction import scene_dna, series_charter, tempo_profile, tempo_text
from .scene_cast import cast_names, resolve_cast
from .style import NO_GUIDELINES, style_brief

AGENT = "script"  # savoir-faire du scénariste (presets/knowledge.yaml)
DIRECTION_LABELS = {"rtl": "de droite à gauche (manga)", "ltr": "de gauche à droite (BD, comics)"}


class ScenesError(Exception):
    """Échec du découpage en scènes, message lisible par l'utilisateur."""


class ScenesValidationError(ValueError):
    pass


# --- types de scène ---------------------------------------------------------------
def type_key(value: Any) -> Any:
    """« Révélation », « sport collectif », « Sport-Collectif » → identifiant du type (« revelation »,
    « sport_collectif ») ; une valeur hors liste reste telle quelle (refusée ensuite)."""
    if not isinstance(value, str):
        return value
    key = re.sub(r"[\s\-]+", "_", plain(value).strip())
    return key if key in SCENE_TYPES else value.strip()


def scene_types(presets: PresetRegistry) -> SceneTypesSettings:
    if presets.scene_types is None:
        raise ScenesError("presets/scene_types.yaml absent ou invalide : types de scène indisponibles")
    return presets.scene_types


def types_for(presets: PresetRegistry, project: Project) -> list[dict[str, Any]]:
    """Types de scène pour une série : nom, aide, profil de tempo (ajusté par la série) et le même en clair."""
    settings = presets.scene_types
    if settings is None:
        return []
    charter = series_charter(presets, project)
    out = []
    for type_id, scene_type in settings.types.items():
        profile = tempo_profile(settings, project, type_id)
        out.append(
            {
                "id": type_id,
                "name": scene_type.name,
                "description": scene_type.description,
                "profile": profile,
                "tempo": tempo_text(profile, scene_dna(charter, profile)),
            }
        )
    return out


# --- réponse du LLM ---------------------------------------------------------------
class _LLMModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SceneDraft(_LLMModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    type: str
    pages: int = Field(ge=1, le=60)
    lieu: int | None = None
    # Distribution : fiches des personnages qui jouent dans la scène (noms tels que dans la liste, ou ids).
    personnages: list[int | Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]] = Field(
        default_factory=list, max_length=30, validation_alias=AliasChoices("personnages", "characters", "cast")
    )

    _type = field_validator("type", mode="before")(type_key)

    @field_validator("personnages", mode="before")
    @classmethod
    def _personnages(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, str):
            return [n for n in re.split(r"[,;]", v) if n.strip()]
        return v

    @field_validator("lieu", mode="before")
    @classmethod
    def _lieu(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if v.isdigit():
                return int(v)
            return None  # un nom de lieu sans id : la scène reste sans lieu de la série
        return v


class ScenesOutput(_LLMModel):
    scenes: list[SceneDraft] = Field(min_length=1, max_length=60)
    deferred: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]] = Field(
        default_factory=list, max_length=20
    )

    @field_validator("deferred", mode="before")
    @classmethod
    def _deferred(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v

    @field_validator("deferred")
    @classmethod
    def _no_blank(cls, v: list[str]) -> list[str]:
        return [x for x in v if x]


ERROR_LABELS = {"scenes": "scène", "deferred": "report"}
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def scene_problems(scenes: Sequence[tuple[str, int]], target: int, settings: SceneTypesSettings) -> list[str]:
    """Problèmes d'une liste de scènes (type, pages) : type hors liste, pages hors bornes, somme ≠ cible."""
    problems = []
    if len(scenes) > settings.max_scenes:
        problems.append(f"{len(scenes)} scènes : {settings.max_scenes} au plus")
    for i, (type_id, pages) in enumerate(scenes, start=1):
        if type_id not in settings.types:
            problems.append(f"scène {i} : type « {type_id} » hors liste ({', '.join(settings.types)})")
        if pages > settings.max_pages_per_scene:
            problems.append(
                f"scène {i} : {pages} pages, {settings.max_pages_per_scene} au plus — découpe-la en deux scènes"
            )
    total = sum(p for _, p in scenes)
    if total != target:
        fix = (
            "reporte la suite au chapitre suivant (« deferred »), sans tasser"
            if total > target
            else "donne plus de pages aux scènes qui en ont besoin, ou ajoute une scène"
        )
        problems.append(f"la somme des pages des scènes vaut {total}, elle doit être égale à {target} : {fix}")
    return problems


def parse_scenes(
    text: str, *, target: int, settings: SceneTypesSettings, library: SeriesLibrary | None = None
) -> ScenesOutput:
    """Valide la réponse brute du LLM ; `ScenesValidationError` explique ce qui ne va pas."""
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScenesValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise ScenesValidationError("la racine doit être un objet JSON avec « scenes » et « deferred »")
    try:
        out = ScenesOutput.model_validate(data)
    except ValidationError as exc:
        raise ScenesValidationError(format_errors(exc, ERROR_LABELS)) from None
    problems = scene_problems([(s.type, s.pages) for s in out.scenes], target, settings)
    if library is not None:
        known = {e["id"] for e in library.lieux}
        problems += [
            f"scène {i} : lieu {s.lieu} inconnu (ids des lieux de la série : {', '.join(map(str, sorted(known))) or 'aucun'}, ou null)"
            for i, s in enumerate(out.scenes, start=1)
            if s.lieu is not None and s.lieu not in known
        ]
    if problems:
        raise ScenesValidationError(" ; ".join(problems[:10]))
    return out


# --- contexte -------------------------------------------------------------------
@dataclass
class ScenesContext:
    series: dict[str, Any]
    characters: list[dict[str, Any]]
    previous_chapters: list[dict[str, Any]]
    chapter: dict[str, Any]
    types: list[dict[str, Any]]
    max_pages_per_scene: int
    max_scenes: int
    knowledge: AgentKnowledge | None = None
    library: SeriesLibrary = field(default_factory=SeriesLibrary)

    def as_json(self) -> dict[str, Any]:
        return {
            "task": "scenes",
            "series": self.series,
            "characters": self.characters,
            "lieux": self.library.lieux,
            "previous_chapters": self.previous_chapters,
            "chapter": self.chapter,
            "scene_types": [{"id": t["id"], "name": t["name"], "tempo": t["tempo"]} for t in self.types],
            "max_pages_per_scene": self.max_pages_per_scene,
            "max_scenes": self.max_scenes,
        }


def build_context(
    session: Session,
    presets: PresetRegistry,
    chapter: Chapter,
    *,
    max_previous: int,
    knowledge: KnowledgeBase | None = None,
) -> ScenesContext:
    from .script import knowledge_query  # script importe ce module

    settings = scene_types(presets)
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
    return ScenesContext(
        series={
            "title": series.title,
            "style": brief.packs,
            "style_guidelines": brief.guidelines,
            "reading_direction": series.reading_direction.value,
        },
        characters=[
            {"id": c.id, "name": c.name, "aliases": list(c.aliases or []), "description": c.visual_description}
            for c in characters
        ],
        previous_chapters=[
            {
                "number": c.number,
                "title": c.title,
                "summary": c.summary or "(pas encore de résumé)",
                # Ce que le chapitre précédent a reporté : à reprendre ici en priorité.
                "deferred": list(c.scenes_deferred or []),
            }
            for c in reversed(previous)
        ],
        chapter={
            "number": chapter.number,
            "title": chapter.title,
            "synopsis": chapter.synopsis,
            "target_pages": chapter.target_page_count,
        },
        types=types_for(presets, series),
        max_pages_per_scene=settings.max_pages_per_scene,
        max_scenes=settings.max_scenes,
        knowledge=knowledge.for_agent(
            session, AGENT, series.id, knowledge_query(presets, chapter), genre=series.style_genre
        )
        if knowledge
        else None,
        library=SeriesLibrary.load(session, series.id),
    )


def _render(template: str, values: dict[str, str], part: str) -> str:
    try:
        return string.Template(template).substitute(values)
    except KeyError as exc:
        raise PresetError(f"presets/prompts/scenes.yaml : variable inconnue ${exc.args[0]} dans « {part} »") from None
    except ValueError as exc:
        raise PresetError(f"presets/prompts/scenes.yaml : gabarit « {part} » invalide ({exc})") from None


def _aliases(character: dict[str, Any]) -> str:
    aliases = [a for a in character.get("aliases") or [] if a]
    return f" (aussi appelé : {', '.join(aliases)})" if aliases else ""


def render_messages(prompt: PromptPreset, ctx: ScenesContext) -> list[ChatMessage]:
    chars = "\n".join(
        f"- {c['name']}{_aliases(c)} : {c['description'] or '(sans description)'}" for c in ctx.characters
    )
    prev = []
    for c in ctx.previous_chapters:
        line = f"- Chapitre {c['number']}{' — ' + c['title'] if c['title'] else ''} : {c['summary']}"
        if c.get("deferred"):
            line += " Reporté à la suite : " + " ; ".join(c["deferred"])
        prev.append(line)
    types = "\n".join(f"- {t['id']} ({t['name']}) : {t['description']} Tempo : {t['tempo']}." for t in ctx.types)
    values = {
        "series_title": ctx.series["title"],
        "style_packs": ctx.series["style"] or "(non précisé)",
        "style_guidelines": ctx.series.get("style_guidelines") or NO_GUIDELINES,
        "reading_direction": DIRECTION_LABELS.get(ctx.series["reading_direction"], ctx.series["reading_direction"]),
        "characters": chars or "(aucun personnage enregistré)",
        # Noms exacts des fiches, à recopier tels quels dans « personnages ».
        "character_names": ", ".join(f"« {c['name']} »" for c in ctx.characters) or "(aucune fiche personnage)",
        "lieux": ctx.library.text("lieux") or "(aucun lieu enregistré : « lieu » vaut null)",
        "previous_chapters": "\n".join(prev) or "(premier chapitre de la série)",
        "chapter_number": str(ctx.chapter["number"]),
        "chapter_title": ctx.chapter["title"] or "sans titre",
        "synopsis": ctx.chapter["synopsis"],
        "target_pages": str(ctx.chapter["target_pages"]),
        "scene_types": types,
        "type_ids": ", ".join(t["id"] for t in ctx.types),
        "max_pages_per_scene": str(ctx.max_pages_per_scene),
        "max_scenes": str(ctx.max_scenes),
        "context_json": json.dumps(ctx.as_json(), ensure_ascii=False, indent=2),
        "savoir_faire": (ctx.knowledge.savoir_faire() if ctx.knowledge else "")
        or "(aucun savoir-faire pour cet agent)",
        "bible": (ctx.knowledge.bible_text() if ctx.knowledge else "") or "(pas encore de bible pour cette série)",
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- appel du LLM avec relances ---------------------------------------------------
Progress = Callable[[int, str], None]


@dataclass
class ScenesRun:
    output: ScenesOutput
    attempts: int


def run_scenes(
    llm: LLMProvider, prompt: PromptPreset, ctx: ScenesContext, settings: SceneTypesSettings, progress: Progress
) -> ScenesRun:
    messages = render_messages(prompt, ctx)
    total = 1 + prompt.max_retries
    target = int(ctx.chapter["target_pages"])
    last_error = ""
    for attempt in range(1, total + 1):
        progress(10 + (attempt - 1) * 25, f"Découpage en scènes par le LLM (essai {attempt}/{total})…")
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise ScenesError(f"Le LLM n'a pas pu répondre : {exc}") from exc
            last_error = str(exc)
            continue
        try:
            output = parse_scenes(result.text, target=target, settings=settings, library=ctx.library)
        except ScenesValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                progress(10 + attempt * 25, f"Réponse invalide ({last_error[:160]}), nouvel essai…")
                retry = _render(prompt.retry, {"error": last_error, "target_pages": str(target)}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return ScenesRun(output=output, attempts=attempt)
    raise ScenesError(
        f"Le LLM a renvoyé une liste de scènes invalide {total} fois de suite. Dernière erreur : {last_error}"
    )


# --- enregistrement ---------------------------------------------------------------
@dataclass
class SceneData:
    title: str
    summary: str
    scene_type: str
    page_count: int
    location_id: int | None = None
    id: int | None = None
    # Distribution (ids des fiches) ; None : celle de la scène gardée telle quelle (vide pour une scène nouvelle).
    character_ids: list[int] | None = None


def replace_scenes(session: Session, chapter: Chapter, scenes: Sequence[SceneData], deferred: Sequence[str]) -> None:
    """Remplace la liste des scènes du chapitre (une scène gardée par son `id` garde ses pages ; une scène retirée
    les libère) et retire la validation de l'auteur."""
    kept = {s.id: s for s in chapter.scenes}
    wanted = {d.id for d in scenes if d.id is not None}
    with session.no_autoflush:
        for scene in list(chapter.scenes):
            if scene.id not in wanted:
                chapter.scenes.remove(scene)
                session.delete(scene)
    session.flush()
    for position, data in enumerate(scenes):
        scene = kept.get(data.id) if data.id is not None else None
        if scene is None:
            scene = ChapterScene(chapter_id=chapter.id)
            chapter.scenes.append(scene)
        scene.position = position
        scene.title = data.title
        scene.summary = data.summary
        scene.scene_type = data.scene_type
        scene.page_count = data.page_count
        scene.location_id = data.location_id
        if data.character_ids is not None:
            scene.character_ids = list(dict.fromkeys(data.character_ids))
        elif scene.character_ids is None:
            scene.character_ids = []
    chapter.scenes.sort(key=lambda s: s.position)
    chapter.scenes_deferred = [d for d in deferred if d.strip()]
    chapter.scenes_validated_at = None
    chapter.scenes_validated_by = ""
    session.flush()


def save_scenes(session: Session, chapter: Chapter, output: ScenesOutput) -> list[ChapterScene]:
    """Proposition de l'agent : remplace toute la liste (non validée). La distribution de chaque scène (noms ou ids)
    est rapprochée des fiches de la série (`pipeline/names.py`) ; un nom sans fiche est ignoré."""
    matcher = CharacterMatcher.for_project(session, chapter.project_id)
    replace_scenes(
        session,
        chapter,
        [
            SceneData(s.title, s.summary, s.type, s.pages, s.lieu, character_ids=resolve_cast(matcher, s.personnages))
            for s in output.scenes
        ],
        output.deferred,
    )
    return list(chapter.scenes)


def total_pages(chapter: Chapter) -> int:
    return sum(s.page_count for s in chapter.scenes)


def validation_problem(chapter: Chapter, settings: SceneTypesSettings | None) -> str | None:
    """Pourquoi la liste ne peut pas être validée (en français), ou None."""
    if not chapter.scenes:
        return "aucune scène : propose ou ajoute d'abord les scènes du chapitre"
    if settings is None:
        return "presets/scene_types.yaml absent ou invalide : types de scène indisponibles"
    problems = scene_problems(
        [(s.scene_type, s.page_count) for s in chapter.scenes], chapter.target_page_count, settings
    )
    return " ; ".join(problems) if problems else None


@dataclass(frozen=True)
class PeakWarning:
    scene_id: int
    message: str


def _pct(x: float) -> str:
    return f"{round(x * 100)} %"


def peak_warnings(presets: PresetRegistry, chapter: Chapter) -> list[PeakWarning]:
    """Pics du chapitre posés sur des scènes au profil calme (`calm` de presets/scene_types.yaml) : la courbe de rythme
    de l'ADN de la série place le premier pic dans une fenêtre du chapitre (`rhythm.first_peak`) et le pic final dans
    ses N dernières planches (`rhythm.final_peak_last_pages`). Quand toutes les scènes qui couvrent ces pages sont au
    profil calme, chacune reçoit un avertissement (jamais bloquant)."""
    settings = presets.scene_types
    charter = series_charter(presets, chapter.project)
    if settings is None or charter is None or not chapter.scenes:
        return []
    calm = {k for k, t in settings.types.items() if t.calm}
    names = {k: t.name for k, t in settings.types.items()}
    page_scene: list[ChapterScene] = [s for s in chapter.scenes for _ in range(max(0, s.page_count))]
    n = len(page_scene)
    if n == 0 or not calm:
        return []
    numbers = {s.id: i for i, s in enumerate(chapter.scenes, start=1)}

    def label(scene: ChapterScene) -> str:
        title = f" « {scene.title} »" if scene.title else ""
        return f"Scène {numbers[scene.id]}{title} ({names.get(scene.scene_type, scene.scene_type).lower()})"

    def span(pages: Sequence[int]) -> str:
        return f"page {pages[0]}" if len(pages) == 1 else f"pages {pages[0]} à {pages[-1]}"

    out: list[PeakWarning] = []
    rhythm = charter.dna.rhythm
    first = rhythm.first_peak
    window = [i for i in range(n) if i / n <= first.max + 1e-9 and (i + 1) / n >= first.min - 1e-9]
    covering = list(dict.fromkeys(page_scene[i] for i in window))
    if covering and all(s.scene_type in calm for s in covering):
        pages = [i + 1 for i in window]
        for scene in covering:
            out.append(
                PeakWarning(
                    scene.id,
                    f"{label(scene)} : le premier pic du chapitre tombe entre {_pct(first.min)} et {_pct(first.max)} "
                    f"({span(pages)}, courbe de rythme de l'ADN de la série), mais son type est au profil calme. "
                    "Donne-lui un type qui porte un pic (combat, poursuite, révélation…) ou déplace le moment fort.",
                )
            )
    last = rhythm.final_peak_last_pages
    if last:
        tail = list(range(max(0, n - last), n))
        covering = list(dict.fromkeys(page_scene[i] for i in tail))
        if covering and all(s.scene_type in calm for s in covering):
            pages = [i + 1 for i in tail]
            for scene in covering:
                out.append(
                    PeakWarning(
                        scene.id,
                        f"{label(scene)} : le pic final du chapitre tombe dans "
                        f"{'ses ' + str(last) + ' dernières planches' if last > 1 else 'sa dernière planche'} "
                        f"({span(pages)}, courbe de rythme "
                        "de l'ADN de la série), mais son type est au profil calme. Si la scène porte le moment fort "
                        "(coup final, révélation), donne-lui le type qui va avec.",
                    )
                )
    return out


def validate(chapter: Chapter, author: str = "") -> None:
    chapter.scenes_validated_at = datetime.now(UTC)
    chapter.scenes_validated_by = (author or "").strip()[:120]


def is_legacy(chapter: Chapter) -> bool:
    """« Ancien mode » : chapitre déjà écrit sans scènes (pages de l'histoire avec des cases, aucune scène)."""
    return not chapter.scenes and any(p.kind == PageKind.story and p.panels for p in chapter.pages)


def is_validated(chapter: Chapter) -> bool:
    return (
        bool(chapter.scenes)
        and chapter.scenes_validated_at is not None
        and total_pages(chapter) == (chapter.target_page_count)
    )


# --- scénariste ---------------------------------------------------------------------
def script_scenes(presets: PresetRegistry, chapter: Chapter) -> list[dict[str, Any]]:
    """Scènes validées, telles que les reçoit le scénariste (vide : chapitre sans scènes validées, ancien mode) :
    numéro, titre, résumé, type, pages (et leurs numéros), profil de tempo en clair, lieu."""
    if not is_validated(chapter):
        return []
    types = {t["id"]: t for t in types_for(presets, chapter.project)}
    characters = list(chapter.project.characters)
    places = {loc.id: loc.name for loc in chapter.project.locations}
    out = []
    first = 1
    for number, scene in enumerate(chapter.scenes, start=1):
        t = types.get(scene.scene_type, {})
        out.append(
            {
                "id": scene.id,
                "number": number,
                "title": scene.title,
                "summary": scene.summary,
                "type": scene.scene_type,
                "type_name": t.get("name", scene.scene_type),
                "pages": scene.page_count,
                "first_page": first,
                "last_page": first + scene.page_count - 1,
                "tempo": t.get("tempo", ""),
                "lieu": scene.location_id,
                "lieu_name": places.get(scene.location_id) if scene.location_id is not None else None,
                # Distribution validée (noms des fiches) : elle descend sur les cases (pipeline/scene_cast.py).
                "cast": cast_names(scene, characters),
            }
        )
        first += scene.page_count
    return out


NO_SCENES = "(pas de liste de scènes validée : découpe le chapitre librement, sans « scene » sur les pages)"


def scenes_text(scenes: Sequence[dict[str, Any]]) -> str:
    """Liste validée en clair pour le prompt du scénariste."""
    if not scenes:
        return NO_SCENES
    lines = []
    for s in scenes:
        span = f"page {s['first_page']}" if s["pages"] == 1 else f"pages {s['first_page']} à {s['last_page']}"
        title = f" « {s['title']} »" if s["title"] else ""
        line = (
            f"- scène {s['number']}{title} — {s['type_name']} ({s['type']}), {s['pages']} page"
            f"{'s' if s['pages'] > 1 else ''} ({span}) : {s['summary']}\n  Tempo : {s['tempo']}."
        )
        if s.get("cast"):
            line += f"\n  Distribution : {', '.join(s['cast'])}."
        if s.get("lieu_name"):
            line += f"\n  Lieu : {s['lieu_name']}."
        lines.append(line)
    return "\n".join(lines)


def scene_page_problems(declared: Sequence[int | None], scenes: Sequence[dict[str, Any]]) -> list[str]:
    """Pages rendues par le scénariste (scène déclarée de chaque page) contre la liste validée : chaque page porte sa
    scène, dans l'ordre, et chaque scène a exactement ses pages."""
    if not scenes:
        return []
    n = len(scenes)
    problems = []
    missing = [i for i, s in enumerate(declared, start=1) if s is None or not 1 <= s <= n]
    if missing:
        shown = ", ".join(map(str, missing[:8])) + ("…" if len(missing) > 8 else "")
        problems.append(f"page{'s' if len(missing) > 1 else ''} {shown} sans scène valable (« scene » : 1 à {n})")
    valid = [s for s in declared if s is not None and 1 <= s <= n]
    if any(b < a for a, b in zip(valid, valid[1:], strict=False)):
        problems.append("les pages doivent suivre l'ordre des scènes (scène 1, puis scène 2…)")
    for s in scenes:
        got = sum(1 for d in declared if d == s["number"])
        if got != s["pages"]:
            problems.append(
                f"scène {s['number']} ({s['type_name']}) : {got} page{'s' if got > 1 else ''} au lieu de {s['pages']}"
            )
    return problems


def assign_scenes(declared: Sequence[int | None], scenes: Sequence[dict[str, Any]]) -> list[int | None]:
    """Scène (id) de chaque page rendue : la scène déclarée quand les déclarations respectent la liste validée,
    sinon la place de la page dans la liste (pages 1 à 3 → scène 1…) ; au-delà, la dernière scène."""
    if not scenes:
        return [None] * len(declared)
    if not scene_page_problems(declared, scenes):
        return [scenes[d - 1]["id"] for d in declared]  # type: ignore[operator]
    out: list[int | None] = []
    for i in range(len(declared)):
        number = i + 1
        scene = next((s for s in scenes if s["first_page"] <= number <= s["last_page"]), scenes[-1])
        out.append(scene["id"])
    return out


# --- job ------------------------------------------------------------------------
def scenes_job(
    db: Database,
    presets: PresetRegistry,
    llm: LLMProvider,
    chapter_id: int,
    *,
    knowledge: KnowledgeBase | None = None,
    job_id: int | None = None,
) -> Callable[[Progress], str]:
    """Fonction exécutée par le `JobRunner` pour « Proposer les scènes »."""
    from .script import record_run  # script importe ce module

    def run(progress: Progress) -> str:
        prompt = presets.prompt("scenes")
        settings = scene_types(presets)
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ScenesError("Chapitre introuvable (supprimé pendant le découpage en scènes ?)")
            progress(5, "Préparation du contexte (synopsis, bible, chapitres précédents, savoir-faire)…")
            ctx = build_context(
                session, presets, chapter, max_previous=prompt.max_previous_chapters, knowledge=knowledge
            )
            if ctx.knowledge is not None:
                record_run(session, chapter, ctx.knowledge, job_id=job_id, model=getattr(llm, "model", llm.name))
                session.commit()
        # Pas de session ouverte pendant l'appel au LLM.
        result = run_scenes(llm, prompt, ctx, settings, progress)
        progress(90, "Enregistrement de la liste des scènes…")
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ScenesError("Chapitre introuvable (supprimé pendant le découpage en scènes ?)")
            scenes = save_scenes(session, chapter, result.output)
            session.commit()
            n, pages = len(scenes), sum(s.page_count for s in scenes)
        tries = f" en {result.attempts} essais" if result.attempts > 1 else ""
        later = f", {len(result.output.deferred)} moment(s) reporté(s)" if result.output.deferred else ""
        return f"{n} scène{'s' if n > 1 else ''}, {pages} pages{later}{tries}"

    return run
