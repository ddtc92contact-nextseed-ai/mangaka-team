"""Composition de la couverture d'un tome (écran « Couverture ») : 4e de couverture, 1re composée, dos, export.

Voir pipeline/cover_composition.py (mise en page, rendu PNG + SVG) et pipeline/back_cover.py (résumé de 4e).

- `GET /volumes/{id}/composition` : état (résumé, accroche, gabarit, petite illustration et ses sources, logo et
  son placement, auteur, dos, ordre à plat, avertissements et problèmes bloquants) ;
- `PATCH /volumes/{id}/composition` : résumé et accroche édités, gabarit, auteur (tome ou série), placement du logo
  (borné à la marge de sécurité), petite illustration (case retenue du tome ou version générée), prompt de 4e ;
- `POST /volumes/{id}/back/summary` : l'IA écrit le résumé et l'accroche (`rewrite` : « Réécrire ») ;
- `POST /volumes/{id}/back/generate` : petite illustration de 4e par le flux de couverture (file ComfyUI) ;
- `GET /volumes/{id}/composition/{front|back|spine|flat}.png` : aperçu (rendu de l'export, réduit) ;
- `POST /volumes/{id}/cover/export` : job d'export (ZIP : 1re, 4e, à plat ; PNG + SVG) ;
- `GET /cover-exports/{job_id}/file` : téléchargement du ZIP.

Les appels au LLM sont synchrones (aucune transaction ouverte pendant l'appel) ; échec → 502 lisible.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.back_cover import AGENT_ID as SUMMARY_AGENT
from ..pipeline.back_cover import BackCoverError, clean_summary, clean_tagline, sign_count, summary_brief, write_summary
from ..pipeline.cover_charter import charter_format, series_charter
from ..pipeline.cover_composition import (
    STEP,
    Composition,
    compose,
    composition_inputs,
    composition_json,
    export_job,
    logo_aspect,
    logo_rect,
    preview_png,
    safe_rect,
    sheet_for,
    tome_panel_images,
    zone_rect,
)
from ..pipeline.covers import active_cover_jobs, enqueue_cover
from ..pipeline.generation import GenerationError
from ..presets import CoverFormat, PresetError, PresetRegistry
from ..store.files import versioned_url
from ..store.models import Job, JobStatus, Volume, VolumeCover
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import JobOut
from .volumes import CoverFormatOut, CoverIdentityOut, cover_url, format_out, get_volume_or_404, identity_out

router = APIRouter(tags=["tomes"])

ACTIVE = (JobStatus.pending, JobStatus.running)


# --- schémas -------------------------------------------------------------------------------------------------
class RelRect(BaseModel):
    x: float
    y: float
    width: float
    height: float


class LogoPlacement(BaseModel):
    cx: float = Field(ge=0, le=1)  # centre, fraction du format rogné
    cy: float = Field(ge=0, le=1)
    scale: float = Field(gt=0, le=2)


class LogoOut(BaseModel):
    present: bool
    placement: LogoPlacement | None
    # En fraction de l'image complète (fond perdu compris), comme les zones de l'écran « Couverture ».
    rect: RelRect | None
    zone: RelRect | None
    safe: RelRect
    scale_min: float
    scale_max: float
    default_scale: float


class BackLayoutOut(BaseModel):
    id: str
    name: str
    description: str


class BackImageIn(BaseModel):
    source: Literal["panel", "generated"]
    id: int


class PanelChoiceOut(BaseModel):
    image_id: int
    url: str
    chapter_number: int
    page_number: int
    panel_number: int


class BackVersionOut(BaseModel):
    id: int
    url: str
    width: int
    height: int
    seed: int | None
    prompt: str
    selected: bool
    # Contrôle d'identité des personnages (charte des couvertures) : avertissement, jamais de blocage.
    identity: CoverIdentityOut | None = None
    created_at: datetime


class NoticeOut(BaseModel):
    code: str
    message: str
    part: str


class ExportOut(BaseModel):
    job_id: int
    filename: str
    url: str
    finished_at: datetime | None


class CompositionOut(BaseModel):
    volume_id: int
    project_id: int
    number: int
    series_title: str
    direction: str
    format: CoverFormatOut | None
    problem: str | None  # composition indisponible (presets)
    revision: str  # change dès que la composition change (aperçus)
    author: str
    series_author: str
    summary: str
    tagline: str
    summary_source: str | None
    summary_notes: str
    summary_chars: int
    summary_min: int
    summary_max: int
    tagline_max: int
    summary_size_pt: float | None
    back_layout: str | None
    back_layouts: list[BackLayoutOut]
    back_image: BackImageIn | None
    back_image_url: str | None
    back_prompt: str
    back_aspect: tuple[int, int]
    back_versions: list[BackVersionOut]
    back_jobs: list[JobOut]
    panel_choices: list[PanelChoiceOut]
    logo: LogoOut | None
    has_front_image: bool
    palette_name: str | None
    spine_mm: float | None
    pages: int
    order: list[str]
    warnings: list[NoticeOut]
    problems: list[NoticeOut]
    export_jobs: list[JobOut]
    last_export: ExportOut | None


class CompositionPatch(BaseModel):
    summary: str | None = Field(default=None, max_length=8000)
    tagline: str | None = Field(default=None, max_length=300)
    back_layout: str | None = None
    author: str | None = Field(default=None, max_length=200)
    series_author: str | None = Field(default=None, max_length=200)
    logo: LogoPlacement | None = None
    reset_logo: bool = False
    back_image: BackImageIn | None = None
    clear_back_image: bool = False
    back_prompt: str | None = Field(default=None, max_length=8000)


class SummaryIn(BaseModel):
    rewrite: bool = False  # « Réécrire » : l'agent voit le résumé actuel, à ne pas répéter


class BackGenerateIn(BaseModel):
    prompt: str | None = Field(default=None, max_length=8000)
    seed: int | None = Field(default=None, ge=0)


class ExportIn(BaseModel):
    bleed: bool = True
    crop_marks: bool = False


# --- conversions -----------------------------------------------------------------------------------------------
def _presets(ctx: AppContext, project_id: int) -> PresetRegistry:
    return ctx.agents.presets_for(project_id)


def _rel(fmt: CoverFormat, x: float, y: float, w: float, h: float) -> RelRect:
    """Rectangle en px du format rogné → fraction de l'image complète (fond perdu compris)."""
    fw, fh = fmt.full_px
    b = fmt.bleed_px
    return RelRect(x=(x + b) / fw, y=(y + b) / fh, width=w / fw, height=h / fh)


def _logo_out(presets: PresetRegistry, comp: Composition) -> LogoOut:
    inp = comp.inputs
    fmt, front = inp.fmt, inp.settings.front
    safe = safe_rect(fmt)
    zone = zone_rect(fmt, "logo")
    rect = None
    placement = None
    if inp.logo is not None:
        r = logo_rect(fmt, inp.settings, logo_aspect(presets, inp.logo), inp.logo_placement)
        rect = _rel(fmt, r.x, r.y, r.w, r.h)
        tw, th = fmt.trim_px
        scale = (inp.logo_placement or {}).get("scale", front.default_logo_scale)
        placement = LogoPlacement(cx=r.cx / tw, cy=r.cy / th, scale=float(scale))
    return LogoOut(
        present=inp.logo is not None,
        placement=placement,
        rect=rect,
        zone=_rel(fmt, zone.x, zone.y, zone.w, zone.h) if zone else None,
        safe=_rel(fmt, safe.x, safe.y, safe.w, safe.h),
        scale_min=front.logo_scale.min,
        scale_max=front.logo_scale.max,
        default_scale=front.default_logo_scale,
    )


def _revision(volume: Volume, comp: Composition | None) -> str:
    series = volume.project
    data = {
        "v": [volume.back_summary, volume.back_tagline, volume.back_layout, volume.author, volume.cover_layout],
        "img": [volume.selected_cover_id, volume.back_image, volume.cover_format, volume.number],
        "s": [series.title, series.author, series.palette, max((lg.id for lg in series.logos), default=0)],
        "p": [comp.inputs.pages, comp.inputs.direction] if comp else None,
    }
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _export_jobs(session: Session, volume_id: int) -> tuple[list[Job], Job | None]:
    rows = list(session.scalars(select(Job).where(Job.step == STEP).order_by(Job.id.desc()).limit(200)))
    mine = [j for j in rows if (j.params or {}).get("volume_id") == volume_id]
    active = [j for j in mine if j.status in ACTIVE]
    done = next((j for j in mine if j.status == JobStatus.succeeded and (j.params or {}).get("file")), None)
    return active, done


def identity_notices(volume: Volume, choice: dict | None) -> list[NoticeOut]:
    """Avertissements du contrôle d'identité de la 1re retenue et de l'illustration de 4e générée retenue."""
    out: list[NoticeOut] = []
    back_id = choice.get("id") if choice and choice.get("source") == "generated" else None
    for cover in volume.covers:
        part = "front" if cover.kind == "front" and cover.id == volume.selected_cover_id else None
        if cover.kind == "back" and cover.id == back_id:
            part = "back"
        identity = identity_out(cover) if part else None
        if identity is None:
            continue
        where = "1re de couverture" if part == "front" else "illustration de 4e"
        for warning in identity.warnings:
            out.append(NoticeOut(code="identity", message=f"{where} : {warning}", part=part or "front"))
    return out


def composition_out(session: Session, ctx: AppContext, volume: Volume) -> CompositionOut:
    presets = _presets(ctx, volume.project_id)
    series = volume.project
    base_fmt = presets.cover_formats.get(volume.cover_format)
    fmt = charter_format(base_fmt, series_charter(presets, series)) if base_fmt else None
    problem = None
    comp: Composition | None = None
    try:
        settings = presets.require_composition()
        if fmt is None:
            raise PresetError(f"Format de couverture inconnu : « {volume.cover_format} »")
        comp = compose(presets, composition_inputs(session, presets, ctx.files, volume))
    except PresetError as exc:
        problem = str(exc)
        settings = presets.composition
    summary = clean_summary(volume.back_summary or "")
    back_versions = sorted((c for c in volume.covers if c.kind == "back"), key=lambda c: -c.id)
    choice = volume.back_image if isinstance(volume.back_image, dict) and volume.back_image.get("source") else None
    choices = tome_panel_images(volume)
    back_url = None
    if choice is not None:
        if choice["source"] == "generated":
            cover = next((c for c in back_versions if c.id == choice.get("id")), None)
            back_url = cover_url(cover) if cover else None
        else:
            img = next((i for *_, i in choices if i.id == choice.get("id")), None)
            back_url = versioned_url(f"/panel-images/{img.id}/file", img.path) if img else None
    active, done = _export_jobs(session, volume.id)
    info = composition_json(comp) if comp else {}
    return CompositionOut(
        volume_id=volume.id,
        project_id=volume.project_id,
        number=volume.number,
        series_title=series.title,
        direction=str(series.reading_direction.value),
        format=format_out(fmt, presets) if fmt else None,
        problem=problem,
        revision=_revision(volume, comp),
        author=volume.author,
        series_author=series.author,
        summary=summary,
        tagline=volume.back_tagline,
        summary_source=volume.back_summary_source,
        summary_notes=volume.back_summary_notes,
        summary_chars=sign_count(summary),
        summary_min=settings.summary.min_chars if settings else 0,
        summary_max=settings.summary.max_chars if settings else 0,
        tagline_max=settings.summary.tagline_max_chars if settings else 0,
        summary_size_pt=info.get("summary_size_pt"),
        back_layout=comp.inputs.layout.id if comp else volume.back_layout,
        back_layouts=[
            BackLayoutOut(id=b.id, name=b.name, description=b.description) for b in presets.back_layouts.values()
        ],
        back_image=BackImageIn(source=choice["source"], id=int(choice["id"])) if choice else None,
        back_image_url=back_url,
        back_prompt=volume.back_prompt,
        back_aspect=settings.back_illustration.aspect if settings else (4, 3),
        back_versions=[
            BackVersionOut(
                id=c.id,
                url=cover_url(c),
                width=c.width,
                height=c.height,
                seed=c.seed,
                prompt=str((c.params or {}).get("prompt") or ""),
                selected=bool(choice and choice["source"] == "generated" and choice.get("id") == c.id),
                identity=identity_out(c),
                created_at=c.created_at,
            )
            for c in back_versions
        ],
        back_jobs=[job_out(j) for j in active_cover_jobs(session, volume.id, "back")],
        panel_choices=[
            PanelChoiceOut(
                image_id=img.id,
                url=versioned_url(f"/panel-images/{img.id}/file", img.path),
                chapter_number=ch.number,
                page_number=page.number,
                panel_number=panel.index + 1,
            )
            for ch, page, panel, img in choices
        ],
        logo=_logo_out(presets, comp) if comp else None,
        has_front_image=bool(comp and comp.inputs.front_image is not None),
        palette_name=comp.inputs.palette_name if comp else None,
        spine_mm=info.get("spine_mm"),
        pages=info.get("pages", 0),
        order=info.get("order", []),
        warnings=[NoticeOut(**n) for n in info.get("warnings", [])] + identity_notices(volume, choice),
        problems=[NoticeOut(**n) for n in info.get("problems", [])],
        export_jobs=[job_out(j) for j in active],
        last_export=ExportOut(
            job_id=done.id,
            filename=str((done.params or {}).get("filename") or "couverture.zip"),
            url=f"/cover-exports/{done.id}/file",
            finished_at=done.finished_at,
        )
        if done
        else None,
    )


def _composition(session: Session, ctx: AppContext, volume: Volume) -> Composition:
    presets = _presets(ctx, volume.project_id)
    try:
        return compose(presets, composition_inputs(session, presets, ctx.files, volume))
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


# --- routes ------------------------------------------------------------------------------------------------------
@router.get("/volumes/{volume_id}/composition", response_model=CompositionOut)
def get_composition(
    volume_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CompositionOut:
    return composition_out(session, ctx, get_volume_or_404(session, volume_id))


@router.patch("/volumes/{volume_id}/composition", response_model=CompositionOut)
def update_composition(
    volume_id: int, body: CompositionPatch, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CompositionOut:
    volume = get_volume_or_404(session, volume_id)
    presets = _presets(ctx, volume.project_id)
    if body.summary is not None:
        text = clean_summary(body.summary)
        if text != clean_summary(volume.back_summary or ""):
            volume.back_summary = text
            volume.back_summary_source = "manual" if text else None
    if body.tagline is not None:
        text = clean_tagline(body.tagline)
        if text != volume.back_tagline:
            volume.back_tagline = text
            if volume.back_summary_source == "ai":
                volume.back_summary_source = "manual"
    if body.back_layout is not None:
        if body.back_layout not in presets.back_layouts:
            known = ", ".join(presets.back_layouts) or "aucun"
            raise FieldError("back_layout", f"gabarit de 4e inconnu : « {body.back_layout} » (gabarits : {known})")
        volume.back_layout = body.back_layout
    if body.author is not None:
        volume.author = " ".join(body.author.split())
    if body.series_author is not None:
        volume.project.author = " ".join(body.series_author.split())
    if body.back_prompt is not None:
        volume.back_prompt = body.back_prompt.strip()
    if body.reset_logo:
        volume.cover_layout = {k: v for k, v in (volume.cover_layout or {}).items() if k != "logo"}
    elif body.logo is not None:
        placement = body.logo.model_dump()
        try:
            settings = presets.require_composition()
            fmt = charter_format(presets.cover_format(volume.cover_format), series_charter(presets, volume.project))
            comp_inputs = composition_inputs(session, presets, ctx.files, volume)
        except PresetError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        bounds = settings.front.logo_scale
        placement["scale"] = min(bounds.max, max(bounds.min, placement["scale"]))
        if comp_inputs.logo is not None:
            # Centre ramené dans la marge de sécurité (le logo ne la quitte jamais).
            r = logo_rect(fmt, settings, logo_aspect(presets, comp_inputs.logo), placement)
            tw, th = fmt.trim_px
            placement.update(cx=round(r.cx / tw, 5), cy=round(r.cy / th, 5))
        volume.cover_layout = {**(volume.cover_layout or {}), "logo": placement}
    if body.clear_back_image:
        volume.back_image = None
    elif body.back_image is not None:
        _set_back_image(session, volume, body.back_image)
    session.commit()
    session.refresh(volume)
    return composition_out(session, ctx, volume)


def _set_back_image(session: Session, volume: Volume, choice: BackImageIn) -> None:
    if choice.source == "panel":
        if choice.id not in {img.id for *_, img in tome_panel_images(volume)}:
            raise FieldError("back_image", "cette case n'est pas une version retenue d'un chapitre du tome")
    else:
        cover = session.get(VolumeCover, choice.id)
        if cover is None or cover.volume_id != volume.id or cover.kind != "back":
            raise FieldError("back_image", "illustration de 4e introuvable pour ce tome")
    volume.back_image = {"source": choice.source, "id": choice.id}


@router.post("/volumes/{volume_id}/back/summary", response_model=CompositionOut)
def write_back_summary(
    volume_id: int, body: SummaryIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CompositionOut:
    """L'IA écrit le résumé de 4e (600 à 900 signes, sans révéler la fin) et l'accroche ; éditables ensuite."""
    volume = get_volume_or_404(session, volume_id)
    presets = _presets(ctx, volume.project_id)
    llm, error = ctx.agents.llm_for(SUMMARY_AGENT, volume.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'non configuré'}")
    try:
        brief = summary_brief(
            session,
            presets,
            volume,
            bible_max_tokens=ctx.knowledge.settings.bible_max_tokens,
            previous=volume.back_summary if body.rewrite else "",
        )
        prompt = presets.prompt(presets.require_composition().summary.prompt)
    except (PresetError, BackCoverError) as exc:
        raise HTTPException(status_code=409, detail=_capitalize(str(exc))) from None
    session.commit()  # aucune transaction ouverte pendant l'appel au LLM
    try:
        run = write_summary(llm, prompt, brief)
    except BackCoverError as exc:
        raise HTTPException(status_code=502, detail=f"L'IA n'a pas pu écrire le résumé : {exc}") from None
    volume = get_volume_or_404(session, volume_id)
    volume.back_summary = run.output.summary
    volume.back_tagline = run.output.tagline
    volume.back_summary_source = "ai"
    volume.back_summary_notes = run.output.notes
    session.commit()
    session.refresh(volume)
    return composition_out(session, ctx, volume)


@router.post("/volumes/{volume_id}/back/generate", response_model=JobOut, status_code=202)
def generate_back_illustration(
    volume_id: int, body: BackGenerateIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> JobOut:
    """Petite illustration de 4e par le flux de couverture (ratio et taille de la 4e) ; nouvelle version à chaque
    appel, retenue d'office si le tome n'a pas encore d'illustration de 4e."""
    if ctx.providers.comfyui is None:
        detail = ctx.providers.errors.get("comfyui", "client non configuré")
        raise HTTPException(status_code=503, detail=f"ComfyUI indisponible : {detail}")
    volume = get_volume_or_404(session, volume_id)
    presets = _presets(ctx, volume.project_id)
    if body.prompt is not None:
        volume.back_prompt = body.prompt.strip()
    try:
        job = enqueue_cover(session, presets, volume, seed=body.seed, kind="back")
    except (PresetError, GenerationError) as exc:
        session.commit()  # prompt édité gardé
        raise HTTPException(status_code=409, detail=_capitalize(str(exc))) from None
    session.commit()
    ctx.generation.notify()
    return job_out(job)


@router.get("/volumes/{volume_id}/composition/{which}.png")
def composition_preview(
    volume_id: int,
    which: Literal["front", "back", "spine", "flat"],
    width: int = Query(default=640, ge=64, le=4000),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    """Aperçu PNG : le rendu de l'export (fond perdu compris), réduit à `width` px de large."""
    volume = get_volume_or_404(session, volume_id)
    comp = _composition(session, ctx, volume)
    presets = _presets(ctx, volume.project_id)
    sheet = sheet_for(comp, which, presets, bleed=True, crop_marks=False)
    data = preview_png(sheet, presets, width)
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/volumes/{volume_id}/cover/export", response_model=JobOut, status_code=202)
def export_cover(
    volume_id: int,
    body: ExportIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> JobOut:
    """Lance l'export de la couverture (1re, 4e, à plat ; PNG au DPI du format + SVG) ; progression via
    GET /jobs/{id}/events. Refusé tant qu'un problème bloquant reste (résumé trop long, vide…)."""
    body = body or ExportIn()
    volume = get_volume_or_404(session, volume_id)
    comp = _composition(session, ctx, volume)
    if comp.problems:
        raise FieldError("export", " ; ".join(n.message for n in comp.problems))
    active, _ = _export_jobs(session, volume.id)
    if active:
        raise HTTPException(status_code=409, detail="Un export de cette couverture est déjà en cours")
    job = Job(
        project_id=volume.project_id,
        step=STEP,
        message="En attente…",
        params={
            "volume_id": volume.id,
            "volume_number": volume.number,
            "bleed": body.bleed,
            "crop_marks": body.crop_marks,
        },
    )
    session.add(job)
    session.commit()
    presets = _presets(ctx, volume.project_id)
    ctx.jobs.submit(
        job.id, export_job(ctx.db, presets, ctx.files, volume.id, job.id, bleed=body.bleed, crop_marks=body.crop_marks)
    )
    return job_out(job)


@router.get("/cover-exports/{job_id}/file")
def download_cover_export(
    job_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    job = session.get(Job, job_id)
    if job is None or job.step != STEP:
        raise HTTPException(status_code=404, detail="Export introuvable")
    rel = (job.params or {}).get("file")
    if job.status != JobStatus.succeeded or not rel:
        raise HTTPException(status_code=409, detail="Export pas encore terminé")
    path = ctx.files.absolute(rel)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier d'export manquant dans data/")
    return FileResponse(path, media_type="application/zip", filename=(job.params or {}).get("filename") or path.name)


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]
