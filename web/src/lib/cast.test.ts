// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { CastMember } from "./api.ts";
import { castCounts, castFaultLabel, secondariesToCreate } from "./cast.ts";

function member(name: string, over: Partial<CastMember> = {}): CastMember {
  return {
    key: `nom-${name}`,
    name,
    character_id: null,
    written: [name],
    appearances: [],
    panel_count: 1,
    images: 0,
    references: "aucune",
    role: "secondaire",
    needs: "portrait",
    crowd: false,
    mark: null,
    fault: "sans fiche",
    advice: null,
    lora_name: null,
    lora_weight: null,
    ...over,
  };
}

test("« Tout créer » : secondaires à régler, jamais les foules ni les principaux", () => {
  const members = [
    member("le garde"),
    member("Mina", { character_id: 3, fault: "sans image" }),
    member("des passants", { crowd: true }),
    member("Aiko", { character_id: 1, role: "principal", fault: null, images: 1, references: "portrait" }),
    member("Kaï", { role: "principal" }),
  ];
  assert.deepEqual(
    secondariesToCreate({ members }).map((m) => m.name),
    ["le garde", "Mina"],
  );
  assert.deepEqual(castCounts({ members }), { secondaries: 2, withoutCard: 3, withoutImage: 1 });
});

test("libellés des fautes", () => {
  assert.equal(castFaultLabel({ fault: "sans fiche" }), "sans fiche : ni référence ni description");
  assert.equal(castFaultLabel({ fault: "sans image" }), "fiche sans image de référence");
  assert.equal(castFaultLabel({ fault: null }), "");
});
