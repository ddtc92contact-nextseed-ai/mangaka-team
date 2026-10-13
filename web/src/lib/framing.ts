// Qui est dans l'image d'une case (moteur : pipeline/framing.py) : présents, hors cadre, point de vue.
// Fonctions pures, importées par l'inspecteur de case et testées par `npm test`.

export type ViewpointMode = "reaction" | "subjective";

export const VIEWPOINT_LABELS: Record<ViewpointMode, string> = {
  reaction: "Plan de réaction",
  subjective: "Vue subjective",
};

export const VIEWPOINT_HELP: Record<ViewpointMode, string> = {
  reaction: "le spectateur est dessiné, avec ce qu'il voit",
  subjective: "on voit ce qu'il voit : le spectateur reste hors cadre",
};

export const VIEWPOINT_SOURCES: Record<string, string> = {
  direction: "choisi par la direction artistique",
  défaut: "choix par défaut (la direction artistique n'a pas tranché)",
  auteur: "choisi par toi",
};

/** Forme comparable d'un nom (casse et accents retirés), comme `name_key` du moteur. */
export function nameKey(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function without(names: string[], removed: string): string[] {
  const key = nameKey(removed);
  return names.filter((n) => nameKey(n) !== key);
}

export interface Cast {
  characters: string[];
  offscreen: string[];
}

/** Sort un personnage du cadre : il reste cité, mais n'est plus dessiné. */
export function moveOffscreen(cast: Cast, name: string): Cast {
  return { characters: without(cast.characters, name), offscreen: [...without(cast.offscreen, name), name] };
}

/** Remet un personnage hors cadre dans l'image. */
export function moveInFrame(cast: Cast, name: string): Cast {
  return { characters: [...without(cast.characters, name), name], offscreen: without(cast.offscreen, name) };
}

/** Spectateurs proposés au choix du point de vue : ceux du choix en cours, sinon ceux repérés dans le texte. */
export function viewpointSpectators(current: { spectators: string[] } | null | undefined, hints: string[]): string[] {
  return current?.spectators.length ? current.spectators : hints;
}

/**
 * Phrase courte de l'inspecteur : « Vue subjective — Seku, Angus hors cadre ». Avec le casting de la case,
 * chaque spectateur est rangé là où il est vraiment (après une bascule partielle, l'un peut être à l'image
 * et l'autre encore hors cadre) ; sans casting, on suit le mode.
 */
export function viewpointSummary(mode: ViewpointMode, spectators: string[], cast?: Cast): string {
  if (!spectators.length) return VIEWPOINT_LABELS[mode];
  const inFrame = new Set((cast?.characters ?? []).map(nameKey));
  const offscreen = new Set((cast?.offscreen ?? []).map(nameKey));
  const shown: string[] = [];
  const hidden: string[] = [];
  for (const s of spectators) {
    const key = nameKey(s);
    const isShown = inFrame.has(key) ? true : offscreen.has(key) ? false : mode === "reaction";
    (isShown ? shown : hidden).push(s);
  }
  const parts = [
    shown.length ? `${shown.join(", ")} à l'image` : "",
    hidden.length ? `${hidden.join(", ")} hors cadre` : "",
  ].filter(Boolean);
  return `${VIEWPOINT_LABELS[mode]} — ${parts.join(", ")}`;
}
