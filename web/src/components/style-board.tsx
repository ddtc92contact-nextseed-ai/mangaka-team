"use client";

import { useEffect, useMemo, useState } from "react";
import { api, engineUrl, fullErrorMessage, type Job, type StyleBoard, type StyleReference, type StyleTrial } from "@/lib/api";
import { generationStep } from "@/lib/generation";
import { useEngineData } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";
import { modalOpen } from "./modal";
import { Alert, Button, Card, Loading, ProgressBar } from "./ui";

export const STYLE_BOARD_ANCHOR = "planche-de-style";

/** Planche de style d'une série : chargée une fois, partagée entre le bandeau et le bloc. */
export function useStyleBoard(projectId: number) {
  return useEngineData(() => api.styleBoard(projectId), [projectId]);
}

type BoardData = ReturnType<typeof useStyleBoard>;

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable));
}

/** Bandeau discret en tête de fiche série tant qu'aucune référence de style n'est retenue. */
export function StyleBoardBanner({ board }: { board: BoardData }) {
  const data = board.data;
  if (!data || !data.configured || data.active || data.problem) return null;
  return (
    <p className="mb-6 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-zinc-800 bg-zinc-900/60 px-4 py-2.5 text-sm text-zinc-400" data-testid="style-board-banner">
      <span>Pas encore de planche de style : la série ne suit que les mots de son style.</span>
      <a href={`#${STYLE_BOARD_ANCHOR}`} className="font-medium text-rose-300 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-rose-400">
        Créer la planche de style →
      </a>
    </p>
  );
}

const QUEUED_NOTICE = "essais en file : ils apparaissent ci-dessous un à un.";

/**
 * « Planche de style » : N essais au palier croquis d'une scène test du genre, avec le style de la série.
 * Le manager en choisit un (clic ou touches 1-4) ou en relance N autres ; l'essai retenu passe au propre
 * et devient la référence de style de la série (jointe aux fiches de référence et, s'il reste une place,
 * aux cases). Les anciennes références restent dans l'historique.
 */
export function StyleBoardCard({ projectId, board }: { projectId: number; board: BoardData }) {
  const data = board.data;
  const [launched, setLaunched] = useState<Job[]>([]);
  const [finished, setFinished] = useState<Set<number>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const jobs = useMemo(() => {
    const byId = new Map<number, Job>();
    for (const j of data?.active_jobs ?? []) byId.set(j.id, j);
    for (const j of launched) byId.set(j.id, j);
    return [...byId.values()].filter((j) => !finished.has(j.id)).sort((a, b) => a.id - b.id);
  }, [data, launched, finished]);
  const trialJobs = jobs.filter((j) => j.params?.mode !== "clean");
  const cleanJobs = jobs.filter((j) => j.params?.mode === "clean");

  const trials = useMemo(() => data?.trials ?? [], [data]);
  const latestBatch = trials[0]?.batch ?? null;
  // Dernière série d'essais, dans l'ordre 1 → N (touches 1-4).
  const latest = useMemo(
    () => trials.filter((t) => t.batch === latestBatch).sort((a, b) => (a.variant ?? 0) - (b.variant ?? 0)),
    [trials, latestBatch],
  );
  const older = trials.filter((t) => t.batch !== latestBatch);
  // Essais déjà terminés de la série en cours (ils apparaissent un à un), sinon la dernière série.
  const pendingBatch = trialJobs[0]?.params?.batch ?? null;
  const shown = pendingBatch !== null && pendingBatch !== latestBatch ? [] : latest;
  const canGenerate = Boolean(data?.configured && !data.problem);
  const choosing = cleanJobs.length > 0;

  async function generate() {
    if (!data) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const newJobs = await api.generateStyleTrials(projectId);
      setLaunched((l) => [...l, ...newJobs]);
      setNotice(`${newJobs.length} ${QUEUED_NOTICE}`);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function choose(trial: StyleTrial) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const job = await api.chooseStyleTrial(trial.id);
      setLaunched((l) => [...l, job]);
      setNotice(`Essai ${trial.variant ?? ""} retenu : passage au propre en cours, il deviendra la référence de style.`);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function reactivate(ref: StyleReference) {
    setError(null);
    try {
      board.setData(await api.activateStyleReference(ref.id));
      setNotice("Référence de style reprise depuis l’historique.");
    } catch (err) {
      setError(fullErrorMessage(err));
    }
  }

  function onJobFinished(job: Job) {
    setFinished((f) => new Set(f).add(job.id));
    // Dernier essai de la série terminé : le message « N essais en file… » n'a plus lieu d'être.
    if (job.params?.mode !== "clean" && trialJobs.every((j) => j.id === job.id)) {
      setNotice((n) => (n?.endsWith(QUEUED_NOTICE) ? null : n));
    }
    if (job.status === "failed") {
      const what = job.params?.mode === "clean" ? "Passage au propre" : `Essai ${String(job.params?.variant ?? "")}`;
      setError(`${what} : ${job.error ?? "échec"}`);
    } else if (job.params?.mode === "clean" && job.status === "succeeded") {
      setNotice("Nouvelle référence de style enregistrée : les prochaines fiches de référence naîtront dans ce style.");
    }
    board.reload();
  }

  // Raccourcis : 1-4 choisit un essai de la dernière série, R relance (hors saisie et hors fenêtre modale).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || modalOpen() || isTyping(e.target)) return;
      if (!canGenerate) return;
      const key = e.key.toLowerCase();
      const n = Number(key);
      if (busy || choosing || trialJobs.length > 0) {
        // Touche ignorée pendant une génération : le dire plutôt que ne rien faire.
        if ((Number.isInteger(n) && n >= 1 && n <= 4) || key === "r") {
          setNotice(choosing ? "Passage au propre en cours : attends sa fin avant de choisir ou de relancer." : "Essais en cours : attends la fin de la série pour choisir (1-4) ou relancer (R).");
          e.preventDefault();
        }
        return;
      }
      if (Number.isInteger(n) && n >= 1 && n <= latest.length) void choose(latest[n - 1]);
      else if (key === "r" && latest.length > 0) void generate();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <Card id={STYLE_BOARD_ANCHOR} className="scroll-mt-6" aria-labelledby="planche-de-style-titre">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="planche-de-style-titre" className="font-semibold text-zinc-100">
            Planche de style
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            Voir le style avant de lancer la série : {data?.trials_per_batch || 4} croquis d&apos;une scène test du genre. L&apos;essai
            retenu passe au propre et devient la référence de style de la série.
          </p>
        </div>
        {data && canGenerate && (
          <Button type="button" onClick={generate} disabled={busy || trialJobs.length > 0} data-testid="style-board-generate">
            {trialJobs.length > 0
              ? "Essais en cours…"
              : busy
                ? "Mise en file…"
                : latest.length
                  ? `Relancer ${data.trials_per_batch} essais`
                  : `Générer ${data.trials_per_batch} essais`}
          </Button>
        )}
      </div>

      {board.loading ? (
        <Loading />
      ) : board.error || !data ? (
        <Alert>{board.error ?? "Planche de style indisponible"}</Alert>
      ) : (
        <div className="space-y-4">
          {data.problem && <Alert tone="info">{data.problem}</Alert>}
          {data.scene_test && (
            <dl className="grid gap-x-4 gap-y-1 text-xs text-zinc-400 sm:grid-cols-[auto_minmax(0,1fr)]">
              <dt className="text-zinc-500">Style</dt>
              <dd>{data.style_names}</dd>
              <dt className="text-zinc-500">Scène test</dt>
              <dd>{data.scene_test}</dd>
            </dl>
          )}
          {error && <Alert>{error}</Alert>}
          {notice && !error && <Alert tone="info">{notice}</Alert>}

          {data.active && <ActiveReference reference={data.active} board={data} />}

          {cleanJobs.map((job) => (
            <PendingJob key={job.id} job={job} label="Passage au propre de l’essai retenu" onFinished={onJobFinished} wide />
          ))}

          {(trialJobs.length > 0 || latest.length > 0) && (
            <section aria-label="Essais">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-zinc-200">
                  {(pendingBatch ?? latestBatch) !== null ? `Essais · série ${String(pendingBatch ?? latestBatch)}` : "Essais"}
                </h3>
                {latest.length > 0 && trialJobs.length === 0 && (
                  <p className="text-xs text-zinc-500">
                    Clique sur un essai ou tape <kbd className="rounded bg-zinc-800 px-1">1</kbd>–
                    <kbd className="rounded bg-zinc-800 px-1">{latest.length}</kbd> pour le choisir,{" "}
                    <kbd className="rounded bg-zinc-800 px-1">R</kbd> pour relancer.
                  </p>
                )}
              </div>
              <ul className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Essais de la planche de style">
                {shown.map((t, i) => (
                  <TrialCard key={t.id} trial={t} index={i + 1} disabled={busy || choosing || trialJobs.length > 0} onChoose={() => choose(t)} />
                ))}
                {trialJobs.map((job) => (
                  <PendingJob key={job.id} job={job} label={`Essai ${String(job.params?.variant ?? "")}/${String(job.params?.count ?? "")}`} onFinished={onJobFinished} />
                ))}
              </ul>
            </section>
          )}

          {(data.history.length > 0 || older.length > 0) && (
            <details className="rounded-md border border-zinc-800 px-3 py-2">
              <summary className="cursor-pointer text-sm text-zinc-400 hover:text-zinc-200">
                Historique · {data.history.length} référence{data.history.length > 1 ? "s" : ""} précédente
                {data.history.length > 1 ? "s" : ""}, {older.length} essai{older.length > 1 ? "s" : ""} plus ancien{older.length > 1 ? "s" : ""}
              </summary>
              {data.history.length > 0 && (
                <ul className="mt-3 grid grid-cols-3 gap-3 md:grid-cols-6" aria-label="Références de style précédentes">
                  {data.history.map((ref) => (
                    <li key={ref.id} className="overflow-hidden rounded-md border border-zinc-800 bg-zinc-950">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={engineUrl(ref.url)} alt={`Ancienne référence de style n° ${ref.id}`} className="aspect-square w-full object-cover" />
                      <Button type="button" variant="ghost" className="w-full rounded-none px-2 py-1 text-xs" onClick={() => reactivate(ref)}>
                        Reprendre
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              {older.length > 0 && (
                <ul className="mt-3 grid grid-cols-3 gap-3 md:grid-cols-6" aria-label="Essais précédents">
                  {older.map((t) => (
                    <li key={t.id} className="overflow-hidden rounded-md border border-zinc-800 bg-zinc-950">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={engineUrl(t.url)} alt={`Essai ${t.variant ?? ""} de la série ${t.batch ?? ""}`} className="w-full object-contain" style={{ aspectRatio: `${t.width} / ${t.height}` }} />
                      <Button
                        type="button"
                        variant="ghost"
                        className="w-full rounded-none px-2 py-1 text-xs"
                        disabled={busy || choosing || !canGenerate}
                        onClick={() => choose(t)}
                      >
                        {t.chosen ? "Retenu · rechoisir" : "Choisir"}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </details>
          )}
        </div>
      )}
    </Card>
  );
}

function ActiveReference({ reference: ref, board }: { reference: StyleReference; board: StyleBoard }) {
  const sheets =
    board.use_reference_sheets === "always"
      ? "jointe à chaque fiche de référence (personnages, objets, décors)"
      : board.use_reference_sheets === "with_subject"
        ? "aux fiches de référence après leur image de départ ou la variante à affiner (pour le trait seulement)"
        : null;
  const panels = board.use_panels === "free_slot" ? "aux cases s’il reste une place parmi leurs images de référence" : null;
  const uses = [sheets, panels].filter(Boolean).join(", ");
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-emerald-700/50 bg-emerald-950/20 p-3 sm:flex-row" data-testid="style-reference-active">
      <a href={engineUrl(ref.url)} target="_blank" rel="noreferrer" className="block w-full shrink-0 sm:w-40">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={engineUrl(ref.url)} alt="Référence de style de la série" className="w-full rounded object-contain" style={{ aspectRatio: `${ref.width} / ${ref.height}` }} />
      </a>
      <div className="space-y-1.5 text-sm">
        <p className="flex items-center gap-2 font-medium text-emerald-200">
          <span className="rounded bg-emerald-500/15 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-emerald-300">Active</span>
          Référence de style
        </p>
        <p className="text-xs text-zinc-400">{uses ? `Utilisée : ${uses}.` : "Non utilisée (désactivée dans presets/defaults.yaml)."}</p>
        {ref.outdated && (
          <p className="text-xs text-amber-300" role="status">
            Le style de la série a changé depuis cette planche : relance des essais pour la remettre à jour.
          </p>
        )}
      </div>
    </div>
  );
}

function TrialCard({ trial: t, index, disabled, onChoose }: { trial: StyleTrial; index: number; disabled: boolean; onChoose: () => void }) {
  return (
    <li className={`overflow-hidden rounded-lg border bg-zinc-950 ${t.chosen ? "border-emerald-600/60" : "border-zinc-800"}`} data-testid="style-trial">
      <button
        type="button"
        onClick={onChoose}
        disabled={disabled}
        className="group relative block w-full bg-zinc-900 focus-visible:outline-2 focus-visible:outline-rose-400 disabled:cursor-not-allowed"
        style={{ aspectRatio: `${t.width} / ${t.height}` }}
        aria-label={`Choisir l’essai ${index}`}
        title={`Choisir l’essai ${index} (touche ${index})`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={engineUrl(t.url)} alt={`Essai ${index}, graine ${String(t.seed ?? "—")}`} className="h-full w-full object-contain group-hover:opacity-90" />
        <span className="absolute left-1.5 top-1.5 inline-flex h-6 min-w-6 items-center justify-center rounded bg-zinc-950/80 px-1 text-xs font-semibold text-zinc-100">
          {index}
        </span>
      </button>
      <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-zinc-400">
        <span className="truncate">seed {String(t.seed ?? "—")}</span>
        {t.chosen ? (
          <span className="rounded bg-emerald-500/15 px-1 py-px text-[10px] text-emerald-300">Retenu</span>
        ) : (
          <button type="button" onClick={onChoose} disabled={disabled} className="text-rose-300 hover:text-rose-200 disabled:opacity-50">
            Choisir
          </button>
        )}
      </div>
    </li>
  );
}

/** Essai ou passage au propre en file ou en cours : progression en direct, annulable. */
function PendingJob({ job: initial, label, onFinished, wide }: { job: Job; label: string; onFinished: (job: Job) => void; wide?: boolean }) {
  const job = useJob(initial, onFinished) ?? initial;
  const [cancelling, setCancelling] = useState(false);

  async function cancel() {
    setCancelling(true);
    try {
      await api.cancelJob(job.id);
    } catch {
      /* déjà terminé : le flux du job le dira */
    }
  }

  const Tag = wide ? "div" : "li";
  return (
    <Tag className="overflow-hidden rounded-lg border border-dashed border-zinc-700 bg-zinc-950" data-testid="style-board-pending">
      <div className={`flex flex-col items-center justify-center gap-2 bg-zinc-900/60 p-3 text-center ${wide ? "" : "aspect-square"}`}>
        <p className="text-xs text-zinc-400">
          {job.status === "pending" ? "En file…" : (generationStep(job.message) ?? job.message ?? "Génération…")}
        </p>
        <ProgressBar value={job.status === "pending" ? 0 : job.progress} label={label} />
      </div>
      <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-zinc-400">
        <span className="truncate">{label}</span>
        <button type="button" onClick={cancel} disabled={cancelling} className="shrink-0 text-red-400 hover:text-red-300 disabled:opacity-50">
          {cancelling ? "Annulation…" : "Annuler"}
        </button>
      </div>
    </Tag>
  );
}
