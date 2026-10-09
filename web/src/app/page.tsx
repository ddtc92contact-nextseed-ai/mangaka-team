"use client";

import Link from "next/link";
import { ComfyBadge, useEngineStatus } from "@/components/engine-status";
import { QueueList } from "@/components/queue";
import { Alert, ButtonLink, Card, EmptyState, Loading, PageHeader, formatDate } from "@/components/ui";
import { DIRECTIONS } from "@/components/reading-direction";
import { ChapterStatusBadge, SeriesStatusBadge, formatPlannedDate } from "@/components/status";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

const PROVIDER_LABELS = {
  llm: "LLM texte",
  vision: "Contrôle visuel",
  comfyui: "ComfyUI",
  embedding: "Embeddings (savoir-faire)",
} as const;

export default function DashboardPage() {
  const status = useEngineStatus();
  const online = status.state === "online";
  const projects = useEngineData(() => api.listProjects(), [online]);
  const week = useEngineData(() => api.upcomingChapters(7), [online]);

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        subtitle="Tes séries, les chapitres à sortir cette semaine et l'état de la chaîne de production locale."
        actions={<ButtonLink href="/projets/nouveau">Nouvelle série</ButtonLink>}
      />

      <section className="mb-10 grid gap-4 md:grid-cols-3" aria-label="État des services">
        <Card>
          <p className="text-xs uppercase tracking-wide text-zinc-500">Moteur</p>
          <p className="mt-2 text-lg font-semibold" data-testid="engine-state">
            {status.state === "loading" && <span className="text-zinc-400">Connexion…</span>}
            {status.state === "offline" && <span className="text-red-400">Moteur hors ligne</span>}
            {status.state === "online" && <span className="text-emerald-400">Moteur OK</span>}
          </p>
          {online && (
            <p className="mt-1 text-xs text-zinc-500">
              v{status.health.engine.version}
              {status.health.mock && " · mode mock (aucun appel réseau, aucun GPU)"}
            </p>
          )}
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-zinc-500">ComfyUI</p>
          <div className="mt-2">
            <ComfyBadge />
          </div>
          {online && (
            <p className="mt-2 text-xs text-zinc-500">
              {status.health.comfyui.detail ?? status.health.comfyui.url} · en cours :{" "}
              {status.health.comfyui.queue_running} · en attente : {status.health.comfyui.queue_pending}
            </p>
          )}
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-zinc-500">Fournisseurs</p>
          {online ? (
            <ul className="mt-2 space-y-1 text-sm">
              {(Object.keys(PROVIDER_LABELS) as (keyof typeof PROVIDER_LABELS)[]).map((kind) => {
                const p = status.health.providers[kind];
                return (
                  <li key={kind} className="flex justify-between gap-2" title={p.detail ?? undefined}>
                    <span className="text-zinc-400">{PROVIDER_LABELS[kind]}</span>
                    <span className={p.ok ? "text-zinc-200" : "text-red-400"}>
                      {p.name}
                      {!p.ok && " ⚠"}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">—</p>
          )}
        </Card>
      </section>

      {online && status.health.presets.issues > 0 && (
        <div className="mb-6">
          <Alert>
            {status.health.presets.issues} preset(s) invalide(s) ignoré(s). Détails :{" "}
            <code className="text-xs">GET /presets</code> du moteur.
          </Alert>
        </div>
      )}
      {online &&
        Object.entries(status.health.providers)
          .filter(([, p]) => !p.ok)
          .map(([kind, p]) => (
            <div key={kind} className="mb-6">
              <Alert>{p.detail}</Alert>
            </div>
          ))}

      <section id="file-attente" className="mb-10 scroll-mt-16" aria-labelledby="queue-title">
        <h2 id="queue-title" className="mb-4 text-lg font-semibold text-zinc-100">
          File d&apos;attente ComfyUI
        </h2>
        <Card>
          <QueueList />
        </Card>
      </section>

      <section className="mb-10" aria-labelledby="week-title">
        <h2 id="week-title" className="mb-4 text-lg font-semibold text-zinc-100">
          Chapitres de la semaine
        </h2>
        {week.loading && !week.data ? (
          <Loading />
        ) : week.error ? (
          <Alert>Impossible de charger les chapitres : {week.error}</Alert>
        ) : week.data?.length ? (
          <ul className="divide-y divide-zinc-800 rounded-xl border border-zinc-800 bg-zinc-900/60">
            {week.data.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/chapitres/${c.id}`}
                  className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm hover:bg-zinc-900"
                >
                  <span className="w-28 text-zinc-300">{formatPlannedDate(c.planned_date)}</span>
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-medium text-zinc-100">{c.series_title}</span>
                    <span className="text-zinc-400">
                      {" "}
                      · ch. {c.number}
                      {c.title ? ` — ${c.title}` : ""}
                    </span>
                  </span>
                  <ChapterStatusBadge status={c.status} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="Aucun chapitre prévu dans les 7 prochains jours">
            Renseigne la date de publication prévue d&apos;un chapitre pour le voir ici.
          </EmptyState>
        )}
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold text-zinc-100">Séries</h2>
        {projects.loading && !projects.data ? (
          <Loading />
        ) : projects.error ? (
          <Alert>Impossible de charger les séries : {projects.error}</Alert>
        ) : projects.data?.length ? (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.data.map((p) => (
              <li key={p.id}>
                <Link
                  href={`/projets/${p.id}`}
                  className="block h-full rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 transition-colors hover:border-zinc-600"
                >
                  <p className="flex items-center justify-between gap-2 font-semibold text-zinc-100">
                    <span className="truncate">{p.title}</span>
                    <SeriesStatusBadge status={p.status} />
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm text-zinc-400">{p.style || "Style non défini"}</p>
                  <p className="mt-3 text-xs text-zinc-500">
                    {p.chapter_count} chapitre{p.chapter_count > 1 ? "s" : ""} · {p.character_count} personnage
                    {p.character_count > 1 ? "s" : ""} ·{" "}
                    {DIRECTIONS[p.reading_direction]} · modifié le {formatDate(p.updated_at)}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="Aucune série pour l'instant">
            <ButtonLink href="/projets/nouveau">Créer ma première série</ButtonLink>
          </EmptyState>
        )}
      </section>
    </>
  );
}
