"use client";

import { useState } from "react";
import { Alert, Button, Card } from "@/components/ui";
import { api, errorMessage, type CleanupResult, type Project } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { CLEANUP_CONFIRM, cleanupSummary } from "@/lib/storage";

/** « Fichiers » de la fiche série : dossier dans ComfyUI, avertissement sans COMFYUI_DIR, nettoyage. */
export function SeriesFiles({ project }: { project: Project }) {
  const health = useEngineData(() => api.health(), []);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CleanupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const storage = health.data?.storage;

  async function cleanup() {
    if (!window.confirm(CLEANUP_CONFIRM)) return;
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

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Fichiers de la série</h2>
        <Button variant="secondary" onClick={cleanup} disabled={busy}>
          {busy ? "Nettoyage…" : "Nettoyer les variantes non retenues"}
        </Button>
      </div>
      <p className="text-sm text-zinc-400">
        Dossier dans ComfyUI :{" "}
        <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-200" data-testid="series-folder">
          mangaka/{project.slug}/
        </code>{" "}
        (personnages, objets, décors, style, puis chapitre-01/page-01…). La sortie de ComfyUI n&apos;est qu&apos;un
        transit : chaque image est effacée de ComfyUI dès qu&apos;elle est enregistrée dans l&apos;application.
      </p>
      {storage?.warning && (
        <div className="mt-3">
          <Alert>
            Fichiers de ComfyUI non nettoyés : {storage.warning}. Renseigne COMFYUI_DIR dans .env (dossier
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
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
    </Card>
  );
}
