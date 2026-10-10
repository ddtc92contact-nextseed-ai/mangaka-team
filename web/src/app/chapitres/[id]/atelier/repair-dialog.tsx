"use client";

import { useRef, useState, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import { Modal } from "@/components/modal";
import { InfoTip } from "@/components/info-tip";
import { Alert, Button, Field, Loading, Select, Textarea } from "@/components/ui";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type DetectionBox,
  type Job,
  type PanelImage,
  type RepairRegion,
  type RepairTarget,
} from "@/lib/api";
import type { HelpId } from "@/lib/help";
import { useEngineData } from "@/lib/hooks";

/** Détection du QC à présélectionner (« Réparer cette main »). */
export interface RepairPreset {
  kind: "faces" | "hands";
  index: number;
}

type Tool = "rect" | "brush" | "erase";

interface Zone {
  key: string; // « faces-0 », « hands-1 », « rect-3 »
  box: RepairRegion;
}

export const REPAIR_TARGETS: Record<RepairTarget, string> = { face: "Visage", hand: "Main", zone: "Zone libre" };
const KIND_TARGET = { faces: "face", hands: "hand" } as const;
const KIND_NAME = { faces: "Visage", hands: "Main" } as const;
const TOOLS: { id: Tool; label: string }[] = [
  { id: "rect", label: "Rectangle" },
  { id: "brush", label: "Pinceau" },
  { id: "erase", label: "Gomme" },
];

/** Vrai pour une version du palier croquis : la réparation ne s'applique qu'aux versions propres. */
export function isSketch(img: PanelImage): boolean {
  const p = img.params;
  const kind = String(p.kind ?? "").toLowerCase();
  const tier = (img.tier ?? "").toLowerCase();
  return img.kind === "croquis" || kind === "croquis" || kind === "sketch" || tier === "croquis" || Boolean(p.sketch);
}

function plainBox(b: DetectionBox | RepairRegion): RepairRegion {
  return { x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 };
}

/**
 * Réparation ciblée d'une version : zone choisie depuis les détections du QC, au rectangle ou au
 * pinceau ; marge, bords fondus, débruitage et prompt (prérempli) réglables. Échap annule,
 * Ctrl + Entrée lance la réparation (nouvelle version, la version choisie ne bouge pas).
 */
export function RepairDialog({
  image,
  preset,
  onClose,
  onQueued,
}: {
  image: PanelImage;
  preset?: RepairPreset;
  onClose: () => void;
  onQueued: (jobs: Job[]) => void;
}) {
  const det = image.detections;
  const initialBox = preset && det ? det[preset.kind][preset.index] : undefined;
  const [zones, setZones] = useState<Zone[]>(
    initialBox && preset ? [{ key: `${preset.kind}-${preset.index}`, box: plainBox(initialBox) }] : [],
  );
  const [target, setTarget] = useState<RepairTarget>(preset ? KIND_TARGET[preset.kind] : "zone");
  const [character, setCharacter] = useState<number | "auto" | "none">("auto");
  const [promptDraft, setPromptDraft] = useState<string | null>(null);
  const [grow, setGrow] = useState<number | null>(null);
  const [feather, setFeather] = useState<number | null>(null);
  const [denoise, setDenoise] = useState<number | null>(null);
  const [tool, setTool] = useState<Tool>("rect");
  const [brush, setBrush] = useState(40);
  const [painted, setPainted] = useState(false);
  const [draft, setDraft] = useState<RepairRegion | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(
    image.width && image.height ? { w: image.width, h: image.height } : det ? { w: det.width, h: det.height } : null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const info = useEngineData(() => api.getRepairInfo(image.id, target, character), [image.id, target, character]);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const counter = useRef(0);

  const i = info.data;
  const prompt = promptDraft ?? i?.prompt ?? "";
  const growPx = grow ?? i?.grow_px ?? 0;
  const featherPx = feather ?? i?.feather_px ?? 0;
  const denoiseValue = denoise ?? i?.denoise ?? 0.45;
  const effectiveCharacter = i?.character_id ?? null;
  const hasZone = zones.length > 0 || painted;
  const w = natural?.w ?? 1;
  const h = natural?.h ?? 1;

  function toImage(e: PointerEvent<HTMLDivElement>): { x: number; y: number } {
    const r = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(w, ((e.clientX - r.left) / r.width) * w)),
      y: Math.max(0, Math.min(h, ((e.clientY - r.top) / r.height) * h)),
    };
  }

  function paint(from: { x: number; y: number }, to: { x: number; y: number }) {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    ctx.globalCompositeOperation = tool === "erase" ? "destination-out" : "source-over";
    ctx.strokeStyle = "#f43f5e"; // seule l'opacité compte pour le masque envoyé
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = brush;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    if (tool === "brush") setPainted(true);
  }

  function down(e: PointerEvent<HTMLDivElement>) {
    if (!natural) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = toImage(e);
    drag.current = p;
    if (tool === "rect") setDraft({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
    else paint(p, p);
  }
  function move(e: PointerEvent<HTMLDivElement>) {
    const start = drag.current;
    if (!start) return;
    const p = toImage(e);
    if (tool === "rect") setDraft({ x1: start.x, y1: start.y, x2: p.x, y2: p.y });
    else {
      paint(start, p);
      drag.current = p;
    }
  }
  function up() {
    if (tool === "rect" && draft) {
      const box = {
        x1: Math.min(draft.x1, draft.x2),
        y1: Math.min(draft.y1, draft.y2),
        x2: Math.max(draft.x1, draft.x2),
        y2: Math.max(draft.y1, draft.y2),
      };
      if (box.x2 - box.x1 >= 4 && box.y2 - box.y1 >= 4) {
        counter.current += 1;
        setZones((z) => [...z, { key: `rect-${counter.current}`, box }]);
      }
    }
    setDraft(null);
    drag.current = null;
  }

  function toggleDetection(kind: "faces" | "hands", index: number, box: DetectionBox) {
    const key = `${kind}-${index}`;
    const on = zones.some((z) => z.key === key);
    setZones((z) => (on ? z.filter((x) => x.key !== key) : [...z, { key, box: plainBox(box) }]));
    if (!on && zones.length === 0 && !painted) {
      setTarget(KIND_TARGET[kind]);
      setPromptDraft(null);
    }
  }

  function clearAll() {
    setZones([]);
    setPainted(false);
    const c = canvas.current;
    c?.getContext("2d")?.clearRect(0, 0, c.width, c.height);
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (busy || !i?.available) return;
    if (!hasZone) {
      setError("Choisis une zone : une détection du QC, un rectangle ou un coup de pinceau.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const jobs = await api.repairPanelImage(image.id, {
        regions: zones.map((z) => z.box),
        mask_png: painted && canvas.current ? canvas.current.toDataURL("image/png") : null,
        target,
        character_id: effectiveCharacter,
        prompt,
        grow_px: growPx,
        feather_px: featherPx,
        denoise: denoiseValue,
      });
      onQueued(jobs);
    } catch (err) {
      setError(fullErrorMessage(err));
      setBusy(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void submit();
    }
  }

  const margin = growPx + featherPx;
  const detectionButtons = det
    ? (["faces", "hands"] as const).flatMap((kind) =>
        det[kind].map((b, index) => ({ kind, index, box: b, key: `${kind}-${index}` })),
      )
    : [];

  return (
    <Modal
      open
      onClose={onClose}
      size="xl"
      title={`Réparer une zone — version ${image.version}`}
      footer={
        <>
          <p className="mr-auto self-center text-[11px] text-zinc-500">Échap : annuler · Ctrl + Entrée : réparer</p>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Annuler
          </Button>
          <Button type="submit" form="repair-form" disabled={busy || !i?.available || !hasZone} data-testid="repair-submit">
            {busy ? "Mise en file…" : "Réparer"}
          </Button>
        </>
      }
    >
      <form id="repair-form" onSubmit={submit} onKeyDown={onKeyDown} className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-2">
          <div role="group" aria-label="Outil de sélection" className="flex flex-wrap items-center gap-1">
            {TOOLS.map((t) => (
              <button
                key={t.id}
                type="button"
                aria-pressed={tool === t.id}
                onClick={() => setTool(t.id)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium focus-visible:outline-2 focus-visible:outline-rose-400 ${
                  tool === t.id ? "bg-rose-500 text-white" : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                }`}
              >
                {t.label}
              </button>
            ))}
            {tool !== "rect" && (
              <label className="ml-2 flex items-center gap-1.5 text-xs text-zinc-400">
                Taille
                <input
                  type="range"
                  min={8}
                  max={200}
                  value={brush}
                  onChange={(e) => setBrush(Number(e.target.value))}
                  className="w-24 accent-rose-500"
                />
                <span className="w-12 tabular-nums">{brush} px</span>
              </label>
            )}
            <Button variant="ghost" type="button" className="ml-auto !px-2 !py-1 text-xs" onClick={clearAll} disabled={!hasZone}>
              Tout effacer
            </Button>
          </div>
          <div className="relative mx-auto w-full overflow-hidden rounded-md bg-zinc-950" style={{ maxWidth: `min(100%, calc(60vh * ${w / h}))` }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={engineUrl(image.url)}
              alt={`Version ${image.version} à réparer`}
              className="block w-full select-none"
              draggable={false}
              onLoad={(e) => {
                const el = e.currentTarget;
                if (!natural) setNatural({ w: el.naturalWidth, h: el.naturalHeight });
              }}
              data-testid="repair-image"
            />
            {natural && (
              <canvas
                ref={canvas}
                width={natural.w}
                height={natural.h}
                className="pointer-events-none absolute inset-0 h-full w-full opacity-50"
                aria-hidden
              />
            )}
            <svg
              className="pointer-events-none absolute inset-0 h-full w-full"
              viewBox={`0 0 ${w} ${h}`}
              preserveAspectRatio="none"
              aria-hidden
            >
              {detectionButtons.map((d) => {
                const on = zones.some((z) => z.key === d.key);
                return on ? null : (
                  <rect
                    key={d.key}
                    x={d.box.x1}
                    y={d.box.y1}
                    width={Math.max(1, d.box.x2 - d.box.x1)}
                    height={Math.max(1, d.box.y2 - d.box.y1)}
                    fill="none"
                    stroke={d.kind === "faces" ? "#34d399" : "#60a5fa"}
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
              {zones.map((z) => (
                <g key={z.key}>
                  <rect
                    x={z.box.x1 - margin}
                    y={z.box.y1 - margin}
                    width={z.box.x2 - z.box.x1 + 2 * margin}
                    height={z.box.y2 - z.box.y1 + 2 * margin}
                    fill="none"
                    stroke="#fda4af"
                    strokeWidth={1}
                    strokeDasharray="4 3"
                    vectorEffect="non-scaling-stroke"
                  />
                  <rect
                    x={z.box.x1}
                    y={z.box.y1}
                    width={z.box.x2 - z.box.x1}
                    height={z.box.y2 - z.box.y1}
                    fill="rgba(244,63,94,0.35)"
                    stroke="#f43f5e"
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                  />
                </g>
              ))}
              {draft && (
                <rect
                  x={Math.min(draft.x1, draft.x2)}
                  y={Math.min(draft.y1, draft.y2)}
                  width={Math.abs(draft.x2 - draft.x1)}
                  height={Math.abs(draft.y2 - draft.y1)}
                  fill="rgba(244,63,94,0.2)"
                  stroke="#f43f5e"
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </svg>
            <div
              className={`absolute inset-0 touch-none ${tool === "rect" ? "cursor-crosshair" : "cursor-cell"}`}
              onPointerDown={down}
              onPointerMove={move}
              onPointerUp={up}
              onPointerCancel={up}
              aria-hidden
              data-testid="repair-surface"
            />
          </div>
          <p className="text-[11px] text-zinc-500">
            Zone en rose ; pointillés clairs : marge + bords fondus. Hors de cette limite, l&apos;image reste identique au pixel près.
          </p>
        </div>

        <div className="space-y-4 text-sm">
          {info.loading && !i ? (
            <Loading />
          ) : info.error && !i ? (
            <Alert>Impossible de préparer la réparation : {info.error}</Alert>
          ) : i && !i.available ? (
            <Alert>{i.problem ?? "Réparation impossible pour cette version."}</Alert>
          ) : null}

          <div className="space-y-1.5">
            <span className="flex items-center gap-1.5 text-sm font-medium text-zinc-300">
              Détections du QC
              <InfoTip help="atelier.repair" label="Réparer une zone" />
            </span>
            {detectionButtons.length === 0 ? (
              <p className="text-xs text-zinc-500">
                {det ? "Aucun visage ni main détecté." : "Pas de détections pour cette version (lance le QC) : trace la zone à la main."}
              </p>
            ) : (
              <ul className="flex flex-wrap gap-1.5" data-testid="repair-detections">
                {detectionButtons.map((d) => {
                  const on = zones.some((z) => z.key === d.key);
                  return (
                    <li key={d.key}>
                      <button
                        type="button"
                        aria-pressed={on}
                        onClick={() => toggleDetection(d.kind, d.index, d.box)}
                        className={`rounded px-2 py-1 text-xs focus-visible:outline-2 focus-visible:outline-rose-400 ${
                          on ? "bg-rose-500 text-white" : d.kind === "faces" ? "bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25" : "bg-sky-500/15 text-sky-200 hover:bg-sky-500/25"
                        }`}
                        title={`Confiance ${d.box.score.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}`}
                      >
                        {KIND_NAME[d.kind]} {d.index + 1}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Zone" htmlFor="repair-target">
              <Select
                id="repair-target"
                value={target}
                onChange={(e) => {
                  setTarget(e.target.value as RepairTarget);
                  setPromptDraft(null);
                }}
              >
                {(Object.keys(REPAIR_TARGETS) as RepairTarget[]).map((t) => (
                  <option key={t} value={t}>
                    {REPAIR_TARGETS[t]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Personnage concerné" htmlFor="repair-character">
              <Select
                id="repair-character"
                value={character === "auto" ? String(effectiveCharacter ?? "none") : String(character)}
                onChange={(e) => {
                  setCharacter(e.target.value === "none" ? "none" : Number(e.target.value));
                  setPromptDraft(null);
                }}
                disabled={!i}
              >
                <option value="none">Aucun en particulier</option>
                {(i?.characters ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Slider id="repair-grow" label="Marge autour de la zone" help="atelier.repair_grow" value={growPx} min={0} max={128} step={2} unit="px" onChange={setGrow} />
          <Slider id="repair-feather" label="Bords fondus" help="atelier.repair_feather" value={featherPx} min={0} max={64} step={2} unit="px" onChange={setFeather} />
          <Slider
            id="repair-denoise"
            label="Force de la retouche (denoise)"
            help="atelier.repair_denoise"
            value={denoiseValue}
            min={0.1}
            max={0.9}
            step={0.05}
            onChange={setDenoise}
            hint="0,3 : retouche légère · 0,6 : la zone est redessinée franchement"
          />

          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <label htmlFor="repair-prompt" className="text-sm font-medium text-zinc-300">
                Prompt de réparation
              </label>
              {promptDraft !== null && (
                <button type="button" onClick={() => setPromptDraft(null)} className="text-xs text-zinc-400 underline-offset-2 hover:text-zinc-100 hover:underline">
                  Revenir au prompt proposé
                </button>
              )}
            </div>
            <Textarea
              id="repair-prompt"
              value={prompt}
              onChange={(e) => setPromptDraft(e.target.value)}
              rows={5}
              className="text-xs leading-relaxed"
              placeholder={info.loading ? "Préparation du prompt…" : "Décris ce qui doit apparaître dans la zone"}
            />
          </div>

          {i?.preset_name && (
            <p className="text-[11px] text-zinc-500">
              Workflow : {i.preset_name}. Le résultat devient une nouvelle version (contrôlée par le QC) ; la version choisie ne change pas.
            </p>
          )}
          {error && <Alert>{error}</Alert>}
        </div>
      </form>
    </Modal>
  );
}

function Slider({
  id,
  label,
  value,
  min,
  max,
  step,
  unit,
  hint,
  help,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  hint?: string;
  help?: HelpId;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-1.5">
          <label htmlFor={id} className="font-medium text-zinc-300">
            {label}
          </label>
          {help && <InfoTip help={help} label={label} />}
        </span>
        <span className="tabular-nums text-xs text-zinc-400">
          {value.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}
          {unit ? ` ${unit}` : ""}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-rose-500"
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-[11px] text-zinc-500">
          {hint}
        </p>
      )}
    </div>
  );
}
