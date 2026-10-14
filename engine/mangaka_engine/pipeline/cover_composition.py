"""Composition de la couverture d'un tome : 1re de couverture, 4e de couverture, dos, couverture à plat, export.

Rien n'est dessiné par le modèle d'image : l'illustration (#159) n'a aucun texte, et tout le texte est posé ici,
en vectoriel, avec les polices réelles (`fonts.yaml`, instances statiques renommées `mk-…`, voir `fonts.py`) et
les couleurs de la palette de la série (#160). Réglages : `presets/cover_composition.yaml` ; gabarits de 4e :
`presets/back_layouts/`.

- **1re** (`compose_front`) : illustration retenue à fond perdu ; logo de la série (`logo.py`) dans sa zone
  réservée (`clear: true` du format), taille ajustable et centre déplaçable, toujours borné à la marge de
  sécurité ; sans logo, titre composé dans la police de repli (`texts.fallback_title`) et avertissement ;
  numéro de tome (badge, zone `tome`) ; nom d'auteur (zone `auteur`).
- **4e** (`compose_back`) : fond aux couleurs de la palette, accroche, résumé (retour à la ligne avec césure,
  taille réduite par pas jusqu'au minimum du style pour tenir dans le cadre, jamais coupé : au-delà, problème
  bloquant lisible), petite illustration (ratio de `back_illustration.aspect`), rappel du titre et du tome.
- **Dos** (`compose_spine`) : largeur = (pages / 2) × épaisseur d'une feuille + couverture ; titre vertical
  (lu de haut en bas) et numéro de tome.
- **Feuilles** (`build_sheet`) : 1re seule, 4e seule, ou couverture à plat (4e + dos + 1re en ltr ; 1re + dos +
  4e en rtl : la 1re est à gauche du dos). Fond perdu sur les bords extérieurs seulement, repères de coupe
  (et de pli du dos) en option, comme l'export d'un chapitre (`assembly.py`).

Chaque partie est une liste d'éléments (aplats, images, textes, logo) en px du format rogné ; le PNG (Pillow) et
le SVG (`<text>` avec police embarquée réduite aux caractères utilisés, accents compris) sont tirés de la même
liste : mêmes positions, mêmes tailles.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import re
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..presets import BackLayout, CoverCompositionSettings, CoverFormat, PresetError, PresetRegistry
from ..presets.schemas import BackBox, SpineSettings, TextStyle
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import Job, PanelImage, Volume, VolumeCover
from .assembly import Canvas, cover_crop, crop_mark_lines, png_bytes
from .back_cover import clean_summary, clean_tagline, sign_count
from .cover_charter import charter_format, series_charter
from .finishing import finished_art
from .fonts import FontBook, pt_to_px
from .jobs import JobReporter
from .lettering import LetteringError, normalize_text, wrap_text
from .logo import LogoError, LogoSpec, contrast, layout_logo, render_png_image, spec_problems
from .logo import render_svg as render_logo_svg

log = logging.getLogger("mangaka_engine")

STEP = "cover_export"
MM_PER_INCH = 25.4
LINE_CLEARANCE = 0.06  # écart minimal entre l'encre de deux lignes (× taille du texte)
PartKind = Literal["front", "back", "spine"]
PART_IDS = {"front": "premiere", "back": "quatrieme", "spine": "dos"}
PART_LABELS = {"front": "1re de couverture", "back": "4e de couverture", "spine": "Dos"}


class CompositionError(LetteringError):
    """Couverture impossible à composer ou à exporter (message lisible, en français)."""


def mm_px(mm: float, dpi: int) -> float:
    return mm / MM_PER_INCH * dpi


# --- géométrie -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def inset(self, d: float) -> Rect:
        return Rect(self.x + d, self.y + d, max(1.0, self.w - 2 * d), max(1.0, self.h - 2 * d))


def safe_rect(fmt: CoverFormat, width: float | None = None) -> Rect:
    """Zone de sécurité d'une face (format rogné moins la marge de sécurité), px du format rogné."""
    w, h = (width if width is not None else fmt.trim_px[0]), fmt.trim_px[1]
    s = mm_px(fmt.safety_mm, fmt.dpi)
    return Rect(s, s, w - 2 * s, h - 2 * s)


def zone_rect(fmt: CoverFormat, zone_id: str) -> Rect | None:
    zone = next((z for z in fmt.zones if z.id == zone_id), None)
    if zone is None and zone_id == "logo":
        zone = fmt.clear_zone
    if zone is None:
        return None
    d = fmt.dpi
    return Rect(mm_px(zone.x_mm, d), mm_px(zone.y_mm, d), mm_px(zone.width_mm, d), mm_px(zone.height_mm, d))


def box_rect(box: BackBox, safe: Rect) -> Rect:
    return Rect(safe.x + box.x * safe.w, safe.y + box.y * safe.h, box.width * safe.w, box.height * safe.h)


def aspect_rect(box: Rect, aspect: float, align: str = "center") -> Rect:
    """Plus grand rectangle de ratio `aspect` (largeur / hauteur) dans `box`, centré verticalement."""
    w = min(box.w, box.h * aspect)
    h = w / aspect
    x = box.x if align == "left" else box.x2 - w if align == "right" else box.cx - w / 2
    return Rect(x, box.cy - h / 2, w, h)


def spine_width_mm(settings: SpineSettings, pages: int) -> float:
    """Largeur du dos : (pages / 2, arrondi à la feuille) × épaisseur d'une feuille + couverture, au minimum."""
    sheets = math.ceil(max(0, pages) / 2)
    return round(max(settings.min_width_mm, sheets * settings.sheet_thickness_mm + settings.cover_mm), 2)


def flat_order(direction: str) -> list[PartKind]:
    """Faces de la couverture à plat, de gauche à droite (extérieur du livre) : en ltr la 1re est à droite du dos,
    en rtl (manga) à gauche."""
    return ["front", "spine", "back"] if direction == "rtl" else ["back", "spine", "front"]


# --- couleurs --------------------------------------------------------------------------------------------
def readable(bg: str, palette: dict[str, str]) -> str:
    """Couleur de texte la plus lisible sur `bg` : texte clair ou sombre de la palette, sinon blanc ou noir."""
    options = [palette[r] for r in ("texte-clair", "texte-sombre") if r in palette] or ["#ffffff", "#000000"]
    best = max(options, key=lambda c: contrast(c, bg))
    if contrast(best, bg) < 3:
        best = max(("#ffffff", "#000000"), key=lambda c: contrast(c, bg))
    return best


def role_color(palette: dict[str, str], roles: list[str], default: str) -> str:
    return next((palette[r] for r in roles if r in palette), default)


def accent_on(bg: str, palette: dict[str, str], roles: list[str], minimum: float = 3.0) -> str:
    """Première couleur de `roles` assez contrastée sur `bg`, sinon la couleur de texte la plus lisible."""
    for r in roles:
        c = palette.get(r)
        if c and contrast(c, bg) >= minimum:
            return c
    return readable(bg, palette)


# --- éléments ----------------------------------------------------------------------------------------------
@dataclass
class Fill:
    rect: Rect
    color: str
    radius: float = 0.0
    name: str = ""


@dataclass
class Picture:
    rect: Rect
    path: Path
    name: str = ""


@dataclass
class Line:
    text: str
    x: float
    y: float  # ligne de base


@dataclass
class Text:
    lines: list[Line]
    style: TextStyle
    size: float  # px
    fill: str
    anchor: Literal["start", "middle", "end"] = "start"
    stroke: str | None = None
    stroke_width: float = 0.0  # px hors de la lettre
    rotate: tuple[float, float] | None = None  # centre d'une rotation de 90° (sens horaire)
    name: str = ""


@dataclass
class LogoItem:
    rect: Rect
    spec: LogoSpec
    name: str = "logo"


Item = Fill | Picture | Text | LogoItem


@dataclass
class Notice:
    code: str
    message: str
    part: PartKind

    def to_json(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "part": self.part}


@dataclass
class Part:
    kind: PartKind
    width: int  # px du format rogné
    height: int
    background: str
    items: list[Item] = field(default_factory=list)
    warnings: list[Notice] = field(default_factory=list)
    problems: list[Notice] = field(default_factory=list)  # bloquants : export refusé

    def warn(self, code: str, message: str) -> None:
        self.warnings.append(Notice(code, message, self.kind))

    def fail(self, code: str, message: str) -> None:
        self.problems.append(Notice(code, message, self.kind))


# --- texte ----------------------------------------------------------------------------------------------------
@dataclass
class Fit:
    size_pt: float
    size: float  # px
    lines: list[tuple[str, float]]  # (texte, ligne de base depuis le haut du bloc)
    height: float
    width: float


def prepare_text(text: str, style: TextStyle) -> str:
    """Typographie française (espaces insécables), NFC (accents composés), majuscules si le style le veut."""
    text = unicodedata.normalize("NFC", text)
    paragraphs = [normalize_text(" ".join(p.split()), uppercase=style.uppercase) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def _sizes(style: TextStyle, start: float | None = None) -> list[float]:
    top = start if start is not None else style.size_pt
    out, size = [], top
    while size > style.min_size_pt + 1e-9:
        out.append(round(size, 3))
        size -= style.step_pt
    out.append(style.min_size_pt)
    return out


def fit_text(
    fonts: FontBook,
    style: TextStyle,
    text: str,
    width: float,
    height: float,
    dpi: int,
    *,
    wrap: bool = True,
    start_pt: float | None = None,
    paragraph_gap: float = 0.55,
    stroke: float = 0.0,
) -> Fit | None:
    """Plus grande taille (de `start_pt` ou `size_pt` à `min_size_pt`, par `step_pt`) à laquelle tout le texte
    tient dans `width` × `height` ; None s'il ne tient pas même au minimum (jamais de texte coupé).

    L'interligne vaut au moins `line_height` × taille, et s'élargit si besoin pour que la boîte réelle des glyphes
    d'une ligne (capitales accentuées É, À, Ç… et contour `stroke` compris) ne touche jamais la ligne précédente."""
    text = prepare_text(text, style)
    if not text:
        return None
    for pt in _sizes(style, start_pt):
        size = pt_to_px(pt, dpi)
        font = fonts.pil(style, size)

        def measure(s: str, font: Any = font) -> float:
            return float(font.getlength(fonts.drawable(style, s)))

        def ink(s: str, font: Any = font) -> tuple[float, float]:
            """(haut, bas) de l'encre de la ligne, relatifs à sa ligne de base (haut négatif), contour compris."""
            box = font.getbbox(fonts.drawable(style, s), anchor="ls")
            return box[1] - stroke, box[3] + stroke

        ascent, descent = font.getmetrics()
        step = size * style.line_height
        gap = LINE_CLEARANCE * size
        lines: list[tuple[str, float]] = []
        y = 0.0
        prev_bottom = 0.0
        for paragraph in text.split("\n\n"):
            rows = wrap_text(paragraph, measure, width) if wrap else [paragraph]
            for j, row in enumerate(rows):
                top, bottom = ink(row)
                if not lines:
                    y = max(float(ascent), -top)
                else:
                    y = max(y + (step * (1 + paragraph_gap) if j == 0 else step), y + prev_bottom - top + gap)
                lines.append((row, y))
                prev_bottom = bottom
        total = y + max(float(descent), prev_bottom)
        widest = max(measure(t) for t, _ in lines)
        if widest <= width + 0.5 and total <= height + 0.5:
            return Fit(pt, size, lines, total, widest)
    return None


def place(
    fit: Fit,
    rect: Rect,
    style: TextStyle,
    color: str,
    *,
    align: str = "center",
    valign: str = "middle",
    stroke: str | None = None,
    stroke_width: float = 0.0,
    name: str = "",
) -> Text:
    top = rect.y + (rect.h - fit.height) * {"top": 0.0, "middle": 0.5, "bottom": 1.0}[valign]
    anchor: Literal["start", "middle", "end"] = {"left": "start", "center": "middle", "right": "end"}[align]  # type: ignore[assignment]
    x = rect.x if align == "left" else rect.x2 if align == "right" else rect.cx
    return Text(
        lines=[Line(t, x, top + y) for t, y in fit.lines],
        style=style,
        size=fit.size,
        fill=color,
        anchor=anchor,
        stroke=stroke,
        stroke_width=stroke_width,
        name=name,
    )


# --- entrées ----------------------------------------------------------------------------------------------------
@dataclass
class CoverInputs:
    """Tout ce que la composition lit (sans session ouverte)."""

    fmt: CoverFormat
    settings: CoverCompositionSettings
    layout: BackLayout
    palette: dict[str, str]
    palette_name: str | None  # None : couleurs de repli (pas de palette retenue)
    title: str
    number: int
    author: str
    logo: LogoSpec | None
    logo_note: str | None  # logo présent mais inutilisable
    logo_placement: dict[str, float] | None
    front_image: Path | None
    back_image: Path | None
    back_image_note: str | None
    tagline: str
    summary: str
    pages: int
    direction: str


@dataclass
class Composition:
    front: Part
    back: Part
    spine: Part
    spine_mm: float
    inputs: CoverInputs

    def parts(self) -> dict[PartKind, Part]:
        return {"front": self.front, "back": self.back, "spine": self.spine}

    @property
    def warnings(self) -> list[Notice]:
        return [n for p in self.parts().values() for n in p.warnings]

    @property
    def problems(self) -> list[Notice]:
        return [n for p in self.parts().values() for n in p.problems]


# --- 1re de couverture -----------------------------------------------------------------------------------------
def logo_aspect(presets: PresetRegistry, spec: LogoSpec) -> float:
    lay = layout_logo(presets, spec, scale=1.0)
    return lay.width / lay.height


def logo_rect(
    fmt: CoverFormat, settings: CoverCompositionSettings, aspect: float, placement: dict[str, float] | None
) -> Rect:
    """Rectangle du logo (px du format rogné) : la plus grande taille qui tient dans la zone du logo × `scale`,
    centre choisi (fraction du format rogné ; défaut : centre de la zone), toujours dans la marge de sécurité."""
    trim_w, trim_h = fmt.trim_px
    safe = safe_rect(fmt)
    zone = zone_rect(fmt, "logo") or Rect(safe.x, safe.y, safe.w, safe.h * 0.25)
    bounds = settings.front.logo_scale
    raw = (placement or {}).get("scale")
    scale = min(bounds.max, max(bounds.min, float(raw if raw is not None else settings.front.default_logo_scale)))
    w = min(zone.w, zone.h * aspect) * scale
    w = min(w, safe.w, safe.h * aspect)
    h = w / aspect
    cx = float((placement or {}).get("cx", zone.cx / trim_w)) * trim_w
    cy = float((placement or {}).get("cy", zone.cy / trim_h)) * trim_h
    cx = min(max(cx, safe.x + w / 2), safe.x2 - w / 2)
    cy = min(max(cy, safe.y + h / 2), safe.y2 - h / 2)
    return Rect(cx - w / 2, cy - h / 2, w, h)


def compose_front(presets: PresetRegistry, fonts: FontBook, inp: CoverInputs) -> Part:
    fmt, s = inp.fmt, inp.settings
    trim_w, trim_h = fmt.trim_px
    dpi = fmt.dpi
    pal = inp.palette
    part = Part("front", trim_w, trim_h, role_color(pal, ["dominante", "secondaire"], "#333333"))
    bleed = mm_px(fmt.bleed_mm, dpi)
    if inp.front_image is not None:
        part.items.append(
            Picture(Rect(-bleed, -bleed, trim_w + 2 * bleed, trim_h + 2 * bleed), inp.front_image, "illustration")
        )
    else:
        part.warn(
            "no_illustration", "Pas d'illustration de 1re de couverture retenue : fond aux couleurs de la palette."
        )
    light, dark = pal.get("texte-clair", "#ffffff"), pal.get("texte-sombre", "#000000")
    outline = pt_to_px(s.front.outline_pt, dpi)

    # Logo de la série, sinon titre composé dans la police de repli.
    if inp.logo is not None:
        rect = logo_rect(fmt, s, logo_aspect(presets, inp.logo), inp.logo_placement)
        part.items.append(LogoItem(rect, inp.logo))
    else:
        zone = zone_rect(fmt, "logo") or Rect(*_band(safe_rect(fmt)))
        style = s.texts.fallback_title
        stroke = outline * 1.5
        fit = fit_text(fonts, style, inp.title, zone.w, zone.h, dpi, stroke=stroke)
        if fit is None:
            part.fail(
                "title_overflow",
                f"Le titre « {inp.title} » ne tient pas dans la zone du logo, même en {style.min_size_pt:g} pt.",
            )
        else:
            part.items.append(place(fit, zone, style, light, stroke=dark, stroke_width=stroke, name="titre"))
        reason = f" ({inp.logo_note})" if inp.logo_note else ""
        part.warn(
            "no_logo",
            f"La série n'a pas de logo utilisable{reason} : titre composé dans la police par défaut "
            "(fiche série › Identité visuelle pour créer le logo).",
        )

    # Numéro de tome : badge dans la zone « tome ».
    zone = zone_rect(fmt, "tome")
    if zone is not None:
        badge = pal.get("accent", pal.get("dominante", "#000000"))
        ink = readable(badge, pal)
        part.items.append(Fill(zone, badge, s.front.badge_radius * min(zone.w, zone.h), "badge-tome"))
        label = Rect(zone.x, zone.y + 0.08 * zone.h, zone.w, 0.24 * zone.h)
        number = Rect(zone.x + 0.08 * zone.w, zone.y + 0.32 * zone.h, 0.84 * zone.w, 0.6 * zone.h)
        fit = fit_text(fonts, s.texts.volume_label, "Tome", label.w * 0.9, label.h, dpi, wrap=False)
        if fit is not None:
            part.items.append(place(fit, label, s.texts.volume_label, ink, name="tome"))
        fit = fit_text(fonts, s.texts.volume_number, str(inp.number), number.w, number.h, dpi, wrap=False, start_pt=200)
        if fit is None:
            part.fail("number_overflow", "Le numéro de tome ne tient pas dans sa zone.")
        else:
            part.items.append(place(fit, number, s.texts.volume_number, ink, name="numero"))
    else:
        part.warn("no_zone", "Format sans zone « tome » : numéro de tome absent de la 1re de couverture.")

    # Nom d'auteur : zone « auteur ».
    zone = zone_rect(fmt, "auteur")
    if not inp.author.strip():
        part.warn("no_author", "Pas de nom d'auteur : renseigne-le (série ou tome) pour l'imprimer sur la 1re.")
    elif zone is not None:
        fit = fit_text(fonts, s.texts.author, inp.author, zone.w, zone.h, dpi)
        if fit is None:
            part.fail(
                "author_overflow",
                f"Le nom d'auteur ne tient pas dans sa zone, même en {s.texts.author.min_size_pt:g} pt.",
            )
        else:
            part.items.append(place(fit, zone, s.texts.author, light, stroke=dark, stroke_width=outline, name="auteur"))
    return part


def _band(safe: Rect) -> tuple[float, float, float, float]:
    return safe.x, safe.y, safe.w, safe.h * 0.25


# --- 4e de couverture -------------------------------------------------------------------------------------------
def summary_frame(fmt: CoverFormat, layout: BackLayout) -> tuple[Rect, Rect]:
    """(encart, cadre du texte) du résumé, px du format rogné."""
    box = box_rect(layout.summary, safe_rect(fmt))
    pad = mm_px(3.5, fmt.dpi) if layout.summary_panel else 0.0
    return box, box.inset(pad) if pad else box


def compose_back(fonts: FontBook, inp: CoverInputs) -> Part:
    fmt, s, layout = inp.fmt, inp.settings, inp.layout
    trim_w, trim_h = fmt.trim_px
    dpi = fmt.dpi
    pal = inp.palette
    bg = role_color(pal, layout.background, "#ffffff")
    part = Part("back", trim_w, trim_h, bg)
    safe = safe_rect(fmt)

    # Accroche.
    tagline = clean_tagline(inp.tagline)
    if tagline:
        box = box_rect(layout.tagline, safe)
        fit = fit_text(fonts, s.texts.tagline, tagline, box.w, box.h, dpi)
        if fit is None:
            part.fail(
                "tagline_overflow",
                f"L'accroche ne tient pas dans son cadre, même en {s.texts.tagline.min_size_pt:g} pt : raccourcis-la.",
            )
        else:
            color = accent_on(bg, pal, layout.tagline_color)
            part.items.append(place(fit, box, s.texts.tagline, color, align=layout.tagline.align, name="accroche"))
    else:
        part.warn("no_tagline", "Pas de phrase d'accroche.")

    # Petite illustration.
    aw, ah = s.back_illustration.aspect
    box = box_rect(layout.illustration, safe)
    rect = aspect_rect(box, aw / ah, layout.illustration.align)
    if inp.back_image is not None:
        part.items.append(Picture(rect, inp.back_image, "illustration"))
        try:
            with Image.open(inp.back_image) as im:
                iw, ih = im.size
            # Résolution à l'impression (image posée « au remplissage »).
            eff = min(iw / rect.w, ih / rect.h) * dpi
            if eff < dpi * 0.5:
                part.warn(
                    "low_dpi",
                    f"Illustration de 4e en {eff:.0f} dpi à l'impression (cible {dpi}) : génère-en une ou finalise la case.",
                )
        except OSError:
            part.fail("image_unreadable", "Illustration de 4e illisible dans data/.")
    else:
        part.warn(
            "no_back_illustration",
            inp.back_image_note or "Pas de petite illustration de 4e : choisis une case ou génère-en une.",
        )

    # Résumé, sur son encart.
    panel_box, frame = summary_frame(fmt, layout)
    summary = clean_summary(inp.summary)
    ground = bg
    if layout.summary_panel:
        ground = role_color(pal, layout.summary_panel, "#ffffff")
        part.items.append(Fill(panel_box, ground, mm_px(2, dpi), "encart"))
    if not summary:
        part.fail("no_summary", "Résumé de 4e vide : fais-le écrire par l'IA ou écris-le.")
    else:
        style = s.texts.summary
        fit = fit_text(fonts, style, summary, frame.w, frame.h, dpi)
        if fit is None:
            part.fail(
                "summary_overflow",
                f"Le résumé ne tient pas dans le cadre de la 4e de couverture, même en {style.min_size_pt:g} pt "
                f"({sign_count(summary)} signes) : raccourcis-le ou choisis un gabarit au cadre plus grand.",
            )
        else:
            part.items.append(
                place(fit, frame, style, readable(ground, pal), align=layout.summary.align, valign="top", name="resume")
            )
            if fit.size_pt < style.size_pt:
                part.warn("summary_shrunk", f"Résumé réduit à {fit.size_pt:g} pt pour tenir dans son cadre.")

    # Rappel du titre et du numéro de tome.
    box = box_rect(layout.title, safe)
    text = f"{inp.title} — Tome {inp.number}"
    style = s.texts.back_title
    fit = fit_text(fonts, style, text, box.w, box.h, dpi, wrap=False) or fit_text(fonts, style, text, box.w, box.h, dpi)
    if fit is None:
        part.fail("title_overflow", "Le rappel du titre ne tient pas en pied de 4e de couverture.")
    else:
        part.items.append(place(fit, box, style, readable(bg, pal), align=layout.title.align, name="titre"))
    return part


# --- dos -----------------------------------------------------------------------------------------------------------
def compose_spine(fonts: FontBook, inp: CoverInputs, width_mm: float) -> Part:
    fmt, s = inp.fmt, inp.settings
    dpi = fmt.dpi
    w = max(1, round(mm_px(width_mm, dpi)))
    h = fmt.trim_px[1]
    pal = inp.palette
    bg = role_color(pal, ["dominante", "secondaire"], "#333333")
    part = Part("spine", w, h, bg)
    ink = readable(bg, pal)
    margin = mm_px(fmt.safety_mm, dpi)

    # Numéro de tome en pied, à l'horizontale.
    number_box = Rect(0.12 * w, h - margin - 0.95 * w, 0.76 * w, 0.95 * w)
    style = s.texts.volume_number
    fit = fit_text(fonts, style, str(inp.number), number_box.w, number_box.h, dpi, wrap=False, start_pt=200)
    if fit is None:
        part.warn("spine_number", "Dos trop étroit pour le numéro de tome.")
        bottom = h - margin
    else:
        part.items.append(place(fit, number_box, style, ink, name="numero"))
        bottom = number_box.y - 0.5 * w

    # Titre vertical, lu de haut en bas.
    if width_mm < s.spine.title_min_width_mm:
        part.warn(
            "spine_narrow",
            f"Dos de {width_mm:g} mm : trop étroit pour le titre (au moins {s.spine.title_min_width_mm:g} mm).",
        )
        return part
    style = s.texts.spine_title
    length = bottom - margin
    title = prepare_text(inp.title, style).replace("\n\n", " ")
    start = min(72.0, s.spine.title_fill * w / dpi * 72)
    fit = fit_text(fonts, style, title, length, w * 0.9, dpi, wrap=False, start_pt=max(start, style.min_size_pt))
    if fit is None:
        part.warn("spine_title", "Titre trop long pour le dos, même au plus petit : absent du dos.")
        return part
    cx, cy = w / 2, margin + length / 2
    font = fonts.pil(style, fit.size)
    ascent, descent = font.getmetrics()
    baseline = cy + (ascent - descent) / 2
    part.items.append(
        Text([Line(fit.lines[0][0], cx, baseline)], style, fit.size, ink, "middle", rotate=(cx, cy), name="titre")
    )
    return part


def compose(presets: PresetRegistry, inp: CoverInputs) -> Composition:
    fonts = FontBook(presets)
    width = spine_width_mm(inp.settings.spine, inp.pages)
    comp = Composition(
        front=compose_front(presets, fonts, inp),
        back=compose_back(fonts, inp),
        spine=compose_spine(fonts, inp, width),
        spine_mm=width,
        inputs=inp,
    )
    if inp.palette_name is None:
        comp.front.warn(
            "no_palette", "La série n'a pas de palette retenue : couleurs par défaut (fiche série › Identité visuelle)."
        )
    return comp


# --- feuilles ------------------------------------------------------------------------------------------------------
@dataclass
class Slot:
    part: Part
    x: int  # bord gauche de la face rognée, dans la feuille
    y: int
    clip: tuple[int, int, int, int]  # x, y, largeur, hauteur dans la feuille (fond perdu extérieur compris)


@dataclass
class Sheet:
    name: str
    width: int
    height: int
    dpi: int
    canvas: Canvas
    slots: list[Slot]
    folds: list[int]  # abscisses des plis (bords du dos)


def build_sheet(
    name: str, parts: list[Part], fmt: CoverFormat, presets: PresetRegistry, *, bleed: bool, crop_marks: bool
) -> Sheet:
    """Faces posées de gauche à droite ; fond perdu sur les bords extérieurs seulement."""
    dpi = fmt.dpi
    b = round(mm_px(fmt.bleed_mm, dpi)) if bleed else 0
    slug = round(mm_px(presets.lettering.crop_marks.slug_mm, dpi)) if crop_marks else 0
    margin = b + slug
    trim_w = sum(p.width for p in parts)
    trim_h = parts[0].height
    slots: list[Slot] = []
    folds: list[int] = []
    x = margin
    for i, p in enumerate(parts):
        left = b if i == 0 else 0
        right = b if i == len(parts) - 1 else 0
        slots.append(Slot(p, x, margin, (x - left, margin - b, p.width + left + right, p.height + 2 * b)))
        if p.kind == "spine":
            folds += [x, x + p.width]
        x += p.width
    canvas = Canvas(
        width=trim_w + 2 * margin,
        height=trim_h + 2 * margin,
        ox=margin,
        oy=margin,
        trim_w=trim_w,
        trim_h=trim_h,
        bleed=b,
        marks=crop_marks,
    )
    return Sheet(name, canvas.width, canvas.height, dpi, canvas, slots, folds)


def sheet_for(comp: Composition, which: str, presets: PresetRegistry, *, bleed: bool, crop_marks: bool) -> Sheet:
    fmt = comp.inputs.fmt
    if which == "front":
        return build_sheet("front", [comp.front], fmt, presets, bleed=bleed, crop_marks=crop_marks)
    if which == "back":
        return build_sheet("back", [comp.back], fmt, presets, bleed=bleed, crop_marks=crop_marks)
    if which == "spine":
        return build_sheet("spine", [comp.spine], fmt, presets, bleed=bleed, crop_marks=crop_marks)
    if which == "flat":
        parts = [comp.parts()[k] for k in flat_order(comp.inputs.direction)]
        return build_sheet("flat", parts, fmt, presets, bleed=bleed, crop_marks=crop_marks)
    raise CompositionError(f"face inconnue : « {which} »")


def mark_lines(sheet: Sheet, presets: PresetRegistry) -> list[tuple[float, float, float, float]]:
    """Repères de coupe aux quatre coins et repères de pli (bords du dos) en tête et en pied."""
    if not sheet.canvas.marks:
        return []
    settings = presets.lettering
    lines = crop_mark_lines(sheet.canvas, settings, sheet.dpi)
    cm = settings.crop_marks
    gap = max(sheet.canvas.bleed, round(mm_px(cm.offset_mm, sheet.dpi)))
    length = round(mm_px(cm.length_mm, sheet.dpi))
    t = sheet.canvas.trim
    for x in sheet.folds:
        lines.append((x, t.y1 - gap, x, t.y1 - gap - length))
        lines.append((x, t.y2 + gap, x, t.y2 + gap + length))
    return lines


# --- rendu PNG ------------------------------------------------------------------------------------------------------
def _hex(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


_ANCHORS = {"start": "ls", "middle": "ms", "end": "rs"}


def _draw_text(layer: Image.Image, item: Text, fonts: FontBook, ox: float, oy: float) -> None:
    font = fonts.pil(item.style, item.size)
    sw = round(item.stroke_width)
    kwargs: dict[str, Any] = {"font": font, "fill": (*_hex(item.fill), 255), "anchor": _ANCHORS[item.anchor]}
    if sw and item.stroke:
        kwargs.update(stroke_width=sw, stroke_fill=(*_hex(item.stroke), 255))
    if item.rotate is None:
        draw = ImageDraw.Draw(layer)
        for ln in item.lines:
            draw.text((ln.x + ox, ln.y + oy), fonts.drawable(item.style, ln.text), **kwargs)
        return
    # Rotation de 90° (sens horaire) autour de `rotate` : texte dessiné à plat sur une tuile, tournée, posée.
    cx, cy = item.rotate
    boxes = [
        font.getbbox(fonts.drawable(item.style, ln.text), anchor=kwargs["anchor"], stroke_width=sw) for ln in item.lines
    ]
    x1 = min(ln.x + b[0] for ln, b in zip(item.lines, boxes, strict=True)) - 2
    y1 = min(ln.y + b[1] for ln, b in zip(item.lines, boxes, strict=True)) - 2
    x2 = max(ln.x + b[2] for ln, b in zip(item.lines, boxes, strict=True)) + 2
    y2 = max(ln.y + b[3] for ln, b in zip(item.lines, boxes, strict=True)) + 2
    tile = Image.new("RGBA", (math.ceil(x2 - x1), math.ceil(y2 - y1)), (*_hex(item.fill), 0))
    draw = ImageDraw.Draw(tile)
    for ln in item.lines:
        draw.text((ln.x - x1, ln.y - y1), fonts.drawable(item.style, ln.text), **kwargs)
    turned = tile.rotate(-90, resample=Image.Resampling.BICUBIC, expand=True)
    ucx, ucy = x1 + tile.width / 2, y1 + tile.height / 2
    ncx, ncy = cx - (ucy - cy), cy + (ucx - cx)  # (dx, dy) → (−dy, dx)
    layer.alpha_composite(turned, (round(ncx + ox - turned.width / 2), round(ncy + oy - turned.height / 2)))


def _paste_rgba(layer: Image.Image, img: Image.Image, x: int, y: int) -> None:
    """`alpha_composite` borné à la tuile (une image peut déborder de la face : fond perdu)."""
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(img.width, layer.width - x), min(img.height, layer.height - y)
    if right <= left or bottom <= top:
        return
    layer.alpha_composite(img.crop((left, top, right, bottom)), (x + left, y + top))


def draw_part(layer: Image.Image, part: Part, presets: PresetRegistry, fonts: FontBook, ox: float, oy: float) -> None:
    draw = ImageDraw.Draw(layer)
    for item in part.items:
        if isinstance(item, Fill):
            r = item.rect
            box = (round(r.x + ox), round(r.y + oy), round(r.x2 + ox) - 1, round(r.y2 + oy) - 1)
            draw.rounded_rectangle(box, radius=round(item.radius), fill=(*_hex(item.color), 255))
        elif isinstance(item, Picture):
            r = item.rect
            x, y = round(r.x + ox), round(r.y + oy)
            w, h = round(r.x2 + ox) - x, round(r.y2 + oy) - y
            with Image.open(item.path) as src:
                rgb = src.convert("RGB")
            crop = cover_crop(rgb.width, rgb.height, w, h)
            _paste_rgba(layer, rgb.resize((w, h), Image.Resampling.LANCZOS, box=crop).convert("RGBA"), x, y)
        elif isinstance(item, Text):
            _draw_text(layer, item, fonts, ox, oy)
            draw = ImageDraw.Draw(layer)
        elif isinstance(item, LogoItem):
            r = item.rect
            x, y = round(r.x + ox), round(r.y + oy)
            w, h = round(r.x2 + ox) - x, round(r.y2 + oy) - y
            lay = layout_logo(presets, item.spec, scale=1.0)
            img = render_png_image(presets, item.spec, scale=w / lay.width)
            _paste_rgba(layer, img.resize((w, h), Image.Resampling.LANCZOS), x, y)


def render_png(sheet: Sheet, presets: PresetRegistry, fonts: FontBook) -> Image.Image:
    img = Image.new("RGB", (sheet.width, sheet.height), (255, 255, 255))
    for slot in sheet.slots:
        cx, cy, cw, ch = slot.clip
        layer = Image.new("RGBA", (cw, ch), (*_hex(slot.part.background), 255))
        draw_part(layer, slot.part, presets, fonts, slot.x - cx, slot.y - cy)
        img.paste(layer.convert("RGB"), (cx, cy))
    lines = mark_lines(sheet, presets)
    if lines:
        draw = ImageDraw.Draw(img)
        stroke = max(1, round(pt_to_px(presets.lettering.crop_marks.stroke_pt, sheet.dpi)))
        for x1, y1, x2, y2 in lines:
            draw.line((x1, y1, x2, y2), fill=(0, 0, 0), width=stroke)
    return img


# --- rendu SVG ------------------------------------------------------------------------------------------------------
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if v % 1 else str(int(v))


def _svg_text(item: Text, fonts: FontBook) -> str:
    attrs = (
        f'font-family="{fonts.family(item.style)}" font-size="{_f(round(item.size, 2))}" fill="{item.fill}" '
        f'text-anchor="{item.anchor}" xml:space="preserve"'
    )
    if item.stroke and item.stroke_width:
        attrs += (
            f' stroke="{item.stroke}" stroke-width="{_f(round(2 * item.stroke_width, 2))}" stroke-linejoin="round"'
            ' paint-order="stroke"'
        )
    rows = "".join(
        f'<text x="{_f(round(ln.x, 2))}" y="{_f(round(ln.y, 2))}" {attrs}>{escape(fonts.drawable(item.style, ln.text))}</text>'
        for ln in item.lines
    )
    transform = (
        f' transform="rotate(90 {_f(round(item.rotate[0], 2))} {_f(round(item.rotate[1], 2))})"' if item.rotate else ""
    )
    return f'<g class="{item.name or "texte"}"{transform}>{rows}</g>'


_SVG_OPEN = re.compile(r'<svg ([^>]*?)width="[^"]*" height="[^"]*"')


def _svg_logo(item: LogoItem, presets: PresetRegistry, fonts: FontBook) -> str:
    """Logo de la série (SVG autonome de `logo.py`) imbriqué à sa place ; sa police est renommée pour ne pas se
    mêler à un texte de la composition qui utiliserait la même police (sous-ensembles différents)."""
    svg = render_logo_svg(presets, item.spec)
    family = fonts.family(fonts.sfx_style(item.spec.font))
    svg = svg.replace(f'"{family}"', f'"{family}-logo"')
    svg = svg.split("?>", 1)[1].strip() if svg.startswith("<?xml") else svg
    r = item.rect
    place_attrs = (
        f'x="{_f(round(r.x, 2))}" y="{_f(round(r.y, 2))}" width="{_f(round(r.w, 2))}" height="{_f(round(r.h, 2))}"'
    )
    return _SVG_OPEN.sub(
        lambda m: f'<svg {m.group(1)}{place_attrs} preserveAspectRatio="none" class="logo"', svg, count=1
    )


def _data_uri(path: Path) -> str:
    mime = _MIME.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def render_svg(sheet: Sheet, presets: PresetRegistry, fonts: FontBook, title: str) -> str:
    dpi = sheet.dpi
    used: dict[str, tuple[TextStyle, set[str]]] = {}
    for slot in sheet.slots:
        for item in slot.part.items:
            if isinstance(item, Text):
                entry = used.setdefault(fonts.family(item.style), (item.style, set()))
                for ln in item.lines:
                    entry[1].update(fonts.drawable(item.style, ln.text))
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
        f'width="{sheet.width / dpi * MM_PER_INCH:.3f}mm" height="{sheet.height / dpi * MM_PER_INCH:.3f}mm" '
        f'viewBox="0 0 {sheet.width} {sheet.height}">',
        f"<title>{escape(title)}</title>",
        "<defs>",
        "<style>",
    ]
    for family, (style, chars) in sorted(used.items()):
        data = base64.b64encode(fonts.subset(style, "".join(sorted(chars)))).decode("ascii")
        out.append(f'@font-face{{font-family:"{family}";src:url(data:font/ttf;base64,{data}) format("truetype");}}')
    out.append("</style>")
    for i, slot in enumerate(sheet.slots):
        x, y, w, h = slot.clip
        out.append(f'<clipPath id="face-{i}"><rect x="{x}" y="{y}" width="{w}" height="{h}"/></clipPath>')
    out.append("</defs>")
    out.append(f'<rect width="{sheet.width}" height="{sheet.height}" fill="#ffffff"/>')
    # Fonds des faces d'abord, chacun 1 px sous la face suivante : aucun liseré blanc au pli (anticrénelage).
    for i, slot in enumerate(sheet.slots):
        x, y, w, h = slot.clip
        w += 1 if i < len(sheet.slots) - 1 else 0
        out.append(f'<rect class="fond" x="{x}" y="{y}" width="{w}" height="{h}" fill="{slot.part.background}"/>')
    for i, slot in enumerate(sheet.slots):
        part = slot.part
        out.append(f'<g id="{PART_IDS[part.kind]}" clip-path="url(#face-{i})">')
        out.append(f'<g transform="translate({slot.x} {slot.y})">')
        for item in part.items:
            if isinstance(item, Fill):
                r = item.rect
                rx = f' rx="{_f(round(item.radius, 2))}"' if item.radius else ""
                out.append(
                    f'<rect class="{item.name or "aplat"}" x="{_f(round(r.x, 2))}" y="{_f(round(r.y, 2))}" '
                    f'width="{_f(round(r.w, 2))}" height="{_f(round(r.h, 2))}"{rx} fill="{item.color}"/>'
                )
            elif isinstance(item, Picture):
                r = item.rect
                href = _data_uri(item.path)
                out.append(
                    f'<image class="{item.name or "image"}" x="{_f(round(r.x, 2))}" y="{_f(round(r.y, 2))}" '
                    f'width="{_f(round(r.w, 2))}" height="{_f(round(r.h, 2))}" preserveAspectRatio="xMidYMid slice" '
                    f'href="{href}" xlink:href="{href}"/>'
                )
            elif isinstance(item, Text):
                out.append(_svg_text(item, fonts))
            elif isinstance(item, LogoItem):
                out.append(_svg_logo(item, presets, fonts))
        out.append("</g></g>")
    lines = mark_lines(sheet, presets)
    if lines:
        stroke = _f(round(max(1.0, pt_to_px(presets.lettering.crop_marks.stroke_pt, dpi)), 2))
        out.append(f'<g id="reperes-de-coupe" stroke="#000000" stroke-width="{stroke}">')
        for x1, y1, x2, y2 in lines:
            out.append(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}"/>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


@dataclass
class RenderedSheet:
    png: bytes
    svg: str
    width: int
    height: int


def render_sheet(sheet: Sheet, presets: PresetRegistry, title: str) -> RenderedSheet:
    fonts = FontBook(presets)
    img = render_png(sheet, presets, fonts)
    return RenderedSheet(png_bytes(img, sheet.dpi), render_svg(sheet, presets, fonts, title), sheet.width, sheet.height)


def preview_png(sheet: Sheet, presets: PresetRegistry, max_width: int) -> bytes:
    """Aperçu : rendu complet (ce qui sera exporté), réduit à `max_width` px de large."""
    img = render_png(sheet, presets, FontBook(presets))
    if img.width > max_width:
        img = img.resize((max_width, max(1, round(img.height * max_width / img.width))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


# --- entrées depuis la base -------------------------------------------------------------------------------------------
def volume_pages(volume: Volume) -> int:
    """Pages du tome : celles de ses chapitres (à défaut de pages, le nombre de pages visé du chapitre)."""
    return sum(len(link.chapter.pages) or link.chapter.target_page_count for link in volume.chapter_links)


def series_palette(series: Any, settings: CoverCompositionSettings) -> tuple[dict[str, str], str | None]:
    """Palette retenue (rôle → couleur), complétée par les couleurs de repli ; nom (None : pas de palette)."""
    pal = dict(settings.fallback_palette)
    data = series.palette or None
    if not data:
        return pal, None
    for c in data.get("colors") or []:
        if isinstance(c, dict) and isinstance(c.get("role"), str) and isinstance(c.get("hex"), str):
            pal[c["role"]] = c["hex"].lower()
    return pal, str(data.get("name") or "Palette de la série")


def series_logo(presets: PresetRegistry, series: Any) -> tuple[LogoSpec | None, str | None]:
    """Dernière version du logo de la série, si elle se rend encore avec les presets (sinon la raison)."""
    if not series.logos:
        return None, None
    latest = max(series.logos, key=lambda lg: lg.version)
    try:
        spec = LogoSpec.model_validate(latest.spec)
    except ValueError:
        return None, "logo enregistré illisible"
    try:
        problems = spec_problems(presets, spec)
    except (PresetError, LogoError) as exc:
        return None, str(exc)
    return (None, problems[0]) if problems else (spec, None)


def back_layout_for(presets: PresetRegistry, volume: Volume) -> BackLayout:
    settings = presets.require_composition()
    for key in (volume.back_layout, settings.default_back_layout):
        if key and key in presets.back_layouts:
            return presets.back_layouts[key]
    return next(iter(presets.back_layouts.values()))


def panel_image_path(files: FileStore, img: PanelImage) -> Path:
    finished = finished_art(img, files)
    return finished[0] if finished is not None else files.absolute(img.path)


def tome_panel_images(volume: Volume) -> list[tuple[Any, Any, Any, PanelImage]]:
    """Versions retenues des cases du tome (chapitre, page, case, version), dans l'ordre de lecture."""
    from .render import selected_image  # import tardif : render importe beaucoup de modules

    out = []
    for link in volume.chapter_links:
        ch = link.chapter
        for page in sorted(ch.pages, key=lambda p: p.number):
            for panel in sorted(page.panels, key=lambda p: p.index):
                img = selected_image(panel)
                if img is not None:
                    out.append((ch, page, panel, img))
    return out


def back_image(session: Session, files: FileStore, volume: Volume) -> tuple[Path | None, str | None]:
    choice = volume.back_image or {}
    source, ident = choice.get("source"), choice.get("id")
    if not source or not isinstance(ident, int):
        return None, None
    if source == "panel":
        img = session.get(PanelImage, ident)
        allowed = {i.id for *_, i in tome_panel_images(volume)}
        if img is None or img.id not in allowed:
            return None, "La case choisie pour la 4e n'est plus une version retenue du tome : choisis-en une autre."
        path = panel_image_path(files, img)
    else:
        cover = session.get(VolumeCover, ident)
        if cover is None or cover.volume_id != volume.id or cover.kind != "back":
            return None, "L'illustration de 4e choisie a été supprimée : choisis-en une autre."
        path = files.absolute(cover.path)
    if not path.is_file():
        return None, "Fichier de l'illustration de 4e absent de data/."
    return path, None


def composition_inputs(session: Session, presets: PresetRegistry, files: FileStore, volume: Volume) -> CoverInputs:
    settings = presets.require_composition()
    series = volume.project
    # Zone du logo selon la charte des couvertures de la série (position du logo par défaut).
    fmt = charter_format(presets.cover_format(volume.cover_format), series_charter(presets, series))
    palette, palette_name = series_palette(series, settings)
    logo, logo_note = series_logo(presets, series)
    front = next((c for c in volume.covers if c.id == volume.selected_cover_id and c.kind == "front"), None)
    front_path = files.absolute(front.path) if front is not None else None
    if front_path is not None and not front_path.is_file():
        front_path = None
    back_path, back_note = back_image(session, files, volume)
    placement = (volume.cover_layout or {}).get("logo")
    return CoverInputs(
        fmt=fmt,
        settings=settings,
        layout=back_layout_for(presets, volume),
        palette=palette,
        palette_name=palette_name,
        title=series.title,
        number=volume.number,
        author=(volume.author or series.author or "").strip(),
        logo=logo,
        logo_note=logo_note,
        logo_placement=placement if isinstance(placement, dict) else None,
        front_image=front_path,
        back_image=back_path,
        back_image_note=back_note,
        tagline=volume.back_tagline or "",
        summary=volume.back_summary or "",
        pages=volume_pages(volume),
        direction=str(
            series.reading_direction.value if hasattr(series.reading_direction, "value") else series.reading_direction
        ),
    )


# --- export --------------------------------------------------------------------------------------------------------
def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "serie"


def export_name(series_title: str, number: int, job_id: int) -> str:
    return f"{_slug(series_title)}-tome{number:02d}-couverture-{job_id}.zip"


EXPORT_FILES = (("front", "1re-de-couverture"), ("back", "4e-de-couverture"), ("flat", "couverture-a-plat"))


def export_job(
    db: Database,
    presets: PresetRegistry,
    files: FileStore,
    volume_id: int,
    job_id: int,
    *,
    bleed: bool,
    crop_marks: bool,
) -> Callable[[JobReporter], str]:
    """Job « Exporter la couverture » : 1re seule, 4e seule et couverture à plat, chacune en PNG (DPI du format) +
    SVG, dans un ZIP (avec le texte de la 4e). Refusé tant qu'un problème bloquant reste (résumé trop long…)."""

    def run(report: JobReporter) -> str:
        report(2, "Lecture du tome…")
        with db.session_scope() as session:
            volume = session.get(Volume, volume_id)
            if volume is None:
                raise CompositionError("tome supprimé pendant l'export")
            try:
                inputs = composition_inputs(session, presets, files, volume)
            except PresetError as exc:
                raise CompositionError(str(exc)) from None
            series_title = volume.project.title
            number = volume.number
        report(6, "Composition de la 1re, de la 4e et du dos…")
        comp = compose(presets, inputs)
        if comp.problems:
            raise CompositionError(" ; ".join(n.message for n in comp.problems))
        name = export_name(series_title, number, job_id)
        rel = f"exports/volume-{volume_id}/{name}"
        buf = io.BytesIO()
        sizes: dict[str, list[int]] = {}
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, (which, stem) in enumerate(EXPORT_FILES):
                label = {"front": "1re de couverture", "back": "4e de couverture", "flat": "couverture à plat"}[which]
                report(10 + 28 * i, f"Rendu : {label} (PNG + SVG)…")
                sheet = sheet_for(comp, which, presets, bleed=bleed, crop_marks=crop_marks)
                rendered = render_sheet(sheet, presets, f"{series_title} — tome {number} — {label}")
                zf.writestr(f"{stem}.png", rendered.png)
                zf.writestr(f"{stem}.svg", rendered.svg)
                sizes[stem] = [rendered.width, rendered.height]
            text = f"{clean_tagline(inputs.tagline)}\n\n{clean_summary(inputs.summary)}\n"
            zf.writestr("4e-de-couverture-texte.txt", text)
        report(96, "Écriture du ZIP…")
        target = files.absolute(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(buf.getvalue())
        warnings = [n.to_json() for n in comp.warnings]
        with db.session_scope() as session:
            job = session.get(Job, job_id)
            params = dict(job.params or {}) if job else {}
            params.update(
                {
                    "file": rel,
                    "filename": name,
                    "sizes": sizes,
                    "spine_mm": comp.spine_mm,
                    "order": flat_order(inputs.direction),
                    "warnings": warnings,
                }
            )
            session.execute(update(Job).where(Job.id == job_id).values(params=params))
            session.commit()
        tail = f" · {len(warnings)} avertissement{'s' if len(warnings) > 1 else ''}" if warnings else ""
        return f"Couverture exportée : 1re, 4e et à plat (dos {comp.spine_mm:g} mm){tail}"

    return run


def composition_json(comp: Composition) -> dict[str, Any]:
    """Résumé lisible d'une composition (taille du résumé, dos, ordre à plat) pour l'API."""
    inp = comp.inputs
    summary = next((i for i in comp.back.items if isinstance(i, Text) and i.name == "resume"), None)
    return {
        "spine_mm": comp.spine_mm,
        "pages": inp.pages,
        "order": flat_order(inp.direction),
        "summary_size_pt": round(summary.size / inp.fmt.dpi * 72, 2) if summary else None,
        "warnings": [n.to_json() for n in comp.warnings],
        "problems": [n.to_json() for n in comp.problems],
    }
