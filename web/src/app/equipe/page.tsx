"use client";

import Link from "next/link";
import { Alert, Card, EmptyState, Loading, PageHeader } from "@/components/ui";
import { api, type AgentSummary } from "@/lib/api";
import { STATE_TONE, formatDateTime } from "@/lib/agents";
import { useEngineData } from "@/lib/hooks";
import { formatMs } from "@/lib/qc";

const RUN_STATUS: Record<string, string> = { succeeded: "réussi", failed: "en échec", cancelled: "annulé" };

export default function TeamPage() {
  const agents = useEngineData(() => api.listAgents());

  return (
    <>
      <PageHeader
        title="L'équipe"
        subtitle="Les agents qui font le travail, étape par étape. Ouvre un agent pour l'essayer et l'adapter."
      />
      {agents.loading && <Loading />}
      {agents.error && <Alert>{agents.error}</Alert>}
      {agents.data && !agents.data.length && (
        <EmptyState title="Aucun agent déclaré">Ajoute un fichier dans presets/agents/ puis redémarre le moteur.</EmptyState>
      )}
      <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {agents.data?.map((a) => (
          <li key={a.id}>
            <AgentCard agent={a} />
          </li>
        ))}
      </ul>
    </>
  );
}

function AgentCard({ agent }: { agent: AgentSummary }) {
  const run = agent.last_run;
  return (
    <Link href={`/equipe/${agent.id}`} className="group block h-full" data-testid={`agent-${agent.id}`}>
      <Card className="flex h-full flex-col gap-3 transition-colors group-hover:border-rose-400/50">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-2xl"
          >
            {agent.icon}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-xs text-zinc-500">
              Étape {agent.step} · {agent.step_label}
            </p>
            <h2 className="font-semibold text-zinc-50 group-hover:text-rose-300">{agent.name}</h2>
          </div>
          <span
            className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATE_TONE[agent.status.state]}`}
            title={agent.status.detail ?? undefined}
          >
            {agent.status.label}
          </span>
        </div>
        <p className="text-sm text-zinc-400">{agent.role}</p>
        {agent.status.state !== "ready" && agent.status.detail && (
          <p className="text-xs text-red-300">{agent.status.detail}</p>
        )}
        <dl className="mt-auto grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-zinc-800 pt-3 text-xs">
          <dt className="text-zinc-500">Modèle</dt>
          <dd className="truncate text-zinc-200">{agent.model}</dd>
          <dt className="text-zinc-500">Dernier passage</dt>
          <dd className="text-zinc-300">
            {run
              ? `${formatDateTime(run.finished_at)} · ${RUN_STATUS[run.status] ?? run.status} · ${formatMs(run.duration_ms)}`
              : "jamais lancé"}
          </dd>
          <dt className="text-zinc-500">Réglages</dt>
          <dd className="text-zinc-300">
            {agent.version ? `profil global v${agent.version}` : "réglages d'origine"}
            {agent.series_overrides > 0 &&
              ` · ${agent.series_overrides} série${agent.series_overrides > 1 ? "s" : ""} avec réglages propres`}
          </dd>
        </dl>
      </Card>
    </Link>
  );
}
