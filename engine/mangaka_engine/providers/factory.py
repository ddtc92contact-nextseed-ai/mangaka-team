"""Sélection des fournisseurs selon la configuration (.env / variables d'environnement).

| Variable            | Valeurs                                   | Défaut                                  |
|---------------------|-------------------------------------------|-----------------------------------------|
| LLM_PROVIDER        | deepseek, ollama*, claude*, mock          | mock                                    |
| VISION_PROVIDER     | ollama, mock (deepseek : pas d'images)    | mock                                    |
| COMFYUI_PROVIDER    | http, mock                                | mock                                    |
| QC_DETECTORS_PROVIDER | dghs, mock                              | mock                                    |
| QC_IDENTITY_PROVIDER  | dghs, mock                              | mock                                    |

`dghs` demande l'extra optionnel `engine[qc]` (dghs-imgutils) : sans lui, le fournisseur est
indisponible (« détecteurs non installés ») mais le moteur démarre.

Le mode réel s'active explicitement (cf. `.env.example`) : une DEEPSEEK_API_KEY
exportée dans le shell ne suffit pas à quitter le mode mock.

(*) prévus par la spec, pas encore implémentés : une erreur lisible est renvoyée.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings
from ..presets import PresetError, PresetRegistry
from .comfyui import ComfyUIClient, HttpComfyUIClient, MockComfyUIClient
from .llm import DeepSeekProvider, LLMError, LLMProvider, MockLLMProvider
from .qc import (
    CcipIdentityProvider,
    DetectorProvider,
    DghsDetectorProvider,
    IdentityProvider,
    MockDetectorProvider,
    MockIdentityProvider,
    QCProviderError,
)
from .vision import MockVisionProvider, OllamaVisionProvider, VisionProvider

LLM_CHOICES = ("deepseek", "ollama", "claude", "mock")
VISION_CHOICES = ("deepseek", "ollama", "mock")
COMFYUI_CHOICES = ("http", "mock")
QC_CHOICES = ("dghs", "mock")


class ProviderSelectionError(Exception):
    pass


def _normalize(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value or None


def _check(kind: str, name: str, choices: tuple[str, ...], implemented: tuple[str, ...]) -> None:
    if name not in choices:
        raise ProviderSelectionError(f"{kind} inconnu : « {name} » (choix : {', '.join(choices)})")
    if name not in implemented:
        raise ProviderSelectionError(f"{kind} « {name} » pas encore disponible (choix : {', '.join(implemented)})")


def resolve_llm_name(settings: Settings) -> str:
    return _normalize(settings.llm_provider) or "mock"


def build_llm(settings: Settings, presets: PresetRegistry) -> LLMProvider:
    name = resolve_llm_name(settings)
    _check("fournisseur LLM", name, LLM_CHOICES, ("deepseek", "mock"))
    if name == "mock":
        return MockLLMProvider(invalid_attempts=settings.mock_llm_invalid_attempts)
    try:
        cfg = presets.require_providers().deepseek
    except PresetError as exc:
        raise ProviderSelectionError(str(exc)) from exc
    key = settings.deepseek_api_key.get_secret_value().strip() if settings.deepseek_api_key else None
    try:
        return DeepSeekProvider(
            api_key=key,
            base_url=settings.deepseek_base_url or cfg.base_url,
            model=settings.deepseek_model or cfg.model,
            timeout_s=cfg.timeout_s,
            temperature=cfg.temperature,
        )
    except LLMError as exc:
        raise ProviderSelectionError(str(exc)) from exc


def build_vision(settings: Settings, presets: PresetRegistry | None = None) -> VisionProvider:
    name = _normalize(settings.vision_provider) or "mock"
    if name == "deepseek":
        raise ProviderSelectionError(
            "DeepSeek n'accepte pas d'images (supports_images: false) : utilise VISION_PROVIDER=ollama ou mock"
        )
    _check("fournisseur vision", name, VISION_CHOICES, ("ollama", "mock"))
    if name == "mock":
        return MockVisionProvider(
            score=settings.mock_vision_score, invalid_attempts=settings.mock_vision_invalid_attempts
        )
    cfg = presets.providers.ollama if presets is not None and presets.providers is not None else None
    if cfg is None:
        raise ProviderSelectionError("section « ollama » absente de presets/providers.yaml")
    return OllamaVisionProvider(
        base_url=cfg.base_url, model=cfg.vision_model, keep_alive=cfg.keep_alive, timeout_s=cfg.timeout_s
    )


def build_detectors(settings: Settings) -> DetectorProvider:
    name = _normalize(settings.qc_detectors_provider) or "mock"
    _check("détecteurs QC", name, QC_CHOICES, QC_CHOICES)
    if name == "mock":
        return MockDetectorProvider()
    try:
        return DghsDetectorProvider()
    except QCProviderError as exc:
        raise ProviderSelectionError(str(exc)) from exc


def build_identity(settings: Settings) -> IdentityProvider:
    name = _normalize(settings.qc_identity_provider) or "mock"
    _check("cohérence des personnages", name, QC_CHOICES, QC_CHOICES)
    if name == "mock":
        return MockIdentityProvider()
    try:
        return CcipIdentityProvider()
    except QCProviderError as exc:
        raise ProviderSelectionError(str(exc)) from exc


def build_comfyui(settings: Settings) -> ComfyUIClient:
    name = _normalize(settings.comfyui_provider) or "mock"
    _check("client ComfyUI", name, COMFYUI_CHOICES, COMFYUI_CHOICES)
    if name == "http":
        return HttpComfyUIClient(settings.comfyui_url, timeout_s=settings.comfyui_timeout_s)
    return MockComfyUIClient(seconds_per_image=settings.mock_comfyui_seconds)


@dataclass
class Providers:
    llm: LLMProvider | None
    vision: VisionProvider | None
    comfyui: ComfyUIClient | None
    errors: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    # Couches 1-2 du contrôle qualité (None : indisponible, raison dans `errors`).
    detectors: DetectorProvider | None = None
    identity: IdentityProvider | None = None


def build_providers(settings: Settings, presets: PresetRegistry) -> Providers:
    """Construit les fournisseurs ; une erreur de configuration n'empêche pas le démarrage."""
    out = Providers(llm=None, vision=None, comfyui=None)
    builders = {
        "llm": (lambda: build_llm(settings, presets), lambda: resolve_llm_name(settings)),
        "vision": (lambda: build_vision(settings, presets), lambda: _normalize(settings.vision_provider) or "mock"),
        "comfyui": (lambda: build_comfyui(settings), lambda: _normalize(settings.comfyui_provider) or "mock"),
        "detectors": (lambda: build_detectors(settings), lambda: _normalize(settings.qc_detectors_provider) or "mock"),
        "identity": (lambda: build_identity(settings), lambda: _normalize(settings.qc_identity_provider) or "mock"),
    }
    for kind, (build, name) in builders.items():
        out.names[kind] = name()
        try:
            setattr(out, kind, build())
        except ProviderSelectionError as exc:
            out.errors[kind] = str(exc)
    return out
