"use client";

import { useState, type KeyboardEvent, type PointerEvent } from "react";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, Select } from "@/components/ui";
import { api, errorMessage, type LayoutGutter, type PageData, type PageLayout } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { INTENSITIES, RYTHMES, centroid, panelPolygon, svgPoints, type Point } from "@/lib/layout";
import { PAGE_KINDS } from "@/lib/script";
import { useChapter } from "../chapter-context";

export default function LayoutPreviewPage() {
  const { chapter } = useChapter();
  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id]);
  const templates = useEngineData(() => api.layoutTemplates());
  const styles = useEngineData(() => api.layoutStyles());
  const project = useEngineData(() => api.getProject(chapter.project_id), [chapter.project_id]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = pages.data ?? [];
  const selected = list.find((p) => p.id === selectedId) ?? list.find((p) => p.layout) ?? list[0] ?? null;

  function replacePage(page: PageData) {
    pages.setData((list ?? []).map((p) => (p.id === page.id ? page : p)));
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const relayout = (body: { template_id?: string | null; style?: string | null; reroll?: boolean } = {}) =>
    selected && run(async () => replacePage(await api.layoutPage(selected.id, body)));
  const recomputeAll = () => run(async () => pages.setData(await api.layoutChapter(chapter.id)));
  const moveGutter = (g: LayoutGutter, position: number) =>
    selected &&
    run(async () => replacePage(await api.moveGutter(selected.id, { path: g.path, index: g.index, position })));
  const slantCut = (g: LayoutGutter, ends: [number, number]) =>
    selected && run(async () => replacePage(await api.slantCut(selected.id, { path: g.path, index: g.index, ends })));

  if (pages.loading && !pages.data) return <Loading />;
  if (pages.error) return <Alert>Impossible de charger les pages : {pages.error}</Alert>;
  if (!list.length)
    return (
      <EmptyState title="Aucune page à mettre en page">
        Découpe d&apos;abord le chapitre dans l&apos;onglet Scénario.
        <div className="mt-4">
          <ButtonLink href={`/chapitres/${chapter.id}/scenario`}>Aller au Scénario</ButtonLink>
        </div>
      </EmptyState>
    );

  const sameCount = (templates.data ?? []).filter((t) => t.panel_count === selected?.panels.length);
  const anyStale = list.some((p) => p.layout_stale);
  const seriesStyle = project.data?.layout_style;
  const styleName = (id: string | null | undefined) => styles.data?.find((s) => s.id === id)?.name ?? id ?? "—";
  const advised = selected?.panels.filter((p) => p.regeneration_advised) ?? [];

  return (
    <div className="grid gap-6 lg:grid-cols-[9rem_minmax(0,1fr)_16rem]">
      <nav aria-label="Pages du chapitre" className="order-2 lg:order-1">
        <ol className="grid grid-cols-4 gap-2 sm:grid-cols-6 lg:grid-cols-2">
          {list.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => setSelectedId(p.id)}
                aria-current={p.id === selected?.id ? "page" : undefined}
                className={`block w-full rounded-md border p-1 text-left transition-colors ${
                  p.id === selected?.id ? "border-rose-400" : "border-zinc-800 hover:border-zinc-600"
                }`}
              >
                {p.layout ? (
                  <PageSvg layout={p.layout} compact />
                ) : (
                  <div className="flex aspect-[210/297] items-center justify-center bg-zinc-900 text-[10px] text-zinc-500">
                    {p.panels.length ? "non calculée" : "sans case"}
                  </div>
                )}
                <span className="mt-1 flex justify-between text-[11px] text-zinc-400">
                  <span>p. {p.number}</span>
                  {p.layout_stale && <span className="text-amber-300">obsolète</span>}
                  {p.kind !== "story" && <span className="text-sky-300">{p.kind === "bonus" ? "bonus" : "garde"}</span>}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </nav>

      <div className="order-1 min-w-0 space-y-4 lg:order-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-lg font-semibold text-zinc-100">
            Page {selected?.number}
            {selected && selected.kind !== "story" && (
              <span className="ml-2 text-sm font-normal text-sky-300">{PAGE_KINDS[selected.kind]}</span>
            )}
          </h2>
          {selected && selected.panels.length > 0 && (
            <>
              <label htmlFor="layout-style" className="sr-only">
                Style de mise en page de la page
              </label>
              <Select
                id="layout-style"
                className="!w-auto py-1.5 text-sm"
                value={selected.layout_style ?? ""}
                onChange={(e) => relayout({ style: e.target.value || null })}
                disabled={busy || !styles.data}
                data-testid="page-style"
              >
                <option value="">Style de la série ({styleName(seriesStyle)})</option>
                {(styles.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    Style : {s.name}
                  </option>
                ))}
              </Select>
              <label htmlFor="template" className="sr-only">
                Gabarit
              </label>
              <Select
                id="template"
                className="!w-auto py-1.5 text-sm"
                value={selected.grid_template ?? ""}
                onChange={(e) => relayout({ template_id: e.target.value || null })}
                disabled={busy || !templates.data}
              >
                <option value="">Gabarit automatique{selected.layout && !selected.grid_template ? ` (${templateName(selected.layout.template_id)})` : ""}</option>
                {sameCount.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </Select>
              <Button onClick={() => relayout({ reroll: true })} disabled={busy} data-testid="reroll-page">
                Nouvelle mise en page
              </Button>
              <Button variant="secondary" onClick={() => relayout()} disabled={busy} data-testid="recompute-page">
                Recalculer
              </Button>
            </>
          )}
          <Button variant="ghost" onClick={recomputeAll} disabled={busy}>
            Recalculer tout le chapitre
          </Button>
          {selected?.layout && (
            <ButtonLink href={`/chapitres/${chapter.id}/atelier?page=${selected.id}`} data-testid="open-workshop">
              Ouvrir dans l&apos;atelier
            </ButtonLink>
          )}
        </div>
        {error && <Alert>{error}</Alert>}
        {anyStale && !error && (
          <Alert tone="info">
            Certaines pages sont obsolètes (format, sens de lecture ou style de mise en page de la série modifié) : clique
            sur « Recalculer ».
          </Alert>
        )}
        {advised.length > 0 && (
          <Alert tone="info">
            Régénération conseillée pour {advised.length > 1 ? "les cases" : "la case"}{" "}
            {advised.map((p) => p.index + 1).join(", ")} : leur forme a trop changé depuis l&apos;image retenue. Les
            autres images sont simplement recadrées.
          </Alert>
        )}
        <Card className="p-3">
          {!selected ? null : !selected.panels.length ? (
            <EmptyState title="Page sans case">
              Page {PAGE_KINDS[selected.kind].toLowerCase()} : ajoute des cases dans l&apos;onglet Scénario pour la mettre
              en page.
            </EmptyState>
          ) : !selected.layout ? (
            <EmptyState title="Mise en page non calculée">
              <Button onClick={() => relayout()} disabled={busy}>
                Calculer
              </Button>
            </EmptyState>
          ) : (
            <PageSvg
              layout={selected.layout}
              onMoveGutter={selected.layout_stale || busy ? undefined : moveGutter}
              onSlantCut={selected.layout_stale || busy ? undefined : slantCut}
              labels={selected.panels.map((p) => p.shot_type ?? "")}
            />
          )}
        </Card>
        {selected?.layout && (
          <p className="text-xs text-zinc-500">
            {selected.layout.page.width} × {selected.layout.page.height} px · {selected.layout.dpi} DPI ·{" "}
            {selected.layout.direction === "rtl" ? "lecture droite → gauche" : "lecture gauche → droite"} · reliure à{" "}
            {selected.layout.inner_side === "left" ? "gauche" : "droite"}
            {selected.layout.style && (
              <>
                {" "}
                · style {styleName(selected.layout.style.id)} · graine {selected.layout.style.seed}
                {selected.rythme && <> · rythme {RYTHMES[selected.rythme].toLowerCase()}</>}
              </>
            )}{" "}
            · glisse une gouttière pour redimensionner ses cases voisines, ou une poignée ronde au bout d&apos;une découpe
            pour l&apos;incliner (flèches du clavier aussi).
          </p>
        )}
      </div>

      <aside className="order-3" aria-label="Détail des cases">
        {selected?.layout && (
          <Card className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-zinc-100">Cases (ordre de lecture)</h3>
            <ol className="space-y-3 text-xs">
              {selected.layout.panels.map((lp) => {
                const panel = selected.panels.find((p) => p.id === lp.panel_id) ?? selected.panels[lp.index];
                return (
                  <li key={lp.index} className="border-b border-zinc-800 pb-2 last:border-0" data-testid="layout-panel-info">
                    <p className="font-medium text-zinc-200">
                      {lp.reading_order}. {panel?.shot_type ?? "—"}
                      <span className="ml-1 text-zinc-500">· imp. {panel?.importance}</span>
                      {panel?.intensity && <span className="ml-1 text-zinc-500">· {INTENSITIES[panel.intensity].toLowerCase()}</span>}
                    </p>
                    <p className="text-zinc-400">
                      {lp.width} × {lp.height} px · ratio {lp.ratio.toFixed(2)}
                      {lp.slanted && <span className="ml-1 text-sky-300">· en biais</span>}
                    </p>
                    <p className="text-zinc-500">
                      génération {lp.target.width} × {lp.target.height}
                    </p>
                    <p className={lp.bubble_zone ? "text-rose-300" : "text-zinc-600"}>
                      {lp.bubble_zone
                        ? `bulles : ${lp.bubble_zone.x2 - lp.bubble_zone.x1} × ${lp.bubble_zone.y2 - lp.bubble_zone.y1} px`
                        : "case muette"}
                    </p>
                    {panel?.regeneration_advised && (
                      <p className="font-medium text-amber-300" data-testid="regeneration-advised">
                        Régénération conseillée
                      </p>
                    )}
                  </li>
                );
              })}
            </ol>
          </Card>
        )}
      </aside>
    </div>
  );

  function templateName(id: string): string {
    return templates.data?.find((t) => t.id === id)?.name ?? id;
  }
}

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

function PageSvg({
  layout,
  compact = false,
  labels = [],
  onMoveGutter,
  onSlantCut,
}: {
  layout: PageLayout;
  compact?: boolean;
  labels?: string[];
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
            <polygon points={svgPoints(poly)} fill="#ffffff" stroke="#18181b" strokeWidth={stroke} strokeLinejoin="miter" />
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
