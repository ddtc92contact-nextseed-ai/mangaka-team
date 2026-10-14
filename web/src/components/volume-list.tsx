"use client";

import Link from "next/link";
import { useState } from "react";
import { api, EngineError, engineUrl, fullErrorMessage, type Chapter, type CoverFormat, type Volume } from "@/lib/api";
import { chapterOwners, nextVolumeNumber, orderedChapterIds } from "@/lib/cover";
import { useEngineData } from "@/lib/hooks";
import { useConfirm } from "./confirm";
import { useToast } from "./toast";
import { Alert, Button, ButtonLink, Card, EmptyState, Field, Input, Loading, Select } from "./ui";

/** Section « Tomes » de la page Série : créer un tome, lui rattacher des chapitres, ouvrir sa couverture. */
export function VolumeList({ projectId }: { projectId: number }) {
  const volumes = useEngineData(() => api.listVolumes(projectId), [projectId]);
  const chapters = useEngineData(() => api.listChapters(projectId), [projectId]);
  const formats = useEngineData(() => api.coverFormats(), []);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();
  const toast = useToast();

  function replace(v: Volume) {
    volumes.setData((list) => {
      const rest = (list ?? []).filter((x) => x.id !== v.id);
      return [...rest, v].sort((a, b) => a.number - b.number);
    });
  }

  async function remove(v: Volume) {
    const ok = await confirm({
      title: `Supprimer le tome ${v.number} ?`,
      message: "Le tome et ses versions de couverture seront supprimés. Ses chapitres restent dans la série.",
      confirmLabel: "Supprimer le tome",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteVolume(v.id);
      volumes.setData((list) => (list ?? []).filter((x) => x.id !== v.id));
      toast(`Tome ${v.number} supprimé`);
    } catch (err) {
      setError(fullErrorMessage(err));
    }
  }

  const list = volumes.data ?? [];
  return (
    <Card aria-labelledby="tomes-titre">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div>
          <h2 id="tomes-titre" className="font-semibold text-zinc-100">
            Tomes
          </h2>
          <p className="mt-1 text-sm text-zinc-500">Regroupe les chapitres en tomes et prépare leur couverture.</p>
        </div>
        {!creating && (
          <Button type="button" onClick={() => setCreating(true)} data-testid="volume-new">
            Nouveau tome
          </Button>
        )}
      </div>
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      {creating && (
        <div className="mb-4">
          <VolumeForm
            projectId={projectId}
            number={nextVolumeNumber(list)}
            formats={formats.data ?? []}
            onCancel={() => setCreating(false)}
            onCreated={(v) => {
              replace(v);
              setCreating(false);
              setEditing(v.id);
              toast(`Tome ${v.number} créé`);
            }}
          />
        </div>
      )}
      {volumes.loading && !volumes.data ? (
        <Loading />
      ) : volumes.error ? (
        <Alert>Impossible de charger les tomes : {volumes.error}</Alert>
      ) : list.length ? (
        <ol className="divide-y divide-zinc-800" aria-label="Tomes de la série">
          {list.map((v) => (
            <li key={v.id} className="py-3" data-testid="volume-row">
              <div className="flex flex-wrap items-center gap-3">
                <div className="h-14 w-10 shrink-0 overflow-hidden rounded border border-zinc-800 bg-zinc-950">
                  {v.selected_cover_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={engineUrl(v.selected_cover_url)} alt={`Couverture du tome ${v.number}`} className="h-full w-full object-cover" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <Link href={`/tomes/${v.id}`} className="block truncate font-medium text-zinc-100 hover:text-rose-300">
                    Tome {v.number}
                    {v.title ? ` — ${v.title}` : ""}
                  </Link>
                  <p className="truncate text-xs text-zinc-500">
                    {v.cover_format_name ?? v.cover_format} ·{" "}
                    {v.chapters.length
                      ? `${v.chapters.length} chapitre${v.chapters.length > 1 ? "s" : ""} (${v.chapters.map((c) => `ch. ${c.number}`).join(", ")})`
                      : "aucun chapitre"}
                  </p>
                </div>
                <span className="flex flex-wrap gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    className="px-2 py-1"
                    onClick={() => setEditing(editing === v.id ? null : v.id)}
                    aria-expanded={editing === v.id}
                  >
                    Chapitres
                  </Button>
                  <ButtonLink href={`/tomes/${v.id}`} variant="secondary" className="px-2 py-1">
                    Couverture
                  </ButtonLink>
                  <Button type="button" variant="ghost" className="px-2 py-1 text-red-400" onClick={() => remove(v)} aria-label={`Supprimer le tome ${v.number}`}>
                    ✕
                  </Button>
                </span>
              </div>
              {editing === v.id && (
                <ChapterPicker
                  volume={v}
                  volumes={list}
                  chapters={chapters.data ?? []}
                  onSaved={(saved) => {
                    replace(saved);
                    setEditing(null);
                    toast(`Chapitres du tome ${saved.number} enregistrés`);
                  }}
                />
              )}
            </li>
          ))}
        </ol>
      ) : (
        !creating && (
          <EmptyState title="Aucun tome">
            Un tome regroupe des chapitres et porte une couverture (format manga 13 × 18 par défaut, ou A4).
          </EmptyState>
        )
      )}
    </Card>
  );
}

function VolumeForm({
  projectId,
  number,
  formats,
  onCancel,
  onCreated,
}: {
  projectId: number;
  number: number;
  formats: CoverFormat[];
  onCancel: () => void;
  onCreated: (v: Volume) => void;
}) {
  const [num, setNum] = useState(String(number));
  const [title, setTitle] = useState("");
  const [format, setFormat] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const chosen = format || formats.find((f) => f.default)?.id || formats[0]?.id || "";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      onCreated(
        await api.createVolume(projectId, {
          number: Number(num) || null,
          title: title.trim(),
          cover_format: chosen || null,
        }),
      );
    } catch (err) {
      setErrors(err instanceof EngineError ? err.fieldErrors : {});
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3" aria-label="Nouveau tome">
      <div className="grid gap-3 sm:grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)]">
        <Field label="Numéro" htmlFor="tome-numero" error={errors.number}>
          <Input id="tome-numero" type="number" min={1} value={num} onChange={(e) => setNum(e.target.value)} />
        </Field>
        <Field label="Titre (facultatif)" htmlFor="tome-titre" error={errors.title}>
          <Input id="tome-titre" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="La ville en feu" />
        </Field>
        <Field label="Format de couverture" htmlFor="tome-format" error={errors.cover_format}>
          <Select id="tome-format" value={chosen} onChange={(e) => setFormat(e.target.value)}>
            {formats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
                {f.default ? " (par défaut)" : ""}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {error && !Object.keys(errors).length && <Alert>{error}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Création…" : "Créer le tome"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Annuler
        </Button>
      </div>
    </form>
  );
}

function ChapterPicker({
  volume,
  volumes,
  chapters,
  onSaved,
}: {
  volume: Volume;
  volumes: Volume[];
  chapters: Chapter[];
  onSaved: (v: Volume) => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(() => new Set(volume.chapters.map((c) => c.id)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owners = chapterOwners(volumes, volume.id);

  function toggle(id: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.updateVolume(volume.id, { chapter_ids: orderedChapterIds(selected, chapters) }));
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
      {chapters.length ? (
        <fieldset>
          <legend className="mb-2 text-sm text-zinc-300">Chapitres du tome {volume.number} (dans l&apos;ordre des numéros)</legend>
          <ul className="grid gap-1 sm:grid-cols-2">
            {chapters.map((c) => {
              const owner = owners.get(c.id);
              return (
                <li key={c.id}>
                  <label className={`flex items-center gap-2 text-sm ${owner ? "text-zinc-600" : "text-zinc-200"}`}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      disabled={owner !== undefined}
                      onChange={() => toggle(c.id)}
                      className="accent-rose-500"
                    />
                    <span className="truncate">
                      Ch. {c.number}
                      {c.title ? ` — ${c.title}` : ""}
                      {owner !== undefined && ` (déjà dans le tome ${owner})`}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </fieldset>
      ) : (
        <p className="text-sm text-zinc-500">La série n&apos;a pas encore de chapitre.</p>
      )}
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-3">
        <Button type="button" onClick={save} disabled={busy || !chapters.length}>
          {busy ? "Enregistrement…" : "Enregistrer les chapitres"}
        </Button>
      </div>
    </div>
  );
}
