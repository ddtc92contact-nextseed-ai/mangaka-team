// Vocabulaire du découpage (mêmes valeurs que le moteur : pipeline/script.py).
import type { BubbleKind, PageData, PageInput, PageKind, PanelInput } from "./api";

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
  speaker: string;
  text: string;
  kind: BubbleKind;
}

export interface DraftPanel extends Omit<PanelInput, "characters" | "dialogues"> {
  key: string;
  charactersText: string;
  dialogues: DraftDialogue[];
}

export interface DraftPage {
  key: string;
  id?: number;
  kind: PageKind;
  panels: DraftPanel[];
}

export function toDraft(pages: PageData[]): DraftPage[] {
  return pages.map((p) => ({
    key: key(),
    id: p.id,
    kind: p.kind,
    panels: p.panels.map((pa) => ({
      key: key(),
      id: pa.id,
      description: pa.description,
      charactersText: pa.characters.join(", "),
      shot_type: pa.shot_type,
      importance: pa.importance,
      dialogues: pa.dialogues.map((d) => ({ key: key(), speaker: d.speaker, text: d.text, kind: d.kind })),
    })),
  }));
}

export function fromDraft(pages: DraftPage[]): PageInput[] {
  return pages.map((p) => ({
    id: p.id,
    kind: p.kind,
    panels: p.panels.map((pa) => ({
      id: pa.id,
      description: pa.description,
      characters: pa.charactersText
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean),
      shot_type: pa.shot_type || null,
      importance: pa.importance,
      dialogues: pa.dialogues
        .filter((d) => d.text.trim())
        .map((d) => ({ speaker: d.speaker, text: d.text, kind: d.kind })),
    })),
  }));
}

export const newPanel = (): DraftPanel => ({
  key: key(),
  description: "",
  charactersText: "",
  shot_type: "plan moyen",
  importance: 2,
  dialogues: [],
});

export const newDialogue = (): DraftDialogue => ({ key: key(), speaker: "", text: "", kind: "speech" });

export const newPage = (kind: PageKind = "story"): DraftPage => ({
  key: key(),
  kind,
  panels: kind === "story" ? [newPanel()] : [],
});

export function moveItem<T>(list: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const out = [...list];
  [out[index], out[target]] = [out[target], out[index]];
  return out;
}
