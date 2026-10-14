"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useConfirm } from "@/components/confirm";
import { CoverComposition } from "@/components/cover-composition";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Field, Input, Loading, PageHeader, ProgressBar, Select, Textarea } from "@/components/ui";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type CoverFormat,
  type CoverStudio,
  type CoverVersion,
  type Job,
} from "@/lib/api";
import { formatSummary, previewSize, rectStyle, safetyRect, trimRect } from "@/lib/cover";
import { generationStep } from "@/lib/generation";
import { useEngineData, useUnsavedWarning } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";

export default function CoverPage() {
  const id = Number(useParams<{ id: string }>().id);
  const studio = useEngineData(() => api.coverStudio(id), [id]);
  const projectId = studio.data?.volume.project_id ?? null;
  const project = useEngineData(() => (projectId ? api.getProject(projectId) : Promise.resolve(null)), [projectId]);

  if (studio.loading && !studio.data) return <Loading />;
  if (studio.error || !studio.data) return <Alert>{studio.error ?? "Tome introuvable"}</Alert>;
  const v = studio.data.volume;
  return (
    <>
      <PageHeader
        title={`Couverture — tome ${v.number}${v.title ? ` · ${v.title}` : ""}`}
        subtitle={
          <Link href={`/projets/${v.project_id}`} className="hover:text-zinc-200">
            ← {project.data?.title ?? "La série"}
          </Link>
        }
      />
      <CoverEditor key={v.id} data={studio.data} onData={studio.setData} reload={studio.reload} />
      <div className="mt-8">
        <CoverComposition volumeId={v.id} refreshKey={`${v.selected_cover_id ?? 0}-${v.cover_count}`} />
      </div>
    </>
  );
}

function CoverEditor({ data, onData, reload }: { data: CoverStudio; onData: (d: CoverStudio) => void; reload: () => void }) {
  const v = data.volume;
  const [intent, setIntent] = useState(v.cover_intent);
  const [prompt, setPrompt] = useState(v.cover_prompt);
  const [seed, setSeed] = useState("");
  const [busy, setBusy] = useState<null | "prompt" | "generate" | "save">(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [launched, setLaunched] = useState<Job[]>([]);
  const [finished, setFinished] = useState<Set<number>>(() => new Set());
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [zones, setZones] = useState(true);
  const toast = useToast();
  const confirm = useConfirm();

  // Prompt rédigé ou retouché ailleurs (IA, autre onglet) : repris tant qu'il n'est pas en cours d'édition.
  const [savedPrompt, setSavedPrompt] = useState(v.cover_prompt);
  if (v.cover_prompt !== savedPrompt) {
    setSavedPrompt(v.cover_prompt);
    setPrompt(v.cover_prompt);
  }
  const dirty = prompt.trim() !== savedPrompt.trim();
  useUnsavedWarning(dirty, "Le prompt de couverture modifié n'est pas enregistré. Quitter la page quand même ?");

  const jobs = useMemo(() => {
    const byId = new Map<number, Job>();
    for (const j of data.active_jobs) byId.set(j.id, j);
    for (const j of launched) byId.set(j.id, j);
    return [...byId.values()].filter((j) => !finished.has(j.id)).sort((a, b) => a.id - b.id);
  }, [data.active_jobs, launched, finished]);

  const fmt = data.format;
  const preview = data.versions.find((x) => x.id === previewId) ?? data.versions.find((x) => x.selected) ?? data.versions[0] ?? null;
  const chosen = new Set(v.cover_character_ids);
  const disabled = Boolean(data.problem);

  async function patch(body: Parameters<typeof api.updateVolume>[1], what: string) {
    setError(null);
    try {
      const volume = await api.updateVolume(v.id, body);
      onData({ ...data, volume });
      reload(); // format changé : géométrie et zones à jour
      toast(what);
    } catch (err) {
      setError(fullErrorMessage(err));
    }
  }

  async function toggleCharacter(charId: number) {
    const ids = chosen.has(charId) ? v.cover_character_ids.filter((x) => x !== charId) : [...v.cover_character_ids, charId];
    await patch({ cover_character_ids: ids }, "Personnages de la couverture enregistrés");
  }

  async function writePrompt() {
    if (dirty) {
      const ok = await confirm({
        title: "Remplacer le prompt ?",
        message: "Ton prompt modifié sera remplacé par celui que l'IA va rédiger.",
        confirmLabel: "Rédiger un nouveau prompt",
      });
      if (!ok) return;
    }
    setBusy("prompt");
    setError(null);
    setNotice(null);
    try {
      const next = await api.writeCoverPrompt(v.id, { intent, character_ids: v.cover_character_ids });
      onData(next);
      toast("Prompt de couverture rédigé par l'IA");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function savePrompt() {
    setBusy("save");
    setError(null);
    try {
      const volume = await api.updateVolume(v.id, { cover_prompt: prompt, cover_intent: intent });
      onData({ ...data, volume });
      toast("Prompt enregistré");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function generate() {
    setBusy("generate");
    setError(null);
    setNotice(null);
    try {
      const job = await api.generateCover(v.id, { prompt, seed: seed.trim() ? seed.trim() : null });
      setLaunched((l) => [...l, job]);
      if (dirty) onData({ ...data, volume: { ...v, cover_prompt: prompt.trim(), cover_prompt_source: "manual" } });
      setNotice("Couverture en file : génération puis agrandissement au DPI du format.");
      toast("Génération de la couverture lancée");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function select(version: CoverVersion) {
    setError(null);
    try {
      onData(await api.selectCover(version.id));
      setPreviewId(version.id);
      toast("Version retenue");
    } catch (err) {
      setError(fullErrorMessage(err));
    }
  }

  async function remove(version: CoverVersion) {
    const ok = await confirm({
      title: "Supprimer cette version ?",
      message: `Version seed ${String(version.seed ?? "—")} : l'image sera supprimée définitivement.`,
      confirmLabel: "Supprimer",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteCover(version.id);
      if (previewId === version.id) setPreviewId(null);
      reload();
    } catch (err) {
      setError(fullErrorMessage(err));
    }
  }

  function onJobFinished(job: Job) {
    setFinished((f) => new Set(f).add(job.id));
    setNotice(null);
    if (job.status === "failed") setError(`Couverture : ${job.error ?? "échec"}`);
    else if (job.status === "succeeded") toast("Nouvelle version de couverture");
    setPreviewId(null);
    reload();
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="space-y-6">
        {data.problem && <Alert>{data.problem}</Alert>}
        {error && <Alert>{error}</Alert>}
        {notice && !error && <Alert tone="info">{notice}</Alert>}
        <Card>
          <h2 className="mb-4 font-semibold text-zinc-100">Format et personnages</h2>
          <div className="space-y-4">
            <Field label="Format de couverture" htmlFor="couverture-format" hint={fmt ? formatSummary(fmt) : undefined}>
              <Select
                id="couverture-format"
                value={v.cover_format}
                onChange={(e) => patch({ cover_format: e.target.value }, "Format enregistré")}
              >
                {data.formats.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                    {f.default ? " (par défaut)" : ""}
                  </option>
                ))}
                {!fmt && <option value={v.cover_format}>{v.cover_format} (inconnu)</option>}
              </Select>
            </Field>
            <fieldset>
              <legend className="mb-2 text-sm font-medium text-zinc-300">
                Personnages ({v.cover_character_ids.length}/{data.max_characters})
              </legend>
              {data.characters.length ? (
                <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Personnages de la série">
                  {data.characters.map((c) => {
                    const on = chosen.has(c.id);
                    const full = !on && v.cover_character_ids.length >= data.max_characters;
                    return (
                      <li key={c.id}>
                        <label
                          className={`flex items-center gap-2 rounded-md border px-2 py-1.5 text-sm ${
                            on ? "border-rose-500/60 bg-rose-500/10 text-zinc-100" : "border-zinc-800 text-zinc-300"
                          } ${full ? "opacity-50" : ""}`}
                        >
                          <input type="checkbox" checked={on} disabled={full} onChange={() => toggleCharacter(c.id)} className="accent-rose-500" />
                          {c.image_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={engineUrl(c.image_url)} alt="" className="h-8 w-8 rounded object-cover" />
                          ) : (
                            <span className="h-8 w-8 rounded bg-zinc-800" aria-hidden />
                          )}
                          <span className="min-w-0 truncate">
                            {c.name}
                            {!c.has_reference && <span className="block text-[10px] text-zinc-500">sans image de référence</span>}
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-sm text-zinc-500">Aucun personnage dans la bibliothèque de la série.</p>
              )}
              <p className="mt-2 text-xs text-zinc-500">
                L&apos;image principale de chaque personnage part en référence ({data.reference_slots} au plus).
              </p>
            </fieldset>
          </div>
        </Card>

        <Card>
          <h2 className="mb-4 font-semibold text-zinc-100">Intention et prompt</h2>
          <div className="space-y-4">
            {data.monochrome_series && (
              <Alert tone="info">Série en noir et blanc : la couverture est toujours générée en couleur.</Alert>
            )}
            <Field label="Intention de l'auteur" htmlFor="couverture-intention" hint="Ex. « Kaito de face, sabre levé, ville en feu derrière »">
              <Textarea
                id="couverture-intention"
                value={intent}
                maxLength={2000}
                onChange={(e) => setIntent(e.target.value)}
                onBlur={() => intent.trim() !== v.cover_intent && patch({ cover_intent: intent }, "Intention enregistrée")}
                className="min-h-20"
              />
            </Field>
            <Button type="button" variant="secondary" onClick={writePrompt} disabled={disabled || busy !== null} data-testid="cover-write-prompt">
              {busy === "prompt" ? "Rédaction par l'IA…" : v.cover_prompt ? "Rédiger un nouveau prompt avec l'IA" : "Rédiger le prompt avec l'IA"}
            </Button>
            <Field
              label="Prompt de couverture"
              htmlFor="couverture-prompt"
              hint={
                v.cover_prompt_source === "ai" && !dirty
                  ? "Rédigé par l'IA — éditable avant génération."
                  : "Éditable : la zone du logo dégagée et « aucun texte » sont toujours ajoutés à l'envoi."
              }
            >
              <Textarea
                id="couverture-prompt"
                value={prompt}
                maxLength={8000}
                onChange={(e) => setPrompt(e.target.value)}
                className="min-h-48 font-mono text-xs"
                placeholder="Rédige le prompt avec l'IA ou écris-le en anglais."
              />
            </Field>
            {v.cover_prompt_notes && <p className="text-xs text-zinc-500">Note de l&apos;IA : {v.cover_prompt_notes}</p>}
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Seed (facultative)" htmlFor="couverture-seed">
                <Input id="couverture-seed" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} className="w-44" placeholder="au hasard" />
              </Field>
              {dirty && (
                <Button type="button" variant="ghost" onClick={savePrompt} disabled={busy !== null}>
                  {busy === "save" ? "Enregistrement…" : "Enregistrer le prompt"}
                </Button>
              )}
              <Button type="button" onClick={generate} disabled={disabled || busy !== null || jobs.length > 0 || !prompt.trim()} data-testid="cover-generate">
                {jobs.length > 0 ? "Génération en cours…" : busy === "generate" ? "Mise en file…" : data.versions.length ? "Régénérer" : "Générer"}
              </Button>
            </div>
            {data.workflow_name && (
              <p className="text-xs text-zinc-500">
                Flux : {data.workflow_name}
                {fmt?.generation_width && ` · généré en ${fmt.generation_width}×${fmt.generation_height}`}
                {fmt && ` · agrandi à ${fmt.full_width_px}×${fmt.full_height_px} px (${fmt.dpi} dpi, fond perdu compris)`}
                {data.upscaler_name && ` par ${data.upscaler_name}`}.
              </p>
            )}
            {jobs.map((job) => (
              <PendingCover key={job.id} job={job} onFinished={onJobFinished} />
            ))}
          </div>
        </Card>

        <Card>
          <h2 className="mb-4 font-semibold text-zinc-100">Versions ({data.versions.length})</h2>
          {data.versions.length ? (
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4" aria-label="Versions de la couverture">
              {data.versions.map((x) => (
                <li
                  key={x.id}
                  className={`overflow-hidden rounded-lg border bg-zinc-950 ${x.selected ? "border-emerald-600/60" : preview?.id === x.id ? "border-rose-500/60" : "border-zinc-800"}`}
                  data-testid="cover-version"
                >
                  <button type="button" onClick={() => setPreviewId(x.id)} className="block w-full" style={{ aspectRatio: `${x.width} / ${x.height}` }} aria-label={`Afficher la version seed ${String(x.seed ?? "—")}`}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={engineUrl(x.url)} alt={`Version seed ${String(x.seed ?? "—")}`} className="h-full w-full object-cover" />
                  </button>
                  <div className="space-y-1 px-2 py-1.5 text-xs text-zinc-400">
                    <p className="truncate" title={`${x.width}×${x.height} px`}>
                      seed {String(x.seed ?? "—")}
                    </p>
                    <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                      {x.selected ? (
                        <span className="rounded bg-emerald-500/15 px-1 py-px text-[10px] text-emerald-300">Retenue</span>
                      ) : (
                        <button type="button" onClick={() => select(x)} className="text-rose-300 hover:text-rose-200">
                          Retenir
                        </button>
                      )}
                      <button type="button" onClick={() => remove(x)} className="text-red-400 hover:text-red-300" aria-label={`Supprimer la version seed ${String(x.seed ?? "—")}`}>
                        Supprimer
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">Aucune version : choisis les personnages, rédige le prompt puis « Générer ».</p>
          )}
        </Card>
      </div>

      <div className="lg:sticky lg:top-6 lg:self-start">
        <Card>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="font-semibold text-zinc-100">Aperçu à l&apos;échelle</h2>
            <label className="flex items-center gap-1.5 text-xs text-zinc-400">
              <input type="checkbox" checked={zones} onChange={(e) => setZones(e.target.checked)} className="accent-rose-500" />
              Zones réservées
            </label>
          </div>
          {fmt ? <CoverPreview format={fmt} version={preview} zones={zones} /> : <p className="text-sm text-zinc-500">Format inconnu.</p>}
          {preview && (
            <p className="mt-2 text-xs text-zinc-500">
              {preview.selected ? "Version retenue" : "Version affichée"} · {preview.width}×{preview.height} px · seed {String(preview.seed ?? "—")}
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

/** Aperçu « à l'échelle » (même échelle mm → px pour tous les formats) avec fond perdu, coupe, sécurité et zones. */
function CoverPreview({ format: fmt, version, zones }: { format: CoverFormat; version: CoverVersion | null; zones: boolean }) {
  const size = previewSize(fmt);
  const trim = trimRect(fmt);
  const safe = safetyRect(fmt);
  return (
    <div className="max-w-full overflow-hidden">
      <div
        className="relative max-w-full bg-zinc-800"
        style={{ width: size.width, aspectRatio: `${fmt.full_width_mm} / ${fmt.full_height_mm}` }}
        data-testid="cover-preview"
      >
        {version ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={engineUrl(version.url)} alt="Aperçu de la couverture" className="absolute inset-0 h-full w-full object-fill" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-xs text-zinc-500">
            Pas encore d&apos;illustration
          </div>
        )}
        {zones && (
          <div className="pointer-events-none absolute inset-0" aria-label="Zones réservées">
            {/* Fond perdu : tout ce qui dépasse du trait de coupe. */}
            <div className="absolute border border-dashed border-red-400/80" style={rectStyle(trim)} title="Trait de coupe" />
            <div className="absolute border border-dotted border-sky-300/70" style={rectStyle(safe)} title="Marge de sécurité" />
            {fmt.zones.map((z) => (
              <div
                key={z.id}
                className={`absolute flex items-start justify-start border ${z.clear ? "border-amber-300 bg-amber-300/20" : "border-emerald-300 bg-emerald-300/15"}`}
                style={rectStyle(z.rel)}
                data-testid={`cover-zone-${z.id}`}
              >
                <span className="m-0.5 rounded bg-zinc-950/80 px-1 text-[10px] leading-tight text-zinc-100">{z.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {zones && (
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-500">
          <li>
            <span className="mr-1 inline-block w-4 border-t border-dashed border-red-400 align-middle" />
            coupe (fond perdu {String(fmt.bleed_mm).replace(".", ",")} mm)
          </li>
          <li>
            <span className="mr-1 inline-block w-4 border-t border-dotted border-sky-300 align-middle" />
            sécurité {String(fmt.safety_mm).replace(".", ",")} mm
          </li>
          <li>
            <span className="mr-1 inline-block h-2 w-3 border border-amber-300 bg-amber-300/20 align-middle" />
            logo (zone dégagée)
          </li>
        </ul>
      )}
    </div>
  );
}

/** Génération en file ou en cours : progression en direct, annulable. */
function PendingCover({ job: initial, onFinished }: { job: Job; onFinished: (job: Job) => void }) {
  const job = useJob(initial, onFinished) ?? initial;
  const [cancelling, setCancelling] = useState(false);

  async function cancel() {
    setCancelling(true);
    try {
      await api.cancelJob(job.id);
    } catch {
      /* déjà terminé : le flux du job le dira */
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-dashed border-zinc-700 bg-zinc-950 p-3" data-testid="cover-pending">
      <div className="flex items-center justify-between gap-2 text-xs text-zinc-400">
        <span>{job.status === "pending" ? "En file…" : (generationStep(job.message) ?? job.message ?? "Génération…")}</span>
        <button type="button" onClick={cancel} disabled={cancelling} className="shrink-0 text-red-400 hover:text-red-300 disabled:opacity-50">
          {cancelling ? "Annulation…" : "Annuler"}
        </button>
      </div>
      <ProgressBar value={job.status === "pending" ? 0 : job.progress} label="Génération de la couverture" />
    </div>
  );
}
