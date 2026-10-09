"""Application FastAPI du moteur mangaka-team.

Lancement : `npm run dev` à la racine, ou
`uvicorn mangaka_engine.main:app --port 8765` depuis `engine/`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .api import chapters, characters, generation, jobs, lettering, projects, system
from .api.deps import AppContext
from .api.errors import install_error_handlers
from .config import Settings, get_settings
from .pipeline.generation import STEP as GENERATION_STEP
from .pipeline.generation import GenerationExecutor, describe_error, recover_states
from .pipeline.jobs import JobRunner
from .pipeline.queue import SerialJobQueue
from .presets import PresetRegistry
from .providers.factory import Providers, build_providers
from .store.db import Database
from .store.files import FileStore

log = logging.getLogger("mangaka_engine")


def build_context(settings: Settings, providers: Providers | None = None) -> AppContext:
    presets = PresetRegistry.load(settings.presets_dir)
    for issue in presets.issues:
        log.warning("preset ignoré — %s : %s", issue.file, issue.message)
    providers = providers or build_providers(settings, presets)
    for kind, error in providers.errors.items():
        log.warning("fournisseur %s indisponible : %s", kind, error)
    db = Database(settings.database_path)
    runner = JobRunner(db)
    interrupted = runner.recover()
    if interrupted:
        log.warning("%s job(s) interrompu(s) par l'arrêt précédent marqué(s) en échec", interrupted)
    recover_states(db)
    files = FileStore(settings.data_dir)
    executor = GenerationExecutor(
        db,
        presets,
        files,
        providers.comfyui,
        comfyui_error=providers.errors.get("comfyui"),
        poll_s=settings.comfyui_poll_s,
    )
    queue = SerialJobQueue(
        db,
        step=GENERATION_STEP,
        execute=executor,
        describe_error=describe_error,
        interrupt=executor.interrupt,
        after=executor.after,
    )
    queue.start()
    return AppContext(
        settings=settings,
        presets=presets,
        providers=providers,
        db=db,
        files=files,
        jobs=runner,
        generation=queue,
    )


def create_app(settings: Settings | None = None, providers: Providers | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.ctx.generation.shutdown()
        app.state.ctx.jobs.shutdown()
        app.state.ctx.db.dispose()

    app = FastAPI(title="mangaka-team — moteur", version=__version__, lifespan=lifespan)
    app.state.ctx = build_context(settings, providers)
    install_error_handlers(app)
    app.include_router(system.router)
    app.include_router(projects.router)
    app.include_router(characters.router)
    app.include_router(chapters.router)
    app.include_router(jobs.router)
    app.include_router(generation.router)
    app.include_router(lettering.router)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn mangaka_engine.main:app` : l'app n'est construite qu'à la demande,
    # pour que l'import du module (tests) ne crée pas de base dans data/.
    if name == "app":
        logging.basicConfig(level=logging.INFO)
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
