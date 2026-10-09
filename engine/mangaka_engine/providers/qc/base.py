"""Interfaces des couches « détecteurs » et « cohérence des personnages » du contrôle qualité."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class QCProviderError(Exception):
    """Erreur d'un fournisseur de QC, avec un message lisible (en français)."""


@dataclass(frozen=True)
class Box:
    """Boîte détectée, en pixels de l'image générée."""

    x1: int
    y1: int
    x2: int
    y2: int
    score: float
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "score": round(self.score, 3),
            "label": self.label,
        }


@dataclass
class Detections:
    width: int
    height: int
    faces: list[Box] = field(default_factory=list)
    hands: list[Box] = field(default_factory=list)
    text: list[Box] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "faces": [b.as_dict() for b in self.faces],
            "hands": [b.as_dict() for b in self.hands],
            "text": [b.as_dict() for b in self.text],
        }


class DetectorProvider(Protocol):
    name: str

    def detect(
        self,
        image: bytes,
        *,
        face: dict[str, Any] | None = None,
        hand: dict[str, Any] | None = None,
        text: dict[str, Any] | None = None,
    ) -> Detections:
        """Visages, mains et texte ; `face`/`hand`/`text` : options du preset passées au détecteur."""
        ...


class IdentityProvider(Protocol):
    name: str

    def compare(
        self, image: bytes, crops: list[Box], references: dict[str, list[bytes]], *, crop_scale: float
    ) -> dict[str, float]:
        """Similarité 0–1 entre chaque personnage (nom → images de référence) et la case.

        `crops` : boîtes (visages) autour desquelles chercher les personnages ; vide = image entière.
        """
        ...
