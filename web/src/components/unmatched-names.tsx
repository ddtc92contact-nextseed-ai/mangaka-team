"use client";

import Link from "next/link";
import { useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { useToast } from "@/components/toast";
import { Button, Select } from "@/components/ui";
import { api, errorMessage, type Character } from "@/lib/api";

/**
 * Noms de personnages écrits par le scénario qui ne désignent aucune fiche (moteur : pipeline/names.py).
 * Chaque nom se rattache en un clic à une fiche (il en devient un alias, pour tout le chapitre et la série)
 * ou s'écarte comme figurant. `disabled` : découpage modifié non enregistré (le rattachement relit les cases).
 */
export function UnmatchedNames({
  chapterId,
  projectId,
  names,
  characters,
  onLinked,
  disabled = false,
  disabledReason,
}: {
  chapterId: number;
  projectId: number;
  names: string[];
  characters: Character[];
  onLinked: () => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  if (names.length === 0) return null;
  return (
    <div
      role="status"
      className="space-y-2 rounded-lg border border-amber-600/50 bg-amber-950/30 p-3 text-sm text-amber-100"
      data-testid="unmatched-names"
    >
      <p className="flex items-center gap-1.5 font-medium">
        <span aria-hidden>⚠</span>
        {names.length > 1
          ? `${names.length} personnages sans fiche : ils seraient dessinés sans leurs références ni leur description.`
          : "Personnage sans fiche : il serait dessiné sans ses références ni sa description."}
        <InfoTip help="scenario.unmatched" label="Personnages sans fiche" />
      </p>
      {disabled && disabledReason && <p className="text-xs text-amber-300/80">{disabledReason}</p>}
      <ul className="space-y-1.5">
        {names.map((name) => (
          <UnmatchedRow
            key={name}
            chapterId={chapterId}
            projectId={projectId}
            name={name}
            characters={characters}
            onLinked={onLinked}
            disabled={disabled}
          />
        ))}
      </ul>
    </div>
  );
}

function UnmatchedRow({
  chapterId,
  projectId,
  name,
  characters,
  onLinked,
  disabled,
}: {
  chapterId: number;
  projectId: number;
  name: string;
  characters: Character[];
  onLinked: () => void;
  disabled: boolean;
}) {
  const [choice, setChoice] = useState<string>(characters.length === 1 ? String(characters[0].id) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function link(characterId: number | null) {
    setBusy(true);
    setError(null);
    try {
      const done = await api.linkCharacterName(chapterId, name, characterId);
      const card = characters.find((c) => c.id === characterId);
      toast(
        card
          ? `« ${name} » rattaché à ${card.name}${done.alias_added ? " (nouvel alias)" : ""}`
          : `« ${name} » écarté (figurant sans fiche)`,
      );
      onLinked();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const selectId = `unmatched-${name.replace(/\W+/g, "-")}`;
  return (
    <li className="flex flex-wrap items-center gap-2" data-testid="unmatched-name">
      <span className="rounded bg-amber-500/20 px-2 py-0.5 font-medium text-amber-100">« {name} »</span>
      {characters.length > 0 ? (
        <>
          <label htmlFor={selectId} className="sr-only">
            Fiche à rattacher à « {name} »
          </label>
          <Select
            id={selectId}
            className="!w-44 py-1 text-xs"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            disabled={disabled || busy}
          >
            <option value="">Choisir une fiche…</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button
            className="!px-2 !py-1 text-xs"
            onClick={() => link(Number(choice))}
            disabled={disabled || busy || !choice}
          >
            Rattacher
          </Button>
        </>
      ) : (
        <Link href={`/projets/${projectId}/personnages/nouveau`} className="text-xs text-amber-200 underline">
          Créer la fiche
        </Link>
      )}
      <Button
        variant="ghost"
        className="!px-2 !py-1 text-xs"
        onClick={() => link(null)}
        disabled={disabled || busy}
        title="Figurant sans fiche : retiré des personnages des cases (la description ne change pas)"
      >
        Écarter (figurant)
      </Button>
      {error && <span className="text-xs text-red-300">{error}</span>}
    </li>
  );
}
