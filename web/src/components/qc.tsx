"use client";

import type { DetectionBox, Detections, QCVerdict } from "@/lib/api";
import { QC_VERDICT } from "@/lib/qc";
import { InfoTip } from "./info-tip";

const VERDICT_TONES: Record<QCVerdict, string> = {
  ok: "bg-emerald-500 text-emerald-950",
  review: "bg-amber-400 text-amber-950",
  reject: "bg-red-500 text-white",
};

const VERDICT_SOFT: Record<QCVerdict, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  review: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  reject: "bg-red-500/15 text-red-300 ring-red-500/30",
};

/** Pastille QC : vert (ok), orange (à revoir), rouge (rejet), gris (pas contrôlée). */
export function QCBadge({
  verdict,
  score,
  override = false,
  soft = false,
  className = "",
}: {
  verdict: QCVerdict | null;
  score?: number | null;
  override?: boolean;
  soft?: boolean;
  className?: string;
}) {
  if (!verdict) {
    return (
      <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-inset ring-zinc-600 ${soft ? "text-zinc-400" : "bg-zinc-800/90 text-zinc-300"} ${className}`}>
        QC —
      </span>
    );
  }
  const label = `${QC_VERDICT[verdict]}${score !== null && score !== undefined ? ` · ${score}` : ""}${override ? " · validée à la main" : ""}`;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold ${soft ? `ring-1 ring-inset ${VERDICT_SOFT[verdict]}` : VERDICT_TONES[verdict]} ${className}`}
      data-testid="qc-badge"
      data-verdict={verdict}
    >
      {override && <span aria-hidden>✋</span>}
      {label}
    </span>
  );
}

const KIND_COLORS = { faces: "#34d399", hands: "#60a5fa", text: "#f87171" } as const;
const KIND_LABELS = { faces: "visage", hands: "main", text: "texte" } as const;

export function DetectionLegend() {
  return (
    <span className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-400">
      {(Object.keys(KIND_COLORS) as (keyof typeof KIND_COLORS)[]).map((k) => (
        <span key={k} className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm border-2" style={{ borderColor: KIND_COLORS[k] }} />
          {KIND_LABELS[k]}
        </span>
      ))}
      <InfoTip help="qc.detections" label="Détections du contrôle qualité" />
    </span>
  );
}

/**
 * Boîtes détectées (visages, mains, texte) superposées à une image. `fit` doit correspondre à
 * l'affichage de l'image : `cover` pour `object-cover`, `contain` pour `object-contain`.
 */
export function DetectionOverlay({ detections, fit = "contain" }: { detections: Detections; fit?: "cover" | "contain" }) {
  const { width, height } = detections;
  if (!width || !height) return null;
  const box = (b: DetectionBox, kind: keyof typeof KIND_COLORS, i: number) => (
    <g key={`${kind}-${i}`}>
      <rect
        x={b.x1}
        y={b.y1}
        width={Math.max(1, b.x2 - b.x1)}
        height={Math.max(1, b.y2 - b.y1)}
        fill="none"
        stroke={KIND_COLORS[kind]}
        strokeWidth={2}
        vectorEffect="non-scaling-stroke"
      />
      <title>{`${KIND_LABELS[kind]} — confiance ${b.score.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}`}</title>
    </g>
  );
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio={fit === "cover" ? "xMidYMid slice" : "xMidYMid meet"}
      role="img"
      aria-label={`Détections : ${detections.faces.length} visage(s), ${detections.hands.length} main(s), ${detections.text.length} zone(s) de texte`}
      data-testid="qc-boxes"
    >
      {detections.faces.map((b, i) => box(b, "faces", i))}
      {detections.hands.map((b, i) => box(b, "hands", i))}
      {detections.text.map((b, i) => box(b, "text", i))}
    </svg>
  );
}
