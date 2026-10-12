"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { HelpLabel } from "@/components/info-tip";
import { PackBadge, RetrievalTester, SUGGESTED_COLLECTIONS, formatTokens } from "@/components/knowledge";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, EmptyState, Field, Input, Loading, PageHeader, Select, Textarea } from "@/components/ui";
import { api, EngineError, errorMessage, type KnowledgeStatus, type PackReport } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function KnowledgeLibraryPage() {
  const collections = useEngineData(() => api.listCollections());
  const projects = useEngineData(() => api.listProjects());
  const status = useEngineData(() => api.knowledgeStatus());

  return (
    <>
      <PageHeader
        title="Bibliothèque de savoir-faire"
        subtitle="Tes fiches de méthode, découpées en passages et injectées dans les agents : le scénariste et le constructeur de prompts image."
      />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section aria-label="Collections" className="space-y-4">
          {collections.loading ? (
            <Loading />
          ) : collections.error ? (
            <Alert>Impossible de charger les collections : {collections.error}</Alert>
          ) : !collections.data?.length ? (
            <EmptyState title="Aucune collection pour l'instant">
              Crée une collection (par exemple « Écriture de scénario »), puis ajoute-y tes fiches .md, .txt ou .pdf.
            </EmptyState>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2" data-testid="collections">
              {collections.data.map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/savoir-faire/${c.id}`}
                    className="block h-full rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 transition-colors hover:border-rose-400/60"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-medium text-zinc-100">{c.name}</span>
                      <span className="flex shrink-0 gap-1">
                        <PackBadge pack={c.pack} />
                        <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300">
                          {c.project_title ? `Série : ${c.project_title}` : "Globale"}
                        </span>
                      </span>
                    </div>
                    {c.description && <p className="mt-1 line-clamp-2 text-sm text-zinc-400">{c.description}</p>}
                    <p className="mt-3 text-xs text-zinc-500">
                      {c.document_count} document{c.document_count > 1 ? "s" : ""} · {c.chunk_count} passage
                      {c.chunk_count > 1 ? "s" : ""} · {formatTokens(c.token_count)}
                      {c.whole && <span className="text-sky-300"> · injectée entière</span>}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Card>
            <h2 className="mb-1 font-semibold text-zinc-100">
              <HelpLabel help="knowledge.search">Tester la recherche</HelpLabel>
            </h2>
            <p className="mb-4 text-sm text-zinc-400">
              Pose une question comme le ferait un agent : les passages sont classés par score hybride (vecteurs +
              mots-clés).
            </p>
            {collections.data && projects.data ? (
              <RetrievalTester collections={collections.data} projects={projects.data} />
            ) : (
              <Loading />
            )}
          </Card>
        </section>

        <aside className="space-y-6">
          <Card>
            <h2 className="mb-4 font-semibold text-zinc-100">
              <HelpLabel help="knowledge.collections">Nouvelle collection</HelpLabel>
            </h2>
            <NewCollectionForm projects={projects.data ?? []} onCreated={collections.reload} />
          </Card>
          <Card>
            <h2 className="mb-3 font-semibold text-zinc-100">
              <HelpLabel help="knowledge.packs">Packs de savoir-faire</HelpLabel>
            </h2>
            <PacksPanel
              reports={status.data?.packs ?? []}
              onUpdated={() => (status.reload(), collections.reload())}
            />
          </Card>
          <Card>
            <h2 className="mb-3 font-semibold text-zinc-100">
              <HelpLabel help="knowledge.indexing">Indexation</HelpLabel>
            </h2>
            {status.data ? (
              <IndexStatus status={status.data} onReindexed={() => (status.reload(), collections.reload())} />
            ) : status.error ? (
              <Alert>{status.error}</Alert>
            ) : (
              <Loading />
            )}
          </Card>
        </aside>
      </div>
    </>
  );
}

function NewCollectionForm({
  projects,
  onCreated,
}: {
  projects: { id: number; title: string }[];
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setError(null);
    try {
      await api.createCollection({ name, description, project_id: scope ? Number(scope) : null });
      toast("Collection créée");
      setName("");
      setDescription("");
      onCreated();
    } catch (err) {
      if (err instanceof EngineError && Object.keys(err.fieldErrors).length) setErrors(err.fieldErrors);
      else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Nom" htmlFor="collection-name" error={errors.name}>
        <Input
          id="collection-name"
          list="collection-suggestions"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Écriture de scénario"
          aria-invalid={Boolean(errors.name)}
        />
      </Field>
      <datalist id="collection-suggestions">
        {SUGGESTED_COLLECTIONS.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <Field label="Description" htmlFor="collection-description" error={errors.description}>
        <Textarea
          id="collection-description"
          className="min-h-16"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Fiches de synthèse sur la structure d'un chapitre hebdomadaire…"
        />
      </Field>
      <Field label="Portée" htmlFor="collection-scope" help="knowledge.scope">
        <Select id="collection-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">Globale (toutes les séries)</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              Série : {p.title}
            </option>
          ))}
        </Select>
      </Field>
      {error && <Alert>{error}</Alert>}
      <Button type="submit" disabled={busy || !name.trim()} data-testid="create-collection">
        {busy ? "Création…" : "Créer la collection"}
      </Button>
    </form>
  );
}

function packSummary(r: PackReport): string {
  if (r.error) return `Pack « ${r.pack} » non importé : ${r.error}`;
  const changes = [
    r.created && `${r.created} ajoutée${r.created > 1 ? "s" : ""}`,
    r.updated && `${r.updated} mise${r.updated > 1 ? "s" : ""} à jour`,
    r.deleted && `${r.deleted} retirée${r.deleted > 1 ? "s" : ""}`,
  ].filter(Boolean);
  return (
    `« ${r.pack} » : ${r.collections} collections, ${r.documents} fiches` +
    (changes.length ? ` (${changes.join(", ")})` : " (à jour)")
  );
}

function PacksPanel({ reports, onUpdated }: { reports: PackReport[]; onUpdated: () => void }) {
  const [busy, setBusy] = useState(false);
  const [latest, setLatest] = useState<PackReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const shown = latest ?? reports;

  async function update() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.updateKnowledgePacks();
      setLatest(r);
      const failed = r.some((p) => p.error);
      toast(failed ? "Mise à jour des packs incomplète" : "Packs à jour", failed ? "error" : "success");
      onUpdated();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 text-sm" data-testid="packs">
      <p className="text-xs text-zinc-400">
        Fiches de mise en scène livrées avec l&apos;appli, rangées en collections « pack » (lecture seule). Tes collections
        ne sont jamais touchées.
      </p>
      {shown.length ? (
        <ul className="space-y-2">
          {shown.map((r) => (
            <li key={r.pack}>
              <p className={r.error ? "text-red-400" : "text-zinc-200"}>{packSummary(r)}</p>
              {r.warnings.map((w) => (
                <p key={w} className="text-xs text-amber-300">
                  {w}
                </p>
              ))}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-zinc-500">Aucun pack importé depuis le démarrage.</p>
      )}
      {error && <Alert>{error}</Alert>}
      <Button variant="secondary" onClick={update} disabled={busy} data-testid="update-packs">
        {busy ? "Mise à jour…" : "Mettre à jour les packs"}
      </Button>
    </div>
  );
}

function IndexStatus({
  status,
  onReindexed,
}: {
  status: KnowledgeStatus;
  onReindexed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const toast = useToast();

  async function reindex() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.reindexKnowledge();
      setMessage(
        r.errors.length
          ? `Réindexation incomplète : ${r.errors.join(" · ")}`
          : `${r.documents} document${r.documents > 1 ? "s" : ""} réindexé${r.documents > 1 ? "s" : ""}.`,
      );
      toast(r.errors.length ? "Réindexation incomplète" : "Réindexation terminée", r.errors.length ? "error" : "success");
      onReindexed();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-zinc-500">Embeddings</dt>
        <dd className={status.available ? "text-zinc-200" : "text-red-400"} title={status.detail ?? undefined}>
          {status.model ?? status.provider ?? "—"}
          {!status.available && " ⚠"}
        </dd>
        <dt className="text-zinc-500">Vecteurs</dt>
        <dd className="text-zinc-200">SQLite + numpy</dd>
        <dt className="text-zinc-500">Passages</dt>
        <dd className="text-zinc-200">
          {status.chunks}
          {status.stale_chunks > 0 && <span className="text-amber-300"> · {status.stale_chunks} à réindexer</span>}
        </dd>
        <dt className="text-zinc-500">
          <HelpLabel help="knowledge.whole">Petite collection</HelpLabel>
        </dt>
        <dd className="text-zinc-200">moins de {formatTokens(status.small_collection_tokens)} : injectée entière</dd>
      </dl>
      {status.detail && <Alert>{status.detail}</Alert>}
      {status.stale_chunks > 0 && (
        <Button variant="secondary" onClick={reindex} disabled={busy || !status.available}>
          {busy ? "Réindexation…" : "Réindexer"}
        </Button>
      )}
      {message && <p className="text-xs text-zinc-400">{message}</p>}
      <div>
        <h3 className="mb-2 mt-4 text-xs uppercase tracking-wide text-zinc-500">
          <HelpLabel help="knowledge.agents">Ce que lit chaque agent</HelpLabel>
        </h3>
        <ul className="space-y-2">
          {status.agents.map((a) => (
            <li key={a.role}>
              <p className="text-zinc-200">{a.label}</p>
              <p className="text-xs text-zinc-500">
                {a.collections.length ? a.collections.join(", ") : "aucune collection"}
                {a.series_collections && " + collections de la série"}
                {a.bible && " + bible"} · {formatTokens(a.budget_tokens)} · top {a.top_k}
                {a.fragment_budget_tokens !== null &&
                  ` pour le rédacteur de prompt · note des fragments : ${formatTokens(a.fragment_budget_tokens)}, top ${a.fragment_top_k}`}
                {a.source === "profile" ? " · profil de l'agent" : " · presets/knowledge.yaml"}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
