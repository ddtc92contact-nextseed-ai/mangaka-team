"use client";

import { useState } from "react";
import { Select } from "@/components/ui";
import { api, fullErrorMessage, type PanelDetail } from "@/lib/api";
import {
  VIEWPOINT_HELP,
  VIEWPOINT_LABELS,
  VIEWPOINT_SOURCES,
  moveInFrame,
  moveOffscreen,
  viewpointSpectators,
  viewpointSummary,
  type Cast,
  type ViewpointMode,
} from "@/lib/framing";

const CHIP = "inline-flex items-center gap-1 rounded px-2 py-0.5";
const MOVE =
  "rounded px-1 text-[11px] leading-4 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-100 focus-visible:outline-2 focus-visible:outline-rose-400 disabled:opacity-40";

/**
 * Qui est dans l'image : personnages présents (dessinés, avec leur référence) et cités hors cadre (jamais
 * dessinés), et, quand le texte met un personnage en spectateur, le choix « plan de réaction » ou « vue
 * subjective ». Chaque correction est enregistrée tout de suite et reconstruit le prompt de la case.
 */
export function CastBlock({ detail, onSaved }: { detail: PanelDetail; onSaved: (d: PanelDetail) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cast: Cast = { characters: detail.characters, offscreen: detail.offscreen_characters ?? [] };
  const viewpoint = detail.viewpoint ?? null;
  const hints = detail.spectator_hints ?? [];
  const spectators = viewpointSpectators(viewpoint, hints);
  const unmatched = new Set(detail.unmatched_characters);

  async function save(body: Parameters<typeof api.updatePanel>[1]) {
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.updatePanel(detail.id, body));
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function saveCast(next: Cast) {
    void save({ characters: next.characters, offscreen_characters: next.offscreen });
  }

  function chooseViewpoint(value: string) {
    if (value === "") void save({ viewpoint: null });
    else void save({ viewpoint: { mode: value as ViewpointMode, spectators } });
  }

  return (
    <div className="space-y-1.5 text-xs" data-testid="panel-cast">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-zinc-500">Dans l&apos;image :</span>
        {cast.characters.length ? (
          cast.characters.map((c) => (
            <span
              key={c}
              className={`${CHIP} ${unmatched.has(c) ? "bg-amber-500/20 text-amber-200" : "bg-violet-500/15 text-violet-200"}`}
              title={unmatched.has(c) ? "Aucune fiche personnage : ni référence, ni description, ni LoRA" : undefined}
            >
              {unmatched.has(c) ? `⚠ ${c}` : c}
              <button
                type="button"
                className={MOVE}
                disabled={busy}
                onClick={() => saveCast(moveOffscreen(cast, c))}
                aria-label={`Sortir ${c} du cadre`}
                title="Sortir du cadre : cité, mais ni dessiné ni image de référence"
              >
                ↗
              </button>
            </span>
          ))
        ) : (
          <span className="text-zinc-400">aucun personnage (décor, objet, foule anonyme)</span>
        )}
      </div>
      {cast.offscreen.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-zinc-500">Hors cadre :</span>
          {cast.offscreen.map((c) => (
            <span key={c} className={`${CHIP} border border-dashed border-zinc-600 text-zinc-400`}>
              {c}
              <button
                type="button"
                className={MOVE}
                disabled={busy}
                onClick={() => saveCast(moveInFrame(cast, c))}
                aria-label={`Remettre ${c} dans l'image`}
                title="Remettre dans l'image : dessiné, avec son image de référence"
              >
                ↙
              </button>
            </span>
          ))}
        </div>
      )}
      {(viewpoint || hints.length > 0) && (
        <div className="space-y-1 rounded-md border border-zinc-800 bg-zinc-950/60 p-2">
          <label htmlFor={`viewpoint-${detail.id}`} className="block text-zinc-400">
            Point de vue
            {hints.length > 0 && detail.perception && (
              <span className="text-zinc-500">
                {" "}
                — le texte dit « {detail.perception} » : {hints.join(", ")} en spectateur
              </span>
            )}
          </label>
          <Select
            id={`viewpoint-${detail.id}`}
            value={viewpoint?.mode ?? ""}
            disabled={busy || spectators.length === 0}
            onChange={(e) => chooseViewpoint(e.target.value)}
            className="py-1 text-xs"
          >
            <option value="">Pas encore choisi</option>
            {(Object.keys(VIEWPOINT_LABELS) as ViewpointMode[]).map((m) => (
              <option key={m} value={m}>
                {VIEWPOINT_LABELS[m]} — {VIEWPOINT_HELP[m]}
              </option>
            ))}
          </Select>
          {viewpoint && (
            <p className="text-zinc-500">
              {viewpointSummary(viewpoint.mode, viewpoint.spectators, cast)} · {VIEWPOINT_SOURCES[viewpoint.source] ?? viewpoint.source}
            </p>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
