"""Étape « Scènes » d'un chapitre (pipeline/scenes.py) : liste des scènes, proposition de l'agent, retouches et
validation par l'auteur.

- `GET /chapters/{id}/scenes` : scènes (type, pages, résumé, lieu, pages de l'histoire rattachées), total face à la
  cible, suite reportée, validation, et les types de scène permis avec leur tempo en clair ;
- `PUT /chapters/{id}/scenes` : liste retouchée par l'auteur (changer le type, les pages, l'ordre, le résumé, le lieu,
  la distribution, ajouter, supprimer, fusionner) — une scène gardée est repérée par son `id` ; la validation est
  retirée ;
- `POST /chapters/{id}/scenes/propose` : « Proposer les scènes » (job en arrière-plan, progression via
  GET /jobs/{id}/events) ; remplace la liste ;
- `POST /chapters/{id}/scenes/validate` : « Valider les scènes » (le rôle de l'éditeur) : refusé tant que la somme
  des pages ne vaut pas la cible du chapitre. La distribution et le lieu de chaque scène descendent alors sur les
  cases déjà écrites (pipeline/scene_cast.py), sans écraser un choix de l'auteur.

Avertissements du pic (`peak_warnings`) : une scène au profil calme là où la courbe de rythme de l'ADN place un pic du
chapitre — affichés avant la validation, jamais bloquants.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline import scenes as sc
from ..pipeline import stage_gate as sg
from ..pipeline.scene_cast import descend_chapter
from ..presets import PresetError
from ..store.models import Chapter, Character, Job, JobStatus, PageKind, SeriesLocation
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import CardRef, JobOut
from .stages import get_chapter_or_404

router = APIRouter(tags=["scènes"])


class SceneTypeOut(BaseModel):
    id: str
    name: str
    description: str
    tempo: str  # profil de tempo en clair (ADN de la série + profil + ajustements de la série)


class SceneOut(BaseModel):
    id: int
    position: int
    title: str
    summary: str
    type: str
    pages: int
    location_id: int | None
    location_name: str | None
    # Distribution de la scène : fiches des personnages qui y jouent (id et nom), dans l'ordre.
    characters: list[CardRef] = Field(default_factory=list)
    page_numbers: list[int]  # pages de l'histoire rattachées à la scène (après le scénario)


class PeakWarningOut(BaseModel):
    scene_id: int
    message: str


class ChapterScenesOut(BaseModel):
    chapter_id: int
    project_id: int
    target_page_count: int
    total_pages: int
    validated: bool
    validated_at: datetime | None
    validated_by: str
    legacy: bool  # chapitre écrit sans scènes (« ancien mode »)
    problem: str | None  # pourquoi « Valider les scènes » est refusé, en français
    deferred: list[str]
    scenes: list[SceneOut]
    types: list[SceneTypeOut]
    available: bool  # presets/scene_types.yaml chargé
    # Scènes au profil calme qui portent un pic du chapitre (courbe de rythme de l'ADN) : avertissement seulement.
    peak_warnings: list[PeakWarningOut] = Field(default_factory=list)


class SceneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    type: str
    pages: int = Field(ge=1, le=60)
    location_id: int | None = None
    # Distribution (ids des fiches de la série) ; absente : celle de la scène gardée telle quelle.
    characters: Annotated[list[int], Field(max_length=30)] | None = None


class ScenesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenes: Annotated[list[SceneIn], Field(max_length=60)]
    deferred: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]], Field(max_length=20)
    ] = Field(default_factory=list)


class ScenesValidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


def scenes_out(session: Session, ctx: AppContext, chapter: Chapter) -> ChapterScenesOut:
    presets = ctx.agents.presets_for(chapter.project_id)
    settings = presets.scene_types
    names = dict(
        session.execute(
            select(SeriesLocation.id, SeriesLocation.name).where(SeriesLocation.project_id == chapter.project_id)
        ).all()
    )
    pages: dict[int, list[int]] = {}
    for page in chapter.pages:
        if page.kind == PageKind.story and page.scene_id is not None:
            pages.setdefault(page.scene_id, []).append(page.number)
    validated = sc.is_validated(chapter)
    cards = dict(
        session.execute(select(Character.id, Character.name).where(Character.project_id == chapter.project_id)).all()
    )
    return ChapterScenesOut(
        chapter_id=chapter.id,
        project_id=chapter.project_id,
        target_page_count=chapter.target_page_count,
        total_pages=sc.total_pages(chapter),
        validated=validated,
        validated_at=chapter.scenes_validated_at.replace(tzinfo=chapter.scenes_validated_at.tzinfo or UTC)
        if validated and chapter.scenes_validated_at
        else None,
        validated_by=chapter.scenes_validated_by if validated else "",
        legacy=sc.is_legacy(chapter),
        problem=sc.validation_problem(chapter, settings),
        deferred=list(chapter.scenes_deferred or []),
        scenes=[
            SceneOut(
                id=s.id,
                position=s.position,
                title=s.title,
                summary=s.summary,
                type=s.scene_type,
                pages=s.page_count,
                location_id=s.location_id,
                location_name=names.get(s.location_id) if s.location_id is not None else None,
                characters=[CardRef(id=i, name=cards[i]) for i in s.character_ids or [] if i in cards],
                page_numbers=sorted(pages.get(s.id, [])),
            )
            for s in chapter.scenes
        ],
        types=[
            SceneTypeOut(**{k: t[k] for k in ("id", "name", "description", "tempo")})
            for t in sc.types_for(presets, chapter.project)
        ],
        available=settings is not None,
        peak_warnings=[
            PeakWarningOut(scene_id=w.scene_id, message=w.message) for w in sc.peak_warnings(presets, chapter)
        ],
    )


@router.get("/chapters/{chapter_id}/scenes", response_model=ChapterScenesOut)
def read_scenes(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ChapterScenesOut:
    return scenes_out(session, ctx, get_chapter_or_404(session, chapter_id))


@router.put("/chapters/{chapter_id}/scenes", response_model=ChapterScenesOut)
def write_scenes(
    chapter_id: int, body: ScenesIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ChapterScenesOut:
    """Liste retouchée par l'auteur ; la validation est retirée (il revalide)."""
    chapter = get_chapter_or_404(session, chapter_id)
    settings = ctx.agents.presets_for(chapter.project_id).scene_types
    if settings is None:
        raise HTTPException(
            status_code=503, detail="presets/scene_types.yaml absent ou invalide : types de scène indisponibles"
        )
    if len(body.scenes) > settings.max_scenes:
        raise FieldError("scenes", f"{len(body.scenes)} scènes : {settings.max_scenes} au plus")
    own = {s.id for s in chapter.scenes}
    places = set(session.scalars(select(SeriesLocation.id).where(SeriesLocation.project_id == chapter.project_id)))
    cards = set(session.scalars(select(Character.id).where(Character.project_id == chapter.project_id)))
    seen: set[int] = set()
    data: list[sc.SceneData] = []
    for i, s in enumerate(body.scenes):
        kind = sc.type_key(s.type)
        if kind not in settings.types:
            raise FieldError(f"scenes.{i}.type", f"type « {s.type} » hors liste ({', '.join(settings.types)})")
        if s.pages > settings.max_pages_per_scene:
            raise FieldError(
                f"scenes.{i}.pages",
                f"{s.pages} pages : {settings.max_pages_per_scene} au plus par scène — découpe-la en deux",
            )
        if s.id is not None and (s.id not in own or s.id in seen):
            raise FieldError(f"scenes.{i}.id", "scène inconnue dans ce chapitre")
        if s.id is not None:
            seen.add(s.id)
        if s.location_id is not None and s.location_id not in places:
            raise FieldError(f"scenes.{i}.location_id", "lieu inconnu dans cette série")
        if s.characters is not None and any(c not in cards for c in s.characters):
            raise FieldError(f"scenes.{i}.characters", "personnage inconnu dans cette série")
        data.append(
            sc.SceneData(
                s.title,
                s.summary,
                kind,
                s.pages,
                s.location_id,
                s.id,
                character_ids=s.characters if s.characters is not None else (None if s.id is not None else []),
            )
        )
    sc.replace_scenes(session, chapter, data, body.deferred)
    session.commit()
    session.refresh(chapter)
    return scenes_out(session, ctx, chapter)


@router.post("/chapters/{chapter_id}/scenes/propose", response_model=JobOut, status_code=202)
def propose_scenes(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> JobOut:
    """« Proposer les scènes » : l'agent « Découpage en scènes » propose la liste (remplace la liste actuelle)."""
    chapter = get_chapter_or_404(session, chapter_id)
    if not chapter.synopsis.strip():
        raise FieldError("synopsis", "écris d'abord le synopsis ou le script brut du chapitre")
    presets = ctx.agents.presets_for(chapter.project_id)
    if presets.scene_types is None:
        raise HTTPException(
            status_code=503, detail="presets/scene_types.yaml absent ou invalide : types de scène indisponibles"
        )
    # Même LLM que le scénariste (écran « L'équipe »).
    llm, error = ctx.agents.llm_for_job("script", chapter.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'fournisseur LLM indisponible'}")
    try:
        presets.prompt("scenes")
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    running = session.scalar(
        select(Job.id).where(
            Job.chapter_id == chapter_id,
            Job.step == "scenes",
            Job.status.in_([JobStatus.pending, JobStatus.running]),
        )
    )
    if running is not None:
        raise HTTPException(status_code=409, detail="Un découpage en scènes de ce chapitre est déjà en cours")
    job = Job(project_id=chapter.project_id, chapter_id=chapter_id, step="scenes", message="En attente…")
    session.add(job)
    session.commit()
    ctx.jobs.submit(job.id, sc.scenes_job(ctx.db, presets, llm, chapter_id, knowledge=ctx.knowledge, job_id=job.id))
    return job_out(job)


@router.post("/chapters/{chapter_id}/scenes/validate", response_model=ChapterScenesOut)
def validate_scenes(
    chapter_id: int,
    body: ScenesValidateIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> ChapterScenesOut:
    """« Valider les scènes » (le rôle de l'éditeur) : la somme des pages doit valoir la cible du chapitre."""
    body = body or ScenesValidateIn()
    chapter = get_chapter_or_404(session, chapter_id)
    problem = sc.validation_problem(chapter, ctx.agents.presets_for(chapter.project_id).scene_types)
    if problem:
        raise FieldError("scenes", problem)
    sc.validate(chapter, body.author)
    # Distribution et lieu validés : ils descendent sur les cases déjà écrites (choix de l'auteur préservés).
    descend_chapter(session, chapter)
    state = sg.chapter_stages(session, chapter, stages=["scenes"])[0]
    # Trace de la validation (étape, auteur, date) dans les décisions de la garde d'étapes.
    sg.record_decision(session, chapter, state, "validated", author=body.author)
    session.commit()
    return scenes_out(session, ctx, chapter)
