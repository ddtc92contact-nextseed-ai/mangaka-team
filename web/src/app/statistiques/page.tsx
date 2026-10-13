"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { useJournalSettings } from "@/components/journal";
import { Alert, Card, EmptyState, Input, Loading, PageHeader, Select } from "@/components/ui";
import { formatDateTime } from "@/lib/agents";
import { api, type MeasureKey, type StageOverrideRow, type StatsFilter, type StatsRow } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { formatPct, rateLabel } from "@/lib/journal";

export default function StatsRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <Statistics />
    </Suspense>
  );
}

const MEASURE_ORDER: MeasureKey[] = ["dark_pct", "black_pct", "white_pct", "saturation_pct", "line_density_pct"];

/** Filtres dans l'URL (la page se recharge et se partage telle quelle). */
type QueryKey = "serie" | "chapitre" | "du" | "au" | "palier" | "sorte";

function Statistics() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const filter: StatsFilter = {
    project_id: Number(params.get("serie")) || null,
    chapter_id: Number(params.get("chapitre")) || null,
    date_from: params.get("du") || null,
    date_to: params.get("au") || null,
    tier: params.get("palier") || null,
    kind: params.get("sorte") || null,
  };
  const key = JSON.stringify(filter);

  function setQuery(changes: Partial<Record<QueryKey, string | number | null>>) {
    const q = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v) q.set(k, String(v));
      else q.delete(k);
    }
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  }

  const settings = useJournalSettings();
  const projects = useEngineData(() => api.listProjects());
  const chapters = useEngineData(
    () => (filter.project_id ? api.listChapters(filter.project_id) : Promise.resolve([])),
    [filter.project_id],
  );
  const presets = useEngineData(() => api.workflowPresets());
  const stats = useEngineData(() => api.stats(filter), [key]);
  const tiers = [...new Set((presets.data ?? []).map((p) => p.tier).filter((t): t is string => Boolean(t)))];
  const measures = MEASURE_ORDER.map((k) => ({
    key: k,
    label: settings?.measures.find((m) => m.key === k)?.label ?? k,
    target: settings?.measures.find((m) => m.key === k)?.target ?? null,
  }));
  const data = stats.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Statistiques"
        subtitle="Ce qui marche, d'après tes verdicts : taux de validation et tonalité moyenne des cases générées, par palier, CFG, plan, fiche de savoir-faire, finition et longueur de prompt."
        actions={
          <>
            <a
              href={api.statsExportUrl("csv", filter)}
              download
              className="rounded-md bg-zinc-800 px-3 py-2 text-sm font-medium text-zinc-100 hover:bg-zinc-700"
              data-testid="export-csv"
            >
              Exporter en CSV
            </a>
            <a
              href={api.statsExportUrl("json", filter)}
              download
              className="rounded-md bg-zinc-800 px-3 py-2 text-sm font-medium text-zinc-100 hover:bg-zinc-700"
              data-testid="export-json"
            >
              Exporter en JSON
            </a>
          </>
        }
      />

      <Card className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6" data-testid="stats-filters">
        <div>
          <label htmlFor="stats-serie" className="mb-1 block text-xs text-zinc-400">
            Série
          </label>
          <Select id="stats-serie" value={filter.project_id ?? ""} onChange={(e) => setQuery({ serie: Number(e.target.value) || null, chapitre: null })}>
            <option value="">Toutes les séries</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="stats-chapitre" className="mb-1 block text-xs text-zinc-400">
            Chapitre
          </label>
          <Select id="stats-chapitre" value={filter.chapter_id ?? ""} disabled={!filter.project_id} onChange={(e) => setQuery({ chapitre: Number(e.target.value) || null })}>
            <option value="">Tous les chapitres</option>
            {(chapters.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                Chapitre {c.number}
                {c.title ? ` — ${c.title}` : ""}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="stats-du" className="mb-1 block text-xs text-zinc-400">
            Du
          </label>
          <Input id="stats-du" type="date" value={filter.date_from ?? ""} onChange={(e) => setQuery({ du: e.target.value || null })} />
        </div>
        <div>
          <label htmlFor="stats-au" className="mb-1 block text-xs text-zinc-400">
            Au (inclus)
          </label>
          <Input id="stats-au" type="date" value={filter.date_to ?? ""} onChange={(e) => setQuery({ au: e.target.value || null })} />
        </div>
        <div>
          <label htmlFor="stats-palier" className="mb-1 block text-xs text-zinc-400">
            Palier
          </label>
          <Select id="stats-palier" value={filter.tier ?? ""} onChange={(e) => setQuery({ palier: e.target.value || null })}>
            <option value="">Tous les paliers</option>
            {tiers.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label htmlFor="stats-sorte" className="mb-1 block text-xs text-zinc-400">
            Sorte
          </label>
          <Select id="stats-sorte" value={filter.kind ?? ""} onChange={(e) => setQuery({ sorte: e.target.value || null })}>
            <option value="">Toutes (cases)</option>
            {Object.entries(settings?.kinds ?? {}).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </Select>
        </div>
      </Card>

      {stats.error && <Alert>{stats.error}</Alert>}
      {!data && !stats.error && <Loading />}
      {data && (
        <>
          {data.low_data && (
            <Alert tone="info">
              <span data-testid="low-data-warning">
                Peu de données : {data.total.judged} case{data.total.judged > 1 ? "s" : ""} jugée
                {data.total.judged > 1 ? "s" : ""} (il en faut au moins {data.low_data_below}). Les taux ci-dessous ne
                veulent encore rien dire : juge tes cases dans l&apos;atelier (G = je garde, X = je rejette).
              </span>
            </Alert>
          )}
          <Card className="space-y-2" data-testid="stats-total">
            <h2 className="text-sm font-medium text-zinc-300">Ensemble</h2>
            {data.total.generations === 0 ? (
              <EmptyState title="Aucune génération dans le journal pour ces filtres">
                Chaque génération ComfyUI (case, croquis, réparation…) s&apos;y ajoute dès maintenant.
              </EmptyState>
            ) : (
              <StatsTable rows={[{ value: "Toutes", ...data.total }]} measures={measures} label="Ensemble" />
            )}
          </Card>
          {data.total.generations > 0 &&
            data.breakdowns.map((b) => (
              <Card key={b.key} className="space-y-2" data-testid={`breakdown-${b.key}`}>
                <h2 className="text-sm font-medium text-zinc-300">Par {b.label === b.label.toUpperCase() ? b.label : b.label.toLowerCase()}</h2>
                <StatsTable rows={b.rows} measures={measures} label={b.label} />
              </Card>
            ))}
          <StageOverrides rows={data.stage_overrides ?? []} />
          {settings?.tonality_reference && (
            <p className="text-xs text-zinc-500">
              Cible de tonalité ({settings.tonality_reference}) :{" "}
              {measures
                .filter((m) => m.target !== null)
                .map((m) => `${m.label.toLowerCase()} ${formatPct(m.target)}`)
                .join(" · ")}{" "}
              — réglable dans presets/qc_tonality.yaml. Export local : le fichier est produit par le moteur sur cette machine.
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** « Passer outre » une étape vitale d'un chapitre (garde d'étapes) : qui, quand, quoi, combien laissé passer. */
function StageOverrides({ rows }: { rows: StageOverrideRow[] }) {
  return (
    <Card className="space-y-2" data-testid="stage-overrides">
      <h2 className="text-sm font-medium text-zinc-300">Étapes forcées</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-zinc-500">
          Aucune étape forcée pour ces filtres : chaque chapitre a franchi ses étapes vitales réglées.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
                <th className="py-1.5 pr-3 font-normal">Date</th>
                <th className="py-1.5 pr-3 font-normal">Chapitre</th>
                <th className="py-1.5 pr-3 font-normal">Étape</th>
                <th className="py-1.5 pr-3 text-right font-normal">Laissé passer</th>
                <th className="py-1.5 pr-3 font-normal">Auteur</th>
                <th className="py-1.5 pr-3 font-normal">Raison</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-zinc-900">
                  <td className="py-1.5 pr-3 tabular-nums text-zinc-400">{formatDateTime(r.at)}</td>
                  <td className="py-1.5 pr-3 text-zinc-200">
                    {r.chapter_title === null ? (
                      <span className="text-zinc-500">chapitre {r.chapter_number ?? "?"} (supprimé)</span>
                    ) : (
                      <Link href={`/chapitres/${r.chapter_id}`} className="hover:text-rose-300">
                        Chapitre {r.chapter_number}
                        {r.chapter_title ? ` — ${r.chapter_title}` : ""}
                      </Link>
                    )}
                  </td>
                  <td className="py-1.5 pr-3 text-zinc-200">{r.stage_label}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-zinc-300">
                    {r.faults}/{r.total}
                  </td>
                  <td className="py-1.5 pr-3 text-zinc-300">{r.author || "—"}</td>
                  <td className="py-1.5 pr-3 text-zinc-400">{r.note || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function StatsTable({
  rows,
  measures,
  label,
}: {
  rows: (StatsRow & { value: string })[];
  measures: { key: MeasureKey; label: string; target: number | null }[];
  label: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[48rem] text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
            <th className="py-1.5 pr-3 font-normal">{label}</th>
            <th className="py-1.5 pr-3 text-right font-normal">Générations</th>
            <th className="py-1.5 pr-3 text-right font-normal">Jugées</th>
            <th className="py-1.5 pr-3 text-right font-normal">Taux de validation</th>
            <th className="py-1.5 pr-3 text-right font-normal">Régén. · retouches</th>
            {measures.map((m) => (
              <th key={m.key} className="py-1.5 pr-3 text-right font-normal" title={m.target !== null ? `Cible : ${formatPct(m.target)}` : undefined}>
                {m.label}
                {m.target !== null && <span className="block text-[10px] text-zinc-600">cible {formatPct(m.target)}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.value} className="border-b border-zinc-900">
              <td className="py-1.5 pr-3 text-zinc-200">
                {r.value}
                {r.low_data && (
                  <span className="ml-2 rounded bg-amber-500/15 px-1 py-px text-[10px] font-medium text-amber-300" title="Moins de cases jugées que le seuil : à prendre avec des pincettes">
                    peu de données
                  </span>
                )}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-zinc-300">{r.generations}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-zinc-300">{r.judged}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-zinc-100">{rateLabel(r.validation_rate, r.validated, r.judged)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-zinc-400">
                {r.regenerated} · {r.edited}
              </td>
              {measures.map((m) => (
                <td key={m.key} className="py-1.5 pr-3 text-right tabular-nums text-zinc-300">
                  {formatPct(r.means[m.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
