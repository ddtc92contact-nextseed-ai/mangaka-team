"use client";

import { useId, useMemo, useState, type KeyboardEvent } from "react";
import { api, type LoraCatalog } from "@/lib/api";
import type { HelpId } from "@/lib/help";
import { useEngineData } from "@/lib/hooks";
import { InfoTip } from "./info-tip";
import { Field, Input } from "./ui";

type Entry = LoraCatalog["loras"][number];

/** Regroupe par sous-dossier de models/loras, dans l'ordre de ComfyUI (racine d'abord). */
function groupByFolder(entries: Entry[]): { folder: string; entries: Entry[] }[] {
  const groups = new Map<string, Entry[]>();
  for (const e of entries) groups.set(e.folder, [...(groups.get(e.folder) ?? []), e]);
  return [...groups.entries()]
    .sort(([a], [b]) => (a === "" ? -1 : b === "" ? 1 : a.localeCompare(b)))
    .map(([folder, list]) => ({ folder, entries: list }));
}

function matches(entry: Entry, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const name = entry.name.toLowerCase();
  return words.every((w) => name.includes(w));
}

/**
 * Choix d'un LoRA parmi ceux que ComfyUI voit (`GET /comfyui/loras`), avec son poids et ses mots
 * déclencheurs. Recherche, groupes par sous-dossier ; saisie libre quand ComfyUI est hors ligne.
 * `savedValue` : valeur enregistrée, signalée si ComfyUI ne la voit plus. Sans `onTriggerWordsChange`,
 * pas de champ de mots déclencheurs (LoRA de style : ils viennent du catalogue des presets).
 */
export function LoraPicker({
  id,
  label,
  hint,
  help,
  weightHelp,
  placeholder,
  value,
  onChange,
  savedValue,
  error,
  weight,
  onWeightChange,
  weightLabel = "Poids",
  weightError,
  triggerWords,
  onTriggerWordsChange,
  triggerWordsError,
}: {
  id: string;
  label: string;
  hint?: string;
  /** Bulles d'aide « ? » du choix du LoRA et de son poids (textes dans lib/help.ts). */
  help?: HelpId;
  weightHelp?: HelpId;
  placeholder?: string;
  value: string;
  onChange: (value: string) => void;
  savedValue?: string | null;
  error?: string;
  weight: string;
  onWeightChange: (value: string) => void;
  weightLabel?: string;
  weightError?: string;
  triggerWords?: string;
  onTriggerWordsChange?: (value: string) => void;
  triggerWordsError?: string;
}) {
  const [refresh, setRefresh] = useState(0);
  const catalog = useEngineData(() => api.comfyLoras(refresh > 0), [refresh]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();

  const data = catalog.data;
  const loading = catalog.loading && !data && !catalog.error;
  const available = Boolean(data?.available) && !catalog.error;
  const entries = useMemo(() => (available ? (data?.loras ?? []) : []), [available, data]);
  const filtered = useMemo(() => entries.filter((e) => matches(e, query)), [entries, query]);
  const groups = useMemo(() => groupByFolder(filtered), [filtered]);
  // Ordre d'affichage (groupes) : celui du clavier.
  const flat = useMemo(() => groups.flatMap((g) => g.entries), [groups]);
  const trimmed = value.trim();
  const known = entries.some((e) => e.name === trimmed);
  const offlineReason = catalog.error ?? (data && !data.available ? data.error : null);

  function select(name: string) {
    onChange(name);
    setOpen(false);
    setQuery("");
  }

  function openList() {
    setOpen(true);
    setQuery("");
    const index = flat.findIndex((e) => e.name === trimmed);
    setActive(Math.max(0, index));
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return openList();
      if (!flat.length) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + flat.length) % flat.length);
    } else if (e.key === "Enter" && open) {
      // Entrée choisit l'option active au lieu d'envoyer le formulaire.
      e.preventDefault();
      if (flat[active]) select(flat[active].name);
      else setOpen(false);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      setOpen(false);
    }
  }

  let status: { tone: "warn" | "error" | "muted"; text: string } | null = null;
  if (loading) status = { tone: "muted", text: "Lecture des LoRA vus par ComfyUI…" };
  else if (offlineReason) {
    // « ComfyUI hors ligne (127.0.0.1:8188) » ne se répète pas ; les autres motifs sont précisés.
    const detail = /hors ligne/i.test(offlineReason) ? "" : ` (${offlineReason})`;
    status = {
      tone: "warn",
      text: trimmed
        ? `ComfyUI hors ligne : nom non vérifié${detail}.`
        : `ComfyUI hors ligne : liste des LoRA indisponible, tu peux taper le nom du fichier${detail}.`,
    };
  }
  else if (trimmed && !known && !open)
    status =
      savedValue && trimmed === savedValue.trim()
        ? {
            tone: "error",
            text: "ComfyUI ne voit plus ce LoRA enregistré : lien cassé ou fichier déplacé dans models/loras ? Choisis-en un autre ou corrige le dossier.",
          }
        : { tone: "error", text: "Ce nom ne figure pas dans la liste de ComfyUI : la génération sera refusée." };
  else if (data?.simulated) status = { tone: "muted", text: "Liste d'exemple : ComfyUI simulé (mode mock)." };

  const activeId = open && flat[active] ? `${listId}-${active}` : undefined;

  return (
    <div className="space-y-4">
      <div className="grid gap-5 md:grid-cols-[1fr_8rem]">
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <label htmlFor={id} className="block text-sm font-medium text-zinc-300">
              {label}
            </label>
            {help && <InfoTip help={help} label={label} />}
          </div>
          <div className="relative">
            <div className="flex gap-1.5">
              <div className="relative flex-1">
                <Input
                  id={id}
                  role="combobox"
                  aria-expanded={open}
                  aria-controls={listId}
                  aria-autocomplete="list"
                  aria-activedescendant={activeId}
                  aria-invalid={Boolean(error) || status?.tone === "error"}
                  autoComplete="off"
                  spellCheck={false}
                  value={value}
                  placeholder={
                    available ? "Chercher un LoRA…" : (placeholder ?? "nom du fichier, ex. dossier/lora.safetensors")
                  }
                  onChange={(e) => {
                    onChange(e.target.value);
                    setQuery(e.target.value);
                    setActive(0);
                    setOpen(true);
                  }}
                  onFocus={() => !open && openList()}
                  onClick={() => !open && openList()}
                  onBlur={() => setOpen(false)}
                  onKeyDown={onKeyDown}
                  maxLength={255}
                  className={value ? "pr-8" : ""}
                />
                {value && (
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => select("")}
                    className="absolute inset-y-0 right-0 px-2.5 text-zinc-500 hover:text-zinc-200"
                    aria-label="Retirer le LoRA"
                    title="Retirer le LoRA"
                  >
                    ✕
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => setRefresh((n) => n + 1)}
                disabled={catalog.loading && refresh > 0}
                className="rounded-md border border-zinc-700 px-2.5 text-sm text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
                aria-label="Relire la liste des LoRA dans ComfyUI"
                title="Relire la liste des LoRA dans ComfyUI"
              >
                ↻
              </button>
            </div>
            {open && (
              <div
                id={listId}
                role="listbox"
                aria-label={label}
                onMouseDown={(e) => e.preventDefault()}
                className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-zinc-700 bg-zinc-950 py-1 text-sm shadow-xl"
              >
                {loading && <p className="px-3 py-2 text-zinc-500">Chargement…</p>}
                {!loading && !available && (
                  <p className="px-3 py-2 text-amber-300">ComfyUI hors ligne : saisie libre du nom du fichier.</p>
                )}
                {available && !entries.length && (
                  <p className="px-3 py-2 text-zinc-500">Aucun LoRA dans ComfyUI/models/loras.</p>
                )}
                {available && entries.length > 0 && !flat.length && (
                  <p className="px-3 py-2 text-zinc-500">Aucun LoRA ne correspond à « {query.trim()} ».</p>
                )}
                {groups.map((g) => (
                  <div key={g.folder || "/"} role="group" aria-label={g.folder ? `${g.folder}/` : "Racine"}>
                    <p className="px-3 pt-2 pb-1 text-xs font-medium tracking-wide text-zinc-500 uppercase">
                      {g.folder ? `${g.folder}/` : "Racine de models/loras"}
                    </p>
                    {g.entries.map((e) => {
                      const index = flat.indexOf(e);
                      const selected = e.name === trimmed;
                      return (
                        <div
                          key={e.name}
                          id={`${listId}-${index}`}
                          role="option"
                          aria-selected={selected}
                          title={e.name}
                          onMouseEnter={() => setActive(index)}
                          onClick={() => select(e.name)}
                          className={`flex cursor-pointer items-center gap-2 px-3 py-1.5 ${
                            index === active ? "bg-zinc-800 text-zinc-50" : "text-zinc-300"
                          }`}
                        >
                          <span className="w-4 shrink-0 text-rose-400">{selected ? "✓" : ""}</span>
                          <span className="truncate">{e.file}</span>
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </div>
          {error ? (
            <p className="text-xs text-red-400" role="alert">
              {error}
            </p>
          ) : status ? (
            <p
              className={`text-xs ${
                status.tone === "error" ? "text-red-400" : status.tone === "warn" ? "text-amber-300" : "text-zinc-500"
              }`}
              role={status.tone === "muted" ? undefined : "status"}
            >
              {status.text}
            </p>
          ) : (
            <p className="text-xs text-zinc-500">
              {hint ?? "Fichiers de ComfyUI/models/loras (sous-dossiers et liens compris)."}
              {available && ` ${entries.length} LoRA disponible${entries.length > 1 ? "s" : ""}.`}
            </p>
          )}
        </div>
        <Field label={weightLabel} htmlFor={`${id}_weight`} help={weightHelp} error={weightError}>
          <Input
            id={`${id}_weight`}
            type="number"
            step="0.05"
            min="0"
            max="2"
            value={weight}
            onChange={(e) => onWeightChange(e.target.value)}
            aria-invalid={Boolean(weightError)}
          />
        </Field>
      </div>
      {onTriggerWordsChange && (
        <Field
          label="Mots déclencheurs (optionnel)"
          htmlFor={`${id}_triggers`}
          error={triggerWordsError}
          hint="Ajoutés au prompt quand ce LoRA est appliqué. Séparés par des virgules."
        >
          <Input
            id={`${id}_triggers`}
            value={triggerWords ?? ""}
            onChange={(e) => onTriggerWordsChange(e.target.value)}
            placeholder="ex. aiko_v1, ink style"
            maxLength={500}
          />
        </Field>
      )}
    </div>
  );
}
