"use client";

import { useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { useQueue } from "@/components/queue";
import { useToast } from "@/components/toast";
import { DetectionLegend, QCBadge } from "@/components/qc";
import { Alert, Button, ProgressBar } from "@/components/ui";
import { api, fullErrorMessage, type Job, type PageData, type QCStatus } from "@/lib/api";
import { isFinished, useJob } from "@/lib/jobs";
import { QC_LAYERS, needsReview } from "@/lib/qc";

export interface QCCounts {
  ok: number;
  review: number;
  reject: number;
  unchecked: number;
}

/** Compteurs du chapitre d'après le verdict de la version choisie de chaque case. */
export function qcCounts(pages: PageData[]): QCCounts {
  const out: QCCounts = { ok: 0, review: 0, reject: 0, unchecked: 0 };
  for (const p of pages) {
    for (const panel of p.panels) {
      if (panel.selected_image_id === null) continue;
      if (panel.qc_verdict) out[panel.qc_verdict] += 1;
      else out.unchecked += 1;
    }
  }
  return out;
}

function Toggle({ pressed, onClick, children, testId }: { pressed: boolean; onClick: () => void; children: React.ReactNode; testId?: string }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      data-testid={testId}
      className={`inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-medium ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-rose-400 ${
        pressed ? "bg-rose-500/15 text-rose-200 ring-rose-500/50" : "text-zinc-300 ring-zinc-700 hover:bg-zinc-800"
      }`}
    >
      <span
        aria-hidden
        className={`inline-block h-3.5 w-6 rounded-full p-0.5 transition-colors ${pressed ? "bg-rose-500" : "bg-zinc-700"}`}
      >
        <span className={`block h-2.5 w-2.5 rounded-full bg-white transition-transform ${pressed ? "translate-x-2.5" : ""}`} />
      </span>
      {children}
    </button>
  );
}

/** Contrôle qualité du chapitre : compteur, filtre « à revoir », boîtes, lancement du QC. */
export function QCToolbar({
  chapterId,
  pages,
  status,
  onlyReview,
  onOnlyReview,
  showBoxes,
  onShowBoxes,
  onOpenPanel,
  onChanged,
}: {
  chapterId: number;
  pages: PageData[];
  status: QCStatus | null;
  onlyReview: boolean;
  onOnlyReview: (value: boolean) => void;
  showBoxes: boolean;
  onShowBoxes: (value: boolean) => void;
  onOpenPanel: (pageId: number, panelId: number) => void;
  onChanged: () => void;
}) {
  const { refresh } = useQueue();
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const toast = useToast();
  const live = useJob(job, (done) => {
    onChanged();
    if (done.status === "failed") setError(done.error ?? "Contrôle qualité en échec");
    else if (done.status === "succeeded") setNotice(`Contrôle du chapitre terminé : ${done.message}.`);
  });

  const counts = qcCounts(pages);
  const flagged = pages.flatMap((p) => p.panels.filter(needsReview).map((panel) => ({ page: p, panel })));
  const running = live && !isFinished(live) ? live : null;
  const missingLayers = status ? QC_LAYERS.filter((l) => !status.layers[l.id]?.available) : [];

  async function start(force: boolean) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.runChapterQC(chapterId, { force });
      refresh();
      if (res.job) {
        setJob(res.job);
        const n = res.panel_ids.length;
        toast(`Contrôle qualité lancé (${n} case${n > 1 ? "s" : ""} en file)`);
        setNotice(`${n} case${n > 1 ? "s" : ""} à contrôler : le contrôle passe après les générations en file.`);
      } else {
        setNotice(
          force
            ? "Aucune case avec une version choisie à contrôler."
            : "Toutes les cases générées sont déjà contrôlées (« Tout recontrôler » pour relancer).",
        );
      }
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="qc-title" className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3" data-testid="qc-toolbar">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="flex items-center gap-1.5">
          <h2 id="qc-title" className="text-sm font-semibold text-zinc-200">
            Contrôle qualité
          </h2>
          <InfoTip help="atelier.qc" label="Contrôle qualité" />
        </span>
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-400" data-testid="qc-counter" aria-label={`Chapitre : ${counts.ok} ok, ${counts.review} à revoir, ${counts.reject} rejet, ${counts.unchecked} non contrôlées`}>
          <QCBadge verdict="ok" soft /> <span className="tabular-nums text-zinc-200">{counts.ok}</span>
          <QCBadge verdict="review" soft className="ml-2" /> <span className="tabular-nums text-zinc-200">{counts.review}</span>
          <QCBadge verdict="reject" soft className="ml-2" /> <span className="tabular-nums text-zinc-200">{counts.reject}</span>
          <span className="ml-2">non contrôlées</span> <span className="tabular-nums text-zinc-200">{counts.unchecked}</span>
        </p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Toggle pressed={onlyReview} onClick={() => onOnlyReview(!onlyReview)} testId="qc-filter">
            Seulement les cases à revoir{flagged.length ? ` (${flagged.length})` : ""}
          </Toggle>
          <Toggle pressed={showBoxes} onClick={() => onShowBoxes(!showBoxes)} testId="qc-boxes-toggle">
            Boîtes détectées
          </Toggle>
          <Button
            variant="secondary"
            className="!py-1.5 text-xs"
            onClick={() => start(false)}
            disabled={busy || running !== null || (status !== null && !status.available)}
            data-testid="qc-chapter"
            title={status && !status.available ? (status.detail ?? undefined) : "Contrôle les cases générées pas encore contrôlées"}
          >
            Contrôler le chapitre
          </Button>
          <Button
            variant="ghost"
            className="!px-2 !py-1.5 text-xs"
            onClick={() => start(true)}
            disabled={busy || running !== null || (status !== null && !status.available)}
          >
            Tout recontrôler
          </Button>
          <InfoTip help="atelier.qc_chapter" label="Contrôler le chapitre" />
        </div>
      </div>

      {showBoxes && <DetectionLegend />}

      {status && !status.available && (
        <Alert>Contrôle qualité indisponible : {status.detail}</Alert>
      )}
      {status && status.available && missingLayers.length > 0 && (
        <Alert tone="info">
          {missingLayers.map((l) => (
            <span key={l.id} className="block" data-testid={`qc-layer-missing-${l.id}`}>
              <strong className="font-semibold">{l.label} : couche indisponible</strong> — {status.layers[l.id].detail}. Le QC
              continue avec les autres couches.
            </span>
          ))}
        </Alert>
      )}

      {running && (
        <div className="space-y-1" aria-live="polite">
          <p className="text-xs text-zinc-300">
            {running.status === "pending" ? "Contrôle du chapitre en file (après les générations)…" : `${running.message || "Contrôle…"} · ${running.progress} %`}
          </p>
          <ProgressBar value={running.progress} label="Progression du contrôle qualité du chapitre" />
        </div>
      )}
      {error && <Alert>{error}</Alert>}
      {notice && !error && !running && <Alert tone="info">{notice}</Alert>}

      {onlyReview && (
        <div data-testid="qc-review-list">
          {flagged.length === 0 ? (
            <p className="text-xs text-zinc-500">Aucune case à revoir dans ce chapitre.</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5" aria-label="Cases à revoir">
              {flagged.map(({ page, panel }) => (
                <li key={panel.id}>
                  <button
                    type="button"
                    onClick={() => onOpenPanel(page.id, panel.id)}
                    className="inline-flex items-center gap-1.5 rounded-md bg-zinc-800 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-rose-400"
                    title={panel.qc_reasons.join(" · ")}
                  >
                    p. {page.number} · case {panel.index + 1}
                    <QCBadge verdict={panel.qc_verdict} score={panel.qc_score} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
