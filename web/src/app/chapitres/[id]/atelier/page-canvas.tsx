"use client";

import { useImperativeHandle, useRef, type KeyboardEvent, type Ref } from "react";
import { engineUrl, type Job, type LayoutPanel, type PageData, type PanelData, type QueueItem } from "@/lib/api";
import { PANEL_STATE } from "@/lib/generation";

/** Ce que montre une case de l'atelier, d'après la page, la file d'attente et le dernier job. */
export interface PanelView {
  panel: PanelData;
  running: QueueItem | null;
  pending: QueueItem[];
  failure: Job | null;
}

export type ArrowDir = "left" | "right" | "up" | "down";
const ARROWS: Record<string, ArrowDir> = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };

/** Case voisine la plus proche dans la direction donnée (centre à centre). */
export function neighbour(panels: LayoutPanel[], from: LayoutPanel, dir: ArrowDir): LayoutPanel | null {
  const c = (p: LayoutPanel) => ({ x: (p.x1 + p.x2) / 2, y: (p.y1 + p.y2) / 2 });
  const o = c(from);
  let best: LayoutPanel | null = null;
  let bestScore = Infinity;
  for (const p of panels) {
    if (p === from) continue;
    const q = c(p);
    const dx = q.x - o.x;
    const dy = q.y - o.y;
    const [main, cross] = dir === "left" ? [-dx, dy] : dir === "right" ? [dx, dy] : dir === "up" ? [-dy, dx] : [dy, dx];
    if (main <= 1) continue;
    const score = main + 2 * Math.abs(cross);
    if (score < bestScore) {
      bestScore = score;
      best = p;
    }
  }
  return best;
}

export interface PageCanvasHandle {
  focusPanel: (panelId: number) => void;
}

export function PageCanvas({
  page,
  views,
  selectedPanelId,
  onOpen,
  ref,
}: {
  page: PageData;
  views: Map<number, PanelView>;
  selectedPanelId: number | null;
  onOpen: (panelId: number) => void;
  ref?: Ref<PageCanvasHandle>;
}) {
  const buttons = useRef(new Map<number, HTMLButtonElement>());
  useImperativeHandle(ref, () => ({ focusPanel: (id) => buttons.current.get(id)?.focus() }), []);

  const layout = page.layout!;
  const { width: W, height: H } = layout.page;
  const byId = new Map(page.panels.map((p) => [p.id, p]));
  const panelOf = (lp: LayoutPanel) => (lp.panel_id !== null ? byId.get(lp.panel_id) : undefined) ?? page.panels[lp.index];

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, lp: LayoutPanel) {
    const dir = ARROWS[e.key];
    if (!dir) return;
    e.preventDefault();
    const next = neighbour(layout.panels, lp, dir);
    const target = next && panelOf(next);
    if (target) buttons.current.get(target.id)?.focus();
  }

  const pct = (v: number, total: number) => `${(v / total) * 100}%`;

  return (
    <div
      className="relative mx-auto overflow-hidden rounded-sm bg-zinc-100 shadow-lg shadow-black/40"
      style={{ aspectRatio: `${W} / ${H}`, width: `min(100%, calc(78vh * ${W} / ${H}))` }}
      data-testid="workshop-page"
      role="group"
      aria-label={`Page ${page.number} : ${layout.panels.length} cases. Flèches pour passer d'une case à l'autre, Entrée pour ouvrir.`}
    >
      {layout.panels.map((lp) => {
        const panel = panelOf(lp);
        if (!panel) return null;
        const view = views.get(panel.id);
        const selected = panel.id === selectedPanelId;
        const running = view?.running ?? null;
        const queued = !running && (view?.pending.length ?? 0) > 0;
        const failure = !running && !queued ? (view?.failure ?? null) : null;
        const stateLabel = running
          ? `Génération ${running.job.progress} %`
          : queued
            ? "En file"
            : failure
              ? "Échec"
              : PANEL_STATE[panel.state] ?? panel.state;
        return (
          <button
            key={lp.index}
            ref={(el) => {
              if (el) buttons.current.set(panel.id, el);
              else buttons.current.delete(panel.id);
            }}
            type="button"
            onClick={() => onOpen(panel.id)}
            onKeyDown={(e) => onKeyDown(e, lp)}
            aria-pressed={selected}
            aria-label={`Case ${panel.index + 1} — ${stateLabel}${panel.shot_type ? ` — ${panel.shot_type}` : ""}`}
            data-testid="workshop-panel"
            data-state={running ? "generating" : queued ? "queued" : failure ? "failed" : panel.state}
            className={`group absolute overflow-hidden bg-white transition-shadow focus-visible:z-20 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-sky-400 ${
              selected ? "z-10 ring-4 ring-rose-500" : "ring-2 ring-zinc-900 hover:ring-4 hover:ring-rose-300"
            }`}
            style={{
              left: pct(lp.x1, W),
              top: pct(lp.y1, H),
              width: pct(lp.width, W),
              height: pct(lp.height, H),
            }}
          >
            {panel.selected_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={engineUrl(panel.selected_image_url)}
                alt=""
                className={`h-full w-full object-cover ${running || queued ? "opacity-60" : ""}`}
                draggable={false}
              />
            ) : (
              <span className="flex h-full w-full flex-col items-center justify-center gap-1 bg-zinc-200 p-1 text-center text-zinc-600 [background-image:repeating-linear-gradient(45deg,transparent_0_10px,rgba(0,0,0,0.035)_10px_20px)]">
                <span className="text-lg font-bold leading-none text-zinc-800">{panel.index + 1}</span>
                <span className="text-[11px] font-medium leading-tight">{stateLabel}</span>
                {failure && <span className="sr-only">{failure.error}</span>}
              </span>
            )}
            {panel.selected_image_url && (
              <span className="absolute left-1 top-1 rounded bg-zinc-950/80 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-100">
                {panel.index + 1}
                {(running || queued || failure || panel.state === "review") && (
                  <span className="ml-1 font-normal text-zinc-300">· {stateLabel}</span>
                )}
              </span>
            )}
            {(running || queued) && (
              <span className="absolute inset-x-0 bottom-0 bg-zinc-950/80 px-1.5 py-1 text-left">
                <span className="block text-[10px] font-medium text-zinc-100">
                  {running ? `Génération ${running.job.progress} %` : `En file (${view!.pending.length})`}
                </span>
                <span className="mt-0.5 block h-1 overflow-hidden rounded bg-zinc-700">
                  <span
                    key={running?.job.id ?? "file"}
                    className={`block h-full transition-[width] duration-500 ${running ? "bg-rose-400" : "bg-zinc-500"}`}
                    style={{ width: `${running ? running.job.progress : 0}%` }}
                  />
                </span>
              </span>
            )}
            {failure && (
              <span className="absolute inset-x-0 bottom-0 bg-red-950/90 px-1.5 py-0.5 text-left text-[10px] font-medium text-red-200">
                Échec de la dernière génération
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
