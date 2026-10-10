"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, EngineError, engineUrl, errorMessage, type Character, type CharacterInput } from "@/lib/api";
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
 * Création (projectId) ou édition (initial) d'un personnage.
 * En création, les images déposées sont envoyées juste après l'enregistrement.
 */
export function CharacterForm({
  projectId,
  initial,
  onSaved,
}: {
  projectId: number;
  initial?: Character;
  /** `uploadError` : le personnage est enregistré mais les images déposées ont été refusées. */
  onSaved: (character: Character, uploadError?: string) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.visual_description ?? "");
  const [keywords, setKeywords] = useState((initial?.prompt_keywords ?? []).join(", "));
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
    const body: CharacterInput = {
      name,
      visual_description: description,
      prompt_keywords: parseKeywords(keywords),
      lora_name: loraName.trim() || null,
      lora_weight: weight,
      lora_trigger_words: loraTriggers.trim(),
    };
    try {
      let saved = initial ? await api.updateCharacter(initial.id, body) : await api.createCharacter(projectId, body);
      let uploadError: string | undefined;
      if (pending.length) {
        try {
          saved = await api.uploadReferenceImages(saved.id, pending);
          setPending([]);
        } catch (err) {
          // Le personnage existe : on y va quand même, en transmettant l'erreur à afficher sur sa fiche.
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
          placeholder="Aiko"
          aria-invalid={Boolean(errors.name)}
          maxLength={120}
          required
        />
      </Field>
      <Field
        label="Description visuelle"
        htmlFor="visual_description"
        error={errors.visual_description}
        hint="Ce qui doit rester identique d'une case à l'autre : visage, coiffure, tenue, signes distinctifs."
      >
        <Textarea
          id="visual_description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Jeune femme, cheveux noirs courts, cicatrice sur la joue gauche, kimono rouge"
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
          placeholder="aiko, kimono rouge, katana"
        />
      </Field>
      <LoraPicker
        id="lora_name"
        label="LoRA d'identité (optionnel)"
        placeholder="aiko_v1.safetensors"
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
          {saving ? "Enregistrement…" : initial ? "Enregistrer" : "Créer le personnage"}
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

/** Galerie des images de référence d'un personnage existant (ajout immédiat, suppression). */
export function ReferenceImages({
  character,
  onChange,
  initialError,
}: {
  character: Character;
  onChange: (character: Character) => void;
  initialError?: string | null;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(initialError ?? null);

  async function upload(files: File[]) {
    setBusy(true);
    setError(null);
    try {
      onChange(await api.uploadReferenceImages(character.id, files));
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(imageId: number) {
    setError(null);
    try {
      await api.deleteReferenceImage(character.id, imageId);
      onChange({ ...character, reference_images: character.reference_images.filter((i) => i.id !== imageId) });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <ImageDropzone onFiles={upload} disabled={busy} label={busy ? "Envoi en cours…" : undefined} />
      {character.reference_images.length > 0 ? (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3">
          {character.reference_images.map((img) => (
            <li key={img.id} className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950">
              <a href={engineUrl(img.url)} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={engineUrl(img.url)} alt={img.original_name} className="aspect-square w-full object-cover" />
              </a>
              <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-zinc-400">
                <span className="shrink-0" title={img.original_name}>
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
