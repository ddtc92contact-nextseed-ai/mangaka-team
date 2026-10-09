"""Étape 4 : contrôle qualité des cases (détecteurs, cohérence des personnages, vision)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline.qc import (
    active_qc_job,
    any_layer_available,
    chapter_summary,
    layer_status,
    make_qc_job,
    override_ok,
    target_image,
)
from ..store.models import Page, Panel, PanelImage
from .chapters import get_chapter_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import get_panel_or_404, panel_image_out
from .jobs import job_out
from .schemas import (
    ChapterQCIn,
    ChapterQCOut,
    JobOut,
    PanelImageOut,
    PanelQCIn,
    QCLayerStatusOut,
    QCOverrideIn,
    QCStatusOut,
    QCSummaryOut,
)

router = APIRouter(tags=["contrôle qualité"])


def _status(ctx: AppContext) -> QCStatusOut:
    cfg = ctx.agents.presets_for(None).qc
    layers = layer_status(ctx.providers)
    detail = None
    if cfg is None:
        issue = next((i.message for i in ctx.presets.issues if i.file.startswith("qc.")), None)
        detail = f"presets/qc.yaml absent ou invalide{f' : {issue}' if issue else ''}"
    elif not any_layer_available(ctx.providers):
        detail = "aucune couche de contrôle disponible"
    return QCStatusOut(
        available=detail is None,
        detail=detail,
        auto_after_generation=bool(cfg and cfg.auto_after_generation),
        max_auto_retries=cfg.max_auto_retries if cfg else 0,
        ok_min=cfg.verdict.ok_min if cfg else None,
        reject_below=cfg.verdict.reject_below if cfg else None,
        vision_mode=cfg.vision.mode if cfg else None,
        layers={k: QCLayerStatusOut(**v) for k, v in layers.items()},
    )


def _require_qc(ctx: AppContext) -> None:
    status = _status(ctx)
    if not status.available:
        raise HTTPException(status_code=503, detail=f"Contrôle qualité indisponible : {status.detail}")


@router.get("/qc/status", response_model=QCStatusOut)
def qc_status(ctx: AppContext = Depends(get_ctx)) -> QCStatusOut:
    """Preset et fournisseurs de chaque couche (« détecteurs non installés »…)."""
    return _status(ctx)


@router.post("/panels/{panel_id}/qc", response_model=JobOut, status_code=202)
def run_panel_qc(
    panel_id: int,
    body: PanelQCIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> JobOut:
    """Contrôle une version de la case (la version choisie par défaut) ; progression via GET /jobs/{id}/events.

    Le job passe par la file de génération : il attend la fin des générations déjà en file.
    """
    body = body or PanelQCIn()
    _require_qc(ctx)
    panel = get_panel_or_404(session, panel_id)
    existing = active_qc_job(session, panel.id)
    if existing is not None:
        return job_out(existing)
    if body.image_id is not None:
        img = session.get(PanelImage, body.image_id)
        if img is None or img.panel_id != panel.id:
            raise FieldError("image_id", "cette version n'appartient pas à la case")
    else:
        img = target_image(panel)
        if img is None:
            raise FieldError("panel", "aucune version à contrôler : génère d'abord la case")
    chapter = panel.page.chapter
    job = make_qc_job(
        panel, [img.id], [panel.id], chapter_id=chapter.id, project_id=chapter.project_id, vision=body.vision
    )
    session.add(job)
    session.commit()
    ctx.generation.notify()
    return job_out(job)


@router.post("/chapters/{chapter_id}/qc", response_model=ChapterQCOut, status_code=202)
def run_chapter_qc(
    chapter_id: int,
    body: ChapterQCIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> ChapterQCOut:
    """Contrôle la version choisie de chaque case du chapitre (déjà contrôlées incluses avec `force`) : un job."""
    body = body or ChapterQCIn()
    _require_qc(ctx)
    chapter = get_chapter_or_404(session, chapter_id)
    pages = list(
        session.scalars(
            select(Page)
            .where(Page.chapter_id == chapter_id)
            .options(selectinload(Page.panels).selectinload(Panel.images))
            .order_by(Page.number)
        )
    )
    panels = [p for page in pages for p in page.panels]
    targets: list[tuple[int, int]] = []
    for panel in panels:
        img = next((i for i in panel.images if i.selected), None)
        if img is None or (img.qc_verdict is not None and not body.force) or active_qc_job(session, panel.id):
            continue
        targets.append((panel.id, img.id))
    job = None
    if targets:
        job = make_qc_job(
            None,
            [i for _, i in targets],
            [p for p, _ in targets],
            chapter_id=chapter.id,
            project_id=chapter.project_id,
            vision=body.vision,
        )
        session.add(job)
        session.commit()
        ctx.generation.notify()
    return ChapterQCOut(
        job=job_out(job) if job else None,
        panel_ids=[p for p, _ in targets],
        skipped=len(panels) - len(targets),
        summary=QCSummaryOut(**chapter_summary(session, chapter_id)),
    )


@router.get("/chapters/{chapter_id}/qc", response_model=QCSummaryOut)
def get_chapter_qc(chapter_id: int, session: Session = Depends(get_session)) -> QCSummaryOut:
    """Compteurs ok / à revoir / rejet du chapitre (verdict de la version choisie de chaque case)."""
    get_chapter_or_404(session, chapter_id)
    return QCSummaryOut(**chapter_summary(session, chapter_id))


@router.post("/panel-images/{image_id}/qc/override", response_model=PanelImageOut)
def override_panel_image_qc(
    image_id: int,
    body: QCOverrideIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PanelImageOut:
    """« Valider quand même » : force le verdict à ok ; la décision humaine et le verdict précédent sont tracés."""
    img = session.get(PanelImage, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="Version introuvable")
    override_ok(session, img, note=(body.note if body else None))
    session.commit()
    return panel_image_out(img, ctx.agents.presets_for(img.panel.page.chapter.project_id))
