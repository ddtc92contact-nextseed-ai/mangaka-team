"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Modal } from "@/components/modal";
import { useToast } from "@/components/toast";
import { Alert, Button } from "@/components/ui";
import { api, engineUrl, fullErrorMessage, type PanelCrop, type PanelData } from "@/lib/api";
import { atMaxZoom, boundedCrop, DEFAULT_CROP, imagePlacement, panCrop, ZOOM_MAX, zoomCrop } from "@/lib/crop";

const zoomLabel = (z: number) => `×${z.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Bloc « Cadrage » de l'inspecteur : état du cadrage de la case, « Recadrer… » et « Recentrer ». */
export function CropBlock({ panel, disabled, onSaved }: { panel: PanelData | null; disabled: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!panel) return null;
  const imageUrl = panel.selected_image_url ?? panel.sketch_image_url ?? null;
  const box = panel.bbox;
  const usable = Boolean(imageUrl && box && box.x2 > box.x1 && box.y2 > box.y1);

  async function recentre() {
    setBusy(true);
    setError(null);
    try {
      await api.resetPanelCrop(panel!.id);
      onSaved();
      toast("Image recentrée dans la case");
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2" data-testid="crop-block">
      <h3 className="text-sm font-medium text-zinc-300">Cadrage dans la case</h3>
      <p className="text-xs text-zinc-400" data-testid="crop-status">
        {panel.crop ? `Cadrage manuel · zoom ${zoomLabel(panel.crop.zoom)}` : "Centré automatiquement (remplissage)"}
        {!imageUrl
          ? " — aucune image à cadrer."
          : !box
            ? " — calcule la mise en page d'abord."
            : panel.selected_image_url
              ? ""
              : " — sur le croquis (gardé pour la version propre)."}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" className="!px-2 !py-1 text-xs" onClick={() => setOpen(true)} disabled={disabled || busy || !usable} data-testid="crop-open">
          Recadrer…
        </Button>
        {panel.crop && (
          <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={recentre} disabled={disabled || busy} data-testid="crop-reset">
            Recentrer
          </Button>
        )}
      </div>
      {error && <Alert>{error}</Alert>}
      {open && usable && (
        <CropEditor
          panel={panel}
          imageUrl={imageUrl!}
          onClose={() => setOpen(false)}
          onSaved={(message) => {
            setOpen(false);
            onSaved();
            toast(message);
          }}
        />
      )}
    </div>
  );
}

/**
 * Fenêtre « Recadrer » : glisser l'image (souris, doigt ou flèches), zoomer (molette, +/−, curseur), « Recentrer »
 * (= centrage automatique), puis Valider / Annuler. Le zoom ne descend jamais sous le remplissage de la case, et
 * s'arrête au maximum permis par la résolution de l'image.
 */
export function CropEditor({
  panel,
  imageUrl,
  onClose,
  onSaved,
}: {
  panel: PanelData;
  imageUrl: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const box = panel.bbox!;
  const W = box.x2 - box.x1;
  const H = box.y2 - box.y1;
  const limit = Math.max(1, Math.min(panel.crop_max_zoom ?? ZOOM_MAX, ZOOM_MAX));
  // null = centré automatiquement (« Recentrer ») ; sinon le cadrage en cours d'édition.
  const [crop, setCrop] = useState<PanelCrop | null>(panel.crop ?? null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; start: PanelCrop; id: number } | null>(null);

  const shown = size ? boundedCrop(crop ?? DEFAULT_CROP, size.w, size.h, W, H, limit) : (crop ?? DEFAULT_CROP);
  const place = size ? imagePlacement(size.w, size.h, W, H, crop ? shown : null) : null;
  const maxed = atMaxZoom(shown, limit);
  const ready = size !== null && !saving;

  const zoomTo = (z: number) => size && setCrop(zoomCrop(shown, z, size.w, size.h, W, H, limit));
  const panBy = (dx: number, dy: number, from: PanelCrop = shown) => size && setCrop(panCrop(from, dx, dy, size.w, size.h, W, H, limit));

  // Molette : écouteur non passif, pour que la page ne défile pas pendant le zoom.
  const wheel = useRef<(e: WheelEvent) => void>(() => {});
  useEffect(() => {
    wheel.current = (e: WheelEvent) => {
      if (!size) return;
      e.preventDefault();
      zoomTo(shown.zoom * Math.exp(-e.deltaY * 0.0015));
    };
  });
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    const handler = (e: WheelEvent) => wheel.current(e);
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (!size || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, start: shown, id: e.pointerId };
    frame.current?.focus();
  }
  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const d = drag.current;
    const rect = frame.current?.getBoundingClientRect();
    if (!d || d.id !== e.pointerId || !rect || rect.width === 0) return;
    panBy((e.clientX - d.x) / rect.width, (e.clientY - d.y) / rect.height, d.start);
  }
  const endDrag = () => {
    drag.current = null;
  };

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.shiftKey ? 0.2 : 0.05;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) {
      e.preventDefault();
      panBy(...moves[e.key]);
    } else if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      zoomTo(shown.zoom * 1.1);
    } else if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      zoomTo(shown.zoom / 1.1);
    } else if (e.key === "0") {
      e.preventDefault();
      setCrop(null);
    }
  }

  async function validate() {
    setSaving(true);
    setError(null);
    try {
      if (crop === null) {
        if (panel.crop) await api.resetPanelCrop(panel.id);
        onSaved("Image recentrée dans la case");
      } else {
        await api.setPanelCrop(panel.id, shown);
        onSaved(`Cadrage enregistré (zoom ${zoomLabel(shown.zoom)})`);
      }
    } catch (e) {
      setError(fullErrorMessage(e));
      setSaving(false);
    }
  }

  const isSketch = !panel.selected_image_url;
  return (
    <Modal
      open
      onClose={onClose}
      title={`Recadrer la case ${panel.index + 1}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving} data-testid="crop-cancel">
            Annuler
          </Button>
          <Button variant="secondary" onClick={() => setCrop(null)} disabled={!ready || crop === null} data-testid="crop-recentre">
            Recentrer
          </Button>
          <Button onClick={validate} disabled={!ready} data-testid="crop-validate">
            {saving ? "Enregistrement…" : "Valider"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p id="crop-help" className="text-xs text-zinc-400">
          Glisse l&apos;image pour la déplacer, molette ou +/− pour zoomer. Au clavier : flèches pour déplacer (Maj : plus
          vite), + et − pour zoomer, 0 pour recentrer.
          {isSketch && " Image montrée : le croquis — le cadrage sera gardé pour la version propre."}
        </p>
        <div
          ref={area}
          className="relative flex h-80 touch-none select-none items-center justify-center overflow-hidden rounded-md bg-zinc-950"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          data-testid="crop-area"
        >
          <div
            ref={frame}
            tabIndex={0}
            role="group"
            aria-label={`Cadre de la case ${panel.index + 1} : zoom ${zoomLabel(shown.zoom)}${crop ? "" : ", centré automatiquement"}`}
            aria-describedby="crop-help"
            onKeyDown={onKeyDown}
            className={`relative cursor-grab focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-sky-400 active:cursor-grabbing`}
            style={{ aspectRatio: `${W} / ${H}`, width: `min(80%, calc(16rem * ${W} / ${H}))` }}
            data-testid="crop-frame"
            data-crop={crop ? `${shown.x.toFixed(3)},${shown.y.toFixed(3)},${shown.zoom.toFixed(3)}` : "auto"}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={engineUrl(imageUrl)}
              alt=""
              draggable={false}
              onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              className={place ? "pointer-events-none absolute max-w-none" : "pointer-events-none h-full w-full object-cover"}
              style={
                place
                  ? { left: `${place.left * 100}%`, top: `${place.top * 100}%`, width: `${place.width * 100}%`, height: `${place.height * 100}%` }
                  : undefined
              }
            />
            {/* Hors de la case : l'image qui dépasse, estompée. */}
            <span aria-hidden className="pointer-events-none absolute inset-0 shadow-[0_0_0_100vmax_rgba(9,9,11,0.7)] ring-2 ring-rose-400" />
            {isSketch && (
              <span className="pointer-events-none absolute left-1 top-1 rounded bg-zinc-950/80 px-1.5 py-0.5 text-[10px] text-zinc-200">croquis</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            className="!px-2 !py-1"
            onClick={() => zoomTo(shown.zoom / 1.1)}
            disabled={!ready || shown.zoom <= 1 + 1e-3}
            aria-label="Dézoomer"
            title="Dézoomer (jamais sous le remplissage de la case)"
            data-testid="crop-zoom-out"
          >
            −
          </Button>
          <input
            type="range"
            min={1}
            max={limit}
            step={0.01}
            value={shown.zoom}
            onChange={(e) => zoomTo(Number(e.target.value))}
            disabled={!ready || limit <= 1}
            aria-label="Zoom"
            aria-valuetext={zoomLabel(shown.zoom)}
            className="min-w-0 flex-1 accent-rose-500"
            data-testid="crop-zoom"
          />
          <Button
            variant="secondary"
            className="!px-2 !py-1"
            onClick={() => zoomTo(shown.zoom * 1.1)}
            disabled={!ready || maxed}
            aria-label={maxed ? "Zoomer — zoom maximal atteint" : "Zoomer"}
            title={maxed ? "Zoom maximal atteint : l'image n'a pas assez de pixels pour aller plus loin" : "Zoomer"}
            data-testid="crop-zoom-in"
          >
            +
          </Button>
          <span className="w-12 text-right text-xs tabular-nums text-zinc-300">{zoomLabel(shown.zoom)}</span>
        </div>
        <p role="status" className="min-h-4 text-xs text-amber-300" data-testid="crop-max">
          {ready && maxed
            ? limit <= 1
              ? "Image trop petite pour cette case : zoom maximal atteint (remplissage)."
              : "Zoom maximal atteint : l'image n'a pas assez de pixels pour aller plus loin."
            : ""}
        </p>
        {error && <Alert>{error}</Alert>}
      </div>
    </Modal>
  );
}
