// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { NameNote } from "./api.ts";
import { noteKey } from "./name-notes.ts";

function note(chosen: number[]): NameNote {
  return {
    name: "Les voyous",
    source: "mise en scène",
    kind: "hors cadre en action",
    chosen: chosen.map((id) => ({ id, name: `Voyou ${id}` })),
    candidates: [],
    message: "",
  };
}

test("noteKey : même nom, même source, même motif → clés distinctes", () => {
  // Le bug #235 : « voyous » → une alerte par fiche, clé `kind-source-name` identique.
  const notes = [note([1]), note([2]), note([1, 2]), note([1, 2])];
  const keys = notes.map((n, i) => noteKey(n, i));
  assert.equal(new Set(keys).size, keys.length);
  assert.match(keys[2], /1\+2/);
});
