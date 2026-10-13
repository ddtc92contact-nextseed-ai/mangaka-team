"use client";

import { useState } from "react";
import { TonalityTable, useJournalSettings } from "@/components/journal";
import { Button, Input, Select, Textarea } from "@/components/ui";
import { api, engineUrl, fullErrorMessage, type ABGroup, type ABMode, type WorkflowPreset } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { AB_MODE_LABEL } from "@/lib/journal";

/**
 * « Comparer deux prompts » : la case générée deux fois à la même graine et au même palier (bras A et B), avec le
 * prompt actuel et une variante éditée — ou deux paliers, ou deux CFG. Les deux images s'affichent côte à côte
 * avec leurs mesures de tonalité ; le choix de l'auteur est noté dans le journal (et le bras retenu devient la
 * version choisie de la case).
 */
export function ABBlock({
  panelId,
  prompt,
  presets,
  refreshKey,
  busy,
  run,
  onQueued,
  onChosen,
}: {
  panelId: number;
  prompt: string;
  presets: WorkflowPreset[] | null;
  refreshKey: number;
  busy: boolean;
  run: (action: () => Promise<void>, done?: string) => Promise<void>;
  onQueued: (message: string) => void;
  onChosen: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState(0);
  const groups = useEngineData(() => api.listAB(panelId), [panelId, refreshKey, version]);
  const latest = groups.data?.[0] ?? null;
  return (
    <div className="space-y-2" data-testid="ab-block">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={() => setOpen((o) => !o)} disabled={busy} aria-expanded={open} data-testid="ab-toggle">
          Comparer deux prompts
        </Button>
        <span className="text-xs text-zinc-500">Même graine, même palier : seul ce que tu changes varie.</span>
      </div>
      {open && (
        <ABForm
          key={panelId}
          panelId={panelId}
          prompt={prompt}
          presets={presets}
          busy={busy}
          run={run}
          onQueued={(message) => {
            setOpen(false);
            setVersion((v) => v + 1);
            onQueued(message);
          }}
        />
      )}
      {latest && (
        <ABResult
          group={latest}
          onChosen={() => {
            setVersion((v) => v + 1);
            onChosen();
          }}
        />
      )}
    </div>
  );
}

function ABForm({
  panelId,
  prompt,
  presets,
  busy,
  run,
  onQueued,
}: {
  panelId: number;
  prompt: string;
  presets: WorkflowPreset[] | null;
  busy: boolean;
  run: (action: () => Promise<void>, done?: string) => Promise<void>;
  onQueued: (message: string) => void;
}) {
  const tiers = (presets ?? []).filter((p) => (p.role ?? "generation") === "generation" && p.tier && !p.is_sketch);
  const [mode, setMode] = useState<ABMode>("prompt");
  const [variant, setVariant] = useState(prompt);
  const [tierA, setTierA] = useState(tiers[0]?.id ?? "");
  const [tierB, setTierB] = useState(tiers[1]?.id ?? tiers[0]?.id ?? "");
  const [cfgA, setCfgA] = useState("2");
  const [cfgB, setCfgB] = useState("3");
  const [seed, setSeed] = useState("");

  const start = () =>
    run(async () => {
      const body =
        mode === "prompt"
          ? { mode, prompt_b: variant }
          : mode === "tier"
            ? { mode, presets: [tierA, tierB] as [string, string] }
            : { mode, cfgs: [Number(cfgA.replace(",", ".")), Number(cfgB.replace(",", "."))] as [number, number] };
      const out = await api.startAB(panelId, { ...body, seed: seed.trim() ? Number(seed.trim()) : null });
      onQueued(`Comparaison (${AB_MODE_LABEL[mode]}) mise en file : 2 générations à la graine ${out.seed}.`);
    }, "Comparaison lancée");

  return (
    <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-sm" data-testid="ab-form">
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-1.5 text-xs text-zinc-400">
          Ce qui varie
          <Select className="!w-auto py-1 text-xs" value={mode} onChange={(e) => setMode(e.target.value as ABMode)} data-testid="ab-mode">
            <option value="prompt">Le prompt (A = actuel, B = variante)</option>
            <option value="tier">Le palier</option>
            <option value="cfg">Le CFG</option>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-zinc-400">
          Graine
          <Input className="!w-36 py-1 text-xs" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="au hasard" inputMode="numeric" />
        </label>
      </div>
      {mode === "prompt" && (
        <div className="space-y-1">
          <label htmlFor="ab-variant" className="text-xs text-zinc-400">
            Prompt B (variante ; A garde le prompt actuel de la case)
          </label>
          <Textarea id="ab-variant" rows={5} value={variant} onChange={(e) => setVariant(e.target.value)} className="text-xs" data-testid="ab-variant" />
        </div>
      )}
      {mode === "tier" && (
        <div className="grid gap-2 sm:grid-cols-2">
          {(["A", "B"] as const).map((arm) => (
            <label key={arm} className="flex items-center gap-1.5 text-xs text-zinc-400">
              {arm}
              <Select className="py-1 text-xs" value={arm === "A" ? tierA : tierB} onChange={(e) => (arm === "A" ? setTierA : setTierB)(e.target.value)}>
                {tiers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.tier} — {p.name}
                  </option>
                ))}
              </Select>
            </label>
          ))}
        </div>
      )}
      {mode === "cfg" && (
        <div className="flex flex-wrap gap-3">
          {(["A", "B"] as const).map((arm) => (
            <label key={arm} className="flex items-center gap-1.5 text-xs text-zinc-400">
              CFG {arm}
              <Input
                className="!w-20 py-1 text-xs"
                value={arm === "A" ? cfgA : cfgB}
                onChange={(e) => (arm === "A" ? setCfgA : setCfgB)(e.target.value)}
                inputMode="decimal"
              />
            </label>
          ))}
          <span className="text-xs text-zinc-500">De 1 à 3 ; jamais sur un palier distillé (Turbo).</span>
        </div>
      )}
      <Button onClick={start} disabled={busy} data-testid="ab-start">
        Lancer la comparaison
      </Button>
    </div>
  );
}

function ABResult({ group, onChosen }: { group: ABGroup; onChosen: () => void }) {
  const settings = useJournalSettings();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = !group.pending && group.arms.every((a) => a.log?.status === "succeeded" && a.image);

  async function choose(winner: "A" | "B") {
    setBusy(true);
    setError(null);
    try {
      await api.chooseAB(group.group, { winner, reason: reason || null });
      onChosen();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3" data-testid="ab-result">
      <h4 className="text-xs font-medium text-zinc-300">
        Dernière comparaison · {group.mode ? AB_MODE_LABEL[group.mode] : "—"} · graine {group.seed ?? "—"}
        {group.choice && <span className="ml-2 text-emerald-300">tu as préféré {group.choice}</span>}
        {group.pending && <span className="ml-2 text-amber-300">en cours…</span>}
      </h4>
      <div className="grid grid-cols-2 gap-2">
        {group.arms.map(({ arm, log, image }) => (
          <div key={arm} className={`space-y-1.5 rounded-md p-1.5 ${group.choice === arm ? "ring-2 ring-emerald-400" : "ring-1 ring-zinc-800"}`}>
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-zinc-200">{arm}</span>
              <span className="text-zinc-500">
                {log ? `${log.tier ?? "—"} · cfg ${log.cfg?.toLocaleString("fr-FR") ?? "—"} · ${log.positive_words} mots` : "en file"}
              </span>
            </div>
            {image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={engineUrl(image.url)} alt={`Bras ${arm}, version ${image.version}`} className="aspect-square w-full rounded bg-zinc-950 object-contain" />
            ) : (
              <div className="flex aspect-square items-center justify-center rounded bg-zinc-900 text-xs text-zinc-500">
                {log?.status === "failed" ? `Échec : ${log.error ?? ""}` : "Génération en attente…"}
              </div>
            )}
            {log && <TonalityTable log={log} settings={settings} compact />}
            {log && group.mode === "prompt" && (
              <details className="text-xs">
                <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">Prompt envoyé</summary>
                <p className="mt-1 whitespace-pre-line break-words text-zinc-400">{log.positive_prompt}</p>
              </details>
            )}
            <Button
              variant={group.choice === arm ? "primary" : "secondary"}
              className="w-full !py-1 text-xs"
              onClick={() => choose(arm)}
              disabled={busy || !ready}
              data-testid={`ab-choose-${arm}`}
            >
              Je préfère {arm}
            </Button>
          </div>
        ))}
      </div>
      {settings && settings.reasons.length > 0 && (
        <label className="flex items-center gap-1.5 text-xs text-zinc-400">
          Raison du rejet de l&apos;autre (facultatif)
          <Select className="!w-auto py-1 text-xs" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">—</option>
            {settings.reasons.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </Select>
        </label>
      )}
      {error && <p className="text-xs text-rose-300">{error}</p>}
    </div>
  );
}
