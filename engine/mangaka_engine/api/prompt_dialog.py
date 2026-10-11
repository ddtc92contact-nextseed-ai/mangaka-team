"""Atelier : dialogue avec l'IA sur une case précise (consigne → proposition → Appliquer / Annuler).

- `POST /panels/{id}/dialog` : la consigne et le contexte de la case partent au LLM du Dessinateur
  (`pipeline/prompt_dialog.py`) ; la proposition validée est notée dans l'historique de la case
  (`proposed`) sans rien changer à la case ; échec → erreur lisible, case inchangée.
- `POST /panel-dialog/{id}/apply` : applique la proposition (prompt gardé comme une édition à la main
  jusqu'à « Reconstruire le prompt », direction et références propres à la case) ; `generate` : une
  nouvelle version de cette case seulement (les versions existantes restent).
- `POST /panel-dialog/{id}/cancel` : la case reste comme elle était.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.generation import apply_dialog_proposal, dialog_request, run_dialog_request
from ..pipeline.prompt_dialog import PromptDialogError
from ..pipeline.prompt_writer import AGENT_ID as WRITER_AGENT
from ..store.models import PanelDialogTurn
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import (
    _enqueue,
    _presets,
    _require_comfyui,
    _require_lock_available,
    get_panel_or_404,
    panel_detail,
)
from .jobs import job_out
from .schemas import DialogApplyIn, DialogChangeOut, JobOut, PanelDetailOut, PanelDialogIn, PanelDialogTurnOut

router = APIRouter(tags=["génération"])


class DialogApplyOut(BaseModel):
    turn: PanelDialogTurnOut
    panel: PanelDetailOut
    jobs: list[JobOut]


def turn_out(turn: PanelDialogTurn) -> PanelDialogTurnOut:
    proposal = turn.proposal or {}
    return PanelDialogTurnOut(
        id=turn.id,
        panel_id=turn.panel_id,
        instruction=turn.instruction,
        explanation=turn.explanation,
        status=turn.status,  # type: ignore[arg-type]
        prompt_before=(turn.before or {}).get("prompt"),
        prompt_after=str(proposal.get("prompt") or ""),
        changes=[DialogChangeOut.model_validate(c) for c in proposal.get("changes") or []],
        created_at=turn.created_at.replace(tzinfo=turn.created_at.tzinfo or UTC),
        applied_at=turn.applied_at.replace(tzinfo=turn.applied_at.tzinfo or UTC) if turn.applied_at else None,
    )


def _get_turn_or_404(session: Session, turn_id: int) -> PanelDialogTurn:
    turn = session.get(PanelDialogTurn, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Échange introuvable")
    return turn


def _require_proposed(turn: PanelDialogTurn) -> None:
    if turn.status != "proposed":
        state = "déjà appliquée" if turn.status == "applied" else "annulée"
        raise FieldError("turn", f"cette proposition est {state} : écris une nouvelle consigne")


@router.get("/panels/{panel_id}/dialog", response_model=list[PanelDialogTurnOut])
def list_dialog(panel_id: int, session: Session = Depends(get_session)) -> list[PanelDialogTurnOut]:
    """Historique des échanges avec l'IA sur la case, du plus ancien au plus récent."""
    panel = get_panel_or_404(session, panel_id)
    return [turn_out(t) for t in panel.dialog]


@router.post("/panels/{panel_id}/dialog", response_model=PanelDialogTurnOut, status_code=201)
def ask_dialog(
    panel_id: int, body: PanelDialogIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDialogTurnOut:
    """« Demander à l'IA pour cette case » : proposition (prompt, direction, références) à montrer avant
    d'appliquer. La case ne change pas ; une proposition précédente non appliquée est annulée."""
    panel = get_panel_or_404(session, panel_id)
    presets = _presets(ctx, panel)
    request = dialog_request(presets, session, panel, body.instruction, ctx.knowledge)
    before = {"prompt": panel.final_prompt}
    session.commit()  # aucune transaction ouverte pendant l'appel au LLM
    llm, llm_error = ctx.agents.llm_for(WRITER_AGENT, request.project_id)
    try:
        run = run_dialog_request(presets, llm, llm_error, request)
    except PromptDialogError as exc:
        raise HTTPException(
            status_code=502, detail=f"L'IA n'a pas pu proposer de changement : {exc}. La case n'a pas changé."
        ) from None
    panel = get_panel_or_404(session, panel_id)
    for old in session.scalars(
        select(PanelDialogTurn).where(PanelDialogTurn.panel_id == panel.id, PanelDialogTurn.status == "proposed")
    ):
        old.status = "cancelled"
    turn = PanelDialogTurn(
        panel_id=panel.id,
        instruction=body.instruction,
        explanation=run.proposal.explanation,
        proposal=run.proposal.as_json(),
        before=before,
        status="proposed",
    )
    session.add(turn)
    session.commit()
    return turn_out(turn)


@router.post("/panel-dialog/{turn_id}/apply", response_model=DialogApplyOut)
def apply_dialog(
    turn_id: int,
    body: DialogApplyIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> DialogApplyOut:
    """« Appliquer » (ou « Appliquer et générer » : une nouvelle version de cette case seulement)."""
    body = body or DialogApplyIn()
    turn = _get_turn_or_404(session, turn_id)
    _require_proposed(turn)
    panel = get_panel_or_404(session, turn.panel_id)
    if body.generate:
        _require_comfyui(ctx)
        _require_lock_available(ctx, panel)
    apply_dialog_proposal(panel, turn.proposal or {})
    turn.status = "applied"
    turn.applied_at = datetime.now(UTC)
    jobs = _enqueue(session, ctx, panel, count=1, extra_params={"dialog_turn": turn.id}) if body.generate else []
    session.commit()
    if jobs:
        ctx.generation.notify()
    return DialogApplyOut(turn=turn_out(turn), panel=panel_detail(session, ctx, panel), jobs=[job_out(j) for j in jobs])


@router.post("/panel-dialog/{turn_id}/cancel", response_model=PanelDialogTurnOut)
def cancel_dialog(turn_id: int, session: Session = Depends(get_session)) -> PanelDialogTurnOut:
    """« Annuler » : la case reste comme elle était."""
    turn = _get_turn_or_404(session, turn_id)
    _require_proposed(turn)
    turn.status = "cancelled"
    session.commit()
    return turn_out(turn)
