"""Savoir-faire : base de connaissances locale (RAG) et bible de série, injectées dans les agents.

1. **Documents** : .md / .txt / .pdf (texte extrait par pypdf) ou texte collé, rangés en collections
   globales ou rattachées à une série ;
2. **découpage** attentif aux titres Markdown (un passage ne chevauche jamais deux sections), puis aux
   paragraphes, phrases et mots pour respecter `chunking.max_tokens` ;
3. **indexation** : un vecteur par passage (fournisseur d'embeddings, cf. `providers/embedding`) stocké en
   BLOB float32 dans SQLite, et le texte dans l'index plein texte FTS5 `knowledge_fts`. Recherche
   vectorielle en numpy (force brute) : sqlite-vec n'est pas utilisé, les volumes visés (quelques
   milliers de passages) se comparent en quelques millisecondes et l'on évite de charger une extension
   SQLite dans chaque connexion. Toute modification d'un document le réindexe ;
4. **recherche hybride** : score = poids × cosinus + poids × BM25 normalisé (le meilleur passage par
   mots-clés vaut 1), top-k, budget de jetons par agent ; une petite collection est injectée entière ;
5. **bible** de la série : toujours injectée dans les agents de cette série, jamais ailleurs.

Les jetons sont estimés (≈ 4 caractères par jeton) : aucun tokenizer n'est chargé.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..presets import KnowledgeAgent, KnowledgeSettings
from ..providers.embedding import EmbeddingError, EmbeddingProvider, normalize_words
from ..store.models import (
    Chapter,
    ChapterStatus,
    Character,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    SeriesBible,
)
from .library import SeriesLibrary

CHARS_PER_TOKEN = 4
KEYWORDS_WEIGHT = 4.0  # poids BM25 de la colonne `keywords` de l'index FTS (texte et titre de section : 1)
SOURCES = {".md": "md", ".markdown": "md", ".txt": "txt", ".pdf": "pdf"}
# Chapitre « validé » : son résumé rejoint la bible de la série.
VALIDATED_STATUSES = (ChapterStatus.ready, ChapterStatus.published)


class KnowledgeError(Exception):
    """Erreur lisible (en français) du savoir-faire."""


def estimate_tokens(value: str) -> int:
    return math.ceil(len(value.strip()) / CHARS_PER_TOKEN) if value.strip() else 0


# --- extraction ------------------------------------------------------------------
def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise KnowledgeError(f"PDF illisible ({exc})") from None
    content = "\n\n".join(p for p in pages if p)
    if not content.strip():
        raise KnowledgeError("aucun texte extractible dans ce PDF (document scanné ?)")
    return content


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """(source, texte) d'un fichier envoyé ; `KnowledgeError` si le format n'est pas pris en charge."""
    suffix = PurePath(filename).suffix.lower()
    source = SOURCES.get(suffix)
    if source is None:
        raise KnowledgeError(f"format non pris en charge : « {suffix or filename} » (acceptés : .md, .txt, .pdf)")
    content = extract_pdf(data) if source == "pdf" else _decode(data)
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not content:
        raise KnowledgeError("le fichier est vide")
    return source, content


def title_from(filename: str, content: str) -> str:
    """Premier titre Markdown du texte, sinon nom du fichier sans extension."""
    for line in content.splitlines()[:30]:
        m = _HEADING.match(line)
        if m:
            return m.group(2).strip()[:200]
    return PurePath(filename).stem.replace("_", " ").strip()[:200] or "Sans titre"


# --- découpage -------------------------------------------------------------------
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


@dataclass
class Chunk:
    heading: str
    text: str
    tokens: int


def split_sections(content: str) -> list[tuple[str, str]]:
    """[(« Titre › Sous-titre », corps)] dans l'ordre ; les titres dans un bloc de code ne comptent pas."""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        value = "\n".join(body).strip()
        if value:
            sections.append((" › ".join(t for _, t in stack), value))
        body.clear()

    for line in content.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            stack = [(lvl, t) for lvl, t in stack if lvl < level] + [(level, m.group(2).strip())]
        else:
            body.append(line)
    flush()
    return sections


def _units(paragraph: str, max_tokens: int) -> list[str]:
    """Découpe un paragraphe trop long en phrases, puis en mots."""
    if estimate_tokens(paragraph) <= max_tokens:
        return [paragraph]
    out: list[str] = []
    for sentence in _SENTENCE.split(paragraph):
        if estimate_tokens(sentence) <= max_tokens:
            out.append(sentence)
            continue
        words, current = sentence.split(), ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and estimate_tokens(candidate) > max_tokens:
                out.append(current)
                candidate = word
            current = candidate
        if current:
            out.append(current)
    return out


def chunk_text(content: str, *, max_tokens: int = 350, min_tokens: int = 40) -> list[Chunk]:
    """Passages d'au plus `max_tokens`, sans jamais mélanger deux sections ; un reste de moins de
    `min_tokens` est rattaché au passage précédent de la même section."""
    chunks: list[Chunk] = []
    for heading, body in split_sections(content):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        units = [u for p in paragraphs for u in _units(p, max_tokens)]
        section: list[str] = []
        current: list[str] = []
        for unit in units:
            if current and estimate_tokens("\n\n".join([*current, unit])) > max_tokens:
                section.append("\n\n".join(current))
                current = []
            current.append(unit)
        if current:
            rest = "\n\n".join(current)
            if section and estimate_tokens(rest) < min_tokens:
                section[-1] = f"{section[-1]}\n\n{rest}"
            else:
                section.append(rest)
        chunks += [Chunk(heading=heading, text=t, tokens=estimate_tokens(t)) for t in section]
    return chunks


# Fragment de prompt d'une fiche de pack (« **Prompt (EN).** `…` », « **Prompt (EN), version vivante.** »).
_PROMPT_EN = re.compile(r"^\W*Prompt \(EN\)")


def chunk_fiche(title: str, content: str, *, max_tokens: int = 800, min_tokens: int = 40) -> list[Chunk]:
    """Une fiche de pack = un passage. Seule une fiche de plus de `max_tokens` est coupée (aux paragraphes) :
    son fragment « Prompt (EN) » reste alors avec ce qui le suit dans le dernier passage, précédé du titre
    de la fiche, pour ne jamais être séparé de la fiche qu'il illustre."""
    body = content.strip()
    if not body:
        return []
    tokens = estimate_tokens(body)
    if tokens <= max_tokens:
        return [Chunk(heading="", text=body, tokens=tokens)]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    start = next((i for i, p in enumerate(paragraphs) if _PROMPT_EN.match(p)), None)
    if start is None:
        return chunk_text(body, max_tokens=max_tokens, min_tokens=min_tokens)
    head, tail = paragraphs[:start], paragraphs[start:]
    # Le dernier passage reprend aussi les paragraphes juste avant le fragment, tant qu'il tient.
    while head and estimate_tokens("\n\n".join([title, head[-1], *tail])) <= max_tokens:
        tail.insert(0, head.pop())
    pieces = chunk_text("\n\n".join(head), max_tokens=max_tokens, min_tokens=min_tokens) if head else []
    last = "\n\n".join([title, *tail])
    return [*(Chunk(heading="", text=p.text, tokens=p.tokens) for p in pieces), Chunk("", last, estimate_tokens(last))]


def chunk_document(doc: KnowledgeDocument, settings: KnowledgeSettings) -> list[Chunk]:
    """Passages d'un document : une fiche de pack par passage (`chunk_fiche`), les autres documents découpés
    aux titres puis aux paragraphes (`chunk_text`)."""
    chunking = settings.chunking
    if doc.pack_key:
        return chunk_fiche(doc.title, doc.content, max_tokens=chunking.fiche_max_tokens, min_tokens=chunking.min_tokens)
    return chunk_text(doc.content, max_tokens=chunking.max_tokens, min_tokens=chunking.min_tokens)


def needs_reindex(doc: KnowledgeDocument, settings: KnowledgeSettings) -> bool:
    """Passages en base différents du découpage actuel (réglage ou règle de découpage changés)."""
    return [c.text for c in sorted(doc.chunks, key=lambda c: c.index)] != [
        c.text for c in chunk_document(doc, settings)
    ]


# --- indexation ------------------------------------------------------------------
def _to_blob(vector: Sequence[float]) -> bytes:
    return np.asarray(vector, dtype="<f4").tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def index_document(
    session: Session, doc: KnowledgeDocument, embedder: EmbeddingProvider | None, settings: KnowledgeSettings
) -> None:
    """(Ré)indexe un document : passages + vecteurs. Embeddings indisponibles → passages sans vecteur
    (recherche par mots-clés seulement) et `index_error` renseigné."""
    for chunk in list(doc.chunks):
        doc.chunks.remove(chunk)
        session.delete(chunk)
    session.flush()
    pieces = chunk_document(doc, settings)
    doc.token_count = sum(c.tokens for c in pieces)
    doc.index_error = None
    vectors: list[list[float]] | None = None
    if pieces and embedder is not None:
        try:
            vectors = embedder.embed([_embed_text(doc.title, c) for c in pieces])
        except EmbeddingError as exc:
            doc.index_error = f"vecteurs non calculés : {exc}"
    elif pieces:
        doc.index_error = "vecteurs non calculés : fournisseur d'embeddings indisponible"
    for i, piece in enumerate(pieces):
        doc.chunks.append(
            KnowledgeChunk(
                collection_id=doc.collection_id,
                index=i,
                heading=piece.heading,
                text=piece.text,
                keywords=doc.keywords or "",
                token_count=piece.tokens,
                embedding=_to_blob(vectors[i]) if vectors else None,
                embedding_model=embedder.model_id if vectors and embedder else None,
            )
        )
    session.flush()


def _embed_text(title: str, chunk: Chunk) -> str:
    # Le titre et la section donnent le contexte du passage au modèle d'embeddings.
    return "\n".join(p for p in (title, chunk.heading, chunk.text) if p)


# --- recherche -------------------------------------------------------------------
@dataclass
class Passage:
    chunk_id: int
    document_id: int
    document_title: str
    collection_id: int
    collection_name: str
    heading: str
    text: str
    tokens: int
    score: float | None = None  # hybride, 0–1 (None : pas de requête)
    vector_score: float | None = None
    keyword_score: float | None = None
    # retrieved | whole (petite collection injectée entière) | framing (fiche du plan ou de l'angle de la case)
    mode: str = "retrieved"
    pack: str | None = None  # pack de savoir-faire livré de la collection (presets/knowledge_packs/)
    pages: list[int] = field(default_factory=list)  # recherche par page : pages pour lesquelles il a été retenu
    dropped: str | None = None  # écarté comme redondant (raison, en français) ; None : servi
    # Fiche d'un pack (meta) : type (« shot_scale », « camera_angle »…) et terme de l'appli dont elle est la
    # fiche de référence (« plan moyen », « en plongée »…). Internes : pas dans `as_dict`.
    fiche_type: str | None = None
    framing: str | None = None

    def source(self) -> str:
        return " › ".join(p for p in (self.document_title, self.heading) if p)

    def as_dict(self, *, excerpt: int | None = None) -> dict[str, Any]:
        out = asdict(self)
        out.pop("fiche_type")
        out.pop("framing")
        if excerpt is not None and len(self.text) > excerpt:
            out["text"] = self.text[:excerpt].rstrip() + "…"
        for key in ("score", "vector_score", "keyword_score"):
            if out[key] is not None:
                out[key] = round(out[key], 4)
        return out


def fused_term(term: str) -> str:
    """Terme de plusieurs mots en un seul jeton (« gros plan » → « grosplan », « en contre-plongée » →
    « contreplongee ») : mot-clé d'un pack, retrouvé par les bigrammes de la requête (`fts_query`)."""
    return "".join(normalize_words(term))


def fts_query(query: str) -> str | None:
    """Mots de la requête, plus leurs bigrammes fusionnés : « gros plan » cherche aussi « grosplan », qui
    n'existe que dans les mots-clés des packs (pont de vocabulaire) et y vaut bien plus que « plan » seul."""
    plain = normalize_words(query)
    words = list(dict.fromkeys(plain))
    bigrams = [a + b for a, b in zip(plain, plain[1:], strict=False) if a != b]
    terms = list(dict.fromkeys([*words[:40], *bigrams[:20]]))
    return " OR ".join(f'"{w}"' for w in terms) or None


def _keyword_scores(session: Session, query: str, chunk_ids: set[int]) -> dict[int, float]:
    match = fts_query(query)
    if not match or not chunk_ids:
        return {}
    rows = session.execute(
        # Colonnes : titre de section, texte, mots-clés (titre et pont de vocabulaire d'un pack, plus parlants).
        text(
            f"SELECT rowid, bm25(knowledge_fts, 1.0, 1.0, {KEYWORDS_WEIGHT}) FROM knowledge_fts WHERE knowledge_fts MATCH :q"
        ),
        {"q": match},
    ).all()
    raw = {int(r[0]): -float(r[1]) for r in rows if int(r[0]) in chunk_ids}
    best = max(raw.values(), default=0.0)
    return {k: max(0.0, v / best) for k, v in raw.items()} if best > 0 else {}


def _vector_scores(
    chunks: Sequence[KnowledgeChunk], query: str, embedder: EmbeddingProvider | None
) -> tuple[dict[int, float], str | None]:
    usable = [c for c in chunks if c.embedding and embedder is not None and c.embedding_model == embedder.model_id]
    if not usable or embedder is None or not query.strip():
        return {}, None
    try:
        q = np.asarray(embedder.embed([query])[0], dtype="<f4")
    except EmbeddingError as exc:
        return {}, f"recherche vectorielle indisponible : {exc}"
    matrix = np.stack([_from_blob(c.embedding) for c in usable if c.embedding])
    if matrix.shape[1] != q.shape[0]:
        return {}, "dimensions des vecteurs incohérentes : réindexe le savoir-faire"
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
    sims = matrix @ q / np.where(norms == 0, 1.0, norms)
    return {c.id: max(0.0, float(s)) for c, s in zip(usable, sims, strict=True)}, None


@dataclass
class Ranking:
    passages: list[Passage]
    warning: str | None = None


def rank(
    session: Session,
    query: str,
    collection_ids: Iterable[int],
    embedder: EmbeddingProvider | None,
    settings: KnowledgeSettings,
) -> Ranking:
    """Tous les passages des collections, classés par score hybride décroissant (ordre du document à égalité)."""
    ids = list(dict.fromkeys(collection_ids))
    if not ids:
        return Ranking([])
    rows = session.execute(
        select(
            KnowledgeChunk,
            KnowledgeDocument.title,
            KnowledgeCollection.name,
            KnowledgeCollection.pack,
            KnowledgeDocument.meta,
        )
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .join(KnowledgeCollection, KnowledgeChunk.collection_id == KnowledgeCollection.id)
        .where(KnowledgeChunk.collection_id.in_(ids))
        .order_by(KnowledgeCollection.name, KnowledgeDocument.id, KnowledgeChunk.index)
    ).all()
    chunks = [r[0] for r in rows]
    vec, warning = _vector_scores(chunks, query, embedder)
    kw = _keyword_scores(session, query, {c.id for c in chunks}) if query.strip() else {}
    wv, wk = settings.retrieval.vector_weight, settings.retrieval.keyword_weight
    passages = []
    for chunk, title, name, pack, meta in rows:
        v, k = vec.get(chunk.id), kw.get(chunk.id, 0.0)
        meta = meta if pack and isinstance(meta, dict) else {}
        fiche_type = meta.get("type") if isinstance(meta.get("type"), str) else None
        score = (wv * (v or 0.0) + wk * k) / (wv + wk) if query.strip() else None
        passages.append(
            Passage(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=title,
                collection_id=chunk.collection_id,
                collection_name=name,
                heading=chunk.heading,
                text=chunk.text,
                tokens=chunk.token_count,
                score=score,
                vector_score=v,
                keyword_score=k if query.strip() else None,
                pack=pack,
                fiche_type=fiche_type,
                framing=meta.get(FRAMING_KEYS.get(fiche_type or ""), None) if fiche_type in FRAMING_KEYS else None,
            )
        )
    if query.strip():
        passages.sort(key=lambda p: -(p.score or 0.0))  # tri stable : l'ordre du document départage
    return Ranking(passages, warning)


def collection_tokens(session: Session, collection_ids: Iterable[int]) -> dict[int, int]:
    ids = list(collection_ids)
    out = dict.fromkeys(ids, 0)
    for cid, tokens in session.execute(
        select(KnowledgeChunk.collection_id, KnowledgeChunk.token_count).where(KnowledgeChunk.collection_id.in_(ids))
    ):
        out[cid] += tokens
    return out


@dataclass
class Selection:
    passages: list[Passage]
    tokens: int
    ranked: list[Passage] = field(default_factory=list)  # classement complet (panneau de test)
    whole_collections: list[int] = field(default_factory=list)
    warning: str | None = None


def select_passages(
    session: Session,
    query: str,
    collection_ids: Iterable[int],
    embedder: EmbeddingProvider | None,
    settings: KnowledgeSettings,
    *,
    top_k: int,
    budget_tokens: int,
) -> Selection:
    """Petites collections entières d'abord, puis les meilleurs passages des autres, dans le budget."""
    ids = list(dict.fromkeys(collection_ids))
    sizes = collection_tokens(session, ids)
    whole = [cid for cid in ids if 0 < sizes[cid] <= settings.small_collection_tokens]
    ranking = rank(session, query, ids, embedder, settings)
    chosen, used = choose_passages(ranking.passages, whole, settings, top_k=top_k, budget_tokens=budget_tokens)
    return Selection(chosen, used, ranking.passages, whole, ranking.warning)


# Type de fiche de pack (meta « type ») → clé du meta qui porte le terme de l'appli dont elle est la référence
# (cf. knowledge_packs.PackVocabulary.reference_terms).
FRAMING_KEYS = {"shot_scale": "plan_appli", "camera_angle": "angle_appli"}
FRAMING_LABELS = {"shot_scale": ("plan", "de plan"), "camera_angle": ("angle", "d'angle")}
DUPLICATE = "doublon : cette fiche est déjà dans le savoir-faire reçu"


def frame_passages(ranked: Sequence[Passage], *, plan: str | None, angle: str | None) -> list[Passage]:
    """Au plus UNE fiche de plan (`SHOT_*`) et UNE fiche d'angle (`ANG_*`) d'un pack par case : celle dont le
    terme de référence (pont de vocabulaire) est le plan / l'angle de la case, mise en tête (mode
    « framing »), même si son score est bas. Case sans plan (ou angle) connu : la meilleure fiche de la
    famille seulement. Les autres fiches de la famille sont marquées `dropped` (jamais servies, signalées
    dans « Sources utilisées » si elles l'auraient été) ; les autres familles gardent leur classement."""
    wanted = {"shot_scale": plan, "camera_angle": angle}
    pinned: list[Passage] = []
    out: list[Passage] = []
    kept: set[str] = set()
    for p in ranked:
        family = p.fiche_type if p.pack and p.fiche_type in wanted else None
        if family is None:
            out.append(p)
            continue
        term = wanted[family]
        if family not in kept and (p.framing == term if term else True):
            kept.add(family)
            if term:
                pinned.append(replace(p, mode="framing"))
            else:
                out.append(p)
            continue
        label, of = FRAMING_LABELS[family]
        one = f"une seule fiche {of} par case"
        out.append(replace(p, dropped=f"autre {label} que « {term} » ({one})" if term else one))
    return [*pinned, *out]


def choose_passages(
    ranked: Sequence[Passage],
    whole: Sequence[int],
    settings: KnowledgeSettings,
    *,
    top_k: int,
    budget_tokens: int,
    dropped: list[Passage] | None = None,
) -> tuple[list[Passage], int]:
    """Passages retenus d'un classement déjà fait (une seule recherche pour plusieurs budgets) :
    les petites collections `whole` entières d'abord, puis les `top_k` meilleurs, dans le budget.

    Une fiche (document) n'est servie qu'une fois : jamais reprise par la recherche quand sa collection est
    injectée entière, ni deux fois par la recherche. Les passages écartés comme redondants (doublons,
    fiches de plan d'un autre cadrage — `frame_passages`) ne prennent ni budget ni place dans le top-k : ceux
    qui auraient été servis sans cela vont dans `dropped` (à recouper avec une sélection sans tri : la boucle
    ne s'arrête qu'au top-k)."""
    chosen: list[Passage] = []
    used = 0
    served: set[int] = set()
    by_doc_order = sorted(
        (p for p in ranked if p.collection_id in whole),
        key=lambda p: (whole.index(p.collection_id), p.chunk_id),
    )
    for p in by_doc_order:
        p.mode = "whole"
        if used + p.tokens <= budget_tokens:
            chosen.append(p)
            used += p.tokens
            served.add(p.document_id)
    retrieved = 0
    for p in ranked:
        if p.collection_id in whole:
            continue
        if retrieved >= top_k:
            break
        if p.mode != "framing" and (p.score or 0.0) < settings.retrieval.min_score:
            if p.dropped is None:
                break
            continue
        redundant = p.dropped or (DUPLICATE if p.document_id in served else None)
        if redundant:
            if dropped is not None and p.chunk_id not in {d.chunk_id for d in dropped}:
                dropped.append(replace(p, dropped=redundant))
            continue
        if used + p.tokens > budget_tokens:
            continue
        chosen.append(p)
        used += p.tokens
        served.add(p.document_id)
        retrieved += 1
    return chosen, used


def choose_page_passages(
    rankings: Mapping[int, Sequence[Passage]],
    whole: Sequence[Passage],
    settings: KnowledgeSettings,
    *,
    top_k: int,
    budget_tokens: int,
) -> tuple[list[Passage], int]:
    """Recherche par page dans un seul budget : les passages `whole` (petites collections) d'abord, puis, page
    après page et tour après tour, le meilleur passage suivant de chaque page (au plus `top_k` par page).
    Un passage déjà retenu pour une autre page n'est pas répété : la page s'ajoute à ses `pages`."""
    chosen: dict[int, Passage] = {}
    used = 0
    for p in whole:
        p.mode = "whole"
        if used + p.tokens <= budget_tokens:
            chosen[p.chunk_id] = p
            used += p.tokens
    cursor = dict.fromkeys(rankings, 0)
    picked = dict.fromkeys(rankings, 0)
    active = list(rankings)
    while active:
        for number in list(active):
            ranked = rankings[number]
            while True:
                i = cursor[number]
                if (
                    picked[number] >= top_k
                    or i >= len(ranked)
                    or (ranked[i].score or 0.0) < settings.retrieval.min_score
                ):
                    active.remove(number)
                    break
                cursor[number] += 1
                p = ranked[i]
                if p.chunk_id in chosen:
                    if p.mode != "whole" and number not in chosen[p.chunk_id].pages:
                        chosen[p.chunk_id].pages.append(number)
                    picked[number] += 1
                    break
                if used + p.tokens > budget_tokens:
                    continue
                p.pages = [number]
                chosen[p.chunk_id] = p
                used += p.tokens
                picked[number] += 1
                break
    # Petites collections d'abord, puis les fiches dans l'ordre des pages.
    for p in chosen.values():
        p.pages.sort()
    order = sorted(chosen.values(), key=lambda p: (p.mode != "whole", min(p.pages, default=0)))
    return order, used


# --- collections d'un agent ---------------------------------------------------------
# Lecture du champ « Savoir-faire » du profil d'un agent (écran « L'équipe ») : renvoie la liste des
# noms de collections, ou None si l'agent n'a pas de profil (on retombe alors sur knowledge.yaml).
# Le troisième argument est la série (profil global + surcharge de la série).
ProfileLookup = Callable[[Session, str, int | None], Sequence[str] | None]
TopKLookup = Callable[[Session, str, int | None], int | None]
BudgetLookup = Callable[[Session, str, int | None], int | None]


def agent_collections(
    session: Session,
    agent: KnowledgeAgent,
    project_id: int | None,
    *,
    profile: Sequence[str] | None = None,
) -> list[KnowledgeCollection]:
    """Collections lues par l'agent : les noms du profil (s'il existe) ou de knowledge.yaml, parmi les
    collections globales et celles de la série ; plus toutes celles de la série si `series_collections`.
    Jamais une collection d'une autre série."""
    names = {n.strip().casefold() for n in (profile if profile is not None else agent.collections) if n.strip()}
    visible = session.scalars(
        select(KnowledgeCollection)
        .where((KnowledgeCollection.project_id.is_(None)) | (KnowledgeCollection.project_id == project_id))
        .order_by(KnowledgeCollection.project_id.is_not(None), KnowledgeCollection.name, KnowledgeCollection.id)
    ).all()
    return [
        c
        for c in visible
        if c.name.strip().casefold() in names
        or (agent.series_collections and project_id is not None and c.project_id == project_id)
    ]


# --- bible -----------------------------------------------------------------------
BIBLE_SECTIONS = (
    ("world", "Univers"),
    ("tone", "Ton"),
    ("rules", "Règles de l'univers"),
    ("motifs", "Gags et motifs récurrents"),
)


def get_bible(session: Session, project_id: int) -> SeriesBible | None:
    return session.scalar(select(SeriesBible).where(SeriesBible.project_id == project_id))


def get_or_create_bible(session: Session, project_id: int) -> SeriesBible:
    bible = get_bible(session, project_id)
    if bible is None:
        bible = SeriesBible(project_id=project_id, character_notes={}, chapter_summaries=[])
        session.add(bible)
        session.flush()
    return bible


@dataclass
class BibleText:
    text: str
    tokens: int
    truncated: bool = False
    chapter_summaries: int = 0  # résumés de chapitres gardés dans le budget

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _character_lines(session: Session, bible: SeriesBible, character_ids: Sequence[int] | None = None) -> list[str]:
    notes = {int(k): v.strip() for k, v in (bible.character_notes or {}).items() if str(k).isdigit() and v.strip()}
    if not notes:
        return []
    q = select(Character).where(Character.project_id == bible.project_id, Character.id.in_(list(notes)))
    by_id = {c.id: c for c in session.scalars(q.order_by(Character.name))}
    order = [i for i in character_ids if i in by_id] if character_ids is not None else list(by_id)
    return [f"- {by_id[i].name} : {notes[i]}" for i in order]


def _library_sections(session: Session, project_id: int) -> list[str]:
    """Décors et objets récurrents de la bibliothèque de la série (id, nom, description courte)."""
    library = SeriesLibrary.load(session, project_id)
    out = []
    for key, label in (("decors", "Décors récurrents"), ("objets", "Objets récurrents")):
        text = library.text(key)
        if text:
            out.append(f"{label} :\n{text}")
    return out


def render_bible(session: Session, project_id: int, *, max_tokens: int) -> BibleText | None:
    """Bible complète en texte ; au-delà du budget, les plus anciens résumés de chapitres partent d'abord.

    Les décors et objets de la bibliothèque de la série y figurent toujours (même sans bible écrite).
    """
    bible = get_bible(session, project_id)
    head: list[str] = []
    if bible is not None:
        for key, label in BIBLE_SECTIONS:
            value = (getattr(bible, key) or "").strip()
            if value:
                head.append(f"{label} :\n{value}")
        chars = _character_lines(session, bible)
        if chars:
            head.append("Personnages :\n" + "\n".join(chars))
    head += _library_sections(session, project_id)
    summaries = [
        f"- Chapitre {s.get('number', '?')}{' — ' + s['title'] if s.get('title') else ''} : {s.get('summary', '')}"
        for s in sorted((bible.chapter_summaries if bible else None) or [], key=lambda s: s.get("number") or 0)
        if str(s.get("summary") or "").strip()
    ]
    if not head and not summaries:
        return None

    def compose(kept: list[str]) -> str:
        parts = list(head)
        if kept:
            parts.append("Résumés des chapitres validés :\n" + "\n".join(kept))
        return "\n\n".join(parts)

    kept = list(summaries)
    content = compose(kept)
    while kept and estimate_tokens(content) > max_tokens:
        kept.pop(0)
        content = compose(kept)
    truncated = len(kept) < len(summaries)
    if estimate_tokens(content) > max_tokens:
        content = content[: max_tokens * CHARS_PER_TOKEN].rstrip() + "…"
        truncated = True
    return BibleText(content, estimate_tokens(content), truncated, len(kept))


def bible_character_notes(session: Session, project_id: int, character_ids: Sequence[int], *, max_tokens: int) -> str:
    """Notes de la bible sur les personnages donnés (prompt image), coupées au budget."""
    bible = get_bible(session, project_id)
    if bible is None or not character_ids or max_tokens <= 0:
        return ""
    lines = [line.removeprefix("- ") for line in _character_lines(session, bible, character_ids)]
    out = " ; ".join(" ".join(line.split()) for line in lines)
    limit = max_tokens * CHARS_PER_TOKEN
    return out if len(out) <= limit else out[:limit].rstrip(" ,;.") + "…"


def record_chapter_summary(session: Session, chapter: Chapter) -> bool:
    """Ajoute (ou met à jour) le résumé d'un chapitre validé dans la bible de sa série."""
    summary = (chapter.summary or "").strip()
    if chapter.status not in VALIDATED_STATUSES or not summary:
        return False
    bible = get_or_create_bible(session, chapter.project_id)
    entries = [e for e in bible.chapter_summaries or [] if e.get("chapter_id") != chapter.id]
    entries.append(
        {
            "chapter_id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "summary": summary,
            "added_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    bible.chapter_summaries = sorted(entries, key=lambda e: e.get("number") or 0)
    return True


# --- injection dans un agent --------------------------------------------------------
@dataclass
class AgentKnowledge:
    role: str
    query: str
    passages: list[Passage]
    tokens: int
    collections: list[str]
    bible: BibleText | None
    warning: str | None = None
    page_queries: dict[int, str] = field(default_factory=dict)  # recherche par page (`for_pages`)

    def savoir_faire(self) -> str:
        return format_passages(self.passages)

    def bible_text(self) -> str:
        return self.bible.text if self.bible else ""


def format_passages(passages: Sequence[Passage]) -> str:
    """Passages numérotés avec leur source, pour un prompt de LLM."""
    blocks = []
    for i, p in enumerate(passages, start=1):
        pages = f" · page{'s' if len(p.pages) > 1 else ''} {', '.join(map(str, p.pages))}" if p.pages else ""
        blocks.append(
            f"[{i}] « {p.document_title} »{' — ' + p.heading if p.heading else ''} ({p.collection_name}){pages}\n{p.text}"
        )
    return "\n\n".join(blocks)


def compact_passages(passages: Sequence[Passage], *, max_tokens: int) -> str:
    """Passages en une ligne (prompt image), coupés au budget."""
    out = " ; ".join(" ".join(p.text.split()).rstrip(" .;") for p in passages)
    limit = max_tokens * CHARS_PER_TOKEN
    return out if len(out) <= limit else out[:limit].rstrip(" ,;.") + "…"


@dataclass
class PanelKnowledge:
    """Savoir-faire d'une case, en deux budgets coupés dans le même classement :

    - le rédacteur de prompt (LLM, rédaction automatique et « Dialogue ») reçoit les passages entiers avec
      leur source (`writer_*`, réglés dans « L'équipe ») et des notes de bible plus longues ;
    - le prompt par fragments (`$savoir_faire` d'image_prompt.yaml, repli sans rédacteur) garde une note
      courte en une ligne (`fragment_*`), pour ne jamais coller de théorie dans le prompt du modèle d'image.
    """

    query: str = ""
    collections: list[str] = field(default_factory=list)
    writer_passages: list[Passage] = field(default_factory=list)
    writer_tokens: int = 0
    writer_budget: int = 0
    writer_top_k: int = 0
    writer_bible: str = ""
    # Passages que le rédacteur aurait reçus sans le tri des redondances (doublons, autre cadrage), avec la raison.
    writer_dropped: list[Passage] = field(default_factory=list)
    fragment_passages: list[Passage] = field(default_factory=list)
    fragment_tokens: int = 0
    fragment_budget: int = 0
    fragment_top_k: int = 0
    fragment_note: str = ""
    fragment_bible: str = ""
    warning: str | None = None

    def writer(self) -> tuple[str, str]:
        """($savoir_faire, $bible) du rédacteur de prompt."""
        return format_passages(self.writer_passages), self.writer_bible

    def fragments(self) -> tuple[str, str]:
        """($savoir_faire, $bible) du prompt par fragments."""
        return self.fragment_note, self.fragment_bible


@dataclass
class KnowledgeBase:
    """Ce dont les agents ont besoin pour lire le savoir-faire : réglages, embeddings, profils."""

    settings: KnowledgeSettings
    embedder: EmbeddingProvider | None
    profile_lookup: ProfileLookup | None = None
    profile_top_k: TopKLookup | None = None
    profile_budget: BudgetLookup | None = None
    # Dernier import des packs de savoir-faire (démarrage ou « Mettre à jour les packs ») : PackReport.
    pack_reports: list[Any] = field(default_factory=list)

    def top_k(self, session: Session, role: str, project_id: int | None) -> int:
        """Top-k de l'agent : profil (« L'équipe ») > knowledge.yaml (celui du rédacteur pour `image_prompt`)."""
        agent = self.settings.agent(role)
        profile = self.profile_top_k(session, role, project_id) if self.profile_top_k else None
        return profile or agent.main_top_k or self.settings.retrieval.top_k

    def budget_tokens(self, session: Session, role: str, project_id: int | None) -> int:
        """Budget de jetons de l'agent : profil (« L'équipe ») > knowledge.yaml (celui du rédacteur pour
        `image_prompt`)."""
        agent = self.settings.agent(role)
        profile = self.profile_budget(session, role, project_id) if self.profile_budget else None
        return profile if profile is not None else agent.main_budget_tokens

    def for_agent(
        self, session: Session, role: str, project_id: int | None, query: str, *, include_bible: bool = True
    ) -> AgentKnowledge:
        agent = self.settings.agent(role)
        profile = self.profile_lookup(session, role, project_id) if self.profile_lookup else None
        collections = agent_collections(session, agent, project_id, profile=profile)
        selection = select_passages(
            session,
            query,
            [c.id for c in collections],
            self.embedder,
            self.settings,
            top_k=self.top_k(session, role, project_id),
            budget_tokens=self.budget_tokens(session, role, project_id),
        )
        bible = None
        if include_bible and agent.bible and project_id is not None:
            limit = agent.bible_max_tokens if agent.bible_max_tokens is not None else self.settings.bible_max_tokens
            bible = render_bible(session, project_id, max_tokens=limit)
        return AgentKnowledge(
            role=role,
            query=query,
            passages=selection.passages,
            tokens=selection.tokens,
            collections=[c.name for c in collections],
            bible=bible,
            warning=selection.warning,
        )

    def for_pages(
        self,
        session: Session,
        role: str,
        project_id: int | None,
        queries: Sequence[tuple[int, str]],
        *,
        include_bible: bool = True,
    ) -> AgentKnowledge:
        """Savoir-faire cherché page par page (numéro de page, requête tirée du scénario de la page), dans le
        budget total de l'agent, sans doublon : une page de dialogue et une page d'action ne reçoivent pas les
        mêmes fiches. Les petites collections d'un pack (vocabulaire, checklist…) ne sont jamais injectées
        entières : leurs fiches sont cherchées comme les autres."""
        agent = self.settings.agent(role)
        profile = self.profile_lookup(session, role, project_id) if self.profile_lookup else None
        collections = agent_collections(session, agent, project_id, profile=profile)
        ids = [c.id for c in collections]
        sizes = collection_tokens(session, ids)
        whole = [c.id for c in collections if not c.pack and 0 < sizes[c.id] <= self.settings.small_collection_tokens]
        searched = [cid for cid in ids if cid not in whole]
        rankings: dict[int, list[Passage]] = {}
        warning = None
        for number, query in queries:
            ranking = rank(session, query, searched, self.embedder, self.settings)
            rankings[number] = ranking.passages
            warning = warning or ranking.warning
        whole_passages = sorted(
            rank(session, "", whole, None, self.settings).passages,
            key=lambda p: (whole.index(p.collection_id), p.chunk_id),
        )
        passages, used = choose_page_passages(
            rankings,
            whole_passages,
            self.settings,
            top_k=self.top_k(session, role, project_id),
            budget_tokens=self.budget_tokens(session, role, project_id),
        )
        bible = None
        if include_bible and agent.bible and project_id is not None:
            limit = agent.bible_max_tokens if agent.bible_max_tokens is not None else self.settings.bible_max_tokens
            bible = render_bible(session, project_id, max_tokens=limit)
        page_queries = dict(queries)
        return AgentKnowledge(
            role=role,
            query="\n".join(f"Page {n} : {q}" for n, q in page_queries.items()),
            passages=passages,
            tokens=used,
            collections=[c.name for c in collections],
            bible=bible,
            warning=warning,
            page_queries=page_queries,
        )

    def for_panel(
        self,
        session: Session,
        project_id: int,
        query: str,
        character_ids: Sequence[int],
        *,
        plan: str | None = None,
        angle: str | None = None,
    ) -> PanelKnowledge:
        """Savoir-faire et notes de la bible d'une case (agent « image_prompt ») : une seule recherche, puis
        les passages du rédacteur et la note courte des fragments, chacun dans son budget.

        `plan` / `angle` : termes de l'appli (`art_direction.PLANS` / `ANGLES`) de la case, None si inconnus.
        Une seule fiche de plan et une seule fiche d'angle d'un pack : celles de ce plan et de cet angle
        (`frame_passages`) ; le budget libéré va aux passages suivants."""
        agent = self.settings.agent(IMAGE_AGENT)
        out = PanelKnowledge(
            query=query,
            writer_budget=self.budget_tokens(session, IMAGE_AGENT, project_id),
            writer_top_k=self.top_k(session, IMAGE_AGENT, project_id),
            fragment_budget=agent.budget_tokens,
            fragment_top_k=agent.top_k or self.settings.retrieval.top_k,
        )
        if out.writer_budget > 0 or out.fragment_budget > 0:
            profile = self.profile_lookup(session, IMAGE_AGENT, project_id) if self.profile_lookup else None
            collections = agent_collections(session, agent, project_id, profile=profile)
            out.collections = [c.name for c in collections]
            # Le classement est fait une fois ; chaque budget y choisit ses passages.
            ranking = select_passages(
                session, query, [c.id for c in collections], self.embedder, self.settings, top_k=0, budget_tokens=0
            )
            out.warning = ranking.warning
            ranked = frame_passages(ranking.ranked, plan=plan, angle=angle)
            if out.writer_budget > 0:
                dropped: list[Passage] = []
                out.writer_passages, out.writer_tokens = choose_passages(
                    ranked,
                    ranking.whole_collections,
                    self.settings,
                    top_k=out.writer_top_k,
                    budget_tokens=out.writer_budget,
                    dropped=dropped,
                )
                # Écartés signalés : ceux qu'aurait servis la même sélection sans tri des fiches de plan / d'angle.
                unsorted, _ = choose_passages(
                    ranking.ranked,
                    ranking.whole_collections,
                    self.settings,
                    top_k=out.writer_top_k,
                    budget_tokens=out.writer_budget,
                )
                would = {p.chunk_id for p in unsorted}
                out.writer_dropped = [p for p in dropped if p.chunk_id in would or p.dropped == DUPLICATE]
            if out.fragment_budget > 0:
                # Jamais de fiche d'un pack (théorie de mise en scène en français) dans le prompt du modèle
                # d'image : seul le rédacteur les lit.
                packs = {p.collection_id for p in ranking.ranked if p.pack}
                out.fragment_passages, out.fragment_tokens = choose_passages(
                    [p for p in ranked if not p.pack],
                    [cid for cid in ranking.whole_collections if cid not in packs],
                    self.settings,
                    top_k=out.fragment_top_k,
                    budget_tokens=out.fragment_budget,
                )
                out.fragment_note = compact_passages(out.fragment_passages, max_tokens=out.fragment_budget)
        if agent.bible:
            limit = agent.bible_max_tokens if agent.bible_max_tokens is not None else self.settings.bible_max_tokens
            writer_limit = agent.writer_bible_max_tokens if agent.writer_bible_max_tokens is not None else limit
            out.fragment_bible = bible_character_notes(session, project_id, character_ids, max_tokens=limit)
            out.writer_bible = bible_character_notes(session, project_id, character_ids, max_tokens=writer_limit)
        return out

    def writer_stamp(self, session: Session, project_id: int | None) -> str:
        """Empreinte du savoir-faire du rédacteur de prompt pour une série : collections de l'agent
        « image_prompt » (profil ou knowledge.yaml), leurs documents (nombre, dernier changement) et passages
        (nombre, jetons, vecteurs), budget et top-k du rédacteur, réglages de la recherche et modèle
        d'embeddings. Elle change avec un import ou une mise à jour de pack, un document ajouté, modifié ou
        retiré, une réindexation ou un budget réglé dans « L'équipe » — et ne change pas sinon : le prompt
        rédigé d'une case n'est redemandé que si elle change (pas à chaque génération)."""
        agent = self.settings.agent(IMAGE_AGENT)
        profile = self.profile_lookup(session, IMAGE_AGENT, project_id) if self.profile_lookup else None
        collections = agent_collections(session, agent, project_id, profile=profile)
        ids = [c.id for c in collections]
        docs = {
            cid: [count, str(latest)]
            for cid, count, latest in session.execute(
                select(
                    KnowledgeDocument.collection_id,
                    func.count(KnowledgeDocument.id),
                    func.max(KnowledgeDocument.updated_at),
                )
                .where(KnowledgeDocument.collection_id.in_(ids))
                .group_by(KnowledgeDocument.collection_id)
            )
        }
        chunks = {
            cid: [count, int(tokens or 0), int(embedded or 0), str(models or "")]
            for cid, count, tokens, embedded, models in session.execute(
                select(
                    KnowledgeChunk.collection_id,
                    func.count(KnowledgeChunk.id),
                    func.sum(KnowledgeChunk.token_count),
                    func.count(KnowledgeChunk.embedding),
                    func.group_concat(KnowledgeChunk.embedding_model.distinct()),
                )
                .where(KnowledgeChunk.collection_id.in_(ids))
                .group_by(KnowledgeChunk.collection_id)
            )
        }
        raw = {
            "collections": [[c.id, c.name, docs.get(c.id), chunks.get(c.id)] for c in collections],
            "budget": self.budget_tokens(session, IMAGE_AGENT, project_id),
            "top_k": self.top_k(session, IMAGE_AGENT, project_id),
            "retrieval": self.settings.retrieval.model_dump(mode="json"),
            "small_collection_tokens": self.settings.small_collection_tokens,
            "embedder": self.embedder.model_id if self.embedder is not None else None,
        }
        return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()[:32]


IMAGE_AGENT = "image_prompt"  # rôle du constructeur de prompt image dans presets/knowledge.yaml
