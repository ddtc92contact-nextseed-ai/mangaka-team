"use client";

import Link from "next/link";
import { useState } from "react";
import { api, fullErrorMessage, type PageData } from "@/lib/api";
import { formatDuration, median } from "@/lib/generation";
import { Modal } from "./modal";
import { InfoTip } from "./info-tip";
import { useQueue } from "./queue";
import { useToast } from "./toast";
import { Alert, Button } from "./ui";

const BUSY = new Set(["queued", "generating"]);

/** Cases qu'un « générer » de page ou de chapitre mettra en file : sans version choisie, pas déjà en file. */
export function missingPanels(pages: PageData[]) {
  return pages.flatMap((p) => p.panels.filter((pa) => pa.selected_image_id === null && !BUSY.has(pa.state)));
}

interface Plan {
  panels: number;
  pages: number;
  unlaid: number[];
  perPanelS: number | null;
}

/** « Générer tout le chapitre » avec confirmation : nombre de cases et durée estimée. */
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
  const [plan, setPlan] = useState<Plan | null>(null);
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
      const [pages, jobs] = await Promise.all([api.listPages(chapterId), api.chapterJobs(chapterId, "generation")]);
      const missing = missingPanels(pages);
      const missingPages = pages.filter((p) => missingPanels([p]).length > 0);
      const durations = jobs
        .filter((j) => j.status === "succeeded" && j.duration_ms !== null)
        .map((j) => (j.duration_ms as number) / 1000);
      setPlan({
        panels: missing.length,
        pages: missingPages.length,
        unlaid: missingPages.filter((p) => !p.layout).map((p) => p.number),
        perPanelS: median(durations),
      });
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
      const res = await api.generateChapter(chapterId);
      refresh();
      setOpen(false);
      const n = res.panel_ids.length;
      toast(n ? `Génération lancée (${n} en file)` : "Rien à générer", n ? "success" : "info");
      onQueued?.(
        n
          ? `${n} case${n > 1 ? "s" : ""} mise${n > 1 ? "s" : ""} en file pour tout le chapitre.`
          : "Rien à générer : toutes les cases ont déjà une version choisie ou sont en file.",
      );
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const waiting = queue ? (queue.running ? 1 : 0) + queue.pending.length : 0;
  const canConfirm = plan !== null && plan.panels > 0 && plan.unlaid.length === 0 && !busy;

  return (
    <>
      <span className="inline-flex items-center gap-1.5">
        <Button variant={variant} onClick={prepare} data-testid="generate-chapter">
          Générer tout le chapitre
        </Button>
        <InfoTip help="chapitre_infos.generate_all" label="Générer tout le chapitre" />
      </span>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Générer tout le chapitre"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Annuler
            </Button>
            <Button onClick={confirm} disabled={!canConfirm} data-testid="confirm-generate-chapter">
              {busy ? "Mise en file…" : plan && plan.panels > 0 ? `Lancer ${plan.panels} génération${plan.panels > 1 ? "s" : ""}` : "Lancer"}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-zinc-300">
          {loading && <p className="text-zinc-500">Calcul des cases à générer…</p>}
          {error && <Alert>{error}</Alert>}
          {plan && plan.panels === 0 && (
            <p>Toutes les cases ont déjà une version choisie ou sont en file : rien à lancer.</p>
          )}
          {plan && plan.panels > 0 && (
            <>
              <p data-testid="chapter-plan">
                <strong className="text-zinc-50">
                  {plan.panels} case{plan.panels > 1 ? "s" : ""}
                </strong>{" "}
                sans version choisie, sur {plan.pages} page{plan.pages > 1 ? "s" : ""}. Les cases déjà choisies ne sont
                pas touchées.
              </p>
              <p>
                Durée estimée :{" "}
                {plan.perPanelS !== null ? (
                  <strong className="text-zinc-50">≈ {formatDuration(plan.perPanelS * plan.panels)}</strong>
                ) : (
                  <span className="text-zinc-400">inconnue (aucune génération terminée dans ce chapitre pour l&apos;estimer)</span>
                )}
                {plan.perPanelS !== null && (
                  <span className="text-zinc-500"> ({formatDuration(plan.perPanelS)} par case)</span>
                )}
                {waiting > 0 && (
                  <>
                    , après {waiting} génération{waiting > 1 ? "s" : ""} déjà en file
                    {queue?.total_eta_s ? ` (≈ ${formatDuration(queue.total_eta_s)})` : ""}
                  </>
                )}
                .
              </p>
              {plan.unlaid.length > 0 && (
                <Alert>
                  Page{plan.unlaid.length > 1 ? "s" : ""} {plan.unlaid.join(", ")} sans mise en page : calcule-la
                  d&apos;abord dans{" "}
                  <Link href={`/chapitres/${chapterId}/mise-en-page`} className="underline">
                    Mise en page
                  </Link>
                  .
                </Alert>
              )}
            </>
          )}
        </div>
      </Modal>
    </>
  );
}
