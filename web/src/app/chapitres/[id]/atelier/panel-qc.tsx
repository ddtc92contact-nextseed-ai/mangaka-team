"use client";

import { useState } from "react";
import { DetectionLegend, DetectionOverlay, QCBadge } from "@/components/qc";
import { Alert, Button, ProgressBar } from "@/components/ui";
import { engineUrl, type PanelImage, type QCStatus, type QueueItem, type VisionMode } from "@/lib/api";
import { QC_LAYERS, QC_LAYER_STATUS, QC_SOURCE, QC_VERDICT, formatMs } from "@/lib/qc";

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

/** Contrôle qualité d'une version : verdict, raisons, couches, boîtes, relance, « valider quand même ». */
export function PanelQC({
  image,
  job,
  status,
  busy,
  onRun,
  onOverride,
}: {
  image: PanelImage | null;
  job: QueueItem | null;
  status: QCStatus | null;
  busy: boolean;
  onRun: (vision: VisionMode) => void;
  onOverride: (img: PanelImage) => void;
}) {
  const [showBoxes, setShowBoxes] = useState(true);
  const qc = image?.qc ?? {};
  const unavailable = status !== null && !status.available;
  const visionOk = status?.layers.vision.available ?? true;

  return (
    <div className="space-y-3" data-testid="panel-qc">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-300">Contrôle qualité</h3>
        {image && <QCBadge verdict={image.qc_verdict} score={image.qc_score} override={Boolean(qc.override)} />}
      </div>

      {!image ? (
        <p className="text-xs text-zinc-500">Pas encore de version à contrôler.</p>
      ) : (
        <>
          <p className="text-xs text-zinc-500">
            Version {image.version}
            {image.selected ? " (choisie)" : ""}
            {qc.at ? ` · ${QC_SOURCE[qc.source ?? ""] ?? "contrôle"} · ${formatDate(qc.at)}` : " · pas encore contrôlée"}
            {qc.duration_ms !== undefined && qc.source !== "human" ? ` · ${formatMs(qc.duration_ms)}` : ""}
          </p>

          {job && (
            <div className="space-y-1" aria-live="polite">
              <p className="text-xs text-zinc-300">
                {job.job.status === "running"
                  ? `${job.job.message || "Contrôle en cours…"} · ${job.job.progress} %`
                  : `Contrôle en file (position ${job.position}) : il passe après les générations en cours.`}
              </p>
              {job.job.status === "running" && <ProgressBar value={job.job.progress} label="Progression du contrôle qualité" />}
            </div>
          )}

          {image.qc_reasons.length > 0 && (
            <ul className="space-y-1 text-xs" data-testid="qc-reasons">
              {image.qc_reasons.map((r, i) => (
                <li key={i} className="flex gap-1.5 text-zinc-300">
                  <span aria-hidden className="text-zinc-500">
                    •
                  </span>
                  {r}
                </li>
              ))}
            </ul>
          )}

          {qc.override && (
            <p className="rounded-md bg-emerald-500/10 px-2 py-1.5 text-xs text-emerald-200" data-testid="qc-override">
              Validée à la main le {formatDate(qc.override.at)}
              {qc.override.previous_verdict
                ? ` (verdict du QC : ${QC_VERDICT[qc.override.previous_verdict].toLowerCase()}${qc.override.previous_score !== null ? `, ${qc.override.previous_score}/100` : ""})`
                : " (pas encore contrôlée)"}
              .
            </p>
          )}

          {qc.layers && (
            <dl className="divide-y divide-zinc-800 rounded-md border border-zinc-800 text-xs">
              {QC_LAYERS.map((l) => {
                const layer = qc.layers?.[l.id];
                if (!layer) return null;
                return (
                  <div key={l.id} className="space-y-0.5 px-2 py-1.5" data-testid={`qc-layer-${l.id}`}>
                    <div className="flex items-center justify-between gap-2">
                      <dt className="text-zinc-300" title={l.hint}>
                        {l.label}
                      </dt>
                      <dd className="text-right tabular-nums text-zinc-400">
                        {layer.status === "done" ? (
                          <>
                            <span className="text-zinc-100">{layer.score}/100</span> · {formatMs(layer.duration_ms)}
                          </>
                        ) : (
                          <span className={layer.status === "error" || layer.status === "unavailable" ? "text-amber-300" : ""}>
                            {QC_LAYER_STATUS[layer.status]}
                          </span>
                        )}
                      </dd>
                    </div>
                    {layer.message && <dd className="text-[11px] text-zinc-500">{layer.message}</dd>}
                    {layer.counts && (
                      <dd className="text-[11px] text-zinc-500">
                        {layer.counts.faces} visage{layer.counts.faces > 1 ? "s" : ""} (attendu{(layer.expected_faces ?? 0) > 1 ? "s" : ""} : {layer.expected_faces ?? 0}) ·{" "}
                        {layer.counts.hands} main{layer.counts.hands > 1 ? "s" : ""} · {layer.counts.text} zone{layer.counts.text > 1 ? "s" : ""} de texte
                      </dd>
                    )}
                    {layer.characters && layer.characters.length > 0 && (
                      <dd className="text-[11px] text-zinc-500">
                        {layer.characters.map((c) => (
                          <span key={c.name} className={`mr-2 ${c.ok ? "" : "text-amber-300"}`}>
                            {c.name} : {c.similarity.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}
                          </span>
                        ))}
                      </dd>
                    )}
                    {layer.status === "done" && layer.why && <dd className="text-[11px] text-zinc-500">Lancée : {layer.why}</dd>}
                  </div>
                );
              })}
            </dl>
          )}

          {image.detections && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <DetectionLegend />
                <label className="flex items-center gap-1.5 text-xs text-zinc-400">
                  <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} className="accent-rose-500" />
                  Boîtes
                </label>
              </div>
              <div className="relative overflow-hidden rounded-md bg-zinc-950">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={engineUrl(image.url)} alt={`Version ${image.version} avec les détections`} className="block max-h-72 w-full object-contain" />
                {showBoxes && <DetectionOverlay detections={image.detections} fit="contain" />}
              </div>
            </div>
          )}

          {unavailable && <Alert>Contrôle qualité indisponible : {status?.detail}</Alert>}

          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" className="!py-1.5 text-xs" onClick={() => onRun("auto")} disabled={busy || unavailable || job !== null} data-testid="qc-run">
              {image.qc_verdict ? "Relancer le QC" : "Lancer le QC"}
            </Button>
            <Button
              variant="ghost"
              className="!px-2 !py-1.5 text-xs"
              onClick={() => onRun("force")}
              disabled={busy || unavailable || job !== null || !visionOk}
              title={visionOk ? "Ajoute la couche vision (lente) même si les détecteurs suffisent" : (status?.layers.vision.detail ?? undefined)}
            >
              Avec la vision
            </Button>
            {image.qc_verdict && image.qc_verdict !== "ok" && (
              <Button className="!py-1.5 text-xs" onClick={() => onOverride(image)} disabled={busy} data-testid="qc-override-button">
                Valider quand même
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
