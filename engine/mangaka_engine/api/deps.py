"""Dépendances FastAPI : accès à l'état de l'application."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..pipeline.jobs import JobRunner
from ..presets import PresetRegistry
from ..providers.factory import Providers
from ..store.db import Database
from ..store.files import FileStore


@dataclass
class AppContext:
    settings: Settings
    presets: PresetRegistry
    providers: Providers
    db: Database
    files: FileStore
    jobs: JobRunner


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_session(request: Request) -> Iterator[Session]:
    yield from get_ctx(request).db.session()
