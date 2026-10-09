"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ChapterForm } from "@/components/chapter-form";
import { GenerateChapterButton } from "@/components/generate-chapter";
import { Alert, Button, ButtonLink, Card } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useChapter } from "./chapter-context";

export default function ChapterInfoPage() {
  const { chapter, setChapter, reload } = useChapter();
  const [queued, setQueued] = useState<string | null>(null);
  const router = useRouter();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    if (!window.confirm(`Supprimer le chapitre ${chapter.number} et toutes ses pages ? Action définitive.`)) return;
    try {
      await api.deleteChapter(chapter.id);
      router.push(`/projets/${chapter.project_id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Card>
        <h2 className="mb-4 font-semibold text-zinc-100">Chapitre</h2>
        {saved && (
          <div className="mb-4">
            <Alert tone="info">Chapitre enregistré.</Alert>
          </div>
        )}
        <ChapterForm
          key={chapter.updated_at}
          projectId={chapter.project_id}
          initial={chapter}
          submitLabel="Enregistrer"
          onSaved={(c) => {
            setChapter(c);
            setSaved(true);
          }}
        />
      </Card>
      <div className="space-y-6">
        <Card>
          <h2 className="mb-2 font-semibold text-zinc-100">Résumé pour la continuité</h2>
          <p className="mb-3 text-xs text-zinc-500">
            Écrit par le LLM au découpage, relu par les chapitres suivants de la série.
          </p>
          {chapter.summary ? (
            <p className="whitespace-pre-line text-sm text-zinc-300" data-testid="chapter-summary">
              {chapter.summary}
            </p>
          ) : (
            <p className="text-sm text-zinc-500">Pas encore de résumé : lance « Découper » dans l&apos;onglet Scénario.</p>
          )}
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold text-zinc-100">Avancement</h2>
          <p className="text-sm text-zinc-400">
            {chapter.page_count} page{chapter.page_count > 1 ? "s" : ""} · {chapter.panel_count} case
            {chapter.panel_count > 1 ? "s" : ""} (objectif : {chapter.target_page_count} pages)
          </p>
          {error && (
            <div className="mt-3">
              <Alert>{error}</Alert>
            </div>
          )}
          {queued && (
            <div className="mt-3">
              <Alert tone="info">{queued}</Alert>
            </div>
          )}
          {chapter.panel_count > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              <ButtonLink href={`/chapitres/${chapter.id}/atelier`}>Ouvrir l&apos;atelier</ButtonLink>
              <GenerateChapterButton
                chapterId={chapter.id}
                onQueued={(m) => {
                  setQueued(m);
                  reload();
                }}
              />
            </div>
          )}
          <div className="mt-4">
            <Button variant="danger" onClick={remove}>
              Supprimer le chapitre
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
