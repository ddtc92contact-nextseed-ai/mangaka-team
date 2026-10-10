"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  api,
  EngineError,
  engineUrl,
  errorMessage,
  type LibraryEntry,
  type LibraryEntryInput,
  type LibraryKind,
} from "@/lib/api";
import { LIBRARY_KINDS } from "@/lib/library";
import { ImageDropzone } from "./image-dropzone";
import { LoraPicker } from "./lora-picker";
import { Alert, Button, Field, Input, Textarea } from "./ui";

function parseKeywords(raw: string): string[] {
  return raw
    .split(",")
    .map((k) => k.trim())
    .filter(Boolean);
}

/**
 * Création (projectId) ou édition (initial) d'une fiche de la bibliothèque : personnage, objet ou décor.
 * En création, les images déposées sont envoyées juste après l'enregistrement.
 */
export function LibraryEntryForm({
  kind,
  projectId,
  initial,
  onSaved,
}: {
  kind: LibraryKind;
  projectId: number;
  initial?: LibraryEntry;
  /** `uploadError` : la fiche est enregistrée mais les images déposées ont été refusées. */
  onSaved: (entry: LibraryEntry, uploadError?: string) => void;
}) {
  const info = LIBRARY_KINDS[kind];
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.visual_description ?? "");
  const [keywords, setKeywords] = useState((initial?.prompt_keywords ?? []).join(", "));
  // Personnages : autres noms reconnus par le scénario (« le petit dragon »).
  const [aliases, setAliases] = useState((initial?.aliases ?? []).join(", "));
  const [loraName, setLoraName] = useState(initial?.lora_name ?? "");
  const [loraWeight, setLoraWeight] = useState(String(initial?.lora_weight ?? 0.8));
  const [loraTriggers, setLoraTriggers] = useState(initial?.lora_trigger_words ?? "");
  const [pending, setPending] = useState<File[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErrors({});
    setFormError(null);
    const weight = Number(loraWeight.replace(",", "."));
    if (loraWeight.trim() === "" || Number.isNaN(weight)) {
      setErrors({ lora_weight: "nombre attendu" });
      setSaving(false);
      return;
    }
    const body: LibraryEntryInput = {
      name,
      visual_description: description,
      prompt_keywords: parseKeywords(keywords),
      lora_name: loraName.trim() || null,
      lora_weight: weight,
      lora_trigger_words: loraTriggers.trim(),
      ...(kind === "character" ? { aliases: parseKeywords(aliases) } : {}),
    };
    try {
      let saved = initial
        ? await api.updateLibraryEntry(kind, initial.id, body)
        : await api.createLibraryEntry(kind, projectId, body);
      let uploadError: string | undefined;
      if (pending.length) {
        try {
          saved = await api.uploadLibraryImages(kind, saved.id, pending);
          setPending([]);
        } catch (err) {
          // La fiche existe : on y va quand même, en transmettant l'erreur à afficher sur sa page.
          uploadError = describe(err);
        }
      }
      onSaved(saved, uploadError);
    } catch (err) {
      if (err instanceof EngineError) setErrors(err.fieldErrors);
      setFormError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <Field label="Nom" htmlFor="name" error={errors.name}>
        <Input
          id="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={info.namePlaceholder}
          aria-invalid={Boolean(errors.name)}
          maxLength={120}
          required
        />
      </Field>
      {kind === "character" && (
        <Field
          label="Autres noms (alias)"
          htmlFor="aliases"
          error={errors.aliases ?? Object.entries(errors).find(([f]) => f.startsWith("aliases."))?.[1]}
          hint="Séparés par des virgules. Le scénario qui écrit l’un de ces noms (« le petit dragon ») désigne cette fiche : ses références, sa description et son LoRA servent à la case."
        >
          <Input
            id="aliases"
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
            placeholder="le petit dragon, Urus le Bleu"
          />
        </Field>
      )}
      <Field
        label="Description visuelle"
        htmlFor="visual_description"
        error={errors.visual_description}
        hint={info.descriptionHint}
      >
        <Textarea
          id="visual_description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={info.descriptionPlaceholder}
        />
      </Field>
      <Field
        label="Mots-clés de prompt"
        htmlFor="prompt_keywords"
        error={errors.prompt_keywords}
        hint="Séparés par des virgules."
      >
        <Input
          id="prompt_keywords"
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          placeholder={info.keywordsPlaceholder}
        />
      </Field>
      <LoraPicker
        id="lora_name"
        label={info.loraLabel}
        placeholder={info.loraPlaceholder}
        value={loraName}
        onChange={setLoraName}
        savedValue={initial?.lora_name}
        error={errors.lora_name}
        weight={loraWeight}
        onWeightChange={setLoraWeight}
        weightLabel="Poids du LoRA"
        weightError={errors.lora_weight}
        triggerWords={loraTriggers}
        onTriggerWordsChange={setLoraTriggers}
        triggerWordsError={errors.lora_trigger_words}
      />
      {!initial && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-zinc-300">Images de référence</p>
          <ImageDropzone onFiles={(files) => setPending((p) => [...p, ...files])} disabled={saving} />
          <PendingImages files={pending} onRemove={(i) => setPending((p) => p.filter((_, j) => j !== i))} />
        </div>
      )}
      <div className="flex justify-end">
        <Button type="submit" disabled={saving}>
          {saving ? "Enregistrement…" : initial ? "Enregistrer" : info.createLabel}
        </Button>
      </div>
    </form>
  );
}

function describe(err: unknown): string {
  if (err instanceof EngineError && err.fieldErrors.files) return err.fieldErrors.files;
  return errorMessage(err);
}

function PendingImages({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  const urls = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls]);
  if (!files.length) return null;
  return (
    <ul className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
      {files.map((f, i) => (
        <li key={urls[i]} className="group relative overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={urls[i]} alt={f.name} className="aspect-square w-full object-cover" />
          <button
            type="button"
            onClick={() => onRemove(i)}
            className="absolute top-1 right-1 rounded bg-black/70 px-1.5 text-xs text-zinc-200 hover:bg-red-600"
            aria-label={`Retirer ${f.name}`}
          >
            ✕
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Plafond d'images de référence par fiche (le même côté moteur : MAX_KEPT). */
export const MAX_REFERENCE_IMAGES = 8;

/**
 * Galerie des images de référence d'une fiche existante (ajout immédiat, ordre, suppression).
 * La première est la référence principale : c'est elle qui sert quand les emplacements d'une case manquent.
 */
export function ReferenceImages({
  kind,
  entry,
  onChange,
  initialError,
}: {
  kind: LibraryKind;
  entry: LibraryEntry;
  onChange: (entry: LibraryEntry) => void;
  initialError?: string | null;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(initialError ?? null);

  async function upload(files: File[]) {
    setBusy(true);
    setError(null);
    try {
      onChange(await api.uploadLibraryImages(kind, entry.id, files));
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  async function move(index: number, to: number) {
    const ids = entry.reference_images.map((i) => i.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(to, 0, moved);
    setError(null);
    try {
      onChange(await api.reorderLibraryImages(kind, entry.id, ids));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(imageId: number) {
    setError(null);
    try {
      await api.deleteLibraryImage(kind, entry.id, imageId);
      onChange({ ...entry, reference_images: entry.reference_images.filter((i) => i.id !== imageId) });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <p className="text-xs text-zinc-500" data-testid="reference-count">
        {entry.reference_images.length} / {MAX_REFERENCE_IMAGES} images · la première est la référence principale.
      </p>
      <ImageDropzone
        onFiles={upload}
        disabled={busy || entry.reference_images.length >= MAX_REFERENCE_IMAGES}
        label={
          busy
            ? "Envoi en cours…"
            : entry.reference_images.length >= MAX_REFERENCE_IMAGES
              ? `${MAX_REFERENCE_IMAGES} images au plus : supprimes-en une pour en ajouter`
              : undefined
        }
      />
      {entry.reference_images.length > 0 ? (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3" aria-label="Images de référence">
          {entry.reference_images.map((img, index) => (
            <li
              key={img.id}
              className={`relative overflow-hidden rounded-lg border bg-zinc-950 ${index === 0 ? "border-rose-500/60" : "border-zinc-800"}`}
            >
              {index === 0 && (
                <span className="absolute top-1 left-1 rounded bg-rose-500 px-1.5 py-px text-[10px] font-semibold text-white">
                  Principale
                </span>
              )}
              <a href={engineUrl(img.url)} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={engineUrl(img.url)} alt={img.original_name} className="aspect-square w-full object-cover" />
              </a>
              <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-2 py-1.5 text-xs text-zinc-400">
                <span className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => move(index, index - 1)}
                    disabled={index === 0}
                    className="rounded px-1 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-30"
                    aria-label={`Avancer ${img.original_name}`}
                    title={index === 1 ? "En faire la référence principale" : "Avancer"}
                  >
                    ←
                  </button>
                  <button
                    type="button"
                    onClick={() => move(index, index + 1)}
                    disabled={index === entry.reference_images.length - 1}
                    className="rounded px-1 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-30"
                    aria-label={`Reculer ${img.original_name}`}
                    title="Reculer"
                  >
                    →
                  </button>
                </span>
                <span className="whitespace-nowrap tabular-nums" title={img.original_name}>
                  {img.width}×{img.height}
                </span>
                <button
                  type="button"
                  onClick={() => remove(img.id)}
                  className="text-red-400 hover:text-red-300"
                  aria-label={`Supprimer ${img.original_name}`}
                >
                  Supprimer
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-zinc-500">Aucune image de référence pour l&apos;instant.</p>
      )}
    </div>
  );
}
