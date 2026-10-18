"use client";

import { useState } from "react";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import {
  api,
  fullErrorMessage,
  type LibraryResult,
  type OrphansPreview,
  type PresetsReload,
  type ResetResult,
  type TidyResult,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { RESET_WORD, isResetConfirmed, resetSummary } from "@/lib/reset";
import { librarySummary, orphanLabel, orphansSummary, tidySummary } from "@/lib/storage";
import { reloadSummary } from "@/lib/workflow-list";

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Réglages" subtitle="Réglages de l'atelier." />
      <div className="space-y-6">
        <AuthorCard />
        <PresetsReloadCard />
        <LibraryCard />
        <TidyCard />
        <ResetCard />
      </div>
    </>
  );
}

/** « Ton nom » : stocké par le moteur, il signe par défaut les validations et décisions d'étape (garde d'étapes,
 * scènes, name, foules sans fiche). Toujours modifiable dans la boîte de dialogue « Passer outre ». */
function AuthorCard() {
  const settings = useEngineData(() => api.getAppSettings(), []);
  const [typed, setTyped] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const saved = settings.data?.author_name ?? "";
  const value = typed ?? saved;
  const dirty = value.trim() !== saved;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const out = await api.saveAppSettings({ author_name: value.trim() });
      settings.setData(out);
      setTyped(null);
      toast(out.author_name ? `Nom enregistré : ${out.author_name}` : "Nom effacé");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="author-card">
      <h2 className="mb-2 font-semibold text-zinc-100">Ton nom</h2>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="min-w-56 flex-1">
          <Field label="Nom affiché sur les validations" htmlFor="settings-author">
            <Input
              id="settings-author"
              value={value}
              maxLength={120}
              placeholder="Ex. David"
              disabled={settings.loading && !settings.data}
              onChange={(e) => setTyped(e.target.value)}
              data-testid="settings-author"
            />
          </Field>
        </div>
        <Button type="submit" disabled={busy || !dirty || !settings.data} data-testid="settings-author-save">
          {busy ? "Enregistrement…" : "Enregistrer"}
        </Button>
      </form>
      <p className="mt-2 text-sm text-zinc-400">
        L&apos;atelier est local et sans compte : ce nom signe par défaut chaque validation et décision d&apos;étape
        (scènes, name, foules sans fiche, passer-outre). Il reste modifiable au cas par cas dans la boîte de dialogue
        « Passer outre ».
      </p>
      {settings.error && (
        <div className="mt-3">
          <Alert>Réglages illisibles : {settings.error}</Alert>
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

/** « Recharger les flux » : relit presets/ (flux ajoutés ou corrigés) sans redémarrer le moteur. Refusé pendant
 * une génération : le message du moteur le dit. */
function PresetsReloadCard() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PresetsReload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function reload() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const out = await api.reloadPresets();
      setResult(out);
      toast(`${out.workflows} flux rechargés`);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="presets-reload-card">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Flux de génération</h2>
        <Button variant="secondary" onClick={reload} disabled={busy} data-testid="presets-reload">
          {busy ? "Rechargement…" : "Recharger les flux"}
        </Button>
      </div>
      <p className="text-sm text-zinc-400">
        Après avoir ajouté ou corrigé un flux dans <code>presets/workflows/</code> (Qwen-Image 2.1),
        recharge-les ici : pas besoin de redémarrer le moteur. Refusé tant qu&apos;une génération tourne ; les
        générations en attente partiront avec les nouveaux flux. Les pages déjà ouvertes les voient après
        actualisation.
      </p>
      {result && (
        <div className="mt-4 space-y-2" data-testid="presets-reload-result">
          <Alert tone="info">{reloadSummary(result)}</Alert>
          {result.issues.length > 0 && (
            <ul className="space-y-1 text-sm text-amber-300">
              {result.issues.map((issue, i) => (
                <li key={`${issue.file}-${i}`}>
                  <code className="text-amber-200">{issue.file}</code> : {issue.message}
                </li>
              ))}
            </ul>
          )}
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
          Chaque série a son dossier dans ComfyUI, <code>output/mangaka/&lt;série&gt;/</code> :{" "}
          <code>references/</code> (un dossier par personnage, objet ou décor, avec un sous-dossier par type de fiche :{" "}
          <code>portrait/</code>, <code>plein-pied/</code>, <code>expressions/</code>, <code>angles/</code>,{" "}
          <code>imports/</code>…), <code>chapitre-01/page-01/</code> (croquis retenu de chaque case, versions choisies)
          et <code>trash/</code> (tout ce qui a été généré sans être retenu, rangé de la même façon). Un dossier
          n&apos;existe que s&apos;il contient un fichier : aucun dossier vide.
        </p>
        <p>
          C&apos;est une copie : l&apos;atelier ne relit jamais ces fichiers. Reconstruire refait l&apos;arborescence de toutes
          les séries depuis data/ (utile après avoir effacé ou déplacé des fichiers à la main), convertit
          l&apos;ancienne disposition à plat et retire les dossiers vides. Rejouer ne duplique rien.
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

/** « Ranger le dossier ComfyUI » : aperçu des dossiers de mangaka/ sans série, puis déplacement dans old/ après
 * confirmation (jamais de suppression). Désactivé sans COMFYUI_DIR valide, avec la raison. */
function TidyCard() {
  const health = useEngineData(() => api.health(), []);
  const storage = health.data?.storage;
  const disabled = storage ? !storage.enabled : false;
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<OrphansPreview | null>(null);
  const [result, setResult] = useState<TidyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function look() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setPreview(await api.comfyuiOrphans());
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function tidy() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.tidyComfyui(preview.orphans.map(({ area, name }) => ({ area, name }))));
      setPreview(null);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const reason = storage?.warning ?? storage?.problem ?? preview?.warning ?? null;
  return (
    <Card data-testid="tidy-card">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Dossier ComfyUI</h2>
        <Button variant="secondary" onClick={look} disabled={busy || disabled} data-testid="tidy-look">
          {busy && !preview ? "Recherche…" : "Ranger le dossier ComfyUI"}
        </Button>
      </div>
      <p className="text-sm text-zinc-400">
        Liste les dossiers de <code>output/mangaka/</code> et <code>input/mangaka/</code> qui ne correspondent à
        aucune série de l&apos;atelier (restes de tests, de démos ou d&apos;une autre base), puis, après confirmation,
        les <strong className="text-zinc-200">déplace</strong> dans <code>old/orphelins-&lt;date&gt;/</code> — rien
        n&apos;est supprimé, une série de l&apos;atelier n&apos;est jamais déplacée, <code>old/</code> reste intact.
        Retire aussi les dossiers vides restants.
      </p>
      {disabled && reason && (
        <div className="mt-3" data-testid="tidy-disabled">
          <Alert>Rangement désactivé : {reason}.</Alert>
        </div>
      )}
      {preview && (
        <div className="mt-4 space-y-3" data-testid="tidy-preview">
          {preview.enabled ? (
            <>
              <p className="text-sm text-zinc-300">{orphansSummary(preview)}</p>
              {preview.orphans.length > 0 && (
                <ul className="max-h-64 overflow-y-auto rounded-md border border-zinc-800 bg-zinc-950 p-2 text-xs text-zinc-300">
                  {preview.orphans.map((o) => (
                    <li key={`${o.area}/${o.name}`} className="break-all py-0.5 font-mono">
                      {orphanLabel(o)}
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex flex-wrap gap-2">
                {preview.orphans.length > 0 && (
                  <Button onClick={tidy} disabled={busy} data-testid="tidy-confirm">
                    {busy ? "Rangement…" : `Déplacer ${preview.orphans.length > 1 ? "ces dossiers" : "ce dossier"} dans old/`}
                  </Button>
                )}
                <Button variant="secondary" onClick={() => setPreview(null)} disabled={busy}>
                  {preview.orphans.length > 0 ? "Annuler" : "Fermer"}
                </Button>
              </div>
            </>
          ) : (
            <Alert>Rangement désactivé : {preview.warning}.</Alert>
          )}
        </div>
      )}
      {result && (
        <div className="mt-4 space-y-2" data-testid="tidy-result">
          <Alert tone="info">{tidySummary(result)}</Alert>
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
