"""Logo du titre de la série : typographique et vectoriel, jamais dessiné par le modèle d'image.

Un logo est un jeu de réglages (`LogoSpec`) : police (parmi `identity.yaml › logo.fonts`), une ou deux lignes
du titre avec leur taille relative, effet (`presets/logo_styles/` : contours, ombre portée, dégradé), couleurs
(tirées de la palette retenue), inclinaison, interlettrage, épaisseur des contours, sous-titre en petit.
Aucune police ni aucun effet n'est écrit ici : tout vient des presets.

Rendu, comme le lettrage (`fonts.py`, `assembly.py`) : la police est une instance statique renommée
`mk-<police>`, mesurée et dessinée par Pillow (mise en page « basic », déterministe) ; le SVG l'embarque,
réduite aux caractères du logo. La mise en page est calculée une seule fois, à l'échelle du PNG, et chaque
caractère est posé à la même abscisse dans les deux rendus (`<text x="x1 x2 …">`) : SVG et PNG concordent.

Calques, de dessous vers dessus : ombre portée, second contour, contour, lettres (pleines ou en dégradé
vertical, ligne par ligne). L'inclinaison est un cisaillement autour du centre du logo. PNG : fond transparent.
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..presets import PresetRegistry
from ..presets.schemas import HEX_COLOR, LogoSettings, LogoStyle
from .fonts import FontBook

HEX = HEX_COLOR


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LogoLine(_Strict):
    text: str = Field(min_length=1, max_length=120)
    scale: float = 1.0

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("ligne vide")
        return v


class LogoColors(_Strict):
    fill: str = Field(pattern=HEX)
    fill_end: str | None = Field(default=None, pattern=HEX)
    outline: str | None = Field(default=None, pattern=HEX)
    outer: str | None = Field(default=None, pattern=HEX)
    shadow: str | None = Field(default=None, pattern=HEX)
    subtitle: str | None = Field(default=None, pattern=HEX)

    @field_validator("*")
    @classmethod
    def _lower(cls, v: str | None) -> str | None:
        return v.lower() if isinstance(v, str) else v


class LogoSpec(_Strict):
    """Réglages complets d'un logo (concept de l'IA, ou logo enregistré de la série)."""

    name: str = Field(default="", max_length=80)
    explanation: str = Field(default="", max_length=600)
    font: str
    style: str
    lines: list[LogoLine] = Field(min_length=1, max_length=4)
    subtitle: str | None = Field(default=None, max_length=120)
    slant: float = 0.0
    letter_spacing: float = 0.0
    outline_scale: float = 1.0
    colors: LogoColors

    @field_validator("subtitle")
    @classmethod
    def _subtitle(cls, v: str | None) -> str | None:
        v = " ".join(v.split()) if v else ""
        return v or None

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)

    def chars(self) -> str:
        return "".join(line.text for line in self.lines) + (self.subtitle or "")


class LogoError(ValueError):
    """Logo impossible à rendre (police ou effet inconnus, caractère absent de la police)."""


def logo_settings(presets: PresetRegistry) -> LogoSettings:
    return presets.require_identity().logo


def logo_style(presets: PresetRegistry, style_id: str) -> LogoStyle:
    style = presets.logo_styles.get(style_id)
    if style is None:
        raise LogoError(f"effet de logo inconnu : « {style_id} » (presets/logo_styles/)")
    return style


def spec_problems(presets: PresetRegistry, spec: LogoSpec) -> list[str]:
    """Écarts d'un logo avec les presets : police et effet permis, bornes des réglages, couleurs de l'effet,
    caractères présents dans la police (accents français compris)."""
    settings = logo_settings(presets)
    problems: list[str] = []
    if spec.font not in settings.fonts:
        problems.append(f"font : « {spec.font} » n'est pas une police permise ({', '.join(settings.fonts)})")
    style = presets.logo_styles.get(spec.style)
    if style is None:
        problems.append(f"style : effet inconnu « {spec.style} » ({', '.join(presets.logo_styles)})")
    if len(spec.lines) > settings.max_lines:
        problems.append(f"lines : {len(spec.lines)} lignes, {settings.max_lines} au plus")
    lo, hi = settings.word_scale.min, settings.word_scale.max
    for i, line in enumerate(spec.lines, 1):
        if not lo <= line.scale <= hi:
            problems.append(f"lines[{i}].scale : {line.scale} hors de [{lo} ; {hi}]")
    if abs(spec.slant) > settings.slant_max_deg:
        problems.append(f"slant : {spec.slant}° hors de ± {settings.slant_max_deg}°")
    lo, hi = settings.letter_spacing.min, settings.letter_spacing.max
    if not lo <= spec.letter_spacing <= hi:
        problems.append(f"letter_spacing : {spec.letter_spacing} hors de [{lo} ; {hi}]")
    lo, hi = settings.outline_scale.min, settings.outline_scale.max
    if not lo <= spec.outline_scale <= hi:
        problems.append(f"outline_scale : {spec.outline_scale} hors de [{lo} ; {hi}]")
    if style is not None:
        missing = [s for s in style.slots() if s != "subtitle" and getattr(spec.colors, s) is None]
        if spec.subtitle and spec.colors.subtitle is None:
            missing.append("subtitle")
        if missing:
            problems.append(f"colors : couleur manquante pour l'effet « {style.name} » ({', '.join(missing)})")
    if spec.font in settings.fonts and presets.fonts is not None:
        fonts = FontBook(presets)
        tstyle = fonts.sfx_style(spec.font)
        absent = sorted({c for c in spec.chars() if not c.isspace() and not fonts.has_char(tstyle, c)})
        if absent:
            name = presets.fonts.fonts[spec.font].name
            problems.append(f"font : « {name} » n'a pas les caractères {' '.join(absent)} (choisis une autre police)")
    return problems


def check_spec(presets: PresetRegistry, spec: LogoSpec) -> None:
    problems = spec_problems(presets, spec)
    if problems:
        raise LogoError(" ; ".join(problems))


# --- contraste (WCAG 2) -----------------------------------------------------------------------------
def rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def luminance(color: str) -> float:
    def channel(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_colors(spec: LogoSpec, style: LogoStyle) -> list[str]:
    """Couleurs des lettres posées sur le contour : remplissage (et fin du dégradé), sous-titre."""
    out = [spec.colors.fill]
    if style.gradient and spec.colors.fill_end:
        out.append(spec.colors.fill_end)
    if spec.subtitle and spec.colors.subtitle:
        out.append(spec.colors.subtitle)
    return out


def edge_color(spec: LogoSpec, style: LogoStyle) -> str | None:
    """Couleur qui borde les lettres : le contour, sinon le second contour ; None sans contour."""
    if spec.outline_scale <= 0:
        return None
    if style.outline_em > 0:
        return spec.colors.outline
    if style.outer_outline_em > 0:
        return spec.colors.outer
    return None


def logo_contrast(spec: LogoSpec, style: LogoStyle) -> float | None:
    """Plus faible contraste entre le texte du logo et son contour (None : pas de contour)."""
    edge = edge_color(spec, style)
    if edge is None:
        return None
    return min(contrast(c, edge) for c in text_colors(spec, style))


def fix_contrast(
    spec: LogoSpec, style: LogoStyle, candidates: list[str], minimum: float
) -> tuple[LogoSpec, str | None]:
    """Contour trop proche du texte : il prend la couleur la plus contrastée parmi `candidates` (palette), sinon
    le noir ou le blanc. Renvoie le logo et une note pour l'auteur (None si rien n'a changé)."""
    ratio = logo_contrast(spec, style)
    if ratio is None or ratio >= minimum:
        return spec, None
    texts = text_colors(spec, style)

    def score(c: str) -> float:
        return min(contrast(t, c) for t in texts)

    best = max(candidates, key=score, default=None)
    if best is None or score(best) < minimum:
        best = max(("#000000", "#ffffff"), key=score)
    slot = "outline" if style.outline_em > 0 else "outer"
    fixed = spec.model_copy(update={"colors": spec.colors.model_copy(update={slot: best})})
    note = f"contour passé en {best} : contraste {ratio:.1f} → {score(best):.1f} (minimum {minimum:g})"
    return fixed, note


# --- mise en page --------------------------------------------------------------------------------------
@dataclass
class _Run:
    """Une ligne posée (ou le sous-titre), en px du PNG."""

    text: str
    size: float
    xs: list[float]
    baseline: float
    ascent: float
    descent: float
    ink: tuple[float, float, float, float]  # x1, y1, x2, y2 (encre des glyphes)
    subtitle: bool = False


@dataclass
class LogoLayout:
    spec: LogoSpec
    style: LogoStyle
    family: str
    scale: float  # px du PNG par unité du SVG
    main: float  # taille de police d'une ligne d'échelle 1, px du PNG
    width: float  # px du PNG
    height: float
    runs: list[_Run] = field(default_factory=list)
    outline: float = 0.0  # largeur du contour hors de la lettre (ligne d'échelle 1), px du PNG
    outer: float = 0.0
    shadow: tuple[float, float] | None = None
    slant: float = 0.0  # degrés (positif : penche vers la droite)


def _measure(fonts: FontBook, spec: LogoSpec, text: str, size: float, spacing_em: float, baseline: float) -> _Run:
    font = fonts.pil(fonts.sfx_style(spec.font), size)
    tstyle = fonts.sfx_style(spec.font)
    text = fonts.drawable(tstyle, text)
    ascent, descent = font.getmetrics()
    spacing = spacing_em * size
    xs = [font.getlength(text[:i]) + i * spacing for i in range(len(text))]
    x1 = y1 = math.inf
    x2 = y2 = -math.inf
    for x, ch in zip(xs, text, strict=True):
        if ch.isspace():
            continue
        left, top, right, low = font.getbbox(ch, anchor="ls")
        x1, y1, x2, y2 = min(x1, x + left), min(y1, baseline + top), max(x2, x + right), max(y2, baseline + low)
    if x1 == math.inf:
        x1, x2, y1, y2 = 0, 0, baseline - ascent, baseline + descent
    return _Run(text, size, xs, baseline, ascent, descent, (x1, y1, x2, y2))


def layout_logo(presets: PresetRegistry, spec: LogoSpec, scale: float | None = None) -> LogoLayout:
    """Pose le logo à l'échelle du PNG (`scale` × l'unité du SVG ; défaut : `png_scale` du preset)."""
    check_spec(presets, spec)
    settings = logo_settings(presets)
    style = logo_style(presets, spec.style)
    fonts = FontBook(presets)
    s = settings.png_scale if scale is None else scale
    main = settings.size_px * s
    runs: list[_Run] = []
    sizes = [(main * line.scale, line.text, False) for line in spec.lines]
    if spec.subtitle:
        sizes.append((main * settings.subtitle_scale, spec.subtitle, True))
    bottom = 0.0
    for i, (size, text, subtitle) in enumerate(sizes):
        run = _measure(fonts, spec, text, size, spec.letter_spacing, 0.0)
        # Lignes empilées sur l'encre des glyphes (accents compris) : jamais un « É » dans la ligne du dessus.
        gap = 0.0 if i == 0 else (settings.subtitle_gap if subtitle else settings.line_gap) * main
        shift = bottom + gap - run.ink[1]
        run.baseline += shift
        run.ink = (run.ink[0], run.ink[1] + shift, run.ink[2], run.ink[3] + shift)
        run.subtitle = subtitle
        bottom = run.ink[3]
        runs.append(run)

    # Chaque ligne centrée sur l'encre de ses glyphes.
    for r in runs:
        dx = -(r.ink[0] + r.ink[2]) / 2
        r.xs = [x + dx for x in r.xs]
        r.ink = (r.ink[0] + dx, r.ink[1], r.ink[2] + dx, r.ink[3])

    outline = style.outline_em * main * spec.outline_scale
    outer = style.outer_outline_em * main * spec.outline_scale
    shadow = (style.shadow.dx_em * main, style.shadow.dy_em * main) if style.shadow else None
    reach = outline + outer + (max(abs(shadow[0]), abs(shadow[1])) if shadow else 0)
    pad = settings.padding * main + reach
    x1 = min(r.ink[0] for r in runs)
    y1 = min(r.ink[1] for r in runs)
    x2 = max(r.ink[2] for r in runs)
    y2 = max(r.ink[3] for r in runs)
    content_h = y2 - y1 + 2 * pad
    lean = math.tan(math.radians(abs(spec.slant))) * content_h / 2
    width = math.ceil(x2 - x1 + 2 * (pad + lean))
    height = math.ceil(content_h)
    ox = (width - (x2 - x1)) / 2 - x1
    oy = (height - (y2 - y1)) / 2 - y1
    for r in runs:
        r.xs = [x + ox for x in r.xs]
        r.baseline += oy
        r.ink = (r.ink[0] + ox, r.ink[1] + oy, r.ink[2] + ox, r.ink[3] + oy)
    return LogoLayout(
        spec=spec,
        style=style,
        family=fonts.family(fonts.sfx_style(spec.font)),
        scale=s,
        main=main,
        width=width,
        height=height,
        runs=runs,
        outline=outline,
        outer=outer,
        shadow=shadow,
        slant=spec.slant,
    )


def _widths(lay: LogoLayout, run: _Run) -> tuple[float, float]:
    """(contour, contour + second contour) d'une ligne, proportionnels à sa taille."""
    ratio = run.size / lay.main
    return lay.outline * ratio, (lay.outline + lay.outer) * ratio


# --- PNG ------------------------------------------------------------------------------------------------
def _mask(
    lay: LogoLayout, fonts: FontBook, runs: list[_Run], stroke: str, offset: tuple[float, float] = (0, 0)
) -> Image.Image:
    """Masque des lettres de `runs` ; `stroke` : « fill » (lettre seule), « outline » ou « outer »."""
    mask = Image.new("L", (int(lay.width), int(lay.height)), 0)
    draw = ImageDraw.Draw(mask)
    tstyle = fonts.sfx_style(lay.spec.font)
    for run in runs:
        font = fonts.pil(tstyle, run.size)
        inner, outer = _widths(lay, run)
        width = {"fill": 0.0, "outline": inner, "outer": outer}[stroke]
        sw = round(width)
        for x, ch in zip(run.xs, run.text, strict=True):
            if ch.isspace():
                continue
            pos = (x + offset[0], run.baseline + offset[1])
            draw.text(pos, ch, font=font, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
    return mask


def _solid(size: tuple[int, int], color: str, mask: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", size, (*rgb(color), 255))
    layer.putalpha(mask)
    return layer


def _gradient(size: tuple[int, int], run: _Run, start: str, end: str, mask: Image.Image) -> Image.Image:
    """Dégradé vertical d'une ligne : du haut au bas de l'encre de ses glyphes (accents compris)."""
    w, h = size
    a, b = rgb(start), rgb(end)
    top, bottom = run.ink[1], run.ink[3]
    column = Image.new("RGB", (1, h), a)
    px = column.load()
    assert px is not None
    for y in range(h):
        t = min(1.0, max(0.0, (y + 0.5 - top) / max(1.0, bottom - top)))
        px[0, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    layer = column.resize((w, h), Image.Resampling.NEAREST).convert("RGBA")
    layer.putalpha(mask)
    return layer


def render_png_image(presets: PresetRegistry, spec: LogoSpec, scale: float | None = None) -> Image.Image:
    lay = layout_logo(presets, spec, scale)
    fonts = FontBook(presets)
    size = (int(lay.width), int(lay.height))
    c = spec.colors
    title = [r for r in lay.runs if not r.subtitle]
    subs = [r for r in lay.runs if r.subtitle]
    img = Image.new("RGBA", size, (*rgb(c.fill), 0))
    if lay.shadow is not None and c.shadow:
        img.alpha_composite(_solid(size, c.shadow, _mask(lay, fonts, lay.runs, "outer", lay.shadow)))
    if lay.outer > 0 and c.outer:
        img.alpha_composite(_solid(size, c.outer, _mask(lay, fonts, lay.runs, "outer")))
    if lay.outline > 0 and c.outline:
        img.alpha_composite(_solid(size, c.outline, _mask(lay, fonts, lay.runs, "outline")))
    if lay.style.gradient and c.fill_end:
        for run in title:
            img.alpha_composite(_gradient(size, run, c.fill, c.fill_end, _mask(lay, fonts, [run], "fill")))
    else:
        img.alpha_composite(_solid(size, c.fill, _mask(lay, fonts, title, "fill")))
    if subs:
        img.alpha_composite(_solid(size, c.subtitle or c.fill, _mask(lay, fonts, subs, "fill")))
    if lay.slant:
        t = math.tan(math.radians(lay.slant))
        cy = lay.height / 2
        img = img.transform(size, Image.Transform.AFFINE, (1, t, -t * cy, 0, 1, 0), Image.Resampling.BICUBIC)
    return img


def render_png(presets: PresetRegistry, spec: LogoSpec, scale: float | None = None) -> bytes:
    """PNG transparent haute définition (`png_scale` × la taille du SVG)."""
    img = render_png_image(presets, spec, scale)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


# --- SVG ------------------------------------------------------------------------------------------------
def _f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def render_svg(presets: PresetRegistry, spec: LogoSpec) -> str:
    """SVG autonome : police embarquée (sous-ensemble renommé), un `<text>` par ligne et par calque."""
    lay = layout_logo(presets, spec)
    fonts = FontBook(presets)
    tstyle = fonts.sfx_style(spec.font)
    k = 1 / lay.scale
    w, h = lay.width * k, lay.height * k
    c = spec.colors
    chars = "".join(sorted(set("".join(r.text for r in lay.runs))))
    data = base64.b64encode(fonts.subset(tstyle, chars)).decode("ascii")
    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{_f(w)}" height="{_f(h)}" '
        f'viewBox="0 0 {_f(w)} {_f(h)}">',
        f"<title>{escape(spec.text)}</title>",
        "<defs>",
        f'<style>@font-face{{font-family:"{lay.family}";src:url(data:font/ttf;base64,{data}) format("truetype");}}</style>',
    ]
    title = [r for r in lay.runs if not r.subtitle]
    gradient = lay.style.gradient and c.fill_end
    if gradient:
        for i, r in enumerate(title):
            out.append(
                f'<linearGradient id="degrade-{i}" gradientUnits="userSpaceOnUse" x1="0" y1="{_f(r.ink[1] * k)}" '
                f'x2="0" y2="{_f(r.ink[3] * k)}">'
                f'<stop offset="0" stop-color="{c.fill}"/><stop offset="1" stop-color="{c.fill_end}"/></linearGradient>'
            )
    out.append("</defs>")
    if lay.slant:
        cy = lay.height / 2 * k
        out.append(f'<g transform="translate(0 {_f(cy)}) skewX({_f(-lay.slant)}) translate(0 {_f(-cy)})">')
    else:
        out.append("<g>")

    def text(run: _Run, attrs: str) -> str:
        xs = " ".join(_f(x * k) for x in run.xs)
        return (
            f'<text x="{xs}" y="{_f(run.baseline * k)}" font-family="{lay.family}" font-size="{_f(run.size * k)}" '
            f'xml:space="preserve" {attrs}>{escape(run.text)}</text>'
        )

    def stroked(color: str, which: int, label: str, transform: str = "") -> None:
        out.append(f'<g class="{label}"{transform}>')
        for r in lay.runs:
            width = 2 * _widths(lay, r)[which] * k
            out.append(text(r, f'fill="{color}" stroke="{color}" stroke-width="{_f(width)}" stroke-linejoin="round"'))
        out.append("</g>")

    if lay.shadow is not None and c.shadow:
        stroked(c.shadow, 1, "ombre", f' transform="translate({_f(lay.shadow[0] * k)} {_f(lay.shadow[1] * k)})"')
    if lay.outer > 0 and c.outer:
        stroked(c.outer, 1, "second-contour")
    if lay.outline > 0 and c.outline:
        stroked(c.outline, 0, "contour")
    out.append('<g class="lettres">')
    for i, r in enumerate(title):
        out.append(text(r, f'fill="url(#degrade-{i})"' if gradient else f'fill="{c.fill}"'))
    for r in lay.runs:
        if r.subtitle:
            out.append(text(r, f'fill="{c.subtitle or c.fill}" class="sous-titre"'))
    out.append("</g></g></svg>")
    return "\n".join(out)


def spec_json(spec: LogoSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json")
