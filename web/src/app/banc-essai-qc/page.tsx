"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { HelpLabel, InfoTip } from "@/components/info-tip";
import { Modal } from "@/components/modal";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, EmptyState, Loading, PageHeader, ProgressBar, Select } from "@/components/ui";
import {
  api,
  fullErrorMessage,
  type BenchApplyResult,
  type BenchDataset,
  type BenchItem,
  type BenchLayerName,
  type BenchRun,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { isFinished, useJob } from "@/lib/jobs";
import { BENCH_LAYERS, DEFECTS, formatMs, formatPct } from "@/lib/qc";
import { ThresholdChart } from "./threshold-chart";

export default function BenchRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <Bench />
    </Suspense>
  );
}

const RUN_STATUS: Record<string, string> = {
  pending: "en file",
  running: "en cours",
  succeeded: "terminé",
  failed: "en échec",
  cancelled: "annulé",
};

function formatDateTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

function Bench() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const projectId = Number(params.get("serie")) || null;
  const chapterId = Number(params.get("chapitre")) || null;
  const runParam = Number(params.get("run")) || null;

  function setQuery(changes: Record<string, number | null>) {
    const q = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v) q.set(k, String(v));
      else q.delete(k);
    }
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  }

  const projects = useEngineData(() => api.listProjects());
  const chapters = useEngineData(() => (projectId ? api.listChapters(projectId) : Promise.resolve([])), [projectId]);
  const dataset = useEngineData(() => api.benchDataset({ project_id: projectId, chapter_id: chapterId }), [projectId, chapterId]);
  const runs = useEngineData(() => api.benchRuns());
  const [vision, setVision] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  const runList = runs.data ?? [];
  const active = runList.find((r) => r.status === "pending" || r.status === "running") ?? null;
  const live = useJob(active?.job ?? null, () => {
    runs.reload();
  });
  const selectedId = runParam ?? runList.find((r) => r.status === "succeeded")?.id ?? runList[0]?.id ?? null;

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const run = await api.startBenchRun({ project_id: projectId, chapter_id: chapterId, vision });
      runs.reload();
      setQuery({ run: run.id });
      toast("Banc d'essai lancé");
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setStarting(false);
    }
  }

  const running = active !== null && !(live && isFinished(live));

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Banc d'essai QC"
        subtitle="Mesure chaque couche du contrôle qualité sur tes cases annotées « bonne » / « mauvaise » avant tout fine-tuning."
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <Card className="space-y-4">
          <h2 className="font-semibold text-zinc-100">
            <HelpLabel help="bench.dataset">Ensemble annoté</HelpLabel>
          </h2>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label htmlFor="bench-serie" className="mb-1 block text-xs text-zinc-400">
                Série
              </label>
              <Select id="bench-serie" value={projectId ?? ""} onChange={(e) => setQuery({ serie: Number(e.target.value) || null, chapitre: null })}>
                <option value="">Toutes les séries</option>
                {(projects.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <label htmlFor="bench-chapitre" className="mb-1 block text-xs text-zinc-400">
                Chapitre
              </label>
              <Select id="bench-chapitre" value={chapterId ?? ""} disabled={!projectId} onChange={(e) => setQuery({ chapitre: Number(e.target.value) || null })}>
                <option value="">Tous les chapitres</option>
                {(chapters.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    Ch. {c.number}
                    {c.title ? ` — ${c.title}` : ""}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <DatasetSummary dataset={dataset.data} error={dataset.error} loading={dataset.loading} />
          <div className="flex flex-wrap items-center gap-3 border-t border-zinc-800 pt-4">
            <span className="flex items-center gap-1.5">
              <Button onClick={start} disabled={starting || running || !dataset.data?.total} data-testid="bench-start">
                {running ? "Banc d'essai en cours…" : "Lancer"}
              </Button>
              <InfoTip help="bench.run" label="Lancer le banc d'essai" />
            </span>
            <span className="flex items-center gap-1.5">
              <label className="flex items-center gap-1.5 text-xs text-zinc-400">
                <input type="checkbox" checked={vision} onChange={(e) => setVision(e.target.checked)} className="accent-rose-500" />
                Inclure la vision (lente, jamais pendant une génération)
              </label>
              <InfoTip help="bench.vision" label="Inclure la vision" />
            </span>
          </div>
          {active && running && (
            <div className="space-y-1.5" aria-live="polite" data-testid="bench-progress">
              <p className="text-xs text-zinc-300">
                {(live ?? active.job)?.status === "pending"
                  ? "En file : le banc passe après les générations et contrôles en cours."
                  : `${(live ?? active.job)?.message || "Mesure en cours…"} · ${(live ?? active.job)?.progress ?? 0} %`}
              </p>
              <ProgressBar value={(live ?? active.job)?.progress ?? 0} label="Progression du banc d'essai" />
            </div>
          )}
        </Card>

        <Card className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold text-zinc-100">
              <HelpLabel help="bench.history">Historique des runs</HelpLabel>
            </h2>
            {runList.length > 0 && <span className="text-xs text-zinc-500">{runList.length} run{runList.length > 1 ? "s" : ""}</span>}
          </div>
          {runs.loading && !runs.data ? (
            <Loading />
          ) : runs.error && !runs.data ? (
            <Alert>Impossible de charger l&apos;historique : {runs.error}</Alert>
          ) : !runList.length ? (
            <p className="text-sm text-zinc-500">Aucun run pour l&apos;instant : annote des cases puis clique « Lancer ».</p>
          ) : (
            <ul className="max-h-64 divide-y divide-zinc-800 overflow-y-auto rounded-md border border-zinc-800 text-sm" data-testid="bench-runs">
              {runList.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setQuery({ run: r.id })}
                    aria-current={r.id === selectedId ? "true" : undefined}
                    className={`flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left hover:bg-zinc-800/60 focus-visible:outline-2 focus-visible:outline-rose-400 ${r.id === selectedId ? "bg-zinc-800/80" : ""}`}
                  >
                    <span className="min-w-0">
                      <span className="text-zinc-100">Run {r.id}</span>
                      <span className="ml-2 text-xs text-zinc-500">
                        {formatDateTime(r.created_at)} · {r.scope} · {r.sample_count} case{r.sample_count > 1 ? "s" : ""}
                        {!r.vision ? " · sans vision" : ""}
                      </span>
                    </span>
                    <span className="text-xs tabular-nums text-zinc-400">
                      {r.status === "succeeded" && r.layers.combined
                        ? `précision ${formatPct(r.layers.combined.precision)} · rappel ${formatPct(r.layers.combined.recall)}`
                        : RUN_STATUS[r.status]}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {selectedId !== null && (
        <RunReport
          key={`${selectedId}-${runList.find((r) => r.id === selectedId)?.status ?? ""}`}
          runId={selectedId}
          onApplied={() => runs.reload()}
        />
      )}
    </div>
  );
}

function DatasetSummary({ dataset, error, loading }: { dataset: BenchDataset | null; error: string | null; loading: boolean }) {
  if (loading && !dataset) return <Loading />;
  if (error && !dataset) return <Alert>Impossible de compter les cases annotées : {error}</Alert>;
  if (!dataset) return null;
  const goalMin = dataset.goal_min ?? 50;
  const goalMax = dataset.goal_max ?? 100;
  if (!dataset.total)
    return (
      <EmptyState title="Aucune case annotée">
        Dans l&apos;atelier, ouvre une case puis annote sa version : <kbd className="rounded bg-zinc-800 px-1">B</kbd> bonne,{" "}
        <kbd className="rounded bg-zinc-800 px-1">M</kbd> mauvaise, flèches pour passer à la suivante. Objectif : {goalMin} à {goalMax} cases.
      </EmptyState>
    );
  const defects = DEFECTS.filter((d) => dataset.by_defect[d.id]);
  return (
    <div className="space-y-2" data-testid="bench-dataset">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="text-2xl font-semibold tabular-nums text-zinc-50">{dataset.total}</p>
        <p className="text-sm text-zinc-400">
          case{dataset.total > 1 ? "s" : ""} annotée{dataset.total > 1 ? "s" : ""} · <span className="text-emerald-300">{dataset.good} bonne{dataset.good > 1 ? "s" : ""}</span> ·{" "}
          <span className="text-amber-300">{dataset.bad} mauvaise{dataset.bad > 1 ? "s" : ""}</span>
        </p>
      </div>
      <ProgressBar value={(dataset.total / goalMax) * 100} label={`Cases annotées sur l'objectif de ${goalMax}`} />
      <p className="text-xs text-zinc-500">
        Objectif : {goalMin} à {goalMax} cases
        {dataset.total < goalMin ? ` — encore ${goalMin - dataset.total} pour des mesures fiables` : dataset.total >= goalMax ? " — atteint" : " — minimum atteint"}.
        {!dataset.bad && " Annote aussi des mauvaises cases : sans elles, le rappel n'est pas mesurable."}
      </p>
      {defects.length > 0 && (
        <p className="text-xs text-zinc-500">
          Défauts : {defects.map((d) => `${d.label.toLowerCase()} (${dataset.by_defect[d.id]})`).join(" · ")}
        </p>
      )}
    </div>
  );
}

function Delta({ now, before, better, rate = false }: { now: number | null; before: number | null | undefined; better: "up" | "down"; rate?: boolean }) {
  if (now === null || before === null || before === undefined) return null;
  const d = now - before;
  if (Math.abs(d) < 1e-9) return <span className="ml-1 text-[10px] text-zinc-500">=</span>;
  const good = better === "up" ? d > 0 : d < 0;
  const size = rate ? `${Math.round(Math.abs(d) * 100)} pt` : `${Math.round(Math.abs(d))}`;
  return (
    <span className={`ml-1 text-[10px] ${good ? "text-emerald-400" : "text-amber-400"}`} title="Par rapport au run précédent">
      {d > 0 ? "▲ +" : "▼ −"}
      {size}
    </span>
  );
}

function RunReport({ runId, onApplied }: { runId: number; onApplied: () => void }) {
  const run = useEngineData(() => api.benchRun(runId), [runId]);
  const [layer, setLayer] = useState<BenchLayerName>("combined");
  const [preview, setPreview] = useState<BenchApplyResult | null>(null);
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const toast = useToast();

  if (run.loading && !run.data) return <Loading />;
  if (run.error && !run.data) return <Alert>Impossible de charger le run {runId} : {run.error}</Alert>;
  const r = run.data;
  if (!r) return null;

  async function askApply(data: BenchRun) {
    setApplyBusy(true);
    setApplyError(null);
    setNotice(null);
    try {
      const res = await api.applyBenchThresholds(data.id, false);
      if (!res.changes.length) setNotice(res.message + ".");
      else setPreview(res);
    } catch (e) {
      setApplyError(fullErrorMessage(e));
    } finally {
      setApplyBusy(false);
    }
  }
  async function confirmApply(data: BenchRun) {
    setApplyBusy(true);
    setApplyError(null);
    try {
      const res = await api.applyBenchThresholds(data.id, true);
      setPreview(null);
      setNotice(res.message + ".");
      toast("Seuils enregistrés dans presets/qc.yaml");
      run.reload();
      onApplied();
    } catch (e) {
      setApplyError(fullErrorMessage(e));
    } finally {
      setApplyBusy(false);
    }
  }

  const header = (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold text-zinc-50">Run {r.id}</h2>
        <p className="text-xs text-zinc-500">
          {formatDateTime(r.created_at)} · {r.scope} · {r.sample_count} case{r.sample_count > 1 ? "s" : ""}
          {r.good !== null && ` (${r.good} bonnes, ${r.bad} mauvaises)`} · {r.vision ? "avec la vision" : "sans la vision"} · preset qc.yaml{" "}
          <code className="text-zinc-400">{r.preset_hash ?? "—"}</code>
          {r.preset_hash && r.current_preset_hash && r.preset_hash !== r.current_preset_hash && " (modifié depuis)"}
          {r.applied_at && ` · seuils appliqués le ${formatDateTime(r.applied_at)}`}
        </p>
      </div>
      {r.metrics && (
        <div className="flex flex-wrap gap-2">
          <a href={api.benchExportUrl(r.id, "json")} download className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700" data-testid="export-json">
            Export JSON
          </a>
          <a href={api.benchExportUrl(r.id, "csv")} download className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700" data-testid="export-csv">
            Export CSV
          </a>
          <span className="flex items-center gap-1.5">
            <Button className="!py-1.5 text-xs" onClick={() => askApply(r)} disabled={applyBusy} data-testid="apply-thresholds">
              Appliquer les seuils suggérés
            </Button>
            <InfoTip help="bench.apply" label="Appliquer les seuils suggérés" />
          </span>
        </div>
      )}
    </div>
  );

  if (!r.metrics) {
    return (
      <Card className="mt-6 space-y-3" data-testid="bench-report">
        {header}
        {r.status === "pending" || r.status === "running" ? (
          <p className="text-sm text-zinc-400">Run {RUN_STATUS[r.status]} : le rapport s&apos;affichera à la fin.</p>
        ) : (
          <Alert>
            Run {RUN_STATUS[r.status] ?? r.status} : {r.error ?? "pas de résultat."}
          </Alert>
        )}
      </Card>
    );
  }

  const m = r.metrics;
  const prev = r.previous;
  const lm = m.layers[layer];
  const layerInfo = BENCH_LAYERS.find((l) => l.id === layer)!;
  const errorsOf = (items: BenchItem[]) => {
    const fn = items.filter((i) => i.bad && i.layers[layer]?.flagged === false);
    const fp = items.filter((i) => !i.bad && i.layers[layer]?.flagged === true);
    return { fn, fp };
  };
  const { fn, fp } = errorsOf(r.items);
  const failed = r.items.filter((i) => i.error);

  return (
    <Card className="mt-6 space-y-6" data-testid="bench-report">
      {header}
      {notice && <Alert tone="info">{notice}</Alert>}
      {applyError && !preview && <Alert>{applyError}</Alert>}
      {failed.length > 0 && (
        <Alert>
          {failed.length} case{failed.length > 1 ? "s" : ""} non mesurée{failed.length > 1 ? "s" : ""} : {failed[0].error}
          {failed.length > 1 ? "…" : ""}
        </Alert>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[44rem] text-left text-sm tabular-nums" data-testid="bench-layers">
          <caption className="mb-2 text-left text-xs text-zinc-500">
            Classe positive = mauvaise case. Objectif : rappel ≥ {formatPct(m.target_recall)} (presque aucune mauvaise case laissée passer).
            {prev && ` Écarts par rapport au run ${prev.id}.`}
          </caption>
          <thead className="border-b border-zinc-800 text-xs text-zinc-500">
            <tr>
              <th className="py-2 pr-3 font-normal">
                <HelpLabel help="bench.layers">Couche</HelpLabel>
              </th>
              <th className="py-2 pr-3 font-normal">Cases</th>
              <th className="py-2 pr-3 font-normal">
                <HelpLabel help="bench.precision">Précision</HelpLabel>
              </th>
              <th className="py-2 pr-3 font-normal">
                <HelpLabel help="bench.recall">Rappel</HelpLabel>
              </th>
              <th className="py-2 pr-3 font-normal">
                <HelpLabel help="bench.fp">Faux positifs</HelpLabel>
              </th>
              <th className="py-2 pr-3 font-normal">
                <HelpLabel help="bench.fn">Faux négatifs</HelpLabel>
              </th>
              <th className="py-2 pr-3 font-normal">
                <HelpLabel help="bench.threshold">Seuil actuel → suggéré</HelpLabel>
              </th>
              <th className="py-2 font-normal">Temps moyen</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/70">
            {BENCH_LAYERS.map((l) => {
              const x = m.layers[l.id];
              // Écarts seulement si la couche a été évaluée dans les deux runs (sinon « −3 FN » ne veut rien dire).
              const p = x.evaluated && prev?.layers[l.id]?.evaluated ? prev.layers[l.id] : undefined;
              return (
                <tr key={l.id} className={l.id === layer ? "bg-zinc-800/40" : ""}>
                  <td className="py-2 pr-3">
                    <button type="button" onClick={() => setLayer(l.id)} className="text-left text-zinc-100 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-rose-400">
                      {l.label}
                    </button>
                  </td>
                  <td className="py-2 pr-3 text-zinc-300">
                    {x.evaluated}
                    {x.missing > 0 && <span className="text-xs text-zinc-500"> (+{x.missing} non évaluée{x.missing > 1 ? "s" : ""})</span>}
                  </td>
                  <td className="py-2 pr-3 text-zinc-100">
                    {formatPct(x.precision)}
                    <Delta now={x.precision} before={p?.precision} better="up" rate />
                  </td>
                  <td className="py-2 pr-3 text-zinc-100">
                    {formatPct(x.recall)}
                    <Delta now={x.recall} before={p?.recall} better="up" rate />
                  </td>
                  <td className="py-2 pr-3 text-zinc-300">
                    {x.confusion.fp}
                    <Delta now={x.confusion.fp} before={p?.fp} better="down" />
                  </td>
                  <td className={`py-2 pr-3 ${x.confusion.fn ? "text-amber-300" : "text-zinc-300"}`}>
                    {x.confusion.fn}
                    <Delta now={x.confusion.fn} before={p?.fn} better="down" />
                  </td>
                  <td className="py-2 pr-3 text-zinc-300">
                    {x.current_threshold ?? "—"} →{" "}
                    {x.suggested ? (
                      <span className="text-emerald-300">{x.suggested.threshold}</span>
                    ) : (
                      <span className="text-xs text-zinc-500" title={x.suggestion_note ?? undefined}>
                        aucun
                      </span>
                    )}
                    {x.suggested && !x.threshold_key && <span className="ml-1 text-[10px] text-zinc-500">(indicatif)</span>}
                  </td>
                  <td className="py-2 text-zinc-300">
                    {formatMs(x.mean_ms)}
                    <Delta now={x.mean_ms} before={p?.mean_ms} better="down" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-zinc-500">Temps total moyen par case : {formatMs(m.mean_ms_per_case)}.</p>
      </div>

      <div className="space-y-4">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Couche détaillée">
          {BENCH_LAYERS.map((l) => (
            <button
              key={l.id}
              role="tab"
              type="button"
              aria-selected={l.id === layer}
              onClick={() => setLayer(l.id)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-rose-400 ${l.id === layer ? "bg-rose-500 text-white" : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"}`}
            >
              {l.label}
            </button>
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
          <div className="min-w-0">
            {lm.evaluated ? (
              <ThresholdChart metrics={lm} targetRecall={m.target_recall} variable={layerInfo.variable} />
            ) : (
              <EmptyState title="Couche non évaluée">Elle n&apos;a tourné sur aucune case de ce run (indisponible, sans référence, ou vision exclue).</EmptyState>
            )}
          </div>
          <div className="space-y-4 text-sm">
            <div>
              <h3 className="mb-2 text-xs font-medium text-zinc-400">
                <HelpLabel help="bench.confusion">Matrice de confusion (seuil actuel)</HelpLabel>
              </h3>
              <table className="w-full text-center text-xs tabular-nums" data-testid="confusion-matrix">
                <thead>
                  <tr className="text-zinc-500">
                    <th />
                    <th className="pb-1 font-normal">Signalée</th>
                    <th className="pb-1 font-normal">Passée</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th className="pr-2 text-right font-normal text-zinc-500">Mauvaise</th>
                    <td className="rounded bg-emerald-500/15 p-2 text-emerald-200">{lm.confusion.tp} VP</td>
                    <td className="rounded bg-amber-500/15 p-2 text-amber-200">{lm.confusion.fn} FN</td>
                  </tr>
                  <tr>
                    <th className="pr-2 text-right font-normal text-zinc-500">Bonne</th>
                    <td className="rounded bg-zinc-800 p-2 text-zinc-300">{lm.confusion.fp} FP</td>
                    <td className="rounded bg-zinc-800/50 p-2 text-zinc-300">{lm.confusion.tn} VN</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="space-y-1 text-xs text-zinc-400">
              <p>
                Seuil suggéré :{" "}
                {lm.suggested ? (
                  <span className="text-emerald-300">
                    {lm.suggested.threshold} (précision {formatPct(lm.suggested.precision)}, rappel {formatPct(lm.suggested.recall)}, {lm.suggested.fp} FP)
                  </span>
                ) : (
                  <span>{lm.suggestion_note ?? "aucun"}</span>
                )}
              </p>
              <p className="text-zinc-500">
                {lm.threshold_key ? (
                  <>
                    Appliqué à <code>{lm.threshold_key}</code>
                    {layer === "identity" ? " (÷ 100)" : ""}.
                  </>
                ) : (
                  "Indicatif : aucune clé de qc.yaml ne règle directement ce seuil."
                )}
              </p>
            </div>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2" data-testid="bench-errors">
          <ErrorList title="Mauvaises cases laissées passer (FN)" items={fn} layer={layer} empty="Aucune : toutes les mauvaises cases sont signalées." />
          <ErrorList title="Bonnes cases signalées à tort (FP)" items={fp} layer={layer} empty="Aucune fausse alerte." />
        </div>
      </div>

      <Modal
        open={preview !== null}
        onClose={() => setPreview(null)}
        title="Appliquer les seuils suggérés ?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPreview(null)} disabled={applyBusy}>
              Annuler
            </Button>
            <Button onClick={() => confirmApply(r)} disabled={applyBusy} data-testid="confirm-apply">
              Écrire presets/qc.yaml
            </Button>
          </>
        }
      >
        {preview && (
          <div className="space-y-3 text-sm">
            <p className="text-zinc-300">Ces valeurs de presets/qc.yaml seront modifiées (commentaires conservés, fichier revalidé puis rechargé) :</p>
            <ul className="space-y-1.5" data-testid="apply-changes">
              {preview.changes.map((c) => (
                <li key={c.key} className="rounded-md border border-zinc-800 px-3 py-2">
                  <p className="text-zinc-200">{c.label}</p>
                  <p className="text-xs text-zinc-500">
                    <code>{c.key}</code> : {c.before} → <span className="text-emerald-300">{c.after}</span>
                  </p>
                </li>
              ))}
            </ul>
            {preview.preset_changed && <Alert tone="info">Le preset a changé depuis ce run : les mesures ont été faites avec d&apos;autres réglages.</Alert>}
            {applyError && <Alert>{applyError}</Alert>}
          </div>
        )}
      </Modal>
    </Card>
  );
}

function ErrorList({ title, items, layer, empty }: { title: string; items: BenchItem[]; layer: BenchLayerName; empty: string }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-zinc-400">
        {title} <span className="text-zinc-500">({items.length})</span>
      </h3>
      {!items.length ? (
        <p className="text-xs text-zinc-500">{empty}</p>
      ) : (
        <ul className="max-h-72 space-y-1 overflow-y-auto">
          {items.map((i) => {
            const l = i.layers[layer];
            return (
              <li key={i.image_id}>
                <Link
                  href={`/chapitres/${i.chapter_id}/atelier?page=${i.page_id}&case=${i.panel_id}`}
                  className="block rounded-md border border-zinc-800 px-3 py-2 text-xs hover:border-zinc-600 hover:bg-zinc-800/50 focus-visible:outline-2 focus-visible:outline-rose-400"
                >
                  <span className="block text-zinc-200">{i.label}</span>
                  <span className="block text-zinc-500">
                    {l?.value !== null && l?.value !== undefined ? `valeur ${l.value}` : "non évaluée"}
                    {i.defects.length > 0 && ` · ${i.defects.map((d) => DEFECTS.find((x) => x.id === d)?.label.toLowerCase() ?? d).join(", ")}`}
                    {i.note && ` · « ${i.note} »`}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

