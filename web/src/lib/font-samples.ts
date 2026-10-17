// Tuiles de choix de police (fiche série, onomatopée au lettrage) : textes d'exemple et adresses des polices.
import { engineUrl } from "./api";

/** Ce que montre une tuile : réplique dans une bulle, cri, ou onomatopée hors bulle. */
export type FontSampleKind = "dialogue" | "shout" | "sfx";

/**
 * Seule source des textes d'exemple. Accents français (é è à ç œ, capitales Ê Ç È À) pour vérifier
 * d'un coup d'œil que la police les dessine. Cris et onomatopées en capitales, comme au lettrage ; espace
 * insécable avant « ! » et « ? » (jamais de « !! » seul en début de ligne).
 */
export const FONT_SAMPLES: Record<FontSampleKind, string> = {
  dialogue: "Attends, Hélène\u00a0! Où vas-tu déjà\u00a0? Ça me brise le cœur…",
  shout: "ARRÊTE ÇA, FRÈRE\u00a0!! À MOI\u00a0!",
  sfx: "BOUM\u00a0! CRAC… ÇA PÈTE\u00a0!",
};

/** Style de lettrage du moteur (fonts.yaml › styles) dont la tuile reprend graisse et italique. */
const ENGINE_KIND: Record<FontSampleKind, string> = { dialogue: "speech", shout: "shout", sfx: "sfx" };

function withProject(path: string, projectId?: number): string {
  return engineUrl(projectId ? `${path}?project_id=${projectId}` : path);
}

/** Fichier de la police `fontId`, tel que le lettrage la poserait pour `kind` (route moteur, mise en cache). */
export function fontSampleUrl(kind: FontSampleKind, fontId: string, projectId?: number): string {
  return withProject(`/lettering/font-samples/${ENGINE_KIND[kind]}/${encodeURIComponent(fontId)}.ttf`, projectId);
}

/** Police par défaut du lettreur (fonts.yaml, réglages de l'équipe) pour les dialogues ou les cris. */
export function letteringDefaultFontUrl(kind: "dialogue" | "shout", projectId?: number): string {
  return withProject(`/lettering/fonts/${ENGINE_KIND[kind]}.ttf`, projectId);
}
