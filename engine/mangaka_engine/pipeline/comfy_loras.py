"""Liste des LoRA vus par ComfyUI, pour le sélecteur de l'interface.

Les noms viennent des valeurs permises de l'entrée `name_input` du chargeur de LoRA des presets
(`lora_chain.class_type`, ex. `LoraLoaderModelOnly`), lues dans `/object_info/<classe>` : ce sont
exactement les noms que ComfyUI accepte dans un workflow, sous-dossiers et liens symboliques de
`ComfyUI/models/loras/` compris. Le moteur n'a jamais besoin du chemin sur le disque.

Le résultat est gardé quelques secondes (`LoraCatalog`) : chaque formulaire ouvert le demande.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ..presets import PresetRegistry
from ..providers.comfyui import ComfyUIClient, ComfyUIError, ComfyUIUnavailableError
from .comfy_check import allowed_values, input_spec

CACHE_TTL_S = 30.0
# Échec (ComfyUI éteint) : on réessaie plus vite, pour voir la liste dès que ComfyUI redémarre.
ERROR_TTL_S = 5.0


def lora_loaders(presets: PresetRegistry) -> list[tuple[str, str]]:
    """(classe, entrée du nom) des chargeurs de LoRA déclarés par les presets, sans doublon."""
    return sorted(
        {
            (w.preset.lora_chain.class_type, w.preset.lora_chain.name_input)
            for w in presets.workflows.values()
            if w.preset.lora_chain is not None
        }
    )


def lora_choices(object_info: dict[str, Any], loaders: list[tuple[str, str]]) -> list[str] | None:
    """Noms permis par les chargeurs présents dans `object_info` (ordre de ComfyUI, sans doublon).

    `None` si aucun chargeur n'y figure (nœud inconnu de ce ComfyUI)."""
    lists = [v for cls, name in loaders if (v := allowed_values(input_spec(object_info, cls, name))) is not None]
    if not lists:
        return None
    return list(dict.fromkeys(name for values in lists for name in values))


def split_lora_name(name: str) -> tuple[str, str]:
    """`ltx2/x.safetensors` → (`ltx2`, `x.safetensors`) ; ComfyUI sous Windows sépare par `\\`."""
    norm = name.replace("\\", "/")
    folder, _, file = norm.rpartition("/")
    return folder, file


def lora_entries(names: list[str]) -> list[dict[str, str]]:
    return [{"name": n, "folder": f, "file": file} for n in names for f, file in [split_lora_name(n)]]


def _report(
    provider: str,
    *,
    names: list[str] | None = None,
    error: str | None = None,
    simulated: bool = False,
    loader: str | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "available": names is not None,
        "simulated": simulated,
        "error": error,
        "loader": loader,
        "loras": lora_entries(names or []),
    }


def unavailable(provider: str, error: str) -> dict[str, Any]:
    return _report(provider, error=error)


def fetch_loras(client: ComfyUIClient, presets: PresetRegistry) -> dict[str, Any]:
    """Interroge ComfyUI (ou le mock) ; état « indisponible » avec le motif en français sinon."""
    loaders = lora_loaders(presets)
    if not loaders:
        return unavailable(client.name, "aucun preset de workflow n'accepte de LoRA (lora_chain)")
    if client.name == "mock":
        try:
            names = client.lora_names()  # type: ignore[attr-defined]
        except ComfyUIError as exc:
            return unavailable(client.name, str(exc))
        return _report(client.name, names=list(names), simulated=True, loader=loaders[0][0])
    info: dict[str, Any] = {}
    for cls, _ in loaders:
        try:
            info.update(client.node_info(cls))
        except ComfyUIUnavailableError as exc:
            return unavailable(client.name, str(exc))
        except ComfyUIError as exc:
            return unavailable(client.name, f"liste des LoRA illisible ({cls}) : {exc}")
    names = lora_choices(info, loaders)
    if names is None:
        classes = ", ".join(cls for cls, _ in loaders)
        return unavailable(client.name, f"chargeur de LoRA inconnu de ce ComfyUI : {classes}")
    present = next(cls for cls, _ in loaders if cls in info)
    return _report(client.name, names=names, loader=present)


class LoraCatalog:
    """Cache court de `fetch_loras` (un seul ComfyUI par moteur)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._value: dict[str, Any] | None = None
        self._expires = 0.0

    def get(self, client: ComfyUIClient, presets: PresetRegistry, *, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if not refresh and self._value is not None and self._clock() < self._expires:
                return self._value
            value = fetch_loras(client, presets)
            self._value = value
            self._expires = self._clock() + (CACHE_TTL_S if value["available"] else ERROR_TTL_S)
            return value

    def clear(self) -> None:
        with self._lock:
            self._value = None
