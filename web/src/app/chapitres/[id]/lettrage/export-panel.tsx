"use client";

import { useState } from "react";
import { Alert, Button, Card, ProgressBar } from "@/components/ui";
import { api, engineUrl, exportFileUrl, fullErrorMessage, type ExportOptions, type Job, type PageRender } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";

function Check({
  id,
  label,
  checked,
  onChange,
  hint,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label htmlFor={id} className="flex items-start gap-2 text-sm text-zinc-300">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 accent-rose-500"
      />
      <span>
        {label}
        {hint && <span className="block text-xs text-zinc-500">{hint}</span>}
      </span>
    </label>
  );
}

/** Options d'export (fond perdu, repères), rendu de la page courante et export du chapitre en ZIP. */
export function ExportPanel({ chapterId, pageId, bleedMm }: { chapterId: number; pageId: number; bleedMm: number }) {
  const [options, setOptions] = useState<ExportOptions>({ bleed: false, crop_marks: false });
  const [render, setRender] = useState<PageRender | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const exports = useEngineData(() => api.chapterJobs(chapterId, "export"), [chapterId]);
  const live = useJob(job, () => exports.reload());
  const lastDone = (exports.data ?? []).find((j) => j.status === "succeeded");
  const running = live && (live.status === "pending" || live.status === "running");

  async function renderPage() {
    setBusy(true);
    setError(null);
    try {
      setRender(await api.renderPage(pageId, options));
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function exportChapter() {
    setBusy(true);
    setError(null);
    try {
      setJob(await api.exportChapter(chapterId, options));
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const shownRender = render && render.page_id === pageId ? render : null;
  const pageWarnings = (live?.params?.warnings as { message: string; page_number?: number }[] | undefined) ?? [];

  return (
    <Card className="space-y-4" data-testid="export-panel">
      <h2 className="font-semibold text-zinc-100">Export</h2>
      <div className="space-y-2">
        <Check
          id="opt-bleed"
          label={`Fond perdu (${bleedMm.toLocaleString("fr-FR")} mm)`}
          hint="L'image déborde du format rogné ; valeur du format de page."
          checked={options.bleed}
          onChange={(bleed) => setOptions({ ...options, bleed })}
        />
        <Check
          id="opt-marks"
          label="Repères de coupe"
          checked={options.crop_marks}
          onChange={(crop_marks) => setOptions({ ...options, crop_marks })}
        />
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={renderPage} disabled={busy} data-testid="render-page">
          Rendre cette page
        </Button>
        <Button onClick={exportChapter} disabled={busy || Boolean(running)} data-testid="export-chapter">
          Exporter le chapitre
        </Button>
      </div>
      {shownRender && (
        <div className="space-y-1 text-sm" data-testid="render-result">
          <p className="text-zinc-400">
            Page {shownRender.page_number} : {shownRender.width} × {shownRender.height} px · {shownRender.dpi} DPI
            {shownRender.bleed ? " · fond perdu" : ""}
            {shownRender.crop_marks ? " · repères" : ""}
          </p>
          <p className="flex gap-3">
            <a className="text-rose-300 underline hover:text-rose-200" href={engineUrl(shownRender.png_url)} download>
              Télécharger le PNG
            </a>
            <a className="text-rose-300 underline hover:text-rose-200" href={engineUrl(shownRender.svg_url)} target="_blank" rel="noreferrer">
              Ouvrir le SVG
            </a>
          </p>
        </div>
      )}
      {live && (
        <div className="space-y-2" data-testid="export-job" data-status={live.status}>
          <ProgressBar value={live.progress} label="Progression de l'export" />
          <p className="text-sm text-zinc-400" aria-live="polite">
            {live.status === "failed" ? `Échec : ${live.error ?? "erreur inconnue"}` : live.message}
          </p>
          {live.status === "succeeded" && (
            <a className="inline-block text-sm font-medium text-rose-300 underline hover:text-rose-200" href={exportFileUrl(live.id)} data-testid="export-download">
              Télécharger le ZIP du chapitre
            </a>
          )}
          {live.status === "succeeded" && pageWarnings.length > 0 && (
            <ul className="list-inside list-disc text-xs text-amber-300">
              {pageWarnings.slice(0, 8).map((w, i) => (
                <li key={i}>
                  {w.page_number ? `Page ${w.page_number} — ` : ""}
                  {w.message}
                </li>
              ))}
              {pageWarnings.length > 8 && <li>… et {pageWarnings.length - 8} autre(s)</li>}
            </ul>
          )}
        </div>
      )}
      {!live && lastDone && (
        <p className="text-xs text-zinc-500">
          Dernier export : {new Date(lastDone.finished_at ?? lastDone.created_at).toLocaleString("fr-FR")} ·{" "}
          <a className="text-rose-300 underline hover:text-rose-200" href={exportFileUrl(lastDone.id)}>
            télécharger le ZIP
          </a>
        </p>
      )}
    </Card>
  );
}
