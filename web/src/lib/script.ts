// Vocabulaire du découpage (mêmes valeurs que le moteur : pipeline/script.py).
import type { BriefNote, BubbleKind, PageData, PageInput, PageKind, PanelInput, Rythme } from "./api";

export const SHOT_TYPES = [
  "plan d'ensemble",
  "plan large",
  "plan moyen",
  "plan américain",
  "plan rapproché",
  "gros plan",
  "très gros plan",
  "plongée",
  "contre-plongée",
  "vue subjective",
  "insert",
] as const;

export const BUBBLE_KINDS: Record<BubbleKind, string> = {
  speech: "Parole",
  thought: "Pensée",
  shout: "Cri",
  narration: "Récitatif",
  off: "Hors champ",
};

export const PAGE_KINDS: Record<PageKind, string> = {
  story: "Histoire",
  bonus: "Bonus (croquis, notes)",
  chapter_cover: "Page de garde",
};

export const IMPORTANCE: Record<number, string> = {
  1: "1 · transition",
  2: "2 · normale",
  3: "3 · forte",
};

// --- brouillon éditable ---------------------------------------------------------
let seq = 0;
const key = () => `k${++seq}`;

export interface DraftDialogue {
  key: string;
  /** Bulle en base : renvoyée au moteur pour garder son lettrage (cadre, queue) ; absente = nouvelle réplique. */
  id?: number;
  speaker: string;
  text: string;
  kind: BubbleKind;
}

export interface DraftPanel extends Omit<PanelInput, "characters" | "dialogues" | "decor" | "objets" | "setting" | "staging" | "location"> {
  key: string;
  charactersText: string;
  /** Décor de la case et mise en scène (prompt image : « Setting: … », « Staging: … »). */
  setting: string;
  staging: string;
  /** Noms sans fiche personnage, d'après le moteur (dernier enregistrement). */
  unmatched: string[];
  /** Défauts du brief d'image, d'après le moteur (dernier enregistrement). */
  briefNotes: BriefNote[];
  /** Bibliothèque de la série : décor (id) et objets (ids) de la case. */
  decor: number | null;
  objets: number[];
  /** Lieu de la série (unité de lieu) ; `setting` décrit ce qu'on en voit dans la case. */
  location: number | null;
  dialogues: DraftDialogue[];
}

export interface DraftPage {
  key: string;
  id?: number;
  kind: PageKind;
  rythme: Rythme | null;
  panels: DraftPanel[];
  /** Scène du chapitre (étape Scènes), gardée par le moteur tant que la page garde son id. */
  sceneId?: number | null;
  /** Défauts du brief d'image de la page (emplacements du gabarit), d'après le moteur. */
  briefNotes?: BriefNote[];
}

export function toDraft(pages: PageData[]): DraftPage[] {
  return pages.map((p) => ({
    key: key(),
    id: p.id,
    kind: p.kind,
    rythme: p.rythme,
    sceneId: p.scene_id ?? null,
    briefNotes: p.brief_notes ?? [],
    panels: p.panels.map((pa) => ({
      key: key(),
      id: pa.id,
      description: pa.description,
      setting: pa.setting ?? "",
      staging: pa.staging ?? "",
      unmatched: pa.unmatched_characters ?? [],
      briefNotes: pa.brief_notes ?? [],
      charactersText: pa.characters.join(", "),
      decor: pa.decor ?? null,
      objets: pa.objets ?? [],
      location: pa.location ?? null,
      shot_type: pa.shot_type,
      importance: pa.importance,
      intensity: pa.intensity,
      dialogues: pa.dialogues.map((d) => ({ key: key(), id: d.id, speaker: d.speaker, text: d.text, kind: d.kind })),
    })),
  }));
}

export function fromDraft(pages: DraftPage[]): PageInput[] {
  return pages.map((p) => ({
    id: p.id,
    kind: p.kind,
    rythme: p.rythme,
    panels: p.panels.map((pa) => ({
      id: pa.id,
      description: pa.description,
      setting: pa.setting,
      staging: pa.staging,
      characters: pa.charactersText
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean),
      decor: pa.decor,
      objets: pa.objets,
      location: pa.location,
      shot_type: pa.shot_type || null,
      importance: pa.importance,
      intensity: pa.intensity ?? null,
      dialogues: pa.dialogues
        .filter((d) => d.text.trim())
        .map((d) => ({ id: d.id, speaker: d.speaker, text: d.text, kind: d.kind })),
    })),
  }));
}

export const newPanel = (): DraftPanel => ({
  key: key(),
  description: "",
  setting: "",
  staging: "",
  unmatched: [],
  briefNotes: [],
  charactersText: "",
  decor: null,
  objets: [],
  location: null,
  shot_type: null, // le plan vient de la direction artistique
  importance: 2,
  dialogues: [],
});

export const newDialogue = (): DraftDialogue => ({ key: key(), speaker: "", text: "", kind: "speech" });

export const newPage = (kind: PageKind = "story"): DraftPage => ({
  key: key(),
  kind,
  rythme: null,
  panels: kind === "story" ? [newPanel()] : [],
});

export function moveItem<T>(list: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const out = [...list];
  [out[index], out[target]] = [out[target], out[index]];
  return out;
}

/** Noms sans fiche encore cités par la case (le brouillon a pu en retirer depuis l'enregistrement). */
export function unmatchedNames(panel: DraftPanel): string[] {
  const cited = new Set(
    panel.charactersText
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean),
  );
  return panel.unmatched.filter((n) => cited.has(n));
}
