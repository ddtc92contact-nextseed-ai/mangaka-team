"use client";

import Link from "next/link";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { EstimateLabel } from "@/components/estimate";
import { ChapterStatusBadge, formatPlannedDate } from "@/components/status";
import { Alert, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { hrefPath, withPage } from "@/lib/stages";
import { ChapterContext } from "./chapter-context";

/** Une adresse `?page=` explicite devient la planche courante du chapitre (elle prime toujours). */
function PageParamSync({ onPage }: { onPage: (id: number) => void }) {
  const page = Number(useSearchParams().get("page")) || null;
  useEffect(() => {
    if (page) onPage(page);
  }, [page, onPage]);
  return null;
}

export default function ChapterLayout({ children }: { children: ReactNode }) {
  const id = Number(useParams<{ id: string }>().id);
  const pathname = usePathname();
  // Planche courante, propre à ce chapitre (un autre chapitre repart sans planche).
  const [current, setCurrent] = useState<{ chapter: number; page: number | null }>({ chapter: id, page: null });
  const currentPageId = current.chapter === id ? current.page : null;
  const setCurrentPageId = useCallback(
    (page: number | null) =>
      setCurrent((prev) => (prev.chapter === id && prev.page === page ? prev : { chapter: id, page })),
    [id],
  );
  const chapter = useEngineData(() => api.getChapter(id), [id]);
  const projectId = chapter.data?.project_id;
  // Étapes vitales : relues à chaque changement d'onglet (une action d'un autre écran a pu les régler).
  const stages = useEngineData(() => api.chapterStages(id), [id, pathname]);
  const series = useEngineData(
    () => (projectId ? api.getProject(projectId) : Promise.resolve(null)),
    [projectId],
  );

  if (chapter.loading && !chapter.data) return <Loading />;
  if (chapter.error || !chapter.data) return <Alert>{chapter.error ?? "Chapitre introuvable"}</Alert>;
  if (series.error) return <Alert>{series.error}</Alert>;
  if (!series.data) return <Loading />;

  const c = chapter.data;
  // Chaque onglet garde la planche courante (`?page=`) : Atelier planche 5 → Lettrage reste sur la planche 5.
  const tabs = [
    { href: `/chapitres/${id}`, label: "Infos" },
    { href: `/chapitres/${id}/scenes`, label: "Scènes" },
    { href: `/chapitres/${id}/scenario`, label: "Scénario" },
    { href: `/chapitres/${id}/direction`, label: "Direction artistique" },
    { href: `/chapitres/${id}/mise-en-page`, label: "Mise en page" },
    ...(series.data.sketch_enabled ? [{ href: `/chapitres/${id}/croquis`, label: "Croquis" }] : []),
    { href: `/chapitres/${id}/atelier`, label: "Atelier" },
    { href: `/chapitres/${id}/lettrage`, label: "Lettrage" },
    { href: `/chapitres/${id}/production`, label: "Production" },
  ].map((t) => ({ ...t, href: withPage(t.href, currentPageId) }));

  return (
    <ChapterContext.Provider
      value={{
        chapter: c,
        series: series.data,
        setChapter: chapter.setData,
        reload: chapter.reload,
        stages: stages.data,
        stagesError: stages.error,
        setStages: stages.setData,
        reloadStages: stages.reload,
        currentPageId,
        setCurrentPageId,
      }}
    >
      <Suspense fallback={null}>
        <PageParamSync onPage={setCurrentPageId} />
      </Suspense>
      <PageHeader
        title={`Chapitre ${c.number}${c.title ? ` — ${c.title}` : ""}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <Link href={`/projets/${c.project_id}`} className="hover:text-zinc-200">
              ← {c.series_title}
            </Link>
            <ChapterStatusBadge status={c.status} />
            <span>Publication : {formatPlannedDate(c.planned_date)}</span>
            <EstimateLabel chapterId={c.id} />
          </span>
        }
      />
      <nav className="mb-6 flex flex-wrap gap-1 border-b border-zinc-800" aria-label="Étapes du chapitre">
        {tabs.map((t) => {
          const active = pathname === hrefPath(t.href);
          return (
            <Link
              key={t.label}
              href={t.href}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
                active ? "border-rose-400 text-zinc-50" : "border-transparent text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </ChapterContext.Provider>
  );
}
