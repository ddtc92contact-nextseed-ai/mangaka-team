// Direction artistique : libellés et petites aides de l'onglet du chapitre.
import type { DaPageChoc, DaRythme, Intensity, PageDirection } from "./api";

export const DA_RYTHMES: Record<DaRythme, string> = {
  calme: "Calme",
  montée: "Montée",
  climax: "Climax",
  respiration: "Respiration",
};

/** Couleur de pastille par rythme (lisible sur fond sombre). */
export const RYTHME_TONE: Record<DaRythme, string> = {
  calme: "bg-sky-500/15 text-sky-200 ring-sky-500/30",
  montée: "bg-amber-500/15 text-amber-200 ring-amber-500/30",
  climax: "bg-rose-500/20 text-rose-200 ring-rose-500/40",
  respiration: "bg-emerald-500/15 text-emerald-200 ring-emerald-500/30",
};

export const DA_INTENSITIES: Record<Intensity, string> = {
  calme: "Calme",
  normal: "Normale",
  choc: "Choc",
};

export const PAGE_CHOCS: Record<DaPageChoc, string> = {
  "pleine page": "Pleine page",
  splash: "Splash",
};

export const SFX_INTENSITIES: Record<string, string> = {
  léger: "léger",
  moyen: "moyen",
  fort: "fort",
};

/** « plan large » → « Plan large ». */
export function capitalize(text: string | null | undefined): string {
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

export const isLocked = (d: PageDirection, key: string) => d.locks.includes(key);

/** Clé de verrou d'un champ de case (« 12.plan »). */
export const panelKey = (panelId: number, field: string) => `${panelId}.${field}`;

export function pageState(d: PageDirection): { label: string; tone: string } {
  if (!d.has_direction) return { label: "à diriger", tone: "text-zinc-500" };
  if (d.out_of_date) return { label: "à refaire", tone: "text-amber-300" };
  if (d.applied && !d.pending) return { label: "appliquée", tone: "text-emerald-300" };
  if (d.status === "accepted") return { label: "acceptée", tone: "text-sky-300" };
  return { label: d.applied ? "modifiée" : "proposée", tone: "text-zinc-300" };
}
