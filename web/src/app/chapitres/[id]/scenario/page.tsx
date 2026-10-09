"use client";

import { useMemo, useState, type ComponentProps } from "react";
import { Alert, Button, ButtonLink, Card, EmptyState, Field, Input, Loading, Select, Textarea } from "@/components/ui";
import { api, EngineError, errorMessage, type Job } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { isFinished, useJob } from "@/lib/jobs";
import {
  BUBBLE_KINDS,
  IMPORTANCE,
  PAGE_KINDS,
  SHOT_TYPES,
  fromDraft,
  moveItem,
  newDialogue,
  newPage,
  newPanel,
  toDraft,
  type DraftDialogue,
  type DraftPage,
  type DraftPanel,
} from "@/lib/script";
import { useChapter } from "../chapter-context";

export default function ScenarioPage() {
  const { chapter, setChapter, reload: reloadChapter } = useChapter();
  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id]);
  const characters = useEngineData(() => api.listCharacters(chapter.project_id), [chapter.project_id]);
  const lastJob = useEngineData(() => api.chapterJobs(chapter.id, "script").then((j) => j[0] ?? null), [chapter.id]);

  const [synopsis, setSynopsis] = useState(chapter.synopsis);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [started, setStarted] = useState<Job | null>(null);

  // Brouillon : la version du moteur tant qu'on n'a rien touché, puis la copie éditée.
  const base = useMemo(() => (pages.data ? toDraft(pages.data) : null), [pages.data]);
  const [edited, setEdited] = useState<DraftPage[] | null>(null);
  const draft = edited ?? base;
  const dirty = edited !== null;
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const current = started ?? lastJob.data ?? null;
  const job = useJob(current, (done) => {
    if (done.status === "succeeded") {
      setEdited(null);
      pages.reload();
      reloadChapter();
    }
  });
  const running = job !== null && !isFinished(job);

  async function decouper() {
    setStartError(null);
    if (dirty && !window.confirm("Le découpage actuel a des modifications non enregistrées. Les remplacer ?")) return;
    if (
      !dirty &&
      draft?.some((p) => p.kind === "story") &&
      !window.confirm("Remplacer les pages de l'histoire par un nouveau découpage ? (les pages bonus sont conservées)")
    )
      return;
    setStarting(true);
    try {
      if (synopsis !== chapter.synopsis) setChapter(await api.updateChapter(chapter.id, { synopsis }));
      setStarted(await api.startScript(chapter.id));
    } catch (err) {
      setStartError(
        err instanceof EngineError && err.fieldErrors.synopsis ? err.fieldErrors.synopsis : errorMessage(err),
      );
    } finally {
      setStarting(false);
    }
  }

  function edit(update: (pages: DraftPage[]) => DraftPage[]) {
    setEdited((d) => update(d ?? base ?? []));
    setSavedAt(null);
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await api.savePages(chapter.id, fromDraft(draft));
      pages.setData(saved);
      setEdited(null);
      setSavedAt(Date.now());
      reloadChapter();
    } catch (err) {
      const fields = err instanceof EngineError ? Object.entries(err.fieldErrors) : [];
      setSaveError(
        fields.length ? fields.map(([f, m]) => `${readableField(f)} : ${m}`).join(" · ") : errorMessage(err),
      );
    } finally {
      setSaving(false);
    }
  }

  const names = characters.data?.map((c) => c.name) ?? [];
  const panelCount = draft?.reduce((n, p) => n + p.panels.length, 0) ?? 0;

  return (
    <div className="space-y-6">
      <Card>
        <Field
          label="Synopsis ou script brut du chapitre"
          htmlFor="synopsis"
          hint="Le LLM reçoit aussi la fiche de la série, les personnages et le résumé des chapitres précédents."
        >
          <Textarea
            id="synopsis"
            className="min-h-36"
            value={synopsis}
            onChange={(e) => setSynopsis(e.target.value)}
            placeholder="Aiko arrive à Kyoto sous la pluie. Un rônin lui vole son sabre…"
            disabled={running}
          />
        </Field>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-zinc-500">
            Objectif : {chapter.target_page_count} pages · modifiable dans l&apos;onglet Infos.
          </p>
          <Button onClick={decouper} disabled={starting || running || !synopsis.trim()} data-testid="decouper">
            {running ? "Découpage en cours…" : starting ? "Lancement…" : "Découper"}
          </Button>
        </div>
        {startError && (
          <div className="mt-4">
            <Alert>{startError}</Alert>
          </div>
        )}
        {job && <JobProgress job={job} onRetry={decouper} />}
      </Card>

      <section aria-label="Découpage">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Découpage</h2>
            {draft && draft.length > 0 && (
              <p className="text-xs text-zinc-500">
                {draft.length} page{draft.length > 1 ? "s" : ""} · {panelCount} case{panelCount > 1 ? "s" : ""}
                {dirty && <span className="ml-2 text-amber-300">· modifications non enregistrées</span>}
                {savedAt && !dirty && <span className="ml-2 text-emerald-300">· enregistré</span>}
              </p>
            )}
          </div>
          {draft && draft.length > 0 && (
            <div className="flex gap-2">
              <ButtonLink href={`/chapitres/${chapter.id}/mise-en-page`} variant="secondary">
                Voir la mise en page
              </ButtonLink>
              <Button onClick={save} disabled={!dirty || saving || running} data-testid="save-breakdown">
                {saving ? "Enregistrement…" : "Enregistrer"}
              </Button>
            </div>
          )}
        </div>
        {saveError && (
          <div className="mb-4">
            <Alert>{saveError}</Alert>
          </div>
        )}
        {pages.loading && !draft ? (
          <Loading />
        ) : pages.error ? (
          <Alert>Impossible de charger le découpage : {pages.error}</Alert>
        ) : !draft || draft.length === 0 ? (
          <EmptyState title="Pas encore de découpage">
            Écris le synopsis puis clique sur « Découper » : le LLM propose pages, cases et dialogues, que tu pourras
            retoucher ici.
            <div className="mt-4">
              <Button variant="secondary" onClick={() => edit(() => [newPage()])}>
                Ou commencer une page à la main
              </Button>
            </div>
          </EmptyState>
        ) : (
          <div className="space-y-5">
            <datalist id="character-names">
              {names.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
            {draft.map((page, pi) => (
              <PageEditor
                key={page.key}
                page={page}
                index={pi}
                total={draft.length}
                disabled={running}
                onChange={(next) => edit((d) => d.map((p, i) => (i === pi ? next : p)))}
                onMove={(delta) => edit((d) => moveItem(d, pi, delta))}
                onRemove={() => {
                  if (window.confirm(`Supprimer la page ${pi + 1} et ses cases ?`))
                    edit((d) => d.filter((_, i) => i !== pi));
                }}
              />
            ))}
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => edit((d) => [...d, newPage()])} disabled={running}>
                + Page d&apos;histoire
              </Button>
              <Button variant="secondary" onClick={() => edit((d) => [...d, newPage("bonus")])} disabled={running}>
                + Page bonus
              </Button>
              <Button onClick={save} disabled={!dirty || saving || running} className="ml-auto">
                {saving ? "Enregistrement…" : "Enregistrer le découpage"}
              </Button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function readableField(path: string): string {
  // « pages.0.panels.2.dialogues.1.text » → « page 1 › case 3 › réplique 2 › text »
  const labels: Record<string, string> = { pages: "page", panels: "case", dialogues: "réplique" };
  const parts = path.split(".");
  const out: string[] = [];
  for (let i = 0; i < parts.length; i++) {
    const next = Number(parts[i + 1]);
    if (labels[parts[i]] && Number.isInteger(next)) {
      out.push(`${labels[parts[i]]} ${next + 1}`);
      i++;
    } else out.push(parts[i]);
  }
  return out.join(" › ");
}

function JobProgress({ job, onRetry }: { job: Job; onRetry: () => void }) {
  if (job.status === "failed" || job.status === "cancelled") {
    return (
      <div className="mt-4 space-y-3" data-testid="job-error">
        <Alert>
          <strong className="font-semibold">Le découpage a échoué.</strong> {job.error ?? job.message}
        </Alert>
        <Button variant="secondary" onClick={onRetry}>
          Réessayer
        </Button>
      </div>
    );
  }
  if (job.status === "succeeded") {
    return (
      <p className="mt-4 text-sm text-emerald-300" role="status" data-testid="job-done">
        Découpage terminé : {job.message}.
      </p>
    );
  }
  return (
    <div className="mt-4" role="status" aria-live="polite" data-testid="job-progress">
      <div className="mb-1 flex justify-between text-xs text-zinc-400">
        <span>{job.message || "En attente…"}</span>
        <span>{job.progress} %</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full bg-rose-500 transition-all duration-300" style={{ width: `${Math.max(3, job.progress)}%` }} />
      </div>
    </div>
  );
}

function SmallButton(props: ComponentProps<typeof Button>) {
  return <Button variant="ghost" className="px-2 py-1 text-xs" {...props} />;
}

function PageEditor({
  page,
  index,
  total,
  disabled,
  onChange,
  onMove,
  onRemove,
}: {
  page: DraftPage;
  index: number;
  total: number;
  disabled: boolean;
  onChange: (p: DraftPage) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const setPanels = (update: (panels: DraftPanel[]) => DraftPanel[]) => onChange({ ...page, panels: update(page.panels) });
  return (
    <Card className="p-4" data-testid="page-editor">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h3 className="font-semibold text-zinc-100">Page {index + 1}</h3>
        <div className="w-56">
        <Select
          aria-label={`Type de la page ${index + 1}`}
          className="py-1 text-xs"
          value={page.kind}
          onChange={(e) => onChange({ ...page, kind: e.target.value as DraftPage["kind"] })}
          disabled={disabled}
        >
          {Object.entries(PAGE_KINDS).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </Select>
        </div>
        <span className="text-xs text-zinc-500">
          {page.panels.length} case{page.panels.length > 1 ? "s" : ""}
        </span>
        <span className="ml-auto flex gap-1">
          <SmallButton onClick={() => onMove(-1)} disabled={disabled || index === 0} aria-label="Monter la page">
            ↑
          </SmallButton>
          <SmallButton onClick={() => onMove(1)} disabled={disabled || index === total - 1} aria-label="Descendre la page">
            ↓
          </SmallButton>
          <SmallButton onClick={onRemove} disabled={disabled} aria-label={`Supprimer la page ${index + 1}`}>
            Supprimer
          </SmallButton>
        </span>
      </div>
      <ol className="space-y-3">
        {page.panels.map((panel, ci) => (
          <PanelEditor
            key={panel.key}
            panel={panel}
            index={ci}
            total={page.panels.length}
            pageIndex={index}
            disabled={disabled}
            onChange={(next) => setPanels((ps) => ps.map((p, i) => (i === ci ? next : p)))}
            onMove={(delta) => setPanels((ps) => moveItem(ps, ci, delta))}
            onRemove={() => setPanels((ps) => ps.filter((_, i) => i !== ci))}
          />
        ))}
      </ol>
      <div className="mt-3">
        <SmallButton
          onClick={() => setPanels((ps) => [...ps, newPanel()])}
          disabled={disabled || page.panels.length >= 9}
        >
          + Ajouter une case
        </SmallButton>
      </div>
    </Card>
  );
}

function PanelEditor({
  panel,
  index,
  total,
  pageIndex,
  disabled,
  onChange,
  onMove,
  onRemove,
}: {
  panel: DraftPanel;
  index: number;
  total: number;
  pageIndex: number;
  disabled: boolean;
  onChange: (p: DraftPanel) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const id = `p${pageIndex}-c${index}`;
  const set = <K extends keyof DraftPanel>(k: K, v: DraftPanel[K]) => onChange({ ...panel, [k]: v });
  const setDialogues = (update: (d: DraftDialogue[]) => DraftDialogue[]) =>
    onChange({ ...panel, dialogues: update(panel.dialogues) });
  return (
    <li className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3" data-testid="panel-editor">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-800 text-xs font-semibold text-zinc-200">
          {index + 1}
        </span>
        <span className="text-xs text-zinc-500">Case {index + 1}</span>
        <span className="ml-auto flex gap-1">
          <SmallButton onClick={() => onMove(-1)} disabled={disabled || index === 0} aria-label="Monter la case">
            ↑
          </SmallButton>
          <SmallButton onClick={() => onMove(1)} disabled={disabled || index === total - 1} aria-label="Descendre la case">
            ↓
          </SmallButton>
          <SmallButton onClick={onRemove} disabled={disabled} aria-label={`Supprimer la case ${index + 1}`}>
            Retirer
          </SmallButton>
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-1">
          <label htmlFor={`${id}-desc`} className="text-xs text-zinc-400">
            Description
          </label>
          <Textarea
            id={`${id}-desc`}
            className="min-h-20 text-sm"
            value={panel.description}
            onChange={(e) => set("description", e.target.value)}
            disabled={disabled}
          />
        </div>
        <div className="grid gap-2">
          <div className="space-y-1">
            <label htmlFor={`${id}-shot`} className="text-xs text-zinc-400">
              Type de plan
            </label>
            <Select
              id={`${id}-shot`}
              className="py-1.5"
              value={panel.shot_type ?? ""}
              onChange={(e) => set("shot_type", e.target.value || null)}
              disabled={disabled}
            >
              <option value="">—</option>
              {SHOT_TYPES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
              {panel.shot_type && !(SHOT_TYPES as readonly string[]).includes(panel.shot_type) && (
                <option value={panel.shot_type}>{panel.shot_type}</option>
              )}
            </Select>
          </div>
          <div className="space-y-1">
            <label htmlFor={`${id}-imp`} className="text-xs text-zinc-400">
              Importance
            </label>
            <Select
              id={`${id}-imp`}
              className="py-1.5"
              value={panel.importance}
              onChange={(e) => set("importance", Number(e.target.value))}
              disabled={disabled}
            >
              {Object.entries(IMPORTANCE).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <label htmlFor={`${id}-chars`} className="text-xs text-zinc-400">
              Personnages (séparés par des virgules)
            </label>
            <Input
              id={`${id}-chars`}
              className="py-1.5"
              value={panel.charactersText}
              onChange={(e) => set("charactersText", e.target.value)}
              disabled={disabled}
            />
          </div>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        <p className="text-xs text-zinc-400">Dialogues</p>
        {panel.dialogues.length === 0 && <p className="text-xs text-zinc-600">Case muette.</p>}
        {panel.dialogues.map((d, di) => (
          <div key={d.key} className="grid gap-2 sm:grid-cols-[9rem_8rem_minmax(0,1fr)_auto]">
            <Input
              aria-label="Locuteur"
              list="character-names"
              placeholder={d.kind === "narration" ? "(récitatif)" : "Locuteur"}
              className="py-1.5 text-sm"
              value={d.speaker}
              onChange={(e) =>
                setDialogues((ds) => ds.map((x, i) => (i === di ? { ...x, speaker: e.target.value } : x)))
              }
              disabled={disabled}
            />
            <Select
              aria-label="Type de bulle"
              className="py-1.5 text-sm"
              value={d.kind}
              onChange={(e) =>
                setDialogues((ds) =>
                  ds.map((x, i) => (i === di ? { ...x, kind: e.target.value as DraftDialogue["kind"] } : x)),
                )
              }
              disabled={disabled}
            >
              {Object.entries(BUBBLE_KINDS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
            <Input
              aria-label="Texte"
              className="py-1.5 text-sm"
              value={d.text}
              onChange={(e) => setDialogues((ds) => ds.map((x, i) => (i === di ? { ...x, text: e.target.value } : x)))}
              disabled={disabled}
            />
            <SmallButton
              onClick={() => setDialogues((ds) => ds.filter((_, i) => i !== di))}
              disabled={disabled}
              aria-label="Supprimer la réplique"
            >
              ✕
            </SmallButton>
          </div>
        ))}
        <SmallButton
          onClick={() => setDialogues((ds) => [...ds, newDialogue()])}
          disabled={disabled || panel.dialogues.length >= 12}
        >
          + Réplique
        </SmallButton>
      </div>
    </li>
  );
}
