"""Distribution du chapitre (pipeline/cast.py) : intervenants, fiches et références, foules sans fiche,
fiches préremplies par le LLM et « Tout créer pour les secondaires »."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline import cast as ca
from ..pipeline.app_settings import author_or_default
from ..pipeline.art_direction import STEP as DIRECTION_STEP
from ..pipeline.generation import GenerationError
from ..pipeline.journal import record_event
from ..pipeline.names import relink_project
from ..pipeline.reference_sheets import ACTIVE, enqueue_sheet
from ..pipeline.reference_sheets import STEP as REFERENCE_STEP
from ..presets import PresetError
from ..store.models import Chapter, ChapterCrowdMark, Character, Job, utcnow
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import (
    CastAppearanceOut,
    CastBatchItemOut,
    CastBatchOut,
    CastMemberOut,
    CastNameIn,
    ChapterCastOut,
    CharacterDraftOut,
    CrowdMarkIn,
    CrowdMarkOut,
    CrowdRevokeIn,
)
from .stages import get_chapter_or_404
from .storage import set_entry_slug

router = APIRouter(tags=["distribution"])


def _mark_out(m: ca.CrowdMark) -> CrowdMarkOut:
    return CrowdMarkOut(id=m.id, name=m.name, author=m.author, at=m.at.replace(tzinfo=m.at.tzinfo or UTC))


def cast_out(chapter: Chapter, cast: ca.ChapterCast) -> ChapterCastOut:
    return ChapterCastOut(
        chapter_id=chapter.id,
        project_id=chapter.project_id,
        members=[
            CastMemberOut(
                key=m.key,
                name=m.name,
                character_id=m.character_id,
                written=m.written,
                appearances=[
                    CastAppearanceOut(
                        panel_id=a.panel_id,
                        page_number=a.page_number,
                        panel_index=a.panel_index,
                        label=a.label,
                        sources=a.sources,
                    )
                    for a in m.appearances
                ],
                panel_count=m.panels,
                images=m.images,
                references=m.references,  # type: ignore[arg-type]
                role=m.role,  # type: ignore[arg-type]
                needs=m.needs,  # type: ignore[arg-type]
                crowd=m.crowd,
                mark=_mark_out(m.mark) if m.mark else None,
                fault=m.fault,  # type: ignore[arg-type]
                advice=m.advice,
                lora_name=m.lora_name,
                lora_weight=m.lora_weight,
            )
            for m in cast.members
        ],
        total=len(cast.counted),
        faults=len(cast.faults),
        without_card=[m.name for m in cast.without_card()],
        without_image=[m.name for m in cast.without_image()],
        marks=[_mark_out(m) for m in cast.marks],
    )


def _cast(session: Session, chapter: Chapter) -> ChapterCastOut:
    session.expire_all()  # fiches, images et marques relues après une écriture
    return cast_out(chapter, ca.chapter_cast(session, chapter))


def _member_or_422(cast: ca.ChapterCast, name: str) -> ca.CastMember:
    member = cast.member(name)
    if member is None:
        raise FieldError("name", f"« {name} » n'est cité dans aucune case du chapitre")
    return member


@router.get("/chapters/{chapter_id}/cast", response_model=ChapterCastOut)
def get_cast(chapter_id: int, session: Session = Depends(get_session)) -> ChapterCastOut:
    """Distribution du chapitre : chaque intervenant cité, sa fiche, ses références, ses cases et son rôle."""
    chapter = get_chapter_or_404(session, chapter_id)
    return cast_out(chapter, ca.chapter_cast(session, chapter))


# --- foules sans fiche ------------------------------------------------------------------------------------
def add_crowd_mark(session: Session, chapter: Chapter, name: str, author: str = "") -> ca.CastMember:
    """Marque « foule sans fiche » (sans commit) ; `FieldError` pour un intervenant nommé ou déjà réglé."""
    cast = ca.chapter_cast(session, chapter)
    member = _member_or_422(cast, name)
    if member.character_id is not None:
        raise FieldError("name", f"« {name} » a déjà une fiche ({member.name}) : rien à marquer")
    if not member.crowd:
        raise FieldError(
            "name",
            f"« {member.name} » désigne un intervenant, pas une foule anonyme : crée sa fiche (même secondaire). "
            "Seules les foules sans nom, au pluriel (« des passants », « la foule »), peuvent se passer de fiche.",
        )
    if member.mark is not None:
        raise FieldError("name", f"« {member.name} » est déjà marqué « foule sans fiche »")
    author = author_or_default(session, author)  # sinon « Ton nom » des Réglages
    session.add(
        ChapterCrowdMark(
            project_id=chapter.project_id,
            chapter_id=chapter.id,
            name=member.name,
            name_key=ca.cast_key(member.name),
            author=author,
        )
    )
    who = f" par {author}" if author else ""
    record_event(
        session,
        verdict="validated",
        action="crowd_mark",
        note=f"Chapitre {chapter.number} · « {member.name} » marqué foule sans fiche{who}",
    )
    session.flush()
    return member


@router.post("/chapters/{chapter_id}/cast/crowds", response_model=ChapterCastOut)
def mark_crowd(chapter_id: int, body: CrowdMarkIn, session: Session = Depends(get_session)) -> ChapterCastOut:
    """« Foule sans fiche » : une foule anonyme (« des passants », « la foule ») sort des fautes de la garde.
    Refusé pour un intervenant nommé (« le garde », « Mina », « trafiquant 2 ») : il lui faut une fiche."""
    chapter = get_chapter_or_404(session, chapter_id)
    add_crowd_mark(session, chapter, body.name, body.author)
    session.commit()
    return _cast(session, chapter)


@router.delete("/chapters/{chapter_id}/cast/crowds/{mark_id}", response_model=ChapterCastOut)
def revoke_crowd(
    chapter_id: int, mark_id: int, body: CrowdRevokeIn | None = None, session: Session = Depends(get_session)
) -> ChapterCastOut:
    """Lève la marque : la foule redevient un intervenant sans fiche (en faute). La trace reste."""
    chapter = get_chapter_or_404(session, chapter_id)
    mark = session.get(ChapterCrowdMark, mark_id)
    if mark is None or mark.chapter_id != chapter.id:
        raise HTTPException(status_code=404, detail="Marque introuvable")
    if mark.revoked_at is not None:
        raise FieldError("mark", f"« {mark.name} » : marque déjà levée")
    author = author_or_default(session, body.author if body else "")
    mark.revoked_at = utcnow()
    mark.revoked_by = author
    record_event(
        session,
        verdict="rejected",
        action="crowd_unmark",
        note=f"Chapitre {chapter.number} · « {mark.name} » n'est plus une foule sans fiche"
        + (f" (levé par {author})" if author else ""),
    )
    session.commit()
    return _cast(session, chapter)


# --- « Créer la fiche » ------------------------------------------------------------------------------------
def _draft(session: Session, ctx: AppContext, chapter: Chapter, member: ca.CastMember) -> ca.CharacterDraft:
    """Fiche préremplie par le LLM du directeur artistique (aucune transaction ouverte pendant l'appel)."""
    try:
        prompt = ctx.agents.presets_for(chapter.project_id).prompt(ca.PROMPT_ID)
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    context = ca.draft_context(session, chapter, member)
    session.commit()
    llm, error = ctx.agents.llm_for_job(DIRECTION_STEP, chapter.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'fournisseur LLM indisponible'}")
    try:
        return ca.draft_character(llm, prompt, context)
    except ca.CastDraftError as exc:
        raise FieldError(
            "name", f"Fiche de « {member.name} » non préremplie : {exc}. Réessaie, ou écris-la à la main."
        ) from None


@router.post("/chapters/{chapter_id}/cast/draft", response_model=CharacterDraftOut)
def draft_card(
    chapter_id: int, body: CastNameIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CharacterDraftOut:
    """« Créer la fiche » : nom et description visuelle tirés par le LLM des cases de l'intervenant. Rien n'est
    enregistré : l'auteur relit, puis crée la fiche (POST /projects/{id}/characters)."""
    chapter = get_chapter_or_404(session, chapter_id)
    member = _member_or_422(ca.chapter_cast(session, chapter), body.name)
    if member.character_id is not None:
        raise FieldError("name", f"« {body.name} » a déjà une fiche : {member.name}")
    draft = _draft(session, ctx, chapter, member)
    return CharacterDraftOut(
        name=ca.card_name(member.name),
        written=member.name,
        visual_description=ca.draft_description(draft),
        prompt_keywords=draft.mots_cles,
        age=draft.age,
        silhouette=draft.silhouette,
        tenue=draft.tenue,
        signe_distinctif=draft.signe_distinctif,
        panel_count=member.panels,
    )


# --- « Tout créer pour les secondaires » --------------------------------------------------------------------
def _reference_running(session: Session, character_id: int) -> bool:
    return any(
        (j.params or {}).get("entry_kind") == "character" and (j.params or {}).get("entry_id") == character_id
        for j in session.scalars(select(Job).where(Job.step == REFERENCE_STEP, Job.status.in_(ACTIVE)))
    )


@router.post("/chapters/{chapter_id}/cast/secondaries", response_model=CastBatchOut)
def create_secondaries(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CastBatchOut:
    """Crée d'un coup les fiches préremplies des intervenants secondaires qui n'en ont pas (foules exclues : à
    marquer), puis met en file leur portrait (un par fiche sans image, gardé d'office comme référence) dans la
    file unique de ComfyUI : une génération à la fois. Un échec (LLM, ComfyUI) n'arrête pas les autres."""
    chapter = get_chapter_or_404(session, chapter_id)
    cast = ca.chapter_cast(session, chapter)
    targets = [m for m in cast.members if m.role == ca.SECONDARY and m.fault and not m.crowd]
    items: list[CastBatchItemOut] = []
    for member in targets:
        item = CastBatchItemOut(name=member.name, character_id=member.character_id)
        items.append(item)
        if member.character_id is not None:
            continue
        try:
            draft = _draft(session, ctx, chapter, member)
        except (FieldError, HTTPException) as exc:
            item.message = exc.message if isinstance(exc, FieldError) else str(exc.detail)
            continue
        series = chapter.project
        character = Character(
            project_id=chapter.project_id,
            name=ca.card_name(member.name),
            visual_description=ca.draft_description(draft),
            prompt_keywords=draft.mots_cles,
        )
        set_entry_slug(ctx, session, character, series)
        session.add(character)
        session.flush()
        item.character_id, item.created = character.id, True
    session.flush()
    relink_project(session, chapter.project_id)
    session.commit()

    jobs: list[Job] = []
    comfy_error = (
        None if ctx.providers.comfyui is not None else ctx.providers.errors.get("comfyui", "client non configuré")
    )
    presets = ctx.agents.presets_for(chapter.project_id)
    for item in items:
        if item.character_id is None:
            continue
        character = session.get(Character, item.character_id, options=[selectinload(Character.reference_images)])
        if character is None or character.reference_images:
            continue
        if comfy_error is not None:
            item.message = item.message or f"portrait non mis en file : ComfyUI indisponible ({comfy_error})"
            continue
        if _reference_running(session, character.id):
            item.message = "portrait déjà en file"
            continue
        try:
            jobs += enqueue_sheet(session, presets, character, ca.PORTRAIT_SHEET, count=1, auto_keep=True)
            item.queued = True
        except (PresetError, GenerationError) as exc:
            item.message = f"portrait non mis en file : {exc}"
    session.commit()
    if jobs:
        ctx.generation.notify()
    return CastBatchOut(items=items, jobs=[job_out(j) for j in jobs], cast=_cast(session, chapter))
