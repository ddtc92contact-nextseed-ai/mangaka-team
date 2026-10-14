// Distribution du chapitre (moteur : pipeline/cast.py) : libellés et petits calculs du panneau « Distribution »
// de la direction artistique et de son résumé sur la page du chapitre.
import type { CastMember, CastReferences, ChapterCast } from "./api";

export const REFERENCE_LABELS: Record<CastReferences, string> = {
  aucune: "aucune image",
  portrait: "portrait seul",
  planche: "planche complète",
};

/** « sans fiche : ni référence ni description », « fiche sans image de référence ». */
export function castFaultLabel(m: Pick<CastMember, "fault">): string {
  if (m.fault === "sans fiche") return "sans fiche : ni référence ni description";
  if (m.fault === "sans image") return "fiche sans image de référence";
  return "";
}

/** Secondaires que « Tout créer pour les secondaires » prend en charge (fiche à créer ou portrait à faire ; les
 * foules anonymes se marquent à part). */
export function secondariesToCreate(cast: Pick<ChapterCast, "members">): CastMember[] {
  return cast.members.filter((m) => m.role === "secondaire" && m.fault !== null && !m.crowd);
}

export function castCounts(cast: Pick<ChapterCast, "members">) {
  return {
    secondaries: secondariesToCreate(cast).length,
    withoutCard: cast.members.filter((m) => m.fault === "sans fiche").length,
    withoutImage: cast.members.filter((m) => m.fault === "sans image").length,
  };
}
