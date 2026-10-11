"use client";

import { useState } from "react";
import { Alert, Button, Card, PageHeader } from "@/components/ui";
import { api, fullErrorMessage, type LibraryResult, type ResetResult } from "@/lib/api";
import { RESET_WORD, isResetConfirmed, resetSummary } from "@/lib/reset";
import { librarySummary } from "@/lib/storage";

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Réglages" subtitle="Réglages de l'atelier." />
      <div className="space-y-6">
        <LibraryCard />
        <ResetCard />
      </div>
    </>
  );
}

/** « Reconstruire la bibliothèque » de toutes les séries (ComfyUI/output/mangaka/), ancienne disposition convertie. */
function LibraryCard() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<LibraryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function rebuild() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.rebuildAllLibraries());
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="library-card">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Bibliothèque lisible</h2>
        <Button variant="secondary" onClick={rebuild} disabled={busy} data-testid="library-rebuild">
          {busy ? "Reconstruction…" : "Reconstruire la bibliothèque"}
        </Button>
      </div>
      <div className="space-y-2 text-sm text-zinc-400">
        <p>
          Chaque série a son dossier dans ComfyUI, <code>output/mangaka/&lt;série&gt;/</code>, créé avec elle :{" "}
          <code>references/</code> (un dossier par personnage, objet ou décor, avec un sous-dossier par type de fiche :{" "}
          <code>portrait/</code>, <code>plein-pied/</code>, <code>expressions/</code>, <code>angles/</code>,{" "}
          <code>imports/</code>…), <code>chapitre-01/page-01/</code> (croquis validés, versions choisies) et{" "}
          <code>trash/</code> (tout ce qui a été généré sans être retenu, rangé de la même façon).
        </p>
        <p>
          C&apos;est une copie : l&apos;atelier ne relit jamais ces fichiers. Reconstruire refait l&apos;arborescence de toutes
          les séries depuis data/ (utile après avoir effacé ou déplacé des fichiers à la main) et convertit
          l&apos;ancienne disposition à plat. Rejouer ne duplique rien.
        </p>
      </div>
      {result && (
        <div className="mt-4 space-y-2" data-testid="library-result">
          <Alert tone="info">{librarySummary(result)}</Alert>
          {result.warning && <Alert>{result.warning}</Alert>}
        </div>
      )}
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
    </Card>
  );
}

/** « Remettre l'atelier à zéro » : sauvegarde complète puis effacement des séries (confirmation forte). */
function ResetCard() {
  const [typed, setTyped] = useState("");
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ResetResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirmed = isResetConfirmed(typed);

  async function reset() {
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.resetWorkshop(typed, all));
      setTyped("");
      setAll(false);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border-red-500/30" data-testid="reset-card">
      <h2 className="mb-2 font-semibold text-zinc-100">Remettre l&apos;atelier à zéro</h2>
      <div className="space-y-2 text-sm text-zinc-400">
        <p>
          Efface <strong className="text-zinc-200">toutes les séries</strong> et tout ce qui en dépend : chapitres,
          pages, cases et leurs images, personnages, objets, décors, planche de style, variantes, bibles, jobs et
          contrôles qualité, leurs fichiers dans data/ et leurs dossiers dans ComfyUI (output/mangaka/ et
          input/mangaka/, seulement si COMFYUI_DIR est renseigné dans .env).
        </p>
        <p>
          Restent : les presets, .env et launcher.env, les réglages globaux et le savoir-faire de l&apos;équipe,
          les sauvegardes (data/backups/) et le dossier <code>output/mangaka/old/</code> de ComfyUI.
        </p>
        <p>
          Une sauvegarde complète (base + data/) est écrite dans data/backups/ avant toute suppression ; si elle
          échoue, rien n&apos;est effacé. Refusé pendant une génération. La restauration est décrite dans le README.
        </p>
      </div>
      <label className="mt-4 flex items-start gap-2 text-sm text-zinc-300">
        <input
          type="checkbox"
          className="mt-0.5 accent-rose-500"
          checked={all}
          onChange={(e) => setAll(e.target.checked)}
          data-testid="reset-all"
        />
        <span>
          Tout remettre à zéro
          <span className="block text-xs text-zinc-500">
            Remet aussi les réglages globaux des agents et le savoir-faire de l&apos;équipe par défaut (jamais les
            presets, les fichiers .env, les sauvegardes ni old/).
          </span>
        </span>
      </label>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm text-zinc-300" htmlFor="reset-confirm">
          Tape <strong className="text-red-300">{RESET_WORD}</strong> pour confirmer
          <input
            id="reset-confirm"
            className="mt-1 block w-64 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 focus:border-red-400 focus:outline-none"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            data-testid="reset-confirm"
          />
        </label>
        <Button variant="danger" onClick={reset} disabled={!confirmed || busy} data-testid="reset-submit">
          {busy ? "Sauvegarde et remise à zéro…" : "Remettre l'atelier à zéro"}
        </Button>
      </div>
      {result && (
        <div className="mt-4" data-testid="reset-result">
          <Alert tone="info">
            <span className="block font-medium">Atelier remis à zéro.</span>
            {resetSummary(result).map((line) => (
              <span key={line} className="block">
                {line}
              </span>
            ))}
          </Alert>
        </div>
      )}
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
    </Card>
  );
}
