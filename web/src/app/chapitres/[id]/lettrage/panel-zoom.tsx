"use client";

import { useCallback, useState, type ReactNode, type Ref } from "react";
import { HelpLabel } from "@/components/info-tip";
import { Modal } from "@/components/modal";
import { Button, Card } from "@/components/ui";
import type { LetteringWarning, PageLettering, SfxUpdate } from "@/lib/api";
import { clampZoom, fitSize, panelView, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP } from "@/lib/panel-zoom";
import { LetteringCanvas, type CanvasEdit, type LetteringCanvasHandle } from "./lettering-canvas";

/** Avertissements du lettrage, avec un lien vers la bulle ou l'onomatopée concernée. */
export function LetteringWarnings({
  data,
  warnings,
  empty,
  onSelect,
}: {
  data: PageLettering;
  warnings: LetteringWarning[];
  empty: string;
  onSelect: (id: number) => void;
}) {
  return (
    <Card data-testid="lettering-warnings">
      <h2 className="mb-2 font-semibold text-zinc-100">
        <HelpLabel help="lettrage.warnings">Avertissements</HelpLabel>
      </h2>
      {warnings.length ? (
        <ul className="space-y-2 text-sm">
          {warnings.map((w, i) => (
            <li key={i} className="flex gap-2 text-amber-200">
              <span aria-hidden="true">⚠</span>
              <span>
                {w.message}
                {w.bubble_id !== null && (
                  <button
                    type="button"
                    className="ml-1 text-rose-300 underline hover:text-rose-200"
                    onClick={() => onSelect(w.bubble_id!)}
                  >
                    {data.sfx?.some((x) => x.id === w.bubble_id) ? "voir l'onomatopée" : "voir la bulle"}
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-zinc-400">{empty}</p>
      )}
    </Card>
  );
}

/** Avertissements qui touchent une case : la case elle-même, ses bulles et ses onomatopées. */
export function panelWarnings(data: PageLettering, panelId: number): LetteringWarning[] {
  const mine = new Set([
    ...data.bubbles.filter((b) => b.panel_id === panelId).map((b) => b.id),
    ...(data.sfx ?? []).filter((x) => x.panel_id === panelId).map((x) => x.id),
  ]);
  return data.warnings.filter((w) => w.panel_id === panelId || (w.bubble_id !== null && mine.has(w.bubble_id)));
}

/**
 * Case agrandie : la même toile de lettrage, cadrée sur une seule case et ajustée à la fenêtre.
 * Mêmes coordonnées de page, mêmes enregistrements : la planche suit dès la fermeture.
 */
export function PanelZoom({
  data,
  panelId,
  selectedId,
  showGuides,
  busy,
  canvasRef,
  sidebar,
  onPanel,
  onClose,
  onSelect,
  onCommit,
  onCommitSfx,
}: {
  data: PageLettering;
  panelId: number | null;
  selectedId: number | null;
  showGuides: boolean;
  busy: boolean;
  canvasRef: Ref<LetteringCanvasHandle>;
  /** Éditeurs de la bulle ou de l'onomatopée choisie, ajout d'onomatopée : ceux de la planche. */
  sidebar: (panel: PageLettering["panels"][number]) => ReactNode;
  onPanel: (panelId: number) => void;
  onClose: () => void;
  onSelect: (id: number | null) => void;
  onCommit: (edit: CanvasEdit) => void;
  onCommitSfx: (id: number, update: SfxUpdate) => void;
}) {
  const ordered = [...data.panels].sort((a, b) => a.index - b.index);
  const at = ordered.findIndex((p) => p.id === panelId);
  const panel = at >= 0 ? ordered[at] : null;
  const prev = at > 0 ? ordered[at - 1] : null;
  const next = at >= 0 && at < ordered.length - 1 ? ordered[at + 1] : null;
  const [zoom, setZoom] = useState(1);
  const [space, setSpace] = useState<{ width: number; height: number } | null>(null);
  // La modale ne monte son contenu qu'une fois ouverte : on mesure la scène quand elle apparaît.
  const measure = useCallback((el: HTMLDivElement | null) => {
    if (!el) return;
    const read = () =>
      setSpace((s) => (s && s.width === el.clientWidth && s.height === el.clientHeight ? s : { width: el.clientWidth, height: el.clientHeight }));
    read();
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  function go(target: PageLettering["panels"][number] | null) {
    if (!target) return;
    setZoom(1);
    onPanel(target.id);
  }

  const view = panel ? panelView(panel, data) : null;
  // Marge intérieure de la scène : la toile ne colle pas au bord, les poignées restent attrapables.
  const fit = view && space ? fitSize(view, { width: Math.max(1, space.width - 32), height: Math.max(1, space.height - 32) }, zoom) : null;
  const warnings = panel ? panelWarnings(data, panel.id) : [];

  return (
    <Modal open={panel !== null} onClose={onClose} title={panel ? `Case ${panel.index + 1}` : "Case"} size="full">
      {panel && view && (
        <div className="grid h-full gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]" data-testid="panel-zoom">
          <div className="flex min-h-[60vh] min-w-0 flex-col gap-3 lg:min-h-0">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1" role="group" aria-label="Choix de la case">
                <Button variant="secondary" className="!px-2.5" onClick={() => go(prev)} disabled={!prev} aria-label="Case précédente" data-testid="panel-zoom-prev">
                  ←
                </Button>
                <span className="min-w-28 text-center text-sm text-zinc-300" aria-live="polite" data-testid="panel-zoom-position">
                  Case {panel.index + 1} / {ordered.length}
                </span>
                <Button variant="secondary" className="!px-2.5" onClick={() => go(next)} disabled={!next} aria-label="Case suivante" data-testid="panel-zoom-next">
                  →
                </Button>
              </div>
              <p className="text-sm text-zinc-500">Page {data.page_number}</p>
              <div className="ml-auto flex items-center gap-1" role="group" aria-label="Zoom">
                <Button
                  variant="secondary"
                  className="!px-2.5"
                  onClick={() => setZoom((z) => clampZoom(z / ZOOM_STEP))}
                  disabled={zoom <= ZOOM_MIN}
                  aria-label="Dézoomer"
                  data-testid="panel-zoom-out"
                >
                  −
                </Button>
                <span className="w-14 text-center text-sm tabular-nums text-zinc-300" data-testid="panel-zoom-level">
                  {Math.round(zoom * 100)} %
                </span>
                <Button
                  variant="secondary"
                  className="!px-2.5"
                  onClick={() => setZoom((z) => clampZoom(z * ZOOM_STEP))}
                  disabled={zoom >= ZOOM_MAX}
                  aria-label="Zoomer"
                  data-testid="panel-zoom-in"
                >
                  +
                </Button>
                <Button variant="ghost" onClick={() => setZoom(1)} disabled={zoom === 1} data-testid="panel-zoom-fit">
                  Ajuster
                </Button>
              </div>
            </div>
            <div ref={measure} className="flex min-h-0 flex-1 overflow-auto rounded-lg bg-zinc-950 p-4" data-testid="panel-zoom-stage">
              {fit && (
                <div className="m-auto">
                  <LetteringCanvas
                    ref={canvasRef}
                    data={data}
                    selectedId={selectedId}
                    showGuides={showGuides}
                    disabled={busy}
                    onSelect={onSelect}
                    onCommit={onCommit}
                    onCommitSfx={onCommitSfx}
                    focus={{ panelId: panel.id, view, size: fit }}
                  />
                </div>
              )}
            </div>
            <p className="text-center text-xs text-zinc-500">
              Mêmes outils que sur la planche : clique une bulle ou une onomatopée pour l&apos;éditer, glisse-la, ses
              poignées la redimensionnent · flèches pour la déplacer · Échap ferme la case.
            </p>
          </div>
          <div className="min-w-0 space-y-4 lg:overflow-y-auto">
            {sidebar(panel)}
            <LetteringWarnings
              data={data}
              warnings={warnings}
              empty="Aucun pour cette case."
              onSelect={(id) => onSelect(id)}
            />
          </div>
        </div>
      )}
    </Modal>
  );
}
