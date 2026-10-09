"use client";

// Aperçu SVG d'une page mise en page : cases (polygones), zones de bulles, gouttières et découpes
// déplaçables / inclinables (écran Mise en page), ou miniature (`compact`).
import { useState, type KeyboardEvent, type PointerEvent } from "react";
import type { LayoutGutter, PageLayout } from "@/lib/api";
import { centroid, panelPolygon, svgPoints, type Point } from "@/lib/layout";

const KEY_STEP = 24; // ≈ 2 mm à 300 DPI

type Drag =
  | { kind: "gutter"; layout: PageLayout; gutter: LayoutGutter; position: number }
  | { kind: "end"; layout: PageLayout; gutter: LayoutGutter; end: 0 | 1; ends: [number, number]; from: number };

/** Ligne médiane d'une découpe, avec repli pour une mise en page d'avant les biais. */
function cutLine(g: LayoutGutter): [Point, Point] {
  if (g.line) return g.line;
  const vertical = g.orientation === "vertical";
  return vertical
    ? [
        [g.position, g.y1],
        [g.position, g.y2],
      ]
    : [
        [g.x1, g.position],
        [g.x2, g.position],
      ];
}

/** Ligne de la découpe dont les extrémités sont aux positions `ends` (le long de l'axe découpé). */
function lineWithEnds(g: LayoutGutter, ends: [number, number]): [Point, Point] {
  const [a, b] = cutLine(g);
  return g.orientation === "vertical"
    ? [
        [ends[0], a[1]],
        [ends[1], b[1]],
      ]
    : [
        [a[0], ends[0]],
        [b[0], ends[1]],
      ];
}

/** Bande de `half` de part et d'autre de la ligne (zone de saisie d'une gouttière en biais). */
function band([a, b]: [Point, Point], half: number): Point[] {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const nx = (-dy / len) * half;
  const ny = (dx / len) * half;
  return [
    [a[0] + nx, a[1] + ny],
    [b[0] + nx, b[1] + ny],
    [b[0] - nx, b[1] - ny],
    [a[0] - nx, a[1] - ny],
  ];
}

export function PageSvg({
  layout,
  compact = false,
  labels = [],
  highlight = null,
  onMoveGutter,
  onSlantCut,
}: {
  layout: PageLayout;
  compact?: boolean;
  labels?: string[];
  /** Case mise en évidence (id de la case). */
  highlight?: number | null;
  onMoveGutter?: (g: LayoutGutter, position: number) => void;
  onSlantCut?: (g: LayoutGutter, ends: [number, number]) => void;
}) {
  // Le glissé en cours appartient à une mise en page : il disparaît dès qu'une nouvelle arrive.
  const [dragState, setDrag] = useState<Drag | null>(null);
  const drag = dragState && dragState.layout === layout ? dragState : null;
  const { width: W, height: H } = layout.page;
  const live = layout.live_area;
  const stroke = Math.max(4, Math.round(W / 300));
  const handleR = stroke * 5;

  function toPage(e: PointerEvent<SVGElement>): { x: number; y: number } | null {
    // Repère de la page : celui du <svg> qui contient l'élément saisi.
    const target = e.currentTarget;
    const svg = target instanceof SVGSVGElement ? target : target.ownerSVGElement;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return { x: pt.x, y: pt.y };
  }

  const clamp = (g: LayoutGutter, v: number) => Math.min(g.max, Math.max(g.min, v));
  const clampEnd = (g: LayoutGutter, j: 0 | 1, v: number) =>
    g.ends_min && g.ends_max ? Math.min(g.ends_max[j], Math.max(g.ends_min[j], v)) : v;

  function onGutterDown(e: PointerEvent<SVGElement>, g: LayoutGutter) {
    if (!onMoveGutter) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ kind: "gutter", layout, gutter: g, position: g.position });
  }
  function onEndDown(e: PointerEvent<SVGElement>, g: LayoutGutter, end: 0 | 1) {
    if (!onSlantCut || !g.ends) return;
    e.stopPropagation();
    const p = toPage(e);
    if (!p) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    // Glissé relatif : la poignée est sur la partie visible, l'extrémité au bord de la zone découpée.
    const from = g.orientation === "vertical" ? p.x : p.y;
    setDrag({ kind: "end", layout, gutter: g, end, ends: [...g.ends], from });
  }
  function onPointerMove(e: PointerEvent<SVGElement>) {
    if (!drag) return;
    const p = toPage(e);
    if (!p) return;
    const v = drag.gutter.orientation === "vertical" ? p.x : p.y;
    if (drag.kind === "gutter") setDrag({ ...drag, position: clamp(drag.gutter, v) });
    else {
      const ends: [number, number] = [...drag.ends];
      ends[drag.end] = clampEnd(drag.gutter, drag.end, drag.gutter.ends![drag.end] + v - drag.from);
      setDrag({ ...drag, ends });
    }
  }
  function onPointerUp() {
    if (!drag) return;
    if (drag.kind === "gutter") {
      if (onMoveGutter && Math.abs(drag.position - drag.gutter.position) >= 1) onMoveGutter(drag.gutter, drag.position);
      else setDrag(null);
      return;
    }
    const before = drag.gutter.ends!;
    if (onSlantCut && Math.abs(drag.ends[drag.end] - before[drag.end]) >= 1) onSlantCut(drag.gutter, drag.ends);
    else setDrag(null);
  }
  function arrow(e: KeyboardEvent, g: LayoutGutter): number {
    const dir =
      g.orientation === "vertical"
        ? { ArrowLeft: -1, ArrowRight: 1 }[e.key as "ArrowLeft"]
        : { ArrowUp: -1, ArrowDown: 1 }[e.key as "ArrowUp"];
    if (dir) e.preventDefault();
    return dir ?? 0;
  }
  function onGutterKey(e: KeyboardEvent<SVGElement>, g: LayoutGutter) {
    if (!onMoveGutter) return;
    const dir = arrow(e, g);
    if (dir) onMoveGutter(g, clamp(g, g.position + dir * KEY_STEP));
  }
  function onEndKey(e: KeyboardEvent<SVGElement>, g: LayoutGutter, end: 0 | 1) {
    if (!onSlantCut || !g.ends) return;
    const dir = arrow(e, g);
    if (!dir) return;
    const ends: [number, number] = [...g.ends];
    ends[end] = clampEnd(g, end, ends[end] + dir * KEY_STEP);
    onSlantCut(g, ends);
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={compact ? "block w-full" : "mx-auto block max-h-[72vh] w-full touch-none"}
      style={{ aspectRatio: `${W} / ${H}` }}
      role="img"
      aria-label={`Aperçu de la page ${layout.page_number}, gabarit ${layout.template_id}`}
      data-testid={compact ? undefined : "layout-svg"}
    >
      <rect x={0} y={0} width={W} height={H} fill="#f4f4f5" />
      {!compact && (
        <rect
          x={live.x1}
          y={live.y1}
          width={live.x2 - live.x1}
          height={live.y2 - live.y1}
          fill="none"
          stroke="#a1a1aa"
          strokeWidth={stroke / 2}
          strokeDasharray={`${stroke * 4} ${stroke * 3}`}
        />
      )}
      {layout.panels.map((p) => {
        const poly = panelPolygon(p);
        const [cx, cy] = centroid(poly);
        const r = Math.min(110, Math.min(p.width, p.height) / 5);
        return (
          <g key={p.index} data-testid={compact ? undefined : "layout-panel"} data-slanted={p.slanted ? "true" : undefined}>
            <polygon
              points={svgPoints(poly)}
              fill={highlight !== null && p.panel_id === highlight ? "#ffe4e6" : "#ffffff"}
              stroke={highlight !== null && p.panel_id === highlight ? "#e11d48" : "#18181b"}
              strokeWidth={highlight !== null && p.panel_id === highlight ? stroke * 2 : stroke}
              strokeLinejoin="miter"
            />
            {p.bubble_zone && (
              <rect
                x={p.bubble_zone.x1}
                y={p.bubble_zone.y1}
                width={p.bubble_zone.x2 - p.bubble_zone.x1}
                height={p.bubble_zone.y2 - p.bubble_zone.y1}
                fill="#fb7185"
                fillOpacity={0.28}
                stroke="#e11d48"
                strokeWidth={stroke / 2}
                strokeDasharray={compact ? undefined : `${stroke * 3} ${stroke * 2}`}
                data-testid={compact ? undefined : "bubble-zone"}
              />
            )}
            {!compact && (
              <>
                <circle cx={cx} cy={cy} r={r} fill="#18181b" />
                <text
                  x={cx}
                  y={cy}
                  fill="#fafafa"
                  fontSize={r * 1.1}
                  fontWeight={700}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontFamily="system-ui, sans-serif"
                >
                  {p.reading_order}
                </text>
                {labels[p.index] && p.height > 300 && (
                  <text
                    x={cx}
                    y={cy + r + Math.min(64, p.width / 12) * 1.4}
                    fill="#52525b"
                    fontSize={Math.min(64, p.width / 12)}
                    textAnchor="middle"
                    fontFamily="system-ui, sans-serif"
                  >
                    {labels[p.index]}
                  </text>
                )}
              </>
            )}
          </g>
        );
      })}
      {!compact &&
        layout.gutters.map((g) => {
          const vertical = g.orientation === "vertical";
          const gutterDrag = drag?.kind === "gutter" && drag.gutter === g ? drag : null;
          const endDrag = drag?.kind === "end" && drag.gutter === g ? drag : null;
          const line = cutLine(g);
          const shift = gutterDrag ? gutterDrag.position - g.position : 0;
          const shown: [Point, Point] = endDrag
            ? lineWithEnds(g, endDrag.ends)
            : vertical
              ? [
                  [line[0][0] + shift, line[0][1]],
                  [line[1][0] + shift, line[1][1]],
                ]
              : [
                  [line[0][0], line[0][1] + shift],
                  [line[1][0], line[1][1] + shift],
                ];
          const width = vertical ? layout.gutters_px.vertical : layout.gutters_px.horizontal;
          // Poignées sur la partie visible de la découpe, décalées comme son extrémité pendant un glissé.
          const handles: [Point, Point] = g.handles ?? line;
          const deltas = [0, 1].map((j) => (endDrag && g.ends ? endDrag.ends[j] - g.ends[j] : shift));
          const handlePts = handles.map(([x, y], j): Point => (vertical ? [x + deltas[j], y] : [x, y + deltas[j]]));
          const label = `Gouttière ${vertical ? "verticale" : "horizontale"}`;
          return (
            <g key={`${g.path.join("-")}:${g.index}`} data-testid="cut">
              {(gutterDrag || endDrag) && (
                <line
                  x1={shown[0][0]}
                  y1={shown[0][1]}
                  x2={shown[1][0]}
                  y2={shown[1][1]}
                  stroke="#e11d48"
                  strokeWidth={stroke * 1.5}
                />
              )}
              <polygon
                points={svgPoints(band(line, width / 2 + 36))}
                fill="#e11d48"
                fillOpacity={gutterDrag ? 0.18 : 0}
                className={onMoveGutter ? "outline-none hover:[fill-opacity:0.15] focus:[fill-opacity:0.3]" : undefined}
                style={{ cursor: onMoveGutter ? (vertical ? "col-resize" : "row-resize") : "default" }}
                tabIndex={onMoveGutter ? 0 : -1}
                role="slider"
                aria-orientation={vertical ? "horizontal" : "vertical"}
                aria-label={label}
                aria-valuemin={Math.round(g.min)}
                aria-valuemax={Math.round(g.max)}
                aria-valuenow={Math.round(gutterDrag ? gutterDrag.position : g.position)}
                data-testid="gutter"
                onPointerDown={(e) => onGutterDown(e, g)}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onKeyDown={(e) => onGutterKey(e, g)}
              />
              {onSlantCut &&
                g.ends &&
                ([0, 1] as const).map((j) => (
                  <circle
                    key={j}
                    cx={handlePts[j][0]}
                    cy={handlePts[j][1]}
                    r={handleR}
                    fill={endDrag?.end === j ? "#e11d48" : "#ffffff"}
                    stroke="#e11d48"
                    strokeWidth={stroke}
                    className="outline-none focus:[stroke-width:12px]"
                    style={{ cursor: vertical ? "ew-resize" : "ns-resize" }}
                    tabIndex={0}
                    role="slider"
                    aria-orientation={vertical ? "horizontal" : "vertical"}
                    aria-label={`${label} : ${j === 0 ? (vertical ? "extrémité haute" : "extrémité de début") : vertical ? "extrémité basse" : "extrémité de fin"} (inclinaison${g.angle_deg ? ` ${g.angle_deg.toFixed(1)}°` : ""})`}
                    aria-valuemin={Math.round(g.ends_min?.[j] ?? 0)}
                    aria-valuemax={Math.round(g.ends_max?.[j] ?? 0)}
                    aria-valuenow={Math.round((endDrag ? endDrag.ends : g.ends!)[j])}
                    data-testid="cut-end"
                    onPointerDown={(e) => onEndDown(e, g, j)}
                    onPointerMove={onPointerMove}
                    onPointerUp={onPointerUp}
                    onKeyDown={(e) => onEndKey(e, g, j)}
                  />
                ))}
            </g>
          );
        })}
    </svg>
  );
}
