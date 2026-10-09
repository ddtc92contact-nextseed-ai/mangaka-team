"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * Fenêtre modale sur `<dialog>` natif : piège le focus, Échap ferme, clic sur le fond aussi.
 * Le focus revient tout seul à l'élément qui l'a ouverte.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "xl";
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      aria-labelledby="modal-title"
      className={`m-auto max-h-[92vh] w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900 p-0 text-zinc-100 shadow-2xl backdrop:bg-black/70 ${
        size === "xl" ? "max-w-6xl" : "max-w-lg"
      }`}
    >
      {open && (
        <div className="flex max-h-[92vh] flex-col">
          <header className="flex items-center justify-between gap-4 border-b border-zinc-800 px-5 py-3">
            <h2 id="modal-title" className="font-semibold text-zinc-50">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Fermer"
              className="rounded-md px-2 py-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-2 focus-visible:outline-rose-400"
            >
              ✕
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <footer className="flex flex-wrap justify-end gap-2 border-t border-zinc-800 px-5 py-3">{footer}</footer>
          )}
        </div>
      )}
    </dialog>
  );
}

/** Vrai si une modale est ouverte (les raccourcis globaux s'effacent alors devant elle). */
export const modalOpen = () => typeof document !== "undefined" && document.querySelector("dialog[open]") !== null;
