"""Garde d'étapes : état des étapes vitales d'un chapitre, refus des actions, « Passer outre » tracé."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..pipeline import stage_gate as sg
from ..pipeline.app_settings import author_or_default
from ..pipeline.journal import record_event
from ..store.models import Chapter, Page
from .deps import get_session
from .errors import FieldError
from .schemas import ChapterStagesOut, StageDecisionOut, StageName, StageOut, StageOverrideIn

router = APIRouter(tags=["garde d'étapes"])


def get_chapter_or_404(session: Session, chapter_id: int) -> Chapter:
    # Pas d'import de .chapters : chapters.py importe `gate` d'ici.
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable")
    return chapter


def gate(
    session: Session, chapter: Chapter, action: str, *, page: Page | None = None, only: Iterable[str] | None = None
) -> None:
    """Refuse l'action (422, champ `stage.<étape>`) si une étape qu'elle exige n'est ni réglée ni forcée."""
    try:
        sg.require(session, chapter, action, page=page, only=only)
    except sg.StageBlocked as exc:
        raise FieldError(f"stage.{exc.state.key}", exc.message) from None


def _decision_out(d: sg.Decision | None) -> StageDecisionOut | None:
    if d is None:
        return None
    return StageDecisionOut(
        decision=d.decision, author=d.author, note=d.note, at=d.at.replace(tzinfo=d.at.tzinfo or UTC)
    )  # type: ignore[arg-type]


def stages_out(session: Session, chapter: Chapter) -> ChapterStagesOut:
    states = sg.chapter_stages(session, chapter)
    blocks = sg.blocked_actions(states)
    return ChapterStagesOut(
        chapter_id=chapter.id,
        project_id=chapter.project_id,
        stages=[
            StageOut(
                key=s.key,  # type: ignore[arg-type]
                label=s.stage.label,
                complete=s.complete,
                forced=s.forced,
                passed=s.passed,
                total=s.total,
                faults=s.faults,
                summary=s.summary(),
                examples=s.examples,
                fix=s.stage.fix,
                screen=s.stage.screen,
                blocks=blocks.get(s.key, []),
                decision=_decision_out(s.decision),
            )
            for s in states
        ],
    )


def _state(session: Session, chapter: Chapter, stage: str) -> sg.StageState:
    if stage not in sg.STAGES:
        raise HTTPException(status_code=404, detail="Étape inconnue")
    return sg.chapter_stages(session, chapter, stages=[stage])[0]


@router.get("/chapters/{chapter_id}/stages", response_model=ChapterStagesOut)
def get_stages(chapter_id: int, session: Session = Depends(get_session)) -> ChapterStagesOut:
    """Étapes vitales du chapitre : cochées / en attente, compteurs, actions qu'elles bloquent, décision."""
    return stages_out(session, get_chapter_or_404(session, chapter_id))


@router.post("/chapters/{chapter_id}/stages/{stage}/override", response_model=ChapterStagesOut)
def override_stage(
    chapter_id: int,
    stage: StageName,
    body: StageOverrideIn | None = None,
    session: Session = Depends(get_session),
) -> ChapterStagesOut:
    """« Passer outre » cette seule étape : elle ne bloque plus le chapitre. La décision (étape, chapitre, date,
    auteur, compte laissé passer) est enregistrée et notée dans le journal de traçabilité."""
    body = body or StageOverrideIn()
    chapter = get_chapter_or_404(session, chapter_id)
    state = _state(session, chapter, stage)
    if state.forced:
        raise FieldError("stage", f"{state.stage.label} : étape déjà forcée")
    if state.complete:
        raise FieldError("stage", f"{state.stage.label} : étape déjà réglée, rien à forcer")
    author = author_or_default(session, body.author)  # sinon « Ton nom » des Réglages
    sg.record_decision(session, chapter, state, "forced", author=author, note=body.note)
    who = f" par {author}" if author else ""
    record_event(
        session,
        verdict="validated",
        action="stage_override",
        note=f"Chapitre {chapter.number} · {state.stage.label} forcée{who} ({state.summary()})"
        + (f" — {body.note}" if body.note else ""),
    )
    session.commit()
    return stages_out(session, chapter)


@router.delete("/chapters/{chapter_id}/stages/{stage}/override", response_model=ChapterStagesOut)
def revoke_override(
    chapter_id: int,
    stage: StageName,
    body: StageOverrideIn | None = None,
    session: Session = Depends(get_session),
) -> ChapterStagesOut:
    """Lève le « Passer outre » : l'étape bloque de nouveau tant qu'elle n'est pas réglée."""
    chapter = get_chapter_or_404(session, chapter_id)
    state = _state(session, chapter, stage)
    if not state.forced:
        raise FieldError("stage", f"{state.stage.label} : aucun passer-outre à lever")
    sg.record_decision(session, chapter, state, "revoked", author=body.author if body else "")
    session.commit()
    return stages_out(session, chapter)
