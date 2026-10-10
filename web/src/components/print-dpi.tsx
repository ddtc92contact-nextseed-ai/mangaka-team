// Indicateur de dpi d'impression d'une case (finition d'impression).
import type { PrintInfo } from "@/lib/api";
import { dpiShort, dpiTitle } from "@/lib/finishing";

const TONES: Record<PrintInfo["status"], string> = {
  ok: "bg-emerald-900/90 text-emerald-100",
  finished: "bg-emerald-900/90 text-emerald-100",
  low: "bg-amber-500/95 text-amber-950",
};

/** Petit badge « 115 dpi » (alerte sous le seuil) ou « 300 dpi ✓ » (au dpi cible / finalisée). */
export function DpiBadge({ info, className = "" }: { info: PrintInfo; className?: string }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${TONES[info.status]} ${className}`}
      title={dpiTitle(info)}
      data-testid="dpi-badge"
      data-status={info.status}
    >
      {info.status === "low" && <span aria-hidden>⚠ </span>}
      {dpiShort(info)}
    </span>
  );
}
