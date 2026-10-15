"use client";

import { useMemo, useState } from "react";
import { useConfirm } from "@/components/confirm";
import { useToast } from "@/components/toast";
import { Alert, Button, ButtonLink, Card, EmptyState, Field, Input, Loading, Select, Textarea } from "@/components/ui";
import {
  api,
  EngineError,
  fullErrorMessage,
  type ChapterScenes,
  type Job,
  type SceneType,
  type SceneTypeId,
  type SeriesLocation,
} from "@/lib/api";
import { useEngineData, useUnsavedWarning } from "@/lib/hooks";
import { isFinished, useJob } from "@/lib/jobs";
import {
  MAX_PAGES_PER_SCENE,
  fromDraft,
  mergeWithNext,
  moveScene,
  newScene,
  pageSpans,
  toDraft,
  totalPages,
  totalStatus,
  type DraftScene,
} from "@/lib/scenes";
import { useChapter } from "../chapter-context";
import { readAuthor, saveAuthor } from "../stages";
import { StepAlert } from "../step-alert";

const SYNOPSIS_FIRST = "écris d'abord le synopsis ou le script brut du chapitre (onglet Scénario) : les scènes partent de lui.";
const DATE = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });

interface Draft {
  scenes: DraftScene[];
  deferred: string;
}

const draftOf = (data: ChapterScenes): Draft => ({ scenes: toDraft(data.scenes), deferred: data.deferred.join("\n") });
const deferredList = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

/**
 * Étape « Scènes » (avant le Scénario) : la liste des scènes du chapitre, chacune avec son type (et son tempo), son
 * nombre de pages et son résumé. L'auteur la retouche puis clique sur « Valider les scènes » — le rôle de l'éditeur.
 */
export default function ScenesPage() {
  const { chapter, reloadStages } = useChapter();
  const scenes = useEngineData(() => api.getScenes(chapter.id), [chapter.id]);
  const places = useEngineData(() => api.listLocations(chapter.project_id), [chapter.project_id]);
  const lastJob = useEngineData(() => api.chapterJobs(chapter.id, "scenes").then((j) => j[0] ?? null), [chapter.id]);

  const [edited, setEdited] = useState<Draft | null>(null);
  const base = useMemo(() => (scenes.data ? draftOf(scenes.data) : null), [scenes.data]);
  const draft = edited ?? base;
  const dirty = edited !== null;
  useUnsavedWarning(dirty);

  const [busy, setBusy] = useState<"save" | "validate" | "propose" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [started, setStarted] = useState<Job | null>(null);
  const toast = useToast();
  const confirm = useConfirm();

  const current = started ?? lastJob.data ?? null;
  const job = useJob(current, (done) => {
    if (done.status === "succeeded") {
      toast("Liste des scènes proposée");
      setEdited(null);
      scenes.reload();
      reloadStages();
    }
  });
  const running = job !== null && !isFinished(job);

  function edit(update: (d: Draft) => Draft) {
    setEdited((d) => update(d ?? base ?? { scenes: [], deferred: "" }));
  }
  const editScenes = (update: (list: DraftScene[]) => DraftScene[]) => edit((d) => ({ ...d, scenes: update(d.scenes) }));

  async function propose() {
    setError(null);
    const hasScenes = (draft?.scenes.length ?? 0) > 0;
    if (hasScenes) {
      const ok = await confirm({
        title: "Redemander une proposition ?",
        message: dirty
          ? "La liste actuelle et tes retouches non enregistrées seront remplacées par une nouvelle proposition."
          : "La liste actuelle sera remplacée par une nouvelle proposition (à revalider).",
        confirmLabel: "Remplacer la liste",
        danger: dirty,
      });
      if (!ok) return;
    }
    setBusy("propose");
    try {
      setStarted(await api.proposeScenes(chapter.id));
      toast("Découpage en scènes lancé", "info");
    } catch (e) {
      setError(e instanceof EngineError && e.fieldErrors.synopsis ? SYNOPSIS_FIRST : fullErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function save(): Promise<ChapterScenes | null> {
    if (!draft) return null;
    setError(null);
    setFieldErrors({});
    try {
      const saved = await api.saveScenes(chapter.id, fromDraft(draft.scenes), deferredList(draft.deferred));
      scenes.setData(saved);
      setEdited(null);
      reloadStages();
      return saved;
    } catch (e) {
      if (e instanceof EngineError && Object.keys(e.fieldErrors).length) setFieldErrors(e.fieldErrors);
      setError(fullErrorMessage(e));
      return null;
    }
  }

  async function onSave() {
    setBusy("save");
    if (await save()) toast("Scènes enregistrées");
    setBusy(null);
  }

  async function onValidate() {
    setBusy("validate");
    try {
      if (dirty && !(await save())) return;
      const author = readAuthor();
      const out = await api.validateScenes(chapter.id, author);
      if (author) saveAuthor(author);
      scenes.setData(out);
      reloadStages();
      toast("Scènes validées : le scénario peut être écrit");
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (scenes.loading && !scenes.data) return <Loading />;
  if (scenes.error || !scenes.data || !draft) return <Alert>Impossible de charger les scènes : {scenes.error}</Alert>;
  const data = scenes.data;
  if (!data.available)
    return <Alert>Types de scène indisponibles : presets/scene_types.yaml absent ou invalide.</Alert>;

  const target = data.target_page_count;
  const total = totalPages(draft.scenes);
  const status = totalStatus(total, target);
  const spans = pageSpans(draft.scenes);
  const types = new Map(data.types.map((t) => [t.id, t]));
  const blocked = busy !== null || running;

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 max-w-2xl">
            <h2 className="font-semibold text-zinc-100">Scènes du chapitre</h2>
            <p className="mt-1 text-sm text-zinc-400">
              Comme un mangaka devant son éditeur : la liste des scènes, chacune avec son type et ses pages, avant le
              découpage en cases. Le nombre de pages du chapitre est fixe ; ce qui ne rentre pas est reporté au chapitre
              suivant, jamais tassé.
            </p>
          </div>
          <Button onClick={propose} disabled={blocked} data-testid="propose-scenes">
            {running
              ? "Proposition en cours…"
              : busy === "propose"
                ? "Lancement…"
                : data.scenes.length
                  ? "Redemander une proposition"
                  : "Proposer les scènes"}
          </Button>
        </div>
        {job && <ProposeProgress job={job} onRetry={propose} />}
      </Card>

      {data.legacy && (
        <Alert tone="info">
          Ce chapitre a été écrit sans scènes (ancien mode) : rien ne le bloque. Tu peux tout de même poser ses scènes
          ici avant de relancer le scénario.
        </Alert>
      )}
      {error && (
        <StepAlert message={error} />
      )}

      <section aria-label="Liste des scènes" className="space-y-4">
        <TotalBar total={total} target={target} state={status.state} message={status.message} />

        {draft.scenes.length === 0 ? (
          <EmptyState title="Pas encore de scènes">
            Clique sur « Proposer les scènes » : l&apos;agent part du synopsis, de la bible et des chapitres précédents et
            propose une liste dont les pages font exactement {target}. Tu pourras tout retoucher ici.
            <div className="mt-4">
              <Button variant="secondary" onClick={() => editScenes(() => [newScene("calme", target)])} disabled={blocked}>
                Ou poser les scènes à la main
              </Button>
            </div>
          </EmptyState>
        ) : (
          <ol className="space-y-3" data-testid="scene-list">
            {draft.scenes.map((scene, i) => (
              <SceneRow
                key={scene.key}
                scene={scene}
                index={i}
                count={draft.scenes.length}
                span={spans[i]}
                types={data.types}
                tempo={types.get(scene.type)}
                places={places.data ?? []}
                pageNumbers={scene.id !== undefined ? data.scenes.find((s) => s.id === scene.id)?.page_numbers ?? [] : []}
                errors={fieldErrors}
                disabled={blocked}
                onChange={(next) => editScenes((list) => list.map((s, j) => (j === i ? next : s)))}
                onMove={(delta) => editScenes((list) => moveScene(list, i, delta))}
                onMerge={() => editScenes((list) => mergeWithNext(list, i))}
                onRemove={async () => {
                  const ok = await confirm({
                    title: `Supprimer la scène ${i + 1} ?`,
                    message: "Elle est retirée de la liste (définitif une fois la liste enregistrée).",
                    confirmLabel: "Supprimer la scène",
                    danger: true,
                  });
                  if (ok) editScenes((list) => list.filter((_, j) => j !== i));
                }}
              />
            ))}
          </ol>
        )}

        {draft.scenes.length > 0 && (
          <Button variant="secondary" onClick={() => editScenes((list) => [...list, newScene()])} disabled={blocked}>
            + Ajouter une scène
          </Button>
        )}

        <Card>
          <Field
            label="À reporter au chapitre suivant"
            htmlFor="scenes-deferred"
            hint="Une ligne par moment reporté. Le prochain découpage en scènes du chapitre suivant les reprend en priorité."
          >
            <Textarea
              id="scenes-deferred"
              value={draft.deferred}
              onChange={(e) => edit((d) => ({ ...d, deferred: e.target.value }))}
              placeholder="Rien de reporté."
              disabled={blocked}
            />
          </Field>
        </Card>

        <ValidateBar
          data={data}
          dirty={dirty}
          busy={busy}
          disabled={blocked}
          canValidate={draft.scenes.length > 0 && status.state === "ok"}
          onSave={onSave}
          onValidate={onValidate}
          scenarioHref={`/chapitres/${chapter.id}/scenario`}
        />
      </section>

      <TypesLegend types={data.types} />
    </div>
  );
}

function TotalBar({ total, target, state, message }: { total: number; target: number; state: string; message: string }) {
  const pct = target ? Math.min(100, (total / target) * 100) : 0;
  const tone = state === "ok" ? "bg-emerald-500" : state === "over" ? "bg-red-500" : "bg-amber-400";
  const text = state === "ok" ? "text-emerald-300" : state === "over" ? "text-red-300" : "text-amber-300";
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3" data-testid="scenes-total" data-state={state}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm text-zinc-300">
          Total : <strong className={`tabular-nums ${text}`}>{total}</strong> / {target} pages
        </p>
        <p className={`text-xs ${text}`}>{message}</p>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-800" aria-hidden>
        <div className={`h-full ${tone} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function SceneRow({
  scene,
  index,
  count,
  span,
  types,
  tempo,
  places,
  pageNumbers,
  errors,
  disabled,
  onChange,
  onMove,
  onMerge,
  onRemove,
}: {
  scene: DraftScene;
  index: number;
  count: number;
  span: string;
  types: SceneType[];
  tempo: SceneType | undefined;
  places: SeriesLocation[];
  pageNumbers: number[];
  errors: Record<string, string>;
  disabled: boolean;
  onChange: (s: DraftScene) => void;
  onMove: (delta: number) => void;
  onMerge: () => void;
  onRemove: () => void;
}) {
  const id = `scene-${scene.key}`;
  const set = (patch: Partial<DraftScene>) => onChange({ ...scene, ...patch });
  const err = (field: string) => errors[`scenes.${index}.${field}`];
  return (
    <li className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4" data-testid="scene-row">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-zinc-100">
          Scène {index + 1} <span className="ml-1 text-xs font-normal text-zinc-500">{span}</span>
          {pageNumbers.length > 0 && (
            <span className="ml-2 text-xs font-normal text-zinc-500">
              · scénario : page{pageNumbers.length > 1 ? "s" : ""} {pageNumbers.join(", ")}
            </span>
          )}
        </p>
        <div className="flex flex-wrap gap-1">
          <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => onMove(-1)} disabled={disabled || index === 0} aria-label={`Monter la scène ${index + 1}`}>
            ↑
          </Button>
          <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => onMove(1)} disabled={disabled || index === count - 1} aria-label={`Descendre la scène ${index + 1}`}>
            ↓
          </Button>
          <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={onMerge} disabled={disabled || index === count - 1} title="Fusionner avec la scène suivante">
            Fusionner avec la suivante
          </Button>
          <Button variant="danger" className="!px-2 !py-1 text-xs" onClick={onRemove} disabled={disabled}>
            Supprimer
          </Button>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1.2fr)_8rem]">
        <Field label="Titre" htmlFor={`${id}-title`} error={err("title")}>
          <Input id={`${id}-title`} value={scene.title} maxLength={200} placeholder="Sans titre" onChange={(e) => set({ title: e.target.value })} disabled={disabled} />
        </Field>
        <Field label="Type" htmlFor={`${id}-type`} error={err("type")}>
          <Select id={`${id}-type`} value={scene.type} onChange={(e) => set({ type: e.target.value as SceneTypeId })} disabled={disabled}>
            {types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Pages" htmlFor={`${id}-pages`} error={err("pages")}>
          <Input
            id={`${id}-pages`}
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_PAGES_PER_SCENE}
            value={scene.pages}
            onChange={(e) => {
              const n = Math.round(Number(e.target.value));
              if (Number.isFinite(n)) set({ pages: Math.max(1, Math.min(MAX_PAGES_PER_SCENE, n)) });
            }}
            disabled={disabled}
          />
        </Field>
      </div>
      {tempo && (
        <p className="mt-2 text-xs text-zinc-500" data-testid="scene-tempo">
          <span className="text-zinc-400">Tempo {tempo.name.toLowerCase()} :</span> {tempo.tempo}
        </p>
      )}
      <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
        <Field label="Résumé (1 ou 2 phrases)" htmlFor={`${id}-summary`} error={err("summary")}>
          <Textarea
            id={`${id}-summary`}
            className="!min-h-16"
            value={scene.summary}
            maxLength={1000}
            onChange={(e) => set({ summary: e.target.value })}
            placeholder="Ce qui se passe et ce que la scène change."
            disabled={disabled}
          />
        </Field>
        <Field label="Lieu (facultatif)" htmlFor={`${id}-place`} error={err("location_id")}>
          <Select
            id={`${id}-place`}
            value={scene.location_id ?? ""}
            onChange={(e) => set({ location_id: e.target.value ? Number(e.target.value) : null })}
            disabled={disabled}
          >
            <option value="">— aucun —</option>
            {places.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </li>
  );
}

function ValidateBar({
  data,
  dirty,
  busy,
  disabled,
  canValidate,
  onSave,
  onValidate,
  scenarioHref,
}: {
  data: ChapterScenes;
  dirty: boolean;
  busy: string | null;
  disabled: boolean;
  canValidate: boolean;
  onSave: () => void;
  onValidate: () => void;
  scenarioHref: string;
}) {
  const validated = data.validated && !dirty;
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3"
      data-testid="scenes-validation"
      data-validated={validated ? "yes" : "no"}
    >
      <p className="min-w-0 text-sm">
        {validated ? (
          <span className="text-emerald-300">
            ✓ Scènes validées{data.validated_by ? ` par ${data.validated_by}` : ""}
            {data.validated_at ? ` le ${DATE.format(new Date(data.validated_at))}` : ""} : le scénariste suit cette liste.
          </span>
        ) : dirty ? (
          <span className="text-amber-300">Modifications non enregistrées.</span>
        ) : data.scenes.length ? (
          <span className="text-zinc-400">Pas encore validées : le scénario attend la validation de l&apos;éditeur.</span>
        ) : (
          <span className="text-zinc-500">Aucune scène.</span>
        )}
      </p>
      <div className="flex flex-wrap gap-2">
        {validated && (
          <ButtonLink href={scenarioHref} variant="secondary">
            Aller au Scénario
          </ButtonLink>
        )}
        <Button variant="secondary" onClick={onSave} disabled={disabled || !dirty} data-testid="save-scenes">
          {busy === "save" ? "Enregistrement…" : "Enregistrer"}
        </Button>
        <Button
          onClick={onValidate}
          disabled={disabled || !canValidate || validated}
          title={canValidate ? undefined : "Le total des pages doit être égal à la cible du chapitre"}
          data-testid="validate-scenes"
        >
          {busy === "validate" ? "Validation…" : validated ? "Validées ✓" : "Valider les scènes"}
        </Button>
      </div>
    </div>
  );
}

function ProposeProgress({ job, onRetry }: { job: Job; onRetry: () => void }) {
  if (job.status === "failed" || job.status === "cancelled") {
    return (
      <div className="mt-4 space-y-3" data-testid="scenes-job-error">
        <Alert>
          <strong className="font-semibold">La proposition a échoué.</strong> {job.error ?? job.message}
        </Alert>
        <Button variant="secondary" onClick={onRetry}>
          Réessayer
        </Button>
      </div>
    );
  }
  if (job.status === "succeeded") {
    return (
      <p className="mt-4 text-sm text-emerald-300" role="status" data-testid="scenes-job-done">
        Proposition enregistrée ({job.message}) : relis-la, retouche-la, puis valide-la.
      </p>
    );
  }
  return (
    <div className="mt-4" role="status" aria-live="polite" data-testid="scenes-job-progress">
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

function TypesLegend({ types }: { types: SceneType[] }) {
  return (
    <details className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4" data-testid="scene-types">
      <summary className="cursor-pointer text-sm font-medium text-zinc-200">Types de scène et leur tempo</summary>
      <p className="mt-2 text-xs text-zinc-500">
        Le tempo d&apos;un type précise l&apos;ADN de la série pour les pages de la scène. Ajustable dans la fiche de la
        série (ADN, familles « Tempo »).
      </p>
      <dl className="mt-3 space-y-2">
        {types.map((t) => (
          <div key={t.id}>
            <dt className="text-sm text-zinc-200">{t.name}</dt>
            <dd className="text-xs text-zinc-400">
              {t.description} <span className="text-zinc-500">Tempo : {t.tempo}.</span>
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
