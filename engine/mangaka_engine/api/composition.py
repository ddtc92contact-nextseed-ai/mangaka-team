"""Verrouillage de composition d'une case (ControlNet Union, voir pipeline/composition.py)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..pipeline.composition import (
    enqueue_preview,
    lock_composition,
    lock_preset_id,
    type_problem,
    unlock_composition,
    update_lock,
)
from ..pipeline.generation import GenerationError
from ..presets import PresetError
from ..store.files import InvalidImageError
from ..store.models import Panel
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import _presets, get_panel_or_404, panel_detail
from .schemas import CompositionLockIn, CompositionLockUpdate, PanelDetailOut

router = APIRouter(tags=["composition"])


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _require_available(ctx: AppContext, type_id: str | None) -> None:
    """Verrouillage refusé (message clair) si ComfyUI n'a pas le patch, son nœud ou le prétraitement."""
    status = ctx.control_status()
    problem = type_problem(status, type_id or str(status.get("default_type") or ""))
    if problem is not None:
        raise FieldError("composition_lock", problem)


def _apply(session: Session, ctx: AppContext, panel: Panel, action: Callable[[], Any]) -> PanelDetailOut:
    try:
        action()
    except PresetError as exc:
        raise FieldError("preset", _capitalize(str(exc))) from None
    except InvalidImageError as exc:
        raise FieldError("file", _capitalize(str(exc))) from None
    except GenerationError as exc:
        raise FieldError("composition_lock", _capitalize(str(exc))) from None
    session.commit()
    ctx.generation.notify()
    return panel_detail(session, ctx, panel)


@router.post("/panels/{panel_id}/composition-lock", response_model=PanelDetailOut)
def lock_panel(
    panel_id: int, body: CompositionLockIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDetailOut:
    """« Verrouiller la composition » depuis le croquis validé (ou un croquis donné) ou une version de la
    case : toute régénération de la case suivra cette image guide jusqu'au déverrouillage. L'aperçu de la
    carte de contrôle est mis en file."""
    panel = get_panel_or_404(session, panel_id)
    _require_available(ctx, body.type)
    if body.source == "version" and body.image_id is None:
        raise FieldError("image_id", "choisis la version qui sert d'image guide")
    return _apply(
        session,
        ctx,
        panel,
        lambda: lock_composition(
            session,
            _presets(ctx, panel),
            ctx.files,
            panel,
            source=body.source,
            image_id=body.image_id,
            control_type=body.type,
            strength=body.strength,
        ),
    )


@router.post("/panels/{panel_id}/composition-lock/import", response_model=PanelDetailOut)
async def lock_panel_from_import(
    panel_id: int,
    file: UploadFile = File(..., description="Image guide : croquis à la main, photo de pose… (PNG, JPEG, WebP)"),
    type: str | None = Form(default=None),
    strength: float | None = Form(default=None, ge=0, le=2),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PanelDetailOut:
    """Verrouille la composition sur une image importée par l'auteur."""
    panel = get_panel_or_404(session, panel_id)
    _require_available(ctx, type or None)
    max_bytes = ctx.settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FieldError("file", f"{file.filename or 'image'} : dépasse {ctx.settings.max_upload_mb} Mo")
    if not data:
        raise FieldError("file", "fichier vide")
    return _apply(
        session,
        ctx,
        panel,
        lambda: lock_composition(
            session,
            _presets(ctx, panel),
            ctx.files,
            panel,
            source="import",
            upload=data,
            control_type=type or None,
            strength=strength,
        ),
    )


@router.patch("/panels/{panel_id}/composition-lock", response_model=PanelDetailOut)
def update_panel_lock(
    panel_id: int,
    body: CompositionLockUpdate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PanelDetailOut:
    """Change le type de contrôle (nouvel aperçu de la carte) et/ou la force du verrou."""
    panel = get_panel_or_404(session, panel_id)
    if body.type is not None:
        _require_available(ctx, body.type)
    return _apply(
        session,
        ctx,
        panel,
        lambda: update_lock(session, _presets(ctx, panel), panel, control_type=body.type, strength=body.strength),
    )


@router.post("/panels/{panel_id}/composition-lock/preview", response_model=PanelDetailOut)
def refresh_lock_preview(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDetailOut:
    """Relance l'aperçu de la carte de contrôle (après un échec, par exemple)."""
    panel = get_panel_or_404(session, panel_id)
    if not isinstance(panel.composition_lock, dict):
        raise FieldError("composition_lock", "la composition de cette case n'est pas verrouillée")
    _require_available(ctx, str(panel.composition_lock.get("type") or ""))
    presets = _presets(ctx, panel)
    return _apply(
        session, ctx, panel, lambda: enqueue_preview(session, presets, panel, lock_preset_id(session, presets, panel))
    )


@router.delete("/panels/{panel_id}/composition-lock", response_model=PanelDetailOut)
def unlock_panel(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDetailOut:
    """Déverrouille : les prochaines générations retrouvent une composition libre."""
    panel = get_panel_or_404(session, panel_id)
    unlock_composition(ctx.files, panel)
    session.commit()
    return panel_detail(session, ctx, panel)


def _lock_file(ctx: AppContext, panel: Panel, key: str) -> FileResponse:
    lock = panel.composition_lock if isinstance(panel.composition_lock, dict) else {}
    holder = lock.get("preview") if key == "preview" else lock
    rel = holder.get("path") if isinstance(holder, dict) else None
    if not isinstance(rel, str) or not rel:
        raise HTTPException(status_code=404, detail="Image introuvable")
    path = ctx.files.absolute(rel)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/panels/{panel_id}/composition-lock/source")
def lock_source_file(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    """Image guide importée du verrou."""
    return _lock_file(ctx, get_panel_or_404(session, panel_id), "source")


@router.get("/panels/{panel_id}/composition-lock/preview")
def lock_preview_file(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    """Dernière carte de contrôle calculée (l'URL change à chaque aperçu : `?v=<job>`)."""
    return _lock_file(ctx, get_panel_or_404(session, panel_id), "preview")
