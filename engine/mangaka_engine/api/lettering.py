"""Étape 5 : lettrage (bulles, onomatopées), assemblage de la planche, rendu d'une page et export d'un chapitre."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.fonts import FontBook
from ..pipeline.lettering import LetteringError
from ..pipeline.render import (
    STEP,
    bubble_fit_preview,
    lettering_json,
    page_file_stem,
    page_inputs,
    read_render_info,
    render_folder,
    render_page_to_files,
)
from ..pipeline.render import export_job as make_export_job
from ..presets import PresetError, PresetRegistry
from ..store.models import Bubble, BubbleKind, Job, JobStatus, Page, Panel
from ..validation import translate_error
from .chapters import get_chapter_or_404, get_page_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import BubbleBox, BubbleUpdate, ExportIn, JobOut, RenderIn, SfxCreate
from .stages import gate
from .storage import sync_library

SFX_MAX_CHARS = 60
SFX_PER_PANEL = 8

router = APIRouter(tags=["lettrage"])


def _presets(ctx: AppContext, page: Page) -> PresetRegistry:
    """Presets de la série de la page, avec les réglages du lettreur (écran « L'équipe »)."""
    return ctx.agents.presets_for(page.chapter.project_id)


def _fonts(ctx: AppContext, presets: PresetRegistry | None = None) -> FontBook:
    try:
        return FontBook(presets or ctx.presets)
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _invalid_data(exc: ValidationError) -> str:
    """Donnée enregistrée hors des bornes (jamais une stack trace ni un message anglais côté client)."""
    details = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', ()))} : {translate_error(e)}" for e in exc.errors())
    return f"données de lettrage invalides ({details})"


def _lettering(ctx: AppContext, page: Page) -> dict[str, Any]:
    presets = _presets(ctx, page)
    fonts = _fonts(ctx, presets)
    try:
        return lettering_json(page, page_inputs(presets, ctx.files, page, fonts, preview=True), fonts, presets)
    except (LetteringError, PresetError) as exc:
        raise FieldError("lettering", str(exc)) from None
    except ValidationError as exc:
        raise FieldError("lettering", _invalid_data(exc)) from None


def _render_out(info: dict[str, Any]) -> dict[str, Any]:
    page_id = info["page_id"]
    # Rendu servi en « no-store » ; la version (date du rendu) change quand même l'URL à chaque rendu.
    v = "".join(ch for ch in str(info.get("rendered_at") or "") if ch.isdigit())
    tag = f"?v={v}" if v else ""
    return {**info, "png_url": f"/pages/{page_id}/render.png{tag}", "svg_url": f"/pages/{page_id}/render.svg{tag}"}


# --- lettrage ------------------------------------------------------------------------------
@router.get("/pages/{page_id}/lettering")
def get_lettering(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """Lettrage calculé de la page : cases, bulles (forme, texte, queue), avertissements."""
    return _lettering(ctx, get_page_or_404(session, page_id))


@router.post("/pages/{page_id}/lettering/reset")
def reset_lettering(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """« Recalculer le lettrage » : oublie les positions, queues et tailles de texte ajustées à la main (et,
    pour une onomatopée, sa taille, son angle et son cisaillement ; son intensité et sa police restent)."""
    page = get_page_or_404(session, page_id)
    for panel in page.panels:
        for bubble in panel.bubbles:
            bubble.position = None
            bubble.tail = None
            if bubble.kind == BubbleKind.sfx and bubble.sfx:
                bubble.sfx = {k: v for k, v in bubble.sfx.items() if k in ("intensity", "font")}
    session.commit()
    return _lettering(ctx, page)


@router.patch("/bubbles/{bubble_id}")
def update_bubble(
    bubble_id: int, body: BubbleUpdate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """Édite une bulle (texte, type, locuteur, cadre, pointe de la queue, taille du texte) ; renvoie le
    lettrage de la page.

    Un cadre ou une pointe envoyés sont conservés tels quels (« ajusté à la main ») ; `null` rend
    la main au placement automatique. Le texte d'un cadre ajusté à la main le remplit (taille recalculée
    au lettrage) ; une taille `size_pt` envoyée l'emporte, jusqu'à `size_pt: null` (automatique). Elle
    est gardée dans `position` et survit au déplacement, au redimensionnement et au retour au placement
    automatique.
    """
    bubble = session.get(Bubble, bubble_id)
    if bubble is None:
        raise HTTPException(status_code=404, detail="Bulle introuvable")
    page = bubble.panel.page
    changes = body.model_dump(exclude_unset=True)
    for key in ("text", "kind", "speaker"):
        if key in changes and changes[key] is None:
            raise FieldError(key, "ne peut pas être vide")
    if bubble.kind == BubbleKind.sfx:
        _update_sfx(bubble, body, changes, fonts=_fonts(ctx, _presets(ctx, page)).preset.sfx_choices())
        session.commit()
        return _lettering(ctx, page)
    if "sfx" in changes:
        raise FieldError("sfx", "réglages réservés aux onomatopées")
    if "text" in changes:
        bubble.text = changes["text"]
    if "kind" in changes:
        bubble.kind = BubbleKind(changes["kind"])
    if "speaker" in changes:
        bubble.speaker_name = changes["speaker"]
    width = page.layout["page"]["width"] if page.layout else None
    height = page.layout["page"]["height"] if page.layout else None
    if "position" in changes or "size_pt" in changes:
        old = dict(bubble.position or {})
        size = changes["size_pt"] if "size_pt" in changes else old.get("size_pt")
        if "position" in changes:
            pos = changes["position"]
            if pos is not None and width and height:
                pos["x"] = min(max(pos["x"], -pos["w"] + 10), width - 10)
                pos["y"] = min(max(pos["y"], -pos["h"] + 10), height - 10)
            frame = {**pos, "manual": True} if pos is not None else {}
        else:
            frame = {k: v for k, v in old.items() if k != "size_pt"}
        if size is not None:
            frame["size_pt"] = round(float(size), 1)
        bubble.position = frame or None
    if "tail" in changes:
        tail = changes["tail"]
        if tail is not None and width and height:
            tail["x"] = min(max(tail["x"], 0), width)
            tail["y"] = min(max(tail["y"], 0), height)
        bubble.tail = {**tail, "manual": True} if tail is not None else None
    session.commit()
    return _lettering(ctx, page)


@router.post("/bubbles/{bubble_id}/fit")
def fit_bubble(
    bubble_id: int, body: BubbleBox, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """Aperçu pendant le redimensionnement d'une bulle : taille et lignes de son texte dans le cadre envoyé,
    calculées comme au lâcher (le texte ne saute pas). Rien n'est enregistré."""
    bubble = session.get(Bubble, bubble_id)
    if bubble is None:
        raise HTTPException(status_code=404, detail="Bulle introuvable")
    if bubble.kind == BubbleKind.sfx:
        raise FieldError("position", "une onomatopée n'a pas de cadre")
    page = bubble.panel.page
    presets = _presets(ctx, page)
    try:
        return bubble_fit_preview(presets, _fonts(ctx, presets), page, bubble, body.model_dump())
    except (LetteringError, PresetError) as exc:
        raise FieldError("lettering", str(exc)) from None


def _update_sfx(bubble: Bubble, body: BubbleUpdate, changes: dict[str, Any], *, fonts: list[str]) -> None:
    for key in ("kind", "position", "tail", "speaker", "size_pt"):
        if key in changes:
            if key == "size_pt":
                raise FieldError(key, "la taille d'une onomatopée se règle dans ses réglages (sfx.size_pt)")
            raise FieldError(key, "une onomatopée n'a ni type de bulle, ni cadre, ni queue, ni locuteur")
    if "text" in changes:
        if len(changes["text"]) > SFX_MAX_CHARS:
            raise FieldError("text", f"une onomatopée tient en {SFX_MAX_CHARS} caractères au plus")
        bubble.text = changes["text"]
    if body.sfx is None:
        if "sfx" in changes:  # null : tout redevient automatique (intensité gardée)
            bubble.sfx = {k: v for k, v in (bubble.sfx or {}).items() if k == "intensity"}
            bubble.position = None
        return
    params = dict(bubble.sfx or {})
    sent = body.sfx.model_fields_set
    if "font" in sent and body.sfx.font is not None and body.sfx.font not in fonts:
        raise FieldError("sfx", f"police d'onomatopée inconnue : « {body.sfx.font} » (au choix : {', '.join(fonts)})")
    for key in ("intensity", "font", "size_pt", "angle", "skew"):
        if key in sent:
            value = getattr(body.sfx, key)
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
    if "x" in sent or "y" in sent:
        x, y = body.sfx.x, body.sfx.y
        if (x is None) != (y is None):
            raise FieldError("sfx", "x et y vont ensemble (centre de l'onomatopée)")
        bubble.position = (
            {"x": round(x, 1), "y": round(y, 1), "manual": True} if x is not None and y is not None else None
        )
    bubble.sfx = params


@router.post("/panels/{panel_id}/sfx", status_code=201)
def add_sfx(
    panel_id: int, body: SfxCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """Ajoute une onomatopée à la case (centre facultatif : sinon placement automatique) ; renvoie le lettrage."""
    panel = session.get(Panel, panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Case introuvable")
    if sum(1 for b in panel.bubbles if b.kind == BubbleKind.sfx) >= SFX_PER_PANEL:
        raise FieldError("sfx", f"{SFX_PER_PANEL} onomatopées au plus par case")
    if (body.x is None) != (body.y is None):
        raise FieldError("sfx", "x et y vont ensemble (centre de l'onomatopée)")
    position = {"x": round(body.x, 1), "y": round(body.y, 1), "manual": True} if body.x is not None else None
    panel.bubbles.append(
        Bubble(
            order=max((b.order for b in panel.bubbles), default=-1) + 1,
            text=body.text,
            kind=BubbleKind.sfx,
            sfx={"intensity": body.intensity},
            position=position,
        )
    )
    session.commit()
    return _lettering(ctx, panel.page)


@router.delete("/bubbles/{bubble_id}")
def delete_sfx(
    bubble_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """Supprime une onomatopée (les répliques se suppriment dans l'écran Scénario) ; renvoie le lettrage."""
    bubble = session.get(Bubble, bubble_id)
    if bubble is None:
        raise HTTPException(status_code=404, detail="Bulle introuvable")
    if bubble.kind != BubbleKind.sfx:
        raise FieldError("bubble", "seules les onomatopées se suppriment ici ; les répliques, dans le Scénario")
    page = bubble.panel.page
    session.delete(bubble)
    session.commit()
    session.refresh(page)
    return _lettering(ctx, page)


@router.delete("/bubbles/{bubble_id}/reply")
def delete_reply(
    bubble_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    """Supprime une réplique depuis la planche brouillon (name) ; les suivantes de la case se resserrent.
    Renvoie le lettrage de la page."""
    bubble = session.get(Bubble, bubble_id)
    if bubble is None:
        raise HTTPException(status_code=404, detail="Bulle introuvable")
    if bubble.kind == BubbleKind.sfx:
        raise FieldError("bubble", "une onomatopée se supprime avec DELETE /bubbles/{id}")
    panel = bubble.panel
    session.delete(bubble)
    session.flush()
    session.expire(panel, ["bubbles"])
    for i, b in enumerate(panel.bubbles):
        b.order = i
    session.commit()
    session.refresh(panel.page)
    return _lettering(ctx, panel.page)


@router.get("/lettering/sfx-fonts/{font_id}.ttf")
def sfx_font(font_id: str, project_id: int | None = None, ctx: AppContext = Depends(get_ctx)) -> Response:
    """Police d'onomatopée (instance statique), pour l'aperçu de l'écran Lettrage."""
    fonts = _fonts(ctx, ctx.agents.presets_for(project_id))
    if font_id not in fonts.preset.sfx_choices():
        raise HTTPException(status_code=404, detail="Police d'onomatopée inconnue")
    return Response(
        fonts.data(fonts.sfx_style(font_id)), media_type="font/ttf", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.get("/lettering/fonts/{kind}.ttf")
def lettering_font(kind: str, project_id: int | None = None, ctx: AppContext = Depends(get_ctx)) -> Response:
    """Police (instance statique) d'un type de bulle, pour l'aperçu de l'écran Lettrage."""
    fonts = _fonts(ctx, ctx.agents.presets_for(project_id))
    if kind not in fonts.preset.styles:
        raise HTTPException(status_code=404, detail="Type de bulle inconnu")
    return Response(
        fonts.data(fonts.style(kind)), media_type="font/ttf", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.get("/lettering/font-samples/{kind}/{font_id}.ttf")
def font_sample(kind: str, font_id: str, project_id: int | None = None, ctx: AppContext = Depends(get_ctx)) -> Response:
    """N'importe quelle police de fonts.yaml telle que le lettrage la poserait pour `kind` (type de bulle, ou
    `sfx` pour une onomatopée) : graisse et italique du style, pour les tuiles d'aperçu de la fiche série.
    Instance statique gardée en cache (lru) côté moteur, et par le navigateur une heure."""
    fonts = _fonts(ctx, ctx.agents.presets_for(project_id))
    if font_id not in fonts.preset.fonts:
        raise HTTPException(status_code=404, detail="Police inconnue")
    if kind == "sfx":
        style = fonts.sfx_style(font_id)
    elif kind in fonts.preset.styles:
        style = fonts.style(kind).model_copy(update={"font": font_id})
    else:
        raise HTTPException(status_code=404, detail="Type de bulle inconnu")
    try:
        data = fonts.data(style)
    except PresetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return Response(data, media_type="font/ttf", headers={"Cache-Control": "private, max-age=3600"})


# --- rendu d'une page ------------------------------------------------------------------------
@router.post("/pages/{page_id}/render")
def render_page(
    page_id: int,
    body: RenderIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> dict[str, Any]:
    """Assemble la page et l'exporte en PNG (300 DPI) + SVG ; option fond perdu / repères de coupe."""
    body = body or RenderIn()
    page = get_page_or_404(session, page_id)
    gate(session, page.chapter, "lettering", page=page)
    try:
        info = render_page_to_files(_presets(ctx, page), ctx.files, page, bleed=body.bleed, crop_marks=body.crop_marks)
    except (LetteringError, PresetError) as exc:
        raise FieldError("render", str(exc)) from None
    except ValidationError as exc:
        raise FieldError("render", _invalid_data(exc)) from None
    sync_library(ctx, session, page.chapter.project)  # planches/page-NN.png|svg de la bibliothèque lisible
    return _render_out(info)


@router.get("/pages/{page_id}/render")
def get_render(
    page_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    get_page_or_404(session, page_id)
    info = read_render_info(ctx.files, page_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Page pas encore rendue")
    return _render_out(info)


def _render_file(ctx: AppContext, page_id: int, ext: str, media_type: str, *, inline: bool = False) -> FileResponse:
    info = read_render_info(ctx.files, page_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Page pas encore rendue")
    name = f"{info.get('stem') or page_file_stem(int(info['page_number']))}.{ext}"
    path = ctx.files.absolute(f"{render_folder(page_id)}/{name}")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier de rendu manquant dans data/")
    return FileResponse(
        path,
        media_type=media_type,
        filename=name,
        headers={"Cache-Control": "no-store"},
        content_disposition_type="inline" if inline else "attachment",
    )


@router.get("/pages/{page_id}/render.png")
def get_render_png(page_id: int, ctx: AppContext = Depends(get_ctx)) -> FileResponse:
    return _render_file(ctx, page_id, "png", "image/png")


@router.get("/pages/{page_id}/render.svg")
def get_render_svg(page_id: int, ctx: AppContext = Depends(get_ctx)) -> FileResponse:
    """SVG affiché dans le navigateur (texte sélectionnable) ; « Enregistrer sous » pour le fichier."""
    return _render_file(ctx, page_id, "svg", "image/svg+xml", inline=True)


# --- export d'un chapitre ---------------------------------------------------------------------
@router.post("/chapters/{chapter_id}/export", response_model=JobOut, status_code=202)
def export_chapter(
    chapter_id: int,
    body: ExportIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> JobOut:
    """Lance l'export du chapitre (ZIP de PNG + SVG numérotés) ; progression via GET /jobs/{id}/events."""
    body = body or ExportIn()
    chapter = get_chapter_or_404(session, chapter_id)
    presets = ctx.agents.presets_for(chapter.project_id)
    _fonts(ctx, presets)
    if not any(p.layout and p.panels for p in chapter.pages):
        raise FieldError("export", "aucune page mise en page dans ce chapitre : rien à exporter")
    gate(session, chapter, "export")
    running = session.scalar(
        select(Job.id).where(
            Job.chapter_id == chapter_id, Job.step == STEP, Job.status.in_([JobStatus.pending, JobStatus.running])
        )
    )
    if running is not None:
        raise HTTPException(status_code=409, detail="Un export de ce chapitre est déjà en cours")
    job = Job(
        project_id=chapter.project_id,
        chapter_id=chapter_id,
        step=STEP,
        message="En attente…",
        params={"bleed": body.bleed, "crop_marks": body.crop_marks},
    )
    session.add(job)
    session.commit()
    ctx.jobs.submit(
        job.id,
        make_export_job(
            ctx.db,
            presets,
            ctx.files,
            chapter_id,
            job.id,
            bleed=body.bleed,
            crop_marks=body.crop_marks,
            on_done=ctx.library.sync_project if ctx.library is not None else None,
        ),
    )
    return job_out(job)


@router.get("/exports/{job_id}/file")
def download_export(
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
