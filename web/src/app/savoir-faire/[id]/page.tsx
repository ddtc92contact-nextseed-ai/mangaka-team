"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { HelpLabel } from "@/components/info-tip";
import { DocumentDropzone, RetrievalTester, SOURCE_LABELS, Tags, formatTokens } from "@/components/knowledge";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, EmptyState, Field, Input, Loading, PageHeader, Select, Textarea } from "@/components/ui";
import { api, EngineError, errorMessage, parseTags, type KnowledgeCollection } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

export default function CollectionPage() {
  const id = Number(useParams<{ id: string }>().id);
  const router = useRouter();
  const collection = useEngineData(() => api.getCollection(id), [id]);
  const documents = useEngineData(() => api.listDocuments(id), [id]);
  const projects = useEngineData(() => api.listProjects());
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  function refresh() {
    documents.reload();
    collection.reload();
  }

  async function remove() {
    if (!collection.data) return;
    if (!window.confirm(`Supprimer la collection « ${collection.data.name} » et tous ses documents ?`)) return;
    try {
      await api.deleteCollection(id);
      toast("Collection supprimée");
      router.push("/savoir-faire");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (collection.loading) return <Loading />;
  if (collection.error || !collection.data) return <Alert>{collection.error ?? "Collection introuvable"}</Alert>;
  const c = collection.data;

  return (
    <>
      <PageHeader
        title={c.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <Link href="/savoir-faire" className="hover:text-zinc-200">
              ← Bibliothèque
            </Link>
            <span>{c.project_title ? `Rattachée à la série « ${c.project_title} »` : "Collection globale"}</span>
            <span>
              {c.document_count} document{c.document_count > 1 ? "s" : ""} · {c.chunk_count} passage
              {c.chunk_count > 1 ? "s" : ""} · {formatTokens(c.token_count)}
            </span>
            {c.whole && <span className="text-sky-300">injectée entière (petite collection)</span>}
          </span>
        }
        actions={
          <>
            <Button variant="secondary" onClick={() => setEditing((v) => !v)}>
              {editing ? "Fermer" : "Modifier"}
            </Button>
            <Button variant="danger" onClick={remove}>
              Supprimer
            </Button>
          </>
        }
      />
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      {c.description && !editing && <p className="-mt-4 mb-6 max-w-3xl text-sm text-zinc-400">{c.description}</p>}
      {editing && (
        <Card className="mb-6">
          <CollectionForm
            collection={c}
            projects={projects.data ?? []}
            onSaved={(next) => {
              collection.setData(next);
              setEditing(false);
              toast("Collection enregistrée");
            }}
          />
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-label="Documents" className="space-y-3">
          <h2 className="text-lg font-semibold text-zinc-100">Documents</h2>
          {documents.loading && !documents.data ? (
            <Loading />
          ) : documents.error ? (
            <Alert>{documents.error}</Alert>
          ) : !documents.data?.length ? (
            <EmptyState title="Collection vide">Envoie un fichier ou colle un texte à droite.</EmptyState>
          ) : (
            <ul className="space-y-2" data-testid="documents">
              {documents.data.map((d) => (
                <li key={d.id}>
                  <Link
                    href={`/savoir-faire/documents/${d.id}`}
                    className="block rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 transition-colors hover:border-rose-400/60"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-zinc-100">{d.title}</span>
                      <span className="text-xs text-zinc-500">{SOURCE_LABELS[d.source] ?? d.source}</span>
                      <Tags tags={d.tags} />
                      <span className="ml-auto text-xs text-zinc-400">
                        {d.chunk_count} passage{d.chunk_count > 1 ? "s" : ""} · {formatTokens(d.token_count)}
                      </span>
                    </div>
                    {d.original_name && <p className="mt-1 text-xs text-zinc-500">{d.original_name}</p>}
                    {d.index_error && <p className="mt-1 text-xs text-amber-300">{d.index_error}</p>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Card className="mt-6">
            <h2 className="mb-4 font-semibold text-zinc-100">
              <HelpLabel help="knowledge.search">Tester la recherche dans cette collection</HelpLabel>
            </h2>
            <RetrievalTester collections={[c]} projects={[]} defaultScope={`c${c.id}`} />
          </Card>
        </section>

        <aside className="space-y-6">
          <Card>
            <h2 className="mb-4 font-semibold text-zinc-100">Envoyer des fichiers</h2>
            <UploadForm collectionId={id} onUploaded={refresh} />
          </Card>
          <Card>
            <h2 className="mb-4 font-semibold text-zinc-100">Coller un texte</h2>
            <PasteForm collectionId={id} onCreated={refresh} />
          </Card>
        </aside>
      </div>
    </>
  );
}

function CollectionForm({
  collection,
  projects,
  onSaved,
}: {
  collection: KnowledgeCollection;
  projects: { id: number; title: string }[];
  onSaved: (c: KnowledgeCollection) => void;
}) {
  const [name, setName] = useState(collection.name);
  const [description, setDescription] = useState(collection.description);
  const [scope, setScope] = useState(collection.project_id ? String(collection.project_id) : "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    try {
      onSaved(await api.updateCollection(collection.id, { name, description, project_id: scope ? Number(scope) : null }));
    } catch (err) {
      setErrors(err instanceof EngineError && Object.keys(err.fieldErrors).length ? err.fieldErrors : { form: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-4 md:grid-cols-2" noValidate>
      <Field label="Nom" htmlFor="edit-name" error={errors.name}>
        <Input id="edit-name" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Portée" htmlFor="edit-scope" help="knowledge.scope">
        <Select id="edit-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">Globale (toutes les séries)</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              Série : {p.title}
            </option>
          ))}
        </Select>
      </Field>
      <div className="md:col-span-2">
        <Field label="Description" htmlFor="edit-description" error={errors.description}>
          <Textarea id="edit-description" className="min-h-16" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </div>
      {errors.form && (
        <div className="md:col-span-2">
          <Alert>{errors.form}</Alert>
        </div>
      )}
      <div>
        <Button type="submit" disabled={busy || !name.trim()}>
          {busy ? "Enregistrement…" : "Enregistrer"}
        </Button>
      </div>
    </form>
  );
}

function UploadForm({ collectionId, onUploaded }: { collectionId: number; onUploaded: () => void }) {
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  async function upload(files: File[]) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const docs = await api.uploadDocuments(collectionId, files, parseTags(tags));
      const chunks = docs.reduce((n, d) => n + d.chunks.length, 0);
      toast(`${docs.length} document${docs.length > 1 ? "s" : ""} ajouté${docs.length > 1 ? "s" : ""}`);
      setMessage(
        `${docs.length} document${docs.length > 1 ? "s" : ""} ajouté${docs.length > 1 ? "s" : ""}, ${chunks} passage${chunks > 1 ? "s" : ""}.`,
      );
      onUploaded();
    } catch (err) {
      setError(err instanceof EngineError && err.fieldErrors.files ? err.fieldErrors.files : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <Field label="Étiquettes (séparées par des virgules)" htmlFor="upload-tags" help="knowledge.tags">
        <Input id="upload-tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="méthode, rythme" />
      </Field>
      <DocumentDropzone onFiles={upload} disabled={busy} />
      {busy && <p className="text-xs text-zinc-400">Extraction et indexation…</p>}
      {message && (
        <p className="text-xs text-emerald-300" role="status">
          {message}
        </p>
      )}
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

function PasteForm({ collectionId, onCreated }: { collectionId: number; onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [content, setContent] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    try {
      await api.createDocument(collectionId, { title, content, tags: parseTags(tags) });
      toast("Texte ajouté à la collection");
      setTitle("");
      setTags("");
      setContent("");
      onCreated();
    } catch (err) {
      setErrors(err instanceof EngineError && Object.keys(err.fieldErrors).length ? err.fieldErrors : { form: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Titre" htmlFor="paste-title" error={errors.title}>
        <Input id="paste-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Le cliffhanger" />
      </Field>
      <Field label="Étiquettes" htmlFor="paste-tags" hint="Séparées par des virgules." help="knowledge.tags">
        <Input id="paste-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
      </Field>
      <Field label="Texte (Markdown accepté)" htmlFor="paste-content" error={errors.content}>
        <Textarea
          id="paste-content"
          className="min-h-40 font-mono text-xs"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={"# Cliffhanger\n\nTermine sur une question ouverte…"}
        />
      </Field>
      {errors.form && <Alert>{errors.form}</Alert>}
      <Button type="submit" disabled={busy || !title.trim() || !content.trim()}>
        {busy ? "Indexation…" : "Ajouter le texte"}
      </Button>
    </form>
  );
}
