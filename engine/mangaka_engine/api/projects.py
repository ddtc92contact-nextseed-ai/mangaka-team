"""CRUD des projets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..store.models import Character, Project, ReadingDirection
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projets"])


def project_out(project: Project, character_count: int) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        style=project.style,
        reading_direction=project.reading_direction.value,
        page_format=project.page_format,
        workflow_preset=project.workflow_preset,
        character_count=character_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def get_project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return project


def _count_characters(session: Session, project_id: int) -> int:
    return session.scalar(select(func.count()).where(Character.project_id == project_id)) or 0


def _check_presets(ctx: AppContext, page_format: str | None, workflow: str | None) -> None:
    if page_format is not None and page_format not in ctx.presets.page_formats:
        raise FieldError("page_format", f"format de page inconnu : « {page_format} »")
    if workflow is not None and workflow not in ctx.presets.workflows:
        raise FieldError("workflow_preset", f"workflow inconnu : « {workflow} »")


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectOut]:
    counts = dict(session.execute(select(Character.project_id, func.count()).group_by(Character.project_id)).all())
    projects = session.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return [project_out(p, counts.get(p.id, 0)) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ProjectOut:
    defaults = ctx.presets.defaults
    page_format = body.page_format or (defaults.page_format if defaults else None)
    workflow = body.workflow_preset or (defaults.workflow if defaults else None)
    if page_format is None:
        raise FieldError("page_format", "aucun format de page par défaut : choisis-en un")
    if workflow is None:
        raise FieldError("workflow_preset", "aucun workflow par défaut : choisis-en un")
    _check_presets(ctx, page_format, workflow)
    project = Project(
        title=body.title,
        style=body.style,
        reading_direction=ReadingDirection(body.reading_direction),
        page_format=page_format,
        workflow_preset=workflow,
    )
    session.add(project)
    session.commit()
    return project_out(project, 0)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, session: Session = Depends(get_session)) -> ProjectOut:
    project = get_project_or_404(session, project_id)
    return project_out(project, _count_characters(session, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> ProjectOut:
    project = get_project_or_404(session, project_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("title", "page_format", "workflow_preset", "reading_direction", "style"):
        if key in changes and changes[key] is None:
            raise FieldError(key, "ne peut pas être vide")
    _check_presets(ctx, changes.get("page_format"), changes.get("workflow_preset"))
    if "reading_direction" in changes:
        changes["reading_direction"] = ReadingDirection(changes["reading_direction"])
    for key, value in changes.items():
        setattr(project, key, value)
    session.commit()
    return project_out(project, _count_characters(session, project_id))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    project = get_project_or_404(session, project_id)
    session.delete(project)
    session.commit()
    ctx.files.delete_tree(f"projects/{project_id}")
    return Response(status_code=204)
