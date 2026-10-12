// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { clampZoom, fitSize, pageToScreen, panelView, screenToPage, ZOOM_MAX, ZOOM_MIN } from "./panel-zoom.ts";

const page = { width: 2480, height: 3508 };
const near = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  assert.ok(Math.abs(a.x - b.x) < 1e-6 && Math.abs(a.y - b.y) < 1e-6, `${JSON.stringify(a)} ≠ ${JSON.stringify(b)}`);

test("fenêtre de la case : son cadre plus une marge, bornée à la page", () => {
  const box = { x1: 200, y1: 300, x2: 1200, y2: 900 };
  assert.deepEqual(panelView({ box }, page, 0.1), { x: 100, y: 200, w: 1200, h: 800 });
  // Case collée au bord : la marge ne sort pas de la page.
  assert.deepEqual(panelView({ box: { x1: 0, y1: 0, x2: 500, y2: 400 } }, page, 0.1), { x: 0, y: 0, w: 550, h: 450 });
});

test("case en biais : la fenêtre englobe tout le polygone", () => {
  const v = panelView({ box: { x1: 0, y1: 0, x2: 10, y2: 10 }, polygon: [[300, 300], [1300, 250], [1250, 900], [320, 950]] }, page, 0);
  assert.deepEqual(v, { x: 300, y: 250, w: 1000, h: 700 });
});

test("un point posé dans la case agrandie tombe aux bonnes coordonnées de la page", () => {
  const view = panelView({ box: { x1: 200, y1: 300, x2: 1200, y2: 900 } }, page, 0.1); // 1200 × 800
  const size = fitSize(view, { width: 900, height: 900 }); // largeur limitante : × 0,75
  assert.deepEqual(size, { width: 900, height: 600 });
  const box = { left: 40, top: 120, ...size };
  // Coin haut-gauche de la fenêtre, centre de la case, coin bas-droit de la case.
  near(screenToPage({ x: 40, y: 120 }, box, view), { x: 100, y: 200 });
  near(screenToPage({ x: 40 + 450, y: 120 + 300 }, box, view), { x: 700, y: 600 });
  near(screenToPage({ x: 40 + (1200 - 100) * 0.75, y: 120 + (900 - 200) * 0.75 }, box, view), { x: 1200, y: 900 });
  // Aller-retour exact.
  near(pageToScreen(screenToPage({ x: 333, y: 444 }, box, view), box, view), { x: 333, y: 444 });
});

test("zoom : la taille suit le facteur, le passage écran → page reste juste", () => {
  const view = { x: 100, y: 200, w: 1200, h: 800 };
  const size = fitSize(view, { width: 900, height: 900 }, 2);
  assert.deepEqual(size, { width: 1800, height: 1200 });
  const box = { left: -500, top: -100, ...size }; // SVG défilé dans son conteneur
  near(screenToPage({ x: -500 + 1.5 * 600, y: -100 + 1.5 * 400 }, box, view), { x: 700, y: 600 });
  near(pageToScreen({ x: 700, y: 600 }, box, view), { x: -500 + 1.5 * 600, y: -100 + 1.5 * 400 });
});

test("boîte plus large que la fenêtre : centrée comme preserveAspectRatio meet", () => {
  const view = { x: 0, y: 0, w: 1000, h: 1000 };
  const box = { left: 0, top: 0, width: 2000, height: 1000 };
  near(screenToPage({ x: 500, y: 0 }, box, view), { x: 0, y: 0 });
  near(screenToPage({ x: 1000, y: 500 }, box, view), { x: 500, y: 500 });
});

test("zoom borné", () => {
  assert.equal(clampZoom(100), ZOOM_MAX);
  assert.equal(clampZoom(0.01), ZOOM_MIN);
  assert.equal(clampZoom(1.5625), 1.56);
});
