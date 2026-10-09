"use client";

// Savoir-faire : passages (sources, scores), zone d'envoi de documents, panneau de test de la recherche.
import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { Alert, Button, Field, Input, Select } from "@/components/ui";
import { api, errorMessage, type KnowledgeCollection, type Passage, type Project, type SearchResult } from "@/lib/api";

export const SOURCE_LABELS: Record<string, string> = { text: "Texte collé", md: "Markdown", txt: "Texte", pdf: "PDF" };

/** Noms suggérés à la création d'une collection. */
export const SUGGESTED_COLLECTIONS = [
  "Écriture de scénario",
  "Rythme et découpage",
  "Design de personnages",
  "Mise en page",
  "Humour jeunesse",
];

export function formatTokens(n: number): string {
  return `${n.toLocaleString("fr-FR")} jeton${n > 1 ? "s" : ""}`;
}

function formatScore(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function Tags({ tags }: { tags: string[] }) {
  if (!tags.length) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {tags.map((t) => (
        <span key={t} className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300">
          {t}
        </span>
      ))}
    </span>
  );
}

/** Passages classés : source (document › section), collection, scores, extrait. */
export function PassageList({
  passages,
  showScores = true,
  excerpt,
  testId = "passages",
}: {
  passages: Passage[];
  showScores?: boolean;
  excerpt?: number;
  testId?: string;
}) {
  return (
    <ol className="space-y-3" data-testid={testId}>
      {passages.map((p, i) => {
        const text = excerpt && p.text.length > excerpt ? `${p.text.slice(0, excerpt).trimEnd()}…` : p.text;
        return (
          <li
            key={p.chunk_id}
            className={`rounded-lg border p-3 ${p.selected ? "border-rose-500/40 bg-rose-500/5" : "border-zinc-800 bg-zinc-950/60"}`}
            data-testid="passage"
          >
            <div className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
              <span className="font-mono text-xs text-zinc-500">#{i + 1}</span>
              <span className="font-medium text-zinc-100">« {p.document_title} »</span>
              {p.heading && <span className="text-xs text-zinc-400">{p.heading}</span>}
              <span className="text-xs text-zinc-500">collection « {p.collection_name} »</span>
              {p.mode === "whole" && (
                <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs text-sky-300">collection entière</span>
              )}
              {p.selected && showScores && (
                <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-xs text-rose-300">injecté</span>
              )}
              {showScores && (
                <span className="ml-auto text-xs text-zinc-400" title="Score hybride (vecteurs · mots-clés)">
                  score <strong className="text-zinc-100">{formatScore(p.score)}</strong>
                  <span className="text-zinc-500">
                    {" "}
                    · vecteurs {formatScore(p.vector_score)} · mots-clés {formatScore(p.keyword_score)}
                  </span>
                </span>
              )}
            </div>
            <p className="whitespace-pre-line text-sm text-zinc-300">{text}</p>
            <p className="mt-1 text-xs text-zinc-600">{formatTokens(p.tokens)}</p>
          </li>
        );
      })}
    </ol>
  );
}

const ACCEPTED = [".md", ".markdown", ".txt", ".pdf"];
const MAX_BYTES = 20 * 1024 * 1024;

/** Zone de glisser-déposer de documents .md / .txt / .pdf (clic = sélecteur de fichiers). */
export function DocumentDropzone({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [ignored, setIgnored] = useState<string[]>([]);

  function accept(list: FileList | null) {
    if (!list) return;
    const files = Array.from(list);
    const okType = (f: File) => ACCEPTED.some((ext) => f.name.toLowerCase().endsWith(ext));
    const ok = files.filter((f) => okType(f) && f.size <= MAX_BYTES);
    setIgnored(files.filter((f) => !ok.includes(f)).map((f) => f.name));
    if (ok.length) onFiles(ok);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    if (!disabled) accept(e.dataTransfer.files);
  }

  return (
    <div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        data-testid="document-dropzone"
        className={`flex w-full flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
          over ? "border-rose-400 bg-rose-500/10" : "border-zinc-700 hover:border-zinc-500 hover:bg-zinc-900"
        }`}
      >
        <span className="text-sm font-medium text-zinc-200">Glisse tes fiches ici</span>
        <span className="text-xs text-zinc-500">ou clique pour parcourir · .md, .txt, .pdf · 20 Mo max</span>
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED.join(",")}
        className="hidden"
        aria-label="Ajouter des documents"
        onChange={(e) => {
          accept(e.target.files);
          e.target.value = "";
        }}
      />
      {ignored.length > 0 && (
        <p className="mt-2 text-xs text-amber-400" role="alert">
          Ignoré (format non accepté ou plus de 20 Mo) : {ignored.join(", ")}
        </p>
      )}
    </div>
  );
}

/** Panneau de test : une question, une collection ou une série → passages classés avec leurs scores. */
export function RetrievalTester({
  collections,
  projects,
  defaultScope = "",
}: {
  collections: KnowledgeCollection[];
  projects: Project[];
  defaultScope?: string;
}) {
  const [query, setQuery] = useState("");
  const [chosen, setScope] = useState(defaultScope);
  // Choix encore valable, sinon la première collection (ou série) de la liste à jour.
  const options = [...collections.map((c) => `c${c.id}`), ...projects.map((p) => `p${p.id}`)];
  const scope = options.includes(chosen) ? chosen : (options[0] ?? "");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || !scope) return;
    setBusy(true);
    setError(null);
    try {
      const id = Number(scope.slice(1));
      setResult(
        await api.searchKnowledge(
          scope.startsWith("c") ? { query, collection_ids: [id] } : { query, project_id: id },
        ),
      );
    } catch (err) {
      setError(errorMessage(err));
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <form onSubmit={run} className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] md:items-end">
        <Field label="Question" htmlFor="retrieval-query">
          <Input
            id="retrieval-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Comment finir un chapitre sur un cliffhanger ?"
          />
        </Field>
        <Field label="Chercher dans" htmlFor="retrieval-scope">
          <Select id="retrieval-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
            {!collections.length && !projects.length && <option value="">—</option>}
            {collections.length > 0 && (
              <optgroup label="Collections">
                {collections.map((c) => (
                  <option key={c.id} value={`c${c.id}`}>
                    {c.name}
                    {c.project_title ? ` (${c.project_title})` : ""}
                  </option>
                ))}
              </optgroup>
            )}
            {projects.length > 0 && (
              <optgroup label="Séries (leurs collections + les globales, et la bible)">
                {projects.map((p) => (
                  <option key={p.id} value={`p${p.id}`}>
                    {p.title}
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
        </Field>
        <Button type="submit" disabled={busy || !query.trim() || !scope} data-testid="run-retrieval">
          {busy ? "Recherche…" : "Tester la recherche"}
        </Button>
      </form>
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      {result && (
        <div className="mt-5 space-y-3" data-testid="retrieval-result">
          <p className="text-xs text-zinc-400">
            {result.passages.length} passage{result.passages.length > 1 ? "s" : ""} classé
            {result.passages.length > 1 ? "s" : ""} · en surbrillance, ce qu&apos;un agent recevrait (top {result.top_k},{" "}
            {formatTokens(result.selected_tokens)} sur un budget de {formatTokens(result.budget_tokens)}) · collections :{" "}
            {result.collections.join(", ") || "aucune"}
          </p>
          {result.warning && <Alert tone="info">{result.warning}</Alert>}
          {result.bible && (
            <Alert tone="info">
              Bible de la série : toujours injectée ({formatTokens(result.bible.tokens)}
              {result.bible.truncated ? ", raccourcie au budget" : ""}).
            </Alert>
          )}
          {result.passages.length ? (
            <PassageList passages={result.passages} excerpt={600} />
          ) : (
            <p className="text-sm text-zinc-500">Aucun passage dans cette sélection.</p>
          )}
        </div>
      )}
    </div>
  );
}
