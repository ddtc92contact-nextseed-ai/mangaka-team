"use client";

import { createContext, useContext } from "react";
import type { Chapter, ChapterStages, Project } from "@/lib/api";

export interface ChapterContextValue {
  chapter: Chapter;
  series: Project;
  setChapter: (c: Chapter) => void;
  reload: () => void;
  /** Étapes vitales du chapitre (garde d'étapes) ; null pendant le chargement. */
  stages: ChapterStages | null;
  stagesError: string | null;
  setStages: (s: ChapterStages) => void;
  /** À appeler après une action qui change le chapitre (génération, direction appliquée…). */
  reloadStages: () => void;
}

export const ChapterContext = createContext<ChapterContextValue | null>(null);

export function useChapter(): ChapterContextValue {
  const ctx = useContext(ChapterContext);
  if (!ctx) throw new Error("useChapter hors de ChapterContext");
  return ctx;
}
