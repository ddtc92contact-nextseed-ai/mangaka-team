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
   voisine passerait sous la taille minimale ;
6. options de cadre (`frames` du style, même règle intensité / importance) : case sans bord (bord
   franc ou fondu), à fond perdu, incrustée dans sa voisine. Elles sont tirées **avant** le gabarit
   (une incrustation ne prend pas de case dans l'arbre), par un générateur à part (`cadres:<graine>`) :
   les tirages des étapes 1–5 ne changent pas. Une option imposée dans l'UI (`PanelSpec.frame`)
   remplace le tirage.

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

from ..presets.schemas import (
    FrameRule,
    InsetRule,
    LayoutSettings,
    LayoutStyle,
    LayoutTemplate,
    PageFormat,
    SlantRule,
    SplitNode,
    TreeNode,
)
from .layout import (
    FRAME_KINDS,
    Direction,
    LayoutError,
    PanelSpec,
    _geometry,
    _node_at,
    _replace_at,
    auto_tree,
    compute_layout,
    count_panels,
    page_frame,
    template_score,
)


@dataclass(frozen=True)
class PagePlan:
    template_id: str
    tree: TreeNode
    style: dict[str, Any]  # id, graine, rythme, gouttières (stocké dans le JSON de la mise en page)
    frames: list[dict[str, Any]] | None = None  # options de cadre de chaque case


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


def frame_rule(style: LayoutStyle, spec: PanelSpec) -> FrameRule:
    table = style.frames
    if spec.intensity in table.by_intensity:
        return table.by_intensity[spec.intensity]  # type: ignore[index]
    return table.by_importance[min(3, max(1, spec.importance))]  # type: ignore[index]


def _override(spec: PanelSpec, key: str) -> Any:
    return (spec.frame or {}).get(key)


NO_FRAMES = FrameRule(frameless=0, bleed=0, inset=0)


def decide_frames(
    style: LayoutStyle | None,
    specs: Sequence[PanelSpec],
    seed: int,
    *,
    allow_insets: bool = True,
    inset_rule: InsetRule | None = None,
) -> list[dict[str, Any]]:
    """Options de cadre de chaque case : imposées dans l'UI, sinon tirées selon le style (aucune sans style).

    Quatre tirages par case, toujours (incrustation, sans bord, fondu, fond perdu) : la suite aléatoire
    ne dépend pas des décisions. Une incrustation demande une case hôte voisine non incrustée (la
    précédente, sinon la suivante), une seule incrustation par hôte, et au moins une case dans l'arbre ;
    les incrustations tirées respectent `max_per_page`, `min_page_panels` et `shot_types` du style.
    Sans style, seules les options imposées comptent (géométrie d'incrustation : `inset_rule`).
    """
    rng = random.Random(f"cadres:{seed}")
    draws = [(rng.random(), rng.random(), rng.random(), rng.random()) for _ in specs]
    rule_in = style.frames.inset if style else inset_rule
    if rule_in is None:
        allow_insets = False
    shots = {s.casefold() for s in (rule_in.shot_types if rule_in else [])}
    n = len(specs)
    out: list[dict[str, Any]] = []
    for spec, (u_inset, u_frame, u_fade, u_bleed) in zip(specs, draws, strict=True):
        rule = frame_rule(style, spec) if style else NO_FRAMES
        kind = _override(spec, "frame")
        if kind not in FRAME_KINDS:
            kind = "border"
            if u_frame < rule.frameless:
                kind = "fade" if style and u_fade < style.frames.fade else "none"
        bleed = _override(spec, "bleed")
        if not isinstance(bleed, bool):
            bleed = u_bleed < rule.bleed
        inset = _override(spec, "inset")
        forced = isinstance(inset, bool)
        if not forced:
            eligible = (
                rule_in is not None
                and n >= rule_in.min_page_panels
                and (not shots or (spec.shot_type or "").casefold() in shots)
            )
            inset = eligible and u_inset < rule.inset
        out.append({"frame": kind, "bleed": bleed, "inset": bool(inset and allow_insets), "forced": forced})

    hosts_used: set[int] = set()
    drawn = 0
    for i, f in enumerate(out):
        if not f["inset"]:
            continue
        assert rule_in is not None
        if not f["forced"] and drawn >= rule_in.max_per_page:
            f["inset"] = False
            continue
        host = next(
            (h for h in (i - 1, i + 1) if 0 <= h < n and h not in hosts_used and not out[h]["inset"]),
            None,
        )
        if host is None:
            f["inset"] = False
            continue
        hosts_used.add(host)
        if not f["forced"]:
            drawn += 1
        f.update(
            host=host,
            bleed=False,
            size=rule_in.size,
            margin_mm=rule_in.margin_mm,
            min_side_mm=rule_in.min_side_mm,
        )
        if _override(specs[i], "frame") not in FRAME_KINDS:
            f["frame"] = "border"  # liseré blanc + bordure : l'incrustation se détache de l'hôte
    for f in out:
        f.pop("forced", None)
    return out


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
    frames = decide_frames(style, specs, seed)
    if forced is not None and count_panels(forced[1]) == len(specs):
        frames = decide_frames(style, specs, seed, allow_insets=False)  # gabarit imposé sans incrustation
    tree_specs = [s for s, f in zip(specs, frames, strict=True) if not f["inset"]]
    weights = panel_weights(style, tree_specs, rythme)
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
            neighbours = [tree_specs[i] for i in cut.before + cut.after]
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
        frames=frames,
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
        frames=plan.frames,
    )
