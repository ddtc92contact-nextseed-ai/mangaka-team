"use client";

// « Savoir-faire de la case » : ce que lit le Dessinateur pour cette case — passages entiers envoyés au
// rédacteur de prompt (IA) et note courte du prompt par fragments, avec leurs jetons.
import { useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { PassageList, formatTokens } from "@/components/knowledge";
import { Alert, Loading } from "@/components/ui";
import { api, errorMessage, type PanelKnowledge, type PanelKnowledgePart } from "@/lib/api";

function Part({
  title,
  part,
  testId,
  showText,
}: {
  title: string;
  part: PanelKnowledgePart;
  testId: string;
  showText?: boolean;
}) {
  const count = part.passages.length;
  return (
    <section className="space-y-2" data-testid={testId}>
      <h4 className="text-xs font-semibold text-zinc-200">
        {title}{" "}
        <span className="font-normal text-zinc-500">
          · {count} passage{count > 1 ? "s" : ""} (top {part.top_k}) · {formatTokens(part.tokens)} sur{" "}
          {formatTokens(part.budget_tokens)}
          {part.bible && ` · bible : ${formatTokens(part.bible_tokens)}`}
        </span>
      </h4>
      {part.budget_tokens === 0 ? (
        <p className="text-xs text-zinc-500">Budget à 0 : aucun savoir-faire.</p>
      ) : count === 0 ? (
        <p className="text-xs text-zinc-500">Aucun passage retenu dans ce budget.</p>
      ) : showText ? (
        <p className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-xs text-zinc-300">
          {part.text} <span className="text-zinc-500">({formatTokens(part.text_tokens)})</span>
        </p>
      ) : (
        <PassageList passages={part.passages} showScores={false} excerpt={240} testId={`${testId}-passages`} />
      )}
      {part.bible && <p className="text-xs text-zinc-400">Notes de la bible : {part.bible}</p>}
    </section>
  );
}

export function PanelKnowledgeBlock({ panelId }: { panelId: number }) {
  const [data, setData] = useState<PanelKnowledge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await api.panelKnowledge(panelId));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <details
      className="text-xs"
      data-testid="panel-knowledge"
      onToggle={(e) => {
        if ((e.currentTarget as HTMLDetailsElement).open) void load();
      }}
    >
      <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">Savoir-faire de la case</summary>
      <div className="mt-2 space-y-3">
        <p className="flex items-center gap-1.5 text-zinc-500">
          Ce que lit le Dessinateur pour cette case : une recherche, deux budgets.
          <InfoTip help="atelier.knowledge" label="Savoir-faire de la case" />
        </p>
        {loading && !data && <Loading />}
        {error && <Alert>{error}</Alert>}
        {data && (
          <>
            <p className="text-zinc-500">
              Recherche : « {data.query || "—"} » · collections :{" "}
              {data.collections.length ? data.collections.join(", ") : "aucune"}
            </p>
            {data.warning && <Alert tone="info">{data.warning}</Alert>}
            <Part title="Rédacteur de prompt (IA)" part={data.writer} testId="panel-knowledge-writer" />
            <Part title="Note des fragments" part={data.fragments} testId="panel-knowledge-fragments" showText />
          </>
        )}
      </div>
    </details>
  );
}
