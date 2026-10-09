"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { CharacterForm } from "@/components/character-form";
import { Alert, Card, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function NewCharacterPage() {
  const projectId = Number(useParams<{ id: string }>().id);
  const router = useRouter();
  const project = useEngineData(() => api.getProject(projectId), [projectId]);

  if (project.loading) return <Loading />;
  if (project.error || !project.data) return <Alert>{project.error ?? "Série introuvable"}</Alert>;

  return (
    <>
      <PageHeader
        title="Nouveau personnage"
        subtitle={
          <Link href={`/projets/${projectId}`} className="hover:text-zinc-200">
            ← {project.data.title}
          </Link>
        }
      />
      <Card className="max-w-3xl">
        <CharacterForm
          projectId={projectId}
          onSaved={(c, uploadError) =>
            router.push(
              `/personnages/${c.id}${uploadError ? `?erreur_images=${encodeURIComponent(uploadError)}` : ""}`,
            )
          }
        />
      </Card>
    </>
  );
}
