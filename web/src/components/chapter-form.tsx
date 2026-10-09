"use client";

import { useState, type FormEvent } from "react";
import { api, EngineError, errorMessage, type Chapter, type ChapterInput } from "@/lib/api";
import { CHAPTER_STATUS } from "./status";
import { Alert, Button, Field, Input, Select, Textarea } from "./ui";

export function ChapterForm({
  projectId,
  initial,
  submitLabel,
  onSaved,
}: {
  projectId: number;
  initial?: Chapter;
  submitLabel: string;
  onSaved: (chapter: Chapter) => void;
}) {
  const [form, setForm] = useState<ChapterInput>({
    title: initial?.title ?? "",
    synopsis: initial?.synopsis ?? "",
    target_page_count: initial?.target_page_count ?? 15,
    status: initial?.status ?? "draft",
    planned_date: initial?.planned_date ?? null,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof ChapterInput>(key: K, value: ChapterInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: "" }));
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    setErrors({});
    try {
      const saved = initial ? await api.updateChapter(initial.id, form) : await api.createChapter(projectId, form);
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
      <Field label="Titre du chapitre" htmlFor="chapter-title" error={errors.title}>
        <Input
          id="chapter-title"
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder="La pluie sur Kamo"
          maxLength={200}
          aria-invalid={Boolean(errors.title)}
        />
      </Field>
      <Field
        label="Synopsis ou script brut"
        htmlFor="chapter-synopsis"
        error={errors.synopsis}
        hint="Envoyé au LLM avec la fiche de la série, les personnages et le résumé des chapitres précédents."
      >
        <Textarea
          id="chapter-synopsis"
          className="min-h-40"
          value={form.synopsis}
          onChange={(e) => set("synopsis", e.target.value)}
          placeholder="Aiko arrive à Kyoto sous la pluie. Elle croise un rônin qui lui vole son sabre…"
          aria-invalid={Boolean(errors.synopsis)}
        />
      </Field>
      <div className="grid gap-5 md:grid-cols-3">
        <Field label="Pages visées" htmlFor="chapter-pages" error={errors.target_page_count}>
          <Input
            id="chapter-pages"
            type="number"
            min={1}
            max={60}
            value={form.target_page_count}
            onChange={(e) => set("target_page_count", Number(e.target.value))}
            aria-invalid={Boolean(errors.target_page_count)}
          />
        </Field>
        <Field label="Statut" htmlFor="chapter-status" error={errors.status}>
          <Select
            id="chapter-status"
            value={form.status}
            onChange={(e) => set("status", e.target.value as ChapterInput["status"])}
          >
            {Object.entries(CHAPTER_STATUS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Publication prévue" htmlFor="chapter-date" error={errors.planned_date}>
          <Input
            id="chapter-date"
            type="date"
            value={form.planned_date ?? ""}
            onChange={(e) => set("planned_date", e.target.value || null)}
            aria-invalid={Boolean(errors.planned_date)}
          />
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
