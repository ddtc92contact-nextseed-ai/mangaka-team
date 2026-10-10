// Libellés et petits calculs de l'étape « génération » (atelier, file d'attente).
import type { PanelImage, PanelState } from "./api";

export const PANEL_STATE: Record<PanelState, string> = {
  draft: "Brouillon",
  queued: "En file",
  generating: "Génération",
  review: "Générée",
  qc: "Contrôle qualité",
  flagged: "À revoir (QC)",
  approved: "QC ok",
};

export const MAX_VARIANTS = 4;
/** Seed valide pour le moteur : entier de 0 à 2⁶³ − 1 (comparé en BigInt, sans arrondi). */
export function isValidSeed(text: string): boolean {
  return /^\d{1,19}$/.test(text) && BigInt(text) <= BigInt("9223372036854775807");
}

/** « 45 s », « 2 min 05 s », « 1 h 10 min ». */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, "0")} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

/** « ~1 h 05 min », « ~12 min », « < 1 min » : temps estimé d'un chapitre ou d'une série. */
export function formatEstimate(seconds: number): string {
  const m = Math.round(Math.max(0, seconds) / 60);
  if (seconds > 0 && m === 0) return "< 1 min";
  if (m < 60) return `~${m} min`;
  return `~${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

export function imageDurationS(img: PanelImage): number | null {
  const ms = img.params.duration_ms;
  return typeof ms === "number" ? ms / 1000 : null;
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Lien vers une case dans l'atelier. */
export function workshopHref(chapterId: number, pageId?: number | null, panelId?: number | null): string {
  const q = new URLSearchParams();
  if (pageId) q.set("page", String(pageId));
  if (panelId) q.set("case", String(panelId));
  const qs = q.toString();
  return `/chapitres/${chapterId}/atelier${qs ? `?${qs}` : ""}`;
}

/** Vue « Production » d'un chapitre (planches qui se remplissent en direct). */
export function productionHref(chapterId: number, pageId?: number | null): string {
  return `/chapitres/${chapterId}/production${pageId ? `?page=${pageId}` : ""}`;
}

/** « Étape 4/8 » d'une génération en cours, lue dans le message du job (null si absente). */
export function generationStep(message: string | null | undefined): string | null {
  const m = /étape (\d+)\s*\/\s*(\d+)/i.exec(message ?? "");
  return m ? `Étape ${m[1]}/${m[2]}` : null;
}

/** Date du moteur (UTC, parfois sans fuseau) → millisecondes. */
export function engineTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(t) ? null : t;
}
