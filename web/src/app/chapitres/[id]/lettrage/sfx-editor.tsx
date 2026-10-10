"use client";

import { useState, type FormEvent } from "react";
import { HelpLabel } from "@/components/info-tip";
import { Alert, Button, Card, Field, Input, Select } from "@/components/ui";
import type { BubbleUpdate, Intensity, LetteredSfx, LetteringWarning, PageLettering } from "@/lib/api";
import { INTENSITIES } from "@/lib/layout";

export const SFX_INTENSITIES: Record<Intensity, string> = {
  calme: "Calme (petite)",
  normal: "Normale",
  choc: "Choc (énorme)",
};

/** Panneau d'édition de l'onomatopée choisie : texte, intensité, police, taille, angle, italique. */
export function SfxEditor({
  sfx,
  fonts,
  warnings,
  busy,
  onSave,
  onDelete,
  onClose,
}: {
  sfx: LetteredSfx;
  fonts: NonNullable<PageLettering["sfx_fonts"]>;
  warnings: LetteringWarning[];
  busy: boolean;
  onSave: (update: BubbleUpdate) => Promise<boolean>;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(sfx.text);
  const [intensity, setIntensity] = useState<Intensity>(sfx.intensity);
  const [font, setFont] = useState(sfx.font.id);
  const [size, setSize] = useState(String(sfx.font.size_pt));
  const [angle, setAngle] = useState(String(sfx.angle));
  const [skew, setSkew] = useState(String(sfx.skew));
  const mine = warnings.filter((w) => w.bubble_id === sfx.id);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    const body: BubbleUpdate = { sfx: {} };
    if (text.trim() !== sfx.text) body.text = text.trim();
    if (intensity !== sfx.intensity) body.sfx!.intensity = intensity;
    if (font !== sfx.font.id) body.sfx!.font = font;
    const n = (v: string) => Number(v.replace(",", "."));
    if (Number.isFinite(n(size)) && n(size) !== sfx.font.size_pt) body.sfx!.size_pt = n(size);
    if (Number.isFinite(n(angle)) && n(angle) !== sfx.angle) body.sfx!.angle = n(angle);
    if (Number.isFinite(n(skew)) && n(skew) !== sfx.skew) body.sfx!.skew = n(skew);
    await onSave(body);
  }

  const rotate = (delta: number) => onSave({ sfx: { angle: Math.round((sfx.angle + delta) * 10) / 10 } });
  const auto = sfx.manual || sfx.manual_size || sfx.manual_angle || sfx.manual_skew;

  return (
    <Card className="space-y-4" data-testid="sfx-editor">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold text-zinc-100">Onomatopée « {sfx.text} »</h2>
          <p className="text-xs text-zinc-500">
            {fonts[sfx.font.id]?.name ?? sfx.font.id} · {sfx.font.size_pt.toLocaleString("fr-FR")} pt ·{" "}
            {sfx.angle.toLocaleString("fr-FR")}° · {INTENSITIES[sfx.intensity].toLowerCase()} ·{" "}
            {sfx.manual ? "placée à la main" : "placement automatique"}
            {sfx.overflow_px > 0 ? " · déborde de la case" : ""}
          </p>
        </div>
        <Button variant="ghost" className="!px-2 !py-1" onClick={onClose} aria-label="Fermer l'éditeur d'onomatopée">
          ✕
        </Button>
      </div>
      {mine.map((w, i) => (
        <Alert key={i}>{w.message}</Alert>
      ))}
      <form onSubmit={submit} className="space-y-3">
        <Field label="Texte" htmlFor="sfx-text" hint="Écrit en majuscules sur la planche ; jamais dessiné par le modèle d'image.">
          <Input id="sfx-text" value={text} onChange={(e) => setText(e.target.value)} maxLength={60} required data-testid="sfx-text" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Intensité" htmlFor="sfx-intensity" help="lettrage.sfx_intensity">
            <Select id="sfx-intensity" value={intensity} onChange={(e) => setIntensity(e.target.value as Intensity)}>
              {(Object.keys(SFX_INTENSITIES) as Intensity[]).map((k) => (
                <option key={k} value={k}>
                  {SFX_INTENSITIES[k]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Police" htmlFor="sfx-font">
            <Select id="sfx-font" value={font} onChange={(e) => setFont(e.target.value)}>
              {Object.entries(fonts).map(([id, f]) => (
                <option key={id} value={id}>
                  {f.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Taille (pt)" htmlFor="sfx-size">
            <Input id="sfx-size" type="number" min={6} max={300} step={0.5} value={size} onChange={(e) => setSize(e.target.value)} data-testid="sfx-size" />
          </Field>
          <Field label="Angle (°)" htmlFor="sfx-angle">
            <Input id="sfx-angle" type="number" min={-180} max={180} step={0.5} value={angle} onChange={(e) => setAngle(e.target.value)} data-testid="sfx-angle" />
          </Field>
          <Field label="Italique (°)" htmlFor="sfx-skew" help="lettrage.sfx_skew">
            <Input id="sfx-skew" type="number" min={-45} max={45} step={0.5} value={skew} onChange={(e) => setSkew(e.target.value)} />
          </Field>
        </div>
        <Button type="submit" disabled={busy || !text.trim()} data-testid="sfx-save">
          Appliquer
        </Button>
      </form>

      <div className="space-y-2 border-t border-zinc-800 pt-3">
        <p className="text-xs text-zinc-400">
          Sur la planche : glisse l&apos;onomatopée pour la déplacer, le rond bleu pour la tourner, le carré rose pour
          la redimensionner. Au clavier : flèches (Maj : ×5), Alt + ←/→ pour tourner, Alt + ↑/↓ pour la taille.
        </p>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Rotation">
          <Button variant="secondary" className="!px-2.5 !py-1" disabled={busy} onClick={() => rotate(-5)} data-testid="sfx-rotate-left">
            ↺ −5°
          </Button>
          <Button variant="secondary" className="!px-2.5 !py-1" disabled={busy} onClick={() => rotate(5)} data-testid="sfx-rotate-right">
            ↻ +5°
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" disabled={busy || !auto} onClick={() => onSave({ sfx: null })} data-testid="sfx-auto">
            Replacer automatiquement
          </Button>
          <Button variant="danger" disabled={busy} onClick={onDelete} data-testid="sfx-delete">
            Supprimer
          </Button>
        </div>
      </div>
    </Card>
  );
}

/** Ajout d'une onomatopée dans une case de la page (placement automatique). */
export function AddSfx({
  panels,
  busy,
  onAdd,
}: {
  panels: PageLettering["panels"];
  busy: boolean;
  onAdd: (panelId: number, text: string, intensity: Intensity) => Promise<boolean>;
}) {
  const ordered = [...panels].sort((a, b) => a.index - b.index);
  const [text, setText] = useState("");
  const [panelId, setPanelId] = useState<number | null>(ordered[0]?.id ?? null);
  const [intensity, setIntensity] = useState<Intensity>("normal");
  const target = ordered.find((p) => p.id === panelId) ?? ordered[0];

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim() || !target) return;
    if (await onAdd(target.id, text.trim(), intensity)) setText("");
  }

  return (
    <Card data-testid="add-sfx-card">
      <h2 className="mb-2 font-semibold text-zinc-100">
        <HelpLabel help="lettrage.sfx">Onomatopées</HelpLabel>
      </h2>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Texte" htmlFor="new-sfx-text" hint="« CLIC », « BIIIP ! », « VROUM ! » : lettrage hors bulle, peut déborder de la case.">
          <Input id="new-sfx-text" value={text} onChange={(e) => setText(e.target.value)} maxLength={60} placeholder="VROUM !" data-testid="new-sfx-text" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Case" htmlFor="new-sfx-panel">
            <Select id="new-sfx-panel" value={target?.id ?? ""} onChange={(e) => setPanelId(Number(e.target.value))} data-testid="new-sfx-panel">
              {ordered.map((p) => (
                <option key={p.id} value={p.id}>
                  Case {p.index + 1}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Intensité" htmlFor="new-sfx-intensity" help="lettrage.sfx_intensity">
            <Select id="new-sfx-intensity" value={intensity} onChange={(e) => setIntensity(e.target.value as Intensity)}>
              {(Object.keys(SFX_INTENSITIES) as Intensity[]).map((k) => (
                <option key={k} value={k}>
                  {SFX_INTENSITIES[k]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Button type="submit" disabled={busy || !text.trim() || !target} data-testid="add-sfx">
          Ajouter l&apos;onomatopée
        </Button>
      </form>
    </Card>
  );
}
