"use client";

import { useState, type FormEvent } from "react";
import { Alert, Button, Card, Field, Input, Select, Textarea } from "@/components/ui";
import type { BubbleKind, BubbleUpdate, LetteredBubble, LetteringWarning } from "@/lib/api";
import { BUBBLE_KINDS } from "@/lib/script";

const TAIL_STEP = 24; // ≈ 2 mm à 300 DPI

/** Panneau d'édition de la bulle choisie : texte, type, locuteur, position automatique, queue. */
export function BubbleEditor({
  bubble,
  index,
  warnings,
  busy,
  onSave,
  onClose,
}: {
  bubble: LetteredBubble;
  index: number;
  warnings: LetteringWarning[];
  busy: boolean;
  onSave: (update: BubbleUpdate) => Promise<boolean>;
  onClose: () => void;
}) {
  const [text, setText] = useState(bubble.text);
  const [kind, setKind] = useState<BubbleKind>(bubble.kind);
  const [speaker, setSpeaker] = useState(bubble.speaker);
  const dirty = text.trim() !== bubble.text || kind !== bubble.kind || speaker.trim() !== bubble.speaker;
  const mine = warnings.filter((w) => w.bubble_id === bubble.id);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    await onSave({ text: text.trim(), kind, speaker: speaker.trim() });
  }

  function nudgeTail(dx: number, dy: number) {
    if (!bubble.tail) return;
    onSave({ tail: { x: bubble.tail.x + dx * TAIL_STEP, y: bubble.tail.y + dy * TAIL_STEP } });
  }

  return (
    <Card className="space-y-4" data-testid="bubble-editor">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold text-zinc-100">Bulle {index + 1}</h2>
          <p className="text-xs text-zinc-500">
            {BUBBLE_KINDS[bubble.kind]} · {bubble.font.size_pt.toLocaleString("fr-FR")} pt ·{" "}
            {bubble.manual ? "cadre ajusté à la main" : "placement automatique"}
            {bubble.manual_tail ? " · queue ajustée" : ""}
          </p>
        </div>
        <Button variant="ghost" className="!px-2 !py-1" onClick={onClose} aria-label="Fermer l'éditeur de bulle">
          ✕
        </Button>
      </div>
      {mine.map((w, i) => (
        <Alert key={i}>{w.message}</Alert>
      ))}
      <form onSubmit={submit} className="space-y-3">
        <Field label="Texte" htmlFor="bubble-text" hint="Accents et « guillemets » français : espaces insécables posées automatiquement.">
          <Textarea
            id="bubble-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={1000}
            required
            autoFocus
            data-testid="bubble-text"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type" htmlFor="bubble-kind">
            <Select id="bubble-kind" value={kind} onChange={(e) => setKind(e.target.value as BubbleKind)} data-testid="bubble-kind">
              {(Object.keys(BUBBLE_KINDS) as BubbleKind[]).map((k) => (
                <option key={k} value={k}>
                  {BUBBLE_KINDS[k]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Locuteur" htmlFor="bubble-speaker">
            <Input id="bubble-speaker" value={speaker} onChange={(e) => setSpeaker(e.target.value)} maxLength={120} />
          </Field>
        </div>
        <Button type="submit" disabled={busy || !dirty || !text.trim()} data-testid="bubble-save">
          Appliquer
        </Button>
      </form>

      <div className="space-y-2 border-t border-zinc-800 pt-3">
        <p className="text-xs text-zinc-400">
          Sur la planche : glisse la bulle pour la déplacer, le carré rose pour la redimensionner, le rond bleu pour
          orienter la queue. Au clavier : flèches (Maj : ×5), Alt + flèches pour la taille.
        </p>
        {bubble.tail && bubble.kind !== "narration" && (
          <div className="flex items-center gap-2" role="group" aria-label="Pointe de la queue">
            <span className="text-xs text-zinc-400">Queue :</span>
            {(
              [
                ["←", -1, 0, "vers la gauche"],
                ["↑", 0, -1, "vers le haut"],
                ["↓", 0, 1, "vers le bas"],
                ["→", 1, 0, "vers la droite"],
              ] as const
            ).map(([label, dx, dy, name]) => (
              <Button
                key={label}
                variant="secondary"
                className="!px-2.5 !py-1"
                disabled={busy}
                onClick={() => nudgeTail(dx, dy)}
                aria-label={`Déplacer la pointe de la queue ${name}`}
              >
                {label}
              </Button>
            ))}
          </div>
        )}
        <Button
          variant="ghost"
          disabled={busy || (!bubble.manual && !bubble.manual_tail)}
          onClick={() => onSave({ position: null, tail: null })}
          data-testid="bubble-auto"
        >
          Replacer automatiquement
        </Button>
      </div>
    </Card>
  );
}
