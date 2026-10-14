"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useConfirm } from "@/components/confirm";
import { Alert, Button, Card, Field, Loading, PageHeader, Select } from "@/components/ui";
import { api, errorMessage, type LibraryKind, type PanelObjectKind } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { LIBRARY_KINDS, PANEL_OBJECT_KINDS, entryHref, isPanelObjectKind, libraryHref } from "@/lib/library";
import { LibraryIcon } from "./library-icon";
import { LibraryEntryForm, ReferenceImages } from "./library-entry-form";
import { ReferenceStudio } from "./reference-studio";
import { useToast } from "./toast";

/** Fiche d'un personnage, d'un objet, d'un décor, d'un véhicule ou d'une créature : champs, images de référence,
 * catégorie (objet ↔ véhicule ↔ créature), suppression. */
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
  const toast = useToast();
  const confirm = useConfirm();

  if (entry.loading) return <Loading />;
  if (entry.error || !entry.data) return <Alert>{entry.error ?? `Fiche introuvable (${info.singular})`}</Alert>;
  const e = entry.data;

  async function remove() {
    const ok = await confirm({
      title: "Supprimer la fiche ?",
      message: info.deleteConfirm(e.name),
      confirmLabel: "Supprimer",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteLibraryEntry(kind, e.id);
      toast("Fiche supprimée");
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
            <Link href={libraryHref(e.project_id, kind)} className="flex items-center gap-1.5 hover:text-zinc-200">
              ← Bibliothèque · <LibraryIcon kind={kind} className="h-3.5 w-3.5" /> {info.tab}
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
              toast(info.saved.replace(/\.$/, ""));
            }}
          />
          {isPanelObjectKind(kind) && <KindSwitcher kind={kind} id={e.id} name={e.name} />}
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
      <Card className="mt-6 scroll-mt-4" id="references">
        <h2 className="mb-1 font-semibold text-zinc-100">Créer des références</h2>
        <ReferenceStudio kind={kind} entry={e} onEntryChange={entry.setData} />
      </Card>
    </>
  );
}

/** Catégorie d'un objet, d'un véhicule ou d'une créature : la changer garde images, variantes et cases. */
function KindSwitcher({ kind, id, name }: { kind: PanelObjectKind; id: number; name: string }) {
  const router = useRouter();
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change(target: PanelObjectKind) {
    if (target === kind) return;
    const ok = await confirm({
      title: "Changer de catégorie ?",
      message: `« ${name} » devient ${target === "creature" ? "une" : "un"} ${LIBRARY_KINDS[target].singular}. Ses images de référence, ses variantes et les cases qui le montrent sont gardées ; les fiches proposées deviennent celles de sa nouvelle catégorie.`,
      confirmLabel: "Changer",
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await api.changeLibraryKind(kind, id, target);
      toast(`Catégorie : ${LIBRARY_KINDS[target].singular}`);
      router.replace(entryHref(target, id));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 border-t border-zinc-800 pt-4">
      <Field label="Catégorie" htmlFor={`kind-${id}`} hint="Un vaisseau rangé en objet ? Change-le de catégorie : il reçoit les fiches et le négatif des véhicules, sans perdre ses images.">
        <Select id={`kind-${id}`} value={kind} disabled={busy} onChange={(ev) => change(ev.target.value as PanelObjectKind)}>
          {PANEL_OBJECT_KINDS.map((k) => (
            <option key={k} value={k}>
              {LIBRARY_KINDS[k].category ?? LIBRARY_KINDS[k].singular}
            </option>
          ))}
        </Select>
      </Field>
      {error && (
        <div className="mt-2">
          <Alert>{error}</Alert>
        </div>
      )}
    </div>
  );
}

/** Création d'une fiche dans la bibliothèque d'une série. */
export function NewLibraryEntryPage({ kind, projectId }: { kind: LibraryKind; projectId: number }) {
  const info = LIBRARY_KINDS[kind];
  const router = useRouter();
  const project = useEngineData(() => api.getProject(projectId), [projectId]);
  const toast = useToast();

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
          onSaved={(saved, uploadError) => {
            toast(info.saved.replace(/\.$/, ""));
            router.push(
              `${entryHref(kind, saved.id)}${uploadError ? `?erreur_images=${encodeURIComponent(uploadError)}` : ""}`,
            );
          }}
        />
      </Card>
    </>
  );
}
