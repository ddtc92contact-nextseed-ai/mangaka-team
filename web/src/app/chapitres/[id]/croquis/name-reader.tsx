"use client";

import { useEffect, useMemo, useState } from "react";
import { modalOpen } from "@/components/modal";
import { DirectionBadge } from "@/components/reading-direction";
import { Alert, Button, Loading, Select } from "@/components/ui";
import { api, type PageData, type ReadingDirection } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { nextKey, spreadLabel, spreadOf, spreads, turnPage } from "@/lib/name";
import { LetteredBoard, NameBar } from "./draft-board";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable));
}

/** Une page de la double page : planche brouillon lettrée, tourne, validation de la name. */
function ReaderPage({
  page,
  turn,
  refreshKey,
  busy,
  onValidate,
  onUnvalidate,
  onOpen,
}: {
  page: PageData;
  turn: boolean;
  refreshKey: unknown;
  busy: boolean;
  onValidate: () => void;
  onUnvalidate: () => void;
  onOpen: () => void;
}) {
  const lettering = useEngineData(() => api.getLettering(page.id), [page.id, refreshKey]);
  const data = lettering.data && lettering.data.page_id === page.id ? lettering.data : null;
  const last = page.panels[page.panels.length - 1];
  return (
    <figure className="min-w-0 flex-1 space-y-2" data-testid="reader-page" data-page={page.number}>
      <div className="relative">
        {!page.layout ? (
          <div className="flex aspect-[3/4] items-center justify-center rounded-sm bg-zinc-900 p-4 text-center text-sm text-zinc-500">
            Page {page.number} pas encore mise en page
          </div>
        ) : lettering.error && !data ? (
          <Alert>Planche indisponible : {lettering.error}</Alert>
        ) : !data ? (
          <Loading />
        ) : (
          <div className="mx-auto w-fit max-w-full overflow-hidden rounded-sm bg-white shadow-lg shadow-black/40">
            <LetteredBoard data={data} vh={78} />
          </div>
        )}
        {turn && (
          <span
            className="absolute bottom-2 right-2 rounded bg-rose-600/90 px-2 py-0.5 text-[11px] font-semibold text-white shadow"
            data-testid="reader-turn"
            title="Dernière page lue avant de tourner : sa dernière case porte la tourne (suspense, révélation)."
          >
            Tourne{last ? ` · après la case ${last.index + 1}` : ""}
          </span>
        )}
      </div>
      <figcaption className="space-y-2">
        <div className="flex items-center justify-between gap-2 text-xs text-zinc-400">
          <span className="font-medium text-zinc-200">Page {page.number}</span>
          <button type="button" className="text-zinc-400 underline-offset-2 hover:text-zinc-100 hover:underline" onClick={onOpen}>
            Corriger cette page →
          </button>
        </div>
        <NameBar page={page} busy={busy} onValidate={onValidate} onUnvalidate={onUnvalidate} compact />
      </figcaption>
    </figure>
  );
}

/**
 * Mode lecture de la name : double pages dans le sens de lecture de la série (manga : la première page lue à
 * droite), tourne visible, validation page par page. Sur téléphone, les pages s'empilent dans l'ordre de lecture.
 */
export function NameReader({
  pages,
  direction,
  pageId,
  refreshKey,
  busy,
  onValidate,
  onUnvalidate,
  onOpen,
}: {
  pages: PageData[];
  direction: ReadingDirection;
  pageId: number | null;
  refreshKey: unknown;
  busy: boolean;
  onValidate: (page: PageData) => void;
  onUnvalidate: (page: PageData) => void;
  onOpen: (page: PageData) => void;
}) {
  const readable = useMemo(() => pages.filter((p) => p.panels.length), [pages]);
  const all = useMemo(() => spreads(readable), [readable]);
  const [at, setAt] = useState(() => spreadOf(all, pageId));
  const index = Math.min(at, Math.max(all.length - 1, 0));
  const spread = all[index] ?? [];
  const turn = turnPage(spread);
  const next = () => setAt((i) => Math.min(i + 1, all.length - 1));
  const prev = () => setAt((i) => Math.max(i - 1, 0));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || modalOpen() || isTyping(e.target)) return;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      if (e.key === nextKey(direction)) next();
      else prev();
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!readable.length) return <Alert tone="info">Aucune page à lire : découpe d&apos;abord le chapitre.</Alert>;
  const rtl = direction === "rtl";
  // Boutons dans le sens de lecture : en manga, « suivante » est à gauche.
  const prevButton = (
    <Button variant="secondary" onClick={prev} disabled={index === 0} data-testid="reader-prev">
      {rtl ? "Précédente →" : "← Précédente"}
    </Button>
  );
  const nextButton = (
    <Button variant="secondary" onClick={next} disabled={index >= all.length - 1} data-testid="reader-next">
      {rtl ? "← Suivante" : "Suivante →"}
    </Button>
  );
  return (
    <section className="space-y-3" aria-label="Lecture de la name" data-testid="name-reader">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {rtl ? nextButton : prevButton}
          <label htmlFor="reader-spread" className="sr-only">
            Double page
          </label>
          <Select id="reader-spread" className="!w-auto py-1.5" value={index} onChange={(e) => setAt(Number(e.target.value))}>
            {all.map((s, i) => (
              <option key={i} value={i}>
                {spreadLabel(s)}
              </option>
            ))}
          </Select>
          {rtl ? prevButton : nextButton}
        </div>
        <p className="flex items-center gap-2 text-xs text-zinc-400">
          <DirectionBadge direction={direction} />
          {index + 1} / {all.length} · flèche {rtl ? "←" : "→"} : double page suivante
        </p>
      </div>
      <div
        className={`flex flex-col gap-4 sm:gap-1 ${rtl ? "sm:flex-row-reverse" : "sm:flex-row"}`}
        data-testid="reader-spread"
        data-direction={direction}
      >
        {spread.map((page, i) =>
          page ? (
            <ReaderPage
              key={page.id}
              page={page}
              turn={page === turn && index < all.length - 1}
              refreshKey={refreshKey}
              busy={busy}
              onValidate={() => onValidate(page)}
              onUnvalidate={() => onUnvalidate(page)}
              onOpen={() => onOpen(page)}
            />
          ) : (
            <div key={`blanc-${i}`} className="hidden flex-1 items-center justify-center rounded-sm border border-dashed border-zinc-800 text-xs text-zinc-600 sm:flex">
              {index === 0 ? "Début du chapitre" : "Fin du chapitre"}
            </div>
          ),
        )}
      </div>
      {index < all.length - 1 && (
        <p className="text-center text-xs text-zinc-500" data-testid="reader-turn-note">
          Tourne après la page {turn?.number} : la double page suivante se découvre d&apos;un coup.
        </p>
      )}
    </section>
  );
}
