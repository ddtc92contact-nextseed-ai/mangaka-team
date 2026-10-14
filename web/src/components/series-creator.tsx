"use client";

import { useEffect, useRef, useState } from "react";
import { useConfirm } from "@/components/confirm";
import { InfoTip } from "@/components/info-tip";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Input, Loading, Textarea } from "@/components/ui";
import {
  api,
  errorMessage,
  type CreatorAnswer,
  type CreatorProposal,
  type DnaValue,
  type SeriesCreator,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

type Step = "closed" | "questions" | "proposal" | "done";

function formatValue(kind: string, value: DnaValue): string {
  if (kind === "bool") return value ? "oui" : "non";
  if (kind === "share") return `${Math.round(Number(value) * 100)} %`;
  return String(value);
}

/**
 * Créateur de série : un échange guidé (questions fermées, réponse libre facultative) puis l'ADN et la bible
 * proposés, corrigés par l'auteur avant d'être enregistrés. Relancé sur une série existante, il montre ce qui est
 * écrit à côté de ce qui est proposé et ne remplace rien sans confirmation.
 */
export function SeriesCreatorCard({
  projectId,
  autoOpen = false,
  onApplied,
}: {
  projectId: number;
  autoOpen?: boolean;
  onApplied: () => void;
}) {
  const info = useEngineData(
    () => api.getSeriesCreator(projectId),
    [projectId],
  );
  const [step, setStep] = useState<Step>(autoOpen ? "questions" : "closed");
  const [pitch, setPitch] = useState("");
  const [answers, setAnswers] = useState<Record<string, CreatorAnswer>>({});
  const [proposal, setProposal] = useState<CreatorProposal | null>(null);
  const [written, setWritten] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoOpen && info.data?.available) {
      requestAnimationFrame(() =>
        ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
    }
  }, [autoOpen, info.data?.available]);

  const data = info.data;
  const existing = data
    ? data.bible_filled.length > 0 ||
      data.notes_filled > 0 ||
      data.dna_adjusted > 0
    : false;

  return (
    <Card
      ref={ref}
      id="createur"
      className="scroll-mt-6"
      data-testid="series-creator"
    >
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 font-semibold text-zinc-100">
          🧭 Créateur de série
          <InfoTip help="serie.createur" label="Créateur de série" />
        </h2>
        {data?.available && (step === "closed" || step === "done") && (
          <Button
            variant={existing ? "secondary" : "primary"}
            onClick={() => setStep("questions")}
            data-testid="creator-open"
          >
            {existing ? "Relancer l'échange" : "Lancer l'échange"}
          </Button>
        )}
      </div>
      {info.loading && !data ? (
        <Loading />
      ) : info.error || !data ? (
        <Alert>{info.error ?? "Créateur de série indisponible"}</Alert>
      ) : !data.available ? (
        <Alert tone="info">
          Créateur de série indisponible : {data.reason}
        </Alert>
      ) : step === "closed" || step === "done" ? (
        <>
          <p className="text-sm text-zinc-400">
            {existing
              ? `Bible : ${data.bible_filled.length}/4 sections écrites, ${data.notes_filled}/${data.characters} personnages avec une note ; ADN : ${data.dna_adjusted} valeur${data.dna_adjusted > 1 ? "s" : ""} ajustée${data.dna_adjusted > 1 ? "s" : ""}. Une relance propose un différentiel : rien de ce que tu as écrit n'est remplacé sans ton accord.`
              : `Quelques questions sur ta série, puis l'agent propose son ADN (les écarts au genre${data.genre_name ? ` « ${data.genre_name} »` : ""}) et rédige sa bible. Tu corriges tout avant d'enregistrer.`}
          </p>
          {step === "done" && (
            <p
              className="mt-2 text-sm text-emerald-300"
              role="status"
              data-testid="creator-done"
            >
              {written.length
                ? `Enregistré : ${written.length} élément${written.length > 1 ? "s" : ""} (cartes « ADN de la série » et « Bible de la série » ci-dessous).`
                : "Rien n'a changé : tout ce qui était retenu était déjà écrit."}
            </p>
          )}
        </>
      ) : step === "questions" ? (
        <Questions
          projectId={projectId}
          creator={data}
          pitch={pitch}
          answers={answers}
          onPitch={setPitch}
          onAnswers={setAnswers}
          onCancel={() => setStep("closed")}
          onProposal={(p) => {
            setProposal(p);
            setStep("proposal");
            requestAnimationFrame(() =>
              ref.current?.scrollIntoView({
                behavior: "smooth",
                block: "start",
              }),
            );
          }}
        />
      ) : proposal ? (
        <Review
          projectId={projectId}
          proposal={proposal}
          onBack={() => setStep("questions")}
          onCancel={() => setStep("closed")}
          onApplied={(keys) => {
            setWritten(keys);
            setStep("done");
            info.reload();
            onApplied();
          }}
        />
      ) : null}
    </Card>
  );
}

function Questions({
  projectId,
  creator,
  pitch,
  answers,
  onPitch,
  onAnswers,
  onCancel,
  onProposal,
}: {
  projectId: number;
  creator: SeriesCreator;
  pitch: string;
  answers: Record<string, CreatorAnswer>;
  onPitch: (v: string) => void;
  onAnswers: (a: Record<string, CreatorAnswer>) => void;
  onCancel: () => void;
  onProposal: (p: CreatorProposal) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const answered = creator.questions.filter(
    (q) => answers[q.id]?.choice,
  ).length;
  const ready = answered === creator.questions.length;

  function set(id: string, patch: Partial<CreatorAnswer>) {
    const prev = answers[id] ?? { choice: null, note: "" };
    onAnswers({ ...answers, [id]: { ...prev, ...patch } });
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      onProposal(await api.proposeSeries(projectId, { pitch, answers }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 space-y-5" data-testid="creator-questions">
      <div>
        <label
          htmlFor="creator-pitch"
          className="mb-1 block text-sm font-medium text-zinc-200"
        >
          De quoi parle ta série ?{" "}
          <span className="font-normal text-zinc-500">(facultatif)</span>
        </label>
        <Textarea
          id="creator-pitch"
          className="min-h-16"
          maxLength={creator.max_pitch_chars}
          value={pitch}
          placeholder="En deux ou trois phrases : le héros, son monde, ce qu'il cherche…"
          onChange={(e) => onPitch(e.target.value)}
          disabled={busy}
        />
      </div>
      <ol className="grid gap-4 lg:grid-cols-2">
        {creator.questions.map((q, i) => {
          const a = answers[q.id];
          return (
            <li
              key={q.id}
              className="rounded-lg border border-zinc-800 p-3"
              data-testid={`creator-q-${q.id}`}
            >
              <p
                id={`creator-q-${q.id}`}
                className="text-sm font-medium text-zinc-100"
              >
                {i + 1}. {q.label}
              </p>
              {q.help && <p className="text-xs text-zinc-500">{q.help}</p>}
              <div
                role="radiogroup"
                aria-labelledby={`creator-q-${q.id}`}
                className="mt-2 flex flex-wrap gap-2"
              >
                {q.choices.map((c) => {
                  const on = a?.choice === c.id;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      disabled={busy}
                      onClick={() => set(q.id, { choice: c.id })}
                      className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                        on
                          ? "bg-rose-500 text-white"
                          : "bg-zinc-800 text-zinc-300 ring-1 ring-inset ring-zinc-700 hover:bg-zinc-700"
                      }`}
                    >
                      {c.label}
                    </button>
                  );
                })}
              </div>
              <Input
                className="mt-2 py-1.5 text-xs"
                aria-label={`${q.label} — précision facultative`}
                placeholder="Une précision ? (facultatif)"
                maxLength={creator.max_free_chars}
                value={a?.note ?? ""}
                disabled={busy}
                onChange={(e) => set(q.id, { note: e.target.value })}
              />
            </li>
          );
        })}
      </ol>
      {error && (
        <div data-testid="creator-error">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={submit}
          disabled={busy || !ready}
          data-testid="creator-propose"
        >
          {busy
            ? "Le créateur de série réfléchit…"
            : error
              ? "Réessayer"
              : "Proposer l'ADN et la bible"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Annuler
        </Button>
        {!ready && (
          <span className="text-xs text-zinc-500">
            {answered}/{creator.questions.length} questions répondues
          </span>
        )}
      </div>
    </div>
  );
}

type Item<T> = T & { keep: boolean };

function Review({
  projectId,
  proposal,
  onBack,
  onCancel,
  onApplied,
}: {
  projectId: number;
  proposal: CreatorProposal;
  onBack: () => void;
  onCancel: () => void;
  onApplied: (written: string[]) => void;
}) {
  // Par défaut : tout ce qui est nouveau est retenu ; ce qui remplacerait un texte de l'auteur ne l'est pas.
  const [dna, setDna] = useState<Item<CreatorProposal["dna"][number]>[]>(() =>
    proposal.dna.map((d) => ({ ...d, keep: !d.conflict })),
  );
  const [bible, setBible] = useState<Item<CreatorProposal["bible"][number]>[]>(
    () =>
      proposal.bible.map((b) => ({
        ...b,
        keep: !b.conflict && b.proposed !== b.current,
      })),
  );
  const [notes, setNotes] = useState<
    Item<CreatorProposal["characters"][number]>[]
  >(() =>
    proposal.characters.map((c) => ({
      ...c,
      keep: !c.conflict && c.proposed !== c.current,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();
  const toast = useToast();

  const replaced = [
    ...bible
      .filter((b) => b.keep && b.current && b.proposed !== b.current)
      .map((b) => ({ key: `bible.${b.key}`, label: b.label })),
    ...notes
      .filter((c) => c.keep && c.current && c.proposed !== c.current)
      .map((c) => ({ key: `character.${c.id}`, label: `note de ${c.name}` })),
    ...dna
      .filter((d) => d.keep && d.adjusted)
      .map((d) => ({ key: `dna.${d.path}`, label: d.label })),
  ];
  const kept =
    dna.filter((d) => d.keep).length +
    bible.filter((b) => b.keep).length +
    notes.filter((c) => c.keep).length;

  async function save() {
    if (replaced.length) {
      const ok = await confirm({
        title: `Remplacer ${replaced.length} élément${replaced.length > 1 ? "s" : ""} déjà écrit${replaced.length > 1 ? "s" : ""} ?`,
        message: (
          <>
            Tu avais déjà écrit : {replaced.map((r) => r.label).join(", ")}.{" "}
            {replaced.length > 1 ? "Ils seront remplacés" : "Il sera remplacé"}{" "}
            par la proposition (corrigée). Le reste n&apos;est pas touché.
          </>
        ),
        confirmLabel: "Remplacer",
        danger: true,
      });
      if (!ok) return;
    }
    setBusy(true);
    setError(null);
    try {
      const out = await api.applySeriesProposal(projectId, {
        dna: Object.fromEntries(
          dna.filter((d) => d.keep).map((d) => [d.path, d.proposed]),
        ),
        bible: Object.fromEntries(
          bible
            .filter((b) => b.keep && b.proposed.trim())
            .map((b) => [b.key, b.proposed]),
        ),
        character_notes: Object.fromEntries(
          notes
            .filter((c) => c.keep && c.proposed.trim())
            .map((c) => [c.id, c.proposed]),
        ),
        overwrite: replaced.map((r) => r.key),
      });
      toast("ADN et bible enregistrés");
      onApplied(out.written);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 space-y-6" data-testid="creator-proposal">
      <p className="text-sm text-zinc-400">
        Proposition du créateur de série
        {proposal.attempts > 1
          ? ` (après ${proposal.attempts - 1} relance${proposal.attempts > 2 ? "s" : ""})`
          : ""}{" "}
        : rien n&apos;est encore enregistré. Corrige ce que tu veux, décoche ce
        que tu ne gardes pas.
        {proposal.notes && (
          <span className="mt-1 block italic text-zinc-300">
            « {proposal.notes} »
          </span>
        )}
      </p>

      <section aria-labelledby="creator-dna-title">
        <h3
          id="creator-dna-title"
          className="mb-2 text-sm font-semibold text-zinc-200"
        >
          ADN de la série — écarts au genre
          {proposal.genre_name ? ` « ${proposal.genre_name} »` : ""}
        </h3>
        {dna.length === 0 ? (
          <p className="text-sm text-zinc-500">
            Aucun écart : tes réponses suivent le genre.
          </p>
        ) : (
          <ul className="grid gap-2 md:grid-cols-2" data-testid="creator-dna">
            {dna.map((d, i) => (
              <li
                key={d.path}
                className={`rounded-lg border p-3 ${d.keep ? "border-rose-500/40 bg-rose-500/5" : "border-zinc-800 opacity-70"}`}
              >
                <label className="flex items-start gap-2 text-sm text-zinc-100">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 accent-rose-500"
                    checked={d.keep}
                    disabled={busy}
                    onChange={(e) =>
                      setDna((l) =>
                        l.map((x, j) =>
                          j === i ? { ...x, keep: e.target.checked } : x,
                        ),
                      )
                    }
                  />
                  <span className="flex-1">
                    {d.label}
                    <span className="block text-xs text-zinc-400">
                      Genre : {formatValue(d.kind, d.genre_value)}
                      {d.adjusted && (
                        <span className="text-amber-300">
                          {" "}
                          · tu avais réglé{" "}
                          {formatValue(d.kind, d.current_value)}
                        </span>
                      )}
                    </span>
                  </span>
                  <DnaInput
                    kind={d.kind}
                    min={d.min}
                    max={d.max}
                    value={d.proposed}
                    label={d.label}
                    disabled={busy || !d.keep}
                    onChange={(v) =>
                      setDna((l) =>
                        l.map((x, j) => (j === i ? { ...x, proposed: v } : x)),
                      )
                    }
                  />
                </label>
                <p className="mt-1 pl-6 text-xs text-zinc-300">{d.why}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="creator-bible-title">
        <h3
          id="creator-bible-title"
          className="mb-2 text-sm font-semibold text-zinc-200"
        >
          Bible de la série
        </h3>
        <ul className="space-y-3" data-testid="creator-bible">
          {bible.map((b, i) => (
            <TextChange
              key={b.key}
              id={`creator-bible-${b.key}`}
              label={b.label}
              current={b.current}
              proposed={b.proposed}
              keep={b.keep}
              disabled={busy}
              onKeep={(keep) =>
                setBible((l) => l.map((x, j) => (j === i ? { ...x, keep } : x)))
              }
              onText={(proposed) =>
                setBible((l) =>
                  l.map((x, j) => (j === i ? { ...x, proposed } : x)),
                )
              }
            />
          ))}
        </ul>
      </section>

      <section aria-labelledby="creator-notes-title">
        <h3
          id="creator-notes-title"
          className="mb-2 text-sm font-semibold text-zinc-200"
        >
          Notes des personnages
        </h3>
        {notes.length === 0 ? (
          <p className="text-sm text-zinc-500">
            Aucune fiche personnage : crée-les dans la bibliothèque, puis
            relance l&apos;échange pour leur écrire une note.
          </p>
        ) : (
          <ul className="space-y-3" data-testid="creator-notes">
            {notes.map((c, i) => (
              <TextChange
                key={c.id}
                id={`creator-note-${c.id}`}
                label={c.name}
                current={c.current}
                proposed={c.proposed}
                keep={c.keep}
                disabled={busy}
                onKeep={(keep) =>
                  setNotes((l) =>
                    l.map((x, j) => (j === i ? { ...x, keep } : x)),
                  )
                }
                onText={(proposed) =>
                  setNotes((l) =>
                    l.map((x, j) => (j === i ? { ...x, proposed } : x)),
                  )
                }
              />
            ))}
          </ul>
        )}
      </section>

      {error && <Alert>{error}</Alert>}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={save}
          disabled={busy || kept === 0}
          data-testid="creator-apply"
        >
          {busy ? "Enregistrement…" : `Enregistrer la sélection (${kept})`}
        </Button>
        <Button variant="secondary" onClick={onBack} disabled={busy}>
          Revenir aux questions
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Abandonner
        </Button>
        {replaced.length > 0 && (
          <span className="text-xs text-amber-300">
            {replaced.length} élément{replaced.length > 1 ? "s" : ""} déjà écrit
            {replaced.length > 1 ? "s" : ""} sera remplacé
            {replaced.length > 1 ? "s" : ""} (confirmation demandée)
          </span>
        )}
      </div>
    </div>
  );
}

function DnaInput({
  kind,
  min,
  max,
  value,
  label,
  disabled,
  onChange,
}: {
  kind: string;
  min: number | null;
  max: number | null;
  value: DnaValue;
  label: string;
  disabled: boolean;
  onChange: (v: DnaValue) => void;
}) {
  if (kind === "bool") {
    return (
      <select
        aria-label={`${label} : valeur proposée`}
        className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-100"
        value={value ? "oui" : "non"}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value === "oui")}
      >
        <option value="oui">oui</option>
        <option value="non">non</option>
      </select>
    );
  }
  const share = kind === "share";
  return (
    <span className="flex shrink-0 items-center gap-1 text-xs text-zinc-300">
      <input
        type="number"
        aria-label={`${label} : valeur proposée${share ? " (en %)" : ""}`}
        className="w-16 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-right text-xs tabular-nums text-zinc-100"
        min={share ? Math.round((min ?? 0) * 100) : (min ?? undefined)}
        max={share ? Math.round((max ?? 1) * 100) : (max ?? undefined)}
        step={share ? 5 : 1}
        value={share ? Math.round(Number(value) * 100) : Number(value)}
        disabled={disabled}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n))
            onChange(share ? Math.round(n) / 100 : Math.round(n));
        }}
      />
      {share && "%"}
    </span>
  );
}

function TextChange({
  id,
  label,
  current,
  proposed,
  keep,
  disabled,
  onKeep,
  onText,
}: {
  id: string;
  label: string;
  current: string;
  proposed: string;
  keep: boolean;
  disabled: boolean;
  onKeep: (keep: boolean) => void;
  onText: (text: string) => void;
}) {
  const conflict = Boolean(current) && current !== proposed;
  const same = Boolean(current) && current === proposed;
  return (
    <li
      className={`rounded-lg border p-3 ${keep ? "border-rose-500/40 bg-rose-500/5" : "border-zinc-800"}`}
      data-testid={id}
    >
      <label className="flex items-center gap-2 text-sm font-medium text-zinc-100">
        <input
          type="checkbox"
          className="h-4 w-4 accent-rose-500"
          checked={keep}
          disabled={disabled || same}
          onChange={(e) => onKeep(e.target.checked)}
        />
        {label}
        {conflict && (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-normal text-amber-200">
            {keep
              ? "remplacera ce que tu as écrit"
              : "déjà écrit : gardé tel quel"}
          </span>
        )}
        {same && (
          <span className="text-xs font-normal text-zinc-500">inchangé</span>
        )}
        {!current && (
          <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-normal text-emerald-200">
            nouveau
          </span>
        )}
      </label>
      <div className={`mt-2 grid gap-2 ${current ? "md:grid-cols-2" : ""}`}>
        {current && (
          <div>
            <p className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">
              Déjà écrit
            </p>
            <p className="whitespace-pre-line rounded-md border border-zinc-800 bg-zinc-950/60 p-2 text-sm text-zinc-300">
              {current}
            </p>
          </div>
        )}
        <div>
          {current && (
            <p className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">
              Proposé
            </p>
          )}
          <Textarea
            aria-label={`${label} : texte proposé`}
            className="min-h-20"
            value={proposed}
            disabled={disabled || !keep}
            onChange={(e) => onText(e.target.value)}
          />
        </div>
      </div>
    </li>
  );
}
