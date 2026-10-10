"""« Générer le chapitre » en un clic : mise en page des pages qui n'en ont pas, puis file de génération
de toutes les cases des pages de l'histoire et bonus (croquis d'abord si le palier croquis est activé)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..pipeline.generation import panels_to_generate
from ..pipeline.pages import is_stale
from ..pipeline.sketch import enqueue_clean, enqueue_sketch, panels_to_clean, panels_to_sketch
from ..store.models import Job, Page, PageKind, Panel
from .chapters import _layout
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import _enqueue, _presets, _require_comfyui, lock_problem
from .jobs import job_out
from .schemas import ChapterProductionOut, ChapterProductionPlanOut, ProductionModeName
from .sketch import _chapter_pages, _require_clean_mode, _run

router = APIRouter(tags=["génération"])

# Pages produites par « Générer le chapitre » (la page de garde se génère depuis sa page).
KINDS = (PageKind.story, PageKind.bonus)


@dataclass
class Plan:
    mode: ProductionModeName
    pages: list[Page]  # pages de l'histoire et bonus qui ont des cases
    to_layout: list[Page]  # sans mise en page (ou obsolète et sans aucune image)


def _plan(session: Session, chapter_id: int) -> Plan:
    pages = [p for p in _chapter_pages(session, chapter_id) if p.kind in KINDS and p.panels]
    # Une page obsolète déjà (en partie) générée garde sa géométrie : la recalculer recadrerait ses images.
    to_layout = [p for p in pages if p.layout is None or (is_stale(p) and not any(pa.images for pa in p.panels))]
    sketch = bool(pages) and pages[0].chapter.project.sketch_enabled
    return Plan(mode="sketch" if sketch else "final", pages=pages, to_layout=to_layout)


def _selection(session: Session, ctx: AppContext, plan: Plan) -> tuple[list[Panel], list[Panel]]:
    """(cases à croquer ou générer, cases à passer au propre)."""
    if plan.mode == "sketch":
        return panels_to_sketch(session, plan.pages), panels_to_clean(session, plan.pages)
    panels = [p for p in panels_to_generate(session, plan.pages, force=False) if lock_problem(ctx, p) is None]
    return panels, []


@router.get("/chapters/{chapter_id}/produce", response_model=ChapterProductionPlanOut)
def production_plan(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ChapterProductionPlanOut:
    """Ce que « Générer le chapitre » mettra en file (rien n'est modifié)."""
    plan = _plan(session, chapter_id)
    panels, to_clean = _selection(session, ctx, plan)
    touched = {p.page_id for p in panels + to_clean} | {p.id for p in plan.to_layout}
    return ChapterProductionPlanOut(
        mode=plan.mode,
        panels=len(panels),
        to_clean=len(to_clean),
        pages=len(touched),
        unlaid_pages=[p.number for p in plan.to_layout],
        total=sum(len(p.panels) for p in plan.pages),
    )


@router.post("/chapters/{chapter_id}/produce", response_model=ChapterProductionOut, status_code=202)
def produce_chapter(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ChapterProductionOut:
    """Met en page les pages qui n'en ont pas, puis met en file (file unique, une génération à la fois) :
    - palier croquis activé : un croquis par case non validée, et le passage au propre des croquis
      validés qui n'en ont pas encore ;
    - sinon : une version de chaque case sans version choisie.
    Les cases déjà en file sont laissées telles quelles ; l'avancement se suit dans Production."""
    _require_comfyui(ctx)
    plan = _plan(session, chapter_id)
    for page in plan.to_layout:  # dans l'ordre : chaque page tient compte du gabarit de la précédente
        _layout(ctx, page)
    session.flush()
    panels, to_clean = _selection(session, ctx, plan)
    if to_clean:
        try:
            _require_clean_mode(ctx, plan.pages)
        except FieldError:
            to_clean = []  # passage au propre impossible ici (ControlNet absent) : les croquis partent quand même
    jobs: list[Job] = []
    for panel in panels:
        presets = _presets(ctx, panel)
        if plan.mode == "sketch":
            jobs.append(_run(panel, lambda p=panel, r=presets: enqueue_sketch(session, r, p, knowledge=ctx.knowledge)))
        else:
            jobs += _enqueue(session, ctx, panel)
    for panel in to_clean:
        presets = _presets(ctx, panel)
        jobs.append(_run(panel, lambda p=panel, r=presets: enqueue_clean(session, r, p, knowledge=ctx.knowledge)))
    session.commit()
    ctx.generation.notify()
    total = sum(len(p.panels) for p in plan.pages)
    return ChapterProductionOut(
        mode=plan.mode,
        jobs=[job_out(j) for j in jobs],
        panel_ids=[p.id for p in panels],
        cleaned_panel_ids=[p.id for p in to_clean],
        laid_out_pages=[p.number for p in plan.to_layout],
        skipped=total - len(panels) - len(to_clean),
    )
