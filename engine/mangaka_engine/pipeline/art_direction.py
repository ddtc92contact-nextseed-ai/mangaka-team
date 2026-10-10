"""Direction artistique — entre le scénario (étape 1) et la mise en page (étape 2).

Pour chaque page d'un chapitre (ou une seule page : « Proposer autre chose »), le LLM choisit parmi
des options structurées — jamais de géométrie :

- page : rythme (calme / montée / climax / respiration), style de mise en page suggéré, gabarit
  suggéré, « page choc » (pleine page ou splash) et une justification en français ;
- case : intensité, type de plan, angle de caméra, cadre, note d'ambiance, onomatopées ; et, s'il le
  juge utile, le décor et les objets de la bibliothèque de la série (ids existants seulement).

Entrées : scénario validé, bible et personnages de la série, style de mise en page de la série, choix
de direction artistique du chapitre précédent (pour éviter les répétitions), savoir-faire de l'agent.
Sortie JSON validée par Pydantic puis contre le chapitre (pages, nombre de cases, gabarits, ids de
la bibliothèque) ;
invalide → nouvel essai avec l'erreur (`max_retries`, 2 au maximum) → sinon `ArtDirectionError`.

Les choix sont stockés par page (`PageDirection`). Un champ modifié par l'auteur est verrouillé : une
nouvelle proposition le garde tant qu'il n'est pas déverrouillé. « Appliquer » recopie les choix dans
ce que lit la grammaire de mise en page (rythme et style de la page, intensité des cases, gabarit
suggéré et page choc) et dans le prompt image (plan, angle, ambiance), puis ne recalcule que les
pages dont la mise en page change. Le cadre devient une option de cadre de la case (`Panel.frame` :
sans bord, fond perdu, incrustation) et les onomatopées des bulles `sfx` du lettrage — sans toucher
à une option ou une onomatopée réglée par l'auteur. Un décor ou des objets proposés remplacent ceux
de la case seulement s'ils ont changé depuis la dernière application (une correction de l'auteur
dans l'écran Scénario reste).
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry, PromptPreset
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.db import Database
from ..store.models import Bubble, BubbleKind, Chapter, Character, LLMRun, Page, PageDirection, PageKind, Panel, utcnow
from ..validation import format_errors
from .knowledge import AgentKnowledge, KnowledgeBase
from .layout import LayoutError
from .library import SeriesLibrary
from .pages import applied_values, is_stale, layout_page
from .script import DIRECTION_LABELS, _render
from .style import NO_GUIDELINES, style_brief, style_names

AGENT = "art_direction"  # rôle de l'agent dans presets/knowledge.yaml
STEP = "art_direction"  # étape des jobs
PROMPT_ID = "direction-artistique"  # presets/prompts/direction-artistique.yaml

RYTHMES = ("calme", "montée", "climax", "respiration")
INTENSITIES = ("calme", "normal", "choc")
PLANS = ("plan large", "plan moyen", "plan rapproché", "gros plan", "insert", "plongée", "contre-plongée")
ANGLES = (
    "de face",
    "de trois quarts",
    "de profil",
    "de dos",
    "en plongée",
    "en contre-plongée",
    "vue subjective",
    "cadre penché",
)
CADRES = ("normal", "sans bord", "fond perdu", "incrustation")
PAGE_CHOCS = ("pleine page", "splash")
SFX_INTENSITIES = ("léger", "moyen", "fort")
VARIETIES = ("sobre", "equilibree", "audacieuse")
VARIETY_LABELS = {
    "sobre": "sobre — lisibilité d'abord : plans classiques, peu de pages choc, variations douces",
    "equilibree": "équilibrée — quelques temps forts marqués, le reste lisible et varié",
    "audacieuse": "audacieuse — cadrages marqués et inattendus, pages choc aux temps forts, contrastes forts",
}
# Rythme de direction artistique → indice de rythme de la grammaire de mise en page (layout_style.py).
RYTHME_TO_LAYOUT = {"calme": "lent", "respiration": "lent", "montée": "normal", "climax": "rapide"}

RythmeName = Literal["calme", "montée", "climax", "respiration"]
IntensityName = Literal["calme", "normal", "choc"]
PlanName = Literal["plan large", "plan moyen", "plan rapproché", "gros plan", "insert", "plongée", "contre-plongée"]
AngleName = Literal[
    "de face",
    "de trois quarts",
    "de profil",
    "de dos",
    "en plongée",
    "en contre-plongée",
    "vue subjective",
    "cadre penché",
]
CadreName = Literal["normal", "sans bord", "fond perdu", "incrustation"]
PageChocName = Literal["pleine page", "splash"]
SfxIntensityName = Literal["léger", "moyen", "fort"]

PAGE_FIELDS = ("rythme", "layout_style", "template", "page_choc")
PANEL_FIELDS = ("intensity", "plan", "angle", "cadre", "ambiance", "sfx")
MAX_SFX = 4


def _norm(value: Any) -> Any:
    """« Gros Plan », « montee », « contre plongée » → la valeur attendue ; vide ou « aucun » = null."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    v = " ".join(value.strip().lower().replace("’", "'").replace("_", " ").split())
    if v in ("", "aucun", "aucune", "none", "null", "non"):
        return None
    v = v.replace("contre plongée", "contre-plongée").replace("contre plongee", "contre-plongée")
    return {
        "montee": "montée",
        "trois-quarts": "de trois quarts",
        "trois quarts": "de trois quarts",
        "leger": "léger",
        "plongee": "plongée",
    }.get(v, v)


class _LLMModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DirectionSfx(_LLMModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    intensity: SfxIntensityName = "moyen"

    _i = field_validator("intensity", mode="before")(_norm)


class DirectionPanel(_LLMModel):
    panel: int = Field(ge=1, le=20, description="Numéro de la case dans la page (1 = première)")
    intensity: IntensityName
    plan: PlanName
    angle: AngleName = "de face"
    cadre: CadreName = "normal"
    ambiance: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    sfx: list[DirectionSfx] = Field(default_factory=list, max_length=MAX_SFX)
    # Bibliothèque (facultatif) : null ou absent = garder le décor / les objets du scénario.
    decor: int | None = None
    objets: list[int] | None = Field(default=None, max_length=8)

    _n = field_validator("intensity", "plan", "angle", "cadre", mode="before")(_norm)

    @field_validator("objets")
    @classmethod
    def _unique_objects(cls, v: list[int] | None) -> list[int] | None:
        return None if v is None else list(dict.fromkeys(v))

    @field_validator("ambiance", mode="before")
    @classmethod
    def _none_text(cls, v: Any) -> Any:
        return "" if v is None else v

    @field_validator("sfx", mode="before")
    @classmethod
    def _none_list(cls, v: Any) -> Any:
        return [] if v is None else v


class DirectionPage(_LLMModel):
    page: int = Field(ge=1, le=200)
    rythme: RythmeName
    layout_style: str | None = None
    template: str | None = None
    page_choc: PageChocName | None = None
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
    panels: list[DirectionPanel] = Field(min_length=1, max_length=20)

    _n = field_validator("rythme", "page_choc", "layout_style", "template", mode="before")(_norm)


class DirectionOutput(_LLMModel):
    pages: list[DirectionPage] = Field(min_length=1, max_length=200)


ERROR_LABELS = {"pages": "page", "panels": "case", "sfx": "onomatopée", "objets": "objet"}


class ArtDirectionError(Exception):
    """Échec de la direction artistique, message lisible par l'utilisateur."""


class DirectionValidationError(ValueError):
    pass


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


# --- contexte -------------------------------------------------------------------
@dataclass
class PageBrief:
    """Ce que l'agent sait d'une page à diriger (scénario validé)."""

    page_id: int
    number: int
    rythme: str | None  # indice de rythme du scénario (lent / normal / rapide)
    panels: list[dict[str, Any]]  # panel_id, description, personnages, plan, importance, intensité, dialogues
    templates: list[str]  # gabarits possibles (même nombre de cases)
    current: dict[str, Any] | None = None  # proposition actuelle (« Proposer autre chose »)
    locks: list[str] = field(default_factory=list)


@dataclass
class DirectionContext:
    series: dict[str, Any]
    characters: list[dict[str, str]]
    chapter: dict[str, Any]
    pages: list[PageBrief]
    styles: list[dict[str, str]]
    previous: dict[str, Any] | None  # choix du chapitre précédent
    variety: str
    variant: int = 0
    single_page: bool = False
    knowledge: AgentKnowledge | None = None
    library: SeriesLibrary = field(default_factory=SeriesLibrary)

    def as_json(self) -> dict[str, Any]:
        return {
            "task": "art_direction",
            "series": self.series,
            **self.library.as_json(),
            "chapter": self.chapter,
            "variety": self.variety,
            "variant": self.variant,
            "styles": [s["id"] for s in self.styles],
            "previous_direction": self.previous,
            "pages": [
                {
                    "page": p.number,
                    "rythme": p.rythme,
                    "templates": p.templates,
                    "panels": [
                        {
                            "panel": i + 1,
                            "description": pa["description"],
                            "characters": pa["characters"],
                            "decor": pa.get("decor"),
                            "objets": pa.get("objets") or [],
                            "shot_type": pa["shot_type"],
                            "importance": pa["importance"],
                            "intensity": pa["intensity"],
                            "dialogue_chars": pa["dialogue_chars"],
                        }
                        for i, pa in enumerate(p.panels)
                    ],
                    **({"current": p.current} if p.current else {}),
                }
                for p in self.pages
            ],
            "rythmes": list(RYTHMES),
            "intensities": list(INTENSITIES),
            "plans": list(PLANS),
            "angles": list(ANGLES),
            "cadres": list(CADRES),
            "page_chocs": list(PAGE_CHOCS),
            "sfx_intensities": list(SFX_INTENSITIES),
        }


def knowledge_query(presets: PresetRegistry, chapter: Chapter) -> str:
    style = style_names(presets, chapter.project)
    return "\n".join(p for p in ("mise en scène, cadrage, rythme", chapter.title, chapter.synopsis, style) if p)


def story_pages(chapter: Chapter) -> list[Page]:
    return [p for p in chapter.pages if p.kind == PageKind.story and p.panels]


def _panel_brief(panel: Panel) -> dict[str, Any]:
    return {
        "panel_id": panel.id,
        "description": panel.description,
        "characters": list(panel.character_names or []),
        "decor": panel.decor_id,
        "objets": list(panel.object_ids or []),
        "shot_type": panel.shot_type,
        "importance": panel.importance,
        "intensity": panel.intensity,
        "dialogue_chars": sum(len(b.text) for b in panel.bubbles),
        "dialogues": [f"{b.speaker_name or 'récitatif'} : {b.text}" for b in panel.bubbles][:6],
    }


def previous_direction(session: Session, chapter: Chapter) -> dict[str, Any] | None:
    """Choix de direction artistique du chapitre précédent de la même série (et d'elle seule)."""
    prev = session.scalars(
        select(Chapter)
        .where(Chapter.project_id == chapter.project_id, Chapter.number < chapter.number)
        .order_by(Chapter.number.desc())
        .limit(1)
    ).first()
    if prev is None:
        return None
    rows = session.scalars(
        select(PageDirection)
        .join(Page, Page.id == PageDirection.page_id)
        .where(PageDirection.chapter_id == prev.id, PageDirection.project_id == chapter.project_id)
        .order_by(Page.number)
    ).all()
    if not rows:
        return None
    pages = []
    plans: Counter[str] = Counter()
    angles: Counter[str] = Counter()
    for d in rows:
        v = d.values or {}
        pages.append(
            {
                "page": d.page.number,
                "rythme": v.get("rythme"),
                "page_choc": v.get("page_choc"),
                "template": v.get("template"),
            }
        )
        for pa in v.get("panels") or []:
            if pa.get("plan"):
                plans[pa["plan"]] += 1
            if pa.get("angle"):
                angles[pa["angle"]] += 1
    return {
        "chapter": prev.number,
        "pages": pages,
        "plans": dict(plans.most_common()),
        "angles": dict(angles.most_common()),
    }


def build_context(
    session: Session,
    presets: PresetRegistry,
    chapter: Chapter,
    prompt: PromptPreset,
    *,
    pages: Sequence[Page] | None = None,
    knowledge: KnowledgeBase | None = None,
) -> DirectionContext:
    series = chapter.project
    characters = session.scalars(
        select(Character).where(Character.project_id == series.id).order_by(Character.name)
    ).all()
    targets = list(pages) if pages is not None else story_pages(chapter)
    single = pages is not None and len(targets) == 1
    templates = list(presets.layout_templates.values())
    briefs = []
    variant = 0
    for page in targets:
        d = page.direction
        if single and d is not None:
            variant = d.variant + 1
        briefs.append(
            PageBrief(
                page_id=page.id,
                number=page.number,
                rythme=page.rythme,
                panels=[_panel_brief(p) for p in page.panels],
                templates=[t.id for t in templates if t.panel_count == len(page.panels)],
                current=public_values(d.values, page) if single and d is not None and d.values else None,
                locks=list(d.locks or []) if d is not None else [],
            )
        )
    style = presets.layout_styles.get(series.layout_style)
    brief = style_brief(presets, series)
    return DirectionContext(
        series={
            "title": series.title,
            "style": brief.packs,
            "style_guidelines": brief.guidelines,
            "reading_direction": series.reading_direction.value,
            "layout_style": series.layout_style,
            "layout_style_name": style.name if style else series.layout_style,
            "layout_style_description": style.description if style else "",
        },
        characters=[{"name": c.name, "description": c.visual_description} for c in characters],
        chapter={
            "number": chapter.number,
            "title": chapter.title,
            "synopsis": chapter.synopsis,
            "summary": chapter.summary,
        },
        pages=briefs,
        styles=[{"id": s.id, "name": s.name, "description": s.description} for s in presets.layout_styles.values()],
        previous=previous_direction(session, chapter),
        variety=prompt.variety or "equilibree",
        variant=variant,
        single_page=single,
        knowledge=knowledge.for_agent(session, AGENT, series.id, knowledge_query(presets, chapter))
        if knowledge
        else None,
        library=SeriesLibrary.load(session, series.id),
    )


def _pages_text(ctx: DirectionContext) -> str:
    names = {e["id"]: e["name"] for e in (*ctx.library.decors, *ctx.library.objets)}
    blocks = []
    for p in ctx.pages:
        lines = [f"Page {p.number} ({len(p.panels)} case{'s' if len(p.panels) > 1 else ''})"]
        if p.rythme:
            lines[0] += f", rythme du scénario : {p.rythme}"
        lines.append(f"  gabarits possibles : {', '.join(p.templates) or '(aucun : grille automatique)'}")
        for i, pa in enumerate(p.panels, start=1):
            who = f" — personnages : {', '.join(pa['characters'])}" if pa["characters"] else ""
            if pa.get("decor") in names:
                who += f" — décor : {names[pa['decor']]} (id {pa['decor']})"
            things = [f"{names[i]} (id {i})" for i in pa.get("objets") or [] if i in names]
            if things:
                who += f" — objets : {', '.join(things)}"
            hint = f" — plan du scénario : {pa['shot_type']}" if pa["shot_type"] else ""
            lines.append(f"  Case {i} (importance {pa['importance']}){hint}{who} : {pa['description']}")
            for d in pa["dialogues"]:
                lines.append(f"    « {d} »")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _previous_text(prev: dict[str, Any] | None) -> str:
    if not prev:
        return "(pas de direction artistique pour le chapitre précédent)"
    rythmes = Counter(p["rythme"] for p in prev["pages"] if p.get("rythme"))
    chocs = [f"page {p['page']} ({p['page_choc']})" for p in prev["pages"] if p.get("page_choc")]
    parts = [f"Chapitre {prev['chapter']}, {len(prev['pages'])} pages"]
    if rythmes:
        parts.append("rythmes : " + ", ".join(f"{k} ×{v}" for k, v in rythmes.most_common()))
    parts.append("pages choc : " + (", ".join(chocs) if chocs else "aucune"))
    if prev["plans"]:
        parts.append("plans : " + ", ".join(f"{k} ×{v}" for k, v in list(prev["plans"].items())[:5]))
    if prev["angles"]:
        parts.append("angles : " + ", ".join(f"{k} ×{v}" for k, v in list(prev["angles"].items())[:5]))
    return " ; ".join(parts) + "."


def _lock_label(key: str, panels: list[dict[str, Any]]) -> str:
    if "." not in key:
        return key
    pid, name = key.split(".", 1)
    index = next((i for i, pa in enumerate(panels, start=1) if str(pa["panel_id"]) == pid), None)
    return f"case {index} › {name}" if index else name


def _request_text(ctx: DirectionContext) -> str:
    if not ctx.single_page:
        return f"Propose la direction artistique de chacune des {len(ctx.pages)} pages ci-dessous."
    p = ctx.pages[0]
    out = f"Propose une AUTRE direction artistique pour la page {p.number}, nettement différente de la proposition actuelle"
    if p.current:
        out += " :\n" + json.dumps(p.current, ensure_ascii=False)
    if p.locks:
        out += "\nGarde tels quels les choix de l'auteur : " + ", ".join(_lock_label(k, p.panels) for k in p.locks)
    return out


def render_messages(prompt: PromptPreset, ctx: DirectionContext) -> list[ChatMessage]:
    chars = "\n".join(f"- {c['name']} : {c['description'] or '(sans description)'}" for c in ctx.characters)
    styles = "\n".join(f"- {s['id']} ({s['name']}) : {s['description']}" for s in ctx.styles)
    s = ctx.series
    values = {
        "series_title": s["title"],
        # Packs de style de la série (genre, rendu, ton, réglages) et consignes du genre et du ton.
        "style_packs": s["style"] or "(non précisé)",
        "style_guidelines": s.get("style_guidelines") or NO_GUIDELINES,
        "series_style": s["style"] or "(non précisé)",  # ancien nom de $style_packs
        "reading_direction": DIRECTION_LABELS.get(s["reading_direction"], s["reading_direction"]),
        "layout_style": f"{s['layout_style_name']} ({s['layout_style']})"
        + (f" : {s['layout_style_description']}" if s["layout_style_description"] else ""),
        "layout_styles": styles or "(aucun)",
        "characters": chars or "(aucun personnage enregistré)",
        "decors": ctx.library.text("decors") or "(aucun décor enregistré)",
        "objets": ctx.library.text("objets") or "(aucun objet enregistré)",
        "chapter_number": str(ctx.chapter["number"]),
        "chapter_title": ctx.chapter["title"] or "sans titre",
        "synopsis": ctx.chapter["synopsis"] or "(pas de synopsis)",
        "summary": ctx.chapter["summary"] or "(pas encore de résumé)",
        "pages": _pages_text(ctx),
        "previous_direction": _previous_text(ctx.previous),
        "variety": VARIETY_LABELS.get(ctx.variety, ctx.variety),
        "request": _request_text(ctx),
        "rythmes": ", ".join(RYTHMES),
        "intensities": ", ".join(INTENSITIES),
        "plans": ", ".join(PLANS),
        "angles": ", ".join(ANGLES),
        "cadres": ", ".join(CADRES),
        "page_chocs": ", ".join(PAGE_CHOCS),
        "sfx_intensities": ", ".join(SFX_INTENSITIES),
        "context_json": json.dumps(ctx.as_json(), ensure_ascii=False, indent=2),
        "savoir_faire": (ctx.knowledge.savoir_faire() if ctx.knowledge else "")
        or "(aucun savoir-faire pour cet agent)",
        "bible": (ctx.knowledge.bible_text() if ctx.knowledge else "") or "(pas encore de bible pour cette série)",
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- validation -------------------------------------------------------------------
def parse_direction(text: str, ctx: DirectionContext | None = None) -> DirectionOutput:
    """Valide la réponse brute du LLM (schéma, puis cohérence avec le chapitre si `ctx` est donné)."""
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DirectionValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise DirectionValidationError("la racine doit être un objet JSON avec « pages »")
    try:
        out = DirectionOutput.model_validate(data)
    except ValidationError as exc:
        raise DirectionValidationError(format_errors(exc, ERROR_LABELS)) from None
    if ctx is not None:
        problems = check_against(out, ctx)
        if problems:
            raise DirectionValidationError(" ; ".join(problems[:8]))
    return out


def check_against(out: DirectionOutput, ctx: DirectionContext) -> list[str]:
    """Pages, cases, styles et gabarits cohérents avec le chapitre (messages lisibles)."""
    problems: list[str] = []
    expected = {p.number: p for p in ctx.pages}
    styles = {s["id"] for s in ctx.styles}
    seen: set[int] = set()
    for dp in out.pages:
        brief = expected.get(dp.page)
        if brief is None:
            problems.append(f"page {dp.page} : n'existe pas (pages attendues : {', '.join(map(str, expected))})")
            continue
        if dp.page in seen:
            problems.append(f"page {dp.page} : en double")
        seen.add(dp.page)
        numbers = sorted(pa.panel for pa in dp.panels)
        if numbers != list(range(1, len(brief.panels) + 1)):
            problems.append(f"page {dp.page} : il faut exactement les cases 1 à {len(brief.panels)}, une fois chacune")
        if dp.layout_style is not None and dp.layout_style not in styles:
            problems.append(
                f"page {dp.page} › layout_style : « {dp.layout_style} » inconnu (choix : {', '.join(styles)}, ou null)"
            )
        if dp.template is not None and dp.template not in brief.templates:
            choices = ", ".join(brief.templates) or "aucun"
            problems.append(
                f"page {dp.page} › template : « {dp.template} » impossible ici (choix : {choices}, ou null)"
            )
        for pa in dp.panels:
            for problem in ctx.library.check_refs(pa.decor, pa.objets or []):
                problems.append(f"page {dp.page} › case {pa.panel} › {problem}")
    missing = [n for n in expected if n not in seen]
    if missing:
        problems.append(f"pages manquantes : {', '.join(map(str, missing))}")
    return problems


# --- appel du LLM avec relances -------------------------------------------------
Progress = Callable[[int, str], None]


@dataclass
class DirectionRun:
    output: DirectionOutput
    attempts: int
    messages: list[ChatMessage]


def run_direction(llm: LLMProvider, prompt: PromptPreset, ctx: DirectionContext, progress: Progress) -> DirectionRun:
    messages = render_messages(prompt, ctx)
    total = 1 + prompt.max_retries
    last_error = ""
    for attempt in range(1, total + 1):
        progress(10 + (attempt - 1) * 25, f"Direction artistique par le LLM (essai {attempt}/{total})…")
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise ArtDirectionError(f"Le LLM n'a pas pu répondre : {exc}") from exc
            last_error = str(exc)
            progress(10 + attempt * 25, f"Le LLM n'a pas répondu ({exc}), nouvel essai…")
            continue
        try:
            output = parse_direction(result.text, ctx)
        except DirectionValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                progress(10 + attempt * 25, f"Réponse invalide ({last_error[:160]}), nouvel essai…")
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return DirectionRun(output=output, attempts=attempt, messages=messages)
    raise ArtDirectionError(
        f"Le LLM a renvoyé une direction artistique invalide {total} fois de suite. Dernière erreur : {last_error}"
    )


# --- stockage, verrous ------------------------------------------------------------
def to_values(dp: DirectionPage, page: Page) -> dict[str, Any]:
    """Page de la réponse → valeurs stockées (cases repérées par leur id)."""
    by_number = {pa.panel: pa for pa in dp.panels}
    panels = []
    for i, panel in enumerate(page.panels, start=1):
        pa = by_number[i]
        panels.append(
            {
                "panel_id": panel.id,
                "intensity": pa.intensity,
                "plan": pa.plan,
                "angle": pa.angle,
                "cadre": pa.cadre,
                "ambiance": pa.ambiance,
                "sfx": [s.model_dump() for s in pa.sfx],
                **({"decor": pa.decor} if pa.decor is not None else {}),
                **({"objets": pa.objets} if pa.objets is not None else {}),
            }
        )
    return {
        "rythme": dp.rythme,
        "layout_style": dp.layout_style,
        "template": dp.template,
        "page_choc": dp.page_choc,
        "rationale": dp.rationale,
        "panels": panels,
    }


def public_values(values: dict[str, Any], page: Page) -> dict[str, Any]:
    """Valeurs avec les cases numérotées 1..n (ce que voit le LLM)."""
    index = {p.id: i for i, p in enumerate(page.panels, start=1)}
    out = {k: v for k, v in values.items() if k != "panels"}
    out["panels"] = [
        {"panel": index.get(pa.get("panel_id"), 0), **{k: v for k, v in pa.items() if k != "panel_id"}}
        for pa in values.get("panels") or []
    ]
    return out


def is_out_of_date(direction: PageDirection, page: Page) -> bool:
    """Les cases de la page ont changé depuis la proposition (scénario modifié) : à refaire."""
    ids = [pa.get("panel_id") for pa in (direction.values or {}).get("panels") or []]
    return ids != [p.id for p in page.panels]


def merge_locked(new: dict[str, Any], old: dict[str, Any] | None, locks: Sequence[str]) -> dict[str, Any]:
    """Nouvelle proposition où chaque champ verrouillé garde la valeur de l'auteur."""
    if not old or not locks:
        return new
    out = copy.deepcopy(new)
    old_panels = {pa.get("panel_id"): pa for pa in old.get("panels") or []}
    for key in locks:
        if "." in key:
            pid, name = key.split(".", 1)
            source = next((pa for i, pa in old_panels.items() if str(i) == pid), None)
            target = next((pa for pa in out["panels"] if str(pa.get("panel_id")) == pid), None)
            if source is not None and target is not None and name in source:
                target[name] = copy.deepcopy(source[name])
        elif key in old:
            out[key] = copy.deepcopy(old[key])
    return out


def save_direction(
    session: Session, chapter: Chapter, pages: Sequence[Page], output: DirectionOutput, *, single_page: bool
) -> list[int]:
    """Enregistre la proposition ; renvoie les numéros des pages modifiées.

    Une page acceptée par l'auteur n'est pas remplacée par une proposition de tout le chapitre (seul
    « Proposer autre chose » sur cette page la relance). Les champs verrouillés sont gardés.
    """
    by_number = {dp.page: dp for dp in output.pages}
    changed: list[int] = []
    for page in pages:
        dp = by_number.get(page.number)
        if dp is None:
            continue
        d = page.direction
        if d is None:
            d = PageDirection(chapter_id=chapter.id, project_id=chapter.project_id, values={}, locks=[])
            page.direction = d
        elif d.status == "accepted" and not single_page:
            continue
        # Cases supprimées depuis : leurs verrous disparaissent.
        ids = {str(p.id) for p in page.panels}
        d.locks = [k for k in d.locks or [] if "." not in k or k.split(".", 1)[0] in ids]
        d.values = merge_locked(to_values(dp, page), d.values, d.locks)
        if single_page:
            d.variant = (d.variant or 0) + 1
            d.status = "proposed"
        changed.append(page.number)
    session.flush()
    return changed


# --- modifications de l'auteur ------------------------------------------------------
class PageEdit(BaseModel):
    """Champs de page modifiés à la main (validés comme une réponse du LLM)."""

    model_config = ConfigDict(extra="forbid")

    rythme: RythmeName | None = None
    layout_style: str | None = None
    template: str | None = None
    page_choc: PageChocName | None = None

    _n = field_validator("rythme", "page_choc", "layout_style", "template", mode="before")(_norm)


class PanelEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_id: int
    intensity: IntensityName | None = None
    plan: PlanName | None = None
    angle: AngleName | None = None
    cadre: CadreName | None = None
    ambiance: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    sfx: list[DirectionSfx] | None = Field(default=None, max_length=MAX_SFX)

    _n = field_validator("intensity", "plan", "angle", "cadre", mode="before")(_norm)


def edit_direction(
    presets: PresetRegistry,
    page: Page,
    *,
    page_fields: PageEdit | None = None,
    panels: Sequence[PanelEdit] = (),
    unlock: Sequence[str] = (),
    lock: Sequence[str] = (),
) -> PageDirection:
    """Applique les modifications de l'auteur : chaque champ modifié est verrouillé."""
    d = page.direction
    if d is None or not d.values:
        raise ArtDirectionError(f"la page {page.number} n'a pas encore de direction artistique : lance l'agent d'abord")
    values = copy.deepcopy(d.values)
    locks = list(d.locks or [])

    def add_lock(key: str) -> None:
        if key not in locks:
            locks.append(key)

    if page_fields is not None:
        for name in page_fields.model_fields_set:
            value = getattr(page_fields, name)
            if name == "rythme" and value is None:
                raise ArtDirectionError("rythme : ne peut pas être vide")
            if name == "layout_style" and value is not None and value not in presets.layout_styles:
                raise ArtDirectionError(f"layout_style : style de mise en page inconnu « {value} »")
            if name == "template" and value is not None:
                tpl = presets.layout_templates.get(value)
                if tpl is None or tpl.panel_count != len(page.panels):
                    raise ArtDirectionError(
                        f"template : gabarit « {value} » impossible pour une page de {len(page.panels)} case(s)"
                    )
            values[name] = value
            add_lock(name)
    by_id = {pa.get("panel_id"): pa for pa in values.get("panels") or []}
    for edit in panels:
        target = by_id.get(edit.panel_id)
        if target is None:
            raise ArtDirectionError(f"case {edit.panel_id} : n'appartient pas à la page {page.number}")
        for name in edit.model_fields_set - {"panel_id"}:
            value = getattr(edit, name)
            if value is None and name not in ("ambiance", "sfx"):
                raise ArtDirectionError(f"{name} : ne peut pas être vide")
            if name == "sfx":
                value = [s.model_dump() for s in value or []]
            elif name == "ambiance":
                value = value or ""
            target[name] = value
            add_lock(f"{edit.panel_id}.{name}")
    valid = set(PAGE_FIELDS) | {f"{pid}.{n}" for pid in by_id for n in PANEL_FIELDS}
    for key in lock:
        if key not in valid:
            raise ArtDirectionError(f"champ inconnu : « {key} »")
        add_lock(key)
    locks = [k for k in locks if k not in set(unlock)]
    d.values = values
    d.locks = locks
    return d


# --- application à la mise en page ---------------------------------------------------
def applied_panel_direction(panel: Panel) -> dict[str, Any]:
    """Direction artistique appliquée à une case (plan, angle, ambiance…), {} sinon."""
    applied = applied_values(panel.page)
    if not applied:
        return {}
    return next((pa for pa in applied.get("panels") or [] if pa.get("panel_id") == panel.id), {})


@dataclass
class ApplyResult:
    applied: list[int] = field(default_factory=list)  # pages dont la direction est appliquée
    relaid: list[int] = field(default_factory=list)  # pages dont la mise en page a été recalculée
    skipped: list[dict[str, Any]] = field(default_factory=list)  # {number, reason}


def apply_direction(
    presets: PresetRegistry, pages: Sequence[Page], library: SeriesLibrary | None = None
) -> ApplyResult:
    """Recopie la direction artistique dans les champs lus par la mise en page, puis recalcule
    uniquement les pages dont la mise en page change."""
    result = ApplyResult()
    for page in sorted(pages, key=lambda p: p.number):
        d = page.direction
        if d is None or not d.values:
            continue
        if is_out_of_date(d, page):
            result.skipped.append(
                {"number": page.number, "reason": "cases modifiées depuis la proposition : relance l'agent"}
            )
            continue
        v = d.values
        previous = d.applied or {}
        page.rythme = RYTHME_TO_LAYOUT.get(v.get("rythme") or "", page.rythme)
        style = v.get("layout_style")
        if style and style in presets.layout_styles:
            page.layout_style = style
        elif previous.get("layout_style") and page.layout_style == previous.get("layout_style"):
            page.layout_style = None  # le style imposé par l'application précédente est retiré
        intensities = {pa.get("panel_id"): pa.get("intensity") for pa in v.get("panels") or []}
        by_panel = {pa.get("panel_id"): pa for pa in v.get("panels") or []}
        before = {pa.get("panel_id"): pa for pa in previous.get("panels") or []}
        for panel in page.panels:
            if intensities.get(panel.id) in INTENSITIES:
                panel.intensity = intensities[panel.id]
            choice = by_panel.get(panel.id)
            if choice is not None:
                _apply_cadre(panel, choice.get("cadre"), (before.get(panel.id) or {}).get("cadre"))
                _apply_sfx(panel, choice.get("sfx") or [])
                if library is not None:
                    _apply_library(panel, choice, before.get(panel.id) or {}, library)
        d.applied = copy.deepcopy(v)
        d.applied_at = utcnow()
        result.applied.append(page.number)
        if page.layout is None or is_stale(page):
            try:
                layout_page(presets, page)
            except LayoutError as exc:
                result.skipped.append({"number": page.number, "reason": str(exc)})
                continue
            result.relaid.append(page.number)
    return result


# Cadre de direction artistique → option de cadre de la case (pipeline/layout.py).
CADRE_TO_FRAME: dict[str, dict[str, Any]] = {
    "normal": {},
    "sans bord": {"frame": "none"},
    "fond perdu": {"bleed": True},
    "incrustation": {"inset": True},
}
SFX_TO_INTENSITY = {"léger": "calme", "moyen": "normal", "fort": "choc"}
DA_SOURCE = "direction"  # marque des onomatopées posées par la direction artistique


def _apply_cadre(panel: Panel, cadre: str | None, before: str | None) -> None:
    """Options de cadre de la DA : remplace celles de l'application précédente, jamais celles de l'auteur."""
    current = dict(panel.frame or {})
    for key, value in CADRE_TO_FRAME.get(before or "normal", {}).items():
        if current.get(key) == value:
            current.pop(key)  # posée par la DA la dernière fois
    for key, value in CADRE_TO_FRAME.get(cadre or "normal", {}).items():
        current.setdefault(key, value)
    panel.frame = current or None


def _apply_library(panel: Panel, choice: dict[str, Any], before: dict[str, Any], library: SeriesLibrary) -> None:
    """Décor et objets proposés : appliqués s'ils existent encore et ont changé depuis l'application
    précédente (sinon l'auteur a pu les corriger dans l'écran Scénario : on garde sa version)."""
    decor = choice.get("decor")
    if decor is not None and decor != before.get("decor") and not library.check_refs(decor, []):
        panel.decor_id = decor
    objets = choice.get("objets")
    if objets is not None and objets != before.get("objets"):
        known = {e["id"] for e in library.objets}
        panel.object_ids = [i for i in objets if i in known]


def _apply_sfx(panel: Panel, sfx: Sequence[dict[str, Any]]) -> None:
    """Onomatopées de la DA : celles de l'application précédente (non retouchées) sont remplacées ;
    celles du scénario ou ajoutées à la main restent, et un texte déjà présent n'est pas doublé."""
    for b in list(panel.bubbles):
        params = b.sfx or {}
        if b.kind == BubbleKind.sfx and params.get("source") == DA_SOURCE and not (b.position or {}).get("manual"):
            panel.bubbles.remove(b)
    present = {b.text.casefold() for b in panel.bubbles if b.kind == BubbleKind.sfx}
    order = max((b.order for b in panel.bubbles), default=-1) + 1
    for item in sfx:
        text = str(item.get("text") or "").strip()
        if not text or text.casefold() in present:
            continue
        present.add(text.casefold())
        intensity = SFX_TO_INTENSITY.get(str(item.get("intensity") or "moyen"), "normal")
        panel.bubbles.append(
            Bubble(order=order, text=text, kind=BubbleKind.sfx, sfx={"intensity": intensity, "source": DA_SOURCE})
        )
        order += 1


# --- job ------------------------------------------------------------------------
def record_run(
    session: Session, chapter: Chapter, knowledge: AgentKnowledge, *, job_id: int | None, model: str | None
) -> LLMRun:
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


def direction_job(
    db: Database,
    presets: PresetRegistry,
    llm: LLMProvider,
    chapter_id: int,
    *,
    page_id: int | None = None,
    knowledge: KnowledgeBase | None = None,
    job_id: int | None = None,
) -> Callable[[Progress], str]:
    """Job « Direction artistique » d'un chapitre, ou d'une seule page (« Proposer autre chose »)."""

    def run(progress: Progress) -> str:
        prompt = presets.prompt(PROMPT_ID)
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ArtDirectionError("Chapitre introuvable (supprimé entre-temps ?)")
            targets = _targets(chapter, page_id)
            progress(5, "Préparation du contexte (scénario, bible, style de la série, chapitre précédent)…")
            ctx = build_context(
                session, presets, chapter, prompt, pages=targets if page_id else None, knowledge=knowledge
            )
            if ctx.knowledge is not None:
                record_run(session, chapter, ctx.knowledge, job_id=job_id, model=getattr(llm, "model", llm.name))
                session.commit()
        run = run_direction(llm, prompt, ctx, progress)
        progress(90, "Enregistrement des choix de direction artistique…")
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ArtDirectionError("Chapitre introuvable (supprimé entre-temps ?)")
            targets = _targets(chapter, page_id)
            changed = save_direction(session, chapter, targets, run.output, single_page=page_id is not None)
            session.commit()
        tries = f" en {run.attempts} essais" if run.attempts > 1 else ""
        if page_id is not None:
            return f"Nouvelle proposition pour la page {changed[0] if changed else '?'}{tries}"
        kept = len(ctx.pages) - len(changed)
        extra = (
            f" ({kept} page{'s' if kept > 1 else ''} acceptée{'s' if kept > 1 else ''} gardée{'s' if kept > 1 else ''})"
            if kept
            else ""
        )
        return f"{len(changed)} page{'s' if len(changed) > 1 else ''} dirigée{'s' if len(changed) > 1 else ''}{extra}{tries}"

    return run


def _targets(chapter: Chapter, page_id: int | None) -> list[Page]:
    pages = story_pages(chapter)
    if page_id is None:
        if not pages:
            raise ArtDirectionError("Aucune page à diriger : découpe d'abord le chapitre (onglet Scénario)")
        return pages
    page = next((p for p in pages if p.id == page_id), None)
    if page is None:
        raise ArtDirectionError("Page introuvable dans ce chapitre (ou page sans case)")
    return [page]
