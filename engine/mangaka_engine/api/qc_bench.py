"""Banc d'essai du QC : annotation bonne / mauvaise des versions, runs de mesure, seuils suggérés."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.qc_bench import (
    BENCH_LAYERS,
    STEP,
    active_bench_job,
    apply_changes,
    dataset_stats,
    export_csv,
    planned_changes,
    preset_hash,
)
from ..presets import PresetError
from ..store.models import (
    AnnotationLabel,
    Chapter,
    Job,
    JobStatus,
    PanelImage,
    PanelImageAnnotation,
    Project,
    QCBenchRun,
    utcnow,
)
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import annotation_out
from .jobs import job_out
from .qc import _require_qc
from .schemas import (
    AnnotationIn,
    AnnotationOut,
    BenchApplyIn,
    BenchApplyOut,
    BenchDatasetOut,
    BenchRunDetailOut,
    BenchRunIn,
    BenchRunOut,
)

router = APIRouter(tags=["banc d'essai du QC"])


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite rend des dates sans fuseau (stockées en UTC) : on les marque UTC pour le navigateur."""
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


# --- annotation --------------------------------------------------------------------------------
def _image_or_404(session: Session, image_id: int) -> PanelImage:
    img = session.get(PanelImage, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="Version introuvable")
    return img


@router.put("/panel-images/{image_id}/annotation", response_model=AnnotationOut)
def annotate_panel_image(image_id: int, body: AnnotationIn, session: Session = Depends(get_session)) -> AnnotationOut:
    """Annote une version « bonne » ou « mauvaise » (+ défauts, note). Indépendant du verdict QC."""
    img = _image_or_404(session, image_id)
    ann = img.annotation
    if ann is None:
        ann = PanelImageAnnotation(image_id=img.id, label=AnnotationLabel(body.label))
        session.add(ann)
        img.annotation = ann
    ann.label = AnnotationLabel(body.label)
    # Les défauts décrivent une mauvaise case : une case « bonne » n'en garde pas.
    ann.defects = list(body.defects) if body.label == "bad" else []
    ann.note = body.note
    ann.updated_at = utcnow()
    session.commit()
    out = annotation_out(ann)
    assert out is not None
    return out


@router.delete("/panel-images/{image_id}/annotation", status_code=204)
def delete_panel_image_annotation(image_id: int, session: Session = Depends(get_session)) -> Response:
    img = _image_or_404(session, image_id)
    if img.annotation is not None:
        session.delete(img.annotation)
        session.commit()
    return Response(status_code=204)


# --- ensemble annoté ---------------------------------------------------------------------------
def _check_scope(session: Session, project_id: int | None, chapter_id: int | None) -> None:
    if project_id is not None and session.get(Project, project_id) is None:
        raise FieldError("project_id", "série introuvable")
    if chapter_id is not None:
        chapter = session.get(Chapter, chapter_id)
        if chapter is None:
            raise FieldError("chapter_id", "chapitre introuvable")
        if project_id is not None and chapter.project_id != project_id:
            raise FieldError("chapter_id", "ce chapitre n'appartient pas à la série choisie")


def _scope_label(session: Session, project_id: int | None, chapter_id: int | None) -> str:
    chapter = session.get(Chapter, chapter_id) if chapter_id is not None else None
    if chapter is not None:
        return f"{chapter.project.title} · ch. {chapter.number}"
    project = session.get(Project, project_id) if project_id is not None else None
    if project is not None:
        return project.title
    return "toutes les séries"


@router.get("/qc/bench/dataset", response_model=BenchDatasetOut)
def bench_dataset(
    project_id: int | None = Query(default=None),
    chapter_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> BenchDatasetOut:
    """Cases annotées (bonnes / mauvaises, par défaut) de l'ensemble filtré, avec l'objectif du preset."""
    _check_scope(session, project_id, chapter_id)
    cfg = ctx.presets.qc
    return BenchDatasetOut(
        **dataset_stats(session, project_id, chapter_id),
        goal_min=cfg.bench.annotation_goal.min if cfg else None,
        goal_max=cfg.bench.annotation_goal.max if cfg else None,
        target_recall=cfg.bench.target_recall if cfg else None,
    )


# --- runs ---------------------------------------------------------------------------------------
def _run_status(run: QCBenchRun, job: Job | None) -> str:
    if job is not None:
        if job.status == JobStatus.succeeded and run.metrics is None:
            return "failed"
        return job.status.value
    return "succeeded" if run.metrics is not None else "failed"


def _run_out(session: Session, run: QCBenchRun) -> BenchRunOut:
    job = session.get(Job, run.job_id) if run.job_id is not None else None
    metrics = run.metrics or {}
    layers: dict[str, dict[str, Any]] = {}
    for name in BENCH_LAYERS:
        m = (metrics.get("layers") or {}).get(name)
        if m is None:
            continue
        layers[name] = {
            "label": m.get("label"),
            "precision": m.get("precision"),
            "recall": m.get("recall"),
            "fp": m["confusion"]["fp"],
            "fn": m["confusion"]["fn"],
            "evaluated": m.get("evaluated"),
            "mean_ms": m.get("mean_ms"),
        }
    error = job.error if job is not None else None
    if job is None and run.metrics is None:
        error = "Run interrompu"
    return BenchRunOut(
        id=run.id,
        job=job_out(job) if job is not None else None,
        status=_run_status(run, job),
        error=error,
        project_id=run.project_id,
        chapter_id=run.chapter_id,
        scope=_scope_label(session, run.project_id, run.chapter_id),
        vision=run.vision,
        preset_hash=run.preset_hash,
        sample_count=run.sample_count,
        good=metrics.get("good"),
        bad=metrics.get("bad"),
        created_at=as_utc(run.created_at),
        finished_at=as_utc(run.finished_at),
        applied_at=as_utc(run.applied_at),
        layers=layers,
    )


def _run_or_404(session: Session, run_id: int) -> QCBenchRun:
    run = session.get(QCBenchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run du banc d'essai introuvable")
    return run


@router.post("/qc/bench/runs", response_model=BenchRunOut, status_code=202)
def start_bench_run(
    body: BenchRunIn | None = None, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BenchRunOut:
    """Lance le banc d'essai sur l'ensemble annoté (filtrable par série / chapitre) : un job `qc_bench`
    dans la file de la génération (la vision ne tourne jamais pendant ComfyUI). Progression : SSE du job."""
    body = body or BenchRunIn()
    _require_qc(ctx)
    _check_scope(session, body.project_id, body.chapter_id)
    if active_bench_job(session) is not None:
        raise HTTPException(status_code=409, detail="Un banc d'essai est déjà en cours : attends sa fin")
    stats = dataset_stats(session, body.project_id, body.chapter_id)
    if not stats["total"]:
        raise FieldError("dataset", "aucune case annotée dans cet ensemble : annote des versions dans l'atelier")
    project_id = body.project_id
    if body.chapter_id is not None and project_id is None:
        chapter = session.get(Chapter, body.chapter_id)
        project_id = chapter.project_id if chapter else None
    scope = _scope_label(session, body.project_id, body.chapter_id)
    job = Job(
        project_id=project_id,
        chapter_id=body.chapter_id,
        step=STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={"sample_count": stats["total"], "scope": scope, "vision": body.vision},
    )
    session.add(job)
    session.flush()
    run = QCBenchRun(
        job_id=job.id,
        project_id=body.project_id,
        chapter_id=body.chapter_id,
        vision=body.vision,
        sample_count=stats["total"],
    )
    session.add(run)
    session.commit()
    ctx.generation.notify()
    return _run_out(session, run)


@router.get("/qc/bench/runs", response_model=list[BenchRunOut])
def list_bench_runs(
    limit: int = Query(default=50, ge=1, le=500), session: Session = Depends(get_session)
) -> list[BenchRunOut]:
    """Historique des runs, du plus récent au plus ancien."""
    runs = session.scalars(select(QCBenchRun).order_by(QCBenchRun.id.desc()).limit(limit))
    return [_run_out(session, r) for r in runs]


@router.get("/qc/bench/runs/{run_id}", response_model=BenchRunDetailOut)
def get_bench_run(
    run_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> BenchRunDetailOut:
    """Run complet : métriques par couche (matrice, balayage, seuil suggéré), cases, run précédent terminé."""
    run = _run_or_404(session, run_id)
    previous = session.scalar(
        select(QCBenchRun)
        .where(QCBenchRun.id < run.id, QCBenchRun.metrics.is_not(None))
        .order_by(QCBenchRun.id.desc())
        .limit(1)
    )
    cfg = ctx.presets.qc
    return BenchRunDetailOut(
        **_run_out(session, run).model_dump(),
        metrics=run.metrics,
        items=list(run.items or []),
        preset=dict(run.preset or {}),
        previous=_run_out(session, previous) if previous is not None else None,
        current_preset_hash=preset_hash(cfg) if cfg else None,
    )


@router.get("/qc/bench/runs/{run_id}/export")
def export_bench_run(
    run_id: int, format: Literal["json", "csv"] = Query(default="json"), session: Session = Depends(get_session)
) -> Response:
    """Export du run : JSON complet (métriques + cases) ou CSV (une ligne par case, séparateur « ; »)."""
    run = _run_or_404(session, run_id)
    if run.metrics is None:
        raise HTTPException(status_code=409, detail="Ce run n'est pas terminé : rien à exporter")
    name = f"banc-essai-qc-{run.id}"
    if format == "csv":
        # BOM : Excel / LibreOffice ouvrent le fichier en UTF-8 (accents).
        return Response(
            content="﻿" + export_csv(run.items or []),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    out = _run_out(session, run).model_dump(mode="json")
    out |= {"preset": run.preset, "metrics": run.metrics, "items": run.items}
    return Response(
        content=json.dumps(out, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
    )


@router.post("/qc/bench/runs/{run_id}/apply", response_model=BenchApplyOut)
def apply_bench_thresholds(
    run_id: int,
    body: BenchApplyIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> BenchApplyOut:
    """Seuils suggérés → presets/qc.yaml. Sans `confirm: true` : simple aperçu, rien n'est écrit.

    Le fichier est revalidé avant écriture (commentaires conservés) puis rechargé : le QC suivant
    utilise les nouveaux seuils."""
    body = body or BenchApplyIn()
    run = _run_or_404(session, run_id)
    if run.metrics is None:
        raise HTTPException(status_code=409, detail="Ce run n'est pas terminé : pas de seuil suggéré")
    cfg = ctx.presets.qc
    if cfg is None:
        raise HTTPException(status_code=503, detail="presets/qc.yaml absent ou invalide : corrige-le d'abord")
    changes = planned_changes(run.metrics, cfg)
    changed = bool(run.preset_hash) and run.preset_hash != preset_hash(cfg)
    if not changes:
        return BenchApplyOut(
            applied=False, changes=[], preset_changed=changed, message="Les seuils du preset sont déjà ceux suggérés"
        )
    if not body.confirm:
        return BenchApplyOut(
            applied=False,
            changes=changes,
            preset_changed=changed,
            message="Aperçu : confirme pour écrire presets/qc.yaml",
        )
    try:
        apply_changes(ctx.presets, changes)
    except PresetError as exc:
        raise HTTPException(status_code=422, detail=f"Seuils non appliqués : {exc}") from None
    run.applied_at = utcnow()
    session.commit()
    n = len(changes)
    return BenchApplyOut(
        applied=True,
        changes=changes,
        preset_changed=changed,
        message=f"presets/qc.yaml mis à jour ({n} valeur{'s' if n > 1 else ''}) et rechargé",
    )
