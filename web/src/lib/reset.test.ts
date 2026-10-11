// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { RESET_WORD, isResetConfirmed, resetSummary } from "./reset.ts";

const result = {
  backup: "/data/backups/reset-2026-10-11-153000",
  all: false,
  series_deleted: 2,
  data_removed: ["projects"],
  comfyui_removed: ["output/mangaka/lucius-et-stan"],
  comfyui_warning: null,
};

test("seul le mot exact confirme la remise à zéro", () => {
  assert.equal(RESET_WORD, "RÉINITIALISER");
  assert.ok(isResetConfirmed("RÉINITIALISER"));
  assert.ok(isResetConfirmed("  RÉINITIALISER "));
  assert.ok(isResetConfirmed("RÉINITIALISER")); // É décomposé (normalisé)
  assert.ok(!isResetConfirmed("REINITIALISER"));
  assert.ok(!isResetConfirmed("réinitialiser"));
  assert.ok(!isResetConfirmed(""));
});

test("résumé : séries, sauvegarde, ComfyUI", () => {
  assert.deepEqual(resetSummary(result), [
    "2 séries effacées.",
    "Sauvegarde : /data/backups/reset-2026-10-11-153000",
    "ComfyUI : 1 dossier effacé (old/ conservé).",
  ]);
  const lines = resetSummary({ ...result, all: true, series_deleted: 1, comfyui_warning: "COMFYUI_DIR non renseigné" });
  assert.equal(lines[0], "1 série effacée.");
  assert.match(lines[2], /savoir-faire remis par défaut/);
  assert.equal(lines[3], "ComfyUI non nettoyé : COMFYUI_DIR non renseigné.");
});
