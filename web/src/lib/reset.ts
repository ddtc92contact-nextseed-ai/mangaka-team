// « Remettre l'atelier à zéro » (écran Réglages) : confirmation forte et résumé du résultat.
import type { ResetResult } from "./api";

export const RESET_WORD = "RÉINITIALISER";

/** Le mot tapé confirme-t-il la remise à zéro ? (espaces autour ignorés, accent obligatoire) */
export function isResetConfirmed(typed: string): boolean {
  return typed.trim().normalize("NFC") === RESET_WORD;
}

/** Lignes du résumé affiché après une remise à zéro. */
export function resetSummary(result: ResetResult): string[] {
  const n = result.series_deleted;
  const lines = [
    `${n} série${n > 1 ? "s" : ""} effacée${n > 1 ? "s" : ""}.`,
    `Sauvegarde : ${result.backup}`,
  ];
  if (result.all) lines.push("Réglages globaux des agents et savoir-faire remis par défaut.");
  lines.push(
    result.comfyui_warning
      ? `ComfyUI non nettoyé : ${result.comfyui_warning}.`
      : `ComfyUI : ${result.comfyui_removed.length} dossier${result.comfyui_removed.length > 1 ? "s" : ""} effacé${result.comfyui_removed.length > 1 ? "s" : ""} (old/ conservé).`,
  );
  return lines;
}
