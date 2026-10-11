"use client";

import { useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { Alert, Button, Textarea } from "@/components/ui";
import { api, fullErrorMessage, type Job, type PanelDetail, type PanelDialogTurn } from "@/lib/api";
import { DIALOG_STATUS, wordDiff } from "@/lib/dialog";
import { useEngineData } from "@/lib/hooks";

/**
 * « Demander à l'IA pour cette case » : une consigne en français → l'IA propose un nouveau prompt et, au besoin, un
 * autre plan, angle, action, ambiance ou image de référence. Aperçu (ancien / nouveau prompt, champs changés), puis
 * « Appliquer », « Appliquer et générer » (une nouvelle version de cette case seulement) ou « Annuler ».
 */
export function DialogBlock({
  panelId,
  overrides,
  disabled,
  onApplied,
  onRebuilt,
}: {
  panelId: number;
  /** Ce que le dialogue impose déjà à la case (« Plan : gros plan »…). */
  overrides: string[];
  disabled: boolean;
  onApplied: (panel: PanelDetail, jobs: Job[]) => void;
  onRebuilt: (panel: PanelDetail) => void;
}) {
  const turns = useEngineData(() => api.panelDialog(panelId), [panelId]);
  // Consigne en cours de saisie, rattachée à la case (repart à zéro en changeant de case).
  const [draft, setDraft] = useState<{ panelId: number; text: string } | null>(null);
  const [working, setWorking] = useState<"ask" | "rebuild" | "apply" | null>(null);
  const [error, setError] = useState<{ panelId: number; message: string } | null>(null);

  const instruction = draft && draft.panelId === panelId ? draft.text : "";
  const list = turns.data && turns.data.every((t) => t.panel_id === panelId) ? turns.data : [];
  const pending = [...list].reverse().find((t) => t.status === "proposed") ?? null;
  const history = list.filter((t) => t.status !== "proposed");
  const shownError = error && error.panelId === panelId ? error.message : null;
  const locked = disabled || working !== null;

  async function act(kind: "ask" | "rebuild" | "apply", action: () => Promise<void>) {
    setWorking(kind);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError({ panelId, message: fullErrorMessage(e) });
    } finally {
      setWorking(null);
    }
  }

  const ask = () =>
    act("ask", async () => {
      const turn = await api.askPanelDialog(panelId, instruction.trim());
      turns.setData((cur) => [...(cur ?? []).map((t) => (t.status === "proposed" ? { ...t, status: "cancelled" as const } : t)), turn]);
      setDraft(null);
    });
  const rebuild = () =>
    act("rebuild", async () => {
      const panel = await api.rebuildPrompt(panelId, instruction.trim());
      setDraft(null);
      turns.reload();
      onRebuilt(panel);
    });
  const apply = (turn: PanelDialogTurn, generate: boolean) =>
    act("apply", async () => {
      const out = await api.applyPanelDialog(turn.id, generate);
      turns.setData((cur) => (cur ?? []).map((t) => (t.id === turn.id ? out.turn : t)));
      onApplied(out.panel, out.jobs);
    });
  const cancel = (turn: PanelDialogTurn) =>
    act("apply", async () => {
      const out = await api.cancelPanelDialog(turn.id);
      turns.setData((cur) => (cur ?? []).map((t) => (t.id === turn.id ? out : t)));
    });

  return (
    <section aria-labelledby="dialog-title" className="space-y-2 rounded-lg border border-zinc-800 p-3" data-testid="panel-dialog">
      <h3 id="dialog-title" className="flex items-center gap-1.5 text-sm font-medium text-zinc-300">
        Demander à l&apos;IA pour cette case
        <InfoTip help="atelier.dialog" label="Demander à l'IA pour cette case" />
      </h3>
      {overrides.length > 0 && (
        <p className="text-[11px] text-zinc-400" data-testid="dialog-overrides">
          <span className="text-zinc-500">Imposé à cette case par le dialogue : </span>
          {overrides.join(" · ")}
          <span className="text-zinc-500"> (« Reconstruire le prompt » le retire)</span>
        </p>
      )}
      <label htmlFor="dialog-instruction" className="sr-only">
        Consigne pour l&apos;IA
      </label>
      <Textarea
        id="dialog-instruction"
        rows={2}
        className="text-xs"
        value={instruction}
        maxLength={1000}
        placeholder="Ex. : plus serré, gros plan sur le visage de Lucius, en contre-plongée — Ctrl+Entrée pour envoyer"
        onChange={(e) => setDraft({ panelId, text: e.target.value })}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && instruction.trim() && !locked) {
            e.preventDefault();
            void ask();
          }
        }}
        disabled={working === "ask" || working === "rebuild"}
        aria-describedby="dialog-hint"
      />
      <p id="dialog-hint" className="sr-only">
        Ctrl+Entrée envoie la consigne.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button className="!px-2.5 !py-1 text-xs" onClick={ask} disabled={locked || !instruction.trim()} data-testid="dialog-ask">
          {working === "ask" ? "L'IA réfléchit…" : "Demander"}
        </Button>
        <Button
          variant="ghost"
          className="!px-2.5 !py-1 text-xs"
          onClick={rebuild}
          disabled={locked || !instruction.trim()}
          title="Repart de la direction de la page (sans ce que le dialogue imposait) et applique directement cette consigne"
          data-testid="dialog-rebuild"
        >
          {working === "rebuild" ? "Reconstruction…" : "Reconstruire le prompt avec cette consigne"}
        </Button>
      </div>
      {(working === "ask" || working === "rebuild") && (
        <p className="text-[11px] text-sky-300" role="status" data-testid="dialog-working">
          L&apos;IA réfléchit à la case… (3 essais au plus ; rien ne change sans ton accord)
        </p>
      )}
      {shownError && (
        <div data-testid="dialog-error">
          <Alert>{shownError}</Alert>
        </div>
      )}
      {turns.error && <p className="text-[11px] text-amber-300">Historique indisponible : {turns.error}</p>}

      {pending && <Proposal turn={pending} disabled={locked} onApply={apply} onCancel={cancel} />}

      {history.length > 0 && (
        <details className="text-xs" data-testid="dialog-history">
          <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">Historique ({history.length})</summary>
          <ol className="mt-2 space-y-2">
            {[...history].reverse().map((t) => (
              <li key={t.id} className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
                <p className="text-zinc-200">
                  <span className="text-zinc-500">Toi : </span>
                  {t.instruction}
                </p>
                <p className="text-zinc-300">
                  <span className="text-zinc-500">IA : </span>
                  {t.explanation}
                </p>
                <p className="text-[10px] text-zinc-500">
                  {DIALOG_STATUS[t.status] ?? t.status}
                  {t.changes.length > 0 && ` · ${t.changes.map((ch) => `${ch.label} → ${ch.after ?? "—"}`).join(" · ")}`}
                </p>
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function Proposal({
  turn,
  disabled,
  onApply,
  onCancel,
}: {
  turn: PanelDialogTurn;
  disabled: boolean;
  onApply: (turn: PanelDialogTurn, generate: boolean) => void;
  onCancel: (turn: PanelDialogTurn) => void;
}) {
  const parts = wordDiff(turn.prompt_before ?? "", turn.prompt_after);
  return (
    <div className="space-y-2 rounded-md border border-sky-500/30 bg-sky-500/5 p-3 text-xs" data-testid="dialog-proposal">
      <p className="text-zinc-200">
        <span className="text-zinc-500">« {turn.instruction} » — </span>
        {turn.explanation}
      </p>
      {turn.changes.length > 0 && (
        <ul className="space-y-0.5" data-testid="dialog-changes">
          {turn.changes.map((ch) => (
            <li key={ch.field}>
              <span className="text-zinc-400">{ch.label} : </span>
              <span className="text-rose-300 line-through">{ch.before ?? "—"}</span>
              {" → "}
              <span className="text-emerald-300">{ch.after ?? "—"}</span>
            </li>
          ))}
        </ul>
      )}
      <div>
        <p className="mb-1 text-[10px] text-zinc-500">
          Prompt : <span className="text-rose-300 line-through">retiré</span> · <span className="text-emerald-300">ajouté</span>
        </p>
        <p className="max-h-56 overflow-y-auto rounded bg-zinc-950/60 p-2 leading-relaxed text-zinc-300" data-testid="dialog-diff">
          {parts.map((p, i) =>
            p.kind === "same" ? (
              <span key={i}>{p.text} </span>
            ) : p.kind === "removed" ? (
              <del key={i} className="bg-rose-500/15 text-rose-300">
                {p.text}{" "}
              </del>
            ) : (
              <ins key={i} className="bg-emerald-500/15 text-emerald-200 no-underline">
                {p.text}{" "}
              </ins>
            ),
          )}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button className="!px-2.5 !py-1 text-xs" onClick={() => onApply(turn, true)} disabled={disabled} data-testid="dialog-apply-generate">
          Appliquer et générer
        </Button>
        <Button variant="secondary" className="!px-2.5 !py-1 text-xs" onClick={() => onApply(turn, false)} disabled={disabled} data-testid="dialog-apply">
          Appliquer
        </Button>
        <Button variant="ghost" className="!px-2.5 !py-1 text-xs" onClick={() => onCancel(turn)} disabled={disabled} data-testid="dialog-cancel">
          Annuler
        </Button>
      </div>
    </div>
  );
}
