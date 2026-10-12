// Case agrandie du lettrage : quelle fenêtre de la page montrer, à quelle taille, et passage
// écran ⇄ page (mêmes px de page que la planche entière : bulles et onomatopées ne bougent pas).
import type { Rect } from "./api";

/** Fenêtre de la page montrée (repère de la page, px à la résolution d'impression). */
export interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Boîte affichée à l'écran (getBoundingClientRect du SVG). */
export interface ScreenBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 4;
export const ZOOM_STEP = 1.25;

/** Fenêtre autour d'une case : son cadre (ou son polygone) + une marge, sans sortir de la page. */
export function panelView(
  panel: { box: Rect; polygon?: [number, number][] | null },
  page: { width: number; height: number },
  margin = 0.06,
): View {
  const pts = panel.polygon && panel.polygon.length >= 3 ? panel.polygon : null;
  const x1 = pts ? Math.min(...pts.map((p) => p[0])) : panel.box.x1;
  const y1 = pts ? Math.min(...pts.map((p) => p[1])) : panel.box.y1;
  const x2 = pts ? Math.max(...pts.map((p) => p[0])) : panel.box.x2;
  const y2 = pts ? Math.max(...pts.map((p) => p[1])) : panel.box.y2;
  const pad = Math.max(x2 - x1, y2 - y1) * margin;
  const left = Math.max(0, x1 - pad);
  const top = Math.max(0, y1 - pad);
  const right = Math.min(page.width, x2 + pad);
  const bottom = Math.min(page.height, y2 + pad);
  return { x: left, y: top, w: Math.max(1, right - left), h: Math.max(1, bottom - top) };
}

/** Taille d'écran (px CSS) de la fenêtre `view` ajustée à `space`, multipliée par `zoom`. */
export function fitSize(view: View, space: { width: number; height: number }, zoom = 1): { width: number; height: number } {
  const scale = Math.max(0, Math.min(space.width / view.w, space.height / view.h)) * zoom;
  return { width: Math.round(view.w * scale), height: Math.round(view.h * scale) };
}

export function clampZoom(zoom: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(zoom * 100) / 100));
}

/**
 * Point écran → px de la page, pour un SVG `viewBox = view` affiché dans `box`
 * (preserveAspectRatio par défaut : xMidYMid meet, la fenêtre est centrée sans déformation).
 */
export function screenToPage(point: { x: number; y: number }, box: ScreenBox, view: View): { x: number; y: number } {
  const scale = Math.min(box.width / view.w, box.height / view.h) || 1;
  const ox = box.left + (box.width - view.w * scale) / 2;
  const oy = box.top + (box.height - view.h * scale) / 2;
  return { x: view.x + (point.x - ox) / scale, y: view.y + (point.y - oy) / scale };
}

/** Inverse de `screenToPage` : px de la page → point écran. */
export function pageToScreen(point: { x: number; y: number }, box: ScreenBox, view: View): { x: number; y: number } {
  const scale = Math.min(box.width / view.w, box.height / view.h) || 1;
  const ox = box.left + (box.width - view.w * scale) / 2;
  const oy = box.top + (box.height - view.h * scale) / 2;
  return { x: ox + (point.x - view.x) * scale, y: oy + (point.y - view.y) * scale };
}
