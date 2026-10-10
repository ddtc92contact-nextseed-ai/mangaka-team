"""Finition d'impression : agrandir la version retenue des cases jusqu'au dpi cible avant l'assemblage."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline.finishing import (
    FinishingError,
    active_finishing,
    enqueue_finish,
    enqueue_pages,
    panel_print_info,
    resolve_upscaler,
)
from ..store.models import Page
from .chapters import get_chapter_or_404, get_page_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import _require_comfyui, get_panel_or_404
from .jobs import job_out
from .schemas import FinishBatchOut, JobOut, PageFinishingOut, UpscalerOut

router = APIRouter(tags=["finition d'impression"])


@router.get("/presets/upscalers", response_model=list[UpscalerOut])
def list_upscalers(ctx: AppContext = Depends(get_ctx)) -> list[UpscalerOut]:
    """Agrandisseurs (presets/upscalers/) : le défaut d'abord, la haute fidélité en dernier."""
    presets = ctx.agents.presets_for(None)
    default = presets.default_upscaler
    ups = sorted(
        presets.upscalers.values(),
        key=lambda u: (u.preset.id != default, u.preset.high_fidelity, u.preset.name.lower()),
    )
    return [
        UpscalerOut(
            id=u.preset.id,
            name=u.preset.name,
            description=u.preset.description,
            model_scale=u.preset.model_scale,
            high_fidelity=u.preset.high_fidelity,
            is_default=u.preset.id == default,
            estimated_s=u.preset.estimated_s,
            timeout_s=u.preset.timeout_s,
        )
        for u in ups
    ]


@router.get("/pages/{page_id}/finishing", response_model=PageFinishingOut)
def page_finishing(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PageFinishingOut:
    """Dpi d'impression de chaque case de la page et finitions en cours."""
    page = get_page_or_404(session, page_id)
    presets = ctx.agents.presets_for(page.chapter.project_id)
    try:
        upscaler: str | None = resolve_upscaler(presets, page.chapter.project).preset.name
    except FinishingError:
        upscaler = None
    return PageFinishingOut(
        page_id=page.id,
        upscaler=upscaler,
        panels={p.id: panel_print_info(presets, ctx.files, p) for p in page.panels},  # type: ignore[misc]
        active_jobs=[job_out(j) for j in active_finishing(session, [p.id for p in page.panels]).values()],
    )


@router.post("/panels/{panel_id}/finish", response_model=JobOut, status_code=202)
def finish_panel(panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)) -> JobOut:
    """« Finaliser cette case » : agrandit la version retenue jusqu'au dpi cible (refus lisible si inutile)."""
    _require_comfyui(ctx)
    panel = get_panel_or_404(session, panel_id)
    try:
        job = enqueue_finish(session, ctx.agents.presets_for(panel.page.chapter.project_id), ctx.files, panel)
    except FinishingError as exc:
        raise FieldError("finish", str(exc)) from None
    session.commit()
    ctx.generation.notify()
    return job_out(job)


def _finish_pages(session: Session, ctx: AppContext, pages: list[Page]) -> FinishBatchOut:
    _require_comfyui(ctx)
    try:
        jobs, skipped = enqueue_pages(session, ctx.agents.presets_for, ctx.files, pages)
    except FinishingError as exc:
        raise FieldError("finish", str(exc)) from None
    session.commit()
    ctx.generation.notify()
    return FinishBatchOut(
        jobs=[job_out(j) for j in jobs], panel_ids=[j.panel_id for j in jobs if j.panel_id], skipped=skipped
    )


@router.post("/pages/{page_id}/finish", response_model=FinishBatchOut, status_code=202)
def finish_page(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FinishBatchOut:
    """« Finaliser la page » : met en file la finition des cases dont la version retenue est sous le seuil."""
    return _finish_pages(session, ctx, [get_page_or_404(session, page_id)])


@router.post("/chapters/{chapter_id}/finish", response_model=FinishBatchOut, status_code=202)
def finish_chapter(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FinishBatchOut:
    """« Finaliser le chapitre » (avant l'export d'impression) : toutes les cases sous le seuil."""
    get_chapter_or_404(session, chapter_id)
    pages = list(
        session.scalars(
            select(Page).where(Page.chapter_id == chapter_id).options(selectinload(Page.panels)).order_by(Page.number)
        )
    )
    return _finish_pages(session, ctx, pages)
