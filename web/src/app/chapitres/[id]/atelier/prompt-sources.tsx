"use client";

// « Sources utilisées » du prompt actuel de la case : les fiches de savoir-faire que le rédacteur de prompt
// a vraiment reçues pour l'écrire, et la date de la rédaction (preuve que le pack a servi).
import { InfoTip } from "@/components/info-tip";
import { PassageList, formatTokens } from "@/components/knowledge";
import type { PanelDetail } from "@/lib/api";

/** Les dates du moteur sans fuseau sont en UTC. */
function engineDate(at: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : `${at}Z`);
}

export function PromptSourcesBlock({ panel }: { panel: PanelDetail }) {
  const sources = panel.prompt_sources;
  if (!sources) {
    if (panel.prompt_source !== "ia" || panel.final_prompt_manual) return null;
    return (
      <p className="text-[11px] text-zinc-500" data-testid="prompt-sources-missing">
        Sources utilisées : prompt rédigé avant leur suivi — il sera réécrit à la prochaine génération.
      </p>
    );
  }
  const count = sources.passages.length;
  const collections = [...new Set(sources.passages.map((p) => p.collection_name))];
  const written = engineDate(sources.written_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  return (
    <details className="text-xs" data-testid="prompt-sources">
      <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">
        Sources utilisées{" "}
        <span className="text-zinc-500">
          · prompt rédigé le {written} · {count} fiche{count > 1 ? "s" : ""} de savoir-faire
        </span>
      </summary>
      <div className="mt-2 space-y-2">
        <p className="flex items-center gap-1.5 text-zinc-500">
          Ce que le rédacteur de prompt a reçu pour écrire le prompt actuel.
          <InfoTip help="atelier.prompt_sources" label="Sources utilisées" />
        </p>
        {sources.edited && (
          <p className="text-amber-200/80">Le prompt a été retouché depuis : ces sources sont celles de sa rédaction.</p>
        )}
        <p className="text-zinc-500" data-testid="prompt-sources-collections">
          {collections.length ? `Collections : ${collections.join(", ")}` : "Aucune fiche reçue (savoir-faire vide ou budget à 0)."}
          {count > 0 && ` · ${formatTokens(sources.tokens)} sur ${formatTokens(sources.budget_tokens)}`}
        </p>
        {count > 0 && (
          <PassageList passages={sources.passages} showScores={false} excerpt={240} testId="prompt-sources-passages" />
        )}
        {sources.bible && <p className="text-zinc-400">Notes de la bible : {sources.bible}</p>}
      </div>
    </details>
  );
}
