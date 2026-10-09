"""Étape 2 — découpage déterministe d'une page en cases.

Entrées : format de page (mm, DPI, marges, gouttières), gabarit (arbre de découpes « guillotine »,
cf. presets/layouts/), sens de lecture, numéro de page et, pour chaque case, son importance et la
longueur de ses dialogues. Sortie : un JSON stocké sur la page (`Page.layout`) :

- `panels` : coordonnées (x1, y1, x2, y2) en px de la page, ratio, taille cible de génération,
  zone réservée aux bulles et numéro d'ordre de lecture ;
- `gutters` : gouttières déplaçables (chemin dans l'arbre, position, bornes) ;
- `tree` : l'arbre avec ses poids courants, pour rejouer ou déplacer une gouttière.

Les calculs se font dans « l'espace de lecture » (colonnes de gauche à droite), puis la page est
mise en miroir dans la zone utile si la lecture se fait de droite à gauche (manga).
Les coordonnées sont des entiers ; x2/y2 sont exclusifs (largeur = x2 − x1).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from ..presets.schemas import LayoutSettings, LayoutTemplate, PageFormat, SplitNode, TreeNode, count_panels

Direction = Literal["ltr", "rtl"]
TREE = TypeAdapter(TreeNode)
LAYOUT_VERSION = 1


class LayoutError(ValueError):
    """Découpage impossible (message lisible)."""


@dataclass(frozen=True)
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def w(self) -> int:
        return self.x2 - self.x1

    @property
    def h(self) -> int:
        return self.y2 - self.y1

    def as_dict(self) -> dict[str, int]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    def mirror(self, left: int, right: int) -> Rect:
        return Rect(left + right - self.x2, self.y1, left + right - self.x1, self.y2)


@dataclass(frozen=True)
class PanelSpec:
    """Ce dont le découpage a besoin pour une case."""

    importance: int = 2
    dialogue_chars: int = 0
    panel_id: int | None = None


# --- arbre ----------------------------------------------------------------------
def tree_to_json(node: TreeNode) -> Any:
    if node == "panel":
        return "panel"
    assert isinstance(node, SplitNode)
    return {node.axis: list(node.sizes), "children": [tree_to_json(c) for c in node.nodes]}


def tree_from_json(data: Any) -> TreeNode:
    try:
        return TREE.validate_python(data)
    except ValidationError as exc:
        raise LayoutError("arbre de mise en page invalide") from exc


def auto_tree(n: int) -> TreeNode:
    """Grille de bandes de 3 cases (2 + 2 en fin de page plutôt qu'une case isolée)."""
    if n <= 1:
        return "panel"
    rows: list[int] = []
    left = n
    while left > 0:
        if left == 4:
            rows += [2, 2]
            break
        take = min(3, left)
        rows.append(take)
        left -= take
    if len(rows) == 1:
        return SplitNode(cols=[1.0] * rows[0])
    children: list[TreeNode] = ["panel" if k == 1 else SplitNode(cols=[1.0] * k) for k in rows]
    return SplitNode(rows=[1.0] * len(rows), children=children)


def _leaf_shares(node: TreeNode, share: float = 1.0) -> list[float]:
    """Part approximative de la surface de chaque case (gouttières ignorées), dans l'ordre de lecture."""
    if node == "panel":
        return [share]
    assert isinstance(node, SplitNode)
    total = sum(node.sizes)
    out: list[float] = []
    for size, child in zip(node.sizes, node.nodes, strict=True):
        out += _leaf_shares(child, share * size / total)
    return out


def template_score(tree: TreeNode, importances: Sequence[int]) -> float:
    """Écart (plus petit = mieux) entre répartition des surfaces et répartition de l'importance."""
    shares = _leaf_shares(tree)
    total = sum(max(1, i) for i in importances)
    return sum((a - max(1, i) / total) ** 2 for a, i in zip(shares, importances, strict=True))


def choose_template(templates: Sequence[LayoutTemplate], importances: Sequence[int]) -> tuple[str, TreeNode]:
    """Gabarit au bon nombre de cases dont les surfaces suivent le mieux l'importance des cases."""
    n = len(importances)
    if n == 0:
        raise LayoutError("page sans case : rien à découper")
    best: tuple[float, LayoutTemplate] | None = None
    for tpl in templates:
        if tpl.panel_count != n:
            continue
        score = template_score(tpl.tree, importances)
        if best is None or score < best[0] - 1e-9:
            best = (score, tpl)
    if best is None:
        return f"auto-{n}", auto_tree(n)
    return best[1].id, best[1].tree


# --- géométrie ------------------------------------------------------------------
@dataclass(frozen=True)
class Frame:
    """Géométrie de la page en px."""

    width: int
    height: int
    live: Rect
    gutter_h: int  # entre deux bandes (empilées verticalement)
    gutter_v: int  # entre deux cases côte à côte
    min_panel: int
    inner_side: Literal["left", "right"]


def page_frame(fmt: PageFormat, settings: LayoutSettings, *, direction: Direction, page_number: int) -> Frame:
    """Zone utile = page − marges. La reliure (marge intérieure) est à gauche des pages de droite.

    En ltr la page 1 est une page de droite (reliure à gauche) ; en rtl (manga) la page 1 est une
    page de gauche (reliure à droite). Les pages paires alternent.
    """
    m = fmt.margins_mm
    odd = page_number % 2 == 1
    inner_left = odd == (direction == "ltr")
    left_mm, right_mm = (m.inner, m.outer) if inner_left else (m.outer, m.inner)
    width, height = fmt.width_px, fmt.height_px
    live = Rect(
        fmt.mm_to_px(left_mm),
        fmt.mm_to_px(m.top),
        width - fmt.mm_to_px(right_mm),
        height - fmt.mm_to_px(m.bottom),
    )
    return Frame(
        width=width,
        height=height,
        live=live,
        gutter_h=fmt.mm_to_px(fmt.gutters_mm.horizontal),
        gutter_v=fmt.mm_to_px(fmt.gutters_mm.vertical),
        min_panel=max(1, fmt.mm_to_px(settings.min_panel_mm)),
        inner_side="left" if inner_left else "right",
    )


def _gutter(frame: Frame, axis: str) -> int:
    return frame.gutter_h if axis == "rows" else frame.gutter_v


def _min_extent(node: TreeNode, axis: str, frame: Frame) -> int:
    """Longueur minimale d'un nœud le long de `axis` ("rows" = vertical, "cols" = horizontal)."""
    if node == "panel":
        return frame.min_panel
    assert isinstance(node, SplitNode)
    mins = [_min_extent(c, axis, frame) for c in node.nodes]
    if node.axis == axis:
        return sum(mins) + _gutter(frame, axis) * (len(mins) - 1)
    return max(mins)


def _spans(start: int, length: int, sizes: Sequence[float], gutter: int) -> list[tuple[int, int]]:
    """Découpe [start, start+length) en segments proportionnels séparés de gouttières exactes."""
    n = len(sizes)
    avail = length - gutter * (n - 1)
    if avail < n:
        raise LayoutError("zone trop petite pour ce gabarit (marges ou gouttières trop grandes)")
    total = float(sum(sizes))
    cum = [0.0]
    for s in sizes:
        cum.append(cum[-1] + s)
    edges = [round(c / total * avail) for c in cum]
    return [(start + edges[i] + i * gutter, start + edges[i + 1] + i * gutter) for i in range(n)]


@dataclass
class _Gutter:
    path: list[int]
    index: int
    axis: str
    rect: Rect  # espace de lecture
    lo: float  # bornes de la position (centre de la gouttière), espace de lecture
    hi: float
    center: float


def _place(
    node: TreeNode, rect: Rect, frame: Frame, path: list[int], leaves: list[Rect], gutters: list[_Gutter]
) -> None:
    if node == "panel":
        leaves.append(rect)
        return
    assert isinstance(node, SplitNode)
    axis = node.axis
    g = _gutter(frame, axis)
    start, length = (rect.y1, rect.h) if axis == "rows" else (rect.x1, rect.w)
    spans = _spans(start, length, node.sizes, g)
    children = node.nodes
    for i, (a, b) in enumerate(spans):
        child = Rect(rect.x1, a, rect.x2, b) if axis == "rows" else Rect(a, rect.y1, b, rect.y2)
        if i > 0:
            pa, pb = spans[i - 1]
            gap = Rect(rect.x1, pb, rect.x2, a) if axis == "rows" else Rect(pb, rect.y1, a, rect.y2)
            lo = pa + _min_extent(children[i - 1], axis, frame) + g / 2
            hi = b - _min_extent(children[i], axis, frame) - g / 2
            gutters.append(
                _Gutter(path=path, index=i - 1, axis=axis, rect=gap, lo=lo, hi=max(lo, hi), center=pb + g / 2)
            )
        _place(children[i], child, frame, [*path, i], leaves, gutters)


def target_size(width: int, height: int, settings: LayoutSettings) -> dict[str, int]:
    """Taille de génération : même ratio que la case, ≈ N mégapixels, multiples de `multiple`."""
    gen = settings.generation
    ratio = width / height
    pixels = gen.megapixels * 1_000_000
    m = gen.multiple
    floor = math.ceil(gen.min_side / m) * m

    def snap(v: float) -> int:
        return max(floor, round(v / m) * m)

    return {"width": snap(math.sqrt(pixels * ratio)), "height": snap(math.sqrt(pixels / ratio))}


def bubble_zone(
    panel: Rect, chars: int, direction: Direction, fmt: PageFormat, settings: LayoutSettings
) -> Rect | None:
    """Zone réservée aux bulles, en haut de la case, du côté où commence la lecture."""
    if chars <= 0:
        return None
    bz = settings.bubble_zone
    pad = fmt.mm_to_px(bz.padding_mm)
    inner_w, inner_h = panel.w - 2 * pad, panel.h - 2 * pad
    if inner_w < 2 or inner_h < 2:
        pad, inner_w, inner_h = 0, panel.w, panel.h
    fraction = bz.min_fraction + (bz.max_fraction - bz.min_fraction) * min(1.0, chars / bz.full_at_chars)
    area = fraction * panel.w * panel.h
    zw = inner_w * bz.width_fraction
    zh = area / zw
    max_h = inner_h * bz.max_height_fraction
    if zh > max_h:
        zh = max_h
        zw = min(inner_w, area / zh)
    zw_i = max(1, min(inner_w, round(zw)))
    zh_i = max(1, min(inner_h, round(zh)))
    y1 = panel.y1 + pad
    if direction == "ltr":
        x1 = panel.x1 + pad
        return Rect(x1, y1, x1 + zw_i, y1 + zh_i)
    x2 = panel.x2 - pad
    return Rect(x2 - zw_i, y1, x2, y1 + zh_i)


def compute_layout(
    fmt: PageFormat,
    settings: LayoutSettings,
    tree: TreeNode,
    panels: Sequence[PanelSpec],
    *,
    direction: Direction,
    page_number: int,
    template_id: str,
) -> dict[str, Any]:
    if count_panels(tree) != len(panels):
        raise LayoutError(f"le gabarit « {template_id} » a {count_panels(tree)} cases, la page en a {len(panels)}")
    frame = page_frame(fmt, settings, direction=direction, page_number=page_number)
    leaves: list[Rect] = []
    gutters: list[_Gutter] = []
    _place(tree, frame.live, frame, [], leaves, gutters)

    L, R = frame.live.x1, frame.live.x2

    def out(r: Rect) -> Rect:
        return r.mirror(L, R) if direction == "rtl" else r

    panels_out: list[dict[str, Any]] = []
    for i, (leaf, spec) in enumerate(zip(leaves, panels, strict=True)):
        rect = out(leaf)
        zone = bubble_zone(rect, spec.dialogue_chars, direction, fmt, settings)
        panels_out.append(
            {
                "index": i,
                "reading_order": i + 1,
                "panel_id": spec.panel_id,
                **rect.as_dict(),
                "width": rect.w,
                "height": rect.h,
                "ratio": round(rect.w / rect.h, 4),
                "target": target_size(rect.w, rect.h, settings),
                "bubble_zone": zone.as_dict() if zone else None,
            }
        )

    gutters_out: list[dict[str, Any]] = []
    for g in gutters:
        rect = out(g.rect)
        if g.axis == "cols" and direction == "rtl":
            lo, hi, center = L + R - g.hi, L + R - g.lo, L + R - g.center
        else:
            lo, hi, center = g.lo, g.hi, g.center
        gutters_out.append(
            {
                "path": g.path,
                "index": g.index,
                # Une gouttière entre deux bandes est une ligne horizontale qu'on déplace en y.
                "orientation": "horizontal" if g.axis == "rows" else "vertical",
                **rect.as_dict(),
                "position": center,
                "min": lo,
                "max": hi,
            }
        )

    return {
        "version": LAYOUT_VERSION,
        "template_id": template_id,
        "page_format": fmt.id,
        "dpi": fmt.dpi,
        "direction": direction,
        "page_number": page_number,
        "page": {"width": frame.width, "height": frame.height},
        "live_area": frame.live.as_dict(),
        "inner_side": frame.inner_side,
        "gutters_px": {"horizontal": frame.gutter_h, "vertical": frame.gutter_v},
        "tree": tree_to_json(tree),
        "panels": panels_out,
        "gutters": gutters_out,
    }


def _node_at(tree: TreeNode, path: Sequence[int]) -> SplitNode:
    node = tree
    for i in path:
        if not isinstance(node, SplitNode) or not 0 <= i < len(node.sizes):
            raise LayoutError("gouttière introuvable")
        node = node.nodes[i]
    if not isinstance(node, SplitNode):
        raise LayoutError("gouttière introuvable")
    return node


def _replace_at(tree: TreeNode, path: Sequence[int], new: SplitNode) -> TreeNode:
    if not path:
        return new
    assert isinstance(tree, SplitNode)
    children = tree.nodes
    children[path[0]] = _replace_at(children[path[0]], path[1:], new)
    return SplitNode(**{tree.axis: tree.sizes}, children=children)


def move_gutter(
    fmt: PageFormat,
    settings: LayoutSettings,
    layout: dict[str, Any],
    panels: Sequence[PanelSpec],
    *,
    path: Sequence[int],
    index: int,
    position: float,
) -> dict[str, Any]:
    """Déplace une gouttière (centre en px de la page) : seules ses deux cases voisines changent.

    La position est bornée pour que chaque voisine (et ses sous-cases) garde la taille minimale.
    """
    tree = tree_from_json(layout["tree"])
    direction: Direction = layout["direction"]
    page_number = int(layout["page_number"])
    node = _node_at(tree, path)
    if not 0 <= index < len(node.sizes) - 1:
        raise LayoutError("gouttière introuvable")
    match = next((g for g in layout.get("gutters", []) if list(g["path"]) == list(path) and g["index"] == index), None)
    if match is None:
        raise LayoutError("gouttière introuvable")

    frame = page_frame(fmt, settings, direction=direction, page_number=page_number)
    L, R = frame.live.x1, frame.live.x2
    pos = min(max(position, match["min"]), match["max"])
    if node.axis == "cols" and direction == "rtl":
        pos = L + R - pos  # retour dans l'espace de lecture

    # Étendue du nœud le long de son axe, recalculée depuis la géométrie actuelle.
    g = _gutter(frame, node.axis)
    span_rect = _node_rect(tree, path, frame)
    start, length = (span_rect.y1, span_rect.h) if node.axis == "rows" else (span_rect.x1, span_rect.w)
    spans = _spans(start, length, node.sizes, g)
    a = spans[index][0]
    b = spans[index + 1][1]
    avail = length - g * (len(node.sizes) - 1)
    first = pos - g / 2 - a
    second = b - (pos + g / 2)
    total = sum(node.sizes)
    sizes = list(node.sizes)
    sizes[index] = max(first, 1e-6) / avail * total
    sizes[index + 1] = max(second, 1e-6) / avail * total
    new_tree = _replace_at(tree, path, SplitNode(**{node.axis: sizes}, children=node.nodes))
    return compute_layout(
        fmt,
        settings,
        new_tree,
        panels,
        direction=direction,
        page_number=page_number,
        template_id=layout["template_id"],
    )


def _node_rect(tree: TreeNode, path: Sequence[int], frame: Frame) -> Rect:
    rect = frame.live
    node = tree
    for i in path:
        assert isinstance(node, SplitNode)
        g = _gutter(frame, node.axis)
        start, length = (rect.y1, rect.h) if node.axis == "rows" else (rect.x1, rect.w)
        a, b = _spans(start, length, node.sizes, g)[i]
        rect = Rect(rect.x1, a, rect.x2, b) if node.axis == "rows" else Rect(a, rect.y1, b, rect.y2)
        node = node.nodes[i]
    return rect
