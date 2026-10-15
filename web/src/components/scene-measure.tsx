"use client";

import { useState } from "react";
import { useConfirm } from "@/components/confirm";
import { useToast } from "@/components/toast";
import { Alert, Button, Card } from "@/components/ui";
import { api, errorMessage, type Job, type SceneMeasure, type SceneMeasures } from "@/lib/api";
import { MOTION_LABELS, rangeText, shotRows } from "@/lib/scene-measure";

/** Name scène par scène : mesure de chaque scène face à son profil (cases, répliques, cases muettes et encadrés par
 * planche, plans appliqués ou proposés), et réécriture d'une seule scène — scénario (`kind="script"`) ou direction
 * artistique (`kind="direction"`) — sans toucher aux autres. Un écart reste un avertissement. */
export function SceneMeasurePanel({
  chapterId,
  measures,
  kind,
  disabled,
  onStarted,
}: {
  chapterId: number;
  measures: SceneMeasures;
  kind: "script" | "direction";
  disabled?: boolean;
  onStarted: (job: Job) => void;
}) {
  if (!measures.scenes.length) return null;
  const written = measures.scenes.some((m) => m.pages.length > 0);
  if (!written) return null;
  return (
    <Card data-testid="scene-measures">
      <div className="mb-3">
        <h2 className="text-lg font-semibold text-zinc-100">Mesure par scène</h2>
        <p className="text-xs text-zinc-500">
          {kind === "script"
            ? "Chaque scène est écrite d'un seul tenant selon le profil de son type : cases, répliques et cases muettes par planche, encadrés de narration."
            : "Chaque scène est dirigée selon le profil de son type : parts de plans de la scène, lignes de mouvement, rythme du chapitre."}{" "}
          Un écart reste un avertissement, jamais un blocage.
        </p>
        {!measures.scene_mode && (
          <p className="mt-1 text-xs text-amber-300">
            Des pages ne sont rattachées à aucune scène : relance « Découper » pour écrire le chapitre scène par scène.
          </p>
        )}
      </div>
      <div className="space-y-4">
        {measures.scenes.map((m) => (
          <SceneRow
            key={m.scene_id}
            chapterId={chapterId}
            measure={m}
            kind={kind}
            disabled={disabled || !measures.scene_mode}
            onStarted={onStarted}
          />
        ))}
      </div>
    </Card>
  );
}

function SceneRow({
  chapterId,
  measure: m,
  kind,
  disabled,
  onStarted,
}: {
  chapterId: number;
  measure: SceneMeasure;
  kind: "script" | "direction";
  disabled?: boolean;
  onStarted: (job: Job) => void;
}) {
  const confirm = useConfirm();
  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const e = m.expected;
  const shots = shotRows(m);
  const label = kind === "script" ? "Réécrire cette scène" : "Rediriger cette scène";

  async function regenerate() {
    const ok = await confirm({
      title: `${label} (scène ${m.number}) ?`,
      message:
        kind === "script"
          ? "Les pages de cette scène seront remplacées par une nouvelle name (leurs croquis et versions avec elles). Les autres scènes, leurs pages, croquis et versions ne bougent pas."
          : "Les pages de cette scène reçoivent une nouvelle direction artistique, même appliquée (tes choix verrouillés sont gardés). Les autres scènes ne bougent pas.",
      confirmLabel: label,
      danger: kind === "script",
    });
    if (!ok) return;
    setStarting(true);
    setError(null);
    try {
      const job =
        kind === "script" ? await api.rewriteScene(chapterId, m.scene_id) : await api.redirectScene(chapterId, m.scene_id);
      toast(kind === "script" ? `Réécriture de la scène ${m.number} lancée` : `Direction de la scène ${m.number} lancée`, "info");
      onStarted(job);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  }

  return (
    <section
      className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4"
      aria-label={`Scène ${m.number}`}
      data-testid={`scene-measure-${m.number}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-medium text-zinc-100">
            Scène {m.number} · {m.type_name}
            {m.title && <span className="text-zinc-400"> — {m.title}</span>}
          </h3>
          <p className="text-xs text-zinc-500">
            {m.pages.length} page{m.pages.length > 1 ? "s" : ""}
            {m.pages.length !== m.planned_pages && ` (${m.planned_pages} prévue${m.planned_pages > 1 ? "s" : ""})`}
            {m.pages.length > 0 && ` · pages ${m.pages[0].number} à ${m.pages[m.pages.length - 1].number}`} · profil :{" "}
            {m.tempo}
          </p>
        </div>
        <Button variant="secondary" onClick={regenerate} disabled={disabled || starting} data-testid={`regenerate-scene-${m.number}`}>
          {starting ? "Lancement…" : label}
        </Button>
      </div>
      {error && (
        <div className="mt-2">
          <Alert>{error}</Alert>
        </div>
      )}
      {m.pages.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[28rem] text-left text-xs">
            <thead className="text-zinc-500">
              <tr>
                <th className="py-1 pr-3 font-normal">Planche</th>
                <th className="py-1 pr-3 font-normal">Cases ({rangeText(e.panels_min, e.panels_max)})</th>
                <th className="py-1 pr-3 font-normal">Répliques ({rangeText(e.replies_min, e.replies_max)})</th>
                <th className="py-1 pr-3 font-normal">Muettes (≥ {e.silent_min ?? "—"})</th>
                <th className="py-1 pr-3 font-normal">
                  Narration ({e.narration_max === null ? "libre" : `≤ ${e.narration_max}`})
                </th>
              </tr>
            </thead>
            <tbody>
              {m.pages.map((p) => (
                <tr key={p.page_id} className={p.warnings.length ? "text-amber-300" : "text-zinc-300"}>
                  <td className="py-0.5 pr-3">p. {p.number}</td>
                  <td className="py-0.5 pr-3">{p.panels}</td>
                  <td className="py-0.5 pr-3">{p.replies}</td>
                  <td className="py-0.5 pr-3">{p.silent}</td>
                  <td className="py-0.5 pr-3">{p.narration}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 text-xs text-zinc-400" data-testid={`scene-shots-${m.number}`}>
        {shots.rows.length === 0 ? (
          <span>Plans : parts de la série (pas de part propre à ce type de scène).</span>
        ) : shots.source === null ? (
          <span>
            Plans visés : {shots.rows.map((r) => `${r.label} ${r.target}`).join(" · ")} — pas encore de direction
            artistique pour toutes les cases.
          </span>
        ) : (
          <span>
            Plans {shots.source} :{" "}
            {shots.rows.map((r, i) => (
              <span key={r.cls} className={r.off ? "text-amber-300" : "text-zinc-300"}>
                {i > 0 && " · "}
                {r.label} {r.count}/{r.total} (visé : {r.target})
              </span>
            ))}
          </span>
        )}
        {e.motion_lines && <span> · {MOTION_LABELS[e.motion_lines]}</span>}
      </div>
      {m.warnings.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-amber-300" data-testid={`scene-warnings-${m.number}`}>
          {m.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
