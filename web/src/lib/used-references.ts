// Pastille d'une image de référence envoyée au workflow (inspecteur de case de l'atelier).
// Le `kind` vient du moteur : personnage, objet, décor, référence de style de la série… et
// demain peut-être autre chose. Un type inconnu doit s'afficher, jamais faire planter l'atelier.
import type { UsedReference } from "./api";

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
