"""Polices du lettrage : instances statiques des polices variables, mesures, sous-ensembles SVG.

Chaque style (type de bulle) vise une police du preset `fonts.yaml` et, pour une police variable,
une graisse. On en tire une police **statique** (fontTools `instancer`) renommée `mk-<police>-<graisse>` :
la même police sert à mesurer, à dessiner le PNG (Pillow / FreeType, mise en page « basic », donc
déterministe) et, réduite aux caractères utilisés, à l'embarquer dans le SVG exporté. Le nouveau nom
respecte la clause 3 de l'OFL (pas de nom réservé sur une version modifiée).
"""

from __future__ import annotations

import io
import threading
from functools import lru_cache
from pathlib import Path

from fontTools import subset as ft_subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import ImageFont

from ..presets import PresetRegistry
from ..presets.schemas import TextStyle

PT_PER_INCH = 72
# Espaces insécables : la fine (U+202F) manque à toutes les polices livrées, l'insécable (U+00A0)
# à certaines. Le retour à la ligne les respecte ; au dessin, une espace absente devient une espace.
NBSP = " "
NNBSP = " "


def pt_to_px(pt: float, dpi: int) -> float:
    return pt / PT_PER_INCH * dpi


def family_name(font_id: str, weight: int | None) -> str:
    return f"mk-{font_id}" + (f"-{weight}" if weight else "")


_lock = threading.Lock()


@lru_cache(maxsize=32)
def _static_font(path: str, weight: int | None, family: str) -> bytes:
    """Instance statique (graisse fixée, autres axes à leur défaut), renommée `family`."""
    with _lock:
        font = TTFont(path)
        if "fvar" in font:
            axes = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
            if weight is not None and "wght" in axes:
                wght = next(a for a in font["fvar"].axes if a.axisTag == "wght")
                axes["wght"] = min(max(float(weight), wght.minValue), wght.maxValue)
            font = instancer.instantiateVariableFont(font, axes, updateFontNames=False)
        name = font["name"]
        for rec in list(name.names):
            if rec.nameID in (1, 4, 6, 16, 17, 21, 22):
                name.removeNames(nameID=rec.nameID)
        name.setName(family, 1, 3, 1, 0x409)
        name.setName("Regular", 2, 3, 1, 0x409)
        name.setName(family, 4, 3, 1, 0x409)
        name.setName(family, 6, 3, 1, 0x409)
        buf = io.BytesIO()
        font.save(buf)
        return buf.getvalue()


@lru_cache(maxsize=32)
def _cmap(data: bytes) -> frozenset[int]:
    return frozenset(TTFont(io.BytesIO(data)).getBestCmap())


@lru_cache(maxsize=256)
def _pil_font(data: bytes, size_px: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(io.BytesIO(data), size=size_px, layout_engine=ImageFont.Layout.BASIC)


class FontBook:
    """Accès aux polices des styles de lettrage du preset."""

    def __init__(self, presets: PresetRegistry) -> None:
        self.presets = presets
        self.preset = presets.require_fonts()

    def style(self, kind: str) -> TextStyle:
        return self.preset.styles[kind]

    def family(self, style: TextStyle) -> str:
        return family_name(style.font, style.weight)

    def data(self, style: TextStyle) -> bytes:
        path: Path = self.presets.font_path(style.font)
        return _static_font(str(path), style.weight, self.family(style))

    def pil(self, style: TextStyle, size_px: float) -> ImageFont.FreeTypeFont:
        return _pil_font(self.data(style), round(size_px, 2))

    def has_char(self, style: TextStyle, char: str) -> bool:
        return ord(char) in _cmap(self.data(style))

    def drawable(self, style: TextStyle, text: str) -> str:
        """Texte tel qu'il est dessiné : espaces insécables absentes de la police → espace simple."""
        for space in (NBSP, NNBSP):
            if space in text and not self.has_char(style, space):
                text = text.replace(space, " ")
        return text

    def subset(self, style: TextStyle, chars: str) -> bytes:
        """Police réduite aux caractères `chars` (embarquée dans le SVG)."""
        font = TTFont(io.BytesIO(self.data(style)))
        options = ft_subset.Options()
        options.name_IDs = ["*"]
        options.name_legacy = True
        options.notdef_outline = True
        options.layout_features = ["kern", "liga"]
        options.drop_tables += ["FFTM"]  # horodatage FontForge : inutile, et fontTools ne sait pas le réduire
        sub = ft_subset.Subsetter(options=options)
        sub.populate(unicodes={ord(c) for c in chars} | {ord(" ")})
        sub.subset(font)
        buf = io.BytesIO()
        font.save(buf)
        return buf.getvalue()
