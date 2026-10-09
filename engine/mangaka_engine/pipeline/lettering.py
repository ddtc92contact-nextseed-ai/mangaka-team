"""Étape 5 — lettrage déterministe : texte, formes de bulle, placement, queues.

Entrées (en px de la page, hors fond perdu) : pour chaque case, son cadre, sa zone réservée aux
bulles (étape 2), les boîtes de visages de la version retenue (QC, facultatives) et ses bulles.
Sortie : pour chaque bulle, son cadre, ses lignes de texte (position de la ligne de base), la
géométrie de sa forme et de sa queue (polygones) ; plus des avertissements lisibles.

Règles :

- **texte** : typographie française (espaces insécables avant « ! ? : ; » et dans les guillemets),
  retour à la ligne glouton avec césure (pyphen) seulement quand la ligne resterait trop vide,
  taille réduite par pas jusqu'au minimum lisible du preset, bloc centré ;
- **placement** : dans la zone réservée, sinon dans toute la case — pour une case en biais, chaque
  bulle reste entièrement dans le polygone de la case (pas seulement sa boîte) ; la 1re bulle lue est en haut
  côté début de lecture (gauche en ltr, droite en rtl), chaque suivante plus bas ou, à la même
  hauteur, plus loin dans le sens de lecture ; jamais sur un visage détecté tant que c'est
  possible ;
- **queue** : vers le visage du locuteur s'il est détecté, sinon dans la direction par défaut du
  preset ; hors-champ → vers le bord de la case ; récitatif → pas de queue ;
- **jamais de texte coupé en silence** : faute de place, la bulle garde tout son texte (taille
  minimale) et un avertissement est émis ;
- **onomatopées** (`sfx`, voir `SfxSpec`) : grand texte sans bulle, posé après toutes les bulles de la
  page. Taille selon l'intensité et la taille de la case, angle et cisaillement tirés (graine =
  l'onomatopée) ; son contour (texte + contour épais + halo, transformé) peut dépasser de la case d'au
  plus `max_overflow_mm`, jamais sur un visage, une bulle, une autre onomatopée ou une incrustation tant
  que c'est possible.

Tout est calculé en flottants puis arrondi au dixième de pixel : deux exécutions donnent le même
résultat, ce qui rend les rendus PNG / SVG reproductibles (tests « golden »).
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

import pyphen

from ..presets.schemas import FontsPreset, LetteringSettings, SfxSettings, TextStyle
from . import geometry as geo
from .fonts import NBSP, NNBSP, FontBook, pt_to_px

Direction = Literal["ltr", "rtl"]
Point = tuple[float, float]
MM_PER_INCH = 25.4
ELLIPSE_POINTS = 96
CIRCLE_POINTS = 24


class LetteringError(ValueError):
    """Lettrage ou rendu impossible (message lisible)."""


# --- géométrie ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    def inset(self, d: float) -> Box:
        if 2 * d >= self.w or 2 * d >= self.h:
            return self
        return Box(self.x1 + d, self.y1 + d, self.x2 - d, self.y2 - d)

    def expand(self, d: float) -> Box:
        return Box(self.x1 - d, self.y1 - d, self.x2 + d, self.y2 + d)

    def intersects(self, o: Box, gap: float = 0) -> bool:
        return not (self.x2 + gap <= o.x1 or o.x2 + gap <= self.x1 or self.y2 + gap <= o.y1 or o.y2 + gap <= self.y1)

    def intersection(self, o: Box) -> Box | None:
        b = Box(max(self.x1, o.x1), max(self.y1, o.y1), min(self.x2, o.x2), min(self.y2, o.y2))
        return b if b.w > 0 and b.h > 0 else None

    def contains_point(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def clamp_point(self, x: float, y: float) -> Point:
        return min(max(x, self.x1), self.x2), min(max(y, self.y1), self.y2)

    def as_rect(self) -> dict[str, int]:
        return {"x1": round(self.x1), "y1": round(self.y1), "x2": round(self.x2), "y2": round(self.y2)}

    def as_xywh(self) -> dict[str, int]:
        return {"x": round(self.x1), "y": round(self.y1), "w": round(self.w), "h": round(self.h)}

    @classmethod
    def parse(cls, data: Any) -> Box | None:
        """{x1,y1,x2,y2}, {x,y,w,h} ou [x1,y1,x2,y2] ; None si illisible ou vide."""
        try:
            if isinstance(data, dict):
                if {"x1", "y1", "x2", "y2"} <= data.keys():
                    box = cls(float(data["x1"]), float(data["y1"]), float(data["x2"]), float(data["y2"]))
                elif {"x", "y", "w", "h"} <= data.keys():
                    x, y = float(data["x"]), float(data["y"])
                    box = cls(x, y, x + float(data["w"]), y + float(data["h"]))
                elif {"x", "y", "width", "height"} <= data.keys():
                    x, y = float(data["x"]), float(data["y"])
                    box = cls(x, y, x + float(data["width"]), y + float(data["height"]))
                else:
                    return None
            elif isinstance(data, (list, tuple)) and len(data) >= 4:
                box = cls(*(float(v) for v in data[:4]))
            else:
                return None
        except (TypeError, ValueError):
            return None
        return box if box.w > 0 and box.h > 0 else None


def _r(v: float) -> float:
    return round(v, 1)


# --- texte --------------------------------------------------------------------------------
_FR_RULES = [
    (re.compile(r"«[ \t  ]*"), "«" + NBSP),
    (re.compile(r"[ \t  ]*»"), NBSP + "»"),
    (re.compile(r"[ \t  ]*([!?:;]+)"), NBSP + r"\1"),
]
_SPACES = re.compile(r"[ \t]+")


def normalize_text(text: str, *, uppercase: bool = False) -> str:
    """Typographie française : espaces insécables dans les guillemets et avant « ! ? : ; »."""
    text = text.replace("\r\n", "\n").replace(NNBSP, NBSP)
    lines = []
    for line in text.split("\n"):
        line = _SPACES.sub(" ", line).strip(" \t")
        for pattern, repl in _FR_RULES:
            line = pattern.sub(repl, line)
        # « ?! » colle à la fin d'une ligne vide : pas d'espace en tête de ligne
        lines.append(line.lstrip(NBSP) if line.startswith(NBSP) else line)
    out = "\n".join(lines).strip()
    return out.upper() if uppercase else out


@lru_cache(maxsize=8)
def _hyphenator(language: str) -> pyphen.Pyphen:
    return pyphen.Pyphen(lang=language, left=2, right=3)


_CORE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)


def split_options(word: str, *, language: str = "fr", min_word_chars: int = 6) -> list[tuple[str, str]]:
    """Coupures possibles d'un mot, de la plus longue tête à la plus courte : (tête affichée, reste).

    Un trait d'union existant est une coupure naturelle (sans tiret ajouté) ; sinon les points de
    césure de pyphen, si le mot a au moins `min_word_chars` lettres.
    """
    m = _CORE.match(word)
    assert m is not None
    pre, core, post = m.groups()
    opts: dict[str, str] = {}
    for i, ch in enumerate(core):
        if ch == "-" and 0 < i < len(core) - 1:
            opts[pre + core[: i + 1]] = core[i + 1 :] + post
    if sum(c.isalpha() for c in core) >= min_word_chars:
        offset = 0
        for part in core.split("-"):
            for pos in _hyphenator(language).positions(part):
                head = core[: offset + pos]
                opts.setdefault(pre + head + "-", core[offset + pos :] + post)
            offset += len(part) + 1
    return sorted(opts.items(), key=lambda kv: -len(kv[0]))


def wrap_text(
    text: str,
    measure: Callable[[str], float],
    max_width: float,
    *,
    language: str = "fr",
    min_word_chars: int = 6,
    min_gap: float = 0.3,
) -> list[str]:
    """Retour à la ligne glouton. Un mot trop long pour la fin de ligne est coupé (césure) si la
    ligne resterait vide à plus de `min_gap`, ou s'il ne tient pas seul sur une ligne. Un mot
    impossible à couper dépasse : c'est l'ajustement de taille qui le détecte."""
    out: list[str] = []
    for paragraph in text.split("\n"):
        queue = [w for w in paragraph.split(" ") if w]
        line = ""
        while queue:
            word = queue.pop(0)
            candidate = f"{line} {word}" if line else word
            if measure(candidate) <= max_width:
                line = candidate
                continue
            prefix = f"{line} " if line else ""
            alone_fits = measure(word) <= max_width
            gap = (max_width - measure(line)) / max_width if line else 1.0
            if not line or not alone_fits or gap > min_gap:
                split = next(
                    (
                        (h, t)
                        for h, t in split_options(word, language=language, min_word_chars=min_word_chars)
                        if measure(prefix + h) <= max_width
                    ),
                    None,
                )
                if split is not None and (not line or not alone_fits or gap > min_gap):
                    out.append(prefix + split[0])
                    line = ""
                    queue.insert(0, split[1])
                    continue
            if line:
                out.append(line)
                line = ""
                queue.insert(0, word)
            else:
                out.append(word)  # mot insécable plus large que la ligne
        if line:
            out.append(line)
    return out


@dataclass(frozen=True)
class TextBlock:
    lines: tuple[str, ...]
    widths: tuple[float, ...]
    size_px: float
    line_px: float
    cap: float  # hauteur des capitales au-dessus de la ligne de base
    desc: float  # jambages sous la ligne de base

    @property
    def width(self) -> float:
        return max(self.widths, default=0.0)

    @property
    def height(self) -> float:
        return (len(self.lines) - 1) * self.line_px + self.cap + self.desc if self.lines else 0.0

    @property
    def hyphens(self) -> int:
        return sum(1 for line in self.lines if line.endswith("-") and not line.endswith(" -"))


# --- formes -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Shape:
    """Polygones fermés d'une bulle : contour épais puis remplissage (union propre corps + queue)."""

    polygons: tuple[tuple[Point, ...], ...]
    fill: str
    stroke: str
    stroke_px: float

    def path(self) -> str:
        parts = []
        for poly in self.polygons:
            pts = " L".join(f"{x:.1f},{y:.1f}" for x, y in poly)
            parts.append(f"M{pts} Z")
        return " ".join(parts)


def ellipse_points(cx: float, cy: float, rx: float, ry: float, n: int = ELLIPSE_POINTS) -> list[Point]:
    return [
        (_r(cx + rx * math.cos(2 * math.pi * i / n)), _r(cy + ry * math.sin(2 * math.pi * i / n))) for i in range(n)
    ]


def _perimeter(rx: float, ry: float) -> float:
    h = ((rx - ry) / (rx + ry)) ** 2 if rx + ry else 0
    return math.pi * (rx + ry) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


def cloud_points(box: Box, bump: float, amplitude: float) -> list[Point]:
    """Nuage : ellipse festonnée de bosses arrondies (pensée)."""
    rx, ry = max(1.0, box.w / 2 - amplitude), max(1.0, box.h / 2 - amplitude)
    bumps = max(6, round(_perimeter(rx, ry) / bump))
    n = bumps * 10
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        k = amplitude * abs(math.sin(bumps * t / 2))
        pts.append((_r(box.cx + (rx + k) * math.cos(t)), _r(box.cy + (ry + k) * math.sin(t))))
    return pts


def spiky_points(box: Box, spike: float, every: float, jitter: float, seed: int) -> list[Point]:
    """Cri : contour en pointes (alternance pointe / creux), irrégularité déterministe."""
    rng = random.Random(seed)
    rx, ry = max(1.0, box.w / 2 - spike), max(1.0, box.h / 2 - spike)
    spikes = max(8, round(_perimeter(rx, ry) / every))
    pts = []
    for i in range(2 * spikes):
        t = math.pi * i / spikes
        if i % 2 == 0:
            k = spike * (1 - jitter * rng.random())
            pts.append((_r(box.cx + (rx + k) * math.cos(t)), _r(box.cy + (ry + k) * math.sin(t))))
        else:
            k = spike * 0.15
            pts.append((_r(box.cx + (rx - k) * math.cos(t)), _r(box.cy + (ry - k) * math.sin(t))))
    return pts


def rect_points(box: Box, radius: float) -> list[Point]:
    r = max(0.0, min(radius, box.w / 2, box.h / 2))
    if r < 0.5:
        return [(_r(box.x1), _r(box.y1)), (_r(box.x2), _r(box.y1)), (_r(box.x2), _r(box.y2)), (_r(box.x1), _r(box.y2))]
    pts: list[Point] = []
    corners = [
        (box.x2 - r, box.y2 - r, 0),
        (box.x1 + r, box.y2 - r, 90),
        (box.x1 + r, box.y1 + r, 180),
        (box.x2 - r, box.y1 + r, 270),
    ]
    for cx, cy, start in corners:
        for j in range(9):
            a = math.radians(start + j * 90 / 8)
            pts.append((_r(cx + r * math.cos(a)), _r(cy + r * math.sin(a))))
    return pts


def ellipse_boundary(box: Box, angle: float, scale: float = 1.0) -> Point:
    """Point du bord de l'ellipse inscrite dans `box`, dans la direction `angle` depuis son centre."""
    rx, ry = box.w / 2 * scale, box.h / 2 * scale
    phi = math.atan2(math.sin(angle) / max(ry, 1e-6), math.cos(angle) / max(rx, 1e-6))
    return box.cx + rx * math.cos(phi), box.cy + ry * math.sin(phi)


def tail_polygons(kind: str, box: Box, tip: Point, base: float, cloud_bubbles: int) -> list[list[Point]]:
    """Queue : triangle effilé (parole, cri, hors-champ) ou bulles décroissantes (pensée)."""
    angle = math.atan2(tip[1] - box.cy, tip[0] - box.cx)
    edge = ellipse_boundary(box, angle)
    if math.dist(edge, (box.cx, box.cy)) >= math.dist(tip, (box.cx, box.cy)) - 1:
        return []  # pointe dans la bulle : pas de queue
    if kind == "thought":
        out = []
        n = max(1, cloud_bubbles)
        for i in range(n):
            f = (i + 1) / (n + 0.4)
            x, y = edge[0] + (tip[0] - edge[0]) * f, edge[1] + (tip[1] - edge[1]) * f
            r = base / 2 * (1 - i / (n + 1))
            out.append(
                [
                    (
                        _r(x + r * math.cos(2 * math.pi * j / CIRCLE_POINTS)),
                        _r(y + r * math.sin(2 * math.pi * j / CIRCLE_POINTS)),
                    )
                    for j in range(CIRCLE_POINTS)
                ]
            )
        return out
    radius = (box.w + box.h) / 4
    delta = min(math.pi / 4, base / 2 / max(radius, 1))
    b1 = ellipse_boundary(box, angle - delta, 0.85)
    b2 = ellipse_boundary(box, angle + delta, 0.85)
    # Légère courbure : un point intermédiaire décalé donne une queue effilée plutôt qu'un triangle.
    mx, my = (b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2
    bend = (tip[0] - mx, tip[1] - my)
    side = (-bend[1] * 0.08, bend[0] * 0.08)
    mid1 = (b1[0] + bend[0] * 0.55 + side[0], b1[1] + bend[1] * 0.55 + side[1])
    mid2 = (b2[0] + bend[0] * 0.5 + side[0], b2[1] + bend[1] * 0.5 + side[1])
    return [
        [
            (_r(b1[0]), _r(b1[1])),
            (_r(mid1[0]), _r(mid1[1])),
            (_r(tip[0]), _r(tip[1])),
            (_r(mid2[0]), _r(mid2[1])),
            (_r(b2[0]), _r(b2[1])),
        ]
    ]


# --- entrées / sorties --------------------------------------------------------------------
@dataclass
class BubbleSpec:
    id: int
    kind: str
    text: str
    speaker: str = ""
    order: int = 0
    manual_box: Box | None = None
    manual_tail: Point | None = None


@dataclass
class PanelSpec:
    id: int
    index: int
    box: Box
    zone: Box | None = None
    faces: list[Box] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    bubbles: list[BubbleSpec] = field(default_factory=list)
    # Polygone de la case (px de la page) quand elle est en biais ; None = son cadre `box`.
    polygon: list[Point] | None = None
    sfx: list[SfxSpec] = field(default_factory=list)
    # Zones à laisser libres (incrustation posée sur la case) : ni bulle ni onomatopée dessus.
    obstacles: list[Box] = field(default_factory=list)

    @property
    def slanted(self) -> bool:
        return self.polygon is not None and len(self.polygon) >= 3 and not geo.is_axis_rect(self.polygon)

    def clamp(self, x: float, y: float) -> Point:
        """Point ramené dans la case (polygone si elle est en biais)."""
        if self.slanted:
            assert self.polygon is not None
            return geo.clamp_point(self.polygon, x, y)
        return self.box.clamp_point(x, y)

    def outline(self) -> list[Point]:
        """Contour de la case : son polygone, sinon les quatre coins de son cadre."""
        if self.polygon is not None and len(self.polygon) >= 3:
            return list(self.polygon)
        return geo.rect_polygon(self.box.x1, self.box.y1, self.box.x2, self.box.y2)


@dataclass
class SfxSpec:
    """Une onomatopée : texte et réglages imposés dans l'écran Lettrage (None = calculé)."""

    id: int
    text: str
    order: int = 0
    intensity: str | None = None  # calme | normal | choc
    font: str | None = None
    size_pt: float | None = None
    angle: float | None = None  # degrés, sens horaire à l'écran
    skew: float | None = None  # degrés (cisaillement horizontal, comme skewX en SVG)
    center: Point | None = None  # px de la page, placé à la main


@dataclass(frozen=True)
class TextLine:
    text: str  # tel qu'il est dessiné (espaces absentes de la police remplacées)
    x: float  # centre
    y: float  # ligne de base
    width: float


@dataclass
class BubbleLayout:
    id: int
    panel_id: int
    kind: str
    text: str
    speaker: str
    box: Box
    tail: Point | None
    style: TextStyle
    family: str
    size_pt: float
    size_px: float
    lines: list[TextLine]
    shape: Shape
    manual: bool
    manual_tail: bool
    overflow: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "panel_id": self.panel_id,
            "kind": self.kind,
            "text": self.text,
            "speaker": self.speaker,
            "box": self.box.as_xywh(),
            "tail": {"x": round(self.tail[0]), "y": round(self.tail[1])} if self.tail else None,
            "manual": self.manual,
            "manual_tail": self.manual_tail,
            "overflow": self.overflow,
            "font": {
                "family": self.family,
                "size_pt": self.size_pt,
                "size_px": round(self.size_px, 2),
                "color": self.style.color,
            },
            "lines": [{"text": ln.text, "x": round(ln.x, 1), "y": round(ln.y, 1)} for ln in self.lines],
            "shape": {
                "path": self.shape.path(),
                "fill": self.shape.fill,
                "stroke": self.shape.stroke,
                "stroke_px": round(self.shape.stroke_px, 2),
            },
        }


@dataclass
class SfxLayout:
    """Onomatopée calculée. Les lignes sont dans le repère local (centre du texte = origine) ; le
    passage à la page est `transform` (rotation · cisaillement, puis translation au centre)."""

    id: int
    panel_id: int
    text: str
    intensity: str
    font_id: str
    style: TextStyle
    family: str
    size_pt: float
    size_px: float
    angle: float
    skew: float
    center: Point
    lines: list[TextLine]
    half: tuple[float, float]  # demi-largeur / demi-hauteur du contour local (halo compris)
    quad: list[Point]  # contour transformé (px de la page) : sert au placement et aux tests
    outline_px: float
    halo_px: float
    fill: str
    outline: str
    halo: str
    manual: bool  # centre placé à la main
    manual_size: bool
    manual_angle: bool
    manual_skew: bool
    overflow_px: float  # dépassement réel hors de la case (≤ max_overflow_mm)

    @property
    def matrix(self) -> tuple[float, float, float, float]:
        return sfx_matrix(self.angle, self.skew)

    def svg_transform(self) -> str:
        cx, cy = self.center
        return f"translate({cx:.1f} {cy:.1f}) rotate({self.angle:.2f}) skewX({self.skew:.2f})"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "panel_id": self.panel_id,
            "kind": "sfx",
            "text": self.text,
            "intensity": self.intensity,
            "font": {
                "id": self.font_id,
                "family": self.family,
                "size_pt": self.size_pt,
                "size_px": round(self.size_px, 2),
            },
            "center": {"x": round(self.center[0], 1), "y": round(self.center[1], 1)},
            "angle": round(self.angle, 2),
            "skew": round(self.skew, 2),
            "half": {"w": round(self.half[0], 1), "h": round(self.half[1], 1)},
            "quad": [[round(x, 1), round(y, 1)] for x, y in self.quad],
            "lines": [{"text": ln.text, "x": round(ln.x, 1), "y": round(ln.y, 1)} for ln in self.lines],
            "paint": {
                "fill": self.fill,
                "outline": self.outline,
                "outline_px": round(self.outline_px, 2),
                "halo": self.halo,
                "halo_px": round(self.halo_px, 2),
            },
            "transform": self.svg_transform(),
            "manual": self.manual,
            "manual_size": self.manual_size,
            "manual_angle": self.manual_angle,
            "manual_skew": self.manual_skew,
            "overflow_px": round(self.overflow_px, 1),
        }


def sfx_matrix(angle: float, skew: float) -> tuple[float, float, float, float]:
    """Matrice 2×2 de rotate(angle) · skewX(skew) (degrés, y vers le bas : angle > 0 = sens horaire)."""
    a, t = math.radians(angle), math.tan(math.radians(skew))
    c, s = math.cos(a), math.sin(a)
    return c, c * t - s, s, s * t + c


@dataclass(frozen=True)
class LetteringWarning:
    code: str  # text_overflow | faces_covered | missing_image | layout_stale | no_layout | sfx_*
    message: str
    panel_id: int | None = None
    bubble_id: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "panel_id": self.panel_id, "bubble_id": self.bubble_id}


@dataclass
class PageLettering:
    bubbles: list[BubbleLayout]
    warnings: list[LetteringWarning]
    sfx: list[SfxLayout] = field(default_factory=list)


@dataclass(frozen=True)
class _Fit:
    size_pt: float
    block: TextBlock
    outer: tuple[float, float]


# --- moteur -------------------------------------------------------------------------------
class Letterer:
    def __init__(self, fonts: FontBook, settings: LetteringSettings, dpi: int) -> None:
        self.fonts = fonts
        self.preset: FontsPreset = fonts.preset
        self.s = settings
        self.dpi = dpi

    def mm(self, v: float) -> float:
        return v / MM_PER_INCH * self.dpi

    def pt(self, v: float) -> float:
        return pt_to_px(v, self.dpi)

    # texte ------------------------------------------------------------------------------
    def sizes(self, kind: str) -> list[float]:
        st = self.fonts.style(kind)
        out, size = [], st.size_pt
        while size > st.min_size_pt + 1e-9:
            out.append(round(size, 2))
            size -= st.step_pt
        out.append(st.min_size_pt)
        return out

    def block(self, kind: str, text: str, size_pt: float, max_text_width: float) -> TextBlock:
        st = self.fonts.style(kind)
        font = self.fonts.pil(st, self.pt(size_pt))

        def measure(s: str) -> float:
            return font.getlength(self.fonts.drawable(st, s))

        hy = self.preset.hyphenation
        lines = wrap_text(
            text, measure, max_text_width, language=hy.language, min_word_chars=hy.min_word_chars, min_gap=hy.min_gap
        )
        cap = -font.getbbox("H", anchor="ls")[1]
        desc = font.getbbox("gjpq", anchor="ls")[3]
        size_px = self.pt(size_pt)
        return TextBlock(
            lines=tuple(lines),
            widths=tuple(measure(line) for line in lines),
            size_px=size_px,
            line_px=size_px * st.line_height,
            cap=cap,
            desc=desc,
        )

    def _pad(self, kind: str) -> tuple[float, float]:
        p = self.s.padding_mm[kind]
        return self.mm(p.x), self.mm(p.y)

    def _ellipse_kind(self, kind: str) -> bool:
        return kind in ("thought", "shout", "off") or (kind == "speech" and self.s.speech_shape == "ellipse")

    def _extra(self, kind: str) -> float:
        if kind == "thought":
            return self.mm(self.s.cloud.amplitude_mm)
        if kind == "shout":
            return self.mm(self.s.shout.spike_mm)
        return 0.0

    def outer_size(self, kind: str, tw: float, th: float) -> tuple[float, float]:
        """Taille de la bulle autour d'un bloc de texte tw × th."""
        px, py = self._pad(kind)
        extra = self._extra(kind)
        if self._ellipse_kind(kind):
            f = self.s.ellipse_factor
            return 2 * (tw / 2 * f + px + extra), 2 * (th / 2 * f + py + extra)
        return tw + 2 * px, th + 2 * py

    def inner_size(self, kind: str, w: float, h: float) -> tuple[float, float]:
        """Inverse de `outer_size` : place disponible pour le texte dans une bulle w × h."""
        px, py = self._pad(kind)
        extra = self._extra(kind)
        if self._ellipse_kind(kind):
            f = self.s.ellipse_factor
            return max(1.0, 2 * (w / 2 - px - extra) / f), max(1.0, 2 * (h / 2 - py - extra) / f)
        return max(1.0, w - 2 * px), max(1.0, h - 2 * py)

    def fit(self, kind: str, text: str, size_pt: float, max_w: float, max_h: float) -> _Fit | None:
        """Meilleur retour à la ligne à cette taille pour une bulle tenant dans max_w × max_h."""
        inner_w, _ = self.inner_size(kind, max_w, max_h)
        size_px = self.pt(size_pt)
        lo = min(inner_w, size_px * 5)
        best: tuple[float, _Fit] | None = None
        seen: set[tuple[str, ...]] = set()
        for i in range(12):
            width = lo + (inner_w - lo) * i / 11
            block = self.block(kind, text, size_pt, width)
            if block.lines in seen:
                continue
            seen.add(block.lines)
            outer = self.outer_size(kind, block.width, block.height)
            if outer[0] > max_w + 0.01 or outer[1] > max_h + 0.01:
                continue
            score = abs(math.log(outer[0] / outer[1] / self.s.preferred_aspect)) + 1.0 * block.hyphens
            if best is None or score < best[0] - 1e-9:
                best = (score, _Fit(size_pt, block, outer))
        return best[1] if best else None

    def fit_any(self, kind: str, text: str, size_pt: float, max_w: float) -> _Fit:
        """Repli sans contrainte de hauteur (texte trop long) : tout le texte, rien de coupé."""
        inner_w, _ = self.inner_size(kind, max_w, max_w)
        block = self.block(kind, text, size_pt, inner_w)
        return _Fit(size_pt, block, self.outer_size(kind, block.width, block.height))

    # formes -----------------------------------------------------------------------------
    def shape(self, kind: str, box: Box, tail: Point | None, seed: int) -> Shape:
        s = self.s
        if kind == "narration":
            body = rect_points(box, 0)
            return Shape((tuple(body),), s.narration_fill, s.bubble_stroke, self.pt(s.narration_stroke_pt))
        if kind == "thought":
            body = cloud_points(box, self.mm(s.cloud.bump_mm), self.mm(s.cloud.amplitude_mm))
        elif kind == "shout":
            body = spiky_points(box, self.mm(s.shout.spike_mm), self.mm(s.shout.spike_every_mm), s.shout.jitter, seed)
        elif kind == "speech" and s.speech_shape == "rounded":
            body = rect_points(box, self.mm(s.rounded_radius_mm))
        else:
            body = ellipse_points(box.cx, box.cy, box.w / 2, box.h / 2)
        polys: list[tuple[Point, ...]] = [tuple(body)]
        if tail is not None:
            inner = box.inset(self._extra(kind)) if kind in ("thought", "shout") else box
            polys += [tuple(p) for p in tail_polygons(kind, inner, tail, self.mm(s.tail.base_mm), s.cloud.tail_bubbles)]
        return Shape(tuple(polys), s.bubble_fill, s.bubble_stroke, self.pt(s.stroke_pt))

    def lines(self, kind: str, block: TextBlock, box: Box) -> list[TextLine]:
        st = self.fonts.style(kind)
        top = box.cy - block.height / 2
        return [
            TextLine(self.fonts.drawable(st, text), _r(box.cx), _r(top + block.cap + i * block.line_px), width)
            for i, (text, width) in enumerate(zip(block.lines, block.widths, strict=True))
        ]

    # placement --------------------------------------------------------------------------
    def place_sequence(
        self,
        sizes: Sequence[tuple[float, float]],
        region: Box,
        obstacles: Sequence[Box],
        direction: Direction,
        tails: Callable[[int, Box], list[Box]] | None = None,
        fits: Callable[[Box], bool] | None = None,
    ) -> list[Box] | None:
        """Pose les bulles dans l'ordre de lecture ; None si l'une d'elles ne trouve pas de place.

        `tails(i, cadre)` donne l'emprise de la queue de la bulle i : une bulle ne recouvre pas la
        queue d'une précédente et sa queue ne traverse pas une bulle déjà posée. `fits(cadre)` (case
        en biais) : le cadre doit être entièrement dans le polygone de la case.
        """
        step = max(1.0, self.mm(self.s.grid_mm))
        gap = self.mm(self.s.spacing_mm)
        placed: list[Box] = []
        tail_boxes: list[Box] = []
        prev: Box | None = None
        for i, (w, h) in enumerate(sizes):
            if w > region.w + 0.01 or h > region.h + 0.01:
                return None
            xs = _steps(region.x1, region.x2 - w, step)
            if direction == "rtl":
                xs.reverse()
            found: Box | None = None
            for y in _steps(region.y1, region.y2 - h, step):
                if prev is not None and y < prev.y1:
                    continue
                for x in xs:
                    cand = Box(x, y, x + w, y + h)
                    if prev is not None and cand.y1 < prev.y2:  # même bande : plus loin dans la lecture
                        if direction == "ltr" and cand.x1 < prev.x2 + gap:
                            continue
                        if direction == "rtl" and cand.x2 > prev.x1 - gap:
                            continue
                    if any(cand.intersects(o, gap) for o in placed):
                        continue
                    if any(cand.intersects(o) for o in obstacles) or any(cand.intersects(t) for t in tail_boxes):
                        continue
                    if fits is not None and not fits(cand):
                        continue
                    own = tails(i, cand) if tails else []
                    if any(t.intersects(o) for t in own for o in placed):
                        continue
                    found = cand
                    tail_boxes += own
                    break
                if found:
                    break
            if found is None:
                return None
            placed.append(found)
            prev = found
        return placed

    def tail_boxes(self, b: BubbleSpec, box: Box, panel: PanelSpec, direction: Direction) -> list[Box]:
        """Emprise approximative de la queue : quelques carrés le long du segment bord → pointe."""
        tip = self.tail_tip(b, box, panel, direction)
        if tip is None:
            return []
        edge = ellipse_boundary(box, math.atan2(tip[1] - box.cy, tip[0] - box.cx))
        r = self.mm(self.s.tail.base_mm) / 2
        out = []
        for k in range(1, 5):
            x, y = edge[0] + (tip[0] - edge[0]) * k / 4, edge[1] + (tip[1] - edge[1]) * k / 4
            out.append(Box(x - r, y - r, x + r, y + r))
        return out

    def tail_tip(self, b: BubbleSpec, box: Box, panel: PanelSpec, direction: Direction) -> Point | None:
        if b.kind == "narration":
            return None
        if b.manual_tail is not None:
            return b.manual_tail
        p = panel.box
        tl = self.s.tail
        if b.kind == "off" and panel.slanted:
            # Hors-champ : la pointe touche le bord de case le plus proche (polygone de la case).
            assert panel.polygon is not None
            return geo.nearest_on_boundary(panel.polygon, box.cx, box.cy)
        if b.kind == "off":
            # Hors-champ : la pointe touche le bord de case le plus proche.
            d = {"left": box.cx - p.x1, "right": p.x2 - box.cx, "top": box.cy - p.y1, "bottom": p.y2 - box.cy}
            edge = min(d, key=lambda k: (d[k], ["top", "left", "right", "bottom"].index(k)))
            return {
                "left": (p.x1, box.cy),
                "right": (p.x2, box.cy),
                "top": (box.cx, p.y1),
                "bottom": (box.cx, p.y2),
            }[edge]
        face = self._speaker_face(b, box, panel, direction)
        if face is not None:
            target = face.expand(self.mm(tl.face_gap_mm))
            dx, dy = target.cx - box.cx, target.cy - box.cy
            norm = math.hypot(dx, dy) or 1.0
            ux, uy = dx / norm, dy / norm
            t = _ray_entry(box.cx, box.cy, ux, uy, target)
            start = math.dist(ellipse_boundary(box, math.atan2(uy, ux)), (box.cx, box.cy))
            length = min(max(t - start, self.mm(tl.length_mm) * 0.5), self.mm(tl.max_length_mm))
        else:
            if tl.default_direction == "down":
                ux, uy = 0.0, 1.0
            else:
                pcx, pcy = geo.centroid(panel.polygon) if panel.slanted and panel.polygon else (p.cx, p.cy)
                dx, dy = pcx - box.cx, pcy - box.cy
                if math.hypot(dx, dy) < 1:
                    dx, dy = 0.0, 1.0
                norm = math.hypot(dx, dy)
                ux, uy = dx / norm, dy / norm
            start = math.dist(ellipse_boundary(box, math.atan2(uy, ux)), (box.cx, box.cy))
            length = self.mm(tl.length_mm)
        tip = (box.cx + ux * (start + length), box.cy + uy * (start + length))
        return panel.clamp(*tip)

    def _speaker_face(self, b: BubbleSpec, box: Box, panel: PanelSpec, direction: Direction) -> Box | None:
        if not panel.faces:
            return None
        faces = sorted(panel.faces, key=lambda f: (f.x1, f.y1) if direction == "ltr" else (-f.x2, f.y1))
        names = [c.casefold() for c in panel.characters]
        speaker = b.speaker.casefold()
        if speaker and speaker in names and names.index(speaker) < len(faces):
            return faces[names.index(speaker)]
        if len(faces) == 1:
            return faces[0]
        return min(faces, key=lambda f: math.dist((f.cx, f.cy), (box.cx, box.cy)))

    # page -------------------------------------------------------------------------------
    def letter_panel(self, panel: PanelSpec, direction: Direction) -> PageLettering:
        warnings: list[LetteringWarning] = []
        out: dict[int, BubbleLayout] = {}
        inner = panel.box.inset(self.mm(self.s.panel_margin_mm))
        faces = [f.expand(self.mm(self.s.face_margin_mm)) for f in panel.faces]
        faces += [o.expand(self.mm(self.s.spacing_mm)) for o in panel.obstacles]
        label = f"Case {panel.index + 1}"
        fits: Callable[[Box], bool] | None = None
        if panel.slanted:
            assert panel.polygon is not None
            planes = geo.edges(geo.inset(panel.polygon, self.mm(self.s.panel_margin_mm)) or panel.polygon)

            def fits(box: Box) -> bool:
                return geo.contains_box(planes, box.x1, box.y1, box.x2, box.y2)

        manual = [b for b in panel.bubbles if b.manual_box is not None]
        auto = [b for b in panel.bubbles if b.manual_box is None]
        for b in manual:
            assert b.manual_box is not None
            text = self._text(b)
            fit = next(
                (
                    f
                    for size in self.sizes(b.kind)
                    if (f := self.fit(b.kind, text, size, b.manual_box.w, b.manual_box.h))
                ),
                None,
            )
            overflow = fit is None
            if fit is None:
                fit = self.fit_any(b.kind, text, self.sizes(b.kind)[-1], b.manual_box.w)
            out[b.id] = self._layout(b, panel, b.manual_box, fit, direction, overflow=overflow)
            if overflow:
                warnings.append(self._overflow(label, b, panel))

        if auto:
            texts = [self._text(b) for b in auto]
            obstacles = [o.box for o in out.values()]
            obstacles += [t for b in manual if b.manual_box for t in self.tail_boxes(b, b.manual_box, panel, direction)]

            def tails(i: int, box: Box) -> list[Box]:
                return self.tail_boxes(auto[i], box, panel, direction)

            regions = [r for r in ((panel.zone.intersection(inner) if panel.zone else None), inner) if r is not None]
            steps = max(len(self.sizes(b.kind)) for b in auto)
            placed: tuple[list[_Fit], list[Box]] | None = None
            for k in range(steps):
                for region in regions:
                    fitted: list[_Fit] = []
                    for b, text in zip(auto, texts, strict=True):
                        sizes = self.sizes(b.kind)
                        f = self.fit(b.kind, text, sizes[min(k, len(sizes) - 1)], region.w, region.h)
                        if f is None:
                            break
                        fitted.append(f)
                    else:
                        boxes = self.place_sequence(
                            [f.outer for f in fitted], region, [*faces, *obstacles], direction, tails, fits
                        )
                        if boxes is not None:
                            placed = (fitted, boxes)
                            break
                if placed:
                    break
            overflow_ids: set[int] = set()
            if placed is None:
                # Plus de place hors des visages : on les ignore (avertissement), puis on empile.
                fitted = []
                for b, text in zip(auto, texts, strict=True):
                    size = self.sizes(b.kind)[-1]
                    f = self.fit(b.kind, text, size, inner.w, inner.h)
                    if f is None:
                        overflow_ids.add(b.id)
                        f = self.fit_any(b.kind, text, size, inner.w)
                    fitted.append(f)
                boxes = None
                if not overflow_ids:
                    hard = [*obstacles, *panel.obstacles]
                    boxes = self.place_sequence([f.outer for f in fitted], inner, hard, direction, tails, fits)
                    if boxes is not None and panel.faces:
                        warnings.append(
                            LetteringWarning(
                                "faces_covered",
                                f"{label} : pas assez de place hors des visages, une bulle chevauche un visage.",
                                panel.id,
                            )
                        )
                if boxes is None:
                    boxes = self._stack([f.outer for f in fitted], inner, direction)
                    overflow_ids |= {b.id for b in auto}
                placed = (fitted, boxes)
            for b, f, box in zip(auto, placed[0], placed[1], strict=True):
                overflow = b.id in overflow_ids
                out[b.id] = self._layout(b, panel, box, f, direction, overflow=overflow)
                if overflow:
                    warnings.append(self._overflow(label, b, panel))
        ordered = [out[b.id] for b in panel.bubbles]
        return PageLettering(ordered, warnings)

    def _stack(self, sizes: Sequence[tuple[float, float]], region: Box, direction: Direction) -> list[Box]:
        """Dernier recours : bulles empilées depuis le coin de début de lecture (chevauchements possibles)."""
        out, y = [], region.y1
        for w, h in sizes:
            x = region.x1 if direction == "ltr" else region.x2 - w
            out.append(Box(x, y, x + w, y + h))
            y = min(y + h, max(region.y1, region.y2 - h))
        return out

    def _text(self, b: BubbleSpec) -> str:
        return normalize_text(b.text, uppercase=self.fonts.style(b.kind).uppercase)

    def _overflow(self, label: str, b: BubbleSpec, panel: PanelSpec) -> LetteringWarning:
        who = f" de {b.speaker}" if b.speaker else ""
        excerpt = b.text if len(b.text) <= 30 else b.text[:29] + "…"
        return LetteringWarning(
            "text_overflow",
            f"{label} : texte trop long pour la bulle {b.order + 1}{who} (« {excerpt} ») — "
            "raccourcis-le ou agrandis la bulle ; rien n'est coupé.",
            panel.id,
            b.id,
        )

    def _layout(
        self, b: BubbleSpec, panel: PanelSpec, box: Box, fit: _Fit, direction: Direction, *, overflow: bool
    ) -> BubbleLayout:
        box = Box(_r(box.x1), _r(box.y1), _r(box.x2), _r(box.y2))
        tail = self.tail_tip(b, box, panel, direction)
        if tail is not None:
            tail = (_r(tail[0]), _r(tail[1]))
        st = self.fonts.style(b.kind)
        return BubbleLayout(
            id=b.id,
            panel_id=panel.id,
            kind=b.kind,
            text=b.text,
            speaker=b.speaker,
            box=box,
            tail=tail,
            style=st,
            family=self.fonts.family(st),
            size_pt=fit.size_pt,
            size_px=fit.block.size_px,
            lines=self.lines(b.kind, fit.block, box),
            shape=self.shape(b.kind, box, tail, seed=b.id),
            manual=b.manual_box is not None,
            manual_tail=b.manual_tail is not None,
            overflow=overflow,
        )

    def letter_page(self, panels: Sequence[PanelSpec], direction: Direction, page: Box | None = None) -> PageLettering:
        """Bulles de chaque case, puis onomatopées (elles peuvent déborder sur une voisine : toutes les
        bulles de la page sont déjà posées). `page` : cadre de la page finie, jamais dépassé."""
        bubbles: list[BubbleLayout] = []
        warnings: list[LetteringWarning] = []
        for panel in panels:
            res = self.letter_panel(panel, direction)
            bubbles += res.bubbles
            warnings += res.warnings
        sfx: list[SfxLayout] = []
        if any(p.sfx for p in panels):
            taken: list[list[Point]] = [_box_poly(b.box) for b in bubbles]
            taken += [_box_poly(o) for p in panels for o in p.obstacles]
            faces = [_box_poly(f.expand(self.mm(self.s.sfx.face_margin_mm))) for p in panels for f in p.faces]
            for panel in panels:
                for spec in panel.sfx:
                    lay, warn = self.letter_sfx(panel, spec, direction, faces, taken, page)
                    sfx.append(lay)
                    taken.append(lay.quad)
                    warnings += warn
        return PageLettering(bubbles, warnings, sfx)

    # onomatopées ---------------------------------------------------------------------------
    def sfx_style(self, spec: SfxSpec, size_pt: float) -> tuple[str, TextStyle]:
        font_id = self.preset.sfx_font(spec.intensity, spec.font)
        cfg = self.preset.sfx
        st = TextStyle(
            font=font_id,
            size_pt=size_pt,
            min_size_pt=size_pt,
            line_height=cfg.line_height if cfg else 0.95,
            uppercase=cfg.uppercase if cfg else True,
            color=self.s.sfx.fill,
        )
        return font_id, st

    def sfx_auto_size(self, panel: PanelSpec, intensity: str) -> float:
        c = self.s.sfx
        side_mm = min(panel.box.w, panel.box.h) / self.dpi * MM_PER_INCH
        scale = min(max(side_mm / c.reference_panel_mm, c.scale_min), c.scale_max)
        return round(min(max(c.size_pt[intensity] * scale, c.min_size_pt), c.max_size_pt), 1)  # type: ignore[index]

    def sfx_block(self, spec: SfxSpec, size_pt: float) -> tuple[str, TextStyle, list[TextLine], tuple[float, float]]:
        """Lignes centrées sur l'origine (encre réelle : accents compris) et demi-taille du contour."""
        font_id, st = self.sfx_style(spec, size_pt)
        font = self.fonts.pil(st, self.pt(size_pt))
        text = normalize_text(spec.text, uppercase=st.uppercase)
        raw = [ln for ln in text.split("\n") if ln.strip()] or [text or " "]
        size_px = self.pt(size_pt)
        line_px = size_px * st.line_height
        drawn = [self.fonts.drawable(st, ln) for ln in raw]
        boxes = [font.getbbox(ln, anchor="ms") for ln in drawn]
        tops = [i * line_px + b[1] for i, b in enumerate(boxes)]
        bottoms = [i * line_px + b[3] for i, b in enumerate(boxes)]
        left, right = min(b[0] for b in boxes), max(b[2] for b in boxes)
        top, bottom = min(tops), max(bottoms)
        dx, dy = -(left + right) / 2, -(top + bottom) / 2
        lines = [TextLine(ln, _r(dx), _r(i * line_px + dy), font.getlength(ln)) for i, ln in enumerate(drawn)]
        pad = self.pt(self.s.sfx.outline_pt + self.s.sfx.halo_pt)
        return font_id, st, lines, ((right - left) / 2 + pad, (bottom - top) / 2 + pad)

    def letter_sfx(
        self,
        panel: PanelSpec,
        spec: SfxSpec,
        direction: Direction,
        faces: Sequence[Sequence[Point]],
        taken: Sequence[Sequence[Point]],
        page: Box | None,
    ) -> tuple[SfxLayout, list[LetteringWarning]]:
        c: SfxSettings = self.s.sfx
        label = f"Case {panel.index + 1}"
        warnings: list[LetteringWarning] = []
        intensity = spec.intensity if spec.intensity in c.size_pt else "normal"
        rng = random.Random(f"sfx:{spec.id}")
        sign = rng.choice((-1.0, 1.0))
        auto_angle = sign * (c.angle_deg.min + (c.angle_deg.max - c.angle_deg.min) * rng.random())
        auto_skew = -sign * (c.skew_deg.min + (c.skew_deg.max - c.skew_deg.min) * rng.random())
        angle = float(spec.angle) if spec.angle is not None else round(auto_angle, 1)
        skew = float(spec.skew) if spec.skew is not None else round(auto_skew, 1)
        matrix = sfx_matrix(angle, skew)
        planes = geo.edges(panel.outline())
        limit = self.mm(c.max_overflow_mm)
        gap = self.mm(c.bubble_gap_mm)
        page_planes = geo.edges(_box_poly(page)) if page else []

        size = float(spec.size_pt) if spec.size_pt is not None else self.sfx_auto_size(panel, intensity)
        block = self.sfx_block(spec, size)
        if spec.size_pt is None:
            # Pas plus large que max_width × la case (texte long) : réduit par pas jusqu'au minimum.
            while 2 * block[3][0] > c.max_width * panel.box.w and size > c.min_size_pt:
                size = max(c.min_size_pt, round(size * 0.92, 1))
                block = self.sfx_block(spec, size)

        def quad_at(half: tuple[float, float], x: float, y: float) -> list[Point]:
            hw, hh = half
            return geo.affine(matrix, x, y, [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)])

        def within(q: Sequence[Point]) -> bool:
            if geo.overflow(planes, q) > limit + 1e-6:
                return False
            return not page_planes or geo.overflow(page_planes, q) <= 1e-6

        def free(q: Sequence[Point], with_faces: bool) -> bool:
            if any(geo.convex_overlap(q, o, gap) for o in taken):
                return False
            return not with_faces or not any(geo.convex_overlap(q, f) for f in faces)

        cx0, cy0 = geo.centroid(panel.outline())
        center: Point | None = None
        if spec.center is not None:
            # Placée à la main : gardée, sauf dépassement au-delà de la limite → ramenée vers le centre.
            tx, ty = spec.center
            shrunk = False
            for _ in range(8):
                if within(quad_at(block[3], cx0, cy0)):
                    break
                size = max(c.min_size_pt / 2, round(size * 0.85, 1))
                block = self.sfx_block(spec, size)
                shrunk = True
            if shrunk:
                warnings.append(self._sfx_warn("sfx_too_big", label, spec, panel, "réduite pour ne pas trop déborder"))
            if within(quad_at(block[3], tx, ty)):
                center = (tx, ty)
            else:
                lo, hi = 0.0, 1.0
                for _ in range(24):
                    mid = (lo + hi) / 2
                    if within(quad_at(block[3], cx0 + (tx - cx0) * mid, cy0 + (ty - cy0) * mid)):
                        lo = mid
                    else:
                        hi = mid
                center = (cx0 + (tx - cx0) * lo, cy0 + (ty - cy0) * lo)
        else:
            bx = panel.box
            tx = bx.x1 + bx.w * (0.68 if direction == "ltr" else 0.32)
            ty = bx.y1 + bx.h * 0.66
            step = max(1.0, self.mm(c.grid_mm))
            for attempt in range(6):
                half = block[3]
                cands = [
                    (x, y)
                    for y in _steps(bx.y1 - limit, bx.y2 + limit, step)
                    for x in _steps(bx.x1 - limit, bx.x2 + limit, step)
                ]
                cands.sort(key=lambda p: (round((p[0] - tx) ** 2 + (p[1] - ty) ** 2, 3), p[1], p[0]))
                for with_faces in (True, False):
                    center = next((p for p in cands if within(q := quad_at(half, *p)) and free(q, with_faces)), None)
                    if center is not None:
                        if not with_faces:
                            warnings.append(
                                self._sfx_warn("sfx_faces_covered", label, spec, panel, "chevauche un visage")
                            )
                        break
                if center is not None or attempt == 5:
                    break
                size = max(c.min_size_pt, round(size * 0.85, 1))
                block = self.sfx_block(spec, size)
            if center is None:
                center = (cx0, cy0)
                warnings.append(self._sfx_warn("sfx_no_room", label, spec, panel, "pas de place libre"))
        font_id, st, lines, half = block
        center = (_r(center[0]), _r(center[1]))
        quad = quad_at(half, *center)
        return (
            SfxLayout(
                id=spec.id,
                panel_id=panel.id,
                text=spec.text,
                intensity=intensity,
                font_id=font_id,
                style=st,
                family=self.fonts.family(st),
                size_pt=size,
                size_px=self.pt(size),
                angle=angle,
                skew=skew,
                center=center,
                lines=lines,
                half=half,
                quad=quad,
                outline_px=self.pt(c.outline_pt),
                halo_px=self.pt(c.halo_pt),
                fill=c.fill,
                outline=c.outline,
                halo=c.halo,
                manual=spec.center is not None,
                manual_size=spec.size_pt is not None,
                manual_angle=spec.angle is not None,
                manual_skew=spec.skew is not None,
                overflow_px=max(0.0, geo.overflow(planes, quad)),
            ),
            warnings,
        )

    def _sfx_warn(self, code: str, label: str, spec: SfxSpec, panel: PanelSpec, why: str) -> LetteringWarning:
        excerpt = spec.text if len(spec.text) <= 20 else spec.text[:19] + "…"
        return LetteringWarning(code, f"{label} : onomatopée « {excerpt} » {why}.", panel.id, spec.id)


def _box_poly(b: Box) -> list[Point]:
    return geo.rect_polygon(b.x1, b.y1, b.x2, b.y2)


def _steps(lo: float, hi: float, step: float) -> list[float]:
    if hi <= lo:
        return [lo]
    n = int((hi - lo) // step)
    out = [lo + i * step for i in range(n + 1)]
    if hi - out[-1] > 1e-6:
        out.append(hi)
    return out


def _ray_entry(ox: float, oy: float, ux: float, uy: float, box: Box) -> float:
    """Distance le long du rayon (o, u) à laquelle il entre dans `box` (0 si déjà dedans)."""
    t_lo, t_hi = -math.inf, math.inf
    for o, u, lo, hi in ((ox, ux, box.x1, box.x2), (oy, uy, box.y1, box.y2)):
        if abs(u) < 1e-9:
            if not lo <= o <= hi:
                return math.inf
            continue
        a, b = (lo - o) / u, (hi - o) / u
        t_lo, t_hi = max(t_lo, min(a, b)), min(t_hi, max(a, b))
    if t_hi < max(t_lo, 0):
        return math.inf
    return max(t_lo, 0.0)
