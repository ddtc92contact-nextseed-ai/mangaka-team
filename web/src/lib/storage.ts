// Rangement des fichiers de la série (dossiers de ComfyUI, « Nettoyer les variantes non retenues »).
import type { CleanupResult, LibraryResult } from "./api";

export const CLEANUP_CONFIRM =
  "Nettoyer les variantes non retenues ?\n\n" +
  "Les variantes de « Créer des références » et les essais de la planche de style qui n'ont pas été gardés " +
  "sont effacés définitivement, et les fichiers de transit de la série dans ComfyUI sont vidés.\n\n" +
  "Restent : les références gardées, les versions des cases (retenues ou non) et leur historique, et la " +
  "bibliothèque lisible de la série (references/, chapitre-01/…).";

/** Résumé lisible d'un nettoyage. */
export function cleanupSummary(result: CleanupResult): string {
  const n = result.variants_deleted;
  const variants =
    n === 0 ? "Aucune variante non retenue à effacer." : `${n} variante${n > 1 ? "s" : ""} non retenue${n > 1 ? "s" : ""} effacée${n > 1 ? "s" : ""}.`;
  return result.comfyui_cleaned ? `${variants} Fichiers de transit de ComfyUI vidés.` : variants;
}

/** Résumé lisible de « Reconstruire la bibliothèque ». */
export function librarySummary(result: LibraryResult): string {
  if (!result.enabled) return "Bibliothèque non écrite.";
  const plural = (n: number, word: string) => `${n} fichier${n > 1 ? "s" : ""} ${word}${n > 1 ? "s" : ""}`;
  const where = result.path ?? result.folder ?? "";
  if (result.written === 0 && result.removed === 0) return `Bibliothèque déjà à jour : ${where}`;
  const parts = [];
  if (result.written) parts.push(plural(result.written, "écrit"));
  if (result.removed) parts.push(plural(result.removed, "retiré"));
  return `Bibliothèque reconstruite (${parts.join(", ")}) : ${where}`;
}
