"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { AgentOverrides } from "@/components/agent-overrides";
import { ChapterList } from "@/components/chapter-list";
import { LibraryList, LibraryTabs } from "@/components/library";
import { EstimateLabel } from "@/components/estimate";
import { ProjectForm } from "@/components/project-form";
import { SeriesBible } from "@/components/series-bible";
import { StyleBoardBanner, StyleBoardCard, useStyleBoard } from "@/components/style-board";
import { DIRECTIONS, DirectionBadge } from "@/components/reading-direction";
import { SeriesStatusBadge } from "@/components/status";
import { Alert, Button, ButtonLink, Card, Loading, PageHeader } from "@/components/ui";
import { api, errorMessage, type LibraryKind } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { libraryHref, newEntryHref } from "@/lib/library";

export default function ProjectPage() {
  const id = Number(useParams<{ id: string }>().id);
  const router = useRouter();
  const project = useEngineData(() => api.getProject(id), [id]);
  const styleBoard = useStyleBoard(id);
  const [tab, setTab] = useState<LibraryKind>("character");
  const [saved, setSaved] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function remove() {
    if (!project.data) return;
    if (!window.confirm(`Supprimer « ${project.data.title} », ses chapitres et sa bibliothèque (personnages, objets, décors) ? Action définitive.`)) return;
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
            <EstimateLabel projectId={id} />
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
      <StyleBoardBanner board={styleBoard} />
      <div className="mb-6">
        <ChapterList projectId={id} />
      </div>
      <div className="mb-6">
        <StyleBoardCard projectId={id} board={styleBoard} />
      </div>
      <div className="mb-6">
        <AgentOverrides projectId={id} />
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
              styleBoard.reload(); // packs changés : scène test et style des essais à jour
            }}
          />
        </Card>
        <Card>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="font-semibold text-zinc-100">
              <Link href={libraryHref(id, tab)} className="hover:text-rose-300">
                Bibliothèque
              </Link>
            </h2>
            <ButtonLink href={newEntryHref(tab, id)} variant="secondary">
              Ajouter
            </ButtonLink>
          </div>
          <div className="mb-2">
            <LibraryTabs value={tab} onChange={setTab} idPrefix="serie-bibliotheque" />
          </div>
          <div role="tabpanel" id="serie-bibliotheque-panel" aria-labelledby={`serie-bibliotheque-tab-${tab}`}>
            <LibraryList key={tab} kind={tab} projectId={id} compact />
          </div>
        </Card>
      </div>
      <div className="mt-6">
        <SeriesBible projectId={id} />
      </div>
    </>
  );
}
