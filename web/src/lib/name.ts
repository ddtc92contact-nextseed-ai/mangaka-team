// Name : planche brouillon d'un chapitre lue comme un lecteur (moteur : pipeline/name_board.py).
// Double pages dans le sens de lecture, tourne, compteur des pages validées.
import type { NameState, PageData, ReadingDirection } from "./api";

/**
 * Double pages d'un chapitre, chacune dans l'ordre de lecture (`null` = côté blanc). Le chapitre commence sur
 * une belle page : la page 1 est seule (en face d'un blanc), puis 2–3, 4–5… ; une dernière page paire est seule.
 */
export function spreads<T>(pages: readonly T[]): (T | null)[][] {
  if (!pages.length) return [];
  const out: (T | null)[][] = [[null, pages[0]]];
  for (let i = 1; i < pages.length; i += 2) out.push([pages[i], pages[i + 1] ?? null]);
  return out;
}

/**
 * Côtés de la double page de gauche à droite à l'écran : en manga (rtl), la première page lue est à droite.
 * `null` = côté blanc.
 */
export function visualOrder<T>(spread: readonly (T | null)[], direction: ReadingDirection): (T | null)[] {
  return direction === "rtl" ? [...spread].reverse() : [...spread];
}

/** Page lue juste avant la tourne (la dernière de la double page), ou null pour une double page vide. */
export function turnPage<T>(spread: readonly (T | null)[]): T | null {
  for (let i = spread.length - 1; i >= 0; i--) if (spread[i] !== null) return spread[i];
  return null;
}

/** Double page qui contient la page `pageId` (0 si absente). */
export function spreadOf(all: (PageData | null)[][], pageId: number | null): number {
  const at = all.findIndex((s) => s.some((p) => p?.id === pageId));
  return at < 0 ? 0 : at;
}

/** « Pages 2–3 », « Page 1 ». */
export function spreadLabel(spread: readonly (Pick<PageData, "number"> | null)[]): string {
  const nums = spread.filter((p): p is Pick<PageData, "number"> => p !== null).map((p) => p.number);
  return nums.length > 1 ? `Pages ${nums[0]}–${nums[nums.length - 1]}` : `Page ${nums[0] ?? "?"}`;
}

/** Pages à valider (avec des cases) : validées, caduques, total. */
export function nameCounts(pages: readonly Pick<PageData, "name_state" | "panels">[]): {
  validated: number;
  stale: number;
  total: number;
} {
  const counted = pages.filter((p) => p.panels.length > 0 && p.name_state);
  return {
    validated: counted.filter((p) => p.name_state === "validated").length,
    stale: counted.filter((p) => p.name_state === "stale").length,
    total: counted.length,
  };
}

export const NAME_STATE_LABEL: Record<NameState, string> = {
  validated: "Name validée",
  stale: "Validation levée (case modifiée)",
  pending: "Name à valider",
};

/** Flèche « suivant » de la lecture : vers la gauche en manga. */
export function nextKey(direction: ReadingDirection): "ArrowLeft" | "ArrowRight" {
  return direction === "rtl" ? "ArrowLeft" : "ArrowRight";
}
