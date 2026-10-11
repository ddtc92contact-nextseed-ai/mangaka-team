// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { wordDiff } from "./dialog.ts";

test("mots gardés, retirés et ajoutés, morceaux fusionnés", () => {
  assert.deepEqual(wordDiff("Camera: medium shot, eye level.", "Camera: close-up, low-angle shot, eye level."), [
    { text: "Camera:", kind: "same" },
    { text: "medium", kind: "removed" },
    { text: "close-up, low-angle", kind: "added" },
    { text: "shot, eye level.", kind: "same" },
  ]);
});

test("ancien prompt vide : tout est ajouté ; textes identiques : rien ne change", () => {
  assert.deepEqual(wordDiff("", "Lucius runs."), [{ text: "Lucius runs.", kind: "added" }]);
  assert.deepEqual(wordDiff("Lucius  runs.", "Lucius runs."), [{ text: "Lucius runs.", kind: "same" }]);
});

test("textes trop longs : ancien retiré, nouveau ajouté, sans calcul", () => {
  const long = Array.from({ length: 700 }, (_, i) => `w${i}`).join(" ");
  const parts = wordDiff(long, `${long} end`);
  assert.deepEqual(
    parts.map((p) => p.kind),
    ["removed", "added"],
  );
});
