"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type Tone = "success" | "info" | "error";

interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

const DURATION_MS = 3500;

const ToastContext = createContext<(message: string, tone?: Tone) => void>(() => {});

/**
 * Confirmation courte après une action (« Série enregistrée », « Génération lancée (3 en file) ») :
 * `const toast = useToast(); toast("Série enregistrée");`.
 */
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);

  const show = useCallback(
    (message: string, tone: Tone = "success") => {
      const id = ++seq.current;
      setToasts((ts) => [...ts.slice(-2), { id, message, tone }]);
      const timer = setTimeout(() => {
        timers.current.delete(timer);
        dismiss(id);
      }, DURATION_MS);
      timers.current.add(timer);
    },
    [dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-center gap-2 sm:inset-x-auto sm:right-6 sm:items-end"
        data-testid="toasts"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex max-w-sm items-center gap-3 rounded-lg border px-4 py-2.5 text-sm shadow-xl shadow-black/40 ${TONES[t.tone]}`}
            data-testid="toast"
          >
            <span>{t.message}</span>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Fermer la notification"
              className="rounded px-1 text-current opacity-60 hover:opacity-100 focus-visible:outline-2 focus-visible:outline-rose-400"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const TONES: Record<Tone, string> = {
  success: "border-emerald-700/60 bg-emerald-950/95 text-emerald-100",
  info: "border-zinc-700 bg-zinc-900/95 text-zinc-100",
  error: "border-red-800/60 bg-red-950/95 text-red-100",
};
