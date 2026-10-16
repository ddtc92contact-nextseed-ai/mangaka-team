"use client";

import Link from "next/link";
import { useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { useToast } from "@/components/toast";
import { Button, Select } from "@/components/ui";
import { api, errorMessage, type Character, type NameNote, type PageData, type PanelDetail } from "@/lib/api";

const KIND_LABELS: Record<NameNote["kind"], string> = {
  ambigu: "ambigu",
  "sans fiche": "sans fiche",
  "non déclaré": "non déclaré",
  "hors cadre en action": "hors cadre en action",
};

/** Alertes d'une case à montrer dans l'inspecteur (les noms présents sans fiche ont déjà leur bloc). */
export function inspectorNotes(notes: NameNote[] | undefined): NameNote[] {
  return (notes ?? []).filter((n) => !(n.kind === "sans fiche" && n.source === "image"));
}

/**
 * Noms de personnages d'une case qui demandent l'avis de l'auteur (moteur : pipeline/names.py) : un nom
 * générique qui désigne plusieurs fiches (« trafiquant » → trafiquant 1 et trafiquant 2, la première est
 * retenue), un nom sans fiche, un personnage nommé par le texte sans être déclaré (dessiné sans sa
 * référence), ou déclaré hors cadre alors que le texte lui donne une action visible. Rien n'est perdu en silence :
 * chaque alerte se corrige ici, en un clic.
 */
export function NameNotes({
  detail,
  characters,
  onChanged,
}: {
  detail: PanelDetail;
  characters: Character[];
  onChanged: (next?: PanelDetail) => void;
}) {
  const notes = inspectorNotes(detail.name_notes);
  if (notes.length === 0) return null;
  return (
    <div
      role="status"
      className="space-y-2 rounded-lg border border-amber-600/50 bg-amber-950/30 p-3 text-sm text-amber-100"
      data-testid="name-notes"
    >
      <p className="flex items-center gap-1.5 font-medium">
        <span aria-hidden>⚠</span>
        {notes.length > 1 ? `${notes.length} noms de personnages à vérifier` : "Nom de personnage à vérifier"}
        <InfoTip help="atelier.name-notes" label="Noms de personnages à vérifier" />
      </p>
      <ul className="space-y-2">
        {notes.map((note) => (
          <NoteRow
            key={`${note.kind}-${note.source}-${note.name}`}
            note={note}
            detail={detail}
            characters={characters}
            onChanged={onChanged}
          />
        ))}
      </ul>
    </div>
  );
}

function NoteRow({
  note,
  detail,
  characters,
  onChanged,
}: {
  note: NameNote;
  detail: PanelDetail;
  characters: Character[];
  onChanged: (next?: PanelDetail) => void;
}) {
  // Les fiches à égalité d'abord : le choix le plus probable est en tête de liste.
  const options = note.candidates.length ? note.candidates : characters.map((c) => ({ id: c.id, name: c.name }));
  const [choice, setChoice] = useState<string>(note.chosen.length === 1 ? String(note.chosen[0].id) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function run(action: () => Promise<PanelDetail | undefined>, done: string) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      toast(done);
      onChanged(next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function link() {
    const card = options.find((c) => String(c.id) === choice);
    if (!card) return;
    void run(async () => {
      await api.linkCharacterName(detail.chapter_id, note.name, card.id);
      return undefined; // l'inspecteur relit la case
    }, `« ${note.name} » rattaché à ${card.name} (alias de la fiche, pour toute la série)`);
  }

  // Nom envoyé à la case : celui de la fiche retenue quand il n'y en a qu'une (sa référence part à coup sûr).
  const cardNames = note.chosen.length && note.candidates.length === 0 ? note.chosen.map((c) => c.name) : [note.name];
  const label = cardNames.join(" et ");

  function declare(where: "image" | "offscreen") {
    const body =
      where === "image"
        ? { characters: [...detail.characters, ...cardNames] }
        : { offscreen_characters: [...(detail.offscreen_characters ?? []), ...cardNames] };
    void run(
      () => api.updatePanel(detail.id, body),
      where === "image" ? `${label} ajouté à la case (dans l'image)` : `${label} déclaré hors cadre`,
    );
  }

  /** « Laisser hors cadre » : choix retenu (plus d'alerte), son action visible est retirée du prompt envoyé. */
  function keepOffscreen() {
    const ids = note.chosen.map((c) => c.id);
    const kept = [...(detail.offscreen_kept ?? []), ...ids.filter((id) => !(detail.offscreen_kept ?? []).includes(id))];
    void run(
      () => api.updatePanel(detail.id, { offscreen_kept: kept }),
      `${label} laissé hors cadre : son action est retirée du prompt`,
    );
  }

  const selectId = `name-note-${detail.id}-${note.source}-${note.name}`.replace(/\W+/g, "-");
  return (
    <li className="space-y-1.5" data-testid="name-note" data-kind={note.kind}>
      <p className="text-xs leading-5">
        <span className="mr-1.5 rounded bg-amber-500/20 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-amber-200">
          {KIND_LABELS[note.kind]}
        </span>
        {note.message}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {note.kind === "hors cadre en action" && (
          <>
            <Button
              className="!px-2 !py-1 text-xs"
              onClick={() => declare("image")}
              disabled={busy}
              title="Le personnage passe dans l'image : sa fiche (image de référence) part avec la case"
            >
              Mettre dans l&apos;image
            </Button>
            <Button
              variant="secondary"
              className="!px-2 !py-1 text-xs"
              onClick={keepOffscreen}
              disabled={busy}
              title="Il reste hors cadre : son action visible est retirée du prompt envoyé au modèle"
            >
              Laisser hors cadre
            </Button>
          </>
        )}
        {note.kind === "non déclaré" && (
          <>
            <Button
              className="!px-2 !py-1 text-xs"
              onClick={() => declare("image")}
              disabled={busy}
              title="Le personnage est déclaré dans l'image : sa fiche (image de référence) part avec la case"
            >
              Ajouter à la case
            </Button>
            <Button
              variant="secondary"
              className="!px-2 !py-1 text-xs"
              onClick={() => declare("offscreen")}
              disabled={busy}
              title="Cité mais hors du cadre : ni dessiné, ni image de référence"
            >
              Hors cadre
            </Button>
          </>
        )}
        {note.kind === "hors cadre en action" ? null : note.kind !== "non déclaré" || note.candidates.length > 0 ? (
          options.length > 0 ? (
            <>
              <label htmlFor={selectId} className="sr-only">
                Fiche désignée par « {note.name} »
              </label>
              <Select
                id={selectId}
                className="!w-44 py-1 text-xs"
                value={choice}
                onChange={(e) => setChoice(e.target.value)}
                disabled={busy}
              >
                <option value="">Choisir une fiche…</option>
                {options.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
              <Button
                variant="secondary"
                className="!px-2 !py-1 text-xs"
                onClick={link}
                disabled={busy || !choice}
                title={`« ${note.name} » devient un alias de la fiche choisie : le choix vaut pour toute la série`}
              >
                Rattacher
              </Button>
            </>
          ) : (
            <Link href={`/projets/${detail.project_id}/personnages/nouveau`} className="text-xs text-amber-200 underline">
              Créer la fiche
            </Link>
          )
        ) : null}
        {note.chosen.length === 1 && (
          <Link href={`/personnages/${note.chosen[0].id}`} className="text-xs text-amber-200 underline">
            Fiche {note.chosen[0].name}
          </Link>
        )}
      </div>
      {error && <p className="text-xs text-red-300">{error}</p>}
    </li>
  );
}

/**
 * Résumé du chapitre dans l'atelier : chaque case dont un nom de personnage est ambigu, sans fiche ou cité
 * sans être déclaré, avec le nom lu, la fiche retenue (ou aucune) et un lien qui ouvre la case pour corriger.
 */
export function ChapterNameNotes({
  pages,
  onOpenPanel,
}: {
  pages: PageData[];
  onOpenPanel: (pageId: number, panelId: number) => void;
}) {
  const rows = pages.flatMap((page) =>
    page.panels.flatMap((panel) =>
      (panel.name_notes ?? []).map((note) => ({ page, panel, note })),
    ),
  );
  if (rows.length === 0) return null;
  const panels = new Set(rows.map((r) => r.panel.id)).size;
  return (
    <details className="rounded-lg border border-amber-600/50 bg-amber-950/30 p-3 text-sm text-amber-100" data-testid="chapter-name-notes">
      <summary className="cursor-pointer font-medium">
        <span aria-hidden>⚠ </span>
        {rows.length} nom{rows.length > 1 ? "s" : ""} de personnage à vérifier dans {panels} case{panels > 1 ? "s" : ""}
        <span className="font-normal text-amber-200/80"> — ambigus, sans fiche, non déclarés ou hors cadre en action : ils seraient dessinés sans leur référence.</span>
      </summary>
      <ul className="mt-2 space-y-1.5">
        {rows.map(({ page, panel, note }) => (
          <li
            key={`${panel.id}-${note.kind}-${note.source}-${note.name}`}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs"
            data-testid="chapter-name-note"
          >
            <button
              type="button"
              onClick={() => onOpenPanel(page.id, panel.id)}
              className="rounded px-1 font-medium text-amber-200 underline hover:bg-amber-500/10 focus-visible:outline-2 focus-visible:outline-rose-400"
            >
              p. {page.number} · case {panel.index + 1}
            </button>
            <span className="rounded bg-amber-500/20 px-1.5 text-[11px] uppercase tracking-wide text-amber-200">{note.kind}</span>
            <span>
              « {note.name} » · fiche retenue :{" "}
              {note.chosen.length ? note.chosen.map((c) => c.name).join(" et ") : "aucune"}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
