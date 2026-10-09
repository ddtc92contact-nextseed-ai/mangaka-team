"use client";

import { useState } from "react";
import { AnnotationBadge, AnnotationBar } from "@/components/annotation";
import { Modal } from "@/components/modal";
import { DetectionOverlay, QCBadge } from "@/components/qc";
import { Alert, Button, Select } from "@/components/ui";
import { engineUrl, fullErrorMessage, type Annotation, type PanelImage } from "@/lib/api";
import { formatDuration, imageDurationS } from "@/lib/generation";
import { QC_VERDICT } from "@/lib/qc";

function caption(img: PanelImage): string {
  return `v${img.version} · seed ${img.seed ?? "—"} · ${formatDuration(imageDurationS(img))}`;
}

/** Bandeau des versions d'une case : vignettes, grand aperçu, choix, suppression, comparaison. */
export function VersionsStrip({
  images,
  onSelect,
  onDelete,
  onAnnotated,
}: {
  images: PanelImage[];
  onSelect: (img: PanelImage) => Promise<void>;
  onDelete: (img: PanelImage) => Promise<void>;
  onAnnotated: (imageId: number, annotation: Annotation | null) => void;
}) {
  const [viewId, setViewId] = useState<number | null>(null);
  const [compareId, setCompareId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sorted = [...images].sort((a, b) => b.version - a.version);
  const viewed = images.find((i) => i.id === viewId) ?? null;
  const chosen = images.find((i) => i.selected) ?? null;
  const compared = viewed && compareId !== null ? (images.find((i) => i.id === compareId) ?? null) : null;

  function open(img: PanelImage) {
    setError(null);
    setCompareId(null);
    setViewId(img.id);
  }
  function close() {
    setViewId(null);
    setCompareId(null);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const remove = (img: PanelImage) =>
    run(async () => {
      if (
        !window.confirm(
          `Supprimer la version ${img.version} (seed ${img.seed ?? "—"}) ? L'image est effacée définitivement.${
            img.selected ? " C'est la version choisie : la case n'en aura plus." : ""
          }`,
        )
      )
        return;
      await onDelete(img);
      close();
    });

  if (!images.length) {
    return <p className="text-xs text-zinc-500">Aucune version pour l&apos;instant : lance une génération.</p>;
  }

  return (
    <>
      <ul className="grid grid-cols-3 gap-2" data-testid="versions">
        {sorted.map((img) => (
          <li key={img.id}>
            <button
              type="button"
              onClick={() => open(img)}
              className={`group relative block w-full overflow-hidden rounded-md bg-zinc-950 text-left ring-inset focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 ${
                img.selected ? "ring-2 ring-rose-400" : "ring-1 ring-zinc-800 hover:ring-zinc-500"
              }`}
              aria-label={`Version ${img.version}, seed ${img.seed ?? "inconnue"}${img.selected ? ", choisie" : ""}${
                img.qc_verdict ? `, QC ${QC_VERDICT[img.qc_verdict].toLowerCase()}` : ""
              } : agrandir`}
              data-testid="version-thumb"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={engineUrl(img.url)}
                alt=""
                loading="lazy"
                className="aspect-square w-full object-cover transition-opacity group-hover:opacity-90"
              />
              {img.selected && (
                <span className="absolute right-1 top-1 rounded bg-rose-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  Choisie
                </span>
              )}
              {img.qc_verdict && (
                <span className="absolute left-1 top-1">
                  <QCBadge verdict={img.qc_verdict} score={img.qc_score} override={Boolean(img.qc.override)} />
                </span>
              )}
              {img.annotation && (
                <span className="absolute bottom-9 right-1">
                  <AnnotationBadge annotation={img.annotation} />
                </span>
              )}
              <span className="block px-1.5 py-1 text-[10px] leading-tight text-zinc-400">
                <span className="block">
                  v{img.version} · {formatDuration(imageDurationS(img))}
                </span>
                <span className="block truncate text-zinc-500" title={`seed ${img.seed ?? "—"}`}>
                  seed {img.seed ?? "—"}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      <Modal
        open={viewed !== null}
        onClose={close}
        size="xl"
        title={
          viewed
            ? compared
              ? `Comparer v${viewed.version} et v${compared.version}`
              : `Version ${viewed.version}${viewed.selected ? " (choisie)" : ""}`
            : ""
        }
        footer={
          viewed && (
            <>
              {!compared && (
                <Button variant="danger" onClick={() => remove(viewed)} disabled={busy} className="mr-auto">
                  Supprimer cette version
                </Button>
              )}
              {!compared && images.length > 1 && (
                <Button
                  variant="secondary"
                  onClick={() => setCompareId((chosen && chosen.id !== viewed.id ? chosen : sorted.find((i) => i.id !== viewed.id))!.id)}
                  disabled={busy}
                >
                  {chosen && chosen.id !== viewed.id ? "Comparer avec la version choisie" : "Comparer avec une autre"}
                </Button>
              )}
              {compared && (
                <Button variant="ghost" onClick={() => setCompareId(null)}>
                  ← Vue simple
                </Button>
              )}
              {!compared && (
                <Button onClick={() => run(() => onSelect(viewed))} disabled={busy || viewed.selected} data-testid="choose-version">
                  {viewed.selected ? "Version choisie" : "Choisir cette version"}
                </Button>
              )}
            </>
          )
        }
      >
        {error && (
          <div className="mb-3">
            <Alert>{error}</Alert>
          </div>
        )}
        {viewed && !compared && (
          <div className="space-y-3">
            <AnnotationBar
              image={viewed}
              onChange={onAnnotated}
              keyboard
              inModal
              navLabel="version"
              onPrev={sorted.indexOf(viewed) > 0 ? () => setViewId(sorted[sorted.indexOf(viewed) - 1].id) : undefined}
              onNext={sorted.indexOf(viewed) < sorted.length - 1 ? () => setViewId(sorted[sorted.indexOf(viewed) + 1].id) : undefined}
            />
            <VersionLarge img={viewed} />
          </div>
        )}
        {viewed && compared && (
          <div className="grid gap-4 md:grid-cols-2">
            {[viewed, compared].map((img, i) => (
              <div key={img.id} className="flex min-w-0 flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  {i === 1 ? (
                    <>
                      <label htmlFor="compare-with" className="sr-only">
                        Version comparée
                      </label>
                      <Select
                        id="compare-with"
                        className="!w-auto py-1 text-xs"
                        value={img.id}
                        onChange={(e) => setCompareId(Number(e.target.value))}
                      >
                        {sorted
                          .filter((o) => o.id !== viewed.id)
                          .map((o) => (
                            <option key={o.id} value={o.id}>
                              Version {o.version}
                              {o.selected ? " (choisie)" : ""}
                            </option>
                          ))}
                      </Select>
                    </>
                  ) : (
                    <span className="text-sm font-medium text-zinc-200">
                      Version {img.version}
                      {img.selected && <span className="ml-2 text-xs text-rose-300">choisie</span>}
                    </span>
                  )}
                  <Button
                    variant={img.selected ? "ghost" : "secondary"}
                    className="!px-2.5 !py-1 text-xs"
                    disabled={busy || img.selected}
                    onClick={() => run(() => onSelect(img))}
                  >
                    {img.selected ? "Choisie" : "Choisir celle-ci"}
                  </Button>
                </div>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={engineUrl(img.url)}
                  alt={`Version ${img.version}`}
                  className="max-h-[60vh] w-full rounded-md bg-zinc-950 object-contain"
                />
                <p className="break-all text-xs text-zinc-500">{caption(img)}</p>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}

function VersionLarge({ img }: { img: PanelImage }) {
  const p = img.params;
  const [boxes, setBoxes] = useState(false);
  const rows: [string, string][] = [
    ["Seed", String(img.seed ?? "—")],
    ["Durée", formatDuration(imageDurationS(img))],
    ["Workflow", img.preset ?? "—"],
    ["Taille", img.width && img.height ? `${img.width} × ${img.height} px` : "—"],
    ["Créée le", new Date(img.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })],
    ["QC", img.qc_verdict ? `${QC_VERDICT[img.qc_verdict]}${img.qc_score !== null ? ` · ${img.qc_score}/100` : ""}` : "pas encore contrôlée"],
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="relative">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={engineUrl(img.url)}
          alt={`Version ${img.version}`}
          className="max-h-[68vh] w-full rounded-md bg-zinc-950 object-contain"
          data-testid="version-large"
        />
        {boxes && img.detections && <DetectionOverlay detections={img.detections} fit="contain" />}
      </div>
      <div className="space-y-3 text-sm">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-zinc-500">{k}</dt>
              <dd className="break-all text-zinc-200">{v}</dd>
            </div>
          ))}
        </dl>
        {img.qc_reasons.length > 0 && (
          <ul className="space-y-0.5 text-xs text-zinc-400">
            {img.qc_reasons.map((r, i) => (
              <li key={i}>• {r}</li>
            ))}
          </ul>
        )}
        {img.detections && (
          <label className="flex items-center gap-1.5 text-xs text-zinc-400">
            <input type="checkbox" checked={boxes} onChange={(e) => setBoxes(e.target.checked)} className="accent-rose-500" />
            Afficher les boîtes détectées
          </label>
        )}
        {typeof p.prompt === "string" && (
          <details>
            <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">Prompt utilisé</summary>
            <p className="mt-1 whitespace-pre-line break-words text-xs text-zinc-400">{p.prompt}</p>
          </details>
        )}
        {typeof p.negative_prompt === "string" && (
          <details>
            <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">Prompt négatif</summary>
            <p className="mt-1 whitespace-pre-line break-words text-xs text-zinc-400">{p.negative_prompt}</p>
          </details>
        )}
      </div>
    </div>
  );
}
