// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { WorkflowPreset } from "./api.ts";
import { workshopPresets } from "./workflow-list.ts";

function preset(id: string, extra: Partial<WorkflowPreset> = {}): WorkflowPreset {
  return {
    id,
    name: id,
    description: "",
    params: [],
    reference_slots: 0,
    supports_lora: true,
    lora_loader: null,
    timeout_s: 600,
    is_default: false,
    is_reference_default: false,
    with_references: null,
    has_trial: false,
    tier: null,
    tier_choice: null,
    tier_order: null,
    estimated_s: null,
    is_quality: false,
    ...extra,
  };
}

const PRESETS = [
  preset("qwen-image-base-qualite"), // sans référence : choisi seul par l'appli
  preset("qwen-image-turbo"),
  preset("qwen-image-edit-ref-qualite", { reference_slots: 5 }),
  preset("qwen-image-edit-ref-turbo", { reference_slots: 5 }),
  preset("qwen-image-couverture", { reference_slots: 5, is_cover: true }),
  preset("qwen-image-edit-ref-croquis", { reference_slots: 5, role: "croquis" }),
  preset("qwen-image-edit-ref-from-sketch", { reference_slots: 5, role: "propre" }),
  preset("qwen-image-edit-ref-controlnet", { reference_slots: 5, role: "controle" }),
];

test("liste Workflow : flux de case avec références seulement, sans la couverture", () => {
  assert.deepEqual(
    workshopPresets(PRESETS).map((p) => p.id),
    ["qwen-image-edit-ref-qualite", "qwen-image-edit-ref-turbo"],
  );
});

test("le workflow déjà imposé à la case reste listé", () => {
  assert.deepEqual(
    workshopPresets(PRESETS, "qwen-image-turbo").map((p) => p.id),
    ["qwen-image-turbo", "qwen-image-edit-ref-qualite", "qwen-image-edit-ref-turbo"],
  );
  assert.equal(workshopPresets(PRESETS, null).length, 2);
});
