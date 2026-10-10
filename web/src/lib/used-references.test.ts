// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { UsedReference } from "./api.ts";
import { STYLE_REFERENCE_BADGE, describeUsedReference } from "./used-references.ts";

const KINDS = {
  character: { singular: "personnage", badge: "bg-violet-500/15 text-violet-200" },
  object: { singular: "objet", badge: "bg-amber-500/15 text-amber-200" },
  decor: { singular: "décor", badge: "bg-emerald-500/15 text-emerald-200" },
};

test("référence de style de la série (case à emplacement libre)", () => {
  const d = describeUsedReference({ kind: "style", asset_id: 4, image_id: 12 } as UsedReference, KINDS);
  assert.equal(d.badge, STYLE_REFERENCE_BADGE);
  assert.equal(d.name, "Référence de style");
  assert.equal(d.kindLabel, "style de la série");
});

test("entrée de la bibliothèque", () => {
  assert.deepEqual(describeUsedReference({ kind: "object", id: 2, name: "Katana", image_id: 5 }, KINDS), {
    badge: KINDS.object.badge,
    name: "Katana",
    kindLabel: "objet",
  });
});

test("version d'avant la bibliothèque : personnage par défaut", () => {
  const d = describeUsedReference({ character_id: 3, image_id: 7 }, KINDS);
  assert.equal(d.badge, KINDS.character.badge);
  assert.equal(d.name, "personnage n° 3");
});

test("type inconnu venu du moteur : repli, pas de plantage", () => {
  for (const kind of ["pose", "toString", "__proto__"]) {
    const d = describeUsedReference({ kind, image_id: 9 } as unknown as UsedReference, KINDS);
    assert.match(d.badge, /zinc/);
    assert.equal(d.name, "référence n° 9");
    assert.equal(d.kindLabel, kind);
  }
});
