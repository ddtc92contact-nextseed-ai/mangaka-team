// Pastille d'une image de référence envoyée au workflow (inspecteur de case de l'atelier).
// Le `kind` vient du moteur : personnage, objet, décor, référence de style de la série… et
// demain peut-être autre chose. Un type inconnu doit s'afficher, jamais faire planter l'atelier.
import type { DroppedReference, UsedReference } from "./api";

export interface UsedReferenceKindInfo {
  singular: string;
  badge: string;
}

export interface UsedReferenceBadge {
  /** Classes Tailwind de la pastille. */
  badge: string;
  /** Nom affiché (nom de l'entrée, ou repli « personnage n° 3 »). */
  name: string;
  /** Type affiché après le nom. */
  kindLabel: string;
}

export const STYLE_REFERENCE_BADGE = "bg-sky-500/15 text-sky-200";
const UNKNOWN_REFERENCE_BADGE = "bg-zinc-500/15 text-zinc-300";

/** « Référence non envoyée : Stan (personnage), Épée (objet) » ; null si rien n'a été écarté. */
export function droppedReferencesNote(
  refs: readonly DroppedReference[] | null | undefined,
  kinds: Readonly<Record<string, UsedReferenceKindInfo>>,
): string | null {
  if (!refs || refs.length === 0) return null;
  const items = refs.map((r) => {
    const d = describeUsedReference({ ...r, image_id: 0 }, kinds);
    return `${d.name} (${d.kindLabel})`;
  });
  return `Référence${refs.length > 1 ? "s" : ""} non envoyée${refs.length > 1 ? "s" : ""} : ${items.join(", ")}`;
}

/** Décrit une référence utilisée ; `kinds` = types de la bibliothèque (`LIBRARY_KINDS`). */
export function describeUsedReference(
  ref: UsedReference,
  kinds: Readonly<Record<string, UsedReferenceKindInfo>>,
): UsedReferenceBadge {
  const kind: string = ref.kind ?? "character";
  if (kind === "style") {
    return { badge: STYLE_REFERENCE_BADGE, name: ref.name ?? "Référence de style", kindLabel: "style de la série" };
  }
  const info = Object.prototype.hasOwnProperty.call(kinds, kind) ? kinds[kind] : undefined;
  const singular = info?.singular ?? "référence";
  return {
    badge: info?.badge ?? UNKNOWN_REFERENCE_BADGE,
    name: ref.name ?? `${singular} n° ${ref.id ?? ref.character_id ?? ref.image_id ?? "?"}`,
    kindLabel: info ? singular : kind,
  };
}
