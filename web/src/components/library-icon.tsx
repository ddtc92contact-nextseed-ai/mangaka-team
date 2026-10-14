import type { ReactNode } from "react";
import type { LibraryKind } from "@/lib/api";

// Icône de chaque sorte de fiche de la bibliothèque (onglets, cartes, pastilles) : trait simple, couleur héritée.
const PATHS: Record<LibraryKind, ReactNode> = {
  // Silhouette : tête et épaules.
  character: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7" />
    </>
  ),
  // Cube.
  object: (
    <>
      <path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Z" />
      <path d="M4 7.5 12 12l8-4.5M12 12v9" />
    </>
  ),
  // Maison au pied d'une montagne.
  decor: (
    <>
      <path d="M3 20h18" />
      <path d="m3 20 6-10 4 6" />
      <path d="M13 20v-5l4-3 4 3v5" />
    </>
  ),
  // Fusée.
  vehicle: (
    <>
      <path d="M12 2c3 2.5 4.5 6 4.5 10.5L14 16h-4l-2.5-3.5C7.5 8 9 4.5 12 2Z" />
      <circle cx="12" cy="9" r="1.6" />
      <path d="M7.5 12.5 5 15l1 4 4-3M16.5 12.5 19 15l-1 4-4-3M10.5 19.5 12 22l1.5-2.5" />
    </>
  ),
  // Empreinte de patte.
  creature: (
    <>
      <path d="M12 12.5c-2.8 0-5 2.6-5 4.8 0 1.6 1.2 2.7 2.7 2.7.9 0 1.5-.4 2.3-.4s1.4.4 2.3.4c1.5 0 2.7-1.1 2.7-2.7 0-2.2-2.2-4.8-5-4.8Z" />
      <ellipse cx="6" cy="9.5" rx="1.6" ry="2" />
      <ellipse cx="9.5" cy="5.8" rx="1.6" ry="2.1" />
      <ellipse cx="14.5" cy="5.8" rx="1.6" ry="2.1" />
      <ellipse cx="18" cy="9.5" rx="1.6" ry="2" />
    </>
  ),
};

export function LibraryIcon({ kind, className = "h-4 w-4" }: { kind: LibraryKind; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`shrink-0 ${className}`}
      data-icon={kind}
    >
      {PATHS[kind]}
    </svg>
  );
}
