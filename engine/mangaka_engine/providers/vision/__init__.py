"""Fournisseurs de contrôle qualité visuel (score 0–100 + raisons).

Seul le mock existe pour l'instant ; DeepSeek (s'il accepte les images) ou
Qwen3-VL 4B via Ollama (chargé à la demande, keep_alive 0, jamais pendant une
génération ComfyUI) arriveront au jalon 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class VisionVerdict:
    score: int  # 0–100
    reasons: list[str] = field(default_factory=list)


class VisionProvider(Protocol):
    name: str

    def score_image(self, image: bytes, *, prompt: str, criteria: list[str] | None = None) -> VisionVerdict: ...


class MockVisionProvider:
    name = "mock"

    def __init__(self, score: int = 80) -> None:
        if not 0 <= score <= 100:
            raise ValueError("le score doit être compris entre 0 et 100")
        self._score = score

    def score_image(self, image: bytes, *, prompt: str, criteria: list[str] | None = None) -> VisionVerdict:
        if not image:
            return VisionVerdict(score=0, reasons=["image vide"])
        return VisionVerdict(score=self._score, reasons=["[mock] aucun défaut détecté"])


__all__ = ["MockVisionProvider", "VisionProvider", "VisionVerdict"]
