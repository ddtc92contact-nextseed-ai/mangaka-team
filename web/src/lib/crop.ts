// Cadrage de l'image dans sa case, côté écran : copie du calcul du moteur (engine/…/pipeline/crop.py).
// Sans cadrage, l'image remplit la case, centrée ; avec, la fenêtre visible est centrée sur (x, y) — fraction
// de l'image — et agrandie de `zoom` (1 = remplissage), toujours bornée : jamais de bande vide.
import type { PanelCrop } from "./api";

export const ZOOM_MAX = 4;
export const DEFAULT_CROP: PanelCrop = { x: 0.5, y: 0.5, zoom: 1 };

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/** Fenêtre de l'image [x1, y1, x2, y2] (unités de l'image) qui remplit la boîte w × h sans déformation. */
export function cropWindow(iw: number, ih: number, w: number, h: number, crop: PanelCrop | null = null): [number, number, number, number] {
  let scale = Math.max(w / iw, h / ih);
  if (!crop) {
    const cw = Math.min(iw, w / scale);
    const ch = Math.min(ih, h / scale);
    const x1 = Math.max(0, (iw - cw) / 2);
    const y1 = Math.max(0, (ih - ch) / 2);
    return [x1, y1, x1 + cw, y1 + ch];
  }
  scale *= clamp(crop.zoom, 1, ZOOM_MAX);
  const cw = Math.min(iw, w / scale);
  const ch = Math.min(ih, h / scale);
  const cx = clamp(crop.x * iw, cw / 2, iw - cw / 2);
  const cy = clamp(crop.y * ih, ch / 2, ih - ch / 2);
  const x1 = clamp(cx - cw / 2, 0, iw - cw);
  const y1 = clamp(cy - ch / 2, 0, ih - ch);
  return [x1, y1, x1 + cw, y1 + ch];
}

/** Image entière placée dans la boîte, en fractions de la boîte (pour un positionnement CSS en %). */
export function imagePlacement(iw: number, ih: number, w: number, h: number, crop: PanelCrop | null) {
  const [x1, y1, x2] = cropWindow(iw, ih, w, h, crop);
  const scale = w / (x2 - x1);
  return { left: (-x1 * scale) / w, top: (-y1 * scale) / h, width: (iw * scale) / w, height: (ih * scale) / h };
}

/** Cadrage ramené dans les bornes : zoom dans [1, limit], centre = celui réellement montré. */
export function boundedCrop(crop: PanelCrop, iw: number, ih: number, w: number, h: number, limit = ZOOM_MAX): PanelCrop {
  const zoom = clamp(crop.zoom, 1, Math.max(1, Math.min(limit, ZOOM_MAX)));
  const [x1, y1, x2, y2] = cropWindow(iw, ih, w, h, { ...crop, zoom });
  return { x: (x1 + x2) / 2 / iw, y: (y1 + y2) / 2 / ih, zoom };
}

/** Glisser l'image de (dx, dy) — fractions de la boîte — : la fenêtre part dans l'autre sens. */
export function panCrop(crop: PanelCrop, dx: number, dy: number, iw: number, ih: number, w: number, h: number, limit = ZOOM_MAX): PanelCrop {
  const start = boundedCrop(crop, iw, ih, w, h, limit);
  const [x1, , x2] = cropWindow(iw, ih, w, h, start);
  const scale = w / (x2 - x1); // px de la boîte par unité de l'image
  return boundedCrop({ ...start, x: start.x - (dx * w) / scale / iw, y: start.y - (dy * h) / scale / ih }, iw, ih, w, h, limit);
}

/** Changer le zoom en gardant le centre de la fenêtre (borné). */
export function zoomCrop(crop: PanelCrop, zoom: number, iw: number, ih: number, w: number, h: number, limit = ZOOM_MAX): PanelCrop {
  return boundedCrop({ ...crop, zoom }, iw, ih, w, h, limit);
}

/** Le zoom est-il au maximum permis ? */
export function atMaxZoom(crop: PanelCrop, limit: number): boolean {
  return crop.zoom >= Math.min(limit, ZOOM_MAX) - 1e-3;
}
