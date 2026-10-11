// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { toneSummary } from "./qc.ts";

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
