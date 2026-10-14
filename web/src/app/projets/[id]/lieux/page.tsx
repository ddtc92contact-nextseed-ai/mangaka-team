"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { LocationsManager } from "@/components/series-locations";
import { Alert, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

/** Écran « Lieux » d'une série : regroupement des cases d'avant, lieux et leur décor. */
export default function LocationsPage() {
  const id = Number(useParams<{ id: string }>().id);
  const project = useEngineData(() => api.getProject(id), [id]);
  if (project.loading) return <Loading />;
  if (project.error || !project.data) return <Alert>{project.error ?? "Série introuvable"}</Alert>;
  return (
    <>
      <PageHeader
        title={`Lieux — ${project.data.title}`}
        subtitle={
          <Link href={`/projets/${id}`} className="hover:text-zinc-200">
            ← Fiche de la série
          </Link>
        }
      />
      <LocationsManager projectId={id} />
    </>
  );
}
