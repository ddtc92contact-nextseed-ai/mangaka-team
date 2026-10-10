"""Dépendances FastAPI : accès à l'état de l'application."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from ..agents import AgentService
from ..config import Settings
from ..pipeline.comfy_loras import LoraCatalog
from ..pipeline.composition import ControlCatalog, unavailable_control
from ..pipeline.jobs import JobRunner
from ..pipeline.knowledge import KnowledgeBase
from ..pipeline.qc import QCExecutor
from ..pipeline.queue import SerialJobQueue
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
    generation: SerialJobQueue  # file ComfyUI : une génération à la fois (et les contrôles qualité)
    qc: QCExecutor
    agents: AgentService  # profils des agents (écran « L'équipe ») : presets effectifs par série
    knowledge: KnowledgeBase  # savoir-faire et bible injectés dans les agents
    lora_catalog: LoraCatalog = field(default_factory=LoraCatalog)  # LoRA vus par ComfyUI (cache court)
    # Verrouillage de composition (ControlNet) disponible dans ComfyUI ? (cache court)
    control_catalog: ControlCatalog = field(default_factory=ControlCatalog)

    def control_status(self, *, refresh: bool = False) -> dict[str, Any]:
        """Disponibilité du verrouillage de composition (nœuds, fichier du patch, prétraitements)."""
        client = self.providers.comfyui
        if client is None:
            return unavailable_control(
                self.providers.names.get("comfyui") or "?",
                self.providers.errors.get("comfyui") or "ComfyUI non configuré",
            )
        return self.control_catalog.get(client, self.presets, refresh=refresh)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_session(request: Request) -> Iterator[Session]:
    yield from get_ctx(request).db.session()
