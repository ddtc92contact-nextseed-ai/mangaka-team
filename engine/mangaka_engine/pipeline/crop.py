"""Cadrage de l'image dans sa case : recadrage « au remplissage » centré, ou imposé à la main.

Sans cadrage enregistré, l'image remplit la case sans déformation, centrée (comportement historique).
Le cadrage manuel d'une case (`Panel.crop`) est indépendant de la résolution et de la boîte :

- `x`, `y` : centre de la fenêtre visible, en fraction de l'image (0–1, 0,5 = centre) ;
- `zoom` : agrandissement par rapport au remplissage (1 = l'image remplit tout juste la case).

Il est recalculé sur la boîte courante à chaque rendu, et borné : jamais de bande vide (zoom ≥ 1, la
fenêtre reste dans l'image) ni de zoom au-delà de `ZOOM_MAX`. Une case en biais est cadrée sur sa boîte
englobante. Le même calcul sert à l'assemblage PNG / SVG, aux visages du lettrage et aux aperçus
(`web/src/lib/crop.ts` en est la copie côté écran).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Zoom maximal absolu (×4 sur le remplissage).
ZOOM_MAX = 4.0
# Au-delà, l'image serait trop agrandie : px de la page par px de l'image (≈ 75 dpi pour une page à 300).
UPSCALE_MAX = 4.0


@dataclass(frozen=True)
class PanelCrop:
    x: float = 0.5
    y: float = 0.5
    zoom: float = 1.0

    @classmethod
    def parse(cls, raw: Any) -> PanelCrop | None:
        """Cadrage stocké → `PanelCrop` borné à [0, 1] et [1, ZOOM_MAX] ; None si absent ou illisible."""
        if not isinstance(raw, dict):
            return None
        try:
            x, y, zoom = float(raw.get("x", 0.5)), float(raw.get("y", 0.5)), float(raw.get("zoom", 1.0))
        except (TypeError, ValueError):
            return None
        if any(v != v or abs(v) == float("inf") for v in (x, y, zoom)):
            return None
        return cls(_clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0), _clamp(zoom, 1.0, ZOOM_MAX))

    def to_json(self) -> dict[str, float]:
        return {"x": round(self.x, 5), "y": round(self.y, 5), "zoom": round(self.zoom, 4)}


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def max_zoom(iw: int, ih: int, w: float, h: float) -> float:
    """Zoom maximal de la case : l'image n'est jamais agrandie au-delà de `UPSCALE_MAX` px de page par px
    d'image (ni au-delà de `ZOOM_MAX`) ; 1 = image trop petite, déjà au maximum en remplissage."""
    if iw <= 0 or ih <= 0 or w <= 0 or h <= 0:
        return 1.0
    fill = max(w / iw, h / ih)
    return _clamp(UPSCALE_MAX / fill, 1.0, ZOOM_MAX)


def bounded(crop: PanelCrop, iw: int, ih: int, w: float, h: float, limit: float | None = None) -> PanelCrop:
    """Cadrage ramené dans les bornes de la boîte w × h : zoom ≤ `limit` (défaut `ZOOM_MAX`), fenêtre dans l'image."""
    zoom = _clamp(crop.zoom, 1.0, limit if limit is not None else ZOOM_MAX)
    x1, y1, x2, y2 = crop_window(iw, ih, w, h, PanelCrop(crop.x, crop.y, zoom))
    return PanelCrop((x1 + x2) / 2 / iw, (y1 + y2) / 2 / ih, zoom)


def crop_window(
    iw: int, ih: int, w: float, h: float, crop: PanelCrop | None = None
) -> tuple[float, float, float, float]:
    """Zone de l'image (x1, y1, x2, y2, px de l'image) qui remplit w × h sans déformation."""
    scale = max(w / iw, h / ih)
    if crop is None:  # centrée : calcul historique, à l'identique (golden tests)
        cw, ch = min(iw, w / scale), min(ih, h / scale)
        x1, y1 = max(0.0, (iw - cw) / 2), max(0.0, (ih - ch) / 2)  # bornés : arrondis flottants (−1e-13)
        return x1, y1, x1 + cw, y1 + ch
    scale *= _clamp(crop.zoom, 1.0, ZOOM_MAX)
    cw, ch = min(iw, w / scale), min(ih, h / scale)
    cx = _clamp(crop.x * iw, cw / 2, iw - cw / 2)
    cy = _clamp(crop.y * ih, ch / 2, ih - ch / 2)
    x1, y1 = _clamp(cx - cw / 2, 0.0, iw - cw), _clamp(cy - ch / 2, 0.0, ih - ch)
    return x1, y1, x1 + cw, y1 + ch


def image_placement(
    iw: int, ih: int, x: float, y: float, w: float, h: float, crop: PanelCrop | None = None
) -> tuple[float, float, float]:
    """(échelle, x0, y0) : un point (u, v) de l'image va en (x0 + u × échelle, y0 + v × échelle) quand
    l'image est cadrée dans la boîte (x, y, w, h)."""
    if crop is None:
        scale = max(w / iw, h / ih)
        return scale, x + (w - iw * scale) / 2, y + (h - ih * scale) / 2
    x1, y1, x2, _ = crop_window(iw, ih, w, h, crop)
    scale = w / (x2 - x1)
    return scale, x - x1 * scale, y - y1 * scale
