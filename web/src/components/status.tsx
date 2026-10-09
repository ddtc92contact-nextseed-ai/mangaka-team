// Libellés et badges des statuts de série / chapitre.
import type { ChapterStatus, SeriesStatus } from "@/lib/api";

export const SERIES_STATUS: Record<SeriesStatus, string> = {
  ongoing: "En cours",
  paused: "En pause",
  completed: "Terminée",
  cancelled: "Arrêtée",
};

export const CHAPTER_STATUS: Record<ChapterStatus, string> = {
  draft: "Brouillon",
  script: "Scénario",
  layout: "Mise en page",
  generation: "Génération",
  lettering: "Lettrage",
  ready: "Prêt",
  published: "Publié",
};

const SERIES_TONE: Record<SeriesStatus, string> = {
  ongoing: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  paused: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  completed: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  cancelled: "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30",
};

const CHAPTER_TONE: Record<ChapterStatus, string> = {
  draft: "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30",
  script: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  layout: "bg-indigo-500/15 text-indigo-300 ring-indigo-500/30",
  generation: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  lettering: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  ready: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  published: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
};

const BADGE = "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset";

export function SeriesStatusBadge({ status }: { status: SeriesStatus }) {
  return <span className={`${BADGE} ${SERIES_TONE[status]}`}>{SERIES_STATUS[status]}</span>;
}

export function ChapterStatusBadge({ status }: { status: ChapterStatus }) {
  return (
    <span className={`${BADGE} ${CHAPTER_TONE[status]}`} data-testid="chapter-status">
      {CHAPTER_STATUS[status]}
    </span>
  );
}

/** « lun. 12 oct. » — une date de publication prévue (AAAA-MM-JJ, sans fuseau). */
export function formatPlannedDate(value: string | null): string {
  if (!value) return "—";
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
}
