// Rangement des fichiers de la série (dossiers de ComfyUI, « Nettoyer les variantes non retenues »).
import type { CleanupResult } from "./api";

export const CLEANUP_CONFIRM =
  "Nettoyer les variantes non retenues ?\n\n" +
  "Les variantes de « Créer des références » et les essais de la planche de style qui n'ont pas été gardés " +
  "sont effacés définitivement, et les fichiers de transit de la série dans ComfyUI sont vidés.\n\n" +
  "Restent : les références gardées, les versions des cases (retenues ou non) et leur historique.";

/** Résumé lisible d'un nettoyage. */
export function cleanupSummary(result: CleanupResult): string {
  const n = result.variants_deleted;
  const variants =
    n === 0 ? "Aucune variante non retenue à effacer." : `${n} variante${n > 1 ? "s" : ""} non retenue${n > 1 ? "s" : ""} effacée${n > 1 ? "s" : ""}.`;
  return result.comfyui_cleaned ? `${variants} Fichiers de transit de ComfyUI vidés.` : variants;
}
