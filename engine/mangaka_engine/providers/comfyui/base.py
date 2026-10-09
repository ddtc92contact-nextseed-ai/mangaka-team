"""Interface commune des clients ComfyUI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

# Progression d'une génération : (étape courante, nombre d'étapes).
ProgressFn = Callable[[int, int], None]
StopFn = Callable[[], bool]


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
    """Workflow refusé par ComfyUI (nœud inconnu, modèle absent…).

    Le message inclut le détail lisible des erreurs par nœud.
    """

    code = "comfyui_workflow"

    def __init__(self, message: str, node_errors: dict[str, Any] | None = None) -> None:
        self.node_errors = node_errors or {}
        details = format_node_errors(self.node_errors)
        super().__init__(f"{message} — {details}" if details else message)


def format_node_errors(node_errors: dict[str, Any], limit: int = 5) -> str:
    """`node_errors` de `/prompt` → « nœud 1 (UNETLoader) : Value not in list: unet_name… »."""
    parts: list[str] = []
    for node_id, info in node_errors.items():
        if not isinstance(info, dict):
            continue
        cls = info.get("class_type")
        msgs = []
        for err in info.get("errors") or []:
            if isinstance(err, dict):
                msg = str(err.get("message", "")).strip()
                details = str(err.get("details", "")).strip()
                msgs.append(f"{msg} : {details}" if details and details not in msg else msg)
        label = f"nœud {node_id}" + (f" ({cls})" if cls else "")
        parts.append(f"{label} : {' ; '.join(m for m in msgs if m) or 'erreur'}")
    if len(parts) > limit:
        parts = [*parts[:limit], f"… et {len(parts) - limit} autre(s)"]
    return " | ".join(parts)


class ComfyUIExecutionError(ComfyUIError):
    code = "comfyui_execution"


class ComfyUITimeoutError(ComfyUIError):
    code = "comfyui_timeout"


class ComfyUIInterruptedError(ComfyUIError):
    """Génération interrompue (annulation via `/interrupt`)."""

    code = "comfyui_interrupted"


class ComfyUIClient(Protocol):
    name: str

    def health(self) -> ComfyStatus: ...

    def queue_prompt(self, workflow: dict[str, Any]) -> str: ...

    def get_history(self, prompt_id: str) -> dict[str, Any] | None: ...

    def wait_for_images(
        self,
        prompt_id: str,
        output_node: str,
        *,
        timeout_s: float = 600,
        poll_s: float = 1.0,
        on_progress: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> list[ImageRef]: ...

    def fetch_image(self, ref: ImageRef) -> bytes: ...

    def upload_image(self, data: bytes, filename: str, *, subfolder: str = "mangaka") -> str:
        """Envoie une image dans `ComfyUI/input/` ; renvoie le nom à mettre dans un `LoadImage`."""
        ...

    def interrupt(self, prompt_id: str | None = None) -> None:
        """Interrompt la génération en cours."""
        ...


def images_from_history(entry: dict[str, Any], output_node: str) -> list[ImageRef]:
    """Extrait les images du nœud de sortie d'une entrée de `/history`."""
    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        message = "exécution ComfyUI en échec"
        kinds = [m[0] for m in status.get("messages") or [] if isinstance(m, list | tuple) and m]
        if "execution_interrupted" in kinds:
            raise ComfyUIInterruptedError("génération interrompue dans ComfyUI")
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
