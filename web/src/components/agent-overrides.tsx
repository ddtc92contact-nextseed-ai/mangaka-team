"use client";

import Link from "next/link";
import { Alert, ButtonLink, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

/** Page série : « Réglages des agents pour cette série » (surcharges du profil global). */
export function AgentOverrides({ projectId }: { projectId: number }) {
  const overrides = useEngineData(() => api.seriesAgents(projectId), [projectId]);
  return (
    <Card data-testid="series-agents">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Réglages des agents pour cette série</h2>
        <ButtonLink href="/equipe" variant="secondary">
          L&apos;équipe
        </ButtonLink>
      </div>
      {overrides.error && <Alert>{overrides.error}</Alert>}
      {overrides.data && overrides.data.length === 0 && (
        <p className="text-sm text-zinc-500">
          Aucun réglage propre : tous les agents suivent le profil global de l&apos;équipe. Pour adapter un agent à cette
          série seulement, ouvre-le dans « L&apos;équipe » et choisis cette série.
        </p>
      )}
      {overrides.data && overrides.data.length > 0 && (
        <ul className="divide-y divide-zinc-800">
          {overrides.data.map((o) => (
            <li key={o.agent_id}>
              <Link
                href={`/equipe/${o.agent_id}?serie=${projectId}`}
                className="flex flex-wrap items-center gap-3 py-2 text-sm text-zinc-200 hover:text-rose-300"
              >
                <span aria-hidden className="text-lg">
                  {o.icon}
                </span>
                <span className="font-medium">{o.name}</span>
                <span className="min-w-0 flex-1 truncate text-xs text-zinc-500">
                  {o.settings.map((s) => s.label).join(" · ")}
                </span>
                <span className="text-xs text-zinc-500">v{o.version}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
