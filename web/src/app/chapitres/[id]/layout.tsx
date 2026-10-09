"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { ChapterStatusBadge, formatPlannedDate } from "@/components/status";
import { Alert, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { ChapterContext } from "./chapter-context";

export default function ChapterLayout({ children }: { children: ReactNode }) {
  const id = Number(useParams<{ id: string }>().id);
  const pathname = usePathname();
  const chapter = useEngineData(() => api.getChapter(id), [id]);
  const projectId = chapter.data?.project_id;
  const series = useEngineData(
    () => (projectId ? api.getProject(projectId) : Promise.resolve(null)),
    [projectId],
  );

  if (chapter.loading && !chapter.data) return <Loading />;
  if (chapter.error || !chapter.data) return <Alert>{chapter.error ?? "Chapitre introuvable"}</Alert>;
  if (series.error) return <Alert>{series.error}</Alert>;
  if (!series.data) return <Loading />;

  const c = chapter.data;
  const tabs = [
    { href: `/chapitres/${id}`, label: "Infos" },
    { href: `/chapitres/${id}/scenario`, label: "Scénario" },
    { href: `/chapitres/${id}/mise-en-page`, label: "Mise en page" },
    { href: `/chapitres/${id}/atelier`, label: "Atelier" },
  ];

  return (
    <ChapterContext.Provider
      value={{ chapter: c, series: series.data, setChapter: chapter.setData, reload: chapter.reload }}
    >
      <PageHeader
        title={`Chapitre ${c.number}${c.title ? ` — ${c.title}` : ""}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <Link href={`/projets/${c.project_id}`} className="hover:text-zinc-200">
              ← {c.series_title}
            </Link>
            <ChapterStatusBadge status={c.status} />
            <span>Publication : {formatPlannedDate(c.planned_date)}</span>
          </span>
        }
      />
      <nav className="mb-6 flex gap-1 border-b border-zinc-800" aria-label="Étapes du chapitre">
        {tabs.map((t) => {
          const active = pathname === t.href;
          return (
            <Link
              key={t.href}
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
