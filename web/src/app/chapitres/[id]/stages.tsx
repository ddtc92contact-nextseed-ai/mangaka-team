"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import { Modal } from "@/components/modal";
import { useToast } from "@/components/toast";
import { Alert, Button, ButtonLink, Card, Field, Input, Loading, Textarea } from "@/components/ui";
import { api, fullErrorMessage, type ChapterStage } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import {
  blockingMessage,
  blockingStages,
  decisionLabel,
  stageHref,
  stageLinkLabel,
  type StageAction,
} from "@/lib/stages";
import { useChapter } from "./chapter-context";

function StageIcon({ stage }: { stage: ChapterStage }) {
  if (stage.complete)
    return (
      <span aria-label="Étape réglée" className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-xs text-emerald-300">
        ✓
      </span>
    );
  if (stage.forced)
    return (
      <span aria-label="Étape forcée" className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-sky-500/20 text-xs text-sky-300">
        »
      </span>
    );
  return (
    <span aria-label="Étape en attente" className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-xs text-amber-300">
      !
    </span>
  );
}

/** « Passer outre » une étape précise : nom de l'auteur et raison, enregistrés dans le journal. */
function OverrideDialog({ stage, onClose }: { stage: ChapterStage | null; onClose: () => void }) {
  const { chapter, setStages } = useChapter();
  // « Ton nom » des Réglages par défaut (le moteur l'applique aussi si le champ reste vide), modifiable ici.
  const settings = useEngineData(() => api.getAppSettings(), []);
  const [typed, setAuthor] = useState<string | null>(null);
  const author = typed ?? settings.data?.author_name ?? "";
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function confirm() {
    if (!stage) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.overrideStage(chapter.id, stage.key, { author: author.trim(), note: note.trim() });
      setStages(next);
      toast(`${stage.label} : étape forcée`, "info");
      setNote("");
      setAuthor(null);
      onClose();
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={stage !== null}
      onClose={onClose}
      title={stage ? `Passer outre « ${stage.label} » ?` : "Passer outre"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button onClick={confirm} disabled={busy} data-testid="confirm-stage-override">
            {busy ? "Enregistrement…" : "Passer outre cette étape"}
          </Button>
        </>
      }
    >
      {stage && (
        <div className="space-y-4 text-sm text-zinc-300">
          <p>
            {stage.summary.charAt(0).toUpperCase() + stage.summary.slice(1)}. Cette seule étape ne bloquera plus le
            chapitre {chapter.number} ; les autres restent gardées. La décision (étape, date, auteur) est notée dans
            le journal et visible dans les statistiques.
          </p>
          {error && <Alert>{error}</Alert>}
          <Field label="Ton nom" htmlFor="stage-override-author" hint="Par défaut, le nom saisi dans les Réglages.">
            <Input id="stage-override-author" value={author} maxLength={120} onChange={(e) => setAuthor(e.target.value)} />
          </Field>
          <Field label="Pourquoi (facultatif)" htmlFor="stage-override-note">
            <Textarea id="stage-override-note" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
      )}
    </Modal>
  );
}

/** Liste des étapes vitales du chapitre : cochées / en attente, compteurs, lien vers l'écran qui les règle. */
export function StageChecklist() {
  const { chapter, stages, stagesError, setStages } = useChapter();
  const [override, setOverride] = useState<ChapterStage | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function revoke(stage: ChapterStage) {
    setError(null);
    try {
      setStages(await api.revokeStageOverride(chapter.id, stage.key));
    } catch (e) {
      setError(fullErrorMessage(e));
    }
  }

  return (
    <Card data-testid="stage-checklist">
      <h2 className="mb-1 font-semibold text-zinc-100">Étapes du chapitre</h2>
      <p className="mb-4 text-xs text-zinc-500">
        Une étape en attente bloque l&apos;action suivante (génération, lettrage, export). « Passer outre » ne débloque
        qu&apos;elle, et laisse une trace dans le journal.
      </p>
      {stagesError && <Alert>Étapes indisponibles : {stagesError}</Alert>}
      {!stages && !stagesError && <Loading />}
      {error && (
        <div className="mb-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {stages && (
        <ul className="space-y-3">
          {stages.stages.map((s) => {
            const decision = decisionLabel(s);
            return (
              <li key={s.key} className="flex gap-3" data-testid={`stage-${s.key}`} data-state={s.complete ? "ok" : s.forced ? "forced" : "pending"}>
                <StageIcon stage={s} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <p className={`font-medium ${s.complete ? "text-zinc-200" : "text-zinc-100"}`}>{s.label}</p>
                    <span className={`text-xs ${s.passed ? "text-zinc-500" : "text-amber-300"}`}>
                      {s.total === 0 && s.complete ? "rien à vérifier" : `${s.total - s.faults}/${s.total}`}
                    </span>
                  </div>
                  {!s.complete && (
                    <p className="text-xs text-zinc-400">
                      {s.summary}
                      {s.examples.length > 0 && ` — ${s.examples.slice(0, 4).join(", ")}${s.faults > 4 ? "…" : ""}`}
                      {!s.passed && s.blocks.length > 0 && <> · bloque : {s.blocks.join(", ")}</>}
                    </p>
                  )}
                  {decision && <p className="text-xs text-zinc-500">{decision}</p>}
                  {!s.complete && (
                    <div className="mt-1.5 flex flex-wrap gap-2">
                      <ButtonLink
                        variant="ghost"
                        className="!px-2 !py-1 text-xs"
                        href={stageHref(s, chapter.id, chapter.project_id)}
                      >
                        {stageLinkLabel(s)}
                      </ButtonLink>
                      {s.forced ? (
                        <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => revoke(s)}>
                          Lever le passer-outre
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          className="!px-2 !py-1 text-xs"
                          onClick={() => setOverride(s)}
                          data-testid={`override-${s.key}`}
                        >
                          Passer outre
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <OverrideDialog stage={override} onClose={() => setOverride(null)} />
    </Card>
  );
}

/**
 * Bandeau des étapes qui bloquent une action de l'écran (« Direction artistique appliquée : 5 pages en attente
 * sur 5. Applique-la avant de générer. »), avec un lien vers l'écran qui règle le problème et « Passer outre ».
 */
export function StageBanner({ action }: { action: StageAction | StageAction[] }) {
  const { chapter, stages } = useChapter();
  const pathname = usePathname();
  const [override, setOverride] = useState<ChapterStage | null>(null);
  const actions = Array.isArray(action) ? action : [action];
  const seen = new Set<string>();
  const rows: { stage: ChapterStage; action: StageAction }[] = [];
  for (const a of actions) {
    for (const s of blockingStages(stages?.stages, a)) {
      if (seen.has(s.key)) continue;
      seen.add(s.key);
      rows.push({ stage: s, action: a });
    }
  }
  if (!rows.length) return null;
  return (
    <div
      role="status"
      data-testid="stage-banner"
      className="mb-4 space-y-2 rounded-md border border-amber-700/50 bg-amber-950/30 px-4 py-3 text-sm"
    >
      <p className="font-medium text-amber-100">Étape{rows.length > 1 ? "s" : ""} à régler d&apos;abord</p>
      {rows.map(({ stage, action: a }) => {
        const href = stageHref(stage, chapter.id, chapter.project_id);
        return (
          <div key={stage.key} className="flex flex-wrap items-center justify-between gap-2">
            <p className="min-w-0 text-amber-200/90">{blockingMessage(stage, a)}</p>
            <div className="flex shrink-0 gap-2">
              {href !== pathname && (
                <ButtonLink variant="secondary" className="!py-1 text-xs" href={href}>
                  {stageLinkLabel(stage)}
                </ButtonLink>
              )}
              <Button variant="ghost" className="!py-1 text-xs" onClick={() => setOverride(stage)}>
                Passer outre
              </Button>
            </div>
          </div>
        );
      })}
      <OverrideDialog stage={override} onClose={() => setOverride(null)} />
    </div>
  );
}
