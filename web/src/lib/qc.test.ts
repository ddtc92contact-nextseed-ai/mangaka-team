// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { colorSummary, toneSummary } from "./qc.ts";

test("tonalité mesurée : les deux parts et leurs cibles", () => {
  assert.equal(
    toneSummary({ checked: true, dark: 0.684, black: 0.3, max_dark: 0.45, max_black: 0.25, too_dark: true, message: null }),
    "Tonalité : 68 % de pixels sombres (cible ≤ 45 %) · 30 % de noir pur (cible ≤ 25 %)",
  );
});

test("tonalité non vérifiée (rendu couleur) ou absente", () => {
  assert.equal(
    toneSummary({ checked: false, dark: null, black: null, max_dark: 0.45, max_black: 0.25, too_dark: false, message: "rendu couleur" }),
    "Tonalité non vérifiée : rendu couleur",
  );
  assert.equal(toneSummary(undefined), null);
});

test("couleur sur une série N&B : saturation et cible, rien quand elle n'est pas vérifiée", () => {
  const base = { checked: true, dark: 0.2, black: 0.1, max_dark: 0.45, max_black: 0.25, too_dark: false, message: null };
  assert.equal(
    colorSummary({ ...base, color_checked: true, saturation: 0.095, max_saturation: 0.03, too_colorful: true }),
    "Couleur sur une série noir et blanc : 9,5 % de saturation (cible ≤ 3 %)",
  );
  assert.equal(
    colorSummary({ ...base, color_checked: true, saturation: 0.012, max_saturation: 0.03, too_colorful: false }),
    "Couleur : 1,2 % de saturation (cible ≤ 3 %)",
  );
  assert.equal(colorSummary({ ...base, color_checked: false, saturation: null, color_message: "rendu couleur" }), null);
  assert.equal(colorSummary(base), null); // ancien QC, sans mesure de couleur
});
