"use client";

import { useEffect, useRef, useState } from "react";
import { modalOpen } from "@/components/modal";
import { api, fullErrorMessage, type GenerationLog, type JournalSettings, type Judge, type MeasureKey } from "@/lib/api";
import { ACTION_LABEL, VERDICT_LABEL, formatGap, formatPct, gapTone, judgeKeyAction } from "@/lib/journal";

let settingsPromise: Promise<JournalSettings> | null = null;

/** Réglages du journal (raisons, mesures, cible), chargés une fois par onglet. */
export function useJournalSettings(): JournalSettings | null {
  const [settings, setSettings] = useState<JournalSettings | null>(null);
  useEffect(() => {
    let cancelled = false;
    settingsPromise ??= api.journalSettings().catch((e) => {
      settingsPromise = null;
      throw e;
    });
    settingsPromise.then((s) => !cancelled && setSettings(s)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return settings;
}

/** Vrai si la touche vient d'un champ de saisie (on ne détourne pas la frappe). */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

const GAP_TONE = {
  near: "text-emerald-300",
  mid: "text-amber-300",
  far: "text-rose-300",
} as const;

/** Mesures de tonalité d'une génération et écart à la cible (presets/qc_tonality.yaml). */
export function TonalityTable({
  log,
  settings,
  compact = false,
}: {
  log: GenerationLog;
  settings: JournalSettings | null;
  /** Colonne étroite (comparaison A/B) : mesure, valeur et écart, sans la colonne cible. */
  compact?: boolean;
}) {
  if (!settings) return null;
  if (!Object.values(log.measures).some((v) => v !== null && v !== undefined)) {
    return <p className="text-xs text-zinc-500">Aucune mesure de tonalité pour cette génération.</p>;
  }
  if (compact) {
    return (
      <dl className="space-y-0.5 text-[11px]" data-testid="tonality-table">
        {settings.measures.map((m) => {
          const gap = log.gaps[m.key as MeasureKey];
          const tone = gapTone(gap);
          return (
            <div key={m.key} className="flex items-baseline justify-between gap-2">
              <dt className="text-zinc-500">{m.label}</dt>
              <dd className="whitespace-nowrap tabular-nums text-zinc-200">
                {formatPct(log.measures[m.key as MeasureKey])}
                {gap !== null && gap !== undefined && (
                  <span className={`ml-1 ${tone ? GAP_TONE[tone] : ""}`} title={`Cible : ${formatPct(m.target)}`}>
                    ({formatGap(gap)})
                  </span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    );
  }
  return (
    <table className="w-full text-xs" data-testid="tonality-table">
      <caption className="sr-only">Mesures de tonalité et écart à la cible</caption>
      <thead>
        <tr className="text-left text-zinc-500">
          <th className="font-normal">Mesure</th>
          <th className="text-right font-normal">Image</th>
          <th className="text-right font-normal">Cible</th>
          <th className="text-right font-normal">Écart</th>
        </tr>
      </thead>
      <tbody>
        {settings.measures.map((m) => {
          const gap = log.gaps[m.key as MeasureKey];
          const tone = gapTone(gap);
          return (
            <tr key={m.key} className="border-t border-zinc-800/70">
              <td className="py-0.5 text-zinc-400">{m.label}</td>
              <td className="py-0.5 text-right tabular-nums text-zinc-200">{formatPct(log.measures[m.key as MeasureKey])}</td>
              <td className="py-0.5 text-right tabular-nums text-zinc-500">{m.target === null ? "—" : formatPct(m.target)}</td>
              <td className={`py-0.5 text-right tabular-nums ${tone ? GAP_TONE[tone] : "text-zinc-600"}`}>{formatGap(gap)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * Journal d'une version dans l'atelier : jugement en un clic (Je garde / Je rejette + raison), mesures de
 * tonalité et écart à la cible, réglages réellement envoyés, historique des verdicts.
 * Avec `keyboard` : G = je garde, X = je rejette, 1 à 9 = je rejette pour la raison n (hors champs de saisie).
 */
export function VersionJournal({
  imageId,
  version,
  keyboard = false,
  inModal = false,
}: {
  imageId: number;
  version: number;
  keyboard?: boolean;
  inModal?: boolean;
}) {
  const settings = useJournalSettings();
  const [log, setLog] = useState<GenerationLog | null>(null);
  const [loaded, setLoaded] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .imageJournal(imageId)
      .then((out) => {
        if (cancelled) return;
        setLog(out.log);
        setLoaded(imageId);
        setNote("");
        setError(null);
        setSaved(null);
      })
      .catch((e) => !cancelled && setError(fullErrorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [imageId]);

  async function judge(verdict: Judge, reason: string | null) {
    setBusy(true);
    setError(null);
    try {
      const out = await api.judgeImage(imageId, { verdict, reason, note: note.trim() });
      setLog(out.log);
      const label = reason ? settings?.reasons.find((r) => r.id === reason)?.label : null;
      setSaved(`Version ${version} ${verdict === "validated" ? "gardée" : "rejetée"}${label ? ` (${label.toLowerCase()})` : ""}.`);
      setNote("");
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  // Raccourcis clavier (référence stable sur la dernière version des actions).
  const actions = useRef({ judge, busy, reasons: settings?.reasons ?? [], ready: false });
  useEffect(() => {
    actions.current = { judge, busy, reasons: settings?.reasons ?? [], ready: loaded === imageId && log !== null };
  });
  useEffect(() => {
    if (!keyboard) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || typing(e.target)) return;
      if (!inModal && modalOpen()) return;
      const a = actions.current;
      if (!a.ready || a.busy) return;
      const action = judgeKeyAction(e.key, a.reasons);
      if (!action) return;
      e.preventDefault();
      a.judge(action.verdict, action.reason);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keyboard, inModal]);

  if (loaded !== imageId && !error) {
    return <p className="text-xs text-zinc-500">Chargement du journal…</p>;
  }
  if (!log) {
    return (
      <p className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-xs text-zinc-500" data-testid="version-journal">
        {error ?? "Version générée avant le journal des générations : pas de jugement ni de mesure."}
      </p>
    );
  }

  const pill = (active: boolean, tone: "good" | "bad") =>
    `inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 disabled:opacity-50 ${
      active
        ? tone === "good"
          ? "bg-emerald-500 text-emerald-950"
          : "bg-rose-500 text-rose-950"
        : "bg-zinc-800 text-zinc-200 hover:bg-zinc-700"
    }`;
  const last = [...log.events].reverse().find((e) => e.verdict === "validated" || e.verdict === "rejected");

  return (
    <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3" data-testid="version-journal">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-300">
          Ton verdict <span className="font-normal text-zinc-500">· v{version} · journal</span>
        </h3>
        <div className="flex gap-1.5" role="group" aria-label="Verdict sur la version">
          <button
            type="button"
            className={pill(log.verdict === "validated", "good")}
            aria-pressed={log.verdict === "validated"}
            onClick={() => judge("validated", null)}
            disabled={busy}
            data-testid="judge-keep"
          >
            Je garde <kbd className="rounded bg-black/20 px-1 text-[10px]">G</kbd>
          </button>
          <button
            type="button"
            className={pill(log.verdict === "rejected", "bad")}
            aria-pressed={log.verdict === "rejected"}
            onClick={() => judge("rejected", null)}
            disabled={busy}
            data-testid="judge-reject"
          >
            Je rejette <kbd className="rounded bg-black/20 px-1 text-[10px]">X</kbd>
          </button>
        </div>
      </div>

      {settings && settings.reasons.length > 0 && (
        <div className="flex flex-wrap gap-1" role="group" aria-label="Rejeter pour une raison (facultatif)">
          {settings.reasons.map((r, i) => {
            const on = log.verdict === "rejected" && last?.reason === r.id;
            return (
              <button
                key={r.id}
                type="button"
                aria-pressed={on}
                onClick={() => judge("rejected", r.id)}
                disabled={busy}
                title={`Rejeter : ${r.label.toLowerCase()} (touche ${i + 1})`}
                className={`rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-rose-400 disabled:opacity-50 ${
                  on ? "bg-rose-400/20 text-rose-200 ring-rose-400/60" : "text-zinc-400 ring-zinc-700 hover:text-zinc-200"
                }`}
                data-testid="judge-reason"
              >
                {i < 9 && <kbd className="mr-1 text-[10px] text-zinc-500">{i + 1}</kbd>}
                {r.label}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex gap-1.5">
        <label htmlFor={`journal-note-${imageId}`} className="sr-only">
          Note libre du verdict
        </label>
        <input
          id={`journal-note-${imageId}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          placeholder="Note libre (enregistrée avec le prochain verdict)"
          className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-rose-400 focus:outline-none focus:ring-1 focus:ring-rose-400"
        />
      </div>

      <p className="min-h-4 text-xs" aria-live="polite">
        {error ? (
          <span className="text-rose-300">{error}</span>
        ) : saved ? (
          <span className="text-emerald-300">{saved}</span>
        ) : last ? (
          <span className="text-zinc-500">
            Dernier verdict : {VERDICT_LABEL[last.verdict]?.toLowerCase()}
            {last.reason_label ? ` (${last.reason_label.toLowerCase()})` : ""} ·{" "}
            {new Date(last.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
          </span>
        ) : (
          <span className="text-zinc-500">Pas encore jugée.</span>
        )}
      </p>

      <div className="space-y-3 border-t border-zinc-800 pt-2">
        <div>
          <h4 className="mb-1 text-xs font-medium text-zinc-400">
            Tonalité{settings?.tonality_reference ? <span className="font-normal text-zinc-500"> · cible : {settings.tonality_reference}</span> : null}
          </h4>
          <TonalityTable log={log} settings={settings} />
        </div>
        <GenerationFacts log={log} />
      </div>
    </div>
  );
}

/** Réglages réellement envoyés, savoir-faire reçu et historique des verdicts d'une génération. */
function GenerationFacts({ log }: { log: GenerationLog }) {
  const rows: [string, string][] = [
    ["Modèle", log.model ?? "—"],
    ["Étapes · CFG", `${log.steps ?? "—"} · ${log.cfg !== null ? log.cfg.toLocaleString("fr-FR") : "—"}`],
    ["Prompt", `${log.positive_words} mots · ${log.positive_chars} car.${log.prompt_source ? ` · ${log.prompt_source}` : ""}`],
    ["Négatif", `${log.negative_words} mots · ${log.negative_chars} car.`],
    ...(log.framing || log.angle || log.mood
      ? ([["Plan · angle · ambiance", [log.framing, log.angle, log.mood].map((v) => v ?? "—").join(" · ")]] as [string, string][])
      : []),
    ...(log.writer_hash ? ([["Consignes du rédacteur", log.writer_hash]] as [string, string][]) : []),
  ];
  return (
    <div className="space-y-2 text-xs">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-zinc-500">{k}</dt>
            <dd className="break-words text-zinc-300">{v}</dd>
          </div>
        ))}
      </dl>
      {log.knowledge.length > 0 && (
        <details>
          <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">
            Savoir-faire reçu ({log.knowledge.length} fiche{log.knowledge.length > 1 ? "s" : ""})
          </summary>
          <ul className="mt-1 space-y-0.5 text-zinc-400">
            {log.knowledge.map((d) => (
              <li key={d.document_id}>
                • {d.title} <span className="text-zinc-600">({d.collection}, {d.tokens} jetons)</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {log.events.length > 0 && (
        <details>
          <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">Historique des verdicts ({log.events.length})</summary>
          <ol className="mt-1 space-y-0.5 text-zinc-400" data-testid="verdict-history">
            {log.events.map((e) => (
              <li key={e.id}>
                {new Date(e.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} —{" "}
                {VERDICT_LABEL[e.verdict] ?? e.verdict} ({ACTION_LABEL[e.action] ?? e.action})
                {e.reason_label ? ` · ${e.reason_label}` : ""}
                {e.note ? ` · « ${e.note} »` : ""}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
