"use client";

import { useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type CameraLoras,
  type Job,
  type LibraryEntry,
  type LibraryKind,
  type ReferenceImage,
  type ReferenceSheet,
  type ReferenceVariant,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { generationStep, MAX_VARIANTS } from "@/lib/generation";
import { useJob } from "@/lib/jobs";
import { LIBRARY_KINDS } from "@/lib/library";
import { useConfirm } from "./confirm";
import { AngleFields, TierRestriction, angleInput, angleLabel, angleWeight, initialAngleForm, type AngleForm } from "./camera-angle";
import { InfoTip } from "./info-tip";
import { Alert, Button, Field, Input, Loading, ProgressBar, Select } from "./ui";

/** `sheet` des variantes de « Nouvel angle » (pas un type de presets/reference_sheets/). */
const ANGLE_SHEET = "nouvel-angle";

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
 * « Créer des références » d'une fiche (personnage, objet, décor, véhicule ou créature) : génère des variantes d'un type de
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
  const camera = useEngineData(() => api.cameraLoras());
  const confirm = useConfirm();
  const [sheetId, setSheetId] = useState("");
  const [count, setCount] = useState(4);
  const [quality, setQuality] = useState(false);
  // Image de départ facultative : une image de référence de la fiche (null : à partir de zéro).
  const [startId, setStartId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
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
  const startImage = entry.reference_images.find((i) => i.id === startId) ?? null;

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
      const newJobs = await api.generateReferences(kind, entry.id, {
        sheet: sheet.id,
        count,
        quality,
        start_image_id: startImage?.id ?? null,
      });
      const from = startImage ? " à partir de l’image de départ" : "";
      enqueued(newJobs, `${plural(newJobs.length, "variante")} « ${sheet.name} »${from} en file : elles apparaissent ci-dessous une à une.`);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** Nouvelle image de départ (photo d'un croquis…) : rangée avec les images de référence de la fiche, puis choisie. */
  async function uploadStart(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const before = new Set(entry.reference_images.map((i) => i.id));
      const updated = await api.uploadLibraryImages(kind, entry.id, [file]);
      onEntryChange(updated);
      const added = updated.reference_images.find((i) => !before.has(i.id));
      if (added) setStartId(added.id);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setUploading(false);
    }
  }

  function onJobFinished(job: Job) {
    setFinished((f) => new Set(f).add(job.id));
    if (job.status === "failed") setError(`Variante ${String(job.params?.variant ?? "")} : ${job.error ?? "échec"}`);
    studio.reload();
    // « Nouvel angle » : la vue attend la validation (« Valider »), comme toute variante.
    if (job.params?.mode === "angle" && job.status === "succeeded" && job.message) setNotice(job.message);
  }

  async function keep(variant: ReferenceVariant, acceptPeople = false) {
    setError(null);
    try {
      onEntryChange(await api.keepReference(variant.id, acceptPeople));
      setNotice(
        variant.sheet === ANGLE_SHEET
          ? "Vue validée : rangée parmi les vues de la fiche, étiquetée par son angle."
          : "Image ajoutée aux références de la fiche (en dernière position : change l’ordre dans « Images de référence »).",
      );
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
    const ok = await confirm({ title: "Supprimer la variante ?", message, confirmLabel: "Supprimer", danger: true });
    if (!ok) return;
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
        À partir de la description visuelle, des mots-clés, du style de la série (packs et LoRA de style) et du LoRA
        de la fiche ; une image de départ est facultative.{" "}
        {kind === "character"
          ? "La référence de style de la série (planche de style) ne sert qu’au trait : elle n’est jointe qu’après une image de départ ou la variante à affiner."
          : kind === "creature"
            ? "Aucun humain ni autre créature ne doit y apparaître : jamais de planche de style, prompt négatif « aucun humain, aucune autre créature » actif (palier Qualité) — il n’interdit ni visage, ni yeux, ni corps."
            : kind === "vehicle"
              ? "Personne ne doit y apparaître, pas même le pilote : jamais de planche de style, prompt négatif « aucune personne, aucun pilote, aucun décor » actif (palier Qualité), et une variante où un visage est détecté ne peut pas servir de référence aux cases sans ton accord."
              : "Personne ne doit y apparaître : jamais de planche de style, prompt négatif « aucune personne » actif (palier Qualité), et une variante où un visage est détecté ne peut pas servir de référence aux cases sans ton accord."}{" "}
        Les variantes non gardées restent dans l&apos;historique : tu peux les garder plus tard ou les supprimer.
      </p>
      {!sheetList.length ? (
        <Alert tone="info">
          Aucun type de fiche pour {kind === "creature" ? "une" : "un"} {info.singular} : ajoute un fichier dans presets/reference_sheets/.
        </Alert>
      ) : (
        <form onSubmit={generate} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
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
          <Button type="submit" disabled={busy || uploading || !sheet} className="sm:mb-[1.375rem]">
            {busy ? "Mise en file…" : `Générer ${plural(count, "variante")}`}
          </Button>
          </div>
          <StartImageField
            images={entry.reference_images}
            selected={startImage}
            onSelect={setStartId}
            onUpload={() => fileInput.current?.click()}
            uploading={uploading}
            full={full}
            maxKept={maxKept}
          />
          <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={uploadStart} data-testid="start-image-upload" />
        </form>
      )}
      {camera.data && (
        <NewAngleSection
          catalog={camera.data}
          images={entry.reference_images}
          full={full}
          maxKept={maxKept}
          onEnqueue={async (body, label) => {
            setError(null);
            setNotice(null);
            try {
              const newJobs = await api.newAngleView(kind, entry.id, body);
              enqueued(newJobs, `Nouvel angle « ${label} » en file : la vue apparaîtra ci-dessous en attente de validation : « Valider » la range parmi les vues de la fiche, étiquetée par son angle.`);
            } catch (err) {
              setError(fullErrorMessage(err));
            }
          }}
        />
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
              onKeep={(acceptPeople) => keep(v, acceptPeople)}
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

/** « Nouvel angle » : une vue de la fiche tournée jusqu'à l'angle choisi (LoRA Multiple-Angles, palier Qualité). */
function NewAngleSection({
  catalog,
  images,
  full,
  maxKept,
  onEnqueue,
}: {
  catalog: CameraLoras;
  images: ReferenceImage[];
  full: boolean;
  maxKept: number;
  onEnqueue: (body: ReturnType<typeof angleInput> & { start_image_id: number | null }, label: string) => Promise<void>;
}) {
  const [form, setForm] = useState<AngleForm>(() => initialAngleForm(catalog));
  const [startId, setStartId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const start = images.find((i) => i.id === startId) ?? images[0] ?? null;
  const problem = catalog.angle_problem;
  const disabled = busy || !start || problem !== null || angleWeight(form) === null || !form.angle;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (disabled || !start) return;
    setBusy(true);
    try {
      await onEnqueue({ ...angleInput(form), start_image_id: start.id }, angleLabel(catalog, form.angle));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-zinc-800 p-4" data-testid="new-angle">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-medium text-zinc-200">
          Nouvel angle
          <InfoTip help="camera.new_angle" label="Nouvel angle" />
        </h3>
        {problem ? (
          <TierRestriction label={problem === catalog.tier_label ? catalog.tier_label : `Indisponible : ${problem}`} />
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-zinc-500">
            Palier {catalog.workflow_tier ?? "Qualité"} (~1 min), quel que soit celui de la série
            <InfoTip help="camera.tier" label="Palier des angles" />
          </span>
        )}
      </div>
      {images.length === 0 ? (
        <p className="text-sm text-zinc-500">Ajoute ou garde d&apos;abord une image : c&apos;est elle qui tourne.</p>
      ) : (
        <>
          <Field label="Vue de départ" htmlFor="angle-start" hint="L'image de la fiche que le modèle fait tourner (la principale par défaut).">
            <Select id="angle-start" value={start?.id ?? ""} onChange={(e) => setStartId(Number(e.target.value))} data-testid="angle-start">
              {images.map((img, i) => (
                <option key={img.id} value={img.id}>
                  Image {i + 1}
                  {i === 0 ? " (principale)" : ""}
                  {img.angle ? ` · ${angleLabel(catalog, img.angle)}` : ""} · {img.original_name}
                </option>
              ))}
            </Select>
          </Field>
          <AngleFields catalog={catalog} form={form} onChange={setForm} disabled={busy || problem !== null} />
          <Button
            type="submit"
            disabled={disabled || full}
            title={full ? `${maxKept} images de référence au plus : supprimes-en une` : undefined}
            data-testid="new-angle-submit"
          >
            {busy ? "Mise en file…" : "Générer la nouvelle vue"}
          </Button>
        </>
      )}
    </form>
  );
}

function sheetHint(sheet: ReferenceSheet): string {
  return `${sheet.description ? `${sheet.description} ` : ""}${sheet.width}×${sheet.height} px. Le sujet vient de la description ou de l’image de départ.`;
}

/** « Image de départ (facultatif) » : une image de référence de la fiche, ou une nouvelle envoyée ici. */
function StartImageField({
  images,
  selected,
  onSelect,
  onUpload,
  uploading,
  full,
  maxKept,
}: {
  images: ReferenceImage[];
  selected: ReferenceImage | null;
  onSelect: (id: number | null) => void;
  onUpload: () => void;
  uploading: boolean;
  full: boolean;
  maxKept: number;
}) {
  return (
    <Field
      label="Image de départ (facultatif)"
      htmlFor="reference-start"
      hint={
        selected
          ? "La fiche garde le sujet, la silhouette et la pose de cette image, redessinés comme la fiche le demande."
          : "Sans image de départ, la fiche est créée à partir de la description seule."
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        {selected && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={engineUrl(selected.url)} alt="Image de départ choisie" className="h-10 w-10 shrink-0 rounded border border-zinc-700 object-cover" />
        )}
        <Select
          id="reference-start"
          className="min-w-0 flex-1"
          value={selected?.id ?? ""}
          onChange={(e) => onSelect(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">Aucune — à partir de la description</option>
          {images.map((img, i) => (
            <option key={img.id} value={img.id}>
              Image {i + 1} · {img.original_name}
            </option>
          ))}
        </Select>
        <Button
          type="button"
          variant="secondary"
          disabled={uploading || full}
          title={full ? `${maxKept} images de référence au plus : supprimes-en une` : "Photo ou scan d’un croquis, par exemple"}
          onClick={onUpload}
        >
          {uploading ? "Envoi…" : "Envoyer une image…"}
        </Button>
      </div>
    </Field>
  );
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
          {refine ? "Affinage" : String(params.sheet_name ?? "Variante")}
          {params.start_image_id !== null && params.start_image_id !== undefined ? " · image de départ" : ""} · {String(params.variant ?? "")}/{String(params.count ?? "")}
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

/** Images envoyées au workflow pour une variante, dans l'ordre (`params.reference_images`). */
function sentImages(v: ReferenceVariant): { kind: string; variant_id?: number }[] {
  const refs = v.params?.reference_images;
  return Array.isArray(refs) ? refs.filter((r): r is { kind: string } => typeof r === "object" && r !== null && typeof (r as { kind?: unknown }).kind === "string") : [];
}

/** La référence de style de la série (planche de style) faisait partie des images envoyées. */
function usedStyleReference(v: ReferenceVariant): boolean {
  return sentImages(v).some((r) => r.kind === "style");
}

const SENT_ROLES: Record<string, string> = {
  start: "Image de départ — sujet",
  variant: "Variante à affiner — sujet",
  style: "Référence de style — trait seulement",
};

/** Images envoyées avec leur rôle ; aucune = fiche créée à partir de la description seule. */
function SentImages({ variant }: { variant: ReferenceVariant }) {
  const refs = sentImages(variant);
  return (
    <div data-testid="variant-inputs">
      <span className="text-zinc-500">Images envoyées : </span>
      {refs.length === 0 ? (
        <span>aucune (à partir de la description)</span>
      ) : (
        <ol className="mt-1 flex flex-wrap gap-1">
          {refs.map((r, i) => (
            <li
              key={`${r.kind}-${i}`}
              data-kind={r.kind}
              className={`rounded px-1.5 py-px ${r.kind === "style" ? "bg-sky-500/15 text-sky-200" : "bg-zinc-800 text-zinc-200"}`}
            >
              {i + 1}. {SENT_ROLES[r.kind] ?? r.kind}
              {r.kind === "variant" && r.variant_id ? ` (n° ${r.variant_id})` : ""}
            </li>
          ))}
        </ol>
      )}
    </div>
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
  /** `acceptPeople` : « Garder quand même » une fiche où un personnage a été détecté. */
  onKeep: (acceptPeople?: boolean) => Promise<void>;
  onRefine: (instruction: string) => Promise<boolean>;
  onDelete: () => Promise<void>;
}) {
  const [refining, setRefining] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  // Fiche d'objet ou de décor où le QC a vu un visage : la garder demande une acceptation explicite.
  const blocked = Boolean(v.people_warning && !v.people_accepted);
  // « Nouvel angle » : une candidate, rangée parmi les vues de la fiche seulement sur « Valider ».
  const angle = v.sheet === ANGLE_SHEET;

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
          {kept && <span className="rounded bg-emerald-500/15 px-1 py-px text-[10px] text-emerald-300">{angle ? "Validée" : "Gardée"}</span>}
          {angle && !kept && (
            <span className="rounded bg-amber-500/15 px-1 py-px text-[10px] text-amber-200" data-testid="variant-pending">
              En attente de validation
            </span>
          )}
          {usedStyleReference(v) && (
            <span className="rounded bg-sky-500/15 px-1 py-px text-[10px] text-sky-200" title="La référence de style de la série a été jointe à cette génération" data-testid="variant-style-reference">
              Référence de style
            </span>
          )}
        </div>
        {v.people_warning && !v.people_accepted && (
          <p
            role="alert"
            className="rounded border border-amber-600/60 bg-amber-950/40 px-2 py-1 text-amber-200"
            data-testid="variant-people-warning"
          >
            ⚠ {v.people_warning}. Elle ne servira pas de référence aux cases tant que tu ne l&apos;as pas acceptée.
          </p>
        )}
        {v.people_warning && v.people_accepted && (
          <p className="text-amber-300/80" data-testid="variant-people-accepted">
            Personnage détecté, accepté à la main.
          </p>
        )}
        {v.instruction && <p className="text-zinc-300">« {v.instruction} »</p>}
        <details>
          <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300">Prompt · seed {String(v.seed ?? "—")}</summary>
          <div className="mt-1 space-y-1.5">
            <SentImages variant={v} />
            <p className="whitespace-pre-wrap text-zinc-400">{v.prompt}</p>
          </div>
        </details>
        <div className="mt-auto flex flex-wrap gap-1.5">
          <Button
            type="button"
            className="px-2 py-1 text-xs"
            disabled={busy || kept || full}
            title={
              kept
                ? "Déjà parmi les références de la fiche"
                : full
                  ? `${maxKept} images de référence au plus : supprimes-en une`
                  : blocked
                    ? `Un personnage a été détecté : mieux vaut régénérer. ${angle ? "Valider" : "Garder"} quand même l'accepte à la main, et elle servira de référence aux cases.`
                    : angle
                      ? "Range cette vue parmi les vues de la fiche, étiquetée par son angle"
                      : undefined
            }
            onClick={() => run(() => onKeep(blocked))}
            data-testid={blocked ? "variant-keep-anyway" : undefined}
          >
            {angle
              ? kept
                ? "Validée ✓"
                : blocked
                  ? "Valider quand même"
                  : "Valider"
              : kept
                ? "Gardée ✓"
                : blocked
                  ? "Garder quand même"
                  : "Garder comme référence"}
          </Button>
          {v.sheet !== ANGLE_SHEET && (
            <Button type="button" variant="secondary" className="px-2 py-1 text-xs" disabled={busy} onClick={() => setRefining((r) => !r)} aria-expanded={refining}>
              Affiner
            </Button>
          )}
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

