"use client";

import { createContext, useContext } from "react";
import type { Chapter, Project } from "@/lib/api";

export interface ChapterContextValue {
  chapter: Chapter;
  series: Project;
  setChapter: (c: Chapter) => void;
  reload: () => void;
}

export const ChapterContext = createContext<ChapterContextValue | null>(null);

export function useChapter(): ChapterContextValue {
  const ctx = useContext(ChapterContext);
  if (!ctx) throw new Error("useChapter hors de ChapterContext");
  return ctx;
}
