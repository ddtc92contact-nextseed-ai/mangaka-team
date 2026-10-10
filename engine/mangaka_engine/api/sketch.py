"""Palier croquis : croquer une case / une page / un chapitre, trier, passer au propre (voir pipeline/sketch.py)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline.composition import type_problem
from ..pipeline.estimate import estimate_panels
from ..pipeline.generation import GenerationError
from ..pipeline.sketch import (
    clean_preset_id,
    enqueue_clean,
    enqueue_sketch,
    panels_to_clean,
    panels_to_sketch,
    require_sketch_enabled,
    sketch_preset_id,
    validate_sketch,
    validated_sketch,
)
from ..presets import PresetError
from ..store.models import Job, Page, Panel, PanelImage
from .chapters import get_chapter_or_404, get_page_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import _estimate_out, _presets, _require_comfyui, get_panel_or_404, panel_detail
from .jobs import job_out
from .schemas import (
    BatchGenerateOut,
    CleanIn,
    JobOut,
    PanelDetailOut,
    SketchEstimateOut,
    SketchIn,
    SketchValidateIn,
)

router = APIRouter(tags=["croquis"])


def _run(panel: Panel, action: Callable[[], Job]) -> Job:
    try:
        return action()
    except PresetError as exc:
        raise FieldError("preset", str(exc)) from None
    except GenerationError as exc:
        raise FieldError("panel", f"case {panel.index + 1} de la page {panel.page.number} : {exc}") from None


def _chapter_pages(session: Session, chapter_id: int) -> list[Page]:
    get_chapter_or_404(session, chapter_id)
    return list(
        session.scalars(
            select(Page)
            .where(Page.chapter_id == chapter_id)
            .options(selectinload(Page.panels).selectinload(Panel.images))
            .order_by(Page.number)
        )
    )


def _require_enabled(pages: list[Page]) -> None:
    panel = next((p for page in pages for p in page.panels), None)
    if panel is None:
        return
    try:
        require_sketch_enabled(panel)
    except GenerationError as exc:
        raise FieldError("sketch_enabled", str(exc)) from None


def _require_clean_mode(ctx: AppContext, pages: list[Page]) -> None:
    """Passage au propre par ControlNet alors que ComfyUI ne l'a pas : message clair, rien en file."""
    panel = next((p for page in pages for p in page.panels), None)
    project = panel.page.chapter.project if panel is not None else None
    if project is None or project.clean_mode != "controlnet":
        return
    status = ctx.control_status()
    problem = type_problem(status, project.clean_control or str(status.get("default_type") or ""))
    if problem is not None:
        raise FieldError(
            "clean_mode",
            f"passage au propre par ControlNet impossible : {problem[:1].lower()}{problem[1:]} "
            "Repasse la série en img2img (fiche série) ou mets ComfyUI à jour.",
        )


# --- une case -------------------------------------------------------------------------------
@router.post("/panels/{panel_id}/sketch", response_model=list[JobOut], status_code=202)
def sketch_panel(
    panel_id: int,
    body: SketchIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> list[JobOut]:
    """Croque (ou re-croque, nouvelle graine) la case ; annule la validation de son croquis."""
    _require_comfyui(ctx)
    panel = get_panel_or_404(session, panel_id)
    seed = body.seed if body else None
    job = _run(panel, lambda: enqueue_sketch(session, _presets(ctx, panel), panel, seed=seed, knowledge=ctx.knowledge))
    session.commit()
    ctx.generation.notify()
    return [job_out(job)]


@router.post("/panels/{panel_id}/sketch/validate", response_model=PanelDetailOut)
def validate_panel_sketch(
    panel_id: int,
    body: SketchValidateIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PanelDetailOut:
    """Valide la composition : le croquis donné, sinon le plus récent."""
    panel = get_panel_or_404(session, panel_id)
    image = None
    if body is not None and body.image_id is not None:
        image = session.get(PanelImage, body.image_id)
        if image is None or image.panel_id != panel.id:
            raise FieldError("image_id", "croquis introuvable pour cette case")
    try:
        validate_sketch(panel, image)
    except GenerationError as exc:
        raise FieldError("image_id", str(exc)) from None
    session.commit()
    return panel_detail(session, ctx, panel)


@router.delete("/panels/{panel_id}/sketch/validate", response_model=PanelDetailOut)
def unvalidate_panel_sketch(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDetailOut:
    """Retire la validation : la case repasse « à trier »."""
    panel = get_panel_or_404(session, panel_id)
    panel.sketch_image_id = None
    session.commit()
    return panel_detail(session, ctx, panel)


@router.post("/panels/{panel_id}/clean", response_model=list[JobOut], status_code=202)
def clean_panel(
    panel_id: int,
    body: CleanIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> list[JobOut]:
    """« Passer au propre » : version finale au palier de la série depuis le croquis validé."""
    _require_comfyui(ctx)
    panel = get_panel_or_404(session, panel_id)
    _require_clean_mode(ctx, [panel.page])
    denoise = body.denoise if body else None
    job = _run(
        panel, lambda: enqueue_clean(session, _presets(ctx, panel), panel, denoise=denoise, knowledge=ctx.knowledge)
    )
    session.commit()
    ctx.generation.notify()
    return [job_out(job)]


# --- page / chapitre ------------------------------------------------------------------------
def _batch(
    session: Session, ctx: AppContext, pages: list[Page], select_panels: Callable[..., list[Panel]], action: str
) -> BatchGenerateOut:
    _require_comfyui(ctx)
    _require_enabled(pages)
    if action == "clean":
        _require_clean_mode(ctx, pages)
    total = sum(len(p.panels) for p in pages)
    panels = select_panels(session, pages)
    jobs: list[Job] = []
    for panel in panels:
        presets = _presets(ctx, panel)
        if action == "sketch":
            jobs.append(_run(panel, lambda p=panel, r=presets: enqueue_sketch(session, r, p, knowledge=ctx.knowledge)))
        else:
            jobs.append(_run(panel, lambda p=panel, r=presets: enqueue_clean(session, r, p, knowledge=ctx.knowledge)))
    session.commit()
    ctx.generation.notify()
    return BatchGenerateOut(
        jobs=[job_out(j) for j in jobs], panel_ids=[p.id for p in panels], skipped=total - len(panels)
    )


@router.post("/pages/{page_id}/sketch", response_model=BatchGenerateOut, status_code=202)
def sketch_page(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BatchGenerateOut:
    """« Croquer la page » : un croquis par case non encore validée (ni version propre, ni croquis validé)."""
    return _batch(session, ctx, [get_page_or_404(session, page_id)], panels_to_sketch, "sketch")


@router.post("/chapters/{chapter_id}/sketch", response_model=BatchGenerateOut, status_code=202)
def sketch_chapter(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BatchGenerateOut:
    """« Croquer le chapitre », page par page."""
    return _batch(session, ctx, _chapter_pages(session, chapter_id), panels_to_sketch, "sketch")


@router.post("/pages/{page_id}/clean", response_model=BatchGenerateOut, status_code=202)
def clean_page(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BatchGenerateOut:
    """« Passer au propre » les cases validées de la page (une fois par croquis validé)."""
    return _batch(session, ctx, [get_page_or_404(session, page_id)], panels_to_clean, "clean")


@router.post("/chapters/{chapter_id}/clean", response_model=BatchGenerateOut, status_code=202)
def clean_chapter(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BatchGenerateOut:
    """« Passer au propre » les cases validées du chapitre."""
    return _batch(session, ctx, _chapter_pages(session, chapter_id), panels_to_clean, "clean")


# --- temps estimé ---------------------------------------------------------------------------
def _sketch_estimate(session: Session, ctx: AppContext, pages: list[Page]) -> SketchEstimateOut:
    to_sketch = panels_to_sketch(session, pages, include_busy=True)
    to_clean = panels_to_clean(session, pages, include_busy=True)
    return SketchEstimateOut(
        panels=sum(len(p.panels) for p in pages),
        to_sketch=len(to_sketch),
        validated=sum(1 for page in pages for p in page.panels if validated_sketch(p) is not None),
        to_clean=len(to_clean),
        sketch=_estimate_out(
            estimate_panels(session, ctx.agents.presets_for, to_sketch, lambda r, _p, e: sketch_preset_id(r, e))
        ),
        clean=_estimate_out(estimate_panels(session, ctx.agents.presets_for, to_clean, clean_preset_id)),
    )


@router.get("/pages/{page_id}/sketch-estimate", response_model=SketchEstimateOut)
def page_sketch_estimate(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> SketchEstimateOut:
    """Temps estimés « croquis de la page » et « passage au propre des cases validées »."""
    return _sketch_estimate(session, ctx, [get_page_or_404(session, page_id)])


@router.get("/chapters/{chapter_id}/sketch-estimate", response_model=SketchEstimateOut)
def chapter_sketch_estimate(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> SketchEstimateOut:
    return _sketch_estimate(session, ctx, _chapter_pages(session, chapter_id))
