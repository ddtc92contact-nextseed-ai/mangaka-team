"""Savoir-faire (bibliothèque, documents, recherche de test), bible de série et sources d'un scénario."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..pipeline.knowledge import (
    KnowledgeError,
    Passage,
    collection_tokens,
    extract_text,
    get_bible,
    get_or_create_bible,
    index_document,
    render_bible,
    select_passages,
    title_from,
)
from ..store.models import (
    Chapter,
    Character,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    LLMRun,
    Project,
)
from .chapters import get_chapter_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .projects import get_project_or_404
from .schemas import (
    BibleCharacter,
    BibleOut,
    BibleSummary,
    BibleUpdate,
    ChapterSummaryEntry,
    ChunkOut,
    CollectionCreate,
    CollectionOut,
    CollectionUpdate,
    DocumentCreate,
    DocumentOut,
    DocumentSummaryOut,
    DocumentUpdate,
    KnowledgeAgentOut,
    KnowledgeStatusOut,
    PassageOut,
    ReindexOut,
    SearchIn,
    SearchOut,
    SourcesOut,
)

router = APIRouter(tags=["savoir-faire"])

MAX_FILES_PER_UPLOAD = 20


# --- collections -----------------------------------------------------------------
def get_collection_or_404(session: Session, collection_id: int) -> KnowledgeCollection:
    collection = session.get(KnowledgeCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection introuvable")
    return collection


def get_document_or_404(session: Session, document_id: int) -> KnowledgeDocument:
    doc = session.get(KnowledgeDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc


def _collections_out(session: Session, ctx: AppContext, collections: list[KnowledgeCollection]) -> list[CollectionOut]:
    ids = [c.id for c in collections]
    tokens = collection_tokens(session, ids)
    docs = dict(
        session.execute(
            select(KnowledgeDocument.collection_id, func.count())
            .where(KnowledgeDocument.collection_id.in_(ids))
            .group_by(KnowledgeDocument.collection_id)
        ).all()
    )
    chunks = dict(
        session.execute(
            select(KnowledgeChunk.collection_id, func.count())
            .where(KnowledgeChunk.collection_id.in_(ids))
            .group_by(KnowledgeChunk.collection_id)
        ).all()
    )
    titles = dict(session.execute(select(Project.id, Project.title)).all())
    threshold = ctx.knowledge.settings.small_collection_tokens
    return [
        CollectionOut(
            id=c.id,
            name=c.name,
            description=c.description,
            project_id=c.project_id,
            project_title=titles.get(c.project_id) if c.project_id else None,
            document_count=docs.get(c.id, 0),
            chunk_count=chunks.get(c.id, 0),
            token_count=tokens[c.id],
            whole=0 < tokens[c.id] <= threshold,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in collections
    ]


def _check_name(session: Session, name: str, project_id: int | None, exclude: int | None = None) -> None:
    # Comparaison en Python : le lower() de SQLite ignore les lettres accentuées.
    scope = (
        KnowledgeCollection.project_id.is_(None) if project_id is None else KnowledgeCollection.project_id == project_id
    )
    taken = session.execute(select(KnowledgeCollection.id, KnowledgeCollection.name).where(scope)).all()
    if any(cid != exclude and other.strip().casefold() == name.strip().casefold() for cid, other in taken):
        raise FieldError("name", "une collection porte déjà ce nom à cet endroit")


@router.get("/knowledge/collections", response_model=list[CollectionOut])
def list_collections(
    project_id: int | None = None, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[CollectionOut]:
    """Toutes les collections ; avec `project_id`, les globales et celles de cette série."""
    q = select(KnowledgeCollection)
    if project_id is not None:
        q = q.where(or_(KnowledgeCollection.project_id.is_(None), KnowledgeCollection.project_id == project_id))
    q = q.order_by(KnowledgeCollection.project_id.is_not(None), KnowledgeCollection.name)
    return _collections_out(session, ctx, list(session.scalars(q)))


@router.post("/knowledge/collections", response_model=CollectionOut, status_code=201)
def create_collection(
    body: CollectionCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CollectionOut:
    if body.project_id is not None:
        get_project_or_404(session, body.project_id)
    _check_name(session, body.name, body.project_id)
    collection = KnowledgeCollection(name=body.name, description=body.description, project_id=body.project_id)
    session.add(collection)
    session.commit()
    return _collections_out(session, ctx, [collection])[0]


@router.get("/knowledge/collections/{collection_id}", response_model=CollectionOut)
def get_collection(
    collection_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CollectionOut:
    return _collections_out(session, ctx, [get_collection_or_404(session, collection_id)])[0]


@router.patch("/knowledge/collections/{collection_id}", response_model=CollectionOut)
def update_collection(
    collection_id: int,
    body: CollectionUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> CollectionOut:
    collection = get_collection_or_404(session, collection_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise FieldError("name", "ne peut pas être vide")
    if changes.get("project_id") is not None:
        get_project_or_404(session, changes["project_id"])
    name = changes.get("name", collection.name)
    project_id = changes.get("project_id", collection.project_id)
    _check_name(session, name, project_id, exclude=collection.id)
    for key, value in changes.items():
        setattr(collection, key, "" if key == "description" and value is None else value)
    session.commit()
    return _collections_out(session, ctx, [collection])[0]


@router.delete("/knowledge/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int, session: Session = Depends(get_session)) -> Response:
    session.delete(get_collection_or_404(session, collection_id))
    session.commit()
    return Response(status_code=204)


# --- documents -------------------------------------------------------------------
def _summary(doc: KnowledgeDocument, chunk_count: int) -> DocumentSummaryOut:
    return DocumentSummaryOut(
        id=doc.id,
        collection_id=doc.collection_id,
        title=doc.title,
        source=doc.source,
        original_name=doc.original_name,
        tags=list(doc.tags or []),
        token_count=doc.token_count,
        chunk_count=chunk_count,
        index_error=doc.index_error,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def document_out(doc: KnowledgeDocument, ctx: AppContext) -> DocumentOut:
    model = ctx.knowledge.embedder.model_id if ctx.knowledge.embedder else None
    return DocumentOut(
        **_summary(doc, len(doc.chunks)).model_dump(),
        content=doc.content,
        collection_name=doc.collection.name,
        chunks=[
            ChunkOut(
                id=c.id,
                index=c.index,
                heading=c.heading,
                text=c.text,
                token_count=c.token_count,
                embedded=c.embedding is not None and c.embedding_model == model,
            )
            for c in doc.chunks
        ],
    )


def _clean_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in tags if t.strip()))


@router.get("/knowledge/collections/{collection_id}/documents", response_model=list[DocumentSummaryOut])
def list_documents(collection_id: int, session: Session = Depends(get_session)) -> list[DocumentSummaryOut]:
    get_collection_or_404(session, collection_id)
    counts = dict(
        session.execute(
            select(KnowledgeChunk.document_id, func.count())
            .where(KnowledgeChunk.collection_id == collection_id)
            .group_by(KnowledgeChunk.document_id)
        ).all()
    )
    docs = session.scalars(
        select(KnowledgeDocument).where(KnowledgeDocument.collection_id == collection_id).order_by(KnowledgeDocument.id)
    )
    return [_summary(d, counts.get(d.id, 0)) for d in docs]


@router.post("/knowledge/collections/{collection_id}/documents", response_model=DocumentOut, status_code=201)
def create_document(
    collection_id: int,
    body: DocumentCreate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> DocumentOut:
    """Texte collé (Markdown accepté) : enregistré puis découpé et indexé."""
    collection = get_collection_or_404(session, collection_id)
    doc = KnowledgeDocument(title=body.title, source="text", content=body.content, tags=_clean_tags(body.tags))
    collection.documents.append(doc)
    session.flush()
    index_document(session, doc, ctx.knowledge.embedder, ctx.knowledge.settings)
    session.commit()
    return document_out(doc, ctx)


@router.post("/knowledge/collections/{collection_id}/upload", response_model=list[DocumentOut], status_code=201)
async def upload_documents(
    collection_id: int,
    files: list[UploadFile] = File(..., description="Fichiers .md, .txt ou .pdf"),
    tags: str = Form("", description="Étiquettes séparées par des virgules"),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> list[DocumentOut]:
    collection = get_collection_or_404(session, collection_id)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise FieldError("files", f"au plus {MAX_FILES_PER_UPLOAD} fichiers par envoi")
    max_bytes = ctx.settings.max_upload_mb * 1024 * 1024
    tag_list = _clean_tags([t[:40] for t in tags.split(",")])
    # Tout extraire avant d'enregistrer quoi que ce soit.
    extracted: list[tuple[str, str, str]] = []
    for upload in files:
        name = (upload.filename or "document").rsplit("/", 1)[-1][:255]
        data = await upload.read(max_bytes + 1)
        if not data:
            raise FieldError("files", f"{name} : fichier vide")
        if len(data) > max_bytes:
            raise FieldError("files", f"{name} : dépasse {ctx.settings.max_upload_mb} Mo")
        try:
            source, content = extract_text(name, data)
        except KnowledgeError as exc:
            raise FieldError("files", f"{name} : {exc}") from None
        extracted.append((name, source, content))
    docs = []
    for name, source, content in extracted:
        doc = KnowledgeDocument(
            title=title_from(name, content), source=source, original_name=name, content=content, tags=tag_list
        )
        collection.documents.append(doc)
        session.flush()
        index_document(session, doc, ctx.knowledge.embedder, ctx.knowledge.settings)
        docs.append(doc)
    session.commit()
    return [document_out(d, ctx) for d in docs]


@router.get("/knowledge/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> DocumentOut:
    return document_out(get_document_or_404(session, document_id), ctx)


@router.patch("/knowledge/documents/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: int,
    body: DocumentUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> DocumentOut:
    """Modifier le texte ou le titre réindexe le document ; les étiquettes seules, non."""
    doc = get_document_or_404(session, document_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("title", "content"):
        if key in changes and changes[key] is None:
            raise FieldError(key, "ne peut pas être vide")
    if "tags" in changes:
        doc.tags = _clean_tags(changes.pop("tags") or [])
    reindex = any(key in changes and changes[key] != getattr(doc, key) for key in ("title", "content"))
    for key, value in changes.items():
        setattr(doc, key, value)
    if reindex:
        index_document(session, doc, ctx.knowledge.embedder, ctx.knowledge.settings)
    session.commit()
    return document_out(doc, ctx)


@router.delete("/knowledge/documents/{document_id}", status_code=204)
def delete_document(document_id: int, session: Session = Depends(get_session)) -> Response:
    session.delete(get_document_or_404(session, document_id))
    session.commit()
    return Response(status_code=204)


@router.post("/knowledge/reindex", response_model=ReindexOut)
def reindex(
    stale_only: bool = True, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ReindexOut:
    """Recalcule les vecteurs (après un changement de modèle d'embeddings, ou Ollama revenu)."""
    embedder = ctx.knowledge.embedder
    if embedder is None:
        detail = ctx.providers.errors.get("embedding", "fournisseur d'embeddings indisponible")
        raise HTTPException(status_code=503, detail=f"Embeddings indisponibles : {detail}")
    q = select(KnowledgeDocument).order_by(KnowledgeDocument.id)
    if stale_only:
        stale = select(KnowledgeChunk.document_id).where(
            or_(KnowledgeChunk.embedding.is_(None), KnowledgeChunk.embedding_model != embedder.model_id)
        )
        q = q.where(KnowledgeDocument.id.in_(stale))
    docs = list(session.scalars(q))
    errors: list[str] = []
    for doc in docs:
        index_document(session, doc, embedder, ctx.knowledge.settings)
        if doc.index_error:
            errors.append(f"{doc.title} : {doc.index_error}")
    session.commit()
    return ReindexOut(documents=len(docs), chunks=sum(len(d.chunks) for d in docs), errors=errors)


# --- recherche (panneau de test) et état ---------------------------------------------
def passage_out(p: Passage | dict, selected: bool = False) -> PassageOut:
    data = p.as_dict() if isinstance(p, Passage) else dict(p)
    return PassageOut(**data, selected=selected)


@router.post("/knowledge/search", response_model=SearchOut)
def search(body: SearchIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)) -> SearchOut:
    """Classement des passages pour une question, comme le verrait un agent ; avec `project_id`, la bible
    de la série (toujours injectée) est jointe."""
    settings = ctx.knowledge.settings
    if body.collection_ids:
        collections = [get_collection_or_404(session, cid) for cid in dict.fromkeys(body.collection_ids)]
    elif body.project_id is not None:
        get_project_or_404(session, body.project_id)
        collections = list(
            session.scalars(
                select(KnowledgeCollection)
                .where(
                    or_(
                        KnowledgeCollection.project_id.is_(None),
                        KnowledgeCollection.project_id == body.project_id,
                    )
                )
                .order_by(KnowledgeCollection.name)
            )
        )
    else:
        raise FieldError("collection_ids", "choisis une collection ou une série")
    top_k = body.top_k or settings.retrieval.top_k
    budget = body.budget_tokens if body.budget_tokens is not None else settings.agent("script").budget_tokens
    selection = select_passages(
        session,
        body.query,
        [c.id for c in collections],
        ctx.knowledge.embedder,
        settings,
        top_k=top_k,
        budget_tokens=budget,
    )
    chosen = {p.chunk_id for p in selection.passages}
    bible = render_bible(session, body.project_id, max_tokens=settings.bible_max_tokens) if body.project_id else None
    return SearchOut(
        query=body.query,
        collections=[c.name for c in collections],
        passages=[passage_out(p, p.chunk_id in chosen) for p in selection.ranked],
        selected_tokens=selection.tokens,
        budget_tokens=budget,
        top_k=top_k,
        bible=BibleSummary(**bible.as_dict()) if bible else None,
        warning=selection.warning,
    )


@router.get("/knowledge/status", response_model=KnowledgeStatusOut)
def status(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)) -> KnowledgeStatusOut:
    embedder = ctx.knowledge.embedder
    model = embedder.model_id if embedder else None
    stale = select(func.count()).where(
        or_(KnowledgeChunk.embedding.is_(None), KnowledgeChunk.embedding_model != (model or ""))
    )
    settings = ctx.knowledge.settings
    agents = []
    for role, agent in settings.agents.items():
        kb = ctx.knowledge
        profile = kb.profile_lookup(session, role, None) if kb.profile_lookup else None
        profile_top_k = kb.profile_top_k(session, role, None) if kb.profile_top_k else None
        agents.append(
            KnowledgeAgentOut(
                role=role,
                label=agent.label,
                collections=list(profile if profile is not None else agent.collections),
                source="profile" if profile is not None else "preset",
                series_collections=agent.series_collections,
                budget_tokens=agent.budget_tokens,
                top_k=profile_top_k or agent.top_k or settings.retrieval.top_k,
                bible=agent.bible,
            )
        )
    return KnowledgeStatusOut(
        provider=ctx.providers.names.get("embedding"),
        model=model,
        available=embedder is not None,
        detail=ctx.providers.errors.get("embedding"),
        collections=session.scalar(select(func.count()).select_from(KnowledgeCollection)) or 0,
        documents=session.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0,
        chunks=session.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0,
        stale_chunks=session.scalar(stale) or 0,
        small_collection_tokens=settings.small_collection_tokens,
        vector_backend="numpy",
        agents=agents,
    )


# --- bible de série ----------------------------------------------------------------
def bible_out(session: Session, ctx: AppContext, project: Project) -> BibleOut:
    bible = get_bible(session, project.id)
    notes = {str(k): v for k, v in (bible.character_notes or {}).items()} if bible else {}
    characters = session.scalars(
        select(Character).where(Character.project_id == project.id).order_by(Character.name)
    ).all()
    rendered = render_bible(session, project.id, max_tokens=ctx.knowledge.settings.bible_max_tokens)
    return BibleOut(
        project_id=project.id,
        world=bible.world if bible else "",
        tone=bible.tone if bible else "",
        rules=bible.rules if bible else "",
        motifs=bible.motifs if bible else "",
        characters=[
            BibleCharacter(id=c.id, name=c.name, visual_description=c.visual_description, note=notes.get(str(c.id), ""))
            for c in characters
        ],
        chapter_summaries=[ChapterSummaryEntry(**e) for e in (bible.chapter_summaries if bible else [])],
        rendered=BibleSummary(**rendered.as_dict()) if rendered else None,
        updated_at=bible.updated_at if bible else None,
    )


@router.get("/projects/{project_id}/bible", response_model=BibleOut)
def read_bible(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BibleOut:
    return bible_out(session, ctx, get_project_or_404(session, project_id))


@router.put("/projects/{project_id}/bible", response_model=BibleOut)
def write_bible(
    project_id: int, body: BibleUpdate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BibleOut:
    project = get_project_or_404(session, project_id)
    bible = get_or_create_bible(session, project.id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("world", "tone", "rules", "motifs"):
        if key in changes:
            setattr(bible, key, changes[key] or "")
    if body.character_notes is not None:
        known = set(session.scalars(select(Character.id).where(Character.project_id == project.id)))
        unknown = [cid for cid in body.character_notes if cid not in known]
        if unknown:
            raise FieldError("character_notes", f"personnage(s) absent(s) de la série : {unknown}")
        bible.character_notes = {str(cid): note for cid, note in body.character_notes.items() if note}
    if body.chapter_summaries is not None:
        bible.chapter_summaries = [
            e.model_dump() for e in sorted(body.chapter_summaries, key=lambda e: e.number or 0) if e.summary
        ]
    session.commit()
    return bible_out(session, ctx, project)


# --- sources d'un scénario -----------------------------------------------------------
@router.get("/chapters/{chapter_id}/sources", response_model=SourcesOut | None)
def chapter_sources(
    chapter_id: int, agent: str = "script", session: Session = Depends(get_session)
) -> SourcesOut | None:
    """Ce que l'agent a reçu lors de son dernier passage sur ce chapitre (« Sources utilisées »)."""
    chapter: Chapter = get_chapter_or_404(session, chapter_id)
    run = session.scalar(
        select(LLMRun).where(LLMRun.chapter_id == chapter.id, LLMRun.agent == agent).order_by(LLMRun.id.desc())
    )
    if run is None:
        return None
    return SourcesOut(
        run_id=run.id,
        job_id=run.job_id,
        agent=run.agent,
        model=run.model,
        collections=list(run.collections or []),
        passages=[passage_out(p, True) for p in run.passages or []],
        bible=BibleSummary(**run.bible) if run.bible else None,
        created_at=run.created_at,
    )
