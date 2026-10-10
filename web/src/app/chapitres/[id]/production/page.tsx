"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { GenerateChapterButton } from "@/components/generate-chapter";
import { hasLettering, LetteredPreview } from "@/components/lettered-preview";
import { queueItems, useQueue } from "@/components/queue";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, ProgressBar } from "@/components/ui";
import { api, engineUrl, fullErrorMessage, type Job, type LayoutPanel, type PageData, type QueueItem } from "@/lib/api";
import { engineTime, formatDuration, formatEstimate, workshopHref } from "@/lib/generation";
import { useEngineData } from "@/lib/hooks";
import { cssClipPath, panelPolygon } from "@/lib/layout";
import { buildPanelViews, PageCanvas, runningLabel, type PanelView } from "../atelier/page-canvas";
import { useChapter } from "../chapter-context";

export default function ProductionRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <Production />
    </Suspense>
  );
}

const ACTIVE = new Set(["pending", "running"]);
const AGENT_POLL_ACTIVE_MS = 1000;
const AGENT_POLL_IDLE_MS = 4000;

interface AgentJobs {
  script: Job | null;
  direction: Job | null;
}

/** Derniers jobs du scénariste et du directeur artistique, relus chaque seconde tant qu'ils tournent. */
function useAgentJobs(chapterId: number) {
  const [jobs, setJobs] = useState<AgentJobs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(0);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Fins d'agent déjà vues (id, statut, fin) : la première lecture sert de référence.
    let seen: Set<string> | null = null;
    const poll = async () => {
      let active = false;
      try {
        const [script, direction] = await Promise.all([
          api.chapterJobs(chapterId, "script"),
          api.chapterJobs(chapterId, "art_direction"),
        ]);
        if (stopped) return;
        const next = { script: script[0] ?? null, direction: direction[0] ?? null };
        const latest = [next.script, next.direction].filter((j): j is Job => j !== null);
        active = latest.some((j) => ACTIVE.has(j.status));
        // Un agent a fini depuis la dernière lecture (même entre deux lectures espacées, ou lancé depuis
        // un autre onglet) : pages, cases et mise en page ont changé.
        const ends = latest.filter((j) => !ACTIVE.has(j.status)).map((j) => `${j.id}:${j.status}:${j.finished_at ?? ""}`);
        if (seen && ends.some((k) => !seen!.has(k))) setFinished((n) => n + 1);
        seen = new Set([...(seen ?? []), ...ends]);
        setJobs(next);
        setError(null);
      } catch (e) {
        if (!stopped) setError(fullErrorMessage(e));
      }
      if (!stopped) timer = setTimeout(poll, active ? AGENT_POLL_ACTIVE_MS : AGENT_POLL_IDLE_MS);
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [chapterId]);

  return { jobs, error, finished };
}

/** Horloge qui avance chaque seconde (temps écoulé de la génération en cours). */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function Production() {
  const { chapter, reload: reloadChapter } = useChapter();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { queue, finished, error: queueError } = useQueue();
  const agents = useAgentJobs(chapter.id);

  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id, finished, agents.finished]);
  const estimate = useEngineData(() => api.chapterEstimate(chapter.id), [chapter.id, finished, agents.finished]);
  const [notice, setNotice] = useState<string | null>(null);
  // Gardé d'une page à l'autre (l'aperçu suit la case en cours).
  const [lettered, setLettered] = useState(false);

  const list = useMemo(() => pages.data ?? [], [pages.data]);
  const items = useMemo(() => queueItems(queue), [queue]);
  const views = useMemo(() => buildPanelViews(list, items), [list, items]);
  const mine = items.filter((i) => i.chapter_id === chapter.id && i.job.step === "generation");
  const running = queue?.running ?? null;
  const runningHere = running && running.chapter_id === chapter.id ? running : null;

  const pageParam = Number(params.get("page")) || null;
  // Sans choix explicite, l'aperçu suit la page de la case en cours.
  const page =
    list.find((p) => p.id === pageParam) ??
    list.find((p) => p.id === runningHere?.page_id) ??
    list.find((p) => p.layout && p.panels.length) ??
    list[0] ??
    null;

  function choosePage(id: number) {
    router.replace(`${pathname}?page=${id}`, { scroll: false });
  }

  return (
    <div className="space-y-6">
      <AgentsCard jobs={agents.jobs} error={agents.error} pages={list} chapterId={chapter.id} />

      <CurrentJob
        chapterId={chapter.id}
        running={running}
        mine={mine}
        queueError={queueError}
        remaining={estimate.data}
        hasPanels={list.some((p) => p.panels.length > 0)}
        onQueued={(m) => {
          setNotice(m);
          pages.reload();
          reloadChapter();
        }}
      />
      {notice && <Alert tone="info">{notice}</Alert>}

      {pages.loading && !pages.data ? (
        <Loading />
      ) : pages.error && !pages.data ? (
        <Alert>Impossible de charger les pages : {pages.error}</Alert>
      ) : !list.length || !page ? (
        <EmptyState title="Aucune page dans ce chapitre pour l'instant">
          Les planches apparaîtront ici dès que le scénariste aura découpé le chapitre.
          <div className="mt-4">
            <ButtonLink href={`/chapitres/${chapter.id}/scenario`}>Aller au Scénario</ButtonLink>
          </div>
        </EmptyState>
      ) : (
        <>
          <section aria-labelledby="planches-titre" className="space-y-3">
            <h2 id="planches-titre" className="text-sm font-semibold text-zinc-200">
              Planches du chapitre
            </h2>
            <ul className="flex gap-3 overflow-x-auto pb-2" data-testid="production-strip">
              {list.map((p) => (
                <li key={p.id} className="shrink-0">
                  <PageThumb page={p} views={views} active={p.id === page.id} onClick={() => choosePage(p.id)} />
                </li>
              ))}
            </ul>
          </section>
          <PagePreview
            key={page.id}
            page={page}
            views={views}
            chapterId={chapter.id}
            refreshKey={finished}
            lettered={lettered}
            onLettered={setLettered}
            onOpen={(panelId) => router.push(workshopHref(chapter.id, page.id, panelId))}
          />
        </>
      )}
    </div>
  );
}

// --- agents avant les images ----------------------------------------------------------------
const AGENTS = [
  {
    key: "script" as const,
    name: "Scénariste",
    doing: "découpe le chapitre en pages, cases et bulles",
    tab: "scenario",
  },
  {
    key: "direction" as const,
    name: "Directeur artistique",
    doing: "choisit le rythme, l'intensité, le cadrage et l'ambiance de chaque page",
    tab: "direction",
  },
];

function timeAgo(iso: string | null): string {
  const t = engineTime(iso);
  if (t === null) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "à l'instant";
  return `il y a ${formatDuration(s).replace(/ \d+ s$/, "")}`;
}

function AgentRow({
  name,
  doing,
  job,
  href,
}: {
  name: string;
  doing: string;
  job: Job | null;
  href: string;
}) {
  const active = job !== null && ACTIVE.has(job.status);
  return (
    <li className="py-3" data-testid="production-agent" data-state={job?.status ?? "idle"}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm text-zinc-100">
          <span className="font-semibold">{name}</span>
          {active ? (
            <span className="text-zinc-300"> {doing}…</span>
          ) : job?.status === "succeeded" ? (
            <span className="text-emerald-300"> a terminé</span>
          ) : job?.status === "failed" ? (
            <span className="text-red-300"> a échoué</span>
          ) : job?.status === "cancelled" ? (
            <span className="text-zinc-400"> a été annulé</span>
          ) : (
            <span className="text-zinc-500"> n&apos;a pas encore travaillé sur ce chapitre</span>
          )}
        </p>
        <Link href={href} className="text-xs text-zinc-400 hover:text-zinc-100">
          {job?.status === "succeeded" ? "Voir le résultat →" : "Ouvrir l'onglet →"}
        </Link>
      </div>
      {active && job && (
        <div className="mt-2 space-y-1.5">
          <p className="text-xs text-zinc-400">{job.message || "En attente…"}</p>
          <ProgressBar value={job.progress} label={`Progression : ${name}`} />
        </div>
      )}
      {job?.status === "succeeded" && (
        <p className="mt-1 text-xs text-zinc-400">
          {job.message}
          {job.finished_at && <span className="text-zinc-500"> · {timeAgo(job.finished_at)}</span>}
        </p>
      )}
      {job?.status === "failed" && (
        <p role="alert" className="mt-1 text-xs text-red-300">
          {job.error ?? "Erreur inconnue"}
        </p>
      )}
    </li>
  );
}

function AgentsCard({
  jobs,
  error,
  pages,
  chapterId,
}: {
  jobs: AgentJobs | null;
  error: string | null;
  pages: PageData[];
  chapterId: number;
}) {
  const script = jobs?.script ?? null;
  // Le metteur en page tourne à la fin du découpage (puis à la demande, dans l'onglet Mise en page).
  const laying = script !== null && script.status === "running" && script.progress >= 85;
  const withPanels = pages.filter((p) => p.panels.length > 0);
  const laid = withPanels.filter((p) => p.layout).length;
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-zinc-200">Les agents</h2>
      {error && !jobs ? (
        <p role="alert" className="mt-2 text-sm text-red-400">
          Activité des agents indisponible : {error}
        </p>
      ) : !jobs ? (
        <p className="mt-2 text-sm text-zinc-500">Chargement…</p>
      ) : (
        <ul className="divide-y divide-zinc-800">
          {AGENTS.map((a) => (
            <AgentRow key={a.key} name={a.name} doing={a.doing} job={jobs[a.key]} href={`/chapitres/${chapterId}/${a.tab}`} />
          ))}
          <li className="py-3" data-testid="production-agent" data-state={laying ? "running" : laid ? "succeeded" : "idle"}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm text-zinc-100">
                <span className="font-semibold">Metteur en page</span>
                {laying ? (
                  <span className="text-zinc-300"> dessine la géométrie des cases de chaque page…</span>
                ) : withPanels.length === 0 ? (
                  <span className="text-zinc-500"> attend le découpage</span>
                ) : (
                  <span className={laid === withPanels.length ? "text-emerald-300" : "text-amber-300"}>
                    {" "}
                    {laid}/{withPanels.length} page{withPanels.length > 1 ? "s" : ""} mise{laid > 1 ? "s" : ""} en page
                  </span>
                )}
              </p>
              <Link href={`/chapitres/${chapterId}/mise-en-page`} className="text-xs text-zinc-400 hover:text-zinc-100">
                Ouvrir l&apos;onglet →
              </Link>
            </div>
          </li>
        </ul>
      )}
    </Card>
  );
}

// --- génération en cours ----------------------------------------------------------------
function CurrentJob({
  chapterId,
  running,
  mine,
  queueError,
  remaining,
  hasPanels,
  onQueued,
}: {
  chapterId: number;
  running: QueueItem | null;
  mine: QueueItem[];
  queueError: string | null;
  remaining: { remaining_panels: number; total_s: number | null; measured: boolean } | null;
  hasPanels: boolean;
  onQueued: (message: string) => void;
}) {
  const { cancel } = useQueue();
  const here = running && running.chapter_id === chapterId ? running : null;
  const now = useNow(here !== null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = engineTime(here?.job.started_at);
  const elapsed = started !== null ? Math.max(0, (now - started) / 1000) : null;
  const waiting = mine.filter((i) => i.job.status === "pending");
  const lastEta = mine.length ? mine[mine.length - 1].eta_s : null;

  async function onCancel(item: QueueItem) {
    setBusy(true);
    setError(null);
    try {
      await cancel(item.job.id);
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3 p-4" data-testid="production-current">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-200">Génération</h2>
          {queueError && !running ? (
            <p role="alert" className="mt-1 text-sm text-red-400">
              File d&apos;attente indisponible : {queueError}
            </p>
          ) : here ? (
            <p className="mt-1 text-sm text-zinc-100" data-testid="production-running">
              <span className="font-semibold">
                {here.job.step === "qc" ? "Contrôle qualité · " : ""}Case {(here.panel_index ?? 0) + 1} · page {here.page_number}
              </span>
              {here.preset && (
                <span className="text-zinc-400">
                  {" "}
                  · {here.tier ? `${here.tier} (${here.preset})` : here.preset}
                </span>
              )}
              {here.count && here.count > 1 ? <span className="text-zinc-400"> · variante {here.variant}/{here.count}</span> : null}
            </p>
          ) : running ? (
            <p className="mt-1 text-sm text-zinc-400">
              Une autre génération passe d&apos;abord : <span className="text-zinc-200">{running.label}</span>
            </p>
          ) : mine.length === 0 ? (
            <p className="mt-1 text-sm text-zinc-400">Aucune case de ce chapitre en cours ni en file.</p>
          ) : (
            <p className="mt-1 text-sm text-zinc-400">Démarrage de la prochaine case…</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {here && (
            <Button variant="danger" onClick={() => onCancel(here)} disabled={busy} data-testid="production-cancel">
              {busy ? "Annulation…" : "Annuler cette case"}
            </Button>
          )}
          {!here && mine.length === 0 && <GenerateChapterButton chapterId={chapterId} onQueued={onQueued} variant="primary" />}
        </div>
      </div>

      {here && (
        <div className="space-y-1.5">
          <ProgressBar value={here.job.progress} label={`Progression de la case ${(here.panel_index ?? 0) + 1}`} />
          <p className="flex flex-wrap gap-x-3 text-xs text-zinc-400">
            <span>{runningLabel(here)}</span>
            <span>
              Écoulé {formatDuration(elapsed)}
              {here.estimated_duration_s !== null && <> sur ≈ {formatDuration(here.estimated_duration_s)}</>}
            </span>
            {here.job.message && !/étape/i.test(here.job.message) && <span>{here.job.message}</span>}
          </p>
        </div>
      )}

      <p className="flex flex-wrap gap-x-4 gap-y-1 border-t border-zinc-800 pt-3 text-xs text-zinc-400" data-testid="production-remaining">
        <span>
          {waiting.length} case{waiting.length > 1 ? "s" : ""} en attente
          {mine.length > 0 && lastEta !== null && <> · file du chapitre vide dans ≈ {formatDuration(lastEta)}</>}
        </span>
        {remaining && hasPanels && (
          <span>
            {remaining.remaining_panels === 0 ? (
              "Toutes les cases ont une version choisie"
            ) : (
              <>
                Reste à produire : {remaining.remaining_panels} case{remaining.remaining_panels > 1 ? "s" : ""},{" "}
                {remaining.total_s === null ? "durée inconnue" : formatEstimate(remaining.total_s)}
                {!remaining.measured && " (estimation des presets)"}
              </>
            )}
          </span>
        )}
      </p>
      {error && <Alert>{error}</Alert>}
    </Card>
  );
}

// --- planches -------------------------------------------------------------------------------
function thumbState(view: PanelView | undefined): "running" | "queued" | "failed" | "done" | "empty" {
  if (view?.running) return "running";
  if (view?.pending.length) return "queued";
  if (view?.panel.selected_image_url) return "done";
  if (view?.failure) return "failed";
  return "empty";
}

const THUMB_BG: Record<ReturnType<typeof thumbState>, string> = {
  running: "bg-rose-200 animate-pulse",
  queued: "bg-zinc-400",
  failed: "bg-red-400",
  done: "bg-white",
  empty: "bg-zinc-200",
};

function ThumbPanel({ lp, view, W, H }: { lp: LayoutPanel; view: PanelView | undefined; W: number; H: number }) {
  const state = thumbState(view);
  const poly = lp.slanted ? panelPolygon(lp) : null;
  const pct = (v: number, total: number) => `${(v / total) * 100}%`;
  const url = view?.panel.selected_image_url ?? null;
  return (
    <div
      className={`absolute overflow-hidden ${THUMB_BG[state]} ${poly ? "" : "outline outline-1 outline-zinc-900"}`}
      style={{
        left: pct(lp.x1, W),
        top: pct(lp.y1, H),
        width: pct(lp.width, W),
        height: pct(lp.height, H),
        clipPath: poly ? cssClipPath(poly, lp) : undefined,
      }}
      data-testid="production-panel"
      data-state={state}
    >
      {url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={engineUrl(url)} alt="" className={`h-full w-full object-cover ${state === "running" || state === "queued" ? "opacity-60" : ""}`} />
      )}
      {state === "queued" && !url && (
        <span className="flex h-full w-full items-center justify-center text-[9px] font-bold text-zinc-100">
          {Math.min(...view!.pending.map((i) => i.position))}
        </span>
      )}
      {state === "running" && (
        <span className="absolute inset-x-0 bottom-0 h-1 bg-zinc-900/40">
          <span className="block h-full bg-rose-500 transition-[width] duration-500" style={{ width: `${view!.running!.job.progress}%` }} />
        </span>
      )}
    </div>
  );
}

function PageThumb({
  page,
  views,
  active,
  onClick,
}: {
  page: PageData;
  views: Map<number, PanelView>;
  active: boolean;
  onClick: () => void;
}) {
  const ready = page.panels.filter((p) => p.selected_image_id !== null).length;
  const states = page.panels.map((p) => thumbState(views.get(p.id)));
  const generating = states.includes("running");
  const failed = states.filter((s) => s === "failed").length;
  const layout = page.layout;
  const byId = new Map(page.panels.map((p) => [p.id, p]));
  const ref = useRef<HTMLButtonElement>(null);
  // La page suivie (case en cours) reste visible dans la bande.
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [active]);
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={`Page ${page.number} : ${ready} case${ready > 1 ? "s" : ""} prête${ready > 1 ? "s" : ""} sur ${page.panels.length}${generating ? ", génération en cours" : ""}${failed ? `, ${failed} échec${failed > 1 ? "s" : ""}` : ""}`}
      className={`block w-28 rounded-md p-1.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 ${
        active ? "bg-rose-500/15 ring-2 ring-rose-400" : "bg-zinc-900 ring-1 ring-zinc-800 hover:ring-zinc-600"
      }`}
      data-testid="production-page"
      data-ready={ready}
    >
      {layout && page.panels.length ? (
        <div className="relative w-full overflow-hidden bg-zinc-100" style={{ aspectRatio: `${layout.page.width} / ${layout.page.height}` }}>
          {[...layout.panels.filter((p) => !p.inset), ...layout.panels.filter((p) => p.inset)].map((lp) => {
            const panel = (lp.panel_id !== null ? byId.get(lp.panel_id) : undefined) ?? page.panels[lp.index];
            return panel ? (
              <ThumbPanel key={lp.index} lp={lp} view={views.get(panel.id)} W={layout.page.width} H={layout.page.height} />
            ) : null;
          })}
        </div>
      ) : (
        <div className="flex aspect-[1/1.414] w-full items-center justify-center bg-zinc-800 p-1 text-center text-[10px] text-zinc-400">
          {page.panels.length ? "Pas encore mise en page" : "Page sans case"}
        </div>
      )}
      <span className="mt-1 flex items-center justify-between text-[11px]">
        <span className="font-medium text-zinc-200">p. {page.number}</span>
        <span className={failed ? "text-red-300" : generating ? "text-rose-300" : "text-zinc-500"}>
          {ready}/{page.panels.length}
        </span>
      </span>
    </button>
  );
}

function PagePreview({
  page,
  views,
  chapterId,
  refreshKey,
  lettered,
  onLettered,
  onOpen,
}: {
  page: PageData;
  views: Map<number, PanelView>;
  chapterId: number;
  refreshKey: number;
  lettered: boolean;
  onLettered: (on: boolean) => void;
  onOpen: (panelId: number) => void;
}) {
  const canLetter = hasLettering(page);
  const ready = page.panels.filter((p) => p.selected_image_id !== null).length;
  const failures = page.panels.map((p) => views.get(p.id)).filter((v) => v && !v.running && !v.pending.length && v.failure);
  return (
    <Card className="p-3 sm:p-5" data-testid="production-preview">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold text-zinc-200">
          Page {page.number}{" "}
          <span className="font-normal text-zinc-400">
            — {ready}/{page.panels.length} case{page.panels.length > 1 ? "s" : ""} prête{page.panels.length > 1 ? "s" : ""}
          </span>
        </h2>
        {canLetter && page.layout && (
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input
              type="checkbox"
              checked={lettered}
              onChange={(e) => onLettered(e.target.checked)}
              className="accent-rose-500"
              data-testid="toggle-lettering"
            />
            Afficher les bulles et onomatopées
          </label>
        )}
        <ButtonLink variant="secondary" className="ml-auto" href={workshopHref(chapterId, page.id)}>
          Ouvrir dans l&apos;atelier
        </ButtonLink>
      </div>
      {failures.length > 0 && (
        <div className="mb-3">
          <Alert>
            {failures.length} case{failures.length > 1 ? "s" : ""} en échec :{" "}
            {failures.map((v) => `case ${v!.panel.index + 1} (${v!.failure!.error ?? "erreur inconnue"})`).join(" ; ")}
          </Alert>
        </div>
      )}
      {!page.panels.length ? (
        <EmptyState title="Page sans case">Cette page n&apos;a rien à générer.</EmptyState>
      ) : !page.layout ? (
        <EmptyState title="Page pas encore mise en page">
          La géométrie des cases vient de la mise en page.
          <div className="mt-4">
            <ButtonLink href={`/chapitres/${chapterId}/mise-en-page`}>Aller à la Mise en page</ButtonLink>
          </div>
        </EmptyState>
      ) : lettered && canLetter ? (
        <LetteredPreview page={page} refreshKey={refreshKey} />
      ) : (
        <>
          <PageCanvas page={page} views={views} selectedPanelId={null} onOpen={onOpen} />
          <p className="mt-3 text-center text-xs text-zinc-500">
            Chaque case apparaît dès qu&apos;elle est terminée · clique sur une case pour l&apos;ouvrir dans l&apos;atelier.
          </p>
        </>
      )}
    </Card>
  );
}
