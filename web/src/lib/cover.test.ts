// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  chapterOwners,
  flatOrderLabel,
  formatSummary,
  mmLabel,
  nextVolumeNumber,
  orderedChapterIds,
  previewSize,
  rectStyle,
  safetyRect,
  signCount,
  summaryLength,
  trimRect,
} from "./cover.ts";

const manga = {
  width_mm: 130,
  height_mm: 180,
  bleed_mm: 3,
  safety_mm: 5,
  full_width_mm: 136,
  full_height_mm: 186,
  dpi: 300,
};
const a4 = { ...manga, width_mm: 210, height_mm: 297, safety_mm: 8, full_width_mm: 216, full_height_mm: 303 };

test("aperçu à l'échelle : même échelle pour tous les formats, fond perdu compris", () => {
  const m = previewSize(manga);
  const big = previewSize(a4);
  assert.deepEqual(m, { width: 354, height: 484 });
  assert.ok(big.width > m.width && big.height > m.height);
  assert.ok(Math.abs(m.width / m.height - 136 / 186) < 0.01);
});

test("trait de coupe et zone de sécurité en fraction de l'image complète", () => {
  const t = trimRect(manga);
  assert.ok(Math.abs(t.x - 3 / 136) < 1e-9 && Math.abs(t.height - 180 / 186) < 1e-9);
  const s = safetyRect(manga);
  assert.ok(Math.abs(s.x - 8 / 136) < 1e-9 && Math.abs(s.width - 120 / 136) < 1e-9);
  assert.deepEqual(rectStyle({ x: 0.5, y: 0.25, width: 0.1, height: 0.2 }), {
    left: "50.000%",
    top: "25.000%",
    width: "10.000%",
    height: "20.000%",
  });
  assert.equal(formatSummary(manga), "130 × 180 mm · 300 dpi · fond perdu 3 mm");
});

test("un chapitre dans un seul tome ; numéro suivant ; ordre des chapitres", () => {
  const volumes = [
    { id: 1, number: 1, chapters: [{ id: 10 }, { id: 11 }] },
    { id: 2, number: 2, chapters: [{ id: 12 }] },
  ];
  const owners = chapterOwners(volumes, 2);
  assert.equal(owners.get(10), 1);
  assert.equal(owners.has(12), false); // le tome édité ne se bloque pas lui-même
  assert.equal(nextVolumeNumber(volumes), 3);
  assert.equal(nextVolumeNumber([]), 1);
  const chapters = [
    { id: 12, number: 3 },
    { id: 10, number: 1 },
    { id: 11, number: 2 },
  ];
  assert.deepEqual(orderedChapterIds([12, 10], chapters), [10, 12]);
});

test("signes du résumé : espaces et paragraphes comptent pour une espace, comme le moteur", () => {
  assert.equal(signCount("Été  brûlant.\n\nÇa  commence !"), "Été brûlant. Ça commence !".length);
  assert.equal(signCount("   "), 0);
});

test("longueur du résumé par rapport aux bornes", () => {
  assert.equal(summaryLength("a".repeat(599), 600, 900).state, "short");
  assert.equal(summaryLength("a".repeat(600), 600, 900).state, "ok");
  const long = summaryLength("a".repeat(901), 600, 900);
  assert.equal(long.state, "long");
  assert.match(long.label, /^901 signes · visé 600 à 900/);
});

test("ordre de la couverture à plat selon le sens de lecture", () => {
  assert.match(flatOrderLabel(["front", "spine", "back"], "rtl"), /^1re · dos · 4e — .*à gauche du dos/);
  assert.match(flatOrderLabel(["back", "spine", "front"], "ltr"), /^4e · dos · 1re — .*à droite du dos/);
  assert.equal(mmLabel(12.14), "12,1 mm");
});
