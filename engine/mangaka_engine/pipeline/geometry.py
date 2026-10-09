"""Polygones convexes (cases en biais) : découpe par demi-plans, retrait, appartenance, point le plus proche.

Un polygone est une liste de sommets (x, y) en px, dans l'ordre du contour (sens horaire à l'écran,
y vers le bas). Toutes les fonctions sont pures et déterministes ; aucune constante de style ici
(les angles et probabilités vivent dans `presets/layout_styles/`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]
Polygon = list[Point]
EPS = 1e-6


def rect_polygon(x1: float, y1: float, x2: float, y2: float) -> Polygon:
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def clip(poly: Sequence[Point], a: float, b: float, c: float) -> Polygon:
    """Garde la partie du polygone où a·x + b·y ≤ c (Sutherland–Hodgman sur un seul demi-plan)."""
    out: Polygon = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp, fq = a * p[0] + b * p[1] - c, a * q[0] + b * q[1] - c
        if fp <= EPS:
            out.append(p)
        if (fp < -EPS and fq > EPS) or (fp > EPS and fq < -EPS):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return _dedupe(out)


def _dedupe(poly: Polygon) -> Polygon:
    out: Polygon = []
    for p in poly:
        if not out or abs(p[0] - out[-1][0]) > EPS or abs(p[1] - out[-1][1]) > EPS:
            out.append(p)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) <= EPS and abs(out[0][1] - out[-1][1]) <= EPS:
        out.pop()
    return out


def area(poly: Sequence[Point]) -> float:
    """Aire signée (> 0 pour un contour horaire à l'écran, y vers le bas)."""
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2


def bbox(poly: Sequence[Point]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(poly: Sequence[Point]) -> Point:
    a = area(poly)
    if abs(a) < EPS:
        x1, y1, x2, y2 = bbox(poly)
        return (x1 + x2) / 2, (y1 + y2) / 2
    cx = cy = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        k = x1 * y2 - x2 * y1
        cx += (x1 + x2) * k
        cy += (y1 + y2) * k
    return cx / (6 * a), cy / (6 * a)


def is_axis_rect(poly: Sequence[Point]) -> bool:
    """Le polygone est un rectangle aux bords horizontaux / verticaux (case droite)."""
    if len(poly) != 4:
        return False
    x1, y1, x2, y2 = bbox(poly)
    return all(
        (abs(x - x1) <= EPS or abs(x - x2) <= EPS) and (abs(y - y1) <= EPS or abs(y - y2) <= EPS) for x, y in poly
    )


def edges(poly: Sequence[Point]) -> list[tuple[float, float, float]]:
    """Demi-plans a·x + b·y ≤ c (normale unitaire sortante) dont l'intersection est le polygone convexe."""
    orient = 1.0 if area(poly) >= 0 else -1.0
    out = []
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        if norm < EPS:
            continue
        # contour horaire (y vers le bas) : la normale sortante est (dy, −dx)
        a, b = orient * dy / norm, -orient * dx / norm
        out.append((a, b, a * x1 + b * y1))
    return out


def inset(poly: Sequence[Point], d: float) -> Polygon:
    """Polygone convexe rétréci de `d` px (chaque bord recule parallèlement). Vide si trop petit."""
    if d <= 0:
        return list(poly)
    out: Polygon = list(poly)
    for a, b, c in edges(poly):
        out = clip(out, a, b, c - d)
        if len(out) < 3:
            return []
    return out


def offset_edges(poly: Sequence[Point], offsets: Sequence[float]) -> Polygon:
    """Polygone convexe dont chaque bord i a reculé de `offsets[i]` px (négatif : avancé vers l'extérieur).

    Intersection des demi-plans décalés, partant d'un grand rectangle : un bord avancé ne déplace que
    lui (les bords voisins gardent leur direction). Vide si le résultat disparaît.
    """
    planes = edges(poly)
    if len(planes) != len(offsets):
        raise ValueError("un décalage par bord")
    x1, y1, x2, y2 = bbox(poly)
    room = (x2 - x1) + (y2 - y1) + 2 * max((abs(o) for o in offsets), default=0) + 10
    out = rect_polygon(x1 - room, y1 - room, x2 + room, y2 + room)
    for (a, b, c), d in zip(planes, offsets, strict=True):
        out = clip(out, a, b, c - d)
        if len(out) < 3:
            return []
    return out


def outset(poly: Sequence[Point], d: float) -> Polygon:
    """Polygone convexe agrandi de `d` px (chaque bord avance parallèlement, coins en onglet)."""
    return offset_edges(poly, [-d] * len(edges(poly)))


def convex_overlap(p: Sequence[Point], q: Sequence[Point], gap: float = 0.0) -> bool:
    """Deux polygones convexes se recouvrent-ils (ou sont-ils à moins de `gap` px) ? Axes séparateurs."""
    for poly in (p, q):
        n = len(poly)
        for i in range(n):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
            nx, ny = y2 - y1, x1 - x2
            norm = math.hypot(nx, ny)
            if norm < EPS:
                continue
            nx, ny = nx / norm, ny / norm
            pa = [nx * x + ny * y for x, y in p]
            pb = [nx * x + ny * y for x, y in q]
            if max(pa) + gap <= min(pb) or max(pb) + gap <= min(pa):
                return False
    return True


def overflow(poly_edges: Sequence[tuple[float, float, float]], points: Sequence[Point]) -> float:
    """Plus grande distance (px) d'un point hors du polygone convexe, mesurée perpendiculairement à un bord."""
    return max((a * x + b * y - c for a, b, c in poly_edges for x, y in points), default=0.0)


def affine(m: tuple[float, float, float, float], tx: float, ty: float, points: Sequence[Point]) -> Polygon:
    """Image des points par x' = m0·x + m1·y + tx, y' = m2·x + m3·y + ty."""
    return [(m[0] * x + m[1] * y + tx, m[2] * x + m[3] * y + ty) for x, y in points]


def contains(poly_edges: Sequence[tuple[float, float, float]], x: float, y: float, tol: float = 1e-4) -> bool:
    return all(a * x + b * y <= c + tol for a, b, c in poly_edges)


def contains_box(poly_edges: Sequence[tuple[float, float, float]], x1: float, y1: float, x2: float, y2: float) -> bool:
    """Le rectangle est entièrement dans le polygone convexe (ses quatre coins le sont)."""
    return all(contains(poly_edges, x, y) for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)))


def nearest_on_boundary(poly: Sequence[Point], x: float, y: float) -> Point:
    best: Point = poly[0]
    best_d = math.inf
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < EPS else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
        p = (x1 + t * dx, y1 + t * dy)
        d = math.dist(p, (x, y))
        if d < best_d - 1e-9:
            best, best_d = p, d
    return best


def clamp_point(poly: Sequence[Point], x: float, y: float) -> Point:
    """Le point s'il est dans le polygone convexe, sinon le point le plus proche de son contour."""
    if contains(edges(poly), x, y, tol=0):
        return x, y
    return nearest_on_boundary(poly, x, y)


def clip_segment(p0: Point, p1: Point, poly: Sequence[Point]) -> tuple[Point, Point] | None:
    """Partie du segment [p0, p1] dans le polygone convexe (None si elle est vide)."""
    lo, hi = 0.0, 1.0
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    for a, b, c in edges(poly):
        den = a * dx + b * dy
        num = c - (a * p0[0] + b * p0[1])
        if abs(den) < EPS:
            if num < -EPS:
                return None
            continue
        t = num / den
        if den > 0:
            hi = min(hi, t)
        else:
            lo = max(lo, t)
    if hi - lo < EPS:
        return None
    return (p0[0] + lo * dx, p0[1] + lo * dy), (p0[0] + hi * dx, p0[1] + hi * dy)


def mirror(poly: Sequence[Point], left: float, right: float) -> Polygon:
    """Miroir horizontal dans [left, right] ; l'ordre est inversé pour garder un contour horaire."""
    return [(left + right - x, y) for x, y in reversed(poly)]


def round_point(p: Point) -> list[float | int]:
    """Sommet arrondi au dixième de px (entier quand il l'est) : JSON stable, rendus reproductibles."""
    out: list[float | int] = []
    for v in p:
        r = round(v, 1)
        out.append(int(r) if r == int(r) else r)
    return out
