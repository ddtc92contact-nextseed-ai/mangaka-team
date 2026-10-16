// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { hasLoraFile, loraSummary, loraUnsupportedNotice, NO_LORA } from "./lora.ts";

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

test("flux sans LoRA (FLUX 3 Klein) : avertissement en français avec la licence ; Qwen : rien", () => {
  const flux = { name: "FLUX 3 Klein · Qualité", engine: "flux3-klein", engine_name: "FLUX 3 Klein", supports_lora: false };
  const notice = loraUnsupportedNotice(flux);
  assert.ok(notice?.startsWith("Le flux de cette série (FLUX 3 Klein) ne prend pas de LoRA"));
  assert.match(notice!, /FLUX Kommunity interdit le fine-tuning/);
  assert.equal(loraUnsupportedNotice({ name: "Qualité", engine: "qwen-image", supports_lora: true }), null);
  // Flux encore inconnu (presets en chargement, ancien moteur) : pas d'alerte.
  assert.equal(loraUnsupportedNotice(undefined), null);
  assert.equal(loraUnsupportedNotice({ name: "Qualité" }), null);
  // Autre moteur sans LoRA : avertissement sans la ligne de licence FLUX.
  assert.doesNotMatch(loraUnsupportedNotice({ name: "Autre", supports_lora: false })!, /Kommunity/);
});
