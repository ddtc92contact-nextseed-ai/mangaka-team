"use client";

import { useState } from "react";
import { AnnotationBar } from "@/components/annotation";
import { useQueue } from "@/components/queue";
import { Alert, Button, Field, Input, Loading, ProgressBar, Select, Textarea } from "@/components/ui";
import {
  api,
  fullErrorMessage,
  type Annotation,
  type GenerateInput,
  type PanelImage,
  type QCStatus,
  type VisionMode,
  type WorkflowPreset,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { MAX_VARIANTS, PANEL_STATE, formatDuration, isValidSeed } from "@/lib/generation";
import { useJob } from "@/lib/jobs";
import type { PanelView } from "./page-canvas";
import { PanelQC } from "./panel-qc";
import { VersionsStrip } from "./versions";

/** Panneau latéral d'une case : contenu, prompt final, réglages de génération, progression, versions. */
export function PanelInspector({
  panelId,
  view,
  presets,
  qcStatus,
  refreshKey,
  onClose,
  onChanged,
  onPrev,
  onNext,
}: {
  panelId: number;
  view: PanelView | null;
  presets: WorkflowPreset[] | null;
  qcStatus: QCStatus | null;
  refreshKey: number;
  onClose: () => void;
  onChanged: () => void;
  /** Case précédente / suivante ayant une version (annotation rapide au clavier). */
  onPrev?: () => void;
  onNext?: () => void;
}) {
  const detail = useEngineData(() => api.getPanel(panelId), [panelId, refreshKey]);
  const { refresh, cancel } = useQueue();
  // Prompt en cours d'édition (null = pas touché), rattaché à la case pour repartir à zéro en changeant de case.
  const [draftState, setDraft] = useState<{ panelId: number; text: string } | null>(null);
  const [seed, setSeed] = useState("");
  const [count, setCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const running = view?.running ?? null;
  const live = useJob(running?.job ?? null);
  const pending = view?.pending ?? [];

  const d = detail.data && detail.data.id === panelId ? detail.data : null;
  const draft = draftState && draftState.panelId === panelId ? draftState.text : null;
  const promptValue = draft ?? d?.final_prompt ?? "";
  const promptDirty = d !== null && draft !== null && draft.trim() !== (d.final_prompt ?? "").trim();
  const chosen = d?.images.find((i) => i.selected) ?? null;
  const seedError = seed.trim() !== "" && !isValidSeed(seed.trim()) ? "Entier de 0 à 9 223 372 036 854 775 807" : undefined;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const generate = (extra: GenerateInput = {}) =>
    run(async () => {
      const body: GenerateInput = { count, ...extra };
      if (extra.seed === undefined && seed.trim() !== "") body.seed = seed.trim();
      if (promptDirty) body.prompt_override = draft;
      const jobs = await api.generatePanel(panelId, body);
      setDraft(null);
      refresh();
      onChanged();
      detail.reload();
      setNotice(
        jobs.length > 1 ? `${jobs.length} variantes mises en file.` : "Génération mise en file.",
      );
    });

  const savePrompt = () =>
    run(async () => {
      detail.setData(await api.updatePanel(panelId, { final_prompt: draft }));
      setDraft(null);
    });
  const rebuild = () =>
    run(async () => {
      detail.setData(await api.rebuildPrompt(panelId));
      setDraft(null);
    });
  const setPreset = (value: string) =>
    run(async () => {
      detail.setData(await api.updatePanel(panelId, { generation_preset: value || null }));
    });

  async function selectImage(img: PanelImage) {
    const images = await api.selectPanelImage(img.id);
    if (d) detail.setData({ ...d, images });
    onChanged();
  }
  async function deleteImage(img: PanelImage) {
    await api.deletePanelImage(img.id);
    detail.reload();
    onChanged();
  }
  const cancelJob = (jobId: number) => run(() => cancel(jobId));

  const runQC = (vision: VisionMode, image?: PanelImage) =>
    run(async () => {
      await api.runPanelQC(panelId, { vision, ...(image ? { image_id: image.id } : {}) });
      refresh();
      onChanged();
      setNotice(vision === "force" ? "Contrôle avec la vision mis en file." : "Contrôle qualité mis en file.");
    });
  const overrideQC = (img: PanelImage) =>
    run(async () => {
      const updated = await api.overrideQC(img.id);
      if (d) detail.setData({ ...d, images: d.images.map((i) => (i.id === updated.id ? updated : i)) });
      onChanged();
      setNotice("Version validée à la main (décision tracée dans le QC).");
    });

  function annotated(imageId: number, annotation: Annotation | null) {
    detail.setData((cur) =>
      cur ? { ...cur, images: cur.images.map((i) => (i.id === imageId ? { ...i, annotation } : i)) } : cur,
    );
  }

  const qcImage = chosen ?? (d?.images.length ? d.images[d.images.length - 1] : null);

  const resolvedName = presets?.find((p) => p.id === d?.resolved_preset)?.name ?? d?.resolved_preset ?? "—";
  const hasImages = (d?.images.length ?? 0) > 0;

  return (
    <section
      aria-labelledby="inspector-title"
      className="rounded-xl border border-zinc-800 bg-zinc-900/80 p-4"
      data-testid="panel-inspector"
    >
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="inspector-title" className="font-semibold text-zinc-50">
            Case {d ? d.index + 1 : "…"}
            {d && <span className="ml-2 text-sm font-normal text-zinc-500">page {d.page_number}</span>}
          </h2>
          {d && (
            <p className="mt-0.5 text-xs text-zinc-400">
              {running
                ? `Génération ${live?.progress ?? running.job.progress} %`
                : pending.length
                  ? "En file"
                  : view?.qc
                    ? "Contrôle qualité…"
                    : (PANEL_STATE[d.state] ?? d.state)}
              {d.target && ` · ${d.target.width} × ${d.target.height} px`}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fermer le panneau (Échap)"
          title="Fermer (Échap)"
          className="rounded-md px-2 py-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-2 focus-visible:outline-rose-400"
        >
          ✕
        </button>
      </header>

      {detail.loading && !d ? (
        <Loading />
      ) : detail.error && !d ? (
        <Alert>Impossible de charger la case : {detail.error}</Alert>
      ) : d ? (
        <div className="space-y-5">
          <div className="space-y-2 text-sm">
            <p className="whitespace-pre-line text-zinc-200">{d.description || <span className="text-zinc-500">Pas de description.</span>}</p>
            <div className="flex flex-wrap gap-1.5 text-xs">
              {d.shot_type && <span className="rounded bg-zinc-800 px-2 py-0.5 text-zinc-300">Plan : {d.shot_type}</span>}
              {d.characters.length ? (
                d.characters.map((c) => (
                  <span key={c} className="rounded bg-violet-500/15 px-2 py-0.5 text-violet-200">
                    {c}
                  </span>
                ))
              ) : (
                <span className="text-zinc-500">Aucun personnage</span>
              )}
            </div>
          </div>

          {(running || pending.length > 0) && (
            <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3" aria-live="polite">
              {running && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-zinc-200">
                      {live?.message || "Génération…"} · {live?.progress ?? running.job.progress} %
                    </span>
                    <Button variant="danger" className="!px-2 !py-0.5 text-xs" onClick={() => cancelJob(running.job.id)} disabled={busy}>
                      Annuler
                    </Button>
                  </div>
                  <ProgressBar key={running.job.id} value={live?.progress ?? running.job.progress} label="Progression de la génération" />
                  {running.eta_s !== null && <p className="text-[11px] text-zinc-500">Fin dans ≈ {formatDuration(running.eta_s)}</p>}
                </div>
              )}
              {pending.map((item) => (
                <div key={item.job.id} className="flex items-center justify-between gap-2 text-xs text-zinc-400">
                  <span>
                    En file (position {item.position})
                    {item.count && item.count > 1 ? ` · variante ${item.variant}/${item.count}` : ""}
                    {item.eta_s !== null && ` · ≈ ${formatDuration(item.eta_s)}`}
                  </span>
                  <Button variant="ghost" className="!px-2 !py-0.5 text-xs" onClick={() => cancelJob(item.job.id)} disabled={busy}>
                    Annuler
                  </Button>
                </div>
              ))}
            </div>
          )}

          {view?.failure && !running && pending.length === 0 && (
            <Alert>
              <strong className="font-semibold">Dernière génération en échec.</strong> {view.failure.error ?? "Erreur inconnue."}
            </Alert>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label htmlFor="final-prompt" className="text-sm font-medium text-zinc-300">
                Prompt final
                {d.final_prompt_manual && !promptDirty && (
                  <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                    édité à la main
                  </span>
                )}
              </label>
              <button
                type="button"
                onClick={rebuild}
                disabled={busy}
                className="text-xs text-zinc-400 underline-offset-2 hover:text-zinc-100 hover:underline focus-visible:outline-2 focus-visible:outline-rose-400 disabled:opacity-50"
              >
                Reconstruire le prompt
              </button>
            </div>
            <Textarea
              id="final-prompt"
              value={promptValue}
              onChange={(e) => setDraft({ panelId, text: e.target.value })}
              rows={6}
              className="text-xs leading-relaxed"
              placeholder="Construit automatiquement (case, personnages, style de la série) à la première génération — ou clique « Reconstruire le prompt » pour le voir et le retoucher."
            />
            {promptDirty && (
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-zinc-500">Modifié : sera utilisé à la prochaine génération.</p>
                <div className="flex gap-1">
                  <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setDraft(null)} disabled={busy}>
                    Annuler
                  </Button>
                  <Button variant="secondary" className="!px-2 !py-1 text-xs" onClick={savePrompt} disabled={busy}>
                    Enregistrer
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <Field label="Workflow" htmlFor="preset">
                <Select id="preset" value={d.generation_preset ?? ""} onChange={(e) => setPreset(e.target.value)} disabled={busy || !presets}>
                  <option value="">Automatique ({resolvedName})</option>
                  {(presets ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.reference_slots ? ` · ${p.reference_slots} réf.` : ""}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field label="Seed" htmlFor="seed" error={seedError} hint="Vide = au hasard">
              <Input
                id="seed"
                inputMode="numeric"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                placeholder="Aléatoire"
                aria-invalid={seedError ? true : undefined}
              />
            </Field>
            <div className="space-y-1.5">
              <span id="variants-label" className="block text-sm font-medium text-zinc-300">
                Variantes
              </span>
              <div role="group" aria-labelledby="variants-label" className="flex gap-1">
                {Array.from({ length: MAX_VARIANTS }, (_, i) => i + 1).map((n) => (
                  <button
                    key={n}
                    type="button"
                    aria-pressed={count === n}
                    onClick={() => setCount(n)}
                    className={`h-9 flex-1 rounded-md text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-rose-400 ${
                      count === n ? "bg-rose-500 text-white" : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {error && <Alert>{error}</Alert>}
          {notice && !error && <Alert tone="info">{notice}</Alert>}

          <div className="flex flex-wrap gap-2">
            <Button onClick={() => generate()} disabled={busy || Boolean(seedError)} data-testid="generate-panel">
              {hasImages ? "Régénérer cette case" : "Générer"}
              {count > 1 ? ` (${count})` : ""}
            </Button>
            <Button
              variant="secondary"
              onClick={() => chosen?.seed != null && generate({ seed: chosen.seed, count: 1 })}
              disabled={busy || chosen?.seed == null}
              title={chosen?.seed != null ? `Relance avec la seed ${chosen.seed} de la version choisie (utile après une retouche du prompt)` : "Choisis d'abord une version"}
            >
              Même seed
            </Button>
          </div>

          {qcImage && <AnnotationBar image={qcImage} onChange={annotated} keyboard onPrev={onPrev} onNext={onNext} />}

          <PanelQC
            image={qcImage}
            job={view?.qc ?? null}
            status={qcStatus}
            busy={busy}
            onRun={(vision) => runQC(vision, qcImage ?? undefined)}
            onOverride={overrideQC}
          />

          <div className="space-y-2">
            <h3 className="text-sm font-medium text-zinc-300">
              Versions <span className="text-zinc-500">({d.images.length})</span>
            </h3>
            <VersionsStrip images={d.images} onSelect={selectImage} onDelete={deleteImage} onAnnotated={annotated} />
          </div>
        </div>
      ) : null}
    </section>
  );
}
