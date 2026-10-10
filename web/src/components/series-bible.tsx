"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { formatTokens } from "@/components/knowledge";
import { Alert, Button, Card, Field, Loading, Textarea } from "@/components/ui";
import { api, EngineError, errorMessage, type Bible, type ChapterSummaryEntry } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { LIBRARY_KINDS, entryHref, libraryHref } from "@/lib/library";

const SECTIONS = [
  { key: "world", label: "Univers", placeholder: "Kyoto, 1864. Les rônins errent sous la pluie…" },
  { key: "tone", label: "Ton", placeholder: "Mélancolique, avec des éclats d'humour." },
  { key: "rules", label: "Règles de l'univers", placeholder: "Aucun sabre ne se brise. Les esprits ne parlent qu'aux enfants." },
  { key: "motifs", label: "Gags et motifs récurrents", placeholder: "Le chat roux apparaît dans chaque chapitre." },
] as const;

/** Bible de la série : toujours injectée dans les agents de cette série (et d'elle seule). */
export function SeriesBible({ projectId }: { projectId: number }) {
  const bible = useEngineData(() => api.getBible(projectId), [projectId]);
  return (
    <Card data-testid="series-bible">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold text-zinc-100">Bible de la série</h2>
        {bible.data?.rendered && (
          <span className="text-xs text-zinc-500">
            {formatTokens(bible.data.rendered.tokens)} injectés
            {bible.data.rendered.truncated ? " (raccourcie au budget)" : ""}
          </span>
        )}
      </div>
      <p className="mb-4 text-sm text-zinc-400">
        Toujours transmise aux agents de cette série — jamais à une autre. Le résumé d&apos;un chapitre s&apos;y ajoute
        quand il passe à « Prêt » ou « Publié ».
      </p>
      {bible.loading && !bible.data ? (
        <Loading />
      ) : bible.error || !bible.data ? (
        <Alert>{bible.error ?? "Bible introuvable"}</Alert>
      ) : (
        <BibleForm projectId={projectId} initial={bible.data} onSaved={bible.setData} />
      )}
    </Card>
  );
}

function BibleForm({ projectId, initial, onSaved }: { projectId: number; initial: Bible; onSaved: (b: Bible) => void }) {
  const [values, setValues] = useState({
    world: initial.world,
    tone: initial.tone,
    rules: initial.rules,
    motifs: initial.motifs,
  });
  const [notes, setNotes] = useState<Record<number, string>>(
    Object.fromEntries(initial.characters.map((c) => [c.id, c.note])),
  );
  const [summaries, setSummaries] = useState<ChapterSummaryEntry[]>(initial.chapter_summaries);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setSaved(false);
    try {
      onSaved(await api.saveBible(projectId, { ...values, character_notes: notes, chapter_summaries: summaries }));
      setSaved(true);
    } catch (err) {
      setErrors(err instanceof EngineError && Object.keys(err.fieldErrors).length ? err.fieldErrors : { form: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div className="grid gap-4 md:grid-cols-2">
        {SECTIONS.map((s) => (
          <Field key={s.key} label={s.label} htmlFor={`bible-${s.key}`} error={errors[s.key]}>
            <Textarea
              id={`bible-${s.key}`}
              className="min-h-24"
              value={values[s.key]}
              placeholder={s.placeholder}
              onChange={(e) => {
                setValues((v) => ({ ...v, [s.key]: e.target.value }));
                setSaved(false);
              }}
            />
          </Field>
        ))}
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-medium text-zinc-300">Personnages</legend>
        {initial.characters.length === 0 ? (
          <p className="text-sm text-zinc-500">Aucune fiche personnage : crées-en une pour lui écrire des notes de bible.</p>
        ) : (
          <ul className="space-y-3">
            {initial.characters.map((c) => (
              <li key={c.id} className="grid gap-2 md:grid-cols-[12rem_minmax(0,1fr)]">
                <div>
                  <Link href={`/personnages/${c.id}`} className="text-sm font-medium text-zinc-200 hover:text-rose-300">
                    {c.name}
                  </Link>
                  {c.visual_description && <p className="line-clamp-2 text-xs text-zinc-500">{c.visual_description}</p>}
                </div>
                <Textarea
                  aria-label={`Notes de bible pour ${c.name}`}
                  className="min-h-16"
                  value={notes[c.id] ?? ""}
                  placeholder="Caractère, rôle, arc, tics de langage…"
                  onChange={(e) => {
                    setNotes((n) => ({ ...n, [c.id]: e.target.value }));
                    setSaved(false);
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      <BibleLibrary projectId={projectId} bible={initial} />

      <div>
        <p className="mb-2 text-sm font-medium text-zinc-300">Résumés des chapitres validés</p>
        {summaries.length === 0 ? (
          <p className="text-sm text-zinc-500">Aucun pour l&apos;instant.</p>
        ) : (
          <ul className="space-y-2">
            {summaries.map((s, i) => (
              <li key={`${s.chapter_id}-${i}`} className="flex gap-3 rounded-md border border-zinc-800 p-2 text-sm">
                <span className="shrink-0 text-zinc-400">Ch. {s.number ?? "?"}</span>
                <span className="text-zinc-300">
                  {s.title && <strong className="font-medium text-zinc-200">{s.title} — </strong>}
                  {s.summary}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  className="ml-auto px-2 py-1 text-xs"
                  onClick={() => {
                    setSummaries((list) => list.filter((_, j) => j !== i));
                    setSaved(false);
                  }}
                  aria-label={`Retirer le résumé du chapitre ${s.number ?? ""}`}
                >
                  Retirer
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {errors.form && <Alert>{errors.form}</Alert>}
      {errors.character_notes && <Alert>{errors.character_notes}</Alert>}
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={busy} data-testid="save-bible">
          {busy ? "Enregistrement…" : "Enregistrer la bible"}
        </Button>
        {saved && (
          <span className="text-xs text-emerald-300" role="status">
            Bible enregistrée.
          </span>
        )}
      </div>
    </form>
  );
}

/** Décors et objets de la bibliothèque : repris tels quels dans la bible (à modifier depuis leur fiche). */
function BibleLibrary({ projectId, bible }: { projectId: number; bible: Bible }) {
  const groups = [
    { kind: "decor" as const, label: "Décors récurrents", items: bible.decors ?? [] },
    { kind: "object" as const, label: "Objets récurrents", items: bible.objets ?? [] },
  ];
  return (
    <div data-testid="bible-library">
      <p className="mb-1 text-sm font-medium text-zinc-300">Décors et objets récurrents</p>
      <p className="mb-2 text-xs text-zinc-500">
        Repris automatiquement de la{" "}
        <Link href={libraryHref(projectId, "decor")} className="underline-offset-2 hover:text-zinc-300 hover:underline">
          bibliothèque de la série
        </Link>{" "}
        : les agents ne peuvent citer que ceux-là.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {groups.map((g) => (
          <div key={g.kind}>
            <p className="mb-1 text-xs text-zinc-400">{g.label}</p>
            {g.items.length === 0 ? (
              <p className="text-xs text-zinc-600">Aucun.</p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {g.items.map((item) => (
                  <li key={item.id}>
                    <Link
                      href={entryHref(g.kind, item.id)}
                      title={item.visual_description || undefined}
                      className={`inline-block rounded px-2 py-0.5 text-xs hover:opacity-80 ${LIBRARY_KINDS[g.kind].badge}`}
                    >
                      {item.name}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
