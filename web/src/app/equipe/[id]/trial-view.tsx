"use client";

import type { Rect, TrialResult, TrialSection } from "@/lib/api";
import { formatMs } from "@/lib/qc";

/** Résultat de « Essayer » : entrée → sortie, côte à côte. */
export function TrialView({ result }: { result: TrialResult }) {
  return (
    <div data-testid="trial-result">
      <p className="mb-3 text-xs text-zinc-500">Essai terminé en {formatMs(result.duration_ms)} · rien n&apos;a été enregistré.</p>
      {result.error && (
        <p role="alert" className="mb-3 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-200">
          {result.error}
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Column title="Entrée" sections={result.input} />
        <Column title="Sortie" sections={result.output} />
      </div>
    </div>
  );
}

function Column({ title, sections }: { title: string; sections: TrialSection[] }) {
  return (
    <section className="min-w-0 space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">{title}</h3>
      {sections.length === 0 && <p className="text-sm text-zinc-500">—</p>}
      {sections.map((s, i) => (
        <div key={i} className="rounded-lg border border-zinc-800 bg-zinc-950/60">
          <p className="border-b border-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-300">{s.title}</p>
          <div className="max-h-96 overflow-auto p-3">
            <SectionBody section={s} />
          </div>
        </div>
      ))}
    </section>
  );
}

function SectionBody({ section }: { section: TrialSection }) {
  if (section.kind === "text") {
    return <pre className="whitespace-pre-wrap break-words font-mono text-xs text-zinc-200">{section.text}</pre>;
  }
  if (section.kind === "layout") return <LayoutPreview data={section.data as LayoutData} />;
  if (section.kind === "bubbles") return <BubblesPreview data={section.data as BubblesData} />;
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-xs text-zinc-300">
      {JSON.stringify(section.data, null, 2)}
    </pre>
  );
}

interface LayoutData {
  page: { width: number; height: number };
  panels: (Rect & { reading_order: number; bubble_zone: Rect | null })[];
}

function LayoutPreview({ data }: { data: LayoutData }) {
  const { width, height } = data.page;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto h-80 w-auto rounded bg-white" role="img" aria-label="Planche d'essai">
      {data.panels.map((p) => (
        <g key={p.reading_order}>
          <rect x={p.x1} y={p.y1} width={p.x2 - p.x1} height={p.y2 - p.y1} fill="#f4f4f5" stroke="#18181b" strokeWidth={width / 250} />
          {p.bubble_zone && (
            <rect
              x={p.bubble_zone.x1}
              y={p.bubble_zone.y1}
              width={p.bubble_zone.x2 - p.bubble_zone.x1}
              height={p.bubble_zone.y2 - p.bubble_zone.y1}
              fill="#fda4af"
              fillOpacity={0.45}
            />
          )}
          <text
            x={(p.x1 + p.x2) / 2}
            y={(p.y1 + p.y2) / 2}
            fontSize={width / 12}
            textAnchor="middle"
            dominantBaseline="central"
            fill="#3f3f46"
          >
            {p.reading_order}
          </text>
        </g>
      ))}
    </svg>
  );
}

interface BubblesData {
  width: number;
  height: number;
  bubbles: {
    id: number;
    shape: { path: string; fill: string; stroke: string; stroke_px: number };
    font: { family: string; size_px: number; color: string };
    lines: { text: string; x: number; y: number }[];
  }[];
}

function BubblesPreview({ data }: { data: BubblesData }) {
  return (
    <svg
      viewBox={`0 0 ${data.width} ${data.height}`}
      className="w-full rounded bg-zinc-300"
      role="img"
      aria-label="Case d'essai lettrée"
    >
      {data.bubbles.map((b) => (
        <g key={b.id}>
          <path d={b.shape.path} fill={b.shape.fill} stroke={b.shape.stroke} strokeWidth={b.shape.stroke_px} />
          {b.lines.map((ln, i) => (
            <text
              key={i}
              x={ln.x}
              y={ln.y}
              textAnchor="middle"
              fontSize={b.font.size_px}
              fill={b.font.color}
              fontFamily="sans-serif"
            >
              {ln.text}
            </text>
          ))}
        </g>
      ))}
    </svg>
  );
}
