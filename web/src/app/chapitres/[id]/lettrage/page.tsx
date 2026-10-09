"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, Select } from "@/components/ui";
import { api, fullErrorMessage, type BubbleUpdate } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { PAGE_KINDS } from "@/lib/script";
import { useChapter } from "../chapter-context";
import { BubbleEditor } from "./bubble-editor";
import { ExportPanel } from "./export-panel";
import { LetteringCanvas, type CanvasEdit, type LetteringCanvasHandle } from "./lettering-canvas";

export default function LetteringRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <Lettering />
    </Suspense>
  );
}

function Lettering() {
  const { chapter } = useChapter();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const pages = useEngineData(() => api.listPages(chapter.id), [chapter.id]);
  const list = useMemo(() => pages.data ?? [], [pages.data]);
  const pageParam = Number(params.get("page")) || null;
  const page = list.find((p) => p.id === pageParam) ?? list.find((p) => p.layout && p.panels.length) ?? list[0] ?? null;
  const ready = Boolean(page && page.layout && page.panels.length);
  const lettering = useEngineData(
    () => (page && ready ? api.getLettering(page.id) : Promise.resolve(null)),
    [page?.id, ready],
  );
  const [selection, setSelection] = useState<{ page: number; id: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showGuides, setShowGuides] = useState(true);
  const canvasRef = useRef<LetteringCanvasHandle>(null);

  const data = lettering.data && page && lettering.data.page_id === page.id ? lettering.data : null;
  const selectedId = selection && page && selection.page === page.id ? selection.id : null;
  const selected = data?.bubbles.find((b) => b.id === selectedId) ?? null;
  const selectedIndex = selected && data ? data.bubbles.indexOf(selected) : -1;

  // Échap ferme l'éditeur et rend le focus à la bulle.
  useEffect(() => {
    if (!selectedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      const id = selectedId;
      setSelection(null);
      requestAnimationFrame(() => canvasRef.current?.focusBubble(id));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  function navigate(pageId: number) {
    router.replace(`${pathname}?page=${pageId}`, { scroll: false });
  }
  function select(id: number | null) {
    setSelection(id !== null && page ? { page: page.id, id } : null);
  }

  async function run(action: () => Promise<void>): Promise<boolean> {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      return true;
    } catch (e) {
      setError(fullErrorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const update = (id: number, body: BubbleUpdate) =>
    run(async () => lettering.setData(await api.updateBubble(id, body)));
  const commit = (edit: CanvasEdit) => {
    const { id, ...body } = edit;
    update(id, body).then((ok) => {
      if (!ok) lettering.reload();
    });
  };
  const recompute = () => {
    if (!page || !data) return;
    const manual = data.bubbles.filter((b) => b.manual || b.manual_tail).length;
    if (
      manual &&
      !window.confirm(
        `Recalculer le lettrage de la page ${page.number} ? ${manual} bulle${manual > 1 ? "s" : ""} ajustée${manual > 1 ? "s" : ""} à la main ser${manual > 1 ? "ont" : "a"} replacée${manual > 1 ? "s" : ""}.`,
      )
    )
      return;
    run(async () => {
      lettering.setData(await api.resetLettering(page.id));
      setNotice("Lettrage recalculé.");
    });
  };

  if (pages.loading && !pages.data) return <Loading />;
  if (pages.error && !pages.data) return <Alert>Impossible de charger les pages : {pages.error}</Alert>;
  if (!list.length || !page)
    return (
      <EmptyState title="Aucune page dans ce chapitre">
        Découpe d&apos;abord le chapitre dans l&apos;onglet Scénario.
        <div className="mt-4">
          <ButtonLink href={`/chapitres/${chapter.id}/scenario`}>Aller au Scénario</ButtonLink>
        </div>
      </EmptyState>
    );

  const index = list.indexOf(page);
  const prev = list[index - 1];
  const next = list[index + 1];
  const bubbleCount = page.panels.reduce((n, p) => n + p.dialogues.length, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1" role="group" aria-label="Choix de la page">
          <Button variant="secondary" className="!px-2.5" onClick={() => prev && navigate(prev.id)} disabled={!prev} aria-label="Page précédente">
            ←
          </Button>
          <label htmlFor="lettering-page" className="sr-only">
            Page
          </label>
          <Select id="lettering-page" className="!w-auto py-1.5" value={page.id} onChange={(e) => navigate(Number(e.target.value))}>
            {list.map((p) => (
              <option key={p.id} value={p.id}>
                Page {p.number}
                {p.kind !== "story" ? ` (${PAGE_KINDS[p.kind].toLowerCase()})` : ""} —{" "}
                {p.panels.reduce((n, pa) => n + pa.dialogues.length, 0)} bulle(s)
                {!p.layout && p.panels.length ? " · sans mise en page" : ""}
              </option>
            ))}
          </Select>
          <Button variant="secondary" className="!px-2.5" onClick={() => next && navigate(next.id)} disabled={!next} aria-label="Page suivante">
            →
          </Button>
        </div>
        <p className="text-sm text-zinc-400">
          {bubbleCount} bulle{bubbleCount > 1 ? "s" : ""}
        </p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-zinc-400">
            <input
              type="checkbox"
              checked={showGuides}
              onChange={(e) => setShowGuides(e.target.checked)}
              className="h-4 w-4 accent-rose-500"
            />
            Zones de bulles et visages
          </label>
          {data && (
            <Button variant="secondary" onClick={recompute} disabled={busy} data-testid="recompute-lettering">
              Recalculer le lettrage
            </Button>
          )}
          <ButtonLink variant="ghost" href={`/chapitres/${chapter.id}/atelier?page=${page.id}`}>
            Atelier
          </ButtonLink>
        </div>
      </div>

      {error && <Alert>{error}</Alert>}
      {notice && !error && <Alert tone="info">{notice}</Alert>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          {!page.panels.length ? (
            <EmptyState title="Page sans case">Rien à lettrer sur cette page.</EmptyState>
          ) : !page.layout ? (
            <EmptyState title="Page pas encore mise en page">
              Les bulles se posent dans les cases du découpage : calcule d&apos;abord la mise en page.
              <div className="mt-4">
                <ButtonLink href={`/chapitres/${chapter.id}/mise-en-page`}>Aller à la Mise en page</ButtonLink>
              </div>
            </EmptyState>
          ) : lettering.error && !data ? (
            <Alert>Lettrage impossible : {lettering.error}</Alert>
          ) : !data ? (
            <Loading />
          ) : (
            <Card className="p-3 sm:p-5">
              <LetteringCanvas
                ref={canvasRef}
                data={data}
                selectedId={selectedId}
                showGuides={showGuides}
                disabled={busy}
                onSelect={select}
                onCommit={commit}
              />
              <p className="mt-3 text-center text-xs text-zinc-500">
                Clique sur une bulle (ou Tab puis Entrée) pour l&apos;éditer · flèches pour la déplacer, Alt + flèches pour
                la redimensionner · Échap ferme l&apos;éditeur.
              </p>
            </Card>
          )}
        </div>

        <div className="min-w-0 space-y-4 lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)] lg:self-start lg:overflow-y-auto">
          {selected && data && (
            <BubbleEditor
              key={`${selected.id}:${selected.text}:${selected.kind}:${selected.speaker}`}
              bubble={selected}
              index={selectedIndex}
              warnings={data.warnings}
              busy={busy}
              onSave={(body) => update(selected.id, body)}
              onClose={() => {
                const id = selected.id;
                select(null);
                requestAnimationFrame(() => canvasRef.current?.focusBubble(id));
              }}
            />
          )}
          {data && (
            <Card data-testid="lettering-warnings">
              <h2 className="mb-2 font-semibold text-zinc-100">Avertissements</h2>
              {data.warnings.length ? (
                <ul className="space-y-2 text-sm">
                  {data.warnings.map((w, i) => (
                    <li key={i} className="flex gap-2 text-amber-200">
                      <span aria-hidden="true">⚠</span>
                      <span>
                        {w.message}
                        {w.bubble_id !== null && (
                          <button
                            type="button"
                            className="ml-1 text-rose-300 underline hover:text-rose-200"
                            onClick={() => select(w.bubble_id)}
                          >
                            voir la bulle
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-zinc-400">Aucun : toutes les cases ont une image et tout le texte tient.</p>
              )}
            </Card>
          )}
          <ExportPanel chapterId={chapter.id} pageId={page.id} bleedMm={data?.bleed_mm ?? 3} />
        </div>
      </div>
    </div>
  );
}
