"use client";

import { useState } from "react";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, Select } from "@/components/ui";
import { PageSvg } from "@/components/page-svg";
import { api, errorMessage, type FrameKind, type LayoutGutter, type LayoutPanel, type PageData, type PanelData, type PanelFrame } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { INTENSITIES, RYTHMES } from "@/lib/layout";
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
  const setFrame = (panel: PanelData, change: Partial<PanelFrame>) =>
    run(async () => replacePage(await api.setPanelFrame(panel.id, { ...(panel.frame ?? {}), ...change })));

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
            pour l&apos;incliner (flèches du clavier aussi). Bord, fond perdu et incrustation se règlent case par case, à
            droite.
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
                      {lp.bleed && <span className="ml-1 text-sky-300">· fond perdu</span>}
                      {lp.inset && <span className="ml-1 text-sky-300">· incrustée dans la case {(lp.host_index ?? 0) + 1}</span>}
                      {lp.frame && lp.frame !== "border" && (
                        <span className="ml-1 text-sky-300">· {lp.frame === "fade" ? "fondu" : "sans bord"}</span>
                      )}
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
                    {panel && (
                      <FrameControls
                        panel={panel}
                        layoutPanel={lp}
                        disabled={busy || selected.layout_stale}
                        onChange={(change) => setFrame(panel, change)}
                      />
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

const FRAME_LABELS: Record<FrameKind, string> = { border: "bordure", none: "sans bord", fade: "fondu au papier" };

/** Options de cadre d'une case : « auto » = décidée par le style de mise en page (valeur actuelle entre parenthèses). */
function FrameControls({
  panel,
  layoutPanel,
  disabled,
  onChange,
}: {
  panel: PanelData;
  layoutPanel: LayoutPanel;
  disabled: boolean;
  onChange: (change: Partial<PanelFrame>) => void;
}) {
  const forced = panel.frame ?? { frame: null, bleed: null, inset: null };
  const yesNo = (v: boolean | null) => (v === null ? "" : v ? "oui" : "non");
  const parse = (v: string) => (v === "" ? null : v === "oui");
  const n = panel.index + 1;
  const bleedOff = !layoutPanel.bleed_possible && !forced.bleed;
  return (
    <div className="mt-2 grid grid-cols-1 gap-1.5" data-testid="frame-controls">
      <label className="flex items-center justify-between gap-2 text-zinc-400">
        <span>Bord</span>
        <Select
          className="!w-36 py-1 text-xs"
          value={forced.frame ?? ""}
          onChange={(e) => onChange({ frame: (e.target.value || null) as FrameKind | null })}
          disabled={disabled}
          aria-label={`Bord de la case ${n}`}
          data-testid="panel-frame"
        >
          <option value="">Auto ({FRAME_LABELS[layoutPanel.frame ?? "border"]})</option>
          <option value="border">Bordure</option>
          <option value="none">Sans bord</option>
          <option value="fade">Fondu au papier</option>
        </Select>
      </label>
      <label className="flex items-center justify-between gap-2 text-zinc-400" title={bleedOff ? "La case ne touche pas un bord extérieur de la page" : undefined}>
        <span>Fond perdu</span>
        <Select
          className="!w-36 py-1 text-xs"
          value={yesNo(forced.bleed)}
          onChange={(e) => onChange({ bleed: parse(e.target.value) })}
          disabled={disabled || bleedOff || Boolean(layoutPanel.inset)}
          aria-label={`Fond perdu de la case ${n}`}
          data-testid="panel-bleed"
        >
          <option value="">Auto ({layoutPanel.bleed ? "oui" : "non"})</option>
          <option value="oui">Oui</option>
          <option value="non">Non</option>
        </Select>
      </label>
      <label className="flex items-center justify-between gap-2 text-zinc-400">
        <span>Incrustation</span>
        <Select
          className="!w-36 py-1 text-xs"
          value={yesNo(forced.inset)}
          onChange={(e) => onChange({ inset: parse(e.target.value) })}
          disabled={disabled}
          aria-label={`Incrustation de la case ${n}`}
          data-testid="panel-inset"
        >
          <option value="">Auto ({layoutPanel.inset ? "oui" : "non"})</option>
          <option value="oui">Oui (dans sa voisine)</option>
          <option value="non">Non</option>
        </Select>
      </label>
    </div>
  );
}
