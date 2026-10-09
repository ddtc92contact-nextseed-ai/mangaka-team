"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Avatar } from "@/components/avatar";
import { ChapterList } from "@/components/chapter-list";
import { ProjectForm } from "@/components/project-form";
import { SeriesBible } from "@/components/series-bible";
import { DIRECTIONS, DirectionBadge } from "@/components/reading-direction";
import { SeriesStatusBadge } from "@/components/status";
import { Alert, Button, ButtonLink, Card, Loading, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function ProjectPage() {
  const id = Number(useParams<{ id: string }>().id);
  const router = useRouter();
  const project = useEngineData(() => api.getProject(id), [id]);
  const characters = useEngineData(() => api.listCharacters(id), [id]);
  const [saved, setSaved] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function remove() {
    if (!project.data) return;
    if (!window.confirm(`Supprimer « ${project.data.title} », ses chapitres et ses personnages ? Action définitive.`)) return;
    try {
      await api.deleteProject(id);
      router.push("/projets");
    } catch (err) {
      setDeleteError(errorMessage(err));
    }
  }

  if (project.loading) return <Loading />;
  if (project.error || !project.data) return <Alert>{project.error ?? "Série introuvable"}</Alert>;

  return (
    <>
      <PageHeader
        title={project.data.title}
        subtitle={
          <span className="flex items-center gap-3">
            <Link href="/projets" className="hover:text-zinc-200">
              ← Toutes les séries
            </Link>
            <SeriesStatusBadge status={project.data.status} />
            <DirectionBadge direction={project.data.reading_direction} />
            <span className="hidden sm:inline">{DIRECTIONS[project.data.reading_direction]}</span>
          </span>
        }
        actions={
          <Button variant="danger" onClick={remove}>
            Supprimer
          </Button>
        }
      />
      {deleteError && (
        <div className="mb-4">
          <Alert>{deleteError}</Alert>
        </div>
      )}
      <div className="mb-6">
        <ChapterList projectId={id} />
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card>
          <h2 className="mb-4 font-semibold text-zinc-100">Paramètres</h2>
          {saved && (
            <div className="mb-4">
              <Alert tone="info">Série enregistrée.</Alert>
            </div>
          )}
          <ProjectForm
            key={project.data.updated_at}
            initial={project.data}
            submitLabel="Enregistrer"
            onSaved={(p) => {
              project.setData(p);
              setSaved(true);
            }}
          />
        </Card>
        <Card>
          <div className="mb-4 flex items-center justify-between gap-2">
            <h2 className="font-semibold text-zinc-100">Personnages</h2>
            <ButtonLink href={`/projets/${id}/personnages/nouveau`} variant="secondary">
              Ajouter
            </ButtonLink>
          </div>
          {characters.data?.length ? (
            <ul className="divide-y divide-zinc-800">
              {characters.data.map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/personnages/${c.id}`}
                    className="flex items-center gap-3 py-2 text-sm text-zinc-200 hover:text-rose-300"
                  >
                    <Avatar url={c.reference_images[0]?.url} name={c.name} />
                    <span className="truncate">{c.name}</span>
                    <span className="ml-auto text-xs text-zinc-500">{c.reference_images.length} réf.</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">Aucun personnage.</p>
          )}
        </Card>
      </div>
      <div className="mt-6">
        <SeriesBible projectId={id} />
      </div>
    </>
  );
}
