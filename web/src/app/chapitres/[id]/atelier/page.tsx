"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { GenerateChapterButton, missingPanels } from "@/components/generate-chapter";
import { InfoTip } from "@/components/info-tip";
import { hasLettering, LetteredPreview } from "@/components/lettered-preview";
import { modalOpen } from "@/components/modal";
import { ProductionLink } from "@/components/production-link";
import { queueItems, useQueue } from "@/components/queue";
import { useToast } from "@/components/toast";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, Select } from "@/components/ui";
import { api, fullErrorMessage, type PageData } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { needsReview } from "@/lib/qc";
import { PAGE_KINDS } from "@/lib/script";
import { useChapter } from "../chapter-context";
import { buildPanelViews, PageCanvas, type PageCanvasHandle } from "./page-canvas";
import { PanelInspector } from "./panel-inspector";
import { QCToolbar } from "./qc-toolbar";

export default function WorkshopRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <Workshop />
    </Suspense>
  );
}

function Workshop() {
  const { chapter, reload: reloadChapter } = useChapter();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { queue, finished, refresh } = useQueue();

  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id, finished]);
  const finishJobs = useEngineData(() => api.chapterJobs(chapter.id, "finishing"), [chapter.id, finished]);
  const presets = useEngineData(() => api.workflowPresets());
  const qcStatus = useEngineData(() => api.qcStatus());
  const [onlyReview, setOnlyReview] = useState(false);
  const [showBoxes, setShowBoxes] = useState(false);
  const [showLettering, setShowLettering] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const toast = useToast();
  const canvasRef = useRef<PageCanvasHandle>(null);
  const inspectorRef = useRef<HTMLDivElement>(null);

  const list = useMemo(() => pages.data ?? [], [pages.data]);
  const panelParam = Number(params.get("case")) || null;
  const pageParam = Number(params.get("page")) || null;
  const page =
    list.find((p) => p.id === pageParam) ??
    (panelParam ? list.find((p) => p.panels.some((pa) => pa.id === panelParam)) : undefined) ??
    list.find((p) => p.layout) ??
    list[0] ??
    null;
  const openPanelId = page && panelParam && page.panels.some((p) => p.id === panelParam) ? panelParam : null;

  function navigate(pageId: number | null, panelId: number | null) {
    const q = new URLSearchParams();
    if (pageId) q.set("page", String(pageId));
    if (panelId) q.set("case", String(panelId));
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  }

  const views = useMemo(
    () => buildPanelViews(list, queueItems(queue), finishJobs.data ?? []),
    [list, queue, finishJobs.data],
  );

  // Échap ferme le panneau latéral (sauf si une fenêtre modale est ouverte) et rend le focus à la case.
  useEffect(() => {
    if (!openPanelId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || modalOpen()) return;
      close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function open(panelId: number) {
    navigate(page?.id ?? null, panelId);
    // Sur petit écran, le panneau est sous la page : on l'amène à l'écran.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      requestAnimationFrame(() => inspectorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  }
  function close() {
    const id = openPanelId;
    navigate(page?.id ?? null, null);
    if (id) requestAnimationFrame(() => canvasRef.current?.focusPanel(id));
  }

  async function generateMissing(p: PageData) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.generatePage(p.id);
      refresh();
      pages.reload();
      reloadChapter();
      const n = res.panel_ids.length;
      toast(n ? `Génération lancée (${n} en file)` : "Rien à générer sur cette page", n ? "success" : "info");
      setNotice(
        n
          ? `${n} case${n > 1 ? "s" : ""} mise${n > 1 ? "s" : ""} en file${res.skipped ? ` (${res.skipped} déjà prête${res.skipped > 1 ? "s" : ""} ou en file)` : ""}.`
          : "Rien à générer sur cette page.",
      );
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function finishPage(p: PageData) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.finishPage(p.id);
      refresh();
      pages.reload();
      finishJobs.reload();
      const n = res.panel_ids.length;
      toast(n ? `Finition lancée (${n} en file)` : "Rien à finaliser sur cette page", n ? "success" : "info");
      setNotice(
        n
          ? `Finition d'impression de ${n} case${n > 1 ? "s" : ""} mise en file (agrandissement jusqu'au dpi du format).`
          : "Toutes les cases retenues de cette page sont déjà au dpi d'impression (ou en file).",
      );
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
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

  const index = list.indexOf(page);
  // Filtre « à revoir » : les flèches sautent aux pages qui ont des cases à revoir.
  const browsable = onlyReview ? list.filter((p) => p === page || p.panels.some(needsReview)) : list;
  const at = browsable.indexOf(page);
  const prev = at >= 0 ? browsable[at - 1] : list[index - 1];
  const next = at >= 0 ? browsable[at + 1] : list[index + 1];
  // Annotation rapide : ← / → passent à la case précédente / suivante qui a une version (toutes pages).
  const annotatable = list.flatMap((p) => p.panels.filter((pa) => pa.image_count > 0).map((pa) => ({ pageId: p.id, panelId: pa.id })));
  const at2 = annotatable.findIndex((x) => x.panelId === openPanelId);
  const prevPanel = at2 > 0 ? annotatable[at2 - 1] : null;
  const nextPanel = at2 >= 0 && at2 < annotatable.length - 1 ? annotatable[at2 + 1] : null;
  const missing = missingPanels([page]).length;
  const finishingNow = page.panels.filter((p) => views.get(p.id)?.finishing).length;
  const toFinish = page.panels.filter((p) => p.print_info?.status === "low" && !views.get(p.id)?.finishing).length;
  const done = page.panels.filter((p) => p.selected_image_id !== null).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1" role="group" aria-label="Choix de la page">
          <Button variant="secondary" className="!px-2.5" onClick={() => prev && navigate(prev.id, null)} disabled={!prev} aria-label="Page précédente">
            ←
          </Button>
          <label htmlFor="page-select" className="sr-only">
            Page
          </label>
          <Select
            id="page-select"
            className="!w-auto py-1.5"
            value={page.id}
            onChange={(e) => navigate(Number(e.target.value), null)}
          >
            {browsable.map((p) => {
              const ready = p.panels.filter((pa) => pa.selected_image_id !== null).length;
              const toReview = p.panels.filter(needsReview).length;
              return (
                <option key={p.id} value={p.id}>
                  Page {p.number}
                  {p.kind !== "story" ? ` (${PAGE_KINDS[p.kind].toLowerCase()})` : ""} — {ready}/{p.panels.length} case
                  {p.panels.length > 1 ? "s" : ""}
                  {toReview ? ` · ${toReview} à revoir` : ""}
                  {!p.layout && p.panels.length ? " · sans mise en page" : ""}
                </option>
              );
            })}
          </Select>
          <Button variant="secondary" className="!px-2.5" onClick={() => next && navigate(next.id, null)} disabled={!next} aria-label="Page suivante">
            →
          </Button>
        </div>
        <p className="text-sm text-zinc-400">
          {done}/{page.panels.length} case{page.panels.length > 1 ? "s" : ""} prête{page.panels.length > 1 ? "s" : ""}
        </p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {page.layout && page.panels.length > 0 && (
            <ButtonLink variant="ghost" href={`/chapitres/${chapter.id}/lettrage?page=${page.id}`} data-testid="open-lettering">
              Lettrage de la page
            </ButtonLink>
          )}
          {page.layout && page.panels.length > 0 && <InfoTip help="atelier.generate_missing" label="Générer cette page" />}
          {page.layout && page.panels.length > 0 && (
            <Button
              variant="secondary"
              onClick={() => generateMissing(page)}
              disabled={busy || missing === 0}
              data-testid="generate-page"
            >
              Générer cette page{missing ? ` (${missing})` : ""}
            </Button>
          )}
          {page.layout && page.panels.length > 0 && (
            <Button
              variant="secondary"
              onClick={() => finishPage(page)}
              disabled={busy || toFinish === 0}
              data-testid="finish-page"
            >
              {finishingNow
                ? `Finition en cours (${finishingNow})`
                : `Finaliser la page${toFinish ? ` (${toFinish})` : ""}`}
            </Button>
          )}
          {page.layout && page.panels.length > 0 && <InfoTip help="atelier.finish" label="Finaliser la page" />}
          <GenerateChapterButton
            chapterId={chapter.id}
            variant="primary"
            onQueued={(m) => {
              setError(null);
              setNotice(m);
              pages.reload();
              reloadChapter();
            }}
          />
        </div>
      </div>

      {error && <Alert>{error}</Alert>}
      {notice && !error && (
        <Alert tone="info">
          {notice} <ProductionLink chapterId={chapter.id} pageId={page.id} />
        </Alert>
      )}
      {finishJobs.error && <Alert>Historique des finitions indisponible : {finishJobs.error}</Alert>}

      <QCToolbar
        chapterId={chapter.id}
        pages={list}
        status={qcStatus.data}
        onlyReview={onlyReview}
        onOnlyReview={setOnlyReview}
        showBoxes={showBoxes}
        onShowBoxes={setShowBoxes}
        onOpenPanel={(pageId, panelId) => navigate(pageId, panelId)}
        onChanged={() => pages.reload()}
      />

      <div className={`grid gap-6 ${openPanelId ? "lg:grid-cols-[minmax(0,1fr)_24rem]" : ""}`}>
        <div className="min-w-0">
          {!page.panels.length ? (
            <EmptyState title="Page sans case">
              Ajoute des cases à cette page dans l&apos;onglet Scénario.
              <div className="mt-4">
                <ButtonLink variant="secondary" href={`/chapitres/${chapter.id}/scenario`}>
                  Aller au Scénario
                </ButtonLink>
              </div>
            </EmptyState>
          ) : !page.layout ? (
            <EmptyState title="Page pas encore mise en page">
              La géométrie des cases vient de la mise en page : « Générer le chapitre » la calcule automatiquement, ou
              ajuste-la d&apos;abord à la main.
              <div className="mt-4">
                <ButtonLink href={`/chapitres/${chapter.id}/mise-en-page`}>Aller à la Mise en page</ButtonLink>
              </div>
            </EmptyState>
          ) : (
            <Card className="p-3 sm:p-5">
              {page.layout_stale && (
                <div className="mb-3">
                  <Alert tone="info">Mise en page obsolète : recalcule-la dans « Mise en page » pour des tailles justes.</Alert>
                </div>
              )}
              {hasLettering(page) && (
                <label className="mb-3 flex w-fit items-center gap-2 text-sm text-zinc-300">
                  <input
                    type="checkbox"
                    checked={showLettering}
                    onChange={(e) => setShowLettering(e.target.checked)}
                    className="accent-rose-500"
                    data-testid="toggle-lettering"
                  />
                  Afficher les bulles et onomatopées
                </label>
              )}
              {showLettering && hasLettering(page) ? (
                <LetteredPreview page={page} refreshKey={finished} />
              ) : (
                <PageCanvas
                  ref={canvasRef}
                  page={page}
                  views={views}
                  selectedPanelId={openPanelId}
                  onOpen={open}
                  showBoxes={showBoxes}
                  onlyReview={onlyReview}
                />
              )}
              <p className="mt-3 text-center text-xs text-zinc-500">
                {showLettering && hasLettering(page)
                  ? "Aperçu lettré en lecture seule : décoche la case pour revenir aux cases cliquables."
                  : "Clique sur une case (ou flèches puis Entrée) pour la générer et choisir sa version · Échap ferme le panneau."}
              </p>
            </Card>
          )}
        </div>
        {openPanelId && (
          <div ref={inspectorRef} className="min-w-0 scroll-mt-16 lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)] lg:self-start lg:overflow-y-auto">
            <PanelInspector
              key={openPanelId}
              panelId={openPanelId}
              view={views.get(openPanelId) ?? null}
              presets={presets.data}
              qcStatus={qcStatus.data}
              refreshKey={finished}
              onClose={close}
              onChanged={() => {
                pages.reload();
                finishJobs.reload();
              }}
              onPrev={prevPanel ? () => navigate(prevPanel.pageId, prevPanel.panelId) : undefined}
              onNext={nextPanel ? () => navigate(nextPanel.pageId, nextPanel.panelId) : undefined}
            />
          </div>
        )}
      </div>
    </div>
  );
}
