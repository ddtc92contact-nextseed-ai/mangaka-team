"""« Remettre l'atelier à zéro » (écran Réglages) : même opération que `npm run reset` (voir reset.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..reset import CONFIRM_WORD, ResetBusyError, ResetError, is_confirmation, reset_workshop
from .deps import AppContext, get_ctx
from .errors import FieldError
from .schemas import ResetIn, ResetOut

router = APIRouter(tags=["réglages"])


@router.post("/reset", response_model=ResetOut)
def reset(body: ResetIn, ctx: AppContext = Depends(get_ctx)) -> ResetOut:
    """Sauvegarde puis efface toutes les séries ; refusé (409) si un job tourne, rien d'effacé si la
    sauvegarde échoue (500 avec la raison)."""
    if not is_confirmation(body.confirm):
        raise FieldError("confirm", f"tape {CONFIRM_WORD} pour confirmer")
    try:
        report = reset_workshop(ctx.settings, everything=body.all)
    except ResetBusyError as exc:
        raise HTTPException(status_code=409, detail=f"Remise à zéro refusée : {exc}") from None
    except ResetError as exc:
        raise HTTPException(status_code=500, detail=f"Remise à zéro impossible : {exc}") from None
    finally:
        ctx.agents.invalidate()  # surcharges et réglages des agents relus depuis la base
    return ResetOut(
        backup=str(report.backup),
        all=report.all,
        series_deleted=report.series_deleted,
        data_removed=report.data_removed,
        comfyui_removed=report.comfyui_removed,
        comfyui_warning=report.comfyui_warning,
    )
