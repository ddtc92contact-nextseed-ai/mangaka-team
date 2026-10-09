"""Grammaire de mise en page par série : du style (presets/layout_styles/) à l'arbre de découpes d'une page.

Tout est déterministe pour une graine donnée (`random.Random(seed)`), et toutes les valeurs de style
— probabilités et angles des biais, gouttières, poids des gabarits, contraste des tailles — viennent
du preset. Étapes, pour une page :

1. poids de chaque case = (importance × poids de son intensité) ^ (contraste du style × contraste du rythme) ;
2. gabarit : parmi ceux qui ont le bon nombre de cases, le mieux adapté à ces poids (température 0)
   ou un tirage pondéré par l'adéquation et le poids du gabarit dans le style ; jamais le gabarit de
   la page précédente si le style l'interdit et qu'il existe une autre possibilité ;
3. variation éventuelle des proportions (`size_jitter`) ;
4. gouttières tirées dans les plages du style (sinon celles du format) ;
5. biais : chaque découpe, dans l'ordre de lecture, passe en biais avec la probabilité de la case
   voisine la plus « forte » (son intensité si le scénario l'a donnée, sinon son importance) × le
   facteur du rythme de la page ; l'angle est tiré dans la plage du style, puis réduit si une case
   voisine passerait sous la taille minimale.

Un assistant de direction artistique (le LLM du scénario aujourd'hui) ne pilote la mise en page que
par les champs structurés `importance`, `intensity` (case) et `rythme` (page), et par le choix du
style : jamais en dessinant les cases.
"""

from __future__ import annotations

import fnmatch
import math
import random
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..presets.schemas import LayoutSettings, LayoutStyle, LayoutTemplate, PageFormat, SlantRule, SplitNode, TreeNode
from .layout import (
    Direction,
    LayoutError,
    PanelSpec,
    _geometry,
    _node_at,
    _replace_at,
    auto_tree,
    compute_layout,
    page_frame,
    template_score,
)


@dataclass(frozen=True)
class PagePlan:
    template_id: str
    tree: TreeNode
    style: dict[str, Any]  # id, graine, rythme, gouttières (stocké dans le JSON de la mise en page)


def default_seed(*parts: object) -> int:
    """Graine stable d'une page (ex. chapitre + numéro) : même page, même mise en page."""
    return zlib.crc32(":".join(str(p) for p in parts).encode("utf-8")) & 0x7FFFFFFF


def template_weight(style: LayoutStyle, template_id: str) -> float:
    if template_id in style.template_weights:
        return style.template_weights[template_id]
    for pattern, weight in style.template_weights.items():
        if fnmatch.fnmatchcase(template_id, pattern):
            return weight
    return style.default_template_weight


def panel_weights(style: LayoutStyle, specs: Sequence[PanelSpec], rythme: str | None) -> list[float]:
    contrast = style.size_contrast * style.rythme[_rythme(rythme)].size_contrast
    return [(max(1, s.importance) * style.intensity_weight[_intensity(s.intensity)]) ** contrast for s in specs]


def _rythme(value: str | None) -> str:
    return value if value in ("lent", "normal", "rapide") else "normal"


def _intensity(value: str | None) -> str:
    return value if value in ("calme", "normal", "choc") else "normal"


def slant_rule(style: LayoutStyle, spec: PanelSpec) -> SlantRule:
    if spec.intensity in style.slants.by_intensity:
        return style.slants.by_intensity[spec.intensity]  # type: ignore[index]
    return style.slants.by_importance[min(3, max(1, spec.importance))]  # type: ignore[index]


def choose_styled_template(
    style: LayoutStyle,
    templates: Sequence[LayoutTemplate],
    weights: Sequence[float],
    rng: random.Random,
    *,
    exclude: set[str],
) -> tuple[str, TreeNode]:
    n = len(weights)
    if n == 0:
        raise LayoutError("page sans case : rien à découper")
    cands = [
        (template_score(t.tree, weights), template_weight(style, t.id), order, t)
        for order, t in enumerate(templates)
        if t.panel_count == n and template_weight(style, t.id) > 0
    ]
    auto_id = f"auto-{n}"
    if not cands:
        return auto_id, auto_tree(n)
    allowed = [c for c in cands if c[3].id not in exclude]
    if not allowed:
        # Seul gabarit possible et déjà utilisé : la grille générée fait une page différente.
        if n > 1 and auto_id not in exclude:
            return auto_id, auto_tree(n)
        allowed = cands
    if style.temperature <= 0:
        best = min(allowed, key=lambda c: (round(c[0], 9), -c[1], c[2]))
        return best[3].id, best[3].tree
    s_min = min(c[0] for c in allowed)
    probs = [c[1] * math.exp(-(c[0] - s_min) / style.temperature) for c in allowed]
    pick = rng.random() * sum(probs)
    for c, p in zip(allowed, probs, strict=True):
        pick -= p
        if pick <= 0:
            return c[3].id, c[3].tree
    return allowed[-1][3].id, allowed[-1][3].tree


def _jitter(node: TreeNode, amount: float, rng: random.Random) -> TreeNode:
    if node == "panel" or amount <= 0:
        return node
    assert isinstance(node, SplitNode)
    sizes = [s * (1 + rng.uniform(-amount, amount)) for s in node.sizes]
    children = [_jitter(c, amount, rng) for c in node.nodes]
    return SplitNode(**{node.axis: sizes}, children=children, slants=node.slants)


def _draw_gutters(style: LayoutStyle, rng: random.Random) -> dict[str, float] | None:
    if style.gutters_mm is None:
        return None

    def pick(r: Any) -> float:
        return round(rng.uniform(r.min, r.max) * 2) / 2

    return {"horizontal": pick(style.gutters_mm.horizontal), "vertical": pick(style.gutters_mm.vertical)}


def plan_page(
    fmt: PageFormat,
    settings: LayoutSettings,
    style: LayoutStyle,
    templates: Sequence[LayoutTemplate],
    specs: Sequence[PanelSpec],
    *,
    direction: Direction,
    page_number: int,
    seed: int,
    rythme: str | None = None,
    forced: tuple[str, TreeNode] | None = None,
    exclude: Sequence[str] = (),
) -> PagePlan:
    """Arbre de découpes (gabarit, proportions, biais) et gouttières d'une page, pour ce style et cette graine."""
    rng = random.Random(seed)
    weights = panel_weights(style, specs, rythme)
    if forced is not None:
        template_id, tree = forced
    else:
        template_id, tree = choose_styled_template(style, templates, weights, rng, exclude=set(exclude))
    tree = _jitter(tree, style.size_jitter, rng)
    gutters = _draw_gutters(style, rng)
    frame = page_frame(fmt, settings, direction=direction, page_number=page_number, gutters_mm=gutters)
    factor = style.rythme[_rythme(rythme)].slant_factor

    if isinstance(tree, SplitNode):
        _, cuts = _geometry(tree, frame)
        for ref in [(c.path, c.index) for c in cuts]:
            # Géométrie recalculée après chaque biais : les bornes tiennent compte des voisines.
            _, current = _geometry(tree, frame)
            cut = next(c for c in current if (c.path, c.index) == ref)
            neighbours = [specs[i] for i in cut.before + cut.after]
            rule = max((slant_rule(style, s) for s in neighbours), key=lambda r: r.probability)
            # Trois tirages par découpe, toujours : la suite aléatoire ne dépend pas des décisions.
            u, t, sign = rng.random(), rng.random(), rng.choice((-1.0, 1.0))
            angles = rule.rows_deg if cut.axis == "rows" else rule.cols_deg
            angle = angles.min + (angles.max - angles.min) * t
            if u >= min(1.0, rule.probability * factor) or angle <= 0:
                continue
            half = math.tan(math.radians(angle)) * cut.length / 2
            # Extrémité 0 décalée de −sign·half, extrémité 1 de +sign·half : bornées par les tailles minimales.
            for j, o in enumerate((-sign, sign)):
                room = cut.end_hi[j] - cut.center if o > 0 else cut.center - cut.end_lo[j]
                half = min(half, max(0.0, room))
            if half < 0.5:
                continue
            node = _node_at(tree, cut.path)
            slants = node.cut_slants
            s = round(sign * half / frame.px_per_mm, 2)
            slants[cut.index] = (-s, s)
            tree = _replace_at(tree, cut.path, SplitNode(**{node.axis: node.sizes}, children=node.nodes, slants=slants))

    return PagePlan(
        template_id=template_id,
        tree=tree,
        style={"id": style.id, "seed": seed, "rythme": rythme, "gutters_mm": gutters},
    )


def styled_layout(
    fmt: PageFormat,
    settings: LayoutSettings,
    style: LayoutStyle,
    templates: Sequence[LayoutTemplate],
    specs: Sequence[PanelSpec],
    *,
    direction: Direction,
    page_number: int,
    seed: int,
    rythme: str | None = None,
    forced: tuple[str, TreeNode] | None = None,
    exclude: Sequence[str] = (),
) -> dict[str, Any]:
    plan = plan_page(
        fmt,
        settings,
        style,
        templates,
        specs,
        direction=direction,
        page_number=page_number,
        seed=seed,
        rythme=rythme,
        forced=forced,
        exclude=exclude,
    )
    return compute_layout(
        fmt,
        settings,
        plan.tree,
        specs,
        direction=direction,
        page_number=page_number,
        template_id=plan.template_id,
        style=plan.style,
    )
