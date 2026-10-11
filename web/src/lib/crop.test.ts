// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { atMaxZoom, boundedCrop, cropWindow, DEFAULT_CROP, imagePlacement, panCrop, zoomCrop } from "./crop.ts";

const near = (a: number[], b: number[]) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 1e-6, `${a} ≠ ${b}`));

test("sans cadrage ou cadrage par défaut : remplissage centré (même calcul que le moteur)", () => {
  near(cropWindow(1000, 500, 400, 400), [250, 0, 750, 500]);
  near(cropWindow(1000, 500, 400, 400, DEFAULT_CROP), [250, 0, 750, 500]);
  const p = imagePlacement(1000, 500, 400, 400, null);
  near([p.left, p.top, p.width, p.height], [-0.5, 0, 2, 1]);
});

test("bornes : jamais de bande vide, dézoom limité au remplissage", () => {
  near(cropWindow(1000, 500, 400, 400, { x: 0, y: 0.5, zoom: 1 }), [0, 0, 500, 500]);
  near(cropWindow(1000, 500, 400, 400, { x: 1, y: 1, zoom: 2 }), [750, 250, 1000, 500]);
  near(cropWindow(1000, 500, 400, 400, { x: 0.5, y: 0.5, zoom: 0.2 }), [250, 0, 750, 500]);
  const b = boundedCrop({ x: 0, y: 0, zoom: 1 }, 1000, 500, 400, 400);
  near([b.x, b.y, b.zoom], [0.25, 0.5, 1]);
});

test("changement de boîte : même cadrage recalculé et borné", () => {
  const crop = { x: 0.9, y: 0.5, zoom: 1 };
  near(cropWindow(1000, 500, 800, 200, crop), [0, 125, 1000, 375]);
  near(cropWindow(1000, 500, 100, 400, crop), [837.5, 0, 962.5, 500]);
});

test("glisser et zoomer", () => {
  // Glisser l'image d'un quart de case vers la droite : la fenêtre part à gauche de 125 px d'image.
  const moved = panCrop(DEFAULT_CROP, 0.25, 0, 1000, 500, 400, 400);
  near([moved.x, moved.y], [0.375, 0.5]);
  const zoomed = zoomCrop(DEFAULT_CROP, 9, 1000, 500, 400, 400, 2.5);
  assert.equal(zoomed.zoom, 2.5);
  assert.ok(atMaxZoom(zoomed, 2.5));
  assert.ok(!atMaxZoom(DEFAULT_CROP, 2.5));
  // Image trop petite : maximum = 1, déjà atteint.
  assert.ok(atMaxZoom(DEFAULT_CROP, 1));
});
