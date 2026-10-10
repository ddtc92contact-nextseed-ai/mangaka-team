"use client";

import Link from "next/link";
import { useMemo, useState, type ComponentProps } from "react";
import { HelpLabel, InfoTip } from "@/components/info-tip";
import { PassageList, formatTokens } from "@/components/knowledge";
import { useToast } from "@/components/toast";
import { UnmatchedNames } from "@/components/unmatched-names";
import { Alert, Button, ButtonLink, Card, EmptyState, Field, Input, Loading, Select, Textarea } from "@/components/ui";
import {
  api,
  EngineError,
  errorMessage,
  type Intensity,
  type Job,
  type LibraryEntry,
  type Rythme,
  type ScriptSources,
} from "@/lib/api";
import { useEngineData, useUnsavedWarning } from "@/lib/hooks";
import { isFinished, useJob } from "@/lib/jobs";
import { INTENSITIES, RYTHMES } from "@/lib/layout";
import { LIBRARY_KINDS, libraryHref } from "@/lib/library";
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
  unmatchedNames,
  type DraftDialogue,
  type DraftPage,
  type DraftPanel,
} from "@/lib/script";
import { useChapter } from "../chapter-context";

export default function ScenarioPage() {
  const { chapter, setChapter, reload: reloadChapter } = useChapter();
  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id]);
  const characters = useEngineData(() => api.listCharacters(chapter.project_id), [chapter.project_id]);
  const decors = useEngineData(() => api.listLibrary("decor", chapter.project_id), [chapter.project_id]);
  const objets = useEngineData(() => api.listLibrary("object", chapter.project_id), [chapter.project_id]);
  const library: SceneLibrary = { decors: decors.data ?? [], objets: objets.data ?? [], projectId: chapter.project_id };
  const lastJob = useEngineData(() => api.chapterJobs(chapter.id, "script").then((j) => j[0] ?? null), [chapter.id]);
  const sources = useEngineData(() => api.chapterSources(chapter.id), [chapter.id]);

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
  const toast = useToast();
  useUnsavedWarning(dirty);

  const current = started ?? lastJob.data ?? null;
  const job = useJob(current, (done) => {
    sources.reload();
    if (done.status === "succeeded") {
      toast("Découpage enregistré automatiquement");
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
      toast("Découpage lancé", "info");
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
      toast("Découpage enregistré");
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
  // Noms sans fiche dans tout le chapitre (un rattachement vaut pour toutes les cases).
  const unmatched = [...new Set(draft?.flatMap((p) => p.panels.flatMap(unmatchedNames)) ?? [])];

  return (
    <div className="space-y-6">
      <Card>
        <Field
          label="Synopsis ou script brut du chapitre"
          htmlFor="synopsis"
          help="scenario.synopsis"
          hint="Le LLM reçoit aussi la fiche de la série, sa bibliothèque (personnages, décors et objets récurrents), le résumé des chapitres précédents, la bible de la série et les passages du savoir-faire."
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
          <span className="flex items-center gap-2">
            <InfoTip help="scenario.decouper" label="Découper" />
            <Button onClick={decouper} disabled={starting || running || !synopsis.trim()} data-testid="decouper">
              {running ? "Découpage en cours…" : starting ? "Lancement…" : "Découper"}
            </Button>
          </span>
        </div>
        {startError && (
          <div className="mt-4">
            <Alert>{startError}</Alert>
          </div>
        )}
        {job && <JobProgress job={job} onRetry={decouper} />}
      </Card>

      {sources.data && <UsedSources sources={sources.data} />}

      <section aria-label="Découpage">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Découpage</h2>
            {draft && draft.length > 0 && (
              <p className="text-xs text-zinc-500">
                {draft.length} page{draft.length > 1 ? "s" : ""} · {panelCount} case{panelCount > 1 ? "s" : ""}
                {dirty && <span className="ml-2 text-amber-300">· modifications non enregistrées</span>}
                {savedAt && !dirty && (
                  <span className="ml-2 text-emerald-300" data-testid="saved-at">
                    · retouches enregistrées à {formatTime(savedAt)}
                  </span>
                )}
              </p>
            )}
          </div>
          {draft && draft.length > 0 && (
            <div className="flex items-center gap-2">
              <ButtonLink href={`/chapitres/${chapter.id}/mise-en-page`} variant="secondary">
                Voir la mise en page
              </ButtonLink>
              <InfoTip help="scenario.enregistrer" label="Enregistrer" />
              <Button onClick={save} disabled={!dirty || saving || running} data-testid="save-breakdown">
                {saveLabel(dirty, saving, "Enregistrer")}
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
            <UnmatchedNames
              chapterId={chapter.id}
              projectId={chapter.project_id}
              names={unmatched}
              characters={characters.data ?? []}
              onLinked={() => {
                pages.reload();
                characters.reload();
              }}
              disabled={dirty || running}
              disabledReason={dirty ? "Enregistre d'abord le découpage : le rattachement relit les cases enregistrées." : undefined}
            />
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
                library={library}
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
                {saveLabel(dirty, saving, "Enregistrer le découpage")}
              </Button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

/** Ce que le scénariste a reçu : bible de la série et passages du savoir-faire (titres + extraits). */
function UsedSources({ sources }: { sources: ScriptSources }) {
  const [open, setOpen] = useState(false);
  const count = sources.passages.length;
  return (
    <Card data-testid="used-sources">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-zinc-100">Sources utilisées</h2>
          <p className="text-xs text-zinc-500">
            Dernier découpage du {engineDate(sources.created_at).toLocaleString("fr-FR")} ·{" "}
            {count} passage{count > 1 ? "s" : ""} du savoir-faire
            {sources.collections.length > 0 && ` (${sources.collections.join(", ")})`} ·{" "}
            {sources.bible ? `bible de la série (${formatTokens(sources.bible.tokens)})` : "pas de bible pour cette série"}
          </p>
        </div>
        <Button variant="secondary" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "Masquer" : "Voir les sources"}
        </Button>
      </div>
      {open && (
        <div className="mt-4 space-y-4">
          {sources.bible && (
            <details className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
              <summary className="cursor-pointer text-sm font-medium text-zinc-200">
                Bible de la série{sources.bible.truncated ? " (raccourcie au budget)" : ""}
              </summary>
              <p className="mt-2 whitespace-pre-line text-sm text-zinc-300">{sources.bible.text}</p>
            </details>
          )}
          {count ? (
            <PassageList passages={sources.passages} excerpt={400} showScores testId="used-passages" />
          ) : (
            <p className="text-sm text-zinc-500">
              Aucun passage : ajoute des fiches dans la bibliothèque de savoir-faire (collections lues par le scénariste).
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

/** « Enregistré ✓ » quand il n'y a rien à enregistrer (le découpage du LLM l'est dès qu'il est terminé). */
function saveLabel(dirty: boolean, saving: boolean, label: string): string {
  return saving ? "Enregistrement…" : dirty ? label : "Enregistré ✓";
}

/** Les dates du moteur sont en UTC sans fuseau (« 2026-10-10T11:49:57 ») : à lire comme telles. */
function engineDate(at: string | number): Date {
  return new Date(typeof at === "string" && !/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? `${at}Z` : at);
}

function formatTime(at: string | number): string {
  return engineDate(at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function readableField(path: string): string {
  // « pages.0.panels.2.dialogues.1.text » → « page 1 › case 3 › réplique 2 › text »
  const labels: Record<string, string> = { pages: "page", panels: "case", dialogues: "réplique" };
  const names: Record<string, string> = { decor: "décor", objets: "objets" };
  const parts = path.split(".");
  const out: string[] = [];
  for (let i = 0; i < parts.length; i++) {
    const next = Number(parts[i + 1]);
    if (labels[parts[i]] && Number.isInteger(next)) {
      out.push(`${labels[parts[i]]} ${next + 1}`);
      i++;
    } else out.push(names[parts[i]] ?? parts[i]);
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
        Découpage enregistré automatiquement
        {job.finished_at && ` à ${formatTime(job.finished_at)}`} ({job.message}).
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

/** Objets récurrents visibles dans la case : boutons à cocher (utilisables au doigt). */
function ObjectPicker({
  id,
  library,
  value,
  onChange,
  disabled,
}: {
  id: string;
  library: SceneLibrary;
  value: number[];
  onChange: (ids: number[]) => void;
  disabled: boolean;
}) {
  const unknown = value.filter((v) => !library.objets.some((o) => o.id === v));
  const options = [...library.objets.map((o) => ({ id: o.id, name: o.name })), ...unknown.map((v) => ({ id: v, name: `Objet n° ${v}` }))];
  return (
    <div className="mt-3 space-y-1" role="group" aria-labelledby={`${id}-label`}>
      <div className="flex items-center gap-1.5">
        <p id={`${id}-label`} className="text-xs text-zinc-400">
          Objets récurrents visibles
        </p>
        <InfoTip help="scenario.objets" label="Objets récurrents visibles" />
      </div>
      {options.length === 0 ? (
        <p className="text-xs text-zinc-600">
          Aucun objet dans la bibliothèque de la série.{" "}
          <Link href={libraryHref(library.projectId, "object")} className="underline-offset-2 hover:text-zinc-300 hover:underline">
            En ajouter
          </Link>
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {options.map((o) => {
            const on = value.includes(o.id);
            return (
              <button
                key={o.id}
                type="button"
                aria-pressed={on}
                disabled={disabled}
                onClick={() => onChange(on ? value.filter((v) => v !== o.id) : [...value, o.id])}
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-rose-400 disabled:opacity-50 ${
                  on
                    ? `border-transparent ${LIBRARY_KINDS.object.badge}`
                    : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
                }`}
              >
                {on ? "✓ " : ""}
                {o.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SmallButton(props: ComponentProps<typeof Button>) {
  return <Button variant="ghost" className="px-2 py-1 text-xs" {...props} />;
}

/** Décors et objets récurrents de la série, proposés dans chaque case. */
interface SceneLibrary {
  decors: LibraryEntry[];
  objets: LibraryEntry[];
  projectId: number;
}

function PageEditor({
  page,
  index,
  total,
  library,
  disabled,
  onChange,
  onMove,
  onRemove,
}: {
  page: DraftPage;
  index: number;
  total: number;
  library: SceneLibrary;
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
        <div className="flex w-60 items-center gap-1.5">
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
        <InfoTip help="scenario.page_kind" label="Type de page" />
        </div>
        {page.kind === "story" && (
          <div className="flex w-52 items-center gap-1.5">
            <Select
              aria-label={`Rythme de la page ${index + 1}`}
              className="py-1 text-xs"
              value={page.rythme ?? ""}
              onChange={(e) => onChange({ ...page, rythme: (e.target.value || null) as Rythme | null })}
              disabled={disabled}
            >
              <option value="">Rythme : non précisé</option>
              {Object.entries(RYTHMES).map(([v, l]) => (
                <option key={v} value={v}>
                  Rythme : {l}
                </option>
              ))}
            </Select>
            <InfoTip help="scenario.rythme" label="Rythme de la page" />
          </div>
        )}
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
            library={library}
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
  library,
  disabled,
  onChange,
  onMove,
  onRemove,
}: {
  panel: DraftPanel;
  index: number;
  total: number;
  pageIndex: number;
  library: SceneLibrary;
  disabled: boolean;
  onChange: (p: DraftPanel) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const id = `p${pageIndex}-c${index}`;
  const missing = unmatchedNames(panel);
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
          <div className="flex items-center gap-1.5 pt-1">
            <label htmlFor={`${id}-setting`} className="text-xs text-zinc-400">
              Lieu
            </label>
            <InfoTip help="scenario.setting" label="Lieu" />
          </div>
          <Textarea
            id={`${id}-setting`}
            className="min-h-12 text-sm"
            value={panel.setting}
            onChange={(e) => set("setting", e.target.value)}
            placeholder="Clairière au bord d'un lac, fin d'après-midi, herbes hautes, montagnes au loin"
            maxLength={1500}
            disabled={disabled}
          />
          <div className="flex items-center gap-1.5 pt-1">
            <label htmlFor={`${id}-staging`} className="text-xs text-zinc-400">
              Mise en scène
            </label>
            <InfoTip help="scenario.staging" label="Mise en scène" />
          </div>
          <Textarea
            id={`${id}-staging`}
            className="min-h-12 text-sm"
            value={panel.staging}
            onChange={(e) => set("staging", e.target.value)}
            placeholder="Urus au premier plan à gauche, ailes déployées ; Kael sur un rocher à droite, le regarde"
            maxLength={1500}
            disabled={disabled}
          />
        </div>
        <div className="grid gap-2">
          <div className="space-y-1">
            <div className="flex items-center gap-1.5">
              <label htmlFor={`${id}-shot`} className="text-xs text-zinc-400">
                Type de plan
              </label>
              <InfoTip help="scenario.shot_type" label="Type de plan" />
            </div>
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
            <div className="flex items-center gap-1.5">
              <label htmlFor={`${id}-imp`} className="text-xs text-zinc-400">
                Importance
              </label>
              <InfoTip help="scenario.importance" label="Importance" />
            </div>
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
            <div className="flex items-center gap-1.5">
              <label htmlFor={`${id}-int`} className="text-xs text-zinc-400">
                Intensité (mise en page)
              </label>
              <InfoTip help="scenario.intensity" label="Intensité (mise en page)" />
            </div>
            <Select
              id={`${id}-int`}
              className="py-1.5"
              value={panel.intensity ?? ""}
              onChange={(e) => set("intensity", (e.target.value || null) as Intensity | null)}
              disabled={disabled}
            >
              <option value="">Non précisée</option>
              {Object.entries(INTENSITIES).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-1.5">
              <label htmlFor={`${id}-chars`} className="text-xs text-zinc-400">
                Personnages (séparés par des virgules)
              </label>
              <InfoTip help="scenario.characters" label="Personnages" />
            </div>
            <Input
              id={`${id}-chars`}
              className="py-1.5"
              value={panel.charactersText}
              onChange={(e) => set("charactersText", e.target.value)}
              aria-describedby={missing.length ? `${id}-missing` : undefined}
              disabled={disabled}
            />
            {missing.length > 0 && (
              <p id={`${id}-missing`} className="text-xs text-amber-300" data-testid="panel-unmatched">
                ⚠ Sans fiche : {missing.map((n) => `« ${n} »`).join(", ")} — à rattacher en haut du découpage.
              </p>
            )}
          </div>
          <div className="space-y-1">
            <label htmlFor={`${id}-decor`} className="text-xs text-zinc-400">
              Décor
            </label>
            <Select
              id={`${id}-decor`}
              className="py-1.5"
              value={panel.decor ?? ""}
              onChange={(e) => set("decor", e.target.value ? Number(e.target.value) : null)}
              disabled={disabled}
            >
              <option value="">Aucun décor récurrent</option>
              {library.decors.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
              {panel.decor !== null && !library.decors.some((d) => d.id === panel.decor) && (
                <option value={panel.decor}>Décor n° {panel.decor}</option>
              )}
            </Select>
          </div>
        </div>
      </div>
      <ObjectPicker
        id={`${id}-objets`}
        library={library}
        value={panel.objets}
        onChange={(objets) => set("objets", objets)}
        disabled={disabled}
      />
      <div className="mt-3 space-y-2">
        <p className="text-xs text-zinc-400">
          <HelpLabel help="scenario.bubbles">Dialogues</HelpLabel>
        </p>
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
