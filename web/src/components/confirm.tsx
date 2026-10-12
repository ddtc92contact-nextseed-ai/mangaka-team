"use client";

import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Modal } from "./modal";
import { Button } from "./ui";

export interface ConfirmOptions {
  title: string;
  message: ReactNode;
  /** Libellé du bouton de confirmation (« Supprimer », « Remplacer »…). */
  confirmLabel?: string;
  cancelLabel?: string;
  /** Action définitive (suppression) : bouton de confirmation rouge. */
  danger?: boolean;
}

/**
 * Fenêtre de confirmation aux couleurs de l'appli (à la place de la popup native du navigateur) : sur la `Modal`, donc focus piégé,
 * Échap = annuler et focus rendu au déclencheur ; Entrée = confirmer (le bouton de confirmation prend le focus).
 */
export function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  message,
  confirmLabel = "Confirmer",
  cancelLabel = "Annuler",
  danger = false,
}: ConfirmOptions & { open: boolean; onConfirm: () => void; onCancel: () => void }) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const messageId = useId();

  // Les effets de la Modal (enfant) passent avant : la fenêtre est déjà ouverte ici.
  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      describedBy={messageId}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} data-testid="confirm-cancel">
            {cancelLabel}
          </Button>
          <Button ref={confirmRef} variant={danger ? "destructive" : "primary"} onClick={onConfirm} data-testid="confirm-ok">
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div id={messageId} className="text-sm whitespace-pre-line text-zinc-300" data-testid="confirm-message">
        {message}
      </div>
    </Modal>
  );
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm>(() => Promise.resolve(false));

/**
 * Demande une confirmation et attend la réponse :
 * `if (!(await confirm({ title: "Supprimer le chapitre ?", message: "…", confirmLabel: "Supprimer", danger: true }))) return;`
 */
export const useConfirm = () => useContext(ConfirmContext);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);

  const settle = useCallback((ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setOptions(null);
  }, []);

  const confirm = useCallback<Confirm>((next) => {
    resolver.current?.(false); // une seule question à la fois : la précédente vaut « Annuler »
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <ConfirmDialog
        open={options !== null}
        title={options?.title ?? ""}
        message={options?.message ?? null}
        confirmLabel={options?.confirmLabel}
        cancelLabel={options?.cancelLabel}
        danger={options?.danger}
        onConfirm={() => settle(true)}
        onCancel={() => settle(false)}
      />
    </ConfirmContext.Provider>
  );
}
