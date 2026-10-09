"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { CharacterForm, ReferenceImages } from "@/components/character-form";
import { Alert, Button, Card, Loading, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function CharacterPage() {
  const id = Number(useParams<{ id: string }>().id);
  const router = useRouter();
  const character = useEngineData(() => api.getCharacter(id), [id]);
  const [saved, setSaved] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  if (character.loading) return <Loading />;
  if (character.error || !character.data) return <Alert>{character.error ?? "Personnage introuvable"}</Alert>;
  const c = character.data;

  async function remove() {
    if (!window.confirm(`Supprimer ${c.name} et ses images de référence ?`)) return;
    try {
      await api.deleteCharacter(c.id);
      router.push(`/projets/${c.project_id}`);
    } catch (err) {
      setDeleteError(errorMessage(err));
    }
  }

  return (
    <>
      <PageHeader
        title={c.name}
        subtitle={
          <Link href={`/projets/${c.project_id}`} className="hover:text-zinc-200">
            ← Retour au projet
          </Link>
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
              <Alert tone="info">Personnage enregistré.</Alert>
            </div>
          )}
          <CharacterForm
            key={c.updated_at}
            projectId={c.project_id}
            initial={c}
            onSaved={(updated) => {
              character.setData(updated);
              setSaved(true);
            }}
          />
        </Card>
        <Card>
          <h2 className="mb-1 font-semibold text-zinc-100">Images de référence</h2>
          <p className="mb-4 text-sm text-zinc-500">
            Planche de référence, visage, profil, tenue : elles guideront la génération de chaque case.
          </p>
          <ReferenceImages character={c} onChange={character.setData} />
        </Card>
      </div>
    </>
  );
}
