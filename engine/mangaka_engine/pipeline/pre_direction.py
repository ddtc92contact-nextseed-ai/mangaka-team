"""ADN de la série (pré-direction) : la charte chiffrée d'une série, lue par le scénariste, le directeur
artistique et leurs contrôles.

- **valeurs** : `presets/pre_direction.yaml` donne le défaut ultime (`defaults`) et les défauts des 7 genres
  (`genres`) ; la série hérite de ceux de son genre et peut en ajuster, valeur par valeur (`Project.pre_direction`,
  chemins « famille.champ[.min|max] »). Uniquement des nombres bornés et des booléens, validés par Pydantic
  (`PreDirection`) : jamais de texte libre ;
- **scénariste** (`pipeline/script.py`) : cases par planche (`panel_count_problems`) et dialogue compté par
  planche (`dialogue_rules_for` → `pipeline/dialogues.py`) ;
- **directeur artistique** (`pipeline/art_direction.py`) : échelle des plans dans `check_variety`
  (`shot_problems` : plancher des plans larges, plafond des plans serrés — la relance dit « élargis » autant que
  « resserre ») ; formes de planche, présence, courbe de rythme et lieux (case d'établissement au changement de
  lieu, cases de décor muettes) dans `check_page_rules` (`chapter_issues`) ;
- **prompts** : `$pre_direction` en clair (`script_text` pour le scénariste, `art_text` pour la direction
  artistique) ; `$style_guidelines` reste.

La charte avertit, elle ne bloque pas : une règle enfreinte relance l'agent, puis devient un avertissement visible.
Elle est distincte de la garde d'étapes (`pipeline/stage_gate.py`). Aucun seuil ici : tous viennent du preset.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from ..presets import PresetRegistry
from ..presets.schemas import (
    SHOT_CLASSES,
    TIGHT_CLASSES,
    DialogueRules,
    LayoutTemplate,
    PreDirection,
    PreDirectionSettings,
    ShareRange,
)
from ..store.models import Project
from .framing import REACTION, SUBJECTIVE, plain, viewpoint_key
from .layout import _leaf_shares

log = logging.getLogger("mangaka_engine")

EPS = 1e-9

# --- libellés (écran « ADN de la série », messages) ------------------------------------
GROUPS: dict[str, str] = {
    "panels": "Cases par planche",
    "shapes": "Formes de planche",
    "shots": "Échelle des plans",
    "presence": "Présence",
    "dialogue": "Dialogue",
    "rhythm": "Courbe de rythme",
    "places": "Lieux et décors",
}
SHOT_LABELS: dict[str, str] = {
    "close_up": "gros plans",
    "medium_close": "plans rapprochés",
    "medium": "plans moyens",
    "wide": "plans larges / d'ensemble",
    "insert": "inserts",
}
# Libellé et aide de chaque valeur réglable (chemin → (libellé, aide)).
LABELS: dict[str, tuple[str, str]] = {
    "panels.min_per_page": ("Cases par planche, au moins", "Une pleine page d'une seule case reste permise."),
    "panels.max_per_page": ("Cases par planche, au plus", ""),
    "shapes.big_panel_share.min": ("Planches à grande case, au moins", "Part des planches du chapitre."),
    "shapes.big_panel_share.max": ("Planches à grande case, au plus", ""),
    "shapes.max_same_in_a_row": (
        "Planches de même forme d'affilée, au plus",
        "Forme : page choc, gabarit, ou nombre de cases et de grandes cases.",
    ),
    "shapes.max_same_share": ("Une même forme sur le chapitre, au plus", "Part des planches du chapitre."),
    "shots.close_up.min": ("Gros plans, au moins", "Gros plan et très gros plan, part des cases du chapitre."),
    "shots.close_up.max": ("Gros plans, au plus", ""),
    "shots.medium_close.min": ("Plans rapprochés, au moins", ""),
    "shots.medium_close.max": ("Plans rapprochés, au plus", ""),
    "shots.medium.min": ("Plans moyens, au moins", ""),
    "shots.medium.max": ("Plans moyens, au plus", "Au-delà, la relance dit « resserre »."),
    "shots.wide.min": ("Plans larges / d'ensemble, au moins", "En dessous, la relance dit « élargis »."),
    "shots.wide.max": ("Plans larges / d'ensemble, au plus", "Au-delà, la relance dit « resserre »."),
    "shots.insert.min": ("Inserts, au moins", ""),
    "shots.insert.max": ("Inserts, au plus", ""),
    "shots.tight_max": (
        "Plans serrés, au plus",
        "Gros plan, plan rapproché et insert ensemble ; au-delà, la relance dit « élargis ».",
    ),
    "presence.subjective.min": ("Vue subjective, au moins", "Part des cases du chapitre."),
    "presence.subjective.max": ("Vue subjective, au plus", ""),
    "presence.empty.min": ("Cases sans personnage, au moins", "Décor, objet, ce qui est vu."),
    "presence.empty.max": ("Cases sans personnage, au plus", ""),
    "dialogue.min_per_page": ("Répliques par planche, au moins", "Onomatopées à part ; borné par la place des cases."),
    "dialogue.max_per_page": ("Répliques par planche, au plus", ""),
    "dialogue.min_silent_panels": ("Cases muettes par planche, au moins", "Cases sans aucune réplique."),
    "dialogue.max_words": ("Mots par réplique, au plus", "Au-delà, le scénariste est relancé : « coupe la réplique »."),
    "dialogue.max_mean_words": ("Mots par réplique en moyenne, au plus", "Moyenne sur le chapitre."),
    "dialogue.target_per_panel": (
        "Répliques visées par case",
        "Dans chaque case où un personnage présent peut parler, sans dépasser la place des bulles.",
    ),
    "dialogue.action_needs_voice": (
        "Case d'action parlée",
        "Une case d'action ou de combat a au moins une parole en plus de l'onomatopée. Non : case d'action muette "
        "permise.",
    ),
    "rhythm.first_peak.min": ("Premier pic, au plus tôt", "Position dans le chapitre (0 % = début)."),
    "rhythm.first_peak.max": ("Premier pic, au plus tard", ""),
    "rhythm.breath_after_peak": ("Respiration obligatoire après un pic", ""),
    "rhythm.max_peaks_in_a_row": ("Pics d'affilée, au plus", "Pages « climax » qui se suivent."),
    "rhythm.final_peak_last_pages": (
        "Pic final dans les dernières planches",
        "Nombre de planches de fin où placer un pic (0 = libre).",
    ),
    "places.establishing": (
        "Case d'établissement au changement de lieu",
        "La première case d'un nouveau lieu est un plan large ou d'ensemble qui installe le lieu.",
    ),
    "places.silent_decor_min": (
        "Cases de décor muettes, au moins",
        "Ni personnage à l'image ni réplique : le lieu seul. Part des cases du chapitre.",
    ),
}


def _de(label: str) -> str:
    """« de plans moyens », « d'inserts »."""
    return f"d'{label}" if label[:1] in "aeiouyéèh" else f"de {label}"


def _pct(value: float) -> str:
    return f"{round(value * 100)} %"


def _key(value: Any) -> str:
    return " ".join(plain(str(value or "")).split())


# --- valeurs : genre, puis ajustements de la série ----------------------------------------
class DnaError(ValueError):
    """Ajustement refusé (message lisible, en français) sur une valeur de la charte."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.message = message


def _leaves(model: type[BaseModel], prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for name, info in model.model_fields.items():
        ann = info.annotation
        path = f"{prefix}{name}"
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            out += _leaves(ann, path + ".")
        else:
            out.append((path, info))
    return out


LEAVES: dict[str, Any] = dict(_leaves(PreDirection))


def flatten(dna: PreDirection) -> dict[str, Any]:
    """{"shots.wide.min": 0.15, …} dans l'ordre du schéma."""
    data = dna.model_dump()
    out: dict[str, Any] = {}
    for path in LEAVES:
        value: Any = data
        for part in path.split("."):
            value = value[part]
        out[path] = value
    return out


def _nest(flat: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, value in flat.items():
        node = out
        *parents, last = path.split(".")
        for p in parents:
            node = node.setdefault(p, {})
        node[last] = value
    return out


def _kind(path: str) -> str:
    ann = LEAVES[path].annotation
    if ann is bool or ann == "bool":
        return "bool"
    if ann is int or ann == "int":
        return "int"
    return "share"


def apply_overrides(base: PreDirection, overrides: Mapping[str, Any]) -> PreDirection:
    """ADN `base` ajusté ; `DnaError` sur une valeur inconnue, du mauvais type ou hors bornes."""
    for path, value in overrides.items():
        if path not in LEAVES:
            raise DnaError(path, f"valeur inconnue de l'ADN : « {path} »")
        kind = _kind(path)
        ok = (
            isinstance(value, bool)
            if kind == "bool"
            else isinstance(value, int | float)
            and not isinstance(value, bool)
            and (kind != "int" or value == int(value))
        )
        if not ok:
            expected = {"bool": "oui ou non", "int": "un nombre entier", "share": "une part entre 0 et 1"}[kind]
            raise DnaError(path, f"{LABELS.get(path, (path,))[0]} : {expected} attendu")
    flat = {**flatten(base), **{p: (int(v) if _kind(p) == "int" else v) for p, v in overrides.items()}}
    # Plafond de mots réglé par la série sous la moyenne héritée (réglé avant que les défauts passent à 22 / 14,
    # 15/10) : la moyenne héritée suit le plafond, l'ajustement de la série reste valable.
    if "dialogue.max_words" in overrides and "dialogue.max_mean_words" not in overrides:
        flat["dialogue.max_mean_words"] = min(flat["dialogue.max_mean_words"], flat["dialogue.max_words"])
    try:
        return PreDirection.model_validate(_nest(flat))
    except ValidationError as exc:
        err = exc.errors()[0]
        loc = ".".join(str(x) for x in err["loc"])
        path = loc if loc in LEAVES else next((p for p in overrides if p.startswith(loc)), loc)
        label = LABELS.get(path, (path,))[0]
        message = str(err["msg"]).removeprefix("Value error, ")
        bounds = {
            "min doit être ≤ max": "le minimum doit rester sous le maximum",
            "max_mean_words doit être ≤ max_words": "la moyenne doit rester sous le plafond de mots par réplique",
        }
        raise DnaError(path, f"{label} : {bounds.get(message, message)}") from None


def clean_overrides(base: PreDirection, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Ajustements utiles : connus et différents de la valeur héritée."""
    inherited = flatten(base)
    return {
        p: v
        for p, v in overrides.items()
        if p in LEAVES and not (v == inherited[p] or (isinstance(v, float) and abs(v - inherited[p]) < EPS))
    }


@dataclass(frozen=True)
class Charter:
    """ADN effectif d'une série, avec le vocabulaire des contrôles (familles de plans, rythmes, gabarits)."""

    dna: PreDirection
    settings: PreDirectionSettings
    templates: tuple[LayoutTemplate, ...] = ()
    genre: str | None = None

    def as_json(self) -> dict[str, Any]:
        s = self.settings
        return {
            **self.dna.model_dump(),
            "shot_classes": {k: list(v) for k, v in s.shot_classes.items()},
            "peak_rythmes": list(s.peak_rythmes),
            "breath_rythmes": list(s.breath_rythmes),
            "min_pages": s.min_pages,
            # Gabarits qui ont une grande case (formes de planche).
            "big_templates": [
                t.id
                for t in self.templates
                if t.panel_count > 1 and max(_leaf_shares(t.tree)) >= s.big_area_ratio / t.panel_count - EPS
            ],
        }


def inherited_dna(presets: PresetRegistry, project: Project) -> PreDirection | None:
    """Valeurs du genre de la série (le défaut ultime sans genre) ; None sans pre_direction.yaml."""
    return presets.genre_dna(project.style_genre)


def series_charter(presets: PresetRegistry, project: Project) -> Charter | None:
    """ADN de la série : celui de son genre, ajusté par la série. Un ajustement devenu invalide (bornes du preset
    changées) est ignoré, jamais bloquant."""
    settings = presets.pre_direction
    base = inherited_dna(presets, project)
    if settings is None or base is None:
        return None
    try:
        dna = apply_overrides(base, project.pre_direction or {})
    except DnaError as exc:
        log.warning("ADN de la série %s : ajustement ignoré (%s)", project.id, exc.message)
        dna = base
    return Charter(dna, settings, tuple(presets.layout_templates.values()), project.style_genre)


# --- scénariste : cases et dialogue par planche ---------------------------------------
def dialogue_rules_for(rules: DialogueRules | None, charter: Charter | None) -> DialogueRules | None:
    """Règles de dialogue du preset avec les valeurs par planche de l'ADN de la série."""
    if rules is None or charter is None:
        return rules
    d = charter.dna.dialogue
    return rules.model_copy(
        update={
            "min_per_page": d.min_per_page,
            "max_per_page": d.max_per_page,
            "min_silent_panels_per_page": d.min_silent_panels,
            "max_words": d.max_words,
            "max_mean_words": float(d.max_mean_words),
            "target_per_panel": d.target_per_panel,
            "action_needs_voice": d.action_needs_voice,
        }
    )


def panel_count_problems(counts: Sequence[int], charter: Charter | None) -> list[str]:
    """Pages (numérotées à partir de 1) dont le nombre de cases sort de la charte ; une pleine page est permise."""
    if charter is None:
        return []
    p = charter.dna.panels
    problems = []
    for number, n in enumerate(counts, start=1):
        if n == 1 or p.min_per_page <= n <= p.max_per_page:
            continue
        fix = "regroupe des cases" if n > p.max_per_page else "découpe davantage le moment (réaction, détail, décor)"
        problems.append(
            f"page {number} : {n} case{'s' if n > 1 else ''} ({p.min_per_page} à {p.max_per_page} par planche pour "
            f"cette série, ou une pleine page d'une seule case) : {fix}"
        )
    return problems


# --- direction artistique : échelle des plans (check_variety) ---------------------------
def shot_class(plan: Any, settings: PreDirectionSettings) -> str | None:
    k = _key(plan)
    return next((c for c, plans in settings.shot_classes.items() if k in {_key(p) for p in plans}), None)


def _allowed(share: float, total: int) -> int:
    """Cases permises au plus : une au moins, sauf part nulle."""
    n = math.floor(share * total + EPS)
    return n if share <= 0 else max(1, n)


def _required(share: float, total: int) -> int:
    return math.ceil(share * total - EPS)


def shot_problems(plans: Sequence[Any], charter: Charter | None, pages: int) -> list[str]:
    """Parts de l'échelle des plans sur les cases dirigées ensemble (dès `min_pages` pages), en français."""
    if charter is None or pages < charter.settings.min_pages or not plans:
        return []
    s = charter.settings
    shots = charter.dna.shots
    total = len(plans)
    counts = Counter(shot_class(p, s) for p in plans)
    out: list[str] = []
    for cls in SHOT_CLASSES:
        r: ShareRange = getattr(shots, cls)
        n = counts.get(cls, 0)
        names = " / ".join(s.shot_classes[cls])
        need = _required(r.min, total)
        if n < need:
            if cls == "wide":
                fix = (
                    "élargis : installe le lieu, montre les personnages en pied dans leur décor, suis l'action de loin"
                )
            else:
                fix = f"passe davantage de cases en {names}"
            out.append(f"trop peu {_de(SHOT_LABELS[cls])} : {n} sur {total} (au moins {need}, {_pct(r.min)}) : {fix}")
        allowed = _allowed(r.max, total)
        if n > allowed:
            fix = (
                "resserre sur les visages, les gestes et les objets"
                if cls in ("wide", "medium")
                else "élargis ou varie le cadrage"
            )
            out.append(f"trop {_de(SHOT_LABELS[cls])} : {n} sur {total} ({allowed} au plus, {_pct(r.max)}) : {fix}")
    tight = sum(counts.get(c, 0) for c in TIGHT_CLASSES)
    allowed = _allowed(shots.tight_max, total)
    if tight > allowed:
        names = ", ".join(p for c in TIGHT_CLASSES for p in s.shot_classes[c])
        out.append(
            f"trop de plans serrés ({names}) : {tight} sur {total} ({allowed} au plus, {_pct(shots.tight_max)}) : "
            "élargis — un plan moyen pour relier les personnages, un plan large pour installer le lieu"
        )
    return out


# --- direction artistique : formes, présence, rythme (check_page_rules) ------------------
@dataclass
class PageView:
    """Une page dirigée, vue par la charte : rythme, gabarit, page choc et cases (plan, angle, point de vue,
    personnages à l'image `visible`, importance du scénario)."""

    number: int
    rythme: str | None
    template: str | None
    page_choc: str | None
    panels: Sequence[dict[str, Any]] = field(default_factory=list)


@dataclass
class CharterIssue:
    """Règle de la charte enfreinte : message, cases à corriger (page, case) et pages dont les champs de page
    (rythme, gabarit, page choc) sont à revoir."""

    message: str
    cases: list[tuple[int, int]]
    pages: list[int]


@dataclass(frozen=True)
class Shape:
    key: str
    label: str
    big: bool


def page_shape(view: PageView, charter: Charter) -> Shape:
    """Forme d'une planche : page choc, sinon gabarit choisi, sinon nombre de cases et de grandes cases (importance
    du scénario) — « 3 cases dont 1 grande » — et si elle a une grande case."""
    if view.page_choc:
        return Shape(f"choc:{_key(view.page_choc)}", f"page choc ({view.page_choc})", True)
    n = len(view.panels)
    tpl = next((t for t in charter.templates if t.id == view.template and t.panel_count == n), None)
    if tpl is not None:
        big = n == 1 or max(_leaf_shares(tpl.tree)) >= charter.settings.big_area_ratio / n - EPS
        return Shape(f"tpl:{tpl.id}", f"« {tpl.name} »", big)
    k = sum(1 for pa in view.panels if int(pa.get("importance") or 2) >= charter.settings.big_importance)
    label = f"{n} case{'s' if n > 1 else ''}" + (f" dont {k} grande{'s' if k > 1 else ''}" if k and n > 1 else "")
    return Shape(f"auto:{n}:{k if n > 1 else 0}", label, n == 1 or k > 0)


def _span(pages: Sequence[int]) -> str:
    return f"page {pages[0]}" if len(pages) == 1 else f"pages {pages[0]} à {pages[-1]}"


def _runs(keys: Sequence[str]) -> list[tuple[int, int]]:
    """Suites de valeurs identiques : (premier index, dernier index exclus)."""
    out = []
    start = 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or keys[i] != keys[start]:
            out.append((start, i))
            start = i
    return out


def _subjective(pa: Mapping[str, Any]) -> bool:
    return viewpoint_key(pa.get("point_de_vue")) == SUBJECTIVE or _key(pa.get("angle")) == "vue subjective"


def chapter_issues(views: Sequence[PageView], charter: Charter | None) -> list[CharterIssue]:
    """Formes de planche, présence et courbe de rythme des pages dirigées ensemble (dès `min_pages` pages)."""
    if charter is None or len(views) < charter.settings.min_pages:
        return []
    views = sorted(views, key=lambda v: v.number)
    return [
        *_shape_issues(views, charter),
        *_presence_issues(views, charter),
        *_rhythm_issues(views, charter),
        *_place_issues(views, charter),
    ]


def _shape_issues(views: Sequence[PageView], charter: Charter) -> list[CharterIssue]:
    d = charter.dna.shapes
    n = len(views)
    shapes = [page_shape(v, charter) for v in views]
    numbers = [v.number for v in views]
    out: list[CharterIssue] = []
    fix = "change de gabarit (« template »), ou fais d'un vrai sommet une page choc"
    for a, b in _runs([s.key for s in shapes]):
        if b - a > d.max_same_in_a_row:
            out.append(
                CharterIssue(
                    f"{_span(numbers[a:b])} : {b - a} planches de même forme d'affilée ({shapes[a].label}, "
                    f"{d.max_same_in_a_row} au plus) : {fix}",
                    [],
                    numbers[a + d.max_same_in_a_row : b],
                )
            )
    key, count = Counter(s.key for s in shapes).most_common(1)[0]
    allowed = _allowed(d.max_same_share, n)
    if count > allowed:
        same = [numbers[i] for i, s in enumerate(shapes) if s.key == key]
        label = next(s.label for s in shapes if s.key == key)
        out.append(
            CharterIssue(
                f"{count} planches sur {n} de même forme ({label}, {allowed} au plus, "
                f"{_pct(d.max_same_share)}) : {fix}",
                [],
                same[allowed:],
            )
        )
    big = [numbers[i] for i, s in enumerate(shapes) if s.big]
    need = _required(d.big_panel_share.min, n)
    if len(big) < need:
        out.append(
            CharterIssue(
                f"{len(big)} planche{'s' if len(big) > 1 else ''} à grande case sur {n} (au moins {need}, "
                f"{_pct(d.big_panel_share.min)}) : donne une grande case aux temps forts (gabarit à grande case ou "
                "page choc)",
                [],
                [x for x in numbers if x not in big],
            )
        )
    allowed = _allowed(d.big_panel_share.max, n)
    if len(big) > allowed:
        out.append(
            CharterIssue(
                f"{len(big)} planches à grande case sur {n} ({allowed} au plus, "
                f"{_pct(d.big_panel_share.max)}) : garde un gaufrier régulier pour les pages de dialogue ou "
                "d'installation (gabarit sans grande case)",
                [],
                big[allowed:],
            )
        )
    return out


def _presence_issues(views: Sequence[PageView], charter: Charter) -> list[CharterIssue]:
    d = charter.dna.presence
    panels = [(v.number, i, pa) for v in views for i, pa in enumerate(v.panels, start=1)]
    total = len(panels)
    if not total:
        return []
    reaction = [(p, i) for p, i, pa in panels if viewpoint_key(pa.get("point_de_vue")) == REACTION]
    subjective = [(p, i) for p, i, pa in panels if _subjective(pa)]
    empty = [(p, i) for p, i, pa in panels if not pa.get("visible")]
    out: list[CharterIssue] = []
    for cases, r, label, fewer, more in (
        (
            subjective,
            d.subjective,
            "en vue subjective",
            "montre ce que voit le spectateur, à travers ses yeux (« vue subjective »)",
            "repasse des spectateurs en « plan de réaction » ou change d'angle",
        ),
        (
            empty,
            d.empty,
            "sans personnage à l'image",
            "montre ce qui est vu (vue subjective), le décor ou l'objet clé, sans personnage",
            "montre le spectateur (« plan de réaction ») plutôt que ce qu'il voit",
        ),
    ):
        need = _required(r.min, total)
        if len(cases) < need:
            targets = [c for c in reaction if c not in cases]
            out.append(
                CharterIssue(
                    f"{len(cases)} case{'s' if len(cases) > 1 else ''} {label} sur {total} (au moins "
                    f"{need}, {_pct(r.min)}) : {fewer}",
                    targets,
                    [],
                )
            )
        allowed = _allowed(r.max, total)
        if len(cases) > allowed:
            out.append(
                CharterIssue(
                    f"{len(cases)} cases {label} sur {total} ({allowed} au plus, {_pct(r.max)}) : {more}",
                    list(cases[allowed:]),
                    [],
                )
            )
    return out


def _cases(cases: Sequence[tuple[int, int]]) -> str:
    shown = ", ".join(f"page {p} case {c}" for p, c in cases[:6])
    return shown + (f" et {len(cases) - 6} autre(s)" if len(cases) > 6 else "")


def _place_issues(views: Sequence[PageView], charter: Charter) -> list[CharterIssue]:
    """Lieux : case d'établissement au changement de lieu (la première case d'un nouveau lieu de la série en plan
    large / d'ensemble) et part de cases de décor muettes. Le lieu d'une case est son unité de lieu (`location`,
    id d'un lieu de la série) : une case sans lieu ne compte ni comme changement ni comme continuité, et un chapitre
    dont aucune case n'est rattachée à un lieu (d'avant l'unité de lieu) n'est pas mesuré."""
    d = charter.dna.places
    s = charter.settings
    panels = [(v.number, i, pa) for v in views for i, pa in enumerate(v.panels, start=1)]
    out: list[CharterIssue] = []
    if not any(pa.get("location") is not None for _p, _i, pa in panels):
        return out
    if d.establishing:
        wide = {_key(p) for p in s.shot_classes["wide"]}
        missing: list[tuple[int, int]] = []
        names: list[str] = []
        previous: Any = None
        for number, i, pa in panels:
            loc = pa.get("location")
            if loc is None:
                continue
            if loc != previous and _key(pa.get("plan")) not in wide:
                missing.append((number, i))
                name = str(pa.get("location_name") or "")
                if name and name not in names:
                    names.append(name)
            previous = loc
        if missing:
            where = f" ({', '.join(f'« {n} »' for n in names[:4])})" if names else ""
            out.append(
                CharterIssue(
                    f"changement de lieu sans case d'établissement{where} : {_cases(missing)} : passe la première case "
                    f"du nouveau lieu en {' / '.join(s.shot_classes['wide'])} qui installe le lieu (le décor entier, "
                    "les personnages petits dans leur décor)",
                    missing,
                    [],
                )
            )
    total = len(panels)
    need = _required(d.silent_decor_min, total)
    silent = [(p, i) for p, i, pa in panels if not pa.get("visible") and not pa.get("replies")]
    if total and len(silent) < need:
        # Cases sans réplique : la direction artistique peut en montrer le lieu seul (vue subjective, les
        # personnages hors cadre) ; les premières cases d'un lieu d'abord.
        quiet = [(p, i) for p, i, pa in panels if not pa.get("replies") and (p, i) not in silent]
        out.append(
            CharterIssue(
                f"{len(silent)} case{'s' if len(silent) > 1 else ''} de décor muette{'s' if len(silent) > 1 else ''} "
                f"sur {total} (au moins {need}, {_pct(d.silent_decor_min)}) : montre le lieu seul, sans personnage ni "
                "réplique — une case sans réplique en vue subjective, les personnages hors cadre",
                quiet[: max(0, need - len(silent))],
                [],
            )
        )
    return out


def _rhythm_issues(views: Sequence[PageView], charter: Charter) -> list[CharterIssue]:
    d = charter.dna.rhythm
    s = charter.settings
    peaks_set = {_key(r) for r in s.peak_rythmes}
    breaths = {_key(r) for r in s.breath_rythmes}
    n = len(views)
    numbers = [v.number for v in views]
    is_peak = [_key(v.rythme) in peaks_set for v in views]
    peak_names = " / ".join(s.peak_rythmes)
    out: list[CharterIssue] = []
    # Premier pic : la page (sa part du chapitre, [i/n, (i+1)/n]) touche la fenêtre visée.
    window = [i for i in range(n) if i / n <= d.first_peak.max + EPS and (i + 1) / n >= d.first_peak.min - EPS]
    where = (
        f"entre {_pct(d.first_peak.min)} et {_pct(d.first_peak.max)} du chapitre "
        f"({_span([numbers[i] for i in window])})"
        if window
        else f"entre {_pct(d.first_peak.min)} et {_pct(d.first_peak.max)} du chapitre"
    )
    first = next((i for i in range(n) if is_peak[i]), None)
    if first is None:
        out.append(
            CharterIssue(
                f"courbe de rythme : aucun pic (« {peak_names} ») : place le premier {where}",
                [],
                [numbers[i] for i in window],
            )
        )
    elif first not in window:
        early = "trop tôt" if first < (window[0] if window else n) else "trop tard"
        out.append(
            CharterIssue(
                f"courbe de rythme : premier pic {early}, page {numbers[first]} ({_pct(first / n)} du chapitre) : "
                f"place-le {where}",
                [],
                list(dict.fromkeys([numbers[first], *(numbers[i] for i in window)])),
            )
        )
    for a, b in _runs(["p" if x else f"-{i}" for i, x in enumerate(is_peak)]):
        if not is_peak[a]:
            continue
        if b - a > d.max_peaks_in_a_row:
            out.append(
                CharterIssue(
                    f"courbe de rythme : {_span(numbers[a:b])} : {b - a} pics d'affilée ({d.max_peaks_in_a_row} au "
                    "plus) : quand tout est un sommet, plus rien ne l'est — passe-en en « montée »",
                    [],
                    numbers[a + d.max_peaks_in_a_row : b],
                )
            )
        if d.breath_after_peak and b < n and _key(views[b].rythme) not in breaths:
            out.append(
                CharterIssue(
                    f"courbe de rythme : page {numbers[b]} : pas de respiration après le pic de la page "
                    f"{numbers[b - 1]} (rythme « {' » ou « '.join(s.breath_rythmes)} » attendu)",
                    [],
                    [numbers[b]],
                )
            )
    last = d.final_peak_last_pages
    if last and not any(is_peak[max(0, n - last) :]):
        tail = numbers[max(0, n - last) :]
        out.append(
            CharterIssue(
                f"courbe de rythme : aucun pic dans les {last} dernière{'s' if last > 1 else ''} planche"
                f"{'s' if last > 1 else ''} ({_span(tail)}) : termine le chapitre sur un sommet",
                [],
                tail,
            )
        )
    return out


# --- prompts : $pre_direction ---------------------------------------------------------
NO_CHARTER = "(pas de charte pour cette série)"


def _range(r: ShareRange) -> str:
    if r.min <= EPS and r.max >= 1 - EPS:
        return "libre"
    if r.min <= EPS:
        return f"au plus {_pct(r.max)}"
    if r.max >= 1 - EPS:
        return f"au moins {_pct(r.min)}"
    return f"{_pct(r.min)} à {_pct(r.max)}"


def _rhythm_lines(charter: Charter, pages: int) -> list[str]:
    d = charter.dna.rhythm
    s = charter.settings
    peaks = " / ".join(s.peak_rythmes)
    lines = []
    window = ""
    if pages >= 1:
        hit = [
            i + 1
            for i in range(pages)
            if i / pages <= d.first_peak.max + EPS and (i + 1) / pages >= d.first_peak.min - EPS
        ]
        if hit:
            window = f" (pages {hit[0]} à {hit[-1]} sur {pages})" if len(hit) > 1 else f" (page {hit[0]} sur {pages})"
    lines.append(
        f"- courbe de rythme : premier pic (« {peaks} ») entre {_pct(d.first_peak.min)} et "
        f"{_pct(d.first_peak.max)} du chapitre{window} ;"
    )
    if d.breath_after_peak:
        lines.append(f"- une respiration (« {' » ou « '.join(s.breath_rythmes)} ») juste après chaque pic ;")
    lines.append(f"- jamais plus de {d.max_peaks_in_a_row} pic{'s' if d.max_peaks_in_a_row > 1 else ''} d'affilée ;")
    if d.final_peak_last_pages:
        n = d.final_peak_last_pages
        lines.append(f"- un pic final dans {'la dernière planche' if n == 1 else f'les {n} dernières planches'}.")
    else:
        lines.append("- fin libre : pas de pic final imposé.")
    return lines


def _place_lines(charter: Charter, *, writer: bool) -> list[str]:
    d = charter.dna.places
    wide = " / ".join(charter.settings.shot_classes["wide"])
    lines = []
    if d.establishing:
        lines.append(
            "- case d'établissement : à chaque changement de lieu, la première case du nouveau lieu l'installe"
            + (
                " (le lieu entier, les personnages petits dans leur décor ; garde-la sans dialogue si possible) ;"
                if writer
                else f" en {wide} ;"
            )
        )
    if d.silent_decor_min > EPS:
        lines.append(
            f"- cases de décor muettes (le lieu seul, sans personnage à l'image ni réplique) : au moins "
            f"{_pct(d.silent_decor_min)} des cases du chapitre ;"
        )
    return lines


def script_text(charter: Charter | None, target_pages: int = 0) -> str:
    """Charte de la série pour le scénariste : cases par planche, dialogue, courbe de rythme."""
    if charter is None:
        return NO_CHARTER
    p = charter.dna.panels
    d = charter.dna.dialogue
    silent = (
        f", et au moins {d.min_silent_panels} case{'s' if d.min_silent_panels > 1 else ''} sans aucune réplique par "
        "planche (le silence d'une réaction, d'un décor, d'un regard)"
        if d.min_silent_panels
        else ""
    )
    lines = [
        f"- {p.min_per_page} à {p.max_per_page} cases par planche (une pleine page d'une seule case reste possible "
        "pour un vrai sommet) ;",
        f"- dialogue compté par planche : {d.min_per_page} à {d.max_per_page} répliques (onomatopées à part){silent} ;",
        *_rhythm_lines(charter, target_pages),
    ]
    lines.append(
        "  (le directeur artistique fixe le rythme de chaque page : écris l'histoire pour que cette courbe tombe juste)"
    )
    lines += _place_lines(charter, writer=True)
    return "\n".join(lines)


def art_text(charter: Charter | None, pages: int = 0) -> str:
    """Charte de la série pour le directeur artistique : échelle des plans, présence, formes de planche, rythme."""
    if charter is None:
        return NO_CHARTER
    s = charter.settings
    shots = charter.dna.shots
    sh = charter.dna.shapes
    pr = charter.dna.presence
    parts = [
        f"{' / '.join(s.shot_classes[c])} {_range(getattr(shots, c))}"
        for c in SHOT_CLASSES
        if _range(getattr(shots, c)) != "libre"
    ]
    tight = ", ".join(p for c in TIGHT_CLASSES for p in s.shot_classes[c])
    lines = [
        f"- échelle des plans (part des cases du chapitre) : {' ; '.join(parts)} ;",
        f"- plans serrés ({tight}) : {_pct(shots.tight_max)} au plus — au-delà, élargis ; sous le plancher de plans "
        "larges, élargis aussi ;",
        f"- présence : vue subjective {_range(pr.subjective)} des cases ; cases sans personnage à l'image "
        f"{_range(pr.empty)} ;",
        f"- formes de planche : {_range(sh.big_panel_share)} des planches avec une grande case ; jamais plus de "
        f"{sh.max_same_in_a_row} planche{'s' if sh.max_same_in_a_row > 1 else ''} de même forme d'affilée, une même "
        f"forme sur {_pct(sh.max_same_share)} des planches au plus (forme : page choc, gabarit, ou nombre de cases et "
        "de grandes cases) — varie « template » et « page_choc » ;",
        *_rhythm_lines(charter, pages),
        *_place_lines(charter, writer=False),
    ]
    return "\n".join(lines)


# --- écran « ADN de la série » ---------------------------------------------------------
def field_specs() -> list[dict[str, Any]]:
    """Valeurs réglables, dans l'ordre du schéma : chemin, famille, libellé, type et bornes."""
    out = []
    for path, info in LEAVES.items():
        kind = _kind(path)
        low = high = None
        for m in info.metadata:
            low = getattr(m, "ge", low)
            high = getattr(m, "le", high)
        if kind == "share":
            low, high = 0.0 if low is None else low, 1.0 if high is None else high
        label, help_text = LABELS.get(path, (path, ""))
        out.append(
            {
                "path": path,
                "group": path.split(".", 1)[0],
                "label": label,
                "help": help_text,
                "kind": kind,
                "min": low,
                "max": high,
                "step": 0.05 if kind == "share" else 1 if kind == "int" else None,
            }
        )
    return out
