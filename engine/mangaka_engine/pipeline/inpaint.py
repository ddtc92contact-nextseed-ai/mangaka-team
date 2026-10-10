"""Réparation ciblée — masque (fonctions pures, sans base ni réseau).

- `build_mask` : zone à repeindre (binaire, taille de l'image) depuis des rectangles (détections du QC,
  rectangles tracés) et/ou un masque peint ;
- `soften_mask` : marge (`grow_px`) puis bords fondus (`feather_px`) ; hors de `influence_zone`
  (zone + marge + adoucissement), le masque vaut exactement 0 ;
- `recompose` : recolle la zone repeinte par ComfyUI sur l'original — là où le masque vaut 0, les
  pixels sont ceux de l'original, au pixel près.
"""

from __future__ import annotations

import base64
import binascii
import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, UnidentifiedImageError


class MaskError(ValueError):
    """Masque illisible (message en français)."""


# Versions issues du palier « croquis » (issue parallèle) : la réparation ne s'applique qu'aux versions propres.
SKETCH_KINDS = frozenset({"croquis", "sketch"})


def is_sketch(params: dict[str, Any] | None) -> bool:
    params = params or {}
    kind = str(params.get("kind") or "").casefold()
    tier = str(params.get("tier") or "").casefold()
    return kind in SKETCH_KINDS or tier in SKETCH_KINDS or bool(params.get("sketch"))


# --- masque (fonctions pures) ------------------------------------------------------------
@dataclass(frozen=True)
class Region:
    """Rectangle en px de l'image (x2, y2 exclus)."""

    x1: float
    y1: float
    x2: float
    y2: float


def decode_png(data: str) -> bytes:
    """PNG en base64 (avec ou sans en-tête `data:image/png;base64,`)."""
    raw = data.split(",", 1)[1] if data.startswith("data:") else data
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise MaskError("masque illisible : PNG en base64 attendu") from None


def build_mask(size: tuple[int, int], regions: Sequence[Region] = (), painted: bytes | None = None) -> Image.Image:
    """Masque binaire (mode L : 255 = à repeindre) à la taille de l'image source.

    `painted` : masque peint (PNG, n'importe quelle taille, redimensionné) ; sa transparence compte
    s'il en a une, sinon sa luminosité (blanc = à repeindre).
    """
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for r in regions:
        x1, x2 = sorted((max(0.0, min(width, r.x1)), max(0.0, min(width, r.x2))))
        y1, y2 = sorted((max(0.0, min(height, r.y1)), max(0.0, min(height, r.y2))))
        if x2 - x1 >= 1 and y2 - y1 >= 1:
            draw.rectangle((round(x1), round(y1), round(x2) - 1, round(y2) - 1), fill=255)
    if painted:
        try:
            with Image.open(io.BytesIO(painted)) as img:
                img.load()
                layer = img.getchannel("A") if "A" in img.getbands() else img.convert("L")
        except (UnidentifiedImageError, OSError, SyntaxError):
            raise MaskError("masque illisible : ce n'est pas une image") from None
        layer = layer.resize(size, Image.Resampling.NEAREST).point(lambda v: 255 if v >= 128 else 0)
        mask = Image.fromarray(np.maximum(np.asarray(mask), np.asarray(layer)))
    return mask


def dilate(mask: Image.Image, px: int) -> Image.Image:
    """Agrandit la zone blanche de `px` pixels (voisinage carré), en numpy : rapide même pour 1 Mpx."""
    a = np.asarray(mask) > 0
    if px <= 0 or not a.any():
        return Image.fromarray((a * 255).astype(np.uint8))
    out = a.copy()
    for _ in range(px):  # max glissant ligne puis colonne : séparable pour un carré
        out[1:, :] |= a[:-1, :]
        out[:-1, :] |= a[1:, :]
        a = out.copy()
    for _ in range(px):
        out[:, 1:] |= a[:, :-1]
        out[:, :-1] |= a[:, 1:]
        a = out.copy()
    return Image.fromarray((out * 255).astype(np.uint8))


def influence_zone(mask: Image.Image, grow_px: int, feather_px: int) -> Image.Image:
    """Zone où la réparation peut toucher des pixels : masque + marge + adoucissement."""
    return dilate(mask, grow_px + feather_px)


def soften_mask(mask: Image.Image, grow_px: int, feather_px: int) -> Image.Image:
    """Masque agrandi de `grow_px` puis adouci sur `feather_px` (0–255).

    La zone d'origine vaut 255 ; hors de `influence_zone`, le masque vaut exactement 0.
    """
    grown = dilate(mask, grow_px)
    if feather_px <= 0:
        return grown
    blurred = np.asarray(grown.filter(ImageFilter.GaussianBlur(feather_px / 3)))
    zone = np.asarray(dilate(grown, feather_px)) > 0
    soft = np.where(zone, np.maximum(blurred, np.asarray(grown)), 0).astype(np.uint8)
    return Image.fromarray(np.maximum(soft, np.asarray(mask)))


def recompose(source: Image.Image, generated: Image.Image, soft_mask: Image.Image) -> Image.Image:
    """Recolle la zone repeinte sur l'original : hors masque (valeur 0), pixels de l'original.

    ComfyUI peut rendre une image un peu plus petite (côtés arrondis au multiple du VAE, recadrage
    centré) : elle est alors replacée au centre ; toute autre différence de taille est redimensionnée.
    """
    mode = "RGBA" if source.mode == "RGBA" else "RGB"
    src = source.convert(mode)
    gen = generated.convert(mode)
    if gen.size != src.size:
        dw, dh = src.width - gen.width, src.height - gen.height
        if 0 <= dw < 64 and 0 <= dh < 64:
            placed = src.copy()
            placed.paste(gen, (dw // 2, dh // 2))
            gen = placed
        else:
            gen = gen.resize(src.size, Image.Resampling.LANCZOS)
    return Image.composite(gen, src, soft_mask.convert("L"))


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
