"use client";

import { useEffect, useState } from "react";
import { api, engineUrl, type Job } from "./api";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
const POLL_MS = 1500;

export const isFinished = (job: Job | null) => job !== null && TERMINAL.has(job.status);

/**
 * Suit un job du moteur en temps réel (SSE `/jobs/{id}/events`), avec repli sur un sondage
 * si le flux est coupé (proxy, mise en veille…). S'arrête dès que le job est terminé.
 */
export function useJob(initial: Job | null, onFinished?: (job: Job) => void): Job | null {
  const [live, setLive] = useState<Job | null>(null);
  const id = initial?.id ?? null;

  useEffect(() => {
    if (id === null || (initial && TERMINAL.has(initial.status))) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let source: EventSource | null = null;

    const update = (next: Job) => {
      if (stopped) return;
      setLive(next);
      if (TERMINAL.has(next.status)) {
        stop();
        onFinished?.(next);
      }
    };
    const poll = async () => {
      try {
        update(await api.getJob(id));
      } catch {
        /* moteur momentanément hors ligne : on réessaie */
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS);
    };
    const stop = () => {
      stopped = true;
      source?.close();
      clearTimeout(timer);
    };

    if (typeof EventSource !== "undefined") {
      source = new EventSource(engineUrl(`/jobs/${id}/events`));
      source.addEventListener("job", (e) => update(JSON.parse((e as MessageEvent<string>).data) as Job));
      source.onerror = () => {
        // Flux coupé : on bascule sur le sondage (EventSource se reconnecterait aussi, mais
        // le proxy coupe les flux longs ; le sondage est plus prévisible).
        source?.close();
        source = null;
        if (!stopped && timer === undefined) poll();
      };
    } else {
      poll();
    }
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Dernier état reçu pour ce job ; sinon celui fourni par l'appelant.
  return live && live.id === id ? live : initial;
}
