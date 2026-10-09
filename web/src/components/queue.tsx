"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, fullErrorMessage, type Queue, type QueueItem } from "@/lib/api";
import { formatDuration, workshopHref } from "@/lib/generation";
import { Badge, useEngineStatus } from "./engine-status";
import { ProgressBar } from "./ui";

const ACTIVE_POLL_MS = 1000;
const IDLE_POLL_MS = 4000;

interface QueueContextValue {
  queue: Queue | null;
  error: string | null;
  /** Incrémenté chaque fois qu'au moins un job quitte la file (terminé, échoué ou annulé). */
  finished: number;
  /** Relit la file tout de suite (après une mise en file). */
  refresh: () => void;
  cancel: (jobId: number) => Promise<void>;
}

const QueueContext = createContext<QueueContextValue>({
  queue: null,
  error: null,
  finished: 0,
  refresh: () => {},
  cancel: async () => {},
});

export const useQueue = () => useContext(QueueContext);

export function queueItems(queue: Queue | null): QueueItem[] {
  if (!queue) return [];
  return queue.running ? [queue.running, ...queue.pending] : queue.pending;
}

/** Sonde `GET /queue` : chaque seconde quand des générations sont actives, sinon toutes les 4 s. */
export function QueueProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(0);
  const pollNow = useRef<() => void>(() => {});

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let known = new Set<number>();
    let inFlight = false;

    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      clearTimeout(timer);
      let active = false;
      try {
        const q = await api.queue();
        if (stopped) return;
        const ids = new Set(queueItems(q).map((i) => i.job.id));
        if ([...known].some((id) => !ids.has(id))) setFinished((n) => n + 1);
        known = ids;
        active = ids.size > 0;
        setQueue(q);
        setError(null);
      } catch (e) {
        if (!stopped) setError(fullErrorMessage(e));
      } finally {
        inFlight = false;
      }
      if (!stopped) timer = setTimeout(poll, active ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    };
    pollNow.current = () => void poll();
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);

  const refresh = useCallback(() => pollNow.current(), []);
  const cancel = useCallback(async (jobId: number) => {
    try {
      await api.cancelJob(jobId);
    } finally {
      pollNow.current();
    }
  }, []);

  return (
    <QueueContext.Provider value={{ queue, error, finished, refresh, cancel }}>{children}</QueueContext.Provider>
  );
}

/** État de ComfyUI vu par la file : hors ligne (avec l'adresse) ou mode simulé. */
export function ComfyQueueStatus() {
  const status = useEngineStatus();
  if (status.state !== "online") return null;
  const { comfyui } = status.health;
  if (!comfyui.online) {
    return (
      <p role="alert" className="rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-200">
        <strong className="font-semibold">ComfyUI hors ligne</strong>
        {comfyui.url && (
          <>
            {" "}
            — <code className="text-xs">{comfyui.url}</code>
          </>
        )}
        . Les générations échouent tant qu&apos;il ne répond pas.
        {comfyui.detail && <span className="mt-1 block text-xs text-red-300/80">{comfyui.detail}</span>}
      </p>
    );
  }
  if (comfyui.provider === "mock") {
    return (
      <p className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
        <Badge tone="warn">Mode simulé</Badge>
        Images factices, aucun GPU sollicité.
      </p>
    );
  }
  return null;
}

function variantLabel(item: QueueItem): string {
  return item.count && item.count > 1 ? `variante ${item.variant}/${item.count}` : "";
}

function itemTitle(item: QueueItem): string {
  const variant = variantLabel(item);
  return variant ? `${item.label} · ${variant}` : item.label;
}

function QueueRow({ item, compact, onNavigate }: { item: QueueItem; compact: boolean; onNavigate?: () => void }) {
  const { cancel } = useQueue();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = item.job.status === "running";
  const href = item.chapter_id ? workshopHref(item.chapter_id, item.page_id, item.panel_id) : null;

  async function onCancel() {
    setBusy(true);
    setError(null);
    try {
      await cancel(item.job.id);
    } catch (e) {
      setError(fullErrorMessage(e));
      setBusy(false);
    }
  }

  return (
    <li className={`flex flex-col gap-1.5 ${compact ? "py-2" : "py-3"}`} data-testid={running ? "queue-running" : "queue-pending"}>
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1 text-[11px] font-semibold ${
            running ? "bg-rose-500/20 text-rose-300" : "bg-zinc-800 text-zinc-400"
          }`}
          aria-label={running ? "En cours" : `Position ${item.position}`}
        >
          {running ? "▶" : item.position}
        </span>
        <div className="min-w-0 flex-1">
          {href ? (
            <Link href={href} onClick={onNavigate} className="block truncate text-sm text-zinc-100 hover:text-rose-300" title={itemTitle(item)}>
              {item.label}
            </Link>
          ) : (
            <span className="block truncate text-sm text-zinc-100">{item.label}</span>
          )}
          <p className="text-xs text-zinc-500">
            {running ? (
              <>
                {item.job.progress} %
              </>
            ) : (
              "En attente"
            )}
            {variantLabel(item) && <> · {variantLabel(item)}</>}
            {item.preset && !compact && <> · {item.preset}</>}
            {" · "}
            {item.eta_s === null ? "durée inconnue" : item.eta_s < 1 ? "fin imminente" : `fin dans ≈ ${formatDuration(item.eta_s)}`}
          </p>
        </div>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="shrink-0 rounded-md px-2 py-1 text-xs text-zinc-400 ring-1 ring-inset ring-zinc-700 hover:bg-red-500/10 hover:text-red-300 hover:ring-red-500/40 focus-visible:outline-2 focus-visible:outline-rose-400 disabled:opacity-50"
          aria-label={`Annuler : ${itemTitle(item)}`}
        >
          {busy ? "Annulation…" : "Annuler"}
        </button>
      </div>
      {running && <ProgressBar key={item.job.id} value={item.job.progress} label={`Progression : ${itemTitle(item)}`} />}
      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}
    </li>
  );
}

/** Liste de la file : génération en cours puis attente, avec ETA et annulation. */
export function QueueList({ compact = false, onNavigate }: { compact?: boolean; onNavigate?: () => void }) {
  const { queue, error } = useQueue();
  const items = queueItems(queue);
  const max = compact ? 6 : 50;

  return (
    <div className="space-y-3">
      <ComfyQueueStatus />
      {error && !queue ? (
        <p role="alert" className="text-sm text-red-400">
          File d&apos;attente indisponible : {error}
        </p>
      ) : !queue ? (
        <p className="text-sm text-zinc-500">Chargement…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-zinc-500" data-testid="queue-empty">
          Aucune génération en cours ni en attente.
        </p>
      ) : (
        <>
          <p className="text-xs text-zinc-400">
            {queue.running ? "1 en cours" : "Rien en cours"} · {queue.pending.length} en attente
            {queue.total_eta_s !== null && queue.total_eta_s > 0 && (
              <> · tout sera fini dans ≈ {formatDuration(queue.total_eta_s)}</>
            )}
          </p>
          <ul className="divide-y divide-zinc-800">
            {items.slice(0, max).map((item) => (
              <QueueRow key={item.job.id} item={item} compact={compact} onNavigate={onNavigate} />
            ))}
          </ul>
          {items.length > max && (
            <p className="text-xs text-zinc-500">… et {items.length - max} autre(s) en attente.</p>
          )}
        </>
      )}
    </div>
  );
}

/** Indicateur compact de l'en-tête : progression en cours, nombre en attente, menu déroulant. */
export function QueueIndicator() {
  const { queue } = useQueue();
  const status = useEngineStatus();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Consommé ici : le panneau latéral de l'atelier ne se ferme pas en même temps.
      e.preventDefault();
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const comfy = status.state === "online" ? status.health.comfyui : null;
  const offline = comfy !== null && !comfy.online;
  const mock = comfy?.provider === "mock";
  const pending = queue?.pending.length ?? 0;
  const running = queue?.running ?? null;

  let label: ReactNode;
  if (running) {
    label = (
      <>
        <span className="h-2 w-2 animate-pulse rounded-full bg-rose-400" />
        Génération {running.job.progress} %{pending > 0 && <span className="text-zinc-400">· {pending} en attente</span>}
      </>
    );
  } else if (pending > 0) {
    label = (
      <>
        <span className="h-2 w-2 rounded-full bg-amber-400" />
        {pending} en attente
      </>
    );
  } else {
    label = (
      <>
        <span className="h-2 w-2 rounded-full bg-zinc-600" />
        File vide
      </>
    );
  }

  return (
    <div ref={rootRef} className="relative flex items-center gap-2">
      {offline && (
        <Badge tone="off" title={comfy?.url ?? undefined}>
          ComfyUI hors ligne
        </Badge>
      )}
      {mock && (
        <span className="inline-flex">
          <Badge tone="warn" title="ComfyUI simulé : images factices, aucun GPU">
            Mode simulé
          </Badge>
        </span>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="queue-popover"
        data-testid="queue-indicator"
        className="relative inline-flex items-center gap-2 overflow-hidden rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 ring-1 ring-inset ring-zinc-800 hover:bg-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400"
      >
        <span className="sr-only">File d&apos;attente : </span>
        {label}
        {running && (
          <span
            aria-hidden
            className="absolute inset-x-0 bottom-0 h-0.5 bg-rose-400 transition-[width] duration-500"
            style={{ width: `${running.job.progress}%` }}
          />
        )}
      </button>
      {open && (
        <div
          id="queue-popover"
          role="region"
          aria-label="File d'attente ComfyUI"
          className="absolute right-0 top-full z-40 mt-2 w-[26rem] max-w-[calc(100vw-2rem)] rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-2xl"
        >
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-zinc-100">File d&apos;attente</h2>
            <Link href="/#file-attente" onClick={() => setOpen(false)} className="text-xs text-zinc-400 hover:text-zinc-100">
              Tableau de bord →
            </Link>
          </div>
          <QueueList compact onNavigate={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}
