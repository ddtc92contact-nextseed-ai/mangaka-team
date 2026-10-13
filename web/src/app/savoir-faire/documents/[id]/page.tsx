"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useConfirm } from "@/components/confirm";
import { PackBadge, SOURCE_LABELS, Tags, formatTokens } from "@/components/knowledge";
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
  const confirm = useConfirm();

  async function remove() {
    if (!doc.data) return;
    const ok = await confirm({
      title: "Supprimer le document ?",
      message: `« ${doc.data.title} » et ses passages seront supprimés.`,
      confirmLabel: "Supprimer",
      danger: true,
    });
    if (!ok) return;
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
            <PackBadge pack={d.pack} />
            <Tags tags={d.tags} />
          </span>
        }
        actions={
          d.pack ? undefined : (
            <Button variant="danger" onClick={remove}>
              Supprimer
            </Button>
          )
        }
      />
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        {d.pack ? (
          <PackFiche doc={d} />
        ) : (
          <Card>
            <h2 className="mb-4 font-semibold text-zinc-100">Modifier</h2>
            <DocumentForm key={d.updated_at} doc={d} onSaved={doc.setData} />
          </Card>
        )}
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

/** Libellés des champs du bloc meta d'une fiche de pack. */
const META_LABELS: Record<string, string> = {
  id: "Identifiant",
  path: "Chemin d'origine",
  type: "Type",
  agents: "Agents visés",
  intent: "Intentions",
  shot_scale: "Échelle de plan",
  camera_angle: "Angle",
  motion_level: "Mouvement",
  genres: "Genres",
  avoid_when: "À éviter quand",
  pairs_with: "Va avec",
  plan_appli: "Fiche de référence du plan",
  angle_appli: "Fiche de référence de l'angle",
};

function metaValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

/** Fiche d'un pack livré : lecture seule, champs du bloc meta et mots-clés de recherche. */
function PackFiche({ doc }: { doc: KnowledgeDocument }) {
  const meta = Object.entries(doc.meta ?? {}).filter(([, v]) => metaValue(v));
  return (
    <Card>
      <h2 className="mb-1 font-semibold text-zinc-100">Fiche du pack « {doc.pack} »</h2>
      <p className="mb-4 text-xs text-zinc-400">
        Lecture seule : modifie presets/knowledge_packs/ puis « Mettre à jour les packs » (Bibliothèque). Le bloc meta
        de la fiche est retiré du texte injecté dans les agents ; ses champs sont gardés ici.
      </p>
      {meta.length > 0 && (
        <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid="pack-meta">
          {meta.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-zinc-500">{META_LABELS[key] ?? key}</dt>
              <dd className="break-words font-mono text-xs leading-5 text-zinc-200">{metaValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {doc.keywords && (
        <p className="text-xs text-zinc-400">
          <span className="text-zinc-500">Mots-clés de recherche (jamais injectés) : </span>
          {doc.keywords}
        </p>
      )}
    </Card>
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
