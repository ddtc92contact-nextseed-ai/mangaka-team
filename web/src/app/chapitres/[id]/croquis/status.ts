import type { PanelData } from "@/lib/api";
import type { PanelView } from "../atelier/page-canvas";

export type Status = "running" | "queued" | "failed" | "clean" | "validated" | "sketch" | "empty";

/** Où en est une case au tri : génération en cours, propre, croquis validé, croquis à trier, rien. */
export function panelStatus(panel: PanelData, view: PanelView | undefined): Status {
  if (view?.running) return "running";
  if (view?.pending.length) return "queued";
  if (panel.selected_image_url) return "clean";
  if (panel.sketch_validated) return "validated";
  if (view?.failure) return "failed";
  if (panel.sketch_image_url) return "sketch";
  return "empty";
}

export const STATUS_LABEL: Record<Status, string> = {
  running: "Croquis en cours",
  queued: "En file",
  failed: "Échec",
  clean: "Au propre",
  validated: "Composition validée",
  sketch: "À trier",
  empty: "Pas encore croquée",
};

export const RING: Record<Status, string> = {
  running: "ring-2 ring-rose-400",
  queued: "ring-2 ring-zinc-500",
  failed: "ring-2 ring-red-500",
  clean: "ring-2 ring-sky-500",
  validated: "ring-4 ring-emerald-500",
  sketch: "ring-2 ring-zinc-900",
  empty: "ring-2 ring-zinc-900",
};

/** Une case est « validée » quand sa composition est retenue (ou qu'elle a déjà une version propre). */
export const isValidated = (p: PanelData) => Boolean(p.sketch_validated || p.selected_image_id !== null);

/** La name d'une page se valide quand chaque case a un croquis (ou déjà une version propre). */
export function unsketched(panels: PanelData[]): PanelData[] {
  return panels.filter((p) => !p.sketch_image_id && p.selected_image_id === null);
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n > 1 ? "s" : ""}`;
}
