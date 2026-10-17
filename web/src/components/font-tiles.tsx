"use client";

// Choix d'une police en mini-tuiles : chaque tuile montre un exemple écrit dans la vraie police, servie par
// le moteur (jamais une police web de substitution). Groupe radio ARIA : Tab entre dans le groupe, les
// flèches (et Début / Fin) changent le choix, Entrée ou Espace sélectionne la tuile qui a le focus.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { FONT_SAMPLES, type FontSampleKind } from "@/lib/font-samples";
import type { HelpId } from "@/lib/help";
import { InfoTip } from "./info-tip";

export interface FontTileOption {
  id: string;
  name: string;
  /** Adresse complète du fichier .ttf (moteur). */
  url: string;
}

// Une seule FontFace par fichier pour toute la page : les tuiles des deux formulaires la partagent.
const loaded = new Map<string, Promise<string>>();

function loadFont(url: string): Promise<string> {
  let family = loaded.get(url);
  if (!family) {
    const name = `mk-tile-${loaded.size}`;
    family = new FontFace(name, `url("${url}") format("truetype")`).load().then((face) => {
      document.fonts.add(face);
      return name;
    });
    // Échec : on retentera au prochain affichage (moteur relancé, preset corrigé…).
    family.catch(() => loaded.delete(url));
    loaded.set(url, family);
  }
  return family;
}

type FontState = { url: string; family: string | null; failed: boolean };

/** Famille CSS chargée pour `url`, `null` tant qu'elle charge, `failed` si le moteur ne l'a pas servie. */
function useFontFamily(url: string | null): { family: string | null; failed: boolean } {
  const [state, setState] = useState<FontState | null>(null);
  useEffect(() => {
    if (!url) return;
    let live = true;
    loadFont(url).then(
      (family) => live && setState({ url, family, failed: false }),
      () => live && setState({ url, family: null, failed: true }),
    );
    return () => {
      live = false;
    };
  }, [url]);
  if (!url || state?.url !== url) return { family: null, failed: false };
  return state;
}

// Bulle de cri en étoile (contour noir = même polygone, un cran plus grand).
const SPIKES =
  "polygon(0% 18%, 12% 10%, 14% 0%, 28% 9%, 40% 0%, 50% 10%, 62% 0%, 72% 10%, 86% 0%, 88% 12%, 100% 14%, 94% 32%, 100% 50%, 94% 68%, 100% 86%, 88% 90%, 86% 100%, 72% 90%, 60% 100%, 50% 90%, 38% 100%, 28% 90%, 14% 100%, 12% 88%, 0% 84%, 6% 66%, 0% 50%, 6% 34%)";

function Sample({ kind, family }: { kind: FontSampleKind; family: string }) {
  const text = FONT_SAMPLES[kind];
  const style = { fontFamily: `"${family}"` };
  if (kind === "dialogue") {
    return (
      <span className="relative block max-w-full">
        <span
          className="block rounded-[50%] border-2 border-zinc-900 bg-white px-3.5 py-2.5 text-center text-[11px] leading-tight text-zinc-950"
          style={style}
        >
          {text}
        </span>
        <span aria-hidden="true" className="absolute -bottom-1.5 left-6 h-3 w-3 rotate-45 border-r-2 border-b-2 border-zinc-900 bg-white" />
      </span>
    );
  }
  if (kind === "shout") {
    return (
      <span className="relative block w-full bg-zinc-900 p-[3px]" style={{ clipPath: SPIKES }}>
        <span
          className="block bg-white px-5 py-4 text-center text-[13px] leading-tight text-zinc-950"
          style={{ ...style, clipPath: SPIKES }}
        >
          {text}
        </span>
      </span>
    );
  }
  return (
    <span
      className="block -rotate-6 text-center text-[19px] leading-none text-amber-300 [paint-order:stroke_fill] [-webkit-text-stroke:3px_#18181b]"
      style={style}
    >
      {text}
    </span>
  );
}

function Tile({
  kind,
  option,
  label,
  missing,
  checked,
  tabbable,
  onSelect,
  onKeyDown,
  setRef,
}: {
  kind: FontSampleKind;
  option: FontTileOption;
  label: string;
  missing: boolean;
  checked: boolean;
  tabbable: boolean;
  onSelect: () => void;
  onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void;
  setRef: (el: HTMLButtonElement | null) => void;
}) {
  const { family, failed } = useFontFamily(missing ? null : option.url);
  const status = missing ? "police introuvable" : failed ? "aperçu indisponible" : null;
  return (
    <button
      ref={setRef}
      type="button"
      role="radio"
      aria-checked={checked}
      aria-label={status ? `${label} (${status})` : label}
      tabIndex={tabbable ? 0 : -1}
      onClick={onSelect}
      onKeyDown={onKeyDown}
      data-testid={`font-tile-${kind}-${option.id || "lettreur"}`}
      data-state={missing ? "missing" : failed ? "error" : family ? "ready" : "loading"}
      className={`flex min-w-0 flex-col overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 ${
        checked ? "border-rose-400 bg-rose-500/10 ring-1 ring-rose-400" : "border-zinc-700 bg-zinc-950 hover:border-zinc-500"
      }`}
    >
      <span
        aria-hidden="true"
        className={`flex h-32 items-center justify-center overflow-hidden px-2.5 ${
          kind === "sfx" ? "bg-[radial-gradient(circle,#d4d4d8_1px,transparent_1.5px)] bg-[length:6px_6px] bg-zinc-100" : "bg-zinc-200"
        }`}
      >
        {family ? (
          <Sample kind={kind} family={family} />
        ) : status ? (
          <span className="px-2 text-center text-xs font-medium text-red-700">
            {missing ? "Police introuvable dans les presets" : "La police n'a pas pu être chargée depuis le moteur"}
          </span>
        ) : (
          <span className="h-10 w-3/4 animate-pulse rounded-full bg-zinc-300" />
        )}
      </span>
      <span className="flex items-center gap-2 px-2.5 py-2">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-zinc-100">{label}</span>
          {status && <span className="block text-[11px] text-red-400">{status}</span>}
        </span>
        <span
          aria-hidden="true"
          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
            checked ? "border-rose-400 bg-rose-400" : "border-zinc-600"
          }`}
        >
          {checked && <span className="h-1.5 w-1.5 rounded-full bg-zinc-950" />}
        </span>
      </span>
    </button>
  );
}

/**
 * Sélecteur de police en tuiles. `defaultUrl` : police du lettreur, proposée (valeur vide) quand rien n'est
 * choisi. Une valeur absente de `fonts` (une fois `fonts` chargées, `ready`) reste affichée « introuvable ».
 */
export function FontTilePicker({
  id,
  label,
  kind,
  value,
  fonts,
  onChange,
  ready = true,
  defaultUrl,
  help,
  hint,
  error,
}: {
  id: string;
  label: string;
  kind: FontSampleKind;
  value: string;
  fonts: FontTileOption[];
  onChange: (id: string) => void;
  ready?: boolean;
  defaultUrl?: string;
  help?: HelpId;
  hint?: string;
  error?: string;
}) {
  const tiles: { option: FontTileOption; value: string; label: string; missing: boolean }[] = [];
  if (!value && defaultUrl) {
    tiles.push({ option: { id: "", name: "Police du lettreur", url: defaultUrl }, value: "", label: "Police du lettreur", missing: false });
  }
  for (const f of fonts) tiles.push({ option: f, value: f.id, label: f.name, missing: false });
  if (value && ready && !fonts.some((f) => f.id === value)) {
    tiles.push({ option: { id: value, name: value, url: "" }, value, label: value, missing: true });
  }
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = tiles.findIndex((t) => t.value === value);

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = tiles.length - 1;
    const next =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? index === last ? 0 : index + 1
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? index === 0 ? last : index - 1
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? last
              : null;
    if (next === null) return;
    e.preventDefault();
    onChange(tiles[next].value);
    refs.current[next]?.focus();
  }

  const describedBy = `${id}-help`;
  return (
    <fieldset className="min-w-0 space-y-2" data-testid={`font-picker-${id}`}>
      <legend className="flex items-center gap-1.5 text-sm font-medium text-zinc-300">
        {label}
        {help && <InfoTip help={help} label={label} />}
      </legend>
      {(error || hint) && (
        <p id={describedBy} className={`text-xs ${error ? "text-red-400" : "text-zinc-500"}`} role={error ? "alert" : undefined}>
          {error || hint}
        </p>
      )}
      <div
        role="radiogroup"
        aria-label={label}
        aria-describedby={error || hint ? describedBy : undefined}
        aria-invalid={error ? true : undefined}
        className="grid grid-cols-[repeat(auto-fill,minmax(8rem,1fr))] gap-2"
      >
        {tiles.length === 0 && <p className="text-xs text-zinc-500">Chargement des polices…</p>}
        {tiles.map((t, i) => (
          <Tile
            key={t.value || "lettreur"}
            kind={kind}
            option={t.option}
            label={t.label}
            missing={t.missing}
            checked={i === current}
            tabbable={current === -1 ? i === 0 : i === current}
            onSelect={() => onChange(t.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            setRef={(el) => {
              refs.current[i] = el;
            }}
          />
        ))}
      </div>
    </fieldset>
  );
}
