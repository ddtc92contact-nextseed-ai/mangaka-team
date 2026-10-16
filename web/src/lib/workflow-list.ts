// Liste « Workflow » de l'inspecteur de case (atelier).
import type { WorkflowPreset } from "./api";

/**
 * Workflows proposés à la main pour une case : génération de case (ni croquis, ni propre, ni ControlNet) avec au
 * moins un emplacement de référence, jamais celui des couvertures. Les workflows sans référence restent choisis
 * par l'appli (« Automatique ») quand personne n'est à l'écran. Le workflow déjà imposé à la case (`selected`)
 * reste listé, même hors de ces critères, pour que la liste montre toujours la valeur en cours.
 */
export function workshopPresets(presets: WorkflowPreset[], selected?: string | null): WorkflowPreset[] {
  return presets.filter(
    (p) =>
      p.id === selected ||
      ((p.role ?? "generation") === "generation" && p.reference_slots > 0 && !p.is_cover),
  );
}
