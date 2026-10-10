"""Planche de style d'une série (fiche série) : essais, choix, référence de style et son historique.

- `GET /projects/{id}/style-board` : référence active, historique, essais (plus récents d'abord), jobs en cours ;
- `POST /projects/{id}/style-board/trials` : met en file une série d'essais (4) au palier croquis ;
- `POST /style-trials/{id}/choose` : l'essai passe au propre et devient la référence de style ;
- `POST /style-references/{id}/activate` : reprend une ancienne référence de l'historique ;
- `GET /style-references/{id}/file` : image d'une référence. Image d'un essai : `/reference-variants/{id}/file`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload

from ..pipeline.generation import GenerationError
from ..pipeline.style import series_style, style_names
from ..pipeline.style_board import (
    ENTRY_KIND,
    activate,
    active_jobs,
    enqueue_choice,
    enqueue_trials,
    scene_test,
    style_assets,
    trials,
)
from ..presets import PresetError, PresetRegistry
from ..store.models import AssetKind, Project, ReferenceVariant, SeriesAsset
from .deps import AppContext, get_ctx, get_session
from .jobs import job_out
from .projects import get_project_or_404
from .schemas import JobOut, StyleBoardOut, StyleReferenceOut, StyleTrialOut

router = APIRouter(tags=["planche de style"])


def _presets(ctx: AppContext, project_id: int) -> PresetRegistry:
    return ctx.agents.presets_for(project_id)


def _require_comfyui(ctx: AppContext) -> None:
    if ctx.providers.comfyui is None:
        detail = ctx.providers.errors.get("comfyui", "client non configuré")
        raise HTTPException(status_code=503, detail=f"ComfyUI indisponible : {detail}")


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _style_or_404(session: Session, asset_id: int) -> SeriesAsset:
    asset = session.get(SeriesAsset, asset_id, options=[selectinload(SeriesAsset.reference_images)])
    if asset is None or asset.kind != AssetKind.style or not asset.reference_images:
        raise HTTPException(status_code=404, detail="Référence de style introuvable")
    return asset


def reference_out(asset: SeriesAsset, current_style: str, trial_ids: dict[int, int]) -> StyleReferenceOut:
    image = asset.reference_images[0]
    return StyleReferenceOut(
        id=asset.id,
        name=asset.name,
        url=f"/style-references/{asset.id}/file",
        width=image.width,
        height=image.height,
        active=asset.active,
        style=asset.visual_description,
        outdated=asset.visual_description != current_style,
        trial_id=trial_ids.get(image.id),
        created_at=asset.created_at,
    )


def trial_out(v: ReferenceVariant) -> StyleTrialOut:
    params = v.params or {}
    return StyleTrialOut(
        id=v.id,
        url=f"/reference-variants/{v.id}/file",
        batch=params.get("batch"),
        variant=params.get("variant"),
        count=params.get("count"),
        seed=v.seed,
        width=v.width,
        height=v.height,
        prompt=str(params.get("prompt") or ""),
        preset=params.get("preset"),
        chosen=v.kept_image_id is not None,
        created_at=v.created_at,
    )


def board_out(session: Session, presets: PresetRegistry, series: Project) -> StyleBoardOut:
    settings = presets.defaults.style_board if presets.defaults else None
    scene = scene_test(presets, series)
    style = series_style(presets, series)
    problem = None
    if settings is None:
        problem = "Aucune planche de style configurée (style_board de presets/defaults.yaml)."
    elif scene is None:
        problem = "Choisis d'abord le genre, le rendu et le ton de la série (Paramètres)."
    rows = trials(session, series.id)
    trial_ids = {v.kept_image_id: v.id for v in rows if v.kept_image_id is not None}
    assets = [a for a in style_assets(session, series.id) if a.reference_images]
    active = next((a for a in assets if a.active), None)
    return StyleBoardOut(
        configured=settings is not None,
        problem=problem,
        scene_test=scene,
        style=style,
        style_names=style_names(presets, series),
        trials_per_batch=settings.trials if settings is not None else 0,
        use_reference_sheets=settings.reference_sheets if settings is not None else None,
        use_panels=settings.panels if settings is not None else None,
        active=reference_out(active, style, trial_ids) if active is not None else None,
        history=[reference_out(a, style, trial_ids) for a in assets if a is not active],
        trials=[trial_out(v) for v in rows],
        active_jobs=[job_out(j) for j in active_jobs(session, series.id)],
    )


@router.get("/projects/{project_id}/style-board", response_model=StyleBoardOut)
def get_style_board(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> StyleBoardOut:
    series = get_project_or_404(session, project_id)
    return board_out(session, _presets(ctx, project_id), series)


@router.post("/projects/{project_id}/style-board/trials", response_model=list[JobOut], status_code=202)
def generate_trials(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[JobOut]:
    """Met en file une série d'essais (palier croquis, une graine par essai) ; progression : /jobs/{id}/events."""
    _require_comfyui(ctx)
    series = get_project_or_404(session, project_id)
    try:
        jobs = enqueue_trials(session, _presets(ctx, project_id), series)
    except (PresetError, GenerationError) as exc:
        raise HTTPException(status_code=409, detail=_capitalize(str(exc))) from None
    session.commit()
    ctx.generation.notify()
    return [job_out(j) for j in jobs]


@router.post("/style-trials/{trial_id}/choose", response_model=JobOut, status_code=202)
def choose_trial(trial_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)) -> JobOut:
    """L'essai passe au propre (palier de la série) puis devient la référence de style active."""
    _require_comfyui(ctx)
    trial = session.get(ReferenceVariant, trial_id)
    if trial is None or trial.entry_kind != ENTRY_KIND:
        raise HTTPException(status_code=404, detail="Essai introuvable")
    series = get_project_or_404(session, trial.entry_id)
    try:
        job = enqueue_choice(session, _presets(ctx, series.id), series, trial)
    except (PresetError, GenerationError) as exc:
        raise HTTPException(status_code=409, detail=_capitalize(str(exc))) from None
    session.commit()
    ctx.generation.notify()
    return job_out(job)


@router.post("/style-references/{asset_id}/activate", response_model=StyleBoardOut)
def activate_reference(
    asset_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> StyleBoardOut:
    """Reprend une référence de style de l'historique (la référence active passe dans l'historique)."""
    asset = _style_or_404(session, asset_id)
    activate(session, asset.project_id, asset)
    session.commit()
    series = get_project_or_404(session, asset.project_id)
    return board_out(session, _presets(ctx, series.id), series)


@router.get("/style-references/{asset_id}/file")
def get_reference_file(
    asset_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    image = _style_or_404(session, asset_id).reference_images[0]
    path = ctx.files.absolute(image.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
    return FileResponse(path, media_type=image.content_type, headers={"Cache-Control": "private, max-age=3600"})
