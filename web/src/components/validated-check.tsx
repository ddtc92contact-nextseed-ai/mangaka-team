// Coche verte « validé » posée au centre d'une vignette de case (croquis, atelier).

/**
 * Grande coche centrée (40–48 px) : liseré blanc + ombre pour rester lisible sur les dessins clairs
 * comme sombres. Purement décorative (aria-hidden, sans clic) : le statut est dit par le texte
 * visible et l'aria-label de la vignette. Le parent doit être positionné (relative/absolute).
 */
export function ValidatedCheck({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      data-testid="validated-check"
      className={`pointer-events-none absolute left-1/2 top-1/2 flex size-10 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-emerald-500 text-white shadow-[0_2px_8px_rgba(0,0,0,0.55)] ring-2 ring-white/90 md:size-12 ${className}`}
    >
      <svg viewBox="0 0 24 24" className="size-6 md:size-7" fill="none" stroke="currentColor" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 12.5l4.5 4.5L19 7.5" />
      </svg>
    </span>
  );
}
