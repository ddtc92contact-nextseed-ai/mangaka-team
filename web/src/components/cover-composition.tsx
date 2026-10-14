"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useConfirm } from "@/components/confirm";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Field, Input, ProgressBar, Select, Textarea } from "@/components/ui";
import {
  api,
  compositionPreviewUrl,
  engineUrl,
  fullErrorMessage,
  type CompositionNotice,
  type CompositionPatch,
  type CoverComposition as Composition,
  type CoverPart,
  type ExportOptions,
  type Job,
  type LogoPlacement,
} from "@/lib/api";
import { flatOrderLabel, mmLabel, rectStyle, summaryLength } from "@/lib/cover";
import { generationStep } from "@/lib/generation";
import { useEngineData, useUnsavedWarning } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";

/**
 * Composition de la couverture d'un tome : 1re (logo, tome, auteur), 4e (résumé de l'IA, accroche, petite
 * illustration, gabarit), dos et couverture à plat, export (ZIP 1re / 4e / à plat, PNG + SVG).
 * `refreshKey` : change quand l'illustration de 1re change (aperçus à recharger).
 */
export function CoverComposition({ volumeId, refreshKey }: { volumeId: number; refreshKey: string }) {
  const state = useEngineData(() => api.coverComposition(volumeId), [volumeId, refreshKey]);
  if (!state.data) {
    return state.error ? <Alert>{state.error}</Alert> : <p className="text-sm text-zinc-500">Chargement de la composition…</p>;
  }
  return <Editor data={state.data} onData={state.setData} reload={state.reload} />;
}

function Notices({ items }: { items: CompositionNotice[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1 text-xs text-amber-300" data-testid="composition-warnings">
      {items.map((n) => (
        <li key={`${n.part}-${n.code}`}>⚠ {n.message}</li>
      ))}
    </ul>
  );
}

function Problems({ items }: { items: CompositionNotice[] }) {
  if (!items.length) return null;
  return (
    <div data-testid="composition-problems">
      <Alert>
        {items.length === 1 ? (
          items[0].message
        ) : (
          <ul className="list-inside list-disc">
            {items.map((n) => (
              <li key={`${n.part}-${n.code}`}>{n.message}</li>
            ))}
          </ul>
        )}
      </Alert>
    </div>
  );
}

function Preview({ data, part, width, label }: { data: Composition; part: CoverPart; width: number; label: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  const src = compositionPreviewUrl(data.volume_id, part, data.revision, width * 2);
  return failed === src ? (
    <p className="text-xs text-red-300">Aperçu impossible (voir les problèmes ci-dessus).</p>
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={label}
      onError={() => setFailed(src)}
      className="h-auto max-w-full rounded border border-zinc-800 bg-zinc-900"
      style={{ width }}
      data-testid={`composition-preview-${part}`}
    />
  );
}

function Editor({ data, onData, reload }: { data: Composition; onData: (d: Composition) => void; reload: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<null | string>(null);
  const toast = useToast();

  async function patch(body: CompositionPatch, what?: string) {
    setError(null);
    try {
      onData(await api.updateComposition(data.volume_id, body));
      if (what) toast(what);
      return true;
    } catch (err) {
      setError(fullErrorMessage(err));
      return false;
    }
  }

  const front = data.warnings.filter((w) => w.part === "front");
  const back = data.warnings.filter((w) => w.part === "back");
  const spine = data.warnings.filter((w) => w.part === "spine");

  return (
    <section className="space-y-6" aria-label="Composition de la couverture" data-testid="cover-composition">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">Composition de la couverture</h2>
        <p className="text-sm text-zinc-500">
          Le texte (titre, résumé, auteur, tome) est posé en vectoriel avec les polices et la palette de la série : jamais
          dessiné par le modèle d&apos;image.
        </p>
      </div>
      {data.problem && <Alert>{data.problem}</Alert>}
      {error && <Alert>{error}</Alert>}
      {!data.problem && (
        <>
          <FrontCard data={data} patch={patch} warnings={front} problems={data.problems.filter((p) => p.part === "front")} />
          <BackCard
            data={data}
            onData={onData}
            reload={reload}
            patch={patch}
            warnings={back}
            problems={data.problems.filter((p) => p.part === "back")}
            busy={busy}
            setBusy={setBusy}
            setError={setError}
          />
          <Card>
            <h3 className="mb-3 font-semibold text-zinc-100">Dos et couverture à plat</h3>
            <p className="mb-3 text-sm text-zinc-400" data-testid="composition-spine">
              Dos : {data.spine_mm !== null ? mmLabel(data.spine_mm) : "—"} pour {data.pages} page{data.pages > 1 ? "s" : ""}{" "}
              (épaisseur du papier en preset) · {flatOrderLabel(data.order, data.direction)}.
            </p>
            <Notices items={spine} />
            <div className="mt-3 overflow-x-auto">
              <Preview data={data} part="flat" width={760} label="Aperçu de la couverture à plat" />
            </div>
          </Card>
          <ExportCard data={data} reload={reload} />
        </>
      )}
    </section>
  );
}

// --- 1re de couverture ----------------------------------------------------------------------------------
function FrontCard({
  data,
  patch,
  warnings,
  problems,
}: {
  data: Composition;
  patch: (body: CompositionPatch, what?: string) => Promise<boolean>;
  warnings: CompositionNotice[];
  problems: CompositionNotice[];
}) {
  const logo = data.logo;
  const [seriesAuthor, setSeriesAuthor] = useState(data.series_author);
  const [author, setAuthor] = useState(data.author);
  const [place, setPlace] = useState<LogoPlacement | null>(logo?.placement ?? null);
  const [showZones, setShowZones] = useState(true);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Placement corrigé par le moteur (borné à la marge de sécurité) : repris.
  const serverPlace = logo?.placement ?? null;
  const [lastServer, setLastServer] = useState(serverPlace);
  if (JSON.stringify(serverPlace) !== JSON.stringify(lastServer)) {
    setLastServer(serverPlace);
    setPlace(serverPlace);
  }

  function move(next: LogoPlacement) {
    setPlace(next);
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(() => patch({ logo: next }), 350);
  }
  useEffect(() => () => {
    if (pending.current) clearTimeout(pending.current);
  }, []);

  return (
    <Card>
      <h3 className="mb-4 font-semibold text-zinc-100">1re de couverture</h3>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="space-y-4">
          <Problems items={problems} />
          <Notices items={warnings} />
          {logo?.present && place ? (
            <fieldset className="space-y-3" data-testid="logo-placement">
              <legend className="mb-1 text-sm font-medium text-zinc-300">Logo de la série</legend>
              <label className="block text-xs text-zinc-400">
                Taille ({Math.round(place.scale * 100)} %)
                <input
                  type="range"
                  min={logo.scale_min}
                  max={logo.scale_max}
                  step={0.01}
                  value={place.scale}
                  onChange={(e) => move({ ...place, scale: Number(e.target.value) })}
                  className="block w-full accent-rose-500"
                  aria-label="Taille du logo"
                />
              </label>
              <label className="block text-xs text-zinc-400">
                Position horizontale
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.005}
                  value={place.cx}
                  onChange={(e) => move({ ...place, cx: Number(e.target.value) })}
                  className="block w-full accent-rose-500"
                  aria-label="Position horizontale du logo"
                />
              </label>
              <label className="block text-xs text-zinc-400">
                Position verticale
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.005}
                  value={place.cy}
                  onChange={(e) => move({ ...place, cy: Number(e.target.value) })}
                  className="block w-full accent-rose-500"
                  aria-label="Position verticale du logo"
                />
              </label>
              <p className="text-xs text-zinc-500">Le logo reste toujours dans la marge de sécurité.</p>
              <Button type="button" variant="ghost" onClick={() => patch({ reset_logo: true }, "Logo replacé dans sa zone")}>
                Replacer dans sa zone
              </Button>
            </fieldset>
          ) : (
            <p className="text-sm text-zinc-500">Pas de logo : le titre est composé dans la police par défaut.</p>
          )}
          <Field label="Auteur de la série" htmlFor="couverture-auteur-serie" hint="Imprimé sur la 1re de chaque tome.">
            <Input
              id="couverture-auteur-serie"
              value={seriesAuthor}
              maxLength={200}
              onChange={(e) => setSeriesAuthor(e.target.value)}
              onBlur={() => seriesAuthor.trim() !== data.series_author && patch({ series_author: seriesAuthor }, "Auteur enregistré")}
            />
          </Field>
          <Field label="Auteur de ce tome (facultatif)" htmlFor="couverture-auteur-tome" hint="Remplace celui de la série pour ce tome.">
            <Input
              id="couverture-auteur-tome"
              value={author}
              maxLength={200}
              onChange={(e) => setAuthor(e.target.value)}
              onBlur={() => author.trim() !== data.author && patch({ author }, "Auteur du tome enregistré")}
            />
          </Field>
        </div>
        <div>
          <div className="relative inline-block max-w-full">
            <Preview data={data} part="front" width={300} label="Aperçu de la 1re de couverture composée" />
            {showZones && logo && (
              <div className="pointer-events-none absolute inset-0" aria-hidden>
                <div className="absolute border border-dotted border-sky-300/80" style={rectStyle(logo.safe)} />
                {logo.zone && <div className="absolute border border-amber-300/70" style={rectStyle(logo.zone)} />}
              </div>
            )}
          </div>
          <label className="mt-1 flex items-center gap-1.5 text-xs text-zinc-400">
            <input type="checkbox" checked={showZones} onChange={(e) => setShowZones(e.target.checked)} className="accent-rose-500" />
            Marge de sécurité et zone du logo
          </label>
        </div>
      </div>
    </Card>
  );
}

// --- 4e de couverture -----------------------------------------------------------------------------------
function BackCard({
  data,
  onData,
  reload,
  patch,
  warnings,
  problems,
  busy,
  setBusy,
  setError,
}: {
  data: Composition;
  onData: (d: Composition) => void;
  reload: () => void;
  patch: (body: CompositionPatch, what?: string) => Promise<boolean>;
  warnings: CompositionNotice[];
  problems: CompositionNotice[];
  busy: string | null;
  setBusy: (b: string | null) => void;
  setError: (e: string | null) => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const [summary, setSummary] = useState(data.summary);
  const [tagline, setTagline] = useState(data.tagline);
  const [saved, setSaved] = useState({ summary: data.summary, tagline: data.tagline });
  if (saved.summary !== data.summary || saved.tagline !== data.tagline) {
    setSaved({ summary: data.summary, tagline: data.tagline });
    setSummary(data.summary);
    setTagline(data.tagline);
  }
  const dirty = summary.trim() !== data.summary.trim() || tagline.trim() !== data.tagline.trim();
  useUnsavedWarning(dirty, "Le texte de 4e de couverture modifié n'est pas enregistré. Quitter la page quand même ?");
  const length = summaryLength(summary, data.summary_min, data.summary_max);
  const [source, setSource] = useState<"panel" | "generated">(data.back_image?.source ?? (data.panel_choices.length ? "panel" : "generated"));
  const [prompt, setPrompt] = useState(data.back_prompt);
  const [launched, setLaunched] = useState<Job[]>([]);
  const [finished, setFinished] = useState<Set<number>>(() => new Set());
  const jobs = useMemo(() => {
    const byId = new Map<number, Job>();
    for (const j of data.back_jobs) byId.set(j.id, j);
    for (const j of launched) byId.set(j.id, j);
    return [...byId.values()].filter((j) => !finished.has(j.id));
  }, [data.back_jobs, launched, finished]);

  async function write(rewrite: boolean) {
    if (dirty) {
      const ok = await confirm({
        title: "Remplacer le texte ?",
        message: "Ton texte modifié sera remplacé par celui que l'IA va écrire.",
        confirmLabel: rewrite ? "Réécrire" : "Écrire avec l'IA",
      });
      if (!ok) return;
    }
    setBusy("summary");
    setError(null);
    try {
      onData(await api.writeBackSummary(data.volume_id, { rewrite }));
      toast(rewrite ? "Résumé réécrit par l'IA" : "Résumé écrit par l'IA");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveText() {
    setBusy("save");
    if (await patch({ summary, tagline }, "Texte de 4e enregistré")) setSaved({ summary: summary.trim(), tagline: tagline.trim() });
    setBusy(null);
  }

  async function generate() {
    setBusy("generate");
    setError(null);
    try {
      const job = await api.generateBackIllustration(data.volume_id, { prompt });
      setLaunched((l) => [...l, job]);
      toast("Illustration de 4e en file");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function onJobFinished(job: Job) {
    setFinished((f) => new Set(f).add(job.id));
    if (job.status === "failed") setError(`Illustration de 4e : ${job.error ?? "échec"}`);
    else if (job.status === "succeeded") toast("Nouvelle illustration de 4e");
    reload();
  }

  return (
    <Card>
      <h3 className="mb-4 font-semibold text-zinc-100">4e de couverture</h3>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="space-y-4">
          <Problems items={problems} />
          <Notices items={warnings} />
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={() => write(false)} disabled={busy !== null} data-testid="back-write-summary">
              {busy === "summary" ? "Écriture par l'IA…" : data.summary ? "Écrire un nouveau texte avec l'IA" : "Écrire le résumé avec l'IA"}
            </Button>
            {data.summary && (
              <Button type="button" variant="ghost" onClick={() => write(true)} disabled={busy !== null} data-testid="back-rewrite-summary">
                Réécrire
              </Button>
            )}
          </div>
          <Field label="Phrase d'accroche" htmlFor="quatrieme-accroche" hint={`${tagline.trim().length}/${data.tagline_max} signes`}>
            <Input id="quatrieme-accroche" value={tagline} maxLength={300} onChange={(e) => setTagline(e.target.value)} />
          </Field>
          <div className="space-y-1">
            <Field label="Résumé" htmlFor="quatrieme-resume">
              <Textarea
                id="quatrieme-resume"
                value={summary}
                maxLength={8000}
                onChange={(e) => setSummary(e.target.value)}
                className="min-h-56"
                placeholder="Écris le texte de 4e de couverture, ou fais-le écrire par l'IA (sans révéler la fin du tome)."
              />
            </Field>
            <p className={`text-xs ${length.state === "ok" ? "text-zinc-500" : "text-amber-300"}`} data-testid="back-summary-length">
              {length.label}
              {data.summary_size_pt !== null && !dirty ? ` · composé en ${String(data.summary_size_pt).replace(".", ",")} pt` : ""}
              {data.summary_source === "ai" && !dirty ? " · écrit par l'IA" : ""}
            </p>
          </div>
          {data.summary_notes && !dirty && <p className="text-xs text-zinc-500">Note de l&apos;IA : {data.summary_notes}</p>}
          {dirty && (
            <Button type="button" onClick={saveText} disabled={busy !== null} data-testid="back-save-text">
              {busy === "save" ? "Enregistrement…" : "Enregistrer le texte"}
            </Button>
          )}
          <Field label="Gabarit de la 4e" htmlFor="quatrieme-gabarit">
            <Select id="quatrieme-gabarit" value={data.back_layout ?? ""} onChange={(e) => patch({ back_layout: e.target.value }, "Gabarit enregistré")}>
              {data.back_layouts.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
          </Field>

          <fieldset className="space-y-3">
            <legend className="mb-1 text-sm font-medium text-zinc-300">
              Petite illustration ({data.back_aspect[0]}:{data.back_aspect[1]}, en couleur)
            </legend>
            <div className="flex gap-4 text-sm text-zinc-300">
              <label className="flex items-center gap-1.5">
                <input type="radio" name="quatrieme-source" checked={source === "panel"} onChange={() => setSource("panel")} className="accent-rose-500" />
                Une case du tome
              </label>
              <label className="flex items-center gap-1.5">
                <input type="radio" name="quatrieme-source" checked={source === "generated"} onChange={() => setSource("generated")} className="accent-rose-500" />
                Une nouvelle illustration
              </label>
            </div>
            {source === "panel" ? (
              data.panel_choices.length ? (
                <ul className="grid max-h-80 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4" aria-label="Cases retenues du tome">
                  {data.panel_choices.map((p) => {
                    const on = data.back_image?.source === "panel" && data.back_image.id === p.image_id;
                    return (
                      <li key={p.image_id}>
                        <button
                          type="button"
                          onClick={() => patch({ back_image: { source: "panel", id: p.image_id } }, "Case retenue pour la 4e")}
                          className={`block w-full overflow-hidden rounded border ${on ? "border-emerald-500" : "border-zinc-800 hover:border-zinc-600"}`}
                          aria-pressed={on}
                          aria-label={`Chapitre ${p.chapter_number}, page ${p.page_number}, case ${p.panel_number}`}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={engineUrl(p.url)} alt="" className="aspect-[4/3] w-full object-cover" />
                          <span className="block px-1 py-0.5 text-[10px] text-zinc-400">
                            Ch. {p.chapter_number} · p. {p.page_number} · c. {p.panel_number}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-sm text-zinc-500">Aucune case retenue dans les chapitres du tome pour l&apos;instant.</p>
              )
            ) : (
              <div className="space-y-3">
                <Field label="Scène à illustrer (prompt, en anglais de préférence)" htmlFor="quatrieme-prompt" hint="« Aucun texte » est toujours ajouté à l'envoi.">
                  <Textarea id="quatrieme-prompt" value={prompt} maxLength={8000} onChange={(e) => setPrompt(e.target.value)} className="min-h-24 text-xs" />
                </Field>
                <Button type="button" variant="secondary" onClick={generate} disabled={busy !== null || jobs.length > 0 || !prompt.trim()} data-testid="back-generate">
                  {jobs.length ? "Génération en cours…" : data.back_versions.length ? "Générer une autre version" : "Générer"}
                </Button>
                {jobs.map((job) => (
                  <PendingJob key={job.id} job={job} onFinished={onJobFinished} label="Génération de l'illustration de 4e" />
                ))}
                {data.back_versions.length > 0 && (
                  <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4" aria-label="Illustrations de 4e générées">
                    {data.back_versions.map((x) => (
                      <li key={x.id}>
                        <button
                          type="button"
                          onClick={() => patch({ back_image: { source: "generated", id: x.id } }, "Illustration retenue pour la 4e")}
                          className={`block w-full overflow-hidden rounded border ${x.selected ? "border-emerald-500" : "border-zinc-800 hover:border-zinc-600"}`}
                          aria-pressed={x.selected}
                          aria-label={`Version seed ${String(x.seed ?? "—")}`}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={engineUrl(x.url)} alt="" className="w-full object-cover" style={{ aspectRatio: `${x.width} / ${x.height}` }} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </fieldset>
        </div>
        <div>
          <Preview data={data} part="back" width={300} label="Aperçu de la 4e de couverture composée" />
        </div>
      </div>
    </Card>
  );
}

function PendingJob({ job: initial, onFinished, label }: { job: Job; onFinished: (job: Job) => void; label: string }) {
  const job = useJob(initial, onFinished) ?? initial;
  return (
    <div className="space-y-1 rounded-lg border border-dashed border-zinc-700 bg-zinc-950 p-3" data-testid="back-pending">
      <p className="text-xs text-zinc-400">{job.status === "pending" ? "En file…" : (generationStep(job.message) ?? job.message ?? "Génération…")}</p>
      <ProgressBar value={job.status === "pending" ? 0 : job.progress} label={label} />
    </div>
  );
}

// --- export ------------------------------------------------------------------------------------------------
function ExportCard({ data, reload }: { data: Composition; reload: () => void }) {
  const [options, setOptions] = useState<ExportOptions>({ bleed: true, crop_marks: false });
  const [job, setJob] = useState<Job | null>(data.export_jobs[0] ?? null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const live = useJob(job, (j) => {
    if (j.status === "succeeded") toast("Couverture exportée");
    reload();
  });
  const current = live ?? job;
  const running = current !== null && (current.status === "pending" || current.status === "running");
  const fmt = data.format;
  const blocked = data.problems.length > 0;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setJob(await api.exportCover(data.volume_id, options));
      toast("Export de la couverture lancé");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const warnings = (current?.params?.warnings as CompositionNotice[] | undefined) ?? [];
  return (
    <Card className="space-y-4" data-testid="cover-export">
      <h3 className="font-semibold text-zinc-100">Export</h3>
      <p className="text-sm text-zinc-400">
        1re seule, 4e seule et couverture à plat (4e + dos + 1re), chacune en PNG {fmt ? `${fmt.dpi} DPI` : ""} et en SVG
        (texte vectoriel, polices embarquées), dans un ZIP{fmt ? ` — format ${fmt.name}` : ""}.
      </p>
      <div className="flex flex-wrap gap-4 text-sm text-zinc-300">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={options.bleed} onChange={(e) => setOptions({ ...options, bleed: e.target.checked })} className="h-4 w-4 accent-rose-500" />
          Fond perdu{fmt ? ` (${String(fmt.bleed_mm).replace(".", ",")} mm)` : ""}
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={options.crop_marks} onChange={(e) => setOptions({ ...options, crop_marks: e.target.checked })} className="h-4 w-4 accent-rose-500" />
          Repères de coupe (et de pli du dos)
        </label>
      </div>
      {error && <Alert>{error}</Alert>}
      {blocked && <p className="text-xs text-amber-300">Export impossible tant que les problèmes signalés ci-dessus restent.</p>}
      <Button type="button" onClick={run} disabled={busy || running || blocked} data-testid="cover-export-run">
        {running ? "Export en cours…" : "Exporter la couverture"}
      </Button>
      {current && (
        <div className="space-y-2" data-testid="cover-export-job" data-status={current.status}>
          <ProgressBar value={current.progress} label="Progression de l'export de la couverture" />
          {current.status === "failed" ? <Alert>Export en échec : {current.error ?? "erreur inconnue"}</Alert> : <p className="text-sm text-zinc-400" aria-live="polite">{current.message}</p>}
          {current.status === "succeeded" && (
            <a className="inline-block text-sm font-medium text-rose-300 underline hover:text-rose-200" href={engineUrl(`/cover-exports/${current.id}/file`)} data-testid="cover-export-download">
              Télécharger le ZIP de la couverture
            </a>
          )}
          {current.status === "succeeded" && warnings.length > 0 && (
            <ul className="list-inside list-disc text-xs text-amber-300">
              {warnings.map((w) => (
                <li key={`${w.part}-${w.code}`}>{w.message}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {!current && data.last_export && (
        <p className="text-xs text-zinc-500">
          Dernier export{data.last_export.finished_at ? ` : ${new Date(data.last_export.finished_at).toLocaleString("fr-FR")}` : ""} ·{" "}
          <a className="text-rose-300 underline hover:text-rose-200" href={engineUrl(data.last_export.url)}>
            télécharger le ZIP
          </a>
        </p>
      )}
    </Card>
  );
}
