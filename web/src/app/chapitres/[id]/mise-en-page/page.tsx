"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, Select } from "@/components/ui";
import { api, errorMessage, type LayoutGutter, type PageData, type PageLayout } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { PAGE_KINDS } from "@/lib/script";
import { useChapter } from "../chapter-context";

export default function LayoutPreviewPage() {
  const { chapter } = useChapter();
  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id]);
  const templates = useEngineData(() => api.layoutTemplates());
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

  const recomputePage = (templateId?: string | null) =>
    selected &&
    run(async () =>
      replacePage(await api.layoutPage(selected.id, templateId === undefined ? {} : { template_id: templateId })),
    );
  const recomputeAll = () => run(async () => pages.setData(await api.layoutChapter(chapter.id)));
  const moveGutter = (g: LayoutGutter, position: number) =>
    selected &&
    run(async () => replacePage(await api.moveGutter(selected.id, { path: g.path, index: g.index, position })));

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
              <label htmlFor="template" className="sr-only">
                Gabarit
              </label>
              <Select
                id="template"
                className="!w-auto py-1.5 text-sm"
                value={selected.grid_template ?? ""}
                onChange={(e) => recomputePage(e.target.value || null)}
                disabled={busy || !templates.data}
              >
                <option value="">Gabarit automatique{selected.layout && !selected.grid_template ? ` (${templateName(selected.layout.template_id)})` : ""}</option>
                {sameCount.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </Select>
              <Button variant="secondary" onClick={() => recomputePage()} disabled={busy} data-testid="recompute-page">
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
            Certaines pages sont obsolètes (format ou sens de lecture de la série modifié) : clique sur « Recalculer ».
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
              <Button onClick={() => recomputePage()} disabled={busy}>
                Calculer
              </Button>
            </EmptyState>
          ) : (
            <PageSvg
              layout={selected.layout}
              onMoveGutter={selected.layout_stale || busy ? undefined : moveGutter}
              labels={selected.panels.map((p) => p.shot_type ?? "")}
            />
          )}
        </Card>
        {selected?.layout && (
          <p className="text-xs text-zinc-500">
            {selected.layout.page.width} × {selected.layout.page.height} px · {selected.layout.dpi} DPI ·{" "}
            {selected.layout.direction === "rtl" ? "lecture droite → gauche" : "lecture gauche → droite"} · reliure à{" "}
            {selected.layout.inner_side === "left" ? "gauche" : "droite"} · glisse une gouttière pour redimensionner ses
            cases voisines (flèches du clavier aussi).
          </p>
        )}
      </div>

      <aside className="order-3" aria-label="Détail des cases">
        {selected?.layout && (
          <Card className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-zinc-100">Cases (ordre de lecture)</h3>
            <ol className="space-y-3 text-xs">
              {selected.layout.panels.map((lp) => {
                const panel = selected.panels[lp.index];
                return (
                  <li key={lp.index} className="border-b border-zinc-800 pb-2 last:border-0">
                    <p className="font-medium text-zinc-200">
                      {lp.reading_order}. {panel?.shot_type ?? "—"}
                      <span className="ml-1 text-zinc-500">· imp. {panel?.importance}</span>
                    </p>
                    <p className="text-zinc-400">
                      {lp.width} × {lp.height} px · ratio {lp.ratio.toFixed(2)}
                    </p>
                    <p className="text-zinc-500">
                      génération {lp.target.width} × {lp.target.height}
                    </p>
                    <p className={lp.bubble_zone ? "text-rose-300" : "text-zinc-600"}>
                      {lp.bubble_zone
                        ? `bulles : ${lp.bubble_zone.x2 - lp.bubble_zone.x1} × ${lp.bubble_zone.y2 - lp.bubble_zone.y1} px`
                        : "case muette"}
                    </p>
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

function PageSvg({
  layout,
  compact = false,
  labels = [],
  onMoveGutter,
}: {
  layout: PageLayout;
  compact?: boolean;
  labels?: string[];
  onMoveGutter?: (g: LayoutGutter, position: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  // Le glissé en cours appartient à une mise en page : il disparaît dès qu'une nouvelle arrive.
  const [dragState, setDrag] = useState<{ layout: PageLayout; gutter: LayoutGutter; position: number } | null>(null);
  const drag = dragState && dragState.layout === layout ? dragState : null;
  const { width: W, height: H } = layout.page;
  const live = layout.live_area;
  const stroke = Math.max(4, Math.round(W / 300));

  function toPage(e: PointerEvent): { x: number; y: number } | null {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return { x: pt.x, y: pt.y };
  }

  const clamp = (g: LayoutGutter, v: number) => Math.min(g.max, Math.max(g.min, v));

  function onPointerDown(e: PointerEvent<SVGRectElement>, g: LayoutGutter) {
    if (!onMoveGutter) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ layout, gutter: g, position: g.position });
  }
  function onPointerMove(e: PointerEvent<SVGRectElement>) {
    if (!drag) return;
    const p = toPage(e);
    if (!p) return;
    const v = drag.gutter.orientation === "vertical" ? p.x : p.y;
    setDrag({ ...drag, position: clamp(drag.gutter, v) });
  }
  function onPointerUp() {
    if (!drag || !onMoveGutter) return;
    if (Math.abs(drag.position - drag.gutter.position) >= 1) onMoveGutter(drag.gutter, drag.position);
    else setDrag(null);
  }
  function onKey(e: KeyboardEvent<SVGRectElement>, g: LayoutGutter) {
    if (!onMoveGutter) return;
    const dir =
      g.orientation === "vertical"
        ? { ArrowLeft: -1, ArrowRight: 1 }[e.key as "ArrowLeft"]
        : { ArrowUp: -1, ArrowDown: 1 }[e.key as "ArrowUp"];
    if (!dir) return;
    e.preventDefault();
    onMoveGutter(g, clamp(g, g.position + dir * KEY_STEP));
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} ${H}`}
      className={compact ? "block w-full" : "mx-auto block max-h-[72vh] w-full"}
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
        const cx = (p.x1 + p.x2) / 2;
        const cy = (p.y1 + p.y2) / 2;
        const r = Math.min(110, Math.min(p.width, p.height) / 5);
        return (
          <g key={p.index}>
            <rect x={p.x1} y={p.y1} width={p.width} height={p.height} fill="#ffffff" stroke="#18181b" strokeWidth={stroke} />
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
                    y={p.y2 - Math.max(40, stroke * 6)}
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
          const active = drag?.gutter === g;
          const pos = active ? drag.position : g.position;
          const pad = 36;
          const hit = vertical
            ? { x: g.x1 - pad, y: g.y1, width: g.x2 - g.x1 + 2 * pad, height: g.y2 - g.y1 }
            : { x: g.x1, y: g.y1 - pad, width: g.x2 - g.x1, height: g.y2 - g.y1 + 2 * pad };
          return (
            <g key={`${g.path.join("-")}:${g.index}`}>
              {active && (
                <line
                  x1={vertical ? pos : g.x1}
                  x2={vertical ? pos : g.x2}
                  y1={vertical ? g.y1 : pos}
                  y2={vertical ? g.y2 : pos}
                  stroke="#e11d48"
                  strokeWidth={stroke * 1.5}
                />
              )}
              <rect
                {...hit}
                fill="#e11d48"
                fillOpacity={active ? 0.18 : 0}
                className={onMoveGutter ? "outline-none hover:[fill-opacity:0.15] focus:[fill-opacity:0.3]" : undefined}
                style={{ cursor: onMoveGutter ? (vertical ? "col-resize" : "row-resize") : "default" }}
                tabIndex={onMoveGutter ? 0 : -1}
                role="slider"
                aria-orientation={vertical ? "horizontal" : "vertical"}
                aria-label={`Gouttière ${vertical ? "verticale" : "horizontale"}`}
                aria-valuemin={Math.round(g.min)}
                aria-valuemax={Math.round(g.max)}
                aria-valuenow={Math.round(pos)}
                data-testid="gutter"
                onPointerDown={(e) => onPointerDown(e, g)}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onKeyDown={(e) => onKey(e, g)}
              />
            </g>
          );
        })}
    </svg>
  );
}
