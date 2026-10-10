"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { modalOpen } from "@/components/modal";
import { ProductionLink } from "@/components/production-link";
import { queueItems, useQueue } from "@/components/queue";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, ProgressBar, Select, Textarea } from "@/components/ui";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type BatchGenerateResult,
  type Estimate,
  type LayoutPanel,
  type PageData,
  type PanelData,
} from "@/lib/api";
import { formatEstimate } from "@/lib/generation";
import { useEngineData } from "@/lib/hooks";
import { cssClipPath, panelPolygon } from "@/lib/layout";
import { buildPanelViews, runningLabel, type PanelView } from "../atelier/page-canvas";
import { useChapter } from "../chapter-context";

export default function SketchRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <SketchTriage />
    </Suspense>
  );
}

type Status = "running" | "queued" | "failed" | "clean" | "validated" | "sketch" | "empty";

/** Où en est une case au tri : génération en cours, propre, croquis validé, croquis à trier, rien. */
function panelStatus(panel: PanelData, view: PanelView | undefined): Status {
  if (view?.running) return "running";
  if (view?.pending.length) return "queued";
  if (panel.selected_image_url) return "clean";
  if (panel.sketch_validated) return "validated";
  if (view?.failure) return "failed";
  if (panel.sketch_image_url) return "sketch";
  return "empty";
}

const STATUS_LABEL: Record<Status, string> = {
  running: "Croquis en cours",
  queued: "En file",
  failed: "Échec",
  clean: "Au propre",
  validated: "Composition validée",
  sketch: "À trier",
  empty: "Pas encore croquée",
};

/** Une case est « validée » quand sa composition est retenue (ou qu'elle a déjà une version propre). */
const isValidated = (p: PanelData) => Boolean(p.sketch_validated || p.selected_image_id !== null);

function plural(n: number, word: string): string {
  return `${n} ${word}${n > 1 ? "s" : ""}`;
}

function estimateText(est: Estimate | undefined): string {
  if (!est || est.remaining_panels === 0) return "rien à faire";
  const time = est.total_s === null ? "durée inconnue" : formatEstimate(est.total_s);
  return `${time} (${plural(est.remaining_panels, "case")})`;
}

function batchNotice(res: BatchGenerateResult, what: string, skippedWhy: string): string {
  const n = res.panel_ids.length;
  if (!n) return `Rien à ${what} : ${skippedWhy}.`;
  return `${plural(n, "case")} mise${n > 1 ? "s" : ""} en file${res.skipped ? ` (${res.skipped} ignorée${res.skipped > 1 ? "s" : ""} : ${skippedWhy})` : ""}.`;
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable));
}

function SketchTriage() {
  const { chapter, series, reload: reloadChapter } = useChapter();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { queue, finished, refresh } = useQueue();
  const [version, setVersion] = useState(0);

  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id, finished, version]);
  const chapterEst = useEngineData(() => api.chapterSketchEstimate(chapter.id), [chapter.id, finished, version]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; queued: boolean } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const editRef = useRef<HTMLTextAreaElement>(null);

  const list = useMemo(() => pages.data ?? [], [pages.data]);
  const views = useMemo(() => buildPanelViews(list, queueItems(queue)), [list, queue]);
  const sortable = list.filter((p) => p.layout && p.panels.length);
  const pageParam = Number(params.get("page")) || null;
  const panelParam = Number(params.get("case")) || null;
  const page =
    list.find((p) => p.id === pageParam) ??
    (panelParam ? list.find((p) => p.panels.some((pa) => pa.id === panelParam)) : undefined) ??
    sortable[0] ??
    list[0] ??
    null;
  const pageEst = useEngineData(
    () => (page ? api.pageSketchEstimate(page.id) : Promise.resolve(null)),
    [page?.id, finished, version],
  );
  const current =
    page?.panels.find((p) => p.id === panelParam) ??
    page?.panels.find((p) => !isValidated(p)) ??
    page?.panels[0] ??
    null;

  // Ordre de lecture de tout le chapitre : « case suivante » passe à la page suivante en fin de page.
  const order = sortable.flatMap((pg) => pg.panels.map((pa) => ({ pageId: pg.id, panel: pa })));
  const at = current ? order.findIndex((o) => o.panel.id === current.id) : -1;
  const prev = at > 0 ? order[at - 1] : null;
  const next = at >= 0 && at < order.length - 1 ? order[at + 1] : null;

  function navigate(pageId: number | null, panelId: number | null) {
    const q = new URLSearchParams();
    if (pageId) q.set("page", String(pageId));
    if (panelId) q.set("case", String(panelId));
    setEditing(null);
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  }
  const goNext = () => next && navigate(next.pageId, next.panel.id);
  const goPrev = () => prev && navigate(prev.pageId, prev.panel.id);

  async function run(action: () => Promise<{ text: string; queued: boolean } | void>) {
    setBusy(true);
    setError(null);
    try {
      const msg = await action();
      if (msg) setNotice(msg);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  /** Mise à jour immédiate d'une case dans la liste (tri au clavier sans attendre le rechargement). */
  function patchPanel(id: number, patch: Partial<PanelData>) {
    pages.setData((cur) =>
      cur ? cur.map((pg) => ({ ...pg, panels: pg.panels.map((pa) => (pa.id === id ? { ...pa, ...patch } : pa)) })) : cur,
    );
  }

  const validate = (panel: PanelData) =>
    run(async () => {
      if (!panel.sketch_image_id) throw new Error("Pas encore de croquis pour cette case : croque-la d'abord (R).");
      await api.validateSketch(panel.id, panel.sketch_image_id);
      patchPanel(panel.id, { sketch_validated: true });
      goNext();
      return { text: `Case ${panel.index + 1} validée.`, queued: false };
    });
  const unvalidate = (panel: PanelData) =>
    run(async () => {
      await api.unvalidateSketch(panel.id);
      patchPanel(panel.id, { sketch_validated: false });
      return { text: `Validation de la case ${panel.index + 1} retirée.`, queued: false };
    });
  const resketch = (panel: PanelData, description?: string) =>
    run(async () => {
      if (description !== undefined && description.trim() !== panel.description.trim()) {
        await api.updatePanel(panel.id, { description: description.trim() });
      }
      await api.sketchPanel(panel.id);
      setEditing(null);
      patchPanel(panel.id, { sketch_validated: false });
      refresh();
      return { text: `Nouveau croquis de la case ${panel.index + 1} en file (nouvelle graine).`, queued: true };
    });
  const sketchPage = (p: PageData) =>
    run(async () => {
      const res = await api.sketchPage(p.id);
      refresh();
      reloadChapter();
      return { text: batchNotice(res, "croquer", "déjà validées, au propre ou en file"), queued: res.panel_ids.length > 0 };
    });
  const sketchChapter = () =>
    run(async () => {
      const res = await api.sketchChapter(chapter.id);
      refresh();
      reloadChapter();
      return { text: batchNotice(res, "croquer", "déjà validées, au propre ou en file"), queued: res.panel_ids.length > 0 };
    });
  const cleanPage = (p: PageData) =>
    run(async () => {
      const res = await api.cleanPage(p.id);
      refresh();
      reloadChapter();
      return { text: batchNotice(res, "passer au propre", "non validées, déjà au propre ou en file"), queued: res.panel_ids.length > 0 };
    });
  const cleanChapter = () =>
    run(async () => {
      const res = await api.cleanChapter(chapter.id);
      refresh();
      reloadChapter();
      return { text: batchNotice(res, "passer au propre", "non validées, déjà au propre ou en file"), queued: res.panel_ids.length > 0 };
    });

  function startEdit(panel: PanelData) {
    setEditing(panel.description);
    requestAnimationFrame(() => editRef.current?.focus());
  }

  // Raccourcis du tri (hors saisie et hors fenêtre modale).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || modalOpen() || isTyping(e.target)) return;
      // Entrée sur un bouton ou un lien : c'est lui qui agit.
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (e.key === "Enter" && (tag === "BUTTON" || tag === "A")) return;
      if (!current || busy) return;
      const key = e.key.toLowerCase();
      const status = panelStatus(current, views.get(current.id));
      if (key === "arrowright" || key === "n") goNext();
      else if (key === "arrowleft" || key === "p") goPrev();
      else if ((key === "v" || key === "enter") && status === "sketch") void validate(current);
      else if (key === "u" && status === "validated") void unvalidate(current);
      else if (key === "r" && status !== "running" && status !== "queued" && status !== "clean") void resketch(current);
      else if (key === "e" && status !== "clean") startEdit(current);
      else if (key === "c" && page) void sketchPage(page);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!series.sketch_enabled) {
    return (
      <EmptyState title="Palier croquis désactivé pour cette série">
        Active-le dans la fiche série (« Croquer les pages avant de les produire ») pour voir chaque page en brouillon en
        quelques secondes et ne passer au propre que les compositions retenues.
        <div className="mt-4">
          <ButtonLink href={`/projets/${series.id}`}>Ouvrir la fiche série</ButtonLink>
        </div>
      </EmptyState>
    );
  }
  if (pages.loading && !pages.data) return <Loading />;
  if (pages.error && !pages.data) return <Alert>Impossible de charger les pages : {pages.error}</Alert>;
  if (!list.length || !page)
    return (
      <EmptyState title="Aucune page dans ce chapitre">
        Découpe d&apos;abord le chapitre dans l&apos;onglet Scénario.
        <div className="mt-4">
          <ButtonLink href={`/chapitres/${chapter.id}/scenario`}>Aller au Scénario</ButtonLink>
        </div>
      </EmptyState>
    );

  const validated = page.panels.filter(isValidated).length;
  const cleanCount = page.panels.filter((p) => p.selected_image_id !== null).length;
  const chapterPanels = sortable.flatMap((p) => p.panels);
  const chapterValidated = chapterPanels.filter(isValidated).length;
  const est = pageEst.data;
  const cEst = chapterEst.data;

  return (
    <div className="space-y-4" data-testid="sketch-triage">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1" role="group" aria-label="Choix de la page">
          <label htmlFor="sketch-page" className="sr-only">
            Page
          </label>
          <Select id="sketch-page" className="!w-auto py-1.5" value={page.id} onChange={(e) => navigate(Number(e.target.value), null)}>
            {list.map((p) => (
              <option key={p.id} value={p.id}>
                Page {p.number} — {p.panels.filter(isValidated).length}/{plural(p.panels.length, "case")} validée
                {p.panels.length > 1 ? "s" : ""}
                {!p.layout && p.panels.length ? " · sans mise en page" : ""}
              </option>
            ))}
          </Select>
        </div>
        <p className="text-sm text-zinc-300" data-testid="sketch-counter" aria-live="polite">
          <strong className="font-semibold text-zinc-50">
            {validated} / {page.panels.length}
          </strong>{" "}
          case{page.panels.length > 1 ? "s validées" : " validée"}
          {cleanCount > 0 && <span className="text-zinc-500"> (dont {cleanCount} au propre)</span>}
          <span className="ml-2 text-zinc-500">· chapitre {chapterValidated}/{chapterPanels.length}</span>
        </p>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button onClick={() => sketchPage(page)} disabled={busy || !page.layout || !est?.to_sketch} data-testid="sketch-page">
            Croquer la page{est?.to_sketch ? ` (${est.to_sketch})` : ""}
          </Button>
          <Button variant="secondary" onClick={sketchChapter} disabled={busy || !cEst?.to_sketch} data-testid="sketch-chapter">
            Croquer le chapitre{cEst?.to_sketch ? ` (${cEst.to_sketch})` : ""}
          </Button>
          <Button onClick={() => cleanPage(page)} disabled={busy || !est?.to_clean} data-testid="clean-page">
            Passer au propre les cases validées{est?.to_clean ? ` (${est.to_clean})` : ""}
          </Button>
          <Button variant="secondary" onClick={cleanChapter} disabled={busy || !cEst?.to_clean} data-testid="clean-chapter">
            … tout le chapitre{cEst?.to_clean ? ` (${cEst.to_clean})` : ""}
          </Button>
        </div>
      </div>

      <p className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-400" data-testid="sketch-estimates">
        {pageEst.error ? (
          <span className="text-red-300">Temps estimés indisponibles : {pageEst.error}</span>
        ) : !est ? (
          <span>Calcul des temps estimés…</span>
        ) : (
          <>
            <span>
              Croquis de la page : <strong className="font-medium text-zinc-200">{estimateText(est.sketch)}</strong>
            </span>
            <span>
              Passage au propre des cases validées :{" "}
              <strong className="font-medium text-zinc-200">{estimateText(est.clean)}</strong>
            </span>
            {(!est.sketch.measured || !est.clean.measured) && (est.sketch.remaining_panels > 0 || est.clean.remaining_panels > 0) && (
              <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium text-zinc-400">estimation des presets</span>
            )}
          </>
        )}
      </p>

      {error && <Alert>{error}</Alert>}
      {notice && !error && (
        <Alert tone="info">
          {notice.text} {notice.queued && <ProductionLink chapterId={chapter.id} pageId={page.id} />}
        </Alert>
      )}

      {!page.panels.length ? (
        <EmptyState title="Page sans case">Cette page n&apos;a rien à croquer.</EmptyState>
      ) : !page.layout ? (
        <EmptyState title="Page pas encore mise en page">
          Un croquis a le ratio de sa case : calcule la mise en page d&apos;abord.
          <div className="mt-4">
            <ButtonLink href={`/chapitres/${chapter.id}/mise-en-page`}>Aller à la Mise en page</ButtonLink>
          </div>
        </EmptyState>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_26rem]">
          <Card className="p-3 sm:p-5">
            <SketchPage page={page} views={views} currentId={current?.id ?? null} onPick={(id) => navigate(page.id, id)} />
            <p className="mt-3 text-center text-xs text-zinc-500">
              Chaque croquis apparaît dès qu&apos;il est prêt · clique sur une case pour la trier.
            </p>
          </Card>
          {current && (
            <CurrentPanel
              key={current.id}
              panel={current}
              view={views.get(current.id)}
              busy={busy}
              editing={editing}
              editRef={editRef}
              hasNext={Boolean(next)}
              hasPrev={Boolean(prev)}
              onValidate={() => validate(current)}
              onUnvalidate={() => unvalidate(current)}
              onResketch={() => resketch(current)}
              onEdit={() => startEdit(current)}
              onEditChange={setEditing}
              onEditSave={() => editing !== null && resketch(current, editing)}
              onEditCancel={() => setEditing(null)}
              onNext={goNext}
              onPrev={goPrev}
              workshopHref={`/chapitres/${chapter.id}/atelier?page=${page.id}&case=${current.id}`}
            />
          )}
        </div>
      )}
    </div>
  );
}

// --- planche en croquis ---------------------------------------------------------------------
const RING: Record<Status, string> = {
  running: "ring-2 ring-rose-400",
  queued: "ring-2 ring-zinc-500",
  failed: "ring-2 ring-red-500",
  clean: "ring-2 ring-sky-500",
  validated: "ring-4 ring-emerald-500",
  sketch: "ring-2 ring-zinc-900",
  empty: "ring-2 ring-zinc-900",
};

function SketchPage({
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
  const pct = (v: number, total: number) => `${(v / total) * 100}%`;
  return (
    <div
      className="relative mx-auto overflow-hidden rounded-sm bg-zinc-100 shadow-lg shadow-black/40"
      style={{ aspectRatio: `${W} / ${H}`, width: `min(100%, calc(74vh * ${W} / ${H}))` }}
      role="group"
      aria-label={`Page ${page.number} en croquis`}
      data-testid="sketch-page-canvas"
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
            <span className="absolute left-1 top-1 rounded bg-zinc-950/80 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-100">
              {panel.index + 1}
              <span className="ml-1 font-normal text-zinc-300">· {STATUS_LABEL[status]}</span>
            </span>
            {status === "validated" && (
              <span aria-hidden className="absolute right-1 top-1 rounded-full bg-emerald-500 px-1.5 text-xs font-bold text-white">
                ✓
              </span>
            )}
            {status === "running" && view?.running && (
              <span className="absolute inset-x-0 bottom-0 bg-zinc-950/80 px-1.5 py-1">
                <span className="block text-[10px] text-zinc-100">{runningLabel(view.running)}</span>
                <span className="mt-0.5 block h-1 overflow-hidden rounded bg-zinc-700">
                  <span className="block h-full bg-rose-400 transition-[width] duration-500" style={{ width: `${view.running.job.progress}%` }} />
                </span>
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// --- case en cours de tri -------------------------------------------------------------------
function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-zinc-600 bg-zinc-800 px-1 py-px font-mono text-[10px] text-zinc-200">{children}</kbd>
  );
}

function CurrentPanel({
  panel,
  view,
  busy,
  editing,
  editRef,
  hasNext,
  hasPrev,
  onValidate,
  onUnvalidate,
  onResketch,
  onEdit,
  onEditChange,
  onEditSave,
  onEditCancel,
  onNext,
  onPrev,
  workshopHref,
}: {
  panel: PanelData;
  view: PanelView | undefined;
  busy: boolean;
  editing: string | null;
  editRef: RefObject<HTMLTextAreaElement | null>;
  hasNext: boolean;
  hasPrev: boolean;
  onValidate: () => void;
  onUnvalidate: () => void;
  onResketch: () => void;
  onEdit: () => void;
  onEditChange: (text: string) => void;
  onEditSave: () => void;
  onEditCancel: () => void;
  onNext: () => void;
  onPrev: () => void;
  workshopHref: string;
}) {
  const status = panelStatus(panel, view);
  const active = status === "running" || status === "queued";
  return (
    <Card className="space-y-4 p-4" data-testid="sketch-current">
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="font-semibold text-zinc-50">
          Case {panel.index + 1}
          <span className="ml-2 text-sm font-normal text-zinc-400" data-testid="sketch-status">
            {STATUS_LABEL[status]}
          </span>
        </h2>
        <Link href={workshopHref} className="text-xs text-zinc-400 hover:text-zinc-100">
          Ouvrir dans l&apos;atelier →
        </Link>
      </header>

      <div className={`grid gap-2 ${panel.selected_image_url && panel.sketch_image_url ? "grid-cols-2" : ""}`}>
        {panel.sketch_image_url ? (
          <figure>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={engineUrl(panel.sketch_image_url)}
              alt={`Croquis de la case ${panel.index + 1}`}
              className={`max-h-[46vh] w-full rounded-md bg-zinc-950 object-contain ${active ? "opacity-50" : ""}`}
              data-testid="sketch-large"
            />
            <figcaption className="mt-1 text-[11px] text-zinc-500">
              Croquis{panel.sketch_count && panel.sketch_count > 1 ? ` (${panel.sketch_count} essais)` : ""}
              {panel.sketch_validated ? " · validé" : ""}
            </figcaption>
          </figure>
        ) : (
          <div className="flex aspect-[3/4] items-center justify-center rounded-md bg-zinc-950 p-4 text-center text-sm text-zinc-500">
            {active ? "Croquis en préparation…" : "Pas encore de croquis : R pour croquer cette case, C pour toute la page."}
          </div>
        )}
        {panel.selected_image_url && (
          <figure>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={engineUrl(panel.selected_image_url)}
              alt={`Version propre de la case ${panel.index + 1}`}
              className="max-h-[46vh] w-full rounded-md bg-zinc-950 object-contain"
            />
            <figcaption className="mt-1 text-[11px] text-zinc-500">Version propre (choisie)</figcaption>
          </figure>
        )}
      </div>

      {status === "running" && view?.running && (
        <ProgressBar value={view.running.job.progress} label={`Croquis de la case ${panel.index + 1}`} />
      )}
      {status === "failed" && view?.failure && <Alert>Dernière génération en échec : {view.failure.error ?? "erreur inconnue"}</Alert>}

      {editing !== null ? (
        <div className="space-y-2">
          <label htmlFor="sketch-description" className="text-sm font-medium text-zinc-300">
            Description de la case
          </label>
          <Textarea
            id="sketch-description"
            ref={editRef}
            rows={4}
            value={editing}
            onChange={(e) => onEditChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                onEditSave();
              } else if (e.key === "Escape") {
                e.preventDefault();
                onEditCancel();
              }
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={onEditSave} disabled={busy || !editing.trim()} data-testid="sketch-save-description">
              Enregistrer et re-croquer
            </Button>
            <Button variant="ghost" onClick={onEditCancel} disabled={busy}>
              Annuler
            </Button>
            <span className="text-[11px] text-zinc-500">
              <Kbd>Ctrl</Kbd> + <Kbd>Entrée</Kbd> enregistre · <Kbd>Échap</Kbd> annule
            </span>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-line text-sm text-zinc-300">{panel.description || <span className="text-zinc-500">Pas de description.</span>}</p>
      )}

      <div className="flex flex-wrap gap-2">
        {status === "validated" ? (
          <Button variant="secondary" onClick={onUnvalidate} disabled={busy} data-testid="sketch-unvalidate">
            Retirer la validation <Kbd>U</Kbd>
          </Button>
        ) : (
          <Button onClick={onValidate} disabled={busy || status !== "sketch"} data-testid="sketch-validate">
            Valider <Kbd>V</Kbd>
          </Button>
        )}
        <Button variant="secondary" onClick={onResketch} disabled={busy || active || status === "clean"} data-testid="sketch-again">
          {panel.sketch_image_url ? "Re-croquer" : "Croquer"} <Kbd>R</Kbd>
        </Button>
        <Button variant="secondary" onClick={onEdit} disabled={busy || editing !== null || status === "clean"} data-testid="sketch-edit">
          Modifier la description <Kbd>E</Kbd>
        </Button>
      </div>
      <div className="flex gap-2">
        <Button variant="ghost" onClick={onPrev} disabled={!hasPrev} aria-label="Case précédente (←)">
          ← Précédente
        </Button>
        <Button variant="ghost" onClick={onNext} disabled={!hasNext} aria-label="Case suivante (→)" data-testid="sketch-next">
          Suivante →
        </Button>
      </div>

      <section aria-label="Raccourcis clavier" className="rounded-md border border-zinc-800 p-2 text-[11px] leading-relaxed text-zinc-400">
        <Kbd>V</Kbd> ou <Kbd>Entrée</Kbd> valider et passer à la suivante · <Kbd>R</Kbd> re-croquer (nouvelle graine) ·{" "}
        <Kbd>E</Kbd> modifier la description · <Kbd>U</Kbd> retirer la validation · <Kbd>→</Kbd>/<Kbd>N</Kbd> case suivante ·{" "}
        <Kbd>←</Kbd>/<Kbd>P</Kbd> précédente · <Kbd>C</Kbd> croquer la page
      </section>
    </Card>
  );
}
