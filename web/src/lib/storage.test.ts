// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { CLEANUP_CONFIRM, cleanupSummary, librarySummary, orphanLabel, orphansSummary, tidySummary } from "./storage.ts";

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

test("aperçu et résumé de « Ranger le dossier ComfyUI », en français", () => {
  const preview = {
    enabled: true,
    path: "/c",
    archive: "old/orphelins-2026-10-14",
    orphans: [
      { area: "output" as const, name: "les-lames-3", files: 1 },
      { area: "output" as const, name: "dragons", files: 0 },
    ],
    warning: null,
  };
  assert.equal(
    orphansSummary(preview),
    "2 dossiers sans série à déplacer vers old/orphelins-2026-10-14/ (rien n'est supprimé) :",
  );
  assert.equal(orphanLabel(preview.orphans[0]), "output/mangaka/les-lames-3 — 1 fichier");
  assert.equal(orphanLabel(preview.orphans[1]), "output/mangaka/dragons — vide");
  assert.match(orphansSummary({ ...preview, orphans: [] }), /Rien à ranger/);
  assert.equal(orphansSummary({ ...preview, enabled: false }), "Rangement désactivé.");
  assert.equal(
    tidySummary({ enabled: true, moved: ["a", "b"], removed_empty: 1, warning: null }),
    "2 dossiers déplacés dans old/. 1 dossier vide retiré.",
  );
  assert.equal(tidySummary({ enabled: true, moved: [], removed_empty: 0, warning: null }), "Aucun dossier déplacé.");
});
