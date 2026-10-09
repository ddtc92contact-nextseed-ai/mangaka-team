"""Détecteurs anime ONNX et CCIP de deepghs (`dghs-imgutils`), sur CPU.

Dépendance **optionnelle** : `pip install -e "engine[qc]"`. Le module `imgutils` n'est importé
qu'au premier usage ; s'il manque, `require_imgutils()` lève une erreur lisible et le fournisseur
est marqué indisponible (le moteur démarre quand même). Les modèles sont téléchargés depuis
Hugging Face au premier appel puis mis en cache.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import threading
from typing import Any

from PIL import Image, UnidentifiedImageError

from .base import Box, Detections, QCProviderError

INSTALL_HINT = 'détecteurs non installés : pip install -e "engine[qc]" (voir README)'


def imgutils_installed() -> bool:
    return importlib.util.find_spec("imgutils") is not None


def require_imgutils() -> None:
    if not imgutils_installed():
        raise QCProviderError(INSTALL_HINT)


def _open(image: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(image))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise QCProviderError("image illisible") from exc
    return img.convert("RGB")


def _boxes(raw: Any, label: str) -> list[Box]:
    out: list[Box] = []
    for (x0, y0, x1, y1), _, score in raw:
        out.append(Box(int(x0), int(y0), int(x1), int(y1), float(score), label))
    return out


class DghsDetectorProvider:
    """Visages, mains et texte via `imgutils.detect` (YOLO / DBNet ONNX)."""

    name = "dghs"

    def __init__(self) -> None:
        require_imgutils()
        self._lock = threading.Lock()  # sessions ONNX partagées : un appel à la fois

    def detect(
        self,
        image: bytes,
        *,
        face: dict[str, Any] | None = None,
        hand: dict[str, Any] | None = None,
        text: dict[str, Any] | None = None,
    ) -> Detections:
        img = _open(image)
        try:
            detect = importlib.import_module("imgutils.detect")
            with self._lock:
                faces = detect.detect_faces(img, **(face or {}))
                hands = detect.detect_hands(img, **(hand or {}))
                texts = detect.detect_text(img, **(text or {}))
        except ImportError as exc:
            raise QCProviderError(INSTALL_HINT) from exc
        except Exception as exc:  # noqa: BLE001 — erreur ONNX / téléchargement : message lisible
            raise QCProviderError(f"détecteurs deepghs : {exc.__class__.__name__} : {exc}") from exc
        return Detections(
            width=img.width,
            height=img.height,
            faces=_boxes(faces, "face"),
            hands=_boxes(hands, "hand"),
            text=_boxes(texts, "text"),
        )


def crop_around(img: Image.Image, box: Box, scale: float) -> Image.Image:
    """Recadre autour d'une boîte agrandie `scale` fois (le buste autour d'un visage)."""
    cx, cy = (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2
    half_w = (box.x2 - box.x1) * scale / 2
    half_h = (box.y2 - box.y1) * scale / 2
    x1, y1 = max(0, int(cx - half_w)), max(0, int(cy - half_h))
    x2, y2 = min(img.width, int(cx + half_w)), min(img.height, int(cy + half_h))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return img
    return img.crop((x1, y1, x2, y2))


class CcipIdentityProvider:
    """Ressemblance personnage ↔ fiche via CCIP (`imgutils.metrics.ccip_*`).

    Similarité = 1 − différence CCIP ; pour chaque personnage, la meilleure correspondance parmi
    les recadrages (moyenne sur ses images de référence). Les traits des références sont gardés
    en cache (empreinte du fichier).
    """

    name = "dghs"

    def __init__(self) -> None:
        require_imgutils()
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}

    def _feature(self, ccip: Any, img: Image.Image, key: str | None = None) -> Any:
        if key is not None and key in self._cache:
            return self._cache[key]
        feat = ccip.ccip_extract_feature(img)
        if key is not None:
            if len(self._cache) > 512:
                self._cache.clear()
            self._cache[key] = feat
        return feat

    def compare(
        self, image: bytes, crops: list[Box], references: dict[str, list[bytes]], *, crop_scale: float
    ) -> dict[str, float]:
        img = _open(image)
        regions = [crop_around(img, b, crop_scale) for b in crops] or [img]
        try:
            ccip = importlib.import_module("imgutils.metrics")
            with self._lock:
                feats = [self._feature(ccip, r) for r in regions]
                out: dict[str, float] = {}
                for name, refs in references.items():
                    ref_feats = [
                        self._feature(ccip, _open(data), hashlib.sha256(data).hexdigest()) for data in refs if data
                    ]
                    if not ref_feats:
                        continue
                    best = 0.0
                    for f in feats:
                        diffs = [float(ccip.ccip_difference(f, r)) for r in ref_feats]
                        best = max(best, 1 - sum(diffs) / len(diffs))
                    out[name] = round(min(1.0, max(0.0, best)), 3)
        except ImportError as exc:
            raise QCProviderError(INSTALL_HINT) from exc
        except QCProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise QCProviderError(f"CCIP deepghs : {exc.__class__.__name__} : {exc}") from exc
        return out
