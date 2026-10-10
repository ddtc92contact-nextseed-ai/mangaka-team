"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { SOURCE_LABELS, Tags, formatTokens } from "@/components/knowledge";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Field, Input, Loading, PageHeader, Textarea } from "@/components/ui";
import { api, EngineError, errorMessage, parseTags, type KnowledgeDocument } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function DocumentPage() {
  const id = Number(useParams<{ id: string }>().id);
  const router = useRouter();
  const doc = useEngineData(() => api.getDocument(id), [id]);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function remove() {
    if (!doc.data || !window.confirm(`Supprimer « ${doc.data.title} » et ses passages ?`)) return;
    try {
      await api.deleteDocument(id);
      toast("Document supprimé");
      router.push(`/savoir-faire/${doc.data.collection_id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (doc.loading) return <Loading />;
  if (doc.error || !doc.data) return <Alert>{doc.error ?? "Document introuvable"}</Alert>;
  const d = doc.data;

  return (
    <>
      <PageHeader
        title={d.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <Link href={`/savoir-faire/${d.collection_id}`} className="hover:text-zinc-200">
              ← {d.collection_name}
            </Link>
            <span>{SOURCE_LABELS[d.source] ?? d.source}</span>
            {d.original_name && <span>{d.original_name}</span>}
            <Tags tags={d.tags} />
          </span>
        }
        actions={
          <Button variant="danger" onClick={remove}>
            Supprimer
          </Button>
        }
      />
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-4 font-semibold text-zinc-100">Modifier</h2>
          <DocumentForm key={d.updated_at} doc={d} onSaved={doc.setData} />
        </Card>
        <section aria-label="Passages">
          <h2 className="mb-1 text-lg font-semibold text-zinc-100">
            {d.chunks.length} passage{d.chunks.length > 1 ? "s" : ""}
          </h2>
          <p className="mb-3 text-xs text-zinc-500">
            Découpés aux titres puis aux paragraphes · {formatTokens(d.token_count)} au total
          </p>
          {d.index_error && (
            <div className="mb-3">
              <Alert>{d.index_error}</Alert>
            </div>
          )}
          <ol className="space-y-3" data-testid="chunks">
            {d.chunks.map((c) => (
              <li key={c.id} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3" data-testid="chunk">
                <div className="mb-1 flex flex-wrap items-baseline gap-2 text-xs">
                  <span className="font-mono text-zinc-500">#{c.index + 1}</span>
                  <span className="font-medium text-zinc-200">{c.heading || "(sans titre)"}</span>
                  <span className="ml-auto text-zinc-500">{formatTokens(c.token_count)}</span>
                  <span className={c.embedded ? "text-emerald-300" : "text-amber-300"}>
                    {c.embedded ? "vectorisé" : "sans vecteur"}
                  </span>
                </div>
                <p className="whitespace-pre-line text-sm text-zinc-300">{c.text}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  );
}

function DocumentForm({ doc, onSaved }: { doc: KnowledgeDocument; onSaved: (d: KnowledgeDocument) => void }) {
  const [title, setTitle] = useState(doc.title);
  const [tags, setTags] = useState(doc.tags.join(", "));
  const [content, setContent] = useState(doc.content);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const toast = useToast();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setSaved(false);
    try {
      onSaved(await api.updateDocument(doc.id, { title, content, tags: parseTags(tags) }));
      setSaved(true);
      toast("Document enregistré et réindexé");
    } catch (err) {
      setErrors(err instanceof EngineError && Object.keys(err.fieldErrors).length ? err.fieldErrors : { form: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Titre" htmlFor="doc-title" error={errors.title}>
        <Input id="doc-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label="Étiquettes" htmlFor="doc-tags" hint="Séparées par des virgules." help="knowledge.tags">
        <Input id="doc-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
      </Field>
      <Field
        label="Texte"
        htmlFor="doc-content"
        error={errors.content}
        hint="Enregistrer réindexe le document : nouveaux passages et nouveaux vecteurs."
      >
        <Textarea
          id="doc-content"
          className="min-h-96 font-mono text-xs"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </Field>
      {errors.form && <Alert>{errors.form}</Alert>}
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={busy || !title.trim() || !content.trim()}>
          {busy ? "Réindexation…" : "Enregistrer"}
        </Button>
        {saved && (
          <span className="text-xs text-emerald-300" role="status">
            Enregistré et réindexé.
          </span>
        )}
      </div>
    </form>
  );
}
