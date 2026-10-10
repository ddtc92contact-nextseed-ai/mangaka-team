"""Direction artistique d'un chapitre : proposition de l'agent, corrections de l'auteur, application."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline import art_direction as da
from ..pipeline.library import SeriesLibrary
from ..presets import PresetError
from ..store.models import Job, JobStatus, Page, PageDirection, Panel
from .chapters import _load_pages, get_chapter_or_404, get_page_or_404, pages_out
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import JobOut, PageOut

router = APIRouter(tags=["direction artistique"])


# --- schémas ----------------------------------------------------------------------
class DirectionPanelOut(BaseModel):
    panel_id: int
    index: int
    intensity: str | None = None
    plan: str | None = None
    angle: str | None = None
    cadre: str | None = None
    ambiance: str = ""
    sfx: list[dict[str, str]] = Field(default_factory=list)
    # Bibliothèque proposée par l'agent (null : garder le décor / les objets du scénario).
    decor: int | None = None
    objets: list[int] | None = None


class PageDirectionOut(BaseModel):
    page_id: int
    number: int
    panel_count: int
    # null : pas encore de direction artistique pour cette page.
    rythme: str | None = None
    layout_style: str | None = None
    template: str | None = None
    page_choc: str | None = None
    rationale: str = ""
    panels: list[DirectionPanelOut] = Field(default_factory=list)
    has_direction: bool = False
    locks: list[str] = Field(default_factory=list)
    status: str = "proposed"  # proposed | accepted
    variant: int = 0
    out_of_date: bool = False  # cases modifiées depuis la proposition
    applied: bool = False  # déjà appliquée à la mise en page
    pending: bool = False  # choix différents de ceux appliqués
    applied_at: datetime | None = None


class Option(BaseModel):
    value: str
    label: str


class DirectionOptions(BaseModel):
    rythmes: list[str]
    intensities: list[str]
    plans: list[str]
    angles: list[str]
    cadres: list[str]
    page_chocs: list[str]
    sfx_intensities: list[str]
    styles: list[Option]
    templates: list[dict[str, Any]]


class ChapterDirectionOut(BaseModel):
    chapter_id: int
    variety: str
    variety_label: str
    series_layout_style: str
    pages: list[PageDirectionOut]
    options: DirectionOptions


class DirectionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: int | None = Field(default=None, description="Une seule page : « Proposer autre chose »")


class DirectionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: da.PageEdit | None = None
    panels: list[da.PanelEdit] = Field(default_factory=list, max_length=20)
    lock: list[str] = Field(default_factory=list, max_length=200)
    unlock: list[str] = Field(default_factory=list, max_length=200)
    accept: bool | None = None


class DirectionApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_ids: list[int] | None = Field(default=None, description="Pages à appliquer (toutes par défaut)")


class ApplyOut(BaseModel):
    applied: list[int]
    relaid: list[int]
    skipped: list[dict[str, Any]]
    message: str
    pages: list[PageOut]


# --- sorties ----------------------------------------------------------------------
def direction_out(page: Page) -> PageDirectionOut:
    d = page.direction
    base = PageDirectionOut(page_id=page.id, number=page.number, panel_count=len(page.panels))
    if d is None or not d.values:
        return base
    v = d.values
    index = {p.id: p.index for p in page.panels}
    return base.model_copy(
        update={
            "rythme": v.get("rythme"),
            "layout_style": v.get("layout_style"),
            "template": v.get("template"),
            "page_choc": v.get("page_choc"),
            "rationale": v.get("rationale") or "",
            "panels": [
                DirectionPanelOut(
                    panel_id=pa["panel_id"],
                    index=index.get(pa["panel_id"], -1),
                    **{k: pa.get(k) for k in ("intensity", "plan", "angle", "cadre")},
                    ambiance=pa.get("ambiance") or "",
                    sfx=list(pa.get("sfx") or []),
                    decor=pa.get("decor"),
                    objets=pa.get("objets"),
                )
                for pa in v.get("panels") or []
            ],
            "has_direction": True,
            "locks": list(d.locks or []),
            "status": d.status,
            "variant": d.variant or 0,
            "out_of_date": da.is_out_of_date(d, page),
            "applied": d.applied is not None,
            "pending": d.applied != d.values,
            "applied_at": d.applied_at,
        }
    )


def _story_pages(session: Session, chapter_id: int) -> list[Page]:
    pages = session.scalars(
        select(Page)
        .where(Page.chapter_id == chapter_id)
        .options(
            selectinload(Page.panels).selectinload(Panel.bubbles),
            selectinload(Page.direction),
        )
        .order_by(Page.number)
    ).all()
    return [p for p in pages if p.kind.value == "story" and p.panels]


@router.get("/chapters/{chapter_id}/direction", response_model=ChapterDirectionOut)
def get_direction(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ChapterDirectionOut:
    chapter = get_chapter_or_404(session, chapter_id)
    presets = ctx.agents.presets_for(chapter.project_id)
    try:
        variety = presets.prompt(da.PROMPT_ID).variety or "equilibree"
    except PresetError:
        variety = "equilibree"
    return ChapterDirectionOut(
        chapter_id=chapter.id,
        variety=variety,
        variety_label=da.VARIETY_LABELS.get(variety, variety),
        series_layout_style=chapter.project.layout_style,
        pages=[direction_out(p) for p in _story_pages(session, chapter_id)],
        options=DirectionOptions(
            rythmes=list(da.RYTHMES),
            intensities=list(da.INTENSITIES),
            plans=list(da.PLANS),
            angles=list(da.ANGLES),
            cadres=list(da.CADRES),
            page_chocs=list(da.PAGE_CHOCS),
            sfx_intensities=list(da.SFX_INTENSITIES),
            styles=[Option(value=s.id, label=s.name) for s in presets.layout_styles.values()],
            templates=[
                {"id": t.id, "name": t.name, "panel_count": t.panel_count} for t in presets.layout_templates.values()
            ],
        ),
    )


# --- lancement --------------------------------------------------------------------
@router.post("/chapters/{chapter_id}/direction", response_model=JobOut, status_code=202)
def start_direction(
    chapter_id: int,
    body: DirectionStart | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> JobOut:
    """Lance l'agent sur tout le chapitre, ou sur une page (`page_id`, « Proposer autre chose »)."""
    chapter = get_chapter_or_404(session, chapter_id)
    page_id = body.page_id if body else None
    pages = _story_pages(session, chapter_id)
    if not pages:
        raise FieldError("chapter", "aucune page à diriger : découpe d'abord le chapitre dans l'onglet Scénario")
    if page_id is not None and all(p.id != page_id for p in pages):
        raise FieldError("page_id", "page inconnue dans ce chapitre (ou page sans case)")
    presets = ctx.agents.presets_for(chapter.project_id)
    llm, error = ctx.agents.llm_for_job(da.STEP, chapter.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'fournisseur LLM indisponible'}")
    try:
        presets.prompt(da.PROMPT_ID)
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    running = session.scalar(
        select(Job.id).where(
            Job.chapter_id == chapter_id,
            Job.step == da.STEP,
            Job.status.in_([JobStatus.pending, JobStatus.running]),
        )
    )
    if running is not None:
        raise HTTPException(status_code=409, detail="La direction artistique de ce chapitre est déjà en cours")
    job = Job(
        project_id=chapter.project_id,
        chapter_id=chapter_id,
        step=da.STEP,
        message="En attente…",
        params={"page_id": page_id} if page_id is not None else {},
    )
    session.add(job)
    session.commit()
    ctx.jobs.submit(
        job.id,
        da.direction_job(ctx.db, presets, llm, chapter_id, page_id=page_id, knowledge=ctx.knowledge, job_id=job.id),
    )
    return job_out(job)


# --- corrections de l'auteur ------------------------------------------------------
@router.patch("/pages/{page_id}/direction", response_model=PageDirectionOut)
def edit_direction(
    page_id: int, body: DirectionEdit, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PageDirectionOut:
    """Modifie des choix (chaque champ modifié est verrouillé), verrouille / déverrouille, accepte la page."""
    page = get_page_or_404(session, page_id)
    presets = ctx.agents.presets_for(page.chapter.project_id)
    try:
        d = da.edit_direction(
            presets, page, page_fields=body.page, panels=body.panels, unlock=body.unlock, lock=body.lock
        )
    except da.ArtDirectionError as exc:
        raise FieldError("direction", str(exc)) from None
    if body.accept is not None:
        d.status = "accepted" if body.accept else "proposed"
    session.commit()
    return direction_out(page)


# --- application ------------------------------------------------------------------
@router.post("/chapters/{chapter_id}/direction/apply", response_model=ApplyOut)
def apply_direction(
    chapter_id: int,
    body: DirectionApply | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> ApplyOut:
    """« Appliquer à la mise en page » : seules les pages dont la mise en page change sont recalculées."""
    chapter = get_chapter_or_404(session, chapter_id)
    pages = _load_pages(session, chapter_id)
    if body is not None and body.page_ids is not None:
        wanted = set(body.page_ids)
        unknown = wanted - {p.id for p in pages}
        if unknown:
            raise FieldError("page_ids", "page inconnue dans ce chapitre")
        targets = [p for p in pages if p.id in wanted]
    else:
        targets = pages
    targets = [p for p in targets if session.scalar(select(PageDirection.id).where(PageDirection.page_id == p.id))]
    if not targets:
        raise FieldError("direction", "aucune direction artistique à appliquer : lance d'abord l'agent")
    library = SeriesLibrary.load(session, chapter.project_id)
    result = da.apply_direction(ctx.agents.presets_for(chapter.project_id), targets, library)
    session.commit()
    parts = []
    if result.applied:
        n = len(result.applied)
        parts.append(f"{n} page{'s' if n > 1 else ''} appliquée{'s' if n > 1 else ''}")
        r = len(result.relaid)
        parts.append(
            f"{r} mise{'s' if r > 1 else ''} en page recalculée{'s' if r > 1 else ''}"
            if r
            else "aucune mise en page à recalculer"
        )
    if result.skipped:
        parts.append(
            f"{len(result.skipped)} page{'s' if len(result.skipped) > 1 else ''} ignorée{'s' if len(result.skipped) > 1 else ''}"
        )
    return ApplyOut(
        applied=result.applied,
        relaid=result.relaid,
        skipped=result.skipped,
        message=" · ".join(parts) or "rien à appliquer",
        pages=pages_out(session, ctx, _load_pages(session, chapter_id)),
    )
