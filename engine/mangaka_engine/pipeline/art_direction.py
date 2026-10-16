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

Name scène par scène (`pipeline/scene_name.py`) : quand le chapitre a des scènes validées et que chaque page de
l'histoire est rattachée à l'une d'elles, l'agent dirige le chapitre UNE SCÈNE À LA FOIS (ou une seule scène,
`scene_id`) : il reçoit le type et le profil de la scène (`$scene`), `check_variety` et `check_page_rules` lisent les
parts de plans de la charte de la scène (ADN de la série précisé par le profil : au moins 50 % de gros plans en
combat), quel que soit son nombre de pages ; les lignes de mouvement imposées ou interdites du profil partent dans
l'action et l'ambiance des cases (`apply_motion`) ; la famille `rhythm` du chapitre garde son rôle (pas de pics
d'affilée, une respiration après un pic, rythmes des pages d'avant compris ; premier pic et pic final en
avertissement sur le chapitre entier).

Savoir-faire : cherché page par page (`page_query` : le scénario de la page), dans le budget de l'agent,
sans doublon ; la trace du passage (« Sources utilisées ») note les pages de chaque fiche.

Mise en scène variée (`variety_rules` du preset, `check_variety`) : pas plus de N cases d'affilée au même
plan ou au même angle dans une page, une part plafonnée de cases « de face » et de plans larges ou moyens,
au moins une case hors hauteur d'œil et un plan serré par page, pas deux plans larges d'affilée, une
`action` de case qui décrit un mouvement du corps. Une règle enfreinte
relance l'agent avec l'erreur ; après les relances, la proposition est gardée avec un avertissement par
page (`warnings`), visible dans l'écran Direction artistique.

Règles par planche (`page_rules` du preset, `check_page_rules`) : un gros plan et une case calme par page, jamais
deux compositions identiques d'affilée (plan, angle, recette « gauche / droite »), pas plus de N cases « choc »
d'affilée sur le chapitre, l'élément important jamais relégué au fond derrière un personnage, une case sans
personnage dont l'action ne nomme personne. Vérifiées après la réponse : une seule relance ciblée renvoie au LLM
les seules cases fautives (`enforce_page_rules`), puis ce qui reste devient un avertissement, sans blocage.

Charte de la série (ADN, `pipeline/pre_direction.py`, en clair dans `$pre_direction`) : `check_variety` y lit
l'échelle des plans (parts par famille, plancher des plans larges, plafond des plans serrés : la relance dit
« élargis » autant que « resserre ») ; `check_page_rules` les formes de planche, la présence et la courbe de
rythme, corrigées par la même relance ciblée — sur les champs de la page (rythme, gabarit, page choc) quand la
règle porte sur la page entière — puis en avertissement.

Spectateur (`pipeline/framing.py`) : quand le texte d'une case met un personnage en spectateur (« voit »,
« regarde », « aperçoit », « découvre », « assiste »…), l'agent choisit explicitement `point_de_vue` :
« plan de réaction » (le spectateur est dessiné) ou « vue subjective » (on voit ce qu'il voit, le spectateur
reste hors cadre). Un choix manquant relance l'agent ; après les relances, le choix par défaut
(`framing.default_viewpoint`) est noté comme tel. « Appliquer » range les spectateurs (présents ou hors
cadre) et note le choix sur la case (`Panel.viewpoint`), sans jamais écraser un choix de l'auteur.

Les choix sont stockés par page (`PageDirection`). Un champ modifié par l'auteur est verrouillé : une
nouvelle proposition le garde tant qu'il n'est pas déverrouillé. La direction s'applique quand l'auteur
valide la page, sur « Appliquer », et d'office au lancement d'une génération (`apply_before_generation`)
— sauf une page que l'auteur a rejetée. Appliquer recopie les choix dans
ce que lit la grammaire de mise en page (rythme et style de la page, intensité des cases, gabarit
suggéré et page choc), inscrit le plan dans la case (`Panel.shot_type`) et donne au prompt image, aux
fiches de savoir-faire et au choix de la vue de référence le plan, l'angle, l'action et l'ambiance de la
direction ; le plan du scénario ne sert plus que de repli sans direction appliquée. Seules les
pages dont la mise en page change sont recalculées. Le cadre devient une option de cadre de la case (`Panel.frame` :
sans bord, débordement sur les cases voisines — seulement sur une page choc ou une case choc —,
incrustation) et les onomatopées des bulles `sfx` du lettrage — sans toucher
à une option ou une onomatopée réglée par l'auteur. Un décor ou des objets proposés remplacent ceux
de la case seulement s'ils ont changé depuis la dernière application (une correction de l'auteur
dans l'écran Scénario reste).
"""

from __future__ import annotations

import copy
import json
import logging
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from ..config import get_settings
from ..presets import PageRules, PresetRegistry, PromptPreset, VarietyRules
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.db import Database
from ..store.models import (
    Bubble,
    BubbleKind,
    Chapter,
    Character,
    LLMRun,
    Page,
    PageDirection,
    PageKind,
    Panel,
    SeriesLocation,
    utcnow,
)
from ..validation import format_errors
from .framing import (
    REACTION,
    SUBJECTIVE,
    VIEWPOINT_LABELS,
    Aliases,
    aliases_from,
    apply_viewpoint,
    cites,
    default_viewpoint,
    find_spectators,
    plain,
    same_name,
    viewpoint_key,
    viewpoint_of,
)
from .knowledge import AgentKnowledge, KnowledgeBase
from .layout import LayoutError
from .library import SeriesLibrary
from .names import CharacterMatcher
from .pages import applied_values, is_stale, layout_page
from .pre_direction import (
    Charter,
    PageView,
    _rhythm_issues,
    art_text,
    chapter_issues,
    scene_issues,
    series_charter,
    shot_problems,
)
from .scene_name import SceneFrame, frame_of, motion_rule, scene_frames, scene_mode
from .script import DIRECTION_LABELS, _render
from .style import NO_GUIDELINES, style_brief

AGENT = "art_direction"  # rôle de l'agent dans presets/knowledge.yaml
STEP = "art_direction"  # étape des jobs
PROMPT_ID = "direction-artistique"  # presets/prompts/direction-artistique.yaml

log = logging.getLogger("mangaka_engine")

RYTHMES = ("calme", "montée", "climax", "respiration")
INTENSITIES = ("calme", "normal", "choc")
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


# Plans de la direction artistique : vocabulaire de l'appli, dans le preset (`plans` de
# presets/prompts/direction-artistique.yaml), lu une fois au chargement du module.
def _preset_plans() -> tuple[str, ...]:
    """`plans` de presets/prompts/direction-artistique.yaml (dossier de presets du moteur). Preset absent ou
    illisible : aucun plan (la direction artistique refuse alors tout plan ; l'erreur du preset est exposée par
    `GET /presets`)."""
    path = get_settings().presets_dir / "prompts" / f"{PROMPT_ID}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        log.warning("plans de la direction artistique illisibles (%s)", path)
        return ()
    plans = data.get("plans") if isinstance(data, dict) else None
    if not isinstance(plans, list):
        log.warning("plans de la direction artistique absents de %s", path)
        return ()
    return tuple(dict.fromkeys(" ".join(str(p).split()) for p in plans if str(p).strip()))


PLANS: tuple[str, ...] = _preset_plans()


def _known_plan(value: str) -> str:
    if value not in PLANS:
        raise ValueError(f"valeur non autorisée « {value} » (attendu : {', '.join(PLANS)})")
    return value


PlanName = Annotated[str, AfterValidator(_known_plan)]
RythmeName = Literal["calme", "montée", "climax", "respiration"]
IntensityName = Literal["calme", "normal", "choc"]
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

# État d'une direction de page (`PageDirection.status`) : proposée par l'agent, appliquée aux cases (à la
# validation de l'auteur, sur « Appliquer » ou d'office au lancement d'une génération), rejetée par
# l'auteur (jamais appliquée d'office : les cases gardent le plan du scénario). « accepted » : ancienne
# validation sans application, traitée comme une page validée.
STATUSES = ("proposed", "applied", "rejected")
KEPT_STATUSES = ("applied", "accepted")  # pages qu'une proposition de tout le chapitre ne remplace pas
# Plans du scénario d'avant la première application (id de case → plan), gardés dans `PageDirection.applied`
# pour les rendre si l'auteur rejette ensuite la direction.
SCRIPT_SHOTS = "script_shots"


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
    # Lieu de la série (id existant, facultatif) : null ou absent = garder le lieu du scénario.
    lieu: int | None = None
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

    @field_validator("lieu", "decor", mode="before")
    @classmethod
    def _no_id(cls, v: Any) -> Any:
        return None if v in ("", "null", "aucun") else v

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
    page_rules: PageRules | None = None  # `page_rules` du preset (règles par planche)
    charter: Charter | None = None  # ADN de la série (presets/pre_direction.yaml), de la scène pour une scène
    # Name scène par scène : la scène dirigée, les rythmes des pages d'avant (dans l'ordre) et le lieu de la
    # dernière case d'avant.
    scene: SceneFrame | None = None
    before: list[str | None] = field(default_factory=list)
    previous_location: Any = None

    def as_json(self) -> dict[str, Any]:
        return {
            "task": "art_direction",
            **(
                {
                    "scene": {**self.scene.as_json(), "motion_lines": motion_rule(self.scene.profile)},
                    "before_rythmes": list(self.before),
                    "previous_location": self.previous_location,
                }
                if self.scene is not None
                else {}
            ),
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
                            "lieu": pa.get("location"),
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
            "page_rules": self.page_rules.model_dump(exclude={"retry", "page_retry"})
            if self.page_rules is not None
            else None,
            "pre_direction": self.charter.as_json() if self.charter is not None else None,
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
        "staging": (panel.staging or "") if present else "",  # case sans personnage : non utilisée (#167)
        "characters": present,
        "offscreen": offscreen,
        "spectators": viewers,
        "seen": spect.seen,
        "perception": spect.verb,
        "decor": panel.decor_id,
        "objets": list(panel.object_ids or []),
        # Unité de lieu (case d'établissement au changement de lieu, pre_direction.py) et répliques (cases de décor
        # muettes).
        "location": panel.location_id,
        "location_name": panel.location.name if panel.location_id is not None and panel.location else None,
        "replies": sum(1 for b in panel.bubbles if b.kind != BubbleKind.sfx),
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
    scene: SceneFrame | None = None,
    single: bool | None = None,
    before: Sequence[str | None] = (),
    previous_location: Any = None,
) -> DirectionContext:
    """Contexte de l'agent : tout le chapitre, une page (« Proposer autre chose »), ou les pages d'une scène
    (`scene` : sa charte remplace celle de la série)."""
    series = chapter.project
    characters = session.scalars(
        select(Character).where(Character.project_id == series.id).order_by(Character.name)
    ).all()
    targets = list(pages) if pages is not None else story_pages(chapter)
    if single is None:
        single = pages is not None and len(targets) == 1 and scene is None
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
        page_rules=prompt.page_rules,
        charter=scene.charter if scene is not None else series_charter(presets, series),
        scene=scene,
        before=list(before),
        previous_location=previous_location,
    )


def _pages_text(ctx: DirectionContext) -> str:
    names = {e["id"]: e["name"] for e in (*ctx.library.decors, *ctx.library.objets)}
    blocks = []
    place: Any = None
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
            if pa.get("location") is not None:
                change = " — NOUVEAU LIEU (case d'établissement)" if pa["location"] != place else ""
                who += f" — lieu : {pa.get('location_name') or '?'} (id {pa['location']}){change}"
                place = pa["location"]
            things = [f"{names[i]} (id {i})" for i in pa.get("objets") or [] if i in names]
            if things:
                who += f" — objets : {', '.join(things)}"
            hint = f" — plan du scénario : {pa['shot_type']}" if pa["shot_type"] else ""
            lines.append(f"  Case {i} (importance {pa['importance']}){hint}{who} : {pa['description']}")
            for d in pa["dialogues"]:
                lines.append(f"    « {d} »")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


NO_SCENE = (
    "(chapitre dirigé d'un seul tenant : pas de scène validée, la charte de la série s'applique à toutes les pages)"
)
MOTION_TEXT = {
    "required": "lignes de mouvement IMPOSÉES : chaque case d'action les montre (vitesse, impact, trajectoire) — "
    "écris-les dans « action » et « ambiance »",
    "forbidden": "lignes de mouvement INTERDITES : image posée, sans effet de vitesse — ni dans « action » ni dans "
    "« ambiance »",
}


def scene_text(ctx: DirectionContext) -> str:
    """La scène dirigée en clair ($scene) : type, pages, profil de tempo, distribution et lieu, lignes de mouvement,
    rythmes d'avant."""
    f = ctx.scene
    if f is None:
        return NO_SCENE
    span = f"page {f.first_page}" if f.pages == 1 else f"pages {f.first_page} à {f.last_page}"
    lines = [
        f"Tu diriges la {f.label}, {span} : {f.summary}",
        f"Profil de la scène (prime sur la charte de la série pour ces pages) : {f.tempo}.",
        f"Distribution de la scène : {f.cast_text}.",
    ]
    rule = motion_rule(f.profile)
    if rule:
        lines.append(f"- {MOTION_TEXT[rule]} ;")
    if any(p.startswith("shots.") for p in f.profile):
        lines.append("- parts de plans de la scène vérifiées sur ses seules cases (voir la charte ci-dessous) ;")
    if ctx.before:
        last = [r or "?" for r in ctx.before[-3:]]
        lines.append(
            f"- rythme des pages juste avant la scène : {', '.join(last)} — pas de pics d'affilée au-delà de la charte, "
            "une respiration juste après un pic, y compris à la jonction des scènes."
        )
    return "\n".join(lines)


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
        "lieux": ctx.library.text("lieux") or "(aucun lieu enregistré)",
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
        "page_rules": page_rules_text(ctx.page_rules),
        # Charte de la série (ADN) : échelle des plans, présence, formes de planche, courbe de rythme.
        "pre_direction": art_text(ctx.charter, len(ctx.pages)),
        # Scène dirigée (name scène par scène) : type, profil, lignes de mouvement, rythmes des pages d'avant.
        "scene": scene_text(ctx),
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
            for problem in [*ctx.library.check_refs(pa.decor, pa.objets or []), *ctx.library.check_location(pa.lieu)]:
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
    pages: Sequence[tuple[int, Sequence[dict[str, Any]]]],
    rules: VarietyRules | None,
    charter: Charter | None = None,
    *,
    scene: bool = False,
) -> tuple[dict[int, list[str]], list[str]]:
    """Règles de variété sur des pages (numéro, cases dans l'ordre avec plan, angle, action) :
    (problèmes par numéro de page, problèmes du chapitre). Messages lisibles, en français. Avec `charter`
    (ADN de la série), l'échelle des plans du chapitre suit aussi ses parts par famille de plans ; `scene` : pages
    d'une scène, `charter` est celle de la scène et ses parts de plans valent quel que soit le nombre de pages."""
    by_page: dict[int, list[str]] = {}
    chapter: list[str] = []
    if rules is None:
        plans = [pa.get("plan") for _n, panels in pages for pa in panels]
        return by_page, shot_problems(plans, charter, len(pages), scene=scene)
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
    plans = [pa.get("plan") for _n, panels in pages for pa in panels]
    chapter += shot_problems(plans, charter, len(pages), scene=scene)
    return by_page, chapter


def output_variety(
    out: DirectionOutput, rules: VarietyRules | None, charter: Charter | None = None, *, scene: bool = False
) -> list[str]:
    """Règles de variété enfreintes par une réponse du LLM (messages pour la relance)."""
    pages = [(dp.page, [pa.model_dump() for pa in sorted(dp.panels, key=lambda p: p.panel)]) for dp in out.pages]
    by_page, chapter = check_variety(pages, rules, charter, scene=scene)
    return [f"page {n} : {p}" for n, problems in by_page.items() for p in problems] + chapter


def page_warnings(
    pages: Sequence[Page],
    rules: VarietyRules | None,
    chapter_level: bool = True,
    page_rules: PageRules | None = None,
    charter: Charter | None = None,
    frames: Sequence[SceneFrame] = (),
) -> dict[int, list[str]]:
    """Avertissements de variété, des règles par planche et de la charte de la série des choix stockés, par id
    de page (« chapitre : … » sur chacune, ou sur les pages concernées pour une règle de la charte ou des cases
    « choc » d'affilée d'une page à l'autre). Avec `frames` (name scène par scène), chaque scène est mesurée avec
    sa propre charte (`scene_warnings`)."""
    if frames:
        return scene_warnings(pages, rules, page_rules, charter, frames, chapter_level=chapter_level)
    rows = [(p.number, list((p.direction.values or {}).get("panels") or [])) for p in pages if p.direction]
    by_page, chapter = check_variety(rows, rules, charter)
    common = [CHAPTER_PREFIX + c for c in chapter] if chapter_level else []
    ruled = page_rule_warnings(
        check_page_rules(stored_rows(pages), page_rules, chapter_names(pages), charter, stored_info(pages))
    )
    return {p.id: [*by_page.get(p.number, []), *ruled.get(p.number, []), *common] for p in pages if p.direction}


def _directed(page: Page) -> bool:
    return page.direction is not None and bool((page.direction.values or {}).get("panels"))


def _last_location(page: Page) -> Any:
    panels = (page.direction.values or {}).get("panels") or [] if page.direction else []
    by_id = {pa.id: pa for pa in page.panels}
    for choice in reversed(panels):
        panel = by_id.get(choice.get("panel_id"))
        location = panel.location_id if panel is not None and panel.location_id is not None else choice.get("lieu")
        if location is not None:
            return location
    return None


def scene_warnings(
    pages: Sequence[Page],
    rules: VarietyRules | None,
    page_rules: PageRules | None,
    charter: Charter | None,
    frames: Sequence[SceneFrame],
    *,
    chapter_level: bool = True,
) -> dict[int, list[str]]:
    """Avertissements des choix stockés, scène par scène : variété et parts de plans de la charte de la scène, règles
    par planche, charte de la scène (grande case du profil, case d'établissement, pics d'affilée et respiration avec
    les pages d'avant) — « scène N … : » devant ce qui porte sur la scène entière ; et, sur le chapitre entier
    (`chapter_level`), la place du premier pic et le pic final de la courbe de rythme de la série. Seules les pages
    de `pages` reçoivent des avertissements, mesurées avec toutes les pages dirigées de leur scène."""
    wanted = {p.id for p in pages if p.direction}
    out: dict[int, list[str]] = {pid: [] for pid in wanted}
    if not pages:
        return out
    chapter = pages[0].chapter
    every = [p for p in story_pages(chapter) if _directed(p)]
    by_number = {p.number: p for p in every}
    for frame in frames:
        group = [p for p in every if p.scene_id == frame.id]
        if not group or not wanted & {p.id for p in group}:
            continue
        rows = [(p.number, list((p.direction.values or {}).get("panels") or [])) for p in group]  # type: ignore[union-attr]
        by_page, whole = check_variety(rows, rules, frame.charter, scene=True)
        earlier = [p for p in every if p.number < group[0].number]
        issues = check_page_rules(stored_rows(group), page_rules, chapter_names(group))
        issues += scene_rule_issues(
            stored_rows(group),
            frame.charter,
            frame,
            stored_info(group),
            [(p.direction.values or {}).get("rythme") for p in earlier],  # type: ignore[union-attr]
            _last_location(earlier[-1]) if earlier else None,
        )
        ruled: dict[int, list[str]] = {}
        for issue in issues:
            for number in issue.pages:
                ruled.setdefault(number, []).append(issue.message)
        common = [f"{frame.label} : {w}" for w in whole]
        for page in group:
            if page.id in wanted:
                out[page.id] += [*by_page.get(page.number, []), *ruled.get(page.number, []), *common]
    if chapter_level and charter is not None and len(every) >= charter.settings.min_pages:
        views = [PageView(p.number, (p.direction.values or {}).get("rythme"), None, None, []) for p in every]  # type: ignore[union-attr]
        for issue in _rhythm_issues(views, charter):
            if "d'affilée" in issue.message or "respiration" in issue.message:
                continue  # déjà mesurés scène par scène, jonctions comprises
            for number in issue.pages:
                page = by_number.get(number)
                if page is not None and page.id in wanted:
                    out[page.id].append(CHAPTER_PREFIX + issue.message)
    return out


# --- règles par planche (page_rules) -------------------------------------------------------
# À l'échelle de la planche, pas de la case (audit du chapitre « vulcano ») : un gros plan et une case calme
# par page, jamais deux compositions identiques d'affilée, pas plus de N cases « choc » d'affilée, l'élément
# important jamais relégué au fond derrière un personnage, une case sans personnage qui le reste. Vérifiées
# après la réponse du LLM : une seule relance ciblée sur les cases fautives, puis un avertissement.
@dataclass
class RuleIssue:
    """Règle par planche enfreinte : message lisible et cases à corriger (page, case numérotée à 1)."""

    message: str
    # Cases à corriger (page, case) ; (page, 0) : les champs de la page (rythme, gabarit, page choc).
    cases: list[tuple[int, int]]
    pages: list[int]
    chapter: bool = False  # cases « choc » d'affilée à cheval sur plusieurs pages, règle de la charte

    def text(self) -> str:
        return self.message if self.chapter else f"page {self.pages[0]} : {self.message}"


# Ligne d'une page pour `check_page_rules` : (numéro, rythme, cases dans l'ordre). Chaque case : plan, angle,
# intensity, action, staging (mise en scène du scénario), visible (personnages à l'image), hidden (hors cadre)
# et importance (scénario).
PageRow = tuple[int, str | None, Sequence[dict[str, Any]]]
# Champs de page lus par la charte (formes de planche) : numéro → {"template": …, "page_choc": …}.
PageInfo = Mapping[int, Mapping[str, Any]]


def _has(text: str, markers: Sequence[str]) -> bool:
    t = f" {plain(text)} "
    return any(plain(m) in t for m in markers if m.strip())


def _cast(characters: Sequence[str], offscreen: Sequence[str], choice: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(à l'image, hors cadre) d'une case : en vue subjective, les spectateurs restent hors cadre."""
    visible = list(characters)
    hidden = list(offscreen)
    if viewpoint_key(choice.get("point_de_vue")) == SUBJECTIVE:
        spect = list(choice.get("spectateurs") or [])
        hidden += [n for n in visible if any(same_name(n, s) for s in spect)]
        visible = [n for n in visible if not any(same_name(n, s) for s in spect)]
    return visible, hidden


def output_rows(out: DirectionOutput, ctx: DirectionContext) -> list[PageRow]:
    """Pages d'une réponse du LLM, complétées par le scénario (personnages, mise en scène)."""
    briefs = _briefs_by_page(ctx)
    rows: list[PageRow] = []
    for dp in sorted(out.pages, key=lambda p: p.page):
        brief = briefs.get(dp.page)
        panels = []
        for pa in sorted(dp.panels, key=lambda p: p.panel):
            info = brief.panels[pa.panel - 1] if brief and 1 <= pa.panel <= len(brief.panels) else {}
            choice = pa.model_dump()
            visible, hidden = _cast(info.get("characters") or [], info.get("offscreen") or [], choice)
            location = pa.lieu if pa.lieu is not None else info.get("location")
            panels.append(
                {
                    **choice,
                    "staging": info.get("staging") or "",
                    "visible": visible,
                    "hidden": hidden,
                    "importance": info.get("importance") or 2,
                    "location": location,
                    "location_name": ctx.library.location_name(location) or info.get("location_name"),
                    "replies": info.get("replies") or 0,
                }
            )
        rows.append((dp.page, dp.rythme, panels))
    return rows


def output_info(out: DirectionOutput) -> dict[int, dict[str, Any]]:
    return {dp.page: {"template": dp.template, "page_choc": dp.page_choc} for dp in out.pages}


def stored_info(pages: Sequence[Page]) -> dict[int, dict[str, Any]]:
    out = {}
    for page in pages:
        values = (page.direction.values or {}) if page.direction else {}
        out[page.number] = {"template": values.get("template"), "page_choc": values.get("page_choc")}
    return out


def stored_rows(pages: Sequence[Page]) -> list[PageRow]:
    """Pages dont les choix sont stockés, complétées par leurs cases (personnages, mise en scène)."""
    rows: list[PageRow] = []
    for page in sorted(pages, key=lambda p: p.number):
        values = (page.direction.values or {}) if page.direction else {}
        if not values.get("panels"):
            continue
        by_id = {pa.id: pa for pa in page.panels}
        panels = []
        for choice in values["panels"]:
            panel = by_id.get(choice.get("panel_id"))
            chars = list(panel.character_names or []) if panel else []
            off = list(panel.offscreen_names or []) if panel else []
            visible, hidden = _cast(chars, off, choice)
            location = panel.location if panel is not None and panel.location_id is not None else None
            panels.append(
                {
                    **choice,
                    "staging": (panel.staging or "") if panel else "",
                    "visible": visible,
                    "hidden": hidden,
                    "importance": panel.importance if panel else 2,
                    # Lieu appliqué à la case (sinon proposé par la direction) : celui que verra la génération.
                    "location": location.id if location is not None else choice.get("lieu"),
                    "location_name": location.name if location is not None else None,
                    "replies": sum(1 for b in panel.bubbles if b.kind != BubbleKind.sfx) if panel else 0,
                }
            )
        rows.append((page.number, values.get("rythme"), panels))
    return rows


def chapter_names(pages: Sequence[Page]) -> list[str]:
    """Personnages cités dans les cases des pages (à l'image ou hors cadre)."""
    names: list[str] = []
    for page in pages:
        for panel in page.panels:
            for n in [*(panel.character_names or []), *(panel.offscreen_names or [])]:
                if n and not any(same_name(n, o) for o in names):
                    names.append(n)
    return names


def _span(cases: Sequence[tuple[int, int]]) -> str:
    (p1, c1), (p2, c2) = cases[0], cases[-1]
    if p1 == p2:
        return f"cases {c1} à {c2}"
    return f"page {p1} case {c1} à page {p2} case {c2}"


def charter_issues(pages: Sequence[PageRow], charter: Charter | None, info: PageInfo | None) -> list[RuleIssue]:
    """Formes de planche, présence et courbe de rythme (ADN de la série) en règles par planche du chapitre."""
    info = info or {}
    views = [
        PageView(
            number,
            rythme,
            (info.get(number) or {}).get("template"),
            (info.get(number) or {}).get("page_choc"),
            panels,
        )
        for number, rythme, panels in pages
    ]
    every = [number for number, _r, _p in pages]
    out = []
    for issue in chapter_issues(views, charter):
        touched = list(dict.fromkeys([*issue.pages, *(p for p, _c in issue.cases)]))
        out.append(
            RuleIssue(
                issue.message,
                [*((p, 0) for p in issue.pages), *issue.cases],
                sorted(touched) or every,
                chapter=True,
            )
        )
    return out


def check_page_rules(
    pages: Sequence[PageRow],
    rules: PageRules | None,
    names: Sequence[str] = (),
    charter: Charter | None = None,
    info: PageInfo | None = None,
) -> list[RuleIssue]:
    """Règles par planche (`page_rules` du preset) sur des pages dans l'ordre : règles enfreintes, en français.
    Avec `charter` (ADN de la série) et `info` (gabarit et page choc de chaque page), aussi les formes de planche,
    la présence et la courbe de rythme du chapitre."""
    issues: list[RuleIssue] = charter_issues(pages, charter, info) if charter is not None else []
    if rules is None:
        return issues
    close = {_key(p) for p in rules.close_plans}
    calm = {_key(i) for i in rules.calm_intensities}
    calm_rythmes = {_key(r) for r in rules.calm_rythmes}
    choc = {_key(i) for i in rules.choc_intensities}
    for number, rythme, panels in pages:
        n = len(panels)
        cases = list(range(1, n + 1))
        plans = [_key(pa.get("plan")) for pa in panels]
        intensities = [_key(pa.get("intensity")) for pa in panels]
        if rules.min_close_per_page and n >= rules.close_min_panels:
            count = sum(1 for p in plans if p in close)
            if count < rules.min_close_per_page:
                issues.append(
                    RuleIssue(
                        f"{'aucun gros plan' if not count else f'{count} gros plan seulement'} (au moins "
                        f"{rules.min_close_per_page} dès {rules.close_min_panels} cases : "
                        f"{', '.join(rules.close_plans)}) : passe en gros plan la case qui porte l'émotion, le "
                        "geste ou l'objet clé",
                        [(number, i) for i in cases if plans[i - 1] not in close],
                        [number],
                    )
                )
        if rules.min_calm_per_page and n >= rules.calm_min_panels:
            restful = _key(rythme) in calm_rythmes
            count = sum(1 for i in intensities if i in calm or (restful and i not in choc))
            if count < rules.min_calm_per_page:
                issues.append(
                    RuleIssue(
                        f"aucune case calme (au moins {rules.min_calm_per_page} dès {rules.calm_min_panels} cases : "
                        f"intensité {' / '.join(rules.calm_intensities)}) : ménage une pause (réaction, souffle, "
                        "regard) pour que les temps forts existent",
                        [(number, i) for i in cases if intensities[i - 1] not in calm],
                        [number],
                    )
                )
        if rules.no_repeated_composition:
            keys = [(_key(pa.get("plan")), _key(pa.get("angle")), _left_right(pa, rules)) for pa in panels]
            first = 0
            for i in range(1, n + 1):
                if i < n and keys[i] == keys[first]:
                    continue
                if i - first > 1:
                    pa = panels[first]
                    recipe = ", personnages à gauche et à droite" if keys[first][2] else ""
                    span = f"cases {first + 1} et {i}" if i - first == 2 else f"cases {first + 1} à {i}"
                    redo = f"case {i}" if i - first == 2 else f"cases {first + 2} à {i}"
                    issues.append(
                        RuleIssue(
                            f"{span} : même composition (« {pa.get('plan')} », « {pa.get('angle')} »{recipe}) : "
                            f"change le plan, l'angle ou la disposition (en {redo})",
                            [(number, c) for c in range(first + 2, i + 1)],
                            [number],
                        )
                    )
                first = i
        for i, pa in enumerate(panels, start=1):
            action = str(pa.get("action") or "")
            drawn_viewer = viewpoint_key(pa.get("point_de_vue")) == REACTION
            if (
                rules.no_background_subject
                and _has(action, rules.background_markers)
                and (_has(action, rules.foreground_markers) or drawn_viewer)
            ):
                fix = (
                    "choisis la vue subjective (ce qui est vu, en grand, le spectateur hors cadre) ou un plan de "
                    "réaction serré sur son visage"
                    if drawn_viewer
                    else "mets ce qui compte au premier plan, ou serre le cadre dessus"
                )
                issues.append(
                    RuleIssue(
                        f"case {i} › action : l'élément important est relégué au fond derrière un personnage : {fix}",
                        [(number, i)],
                        [number],
                    )
                )
            if rules.empty_panel_without_names and action:
                visible = list(pa.get("visible") or [])
                hidden = [*(pa.get("hidden") or []), *([] if visible else names)]
                named = [
                    h for h in dict.fromkeys(hidden) if not any(same_name(h, v) for v in visible) and cites(action, h)
                ]
                if named:
                    where = "case sans personnage à l'image" if not visible else "personnage hors cadre"
                    issues.append(
                        RuleIssue(
                            f"case {i} › action : {where}, l'action ne nomme pas {', '.join(named)} (il serait "
                            "dessiné) : décris le décor, l'objet ou ce qui est vu",
                            [(number, i)],
                            [number],
                        )
                    )
    if rules.max_choc_in_a_row:
        run: list[tuple[int, int]] = []
        for number, _rythme, panels in [*pages, (0, None, [{}])]:
            for i, pa in enumerate(panels, start=1):
                if number and _key(pa.get("intensity")) in choc:
                    run.append((number, i))
                    continue
                if len(run) > rules.max_choc_in_a_row:
                    pages_in = list(dict.fromkeys(p for p, _ in run))
                    issues.append(
                        RuleIssue(
                            f"{_span(run)} : {len(run)} cases « choc » d'affilée ({rules.max_choc_in_a_row} au plus) "
                            "— quand tout est un choc, plus rien ne choque : passe-en en « normal » ou « calme »",
                            list(run),
                            pages_in,
                            chapter=len(pages_in) > 1,
                        )
                    )
                run = []
    return issues


def _left_right(panel: dict[str, Any], rules: PageRules) -> bool:
    """Recette « X à gauche / Y à droite » dans l'action ou la mise en scène de la case."""
    return _has(f"{panel.get('action') or ''} {panel.get('staging') or ''}", rules.left_right_markers)


def page_rule_warnings(issues: Sequence[RuleIssue]) -> dict[int, list[str]]:
    """Avertissements par numéro de page (« chapitre : … » sur chaque page d'une suite à cheval)."""
    out: dict[int, list[str]] = {}
    for issue in issues:
        text = CHAPTER_PREFIX + issue.message if issue.chapter else issue.message
        for number in issue.pages:
            out.setdefault(number, []).append(text)
    return out


def page_rules_text(rules: PageRules | None) -> str:
    """Règles par planche en clair, pour le prompt de l'agent ($page_rules)."""
    if rules is None:
        return "(aucune règle par planche)"
    lines = []
    if rules.min_close_per_page:
        lines.append(
            f"- au moins {rules.min_close_per_page} {' / '.join(rules.close_plans)} par page (dès "
            f"{rules.close_min_panels} cases) : le visage, les yeux, la main, l'objet clé ;"
        )
    if rules.min_calm_per_page:
        lines.append(
            f"- au moins {rules.min_calm_per_page} case calme par page (dès {rules.calm_min_panels} cases), même "
            "en plein combat : une pause, une réaction, un souffle ;"
        )
    if rules.max_choc_in_a_row:
        lines.append(f"- jamais plus de {rules.max_choc_in_a_row} cases « choc » d'affilée sur le chapitre ;")
    if rules.no_repeated_composition:
        lines.append(
            "- jamais deux cases d'affilée de même composition (même plan, même angle, même recette « un "
            "personnage à gauche, un autre à droite ») : varie la disposition, pas seulement le plan ;"
        )
    if rules.no_background_subject:
        lines.append(
            "- ce qui compte (ce qui est vu, l'arme, le fuyard) n'est jamais relégué au fond derrière un héros : "
            "montre-le en grand, ou choisis la vue subjective ;"
        )
    if rules.empty_panel_without_names:
        lines.append(
            "- une case sans personnage (décor, objet, ce qui est vu) est permise quand le texte s'y prête ; son "
            "action ne nomme alors aucun personnage."
        )
    return "\n".join(lines) or "(aucune règle par planche)"


# --- appel du LLM avec relances -------------------------------------------------
Progress = Callable[[int, str], None]


@dataclass
class DirectionRun:
    output: DirectionOutput
    attempts: int
    messages: list[ChatMessage]
    # Règles de variété encore enfreintes après les relances (proposition gardée, avertissements).
    variety: list[str] = field(default_factory=list)
    # Règles par planche encore enfreintes après la relance ciblée (proposition gardée, avertissements).
    page_rules: list[str] = field(default_factory=list)
    targeted: bool = False  # relance ciblée faite sur les cases fautives


def run_direction(llm: LLMProvider, prompt: PromptPreset, ctx: DirectionContext, progress: Progress) -> DirectionRun:
    """Réponse validée du LLM (relances complètes sur une réponse invalide ou trop répétitive), puis règles
    par planche : une seule relance ciblée sur les cases fautives, le reste en avertissement."""
    run = _run_full(llm, prompt, ctx, progress)
    return enforce_page_rules(llm, prompt, ctx, run, progress)


def _run_full(llm: LLMProvider, prompt: PromptPreset, ctx: DirectionContext, progress: Progress) -> DirectionRun:
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
            variety = output_variety(output, ctx.rules, ctx.charter, scene=ctx.scene is not None)
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


class _PatchPage(_LLMModel):
    page: int = Field(ge=1, le=200)
    panels: list[DirectionPanel] = Field(default_factory=list, max_length=20)
    # Champs de la page, pris seulement pour une règle de la charte qui porte sur la page entière.
    rythme: RythmeName | None = None
    template: str | None = None
    page_choc: PageChocName | None = None

    _n = field_validator("rythme", "page_choc", "template", mode="before")(_norm)

    @field_validator("panels", mode="before")
    @classmethod
    def _none_panels(cls, v: Any) -> Any:
        return [] if v is None else v


class DirectionPatch(_LLMModel):
    """Réponse à la relance ciblée : seulement les cases corrigées (objets complets)."""

    pages: list[_PatchPage] = Field(min_length=1, max_length=200)


def output_page_issues(out: DirectionOutput, ctx: DirectionContext) -> list[RuleIssue]:
    names = [c["name"] for c in ctx.characters if c.get("name")]
    rows = output_rows(out, ctx)
    if ctx.scene is not None:
        # Une scène : règles par planche, puis la charte de la scène (grande case du profil, case d'établissement,
        # pics d'affilée et respiration avec les pages d'avant).
        issues = check_page_rules(rows, ctx.page_rules, names)
        return issues + scene_rule_issues(
            rows, ctx.charter, ctx.scene, output_info(out), ctx.before, ctx.previous_location
        )
    # Charte du chapitre (formes, présence, rythme) : seulement sur toutes les pages dirigées ensemble.
    charter = None if ctx.single_page else ctx.charter
    return check_page_rules(rows, ctx.page_rules, names, charter, output_info(out))


def scene_rule_issues(
    rows: Sequence[PageRow],
    charter: Charter | None,
    frame: SceneFrame,
    info: PageInfo | None,
    before: Sequence[str | None] = (),
    previous_location: Any = None,
) -> list[RuleIssue]:
    """Charte d'une scène (`pre_direction.scene_issues`) en règles par planche."""
    info = info or {}
    views = [
        PageView(
            number,
            rythme,
            (info.get(number) or {}).get("template"),
            (info.get(number) or {}).get("page_choc"),
            panels,
        )
        for number, rythme, panels in rows
    ]
    every = [number for number, _r, _p in rows]
    out = []
    for issue in scene_issues(views, charter, frame.profile, before=before, previous_location=previous_location):
        touched = list(dict.fromkeys([*issue.pages, *(p for p, _c in issue.cases)]))
        out.append(
            RuleIssue(
                f"{frame.label} : {issue.message}",
                [*((p, 0) for p in issue.pages), *issue.cases],
                sorted(touched) or every,
                chapter=True,
            )
        )
    return out


def targeted_text(rules: PageRules, issues: Sequence[RuleIssue]) -> str:
    """Message de la relance ciblée : les règles enfreintes et les seules cases à renvoyer (et les pages dont
    renvoyer aussi les champs de page, pour une règle de la charte qui porte sur la page entière)."""
    cases: dict[int, list[int]] = {}
    whole: list[int] = []
    for issue in issues:
        for number, case in issue.cases:
            if case == 0:
                if number not in whole:
                    whole.append(number)
                cases.setdefault(number, [])
            elif case not in cases.setdefault(number, []):
                cases[number].append(case)
    where = " ; ".join(
        f"page {n} : case{'s' if len(c) > 1 else ''} {', '.join(map(str, sorted(c)))}"
        if c
        else f"page {n} : champs de la page"
        for n, c in sorted(cases.items())
    )
    text = _render(
        rules.retry,
        {"error": "\n".join(f"- {i.text()}" for i in issues), "cases": where},
        "page_rules.retry",
    )
    if whole:
        text += "\n" + _render(rules.page_retry, {"pages": ", ".join(map(str, sorted(whole)))}, "page_rules.page_retry")
    return text


def _patched(out: DirectionOutput, patch: DirectionPatch, allowed: set[tuple[int, int]]) -> DirectionOutput | None:
    """Réponse où seules les cases fautives (`allowed`) sont remplacées par la correction ; None si rien ne change."""
    merged = out.model_copy(deep=True)
    pages = {dp.page: dp for dp in merged.pages}
    changed = False
    for pp in patch.pages:
        dp = pages.get(pp.page)
        if dp is None:
            continue
        if (pp.page, 0) in allowed:
            for name in sorted({"rythme", "template", "page_choc"} & pp.model_fields_set):
                value = getattr(pp, name)
                if name == "rythme" and value is None:
                    continue
                if getattr(dp, name) != value:
                    setattr(dp, name, value)
                    changed = True
        for pa in pp.panels:
            if (pp.page, pa.panel) not in allowed:
                continue
            index = next((i for i, old in enumerate(dp.panels) if old.panel == pa.panel), None)
            if index is not None:
                dp.panels[index] = pa
                changed = True
    return merged if changed else None


def enforce_page_rules(
    llm: LLMProvider, prompt: PromptPreset, ctx: DirectionContext, run: DirectionRun, progress: Progress
) -> DirectionRun:
    """Règles par planche (`page_rules`) : une relance ciblée au plus (`targeted_retry`) qui ne corrige que les
    cases fautives ; la correction n'est gardée que si elle enfreint moins de règles. Ce qui reste devient un
    avertissement (jamais un blocage, même si le LLM ne répond pas)."""
    rules = ctx.page_rules
    issues = output_page_issues(run.output, ctx)
    if rules is None or not issues:
        return run
    if rules.targeted_retry:
        progress(85, f"Règles par planche : relance ciblée ({len(issues)} à corriger)…")
        answer = json.dumps(run.output.model_dump(mode="json"), ensure_ascii=False)
        messages = [*run.messages, ChatMessage("assistant", answer), ChatMessage("user", targeted_text(rules, issues))]
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
            m = _FENCE.match(result.text)
            patch = DirectionPatch.model_validate(json.loads(m.group(1) if m else result.text.strip()))
        except (LLMError, json.JSONDecodeError, ValidationError, TypeError):
            patch = None
        allowed = {c for issue in issues for c in issue.cases}
        merged = _patched(run.output, patch, allowed) if patch is not None else None
        if merged is not None and not check_against(merged, ctx):
            default_viewpoints(merged, ctx)
            after = output_page_issues(merged, ctx)
            variety = output_variety(merged, ctx.rules, ctx.charter, scene=ctx.scene is not None)
            if len(after) + len(variety) < len(issues) + len(run.variety):
                run = DirectionRun(output=merged, attempts=run.attempts, messages=run.messages, variety=variety)
                issues = after
        run.targeted = True
    run.page_rules = [i.text() for i in issues]
    return run


# --- lignes de mouvement du profil de la scène ----------------------------------------------
MOTION_REQUIRED = "lignes de mouvement marquées (vitesse, impact)"
MOTION_FORBIDDEN = "image posée, sans lignes de mouvement"
_MOTION_WORDS = re.compile(r",?\s*(?:avec |et )?(?:des )?lignes de (?:mouvement|vitesse)[^,;.]*", re.IGNORECASE)


def _append(text: str, extra: str, limit: int) -> str:
    text = text.strip().rstrip(".")
    if extra.lower() in text.lower():
        return text
    joined = f"{text}, {extra}" if text else extra[:1].upper() + extra[1:]
    return joined if len(joined) <= limit else text[: max(0, limit - len(extra) - 3)].rstrip() + f"…, {extra}"


def apply_motion(out: DirectionOutput, frame: SceneFrame | None) -> None:
    """Lignes de mouvement imposées ou interdites par le profil de la scène : recopiées dans l'action et l'ambiance
    des cases (que lit le rédacteur de prompt image). Imposées : chaque case qui n'est pas calme les porte dans son
    ambiance et son action ; interdites : retirées du texte, et l'ambiance dit « image posée »."""
    rule = motion_rule(frame.profile) if frame is not None else None
    if rule is None:
        return
    for dp in out.pages:
        for pa in dp.panels:
            if rule == "required":
                if pa.intensity == "calme":
                    continue
                pa.ambiance = _append(pa.ambiance, MOTION_REQUIRED, 300)
                pa.action = _append(pa.action, "lignes de vitesse", 200)
            else:
                pa.action = _MOTION_WORDS.sub("", pa.action).strip()
                pa.ambiance = _append(_MOTION_WORDS.sub("", pa.ambiance).strip(), MOTION_FORBIDDEN, 300)


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
                **({"lieu": pa.lieu} if pa.lieu is not None else {}),
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


def is_pending(direction: PageDirection) -> bool:
    """Choix pas encore appliqués aux cases (jamais appliqués, ou modifiés depuis la dernière application)."""
    if direction.applied is None:
        return True
    return {k: v for k, v in direction.applied.items() if k != SCRIPT_SHOTS} != direction.values


def to_apply_at_generation(page: Page) -> bool:
    """La direction de la page s'applique d'office au lancement d'une génération : proposée (ou modifiée
    depuis son application), ni rejetée par l'auteur, ni dépassée par un scénario modifié."""
    d = page.direction
    return d is not None and bool(d.values) and d.status != "rejected" and not is_out_of_date(d, page) and is_pending(d)


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
    page_rules: PageRules | None = None,
    charter: Charter | None = None,
    frames: Sequence[SceneFrame] = (),
    force: bool = False,
) -> list[int]:
    """Enregistre la proposition ; renvoie les numéros des pages modifiées.

    Une page validée ou appliquée n'est pas remplacée par une proposition de tout le chapitre (seul
    « Proposer autre chose » sur cette page la relance) ; une page rejetée reçoit la nouvelle proposition
    et redevient « proposée ». Les champs verrouillés sont gardés. Les règles
    de variété encore enfreintes (après verrous) sont notées sur chaque page (`warnings`). `force` : une scène
    redirigée seule — ses pages reçoivent la nouvelle proposition même appliquées (verrous gardés) ; `frames` :
    avertissements scène par scène (`scene_warnings`).
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
        elif d.status in KEPT_STATUSES and not (single_page or force):
            continue
        # Cases supprimées depuis : leurs verrous disparaissent.
        ids = {str(p.id) for p in page.panels}
        d.locks = [k for k in d.locks or [] if "." not in k or k.split(".", 1)[0] in ids]
        d.values = merge_locked(to_values(dp, page), d.values, d.locks)
        if single_page or force or d.status == "rejected":
            d.status = "proposed"  # nouvelle proposition : appliquée à la prochaine génération, sauf rejet
        if single_page:
            d.variant = (d.variant or 0) + 1
        changed.append(page.number)
        saved.append(page)
    for page in saved:
        page.direction.values = {**page.direction.values, "warnings": []}
    session.flush()
    for page_id, warnings in page_warnings(saved, rules, page_rules=page_rules, charter=charter, frames=frames).items():
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
    page_rules = prompt.page_rules if prompt is not None else None
    charter = series_charter(presets, page.chapter.project)
    kept = [w for w in values.get("warnings") or [] if w.startswith(CHAPTER_PREFIX)]
    frames = scene_frames(presets, page.chapter)
    if not scene_mode(page.chapter, frames):
        frames = []
    fresh = page_warnings(
        [page], rules, chapter_level=False, page_rules=page_rules, charter=charter, frames=frames
    ).get(page.id, [])
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
    presets: PresetRegistry,
    pages: Sequence[Page],
    library: SeriesLibrary | None = None,
    *,
    skip_rejected: bool = False,
) -> ApplyResult:
    """Recopie la direction artistique dans les cases et les champs lus par la mise en page, puis recalcule
    uniquement les pages dont la mise en page change. Le plan de chaque case devient son plan inscrit
    (`Panel.shot_type`) ; l'angle, l'action et l'ambiance sont lus dans la direction appliquée
    (`applied_panel_direction`). Un plan retouché par l'auteur est un choix verrouillé de la direction
    (écran Direction artistique, ou `keep_author_plan` depuis l'écran Scénario) : il est réappliqué tel quel.
    La page passe « appliquée ». `skip_rejected` : les pages rejetées par l'auteur sont laissées de côté."""
    result = ApplyResult()
    for page in sorted(pages, key=lambda p: p.number):
        d = page.direction
        if d is None or not d.values:
            continue
        if skip_rejected and d.status == "rejected":
            result.skipped.append({"number": page.number, "reason": "direction rejetée par l'auteur"})
            continue
        if is_out_of_date(d, page):
            result.skipped.append(
                {"number": page.number, "reason": "cases modifiées depuis la proposition : relance l'agent"}
            )
            continue
        v = d.values
        previous = d.applied or {}
        script_shots = dict(previous.get(SCRIPT_SHOTS) or {})
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
                plan = choice.get("plan")
                if isinstance(plan, str) and plan.strip():
                    script_shots.setdefault(str(panel.id), panel.shot_type)
                    panel.shot_type = plan.strip()
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
        d.applied = {**copy.deepcopy(v), SCRIPT_SHOTS: script_shots}
        d.applied_at = utcnow()
        d.status = "applied"
        result.applied.append(page.number)
        if page.layout is None or is_stale(page):
            try:
                layout_page(presets, page)
            except LayoutError as exc:
                result.skipped.append({"number": page.number, "reason": str(exc)})
                continue
            result.relaid.append(page.number)
    return result


def apply_before_generation(session: Session, presets: PresetRegistry, page: Page) -> bool:
    """Lancer une génération vaut accord : la direction proposée (ou modifiée depuis son application) de la
    page est appliquée d'office, sauf si l'auteur l'a rejetée. True si elle vient d'être appliquée."""
    if not to_apply_at_generation(page):
        return False
    library = SeriesLibrary.load(session, page.chapter.project_id)
    return bool(apply_direction(presets, [page], library).applied)


def reject_direction(page: Page) -> PageDirection:
    """L'auteur ne veut pas de la direction de cette page : elle n'est plus appliquée (ni d'office à la
    génération) et les cases reprennent le plan du scénario, sauf un plan retouché depuis. Les options de
    mise en page déjà posées (intensités, cadres, onomatopées) restent jusqu'à la prochaine application."""
    d = page.direction
    if d is None or not d.values:
        raise ArtDirectionError(f"la page {page.number} n'a pas encore de direction artistique : rien à rejeter")
    applied = d.applied or {}
    shots = applied.get(SCRIPT_SHOTS) or {}
    plans = {pa.get("panel_id"): pa.get("plan") for pa in applied.get("panels") or []}
    for panel in page.panels:
        key = str(panel.id)
        if key in shots and panel.shot_type == plans.get(panel.id):
            panel.shot_type = shots[key]
    d.applied = None
    d.applied_at = None
    d.status = "rejected"
    return d


def keep_author_plan(page: Page, panel_id: int, plan: str) -> None:
    """Plan d'une case retouché à la main dans l'écran Scénario : devient un choix verrouillé de la direction
    artistique de la page (gardé par les nouvelles propositions et les applications suivantes) et, si elle
    est appliquée, le plan appliqué — la génération le suit tout de suite."""
    d = page.direction
    if d is None or not d.values:
        return
    values = copy.deepcopy(d.values)
    target = next((pa for pa in values.get("panels") or [] if pa.get("panel_id") == panel_id), None)
    if target is None:
        return
    target["plan"] = plan
    locks = list(d.locks or [])
    if f"{panel_id}.plan" not in locks:
        locks.append(f"{panel_id}.plan")
    d.locks = locks
    d.values = values
    if d.applied:
        applied = copy.deepcopy(d.applied)
        for pa in applied.get("panels") or []:
            if pa.get("panel_id") == panel_id:
                pa["plan"] = plan
        shots = applied.get(SCRIPT_SHOTS)
        if isinstance(shots, dict) and str(panel_id) in shots:
            shots[str(panel_id)] = plan  # un rejet ultérieur garde le plan de l'auteur
        d.applied = applied


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
    """Décor, objets et lieu proposés : appliqués s'ils existent encore et ont changé depuis l'application
    précédente (sinon l'auteur a pu les corriger dans l'écran Scénario : on garde sa version)."""
    lieu = choice.get("lieu")
    session = object_session(panel)
    if lieu is not None and lieu != before.get("lieu") and any(e["id"] == lieu for e in library.lieux) and session:
        panel.location = session.get(SeriesLocation, lieu)
    decor = choice.get("decor")
    if decor is not None and decor != before.get("decor") and not library.check_refs(decor, []):
        panel.decor_id = decor
    objets = choice.get("objets")
    if objets is not None and objets != before.get("objets"):
        known = {e["id"] for e in library.objets}
        panel.object_ids = [i for i in objets if i in known]


_SFX_REPEATS = re.compile(r"(.)\1+")


def sfx_key(text: str) -> str:
    """Clé de comparaison d'une onomatopée : sans casse, accents, ponctuation ni espaces, lettres répétées
    réduites à une (« GRAAA ! », « Graaaa », « graa » → « gra » ; « Bam… » → « bam »)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    letters = "".join(ch for ch in decomposed if ch.isalnum())
    return _SFX_REPEATS.sub(r"\1", letters) or text.strip().casefold()


def _apply_sfx(panel: Panel, sfx: Sequence[dict[str, Any]]) -> None:
    """Onomatopées de la DA : celles de l'application précédente (non retouchées) sont remplacées ;
    celles du scénario ou ajoutées à la main restent, et une onomatopée déjà présente n'est pas doublée
    (comparaison `sfx_key` : « GRAAA ! » = « GRAAA »). Une quasi-doublure d'une onomatopée du scénario la
    remplace (texte et intensité de la DA, même place) ; une onomatopée placée à la main n'est jamais touchée."""
    for b in list(panel.bubbles):
        params = b.sfx or {}
        if b.kind == BubbleKind.sfx and params.get("source") == DA_SOURCE and not (b.position or {}).get("manual"):
            panel.bubbles.remove(b)
    present = {sfx_key(b.text): b for b in panel.bubbles if b.kind == BubbleKind.sfx}
    proposed: set[str] = set()
    order = max((b.order for b in panel.bubbles), default=-1) + 1
    for item in sfx:
        text = str(item.get("text") or "").strip()
        key = sfx_key(text) if text else ""
        if not key or key in proposed:
            continue
        proposed.add(key)
        intensity = SFX_TO_INTENSITY.get(str(item.get("intensity") or "moyen"), "normal")
        existing = present.get(key)
        if existing is not None:
            if not (existing.position or {}).get("manual"):
                existing.text = text
                existing.sfx = {**(existing.sfx or {}), "intensity": intensity}
            continue
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
    scene_id: int | None = None,
) -> Callable[[Progress], str]:
    """Job « Direction artistique » d'un chapitre — scène par scène quand ses scènes sont validées et ses pages
    rattachées —, d'une seule scène (`scene_id`) ou d'une seule page (« Proposer autre chose »)."""

    def run(progress: Progress) -> str:
        prompt = presets.prompt(PROMPT_ID)
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ArtDirectionError("Chapitre introuvable (supprimé entre-temps ?)")
            targets = _targets(chapter, page_id)
            frames = scene_frames(presets, chapter)
            if not scene_mode(chapter, frames):
                frames = []
            if scene_id is not None and frame_of(frames, scene_id) is None:
                raise ArtDirectionError(
                    "Scène introuvable, ou chapitre pas écrit scène par scène : valide les scènes, puis réécris le "
                    "scénario"
                )
            progress(5, "Préparation du contexte (scénario, bible, style de la série, chapitre précédent)…")
            if frames and page_id is None:
                return _run_scenes(db, presets, llm, chapter, prompt, frames, scene_id, knowledge, job_id, progress)
            frame = frame_of(frames, targets[0].scene_id) if frames and page_id is not None else None
            before, previous = _before(chapter, targets[0]) if frame is not None else ([], None)
            ctx = build_context(
                session,
                presets,
                chapter,
                prompt,
                pages=targets if page_id else None,
                knowledge=knowledge,
                scene=frame,
                single=True if page_id is not None else None,
                before=before,
                previous_location=previous,
            )
            if ctx.knowledge is not None:
                record_run(session, chapter, ctx.knowledge, job_id=job_id, model=getattr(llm, "model", llm.name))
                session.commit()
        run = run_direction(llm, prompt, ctx, progress)
        apply_motion(run.output, frame)
        progress(90, "Enregistrement des choix de direction artistique…")
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ArtDirectionError("Chapitre introuvable (supprimé entre-temps ?)")
            targets = _targets(chapter, page_id)
            changed = save_direction(
                session,
                chapter,
                targets,
                run.output,
                single_page=page_id is not None,
                rules=prompt.variety_rules,
                page_rules=prompt.page_rules,
                charter=series_charter(presets, chapter.project),
                frames=frames,
            )
            session.commit()
        tries = f" en {run.attempts} essais" if run.attempts > 1 else ""
        if run.targeted:
            tries += ", relance ciblée sur les règles par planche"
        warned = len(run.variety) + len(run.page_rules)
        if warned:
            tries += f", avec {warned} avertissement{'s' if warned > 1 else ''} de mise en scène"
        if page_id is not None:
            return f"Nouvelle proposition pour la page {changed[0] if changed else '?'}{tries}"
        kept = len(ctx.pages) - len(changed)
        extra = (
            f" ({kept} page{'s' if kept > 1 else ''} appliquée{'s' if kept > 1 else ''} gardée{'s' if kept > 1 else ''} :"
            " « Proposer autre chose » pour la changer)"
            if kept
            else ""
        )
        return f"{len(changed)} page{'s' if len(changed) > 1 else ''} dirigée{'s' if len(changed) > 1 else ''}{extra}{tries}"

    return run


def _before(
    chapter: Chapter, first: Page, chosen: Mapping[int, str | None] | None = None
) -> tuple[list[str | None], Any]:
    """Rythmes des pages de l'histoire avant `first` (choix de ce passage `chosen`, sinon direction stockée) et lieu
    de la dernière case d'avant."""
    earlier = [p for p in story_pages(chapter) if p.number < first.number]
    chosen = chosen or {}
    rythmes = [
        chosen[p.number] if p.number in chosen else ((p.direction.values or {}).get("rythme") if p.direction else None)
        for p in earlier
    ]
    location = None
    if earlier:
        location = _last_location(earlier[-1]) if _directed(earlier[-1]) else None
        if location is None:
            location = next((pa.location_id for pa in reversed(earlier[-1].panels) if pa.location_id is not None), None)
    return rythmes, location


def _run_scenes(
    db: Database,
    presets: PresetRegistry,
    llm: LLMProvider,
    chapter: Chapter,
    prompt: PromptPreset,
    frames: Sequence[SceneFrame],
    scene_id: int | None,
    knowledge: KnowledgeBase | None,
    job_id: int | None,
    progress: Progress,
) -> str:
    """Direction scène par scène : une génération par scène (ou la seule scène `scene_id`), chacune avec sa charte,
    son profil et les rythmes des pages d'avant ; la proposition de toutes les scènes est enregistrée d'un coup.
    Appelé avec la session de préparation ouverte (fermée avant le premier appel au LLM)."""
    session = object_session(chapter)
    assert session is not None
    chapter_id = chapter.id
    todo = [f for f in frames if scene_id is None or f.id == scene_id]
    plans: list[tuple[SceneFrame, list[int], DirectionContext]] = []
    for frame in todo:
        pages = [p for p in story_pages(chapter) if p.scene_id == frame.id]
        if not pages:
            continue
        ctx = build_context(session, presets, chapter, prompt, pages=pages, knowledge=knowledge, scene=frame)
        if ctx.knowledge is not None:
            record_run(session, chapter, ctx.knowledge, job_id=job_id, model=getattr(llm, "model", llm.name))
        plans.append((frame, [p.id for p in pages], ctx))
    if not plans:
        raise ArtDirectionError("Aucune page à diriger dans cette scène : écris d'abord son scénario")
    first_pages = {
        frame.id: min(p.number for p in story_pages(chapter) if p.scene_id == frame.id) for frame, _i, _c in plans
    }
    session.commit()
    session.close()

    chosen: dict[int, str | None] = {}
    outputs: list[DirectionPage] = []
    runs: list[DirectionRun] = []
    span = 80 / len(plans)
    for k, (frame, _ids, ctx) in enumerate(plans):
        # Rythmes d'avant : ceux de ce passage pour les scènes déjà dirigées, sinon la direction stockée.
        with db.session_scope() as s2:
            ch = s2.get(Chapter, chapter_id)
            if ch is None:
                raise ArtDirectionError("Chapitre introuvable (supprimé entre-temps ?)")
            first = next(p for p in story_pages(ch) if p.number == first_pages[frame.id])
            ctx.before, ctx.previous_location = _before(ch, first, chosen)
        low = 5 + k * span

        def step(pct: int, message: str, low: float = low, frame: SceneFrame = frame) -> None:
            progress(int(low + span * min(max(pct, 0), 100) / 100), f"Scène {frame.number}/{len(frames)} — {message}")

        run = run_direction(llm, prompt, ctx, step)
        apply_motion(run.output, frame)
        runs.append(run)
        for dp in run.output.pages:
            chosen[dp.page] = dp.rythme
            outputs.append(dp)
    progress(90, "Enregistrement des choix de direction artistique…")
    merged = DirectionOutput.model_construct(pages=outputs)
    ids = [i for _f, page_ids, _c in plans for i in page_ids]
    with db.session_scope() as s3:
        ch = s3.get(Chapter, chapter_id)
        if ch is None:
            raise ArtDirectionError("Chapitre introuvable (supprimé entre-temps ?)")
        targets = [p for p in story_pages(ch) if p.id in ids]
        changed = save_direction(
            s3,
            ch,
            targets,
            merged,
            single_page=False,
            rules=prompt.variety_rules,
            page_rules=prompt.page_rules,
            charter=series_charter(presets, ch.project),
            frames=frames,
            force=scene_id is not None,
        )
        s3.commit()
    attempts = max(r.attempts for r in runs)
    tries = f" en {attempts} essais" if attempts > 1 else ""
    if any(r.targeted for r in runs):
        tries += ", relance ciblée sur les règles par planche"
    warned = sum(len(r.variety) + len(r.page_rules) for r in runs)
    if warned:
        tries += f", avec {warned} avertissement{'s' if warned > 1 else ''} de mise en scène"
    n = len(changed)
    pages = f"{n} page{'s' if n > 1 else ''} dirigée{'s' if n > 1 else ''}"
    if scene_id is not None:
        return f"Scène {plans[0][0].number} redirigée : {pages}{tries}"
    kept = len(ids) - n
    extra = (
        f" ({kept} page{'s' if kept > 1 else ''} appliquée{'s' if kept > 1 else ''} gardée{'s' if kept > 1 else ''} :"
        " « Proposer autre chose » ou « Rediriger la scène » pour la changer)"
        if kept
        else ""
    )
    return f"{pages}, scène par scène ({len(plans)} scène{'s' if len(plans) > 1 else ''}){extra}{tries}"


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
