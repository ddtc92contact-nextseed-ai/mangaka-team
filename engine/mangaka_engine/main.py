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
from .api import characters, projects, system
from .api.deps import AppContext
from .api.errors import install_error_handlers
from .config import Settings, get_settings
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
    return AppContext(
        settings=settings,
        presets=presets,
        providers=providers,
        db=Database(settings.database_path),
        files=FileStore(settings.data_dir),
    )


def create_app(settings: Settings | None = None, providers: Providers | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.ctx.db.dispose()

    app = FastAPI(title="mangaka-team — moteur", version=__version__, lifespan=lifespan)
    app.state.ctx = build_context(settings, providers)
    install_error_handlers(app)
    app.include_router(system.router)
    app.include_router(projects.router)
    app.include_router(characters.router)
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
