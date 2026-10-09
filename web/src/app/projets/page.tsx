"use client";

import Link from "next/link";
import { DirectionBadge } from "@/components/reading-direction";
import { SeriesStatusBadge } from "@/components/status";
import { Alert, ButtonLink, EmptyState, Loading, PageHeader, formatDate } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function ProjectsPage() {
  const projects = useEngineData(() => api.listProjects());

  return (
    <>
      <PageHeader
        title="Séries"
        subtitle="Une série = un style, un sens de lecture, un format de page, ses personnages et ses chapitres."
        actions={<ButtonLink href="/projets/nouveau">Nouvelle série</ButtonLink>}
      />
      {projects.loading ? (
        <Loading />
      ) : projects.error ? (
        <Alert>Impossible de charger les séries : {projects.error}</Alert>
      ) : projects.data?.length ? (
        <div className="overflow-x-auto rounded-xl border border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Titre</th>
                <th className="px-4 py-3 font-medium">Statut</th>
                <th className="px-4 py-3 font-medium">Chapitres</th>
                <th className="px-4 py-3 font-medium">Sens de lecture</th>
                <th className="px-4 py-3 font-medium">Format</th>
                <th className="px-4 py-3 font-medium">Personnages</th>
                <th className="px-4 py-3 font-medium">Modifié</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {projects.data.map((p) => (
                <tr key={p.id} className="hover:bg-zinc-900/60">
                  <td className="px-4 py-3">
                    <Link href={`/projets/${p.id}`} className="font-medium text-zinc-100 hover:text-rose-300">
                      {p.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <SeriesStatusBadge status={p.status} />
                  </td>
                  <td className="px-4 py-3 text-zinc-400">{p.chapter_count}</td>
                  <td className="px-4 py-3">
                    <DirectionBadge direction={p.reading_direction} />
                  </td>
                  <td className="px-4 py-3 text-zinc-400">{p.page_format}</td>
                  <td className="px-4 py-3 text-zinc-400">{p.character_count}</td>
                  <td className="px-4 py-3 text-zinc-500">{formatDate(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune série">
          <ButtonLink href="/projets/nouveau">Créer une série</ButtonLink>
        </EmptyState>
      )}
    </>
  );
}
