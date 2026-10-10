"use client";

import { useEffect, useId, useLayoutEffect, useReducer, useRef, useState } from "react";
import { HELP, type HelpId } from "@/lib/help";
import { TIP_CLOSED, placeTip, tipButtonAria, tipReducer, type TipPlacement } from "@/lib/info-tip";

/**
 * Bulle d'aide « ? » à côté d'un libellé : s'ouvre au survol, au focus clavier et au tap (téléphone) ; Échap ou un
 * clic à l'extérieur la referment. Le texte vient de `lib/help.ts` (clé `help`).
 * La bulle est en `position: fixed`, recalée dans l'écran : jamais coupée par un conteneur ou un bord.
 */
export function InfoTip({ help, label, className = "" }: { help: HelpId; label: string; className?: string }) {
  const [state, dispatch] = useReducer(tipReducer, TIP_CLOSED);
  const [place, setPlace] = useState<TipPlacement | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const bubbleId = `tip-${useId().replace(/:/g, "")}`;

  useLayoutEffect(() => {
    if (!state.open) return;
    const update = () => {
      if (!button.current || !bubble.current) return;
      const a = button.current.getBoundingClientRect();
      const b = bubble.current.getBoundingClientRect();
      setPlace(
        placeTip(
          { top: a.top, left: a.left, width: a.width, height: a.height },
          { width: b.width, height: b.height },
          { width: document.documentElement.clientWidth, height: window.innerHeight },
        ),
      );
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      setPlace(null);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [state.open]);

  useEffect(() => {
    if (!state.open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatch("escape");
    };
    const onDown = (e: PointerEvent) => {
      if (!button.current?.contains(e.target as Node)) dispatch("outside");
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [state.open]);

  return (
    <span className={`inline-flex align-middle ${className}`}>
      <button
        ref={button}
        type="button"
        {...tipButtonAria(bubbleId, state.open, label)}
        data-testid={`help-${help}`}
        onPointerEnter={(e) => e.pointerType === "mouse" && dispatch("hover")}
        onPointerLeave={(e) => e.pointerType === "mouse" && dispatch("leave")}
        onFocus={() => dispatch("focus")}
        onBlur={() => dispatch("blur")}
        onClick={(e) => {
          // Dans un <label> ou un <summary> : ne pas activer le champ ou l'accordéon voisin.
          e.preventDefault();
          e.stopPropagation();
          dispatch("tap");
        }}
        className="inline-flex h-4 w-4 shrink-0 cursor-help items-center justify-center rounded-full border border-zinc-600 text-[10px] font-semibold leading-none text-zinc-400 transition-colors hover:border-rose-400 hover:text-rose-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 aria-expanded:border-rose-400 aria-expanded:text-rose-200"
      >
        ?
      </button>
      <span
        ref={bubble}
        id={bubbleId}
        role="tooltip"
        hidden={!state.open}
        data-testid="help-bubble"
        style={place ? { top: place.top, left: place.left } : { top: 0, left: 0, visibility: "hidden" }}
        className="pointer-events-none fixed z-50 w-max max-w-[min(18rem,calc(100vw-16px))] rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-zinc-200 shadow-xl shadow-black/50"
      >
        {HELP[help]}
      </span>
    </span>
  );
}

/** Libellé suivi de sa bulle d'aide, pour les en-têtes de section et les libellés hors `<Field>`. */
export function HelpLabel({ help, children, className = "" }: { help: HelpId; children: string; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      {children}
      <InfoTip help={help} label={children} />
    </span>
  );
}
