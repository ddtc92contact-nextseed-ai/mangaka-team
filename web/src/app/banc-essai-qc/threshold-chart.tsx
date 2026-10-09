"use client";

import { useState, type MouseEvent } from "react";
import type { BenchLayerMetrics, BenchPoint } from "@/lib/api";
import { formatPct } from "@/lib/qc";

// Palette validée (scripts/validate_palette.js, mode sombre sur zinc-900) : séparation CVD ΔE 16.
const PRECISION = "#0284c7";
const RECALL = "#f43f5e";

const W = 640;
const H = 260;
const M = { top: 16, right: 76, bottom: 34, left: 44 };
const IW = W - M.left - M.right;
const IH = H - M.top - M.bottom;

const x = (t: number) => M.left + (t / 100) * IW;
const y = (v: number) => M.top + (1 - v) * IH;

/** Chemin d'une série ; les points non mesurables (null) coupent la ligne. */
function path(points: BenchPoint[], key: "precision" | "recall"): string {
  let d = "";
  let open = false;
  for (const p of points) {
    const v = p[key];
    if (v === null) {
      open = false;
      continue;
    }
    d += `${open ? "L" : "M"}${x(p.threshold).toFixed(1)},${y(v).toFixed(1)}`;
    open = true;
  }
  return d;
}

function lastValue(points: BenchPoint[], key: "precision" | "recall"): number | null {
  for (let i = points.length - 1; i >= 0; i--) if (points[i][key] !== null) return points[i][key];
  return null;
}

/** Courbe seuil → précision / rappel d'une couche, avec seuil actuel, seuil suggéré et objectif de rappel. */
export function ThresholdChart({ metrics, targetRecall, variable }: { metrics: BenchLayerMetrics; targetRecall: number; variable: string }) {
  const [hover, setHover] = useState<BenchPoint | null>(null);
  const points = metrics.sweep;
  const current = metrics.current_threshold;
  const suggested = metrics.suggested?.threshold ?? null;

  function onMove(e: MouseEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const t = Math.round(((e.clientX - box.left) / box.width) * 100);
    setHover(points.find((p) => p.threshold === Math.max(0, Math.min(100, t))) ?? null);
  }

  // Étiquettes directes en fin de ligne, écartées si elles se chevauchent.
  const pEnd = lastValue(points, "precision");
  const rEnd = lastValue(points, "recall");
  let pY = pEnd !== null ? y(pEnd) : null;
  let rY = rEnd !== null ? y(rEnd) : null;
  if (pY !== null && rY !== null && Math.abs(pY - rY) < 14) {
    const mid = (pY + rY) / 2;
    [pY, rY] = pY <= rY ? [mid - 7, mid + 7] : [mid + 7, mid - 7];
  }

  return (
    <figure className="space-y-2" data-testid="threshold-chart">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-400">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: PRECISION }} /> Précision
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: RECALL }} /> Rappel
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-3 border-l border-dashed border-zinc-400" /> Seuil actuel
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-3 border-l-2 border-emerald-400" /> Seuil suggéré
        </span>
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Précision et rappel de « ${metrics.label} » selon le seuil (${variable})`}>
          {[0, 0.25, 0.5, 0.75, 1].map((v) => (
            <g key={v}>
              <line x1={M.left} x2={M.left + IW} y1={y(v)} y2={y(v)} className="stroke-zinc-800" strokeWidth={1} />
              <text x={M.left - 6} y={y(v) + 4} textAnchor="end" className="fill-zinc-500 text-[10px]">
                {v * 100} %
              </text>
            </g>
          ))}
          {[0, 20, 40, 60, 80, 100].map((t) => (
            <text key={t} x={x(t)} y={H - M.bottom + 16} textAnchor="middle" className="fill-zinc-500 text-[10px]">
              {t}
            </text>
          ))}
          <text x={M.left + IW / 2} y={H - 4} textAnchor="middle" className="fill-zinc-500 text-[10px]">
            Seuil ({variable}) — case signalée si valeur &lt; seuil
          </text>
          <line x1={M.left} x2={M.left + IW} y1={y(targetRecall)} y2={y(targetRecall)} className="stroke-zinc-500" strokeDasharray="2 4" strokeWidth={1} />
          <text x={M.left + 4} y={y(targetRecall) - 4} className="fill-zinc-500 text-[10px]">
            objectif de rappel {formatPct(targetRecall)}
          </text>
          {current !== null && (
            <line x1={x(current)} x2={x(current)} y1={M.top} y2={M.top + IH} className="stroke-zinc-400" strokeDasharray="4 3" strokeWidth={1} />
          )}
          {suggested !== null && <line x1={x(suggested)} x2={x(suggested)} y1={M.top} y2={M.top + IH} className="stroke-emerald-400" strokeWidth={2} />}
          <path d={path(points, "precision")} fill="none" stroke={PRECISION} strokeWidth={2} strokeLinejoin="round" />
          <path d={path(points, "recall")} fill="none" stroke={RECALL} strokeWidth={2} strokeLinejoin="round" />
          {pY !== null && (
            <text x={M.left + IW + 6} y={pY + 4} className="fill-zinc-300 text-[11px]">
              Précision
            </text>
          )}
          {rY !== null && (
            <text x={M.left + IW + 6} y={rY + 4} className="fill-zinc-300 text-[11px]">
              Rappel
            </text>
          )}
          {hover && (
            <g pointerEvents="none">
              <line x1={x(hover.threshold)} x2={x(hover.threshold)} y1={M.top} y2={M.top + IH} className="stroke-zinc-300" strokeWidth={1} />
              {(["precision", "recall"] as const).map((k) =>
                hover[k] !== null ? (
                  <circle key={k} cx={x(hover.threshold)} cy={y(hover[k]!)} r={4} fill={k === "precision" ? PRECISION : RECALL} className="stroke-zinc-900" strokeWidth={2} />
                ) : null,
              )}
            </g>
          )}
          <rect x={M.left} y={M.top} width={IW} height={IH} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        </svg>
        {hover && (
          <div
            className="pointer-events-none absolute top-2 rounded-md border border-zinc-700 bg-zinc-950/95 px-2.5 py-1.5 text-xs text-zinc-300 shadow-lg"
            style={{ left: `${(x(hover.threshold) / W) * 100}%`, transform: hover.threshold > 60 ? "translateX(calc(-100% - 8px))" : "translateX(8px)" }}
            data-testid="chart-tooltip"
          >
            <p className="font-medium text-zinc-100">Seuil {hover.threshold}</p>
            <p>Précision : {formatPct(hover.precision)}</p>
            <p>Rappel : {formatPct(hover.recall)}</p>
            <p className="text-zinc-500">
              {hover.tp + hover.fp} signalée{hover.tp + hover.fp > 1 ? "s" : ""} · {hover.fn} mauvaise{hover.fn > 1 ? "s" : ""} laissée{hover.fn > 1 ? "s" : ""} passer
            </p>
          </div>
        )}
      </div>
      <details className="text-xs text-zinc-400">
        <summary className="cursor-pointer hover:text-zinc-200">Valeurs de la courbe (tableau)</summary>
        <div className="mt-2 max-h-60 overflow-y-auto">
          <table className="w-full text-left tabular-nums">
            <thead className="sticky top-0 bg-zinc-900 text-zinc-500">
              <tr>
                <th className="py-1 font-normal">Seuil</th>
                <th className="py-1 font-normal">Précision</th>
                <th className="py-1 font-normal">Rappel</th>
                <th className="py-1 font-normal">FP</th>
                <th className="py-1 font-normal">FN</th>
              </tr>
            </thead>
            <tbody>
              {points
                .filter((p) => p.threshold % 5 === 0 || p.threshold === current || p.threshold === suggested)
                .map((p) => (
                  <tr key={p.threshold} className={p.threshold === suggested ? "text-emerald-300" : ""}>
                    <td className="py-0.5">{p.threshold}</td>
                    <td>{formatPct(p.precision)}</td>
                    <td>{formatPct(p.recall)}</td>
                    <td>{p.fp}</td>
                    <td>{p.fn}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
