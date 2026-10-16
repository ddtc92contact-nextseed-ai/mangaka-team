"use client";

import Link from "next/link";
import { useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { Modal } from "@/components/modal";
import { ProductionLink } from "@/components/production-link";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Field, Input, Loading, Select, Textarea } from "@/components/ui";
import {
  api,
  fullErrorMessage,
  parseTags,
  type CastMember,
  type ChapterCast,
  type Character,
  type CharacterDraft,
} from "@/lib/api";
import { castCounts, castFaultLabel, REFERENCE_LABELS } from "@/lib/cast";
import { loraSummary } from "@/lib/lora";
import { useEngineData } from "@/lib/hooks";
import { entryHref } from "@/lib/library";
import { useChapter } from "./chapter-context";

const CHIP = "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] leading-4";

/**
 * Distribution du chapitre (moteur : pipeline/cast.py) : chaque intervenant cité, même secondaire, avec sa fiche,
 * ses références et ses cases. Tant qu'un intervenant n'a ni fiche ni image, la génération est refusée (étape
 * « Références prêtes ») ; seules les foules anonymes peuvent être marquées « foule sans fiche ».
 */
export function CastPanel() {
  const { chapter, reloadStages } = useChapter();
  const cast = useEngineData(() => api.chapterCast(chapter.id), [chapter.id]);
  const characters = useEngineData(() => api.listCharacters(chapter.project_id), [chapter.project_id]);
  const [drafting, setDrafting] = useState<CastMember | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState<string | null>(null);
  const toast = useToast();

  function refresh(next?: ChapterCast) {
    if (next) cast.setData(next);
    else cast.reload();
    characters.reload();
    reloadStages();
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const createAll = () =>
    run(async () => {
      const res = await api.createSecondaries(chapter.id);
      refresh(res.cast);
      const created = res.items.filter((i) => i.created).length;
      const queued = res.items.filter((i) => i.queued).length;
      const failed = res.items.filter((i) => i.message && !i.queued);
      setBatch(
        [
          `${created} fiche${created > 1 ? "s" : ""} créée${created > 1 ? "s" : ""}, ${queued} portrait${queued > 1 ? "s" : ""} en file (une génération à la fois, gardés d'office comme référence).`,
          ...failed.map((i) => `${i.name} : ${i.message}`),
        ].join(" "),
      );
      toast(`${created} fiche${created > 1 ? "s" : ""} créée${created > 1 ? "s" : ""}`);
    });

  if (cast.loading && !cast.data) return <Loading />;
  if (cast.error) return <Alert>Impossible de charger la distribution : {cast.error}</Alert>;
  const data = cast.data;
  if (!data || data.members.length === 0) return null;
  const counts = castCounts(data);

  return (
    <Card data-testid="cast-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl space-y-1">
          <h2 className="flex items-center gap-1.5 font-semibold text-zinc-100">
            Distribution
            <InfoTip help="direction.distribution" label="Distribution du chapitre" />
          </h2>
          <p className="text-sm text-zinc-400" data-testid="cast-counts">
            {data.total} intervenant{data.total > 1 ? "s" : ""} ·{" "}
            {data.faults ? (
              <span className="text-amber-300">
                {data.faults} sans référence : la génération est refusée tant qu&apos;il en manque
              </span>
            ) : (
              <span className="text-emerald-300">tous ont leur fiche et une image de référence</span>
            )}
            {data.marks.length > 0 && ` · ${data.marks.length} foule${data.marks.length > 1 ? "s" : ""} sans fiche`}
          </p>
          <p className="text-xs text-zinc-500">
            Chaque intervenant cité, même pour une case, est dessiné d&apos;après sa fiche : un secondaire peut se contenter
            d&apos;un portrait, un principal demande la planche (portrait + turnaround).
          </p>
        </div>
        {counts.secondaries > 0 && (
          <Button onClick={createAll} disabled={busy} data-testid="cast-create-secondaries">
            {busy ? "Création…" : `Tout créer pour les secondaires (${counts.secondaries})`}
          </Button>
        )}
      </div>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {batch && (
        <div className="mt-3" data-testid="cast-batch">
          <Alert tone="info">
            {batch} <ProductionLink chapterId={chapter.id} />
          </Alert>
        </div>
      )}
      <ul className="mt-4 divide-y divide-zinc-800">
        {data.members.map((m) => (
          <CastRow
            key={m.key}
            member={m}
            characters={characters.data ?? []}
            busy={busy}
            onDraft={() => setDrafting(m)}
            onRun={run}
            onChanged={refresh}
          />
        ))}
      </ul>
      <DraftDialog member={drafting} onClose={() => setDrafting(null)} onCreated={() => refresh()} />
    </Card>
  );
}

function CastRow({
  member: m,
  characters,
  busy,
  onDraft,
  onRun,
  onChanged,
}: {
  member: CastMember;
  characters: Character[];
  busy: boolean;
  onDraft: () => void;
  onRun: (action: () => Promise<void>) => Promise<void>;
  onChanged: (next?: ChapterCast) => void;
}) {
  const { chapter } = useChapter();
  const [choice, setChoice] = useState("");
  const toast = useToast();
  const selectId = `cast-link-${m.key.replace(/\W+/g, "-")}`;
  const where = m.appearances.map((a) => `${a.label} (${a.sources.join(", ")})`).join(" · ");

  const link = () =>
    onRun(async () => {
      const card = characters.find((c) => c.id === Number(choice));
      const done = await api.linkCharacterName(chapter.id, m.name, Number(choice));
      toast(`« ${m.name} » relié à ${card?.name ?? "la fiche"}${done.alias_added ? " (nouvel alias)" : ""}`);
      onChanged();
    });
  const mark = () =>
    onRun(async () => {
      onChanged(await api.markCrowd(chapter.id, m.name));
      toast(`« ${m.name} » : foule sans fiche`);
    });
  const unmark = () =>
    onRun(async () => {
      if (!m.mark) return;
      onChanged(await api.revokeCrowd(chapter.id, m.mark.id));
      toast(`« ${m.name} » redevient un intervenant à régler`);
    });

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3" data-testid="cast-member">
      <div className="min-w-0 space-y-1">
        <p className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="font-medium text-zinc-100" data-testid="cast-name">
            {m.name}
          </span>
          <span className={`${CHIP} ${m.role === "principal" ? "bg-violet-500/15 text-violet-200" : "bg-zinc-800 text-zinc-300"}`}>
            {m.role}
          </span>
          {m.character_id !== null ? (
            <span className={`${CHIP} ${m.images ? "bg-emerald-500/15 text-emerald-200" : "bg-amber-500/20 text-amber-200"}`}>
              {REFERENCE_LABELS[m.references]}
            </span>
          ) : m.mark ? (
            <span className={`${CHIP} bg-sky-500/15 text-sky-200`}>foule sans fiche</span>
          ) : (
            <span className={`${CHIP} bg-amber-500/20 text-amber-200`}>⚠ sans fiche</span>
          )}
          {m.character_id !== null && (
            <span className={`${CHIP} bg-zinc-800 text-zinc-400`} data-testid="cast-lora">
              {loraSummary(m.lora_name, m.lora_weight)}
            </span>
          )}
          {m.fault && (
            <span className="text-xs text-amber-300" data-testid="cast-fault">
              {castFaultLabel(m)}
            </span>
          )}
          {m.advice && <span className="text-xs text-zinc-400">{m.advice}</span>}
        </p>
        <p className="text-xs text-zinc-500" title={where}>
          {m.panel_count} case{m.panel_count > 1 ? "s" : ""} : {m.appearances.slice(0, 4).map((a) => a.label).join(", ")}
          {m.appearances.length > 4 ? "…" : ""}
          {m.written.length > 1 && ` · écrit « ${m.written.join(" », « ")} »`}
        </p>
        {m.mark && (
          <p className="text-xs text-sky-300/80">
            Marquée{m.mark.author ? ` par ${m.mark.author}` : ""} le {new Date(m.mark.at).toLocaleString("fr-FR")}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {m.character_id !== null ? (
          <Link
            href={`${entryHref("character", m.character_id)}#references`}
            className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-200 hover:border-rose-400"
            data-testid="cast-references"
            title={m.needs === "planche" ? "Portrait de face puis turnaround" : "Un portrait de face suffit"}
          >
            {m.images ? "Compléter ses références" : "Créer ses références"}
          </Link>
        ) : m.mark ? (
          <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={unmark} disabled={busy} data-testid="cast-unmark">
            Annuler la marque
          </Button>
        ) : (
          <>
            {characters.length > 0 && (
              <>
                <label htmlFor={selectId} className="sr-only">
                  Fiche à relier à « {m.name} »
                </label>
                <Select id={selectId} className="!w-40 py-1 text-xs" value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy}>
                  <option value="">Relier à une fiche…</option>
                  {characters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
                <Button variant="secondary" className="!px-2 !py-1 text-xs" onClick={link} disabled={busy || !choice}>
                  Relier
                </Button>
              </>
            )}
            <Button className="!px-2 !py-1 text-xs" onClick={onDraft} disabled={busy} data-testid="cast-draft">
              Créer la fiche
            </Button>
            {m.crowd && (
              <Button
                variant="ghost"
                className="!px-2 !py-1 text-xs"
                onClick={mark}
                disabled={busy}
                title="Foule anonyme : dessinée sans fiche ni référence. Décision tracée, annulable."
                data-testid="cast-mark-crowd"
              >
                Foule sans fiche
              </Button>
            )}
          </>
        )}
      </div>
    </li>
  );
}

/** « Créer la fiche » : le LLM préremplit la fiche depuis les cases de l'intervenant ; l'auteur la relit. */
function DraftDialog({ member, onClose, onCreated }: { member: CastMember | null; onClose: () => void; onCreated: () => void }) {
  return (
    <Modal open={member !== null} onClose={onClose} title={member ? `Fiche de « ${member.name} »` : "Fiche"} size="xl">
      {member && <DraftForm key={member.key} member={member} onClose={onClose} onCreated={onCreated} />}
    </Modal>
  );
}

function DraftForm({ member, onClose, onCreated }: { member: CastMember; onClose: () => void; onCreated: () => void }) {
  const { chapter } = useChapter();
  const draft = useEngineData(() => api.draftCastCard(chapter.id, member.name), [chapter.id, member.name]);
  const [edited, setEdited] = useState<Partial<CharacterDraft> & { keywords?: string }>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Character | null>(null);
  const toast = useToast();

  if (draft.loading && !draft.data) {
    return <p className="text-sm text-zinc-400">Le directeur artistique lit les {member.panel_count} case(s) de « {member.name} »…</p>;
  }
  if (draft.error) {
    return (
      <div className="space-y-3">
        <Alert>{draft.error}</Alert>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={draft.reload}>
            Réessayer
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Fermer
          </Button>
        </div>
      </div>
    );
  }
  const d = draft.data;
  if (!d) return null;
  const name = edited.name ?? d.name;
  const description = edited.visual_description ?? d.visual_description;
  const keywords = edited.keywords ?? d.prompt_keywords.join(", ");

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const entry = await api.createLibraryEntry("character", chapter.project_id, {
        name: name.trim(),
        visual_description: description.trim(),
        prompt_keywords: parseTags(keywords),
        lora_name: null,
        lora_weight: 0.8,
        lora_trigger_words: "",
        // Le nom écrit par le scénario reste reconnu s'il diffère du nom de la fiche.
        aliases: name.trim().toLowerCase() === member.name.toLowerCase() ? [] : [member.name],
      });
      setCreated(entry as Character);
      toast(`Fiche « ${entry.name} » créée`);
      onCreated();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <div className="space-y-3 text-sm text-zinc-300" data-testid="cast-draft-created">
        <Alert tone="info">
          Fiche « {created.name} » créée. Il lui faut encore une image de référence :{" "}
          {member.role === "principal" ? "la planche (portrait puis turnaround)" : "un portrait suffit"}.
        </Alert>
        <div className="flex gap-2">
          <Link
            href={`${entryHref("character", created.id)}#references`}
            className="rounded-md bg-rose-500 px-3 py-2 text-sm font-medium text-white hover:bg-rose-400"
          >
            Créer ses références
          </Link>
          <Button variant="ghost" onClick={onClose}>
            Fermer
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 text-sm" data-testid="cast-draft-form">
      <p className="text-zinc-400">
        Préremplie depuis {d.panel_count} case{d.panel_count > 1 ? "s" : ""} où apparaît « {d.written} ». Relis et
        corrige avant d&apos;enregistrer.
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {(
          [
            ["Âge", d.age],
            ["Silhouette", d.silhouette],
            ["Tenue", d.tenue],
            ["Signe distinctif", d.signe_distinctif],
          ] as const
        )
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-zinc-500">{k}</dt>
              <dd className="text-zinc-200">{v}</dd>
            </div>
          ))}
      </dl>
      {error && <Alert>{error}</Alert>}
      <Field label="Nom de la fiche" htmlFor="cast-draft-name">
        <Input id="cast-draft-name" value={name} maxLength={120} onChange={(e) => setEdited({ ...edited, name: e.target.value })} />
      </Field>
      <Field label="Description visuelle" htmlFor="cast-draft-description">
        <Textarea
          id="cast-draft-description"
          rows={5}
          value={description}
          maxLength={4000}
          onChange={(e) => setEdited({ ...edited, visual_description: e.target.value })}
        />
      </Field>
      <Field label="Mots-clés (séparés par des virgules)" htmlFor="cast-draft-keywords">
        <Input id="cast-draft-keywords" value={keywords} onChange={(e) => setEdited({ ...edited, keywords: e.target.value })} />
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Annuler
        </Button>
        <Button onClick={save} disabled={busy || !name.trim()} data-testid="cast-draft-save">
          {busy ? "Création…" : "Créer la fiche"}
        </Button>
      </div>
    </div>
  );
}

/** Résumé de la distribution sur la page du chapitre : qui manque, et le lien vers le panneau complet. */
export function CastSummary() {
  const { chapter, stages } = useChapter();
  const cast = useEngineData(
    () => api.chapterCast(chapter.id),
    // Relu quand la garde d'étapes change (fiche créée, image gardée, foule marquée).
    [chapter.id, stages],
  );
  const data = cast.data;
  if (!data || data.members.length === 0) return null;
  const missing = data.members.filter((m) => m.fault);
  return (
    <Card data-testid="cast-summary">
      <h2 className="mb-2 flex items-center gap-1.5 font-semibold text-zinc-100">
        Distribution
        <InfoTip help="direction.distribution" label="Distribution du chapitre" />
      </h2>
      <p className="text-sm text-zinc-400">
        {data.total} intervenant{data.total > 1 ? "s" : ""}
        {data.marks.length > 0 && ` (+ ${data.marks.length} foule${data.marks.length > 1 ? "s" : ""} sans fiche)`}
        {missing.length === 0 && " · tous prêts"}
      </p>
      {missing.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-sm">
          {missing.slice(0, 8).map((m) => (
            <li key={m.key} className="text-amber-200">
              ⚠ {m.name} <span className="text-xs text-amber-300/80">— {castFaultLabel(m)}</span>
            </li>
          ))}
          {missing.length > 8 && <li className="text-xs text-zinc-500">… et {missing.length - 8} autres</li>}
        </ul>
      )}
      <Link
        href={`/chapitres/${chapter.id}/direction`}
        className="mt-3 inline-block text-sm text-rose-300 hover:text-rose-200"
        data-testid="cast-summary-link"
      >
        {missing.length ? "Régler dans la Direction artistique" : "Voir la distribution"}
      </Link>
    </Card>
  );
}
