// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { hasLoraFile, loraSummary, NO_LORA } from "./lora.ts";

test("sans fichier : aucun LoRA, le poids stocké (0,8 par défaut) n'est pas montré", () => {
  for (const name of [null, undefined, "", "   "]) {
    assert.equal(hasLoraFile(name), false);
    assert.equal(loraSummary(name, 0.8), NO_LORA);
  }
  assert.equal(NO_LORA, "aucun LoRA");
});

test("avec un fichier : nom du fichier et poids, comme avant", () => {
  assert.equal(hasLoraFile("perso/aiko_v1.safetensors"), true);
  assert.equal(loraSummary("perso/aiko_v1.safetensors", 0.8), "LoRA aiko_v1.safetensors · poids 0,8");
  assert.equal(loraSummary("encre.safetensors", 1.25), "LoRA encre.safetensors · poids 1,25");
  assert.equal(loraSummary("encre.safetensors", null), "LoRA encre.safetensors");
});
