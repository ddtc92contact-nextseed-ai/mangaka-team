// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { WorkflowPreset } from "./api.ts";
import { OTHER_ENGINES, engineLabel, groupByEngine, reloadSummary, workshopPresets } from "./workflow-list.ts";

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

const ENGINES = [
  preset("flux3-klein-edit-ref-qualite", { reference_slots: 5, engine: "flux3-klein", engine_name: "FLUX 3 Klein" }),
  preset("maison-ref", { reference_slots: 2 }), // sans `engine` : « Autres »
  preset("qwen-image-edit-ref-turbo", { reference_slots: 5, engine: "qwen-image", engine_name: "Qwen-Image 2.1" }),
  preset("flux3-klein-croquis", { reference_slots: 5, engine: "flux3-klein", engine_name: "FLUX 3 Klein", role: "croquis" }),
  preset("sdxl-ref", { reference_slots: 1, engine: "sdxl" }), // moteur inconnu : son id, avant « Autres »
  preset("qwen-image-edit-ref-qualite", { reference_slots: 5, engine: "qwen-image", engine_name: "Qwen-Image 2.1" }),
];

test("flux groupés par moteur : Qwen, FLUX, moteurs inconnus, puis « Autres »", () => {
  const groups = groupByEngine(workshopPresets(ENGINES));
  assert.deepEqual(
    groups.map((g) => [g.label, g.items.map((p) => p.id)]),
    [
      ["Qwen-Image 2.1", ["qwen-image-edit-ref-turbo", "qwen-image-edit-ref-qualite"]],
      ["FLUX 3 Klein", ["flux3-klein-edit-ref-qualite"]],
      ["sdxl", ["sdxl-ref"]],
      ["Autres", ["maison-ref"]],
    ],
  );
  assert.equal(groups.at(-1)?.engine, null);
});

test("nom du moteur d'un flux", () => {
  assert.equal(engineLabel(ENGINES[0]), "FLUX 3 Klein");
  assert.equal(engineLabel(ENGINES[1]), OTHER_ENGINES);
  assert.equal(engineLabel(ENGINES[4]), "sdxl");
  assert.equal(engineLabel(undefined), "Autres");
  assert.deepEqual(groupByEngine([]), []);
});

test("résumé du rechargement des flux", () => {
  const engines = [
    { engine: "qwen-image", name: "Qwen-Image 2.1", workflows: 30 },
    { engine: "flux3-klein", name: "FLUX 3 Klein", workflows: 7 },
  ];
  assert.equal(
    reloadSummary({ workflows: 37, engines, issues: [] }),
    "37 flux rechargés (Qwen-Image 2.1 : 30, FLUX 3 Klein : 7). Aucun preset à corriger.",
  );
  assert.equal(
    reloadSummary({ workflows: 1, engines: [], issues: [{ file: "workflows/x.yaml", message: "invalide" }] }),
    "1 flux rechargé. 1 preset à corriger :",
  );
});
