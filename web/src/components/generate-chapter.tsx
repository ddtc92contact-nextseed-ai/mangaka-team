"use client";

import { useState } from "react";
import { api, fullErrorMessage, type ChapterProductionPlan, type PageData } from "@/lib/api";
import { formatDuration, median } from "@/lib/generation";
import { Modal } from "./modal";
import { InfoTip } from "./info-tip";
import { useQueue } from "./queue";
import { useToast } from "./toast";
import { Alert, Button } from "./ui";

const BUSY = new Set(["queued", "generating"]);

/** Cases qu'un « générer » de page mettra en file : sans version choisie, pas déjà en file. */
export function missingPanels(pages: PageData[]) {
  return pages.flatMap((p) => p.panels.filter((pa) => pa.selected_image_id === null && !BUSY.has(pa.state)));
}

const plural = (n: number, word: string) => `${n} ${word}${n > 1 && !word.endsWith("s") ? "s" : ""}`;

function pageList(numbers: number[]) {
  return `${numbers.length > 1 ? "Pages" : "Page"} ${numbers.join(", ")}`;
}

/** Message affiché après la mise en file (bandeau de l'écran appelant). */
function queuedMessage(mode: ChapterProductionPlan["mode"], panels: number, cleaned: number, laidOut: number[]) {
  if (!panels && !cleaned) return "Rien à générer : toutes les cases ont déjà une version choisie ou sont en file.";
  const parts = [];
  if (mode === "sketch") {
    if (panels) parts.push(`${plural(panels, "croquis")} en file (à trier ensuite dans Croquis)`);
    if (cleaned) parts.push(`${plural(cleaned, "case")} validée${cleaned > 1 ? "s" : ""} à passer au propre`);
  } else {
    parts.push(`${plural(panels, "case")} mise${panels > 1 ? "s" : ""} en file pour tout le chapitre`);
  }
  const layout = laidOut.length ? ` ${pageList(laidOut)} mise${laidOut.length > 1 ? "s" : ""} en page automatiquement.` : "";
  return `${parts.join(", ")}.${layout}`;
}

/** « Générer le chapitre » avec confirmation : mise en page automatique des pages qui n'en ont pas, puis
 * toutes les cases des pages de l'histoire et bonus (croquis d'abord si le palier croquis est activé). */
export function GenerateChapterButton({
  chapterId,
  onQueued,
  variant = "secondary",
}: {
  chapterId: number;
  onQueued?: (message: string) => void;
  variant?: "primary" | "secondary";
}) {
  const { queue, refresh } = useQueue();
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<ChapterProductionPlan | null>(null);
  const [perPanelS, setPerPanelS] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function prepare() {
    setOpen(true);
    setPlan(null);
    setError(null);
    setLoading(true);
    try {
      const [next, jobs] = await Promise.all([
        api.chapterProductionPlan(chapterId),
        api.chapterJobs(chapterId, "generation"),
      ]);
      const durations = jobs
        .filter((j) => j.status === "succeeded" && j.duration_ms !== null)
        .map((j) => (j.duration_ms as number) / 1000);
      setPlan(next);
      setPerPanelS(median(durations));
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.produceChapter(chapterId);
      refresh();
      setOpen(false);
      const n = res.panel_ids.length + res.cleaned_panel_ids.length;
      toast(n ? `Génération lancée (${n} en file)` : "Rien à générer", n ? "success" : "info");
      onQueued?.(queuedMessage(res.mode, res.panel_ids.length, res.cleaned_panel_ids.length, res.laid_out_pages));
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const waiting = queue ? (queue.running ? 1 : 0) + queue.pending.length : 0;
  const jobs = plan ? plan.panels + plan.to_clean : 0;
  const canConfirm = plan !== null && jobs > 0 && !busy;

  return (
    <>
      <span className="inline-flex items-center gap-1.5">
        <Button variant={variant} onClick={prepare} data-testid="generate-chapter">
          Générer le chapitre
        </Button>
        <InfoTip help="chapitre_infos.generate_all" label="Générer le chapitre" />
      </span>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Générer le chapitre"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Annuler
            </Button>
            <Button onClick={confirm} disabled={!canConfirm} data-testid="confirm-generate-chapter">
              {busy ? "Mise en file…" : jobs > 0 ? `Lancer ${plural(jobs, "génération")}` : "Lancer"}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-zinc-300">
          {loading && <p className="text-zinc-500">Calcul des cases à générer…</p>}
          {error && <Alert>{error}</Alert>}
          {plan && plan.total === 0 && <p>Aucune case dans les pages de l&apos;histoire : découpe d&apos;abord le chapitre.</p>}
          {plan && plan.total > 0 && jobs === 0 && (
            <p>Toutes les cases ont déjà une version choisie ou sont en file : rien à lancer.</p>
          )}
          {plan && jobs > 0 && (
            <>
              <p data-testid="chapter-plan">
                {plan.mode === "sketch" ? (
                  <>
                    Palier croquis activé :{" "}
                    <strong className="text-zinc-50">{plural(plan.panels, "croquis")}</strong> (une composition rapide
                    par case non validée)
                    {plan.to_clean > 0 && (
                      <>
                        {" "}
                        et <strong className="text-zinc-50">{plural(plan.to_clean, "passage")} au propre</strong> des
                        croquis déjà validés
                      </>
                    )}
                    , sur {plural(plan.pages, "page")}. Trie ensuite les croquis dans l&apos;onglet Croquis avant de
                    passer les autres au propre.
                  </>
                ) : (
                  <>
                    <strong className="text-zinc-50">{plural(plan.panels, "case")}</strong> sans version choisie, sur{" "}
                    {plural(plan.pages, "page")}. Les cases déjà choisies ne sont pas touchées.
                  </>
                )}
              </p>
              {plan.unlaid_pages.length > 0 && (
                <Alert tone="info">
                  <span data-testid="chapter-plan-unlaid">
                    {pageList(plan.unlaid_pages)} sans mise en page : elle{plan.unlaid_pages.length > 1 ? "s" : ""}{" "}
                    {plan.unlaid_pages.length > 1 ? "seront mises" : "sera mise"} en page automatiquement (style de la
                    série) juste avant la génération.
                  </span>
                </Alert>
              )}
              <p>
                Durée estimée :{" "}
                {perPanelS !== null ? (
                  <strong className="text-zinc-50">≈ {formatDuration(perPanelS * jobs)}</strong>
                ) : (
                  <span className="text-zinc-400">inconnue (aucune génération terminée dans ce chapitre pour l&apos;estimer)</span>
                )}
                {perPanelS !== null && <span className="text-zinc-500"> ({formatDuration(perPanelS)} par case)</span>}
                {waiting > 0 && (
                  <>
                    , après {plural(waiting, "génération")} déjà en file
                    {queue?.total_eta_s ? ` (≈ ${formatDuration(queue.total_eta_s)})` : ""}
                  </>
                )}
                . Une génération à la fois : suis l&apos;avancement dans Production.
              </p>
            </>
          )}
        </div>
      </Modal>
    </>
  );
}
