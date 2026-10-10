"use client";

import { useState } from "react";
import { api, errorMessage, type Project } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { useToast } from "./toast";
import { Alert, Button } from "./ui";

const plural = (n: number, word: string) => `${n} ${word}${n > 1 ? "s" : ""}`;

/** Fiche série : note unique « série restée en sage » (ancienne mise à jour) et, après un changement de
 * style de mise en page, proposition de remettre en page les pages pas encore générées. */
export function LayoutStyleNotices({
  project,
  offerRelayout,
  onProject,
  onDone,
}: {
  project: Project;
  /** Le style vient de changer : proposer « Remettre en page les pages non générées ». */
  offerRelayout: boolean;
  onProject: (project: Project, styleChanged: boolean) => void;
  onDone: () => void;
}) {
  const presets = useEngineData(() => api.presets());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const styles = presets.data?.layout_styles ?? [];
  const current = styles.find((s) => s.id === project.layout_style);
  const fallback = styles.find((s) => s.is_default && s.id !== "sage");

  async function update(body: { layout_style?: string; layout_style_notice?: false }) {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.updateProject(project.id, body);
      onProject(saved, saved.layout_style !== project.layout_style);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function relayout() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.relayoutProject(project.id);
      const n = res.relaid_page_ids.length;
      toast(n ? `${plural(n, "page")} remise${n > 1 ? "s" : ""} en page` : "Aucune page à remettre en page", n ? "success" : "info");
      onProject(await api.getProject(project.id), false);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const relayoutCount = project.relayout_page_count;
  const showOffer = offerRelayout && relayoutCount > 0;
  if (!project.layout_style_notice && !showOffer && !error) return null;

  return (
    <div className="mb-4 space-y-3">
      {error && <Alert>{error}</Alert>}
      {project.layout_style_notice && project.layout_style === "sage" && (
        <div
          role="status"
          className="rounded-md border border-amber-800/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-200"
          data-testid="sage-notice"
        >
          <p>
            Cette série est en mise en page <strong>Sage</strong> (cases droites) parce qu&apos;une ancienne mise à jour
            l&apos;y a passée, pas par ton choix. Les nouvelles séries sont en{" "}
            <strong>{fallback?.name ?? "Dynamique"}</strong> : des découpes en biais sur la plupart des pages.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {fallback && (
              <Button onClick={() => update({ layout_style: fallback.id })} disabled={busy} data-testid="sage-notice-switch">
                Passer en {fallback.name}
              </Button>
            )}
            <Button variant="secondary" onClick={() => update({ layout_style_notice: false })} disabled={busy}>
              Garder Sage
            </Button>
          </div>
        </div>
      )}
      {showOffer && (
        <div
          role="status"
          className="rounded-md border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm text-zinc-300"
          data-testid="relayout-offer"
        >
          <p>
            Style de mise en page : <strong className="text-zinc-50">{current?.name ?? project.layout_style}</strong>.{" "}
            {plural(relayoutCount, "page")} sans image générée {relayoutCount > 1 ? "peuvent" : "peut"} prendre ce style
            tout de suite. Les pages déjà générées (même en croquis) ne bougent pas ; les gouttières déplacées à la main
            des pages remises en page sont recalculées.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={relayout} disabled={busy} data-testid="relayout-pages">
              {busy ? "Mise en page…" : "Remettre en page les pages non générées"}
            </Button>
            <Button variant="ghost" onClick={onDone} disabled={busy}>
              Plus tard
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
