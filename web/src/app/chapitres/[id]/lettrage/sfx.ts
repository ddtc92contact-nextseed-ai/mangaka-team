// Géométrie des onomatopées côté interface : même transformation que le moteur (rotate · skewX autour du centre).
import type { LetteredSfx, SfxUpdate } from "@/lib/api";
import type { Point } from "@/lib/layout";

export type SfxMode = "move" | "rotate" | "resize";

/** Ce qui suffit à dessiner une onomatopée ; `scale` : agrandissement en cours de glissé. */
export type SfxShape = Pick<LetteredSfx, "center" | "angle" | "skew" | "half"> & { scale?: number };

const rad = (deg: number) => (deg * Math.PI) / 180;

/** Matrice de rotate(angle) · skewX(skew) (y vers le bas : angle > 0 = sens horaire). */
export function sfxMatrix(angle: number, skew: number): [number, number, number, number] {
  const c = Math.cos(rad(angle));
  const s = Math.sin(rad(angle));
  const t = Math.tan(rad(skew));
  return [c, c * t - s, s, s * t + c];
}

export function sfxTransform(s: SfxShape): string {
  const scale = s.scale && s.scale !== 1 ? ` scale(${s.scale.toFixed(3)})` : "";
  return `translate(${s.center.x} ${s.center.y}) rotate(${s.angle}) skewX(${s.skew})${scale}`;
}

/** Coin bas-droit du contour (poignée de taille), en px de la page. */
export function sfxCorner(s: SfxShape): Point {
  const [a, b, c, d] = sfxMatrix(s.angle, s.skew);
  const k = s.scale ?? 1;
  const x = s.half.w * k;
  const y = s.half.h * k;
  return [s.center.x + a * x + b * y, s.center.y + c * x + d * y];
}

/** Poignée de rotation : au-dessus du texte, dans l'axe de l'onomatopée. */
export function sfxRotateHandle(s: SfxShape, gap: number): Point {
  const r = s.half.h * (s.scale ?? 1) + gap;
  return [s.center.x + Math.sin(rad(s.angle)) * r, s.center.y - Math.cos(rad(s.angle)) * r];
}

function normalizeAngle(deg: number): number {
  let a = deg % 360;
  if (a > 180) a -= 360;
  if (a < -180) a += 360;
  return Math.round(a * 10) / 10;
}

/** Aperçu et réglages envoyés au moteur pour un glissé de `start` à `now` (px de la page). */
export function applySfxDelta(
  fx: LetteredSfx,
  mode: SfxMode,
  start: Point,
  now: Point,
): { preview: SfxShape; update: SfxUpdate } {
  const { x: cx, y: cy } = fx.center;
  if (mode === "rotate") {
    const a0 = Math.atan2(start[1] - cy, start[0] - cx);
    const a1 = Math.atan2(now[1] - cy, now[0] - cx);
    const angle = normalizeAngle(fx.angle + ((a1 - a0) * 180) / Math.PI);
    return { preview: { ...fx, angle }, update: { angle } };
  }
  if (mode === "resize") {
    const d0 = Math.hypot(start[0] - cx, start[1] - cy) || 1;
    const d1 = Math.hypot(now[0] - cx, now[1] - cy);
    const scale = Math.min(5, Math.max(0.2, d1 / d0));
    const size = Math.min(300, Math.max(6, Math.round(fx.font.size_pt * scale * 2) / 2));
    return { preview: { ...fx, scale: size / fx.font.size_pt }, update: { size_pt: size } };
  }
  const x = Math.round(cx + now[0] - start[0]);
  const y = Math.round(cy + now[1] - start[1]);
  return { preview: { ...fx, center: { x, y } }, update: { x, y } };
}
