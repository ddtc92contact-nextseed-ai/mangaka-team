"""Suivi des jobs : état courant et flux d'événements temps réel (SSE)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..pipeline.jobs import TERMINAL
from ..store.models import Job
from .deps import AppContext, get_ctx, get_session
from .schemas import JobOut

router = APIRouter(tags=["jobs"])

POLL_S = 0.25
HEARTBEAT_S = 15.0


def job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        step=job.step,
        status=job.status.value,
        progress=job.progress,
        message=job.message,
        error=job.error,
        project_id=job.project_id,
        chapter_id=job.chapter_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=job.duration_ms,
    )


def _get_job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: Session = Depends(get_session)) -> JobOut:
    return job_out(_get_job(session, job_id))


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: int, request: Request, ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    """Flux SSE : un événement `job` (JSON de JobOut) à chaque changement, fermé quand le job se termine.

    À la (re)connexion, l'état courant est renvoyé immédiatement : un client qui perd la
    connexion ne rate rien.
    """
    with ctx.db.session_scope() as session:
        _get_job(session, job_id)

    async def stream():  # type: ignore[no-untyped-def]
        last = ""
        idle = 0.0
        yield "retry: 2000\n\n"
        while True:
            with ctx.db.session_scope() as session:
                job = session.get(Job, job_id)
                if job is None:
                    yield 'event: gone\ndata: {"detail": "Job introuvable"}\n\n'
                    return
                payload = job_out(job).model_dump_json()
                done = job.status in TERMINAL
            if payload != last:
                yield f"event: job\ndata: {payload}\n\n"
                last = payload
                idle = 0.0
            elif idle >= HEARTBEAT_S:
                yield ": ping\n\n"
                idle = 0.0
            if done or await request.is_disconnected():
                return
            await asyncio.sleep(POLL_S)
            idle += POLL_S

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
