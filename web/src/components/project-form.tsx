"use client";

import { useRef, useState, type FormEvent } from "react";
import { api, EngineError, errorMessage, type Presets, type Project, type ProjectInput } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { Modal } from "./modal";
import { LoraPicker } from "./lora-picker";
import { DIRECTIONS, DirectionPicker } from "./reading-direction";
import { SERIES_STATUS } from "./status";
import { Alert, Button, Field, Input, Select, Textarea } from "./ui";

const DIRECTION_REQUIRED = "Choisis le sens de lecture : manga (droite → gauche) ou BD (gauche → droite).";

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
    // À la création rien n'est présélectionné : le sens de lecture est un choix explicite.
    reading_direction: initial?.reading_direction,
    page_format: initial?.page_format,
    workflow_preset: initial?.workflow_preset,
    style_lora_name: initial?.style_lora_name ?? "",
    style_lora_weight: initial?.style_lora_weight ?? 0.8,
    style_lora_trigger_words: initial?.style_lora_trigger_words ?? "",
    layout_style: initial?.layout_style,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  const defaults = presets.data?.defaults;
  const pageFormat = form.page_format ?? defaults?.page_format ?? "";
  const workflow = form.workflow_preset ?? defaults?.workflow ?? "";
  const styles = presets.data?.layout_styles ?? [];
  const layoutStyle =
    form.layout_style ?? defaults?.layout_style ?? styles.find((s) => s.is_default)?.id ?? "";
  const styleInfo = styles.find((s) => s.id === layoutStyle);
  // Paliers proposés (Turbo, Rapide, Qualité) : workflows qui déclarent un libellé de palier.
  const tiers = (presets.data?.workflows ?? [])
    .filter((w) => w.tier_choice)
    .sort((a, b) => (a.tier_order ?? 0) - (b.tier_order ?? 0));
  const currentWorkflow = presets.data?.workflows.find((w) => w.id === workflow);

  const set = <K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: "" }));
  };

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.reading_direction) {
      setErrors({ reading_direction: DIRECTION_REQUIRED });
      setFormError(null);
      formRef.current?.querySelector<HTMLInputElement>('input[name="reading_direction"]')?.focus();
      return;
    }
    const relayout = initial && form.reading_direction !== initial.reading_direction && initial.laid_out_page_count > 0;
    if (relayout) setConfirming(true);
    else void save();
  }

  async function save() {
    setConfirming(false);
    setSaving(true);
    setFormError(null);
    setErrors({});
    const body = {
      ...form,
      page_format: pageFormat || undefined,
      workflow_preset: workflow || undefined,
      layout_style: layoutStyle || undefined,
      style_lora_name: form.style_lora_name?.trim() || null,
      style_lora_trigger_words: form.style_lora_trigger_words?.trim() ?? "",
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
    <form ref={formRef} onSubmit={submit} className="space-y-5" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <DirectionPicker
        value={form.reading_direction}
        onChange={(v) => set("reading_direction", v)}
        error={errors.reading_direction}
      />
      <Field
        label="Style de mise en page"
        htmlFor="layout_style"
        error={errors.layout_style}
        hint={styleInfo?.description || "Découpes, biais et gouttières de toutes les pages de la série."}
      >
        <Select
          id="layout_style"
          value={layoutStyle}
          onChange={(e) => set("layout_style", e.target.value)}
          aria-invalid={Boolean(errors.layout_style)}
          disabled={!presets.data}
        >
          {styles.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
          {layoutStyle && presets.data && !styles.some((s) => s.id === layoutStyle) && (
            <option value={layoutStyle}>{layoutStyle} (preset introuvable)</option>
          )}
        </Select>
      </Field>
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
      </div>
      <LoraPicker
        id="style_lora_name"
        label="LoRA de style (optionnel)"
        hint="Appliqué à toutes les cases de la série."
        placeholder="encre-seinen-v2.safetensors"
        value={form.style_lora_name ?? ""}
        onChange={(v) => set("style_lora_name", v)}
        savedValue={initial?.style_lora_name}
        error={errors.style_lora_name}
        weight={String(form.style_lora_weight ?? 0.8)}
        onWeightChange={(v) => set("style_lora_weight", Number(v))}
        weightLabel="Poids du LoRA de style"
        weightError={errors.style_lora_weight}
        triggerWords={form.style_lora_trigger_words ?? ""}
        onTriggerWordsChange={(v) => set("style_lora_trigger_words", v)}
        triggerWordsError={errors.style_lora_trigger_words}
      />
      <div className="grid gap-5 md:grid-cols-2">
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
        <Field
          label="Palier de génération"
          htmlFor="workflow_preset"
          error={errors.workflow_preset}
          hint="Chaque case peut ensuite être régénérée en Qualité depuis l'atelier."
        >
          <Select
            id="workflow_preset"
            value={workflow}
            onChange={(e) => set("workflow_preset", e.target.value)}
            aria-invalid={Boolean(errors.workflow_preset)}
            disabled={!presets.data}
          >
            {tiers.map((w) => (
              <option key={w.id} value={w.id}>
                {w.tier_choice}
              </option>
            ))}
            {/* Série réglée sur un workflow qui n'est pas un palier (ou disparu) : on le garde visible. */}
            {workflow && presets.data && !tiers.some((w) => w.id === workflow) && (
              <option value={workflow}>{currentWorkflow?.name ?? `${workflow} (preset introuvable)`}</option>
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
      {initial && form.reading_direction && (
        <Modal
          open={confirming}
          onClose={() => setConfirming(false)}
          title="Changer le sens de lecture ?"
          footer={
            <>
              <Button type="button" variant="secondary" onClick={() => setConfirming(false)}>
                Annuler
              </Button>
              <Button type="button" onClick={() => void save()}>
                Changer et recalculer
              </Button>
            </>
          }
        >
          <div className="space-y-3 text-sm text-zinc-300">
            <p>
              La série passe en <strong className="text-zinc-100">{DIRECTIONS[form.reading_direction]}</strong>.
            </p>
            <p>
              {initial.laid_out_page_count === 1
                ? "La page déjà mise en page va être mise en miroir et recalculée"
                : `Les ${initial.laid_out_page_count} pages déjà mises en page vont être mises en miroir et recalculées`}{" "}
              : ordre de lecture des cases, gouttières et bulles placées à la main passent de l&apos;autre côté.
            </p>
            <p>
              Les images de cases déjà générées sont conservées telles quelles (elles ne sont pas retournées) : regénère
              celles dont la composition ne colle plus au nouveau sens.
            </p>
          </div>
        </Modal>
      )}
    </form>
  );
}
