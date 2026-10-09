"use client";

import Link from "next/link";
import { ComfyBadge, useEngineStatus } from "@/components/engine-status";
import { Alert, ButtonLink, Card, EmptyState, Loading, PageHeader, formatDate } from "@/components/ui";
import { DIRECTIONS } from "@/components/project-form";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

const PROVIDER_LABELS = { llm: "LLM texte", vision: "Contrôle visuel", comfyui: "ComfyUI" } as const;

export default function DashboardPage() {
  const status = useEngineStatus();
  const online = status.state === "online";
  const projects = useEngineData(() => api.listProjects(), [online]);

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        subtitle="Tes projets et l'état de la chaîne de production locale."
        actions={<ButtonLink href="/projets/nouveau">Nouveau projet</ButtonLink>}
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

      <section>
        <h2 className="mb-4 text-lg font-semibold text-zinc-100">Projets</h2>
        {projects.loading && !projects.data ? (
          <Loading />
        ) : projects.error ? (
          <Alert>Impossible de charger les projets : {projects.error}</Alert>
        ) : projects.data?.length ? (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.data.map((p) => (
              <li key={p.id}>
                <Link
                  href={`/projets/${p.id}`}
                  className="block h-full rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 transition-colors hover:border-zinc-600"
                >
                  <p className="font-semibold text-zinc-100">{p.title}</p>
                  <p className="mt-1 line-clamp-2 text-sm text-zinc-400">{p.style || "Style non défini"}</p>
                  <p className="mt-3 text-xs text-zinc-500">
                    {p.character_count} personnage{p.character_count > 1 ? "s" : ""} ·{" "}
                    {DIRECTIONS[p.reading_direction]} · modifié le {formatDate(p.updated_at)}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="Aucun projet pour l'instant">
            <ButtonLink href="/projets/nouveau">Créer mon premier projet</ButtonLink>
          </EmptyState>
        )}
      </section>
    </>
  );
}
