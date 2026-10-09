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

Options de cadre (voir `layout.py`) : une case `none` n'a pas de bordure ; une case `fade` non plus, et
son image se fond au papier sur `frames.fade_mm` (masque flou) ; une case à fond perdu atteint le bord
de la page (et celui du fond perdu à l'export avec fond perdu), sans bordure sur ses bords posés au bord
de la page ; une incrustation est dessinée **après** toutes les autres cases, sur un liseré blanc.

Onomatopées : texte de la police de l'onomatopée, halo puis contour épais puis remplissage, transformé
(rotation · cisaillement) autour de son centre, posé après les bulles.

Le SVG reprend exactement la même géométrie : images embarquées (fichiers d'origine, recadrage
par `preserveAspectRatio="xMidYMid slice"`), texte en vraies balises `<text>` sélectionnables avec
la police embarquée (sous-ensemble des caractères utilisés), formes de bulle en chemins ; une
onomatopée reste du texte (`<text>` dans un `<g transform>`), contour et halo en `stroke`.
"""

from __future__ import annotations

import base64
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..presets.schemas import LetteringSettings, PageFormat, TextStyle
from . import geometry as geo
from .fonts import FontBook, pt_to_px
from .lettering import (
    MM_PER_INCH,
    Box,
    BubbleLayout,
    LetteringWarning,
    PageLettering,
    SfxLayout,
    Shape,
    normalize_text,
)


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
    frame: str = "border"  # border | none | fade
    inset: bool = False  # incrustation : dessinée après les autres cases, sur un liseré blanc

    @property
    def slanted(self) -> bool:
        return self.polygon is not None and len(self.polygon) >= 3 and not geo.is_axis_rect(self.polygon)

    def outline(self) -> geo.Polygon:
        """Contour en px de la page finie : le polygone, sinon le rectangle de la case."""
        if self.polygon is not None and len(self.polygon) >= 3:
            return list(self.polygon)
        b = self.box
        return geo.rect_polygon(b.x1, b.y1, b.x2, b.y2)

    def edge_flags(self, canvas: Canvas) -> list[bool]:
        """Pour chaque bord du contour : est-il posé sur un bord de la page (case à fond perdu) ?"""
        poly = self.outline()
        flags = []
        for k in range(len(poly)):
            (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % len(poly)]
            if math.hypot(x2 - x1, y2 - y1) < geo.EPS:
                continue
            flags.append(
                (x1 <= 0 and x2 <= 0)
                or (y1 <= 0 and y2 <= 0)
                or (x1 >= canvas.trim_w and x2 >= canvas.trim_w)
                or (y1 >= canvas.trim_h and y2 >= canvas.trim_h)
            )
        return flags


def draw_order(panels: Sequence[PanelArt]) -> list[PanelArt]:
    """Ordre de dessin : les cases de l'arbre (ordre de lecture), puis les incrustations par-dessus."""
    return [p for p in panels if not p.inset] + [p for p in panels if p.inset]


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
    out = []
    for x, y in panel.outline():
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
    cw, ch = min(iw, w / scale), min(ih, h / scale)
    x1, y1 = max(0.0, (iw - cw) / 2), max(0.0, (ih - ch) / 2)  # bornés : arrondis flottants (−1e-13)
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
    for panel in draw_order(art.panels):
        if panel.inset:
            _draw_inset_outline(img, panel, settings, canvas, dpi)
        if panel.slanted or panel.frame == "fade" or any(panel.edge_flags(canvas)):
            _draw_slanted_panel(img, panel, fonts, settings, canvas, border if panel.frame == "border" else 0, dpi)
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
        if border and panel.frame == "border":
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
    for sfx in art.lettering.sfx:
        _draw_sfx(img, sfx, fonts, canvas.ox, canvas.oy, settings.supersampling)
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
    flags = panel.edge_flags(canvas)
    mask = polygon_mask(poly, x1, y1, w, h, ss)
    if panel.frame == "fade":
        # Fondu au papier : masque du polygone rétréci de la largeur du fondu (bords de page exceptés), flouté.
        fade = settings.frames.fade_mm / MM_PER_INCH * dpi
        inner = geo.offset_edges(poly, [-fade if f else fade for f in flags])
        soft = polygon_mask(inner, x1, y1, w, h, ss) if len(inner) >= 3 else Image.new("L", (w, h), 0)
        soft = soft.filter(ImageFilter.GaussianBlur(fade / 2))
        mask = ImageChops.multiply(mask, soft)
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
        # Bordure intérieure le long des bords du polygone (page finie, sans le fond perdu) ; aucune le
        # long d'un bord posé au bord de la page (fond perdu : il sera rogné).
        trim = [(x + canvas.ox, y + canvas.oy) for x, y in panel.outline()]
        if any(flags):
            trim = poly
        bx1, by1, bx2, by2 = geo.bbox(trim)
        bx, by = max(0, math.floor(bx1) - 1), max(0, math.floor(by1) - 1)
        bw = min(img.width, math.ceil(bx2) + 1) - bx
        bh = min(img.height, math.ceil(by2) + 1) - by
        outer = polygon_mask(trim, bx, by, bw, bh, ss)
        if any(flags):
            inner_poly = geo.offset_edges(trim, [-(border + 4.0) if f else float(border) for f in flags])
        else:
            inner_poly = geo.inset(trim, border)
        inner = polygon_mask(inner_poly, bx, by, bw, bh, ss) if inner_poly else Image.new("L", (bw, bh), 0)
        ring = ImageChops.subtract(outer, inner)
        img.paste(Image.new("RGB", (bw, bh), _hex(settings.panel_border_color)), (bx, by), ring)


def _draw_inset_outline(
    img: Image.Image, panel: PanelArt, settings: LetteringSettings, canvas: Canvas, dpi: int
) -> None:
    """Liseré blanc autour d'une incrustation : elle se détache de la case hôte."""
    width = settings.frames.inset_outline_mm / MM_PER_INCH * dpi
    if width <= 0:
        return
    ring = geo.outset(panel_polygon(panel, canvas), width)
    bx1, by1, bx2, by2 = geo.bbox(ring)
    bx, by = max(0, math.floor(bx1) - 1), max(0, math.floor(by1) - 1)
    bw, bh = min(canvas.width, math.ceil(bx2) + 1) - bx, min(canvas.height, math.ceil(by2) + 1) - by
    mask = polygon_mask(ring, bx, by, bw, bh, settings.supersampling)
    img.paste(Image.new("RGB", (bw, bh), _hex(settings.frames.inset_outline_color)), (bx, by), mask)


def _draw_sfx(base: Image.Image, sfx: SfxLayout, fonts: FontBook, dx: float, dy: float, ss: int) -> None:
    """Onomatopée : texte (halo, puis contour + remplissage) dessiné à plat sur une tuile sur-échantillonnée,
    puis transformée (rotation · cisaillement) et posée en son centre."""
    font = fonts.pil(sfx.style, sfx.size_px * ss)
    hw, hh = sfx.half
    margin = 4
    tw, th = math.ceil(2 * hw * ss) + 2 * margin * ss, math.ceil(2 * hh * ss) + 2 * margin * ss
    # Fond transparent de la couleur du halo : l'interpolation du bord ne fonce pas le halo.
    tile = Image.new("RGBA", (tw, th), (*_hex(sfx.halo), 0))
    draw = ImageDraw.Draw(tile)
    ox, oy = tw / 2, th / 2
    outline_w = round(sfx.outline_px * ss)
    halo_w = round((sfx.outline_px + sfx.halo_px) * ss)
    halo, outline, fill = (*_hex(sfx.halo), 255), (*_hex(sfx.outline), 255), (*_hex(sfx.fill), 255)
    if halo_w > outline_w:
        for ln in sfx.lines:
            pos = (ox + ln.x * ss, oy + ln.y * ss)
            draw.text(pos, ln.text, font=font, fill=halo, anchor="ms", stroke_width=halo_w, stroke_fill=halo)
    for ln in sfx.lines:
        pos = (ox + ln.x * ss, oy + ln.y * ss)
        draw.text(pos, ln.text, font=font, fill=fill, anchor="ms", stroke_width=outline_w, stroke_fill=outline)

    m0, m1, m2, m3 = sfx.matrix
    det = m0 * m3 - m1 * m2
    i0, i1, i2, i3 = m3 / det, -m1 / det, -m2 / det, m0 / det
    cx, cy = sfx.center[0] + dx, sfx.center[1] + dy
    # Emprise de la tuile transformée dans la feuille (marge comprise), bornée à la feuille.
    corners = geo.affine(
        sfx.matrix,
        cx,
        cy,
        [
            (-hw - margin, -hh - margin),
            (hw + margin, hh + margin),
            (hw + margin, -hh - margin),
            (-hw - margin, hh + margin),
        ],
    )
    qx1, qy1, qx2, qy2 = geo.bbox(corners)
    X0, Y0 = max(0, math.floor(qx1)), max(0, math.floor(qy1))
    X1, Y1 = min(base.width, math.ceil(qx2)), min(base.height, math.ceil(qy2))
    if X1 <= X0 or Y1 <= Y0:
        return
    # Pixel (u, v) de la sortie sur-échantillonnée → point de la feuille → repère local → tuile.
    ex, ey = X0 - cx, Y0 - cy
    data = (i0, i1, ss * (i0 * ex + i1 * ey) + ox, i2, i3, ss * (i2 * ex + i3 * ey) + oy)
    out = tile.transform(((X1 - X0) * ss, (Y1 - Y0) * ss), Image.Transform.AFFINE, data, Image.Resampling.BICUBIC)
    if ss > 1:
        out = out.resize((X1 - X0, Y1 - Y0), Image.Resampling.BOX)
    base.alpha_composite(out, (X0, Y0))


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
    for sx in art.lettering.sfx:
        entry = used.setdefault(sx.family, (sx.style, set()))
        for line in sx.lines:
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
    fade = settings.frames.fade_mm / MM_PER_INCH * dpi
    for panel in art.panels:
        r = panel_rect(panel, canvas)
        if panel.frame == "fade":
            flags = panel.edge_flags(canvas)
            inner = geo.offset_edges(panel_polygon(panel, canvas), [-fade if f else fade for f in flags])
            out.append(
                f'<filter id="flou-{panel.id}" x="-20%" y="-20%" width="140%" height="140%">'
                f'<feGaussianBlur stdDeviation="{_f(round(fade / 2, 2))}"/></filter>'
                f'<mask id="fondu-{panel.id}" maskUnits="userSpaceOnUse">'
                f'<polygon points="{_points(inner)}" fill="#ffffff" filter="url(#flou-{panel.id})"/></mask>'
            )
        if panel.slanted or any(panel.edge_flags(canvas)):
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
    outline_w = settings.frames.inset_outline_mm / MM_PER_INCH * dpi
    for panel in draw_order(art.panels):
        r = panel_rect(panel, canvas)
        geom = f'x="{_f(r.x1)}" y="{_f(r.y1)}" width="{_f(r.w)}" height="{_f(r.h)}"'
        if panel.inset and outline_w > 0:
            ring = geo.outset(panel_polygon(panel, canvas), outline_w)
            out.append(
                f'<polygon class="liseré" points="{_points(ring)}" fill="{settings.frames.inset_outline_color}"/>'
            )
        masked = f' mask="url(#fondu-{panel.id})"' if panel.frame == "fade" else ""
        kind = " incrustation" if panel.inset else ""
        out.append(
            f'<g id="case-{panel.index + 1}" class="case case-{panel.frame}{kind}" '
            f'clip-path="url(#case-{panel.id})"{masked}>'
        )
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
        flags = panel.edge_flags(canvas)
        if panel.frame != "border":
            continue
        if border and any(flags):
            # Fond perdu : pas de bordure le long des bords posés au bord de la page (trait rogné par la découpe).
            sheet = panel_polygon(panel, canvas)
            ring = geo.offset_edges(sheet, [-(border + 4.0) if f else border / 2 for f in flags])
            out.append(
                f'<polygon points="{_points(ring)}" fill="none" stroke="{settings.panel_border_color}" '
                f'stroke-width="{_f(round(border, 2))}" stroke-linejoin="miter" clip-path="url(#case-{panel.id})"/>'
            )
        elif border and panel.slanted:
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
    if art.lettering.sfx:
        out.append(f'<g id="onomatopees" transform="translate({ox} {oy})">')
        for sx in art.lettering.sfx:
            out.append(_svg_sfx(sx))
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


def _svg_sfx(s: SfxLayout) -> str:
    """Onomatopée en texte SVG : halo (trait large), puis contour + remplissage (`paint-order` : trait dessous)."""
    lines = "".join(f'<tspan x="{_f(ln.x)}" y="{_f(ln.y)}">{escape(ln.text)}</tspan>' for ln in s.lines)
    font = f'font-family="{s.family}" font-size="{_f(round(s.size_px, 2))}" text-anchor="middle" xml:space="preserve"'
    halo = _f(round(2 * (s.outline_px + s.halo_px), 2))
    outline = _f(round(2 * s.outline_px, 2))
    return (
        f'<g class="onomatopee onomatopee-{s.intensity}" data-onomatopee="{s.id}" aria-label={quoteattr(s.text)} '
        f'transform="{s.svg_transform()}">'
        f'<text {font} fill="{s.halo}" stroke="{s.halo}" stroke-width="{halo}" stroke-linejoin="round">{lines}</text>'
        f'<text {font} fill="{s.fill}" stroke="{s.outline}" stroke-width="{outline}" stroke-linejoin="round" '
        f'paint-order="stroke">{lines}</text>'
        "</g>"
    )
