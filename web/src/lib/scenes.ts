// Étape « Scènes » : brouillon de la liste des scènes d'un chapitre (moteur : pipeline/scenes.py) — retouches de
// l'auteur (type, pages, ordre, résumé, lieu, distribution, ajout, suppression, fusion) et total des pages face à la cible.
import type { ChapterSceneItem, SceneInput, SceneTypeId } from "./api";

export interface DraftScene {
  /** Clé React stable (l'id du moteur, ou une clé locale pour une scène ajoutée). */
  key: string;
  id?: number;
  title: string;
  summary: string;
  type: SceneTypeId;
  pages: number;
  location_id: number | null;
  /** Distribution : ids des fiches des personnages qui jouent dans la scène. */
  characters: number[];
}

let counter = 0;
const localKey = () => `nouvelle-${++counter}`;

export function toDraft(scenes: ChapterSceneItem[]): DraftScene[] {
  return scenes.map((s) => ({
    key: `scene-${s.id}`,
    id: s.id,
    title: s.title,
    summary: s.summary,
    type: s.type,
    pages: s.pages,
    location_id: s.location_id,
    characters: (s.characters ?? []).map((c) => c.id),
  }));
}

export function fromDraft(draft: DraftScene[]): SceneInput[] {
  return draft.map((s) => ({
    ...(s.id !== undefined ? { id: s.id } : {}),
    title: s.title.trim(),
    summary: s.summary.trim(),
    type: s.type,
    pages: s.pages,
    location_id: s.location_id,
    characters: [...s.characters],
  }));
}

export function newScene(type: SceneTypeId = "calme", pages = 1): DraftScene {
  return { key: localKey(), title: "", summary: "", type, pages, location_id: null, characters: [] };
}

/** Fusionne la scène `index` avec la suivante : la première garde son id, son type et son titre, les pages
 * s'additionnent, les résumés se suivent. */
export function mergeWithNext(list: DraftScene[], index: number): DraftScene[] {
  if (index < 0 || index >= list.length - 1) return list;
  const a = list[index];
  const b = list[index + 1];
  const merged: DraftScene = {
    ...a,
    title: a.title || b.title,
    summary: [a.summary.trim(), b.summary.trim()].filter(Boolean).join(" "),
    pages: a.pages + b.pages,
    location_id: a.location_id ?? b.location_id,
    characters: [...a.characters, ...b.characters.filter((id) => !a.characters.includes(id))],
  };
  return [...list.slice(0, index), merged, ...list.slice(index + 2)];
}

export function moveScene(list: DraftScene[], index: number, delta: number): DraftScene[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const out = [...list];
  [out[index], out[target]] = [out[target], out[index]];
  return out;
}

/** Ajoute ou retire une fiche de la distribution d'une scène (l'ordre d'ajout est gardé). */
export function toggleCast(characters: number[], id: number): number[] {
  return characters.includes(id) ? characters.filter((c) => c !== id) : [...characters, id];
}

/** Avertissements du pic du chapitre d'une scène (par son id ; une scène nouvelle n'en a pas encore). */
export function peakWarningsFor(warnings: { scene_id: number; message: string }[], id?: number): string[] {
  return id === undefined ? [] : warnings.filter((w) => w.scene_id === id).map((w) => w.message);
}

export const totalPages = (list: { pages: number }[]) => list.reduce((n, s) => n + s.pages, 0);

/** Pages de chaque scène dans le chapitre : « p. 1-3 », « p. 4 ». */
export function pageSpans(list: { pages: number }[]): string[] {
  let first = 1;
  return list.map((s) => {
    const last = first + s.pages - 1;
    const label = s.pages <= 1 ? `p. ${first}` : `p. ${first}-${last}`;
    first = last + 1;
    return label;
  });
}

export type TotalState = "ok" | "over" | "under";

/** Total des pages face à la cible : état et phrase à afficher. */
export function totalStatus(total: number, target: number): { state: TotalState; message: string } {
  if (total === target) return { state: "ok", message: `${total} pages sur ${target} : le compte est bon.` };
  if (total > target) {
    const n = total - target;
    return {
      state: "over",
      message: `${n} page${n > 1 ? "s" : ""} de trop : raccourcis une scène ou reporte-la au chapitre suivant, sans tasser.`,
    };
  }
  const n = target - total;
  return {
    state: "under",
    message: `Il manque ${n} page${n > 1 ? "s" : ""} : donne plus de place à une scène ou ajoutes-en une.`,
  };
}

/** Bornes du nombre de pages d'une scène dans l'écran (le moteur refuse au-delà de son plafond). */
export const MAX_PAGES_PER_SCENE = 12;
