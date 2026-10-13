"""Direction artistique — entre le scénario (étape 1) et la mise en page (étape 2).

Pour chaque page d'un chapitre (ou une seule page : « Proposer autre chose »), le LLM choisit parmi
des options structurées — jamais de géométrie :

- page : rythme (calme / montée / climax / respiration), style de mise en page suggéré, gabarit
  suggéré, « page choc » (pleine page ou splash) et une justification en français ;
- case : intensité, type de plan, angle de caméra, cadre, note d'ambiance, **action** (mouvement ou pose
  du corps, reprise par le rédacteur de prompt), onomatopées ; et, s'il le juge utile, le décor et les
  objets de la bibliothèque de la série (ids existants seulement).

Entrées : scénario validé, bible et personnages de la série, style de mise en page de la série, choix
de direction artistique du chapitre précédent (pour éviter les répétitions), savoir-faire de l'agent.
Sortie JSON validée par Pydantic puis contre le chapitre (pages, nombre de cases, gabarits, ids de
la bibliothèque) ;
invalide → nouvel essai avec l'erreur (`max_retries`, 2 au maximum) → sinon `ArtDirectionError`.

Savoir-faire : cherché page par page (`page_query` : le scénario de la page), dans le budget de l'agent,
sans doublon ; la trace du passage (« Sources utilisées ») note les pages de chaque fiche.

Mise en scène variée (`variety_rules` du preset, `check_variety`) : pas plus de N cases d'affilée au même
plan ou au même angle dans une page, une part plafonnée de cases « de face » et de plans larges ou moyens,
au moins une case hors hauteur d'œil et un plan serré par page, pas deux plans larges d'affilée, une
`action` de case qui décrit un mouvement du corps. Une règle enfreinte
relance l'agent avec l'erreur ; après les relances, la proposition est gardée avec un avertissement par
page (`warnings`), visible dans l'écran Direction artistique.

Spectateur (`pipeline/framing.py`) : quand le texte d'une case met un personnage en spectateur (« voit »,
« regarde », « aperçoit », « découvre », « assiste »…), l'agent choisit explicitement `point_de_vue` :
« plan de réaction » (le spectateur est dessiné) ou « vue subjective » (on voit ce qu'il voit, le spectateur
reste hors cadre). Un choix manquant relance l'agent ; après les relances, le choix par défaut
(`framing.default_viewpoint`) est noté comme tel. « Appliquer » range les spectateurs (présents ou hors
cadre) et note le choix sur la case (`Panel.viewpoint`), sans jamais écraser un choix de l'auteur.

Les choix sont stockés par page (`PageDirection`). Un champ modifié par l'auteur est verrouillé : une
nouvelle proposition le garde tant qu'il n'est pas déverrouillé. « Appliquer » recopie les choix dans
ce que lit la grammaire de mise en page (rythme et style de la page, intensité des cases, gabarit
suggéré et page choc) et dans le prompt image (plan, angle, ambiance), puis ne recalcule que les
pages dont la mise en page change. Le cadre devient une option de cadre de la case (`Panel.frame` :
sans bord, débordement sur les cases voisines — seulement sur une page choc ou une case choc —,
incrustation) et les onomatopées des bulles `sfx` du lettrage — sans toucher
à une option ou une onomatopée réglée par l'auteur. Un décor ou des objets proposés remplacent ceux
de la case seulement s'ils ont changé depuis la dernière application (une correction de l'auteur
dans l'écran Scénario reste).
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from ..presets import PresetRegistry, PromptPreset, VarietyRules
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.db import Database
from ..store.models import Bubble, BubbleKind, Chapter, Character, LLMRun, Page, PageDirection, PageKind, Panel, utcnow
from ..validation import format_errors
from .framing import (
    VIEWPOINT_LABELS,
    Aliases,
    aliases_from,
    apply_viewpoint,
    default_viewpoint,
    find_spectators,
    same_name,
    viewpoint_key,
    viewpoint_of,
)
from .knowledge import AgentKnowledge, KnowledgeBase
from .layout import LayoutError
from .library import SeriesLibrary
from .names import CharacterMatcher
from .pages import applied_values, is_stale, layout_page
from .script import DIRECTION_LABELS, _render
from .style import NO_GUIDELINES, style_brief

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
CADRES = ("normal", "sans bord", "débordement", "incrustation")
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
CadreName = Literal["normal", "sans bord", "débordement", "incrustation"]
PageChocName = Literal["pleine page", "splash"]
SfxIntensityName = Literal["léger", "moyen", "fort"]
POINTS_DE_VUE = ("plan de réaction", "vue subjective")
PointDeVueName = Literal["plan de réaction", "vue subjective"]

PAGE_FIELDS = ("rythme", "layout_style", "template", "page_choc")
PANEL_FIELDS = ("intensity", "plan", "angle", "cadre", "ambiance", "action", "sfx", "point_de_vue", "spectateurs")
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
        "debordement": "débordement",
        # Ancien cadre : une case ne franchit plus la marge extérieure, elle déborde sur ses voisines.
        "fond perdu": "débordement",
    }.get(v, v)


class _LLMModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DirectionSfx(_LLMModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    intensity: SfxIntensityName = "moyen"

    _i = field_validator("intensity", mode="before")(_norm)


def _point_de_vue(value: Any) -> Any:
    """« Vue Subjective », « réaction », « pov » → libellé attendu ; vide ou « aucun » = null."""
    v = _norm(value)
    key = viewpoint_key(v)
    return VIEWPOINT_LABELS[key] if key else v


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class DirectionPanel(_LLMModel):
    panel: int = Field(ge=1, le=20, description="Numéro de la case dans la page (1 = première)")
    intensity: IntensityName
    plan: PlanName
    angle: AngleName = "de face"
    cadre: CadreName = "normal"
    ambiance: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    # Mouvement ou pose du corps (français) : exigé par `variety_rules` (règle souple, voir `check_variety`).
    action: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    sfx: list[DirectionSfx] = Field(default_factory=list, max_length=MAX_SFX)
    # Bibliothèque (facultatif) : null ou absent = garder le décor / les objets du scénario.
    decor: int | None = None
    objets: list[int] | None = Field(default=None, max_length=8)
    # Spectateur (voir le module) : null = la case n'a pas de spectateur ; `spectateurs` : null = ceux repérés.
    point_de_vue: PointDeVueName | None = None
    spectateurs: list[Name] | None = Field(default=None, max_length=12)
    # Choix fait par défaut, l'agent n'ayant rien choisi (jamais lu dans une réponse du LLM).
    point_de_vue_defaut: bool = Field(default=False, exclude=True)

    _n = field_validator("intensity", "plan", "angle", "cadre", mode="before")(_norm)
    _pdv = field_validator("point_de_vue", mode="before")(_point_de_vue)

    @field_validator("point_de_vue_defaut", mode="before")
    @classmethod
    def _never_from_llm(cls, v: Any) -> bool:
        return False

    @field_validator("objets")
    @classmethod
    def _unique_objects(cls, v: list[int] | None) -> list[int] | None:
        return None if v is None else list(dict.fromkeys(v))

    @field_validator("ambiance", "action", mode="before")
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
    rules: VarietyRules | None = None  # `variety_rules` du preset

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
                            **({"offscreen": pa["offscreen"]} if pa.get("offscreen") else {}),
                            **({"spectators": pa["spectators"]} if pa.get("spectators") else {}),
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
            "points_de_vue": list(POINTS_DE_VUE),
            "variety_rules": self.rules.model_dump() if self.rules is not None else None,
        }


def page_query(brief: PageBrief) -> str:
    """Requête de savoir-faire d'une page : son scénario (descriptions, émotions, gestes, personnages,
    répliques), précédé d'indices de mise en scène (dialogue, temps fort) pour retrouver les bonnes fiches
    (champ / contrechamp d'une page de dialogue, impact et raccourci d'une page d'action)."""
    panels = brief.panels
    hints = ["mise en scène, cadrage"]
    if any(pa.get("dialogues") for pa in panels):
        hints.append("dialogue, champ contrechamp, réplique")
    if any(pa.get("intensity") == "choc" or (pa.get("importance") or 0) >= 3 for pa in panels):
        hints.append("temps fort, impact")
    lines = [", ".join(hints)]
    for pa in panels:
        parts = [pa.get("description") or "", pa.get("staging") or "", ", ".join(pa.get("characters") or [])]
        lines.append(" — ".join(p for p in parts if p))
        lines += [d.split(" : ", 1)[-1] for d in (pa.get("dialogues") or [])[:2]]
    return "\n".join(line for line in lines if line.strip())


def story_pages(chapter: Chapter) -> list[Page]:
    return [p for p in chapter.pages if p.kind == PageKind.story and p.panels]


def _panel_brief(panel: Panel, aliases: Aliases | None = None) -> dict[str, Any]:
    present = list(panel.character_names or [])
    offscreen = list(panel.offscreen_names or [])
    # Spectateurs repérés dans le texte, parmi les personnages présents et hors cadre (et ceux du choix
    # déjà appliqué : un spectateur rangé hors cadre reste un spectateur).
    vp = viewpoint_of(panel)
    spect = find_spectators(panel.description or "", [*present, *offscreen], aliases)
    viewers = spect.viewers or (list(vp.get("spectators") or []) if vp else [])
    return {
        "panel_id": panel.id,
        "description": panel.description,
        "staging": panel.staging or "",
        "characters": present,
        "offscreen": offscreen,
        "spectators": viewers,
        "seen": spect.seen,
        "perception": spect.verb,
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
    aliases = aliases_from(CharacterMatcher(characters))
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
                panels=[_panel_brief(p, aliases) for p in page.panels],
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
        # Savoir-faire cherché page par page (une page de dialogue n'appelle pas les fiches d'une page d'action).
        knowledge=knowledge.for_pages(session, AGENT, series.id, [(b.number, page_query(b)) for b in briefs])
        if knowledge
        else None,
        library=SeriesLibrary.load(session, series.id),
        rules=prompt.variety_rules,
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
            who = (
                f" — personnages à l'image : {', '.join(pa['characters'])}"
                if pa["characters"]
                else " — aucun personnage à l'image"
            )
            if pa.get("offscreen"):
                who += f" — hors cadre : {', '.join(pa['offscreen'])}"
            if pa.get("spectators"):
                verb = f" (« {pa['perception']} »)" if pa.get("perception") else ""
                who += (
                    f" — SPECTATEUR{'S' if len(pa['spectators']) > 1 else ''}{verb} : {', '.join(pa['spectators'])}"
                    " → choisis point_de_vue"
                )
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
        "points_de_vue": ", ".join(POINTS_DE_VUE),
        "variety_rules": variety_text(ctx.rules),
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


# --- spectateurs : plan de réaction ou vue subjective -------------------------------------
def _briefs_by_page(ctx: DirectionContext) -> dict[int, PageBrief]:
    return {p.number: p for p in ctx.pages}


def viewpoint_problems(out: DirectionOutput, ctx: DirectionContext) -> list[str]:
    """Cases dont le texte met un personnage en spectateur sans choix explicite (messages pour la relance),
    et spectateurs inconnus de la case."""
    problems: list[str] = []
    briefs = _briefs_by_page(ctx)
    for dp in out.pages:
        brief = briefs.get(dp.page)
        if brief is None:
            continue
        for pa in dp.panels:
            if not 1 <= pa.panel <= len(brief.panels):
                continue
            info = brief.panels[pa.panel - 1]
            viewers = info.get("spectators") or []
            if viewers and pa.point_de_vue is None:
                verb = f"« {info['perception']} »" if info.get("perception") else "le texte"
                problems.append(
                    f"page {dp.page} › case {pa.panel} › point_de_vue : {verb} met {', '.join(viewers)} en "
                    f"spectateur : choisis « plan de réaction » (le spectateur est dessiné) ou « vue subjective » "
                    "(on voit ce qu'il voit, le spectateur reste hors cadre)"
                )
            unknown = _unknown_spectators(info, pa)
            if pa.point_de_vue is not None and unknown:
                names = [*info.get("characters", []), *info.get("offscreen", [])]
                problems.append(
                    f"page {dp.page} › case {pa.panel} › spectateurs : {', '.join(unknown)} ne sont pas dans la case "
                    f"(personnages : {', '.join(names) or 'aucun'})"
                )
    return problems


def _unknown_spectators(info: dict[str, Any], pa: DirectionPanel) -> list[str]:
    names = [*info.get("characters", []), *info.get("offscreen", [])]
    return [s for s in pa.spectateurs or [] if not any(same_name(s, n) for n in names)]


def default_viewpoints(out: DirectionOutput, ctx: DirectionContext) -> None:
    """Complète les choix de spectateur : spectateurs absents ou inconnus de la case → ceux repérés dans le
    texte ; case à spectateur sans `point_de_vue` → le choix par défaut, noté `point_de_vue_defaut`."""
    briefs = _briefs_by_page(ctx)
    for dp in out.pages:
        brief = briefs.get(dp.page)
        if brief is None:
            continue
        for pa in dp.panels:
            if not 1 <= pa.panel <= len(brief.panels):
                continue
            info = brief.panels[pa.panel - 1]
            viewers = info.get("spectators") or []
            if pa.point_de_vue is not None:
                if pa.spectateurs is None or _unknown_spectators(info, pa):
                    pa.spectateurs = list(viewers)
                continue
            if not viewers:
                continue
            spect = find_spectators(info.get("description") or "", [*info["characters"], *info.get("offscreen", [])])
            spect.viewers = viewers
            pa.point_de_vue = VIEWPOINT_LABELS[default_viewpoint(spect, info["characters"])]
            pa.spectateurs = list(viewers)
            pa.point_de_vue_defaut = True


# --- mise en scène variée (variety_rules) -------------------------------------------------
CHAPTER_PREFIX = "chapitre : "  # avertissement qui porte sur toutes les pages dirigées ensemble


def _key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("’", "'").split())


def variety_text(rules: VarietyRules | None) -> str:
    """Règles de variété en clair, pour le prompt de l'agent ($variety_rules)."""
    if rules is None:
        return "(aucune règle imposée)"
    lines = [
        f"- jamais plus de {rules.max_same_plan_in_a_row} cases d'affilée au même plan dans une page ;",
        f"- jamais plus de {rules.max_same_angle_in_a_row} cases d'affilée au même angle dans une page ;",
        f"- au plus {round(rules.max_frontal_share * 100)} % des cases du chapitre avec l'angle "
        f"{' / '.join(rules.frontal_angles)} (vue de face, à hauteur d'œil) ;",
    ]
    if rules.min_off_eye_level_per_page:
        lines.append(
            f"- au moins {rules.min_off_eye_level_per_page} case par page (dès {rules.off_eye_level_min_panels} cases) "
            f"hors hauteur d'œil : plan ou angle parmi {', '.join(rules.off_eye_level)} ;"
        )
    if rules.max_wide_medium_share < 1:
        lines.append(
            f"- au plus {round(rules.max_wide_medium_share * 100)} % des cases du chapitre en "
            f"{' / '.join(rules.wide_medium_plans)} (personnages en pied) ;"
        )
    if rules.min_tight_per_page:
        lines.append(
            f"- au moins {rules.min_tight_per_page} plan serré par page (dès {rules.tight_min_panels} cases) : "
            f"{', '.join(rules.tight_plans)} — pour l'émotion, la révélation ou la réplique clé ;"
        )
    lines.append(
        f"- jamais plus de {rules.max_wide_in_a_row} case{'s' if rules.max_wide_in_a_row > 1 else ''} "
        f"d'affilée en {' / '.join(rules.wide_plans)} dans une page ;"
    )
    if rules.require_action:
        weak = f" (pas « {' », « '.join(rules.weak_actions[:4])} »)" if rules.weak_actions else ""
        lines.append(f"- chaque case a une « action » : un mouvement ou une pose du corps{weak}.")
    return "\n".join(lines)


def _wide_runs(plans: Sequence[str], wide: set[str], limit: int) -> list[tuple[int, int]]:
    """Suites de plus de `limit` plans larges d'affilée : (première case, dernière case), numérotées à 1."""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for i, plan in enumerate([*plans, ""]):
        if _key(plan) in wide:
            start = i if start is None else start
            continue
        if start is not None and i - start > limit:
            out.append((start + 1, i))
        start = None
    return out


def _weak_action(action: str, rules: VarietyRules) -> str | None:
    """Verbe statique d'une action courte (« Aiko regarde Kenji » → « regarde »), sinon None."""
    text = f" {_key(action)} "
    if len(text.split()) > rules.weak_max_words:
        return None
    return next((w for w in rules.weak_actions if f" {_key(w)} " in text), None)


def _runs(values: Sequence[str], limit: int) -> list[tuple[int, int, str]]:
    """Suites de plus de `limit` valeurs identiques : (première case, dernière case, valeur), numérotées à 1."""
    out: list[tuple[int, int, str]] = []
    start = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or _key(values[i]) != _key(values[start]):
            if i - start > limit and values[start]:
                out.append((start + 1, i, values[start]))
            start = i
    return out


def check_variety(
    pages: Sequence[tuple[int, Sequence[dict[str, Any]]]], rules: VarietyRules | None
) -> tuple[dict[int, list[str]], list[str]]:
    """Règles de variété sur des pages (numéro, cases dans l'ordre avec plan, angle, action) :
    (problèmes par numéro de page, problèmes du chapitre). Messages lisibles, en français."""
    by_page: dict[int, list[str]] = {}
    chapter: list[str] = []
    if rules is None:
        return by_page, chapter
    frontal = {_key(a) for a in rules.frontal_angles}
    off_level = {_key(a) for a in rules.off_eye_level}
    wide_medium = {_key(p) for p in rules.wide_medium_plans}
    tight = {_key(p) for p in rules.tight_plans}
    wide = {_key(p) for p in rules.wide_plans}
    total = front = loose = 0
    for number, panels in pages:
        problems: list[str] = []
        plans = [str(pa.get("plan") or "") for pa in panels]
        angles = [str(pa.get("angle") or "") for pa in panels]
        for first, last, value in _runs(plans, rules.max_same_plan_in_a_row):
            problems.append(
                f"cases {first} à {last} au même plan « {value} » "
                f"({rules.max_same_plan_in_a_row} d'affilée au plus : varie le cadrage)"
            )
        for first, last, value in _runs(angles, rules.max_same_angle_in_a_row):
            problems.append(
                f"cases {first} à {last} au même angle « {value} » ({rules.max_same_angle_in_a_row} d'affilée au plus)"
            )
        if rules.min_off_eye_level_per_page and len(panels) >= rules.off_eye_level_min_panels:
            off = sum(1 for p, a in zip(plans, angles, strict=True) if _key(p) in off_level or _key(a) in off_level)
            if off < rules.min_off_eye_level_per_page:
                problems.append(
                    f"aucune case hors hauteur d'œil (au moins {rules.min_off_eye_level_per_page} : "
                    f"plan ou angle parmi {', '.join(rules.off_eye_level)})"
                )
        for first, last in _wide_runs(plans, wide, rules.max_wide_in_a_row):
            problems.append(
                f"cases {first} à {last} en plan large d'affilée ({rules.max_wide_in_a_row} au plus : "
                "intercale un plan plus serré)"
            )
        if rules.min_tight_per_page and len(panels) >= rules.tight_min_panels:
            close = sum(1 for p in plans if _key(p) in tight)
            if close < rules.min_tight_per_page:
                problems.append(
                    f"{'aucun plan serré' if not close else f'{close} plan serré seulement'} "
                    f"(au moins {rules.min_tight_per_page} dès {rules.tight_min_panels} cases : "
                    f"{', '.join(rules.tight_plans)}) : serre le cadre sur l'émotion, la révélation ou la réplique clé"
                )
        if rules.require_action:
            for i, pa in enumerate(panels, start=1):
                action = str(pa.get("action") or "").strip()
                if not action:
                    problems.append(f"case {i} › action : vide (décris un mouvement ou une pose du corps)")
                elif (weak := _weak_action(action, rules)) is not None:
                    problems.append(
                        f"case {i} › action : « {action} » trop statique (« {weak} ») : "
                        "décris un mouvement ou une pose du corps"
                    )
        total += len(panels)
        front += sum(1 for a in angles if _key(a) in frontal)
        loose += sum(1 for p in plans if _key(p) in wide_medium)
        if problems:
            by_page[number] = problems
    allowed = max(1, math.floor(rules.max_frontal_share * total + 1e-9))
    if total and front > allowed:
        chapter.append(
            f"trop de cases {' / '.join(rules.frontal_angles)} : {front} sur {total} "
            f"({allowed} au plus, {round(rules.max_frontal_share * 100)} %) : varie les angles"
        )
    allowed = max(1, math.floor(rules.max_wide_medium_share * total + 1e-9))
    if total and loose > allowed:
        chapter.append(
            f"trop de plans larges et moyens ({' / '.join(rules.wide_medium_plans)}) : {loose} sur {total} "
            f"({allowed} au plus, {round(rules.max_wide_medium_share * 100)} %) : resserre sur les visages, "
            "les gestes et les objets"
        )
    return by_page, chapter


def output_variety(out: DirectionOutput, rules: VarietyRules | None) -> list[str]:
    """Règles de variété enfreintes par une réponse du LLM (messages pour la relance)."""
    pages = [(dp.page, [pa.model_dump() for pa in sorted(dp.panels, key=lambda p: p.panel)]) for dp in out.pages]
    by_page, chapter = check_variety(pages, rules)
    return [f"page {n} : {p}" for n, problems in by_page.items() for p in problems] + chapter


def page_warnings(
    pages: Sequence[Page], rules: VarietyRules | None, chapter_level: bool = True
) -> dict[int, list[str]]:
    """Avertissements de variété des choix stockés, par id de page (« chapitre : … » sur chacune)."""
    rows = [(p.number, list((p.direction.values or {}).get("panels") or [])) for p in pages if p.direction]
    by_page, chapter = check_variety(rows, rules)
    common = [CHAPTER_PREFIX + c for c in chapter] if chapter_level else []
    return {p.id: [*by_page.get(p.number, []), *common] for p in pages if p.direction}


# --- appel du LLM avec relances -------------------------------------------------
Progress = Callable[[int, str], None]


@dataclass
class DirectionRun:
    output: DirectionOutput
    attempts: int
    messages: list[ChatMessage]
    # Règles de variété encore enfreintes après les relances (proposition gardée, avertissements).
    variety: list[str] = field(default_factory=list)


def run_direction(llm: LLMProvider, prompt: PromptPreset, ctx: DirectionContext, progress: Progress) -> DirectionRun:
    messages = render_messages(prompt, ctx)
    total = 1 + prompt.max_retries
    last_error = ""
    # Dernière réponse valide qui n'enfreint que les règles de variété : gardée si les relances échouent.
    fallback: DirectionRun | None = None
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
            viewpoints = viewpoint_problems(output, ctx)
            variety = output_variety(output, ctx.rules)
            if viewpoints or variety:
                fallback = DirectionRun(output=output, attempts=attempt, messages=messages, variety=variety)
                parts = []
                if viewpoints:
                    parts.append("spectateur sans point de vue : " + " ; ".join(viewpoints[:8]))
                if variety:
                    parts.append("mise en scène trop répétitive : " + " ; ".join(variety[:8]))
                raise DirectionValidationError(" ; ".join(parts))
        except DirectionValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                progress(10 + attempt * 25, f"Réponse invalide ({last_error[:160]}), nouvel essai…")
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        default_viewpoints(output, ctx)
        return DirectionRun(output=output, attempts=attempt, messages=messages)
    if fallback is not None:
        # Spectateurs encore sans choix (ou inconnus de la case) : le choix par défaut, noté comme tel.
        default_viewpoints(fallback.output, ctx)
        return fallback
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
                "action": pa.action,
                "sfx": [s.model_dump() for s in pa.sfx],
                **({"decor": pa.decor} if pa.decor is not None else {}),
                **({"objets": pa.objets} if pa.objets is not None else {}),
                **(
                    {
                        "point_de_vue": pa.point_de_vue,
                        "spectateurs": list(pa.spectateurs or []),
                        **({"point_de_vue_defaut": True} if pa.point_de_vue_defaut else {}),
                    }
                    if pa.point_de_vue is not None
                    else {}
                ),
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
    session: Session,
    chapter: Chapter,
    pages: Sequence[Page],
    output: DirectionOutput,
    *,
    single_page: bool,
    rules: VarietyRules | None = None,
) -> list[int]:
    """Enregistre la proposition ; renvoie les numéros des pages modifiées.

    Une page acceptée par l'auteur n'est pas remplacée par une proposition de tout le chapitre (seul
    « Proposer autre chose » sur cette page la relance). Les champs verrouillés sont gardés. Les règles
    de variété encore enfreintes (après verrous) sont notées sur chaque page (`warnings`).
    """
    by_number = {dp.page: dp for dp in output.pages}
    changed: list[int] = []
    saved: list[Page] = []
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
        saved.append(page)
    for page in saved:
        page.direction.values = {**page.direction.values, "warnings": []}
    for page_id, warnings in page_warnings(saved, rules).items():
        page = next(p for p in saved if p.id == page_id)
        page.direction.values = {**page.direction.values, "warnings": warnings}
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
    action: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    sfx: list[DirectionSfx] | None = Field(default=None, max_length=MAX_SFX)
    point_de_vue: PointDeVueName | None = None
    spectateurs: list[Name] | None = Field(default=None, max_length=12)

    _n = field_validator("intensity", "plan", "angle", "cadre", mode="before")(_norm)
    _pdv = field_validator("point_de_vue", mode="before")(_point_de_vue)


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
            if value is None and name not in ("ambiance", "action", "sfx", "point_de_vue", "spectateurs"):
                raise ArtDirectionError(f"{name} : ne peut pas être vide")
            if name == "sfx":
                value = [s.model_dump() for s in value or []]
            elif name in ("ambiance", "action"):
                value = value or ""
            elif name == "spectateurs":
                value = list(value or [])
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
    # Avertissements de variété de la page recalculés ; ceux du chapitre (part de cases de face) restent.
    prompt = presets.prompts.get(PROMPT_ID)
    rules = prompt.variety_rules if prompt is not None else None
    kept = [w for w in values.get("warnings") or [] if w.startswith(CHAPTER_PREFIX)]
    fresh = page_warnings([page], rules, chapter_level=False).get(page.id, [])
    d.values = {**values, "warnings": [*fresh, *kept]}
    return d


# --- application à la mise en page ---------------------------------------------------
def applied_panel_direction(panel: Panel) -> dict[str, Any]:
    """Direction artistique appliquée à une case (plan, angle, ambiance…), {} sinon. Les choix du dialogue
    avec l'IA sur la case (`Panel.dialog_direction`) passent par-dessus ceux de la page."""
    applied = applied_values(panel.page)
    page = next((pa for pa in (applied or {}).get("panels") or [] if pa.get("panel_id") == panel.id), {})
    own = {
        k: v
        for k, v in (getattr(panel, "dialog_direction", None) or {}).items()
        if k in DIALOG_FIELDS and v is not None
    }
    return {**page, **own} if own else page


# Champs de direction artistique qu'un dialogue avec l'IA peut imposer à une case.
DIALOG_FIELDS = ("plan", "angle", "action", "ambiance")


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
        page_choc = bool(v.get("page_choc"))
        by_panel = {pa.get("panel_id"): pa for pa in v.get("panels") or []}
        before = {pa.get("panel_id"): pa for pa in previous.get("panels") or []}
        matcher = _matcher(page)
        for panel in page.panels:
            if intensities.get(panel.id) in INTENSITIES:
                panel.intensity = intensities[panel.id]
            choice = by_panel.get(panel.id)
            if choice is not None:
                _apply_cadre(
                    panel,
                    choice.get("cadre"),
                    (before.get(panel.id) or {}).get("cadre"),
                    break_out_allowed=page_choc or panel.intensity == "choc",
                )
                _apply_sfx(panel, choice.get("sfx") or [])
                if library is not None:
                    _apply_library(panel, choice, before.get(panel.id) or {}, library)
                _apply_viewpoint(panel, choice, before.get(panel.id) or {}, matcher)
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
    # Débordement sur les cases voisines : réservé aux pages choc et aux cases choc (sinon « normal »).
    "débordement": {"break_out": True},
    "fond perdu": {"break_out": True},  # ancienne proposition déjà stockée
    "incrustation": {"inset": True},
}
SFX_TO_INTENSITY = {"léger": "calme", "moyen": "normal", "fort": "choc"}
DA_SOURCE = "direction"  # marque des onomatopées posées par la direction artistique


def _apply_cadre(panel: Panel, cadre: str | None, before: str | None, *, break_out_allowed: bool = True) -> None:
    """Options de cadre de la DA : remplace celles de l'application précédente, jamais celles de l'auteur.
    Un débordement n'est posé que sur une page choc ou une case choc (`break_out_allowed`)."""
    if not break_out_allowed and "break_out" in CADRE_TO_FRAME.get(cadre or "normal", {}):
        cadre = "normal"
    current = dict(panel.frame or {})
    for key, value in CADRE_TO_FRAME.get(before or "normal", {}).items():
        if current.get(key) == value:
            current.pop(key)  # posée par la DA la dernière fois
    for key, value in CADRE_TO_FRAME.get(cadre or "normal", {}).items():
        current.setdefault(key, value)
    panel.frame = current or None


def _matcher(page: Page) -> CharacterMatcher | None:
    session = object_session(page)
    return CharacterMatcher.for_project(session, page.chapter.project_id) if session is not None else None


def _apply_viewpoint(
    panel: Panel, choice: dict[str, Any], before: dict[str, Any], matcher: CharacterMatcher | None
) -> None:
    """Point de vue de la DA : range les spectateurs (hors cadre en vue subjective, présents en plan de
    réaction) et le note sur la case. Jamais par-dessus un choix de l'auteur ; un choix inchangé depuis
    l'application précédente n'est pas réappliqué (l'auteur a pu corriger les personnages depuis)."""
    mode = viewpoint_key(choice.get("point_de_vue"))
    current = viewpoint_of(panel)
    if mode is None or (current is not None and current.get("source") == "auteur"):
        return
    spectators = list(choice.get("spectateurs") or [])
    same = (before.get("point_de_vue"), before.get("spectateurs") or []) == (choice.get("point_de_vue"), spectators)
    if same and current is not None:
        return
    source = "défaut" if choice.get("point_de_vue_defaut") else "direction"
    apply_viewpoint(panel, mode, spectators, source=source, matcher=matcher)


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
            changed = save_direction(
                session, chapter, targets, run.output, single_page=page_id is not None, rules=prompt.variety_rules
            )
            session.commit()
        tries = f" en {run.attempts} essais" if run.attempts > 1 else ""
        if run.variety:
            tries += f", avec {len(run.variety)} avertissement{'s' if len(run.variety) > 1 else ''} de mise en scène"
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
