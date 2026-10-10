"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { LibraryList, LibraryTabs } from "@/components/library";
import { Alert, ButtonLink, EmptyState, Field, Loading, PageHeader, Select } from "@/components/ui";
import { api, type LibraryKind } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { LIBRARY_KINDS, kindFromSlug, newEntryHref } from "@/lib/library";

const STORAGE_KEY = "mangaka.projet-courant";

function storedProjectId(): number | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

export default function LibraryPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Library />
    </Suspense>
  );
}

/** Bibliothèque d'une série : onglets Personnages / Objets / Décors (`?serie=…&onglet=…`). */
function Library() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const projects = useEngineData(() => api.listProjects());
  const kind: LibraryKind = kindFromSlug(params.get("onglet")) ?? "character";
  const info = LIBRARY_KINDS[kind];

  // Série affichée : celle de l'URL, sinon la dernière choisie si elle existe encore, sinon la plus récente.
  const list = projects.data;
  const wanted = Number(params.get("serie")) || null;
  const projectId = list?.length
    ? (list.find((p) => p.id === wanted)?.id ?? list.find((p) => p.id === storedProjectId())?.id ?? list[0].id)
    : null;

  useEffect(() => {
    if (projectId === null) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, String(projectId));
    } catch {
      // stockage indisponible (navigation privée) : sans conséquence
    }
  }, [projectId]);

  function go(next: { serie?: number; kind?: LibraryKind }) {
    const q = new URLSearchParams();
    q.set("serie", String(next.serie ?? projectId ?? ""));
    q.set("onglet", LIBRARY_KINDS[next.kind ?? kind].slug);
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  }

  return (
    <>
      <PageHeader
        title="Bibliothèque"
        subtitle="Personnages, objets et décors récurrents de la série : description, mots-clés, LoRA et images de référence, pour qu'ils restent les mêmes d'une page à l'autre."
        actions={projectId !== null && <ButtonLink href={newEntryHref(kind, projectId)}>{info.addLabel}</ButtonLink>}
      />
      {projects.loading ? (
        <Loading />
      ) : projects.error ? (
        <Alert>Impossible de charger les séries : {projects.error}</Alert>
      ) : !list?.length || projectId === null ? (
        <EmptyState title="Crée d'abord une série : sa bibliothèque lui appartient.">
          <ButtonLink href="/projets/nouveau">Nouvelle série</ButtonLink>
        </EmptyState>
      ) : (
        <>
          <div className="mb-4 max-w-sm">
            <Field label="Série" htmlFor="project">
              <Select id="project" value={projectId} onChange={(e) => go({ serie: Number(e.target.value) })}>
                {list.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="mb-5">
            <LibraryTabs value={kind} onChange={(k) => go({ kind: k })} idPrefix="bibliotheque" />
          </div>
          <div role="tabpanel" id="bibliotheque-panel" aria-labelledby={`bibliotheque-tab-${kind}`}>
            <LibraryList key={`${kind}-${projectId}`} kind={kind} projectId={projectId} />
          </div>
        </>
      )}
    </>
  );
}
