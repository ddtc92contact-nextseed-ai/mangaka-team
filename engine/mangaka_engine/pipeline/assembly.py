"""Étape 5 — assemblage de la planche et rendu PNG (300 DPI) / SVG (texte vectoriel).

Pour chaque case, la version retenue est recadrée « au remplissage » (centrée, sans déformation)
aux coordonnées du découpage ; une case sans image devient un aplat gris « case manquante ». Les
bordures de case viennent du preset de lettrage, les marges et gouttières du découpage (format de
page). Les bulles (voir `lettering.py`) sont posées par-dessus.

Géométrie de la feuille (`Canvas`) : la page finie (« format rogné ») mesure
`round(mm / 25,4 × dpi)` px. Avec le fond perdu, la feuille mesure
`round((largeur + 2 × fond perdu) / 25,4 × dpi)` px — A4 + 3 mm à 300 DPI = 2551 × 3579 px — et la
page y est décalée de `round(fond perdu / 25,4 × dpi)` px (35 px) ; une case qui touche le bord de la
page déborde dans le fond perdu. Les repères de coupe, en option, sont dessinés dans une bande
supplémentaire (`crop_marks.slug_mm`) autour du fond perdu.

Case en biais (polygone convexe du découpage) : l'image, générée à la taille de la boîte englobante,
est recadrée sur cette boîte puis découpée au polygone par un masque anticrénelé (sur-échantillonné) ;
la bordure suit les bords du polygone (bande intérieure, comme pour un rectangle). Une case droite
garde exactement le rendu d'avant.

Le SVG reprend exactement la même géométrie : images embarquées (fichiers d'origine, recadrage
par `preserveAspectRatio="xMidYMid slice"`), texte en vraies balises `<text>` sélectionnables avec
la police embarquée (sous-ensemble des caractères utilisés), formes de bulle en chemins.
"""

from __future__ import annotations

import base64
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from PIL import Image, ImageChops, ImageDraw

from ..presets.schemas import LetteringSettings, PageFormat, TextStyle
from . import geometry as geo
from .fonts import FontBook, pt_to_px
from .lettering import MM_PER_INCH, Box, BubbleLayout, LetteringWarning, PageLettering, Shape, normalize_text


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    ox: int  # décalage de la page finie dans la feuille
    oy: int
    trim_w: int
    trim_h: int
    bleed: int  # px de fond perdu (0 sans)
    marks: bool

    @property
    def trim(self) -> Box:
        return Box(self.ox, self.oy, self.ox + self.trim_w, self.oy + self.trim_h)


def _px(mm: float, dpi: int) -> int:
    return round(mm / MM_PER_INCH * dpi)


def canvas_geometry(
    fmt: PageFormat, settings: LetteringSettings, *, bleed: bool = False, crop_marks: bool = False
) -> Canvas:
    """Taille de la feuille et position de la page finie, calculées depuis les mm du preset."""
    bleed_mm = fmt.bleed_mm if bleed else 0.0
    slug_mm = settings.crop_marks.slug_mm if crop_marks else 0.0
    margin_mm = bleed_mm + slug_mm
    return Canvas(
        width=_px(fmt.width_mm + 2 * margin_mm, fmt.dpi),
        height=_px(fmt.height_mm + 2 * margin_mm, fmt.dpi),
        ox=_px(margin_mm, fmt.dpi),
        oy=_px(margin_mm, fmt.dpi),
        trim_w=fmt.width_px,
        trim_h=fmt.height_px,
        bleed=_px(bleed_mm, fmt.dpi),
        marks=crop_marks,
    )


@dataclass
class PanelArt:
    id: int
    index: int
    box: Box  # px de la page finie
    image: Path | None = None  # fichier de la version retenue (None = case manquante)
    image_size: tuple[int, int] | None = None
    polygon: list[geo.Point] | None = None  # px de la page finie ; None ou rectangle = case droite

    @property
    def slanted(self) -> bool:
        return self.polygon is not None and len(self.polygon) >= 3 and not geo.is_axis_rect(self.polygon)


@dataclass
class PageArt:
    number: int
    fmt: PageFormat
    panels: list[PanelArt]
    lettering: PageLettering
    warnings: list[LetteringWarning] = field(default_factory=list)


def _hex(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def panel_rect(panel: PanelArt, canvas: Canvas) -> Box:
    """Cadre de la case dans la feuille ; une case au bord de la page déborde dans le fond perdu."""
    b = panel.box
    x1, y1, x2, y2 = b.x1 + canvas.ox, b.y1 + canvas.oy, b.x2 + canvas.ox, b.y2 + canvas.oy
    if canvas.bleed:
        if b.x1 <= 0:
            x1 -= canvas.bleed
        if b.y1 <= 0:
            y1 -= canvas.bleed
        if b.x2 >= canvas.trim_w:
            x2 += canvas.bleed
        if b.y2 >= canvas.trim_h:
            y2 += canvas.bleed
    return Box(x1, y1, x2, y2)


def panel_polygon(panel: PanelArt, canvas: Canvas) -> geo.Polygon:
    """Polygone de la case dans la feuille ; les sommets posés sur un bord de page passent dans le fond perdu."""
    assert panel.polygon is not None
    out = []
    for x, y in panel.polygon:
        if canvas.bleed:
            if x <= 0:
                x -= canvas.bleed
            elif x >= canvas.trim_w:
                x += canvas.bleed
            if y <= 0:
                y -= canvas.bleed
            elif y >= canvas.trim_h:
                y += canvas.bleed
        out.append((x + canvas.ox, y + canvas.oy))
    return out


def polygon_mask(poly: Sequence[geo.Point], x0: int, y0: int, w: int, h: int, ss: int) -> Image.Image:
    """Masque « L » anticrénelé du polygone sur la tuile (x0, y0, w, h) : rendu sur-échantillonné puis réduit."""
    mask = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(mask).polygon([((x - x0) * ss, (y - y0) * ss) for x, y in poly], fill=255)
    return mask.resize((w, h), Image.Resampling.BOX) if ss > 1 else mask


def cover_crop(iw: int, ih: int, w: float, h: float) -> tuple[float, float, float, float]:
    """Zone de l'image (x1, y1, x2, y2) qui remplit w × h sans déformation, centrée."""
    scale = max(w / iw, h / ih)
    cw, ch = w / scale, h / scale
    x1, y1 = (iw - cw) / 2, (ih - ch) / 2
    return x1, y1, x1 + cw, y1 + ch


def cover_transform(iw: int, ih: int, box: Box) -> tuple[float, float, float]:
    """(échelle, x0, y0) : un point (u, v) de l'image va en (x0 + u × échelle, y0 + v × échelle)."""
    scale = max(box.w / iw, box.h / ih)
    return scale, box.x1 + (box.w - iw * scale) / 2, box.y1 + (box.h - ih * scale) / 2


def crop_mark_lines(canvas: Canvas, settings: LetteringSettings, dpi: int) -> list[tuple[float, float, float, float]]:
    """Segments des repères de coupe (deux par coin), hors du fond perdu."""
    if not canvas.marks:
        return []
    cm = settings.crop_marks
    gap = max(canvas.bleed, _px(cm.offset_mm, dpi))
    length = _px(cm.length_mm, dpi)
    t = canvas.trim
    out = []
    for x, sx in ((t.x1, -1), (t.x2, 1)):
        for y, sy in ((t.y1, -1), (t.y2, 1)):
            out.append((x + sx * gap, y, x + sx * (gap + length), y))  # horizontal
            out.append((x, y + sy * gap, x, y + sy * (gap + length)))  # vertical
    return out


# --- PNG ---------------------------------------------------------------------------------
def _draw_shape(base: Image.Image, shape: Shape, dx: float, dy: float, ss: int) -> None:
    """Dessine une bulle anticrénelée : contour épais (centré) puis remplissage, sur une tuile sur-échantillonnée."""
    pts = [p for poly in shape.polygons for p in poly]
    pad = shape.stroke_px + 2
    x0 = math.floor(min(p[0] for p in pts) + dx - pad)
    y0 = math.floor(min(p[1] for p in pts) + dy - pad)
    x1 = math.ceil(max(p[0] for p in pts) + dx + pad)
    y1 = math.ceil(max(p[1] for p in pts) + dy + pad)
    tw, th = x1 - x0, y1 - y0
    tile = Image.new("RGBA", (tw * ss, th * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)

    def scaled(poly: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        return [((x + dx - x0) * ss, (y + dy - y0) * ss) for x, y in poly]

    width = max(1, round(2 * shape.stroke_px * ss))
    stroke = (*_hex(shape.stroke), 255)
    for poly in shape.polygons:
        p = scaled(poly)
        draw.line([*p, p[0], p[1]], fill=stroke, width=width, joint="curve")
    fill = (*_hex(shape.fill), 255)
    for poly in shape.polygons:
        draw.polygon(scaled(poly), fill=fill)
    if ss > 1:
        tile = tile.resize((tw, th), Image.Resampling.BOX)
    base.alpha_composite(tile, (x0, y0))


def _fit_label(fonts: FontBook, settings: LetteringSettings, box: Box, dpi: int) -> tuple[str, float]:
    st = fonts.preset.missing_panel
    text = normalize_text(settings.missing_panel_label, uppercase=st.uppercase)
    size = st.size_pt
    while size > st.min_size_pt and fonts.pil(st, pt_to_px(size, dpi)).getlength(text) > box.w * 0.8:
        size -= st.step_pt
    return text, max(size, st.min_size_pt)


def render_png(art: PageArt, fonts: FontBook, settings: LetteringSettings, canvas: Canvas) -> Image.Image:
    dpi = art.fmt.dpi
    img = Image.new("RGBA", (canvas.width, canvas.height), (*_hex(settings.page_background), 255))
    draw = ImageDraw.Draw(img)
    border = round(pt_to_px(settings.panel_border_pt, dpi))
    for panel in art.panels:
        if panel.slanted:
            _draw_slanted_panel(img, panel, fonts, settings, canvas, border, dpi)
            continue
        rect = panel_rect(panel, canvas)
        x1, y1, x2, y2 = round(rect.x1), round(rect.y1), round(rect.x2), round(rect.y2)
        if panel.image is not None:
            with Image.open(panel.image) as src:
                src_rgb = src.convert("RGB")
            crop = cover_crop(src_rgb.width, src_rgb.height, x2 - x1, y2 - y1)
            tile = src_rgb.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS, box=crop)
            img.paste(tile, (x1, y1))
        else:
            draw.rectangle((x1, y1, x2 - 1, y2 - 1), fill=_hex(settings.missing_panel_fill))
            text, size = _fit_label(fonts, settings, rect, dpi)
            st = fonts.preset.missing_panel
            font = fonts.pil(st, pt_to_px(size, dpi))
            draw.text((rect.cx, rect.cy), fonts.drawable(st, text), font=font, fill=_hex(st.color), anchor="mm")
        if border:
            b = panel.box
            draw.rectangle(
                (
                    round(b.x1 + canvas.ox),
                    round(b.y1 + canvas.oy),
                    round(b.x2 + canvas.ox) - 1,
                    round(b.y2 + canvas.oy) - 1,
                ),
                outline=_hex(settings.panel_border_color),
                width=border,
            )
    for bubble in art.lettering.bubbles:
        _draw_shape(img, bubble.shape, canvas.ox, canvas.oy, settings.supersampling)
        font = fonts.pil(bubble.style, bubble.size_px)
        for line in bubble.lines:
            draw.text(
                (line.x + canvas.ox, line.y + canvas.oy),
                line.text,
                font=font,
                fill=_hex(bubble.style.color),
                anchor="ms",
            )
    stroke = max(1, round(pt_to_px(settings.crop_marks.stroke_pt, dpi)))
    for x1, y1, x2, y2 in crop_mark_lines(canvas, settings, dpi):
        draw.line((x1, y1, x2, y2), fill=(0, 0, 0), width=stroke)
    return img.convert("RGB")


def _draw_slanted_panel(
    img: Image.Image,
    panel: PanelArt,
    fonts: FontBook,
    settings: LetteringSettings,
    canvas: Canvas,
    border: int,
    dpi: int,
) -> None:
    rect = panel_rect(panel, canvas)
    x1, y1, x2, y2 = round(rect.x1), round(rect.y1), round(rect.x2), round(rect.y2)
    w, h = x2 - x1, y2 - y1
    ss = settings.supersampling
    poly = panel_polygon(panel, canvas)
    mask = polygon_mask(poly, x1, y1, w, h, ss)
    if panel.image is not None:
        with Image.open(panel.image) as src:
            src_rgb = src.convert("RGB")
        crop = cover_crop(src_rgb.width, src_rgb.height, w, h)
        tile = src_rgb.resize((w, h), Image.Resampling.LANCZOS, box=crop)
    else:
        tile = Image.new("RGB", (w, h), _hex(settings.missing_panel_fill))
    img.paste(tile, (x1, y1), mask)
    if panel.image is None:
        st = fonts.preset.missing_panel
        cx, cy = geo.centroid(poly)
        text, size = _fit_label(fonts, settings, rect, dpi)
        font = fonts.pil(st, pt_to_px(size, dpi))
        ImageDraw.Draw(img).text((cx, cy), fonts.drawable(st, text), font=font, fill=_hex(st.color), anchor="mm")
    if border:
        # Bordure intérieure le long des bords du polygone (page finie, sans le fond perdu).
        trim = [(x + canvas.ox, y + canvas.oy) for x, y in panel.polygon or []]
        bx1, by1, bx2, by2 = geo.bbox(trim)
        bx, by = math.floor(bx1) - 1, math.floor(by1) - 1
        bw, bh = math.ceil(bx2) - bx + 2, math.ceil(by2) - by + 2
        outer = polygon_mask(trim, bx, by, bw, bh, ss)
        inner_poly = geo.inset(trim, border)
        inner = polygon_mask(inner_poly, bx, by, bw, bh, ss) if inner_poly else Image.new("L", (bw, bh), 0)
        ring = ImageChops.subtract(outer, inner)
        img.paste(Image.new("RGB", (bw, bh), _hex(settings.panel_border_color)), (bx, by), ring)


def png_bytes(img: Image.Image, dpi: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(dpi, dpi), optimize=False, compress_level=6)
    return buf.getvalue()


# --- SVG ---------------------------------------------------------------------------------
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if v % 1 else str(int(v))


def _points(poly: Sequence[geo.Point]) -> str:
    return " ".join(f"{_f(round(x, 1))},{_f(round(y, 1))}" for x, y in poly)


def render_svg(art: PageArt, fonts: FontBook, settings: LetteringSettings, canvas: Canvas) -> str:
    dpi = art.fmt.dpi
    ox, oy = canvas.ox, canvas.oy
    width_mm = canvas.width / dpi * MM_PER_INCH
    height_mm = canvas.height / dpi * MM_PER_INCH

    # Polices : un sous-ensemble par famille, limité aux caractères dessinés.
    used: dict[str, tuple[TextStyle, set[str]]] = {}
    for b in art.lettering.bubbles:
        entry = used.setdefault(b.family, (b.style, set()))
        for line in b.lines:
            entry[1].update(line.text)
    missing = [p for p in art.panels if p.image is None]
    label_st = fonts.preset.missing_panel
    if missing:
        text, _ = _fit_label(fonts, settings, missing[0].box, dpi)
        used.setdefault(fonts.family(label_st), (label_st, set()))[1].update(fonts.drawable(label_st, text))

    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
        f'width="{width_mm:.3f}mm" height="{height_mm:.3f}mm" viewBox="0 0 {canvas.width} {canvas.height}">',
        f"<title>Page {art.number}</title>",
        "<defs>",
        "<style>",
    ]
    for family, (style, chars) in sorted(used.items()):
        data = base64.b64encode(fonts.subset(style, "".join(sorted(chars)))).decode("ascii")
        out.append(f'@font-face{{font-family:"{family}";src:url(data:font/ttf;base64,{data}) format("truetype");}}')
    out.append("</style>")
    for panel in art.panels:
        r = panel_rect(panel, canvas)
        if panel.slanted:
            out.append(
                f'<clipPath id="case-{panel.id}"><polygon points="{_points(panel_polygon(panel, canvas))}"/></clipPath>'
            )
            continue
        out.append(
            f'<clipPath id="case-{panel.id}"><rect x="{_f(r.x1)}" y="{_f(r.y1)}" width="{_f(r.w)}" height="{_f(r.h)}"/></clipPath>'
        )
    out.append("</defs>")
    out.append(f'<rect width="{canvas.width}" height="{canvas.height}" fill="{settings.page_background}"/>')

    out.append('<g id="cases">')
    border = pt_to_px(settings.panel_border_pt, dpi)
    for panel in art.panels:
        r = panel_rect(panel, canvas)
        geom = f'x="{_f(r.x1)}" y="{_f(r.y1)}" width="{_f(r.w)}" height="{_f(r.h)}"'
        out.append(f'<g id="case-{panel.index + 1}" clip-path="url(#case-{panel.id})">')
        if panel.image is not None:
            mime = _MIME.get(panel.image.suffix.lower(), "image/png")
            href = f"data:{mime};base64," + base64.b64encode(panel.image.read_bytes()).decode("ascii")
            out.append(f'<image {geom} preserveAspectRatio="xMidYMid slice" href="{href}" xlink:href="{href}"/>')
        else:
            text, size = _fit_label(fonts, settings, r, dpi)
            cx, cy = geo.centroid(panel_polygon(panel, canvas)) if panel.slanted else (r.cx, r.cy)
            out.append(f'<rect {geom} fill="{settings.missing_panel_fill}"/>')
            out.append(
                f'<text x="{_f(cx)}" y="{_f(cy)}" font-family="{fonts.family(label_st)}" '
                f'font-size="{_f(round(pt_to_px(size, dpi), 2))}" fill="{label_st.color}" text-anchor="middle" '
                f'dominant-baseline="central">{escape(fonts.drawable(label_st, text))}</text>'
            )
        out.append("</g>")
        if border and panel.slanted:
            # Trait centré sur le polygone rétréci d'une demi-épaisseur : bordure intérieure, comme le PNG.
            trim = [(x + ox, y + oy) for x, y in panel.polygon or []]
            ring = geo.inset(trim, border / 2) or trim
            out.append(
                f'<polygon points="{_points(ring)}" fill="none" stroke="{settings.panel_border_color}" '
                f'stroke-width="{_f(round(border, 2))}" stroke-linejoin="miter"/>'
            )
        elif border:
            b = panel.box
            half = border / 2
            out.append(
                f'<rect x="{_f(b.x1 + ox + half)}" y="{_f(b.y1 + oy + half)}" width="{_f(b.w - border)}" '
                f'height="{_f(b.h - border)}" fill="none" stroke="{settings.panel_border_color}" '
                f'stroke-width="{_f(round(border, 2))}"/>'
            )
    out.append("</g>")

    out.append(f'<g id="bulles" transform="translate({ox} {oy})">')
    for b in art.lettering.bubbles:
        out.append(_svg_bubble(b))
    out.append("</g>")

    marks = crop_mark_lines(canvas, settings, dpi)
    if marks:
        stroke = _f(round(max(1.0, pt_to_px(settings.crop_marks.stroke_pt, dpi)), 2))
        out.append(f'<g id="reperes-de-coupe" stroke="#000000" stroke-width="{stroke}">')
        for x1, y1, x2, y2 in marks:
            out.append(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}"/>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _svg_bubble(b: BubbleLayout) -> str:
    s = b.shape
    d = s.path()
    lines = "".join(f'<tspan x="{_f(ln.x)}" y="{_f(ln.y)}">{escape(ln.text)}</tspan>' for ln in b.lines)
    label = quoteattr(f"{b.speaker} : {b.text}" if b.speaker else b.text)
    return (
        f'<g class="bulle bulle-{b.kind}" data-bulle="{b.id}" aria-label={label}>'
        f'<path d="{d}" fill="none" stroke="{s.stroke}" stroke-width="{_f(round(2 * s.stroke_px, 2))}" '
        f'stroke-linejoin="round"/>'
        f'<path d="{d}" fill="{s.fill}"/>'
        f'<text font-family="{b.family}" font-size="{_f(round(b.size_px, 2))}" fill="{b.style.color}" '
        f'text-anchor="middle" xml:space="preserve">{lines}</text>'
        "</g>"
    )
