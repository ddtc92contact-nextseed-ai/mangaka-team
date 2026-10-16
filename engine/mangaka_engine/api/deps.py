"""Dépendances FastAPI : accès à l'état de l'application."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from ..agents import AgentService
from ..config import Settings
from ..pipeline.comfy_library import ComfyLibrary
from ..pipeline.comfy_loras import LoraCatalog
from ..pipeline.composition import ControlCatalog, unavailable_control
from ..pipeline.jobs import JobRunner
from ..pipeline.knowledge import KnowledgeBase
from ..pipeline.qc import QCExecutor
from ..pipeline.queue import SerialJobQueue
from ..presets import PresetRegistry
from ..providers.factory import Providers
from ..providers.llm import DeepSeekModelCatalog
from ..store.comfy_folders import ComfyFolders
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
    # Dossiers de la série dans ComfyUI (rangement, renommage, nettoyage) ; désactivé sans COMFYUI_DIR valide.
    folders: ComfyFolders = field(default_factory=lambda: ComfyFolders(None, mock=True))
    # Bibliothèque lisible de la série dans ComfyUI (output/mangaka/<série>/) ; None : jamais écrite.
    library: ComfyLibrary | None = None
    lora_catalog: LoraCatalog = field(default_factory=LoraCatalog)  # LoRA vus par ComfyUI (cache court)
    # Verrouillage de composition (ControlNet) disponible dans ComfyUI ? (cache court)
    control_catalog: ControlCatalog = field(default_factory=ControlCatalog)
    deepseek_models: DeepSeekModelCatalog = field(default_factory=DeepSeekModelCatalog)  # GET /models (cache court)

    def control_status(self, *, refresh: bool = False) -> dict[str, Any]:
        """Disponibilité du verrouillage de composition (nœuds, fichier du patch, prétraitements)."""
        client = self.providers.comfyui
        if client is None:
            return unavailable_control(
                self.providers.names.get("comfyui") or "?",
                self.providers.errors.get("comfyui") or "ComfyUI non configuré",
            )
        return self.control_catalog.get(client, self.presets, refresh=refresh)

    def reload_presets(self) -> PresetRegistry:
        """« Recharger les flux » : relit presets/ sans redémarrer le moteur.

        Refusé (`PresetsBusy`) tant qu'un job de la file ComfyUI tourne : un flux ne change jamais sous une
        génération. Le registre est remplacé sur place (exécuteurs, bibliothèque, QC… gardent la même référence),
        puis ce qui en garde une copie est recalculé : presets effectifs des agents, réglages du savoir-faire,
        cache du verrouillage de composition. Les jobs en attente partiront avec les nouveaux flux."""
        running = self.generation.current_job_id
        if running is not None:
            raise PresetsBusy(running)
        self.presets.reload()
        self.agents.presets_reloaded()
        self.knowledge.settings = self.presets.knowledge
        self.control_catalog = ControlCatalog()
        return self.presets


class PresetsBusy(Exception):
    """Rechargement des presets refusé : un job de la file ComfyUI est en cours."""

    def __init__(self, job_id: int) -> None:
        super().__init__(job_id)
        self.job_id = job_id


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_session(request: Request) -> Iterator[Session]:
    yield from get_ctx(request).db.session()
