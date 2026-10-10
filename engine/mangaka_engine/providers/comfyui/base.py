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


# Entrées de chargeurs (sous-chaîne du nom d'entrée → libellé) : sert aux messages
# « modèle introuvable dans ComfyUI : … ». Aucun nom de fichier ici, seulement des noms d'entrées.
_FILE_INPUT_LABELS = (
    ("lora", "LoRA"),
    ("vae", "VAE"),
    ("clip", "encodeur de texte"),
    ("text_encoder", "encodeur de texte"),
    ("unet", "modèle"),
    ("ckpt", "modèle"),
    ("model", "modèle"),
)

# Entrée de chargeur (nom exact) → dossier de ComfyUI/models/ où le fichier est attendu.
_FILE_INPUT_FOLDERS = {
    "unet_name": "diffusion_models",
    "clip_name": "text_encoders",
    "vae_name": "vae",
    "lora_name": "loras",
    "ckpt_name": "checkpoints",
    "model_name": "upscale_models",  # UpscaleModelLoader (finition d'impression)
}

# Types d'erreurs de validation de `/prompt` (champ `type`) → libellé français.
_NODE_ERROR_LABELS = {
    "required_input_missing": "entrée obligatoire manquante",
    "value_smaller_than_min": "valeur trop petite",
    "value_bigger_than_max": "valeur trop grande",
    "invalid_input_type": "type de valeur invalide",
    "return_type_mismatch": "liaison de type incompatible",
    "bad_linked_input": "liaison invalide",
    "dependency_cycle": "boucle entre nœuds",
    "custom_validation_failed": "valeur refusée par le nœud",
    "exception_during_validation": "erreur pendant la validation",
    "exception_during_inner_validation": "erreur pendant la validation",
}


def missing_value_message(input_name: str, value: Any) -> str:
    """« modèle introuvable dans ComfyUI : x.safetensors » d'après le nom de l'entrée du chargeur."""
    name = input_name.lower()
    for key, label in _FILE_INPUT_LABELS:
        if key in name:
            folder = _FILE_INPUT_FOLDERS.get(name)
            where = f" — à placer dans ComfyUI/models/{folder}/" if folder else ""
            return f"{label} introuvable dans ComfyUI : {value}{where}"
    if name == "image":
        return f"image introuvable dans ComfyUI (dossier input) : {value}"
    return f"valeur « {value} » refusée pour l'entrée {input_name}"


def _node_error_message(err: dict[str, Any]) -> str:
    kind = str(err.get("type") or "")
    msg = str(err.get("message", "")).strip()
    details = str(err.get("details", "")).strip()
    extra = err.get("extra_info") if isinstance(err.get("extra_info"), dict) else {}
    input_name = str(extra.get("input_name") or "")
    if kind == "value_not_in_list" and input_name:
        return missing_value_message(input_name, extra.get("received_value", "?"))
    original = f"{msg} : {details}" if details and details not in msg else msg
    label = _NODE_ERROR_LABELS.get(kind)
    if label is None:
        return original
    target = f" ({input_name})" if input_name else ""
    return f"{label}{target} — {original}" if original else f"{label}{target}"


def format_node_errors(node_errors: dict[str, Any], limit: int = 5) -> str:
    """`node_errors` de `/prompt` → « nœud 1 (UNETLoader) : modèle introuvable dans ComfyUI : … »."""
    parts: list[str] = []
    for node_id, info in node_errors.items():
        if not isinstance(info, dict):
            continue
        cls = info.get("class_type")
        msgs = [_node_error_message(err) for err in info.get("errors") or [] if isinstance(err, dict)]
        label = f"nœud {node_id}" + (f" ({cls})" if cls else "")
        parts.append(f"{label} : {' ; '.join(m for m in msgs if m) or 'erreur'}")
    if len(parts) > limit:
        parts = [*parts[:limit], f"… et {len(parts) - limit} autre(s)"]
    return " | ".join(parts)


def describe_prompt_error(data: Any, status_code: int) -> str:
    """Erreur globale d'un refus de `/prompt` (champ `error`) en français."""
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return str(err) if isinstance(err, str) and err else f"HTTP {status_code}"
    kind = err.get("type")
    message = str(err.get("message") or "").strip()
    extra = err.get("extra_info") if isinstance(err.get("extra_info"), dict) else {}
    if kind == "prompt_outputs_failed_validation":
        return "le workflow ne passe pas la validation de ComfyUI"
    if kind == "missing_node_type":
        node = f" (nœud {extra['node_id']})" if extra.get("node_id") else ""
        return (
            f"nœud inconnu : {extra.get('class_type') or message}{node} — "
            "nœud personnalisé non installé ou ComfyUI pas à jour ?"
        )
    if kind == "prompt_no_outputs":
        return "le workflow n'a aucun nœud de sortie"
    if kind == "invalid_prompt":
        return f"workflow invalide : {message}"
    return message or f"HTTP {status_code}"


def check_prompt_nodes(workflow: dict[str, Any]) -> None:
    """Garde-fou avant `/prompt` : chaque clé de premier niveau doit être un nœud (`class_type` + `inputs`).

    ComfyUI 0.39 répond HTTP 500 sans message sur une clé qui n'est pas un nœud ; on refuse ici, en clair."""
    bad = [
        str(key)
        for key, node in workflow.items()
        if not isinstance(node, dict)
        or not isinstance(node.get("class_type"), str)
        or not isinstance(node.get("inputs"), dict)
    ]
    if bad:
        raise ComfyUIWorkflowError(f"workflow invalide : clés qui ne sont pas des nœuds : {', '.join(sorted(bad))}")


def is_out_of_memory(exception_type: str, message: str) -> bool:
    text = f"{exception_type} {message}".lower()
    return "outofmemory" in text or "out of memory" in text or "allocation on device" in text


class ComfyUIExecutionError(ComfyUIError):
    code = "comfyui_execution"


class ComfyUIOutOfMemoryError(ComfyUIExecutionError):
    """Mémoire GPU insuffisante pendant la génération."""

    code = "comfyui_out_of_memory"


class ComfyUITimeoutError(ComfyUIError):
    code = "comfyui_timeout"


class ComfyUIInterruptedError(ComfyUIError):
    """Génération interrompue (annulation via `/interrupt`)."""

    code = "comfyui_interrupted"


class ComfyUIClient(Protocol):
    name: str

    def health(self) -> ComfyStatus: ...

    def system_stats(self) -> dict[str, Any]:
        """`GET /system_stats` : versions, RAM, périphériques (VRAM)."""
        ...

    def object_info(self) -> dict[str, Any]:
        """`GET /object_info` : classes de nœuds, leurs entrées et les valeurs permises (fichiers…)."""
        ...

    def node_info(self, class_type: str) -> dict[str, Any]:
        """`GET /object_info/<classe>` : `{classe: {...}}` pour une seule classe (`{}` si inconnue)."""
        ...

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
                node_type = data.get("node_type", "?")
                text = str(data.get("exception_message", "")).strip()
                if is_out_of_memory(str(data.get("exception_type", "")), text):
                    raise ComfyUIOutOfMemoryError(
                        f"mémoire GPU insuffisante dans ComfyUI ({node_type}) : libère la mémoire "
                        "(autre génération, Ollama…), passe sur le palier Rapide ou réduis la taille"
                    )
                message = f"{message} : {node_type} — {text.splitlines()[0] if text else 'erreur'}"
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
