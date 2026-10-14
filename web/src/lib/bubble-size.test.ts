// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { previewSizePt } from "./bubble-size.ts";

// Bulle de parole placée automatiquement, telle que la renvoie le moteur (presets du dépôt, 300 DPI) ;
// les tailles attendues sont celles que le moteur calcule au lâcher (engine/tests/test_lettering.py).
const font = {
  size_pt: 9,
  min_size_pt: 6.5,
  max_size_pt: 48,
  manual_size: false,
  style_size_pt: 9,
  margin_px: { w: 59.06, h: 47.24 },
};
const box = { w: 453, h: 224 };
const near = (actual: number, engine: number) =>
  assert.ok(Math.abs(actual - engine) <= 0.5, `aperçu ${actual} pt, moteur ${engine} pt`);

test("agrandir la bulle fait grandir le texte en proportion (plus bloqué à 14 pt)", () => {
  assert.equal(previewSizePt(font, box, { w: 906, h: 448 }), 18);
  assert.equal(previewSizePt(font, box, { w: 1359, h: 672 }), 27);
  // Bulle énorme : plafond du style (fonts.yaml max_size_pt).
  assert.equal(previewSizePt(font, box, { w: 2718, h: 1344 }), 48);
  // Le plus petit rapport des côtés compte : élargir seulement ne fait pas grandir.
  assert.equal(previewSizePt(font, box, { w: 906, h: 224 }), 9);
});

test("rétrécir la bulle fait baisser le texte jusqu'au minimum", () => {
  near(previewSizePt(font, box, { w: 362, h: 179 }), 7);
  assert.equal(previewSizePt(font, box, { w: 40, h: 24 }), 6.5);
});

test("depuis un cadre déjà ajusté à la main, l'aperçu suit encore le moteur", () => {
  const filled = { ...font, size_pt: 18 };
  assert.equal(previewSizePt(filled, { w: 906, h: 448 }, { w: 1359, h: 672 }, true), 27);
  assert.equal(previewSizePt(filled, { w: 906, h: 448 }, box, true), 9);
});

test("bulle réduite par le placement automatique : ses marges sont celles de la taille normale", () => {
  const shrunk = { ...font, size_pt: 8 };
  assert.equal(previewSizePt(shrunk, { w: 413, h: 205 }, { w: 413, h: 205 }), 8);
  near(previewSizePt(shrunk, { w: 413, h: 205 }, { w: 826, h: 410 }), 16);
});

test("une taille saisie à la main ne suit pas le cadre", () => {
  assert.equal(previewSizePt({ ...font, manual_size: true, size_pt: 8 }, box, { w: 800, h: 480 }), 8);
});
