"""Name scène par scène (pipeline/scene_name.py) : mesure de chaque scène face à son profil, et réécriture d'une
seule scène (scénario ou direction artistique) sans toucher aux autres.

- `GET /chapters/{id}/scenes/measure` : par scène, cases, répliques, cases muettes et encadrés par planche, plans
  appliqués et proposés, face au profil de la scène ; les écarts sont des avertissements, jamais des blocages ;
- `POST /chapters/{id}/scenes/{scene_id}/script` : réécrit la name de cette scène seulement (job « script ») ;
- `POST /chapters/{id}/scenes/{scene_id}/direction` : redirige cette scène seulement (job « direction artistique »).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline import art_direction as da
from ..pipeline import scene_name as sn
from ..pipeline import scenes as sc
from ..pipeline.script import script_job
from ..presets import PresetError
from ..store.models import Chapter, Job, JobStatus
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import JobOut
from .stages import get_chapter_or_404

router = APIRouter(tags=["scènes"])


class PageMeasureOut(BaseModel):
    page_id: int
    number: int
    panels: int
    replies: int
    silent: int
    narration: int
    warnings: list[str] = Field(default_factory=list)


class SceneMeasureOut(BaseModel):
    scene_id: int
    number: int
    title: str
    type: str
    type_name: str
    tempo: str
    planned_pages: int
    # Attendu par le profil de la scène : cases, répliques (min / max), cases muettes (min), encadrés de narration
    # (max, null = libre), lignes de mouvement (« required » / « forbidden » / null), parts de plans visées.
    expected: dict[str, Any]
    pages: list[PageMeasureOut]
    # Plans : total des cases, plans appliqués aux cases et proposés par la direction, comptés par famille.
    shots: dict[str, Any]
    warnings: list[str]


class SceneMeasuresOut(BaseModel):
    chapter_id: int
    scene_mode: bool  # chapitre écrit (ou à écrire) scène par scène
    scenes: list[SceneMeasureOut]


@router.get("/chapters/{chapter_id}/scenes/measure", response_model=SceneMeasuresOut)
def measure_scenes(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> SceneMeasuresOut:
    chapter = get_chapter_or_404(session, chapter_id)
    presets = ctx.agents.presets_for(chapter.project_id)
    data = sn.scene_measures(presets, chapter)
    return SceneMeasuresOut(chapter_id=chapter.id, scene_mode=data["scene_mode"], scenes=data["scenes"])


def _frame(ctx: AppContext, chapter: Chapter, scene_id: int) -> tuple[sn.SceneFrame, list[sn.SceneFrame]]:
    presets = ctx.agents.presets_for(chapter.project_id)
    if not sc.is_validated(chapter):
        raise FieldError("scenes", "liste des scènes pas encore validée : valide-la dans l'onglet Scènes")
    frames = sn.scene_frames(presets, chapter)
    frame = sn.frame_of(frames, scene_id)
    if frame is None:
        raise FieldError("scene_id", "scène inconnue dans ce chapitre")
    return frame, frames


def _busy(session: Session, chapter_id: int, step: str) -> bool:
    return (
        session.scalar(
            select(Job.id).where(
                Job.chapter_id == chapter_id,
                Job.step == step,
                Job.status.in_([JobStatus.pending, JobStatus.running]),
            )
        )
        is not None
    )


@router.post("/chapters/{chapter_id}/scenes/{scene_id}/script", response_model=JobOut, status_code=202)
def rewrite_scene(
    chapter_id: int, scene_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> JobOut:
    """Réécrit la name d'une seule scène : ses pages sont remplacées, celles des autres scènes (cases, croquis,
    versions) restent telles quelles."""
    chapter = get_chapter_or_404(session, chapter_id)
    if not chapter.synopsis.strip():
        raise FieldError("synopsis", "écris d'abord le synopsis ou le script brut du chapitre")
    _, frames = _frame(ctx, chapter, scene_id)
    if not sn.scene_mode(chapter, frames):
        raise FieldError(
            "scene_id",
            "des pages du chapitre ne sont rattachées à aucune scène : réécris d'abord tout le chapitre (« Découper »)",
        )
    presets = ctx.agents.presets_for(chapter.project_id)
    llm, error = ctx.agents.llm_for_job("script", chapter.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'fournisseur LLM indisponible'}")
    try:
        presets.prompt("script")
        presets.prompt(sn.SCENE_PROMPT)
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    if _busy(session, chapter_id, "script"):
        raise HTTPException(status_code=409, detail="Un découpage de ce chapitre est déjà en cours")
    job = Job(
        project_id=chapter.project_id,
        chapter_id=chapter_id,
        step="script",
        message="En attente…",
        params={"scene_id": scene_id},
    )
    session.add(job)
    session.commit()
    ctx.jobs.submit(
        job.id,
        script_job(ctx.db, presets, llm, chapter_id, knowledge=ctx.knowledge, job_id=job.id, scene_id=scene_id),
    )
    return job_out(job)


@router.post("/chapters/{chapter_id}/scenes/{scene_id}/direction", response_model=JobOut, status_code=202)
def redirect_scene(
    chapter_id: int, scene_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> JobOut:
    """Redirige une seule scène : ses pages reçoivent une nouvelle proposition (verrous de l'auteur gardés), la
    direction des autres scènes reste telle quelle."""
    chapter = get_chapter_or_404(session, chapter_id)
    frame, frames = _frame(ctx, chapter, scene_id)
    if not sn.scene_mode(chapter, frames) or not sn.scene_pages(chapter, frame):
        raise FieldError("scene_id", "scène sans pages écrites scène par scène : écris d'abord son scénario")
    presets = ctx.agents.presets_for(chapter.project_id)
    llm, error = ctx.agents.llm_for_job(da.STEP, chapter.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'fournisseur LLM indisponible'}")
    try:
        presets.prompt(da.PROMPT_ID)
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    if _busy(session, chapter_id, da.STEP):
        raise HTTPException(status_code=409, detail="La direction artistique de ce chapitre est déjà en cours")
    job = Job(
        project_id=chapter.project_id,
        chapter_id=chapter_id,
        step=da.STEP,
        message="En attente…",
        params={"scene_id": scene_id},
    )
    session.add(job)
    session.commit()
    ctx.jobs.submit(
        job.id,
        da.direction_job(ctx.db, presets, llm, chapter_id, knowledge=ctx.knowledge, job_id=job.id, scene_id=scene_id),
    )
    return job_out(job)
