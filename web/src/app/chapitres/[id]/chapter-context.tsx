"use client";

import { createContext, useContext, useEffect } from "react";
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
  /**
   * Planche courante du chapitre : la dernière affichée par une section (Atelier, Croquis, Lettrage…),
   * recopiée dans les onglets et les liens d'étape (`?page=`). null tant qu'aucune section n'en a montré.
   */
  currentPageId: number | null;
  setCurrentPageId: (id: number | null) => void;
}

export const ChapterContext = createContext<ChapterContextValue | null>(null);

export function useChapter(): ChapterContextValue {
  const ctx = useContext(ChapterContext);
  if (!ctx) throw new Error("useChapter hors de ChapterContext");
  return ctx;
}

/**
 * Planche voulue par une section : `explicit` (adresse `?page=`, ou choix fait dans la section) prime
 * toujours, sinon la planche courante du chapitre.
 */
export function useWantedPage(explicit: number | null): number | null {
  const { currentPageId } = useChapter();
  return explicit ?? currentPageId;
}

/** La planche affichée par une section devient la planche courante du chapitre. */
export function useRememberPage(shown: number | null | undefined) {
  const { currentPageId, setCurrentPageId } = useChapter();
  useEffect(() => {
    if (shown && shown !== currentPageId) setCurrentPageId(shown);
  }, [shown, currentPageId, setCurrentPageId]);
}
