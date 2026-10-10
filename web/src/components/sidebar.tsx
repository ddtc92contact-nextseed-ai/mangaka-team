"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ComfyBadge, EngineBadge } from "./engine-status";

const NAV = [
  { href: "/", label: "Tableau de bord", match: (p: string) => p === "/" },
  {
    href: "/projets",
    label: "Séries",
    match: (p: string) =>
      (p.startsWith("/projets") && !p.includes("/personnages") && !p.includes("/bibliotheque")) ||
      p.startsWith("/chapitres"),
  },
  {
    href: "/bibliotheque",
    label: "Bibliothèque",
    match: (p: string) =>
      p.startsWith("/bibliotheque") || p.startsWith("/personnages") || p.includes("/personnages") || p.includes("/bibliotheque"),
  },
  { href: "/equipe", label: "L'équipe", match: (p: string) => p.startsWith("/equipe") },
  { href: "/savoir-faire", label: "Savoir-faire", match: (p: string) => p.startsWith("/savoir-faire") },
  { href: "/banc-essai-qc", label: "Banc d'essai QC", match: (p: string) => p.startsWith("/banc-essai-qc") },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-zinc-800 bg-zinc-950 md:sticky md:top-0 md:h-screen md:w-60 md:border-r md:border-b-0">
      <div className="px-5 py-5">
        <Link href="/" className="block">
          <span className="text-lg font-bold tracking-tight text-zinc-50">
            mangaka<span className="text-rose-400">·</span>team
          </span>
          <span className="block text-xs text-zinc-500">Studio local de planches</span>
        </Link>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible">
        {NAV.map((item) => {
          const active = item.match(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors ${
                active ? "bg-zinc-800 text-zinc-50" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto hidden flex-col gap-2 border-t border-zinc-800 px-5 py-4 md:flex">
        <EngineBadge />
        <ComfyBadge />
      </div>
    </aside>
  );
}
