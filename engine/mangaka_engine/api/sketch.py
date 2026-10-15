"""Palier croquis : croquer une case / une page / un chapitre, trier, passer au propre (voir pipeline/sketch.py) ;
name : valider la planche brouillon page par page, couper une case en deux (voir pipeline/name_board.py)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline.composition import type_problem
from ..pipeline.estimate import estimate_panels
from ..pipeline.generation import GenerationError, update_panel_prompt
from ..pipeline.journal import note_regenerated, record_event
from ..pipeline.layout import LayoutError
from ..pipeline.name_board import NameBoardError, split_panel, unvalidate_page_name, validate_page_name
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
from .chapters import _page_out, get_chapter_or_404, get_page_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import _estimate_out, _presets, _require_comfyui, get_panel_or_404, panel_detail
from .jobs import job_out
from .schemas import (
    BatchGenerateOut,
    CleanIn,
    JobOut,
    NameValidateIn,
    PageOut,
    PanelDetailOut,
    PanelSplitIn,
    PanelSplitOut,
    SketchEstimateOut,
    SketchIn,
    SketchValidateIn,
)
from .stages import gate

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
    note_regenerated(session, panel, "resketch", sketch=True)
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
        validated = validate_sketch(panel, image)
    except GenerationError as exc:
        raise FieldError("image_id", str(exc)) from None
    record_event(session, verdict="validated", action="validate_sketch", image_id=validated.id, panel_id=panel.id)
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
    # Le propre part d'une name relue : page validée (palier croquis), ou étape forcée. Sans croquis retenu,
    # l'erreur de la case (« aucun croquis validé ») passe d'abord.
    if validated_sketch(panel) is not None:
        gate(session, panel.page.chapter, "clean", page=panel.page, only=("name",))
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
        if pages:  # les versions propres sont des générations, d'une name validée (les croquis restent libres)
            gate(session, pages[0].chapter, "clean", page=pages[0] if len(pages) == 1 else None)
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


# --- name : valider la planche brouillon, couper une case ------------------------------------
@router.post("/pages/{page_id}/name/validate", response_model=PageOut)
def validate_name(
    page_id: int,
    body: NameValidateIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PageOut:
    """« Valider la name » de la page : ses croquis retenus (le dernier, pour une case sans croquis retenu)
    deviennent la source de composition du propre. Une case modifiée ensuite dévalide la page."""
    page = get_page_or_404(session, page_id)
    try:
        validate_page_name(session, page, author=body.author if body else "")
    except NameBoardError as exc:
        raise FieldError("name", str(exc)) from None
    record_event(
        session,
        verdict="validated",
        action="validate_name",
        note=f"Chapitre {page.chapter.number} · name de la page {page.number} validée",
    )
    session.commit()
    return _page_out(ctx, page)


@router.delete("/pages/{page_id}/name/validate", response_model=PageOut)
def unvalidate_name(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PageOut:
    """Retire la validation de la name : la page repasse « à valider » (les croquis retenus restent)."""
    page = get_page_or_404(session, page_id)
    unvalidate_page_name(session, page)
    session.commit()
    return _page_out(ctx, page)


@router.post("/panels/{panel_id}/split", response_model=PanelSplitOut)
def split(
    panel_id: int,
    body: PanelSplitIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PanelSplitOut:
    """« Couper la case en deux » : nouvelle case juste après, page remise en page ; seules les deux cases
    touchées sont re-croquées (palier croquis), les versions et croquis des autres cases ne changent pas."""
    body = body or PanelSplitIn()
    panel = get_panel_or_404(session, panel_id)
    page = panel.page
    presets = _presets(ctx, panel)
    try:
        new = split_panel(
            session, presets, panel, first=body.first, second=body.second, move_bubble_ids=body.move_bubble_ids
        )
    except NameBoardError as exc:
        raise FieldError("split", str(exc)) from None
    except (LayoutError, PresetError) as exc:
        raise FieldError("layout", f"page {page.number} : {exc}") from None
    touched = [panel, new]
    for p in touched:
        update_panel_prompt(presets, session, p, ctx.knowledge, reset=True)
    record_event(
        session,
        verdict="edited",
        action="split_panel",
        panel_id=panel.id,
        note=f"Chapitre {page.chapter.number} · case {panel.index + 1} de la page {page.number} coupée en deux",
    )
    jobs: list[Job] = []
    note: str | None = None
    if body.sketch:
        if not page.chapter.project.sketch_enabled:
            note = "palier croquis désactivé pour cette série : rien n'est re-croqué"
        elif ctx.providers.comfyui is None:
            why = ctx.providers.errors.get("comfyui", "client non configuré")
            note = f"rien n'est re-croqué : ComfyUI indisponible ({why})"
        else:
            try:
                for p in touched:
                    jobs.append(_run(p, lambda p=p: enqueue_sketch(session, presets, p, knowledge=ctx.knowledge)))
            except FieldError as exc:
                note = f"re-croquis impossible : {exc.message}"
    session.commit()
    if jobs:
        ctx.generation.notify()
    session.refresh(page)
    return PanelSplitOut(
        page=_page_out(ctx, page), panel_ids=[p.id for p in touched], jobs=[job_out(j) for j in jobs], sketch_note=note
    )
