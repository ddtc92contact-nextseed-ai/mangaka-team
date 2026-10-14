"use client";

import { useState } from "react";
import { useToast } from "./toast";
import { Alert, Button, Card, Field, Loading, Select } from "./ui";
import { api, engineUrl, fullErrorMessage, type CharterField, type CoverCharter } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

type Draft = Record<CharterField, string> & { character_ids: number[] };

function draftOf(data: CoverCharter): Draft {
  return { ...data.values, character_ids: data.character_ids };
}

/**
 * « Charte des couvertures » de la série (fiche série) : à part de l'ADN des chapitres. Une couverture est toujours
 * en couleur, sans timing ni découpage ; la charte tient la couleur, la cohérence des personnages, le cadrage et
 * l'accroche, pour tous les tomes. Choix bornés (presets/cover_charter.yaml).
 */
export function CoverCharterCard({ projectId }: { projectId: number }) {
  const charter = useEngineData(() => api.coverCharter(projectId), [projectId]);
  const data = charter.data;
  return (
    <Card data-testid="cover-charter" id="charte-couvertures">
      <h2 className="mb-1 font-semibold text-zinc-100">Charte des couvertures</h2>
      <p className="mb-4 text-sm text-zinc-400">
        À part de l&apos;ADN des chapitres : une couverture est toujours en couleur, sans timing ni découpage. La charte
        fixe sa couleur, ses personnages, son cadrage et son accroche, pour tous les tomes de la série.
      </p>
      {charter.loading && !data ? (
        <Loading />
      ) : charter.error || !data ? (
        <Alert>{charter.error ?? "Charte des couvertures indisponible"}</Alert>
      ) : !data.available ? (
        <Alert>{data.problem ?? "Charte des couvertures indisponible"}</Alert>
      ) : (
        <CharterForm key={JSON.stringify(draftOf(data))} projectId={projectId} data={data} onData={charter.setData} />
      )}
    </Card>
  );
}

function CharterForm({ projectId, data, onData }: { projectId: number; data: CoverCharter; onData: (d: CoverCharter) => void }) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(data));
  const [busy, setBusy] = useState<null | "save" | "reset">(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(data));
  const chosen = new Set(draft.character_ids);

  async function save() {
    setBusy("save");
    setError(null);
    try {
      onData(await api.saveCoverCharter(projectId, draft));
      toast("Charte des couvertures enregistrée");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    setBusy("reset");
    setError(null);
    try {
      onData(await api.resetCoverCharter(projectId));
      toast("Charte remise aux réglages par défaut");
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function toggle(id: number) {
    setDraft((d) => ({
      ...d,
      character_ids: d.character_ids.includes(id) ? d.character_ids.filter((x) => x !== id) : [...d.character_ids, id],
    }));
  }

  function select(name: CharterField, hint?: string) {
    const id = `charte-${name}`;
    const current = data.options[name].find((o) => o.id === draft[name]);
    return (
      <Field label={data.labels[name][0].toUpperCase() + data.labels[name].slice(1)} htmlFor={id} hint={current?.description || hint}>
        <Select id={id} value={draft[name]} onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}>
          {data.options[name].map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
    );
  }

  return (
    <div className="space-y-6">
      {error && <Alert>{error}</Alert>}
      <p className="text-xs text-zinc-500" data-testid="cover-charter-state">
        {data.saved ? "Charte enregistrée pour la série." : "Réglages par défaut (pas encore de charte enregistrée)."}
      </p>
      {data.monochrome_series && (
        <Alert tone="info">Série en noir et blanc : ses couvertures restent en couleur.</Alert>
      )}

      <section aria-labelledby="charte-couleur" className="space-y-3">
        <h3 id="charte-couleur" className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          Couleur
        </h3>
        <div className="grid gap-4 sm:grid-cols-2">
          {select("palette_mode")}
          {select("mood")}
        </div>
        {data.palette.length ? (
          <div>
            <div className="flex overflow-hidden rounded-md border border-zinc-800" aria-label={`Palette ${data.palette_name ?? ""}`}>
              {data.palette.map((c) => (
                <div
                  key={c.role}
                  className={`h-8 flex-1 ${c.sent && draft.palette_mode !== "libre" ? "" : "opacity-30"}`}
                  style={{ background: c.hex }}
                  title={`${c.role} : ${c.hex}${c.sent ? "" : " (lettrage, non envoyée)"}`}
                />
              ))}
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              Palette « {data.palette_name} » (Identité visuelle) — les couleurs de texte servent au lettrage, pas à
              l&apos;illustration.
            </p>
          </div>
        ) : null}
      </section>

      <section aria-labelledby="charte-personnages" className="space-y-3">
        <h3 id="charte-personnages" className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          Cohérence des personnages ({draft.character_ids.length}/{data.max_characters})
        </h3>
        {data.characters.length ? (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4" aria-label="Personnages admis en couverture">
            {data.characters.map((c) => {
              const on = chosen.has(c.id);
              const full = !on && draft.character_ids.length >= data.max_characters;
              return (
                <li key={c.id}>
                  <label
                    className={`flex items-center gap-2 rounded-md border px-2 py-1.5 text-sm ${
                      on ? "border-rose-500/60 bg-rose-500/10 text-zinc-100" : "border-zinc-800 text-zinc-300"
                    } ${full ? "opacity-50" : ""}`}
                  >
                    <input type="checkbox" checked={on} disabled={full} onChange={() => toggle(c.id)} className="accent-rose-500" />
                    {c.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={engineUrl(c.image_url)} alt="" className="h-8 w-8 rounded object-cover" />
                    ) : (
                      <span className="h-8 w-8 rounded bg-zinc-800" aria-hidden />
                    )}
                    <span className="min-w-0 truncate">
                      {c.name}
                      {!c.has_reference && <span className="block text-[10px] text-zinc-500">sans image de référence</span>}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-zinc-500">Aucun personnage dans la bibliothèque de la série.</p>
        )}
        <p className="text-xs text-zinc-500">
          Leurs références d&apos;identité partent à chaque génération de la 1re et de l&apos;illustration de 4e. Aucun
          personnage coché : ceux choisis sur chaque tome.{" "}
          {data.identity_check &&
            (data.identity_available
              ? `Après chaque génération, chacun est comparé à sa fiche (similarité ≥ ${String(data.min_similarity ?? "—").replace(".", ",")}) : un écart est signalé, sans bloquer.`
              : "Contrôle d'identité indisponible (fournisseur QC) : les versions ne sont pas vérifiées.")}
        </p>
      </section>

      <section aria-labelledby="charte-cadrage" className="space-y-3">
        <h3 id="charte-cadrage" className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          Cadrage et accroche
        </h3>
        <div className="grid gap-4 sm:grid-cols-2">
          {select("shot")}
          {select("back_shot")}
          {select("logo_place", "Zone gardée dégagée dans l'illustration ; le logo s'y pose par défaut.")}
          {select("subject")}
        </div>
      </section>

      {data.warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-300" data-testid="cover-charter-warnings">
          {data.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}

      <details className="rounded-lg border border-zinc-800 p-3 text-xs text-zinc-400">
        <summary className="cursor-pointer text-zinc-300">Consignes envoyées au modèle d&apos;image (réglages enregistrés)</summary>
        <p className="mt-2 font-medium text-zinc-300">1re de couverture</p>
        <ul className="list-inside list-disc font-mono">
          {data.front_lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        <p className="mt-2 font-medium text-zinc-300">Illustration de 4e</p>
        <ul className="list-inside list-disc font-mono">
          {data.back_lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>

      <div className="flex flex-wrap gap-2">
        <Button onClick={save} disabled={busy !== null || (!dirty && data.saved)} data-testid="cover-charter-save">
          {busy === "save" ? "Enregistrement…" : "Enregistrer la charte"}
        </Button>
        {dirty && (
          <Button variant="ghost" onClick={() => setDraft(draftOf(data))} disabled={busy !== null}>
            Annuler
          </Button>
        )}
        {data.saved && (
          <Button variant="secondary" onClick={reset} disabled={busy !== null}>
            {busy === "reset" ? "…" : "Revenir aux réglages par défaut"}
          </Button>
        )}
      </div>
    </div>
  );
}
