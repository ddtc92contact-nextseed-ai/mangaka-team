"""ComfyUI factice : renvoie une image unie à la taille demandée, sans GPU ni réseau."""

from __future__ import annotations

import io
import uuid
from typing import Any

from PIL import Image

from .base import ComfyStatus, ComfyUIError, ImageRef

DEFAULT_SIZE = (512, 512)


def requested_size(workflow: dict[str, Any]) -> tuple[int, int]:
    """Cherche la première paire d'entrées entières width/height (ex. nœud latent vide)."""
    for node in workflow.values():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        w, h = inputs.get("width"), inputs.get("height")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            return w, h
    return DEFAULT_SIZE


def _seed(workflow: dict[str, Any]) -> int:
    for node in workflow.values():
        seed = node.get("inputs", {}).get("seed") if isinstance(node, dict) else None
        if isinstance(seed, int):
            return seed
    return 0


class MockComfyUIClient:
    name = "mock"

    def __init__(self, *, online: bool = True) -> None:
        self.online = online
        self.prompts: dict[str, dict[str, Any]] = {}
        self._images: dict[str, bytes] = {}
        self._history: dict[str, dict[str, Any]] = {}

    def health(self) -> ComfyStatus:
        if not self.online:
            return ComfyStatus(online=False, provider=self.name, detail="ComfyUI factice hors ligne")
        return ComfyStatus(online=True, provider=self.name, detail="ComfyUI factice (mode mock)")

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        if not self.online:
            raise ComfyUIError("ComfyUI factice hors ligne")
        prompt_id = uuid.uuid4().hex
        self.prompts[prompt_id] = workflow
        width, height = requested_size(workflow)
        seed = _seed(workflow)
        color = (seed * 37 % 256, seed * 91 % 256, seed * 53 % 256)
        buf = io.BytesIO()
        Image.new("RGB", (width, height), color).save(buf, format="PNG")
        filename = f"mock_{prompt_id}.png"
        self._images[filename] = buf.getvalue()
        output_nodes = [k for k, n in workflow.items() if isinstance(n, dict) and n.get("class_type") == "SaveImage"]
        outputs = {
            node: {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}
            for node in output_nodes or ["output"]
        }
        self._history[prompt_id] = {"outputs": outputs, "status": {"status_str": "success", "completed": True}}
        return prompt_id

    def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        return self._history.get(prompt_id)

    def wait_for_images(
        self, prompt_id: str, output_node: str, *, timeout_s: float = 600, poll_s: float = 1.0
    ) -> list[ImageRef]:
        entry = self._history.get(prompt_id)
        if entry is None:
            raise ComfyUIError(f"génération inconnue : {prompt_id}")
        outputs = entry["outputs"].get(output_node) or next(iter(entry["outputs"].values()))
        return [ImageRef(**img) for img in outputs["images"]]

    def fetch_image(self, ref: ImageRef) -> bytes:
        try:
            return self._images[ref.filename]
        except KeyError:
            raise ComfyUIError(f"image {ref.filename} introuvable") from None
