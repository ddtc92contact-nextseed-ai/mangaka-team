"use client";

import Link from "next/link";
import { useState } from "react";
import { useConfirm } from "@/components/confirm";
import { useToast } from "@/components/toast";
import { Alert, Button, ButtonLink, Card, EmptyState, Field, Input, Loading, Select, Textarea } from "@/components/ui";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type LibraryEntry,
  type LocationGroup,
  type LocationProposal,
  type SeriesLocation,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { libraryHref } from "@/lib/library";

export const locationsHref = (projectId: number) => `/projets/${projectId}/lieux`;

/** Carte de la fiche série : les lieux de la série et l'accès à l'écran « Lieux ». */
export function SeriesLocationsCard({ projectId }: { projectId: number }) {
  const locations = useEngineData(() => api.listLocations(projectId), [projectId]);
  const list = locations.data ?? [];
  const withoutDecor = list.filter((l) => l.decor === null).length;
  return (
    <Card data-testid="series-locations-card">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">
          <Link href={locationsHref(projectId)} className="hover:text-rose-300">
            Lieux
          </Link>
        </h2>
        <ButtonLink href={locationsHref(projectId)} variant="secondary">
          Gérer les lieux
        </ButtonLink>
      </div>
      {locations.error && <Alert>{locations.error}</Alert>}
      {locations.loading && !locations.data ? (
        <Loading />
      ) : list.length === 0 ? (
        <p className="text-sm text-zinc-400">
          Aucun lieu : le scénariste crée les lieux en découpant un chapitre, et les chapitres d&apos;avant se regroupent
          depuis l&apos;écran « Lieux ».
        </p>
      ) : (
        <p className="text-sm text-zinc-400">
          {list.length} lieu{list.length > 1 ? "x" : ""} : {list.map((l) => l.name).join(", ")}
          {withoutDecor > 0 && (
            <span className="text-amber-300">
              {" "}
              · {withoutDecor} sans décor (pas de référence de lieu à la génération)
            </span>
          )}
        </p>
      )}
    </Card>
  );
}

function DecorSelect({
  id,
  value,
  decors,
  onChange,
}: {
  id: string;
  value: number | null;
  decors: LibraryEntry[];
  onChange: (v: number | null) => void;
}) {
  return (
    <Select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">— aucun décor —</option>
      {decors.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name}
          {d.reference_images.length === 0 ? " (sans image)" : ""}
        </option>
      ))}
    </Select>
  );
}

/** Une ligne de la liste des lieux : nom, description et décor modifiables, suppression. */
function LocationRow({
  location,
  decors,
  onChanged,
}: {
  location: SeriesLocation;
  decors: LibraryEntry[];
  onChanged: () => void;
}) {
  const [name, setName] = useState(location.name);
  const [description, setDescription] = useState(location.description);
  const [decor, setDecor] = useState<number | null>(location.decor);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();
  const dirty = name !== location.name || description !== location.description || decor !== location.decor;
  const id = `lieu-${location.id}`;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.updateLocation(location.id, { name, description, decor });
      onChanged();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    const ok = await confirm({
      title: `Supprimer le lieu « ${location.name} » ?`,
      message: `Ses ${location.panel_count} case(s) seront détachées ; leur texte de lieu et leur décor restent.`,
      confirmLabel: "Supprimer le lieu",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteLocation(location.id);
      onChanged();
    } catch (e) {
      setError(fullErrorMessage(e));
    }
  }

  return (
    <li className="rounded-lg border border-zinc-800 p-3" data-testid="location-row">
      <div className="grid gap-3 md:grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex aspect-square items-center justify-center overflow-hidden rounded-md bg-zinc-900 text-center text-xs text-zinc-500">
          {location.decor_image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={engineUrl(location.decor_image_url)} alt={`Décor de ${location.name}`} className="size-full object-cover" />
          ) : location.decor !== null ? (
            "Décor sans image"
          ) : (
            "Sans décor"
          )}
        </div>
        <div className="space-y-2">
          <Field label="Nom" htmlFor={`${id}-name`}>
            <Input id={`${id}-name`} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Décor de la bibliothèque" htmlFor={`${id}-decor`}>
            <DecorSelect id={`${id}-decor`} value={decor} decors={decors} onChange={setDecor} />
          </Field>
        </div>
        <Field label="Description" htmlFor={`${id}-description`}>
          <Textarea
            id={`${id}-description`}
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-zinc-400">
        <span>
          {location.panel_count} case{location.panel_count > 1 ? "s" : ""}
          {location.chapters.length > 0 && ` · chapitre${location.chapters.length > 1 ? "s" : ""} ${location.chapters.join(", ")}`}
        </span>
        {location.decor === null && <span className="text-amber-300">Sans décor : aucune référence de lieu envoyée.</span>}
        <span className="ml-auto flex gap-2">
          <Button variant="secondary" onClick={save} disabled={!dirty || busy || !name.trim()}>
            Enregistrer
          </Button>
          <Button variant="danger" onClick={remove}>
            Supprimer
          </Button>
        </span>
      </div>
      {error && (
        <div className="mt-2">
          <Alert>{error}</Alert>
        </div>
      )}
    </li>
  );
}

function NewLocation({ projectId, decors, onCreated }: { projectId: number; decors: LibraryEntry[]; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [decor, setDecor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setError(null);
    try {
      await api.createLocation(projectId, { name, decor });
      setName("");
      setDecor(null);
      onCreated();
    } catch (e) {
      setError(fullErrorMessage(e));
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="min-w-48 flex-1">
        <Field label="Nouveau lieu" htmlFor="nouveau-lieu-nom">
          <Input id="nouveau-lieu-nom" value={name} placeholder="La clairière" onChange={(e) => setName(e.target.value)} />
        </Field>
      </div>
      <div className="min-w-48">
        <Field label="Décor" htmlFor="nouveau-lieu-decor">
          <DecorSelect id="nouveau-lieu-decor" value={decor} decors={decors} onChange={setDecor} />
        </Field>
      </div>
      <Button onClick={create} disabled={!name.trim()}>
        Ajouter le lieu
      </Button>
      {error && (
        <div className="basis-full">
          <Alert>{error}</Alert>
        </div>
      )}
    </div>
  );
}

const nameKey = (name: string) =>
  name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}']+/gu, " ")
    .trim();

/** Nom d'un nouveau lieu qui ne se confond avec aucun groupe ni lieu existant (le moteur fusionnerait deux lieux de
 * même nom) : « Crique » → « Crique (2) ». */
function uniqueName(base: string, groups: LocationGroup[], locations: SeriesLocation[]): string {
  const taken = new Set([...groups.map((g) => nameKey(g.name)), ...locations.map((l) => nameKey(l.name))]);
  const root = base || "Nouveau lieu";
  let name = root;
  for (let n = 2; taken.has(nameKey(name)); n++) name = `${root} (${n})`;
  return name;
}

/** Regroupement des cases d'avant : le LLM propose des lieux, l'auteur les relit (renomme, déplace une variante,
 * choisit le décor) puis valide. */
function Regroup({
  projectId,
  locations,
  decors,
  onApplied,
}: {
  projectId: number;
  locations: SeriesLocation[];
  decors: LibraryEntry[];
  onApplied: () => void;
}) {
  const [proposal, setProposal] = useState<LocationProposal | null>(null);
  const [groups, setGroups] = useState<LocationGroup[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function propose() {
    setBusy(true);
    setError(null);
    try {
      const p = await api.proposeLocations(projectId);
      setProposal(p);
      setGroups(p.groups);
      if (!p.variants.length) toast("Toutes les cases sont déjà rattachées à un lieu.");
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function patch(i: number, change: Partial<LocationGroup>) {
    setGroups((gs) => gs.map((g, k) => (k === i ? { ...g, ...change } : g)));
  }

  function move(text: string, from: number, to: number) {
    setGroups((gs) => {
      const next = gs.map((g, k) => (k === from ? { ...g, settings: g.settings.filter((t) => t !== text) } : g));
      if (to === -1) next.push({ name: uniqueName(text.split(",")[0].trim(), next, locations), description: "", existing: null, decor: null, settings: [text] });
      else next[to] = { ...next[to], settings: [...next[to].settings, text] };
      return next.filter((g) => g.settings.length > 0);
    });
  }

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.applyLocations(projectId, groups);
      toast(
        `${r.attached + r.inherited} case(s) rattachée(s), ${r.created} lieu(x) créé(s)` +
          (r.unattached ? ` — ${r.unattached} case(s) encore sans lieu.` : "."),
      );
      setProposal(null);
      setGroups([]);
      onApplied();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const counts = new Map((proposal?.variants ?? []).map((v) => [v.text, v.panels]));
  return (
    <Card data-testid="locations-regroup">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Regrouper les lieux des chapitres d&apos;avant</h2>
        <Button variant="secondary" onClick={propose} disabled={busy} data-testid="locations-propose">
          {busy && !proposal ? "Proposition en cours…" : "Proposer un regroupement"}
        </Button>
      </div>
      <p className="mb-3 text-sm text-zinc-400">
        Avant l&apos;unité de lieu, le lieu n&apos;était qu&apos;un texte libre recopié sur chaque case (« clairière »,
        « clairière au centre de l&apos;île »…). L&apos;IA range ces variantes en lieux ; relis, corrige, puis valide.
        Rien n&apos;est perdu : le texte de chaque case reste comme décor de la case.
      </p>
      {error && <Alert>{error}</Alert>}
      {proposal && proposal.variants.length > 0 && (
        <>
          <p className="mb-3 text-sm text-zinc-300" data-testid="locations-proposal-summary">
            {proposal.variants.length} variante{proposal.variants.length > 1 ? "s" : ""} de texte sur {proposal.unattached}{" "}
            case{proposal.unattached > 1 ? "s" : ""} sans lieu → <strong>{groups.length} lieu{groups.length > 1 ? "x" : ""}</strong>
          </p>
          <ol className="space-y-3">
            {groups.map((g, i) => (
              <li key={i} className="rounded-lg border border-zinc-800 p-3" data-testid="location-group">
                <div className="grid gap-2 md:grid-cols-3">
                  <Field label="Lieu" htmlFor={`groupe-${i}-nom`}>
                    <Input id={`groupe-${i}-nom`} value={g.name} onChange={(e) => patch(i, { name: e.target.value })} />
                  </Field>
                  <Field label="Lieu existant" htmlFor={`groupe-${i}-existant`}>
                    <Select
                      id={`groupe-${i}-existant`}
                      value={g.existing ?? ""}
                      onChange={(e) => patch(i, { existing: e.target.value ? Number(e.target.value) : null })}
                    >
                      <option value="">— nouveau lieu —</option>
                      {locations.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Décor" htmlFor={`groupe-${i}-decor`}>
                    <DecorSelect id={`groupe-${i}-decor`} value={g.decor} decors={decors} onChange={(v) => patch(i, { decor: v })} />
                  </Field>
                </div>
                <ul className="mt-2 space-y-1 text-sm">
                  {g.settings.map((text) => (
                    <li key={text} className="flex flex-wrap items-center gap-2">
                      <span className="text-zinc-300">« {text} »</span>
                      <span className="text-xs text-zinc-500">
                        {counts.get(text) ?? 0} case{(counts.get(text) ?? 0) > 1 ? "s" : ""}
                      </span>
                      <label className="sr-only" htmlFor={`deplacer-${i}-${text}`}>
                        Déplacer « {text} »
                      </label>
                      <Select
                        id={`deplacer-${i}-${text}`}
                        className="!w-auto py-0.5 text-xs"
                        value=""
                        onChange={(e) => e.target.value !== "" && move(text, i, Number(e.target.value))}
                      >
                        <option value="">Déplacer vers…</option>
                        {groups.map((o, k) =>
                          k === i ? null : (
                            <option key={k} value={k}>
                              {o.name || `Lieu ${k + 1}`}
                            </option>
                          ),
                        )}
                        <option value={-1}>Un nouveau lieu</option>
                      </Select>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
          <div className="mt-3 flex gap-2">
            <Button onClick={apply} disabled={busy || groups.some((g) => !g.name.trim() && g.existing === null)} data-testid="locations-apply">
              Valider le regroupement
            </Button>
            <Button variant="ghost" onClick={() => setProposal(null)} disabled={busy}>
              Annuler
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}

/** Écran « Lieux » d'une série. */
export function LocationsManager({ projectId }: { projectId: number }) {
  const locations = useEngineData(() => api.listLocations(projectId), [projectId]);
  const decors = useEngineData(() => api.listLibrary("decor", projectId), [projectId]);
  if (locations.loading && !locations.data) return <Loading />;
  if (locations.error && !locations.data) return <Alert>{locations.error}</Alert>;
  const list = locations.data ?? [];
  const decorList = decors.data ?? [];
  return (
    <div className="space-y-6">
      <Regroup projectId={projectId} locations={list} decors={decorList} onApplied={locations.reload} />
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold text-zinc-100">Lieux de la série</h2>
          <Link href={libraryHref(projectId, "decor")} className="text-sm text-zinc-400 hover:text-zinc-200">
            Décors de la bibliothèque →
          </Link>
        </div>
        <p className="mb-3 text-sm text-zinc-400">
          Chaque case se rattache à un lieu. Le décor d&apos;un lieu est envoyé comme référence de lieu à chaque case qui
          s&apos;y passe (après les références des personnages), pour que le décor ne dérive pas d&apos;une case à
          l&apos;autre.
        </p>
        {list.length === 0 ? (
          <EmptyState title="Aucun lieu pour l'instant" />
        ) : (
          <ul className="space-y-3">
            {list.map((l) => (
              <LocationRow key={`${l.id}-${l.name}-${l.decor}`} location={l} decors={decorList} onChanged={locations.reload} />
            ))}
          </ul>
        )}
        <div className="mt-4 border-t border-zinc-800 pt-4">
          <NewLocation projectId={projectId} decors={decorList} onCreated={locations.reload} />
        </div>
      </Card>
    </div>
  );
}
