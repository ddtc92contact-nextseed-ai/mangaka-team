"""Fournisseurs de la couche « vision » du contrôle qualité : « la case colle-t-elle à sa description ? ».

Un fournisseur renvoie le texte brut du modèle ; la validation (JSON Pydantic, nouvel essai,
erreur lisible) est faite par `pipeline/qc.py`, la même pour tous.

- `mock` : réponse JSON fixe, éventuellement précédée de réponses invalides (test des relances) ;
- `ollama` : Qwen3-VL 4B via l'API Ollama locale, chargé à la demande (`keep_alive: 0` : le modèle
  est déchargé aussitôt pour rendre la mémoire à ComfyUI). Le QC ne l'appelle jamais pendant une
  génération ComfyUI.

DeepSeek n'accepte pas d'images (`supports_images: false` dans presets/providers.yaml).
"""

from __future__ import annotations

import base64
import json
import threading
from typing import Any, Protocol

import httpx


class VisionError(Exception):
    """Erreur d'un fournisseur vision, avec un message lisible."""


class VisionUnavailableError(VisionError):
    pass


class VisionResponseError(VisionError):
    """Réponse du modèle invalide (après les nouveaux essais)."""


class VisionProvider(Protocol):
    name: str

    def ask(self, image: bytes, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        """Envoie l'image et la consigne ; renvoie la réponse brute (JSON attendu)."""
        ...


class MockVisionProvider:
    name = "mock"

    def __init__(self, score: int = 80, invalid_attempts: int = 0) -> None:
        if not 0 <= score <= 100:
            raise ValueError("le score doit être compris entre 0 et 100")
        self._score = score
        self._invalid_left = invalid_attempts
        self._lock = threading.Lock()
        self.calls = 0

    def ask(self, image: bytes, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        with self._lock:
            self.calls += 1
            if self._invalid_left > 0:
                self._invalid_left -= 1
                return "Je pense que la case est plutôt réussie."  # pas du JSON
        if not image:
            return json.dumps({"score": 0, "raisons": ["image vide"]})
        return json.dumps({"score": self._score, "raisons": ["[mock] la case correspond à sa description"]})


class OllamaVisionProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        keep_alive: int | str = 0,
        num_ctx: int | None = None,
        timeout_s: float = 120,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 5)),
            transport=transport,
        )

    def ask(self, image: bytes, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(image).decode()]}],
            "stream": False,
            "keep_alive": self.keep_alive,
            "format": schema or "json",
            "options": {"temperature": 0},
        }
        if self.num_ctx is not None:
            payload["options"]["num_ctx"] = self.num_ctx
        try:
            resp = self._client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise VisionUnavailableError(f"Ollama n'a pas répondu à temps ({self.model})") from exc
        except httpx.HTTPError as exc:
            raise VisionUnavailableError(
                f"Ollama injoignable sur {self.base_url} : lance « ollama serve » (ou VISION_PROVIDER=mock)"
            ) from exc
        if resp.status_code == 404:
            raise VisionUnavailableError(f"modèle {self.model} absent d'Ollama : lance « ollama pull {self.model} »")
        if resp.status_code >= 400:
            detail = resp.text[:200]
            raise VisionError(f"Ollama a répondu {resp.status_code} : {detail}")
        try:
            data = resp.json()
            return str(data["message"]["content"])
        except (ValueError, KeyError, TypeError) as exc:
            raise VisionResponseError("réponse d'Ollama illisible") from exc


__all__ = [
    "MockVisionProvider",
    "OllamaVisionProvider",
    "VisionError",
    "VisionProvider",
    "VisionResponseError",
    "VisionUnavailableError",
]
