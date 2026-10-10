"use client";

import Link from "next/link";
import { useState } from "react";
import { api, errorMessage, type Chapter } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { ChapterStatusBadge, formatPlannedDate } from "./status";
import { useToast } from "./toast";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading } from "./ui";

export function ChapterList({ projectId }: { projectId: number }) {
  const chapters = useEngineData(() => api.listChapters(projectId), [projectId]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function move(index: number, delta: -1 | 1) {
    const list = chapters.data;
    if (!list) return;
    const target = index + delta;
    if (target < 0 || target >= list.length) return;
    const ids = list.map((c) => c.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    setBusy(true);
    setError(null);
    try {
      chapters.setData(await api.reorderChapters(projectId, ids));
      toast("Ordre des chapitres enregistré");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Chapitres</h2>
        <ButtonLink href={`/projets/${projectId}/chapitres/nouveau`}>Nouveau chapitre</ButtonLink>
      </div>
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      {chapters.loading && !chapters.data ? (
        <Loading />
      ) : chapters.error ? (
        <Alert>Impossible de charger les chapitres : {chapters.error}</Alert>
      ) : chapters.data?.length ? (
        <ol className="divide-y divide-zinc-800" aria-label="Chapitres de la série">
          {chapters.data.map((c: Chapter, i) => (
            <li key={c.id} className="flex flex-wrap items-center gap-3 py-3">
              <span className="w-10 shrink-0 text-right font-mono text-sm text-zinc-500">#{c.number}</span>
              <Link
                href={`/chapitres/${c.id}`}
                className="min-w-0 flex-1 truncate font-medium text-zinc-100 hover:text-rose-300"
              >
                {c.title || `Chapitre ${c.number}`}
              </Link>
              <ChapterStatusBadge status={c.status} />
              <span className="w-28 text-xs text-zinc-400" title="Publication prévue">
                {formatPlannedDate(c.planned_date)}
              </span>
              <span className="w-24 text-xs text-zinc-500">
                {c.page_count ? `${c.page_count} p. · ${c.panel_count} cases` : `${c.target_page_count} p. visées`}
              </span>
              <span className="flex gap-1">
                <Button
                  variant="ghost"
                  className="px-2 py-1"
                  onClick={() => move(i, -1)}
                  disabled={busy || i === 0}
                  aria-label={`Monter le chapitre ${c.number}`}
                >
                  ↑
                </Button>
                <Button
                  variant="ghost"
                  className="px-2 py-1"
                  onClick={() => move(i, 1)}
                  disabled={busy || i === chapters.data!.length - 1}
                  aria-label={`Descendre le chapitre ${c.number}`}
                >
                  ↓
                </Button>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <EmptyState title="Aucun chapitre">
          Une série avance chapitre par chapitre : crée le premier pour écrire son synopsis puis le découper.
        </EmptyState>
      )}
    </Card>
  );
}
