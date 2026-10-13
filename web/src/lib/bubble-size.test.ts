// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { previewSizePt } from "./bubble-size.ts";

const font = { size_pt: 9, min_size_pt: 6.5, max_size_pt: 14, manual_size: false };
const box = { w: 400, h: 240 };

test("agrandir la bulle fait grandir le texte, plafonné au maximum du style", () => {
  assert.equal(previewSizePt(font, box, { w: 600, h: 360 }), 13.5);
  assert.equal(previewSizePt(font, box, { w: 4000, h: 2400 }), 14);
  // Le plus petit rapport des côtés compte : élargir seulement ne fait pas grandir.
  assert.equal(previewSizePt(font, box, { w: 800, h: 240 }), 9);
});

test("rétrécir la bulle fait baisser le texte jusqu'au minimum", () => {
  assert.equal(previewSizePt(font, box, { w: 320, h: 192 }), 7);
  assert.equal(previewSizePt(font, box, { w: 40, h: 24 }), 6.5);
});

test("une taille saisie à la main ne suit pas le cadre", () => {
  assert.equal(previewSizePt({ ...font, manual_size: true, size_pt: 8 }, box, { w: 800, h: 480 }), 8);
});
