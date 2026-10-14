"""Tomes d'une série et couverture d'un tome (écran « Couverture »).

- `GET /presets/cover-formats` : formats de couverture (mm, px, fond perdu, zones réservées) ;
- `GET|POST /projects/{id}/volumes` : tomes de la série (numéro unique, format 13 × 18 par défaut) ;
- `GET|PATCH|DELETE /volumes/{id}` : titre, numéro, format, chapitres inclus (dans l'ordre, un chapitre dans un
  seul tome), personnages, intention et prompt de la couverture ;
- `GET /volumes/{id}/cover` : écran « Couverture » (format et zones, personnages, versions, jobs en cours) ;
- `POST /volumes/{id}/cover/prompt` : prompt rédigé par l'IA (bible, personnages, intention), éditable ensuite ;
- `POST /volumes/{id}/cover/generate` : met la génération en file (file ComfyUI, une à la fois) ;
- `POST /volume-covers/{id}/select` · `DELETE /volume-covers/{id}` · `GET /volume-covers/{id}/file`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..pipeline.covers import (
    active_cover_jobs,
    clear_zone_text,
    cover_brief,
    cover_style,
    enqueue_cover,
    generation_size,
    resolve_cover_upscaler,
    write_cover_prompt,
)
from ..pipeline.generation import GenerationError
from ..pipeline.prompt_writer import AGENT_ID as WRITER_AGENT
from ..presets import CoverFormat, PresetError, PresetRegistry
from ..store.files import cache_headers, versioned_url
from ..store.models import Chapter, Character, Volume, VolumeChapter, VolumeCover
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .projects import get_project_or_404
from .schemas import JobOut

router = APIRouter(tags=["tomes"])


# --- schémas ---------------------------------------------------------------------------------
class ZoneOut(BaseModel):
    id: str
    label: str
    clear: bool
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    # Dans l'image complète (fond perdu compris), en px et en fraction (aperçu en surimpression).
    px: dict[str, int]
    rel: dict[str, float]


class CoverFormatOut(BaseModel):
    id: str
    name: str
    default: bool
    page_format: str | None
    width_mm: float
    height_mm: float
    dpi: int
    bleed_mm: float
    safety_mm: float
    full_width_mm: float
    full_height_mm: float
    trim_width_px: int
    trim_height_px: int
    full_width_px: int
    full_height_px: int
    bleed_px: int
    zones: list[ZoneOut]
    # Taille générée par le flux de couverture avant l'agrandissement (None : cover.yaml absent).
    generation_width: int | None = None
    generation_height: int | None = None


class VolumeChapterOut(BaseModel):
    id: int
    number: int
    title: str
    status: str


class VolumeOut(BaseModel):
    id: int
    project_id: int
    number: int
    title: str
    cover_format: str
    cover_format_name: str | None
    chapters: list[VolumeChapterOut]
    cover_character_ids: list[int]
    cover_intent: str
    cover_prompt: str
    cover_prompt_source: str | None
    cover_prompt_notes: str
    selected_cover_id: int | None
    selected_cover_url: str | None
    cover_count: int
    created_at: datetime
    updated_at: datetime


class VolumeIn(BaseModel):
    number: int | None = Field(default=None, ge=1, le=9999)
    title: str = Field(default="", max_length=200)
    cover_format: str | None = None
    chapter_ids: list[int] = Field(default_factory=list)


class VolumePatch(BaseModel):
    number: int | None = Field(default=None, ge=1, le=9999)
    title: str | None = Field(default=None, max_length=200)
    cover_format: str | None = None
    chapter_ids: list[int] | None = None
    cover_character_ids: list[int] | None = None
    cover_intent: str | None = Field(default=None, max_length=2000)
    cover_prompt: str | None = Field(default=None, max_length=8000)


class CoverPromptIn(BaseModel):
    intent: str | None = Field(default=None, max_length=2000)
    character_ids: list[int] | None = None


class CoverGenerateIn(BaseModel):
    # Prompt édité à envoyer (enregistré sur le tome) ; absent = celui du tome.
    prompt: str | None = Field(default=None, max_length=8000)
    seed: int | None = Field(default=None, ge=0)


class CoverCharacterOut(BaseModel):
    id: int
    name: str
    has_reference: bool
    image_url: str | None


class CoverVersionOut(BaseModel):
    id: int
    url: str
    width: int
    height: int
    seed: int | None
    selected: bool
    cover_format: str
    prompt: str
    preset_name: str | None
    upscaler_name: str | None
    generated_width: int | None
    generated_height: int | None
    created_at: datetime


class CoverStudioOut(BaseModel):
    volume: VolumeOut
    format: CoverFormatOut | None
    formats: list[CoverFormatOut]
    characters: list[CoverCharacterOut]
    max_characters: int
    reference_slots: int
    versions: list[CoverVersionOut]
    active_jobs: list[JobOut]
    # Couverture indisponible (cover.yaml absent ou invalide, format inconnu).
    problem: str | None
    monochrome_series: bool
    style: str
    clear_zone: str | None
    workflow: str | None
    workflow_name: str | None
    upscaler_name: str | None


# --- conversions ------------------------------------------------------------------------------
def _presets(ctx: AppContext, project_id: int) -> PresetRegistry:
    return ctx.agents.presets_for(project_id)


def format_out(fmt: CoverFormat, presets: PresetRegistry) -> CoverFormatOut:
    full_w, full_h = fmt.full_px
    full_wmm, full_hmm = fmt.full_mm
    size = generation_size(fmt, presets.cover.long_side, presets.cover.multiple) if presets.cover is not None else None
    zones = []
    for z in fmt.zones:
        zones.append(
            ZoneOut(
                id=z.id,
                label=z.label,
                clear=z.clear,
                x_mm=z.x_mm,
                y_mm=z.y_mm,
                width_mm=z.width_mm,
                height_mm=z.height_mm,
                px=fmt.zone_px(z),
                rel={
                    "x": (fmt.bleed_mm + z.x_mm) / full_wmm,
                    "y": (fmt.bleed_mm + z.y_mm) / full_hmm,
                    "width": z.width_mm / full_wmm,
                    "height": z.height_mm / full_hmm,
                },
            )
        )
    return CoverFormatOut(
        id=fmt.id,
        name=fmt.name,
        default=fmt.default,
        page_format=fmt.page_format,
        width_mm=fmt.width_mm,
        height_mm=fmt.height_mm,
        dpi=fmt.dpi,
        bleed_mm=fmt.bleed_mm,
        safety_mm=fmt.safety_mm,
        full_width_mm=full_wmm,
        full_height_mm=full_hmm,
        trim_width_px=fmt.trim_px[0],
        trim_height_px=fmt.trim_px[1],
        full_width_px=full_w,
        full_height_px=full_h,
        bleed_px=fmt.bleed_px,
        zones=zones,
        generation_width=size[0] if size else None,
        generation_height=size[1] if size else None,
    )


def cover_url(cover: VolumeCover) -> str:
    return versioned_url(f"/volume-covers/{cover.id}/file", cover.path)


def volume_out(volume: Volume, presets: PresetRegistry) -> VolumeOut:
    fmt = presets.cover_formats.get(volume.cover_format)
    selected = next((c for c in volume.covers if c.id == volume.selected_cover_id and c.kind == "front"), None)
    return VolumeOut(
        id=volume.id,
        project_id=volume.project_id,
        number=volume.number,
        title=volume.title,
        cover_format=volume.cover_format,
        cover_format_name=fmt.name if fmt else None,
        chapters=[
            VolumeChapterOut(
                id=link.chapter.id, number=link.chapter.number, title=link.chapter.title, status=link.chapter.status
            )
            for link in volume.chapter_links
        ],
        cover_character_ids=[int(i) for i in volume.cover_character_ids or []],
        cover_intent=volume.cover_intent,
        cover_prompt=volume.cover_prompt,
        cover_prompt_source=volume.cover_prompt_source,
        cover_prompt_notes=volume.cover_prompt_notes,
        selected_cover_id=selected.id if selected else None,
        selected_cover_url=cover_url(selected) if selected else None,
        cover_count=sum(1 for c in volume.covers if c.kind == "front"),
        created_at=volume.created_at,
        updated_at=volume.updated_at,
    )


def version_out(cover: VolumeCover, selected_id: int | None) -> CoverVersionOut:
    params: dict[str, Any] = cover.params or {}
    return CoverVersionOut(
        id=cover.id,
        url=cover_url(cover),
        width=cover.width,
        height=cover.height,
        seed=cover.seed,
        selected=cover.id == selected_id,
        cover_format=cover.cover_format,
        prompt=str(params.get("prompt") or ""),
        preset_name=params.get("preset_name"),
        upscaler_name=params.get("upscaler_name"),
        generated_width=params.get("generated_width"),
        generated_height=params.get("generated_height"),
        created_at=cover.created_at,
    )


def studio_out(session: Session, presets: PresetRegistry, volume: Volume) -> CoverStudioOut:
    series = volume.project
    fmt = presets.cover_formats.get(volume.cover_format)
    cover = presets.cover
    problem = None
    if cover is None:
        problem = "Couverture indisponible : presets/cover.yaml absent ou invalide (voir Réglages → presets)."
    elif fmt is None:
        problem = f"Format de couverture inconnu : « {volume.cover_format} ». Choisis un autre format."
    loaded = presets.workflows.get(cover.workflow) if cover else None
    upscaler = resolve_cover_upscaler(presets, cover, series) if cover else None
    style = cover_style(presets, series, cover) if cover else None
    chars = session.scalars(select(Character).where(Character.project_id == series.id).order_by(Character.name))
    return CoverStudioOut(
        volume=volume_out(volume, presets),
        format=format_out(fmt, presets) if fmt else None,
        formats=[format_out(f, presets) for f in presets.cover_formats.values()],
        characters=[
            CoverCharacterOut(
                id=c.id,
                name=c.name,
                has_reference=bool(c.reference_images),
                image_url=versioned_url(
                    f"/characters/{c.id}/images/{c.reference_images[0].id}/file", c.reference_images[0].path
                )
                if c.reference_images
                else None,
            )
            for c in chars
        ],
        max_characters=cover.max_characters if cover else 0,
        reference_slots=len(loaded.preset.reference_images) if loaded else 0,
        versions=[
            version_out(c, volume.selected_cover_id)
            for c in sorted(volume.covers, key=lambda c: -c.id)
            if c.kind == "front"
        ],
        active_jobs=[job_out(j) for j in active_cover_jobs(session, volume.id)],
        problem=problem,
        monochrome_series=style.monochrome_series if style else False,
        style=style.style if style else "",
        clear_zone=clear_zone_text(fmt) if fmt else None,
        workflow=loaded.preset.id if loaded else None,
        workflow_name=loaded.preset.name if loaded else None,
        upscaler_name=upscaler.preset.name if upscaler else None,
    )


# --- règles ----------------------------------------------------------------------------------
def get_volume_or_404(session: Session, volume_id: int) -> Volume:
    volume = session.get(Volume, volume_id)
    if volume is None:
        raise HTTPException(status_code=404, detail="Tome introuvable")
    return volume


def _check_number(session: Session, project_id: int, number: int, volume_id: int | None = None) -> None:
    q = select(Volume.id).where(Volume.project_id == project_id, Volume.number == number)
    if volume_id is not None:
        q = q.where(Volume.id != volume_id)
    if session.scalar(q) is not None:
        raise FieldError("number", f"le tome {number} existe déjà dans cette série")


def _check_format(presets: PresetRegistry, format_id: str) -> None:
    if format_id not in presets.cover_formats:
        known = ", ".join(presets.cover_formats) or "aucun"
        raise FieldError("cover_format", f"format de couverture inconnu : « {format_id} » (formats : {known})")


def set_chapters(session: Session, volume: Volume, chapter_ids: list[int]) -> None:
    """Chapitres du tome, dans l'ordre donné : de la même série, chacun dans un seul tome."""
    if len(set(chapter_ids)) != len(chapter_ids):
        raise FieldError("chapter_ids", "un chapitre est cité deux fois")
    chapters = {c.id: c for c in session.scalars(select(Chapter).where(Chapter.id.in_(chapter_ids)))}
    for cid in chapter_ids:
        chapter = chapters.get(cid)
        if chapter is None or chapter.project_id != volume.project_id:
            raise FieldError("chapter_ids", f"chapitre {cid} introuvable dans cette série")
    taken = session.execute(
        select(VolumeChapter.chapter_id, Volume.number)
        .join(Volume, Volume.id == VolumeChapter.volume_id)
        .where(VolumeChapter.chapter_id.in_(chapter_ids), VolumeChapter.volume_id != (volume.id or -1))
    ).all()
    if taken:
        chapter_id, number = taken[0]
        raise FieldError(
            "chapter_ids",
            f"le chapitre {chapters[chapter_id].number} est déjà dans le tome {number} : retire-l'en d'abord",
        )
    volume.chapter_links.clear()
    session.flush()
    for position, cid in enumerate(chapter_ids):
        volume.chapter_links.append(VolumeChapter(chapter_id=cid, position=position))


def _set_characters(session: Session, presets: PresetRegistry, volume: Volume, ids: list[int]) -> None:
    ids = list(dict.fromkeys(ids))
    limit = presets.cover.max_characters if presets.cover else 0
    if len(ids) > limit:
        raise FieldError("cover_character_ids", f"{limit} personnages au plus sur une couverture")
    found = set(
        session.scalars(select(Character.id).where(Character.project_id == volume.project_id, Character.id.in_(ids)))
    )
    missing = [i for i in ids if i not in found]
    if missing:
        raise FieldError("cover_character_ids", f"personnage {missing[0]} introuvable dans cette série")
    volume.cover_character_ids = ids


def _set_prompt(volume: Volume, prompt: str) -> None:
    text = prompt.strip()
    if text == (volume.cover_prompt or "").strip():
        return
    volume.cover_prompt = text
    volume.cover_prompt_source = "manual" if text else None
    if not text:
        volume.cover_prompt_notes = ""


# --- formats -----------------------------------------------------------------------------------
@router.get("/presets/cover-formats", response_model=list[CoverFormatOut])
def list_cover_formats(ctx: AppContext = Depends(get_ctx)) -> list[CoverFormatOut]:
    return [format_out(f, ctx.presets) for f in ctx.presets.cover_formats.values()]


# --- tomes -------------------------------------------------------------------------------------
@router.get("/projects/{project_id}/volumes", response_model=list[VolumeOut])
def list_volumes(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[VolumeOut]:
    series = get_project_or_404(session, project_id)
    presets = _presets(ctx, project_id)
    return [volume_out(v, presets) for v in series.volumes]


@router.post("/projects/{project_id}/volumes", response_model=VolumeOut, status_code=201)
def create_volume(
    project_id: int, body: VolumeIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> VolumeOut:
    get_project_or_404(session, project_id)
    presets = _presets(ctx, project_id)
    number = body.number
    if number is None:
        number = (session.scalar(select(func.max(Volume.number)).where(Volume.project_id == project_id)) or 0) + 1
    _check_number(session, project_id, number)
    format_id = body.cover_format or presets.default_cover_format
    if format_id is None:
        raise FieldError("cover_format", "aucun format de couverture dans presets/cover_formats/")
    _check_format(presets, format_id)
    volume = Volume(project_id=project_id, number=number, title=body.title.strip(), cover_format=format_id)
    session.add(volume)
    session.flush()
    set_chapters(session, volume, body.chapter_ids)
    session.commit()
    session.refresh(volume)
    return volume_out(volume, presets)


@router.get("/volumes/{volume_id}", response_model=VolumeOut)
def get_volume(
    volume_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> VolumeOut:
    volume = get_volume_or_404(session, volume_id)
    return volume_out(volume, _presets(ctx, volume.project_id))


@router.patch("/volumes/{volume_id}", response_model=VolumeOut)
def update_volume(
    volume_id: int, body: VolumePatch, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> VolumeOut:
    volume = get_volume_or_404(session, volume_id)
    presets = _presets(ctx, volume.project_id)
    apply_patch(session, presets, volume, body)
    session.commit()
    session.refresh(volume)
    return volume_out(volume, presets)


def apply_patch(session: Session, presets: PresetRegistry, volume: Volume, body: VolumePatch) -> None:
    fields = body.model_fields_set
    if body.number is not None and body.number != volume.number:
        _check_number(session, volume.project_id, body.number, volume.id)
        volume.number = body.number
    if body.title is not None:
        volume.title = body.title.strip()
    if body.cover_format is not None and body.cover_format != volume.cover_format:
        _check_format(presets, body.cover_format)
        volume.cover_format = body.cover_format
    if body.chapter_ids is not None:
        set_chapters(session, volume, body.chapter_ids)
    if body.cover_character_ids is not None:
        _set_characters(session, presets, volume, body.cover_character_ids)
    if body.cover_intent is not None:
        volume.cover_intent = body.cover_intent.strip()
    if "cover_prompt" in fields and body.cover_prompt is not None:
        _set_prompt(volume, body.cover_prompt)


@router.delete("/volumes/{volume_id}", status_code=204)
def delete_volume(
    volume_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    """Supprime le tome, ses versions de couverture et leurs fichiers ; ses chapitres restent dans la série."""
    volume = get_volume_or_404(session, volume_id)
    if active_cover_jobs(session, volume.id, None):
        raise HTTPException(status_code=409, detail="Couverture en cours de génération : annule-la d'abord")
    folder = f"projects/{volume.project_id}/volumes/{volume.id}"
    session.delete(volume)
    session.commit()
    ctx.files.delete_tree(folder)
    return Response(status_code=204)


# --- couverture -----------------------------------------------------------------------------------
@router.get("/volumes/{volume_id}/cover", response_model=CoverStudioOut)
def get_cover_studio(
    volume_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CoverStudioOut:
    volume = get_volume_or_404(session, volume_id)
    return studio_out(session, _presets(ctx, volume.project_id), volume)


@router.post("/volumes/{volume_id}/cover/prompt", response_model=CoverStudioOut)
def write_prompt(
    volume_id: int, body: CoverPromptIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CoverStudioOut:
    """L'IA rédige le prompt de couverture (bible, personnages choisis, intention) ; il reste éditable."""
    volume = get_volume_or_404(session, volume_id)
    presets = _presets(ctx, volume.project_id)
    if body.character_ids is not None:
        _set_characters(session, presets, volume, body.character_ids)
    if body.intent is not None:
        volume.cover_intent = body.intent.strip()
    session.flush()
    llm, error = ctx.agents.llm_for(WRITER_AGENT, volume.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'non configuré'}")
    try:
        brief = cover_brief(session, presets, volume, volume.project)
        run = write_cover_prompt(llm, presets.prompt(presets.require_cover().prompt), brief)
    except (PresetError, GenerationError) as exc:
        session.commit()  # intention et personnages gardés
        raise HTTPException(status_code=409, detail=_capitalize(str(exc))) from None
    volume.cover_prompt = run.prompt
    volume.cover_prompt_source = "ai"
    volume.cover_prompt_notes = run.notes
    session.commit()
    session.refresh(volume)
    return studio_out(session, presets, volume)


@router.post("/volumes/{volume_id}/cover/generate", response_model=JobOut, status_code=202)
def generate_cover(
    volume_id: int, body: CoverGenerateIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> JobOut:
    """Met en file la génération (palier Qualité, références des personnages, agrandissement au DPI du format) ;
    progression : /jobs/{id}/events. « Régénérer » = même appel : nouvelle graine, nouvelle version."""
    if ctx.providers.comfyui is None:
        detail = ctx.providers.errors.get("comfyui", "client non configuré")
        raise HTTPException(status_code=503, detail=f"ComfyUI indisponible : {detail}")
    volume = get_volume_or_404(session, volume_id)
    presets = _presets(ctx, volume.project_id)
    if body.prompt is not None:
        _set_prompt(volume, body.prompt)
    try:
        job = enqueue_cover(session, presets, volume, seed=body.seed)
    except (PresetError, GenerationError) as exc:
        session.commit()  # prompt édité gardé
        raise HTTPException(status_code=409, detail=_capitalize(str(exc))) from None
    session.commit()
    ctx.generation.notify()
    return job_out(job)


def _cover_or_404(session: Session, cover_id: int) -> VolumeCover:
    cover = session.get(VolumeCover, cover_id)
    if cover is None:
        raise HTTPException(status_code=404, detail="Version de couverture introuvable")
    return cover


@router.post("/volume-covers/{cover_id}/select", response_model=CoverStudioOut)
def select_cover(
    cover_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CoverStudioOut:
    cover = _cover_or_404(session, cover_id)
    volume = cover.volume
    if cover.kind == "back":
        volume.back_image = {"source": "generated", "id": cover.id}
    else:
        volume.selected_cover_id = cover.id
    session.commit()
    session.refresh(volume)
    return studio_out(session, _presets(ctx, volume.project_id), volume)


@router.delete("/volume-covers/{cover_id}", status_code=204)
def delete_cover(
    cover_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    cover = _cover_or_404(session, cover_id)
    volume = cover.volume
    path = cover.path
    volume.covers.remove(cover)
    if volume.selected_cover_id == cover_id:
        volume.selected_cover_id = None
    if (volume.back_image or {}).get("source") == "generated" and (volume.back_image or {}).get("id") == cover_id:
        volume.back_image = None
    session.commit()
    ctx.files.delete(path)
    return Response(status_code=204)


@router.get("/volume-covers/{cover_id}/file")
def get_cover_file(
    cover_id: int, v: str | None = None, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    cover = _cover_or_404(session, cover_id)
    path = ctx.files.absolute(cover.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
    return FileResponse(path, media_type=cover.content_type, headers=cache_headers(cover.path, v))


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]
