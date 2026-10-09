"use client";

import { api, type Estimate } from "@/lib/api";
import { formatDuration, formatEstimate } from "@/lib/generation";
import { useEngineData } from "@/lib/hooks";
import { useQueue } from "./queue";

function detail(est: Estimate): string {
  return est.by_preset
    .map(
      (p) =>
        `${p.panels} case${p.panels > 1 ? "s" : ""} ${p.tier ?? p.preset} (${p.preset}) × ${formatDuration(p.per_panel_s)}` +
        (p.measured ? ` — médiane de ${p.samples} générations` : " — estimation du preset"),
    )
    .join("\n");
}

/** « Temps estimé : ~X h Y min » des cases encore à générer d'un chapitre ou d'une série.
 *  Recalculé à chaque job qui quitte la file ; « estimation » tant que les vraies durées manquent. */
export function EstimateLabel({ chapterId, projectId }: { chapterId?: number; projectId?: number }) {
  const { finished } = useQueue();
  const est = useEngineData(
    () => (chapterId ? api.chapterEstimate(chapterId) : api.projectEstimate(projectId as number)),
    [chapterId, projectId, finished],
  );
  const e = est.data;
  if (!e) return null;
  if (e.remaining_panels === 0) {
    return (
      <span className="text-zinc-500" data-testid="time-estimate">
        Toutes les cases ont une version choisie
      </span>
    );
  }
  return (
    <span title={detail(e)} data-testid="time-estimate">
      Temps estimé :{" "}
      <strong className="font-medium text-zinc-200">{e.total_s === null ? "inconnu" : formatEstimate(e.total_s)}</strong>{" "}
      <span className="text-zinc-500">
        ({e.remaining_panels} case{e.remaining_panels > 1 ? "s" : ""} à générer)
      </span>
      {!e.measured && (
        <span className="ml-1.5 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium text-zinc-400">estimation</span>
      )}
    </span>
  );
}
