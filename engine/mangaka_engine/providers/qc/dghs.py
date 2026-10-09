"""Détecteurs anime ONNX et CCIP de deepghs (`dghs-imgutils`), sur CPU.

Dépendance **optionnelle** : `pip install -e "engine[qc]"`. Le module `imgutils` n'est importé
qu'au premier usage ; s'il manque, `require_imgutils()` lève une erreur lisible et le fournisseur
est marqué indisponible (le moteur démarre quand même). Les modèles sont téléchargés depuis
Hugging Face au premier appel puis mis en cache.

Les détecteurs tournent sur **CPU** (le GPU reste à ComfyUI) : `ONNX_MODE=cpu` est posé avant
l'import d'imgutils, et une erreur de chargement CUDA/cuDNN (onnxruntime-gpu installé sans cuDNN)
bascule sur `CPUExecutionProvider` avec un avertissement. Les modèles publiés par deepghs et les
options acceptées sont listés ici (`DETECTOR_MODELS`) : `presets/qc.yaml` est vérifié au chargement
avec `check_detector_options`, une mise à jour d'imgutils se corrige à cet endroit seulement.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import logging
import os
import threading
from typing import Any

from PIL import Image, UnidentifiedImageError

from .base import Box, Detections, QCProviderError

log = logging.getLogger(__name__)

INSTALL_HINT = 'détecteurs non installés : pip install -e "engine[qc]" (voir README)'

# Modèles publiés par deepghs pour dghs-imgutils 0.19 (dépôts Hugging Face deepghs/anime_face_detection,
# deepghs/anime_hand_detection, deepghs/text_detection). Visages et mains : `{prefix}_{version}_{level}`.
DETECTOR_MODELS: dict[str, dict[str, Any]] = {
    "face": {
        "prefix": "face_detect",
        "default_version": "v1.4",
        "models": {
            "v0": ("n", "s"),
            "v1": ("n", "s"),
            "v1.1": ("n", "s"),
            "v1.2": ("s",),
            "v1.3": ("n", "s"),
            "v1.4": ("n", "s"),
        },
        "options": ("level", "version", "conf_threshold", "iou_threshold"),
    },
    "hand": {
        "prefix": "hand_detect",
        "default_version": "v1.0",
        "models": {
            "v0.1": ("n", "s"),
            **{f"v0.{i}": ("s",) for i in range(2, 9)},
            "v1.0": ("n", "s"),
        },
        "options": ("level", "version", "conf_threshold", "iou_threshold"),
    },
    "text": {
        "models": (
            "dbnet_resnet18_fpnc_1200e_icdar2015",
            "dbnet_resnet18_fpnc_1200e_totaltext",
            "dbnet_resnet50-dcnv2_fpnc_1200e_icdar2015",
            "dbnet_resnet50-oclip_fpnc_1200e_icdar2015",
            "dbnetpp_resnet50-dcnv2_fpnc_1200e_icdar2015",
            "dbnetpp_resnet50-oclip_fpnc_1200e_icdar2015",
            "dbnetpp_resnet50_fpnc_1200e_icdar2015",
        ),
        "options": ("model", "threshold", "max_area_size"),
    },
}


def check_detector_options(detector: str, options: dict[str, Any]) -> list[str]:
    """Problèmes des `options` d'un détecteur (clé relative à `options`), vide si tout est connu."""
    spec = DETECTOR_MODELS[detector]
    problems = [
        f"{key} : option inconnue — options permises : {', '.join(spec['options'])}"
        for key in options
        if key not in spec["options"]
    ]
    if detector == "text":
        model = options.get("model")
        if model is not None and model not in spec["models"]:
            problems.append(
                f"model : « {model} » non publié par deepghs — valeurs permises : {', '.join(spec['models'])}"
            )
        return problems
    version = str(options.get("version", spec["default_version"]))
    levels = spec["models"].get(version)
    if levels is None:
        problems.append(
            f"version : « {version} » non publiée par deepghs — valeurs permises : {', '.join(spec['models'])}"
        )
    elif "level" in options and str(options["level"]) not in levels:
        problems.append(
            f"level : « {options['level']} » inconnu ({spec['prefix']}_{version}_{options['level']} non publié par "
            f"deepghs) — valeurs permises : {', '.join(levels)}"
        )
    return problems


def _is_gpu_load_error(exc: Exception) -> bool:
    text = f"{exc.__class__.__name__} {exc}".lower()
    return any(k in text for k in ("cuda", "cudnn", "cublas", "tensorrt"))


def _call_onnx(fn: Any) -> Any:
    """Appel imgutils ; erreur de chargement CUDA/cuDNN → avertissement et nouvel essai sur CPU."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if not _is_gpu_load_error(exc) or os.environ.get("ONNX_MODE", "").lower() == "cpu":
            raise
        log.warning("onnxruntime : échec du fournisseur GPU (%s), repli sur CPUExecutionProvider", exc)
        os.environ["ONNX_MODE"] = "cpu"
        return fn()


def imgutils_installed() -> bool:
    return importlib.util.find_spec("imgutils") is not None


def require_imgutils() -> None:
    if not imgutils_installed():
        raise QCProviderError(INSTALL_HINT)
    # imgutils choisit CUDA dès qu'il le voit : les détecteurs restent sur CPU, sauf choix explicite.
    os.environ.setdefault("ONNX_MODE", "cpu")


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
                faces = _call_onnx(lambda: detect.detect_faces(img, **(face or {})))
                hands = _call_onnx(lambda: detect.detect_hands(img, **(hand or {})))
                texts = _call_onnx(lambda: detect.detect_text(img, **(text or {})))
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
                feats = [_call_onnx(lambda r=r: self._feature(ccip, r)) for r in regions]
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
