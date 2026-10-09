"""File d'attente sérielle : un seul job à la fois, dans l'ordre d'arrivée (FIFO).

Sert à la génération ComfyUI (une seule génération à la fois, spec §1), séparée du pool de
threads des étapes LLM. La base fait foi : les jobs `pending` de l'étape sont pris par id
croissant ; le worker ne garde en mémoire que le job en cours et son signal d'annulation.

D'autres étapes peuvent partager le même worker (`add_step`) : le contrôle qualité y passe, ce
qui garantit que sa couche vision (Ollama) ne tourne jamais pendant une génération ComfyUI.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select, update

from ..store.db import Database
from ..store.models import Job, JobStatus, utcnow
from .jobs import TERMINAL, JobReporter, finish_job

log = logging.getLogger("mangaka_engine")

# (job_id, reporter, signal d'annulation) → message final
Executor = Callable[[int, JobReporter, threading.Event], str | None]
# Exception → message lisible (None : erreur interne inattendue)
DescribeError = Callable[[Exception], str | None]


class CancelResult(enum.StrEnum):
    cancelled = "cancelled"  # job en attente : retiré de la file
    cancelling = "cancelling"  # job en cours : interruption demandée
    finished = "finished"  # déjà terminé : rien à faire
    not_found = "not_found"


@dataclass
class _Current:
    job_id: int
    cancel: threading.Event
    step: str = ""


@dataclass
class QueueStep:
    """Une étape exécutée par la file : exécution, message d'erreur, interruption, mise à jour des états."""

    execute: Executor
    describe_error: DescribeError = lambda exc: None
    interrupt: Callable[[int], None] | None = None
    after: Callable[[int], None] | None = None


class SerialJobQueue:
    def __init__(
        self,
        db: Database,
        *,
        step: str,
        execute: Executor,
        describe_error: DescribeError = lambda exc: None,
        interrupt: Callable[[int], None] | None = None,
        after: Callable[[int], None] | None = None,
        idle_poll_s: float = 1.0,
    ) -> None:
        self._db = db
        self.step = step  # étape principale (génération)
        self._steps: dict[str, QueueStep] = {
            step: QueueStep(execute=execute, describe_error=describe_error, interrupt=interrupt, after=after)
        }
        self._idle_poll_s = idle_poll_s
        self._lock = threading.Lock()
        self._wake = threading.Condition()
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._current: _Current | None = None
        self._thread: threading.Thread | None = None

    def add_step(self, step: str, spec: QueueStep) -> None:
        """Fait passer une autre étape par le même worker (avant `start`)."""
        self._steps[step] = spec

    def handles(self, step: str) -> bool:
        return step in self._steps

    @property
    def steps(self) -> tuple[str, ...]:
        return tuple(self._steps)

    # --- cycle de vie -------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name=f"queue-{self.step}", daemon=True)
            self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        current = self._current
        if current is not None:
            current.cancel.set()
        self.notify()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def notify(self) -> None:
        """Signale de nouveaux jobs en attente."""
        self._idle.clear()
        with self._wake:
            self._wake.notify_all()

    @property
    def current_job_id(self) -> int | None:
        current = self._current
        return current.job_id if current else None

    @property
    def current_step(self) -> str | None:
        current = self._current
        return current.step if current else None

    def wait_idle(self, timeout: float = 10) -> bool:
        """Attend que la file soit vide et le worker au repos (tests)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._idle.wait(timeout=0.05) and self._current is None and not self._pending_ids(limit=1):
                return True
        return False

    # --- annulation ----------------------------------------------------------
    def cancel(self, job_id: int) -> CancelResult:
        with self._lock:
            with self._db.session_scope() as session:
                job = session.get(Job, job_id)
                if job is None or job.step not in self._steps:
                    return CancelResult.not_found
                status, step = job.status, job.step
                if status == JobStatus.pending:
                    session.execute(
                        update(Job)
                        .where(Job.id == job_id, Job.status == JobStatus.pending)
                        .values(status=JobStatus.cancelled, message="Annulé", finished_at=utcnow())
                    )
                    session.commit()
            if status in TERMINAL:
                return CancelResult.finished
            current = self._current
            if status == JobStatus.running and (current is None or current.job_id != job_id):
                # Job orphelin (ne devrait pas arriver : recover() au démarrage) : on le clôt.
                with self._db.session_scope() as session:
                    session.execute(
                        update(Job)
                        .where(Job.id == job_id, Job.status == JobStatus.running)
                        .values(status=JobStatus.cancelled, message="Annulé", finished_at=utcnow())
                    )
                    session.commit()
                status = JobStatus.pending  # traité comme un retrait de la file
        if status == JobStatus.pending:
            self._run_after(job_id, step)
            return CancelResult.cancelled
        assert current is not None
        current.cancel.set()
        interrupt = self._steps[step].interrupt
        if interrupt is not None:
            try:
                interrupt(job_id)
            except Exception as exc:  # noqa: BLE001 — l'annulation reste demandée côté moteur
                log.warning("interruption du job %s : %s", job_id, exc)
        return CancelResult.cancelling

    # --- worker ---------------------------------------------------------------
    def _pending_ids(self, limit: int | None = None) -> list[int]:
        with self._db.session_scope() as session:
            q = select(Job.id).where(Job.step.in_(list(self._steps)), Job.status == JobStatus.pending).order_by(Job.id)
            if limit is not None:
                q = q.limit(limit)
            return list(session.scalars(q))

    def _claim_next(self) -> _Current | None:
        with self._lock:
            for job_id in self._pending_ids(limit=5):
                with self._db.session_scope() as session:
                    res = session.execute(
                        update(Job)
                        .where(Job.id == job_id, Job.status == JobStatus.pending)
                        .values(status=JobStatus.running, started_at=utcnow(), progress=0, message="Démarrage…")
                    )
                    session.commit()
                    step = session.scalar(select(Job.step).where(Job.id == job_id)) or self.step
                if res.rowcount:  # type: ignore[attr-defined]
                    self._current = _Current(job_id, threading.Event(), step)
                    return self._current
        return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                current = self._claim_next()
            except Exception:  # noqa: BLE001 — base momentanément indisponible : on réessaie
                log.exception("file %s : lecture des jobs en attente impossible", self.step)
                current = None
            if current is None:
                self._idle.set()
                with self._wake:
                    self._wake.wait(timeout=self._idle_poll_s)
                continue
            self._idle.clear()
            try:
                self._run(current)
            finally:
                with self._lock:
                    self._current = None
                self._run_after(current.job_id, current.step)

    def _run(self, current: _Current) -> None:
        job_id = current.job_id
        spec = self._steps.get(current.step) or self._steps[self.step]
        reporter = JobReporter(self._db, job_id)
        t0 = time.monotonic()
        try:
            message = spec.execute(job_id, reporter, current.cancel)
        except Exception as exc:  # noqa: BLE001 — un job ne doit jamais rester « en cours »
            if current.cancel.is_set():
                finish_job(reporter, t0, JobStatus.cancelled, message="Annulé")
                return
            described = self._safe_describe(spec, exc)
            if described is None:
                log.exception("job %s : erreur interne", job_id, exc_info=exc)
                described = f"Erreur interne du moteur ({exc.__class__.__name__})"
            finish_job(reporter, t0, JobStatus.failed, error=described)
        else:
            finish_job(reporter, t0, JobStatus.succeeded, message=message or "Terminé")

    def _safe_describe(self, spec: QueueStep, exc: Exception) -> str | None:
        try:
            return spec.describe_error(exc)
        except Exception:  # noqa: BLE001
            return None

    def _run_after(self, job_id: int, step: str) -> None:
        spec = self._steps.get(step)
        if spec is None or spec.after is None:
            return
        try:
            spec.after(job_id)
        except Exception:  # noqa: BLE001
            log.exception("job %s : mise à jour des états impossible", job_id)
