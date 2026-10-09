"use client";

import { useState, type FormEvent } from "react";
import { api, EngineError, errorMessage, type Presets, type Project, type ProjectInput } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { SERIES_STATUS } from "./status";
import { Alert, Button, Field, Input, Select, Textarea } from "./ui";

export const DIRECTIONS = {
  rtl: "Droite → gauche (manga)",
  ltr: "Gauche → droite (BD, comics)",
} as const;

/** Rappelle quel workflow du même palier sert aux cases avec images de référence. */
function WorkflowHint({ presets, workflow }: { presets?: Presets["workflows"]; workflow: string }) {
  const current = presets?.find((w) => w.id === workflow);
  if (!current?.with_references) return null;
  const refs = presets?.find((w) => w.id === current.with_references);
  return (
    <p className="mt-1 text-xs text-zinc-500">
      Cases avec images de référence : {refs?.name ?? `${current.with_references} (preset introuvable)`}
    </p>
  );
}

export function ProjectForm({
  initial,
  submitLabel,
  onSaved,
}: {
  initial?: Project;
  submitLabel: string;
  onSaved: (project: Project) => void;
}) {
  const presets = useEngineData(() => api.presets());
  const [form, setForm] = useState<Partial<ProjectInput>>({
    title: initial?.title ?? "",
    style: initial?.style ?? "",
    status: initial?.status ?? "ongoing",
    reading_direction: initial?.reading_direction ?? "rtl",
    page_format: initial?.page_format,
    workflow_preset: initial?.workflow_preset,
    style_lora_name: initial?.style_lora_name ?? "",
    style_lora_weight: initial?.style_lora_weight ?? 0.8,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const defaults = presets.data?.defaults;
  const pageFormat = form.page_format ?? defaults?.page_format ?? "";
  const workflow = form.workflow_preset ?? defaults?.workflow ?? "";

  const set = <K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: "" }));
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    setErrors({});
    const body = {
      ...form,
      page_format: pageFormat || undefined,
      workflow_preset: workflow || undefined,
      style_lora_name: form.style_lora_name?.trim() || null,
    };
    try {
      const saved = initial ? await api.updateProject(initial.id, body) : await api.createProject(body);
      onSaved(saved);
    } catch (err) {
      if (err instanceof EngineError && Object.keys(err.fieldErrors).length) setErrors(err.fieldErrors);
      setFormError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <Field label="Titre" htmlFor="title" error={errors.title}>
        <Input
          id="title"
          value={form.title ?? ""}
          onChange={(e) => set("title", e.target.value)}
          placeholder="Les Lames de Kyoto"
          aria-invalid={Boolean(errors.title)}
          required
          maxLength={200}
        />
      </Field>
      <Field
        label="Style graphique"
        htmlFor="style"
        error={errors.style}
        hint="Repris dans chaque prompt : encrage, trames, ambiance, références…"
      >
        <Textarea
          id="style"
          value={form.style ?? ""}
          onChange={(e) => set("style", e.target.value)}
          placeholder="Manga seinen noir et blanc, encrage épais, trames, décors détaillés"
          aria-invalid={Boolean(errors.style)}
        />
      </Field>
      <div className="grid gap-5 md:grid-cols-3">
        <Field label="Statut de la série" htmlFor="status" error={errors.status}>
          <Select
            id="status"
            value={form.status}
            onChange={(e) => set("status", e.target.value as ProjectInput["status"])}
          >
            {Object.entries(SERIES_STATUS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label="LoRA de style (optionnel)"
          htmlFor="style_lora_name"
          error={errors.style_lora_name}
          hint="Fichier dans ComfyUI/models/loras, appliqué à toutes les cases."
        >
          <Input
            id="style_lora_name"
            value={form.style_lora_name ?? ""}
            onChange={(e) => set("style_lora_name", e.target.value)}
            placeholder="encre-seinen-v2.safetensors"
            maxLength={255}
          />
        </Field>
        <Field label="Poids du LoRA de style" htmlFor="style_lora_weight" error={errors.style_lora_weight}>
          <Input
            id="style_lora_weight"
            type="number"
            min={0}
            max={2}
            step={0.05}
            value={form.style_lora_weight ?? 0.8}
            onChange={(e) => set("style_lora_weight", Number(e.target.value))}
            aria-invalid={Boolean(errors.style_lora_weight)}
          />
        </Field>
      </div>
      <div className="grid gap-5 md:grid-cols-3">
        <Field label="Sens de lecture" htmlFor="reading_direction" error={errors.reading_direction}>
          <Select
            id="reading_direction"
            value={form.reading_direction}
            onChange={(e) => set("reading_direction", e.target.value as ProjectInput["reading_direction"])}
          >
            {Object.entries(DIRECTIONS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Format de page" htmlFor="page_format" error={errors.page_format}>
          <Select
            id="page_format"
            value={pageFormat}
            onChange={(e) => set("page_format", e.target.value)}
            aria-invalid={Boolean(errors.page_format)}
            disabled={!presets.data}
          >
            {presets.data?.page_formats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.width_px}×{f.height_px} px)
              </option>
            ))}
            {pageFormat && !presets.data?.page_formats.some((f) => f.id === pageFormat) && (
              <option value={pageFormat}>{pageFormat} (preset introuvable)</option>
            )}
          </Select>
        </Field>
        <Field label="Workflow ComfyUI" htmlFor="workflow_preset" error={errors.workflow_preset}>
          <Select
            id="workflow_preset"
            value={workflow}
            onChange={(e) => set("workflow_preset", e.target.value)}
            aria-invalid={Boolean(errors.workflow_preset)}
            disabled={!presets.data}
          >
            {presets.data?.workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
            {workflow && !presets.data?.workflows.some((w) => w.id === workflow) && (
              <option value={workflow}>{workflow} (preset introuvable)</option>
            )}
          </Select>
          <WorkflowHint presets={presets.data?.workflows} workflow={workflow} />
        </Field>
      </div>
      <div className="flex justify-end">
        <Button type="submit" disabled={saving}>
          {saving ? "Enregistrement…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
