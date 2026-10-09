"use client";

import Link from "next/link";
import { DIRECTIONS } from "@/components/project-form";
import { Alert, ButtonLink, EmptyState, Loading, PageHeader, formatDate } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function ProjectsPage() {
  const projects = useEngineData(() => api.listProjects());

  return (
    <>
      <PageHeader
        title="Projets"
        subtitle="Une série = un style, un sens de lecture, un format de page et ses personnages."
        actions={<ButtonLink href="/projets/nouveau">Nouveau projet</ButtonLink>}
      />
      {projects.loading ? (
        <Loading />
      ) : projects.error ? (
        <Alert>Impossible de charger les projets : {projects.error}</Alert>
      ) : projects.data?.length ? (
        <div className="overflow-x-auto rounded-xl border border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Titre</th>
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
                  <td className="px-4 py-3 text-zinc-400">{DIRECTIONS[p.reading_direction]}</td>
                  <td className="px-4 py-3 text-zinc-400">{p.page_format}</td>
                  <td className="px-4 py-3 text-zinc-400">{p.character_count}</td>
                  <td className="px-4 py-3 text-zinc-500">{formatDate(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun projet">
          <ButtonLink href="/projets/nouveau">Créer un projet</ButtonLink>
        </EmptyState>
      )}
    </>
  );
}
