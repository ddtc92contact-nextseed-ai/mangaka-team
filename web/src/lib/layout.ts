// Géométrie des cases côté interface : polygone (case en biais) ou rectangle (mise en page d'avant).
import type { Intensity, LayoutPanel, Rect, Rythme } from "./api";

export type Point = [number, number];

export const INTENSITIES: Record<Intensity, string> = {
  calme: "Calme",
  normal: "Normale",
  choc: "Choc (action)",
};

export const RYTHMES: Record<Rythme, string> = {
  lent: "Lent (ambiance)",
  normal: "Normal",
  rapide: "Rapide (action)",
};

export function rectPolygon(r: Rect): Point[] {
  return [
    [r.x1, r.y1],
    [r.x2, r.y1],
    [r.x2, r.y2],
    [r.x1, r.y2],
  ];
}

/** Polygone d'une case : celui du découpage, sinon son rectangle. */
export function panelPolygon(p: LayoutPanel | { polygon?: Point[] | null } & Rect): Point[] {
  return p.polygon && p.polygon.length >= 3 ? p.polygon : rectPolygon(p);
}

/** Attribut `points` d'un <polygon> SVG. */
export function svgPoints(poly: Point[]): string {
  return poly.map(([x, y]) => `${x},${y}`).join(" ");
}

/** `clip-path: polygon(…)` CSS, en % de la boîte englobante de la case. */
export function cssClipPath(poly: Point[], box: Rect): string {
  const w = box.x2 - box.x1 || 1;
  const h = box.y2 - box.y1 || 1;
  const pts = poly.map(([x, y]) => `${(((x - box.x1) / w) * 100).toFixed(3)}% ${(((y - box.y1) / h) * 100).toFixed(3)}%`);
  return `polygon(${pts.join(", ")})`;
}

/** Centre de gravité (pour poser un numéro au milieu d'une case en biais). */
export function centroid(poly: Point[]): Point {
  let a = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    const k = x1 * y2 - x2 * y1;
    a += k;
    cx += (x1 + x2) * k;
    cy += (y1 + y2) * k;
  }
  if (Math.abs(a) < 1e-6) {
    const xs = poly.map((p) => p[0]);
    const ys = poly.map((p) => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  }
  return [cx / (3 * a), cy / (3 * a)];
}

/** Polygone convexe rétréci de `d` (bordure intérieure, comme le rendu du moteur). */
export function insetPolygon(poly: Point[], d: number): Point[] {
  const n = poly.length;
  let area = 0;
  for (let i = 0; i < n; i++) area += poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1];
  const orient = area >= 0 ? 1 : -1;
  // Bords décalés vers l'intérieur, puis intersection des bords consécutifs.
  const lines = poly.map((p, i) => {
    const q = poly[(i + 1) % n];
    const dx = q[0] - p[0];
    const dy = q[1] - p[1];
    const len = Math.hypot(dx, dy) || 1;
    const nx = (-orient * dy) / len;
    const ny = (orient * dx) / len;
    return { p: [p[0] + nx * d, p[1] + ny * d] as Point, dx, dy };
  });
  const out: Point[] = [];
  for (let i = 0; i < n; i++) {
    const a = lines[(i + n - 1) % n];
    const b = lines[i];
    const den = a.dx * b.dy - a.dy * b.dx;
    if (Math.abs(den) < 1e-9) {
      out.push(b.p);
      continue;
    }
    const t = ((b.p[0] - a.p[0]) * b.dy - (b.p[1] - a.p[1]) * b.dx) / den;
    out.push([a.p[0] + a.dx * t, a.p[1] + a.dy * t]);
  }
  return out;
}
