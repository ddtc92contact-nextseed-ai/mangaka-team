"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Avatar } from "@/components/avatar";
import { Alert, ButtonLink, EmptyState, Field, Loading, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

const STORAGE_KEY = "mangaka.projet-courant";

function storedProjectId(): number | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

export default function CharactersPage() {
  const projects = useEngineData(() => api.listProjects());
  const [selected, setSelected] = useState<number | null>(null);

  // Projet sélectionné : dernier choisi s'il existe encore, sinon le plus récent.
  const list = projects.data;
  const projectId =
    selected ?? (list?.length ? (list.find((p) => p.id === storedProjectId())?.id ?? list[0].id) : null);

  useEffect(() => {
    if (projectId === null) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, String(projectId));
    } catch {
      // stockage indisponible (navigation privée) : sans conséquence
    }
  }, [projectId]);

  const characters = useEngineData(
    () => (projectId === null ? Promise.resolve([]) : api.listCharacters(projectId)),
    [projectId],
  );

  return (
    <>
      <PageHeader
        title="Personnages"
        subtitle="Fiches d'identité visuelle : description, mots-clés, LoRA et images de référence."
        actions={
          projectId !== null && (
            <ButtonLink href={`/projets/${projectId}/personnages/nouveau`}>Nouveau personnage</ButtonLink>
          )
        }
      />
      {projects.loading ? (
        <Loading />
      ) : projects.error ? (
        <Alert>Impossible de charger les projets : {projects.error}</Alert>
      ) : !list?.length ? (
        <EmptyState title="Crée d'abord un projet : les personnages appartiennent à une série.">
          <ButtonLink href="/projets/nouveau">Nouveau projet</ButtonLink>
        </EmptyState>
      ) : (
        <>
          <div className="mb-6 max-w-sm">
            <Field label="Projet" htmlFor="project">
              <Select id="project" value={projectId ?? ""} onChange={(e) => setSelected(Number(e.target.value))}>
                {list.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          {characters.loading ? (
            <Loading />
          ) : characters.error ? (
            <Alert>{characters.error}</Alert>
          ) : characters.data?.length ? (
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {characters.data.map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/personnages/${c.id}`}
                    className="flex h-full gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 transition-colors hover:border-zinc-600"
                  >
                    <Avatar url={c.reference_images[0]?.url} name={c.name} size="h-14 w-14" />
                    <div className="min-w-0">
                      <p className="font-semibold text-zinc-100">{c.name}</p>
                      <p className="line-clamp-2 text-sm text-zinc-400">
                        {c.visual_description || "Pas de description visuelle"}
                      </p>
                      <p className="mt-2 text-xs text-zinc-500">
                        {c.reference_images.length} image{c.reference_images.length > 1 ? "s" : ""} de référence
                        {c.lora_name && ` · LoRA ${c.lora_name}`}
                      </p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Aucun personnage dans ce projet">
              <ButtonLink href={`/projets/${projectId}/personnages/nouveau`}>Créer un personnage</ButtonLink>
            </EmptyState>
          )}
        </>
      )}
    </>
  );
}
