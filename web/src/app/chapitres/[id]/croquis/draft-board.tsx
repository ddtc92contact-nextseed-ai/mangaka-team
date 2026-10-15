"use client";

import { ValidatedCheck } from "@/components/validated-check";
import { Button, Loading } from "@/components/ui";
import { api, engineUrl, type LayoutPanel, type PageData, type PageLettering } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { cssClipPath, panelPolygon } from "@/lib/layout";
import { NAME_STATE_LABEL } from "@/lib/name";
import { runningLabel, type PanelView } from "../atelier/page-canvas";
import { LetteringCanvas } from "../lettrage/lettering-canvas";
import { panelStatus, plural, RING, STATUS_LABEL, unsketched, type Status } from "./status";

const noop = () => {};
// Planche brouillon : aussi grande que possible pour lire les bulles.
const BOARD_VH = 78; // < 80vh : hauteur maximale du SVG du lettrage (sinon il se réduit et les cases se décalent)
const pct = (v: number, total: number) => `${(v / total) * 100}%`;

/** Taille de la planche à l'écran : toute la largeur, sans dépasser `vh` de la hauteur de la fenêtre. */
function boardStyle(W: number, H: number, vh: number) {
  return { aspectRatio: `${W} / ${H}`, width: `min(100%, calc(${vh}vh * ${W} / ${H}))` };
}

/** Pastille et progression d'une case sur la planche (tri). */
function PanelBadge({ index, status, view }: { index: number; status: Status; view: PanelView | undefined }) {
  return (
    <>
      <span className="absolute bottom-1 left-1 rounded bg-zinc-950/80 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-100">
        {index + 1}
        <span className="ml-1 font-normal text-zinc-300">· {STATUS_LABEL[status]}</span>
      </span>
      {status === "validated" && <ValidatedCheck />}
      {status === "running" && view?.running && (
        <span className="absolute inset-x-0 bottom-0 bg-zinc-950/80 px-1.5 py-1">
          <span className="block text-[10px] text-zinc-100">{runningLabel(view.running)}</span>
          <span className="mt-0.5 block h-1 overflow-hidden rounded bg-zinc-700">
            <span className="block h-full bg-rose-400 transition-[width] duration-500" style={{ width: `${view.running.job.progress}%` }} />
          </span>
        </span>
      )}
    </>
  );
}

/** Planche lettrée en lecture seule (croquis à défaut de version propre, bulles et onomatopées). */
export function LetteredBoard({ data, vh = 74 }: { data: PageLettering; vh?: number }) {
  return (
    <div inert className="pointer-events-none" style={boardStyle(data.width, data.height, vh)}>
      <LetteringCanvas data={data} selectedId={null} showGuides={false} disabled onSelect={noop} onCommit={noop} onCommitSfx={noop} />
    </div>
  );
}

/**
 * Planche brouillon (la name) : croquis dans leurs cases avec les bulles du chapitre (texte réel, type, position
 * du lettrage) et les onomatopées. Chaque case reste cliquable pour le tri. Sans bulles (ou lettrage
 * indisponible) : la planche en croquis seule.
 */
export function DraftBoard({
  page,
  views,
  currentId,
  onPick,
  refreshKey,
  bubbles,
}: {
  page: PageData;
  views: Map<number, PanelView>;
  currentId: number | null;
  onPick: (panelId: number) => void;
  refreshKey: unknown;
  bubbles: boolean;
}) {
  const lettering = useEngineData(
    () => (bubbles ? api.getLettering(page.id) : Promise.resolve(null)),
    [page.id, refreshKey, bubbles],
  );
  const data = lettering.data && lettering.data.page_id === page.id ? lettering.data : null;
  if (!bubbles || (lettering.error && !data))
    return (
      <>
        {bubbles && lettering.error && (
          <p className="mb-2 text-center text-xs text-amber-300">Bulles indisponibles : {lettering.error}</p>
        )}
        <SketchPage page={page} views={views} currentId={currentId} onPick={onPick} />
      </>
    );
  if (!data) return <Loading />;
  const byId = new Map(page.panels.map((p) => [p.id, p]));
  const W = data.width;
  const H = data.height;
  return (
    <div
      className="relative mx-auto overflow-hidden rounded-sm bg-white shadow-lg shadow-black/40"
      style={boardStyle(W, H, BOARD_VH)}
      role="group"
      aria-label={`Page ${page.number} en brouillon : croquis et bulles`}
      data-testid="sketch-page-canvas"
      data-board="draft"
    >
      <LetteredBoard data={data} vh={BOARD_VH} />
      {data.panels.map((lp) => {
        const panel = byId.get(lp.id);
        if (!panel) return null;
        const view = views.get(panel.id);
        const status = panelStatus(panel, view);
        const isCurrent = panel.id === currentId;
        const box = lp.box;
        return (
          <button
            key={lp.id}
            type="button"
            onClick={() => onPick(panel.id)}
            aria-pressed={isCurrent}
            aria-label={`Case ${panel.index + 1} — ${STATUS_LABEL[status]}`}
            data-testid="sketch-panel"
            data-state={status}
            className={`absolute focus-visible:z-20 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-sky-400 ${
              lp.polygon ? "" : RING[status]
            } ${isCurrent ? "z-10 outline outline-4 outline-offset-2 outline-rose-500" : ""} ${
              status === "running" || status === "queued" ? "bg-white/40" : ""
            }`}
            style={{ left: pct(box.x1, W), top: pct(box.y1, H), width: pct(box.x2 - box.x1, W), height: pct(box.y2 - box.y1, H) }}
          >
            <PanelBadge index={panel.index} status={status} view={view} />
          </button>
        );
      })}
    </div>
  );
}

/** Planche en croquis sans lettrage (mise en page seule). */
export function SketchPage({
  page,
  views,
  currentId,
  onPick,
}: {
  page: PageData;
  views: Map<number, PanelView>;
  currentId: number | null;
  onPick: (panelId: number) => void;
}) {
  const layout = page.layout!;
  const { width: W, height: H } = layout.page;
  const byId = new Map(page.panels.map((p) => [p.id, p]));
  const panelOf = (lp: LayoutPanel) => (lp.panel_id !== null ? byId.get(lp.panel_id) : undefined) ?? page.panels[lp.index];
  return (
    <div
      className="relative mx-auto overflow-hidden rounded-sm bg-zinc-100 shadow-lg shadow-black/40"
      style={boardStyle(W, H, 74)}
      role="group"
      aria-label={`Page ${page.number} en croquis`}
      data-testid="sketch-page-canvas"
      data-board="sketch"
    >
      {[...layout.panels.filter((p) => !p.inset), ...layout.panels.filter((p) => p.inset)].map((lp) => {
        const panel = panelOf(lp);
        if (!panel) return null;
        const view = views.get(panel.id);
        const status = panelStatus(panel, view);
        const url = panel.selected_image_url ?? panel.sketch_image_url ?? null;
        const poly = lp.slanted ? panelPolygon(lp) : null;
        const isCurrent = panel.id === currentId;
        return (
          <button
            key={lp.index}
            type="button"
            onClick={() => onPick(panel.id)}
            aria-pressed={isCurrent}
            aria-label={`Case ${panel.index + 1} — ${STATUS_LABEL[status]}`}
            data-testid="sketch-panel"
            data-state={status}
            className={`absolute overflow-hidden bg-zinc-200 focus-visible:z-20 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-sky-400 ${
              poly ? "" : RING[status]
            } ${isCurrent ? "z-10 outline outline-4 outline-offset-2 outline-rose-500" : ""}`}
            style={{
              left: pct(lp.x1, W),
              top: pct(lp.y1, H),
              width: pct(lp.width, W),
              height: pct(lp.height, H),
              clipPath: poly ? cssClipPath(poly, lp) : undefined,
            }}
          >
            {url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={engineUrl(url)}
                alt=""
                className={`h-full w-full object-cover ${status === "running" || status === "queued" ? "opacity-50" : ""}`}
                draggable={false}
              />
            ) : (
              <span className="flex h-full w-full items-center justify-center text-lg font-bold text-zinc-500">{panel.index + 1}</span>
            )}
            <PanelBadge index={panel.index} status={status} view={view} />
          </button>
        );
      })}
    </div>
  );
}

const DATE = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });

const NAME_TONE = {
  validated: "border-emerald-700/60 bg-emerald-950/30 text-emerald-100",
  stale: "border-amber-700/60 bg-amber-950/30 text-amber-100",
  pending: "border-zinc-700 bg-zinc-900/60 text-zinc-200",
} as const;

/** « Valider la name » d'une page : état, raison d'un refus prévisible, bouton. */
export function NameBar({
  page,
  busy,
  onValidate,
  onUnvalidate,
  compact = false,
}: {
  page: PageData;
  busy: boolean;
  onValidate: () => void;
  onUnvalidate: () => void;
  compact?: boolean;
}) {
  const state = page.name_state;
  if (!state) return null;
  const missing = unsketched(page.panels);
  const hint =
    state === "validated"
      ? page.name_validated_at
        ? `Validée le ${DATE.format(new Date(page.name_validated_at))} : ses croquis retenus servent au passage au propre.`
        : "Ses croquis retenus servent au passage au propre."
      : state === "stale"
        ? "Une case a changé depuis la validation (description, plan, découpe ou croquis) : relis-la et revalide."
        : missing.length
          ? `${plural(missing.length, "case")} pas encore croquée${missing.length > 1 ? "s" : ""} (${missing.map((p) => p.index + 1).join(", ")}).`
          : "Relis la page comme un lecteur, puis valide-la : le propre de cette page attend sa name.";
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm ${NAME_TONE[state]}`}
      data-testid="name-bar"
      data-state={state}
    >
      <div className="min-w-0">
        <p className="font-medium">
          {state === "validated" && <span aria-hidden="true">✓ </span>}
          {NAME_STATE_LABEL[state]}
          {compact ? "" : ` · page ${page.number}`}
        </p>
        {!compact && <p className="text-xs opacity-80">{hint}</p>}
      </div>
      {state === "validated" ? (
        <Button variant="ghost" className="!py-1 text-xs" onClick={onUnvalidate} disabled={busy} data-testid="name-unvalidate">
          Retirer la validation
        </Button>
      ) : (
        <Button
          className="!py-1 text-xs"
          onClick={onValidate}
          disabled={busy || missing.length > 0}
          title={missing.length ? hint : undefined}
          data-testid="name-validate"
        >
          {state === "stale" ? "Revalider la name" : "Valider la name"}
        </Button>
      )}
    </div>
  );
}
