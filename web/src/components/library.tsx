"use client";

import Link from "next/link";
import { useRef, type KeyboardEvent } from "react";
import { Avatar } from "@/components/avatar";
import { Alert, ButtonLink, EmptyState, Loading } from "@/components/ui";
import { api, type LibraryKind } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { LIBRARY_KINDS, LIBRARY_ORDER, entryHref, newEntryHref } from "@/lib/library";

/** Onglets Personnages / Objets / Décors (flèches gauche / droite pour changer d'onglet). */
export function LibraryTabs({
  value,
  onChange,
  idPrefix,
}: {
  value: LibraryKind;
  onChange: (kind: LibraryKind) => void;
  idPrefix: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(e: KeyboardEvent, index: number) {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = (index + delta + LIBRARY_ORDER.length) % LIBRARY_ORDER.length;
    onChange(LIBRARY_ORDER[next]);
    refs.current[next]?.focus();
  }
  return (
    <div role="tablist" aria-label="Bibliothèque de la série" className="flex gap-1 overflow-x-auto border-b border-zinc-800">
      {LIBRARY_ORDER.map((k, i) => {
        const active = k === value;
        return (
          <button
            key={k}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${k}`}
            aria-selected={active}
            aria-controls={`${idPrefix}-panel`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(k)}
            onKeyDown={(e) => onKey(e, i)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-rose-400 ${
              active ? "border-rose-400 text-zinc-50" : "border-transparent text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {LIBRARY_KINDS[k].tab}
          </button>
        );
      })}
    </div>
  );
}

/** Fiches d'une sorte pour une série : grille de cartes (`compact` : liste dans la fiche série). */
export function LibraryList({ kind, projectId, compact = false }: { kind: LibraryKind; projectId: number; compact?: boolean }) {
  const info = LIBRARY_KINDS[kind];
  const entries = useEngineData(() => api.listLibrary(kind, projectId), [kind, projectId]);

  if (entries.loading) return <Loading />;
  if (entries.error) return <Alert>{entries.error}</Alert>;
  const list = entries.data ?? [];

  if (compact) {
    return list.length ? (
      <ul className="divide-y divide-zinc-800">
        {list.map((e) => (
          <li key={e.id}>
            <Link
              href={entryHref(kind, e.id)}
              className="flex items-center gap-3 py-2 text-sm text-zinc-200 hover:text-rose-300"
            >
              <Avatar url={e.reference_images[0]?.url} name={e.name} />
              <span className="truncate">{e.name}</span>
              <span className="ml-auto shrink-0 text-xs text-zinc-500">{e.reference_images.length} réf.</span>
            </Link>
          </li>
        ))}
      </ul>
    ) : (
      <p className="py-2 text-sm text-zinc-500">{info.emptyList}.</p>
    );
  }

  return list.length ? (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {list.map((e) => (
        <li key={e.id}>
          <Link
            href={entryHref(kind, e.id)}
            className="flex h-full gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 transition-colors hover:border-zinc-600"
          >
            <Avatar url={e.reference_images[0]?.url} name={e.name} size="h-14 w-14" />
            <div className="min-w-0">
              <p className="font-semibold text-zinc-100">{e.name}</p>
              <p className="line-clamp-2 text-sm text-zinc-400">{e.visual_description || "Pas de description visuelle"}</p>
              <p className="mt-2 text-xs text-zinc-500">
                {e.reference_images.length} image{e.reference_images.length > 1 ? "s" : ""} de référence
                {e.lora_name && ` · LoRA ${e.lora_name}`}
              </p>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  ) : (
    <EmptyState title={info.emptyList}>
      <ButtonLink href={newEntryHref(kind, projectId)}>{info.addLabel}</ButtonLink>
    </EmptyState>
  );
}
