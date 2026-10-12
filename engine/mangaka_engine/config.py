"""Configuration du moteur, lue depuis l'environnement et le `.env` racine.

Sans `.env`, tout tourne en mode mock : aucun appel réseau, aucun GPU.
Les noms de modèles et de workflows ne vivent pas ici mais dans `presets/`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Fournisseurs : vide = choix automatique (voir providers/factory.py).
    llm_provider: str | None = None
    vision_provider: str | None = None
    comfyui_provider: str | None = None
    # Contrôle qualité : détecteurs (visages/mains/texte) et cohérence des personnages (CCIP).
    qc_detectors_provider: str | None = None
    qc_identity_provider: str | None = None
    # Savoir-faire : embeddings des passages (mock | ollama).
    embedding_provider: str | None = None
    # Packs de savoir-faire livrés (presets/knowledge_packs/) : importés ou mis à jour au démarrage.
    knowledge_packs: bool = True

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str | None = None

    # Mode mock : nombre de réponses invalides du LLM factice avant une réponse valide (test des relances).
    mock_llm_invalid_attempts: int = 0
    # Mode mock : score de la couche vision factice et nombre de réponses invalides avant une valide.
    mock_vision_score: int = 80
    mock_vision_invalid_attempts: int = 0

    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_timeout_s: float = 5.0  # par requête HTTP ; la durée max d'une génération est dans le preset
    comfyui_poll_s: float = 1.0  # sondage de /history (et lecture du websocket) pendant une génération
    # Mode mock : durée simulée d'une génération (progression factice étape par étape).
    mock_comfyui_seconds: float = 4.0
    # Dossier d'installation de ComfyUI (celui du lanceur) : rangement et nettoyage de `output/mangaka/` et
    # `input/mangaka/` (store/comfy_folders.py). Absent : `~/ComfyUI` avec le vrai ComfyUI, aucun en mode
    # mock ; vide ou introuvable : rien n'est supprimé hors de data/ (avertissement dans l'interface).
    comfyui_dir: str | None = None
    # Variantes non gardées de « Créer des références » conservées au plus par fiche et par type de fiche ; les
    # plus anciennes sont effacées après chaque génération (les références gardées restent toujours).
    reference_variants_kept: int = Field(default=4, ge=1)

    mangaka_data_dir: Path = REPO_ROOT / "data"
    mangaka_presets_dir: Path = REPO_ROOT / "presets"
    max_upload_mb: int = 20

    @field_validator("mangaka_data_dir", "mangaka_presets_dir")
    @classmethod
    def _relative_to_repo(cls, value: Path) -> Path:
        # Un chemin relatif dans .env s'entend depuis la racine du dépôt.
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @property
    def data_dir(self) -> Path:
        return self.mangaka_data_dir

    @property
    def presets_dir(self) -> Path:
        return self.mangaka_presets_dir

    @property
    def database_path(self) -> Path:
        return self.data_dir / "mangaka.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
