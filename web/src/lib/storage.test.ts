// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { CLEANUP_CONFIRM, cleanupSummary, librarySummary } from "./storage.ts";

const result = { variants_deleted: 0, comfyui_folders_removed: [], comfyui_cleaned: false, warning: null };

test("résumé du nettoyage, accordé au nombre de variantes", () => {
  assert.equal(cleanupSummary(result), "Aucune variante non retenue à effacer.");
  assert.equal(cleanupSummary({ ...result, variants_deleted: 1 }), "1 variante non retenue effacée.");
  assert.equal(
    cleanupSummary({ ...result, variants_deleted: 3, comfyui_cleaned: true }),
    "3 variantes non retenues effacées. Fichiers de transit de ComfyUI vidés.",
  );
});

test("la confirmation dit ce qui reste", () => {
  assert.match(CLEANUP_CONFIRM, /références gardées/);
  assert.match(CLEANUP_CONFIRM, /versions des cases/);
});

test("résumé de « Reconstruire la bibliothèque »", () => {
  const lib = { enabled: true, folder: "output/mangaka/lucius", path: "/c/output/mangaka/lucius", written: 0, removed: 0, warning: null };
  assert.equal(librarySummary(lib), "Bibliothèque déjà à jour : /c/output/mangaka/lucius");
  assert.equal(
    librarySummary({ ...lib, written: 3, removed: 1 }),
    "Bibliothèque reconstruite (3 fichiers écrits, 1 fichier retiré) : /c/output/mangaka/lucius",
  );
  assert.equal(librarySummary({ ...lib, enabled: false, path: null }), "Bibliothèque non écrite.");
});
