"""CRUD des séries (table historique « projects », routes /projects)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents.profiles import ProfileInvalid
from ..pipeline.comfy_check import control_types
from ..pipeline.pages import change_reading_direction
from ..pipeline.style import StyleError, check_style, lora_triggers, series_style, style_names
from ..presets.schemas import AgentPreset
from ..store.models import Chapter, Character, Page, Project, ReadingDirection, SeriesStatus
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projets"])

# Polices de la série : réglages de série de l'agent lettreur (écran « L'équipe »), champ API → réglage.
FONT_SOURCES = {"dialogue_font": "fonts.yaml#styles.speech.font", "shout_font": "fonts.yaml#styles.shout.font"}


def project_out(
    ctx: AppContext, project: Project, character_count: int, chapter_count: int, laid_out: int = 0
) -> ProjectOut:
    presets = ctx.agents.presets_for(project.id)
    styles = presets.fonts.styles if presets.fonts else {}
    return ProjectOut(
        id=project.id,
        title=project.title,
        legacy_style=project.legacy_style or "",
        style_genre=project.style_genre,
        style_rendering=project.style_rendering,
        style_tone=project.style_tone,
        style_options=dict(project.style_options or {}),
        style_label=style_names(presets, project),
        style_prompt=series_style(presets, project),
        status=project.status.value,
        reading_direction=project.reading_direction.value,
        page_format=project.page_format,
        workflow_preset=project.workflow_preset,
        style_lora_name=project.style_lora_name,
        style_lora_weight=project.style_lora_weight,
        style_lora_trigger_words=list(lora_triggers(presets, project)),
        style_lora_in_catalog=presets.style_loras.get(project.style_lora_name) is not None,
        layout_style=project.layout_style,
        dialogue_font=styles["speech"].font if "speech" in styles else None,
        shout_font=styles["shout"].font if "shout" in styles else None,
        sketch_enabled=project.sketch_enabled,
        sketch_denoise=project.sketch_denoise,
        clean_mode=project.clean_mode or "img2img",
        clean_control=project.clean_control,
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


def _check_style(ctx: AppContext, genre: str | None, rendering: str | None, tone: str | None, options: dict) -> None:
    try:
        check_style(ctx.presets, genre, rendering, tone, options)
    except StyleError as exc:
        raise FieldError(exc.field, exc.message) from None


def _font_agent(ctx: AppContext) -> tuple[AgentPreset, dict[str, str]] | None:
    """Agent qui règle les polices (lettreur) et clé de ses réglages pour chaque champ de police."""
    for agent in ctx.agents.agents():
        keys = {f: s.key for f, src in FONT_SOURCES.items() for s in agent.settings if s.source == src}
        if len(keys) == len(FONT_SOURCES):
            return agent, keys
    return None


def _check_fonts(ctx: AppContext, fonts: dict[str, str | None]) -> None:
    """Avant toute écriture : polices connues de fonts.yaml et agent lettreur présent."""
    fonts = {k: v for k, v in fonts.items() if v}
    known = ctx.presets.fonts.fonts if ctx.presets.fonts else {}
    for key, font in fonts.items():
        if font not in known:
            raise FieldError(key, f"police inconnue : « {font} » (presets/fonts.yaml)")
    if fonts and _font_agent(ctx) is None:
        raise FieldError(next(iter(fonts)), "aucun agent ne règle les polices (presets/agents/lettreur.yaml)")


def _save_fonts(ctx: AppContext, session: Session, project: Project, fonts: dict[str, str | None]) -> None:
    """Polices choisies → réglages de série du lettreur (une valeur égale à l'héritée n'est pas stockée)."""
    fonts = {k: v for k, v in fonts.items() if v}
    found = _font_agent(ctx)
    if not fonts or found is None:
        return
    agent, keys = found
    try:
        ctx.agents.save(session, agent, project.id, {keys[k]: v for k, v in fonts.items()}, author="fiche série")
    except ProfileInvalid as exc:
        field = next((k for k, key in keys.items() if any(e.field == key for e in exc.errors)), next(iter(fonts)))
        raise FieldError(field, " ; ".join(e.message for e in exc.errors)) from None


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
    clean_control: str | None = None,
) -> None:
    if page_format is not None and page_format not in ctx.presets.page_formats:
        raise FieldError("page_format", f"format de page inconnu : « {page_format} »")
    if workflow is not None and workflow not in ctx.presets.workflows:
        raise FieldError("workflow_preset", f"workflow inconnu : « {workflow} »")
    if layout_style is not None and layout_style not in ctx.presets.layout_styles:
        raise FieldError("layout_style", f"style de mise en page inconnu : « {layout_style} »")
    if upscaler is not None and upscaler not in ctx.presets.upscalers:
        raise FieldError("upscaler", f"agrandisseur inconnu : « {upscaler} »")
    if clean_control is not None and clean_control not in control_types(ctx.presets):
        known = ", ".join(control_types(ctx.presets)) or "aucun"
        raise FieldError("clean_control", f"type de contrôle inconnu : « {clean_control} » (possibles : {known})")


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)) -> list[ProjectOut]:
    chars = dict(session.execute(select(Character.project_id, func.count()).group_by(Character.project_id)).all())
    chapters = dict(session.execute(select(Chapter.project_id, func.count()).group_by(Chapter.project_id)).all())
    projects = session.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return [project_out(ctx, p, chars.get(p.id, 0), chapters.get(p.id, 0)) for p in projects]


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
    _check_style(ctx, body.style_genre, body.style_rendering, body.style_tone, body.style_options)
    # Le genre pré-remplit la mise en page, le sens de lecture et les polices (modifiables).
    genre = ctx.presets.style_genres[body.style_genre]
    layout_style = body.layout_style or genre.layout_style
    _check_presets(ctx, page_format, workflow, layout_style, body.upscaler, body.clean_control)
    lora = ctx.presets.style_loras.get(body.style_lora_name)
    weight = body.style_lora_weight if body.style_lora_weight is not None else (lora.weight if lora else 0.8)
    project = Project(
        title=body.title,
        style_genre=body.style_genre,
        style_rendering=body.style_rendering,
        style_tone=body.style_tone,
        style_options=dict(body.style_options),
        status=SeriesStatus(body.status),
        reading_direction=ReadingDirection(body.reading_direction or genre.reading_direction),
        page_format=page_format,
        workflow_preset=workflow,
        style_lora_name=body.style_lora_name or None,
        style_lora_weight=weight,
        layout_style=layout_style,
        # Palier croquis : activé pour les nouvelles séries sauf avis contraire (defaults.yaml).
        sketch_enabled=body.sketch_enabled
        if body.sketch_enabled is not None
        else defaults is None or defaults.sketch_enabled,
        sketch_denoise=body.sketch_denoise,
        clean_mode=body.clean_mode,
        clean_control=body.clean_control,
        upscaler=body.upscaler,
    )
    fonts = {
        "dialogue_font": body.dialogue_font or genre.fonts.dialogue,
        "shout_font": body.shout_font or genre.fonts.shout,
    }
    _check_fonts(ctx, {"dialogue_font": body.dialogue_font, "shout_font": body.shout_font})
    session.add(project)
    session.commit()
    _save_fonts(ctx, session, project, fonts)
    return project_out(ctx, project, 0, 0)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ProjectOut:
    project = get_project_or_404(session, project_id)
    return project_out(ctx, project, *_counts(session, project_id))


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
        "style_genre",
        "style_rendering",
        "style_tone",
        "status",
        "style_lora_weight",
        "layout_style",
        "sketch_enabled",
        "clean_mode",
    ):
        if key in changes and changes[key] is None:
            raise FieldError(key, "ne peut pas être vide")
    _check_presets(
        ctx,
        changes.get("page_format"),
        changes.get("workflow_preset"),
        changes.get("layout_style"),
        changes.get("upscaler"),
        changes.get("clean_control"),
    )
    if "style_options" in changes:
        changes["style_options"] = dict(changes["style_options"] or {})
    if {"style_genre", "style_rendering", "style_tone", "style_options"} & set(changes):
        _check_style(
            ctx,
            changes.get("style_genre", project.style_genre),
            changes.get("style_rendering", project.style_rendering),
            changes.get("style_tone", project.style_tone),
            changes.get("style_options", project.style_options or {}),
        )
    fonts = {k: changes.pop(k) for k in FONT_SOURCES if k in changes}
    _check_fonts(ctx, fonts)
    direction = changes.pop("reading_direction", None)
    if "status" in changes:
        changes["status"] = SeriesStatus(changes["status"])
    if "style_lora_name" in changes:
        changes["style_lora_name"] = changes["style_lora_name"] or None
    for key, value in changes.items():
        setattr(project, key, value)
    if direction is not None:
        # Après les autres champs : un changement de format en même temps fait tout recalculer.
        change_reading_direction(ctx.agents.presets_for(project.id), project, ReadingDirection(direction))
    session.commit()
    _save_fonts(ctx, session, project, fonts)
    return project_out(ctx, project, *_counts(session, project_id))


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
