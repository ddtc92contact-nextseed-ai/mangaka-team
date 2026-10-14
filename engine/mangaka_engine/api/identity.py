"""Identité visuelle de la série (fiche série) : palette proposée par l'IA, logo du titre (voir pipeline/identity.py,
pipeline/logo.py).

- `GET /projects/{id}/identity` : palette retenue, dernières palettes proposées, logo de la série (dernière version)
  et ses versions, derniers concepts de logo (rendus en SVG), polices, effets et bornes des réglages ;
- `POST /projects/{id}/identity/palettes` : l'agent propose des palettes (`more` : « Proposer d'autres palettes ») ;
- `PUT /projects/{id}/identity/palette` : palette retenue (choisie, couleurs modifiées à la main) ;
- `POST /projects/{id}/identity/logos` : l'agent propose des concepts de logo (palette retenue obligatoire) ;
- `POST /projects/{id}/identity/logo/preview` : aperçu SVG d'un logo réglé à la main (contraste compris) ;
- `POST /projects/{id}/identity/logo` : enregistre un logo comme nouvelle version du logo de la série ;
- `GET /logos/{id}/file?format=svg|png` : téléchargement d'une version (PNG transparent haute définition).

Les appels au LLM sont synchrones (aucune transaction ouverte pendant l'appel) ; échec → 502 lisible, rien ne change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..pipeline.identity import (
    AGENT_ID,
    IdentityBrief,
    IdentityError,
    Palette,
    concept_contrast,
    palette_problems,
    propose_logos,
    propose_palettes,
)
from ..pipeline.logo import LogoError, LogoSpec, render_png, render_svg, spec_problems
from ..presets import PresetError, PresetRegistry
from ..store.models import Project, SeriesLogo
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .projects import get_project_or_404

router = APIRouter(tags=["identité visuelle"])


class ProposeIn(BaseModel):
    more: bool = False  # « Proposer d'autres » : l'agent voit les propositions actuelles, à ne pas répéter


class FontOut(BaseModel):
    id: str
    name: str


class LogoStyleOut(BaseModel):
    id: str
    name: str
    description: str
    slots: list[str]


class Bounds(BaseModel):
    min: float
    max: float


class LogoLimits(BaseModel):
    max_lines: int
    slant_max_deg: float
    letter_spacing: Bounds
    word_scale: Bounds
    outline_scale: Bounds
    min_contrast: float
    backgrounds: dict[str, str]


class RenderedLogoOut(BaseModel):
    spec: LogoSpec
    svg: str
    contrast: float | None
    contrast_ok: bool
    notes: list[str] = []


class LogoVersionOut(RenderedLogoOut):
    id: int
    version: int
    created_at: datetime
    svg_url: str
    png_url: str


class IdentityOut(BaseModel):
    palette: Palette | None
    palette_proposals: list[Palette]
    logo: LogoVersionOut | None
    logo_versions: list[LogoVersionOut]
    logo_proposals: list[RenderedLogoOut]
    roles: dict[str, str]
    required_roles: list[str]
    palette_colors: Bounds
    fonts: list[FontOut]
    styles: list[LogoStyleOut]
    limits: LogoLimits


class PreviewOut(BaseModel):
    svg: str
    contrast: float | None
    contrast_ok: bool
    problems: list[str]


def _presets(ctx: AppContext, project_id: int) -> PresetRegistry:
    presets = ctx.agents.presets_for(project_id)
    try:
        presets.require_identity()
        presets.require_fonts()
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return presets


def _rendered(presets: PresetRegistry, spec: LogoSpec, notes: list[str] | None = None) -> RenderedLogoOut:
    ratio = concept_contrast(presets, spec)
    minimum = presets.require_identity().logo.min_contrast
    return RenderedLogoOut(
        spec=spec,
        svg=render_svg(presets, spec),
        contrast=round(ratio, 2) if ratio is not None else None,
        contrast_ok=ratio is None or ratio >= minimum,
        notes=notes or [],
    )


def _version_out(presets: PresetRegistry, logo: SeriesLogo) -> LogoVersionOut | None:
    try:
        spec = LogoSpec.model_validate(logo.spec)
        base = _rendered(presets, spec)
    except (ValueError, LogoError):
        return None  # preset retiré depuis (police, effet) : la version reste en base, sans aperçu
    created = logo.created_at.replace(tzinfo=logo.created_at.tzinfo or UTC)
    return LogoVersionOut(
        **base.model_dump(),
        id=logo.id,
        version=logo.version,
        created_at=created,
        svg_url=f"/logos/{logo.id}/file?format=svg",
        png_url=f"/logos/{logo.id}/file?format=png",
    )


def _palettes(items: list[dict[str, Any]] | None) -> list[Palette]:
    out = []
    for item in items or []:
        try:
            out.append(Palette.model_validate(item))
        except ValueError:
            continue
    return out


def identity_out(presets: PresetRegistry, project: Project) -> IdentityOut:
    identity = presets.require_identity()
    fonts = presets.require_fonts().fonts
    logo = identity.logo
    versions = [v for v in (_version_out(presets, lg) for lg in reversed(project.logos)) if v is not None]
    proposals: list[RenderedLogoOut] = []
    for item in project.logo_proposals or []:
        try:
            spec = LogoSpec.model_validate(item.get("spec"))
            proposals.append(_rendered(presets, spec, list(item.get("notes") or [])))
        except (ValueError, LogoError):
            continue
    palette = _palettes([project.palette] if project.palette else [])
    return IdentityOut(
        palette=palette[0] if palette else None,
        palette_proposals=_palettes(project.palette_proposals),
        logo=versions[0] if versions else None,
        logo_versions=versions,
        logo_proposals=proposals,
        roles=identity.palette.roles,
        required_roles=identity.palette.required_roles,
        palette_colors=Bounds(min=identity.palette.colors.min, max=identity.palette.colors.max),
        fonts=[FontOut(id=f, name=fonts[f].name) for f in logo.fonts],
        styles=[
            LogoStyleOut(id=s.id, name=s.name, description=s.description, slots=s.slots())
            for s in presets.logo_styles.values()
        ],
        limits=LogoLimits(
            max_lines=logo.max_lines,
            slant_max_deg=logo.slant_max_deg,
            letter_spacing=Bounds(**logo.letter_spacing.model_dump()),
            word_scale=Bounds(**logo.word_scale.model_dump()),
            outline_scale=Bounds(**logo.outline_scale.model_dump()),
            min_contrast=logo.min_contrast,
            backgrounds=dict(logo.preview_backgrounds),
        ),
    )


def _brief(session: Session, ctx: AppContext, presets: PresetRegistry, project: Project) -> IdentityBrief:
    return IdentityBrief.build(
        session, presets, ctx.files, project, bible_max_tokens=ctx.knowledge.settings.bible_max_tokens
    )


def _llm(ctx: AppContext, project_id: int):  # type: ignore[no-untyped-def]
    llm, error = ctx.agents.llm_for(AGENT_ID, project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'non configuré'}")
    return llm


@router.get("/projects/{project_id}/identity", response_model=IdentityOut)
def get_identity(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> IdentityOut:
    project = get_project_or_404(session, project_id)
    return identity_out(_presets(ctx, project_id), project)


@router.post("/projects/{project_id}/identity/palettes", response_model=IdentityOut)
def propose_palettes_route(
    project_id: int, body: ProposeIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> IdentityOut:
    """« Proposer des palettes » : les palettes précédentes sont remplacées (la palette retenue ne change pas)."""
    project = get_project_or_404(session, project_id)
    presets = _presets(ctx, project_id)
    brief = _brief(session, ctx, presets, project)
    previous = [p.name for p in _palettes(project.palette_proposals)] if body.more else []
    session.commit()  # aucune transaction ouverte pendant l'appel au LLM
    try:
        run = propose_palettes(_llm(ctx, project_id), presets, brief, previous)
    except (IdentityError, PresetError) as exc:
        raise HTTPException(status_code=502, detail=f"L'IA n'a pas pu proposer de palettes : {exc}") from None
    project = get_project_or_404(session, project_id)
    project.palette_proposals = [p.model_dump(mode="json") for p in run.output]
    session.commit()
    return identity_out(presets, project)


@router.put("/projects/{project_id}/identity/palette", response_model=IdentityOut)
def save_palette(
    project_id: int, body: Palette, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> IdentityOut:
    """Palette retenue pour la série (une proposition, éventuellement retouchée à la main)."""
    project = get_project_or_404(session, project_id)
    presets = _presets(ctx, project_id)
    problems = palette_problems(body, presets.require_identity())
    if problems:
        raise FieldError("colors", " ; ".join(problems))
    project.palette = body.model_dump(mode="json")
    session.commit()
    return identity_out(presets, project)


@router.post("/projects/{project_id}/identity/logos", response_model=IdentityOut)
def propose_logos_route(
    project_id: int, body: ProposeIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> IdentityOut:
    """« Proposer des logos » : concepts typographiques aux couleurs de la palette retenue."""
    project = get_project_or_404(session, project_id)
    presets = _presets(ctx, project_id)
    if not project.palette:
        raise FieldError("palette", "Retiens d'abord une palette : les logos en tirent leurs couleurs")
    palette = Palette.model_validate(project.palette)
    brief = _brief(session, ctx, presets, project)
    previous = []
    if body.more:
        for item in project.logo_proposals or []:
            spec = item.get("spec") or {}
            previous.append(f"{spec.get('name') or '?'} : police {spec.get('font')}, effet {spec.get('style')}")
    session.commit()
    try:
        run = propose_logos(_llm(ctx, project_id), presets, brief, palette, previous)
    except (IdentityError, PresetError) as exc:
        raise HTTPException(status_code=502, detail=f"L'IA n'a pas pu proposer de logos : {exc}") from None
    project = get_project_or_404(session, project_id)
    project.logo_proposals = [{"spec": c.spec.model_dump(mode="json"), "notes": c.notes} for c in run.output]
    session.commit()
    return identity_out(presets, project)


def _checked(presets: PresetRegistry, spec: LogoSpec) -> None:
    problems = spec_problems(presets, spec)
    if problems:
        raise FieldError("spec", " ; ".join(problems))


@router.post("/projects/{project_id}/identity/logo/preview", response_model=PreviewOut)
def preview_logo(
    project_id: int, body: LogoSpec, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PreviewOut:
    get_project_or_404(session, project_id)
    presets = _presets(ctx, project_id)
    _checked(presets, body)
    out = _rendered(presets, body)
    problems = [] if out.contrast_ok else [f"contraste texte / contour faible ({out.contrast:g})"]
    return PreviewOut(svg=out.svg, contrast=out.contrast, contrast_ok=out.contrast_ok, problems=problems)


@router.post("/projects/{project_id}/identity/logo", response_model=IdentityOut, status_code=201)
def save_logo(
    project_id: int, body: LogoSpec, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> IdentityOut:
    """Nouvelle version du logo de la série (les précédentes restent dans l'historique)."""
    project = get_project_or_404(session, project_id)
    presets = _presets(ctx, project_id)
    _checked(presets, body)
    version = max((lg.version for lg in project.logos), default=0) + 1
    project.logos.append(SeriesLogo(version=version, spec=body.model_dump(mode="json")))
    session.commit()
    session.refresh(project)
    return identity_out(presets, project)


@router.get("/logos/{logo_id}/file")
def logo_file(
    logo_id: int,
    format: Literal["svg", "png"] = "svg",
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    logo = session.get(SeriesLogo, logo_id)
    if logo is None:
        raise HTTPException(status_code=404, detail="Logo introuvable")
    presets = _presets(ctx, logo.project_id)
    try:
        spec = LogoSpec.model_validate(logo.spec)
        data: bytes = render_svg(presets, spec).encode("utf-8") if format == "svg" else render_png(presets, spec)
    except (ValueError, LogoError) as exc:
        raise HTTPException(status_code=409, detail=f"Logo impossible à rendre : {exc}") from None
    stem = f"logo-{logo.project.slug or logo.project_id}-v{logo.version}"
    name = f"{stem}.{format}"
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return Response(
        content=data,
        media_type="image/svg+xml" if format == "svg" else "image/png",
        headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"},
    )
