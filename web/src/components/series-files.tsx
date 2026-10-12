"use client";

import { useState } from "react";
import { useConfirm } from "@/components/confirm";
import { Alert, Button, Card } from "@/components/ui";
import { api, errorMessage, type CleanupResult, type LibraryResult, type Project } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { CLEANUP_CONFIRM, CLEANUP_CONFIRM_TITLE, cleanupSummary, librarySummary } from "@/lib/storage";

/** « Fichiers » de la fiche série : dossier dans ComfyUI (bibliothèque lisible), avertissement sans COMFYUI_DIR,
 * nettoyage du transit, « Reconstruire la bibliothèque ». */
export function SeriesFiles({ project }: { project: Project }) {
  const health = useEngineData(() => api.health(), []);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CleanupResult | null>(null);
  const [library, setLibrary] = useState<LibraryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const storage = health.data?.storage;
  const confirm = useConfirm();

  async function cleanup() {
    const ok = await confirm({ title: CLEANUP_CONFIRM_TITLE, message: CLEANUP_CONFIRM, confirmLabel: "Nettoyer", danger: true });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.cleanupProject(project.id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function rebuild() {
    setBusy(true);
    setError(null);
    try {
      setLibrary(await api.rebuildLibrary(project.id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Fichiers de la série</h2>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={rebuild} disabled={busy}>
            Reconstruire la bibliothèque
          </Button>
          <Button variant="secondary" onClick={cleanup} disabled={busy}>
            {busy ? "Patiente…" : "Nettoyer les variantes non retenues"}
          </Button>
        </div>
      </div>
      <p className="text-sm text-zinc-400">
        Dossier dans ComfyUI :{" "}
        <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-200" data-testid="series-folder">
          mangaka/{project.slug}/
        </code>{" "}
        — la bibliothèque lisible de la série : <code>references/</code> (un dossier par personnage, objet ou décor,
        un sous-dossier par type de fiche, ex. <code>personnages/lucius/portrait/lucius-portrait.png</code>),{" "}
        <code>chapitre-01/page-01/</code> (croquis validés, versions choisies <code>case-01.png</code>, planches
        rendues dans <code>chapitre-01/planches/</code>) et <code>trash/</code> (variantes non gardées, versions non
        choisies, croquis non validés, rangés de la même façon). Les sorties brutes de ComfyUI passent par{" "}
        <code>_transit/</code> et en sont effacées dès qu&apos;elles sont enregistrées.
      </p>
      {storage?.warning && (
        <div className="mt-3">
          <Alert>
            Fichiers de ComfyUI non nettoyés et bibliothèque non écrite : {storage.warning}. Renseigne COMFYUI_DIR dans .env (dossier
            d&apos;installation de ComfyUI), puis relance le moteur.
          </Alert>
        </div>
      )}
      {result && (
        <div className="mt-3 space-y-2">
          <Alert tone="info">{cleanupSummary(result)}</Alert>
          {result.warning && !storage?.warning && <Alert>{result.warning}</Alert>}
        </div>
      )}
      {library && (
        <div className="mt-3 space-y-2" data-testid="library-result">
          <Alert tone="info">{librarySummary(library)}</Alert>
          {library.warning && !storage?.warning && <Alert>{library.warning}</Alert>}
        </div>
      )}
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
    </Card>
  );
}
