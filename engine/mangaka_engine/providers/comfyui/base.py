"""Interface commune des clients ComfyUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ImageRef:
    filename: str
    subfolder: str = ""
    type: str = "output"


@dataclass
class ComfyStatus:
    online: bool
    provider: str
    url: str | None = None
    queue_running: int = 0
    queue_pending: int = 0
    detail: str | None = None


class ComfyUIError(Exception):
    code = "comfyui_error"


class ComfyUIUnavailableError(ComfyUIError):
    code = "comfyui_unavailable"


class ComfyUIWorkflowError(ComfyUIError):
    """Workflow refusé par ComfyUI (nœud inconnu, modèle absent…)."""

    code = "comfyui_workflow"

    def __init__(self, message: str, node_errors: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.node_errors = node_errors or {}


class ComfyUIExecutionError(ComfyUIError):
    code = "comfyui_execution"


class ComfyUITimeoutError(ComfyUIError):
    code = "comfyui_timeout"


class ComfyUIClient(Protocol):
    name: str

    def health(self) -> ComfyStatus: ...

    def queue_prompt(self, workflow: dict[str, Any]) -> str: ...

    def get_history(self, prompt_id: str) -> dict[str, Any] | None: ...

    def wait_for_images(
        self, prompt_id: str, output_node: str, *, timeout_s: float = 600, poll_s: float = 1.0
    ) -> list[ImageRef]: ...

    def fetch_image(self, ref: ImageRef) -> bytes: ...


def images_from_history(entry: dict[str, Any], output_node: str) -> list[ImageRef]:
    """Extrait les images du nœud de sortie d'une entrée de `/history`."""
    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        message = "exécution ComfyUI en échec"
        for kind, data in status.get("messages") or []:
            if kind == "execution_error" and isinstance(data, dict):
                message = f"{message} : {data.get('node_type', '?')} — {data.get('exception_message', '').strip()}"
                break
        raise ComfyUIExecutionError(message)
    node_out = (entry.get("outputs") or {}).get(output_node) or {}
    images = [
        ImageRef(filename=img["filename"], subfolder=img.get("subfolder", ""), type=img.get("type", "output"))
        for img in node_out.get("images", [])
        if isinstance(img, dict) and "filename" in img
    ]
    if not images and status.get("completed"):
        raise ComfyUIExecutionError(f"aucune image produite par le nœud {output_node}")
    return images
