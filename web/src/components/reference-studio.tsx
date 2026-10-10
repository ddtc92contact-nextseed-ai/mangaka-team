"use client";

import { useMemo, useState, type FormEvent } from "react";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type Job,
  type LibraryEntry,
  type LibraryKind,
  type ReferenceSheet,
  type ReferenceVariant,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { generationStep, MAX_VARIANTS } from "@/lib/generation";
import { useJob } from "@/lib/jobs";
import { LIBRARY_KINDS } from "@/lib/library";
import { Alert, Button, Field, Input, Loading, ProgressBar, Select } from "./ui";

/** Pastille du palier qui a produit la variante (Turbo, Rapide, Qualité). */
function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  const tone =
    tier === "Qualité"
      ? "bg-amber-500/15 text-amber-300"
      : tier === "Turbo"
        ? "bg-sky-500/15 text-sky-300"
        : "bg-zinc-800 text-zinc-300";
  return <span className={`rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide ${tone}`}>{tier}</span>;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n > 1 ? "s" : ""}`;
}

/**
 * « Créer des références » d'une fiche (personnage, objet ou décor) : génère des variantes d'un type de
 * fiche dans la file ComfyUI, les affiche au fil de l'eau, « Affiner » repart d'une variante, « Garder
 * comme référence » l'ajoute aux images de référence de la fiche. Les variantes restent dans l'historique.
 */
export function ReferenceStudio({
  kind,
  entry,
  onEntryChange,
}: {
  kind: LibraryKind;
  entry: LibraryEntry;
  onEntryChange: (entry: LibraryEntry) => void;
}) {
  const info = LIBRARY_KINDS[kind];
  const sheets = useEngineData(() => api.referenceSheets(kind), [kind]);
  const studio = useEngineData(() => api.referenceStudio(kind, entry.id), [kind, entry.id]);
  const [sheetId, setSheetId] = useState("");
  const [count, setCount] = useState(4);
  const [quality, setQuality] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Jobs mis en file depuis cet écran ; ceux déjà en cours au chargement viennent du moteur.
  const [launched, setLaunched] = useState<Job[]>([]);
  const [finished, setFinished] = useState<Set<number>>(() => new Set());

  const sheetList = useMemo(() => sheets.data ?? [], [sheets.data]);
  const sheet = sheetList.find((s) => s.id === sheetId) ?? sheetList[0] ?? null;
  const sheetsById = useMemo(() => new Map(sheetList.map((s) => [s.id, s])), [sheetList]);

  const jobs = useMemo(() => {
    const byId = new Map<number, Job>();
    for (const j of studio.data?.active_jobs ?? []) byId.set(j.id, j);
    for (const j of launched) byId.set(j.id, j);
    return [...byId.values()].filter((j) => !finished.has(j.id)).sort((a, b) => a.id - b.id);
  }, [studio.data, launched, finished]);

  const maxKept = studio.data?.max_kept ?? 8;
  const keptIds = new Set(entry.reference_images.map((i) => i.id));
  const full = entry.reference_images.length >= maxKept;

  function enqueued(newJobs: Job[], message: string) {
    setLaunched((l) => [...l, ...newJobs]);
    setNotice(message);
  }

  async function generate(e: FormEvent) {
    e.preventDefault();
    if (!sheet) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const newJobs = await api.generateReferences(kind, entry.id, { sheet: sheet.id, count, quality });
      enqueued(newJobs, `${plural(newJobs.length, "variante")} « ${sheet.name} » en file : elles apparaissent ci-dessous une à une.`);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function onJobFinished(job: Job) {
    setFinished((f) => new Set(f).add(job.id));
    if (job.status === "failed") setError(`Variante ${String(job.params?.variant ?? "")} : ${job.error ?? "échec"}`);
    studio.reload();
  }

  async function keep(variant: ReferenceVariant) {
    setError(null);
    try {
      onEntryChange(await api.keepReference(variant.id));
      setNotice("Image ajoutée aux références de la fiche (en dernière position : change l’ordre dans « Images de référence »).");
      studio.reload();
    } catch (err) {
      setError(fullErrorMessage(err));
    }
  }

  async function refine(variant: ReferenceVariant, instruction: string) {
    setError(null);
    try {
      const newJobs = await api.refineReference(variant.id, { instruction, count, quality });
      enqueued(newJobs, `${plural(newJobs.length, "variante")} affinée${newJobs.length > 1 ? "s" : ""} en file à partir de la variante n° ${variant.id}.`);
      return true;
    } catch (err) {
      setError(fullErrorMessage(err));
      return false;
    }
  }

  async function remove(variant: ReferenceVariant) {
    const message = keptIds.has(variant.kept_image_id ?? -1)
      ? "Retirer cette variante de l'historique ? L'image gardée comme référence reste sur la fiche."
      : "Supprimer cette variante de l'historique ?";
    if (!window.confirm(message)) return;
    setError(null);
    try {
      await api.deleteReferenceVariant(variant.id);
      studio.setData((s) => (s ? { ...s, variants: s.variants.filter((v) => v.id !== variant.id) } : s));
    } catch (err) {
      setError(fullErrorMessage(err));
    }
  }

  if (sheets.loading || studio.loading) return <Loading />;
  if (sheets.error || studio.error) return <Alert>{sheets.error ?? studio.error}</Alert>;

  const variants = studio.data?.variants ?? [];
  return (
    <div className="space-y-5">
      <p className="text-sm text-zinc-500">
        À partir de la description visuelle, des mots-clés, du LoRA de style de la série et du LoRA de la fiche. Les
        variantes non gardées restent dans l&apos;historique : tu peux les garder plus tard ou les supprimer.
      </p>
      {!sheetList.length ? (
        <Alert tone="info">
          Aucun type de fiche pour un {info.singular} : ajoute un fichier dans presets/reference_sheets/.
        </Alert>
      ) : (
        <form onSubmit={generate} className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
          <Field label="Type de fiche" htmlFor="reference-sheet" hint={sheet ? sheetHint(sheet) : undefined}>
            <Select id="reference-sheet" value={sheet?.id ?? ""} onChange={(e) => setSheetId(e.target.value)}>
              {sheetList.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Variantes" htmlFor="reference-count">
            <Select id="reference-count" value={count} onChange={(e) => setCount(Number(e.target.value))}>
              {Array.from({ length: MAX_VARIANTS }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Palier" htmlFor="reference-tier">
            <Select id="reference-tier" value={quality ? "quality" : "series"} onChange={(e) => setQuality(e.target.value === "quality")}>
              <option value="series">Celui de la série</option>
              <option value="quality">Qualité (plus lent)</option>
            </Select>
          </Field>
          <Button type="submit" disabled={busy || !sheet} className="sm:mb-[1.375rem]">
            {busy ? "Mise en file…" : `Générer ${plural(count, "variante")}`}
          </Button>
        </form>
      )}
      {error && <Alert>{error}</Alert>}
      {notice && !error && <Alert tone="info">{notice}</Alert>}

      {(jobs.length > 0 || variants.length > 0) && (
        <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4" aria-label="Variantes">
          {jobs.map((job) => (
            <PendingVariant key={job.id} job={job} sheet={sheetsById.get(String(job.params?.sheet))} onFinished={onJobFinished} />
          ))}
          {variants.map((v) => (
            <VariantCard
              key={v.id}
              variant={v}
              kept={v.kept_image_id !== null && keptIds.has(v.kept_image_id)}
              full={full}
              maxKept={maxKept}
              onKeep={() => keep(v)}
              onRefine={(instruction) => refine(v, instruction)}
              onDelete={() => remove(v)}
            />
          ))}
        </ul>
      )}
      {variants.length > 0 && (
        <p className="text-xs text-zinc-500">
          Historique : {plural(variants.length, "variante")}, dont {variants.filter((v) => v.kept_image_id !== null && keptIds.has(v.kept_image_id)).length} gardée(s).
        </p>
      )}
    </div>
  );
}

function sheetHint(sheet: ReferenceSheet): string {
  return `${sheet.description ? `${sheet.description} ` : ""}${sheet.width}×${sheet.height} px.`;
}

/** Variante en file ou en cours de génération : progression en direct, annulable. */
function PendingVariant({
  job: initial,
  sheet,
  onFinished,
}: {
  job: Job;
  sheet: ReferenceSheet | undefined;
  onFinished: (job: Job) => void;
}) {
  const job = useJob(initial, onFinished) ?? initial;
  const [cancelling, setCancelling] = useState(false);
  const params = job.params ?? {};
  const ratio = sheet ? `${sheet.width} / ${sheet.height}` : "1 / 1";
  const refine = params.parent_id !== null && params.parent_id !== undefined;

  async function cancel() {
    setCancelling(true);
    try {
      await api.cancelJob(job.id);
    } catch {
      /* déjà terminé : le flux du job le dira */
    }
  }

  return (
    <li className="overflow-hidden rounded-lg border border-dashed border-zinc-700 bg-zinc-950" data-testid="pending-variant">
      <div className="flex flex-col items-center justify-center gap-2 bg-zinc-900/60 p-3 text-center" style={{ aspectRatio: ratio }}>
        <p className="text-xs text-zinc-400">
          {job.status === "pending" ? "En file…" : (generationStep(job.message) ?? job.message ?? "Génération…")}
        </p>
        <ProgressBar value={job.status === "pending" ? 0 : job.progress} label={`Variante ${String(params.variant ?? "")}`} />
      </div>
      <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-zinc-400">
        <span className="truncate">
          {refine ? "Affinage" : String(params.sheet_name ?? "Variante")} · {String(params.variant ?? "")}/{String(params.count ?? "")}
        </span>
        <button
          type="button"
          onClick={cancel}
          disabled={cancelling}
          className="shrink-0 text-red-400 hover:text-red-300 disabled:opacity-50"
        >
          {cancelling ? "Annulation…" : "Annuler"}
        </button>
      </div>
    </li>
  );
}

function VariantCard({
  variant: v,
  kept,
  full,
  maxKept,
  onKeep,
  onRefine,
  onDelete,
}: {
  variant: ReferenceVariant;
  kept: boolean;
  full: boolean;
  maxKept: number;
  onKeep: () => Promise<void>;
  onRefine: (instruction: string) => Promise<boolean>;
  onDelete: () => Promise<void>;
}) {
  const [refining, setRefining] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  async function submitRefine(e: FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    await run(async () => {
      if (await onRefine(instruction.trim())) {
        setInstruction("");
        setRefining(false);
      }
    });
  }

  return (
    <li
      className={`flex flex-col overflow-hidden rounded-lg border bg-zinc-950 ${kept ? "border-emerald-600/60" : "border-zinc-800"}`}
      data-testid="reference-variant"
    >
      <a href={engineUrl(v.url)} target="_blank" rel="noreferrer" className="block bg-zinc-900" style={{ aspectRatio: `${v.width} / ${v.height}` }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={engineUrl(v.url)} alt={`${v.sheet_name}, variante n° ${v.id}`} className="h-full w-full object-contain" />
      </a>
      <div className="flex flex-1 flex-col gap-2 p-2 text-xs text-zinc-400">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium text-zinc-200">{v.sheet_name}</span>
          <TierBadge tier={v.tier} />
          {v.parent_id !== null && (
            <span className="rounded bg-violet-500/15 px-1 py-px text-[10px] text-violet-200" title={`Affinée depuis la variante n° ${v.parent_id}`}>
              Affinée
            </span>
          )}
          {kept && <span className="rounded bg-emerald-500/15 px-1 py-px text-[10px] text-emerald-300">Gardée</span>}
        </div>
        {v.instruction && <p className="text-zinc-300">« {v.instruction} »</p>}
        <details>
          <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300">Prompt · seed {String(v.seed ?? "—")}</summary>
          <p className="mt-1 whitespace-pre-wrap text-zinc-400">{v.prompt}</p>
        </details>
        <div className="mt-auto flex flex-wrap gap-1.5">
          <Button
            type="button"
            className="px-2 py-1 text-xs"
            disabled={busy || kept || full}
            title={kept ? "Déjà parmi les références de la fiche" : full ? `${maxKept} images de référence au plus : supprimes-en une` : undefined}
            onClick={() => run(onKeep)}
          >
            {kept ? "Gardée ✓" : "Garder comme référence"}
          </Button>
          <Button type="button" variant="secondary" className="px-2 py-1 text-xs" disabled={busy} onClick={() => setRefining((r) => !r)} aria-expanded={refining}>
            Affiner
          </Button>
          <Button type="button" variant="ghost" className="px-2 py-1 text-xs" disabled={busy} onClick={() => run(onDelete)}>
            Supprimer
          </Button>
        </div>
        {refining && (
          <form onSubmit={submitRefine} className="space-y-1.5">
            <label htmlFor={`refine-${v.id}`} className="block text-zinc-300">
              Ce qu&apos;il faut changer
            </label>
            <Input
              id={`refine-${v.id}`}
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="cheveux plus courts"
              maxLength={500}
              autoFocus
            />
            <Button type="submit" variant="secondary" className="w-full px-2 py-1 text-xs" disabled={busy || !instruction.trim()}>
              Affiner à partir de cette image
            </Button>
          </form>
        )}
      </div>
    </li>
  );
}

