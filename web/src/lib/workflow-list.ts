// Liste « Workflow » de l'inspecteur de case (atelier) et choix du flux de la fiche série.
import type { PresetsReload, WorkflowPreset } from "./api";

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

/** Libellé du groupe des flux sans moteur déclaré (`engine` absent du preset). */
export const OTHER_ENGINES = "Autres";

/** Moteurs connus, dans l'ordre d'affichage ; les autres suivent dans l'ordre des presets, « Autres » en dernier. */
const ENGINE_ORDER = ["qwen-image"];

export interface EngineGroup<T> {
  /** `engine` du preset ; null : « Autres ». */
  engine: string | null;
  label: string;
  items: T[];
}

type EngineFields = Pick<WorkflowPreset, "engine" | "engine_name">;

/** Nom affiché du moteur d'un flux (« Qwen-Image 2.1 ») ; « Autres » sans moteur déclaré. */
export function engineLabel(preset: EngineFields | null | undefined): string {
  if (!preset?.engine) return OTHER_ENGINES;
  return preset.engine_name || preset.engine;
}

/**
 * Flux groupés par moteur (un `<optgroup>` chacun), en gardant leur ordre dans chaque groupe. Un seul groupe
 * possible : l'appelant peut alors se passer des `<optgroup>`.
 */
export function groupByEngine<T extends EngineFields>(presets: T[]): EngineGroup<T>[] {
  const groups = new Map<string | null, EngineGroup<T>>();
  for (const p of presets) {
    const key = p.engine || null;
    let group = groups.get(key);
    if (!group) {
      group = { engine: key, label: engineLabel(p), items: [] };
      groups.set(key, group);
    }
    group.items.push(p);
  }
  const rank = (g: EngineGroup<T>) => {
    if (g.engine === null) return ENGINE_ORDER.length + 1;
    const i = ENGINE_ORDER.indexOf(g.engine);
    return i === -1 ? ENGINE_ORDER.length : i;
  };
  // Tri stable : les moteurs inconnus gardent l'ordre des presets entre eux.
  return [...groups.values()].sort((a, b) => rank(a) - rank(b));
}

/** Résumé de « Recharger les flux » : « 30 flux rechargés (Qwen-Image 2.1 : 30). » */
export function reloadSummary(result: Pick<PresetsReload, "workflows" | "engines" | "issues">): string {
  const engines = result.engines.map((e) => `${e.name} : ${e.workflows}`).join(", ");
  const head = `${result.workflows} flux rechargé${result.workflows > 1 ? "s" : ""}${engines ? ` (${engines})` : ""}.`;
  const n = result.issues.length;
  return n ? `${head} ${n} preset${n > 1 ? "s" : ""} à corriger :` : `${head} Aucun preset à corriger.`;
}
