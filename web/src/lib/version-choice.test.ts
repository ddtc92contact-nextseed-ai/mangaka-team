// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { isRetained, versionChoice } from "./version-choice.ts";

const sketch = (id: number) => ({ id, kind: "croquis", selected: false });
const final = (id: number, selected = false) => ({ id, kind: "final", selected });

test("croquis non validé (même plus ancien que le dernier) : « Valider ce croquis »", () => {
  const v1 = sketch(1);
  const choice = versionChoice(v1, 3); // v3 validé, v1 plus ancien
  assert.equal(choice.action, "validate");
  assert.equal(choice.label, "Valider ce croquis");
  assert.equal(choice.short, "Choisir celle-ci");
  assert.equal(choice.retained, false);
  assert.equal(versionChoice(v1, null).action, "validate");
});

test("croquis validé : « Croquis validé », plus rien à faire", () => {
  const choice = versionChoice(sketch(3), 3);
  assert.equal(choice.action, null);
  assert.equal(choice.label, "Croquis validé");
  assert.equal(choice.short, "Validé");
  assert.ok(isRetained(sketch(3), 3));
});

test("versions propres : choisir comme avant, le croquis validé n'y change rien", () => {
  assert.deepEqual(
    { a: versionChoice(final(5), 5).action, l: versionChoice(final(5), 5).label },
    { a: "select", l: "Choisir cette version" },
  );
  const chosen = versionChoice(final(6, true), null);
  assert.equal(chosen.action, null);
  assert.equal(chosen.label, "Version choisie");
  assert.equal(chosen.short, "Choisie");
});

test("un croquis n'est jamais « choisi » même si son drapeau selected traîne", () => {
  assert.equal(isRetained({ id: 2, kind: "croquis", selected: true }, null), false);
});
