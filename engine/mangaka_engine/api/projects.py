"""CRUD des séries (table historique « projects », routes /projects)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..pipeline.pages import change_reading_direction
from ..store.models import Chapter, Character, Page, Project, ReadingDirection, SeriesStatus
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projets"])


def project_out(project: Project, character_count: int, chapter_count: int, laid_out: int = 0) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        style=project.style,
        status=project.status.value,
        reading_direction=project.reading_direction.value,
        page_format=project.page_format,
        workflow_preset=project.workflow_preset,
        style_lora_name=project.style_lora_name,
        style_lora_weight=project.style_lora_weight,
        style_lora_trigger_words=project.style_lora_trigger_words or "",
        layout_style=project.layout_style,
        sketch_enabled=project.sketch_enabled,
        sketch_denoise=project.sketch_denoise,
        upscaler=project.upscaler,
        character_count=character_count,
        chapter_count=chapter_count,
        laid_out_page_count=laid_out,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def get_project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    return project


def _counts(session: Session, project_id: int) -> tuple[int, int, int]:
    chars = session.scalar(select(func.count()).where(Character.project_id == project_id)) or 0
    chapters = session.scalar(select(func.count()).where(Chapter.project_id == project_id)) or 0
    laid_out = (
        session.scalar(
            select(func.count())
            .select_from(Page)
            .join(Chapter, Page.chapter_id == Chapter.id)
            .where(Chapter.project_id == project_id, func.json_type(Page.layout) == "object")  # JSON null ≠ NULL
        )
        or 0
    )
    return chars, chapters, laid_out


def _check_presets(
    ctx: AppContext,
    page_format: str | None,
    workflow: str | None,
    layout_style: str | None = None,
    upscaler: str | None = None,
) -> None:
    if page_format is not None and page_format not in ctx.presets.page_formats:
        raise FieldError("page_format", f"format de page inconnu : « {page_format} »")
    if workflow is not None and workflow not in ctx.presets.workflows:
        raise FieldError("workflow_preset", f"workflow inconnu : « {workflow} »")
    if layout_style is not None and layout_style not in ctx.presets.layout_styles:
        raise FieldError("layout_style", f"style de mise en page inconnu : « {layout_style} »")
    if upscaler is not None and upscaler not in ctx.presets.upscalers:
        raise FieldError("upscaler", f"agrandisseur inconnu : « {upscaler} »")


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectOut]:
    chars = dict(session.execute(select(Character.project_id, func.count()).group_by(Character.project_id)).all())
    chapters = dict(session.execute(select(Chapter.project_id, func.count()).group_by(Chapter.project_id)).all())
    projects = session.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return [project_out(p, chars.get(p.id, 0), chapters.get(p.id, 0)) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ProjectOut:
    # Formats / workflow des nouvelles séries : profils globaux du metteur en page et du dessinateur.
    defaults = ctx.agents.presets_for(None).defaults
    page_format = body.page_format or (defaults.page_format if defaults else None)
    workflow = body.workflow_preset or (defaults.workflow if defaults else None)
    if page_format is None:
        raise FieldError("page_format", "aucun format de page par défaut : choisis-en un")
    if workflow is None:
        raise FieldError("workflow_preset", "aucun workflow par défaut : choisis-en un")
    layout_style = body.layout_style or ctx.presets.default_layout_style
    if layout_style is None:
        raise FieldError("layout_style", "aucun style de mise en page disponible (presets/layout_styles/)")
    _check_presets(ctx, page_format, workflow, layout_style, body.upscaler)
    project = Project(
        title=body.title,
        style=body.style,
        status=SeriesStatus(body.status),
        reading_direction=ReadingDirection(body.reading_direction),
        page_format=page_format,
        workflow_preset=workflow,
        style_lora_name=body.style_lora_name or None,
        style_lora_weight=body.style_lora_weight,
        style_lora_trigger_words=body.style_lora_trigger_words,
        layout_style=layout_style,
        # Palier croquis : activé pour les nouvelles séries sauf avis contraire (defaults.yaml).
        sketch_enabled=body.sketch_enabled
        if body.sketch_enabled is not None
        else defaults is None or defaults.sketch_enabled,
        sketch_denoise=body.sketch_denoise,
        upscaler=body.upscaler,
    )
    session.add(project)
    session.commit()
    return project_out(project, 0, 0)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, session: Session = Depends(get_session)) -> ProjectOut:
    project = get_project_or_404(session, project_id)
    return project_out(project, *_counts(session, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> ProjectOut:
    project = get_project_or_404(session, project_id)
    changes = body.model_dump(exclude_unset=True)
    for key in (
        "title",
        "page_format",
        "workflow_preset",
        "reading_direction",
        "style",
        "status",
        "style_lora_weight",
        "layout_style",
        "sketch_enabled",
    ):
        if key in changes and changes[key] is None:
            raise FieldError(key, "ne peut pas être vide")
    _check_presets(
        ctx,
        changes.get("page_format"),
        changes.get("workflow_preset"),
        changes.get("layout_style"),
        changes.get("upscaler"),
    )
    direction = changes.pop("reading_direction", None)
    if "status" in changes:
        changes["status"] = SeriesStatus(changes["status"])
    if "style_lora_name" in changes:
        changes["style_lora_name"] = changes["style_lora_name"] or None
    if "style_lora_trigger_words" in changes:
        changes["style_lora_trigger_words"] = changes["style_lora_trigger_words"] or ""
    for key, value in changes.items():
        setattr(project, key, value)
    if direction is not None:
        # Après les autres champs : un changement de format en même temps fait tout recalculer.
        change_reading_direction(ctx.agents.presets_for(project.id), project, ReadingDirection(direction))
    session.commit()
    return project_out(project, *_counts(session, project_id))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    project = get_project_or_404(session, project_id)
    session.delete(project)
    session.commit()
    ctx.agents.invalidate()  # surcharges d'agents de la série supprimées avec elle
    ctx.files.delete_tree(f"projects/{project_id}")
    return Response(status_code=204)
