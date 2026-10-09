"""Fournisseurs de QC factices : résultats déterministes tirés de l'empreinte de l'image.

Une même image donne toujours le même résultat ; des images différentes (autre seed) donnent
des résultats variés (visages manquants, texte parasite, mains douteuses…) pour tester l'atelier
sans GPU ni modèle.
"""

from __future__ import annotations

import hashlib
import io
import random
from typing import Any

from PIL import Image, UnidentifiedImageError

from .base import Box, Detections, QCProviderError


def _rng(*parts: bytes | str) -> random.Random:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode() if isinstance(p, str) else p)
    return random.Random(int.from_bytes(h.digest()[:8], "big"))


def _size(image: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(image)) as img:
            return img.size
    except (UnidentifiedImageError, OSError) as exc:
        raise QCProviderError("image illisible") from exc


def _box(rng: random.Random, w: int, h: int, rel: float, score: float, label: str) -> Box:
    bw, bh = max(4, int(w * rel)), max(4, int(h * rel))
    x1 = rng.randint(0, max(0, w - bw))
    y1 = rng.randint(0, max(0, h - bh))
    return Box(x1, y1, x1 + bw, y1 + bh, score, label)


class MockDetectorProvider:
    name = "mock"

    def detect(
        self,
        image: bytes,
        *,
        face: dict[str, Any] | None = None,
        hand: dict[str, Any] | None = None,
        text: dict[str, Any] | None = None,
    ) -> Detections:
        w, h = _size(image)
        rng = _rng(b"detect", image)
        out = Detections(width=w, height=h)
        n_faces = rng.choices([0, 1, 2, 3], weights=[2, 5, 3, 1])[0]
        out.faces = [_box(rng, w, h, rng.uniform(0.12, 0.25), rng.uniform(0.55, 0.95), "face") for _ in range(n_faces)]
        n_hands = rng.choices([0, 1, 2], weights=[3, 4, 3])[0]
        out.hands = [_box(rng, w, h, rng.uniform(0.06, 0.12), rng.uniform(0.35, 0.9), "hand") for _ in range(n_hands)]
        if rng.random() < 0.15:
            out.text = [_box(rng, w, h, rng.uniform(0.1, 0.2), rng.uniform(0.5, 0.9), "text")]
        return out


class MockIdentityProvider:
    name = "mock"

    def compare(
        self, image: bytes, crops: list[Box], references: dict[str, list[bytes]], *, crop_scale: float
    ) -> dict[str, float]:
        _size(image)
        return {name: round(_rng(b"identity", image, name).uniform(0.6, 0.98), 3) for name in references}
