"use client";

import { useImperativeHandle, useRef, useState, type KeyboardEvent, type PointerEvent, type Ref } from "react";
import { engineUrl, type BubbleBox, type LetteredBubble, type PageLettering } from "@/lib/api";
import { BUBBLE_KINDS } from "@/lib/script";

/** Modification d'une bulle faite à la souris ou au clavier sur la planche. */
export interface CanvasEdit {
  id: number;
  position?: BubbleBox;
  tail?: { x: number; y: number };
}

type Mode = "move" | "resize" | "tail";

interface Drag {
  data: PageLettering;
  id: number;
  mode: Mode;
  x: number;
  y: number;
  dx: number;
  dy: number;
}

const MIN_W = 60;
const MIN_H = 40;
const STEP = 12; // ≈ 1 mm à 300 DPI
const COMMIT_MS = 450;

export interface LetteringCanvasHandle {
  focusBubble: (id: number) => void;
}

/** Édition résultante d'un déplacement (dx, dy) en mode `mode`. */
export function applyDelta(b: LetteredBubble, mode: Mode, dx: number, dy: number): CanvasEdit {
  if (mode === "tail") {
    const tail = b.tail ?? { x: b.box.x + b.box.w / 2, y: b.box.y + b.box.h };
    return { id: b.id, tail: { x: Math.round(tail.x + dx), y: Math.round(tail.y + dy) } };
  }
  if (mode === "resize") {
    return {
      id: b.id,
      position: { ...b.box, w: Math.max(MIN_W, Math.round(b.box.w + dx)), h: Math.max(MIN_H, Math.round(b.box.h + dy)) },
    };
  }
  return { id: b.id, position: { ...b.box, x: Math.round(b.box.x + dx), y: Math.round(b.box.y + dy) } };
}

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

export function LetteringCanvas({
  data,
  selectedId,
  showGuides,
  disabled,
  onSelect,
  onCommit,
  ref,
}: {
  data: PageLettering;
  selectedId: number | null;
  showGuides: boolean;
  disabled: boolean;
  onSelect: (id: number | null) => void;
  onCommit: (edit: CanvasEdit) => void;
  ref?: Ref<LetteringCanvasHandle>;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const groups = useRef(new Map<number, SVGGElement>());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Glissé (souris) ou déplacement au clavier en cours : il appartient à un lettrage et disparaît
  // dès que le moteur renvoie le suivant.
  const [dragState, setDrag] = useState<Drag | null>(null);
  const drag = dragState && dragState.data === data ? dragState : null;
  useImperativeHandle(ref, () => ({ focusBubble: (id) => groups.current.get(id)?.focus() }), []);

  const { width: W, height: H } = data;
  const border = (1.5 / 72) * data.dpi;
  const guide = Math.max(3, W / 600);
  const warnedPanels = new Set(data.warnings.map((w) => w.panel_id).filter((id): id is number => id !== null));
  const families = new Map(Object.values(data.styles).map((s) => [s.family, s.url]));
  const fontCss = [...families]
    .map(([family, url]) => `@font-face{font-family:"${family}";src:url("${engineUrl(url)}") format("truetype");}`)
    .join("");

  function toPage(e: PointerEvent): { x: number; y: number } | null {
    const ctm = svgRef.current?.getScreenCTM();
    if (!ctm) return null;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return { x: pt.x, y: pt.y };
  }

  function onPointerDown(e: PointerEvent<SVGElement>, b: LetteredBubble, mode: Mode) {
    if (disabled || e.button !== 0) return;
    e.stopPropagation();
    const p = toPage(e);
    if (!p) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    onSelect(b.id);
    setDrag({ data, id: b.id, mode, x: p.x, y: p.y, dx: 0, dy: 0 });
  }
  function onPointerMove(e: PointerEvent<SVGElement>) {
    if (!drag) return;
    const p = toPage(e);
    if (p) setDrag({ ...drag, dx: p.x - drag.x, dy: p.y - drag.y });
  }
  function onPointerUp() {
    if (!drag) return;
    const b = data.bubbles.find((x) => x.id === drag.id);
    if (b && Math.hypot(drag.dx, drag.dy) >= 3) onCommit(applyDelta(b, drag.mode, drag.dx, drag.dy));
    else setDrag(null);
  }

  function onKeyDown(e: KeyboardEvent<SVGGElement>, b: LetteredBubble) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(b.id);
      return;
    }
    const arrow = ARROWS[e.key];
    if (!arrow || disabled) return;
    e.preventDefault();
    // Flèches : déplacer · Alt + flèches : redimensionner · Maj : pas × 5. Envoi groupé après une pause.
    const mode: Mode = e.altKey ? "resize" : "move";
    const step = STEP * (e.shiftKey ? 5 : 1);
    const base = drag && drag.id === b.id && drag.mode === mode ? drag : { data, id: b.id, mode, x: 0, y: 0, dx: 0, dy: 0 };
    const next = { ...base, dx: base.dx + arrow[0] * step, dy: base.dy + arrow[1] * step };
    setDrag(next);
    onSelect(b.id);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => onCommit(applyDelta(b, next.mode, next.dx, next.dy)), COMMIT_MS);
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} ${H}`}
      className="mx-auto block max-h-[80vh] w-full touch-none select-none"
      style={{ aspectRatio: `${W} / ${H}` }}
      data-testid="lettering-svg"
      role="group"
      aria-label={`Planche assemblée, page ${data.page_number} : ${data.bubbles.length} bulle${data.bubbles.length > 1 ? "s" : ""}. Tab pour passer d'une bulle à l'autre, flèches pour la déplacer, Alt + flèches pour la redimensionner.`}
      onPointerDown={() => onSelect(null)}
    >
      <defs>
        <style>{fontCss}</style>
        {data.panels.map((p) => (
          <clipPath key={p.id} id={`clip-case-${p.id}`}>
            <rect x={p.box.x1} y={p.box.y1} width={p.box.x2 - p.box.x1} height={p.box.y2 - p.box.y1} />
          </clipPath>
        ))}
      </defs>
      <rect width={W} height={H} fill="#ffffff" />
      {data.panels.map((p) => {
        const w = p.box.x2 - p.box.x1;
        const h = p.box.y2 - p.box.y1;
        return (
          <g key={p.id} data-testid="lettering-panel" data-missing={p.image_url ? undefined : "true"}>
            {p.image_url ? (
              <image
                href={engineUrl(p.image_url)}
                x={p.box.x1}
                y={p.box.y1}
                width={w}
                height={h}
                preserveAspectRatio="xMidYMid slice"
                clipPath={`url(#clip-case-${p.id})`}
              />
            ) : (
              <>
                <rect x={p.box.x1} y={p.box.y1} width={w} height={h} fill="#9e9e9e" />
                <text
                  x={p.box.x1 + w / 2}
                  y={p.box.y1 + h / 2}
                  fill="#3f3f46"
                  fontSize={Math.min(58, w / 9)}
                  fontWeight={700}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontFamily="system-ui, sans-serif"
                >
                  CASE MANQUANTE
                </text>
              </>
            )}
            <rect
              x={p.box.x1 + border / 2}
              y={p.box.y1 + border / 2}
              width={w - border}
              height={h - border}
              fill="none"
              stroke={warnedPanels.has(p.id) ? "#f59e0b" : "#000000"}
              strokeWidth={warnedPanels.has(p.id) ? border * 2.5 : border}
            />
            {showGuides && p.bubble_zone && (
              <rect
                x={p.bubble_zone.x1}
                y={p.bubble_zone.y1}
                width={p.bubble_zone.x2 - p.bubble_zone.x1}
                height={p.bubble_zone.y2 - p.bubble_zone.y1}
                fill="#fb7185"
                fillOpacity={0.12}
                stroke="#e11d48"
                strokeWidth={guide}
                strokeDasharray={`${guide * 4} ${guide * 3}`}
                pointerEvents="none"
              />
            )}
            {showGuides &&
              p.faces.map((f, i) => (
                <rect
                  key={i}
                  x={f.x1}
                  y={f.y1}
                  width={f.x2 - f.x1}
                  height={f.y2 - f.y1}
                  fill="none"
                  stroke="#f59e0b"
                  strokeWidth={guide}
                  strokeDasharray={`${guide * 2} ${guide * 2}`}
                  pointerEvents="none"
                  data-testid="face-box"
                />
              ))}
          </g>
        );
      })}

      {data.bubbles.map((b, i) => {
        const active = drag?.id === b.id ? drag : null;
        const selected = b.id === selectedId;
        const move = active?.mode === "move" ? `translate(${active.dx} ${active.dy})` : undefined;
        const kind = BUBBLE_KINDS[b.kind];
        return (
          <g
            key={b.id}
            ref={(el) => {
              if (el) groups.current.set(b.id, el);
              else groups.current.delete(b.id);
            }}
            transform={move}
            tabIndex={0}
            role="button"
            aria-pressed={selected}
            aria-label={`Bulle ${i + 1}, ${kind.toLowerCase()}${b.speaker ? ` de ${b.speaker}` : ""} : ${b.text}${b.overflow ? " — texte trop long" : ""}`}
            data-testid="lettering-bubble"
            data-kind={b.kind}
            data-overflow={b.overflow ? "true" : undefined}
            className="cursor-move outline-none [&:focus-visible>.focus-ring]:opacity-100"
            onPointerDown={(e) => onPointerDown(e, b, "move")}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onKeyDown={(e) => onKeyDown(e, b)}
          >
            <path d={b.shape.path} fill="none" stroke={b.shape.stroke} strokeWidth={2 * b.shape.stroke_px} strokeLinejoin="round" />
            <path d={b.shape.path} fill={b.shape.fill} />
            <text
              fontFamily={`"${b.font.family}", sans-serif`}
              fontSize={b.font.size_px}
              fill={b.font.color}
              textAnchor="middle"
              xmlSpace="preserve"
            >
              {b.lines.map((l, j) => (
                <tspan key={j} x={l.x} y={l.y}>
                  {l.text}
                </tspan>
              ))}
            </text>
            <rect
              className="focus-ring opacity-0"
              x={b.box.x - 10}
              y={b.box.y - 10}
              width={b.box.w + 20}
              height={b.box.h + 20}
              fill="none"
              stroke="#38bdf8"
              strokeWidth={guide * 1.5}
              pointerEvents="none"
            />
            {(selected || b.overflow) && (
              <rect
                x={b.box.x - 6}
                y={b.box.y - 6}
                width={b.box.w + 12}
                height={b.box.h + 12}
                fill="none"
                stroke={b.overflow ? "#ef4444" : "#e11d48"}
                strokeWidth={guide}
                strokeDasharray={`${guide * 3} ${guide * 2}`}
                pointerEvents="none"
              />
            )}
          </g>
        );
      })}

      {/* Poignées de la bulle choisie : taille (coin) et pointe de la queue. */}
      {data.bubbles
        .filter((b) => b.id === selectedId && !disabled)
        .map((b) => {
          const active = drag?.id === b.id ? drag : null;
          const preview = active ? applyDelta(b, active.mode, active.dx, active.dy) : null;
          const box = preview?.position ?? b.box;
          const tail = preview?.tail ?? b.tail;
          const handle = Math.max(26, W / 90);
          return (
            <g key={`handles-${b.id}`}>
              {active?.mode === "resize" && (
                <rect x={box.x} y={box.y} width={box.w} height={box.h} fill="#e11d48" fillOpacity={0.08} stroke="#e11d48" strokeWidth={guide} strokeDasharray={`${guide * 3} ${guide * 2}`} />
              )}
              {active?.mode === "tail" && tail && (
                <line x1={b.box.x + b.box.w / 2} y1={b.box.y + b.box.h / 2} x2={tail.x} y2={tail.y} stroke="#e11d48" strokeWidth={guide} strokeDasharray={`${guide * 3} ${guide * 2}`} />
              )}
              <rect
                x={box.x + box.w - handle / 2 + (active?.mode === "move" ? active.dx : 0)}
                y={box.y + box.h - handle / 2 + (active?.mode === "move" ? active.dy : 0)}
                width={handle}
                height={handle}
                rx={4}
                fill="#e11d48"
                stroke="#ffffff"
                strokeWidth={guide}
                className="cursor-nwse-resize"
                data-testid="resize-handle"
                aria-hidden="true"
                onPointerDown={(e) => onPointerDown(e, b, "resize")}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
              />
              {tail && b.kind !== "narration" && (
                <circle
                  cx={tail.x + (active?.mode === "move" ? active.dx : 0)}
                  cy={tail.y + (active?.mode === "move" ? active.dy : 0)}
                  r={handle / 1.6}
                  fill="#38bdf8"
                  stroke="#ffffff"
                  strokeWidth={guide}
                  className="cursor-crosshair"
                  data-testid="tail-handle"
                  aria-hidden="true"
                  onPointerDown={(e) => onPointerDown(e, b, "tail")}
                  onPointerMove={onPointerMove}
                  onPointerUp={onPointerUp}
                />
              )}
            </g>
          );
        })}
    </svg>
  );
}
