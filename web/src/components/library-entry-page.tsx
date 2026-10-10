"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Button, Card, Loading, PageHeader } from "@/components/ui";
import { api, errorMessage, type LibraryKind } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { LIBRARY_KINDS, entryHref, libraryHref } from "@/lib/library";
import { LibraryEntryForm, ReferenceImages } from "./library-entry-form";
import { ReferenceStudio } from "./reference-studio";

/** Fiche d'un personnage, d'un objet ou d'un décor : champs, images de référence, suppression. */
export function LibraryEntryPage({ kind, id }: { kind: LibraryKind; id: number }) {
  const info = LIBRARY_KINDS[kind];
  const router = useRouter();
  const entry = useEngineData(() => api.getLibraryEntry(kind, id), [kind, id]);
  const searchParams = useSearchParams();
  // Erreur d'upload transmise par la page de création : figée au montage, puis retirée de l'URL.
  const [uploadError] = useState(() => searchParams.get("erreur_images"));
  useEffect(() => {
    if (uploadError) router.replace(entryHref(kind, id));
  }, [uploadError, router, kind, id]);
  const [saved, setSaved] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  if (entry.loading) return <Loading />;
  if (entry.error || !entry.data) return <Alert>{entry.error ?? `Fiche introuvable (${info.singular})`}</Alert>;
  const e = entry.data;

  async function remove() {
    if (!window.confirm(info.deleteConfirm(e.name))) return;
    try {
      await api.deleteLibraryEntry(kind, e.id);
      router.push(libraryHref(e.project_id, kind));
    } catch (err) {
      setDeleteError(errorMessage(err));
    }
  }

  return (
    <>
      <PageHeader
        title={e.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <Link href={libraryHref(e.project_id, kind)} className="hover:text-zinc-200">
              ← Bibliothèque · {info.tab}
            </Link>
            <Link href={`/projets/${e.project_id}`} className="hover:text-zinc-200">
              Voir la série
            </Link>
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
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-4 font-semibold text-zinc-100">Fiche</h2>
          {saved && (
            <div className="mb-4">
              <Alert tone="info">{info.saved}</Alert>
            </div>
          )}
          <LibraryEntryForm
            key={e.updated_at}
            kind={kind}
            projectId={e.project_id}
            initial={e}
            onSaved={(updated) => {
              entry.setData(updated);
              setSaved(true);
            }}
          />
        </Card>
        <Card>
          <h2 className="mb-1 font-semibold text-zinc-100">Images de référence</h2>
          <p className="mb-4 text-sm text-zinc-500">{info.imagesHint}</p>
          <ReferenceImages
            kind={kind}
            entry={e}
            onChange={entry.setData}
            initialError={uploadError && `Fiche enregistrée, mais images refusées : ${uploadError}`}
          />
        </Card>
      </div>
      <Card className="mt-6">
        <h2 className="mb-1 font-semibold text-zinc-100">Créer des références</h2>
        <ReferenceStudio kind={kind} entry={e} onEntryChange={entry.setData} />
      </Card>
    </>
  );
}

/** Création d'une fiche dans la bibliothèque d'une série. */
export function NewLibraryEntryPage({ kind, projectId }: { kind: LibraryKind; projectId: number }) {
  const info = LIBRARY_KINDS[kind];
  const router = useRouter();
  const project = useEngineData(() => api.getProject(projectId), [projectId]);

  if (project.loading) return <Loading />;
  if (project.error || !project.data) return <Alert>{project.error ?? "Série introuvable"}</Alert>;

  return (
    <>
      <PageHeader
        title={info.newTitle}
        subtitle={
          <Link href={libraryHref(projectId, kind)} className="hover:text-zinc-200">
            ← {project.data.title} · {info.tab}
          </Link>
        }
      />
      <Card className="max-w-3xl">
        <LibraryEntryForm
          kind={kind}
          projectId={projectId}
          onSaved={(saved, uploadError) =>
            router.push(
              `${entryHref(kind, saved.id)}${uploadError ? `?erreur_images=${encodeURIComponent(uploadError)}` : ""}`,
            )
          }
        />
      </Card>
    </>
  );
}
