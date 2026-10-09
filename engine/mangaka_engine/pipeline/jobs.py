"""Exécution des jobs en arrière-plan, état et progression persistés dans la table `jobs`.

Les étapes LLM tournent en parallèle dans un pool de threads ; l'interface suit un job via
`GET /jobs/{id}/events` (SSE), qui relit la base : aucun état n'est gardé en mémoire seulement.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import update

from ..presets import PresetError
from ..providers.llm import LLMError
from ..store.db import Database
from ..store.models import Job, JobStatus, utcnow
from .art_direction import ArtDirectionError
from .layout import LayoutError
from .lettering import LetteringError
from .script import ScriptError

log = logging.getLogger("mangaka_engine")

TERMINAL = (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled)
EXPECTED_ERRORS = (ScriptError, ArtDirectionError, LLMError, PresetError, LayoutError, LetteringError)


class JobReporter:
    def __init__(self, db: Database, job_id: int) -> None:
        self._db = db
        self.job_id = job_id

    def __call__(self, progress: int, message: str) -> None:
        self._update(progress=max(0, min(100, progress)), message=message)

    def _update(self, **values: object) -> None:
        with self._db.session_scope() as session:
            session.execute(update(Job).where(Job.id == self.job_id).values(**values))
            session.commit()


JobFn = Callable[[JobReporter], str | None]  # renvoie le message final


class JobRunner:
    def __init__(self, db: Database, max_workers: int = 4) -> None:
        self._db = db
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._futures: dict[int, Future[None]] = {}

    def recover(self) -> int:
        """Au démarrage : un job resté « en cours » a été interrompu par l'arrêt du moteur."""
        with self._db.session_scope() as session:
            res = session.execute(
                update(Job)
                .where(Job.status.in_([JobStatus.pending, JobStatus.running]))
                .values(status=JobStatus.failed, error="Interrompu par un redémarrage du moteur", finished_at=utcnow())
            )
            session.commit()
            return res.rowcount or 0  # type: ignore[attr-defined]

    def submit(self, job_id: int, fn: JobFn) -> Future[None]:
        future = self._pool.submit(self._run, job_id, fn)
        self._futures[job_id] = future
        return future

    def wait(self, job_id: int, timeout: float = 10) -> None:
        future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _run(self, job_id: int, fn: JobFn) -> None:
        reporter = JobReporter(self._db, job_id)
        started = utcnow()
        t0 = time.monotonic()
        reporter._update(status=JobStatus.running, started_at=started, progress=0, message="Démarrage…")
        try:
            message = fn(reporter)
        except EXPECTED_ERRORS as exc:
            finish_job(reporter, t0, JobStatus.failed, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — un job ne doit jamais rester « en cours »
            log.exception("job %s : erreur interne", job_id, exc_info=exc)
            finish_job(reporter, t0, JobStatus.failed, error=f"Erreur interne du moteur ({exc.__class__.__name__})")
        else:
            finish_job(reporter, t0, JobStatus.succeeded, message=message or "Terminé")

    def cancel(self, job_id: int) -> bool:
        """Annule un job LLM pas encore démarré ; False s'il tourne déjà (non interruptible)."""
        future = self._futures.get(job_id)
        if future is None or not future.cancel():
            return False
        with self._db.session_scope() as session:
            res = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == JobStatus.pending)
                .values(status=JobStatus.cancelled, message="Annulé", finished_at=utcnow())
            )
            session.commit()
            return bool(res.rowcount)  # type: ignore[attr-defined]


def finish_job(
    reporter: JobReporter, t0: float, status: JobStatus, *, error: str | None = None, message: str | None = None
) -> None:
    finished: datetime = utcnow()
    values: dict[str, object] = {
        "status": status,
        "finished_at": finished,
        "duration_ms": int((time.monotonic() - t0) * 1000),
        "error": error,
    }
    if status == JobStatus.succeeded:
        values["progress"] = 100
    if message is not None:
        values["message"] = message
    elif error is not None:
        values["message"] = "Échec"
    reporter._update(**values)
