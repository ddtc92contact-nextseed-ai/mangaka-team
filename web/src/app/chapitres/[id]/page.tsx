"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useConfirm } from "@/components/confirm";
import { ChapterForm } from "@/components/chapter-form";
import { GenerateChapterButton } from "@/components/generate-chapter";
import { InfoTip } from "@/components/info-tip";
import { ProductionLink } from "@/components/production-link";
import { useToast } from "@/components/toast";
import { Alert, Button, ButtonLink, Card } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useChapter } from "./chapter-context";

export default function ChapterInfoPage() {
  const { chapter, setChapter, reload } = useChapter();
  const [queued, setQueued] = useState<string | null>(null);
  const router = useRouter();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();
  const toast = useToast();
  const [rewriting, setRewriting] = useState(false);
  const [rewritten, setRewritten] = useState<string | null>(null);

  async function rewritePrompts() {
    setError(null);
    setRewritten(null);
    setRewriting(true);
    try {
      const { count, ai_prompt } = await api.rewritablePrompts(chapter.id);
      if (!ai_prompt) {
        setRewritten("Cette série assemble ses prompts par fragments : rien à réécrire (active « Prompt rédigé par l'IA » dans la fiche série).");
        return;
      }
      if (count === 0) {
        setRewritten("Aucun prompt rédigé par l'IA à réécrire dans ce chapitre (les prompts retouchés à la main ne sont jamais touchés).");
        return;
      }
      const plural = count > 1 ? "s" : "";
      const ok = await confirm({
        title: `Réécrire ${count} prompt${plural} ?`,
        message: `${count} case${plural} du chapitre ${count > 1 ? "ont" : "a"} un prompt rédigé par l'IA. ${count > 1 ? "Ils seront rédigés" : "Il sera rédigé"} de nouveau, avec le savoir-faire et le cadrage actuels, à la prochaine génération de chaque case. Les prompts retouchés à la main ne bougent pas.`,
        confirmLabel: `Réécrire ${count} prompt${plural}`,
      });
      if (!ok) return;
      const res = await api.rewriteChapterPrompts(chapter.id);
      const n = res.count;
      setRewritten(
        `${n} prompt${n > 1 ? "s" : ""} à réécrire : ${n > 1 ? "ils seront rédigés" : "il sera rédigé"} de nouveau à la prochaine génération de ${n > 1 ? "leur" : "sa"} case.`,
      );
      toast(`${n} prompt${n > 1 ? "s" : ""} à réécrire`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRewriting(false);
    }
  }

  async function remove() {
    const ok = await confirm({
      title: `Supprimer le chapitre ${chapter.number} ?`,
      message: "Le chapitre et toutes ses pages seront supprimés. Action définitive.",
      confirmLabel: "Supprimer le chapitre",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteChapter(chapter.id);
      router.push(`/projets/${chapter.project_id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
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
          <h2 className="mb-2 flex items-center gap-1.5 font-semibold text-zinc-100">
            Résumé pour la continuité
            <InfoTip help="chapitre_infos.summary" label="Résumé pour la continuité" />
          </h2>
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
              <Alert tone="info">
                {queued} <ProductionLink chapterId={chapter.id} />
              </Alert>
            </div>
          )}
          {rewritten && (
            <div className="mt-3">
              <Alert tone="info">
                <span data-testid="rewrite-prompts-result">{rewritten}</span>
              </Alert>
            </div>
          )}
          {chapter.panel_count > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button variant="secondary" onClick={rewritePrompts} disabled={rewriting} data-testid="rewrite-prompts">
                {rewriting ? "Comptage…" : "Réécrire les prompts du chapitre"}
              </Button>
              <InfoTip help="chapitre_infos.rewrite_prompts" label="Réécrire les prompts du chapitre" />
            </div>
          )}
          {chapter.panel_count > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              <ButtonLink href={`/chapitres/${chapter.id}/atelier`}>Ouvrir l&apos;atelier</ButtonLink>
              <ButtonLink variant="secondary" href={`/chapitres/${chapter.id}/lettrage`} data-testid="open-lettering">
                Lettrage et export
              </ButtonLink>
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
