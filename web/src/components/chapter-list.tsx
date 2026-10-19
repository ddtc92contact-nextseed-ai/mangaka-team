"use client";

import Link from "next/link";
import { useState } from "react";
import { api, errorMessage, type Chapter } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { chapterDeleteDialog } from "./chapter-delete";
import { useConfirm } from "./confirm";
import { ChapterStatusBadge, formatPlannedDate } from "./status";
import { useToast } from "./toast";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading } from "./ui";

/** `onDeleted` : après une suppression, pour relire ce qui en dépend (tomes, bible, estimation). */
export function ChapterList({ projectId, onDeleted }: { projectId: number; onDeleted?: () => void }) {
  const chapters = useEngineData(() => api.listChapters(projectId), [projectId]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const toast = useToast();
  const confirm = useConfirm();
  // Sélection limitée aux chapitres encore listés (un chapitre supprimé en sort de lui-même).
  const listed = chapters.data ?? [];
  const picked = listed.filter((c) => selected.has(c.id));
  const allPicked = listed.length > 0 && picked.length === listed.length;

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function remove(targets: Chapter[]) {
    if (!targets.length || !(await confirm(chapterDeleteDialog(targets)))) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteChapters(
        projectId,
        targets.map((c) => c.id),
      );
      chapters.setData(await api.listChapters(projectId));
      onDeleted?.();
      toast(targets.length > 1 ? `${targets.length} chapitres supprimés` : `Chapitre ${targets[0].number} supprimé`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

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
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Chapitres</h2>
        <div className="flex flex-wrap gap-2">
          {picked.length > 0 && (
            <Button variant="danger" onClick={() => remove(picked)} disabled={busy} data-testid="delete-selected-chapters">
              Supprimer la sélection ({picked.length})
            </Button>
          )}
          <ButtonLink href={`/projets/${projectId}/chapitres/nouveau`}>Nouveau chapitre</ButtonLink>
        </div>
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
        <>
          <label className="flex w-fit items-center gap-2 border-b border-zinc-800 pb-2 text-xs text-zinc-400">
            <input
              type="checkbox"
              checked={allPicked}
              ref={(el) => {
                if (el) el.indeterminate = picked.length > 0 && !allPicked;
              }}
              onChange={() => setSelected(allPicked ? new Set() : new Set(listed.map((c) => c.id)))}
              disabled={busy}
              className="accent-rose-500"
              data-testid="select-all-chapters"
            />
            Tout sélectionner
            {picked.length > 0 && (
              <span className="text-zinc-500">
                · {picked.length} sélectionné{picked.length > 1 ? "s" : ""}
              </span>
            )}
          </label>
          <ol className="divide-y divide-zinc-800" aria-label="Chapitres de la série">
            {chapters.data.map((c: Chapter, i) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 py-3">
                <input
                  type="checkbox"
                  checked={selected.has(c.id)}
                  onChange={() => toggle(c.id)}
                  disabled={busy}
                  className="accent-rose-500"
                  aria-label={`Sélectionner le chapitre ${c.number}`}
                />
                <span className="w-8 shrink-0 text-right font-mono text-sm text-zinc-500">#{c.number}</span>
                <Link
                  href={`/chapitres/${c.id}`}
                  className="min-w-0 flex-1 basis-40 truncate font-medium text-zinc-100 hover:text-rose-300"
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
                  <Button
                    variant="ghost"
                    className="px-2 py-1 text-red-400 hover:text-red-300"
                    onClick={() => remove([c])}
                    disabled={busy}
                    aria-label={`Supprimer le chapitre ${c.number}`}
                  >
                    Supprimer
                  </Button>
                </span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <EmptyState title="Aucun chapitre">
          Une série avance chapitre par chapitre : crée le premier pour écrire son synopsis puis le découper.
        </EmptyState>
      )}
    </Card>
  );
}
