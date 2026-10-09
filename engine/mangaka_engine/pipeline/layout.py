"""Étape 2 — découpage déterministe d'une page en cases.

Entrées : format de page (mm, DPI, marges, gouttières), gabarit (arbre de découpes « guillotine »,
cf. presets/layouts/), sens de lecture, numéro de page et, pour chaque case, son importance et la
longueur de ses dialogues. Sortie : un JSON stocké sur la page (`Page.layout`) :

- `panels` : polygone convexe de la case (`polygon`, px de la page), sa boîte englobante
  (x1, y1, x2, y2), ratio et taille cible de génération (ceux de la boîte englobante), zone réservée
  aux bulles (toujours dans le polygone) et numéro d'ordre de lecture ;
- `gutters` : découpes déplaçables (chemin dans l'arbre, position, bornes) et inclinables
  (extrémités `line`, positions `ends` et leurs bornes) ;
- `tree` : l'arbre avec ses poids et biais courants, pour rejouer ou modifier une découpe.

Une découpe peut être en biais (`slants` d'un nœud, cf. presets/schemas.py) : la gouttière garde
alors une largeur constante, mesurée perpendiculairement à la découpe. Sans biais, chaque case est
exactement le rectangle d'avant (mêmes coordonnées entières).

Les calculs se font dans « l'espace de lecture » (colonnes de gauche à droite), puis la page est
mise en miroir dans la zone utile si la lecture se fait de droite à gauche (manga).
Les boîtes sont entières ; x2/y2 sont exclusifs (largeur = x2 − x1).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from ..presets.schemas import LayoutSettings, LayoutTemplate, PageFormat, SplitNode, TreeNode, count_panels
from . import geometry as geo

Direction = Literal["ltr", "rtl"]
TREE = TypeAdapter(TreeNode)
LAYOUT_VERSION = 2


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

    def polygon(self) -> geo.Polygon:
        return geo.rect_polygon(self.x1, self.y1, self.x2, self.y2)


def bounding_rect(poly: Sequence[geo.Point]) -> Rect:
    x1, y1, x2, y2 = geo.bbox(poly)
    return Rect(math.floor(x1 + 1e-6), math.floor(y1 + 1e-6), math.ceil(x2 - 1e-6), math.ceil(y2 - 1e-6))


@dataclass(frozen=True)
class PanelSpec:
    """Ce dont le découpage a besoin pour une case."""

    importance: int = 2
    dialogue_chars: int = 0
    panel_id: int | None = None
    intensity: str | None = None  # calme | normal | choc (indice de mise en scène du scénario)


# --- arbre ----------------------------------------------------------------------
def tree_to_json(node: TreeNode) -> Any:
    if node == "panel":
        return "panel"
    assert isinstance(node, SplitNode)
    out: dict[str, Any] = {node.axis: list(node.sizes), "children": [tree_to_json(c) for c in node.nodes]}
    if node.slants is not None and any(a or b for a, b in node.slants):
        out["slants"] = [[round(a, 2), round(b, 2)] for a, b in node.slants]
    return out


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


def template_score(tree: TreeNode, importances: Sequence[float]) -> float:
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
    px_per_mm: float = 300 / 25.4


def page_frame(
    fmt: PageFormat,
    settings: LayoutSettings,
    *,
    direction: Direction,
    page_number: int,
    gutters_mm: dict[str, float] | None = None,
) -> Frame:
    """Zone utile = page − marges. La reliure (marge intérieure) est à gauche des pages de droite.

    En ltr la page 1 est une page de droite (reliure à gauche) ; en rtl (manga) la page 1 est une
    page de gauche (reliure à droite). Les pages paires alternent. `gutters_mm` (style de mise en
    page) remplace les gouttières du format.
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
    gh = gutters_mm["horizontal"] if gutters_mm else fmt.gutters_mm.horizontal
    gv = gutters_mm["vertical"] if gutters_mm else fmt.gutters_mm.vertical
    return Frame(
        width=width,
        height=height,
        live=live,
        gutter_h=fmt.mm_to_px(gh),
        gutter_v=fmt.mm_to_px(gv),
        min_panel=max(1, fmt.mm_to_px(settings.min_panel_mm)),
        inner_side="left" if inner_left else "right",
        px_per_mm=fmt.dpi / 25.4,
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


def _spans(start: float, length: float, sizes: Sequence[float], gutter: int) -> list[tuple[float, float]]:
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
class _Cut:
    """Une découpe d'un nœud, dans l'espace de lecture."""

    path: list[int]
    index: int  # découpe entre l'enfant `index` et l'enfant `index + 1`
    axis: str
    gutter: int
    center: float  # position (le long de l'axe) du milieu de la découpe droite
    slant: tuple[float, float]  # décalage de chaque extrémité (px)
    cross: tuple[float, float]  # coordonnées des extrémités sur l'autre axe
    node_start: float  # étendue du nœud le long de l'axe
    node_length: float
    spans: list[tuple[float, float]]
    lo: float  # bornes du milieu (biais conservé)
    hi: float
    end_lo: tuple[float, float]  # bornes de chaque extrémité
    end_hi: tuple[float, float]
    gap: geo.Polygon  # bande de la gouttière
    visible: tuple[geo.Point, geo.Point] | None = None  # partie de la ligne médiane dans le nœud
    before: list[int] = field(default_factory=list)  # cases de part et d'autre (index de feuille)
    after: list[int] = field(default_factory=list)

    @property
    def ends(self) -> tuple[float, float]:
        return self.center + self.slant[0], self.center + self.slant[1]

    @property
    def length(self) -> float:
        return abs(self.cross[1] - self.cross[0])

    def line(self) -> tuple[geo.Point, geo.Point]:
        (e0, e1), (q0, q1) = self.ends, self.cross
        return ((q0, e0), (q1, e1)) if self.axis == "rows" else ((e0, q0), (e1, q1))


def _halfplane(cut_line: tuple[geo.Point, geo.Point], axis: str) -> tuple[float, float, float]:
    """(nx, ny, n·P0) : normale unitaire de la ligne orientée vers les coordonnées croissantes de l'axe."""
    (x0, y0), (x1, y1) = cut_line
    dx, dy = x1 - x0, y1 - y0
    nx, ny = (-dy, dx) if axis == "rows" else (dy, -dx)
    norm = math.hypot(nx, ny) or 1.0
    nx, ny = nx / norm, ny / norm
    return nx, ny, nx * x0 + ny * y0


def _place(
    node: TreeNode,
    region: geo.Polygon,
    frame: Frame,
    path: list[int],
    leaves: list[geo.Polygon],
    cuts: list[_Cut],
) -> None:
    if node == "panel":
        leaves.append(region)
        return
    assert isinstance(node, SplitNode)
    axis = node.axis
    g = _gutter(frame, axis)
    bx1, by1, bx2, by2 = geo.bbox(region)
    start, length = (by1, by2 - by1) if axis == "rows" else (bx1, bx2 - bx1)
    cross = (bx1, bx2) if axis == "rows" else (by1, by2)
    spans = _spans(start, length, node.sizes, g)
    children = node.nodes
    slants = [(a * frame.px_per_mm, b * frame.px_per_mm) for a, b in node.cut_slants]
    centers = [(spans[i][1] + spans[i + 1][0]) / 2 for i in range(len(spans) - 1)]
    node_cuts: list[_Cut] = []
    planes: list[tuple[float, float, float]] = []
    for k, c in enumerate(centers):
        s = slants[k]
        end_lo, end_hi = [], []
        for j in (0, 1):
            prev_edge = start if k == 0 else centers[k - 1] + slants[k - 1][j] + g / 2
            next_edge = start + length if k == len(centers) - 1 else centers[k + 1] + slants[k + 1][j] - g / 2
            end_lo.append(prev_edge + _min_extent(children[k], axis, frame) + g / 2)
            end_hi.append(next_edge - _min_extent(children[k + 1], axis, frame) - g / 2)
        if any(not end_lo[j] - 1 <= c + s[j] <= end_hi[j] + 1 for j in (0, 1)):
            raise LayoutError("découpe trop inclinée : une case voisine passerait sous la taille minimale")
        lo = max(end_lo[0] - s[0], end_lo[1] - s[1])
        hi = min(end_hi[0] - s[0], end_hi[1] - s[1])
        cut = _Cut(
            path=path,
            index=k,
            axis=axis,
            gutter=g,
            center=c,
            slant=s,
            cross=cross,
            node_start=start,
            node_length=length,
            spans=spans,
            lo=lo,
            hi=max(lo, hi),
            end_lo=(end_lo[0], end_lo[1]),
            end_hi=(end_hi[0], end_hi[1]),
            gap=[],
        )
        nx, ny, d = _halfplane(cut.line(), axis)
        planes.append((nx, ny, d))
        cut.gap = geo.clip(geo.clip(region, -nx, -ny, -(d - g / 2)), nx, ny, d + g / 2)
        cut.visible = geo.clip_segment(*cut.line(), region)
        node_cuts.append(cut)
    for i, child in enumerate(children):
        poly = region
        if i > 0:  # après la découpe i − 1
            nx, ny, d = planes[i - 1]
            poly = geo.clip(poly, -nx, -ny, -(d + g / 2))
        if i < len(children) - 1:  # avant la découpe i
            nx, ny, d = planes[i]
            poly = geo.clip(poly, nx, ny, d - g / 2)
        if len(poly) < 3 or abs(geo.area(poly)) < 1:
            raise LayoutError("découpe trop inclinée : une case disparaît (réduis le biais)")
        if i > 0:
            cuts.append(node_cuts[i - 1])  # même ordre qu'avant : découpe, puis le contenu qui la suit
        first = len(leaves)
        _place(child, poly, frame, [*path, i], leaves, cuts)
        if i > 0:
            node_cuts[i - 1].after = list(range(first, len(leaves)))
        if i < len(children) - 1:
            node_cuts[i].before = list(range(first, len(leaves)))


def _geometry(tree: TreeNode, frame: Frame) -> tuple[list[geo.Polygon], list[_Cut]]:
    leaves: list[geo.Polygon] = []
    cuts: list[_Cut] = []
    _place(tree, frame.live.polygon(), frame, [], leaves, cuts)
    return leaves, cuts


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
    panel: Rect,
    chars: int,
    direction: Direction,
    fmt: PageFormat,
    settings: LayoutSettings,
    polygon: Sequence[geo.Point] | None = None,
) -> Rect | None:
    """Zone réservée aux bulles, en haut de la case, du côté où commence la lecture.

    Pour une case en biais, la zone reste entièrement dans le polygone (retrait de `padding_mm`) :
    elle est cherchée du haut vers le bas, depuis le côté où commence la lecture, puis réduite par
    paliers si elle ne tient nulle part.
    """
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
    if polygon is None or geo.is_axis_rect(polygon):
        y1 = panel.y1 + pad
        if direction == "ltr":
            x1 = panel.x1 + pad
            return Rect(x1, y1, x1 + zw_i, y1 + zh_i)
        x2 = panel.x2 - pad
        return Rect(x2 - zw_i, y1, x2, y1 + zh_i)
    return _zone_in_polygon(polygon, pad, zw_i, zh_i, direction)


def _zone_in_polygon(polygon: Sequence[geo.Point], pad: int, w: int, h: int, direction: Direction) -> Rect | None:
    inner = geo.inset(polygon, pad) or list(polygon)
    planes = geo.edges(inner)
    x1, y1, x2, y2 = geo.bbox(inner)
    left, top, right, bottom = math.ceil(x1), math.ceil(y1), math.floor(x2), math.floor(y2)
    for _ in range(12):
        step = max(1, min(w, h) // 20)
        best: tuple[int, Rect] | None = None
        for y in range(top, bottom - h + 1, step):
            if best is not None and y - top >= best[0]:
                break  # plus bas que la meilleure trouvée : inutile de continuer
            for x in range(left, right - w + 1, step):
                # au plus près du coin haut côté début de lecture
                score = (y - top) + (x - left if direction == "ltr" else right - (x + w))
                if (best is None or score < best[0]) and geo.contains_box(planes, x, y, x + w, y + h):
                    best = (score, Rect(x, y, x + w, y + h))
        if best is not None:
            return best[1]
        w, h = max(1, round(w * 0.85)), max(1, round(h * 0.85))
        if w <= 2 or h <= 2:
            break
    return None


def _out_poly(poly: geo.Polygon, direction: Direction, frame: Frame) -> geo.Polygon:
    return geo.mirror(poly, frame.live.x1, frame.live.x2) if direction == "rtl" else poly


def compute_layout(
    fmt: PageFormat,
    settings: LayoutSettings,
    tree: TreeNode,
    panels: Sequence[PanelSpec],
    *,
    direction: Direction,
    page_number: int,
    template_id: str,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Géométrie complète de la page. `style` (id, graine, rythme, gouttières) vient de la grammaire de
    mise en page (`layout_style.py`) ; ses gouttières remplacent celles du format."""
    if count_panels(tree) != len(panels):
        raise LayoutError(f"le gabarit « {template_id} » a {count_panels(tree)} cases, la page en a {len(panels)}")
    gutters_mm = (style or {}).get("gutters_mm")
    frame = page_frame(fmt, settings, direction=direction, page_number=page_number, gutters_mm=gutters_mm)
    leaves, cuts = _geometry(tree, frame)

    L, R = frame.live.x1, frame.live.x2

    def mx(x: float) -> float:
        return L + R - x if direction == "rtl" else x

    panels_out: list[dict[str, Any]] = []
    for i, (leaf, spec) in enumerate(zip(leaves, panels, strict=True)):
        # Sommets arrondis au dixième de px : la boîte, la zone de bulles et le rendu partent du même polygone.
        poly = [(float(x), float(y)) for x, y in (geo.round_point(p) for p in _out_poly(leaf, direction, frame))]
        top = min(range(len(poly)), key=lambda k: (poly[k][1], poly[k][0]))
        poly = poly[top:] + poly[:top]  # contour horaire depuis le sommet en haut à gauche
        rect = bounding_rect(poly)
        if rect.w < 1 or rect.h < 1:
            raise LayoutError("découpe trop inclinée : une case disparaît (réduis le biais)")
        slanted = not geo.is_axis_rect(poly)
        zone = bubble_zone(rect, spec.dialogue_chars, direction, fmt, settings, poly if slanted else None)
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
                "polygon": [geo.round_point(p) for p in poly],
                "slanted": slanted,
            }
        )

    gutters_out: list[dict[str, Any]] = []
    for g in cuts:
        gap = _out_poly(g.gap, direction, frame)
        rect = bounding_rect(gap) if len(gap) >= 3 else Rect(0, 0, 0, 0)
        p0, p1 = g.line()
        (e0, e1), (lo0, lo1), (hi0, hi1) = g.ends, g.end_lo, g.end_hi
        if g.axis == "cols" and direction == "rtl":
            lo, hi, center = L + R - g.hi, L + R - g.lo, L + R - g.center
            ends = [L + R - e0, L + R - e1]
            ends_min, ends_max = [L + R - hi0, L + R - hi1], [L + R - lo0, L + R - lo1]
        else:
            lo, hi, center = g.lo, g.hi, g.center
            ends, ends_min, ends_max = [e0, e1], [lo0, lo1], [hi0, hi1]
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
                # Ligne médiane de la découpe (extrémité « début » puis « fin » : gauche → droite dans
                # le sens de lecture pour une découpe horizontale, haut → bas pour une verticale).
                "line": [geo.round_point((mx(p0[0]), p0[1])), geo.round_point((mx(p1[0]), p1[1]))],
                # Extrémités visibles de la découpe (dans sa zone) : là où l'interface pose ses poignées.
                "handles": [geo.round_point((mx(q[0]), q[1])) for q in (g.visible or (p0, p1))],
                "ends": [round(v, 1) for v in ends],
                "ends_min": [round(v, 1) for v in ends_min],
                "ends_max": [round(v, 1) for v in ends_max],
                "slant_mm": [round(s / frame.px_per_mm, 2) for s in g.slant],
                "angle_deg": round(math.degrees(math.atan2(g.slant[1] - g.slant[0], g.length or 1)), 2),
            }
        )

    out = {
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
    if style is not None:
        out["style"] = style
    return out


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
    return SplitNode(**{tree.axis: tree.sizes}, children=children, slants=tree.slants)


def _layout_frame(fmt: PageFormat, settings: LayoutSettings, layout: dict[str, Any]) -> Frame:
    return page_frame(
        fmt,
        settings,
        direction=layout["direction"],
        page_number=int(layout["page_number"]),
        gutters_mm=(layout.get("style") or {}).get("gutters_mm"),
    )


def _find_cut(tree: TreeNode, frame: Frame, path: Sequence[int], index: int) -> tuple[SplitNode, _Cut]:
    node = _node_at(tree, path)
    if not 0 <= index < len(node.sizes) - 1:
        raise LayoutError("gouttière introuvable")
    _, cuts = _geometry(tree, frame)
    cut = next((c for c in cuts if c.path == list(path) and c.index == index), None)
    if cut is None:
        raise LayoutError("gouttière introuvable")
    return node, cut


def _resized(node: SplitNode, cut: _Cut, center: float, slants: list[tuple[float, float]] | None) -> SplitNode:
    """Nœud dont la découpe `cut` est centrée en `center` (espace de lecture) : seules ses deux voisines changent."""
    g, index = cut.gutter, cut.index
    a = cut.spans[index][0]
    b = cut.spans[index + 1][1]
    avail = cut.node_length - g * (len(node.sizes) - 1)
    first = center - g / 2 - a
    second = b - (center + g / 2)
    total = sum(node.sizes)
    sizes = list(node.sizes)
    sizes[index] = max(first, 1e-6) / avail * total
    sizes[index + 1] = max(second, 1e-6) / avail * total
    return SplitNode(**{node.axis: sizes}, children=node.nodes, slants=slants)


def _relayout(
    fmt: PageFormat, settings: LayoutSettings, layout: dict[str, Any], tree: TreeNode, panels: Sequence[PanelSpec]
) -> dict[str, Any]:
    return compute_layout(
        fmt,
        settings,
        tree,
        panels,
        direction=layout["direction"],
        page_number=int(layout["page_number"]),
        template_id=layout["template_id"],
        style=layout.get("style"),
    )


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

    La position est bornée pour que chaque voisine (et ses sous-cases) garde la taille minimale ;
    un biais éventuel est conservé.
    """
    tree = tree_from_json(layout["tree"])
    direction: Direction = layout["direction"]
    match = next((g for g in layout.get("gutters", []) if list(g["path"]) == list(path) and g["index"] == index), None)
    frame = _layout_frame(fmt, settings, layout)
    node, cut = _find_cut(tree, frame, path, index)
    if match is None:
        raise LayoutError("gouttière introuvable")
    L, R = frame.live.x1, frame.live.x2
    pos = min(max(position, match["min"]), match["max"])
    if node.axis == "cols" and direction == "rtl":
        pos = L + R - pos  # retour dans l'espace de lecture
    new_tree = _replace_at(tree, path, _resized(node, cut, pos, node.slants))
    return _relayout(fmt, settings, layout, new_tree, panels)


def set_cut_slant(
    fmt: PageFormat,
    settings: LayoutSettings,
    layout: dict[str, Any],
    panels: Sequence[PanelSpec],
    *,
    path: Sequence[int],
    index: int,
    ends: Sequence[float],
) -> dict[str, Any]:
    """Incline une découpe : nouvelles positions (px de la page, le long de l'axe découpé) de ses deux
    extrémités, dans l'ordre de `gutters[].ends`. Chaque extrémité est bornée pour que les cases
    voisines gardent la taille minimale ; la découpe pivote autour de son milieu."""
    if len(ends) != 2:
        raise LayoutError("une découpe a deux extrémités")
    tree = tree_from_json(layout["tree"])
    direction: Direction = layout["direction"]
    frame = _layout_frame(fmt, settings, layout)
    node, cut = _find_cut(tree, frame, path, index)
    L, R = frame.live.x1, frame.live.x2
    e = [float(v) for v in ends]
    if node.axis == "cols" and direction == "rtl":
        e = [L + R - v for v in e]
    e = [min(max(v, cut.end_lo[j]), cut.end_hi[j]) for j, v in enumerate(e)]
    center = (e[0] + e[1]) / 2
    half = (e[1] - e[0]) / 2
    slants = node.cut_slants
    slants[index] = (round(-half / frame.px_per_mm, 2), round(half / frame.px_per_mm, 2))
    new_tree = _replace_at(tree, path, _resized(node, cut, center, slants))
    return _relayout(fmt, settings, layout, new_tree, panels)
