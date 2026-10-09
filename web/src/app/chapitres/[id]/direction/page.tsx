"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { PageSvg } from "@/components/page-svg";
import { Alert, Button, ButtonLink, Card, EmptyState, Input, Loading, ProgressBar, Select } from "@/components/ui";
import {
  api,
  fullErrorMessage,
  type ChapterDirection,
  type DaPanel,
  type DirectionEdit,
  type Job,
  type PageData,
  type PageDirection,
} from "@/lib/api";
import {
  DA_INTENSITIES,
  DA_RYTHMES,
  PAGE_CHOCS,
  RYTHME_TONE,
  SFX_INTENSITIES,
  capitalize,
  isLocked,
  pageState,
  panelKey,
} from "@/lib/direction";
import { useEngineData } from "@/lib/hooks";
import { isFinished, useJob } from "@/lib/jobs";
import { useChapter } from "../chapter-context";

const STEP = "art_direction";

export default function DirectionPage() {
  const { chapter } = useChapter();
  const direction = useEngineData(() => api.getDirection(chapter.id), [chapter.id]);
  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id]);
  const lastJob = useEngineData(() => api.chapterJobs(chapter.id, STEP).then((j) => j[0] ?? null), [chapter.id]);
  const [started, setStarted] = useState<Job | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const current = started ?? lastJob.data ?? null;
  const job = useJob(current, (done) => {
    if (done.status === "succeeded") direction.reload();
  });
  const running = job !== null && !isFinished(job);

  const data = direction.data;
  const list = data?.pages ?? [];
  const selected = list.find((p) => p.page_id === selectedId) ?? list[0] ?? null;
  const pageData = pages.data?.find((p) => p.id === selected?.page_id) ?? null;
  const anyDirection = list.some((p) => p.has_direction);
  const pendingCount = list.filter((p) => p.has_direction && p.pending && !p.out_of_date).length;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const start = (pageId?: number) =>
    run(async () => {
      setStarted(await api.startDirection(chapter.id, pageId));
    });

  function replace(d: PageDirection) {
    if (data) direction.setData({ ...data, pages: data.pages.map((p) => (p.page_id === d.page_id ? d : p)) });
  }

  const edit = (d: PageDirection, body: DirectionEdit) => run(async () => replace(await api.editDirection(d.page_id, body)));

  const apply = (pageIds?: number[]) =>
    run(async () => {
      const res = await api.applyDirection(chapter.id, pageIds);
      pages.setData(res.pages);
      direction.reload();
      const skipped = res.skipped.map((s) => `page ${s.number} : ${s.reason}`).join(" · ");
      setNotice(`${capitalize(res.message)}.${skipped ? ` ${skipped}.` : ""}`);
    });

  if ((direction.loading && !data) || (pages.loading && !pages.data)) return <Loading />;
  if (direction.error) return <Alert>Impossible de charger la direction artistique : {direction.error}</Alert>;
  if (!data) return null;
  if (!list.length)
    return (
      <EmptyState title="Aucune page à diriger">
        Découpe d&apos;abord le chapitre dans l&apos;onglet Scénario : la direction artistique part du scénario validé.
        <div className="mt-4">
          <ButtonLink href={`/chapitres/${chapter.id}/scenario`}>Aller au Scénario</ButtonLink>
        </div>
      </EmptyState>
    );

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl space-y-1 text-sm text-zinc-400">
            <p>
              Le directeur artistique choisit le rythme de chaque page, l&apos;intensité et le cadrage de chaque case, à
              partir du scénario, de la bible, du style de mise en page de la série et des choix du chapitre précédent.
              Il ne dessine pas les cases : la mise en page en tire les découpes quand tu appliques ses choix.
            </p>
            <p className="text-xs text-zinc-500">
              Audace : {data.variety_label} ·{" "}
              <Link href="/equipe/directeur-artistique" className="text-rose-300 hover:text-rose-200">
                régler l&apos;agent dans « L&apos;équipe »
              </Link>
              . Un choix que tu modifies est verrouillé 🔒 : l&apos;agent le garde quand il repropose.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => start()} disabled={busy || running} data-testid="run-direction">
              {running ? "Direction en cours…" : anyDirection ? "Relancer sur tout le chapitre" : "Lancer la direction artistique"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => apply()}
              disabled={busy || running || !pendingCount}
              data-testid="apply-direction"
            >
              Appliquer à la mise en page{pendingCount ? ` (${pendingCount})` : ""}
            </Button>
          </div>
        </div>
        {job && <JobLine job={job} />}
        {error && (
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
        )}
        {notice && (
          <div className="mt-4" data-testid="apply-notice">
            <Alert tone="info">
              {notice}{" "}
              <Link href={`/chapitres/${chapter.id}/mise-en-page`} className="text-rose-300 hover:text-rose-200">
                Voir la mise en page
              </Link>
            </Alert>
          </div>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <nav aria-label="Pages du chapitre">
          <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-1">
            {list.map((d) => {
              const page = pages.data?.find((p) => p.id === d.page_id);
              const state = pageState(d);
              return (
                <li key={d.page_id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedId(d.page_id);
                      setHighlight(null);
                    }}
                    aria-current={d.page_id === selected?.page_id ? "page" : undefined}
                    data-testid="direction-thumb"
                    className={`flex w-full gap-2 rounded-md border p-1.5 text-left transition-colors ${
                      d.page_id === selected?.page_id ? "border-rose-400" : "border-zinc-800 hover:border-zinc-600"
                    }`}
                  >
                    <div className="w-14 shrink-0">
                      {page?.layout ? (
                        <PageSvg layout={page.layout} compact />
                      ) : (
                        <div className="aspect-[210/297] bg-zinc-900" />
                      )}
                    </div>
                    <div className="min-w-0 space-y-1 text-[11px]">
                      <p className="font-medium text-zinc-200">Page {d.number}</p>
                      {d.rythme && <RythmeBadge rythme={d.rythme} />}
                      {d.page_choc && <p className="text-rose-300">⚡ {PAGE_CHOCS[d.page_choc]}</p>}
                      <p className={state.tone}>{state.label}</p>
                    </div>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        {selected && (
          <PageEditor
            key={selected.page_id}
            d={selected}
            page={pageData}
            options={data.options}
            seriesStyle={data.series_layout_style}
            busy={busy || running}
            highlight={highlight}
            onHighlight={setHighlight}
            onEdit={(body) => edit(selected, body)}
            onRerun={() => start(selected.page_id)}
            onApply={() => apply([selected.page_id])}
          />
        )}
      </div>
    </div>
  );
}

function JobLine({ job }: { job: Job }) {
  const failed = job.status === "failed";
  return (
    <div className="mt-4 space-y-2" data-testid="direction-job">
      {!isFinished(job) && <ProgressBar value={job.progress} label="Progression de la direction artistique" />}
      {failed ? (
        <Alert>La direction artistique a échoué : {job.error ?? "erreur inconnue"}</Alert>
      ) : (
        <p className={`text-xs ${job.status === "succeeded" ? "text-emerald-300" : "text-zinc-400"}`}>
          {job.status === "succeeded" ? `Terminé : ${job.message}` : job.message}
        </p>
      )}
    </div>
  );
}

function RythmeBadge({ rythme }: { rythme: keyof typeof DA_RYTHMES }) {
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${RYTHME_TONE[rythme]}`}>
      {DA_RYTHMES[rythme]}
    </span>
  );
}

function PageEditor({
  d,
  page,
  options,
  seriesStyle,
  busy,
  highlight,
  onHighlight,
  onEdit,
  onRerun,
  onApply,
}: {
  d: PageDirection;
  page: PageData | null;
  options: ChapterDirection["options"];
  seriesStyle: string;
  busy: boolean;
  highlight: number | null;
  onHighlight: (id: number | null) => void;
  onEdit: (body: DirectionEdit) => void;
  onRerun: () => void;
  onApply: () => void;
}) {
  const templates = options.templates.filter((t) => t.panel_count === d.panel_count);
  const styleName = (id: string | null) => options.styles.find((s) => s.value === id)?.label ?? id ?? "";
  const toggleLock = (key: string) => onEdit(isLocked(d, key) ? { unlock: [key] } : { lock: [key] });

  return (
    <section className="min-w-0 space-y-4" aria-label={`Direction artistique de la page ${d.number}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold text-zinc-100">Page {d.number}</h2>
        {d.has_direction && (
          <>
            <Button
              variant="ghost"
              onClick={() => onEdit({ accept: d.status !== "accepted" })}
              disabled={busy}
              data-testid="accept-page"
            >
              {d.status === "accepted" ? "✓ Acceptée (annuler)" : "Accepter la page"}
            </Button>
            <Button variant="secondary" onClick={onRerun} disabled={busy} data-testid="rerun-page">
              Proposer autre chose
            </Button>
            <Button onClick={onApply} disabled={busy || !d.pending || d.out_of_date} data-testid="apply-page">
              Appliquer cette page
            </Button>
          </>
        )}
      </div>

      {!d.has_direction ? (
        <EmptyState title="Pas encore de direction artistique pour cette page">
          Lance l&apos;agent sur le chapitre : il proposera le rythme, l&apos;intensité et le cadrage de chaque case.
        </EmptyState>
      ) : (
        <>
          {d.out_of_date && (
            <Alert tone="info">
              Les cases de cette page ont changé depuis la proposition : clique sur « Proposer autre chose » pour la
              refaire.
            </Alert>
          )}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
            <div className="space-y-3">
              <Card className="p-3">
                {page?.layout ? (
                  <PageSvg
                    layout={page.layout}
                    labels={page.layout.panels.map((lp) => d.panels.find((pa) => pa.panel_id === lp.panel_id)?.plan ?? "")}
                    highlight={highlight}
                  />
                ) : (
                  <p className="text-xs text-zinc-500">Page pas encore mise en page.</p>
                )}
              </Card>
              <p className="text-xs text-zinc-500">
                {d.applied ? (d.pending ? "Choix modifiés depuis la dernière application." : "Choix appliqués à la mise en page.") : "Pas encore appliquée à la mise en page."}
              </p>
            </div>

            <div className="space-y-4">
              <Card className="p-4" data-testid="rationale">
                <h3 className="mb-1 text-sm font-semibold text-zinc-100">Pourquoi ces choix</h3>
                <p className="text-sm leading-relaxed text-zinc-300">{d.rationale}</p>
              </Card>

              <Card className="grid gap-3 p-4 sm:grid-cols-2">
                <LockedField label="Rythme" id="da-rythme" locked={isLocked(d, "rythme")} onToggle={() => toggleLock("rythme")}>
                  <Select
                    id="da-rythme"
                    value={d.rythme ?? ""}
                    disabled={busy}
                    onChange={(e) => onEdit({ page: { rythme: e.target.value as PageDirection["rythme"] } })}
                  >
                    {options.rythmes.map((r) => (
                      <option key={r} value={r}>
                        {DA_RYTHMES[r]}
                      </option>
                    ))}
                  </Select>
                </LockedField>
                <LockedField
                  label="Page choc"
                  id="da-choc"
                  locked={isLocked(d, "page_choc")}
                  onToggle={() => toggleLock("page_choc")}
                >
                  <Select
                    id="da-choc"
                    value={d.page_choc ?? ""}
                    disabled={busy}
                    onChange={(e) => onEdit({ page: { page_choc: (e.target.value || null) as PageDirection["page_choc"] } })}
                  >
                    <option value="">Non</option>
                    {options.page_chocs.map((c) => (
                      <option key={c} value={c}>
                        {PAGE_CHOCS[c]}
                      </option>
                    ))}
                  </Select>
                </LockedField>
                <LockedField
                  label="Style de mise en page"
                  id="da-style"
                  locked={isLocked(d, "layout_style")}
                  onToggle={() => toggleLock("layout_style")}
                >
                  <Select
                    id="da-style"
                    value={d.layout_style ?? ""}
                    disabled={busy}
                    onChange={(e) => onEdit({ page: { layout_style: e.target.value || null } })}
                  >
                    <option value="">Style de la série ({styleName(seriesStyle)})</option>
                    {options.styles.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </Select>
                </LockedField>
                <LockedField
                  label="Gabarit suggéré"
                  id="da-template"
                  locked={isLocked(d, "template")}
                  onToggle={() => toggleLock("template")}
                >
                  <Select
                    id="da-template"
                    value={d.template ?? ""}
                    disabled={busy}
                    onChange={(e) => onEdit({ page: { template: e.target.value || null } })}
                  >
                    <option value="">Au choix de la mise en page</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </Select>
                </LockedField>
              </Card>

              <ol className="space-y-3">
                {d.panels.map((pa) => (
                  <PanelRow
                    key={`${pa.panel_id}:${pa.ambiance}`}
                    d={d}
                    pa={pa}
                    description={page?.panels.find((p) => p.id === pa.panel_id)?.description ?? ""}
                    scriptShot={page?.panels.find((p) => p.id === pa.panel_id)?.shot_type ?? null}
                    options={options}
                    busy={busy}
                    active={highlight === pa.panel_id}
                    onFocus={() => onHighlight(pa.panel_id)}
                    onEdit={onEdit}
                    onToggle={toggleLock}
                  />
                ))}
              </ol>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function LockButton({ locked, label, onToggle }: { locked: boolean; label: string; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={locked}
      aria-label={locked ? `Déverrouiller : ${label}` : `Verrouiller : ${label}`}
      title={locked ? "Choix de l'auteur, gardé quand l'agent repropose (cliquer pour déverrouiller)" : "Verrouiller ce choix"}
      className={`rounded px-1 text-xs transition-colors ${locked ? "" : "opacity-30 grayscale hover:opacity-80"}`}
      data-testid="lock"
    >
      {locked ? "🔒" : "🔓"}
    </button>
  );
}

function LockedField({
  label,
  id,
  locked,
  onToggle,
  children,
}: {
  label: string;
  id: string;
  locked: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-xs font-medium text-zinc-400">
          {label}
        </label>
        <LockButton locked={locked} label={label} onToggle={onToggle} />
      </div>
      {children}
    </div>
  );
}

function PanelRow({
  d,
  pa,
  description,
  scriptShot,
  options,
  busy,
  active,
  onFocus,
  onEdit,
  onToggle,
}: {
  d: PageDirection;
  pa: DaPanel;
  description: string;
  scriptShot: string | null;
  options: ChapterDirection["options"];
  busy: boolean;
  active: boolean;
  onFocus: () => void;
  onEdit: (body: DirectionEdit) => void;
  onToggle: (key: string) => void;
}) {
  const n = pa.index + 1;
  const [ambiance, setAmbiance] = useState(pa.ambiance);
  const [sfxText, setSfxText] = useState("");
  const [sfxLevel, setSfxLevel] = useState("moyen");
  const set = (fields: Partial<Omit<DaPanel, "panel_id" | "index">>) => onEdit({ panels: [{ panel_id: pa.panel_id, ...fields }] });
  const field = (name: string, label: string, values: string[], labels?: Record<string, string>) => {
    const key = panelKey(pa.panel_id, name);
    const id = `da-${pa.panel_id}-${name}`;
    return (
      <LockedField label={label} id={id} locked={isLocked(d, key)} onToggle={() => onToggle(key)}>
        <Select
          id={id}
          className="py-1.5"
          value={(pa as unknown as Record<string, string | null>)[name] ?? ""}
          disabled={busy}
          onChange={(e) => set({ [name]: e.target.value })}
          data-testid={`panel-${name}`}
        >
          {values.map((v) => (
            <option key={v} value={v}>
              {labels?.[v] ?? capitalize(v)}
            </option>
          ))}
        </Select>
      </LockedField>
    );
  };

  return (
    <li
      onFocusCapture={onFocus}
      onMouseEnter={onFocus}
      data-testid="direction-panel"
      className={`rounded-xl border bg-zinc-900/60 p-4 transition-colors ${active ? "border-rose-400/70" : "border-zinc-800"}`}
    >
      <p className="mb-3 text-sm text-zinc-300">
        <span className="font-semibold text-zinc-100">Case {n}</span>
        {scriptShot && <span className="text-zinc-500"> · scénario : {scriptShot}</span>}
        {description && <span className="block text-xs text-zinc-500">{description}</span>}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {field("intensity", "Intensité", options.intensities, DA_INTENSITIES)}
        {field("plan", "Plan", options.plans)}
        {field("angle", "Angle", options.angles)}
        {field("cadre", "Cadre", options.cadres)}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <LockedField
          label="Lumière et ambiance"
          id={`da-${pa.panel_id}-ambiance`}
          locked={isLocked(d, panelKey(pa.panel_id, "ambiance"))}
          onToggle={() => onToggle(panelKey(pa.panel_id, "ambiance"))}
        >
          <Input
            id={`da-${pa.panel_id}-ambiance`}
            className="py-1.5"
            value={ambiance}
            disabled={busy}
            maxLength={300}
            onChange={(e) => setAmbiance(e.target.value)}
            onBlur={() => ambiance !== pa.ambiance && set({ ambiance })}
          />
        </LockedField>
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400">Onomatopées suggérées</span>
            <LockButton
              locked={isLocked(d, panelKey(pa.panel_id, "sfx"))}
              label={`onomatopées de la case ${n}`}
              onToggle={() => onToggle(panelKey(pa.panel_id, "sfx"))}
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {pa.sfx.map((s, i) => (
              <span key={`${s.text}-${i}`} className="inline-flex items-center gap-1 rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-200">
                {s.text} <span className="text-zinc-500">({SFX_INTENSITIES[s.intensity] ?? s.intensity})</span>
                <button
                  type="button"
                  className="text-zinc-500 hover:text-red-300"
                  aria-label={`Retirer l'onomatopée ${s.text}`}
                  disabled={busy}
                  onClick={() => set({ sfx: pa.sfx.filter((_, j) => j !== i) })}
                >
                  ×
                </button>
              </span>
            ))}
            {pa.sfx.length < 4 && (
              <form
                className="flex items-center gap-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!sfxText.trim()) return;
                  set({ sfx: [...pa.sfx, { text: sfxText.trim(), intensity: sfxLevel }] });
                  setSfxText("");
                }}
              >
                <label htmlFor={`sfx-${pa.panel_id}`} className="sr-only">
                  Nouvelle onomatopée
                </label>
                <Input
                  id={`sfx-${pa.panel_id}`}
                  className="!w-24 py-1 text-xs"
                  placeholder="BAM !"
                  maxLength={40}
                  value={sfxText}
                  disabled={busy}
                  onChange={(e) => setSfxText(e.target.value)}
                />
                <label htmlFor={`sfx-level-${pa.panel_id}`} className="sr-only">
                  Intensité de l&apos;onomatopée
                </label>
                <Select
                  id={`sfx-level-${pa.panel_id}`}
                  className="!w-auto py-1 text-xs"
                  value={sfxLevel}
                  disabled={busy}
                  onChange={(e) => setSfxLevel(e.target.value)}
                >
                  {options.sfx_intensities.map((v) => (
                    <option key={v} value={v}>
                      {SFX_INTENSITIES[v] ?? v}
                    </option>
                  ))}
                </Select>
                <Button type="submit" variant="ghost" className="px-2 py-1 text-xs" disabled={busy || !sfxText.trim()}>
                  Ajouter
                </Button>
              </form>
            )}
          </div>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">Le cadre et les onomatopées seront utilisés par le lettrage.</p>
    </li>
  );
}

