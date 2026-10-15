"use client";

import { useState } from "react";
import { useConfirm } from "@/components/confirm";
import { Button, Select, Textarea } from "@/components/ui";
import type { PanelData } from "@/lib/api";
import { BUBBLE_KINDS, SHOT_TYPES } from "@/lib/script";

export interface SplitRequest {
  first: string;
  second: string;
  moveBubbleIds: number[];
}

/**
 * Corrections rapides depuis la planche brouillon, sans quitter l'écran : changer le plan (re-croqué), réécrire
 * ou supprimer une réplique ou une onomatopée, couper la case en deux.
 */
export function PanelFixes({
  panel,
  busy,
  locked,
  onShot,
  onReplyText,
  onReplyDelete,
  onSfxDelete,
  onSplit,
}: {
  panel: PanelData;
  busy: boolean;
  /** Case au propre ou en cours de croquis : plan et découpe attendent. */
  locked: boolean;
  onShot: (shot: string | null) => void;
  onReplyText: (bubbleId: number, text: string) => void;
  onReplyDelete: (bubbleId: number) => void;
  onSfxDelete: (bubbleId: number) => void;
  onSplit: (req: SplitRequest) => void;
}) {
  const confirm = useConfirm();
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null);
  const [split, setSplit] = useState<SplitRequest | null>(null);
  const shot = panel.shot_type ?? "";
  const replies = panel.dialogues.filter((d) => d.id !== undefined);
  const sfx = panel.sfx ?? [];

  function openSplit() {
    // Par défaut : la même description des deux côtés, la seconde moitié des répliques dans la nouvelle case.
    const half = Math.ceil(replies.length / 2);
    setSplit({ first: panel.description, second: panel.description, moveBubbleIds: replies.slice(half).map((d) => d.id!) });
  }

  return (
    <section className="space-y-3 border-t border-zinc-800 pt-3" aria-label="Corrections rapides" data-testid="panel-fixes">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="sketch-shot" className="text-sm font-medium text-zinc-300">
          Plan
        </label>
        <Select
          id="sketch-shot"
          className="!w-auto py-1"
          value={shot}
          disabled={busy || locked}
          onChange={(e) => onShot(e.target.value || null)}
          data-testid="sketch-shot"
        >
          <option value="">— aucun —</option>
          {SHOT_TYPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
          {shot && !(SHOT_TYPES as readonly string[]).includes(shot) && <option value={shot}>{shot}</option>}
        </Select>
        <span className="text-[11px] text-zinc-500">changer le plan re-croque la case</span>
      </div>

      <div className="space-y-1.5">
        <h3 className="text-sm font-medium text-zinc-300">
          Répliques{replies.length ? ` (${replies.length})` : ""}
        </h3>
        {!replies.length && !sfx.length && <p className="text-xs text-zinc-500">Aucune réplique dans cette case.</p>}
        <ul className="space-y-1.5" data-testid="sketch-replies">
          {replies.map((d) => {
            const draft = editing?.id === d.id ? editing : null;
            return (
            <li key={d.id} className="rounded-md border border-zinc-800 bg-zinc-950/40 p-2 text-sm" data-testid="sketch-reply">
              <p className="text-[11px] text-zinc-500">
                {d.speaker || "—"} · {BUBBLE_KINDS[d.kind] ?? d.kind}
              </p>
              {draft ? (
                <div className="mt-1 space-y-1.5">
                  <label htmlFor={`reply-${d.id}`} className="sr-only">
                    Texte de la réplique
                  </label>
                  <Textarea
                    id={`reply-${d.id}`}
                    rows={2}
                    value={draft.text}
                    autoFocus
                    onChange={(e) => setEditing({ id: d.id!, text: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                        e.preventDefault();
                        if (draft.text.trim()) onReplyText(d.id!, draft.text.trim());
                        setEditing(null);
                      } else if (e.key === "Escape") {
                        e.preventDefault();
                        setEditing(null);
                      }
                    }}
                  />
                  <div className="flex gap-2">
                    <Button
                      className="!py-1 text-xs"
                      disabled={busy || !draft.text.trim()}
                      onClick={() => {
                        onReplyText(d.id!, draft.text.trim());
                        setEditing(null);
                      }}
                      data-testid="reply-save"
                    >
                      Enregistrer
                    </Button>
                    <Button variant="ghost" className="!py-1 text-xs" onClick={() => setEditing(null)}>
                      Annuler
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 whitespace-pre-line text-zinc-100">{d.text}</p>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      variant="ghost"
                      className="!px-2 !py-0.5 text-xs"
                      disabled={busy}
                      onClick={() => setEditing({ id: d.id!, text: d.text })}
                      data-testid="reply-edit"
                    >
                      Réécrire
                    </Button>
                    <Button
                      variant="ghost"
                      className="!px-2 !py-0.5 text-xs text-red-300"
                      disabled={busy}
                      onClick={async () => {
                        if (
                          await confirm({
                            title: "Supprimer la réplique ?",
                            message: `« ${d.text} » disparaît de la case ${panel.index + 1}.`,
                            confirmLabel: "Supprimer",
                            danger: true,
                          })
                        )
                          onReplyDelete(d.id!);
                      }}
                      data-testid="reply-delete"
                    >
                      Supprimer
                    </Button>
                  </div>
                </div>
              )}
            </li>
            );
          })}
          {sfx.map((fx) => (
            <li key={`sfx-${fx.id}`} className="flex items-center justify-between gap-2 rounded-md border border-zinc-800 bg-zinc-950/40 p-2 text-sm">
              <p className="min-w-0">
                <span className="text-[11px] text-zinc-500">Onomatopée · </span>
                <span className="font-semibold text-zinc-100">{fx.text}</span>
              </p>
              <Button
                variant="ghost"
                className="!px-2 !py-0.5 text-xs text-red-300"
                disabled={busy}
                onClick={() => onSfxDelete(fx.id)}
                data-testid="sfx-delete"
              >
                Supprimer
              </Button>
            </li>
          ))}
        </ul>
      </div>

      {split === null ? (
        <Button variant="secondary" onClick={openSplit} disabled={busy || locked} data-testid="split-open">
          Couper la case en deux
        </Button>
      ) : (
        <div className="space-y-2 rounded-md border border-zinc-700 p-3" data-testid="split-form">
          <p className="text-sm font-medium text-zinc-200">Couper la case {panel.index + 1} en deux</p>
          <p className="text-[11px] text-zinc-500">
            La nouvelle case suit juste après ; la page est remise en page et seules ces deux cases sont re-croquées.
          </p>
          <label htmlFor="split-first" className="text-xs font-medium text-zinc-300">
            Case {panel.index + 1}
          </label>
          <Textarea id="split-first" rows={2} value={split.first} onChange={(e) => setSplit({ ...split, first: e.target.value })} />
          <label htmlFor="split-second" className="text-xs font-medium text-zinc-300">
            Nouvelle case {panel.index + 2}
          </label>
          <Textarea
            id="split-second"
            rows={2}
            value={split.second}
            onChange={(e) => setSplit({ ...split, second: e.target.value })}
            data-testid="split-second"
          />
          {replies.length > 0 && (
            <fieldset className="space-y-1">
              <legend className="text-xs font-medium text-zinc-300">Répliques qui passent dans la nouvelle case</legend>
              {replies.map((d) => (
                <label key={d.id} className="flex items-start gap-2 text-xs text-zinc-300">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={split.moveBubbleIds.includes(d.id!)}
                    onChange={(e) =>
                      setSplit({
                        ...split,
                        moveBubbleIds: e.target.checked
                          ? [...split.moveBubbleIds, d.id!]
                          : split.moveBubbleIds.filter((id) => id !== d.id),
                      })
                    }
                  />
                  <span>{d.text}</span>
                </label>
              ))}
            </fieldset>
          )}
          <div className="flex gap-2">
            <Button
              disabled={busy || !split.first.trim() || !split.second.trim()}
              onClick={() => {
                onSplit(split);
                setSplit(null);
              }}
              data-testid="split-submit"
            >
              Couper et re-croquer
            </Button>
            <Button variant="ghost" onClick={() => setSplit(null)}>
              Annuler
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
