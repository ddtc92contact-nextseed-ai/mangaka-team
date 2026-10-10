// Logique de la bulle d'aide (« ? »), sans React : testée par `npm test`.

/** `open` : bulle visible ; `pinned` : ouverte d'un tap / clic, elle reste ouverte quand la souris s'en va. */
export interface TipState {
  open: boolean;
  pinned: boolean;
}

export type TipEvent = "hover" | "leave" | "focus" | "blur" | "tap" | "escape" | "outside";

export const TIP_CLOSED: TipState = { open: false, pinned: false };

export function tipReducer(state: TipState, event: TipEvent): TipState {
  switch (event) {
    case "hover":
    case "focus":
      return state.open ? state : { open: true, pinned: false };
    case "leave":
      return state.pinned ? state : TIP_CLOSED;
    case "tap":
      // Un tap ouvre et épingle ; un second tap referme (au doigt, pas de survol pour refermer).
      return state.open && state.pinned ? TIP_CLOSED : { open: true, pinned: true };
    case "blur":
    case "escape":
    case "outside":
      return TIP_CLOSED;
  }
}

/** Attributs ARIA du bouton « ? » : la bulle le décrit (elle reste dans le DOM, masquée, quand elle est fermée). */
export function tipButtonAria(bubbleId: string, open: boolean, label: string) {
  return {
    "aria-label": `Aide : ${label}`,
    "aria-describedby": bubbleId,
    "aria-expanded": open,
  };
}

export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface TipPlacement {
  top: number;
  left: number;
  side: "below" | "above";
}

/** Marge minimale entre la bulle et les bords de l'écran (px). */
export const TIP_MARGIN = 8;
const GAP = 6;

/**
 * Position (en `position: fixed`) d'une bulle de `size` sous le bouton `anchor`, ou au-dessus s'il n'y a pas la
 * place en bas ; recentrée horizontalement sur le bouton puis ramenée à l'intérieur de l'écran.
 */
export function placeTip(
  anchor: Rect,
  size: { width: number; height: number },
  viewport: { width: number; height: number },
): TipPlacement {
  const below = anchor.top + anchor.height + GAP;
  const above = anchor.top - GAP - size.height;
  const fitsBelow = below + size.height <= viewport.height - TIP_MARGIN;
  const side = fitsBelow || above < TIP_MARGIN ? "below" : "above";
  const centered = anchor.left + anchor.width / 2 - size.width / 2;
  const maxLeft = viewport.width - TIP_MARGIN - size.width;
  const left = Math.max(TIP_MARGIN, Math.min(centered, maxLeft));
  const top = side === "below" ? Math.min(below, Math.max(TIP_MARGIN, viewport.height - TIP_MARGIN - size.height)) : above;
  return { top, left, side };
}
