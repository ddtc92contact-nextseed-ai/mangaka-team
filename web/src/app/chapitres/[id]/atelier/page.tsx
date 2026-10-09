"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { GenerateChapterButton, missingPanels } from "@/components/generate-chapter";
import { modalOpen } from "@/components/modal";
import { queueItems, useQueue } from "@/components/queue";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, Select } from "@/components/ui";
import { api, fullErrorMessage, type Job, type PageData } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { PAGE_KINDS } from "@/lib/script";
import { useChapter } from "../chapter-context";
import { PageCanvas, type PageCanvasHandle, type PanelView } from "./page-canvas";
import { PanelInspector } from "./panel-inspector";

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
  const jobs = useEngineData(() => api.chapterJobs(chapter.id, "generation"), [chapter.id, finished]);
  const presets = useEngineData(() => api.workflowPresets());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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

  // État vivant de chaque case : job en cours / en file (d'après la file), dernier échec (d'après les jobs).
  const views = useMemo(() => {
    const items = queueItems(queue);
    const latest = new Map<number, Job>();
    for (const j of jobs.data ?? []) {
      if (j.panel_id != null && !latest.has(j.panel_id)) latest.set(j.panel_id, j);
    }
    const map = new Map<number, PanelView>();
    for (const p of list) {
      for (const panel of p.panels) {
        const mine = items.filter((i) => i.panel_id === panel.id);
        const last = latest.get(panel.id);
        map.set(panel.id, {
          panel,
          running: mine.find((i) => i.job.status === "running") ?? null,
          pending: mine.filter((i) => i.job.status === "pending"),
          failure: last?.status === "failed" ? last : null,
        });
      }
    }
    return map;
  }, [list, queue, jobs.data]);

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
  const prev = list[index - 1];
  const next = list[index + 1];
  const missing = missingPanels([page]).length;
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
            {list.map((p) => {
              const ready = p.panels.filter((pa) => pa.selected_image_id !== null).length;
              return (
                <option key={p.id} value={p.id}>
                  Page {p.number}
                  {p.kind !== "story" ? ` (${PAGE_KINDS[p.kind].toLowerCase()})` : ""} — {ready}/{p.panels.length} case
                  {p.panels.length > 1 ? "s" : ""}
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
        <div className="ml-auto flex flex-wrap gap-2">
          {page.layout && page.panels.length > 0 && (
            <ButtonLink variant="ghost" href={`/chapitres/${chapter.id}/lettrage?page=${page.id}`} data-testid="open-lettering">
              Lettrage de la page
            </ButtonLink>
          )}
          {page.layout && page.panels.length > 0 && (
            <Button onClick={() => generateMissing(page)} disabled={busy || missing === 0} data-testid="generate-page">
              Générer les cases manquantes{missing ? ` (${missing})` : ""}
            </Button>
          )}
          <GenerateChapterButton
            chapterId={chapter.id}
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
      {notice && !error && <Alert tone="info">{notice}</Alert>}
      {jobs.error && <Alert>Historique des générations indisponible : {jobs.error}</Alert>}

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
              La géométrie des cases vient de la mise en page : calcule-la avant de générer.
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
              <PageCanvas ref={canvasRef} page={page} views={views} selectedPanelId={openPanelId} onOpen={open} />
              <p className="mt-3 text-center text-xs text-zinc-500">
                Clique sur une case (ou flèches puis Entrée) pour la générer et choisir sa version · Échap ferme le panneau.
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
              refreshKey={finished}
              onClose={close}
              onChanged={() => {
                pages.reload();
                jobs.reload();
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
