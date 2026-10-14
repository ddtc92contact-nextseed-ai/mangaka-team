// Rangement des fichiers de la série (dossiers de ComfyUI, « Nettoyer les variantes non retenues »).
import type { CleanupResult, LibraryResult, OrphanFolder, OrphansPreview, TidyResult } from "./api";

export const CLEANUP_CONFIRM_TITLE = "Nettoyer les variantes non retenues ?";

export const CLEANUP_CONFIRM =
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

const files = (n: number) => (n === 0 ? "vide" : `${n} fichier${n > 1 ? "s" : ""}`);

/** Ligne d'un dossier orphelin : `output/mangaka/les-lames-3 — 1 fichier`. */
export function orphanLabel(orphan: OrphanFolder): string {
  return `${orphan.area}/mangaka/${orphan.name} — ${files(orphan.files)}`;
}

/** Résumé de l'aperçu de « Ranger le dossier ComfyUI ». */
export function orphansSummary(preview: OrphansPreview): string {
  if (!preview.enabled) return "Rangement désactivé.";
  const n = preview.orphans.length;
  if (n === 0) return "Rien à ranger : chaque dossier de mangaka/ correspond à une série.";
  const where = preview.archive ? ` vers ${preview.archive}/` : "";
  return `${n} dossier${n > 1 ? "s" : ""} sans série à déplacer${where} (rien n'est supprimé) :`;
}

/** Résumé lisible de « Ranger le dossier ComfyUI ». */
export function tidySummary(result: TidyResult): string {
  if (!result.enabled) return "Rien n'a été rangé.";
  const n = result.moved.length;
  const moved = n === 0 ? "Aucun dossier déplacé." : `${n} dossier${n > 1 ? "s" : ""} déplacé${n > 1 ? "s" : ""} dans old/.`;
  const e = result.removed_empty;
  return e ? `${moved} ${e} dossier${e > 1 ? "s" : ""} vide${e > 1 ? "s" : ""} retiré${e > 1 ? "s" : ""}.` : moved;
}
