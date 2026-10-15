"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { InfoTip } from "@/components/info-tip";
import { modalOpen } from "@/components/modal";
import { ProductionLink } from "@/components/production-link";
import { queueItems, useQueue } from "@/components/queue";
import { useToast } from "@/components/toast";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, ProgressBar, Select, Textarea } from "@/components/ui";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type BatchGenerateResult,
  type Estimate,
  type PageData,
  type PanelData,
} from "@/lib/api";
import { formatEstimate } from "@/lib/generation";
import { useEngineData } from "@/lib/hooks";
import { nameCounts } from "@/lib/name";
import { buildPanelViews, type PanelView } from "../atelier/page-canvas";
import { useChapter } from "../chapter-context";
import { readAuthor, StageBanner } from "../stages";
import { StepAlert } from "../step-alert";
import { DraftBoard, NameBar } from "./draft-board";
import { NameReader } from "./name-reader";
import { PanelFixes, type SplitRequest } from "./panel-fixes";
import { isValidated, panelStatus, plural, STATUS_LABEL } from "./status";

export default function SketchRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <SketchTriage />
    </Suspense>
  );
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
  const { chapter, series, reload: reloadChapter, reloadStages } = useChapter();
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
  const [bubbles, setBubbles] = useState(true);
  const toast = useToast();
  const reading = params.get("vue") === "lecture";
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

  function navigate(pageId: number | null, panelId: number | null, read = reading) {
    const q = new URLSearchParams();
    if (pageId) q.set("page", String(pageId));
    if (panelId) q.set("case", String(panelId));
    if (read) q.set("vue", "lecture");
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
      if (msg) {
        setNotice(msg);
        toast(msg.text);
      }
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

  // --- name : validation par page et corrections rapides ---
  const validateName = (p: PageData) =>
    run(async () => {
      await api.validateName(p.id, readAuthor());
      reloadStages();
      return { text: `Name de la page ${p.number} validée : ses croquis retenus serviront au propre.`, queued: false };
    });
  const unvalidateName = (p: PageData) =>
    run(async () => {
      await api.unvalidateName(p.id);
      reloadStages();
      return { text: `Validation de la name de la page ${p.number} retirée.`, queued: false };
    });
  const changeShot = (panel: PanelData, shot: string | null) =>
    run(async () => {
      await api.updatePanel(panel.id, { shot_type: shot });
      await api.sketchPanel(panel.id);
      refresh();
      reloadStages();
      return { text: `Case ${panel.index + 1} : ${shot ?? "aucun plan"}, nouveau croquis en file.`, queued: true };
    });
  const rewriteReply = (panel: PanelData, bubbleId: number, text: string) =>
    run(async () => {
      await api.updateBubble(bubbleId, { text });
      return { text: `Réplique de la case ${panel.index + 1} réécrite.`, queued: false };
    });
  const deleteReply = (panel: PanelData, bubbleId: number) =>
    run(async () => {
      await api.deleteReply(bubbleId);
      return { text: `Réplique supprimée de la case ${panel.index + 1}.`, queued: false };
    });
  const deleteSfx = (panel: PanelData, bubbleId: number) =>
    run(async () => {
      await api.deleteSfx(bubbleId);
      return { text: `Onomatopée supprimée de la case ${panel.index + 1}.`, queued: false };
    });
  const splitPanel = (panel: PanelData, req: SplitRequest) =>
    run(async () => {
      const res = await api.splitPanel(panel.id, {
        first: req.first.trim(),
        second: req.second.trim(),
        move_bubble_ids: req.moveBubbleIds,
      });
      refresh();
      reloadStages();
      navigate(res.page.id, res.panel_ids[1] ?? panel.id);
      const sketched = res.jobs.length ? ` ${plural(res.jobs.length, "croquis")} en file.` : "";
      return {
        text: `Case ${panel.index + 1} coupée en deux, page ${res.page.number} remise en page.${sketched}${res.sketch_note ? ` ${res.sketch_note}.` : ""}`,
        queued: res.jobs.length > 0,
      };
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
      if (!current || busy || reading) return;
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
  const name = nameCounts(list);

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
                {p.name_state === "validated" ? " · name ✓" : p.name_state === "stale" ? " · name à revalider" : ""}
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
        <p className="text-sm text-zinc-300" data-testid="name-counter" aria-live="polite">
          Name :{" "}
          <strong className="font-semibold text-zinc-50">
            {name.validated} / {plural(name.total, "page")}
          </strong>{" "}
          validée{name.validated > 1 ? "s" : ""}
          {name.stale > 0 && <span className="text-amber-300"> · {name.stale} à revalider</span>}
        </p>
        <div className="flex rounded-md border border-zinc-700 p-0.5 text-xs" role="group" aria-label="Vue">
          {[
            { read: false, label: "Tri" },
            { read: true, label: "Lecture" },
          ].map((v) => (
            <button
              key={v.label}
              type="button"
              aria-pressed={reading === v.read}
              onClick={() => navigate(page.id, v.read ? null : (current?.id ?? null), v.read)}
              className={`rounded px-2.5 py-1 ${reading === v.read ? "bg-zinc-700 text-zinc-50" : "text-zinc-400 hover:text-zinc-100"}`}
              data-testid={v.read ? "view-reading" : "view-triage"}
            >
              {v.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <InfoTip help="croquis.croquer" label="Croquer" />
          <Button onClick={() => sketchPage(page)} disabled={busy || !page.layout || !est?.to_sketch} data-testid="sketch-page">
            Croquer la page{est?.to_sketch ? ` (${est.to_sketch})` : ""}
          </Button>
          <Button variant="secondary" onClick={sketchChapter} disabled={busy || !cEst?.to_sketch} data-testid="sketch-chapter">
            Croquer le chapitre{cEst?.to_sketch ? ` (${cEst.to_sketch})` : ""}
          </Button>
          <InfoTip help="croquis.propre" label="Passer au propre" />
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

      <StageBanner action="clean" />
      {error && <StepAlert message={error} />}
      {notice && !error && (
        <Alert tone="info">
          {notice.text} {notice.queued && <ProductionLink chapterId={chapter.id} pageId={page.id} />}
        </Alert>
      )}

      {reading ? (
        <Card className="p-3 sm:p-5">
          <NameReader
            key={chapter.id}
            pages={sortable}
            direction={series.reading_direction}
            pageId={page.id}
            refreshKey={`${finished}-${version}`}
            busy={busy}
            onValidate={validateName}
            onUnvalidate={unvalidateName}
            onOpen={(p) => navigate(p.id, null, false)}
          />
        </Card>
      ) : !page.panels.length ? (
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
          <Card className="space-y-3 p-3 sm:p-5">
            <DraftBoard
              page={page}
              views={views}
              currentId={current?.id ?? null}
              onPick={(id) => navigate(page.id, id)}
              refreshKey={`${finished}-${version}`}
              bubbles={bubbles}
            />
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-500">
              <p>Chaque croquis apparaît dès qu&apos;il est prêt · clique sur une case pour la trier.</p>
              <label className="flex items-center gap-1.5 text-zinc-300">
                <input type="checkbox" checked={bubbles} onChange={(e) => setBubbles(e.target.checked)} data-testid="toggle-bubbles" />
                Bulles et onomatopées
              </label>
            </div>
            <NameBar page={page} busy={busy} onValidate={() => validateName(page)} onUnvalidate={() => unvalidateName(page)} />
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
              fixes={
                <PanelFixes
                  panel={current}
                  busy={busy}
                  locked={["running", "queued", "clean"].includes(panelStatus(current, views.get(current.id)))}
                  onShot={(shot) => changeShot(current, shot)}
                  onReplyText={(id, text) => rewriteReply(current, id, text)}
                  onReplyDelete={(id) => deleteReply(current, id)}
                  onSfxDelete={(id) => deleteSfx(current, id)}
                  onSplit={(req) => splitPanel(current, req)}
                />
              }
            />
          )}
        </div>
      )}
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
  fixes,
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
  fixes?: ReactNode;
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
      {fixes}
      <div className="flex gap-2">
        <Button variant="ghost" onClick={onPrev} disabled={!hasPrev} aria-label="Case précédente (←)">
          ← Précédente
        </Button>
        <Button variant="ghost" onClick={onNext} disabled={!hasNext} aria-label="Case suivante (→)" data-testid="sketch-next">
          Suivante →
        </Button>
      </div>

      <section aria-label="Raccourcis clavier" className="rounded-md border border-zinc-800 p-2 text-[11px] leading-relaxed text-zinc-400">
        <InfoTip help="croquis.clavier" label="Tri au clavier" className="mr-1.5" />
        <Kbd>V</Kbd> ou <Kbd>Entrée</Kbd> valider et passer à la suivante · <Kbd>R</Kbd> re-croquer (nouvelle graine) ·{" "}
        <Kbd>E</Kbd> modifier la description · <Kbd>U</Kbd> retirer la validation · <Kbd>→</Kbd>/<Kbd>N</Kbd> case suivante ·{" "}
        <Kbd>←</Kbd>/<Kbd>P</Kbd> précédente · <Kbd>C</Kbd> croquer la page
      </section>
    </Card>
  );
}
