"""Test de connexion à un vrai ComfyUI : les nœuds et les fichiers des presets existent-ils ?

À partir de `/object_info` (classes de nœuds, entrées, valeurs permises) et `/system_stats`
(versions, VRAM), vérifie pour chaque workflow chargé :

- que chaque `class_type` du JSON (et le chargeur de LoRA de `lora_chain`) est connu ;
- que chaque valeur fixe d'une entrée à liste (modèle, encodeur, VAE, échantillonneur…) figure
  parmi les valeurs permises — les entrées remplies par le moteur (mapping, références) sont
  ignorées ;
- que chaque LoRA saisi dans les séries et les fiches figure dans la liste du chargeur.

Aucun nom de fichier ici : tout vient des presets et de la base.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ..presets import LoadedWorkflow, PresetRegistry
from ..providers.comfyui import ComfyUIClient, ComfyUIError, missing_value_message


@dataclass(frozen=True)
class LoraUse:
    name: str
    source: str  # « série « X », style » / « personnage Y (série « X ») »


def input_spec(object_info: dict[str, Any], class_type: str, input_name: str) -> Any:
    info = object_info.get(class_type)
    inputs = info.get("input") if isinstance(info, dict) else None
    if not isinstance(inputs, dict):
        return None
    for section in ("required", "optional"):
        group = inputs.get(section)
        if isinstance(group, dict) and input_name in group:
            return group[input_name]
    return None


def allowed_values(spec: Any) -> list[str] | None:
    """Valeurs permises d'une entrée « liste » (`[[…], {…}]` ou `["COMBO", {"options": […]}]`)."""
    if not isinstance(spec, list | tuple) or not spec:
        return None
    first = spec[0]
    if isinstance(first, list):
        return [str(v) for v in first]
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get("options")
        if isinstance(options, list):
            return [str(v) for v in options]
    return None


def _node_order(node_id: str) -> tuple[int, str]:
    return (int(node_id), node_id) if node_id.isdigit() else (10**9, node_id)


def check_workflow(loaded: LoadedWorkflow, object_info: dict[str, Any]) -> list[str]:
    """Problèmes lisibles d'un workflow face aux nœuds et fichiers du ComfyUI interrogé."""
    preset = loaded.preset
    runtime = {(t.node, t.input) for t in preset.mapping.values()}
    runtime |= {(s.node, s.input) for s in preset.reference_images}
    if preset.inpaint is not None:  # image source et masque : envoyés par le moteur
        runtime |= {(t.node, t.input) for t in (preset.inpaint.source_image, preset.inpaint.mask_image)}
    problems: list[str] = []
    unknown: set[str] = set()
    for node_id in sorted(loaded.workflow, key=_node_order):
        node = loaded.workflow[node_id]
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        if cls not in object_info:
            if cls not in unknown:
                problems.append(f"nœud inconnu : {cls or '(sans class_type)'} (nœud {node_id})")
                unknown.add(cls)
            continue
        for name, value in (node.get("inputs") or {}).items():
            if (node_id, name) in runtime or not isinstance(value, str):
                continue
            allowed = allowed_values(input_spec(object_info, cls, name))
            if allowed is not None and value not in allowed:
                problems.append(f"{missing_value_message(name, value)} (nœud {node_id}, {cls})")
    chain = preset.lora_chain
    if chain is not None and chain.class_type not in object_info and chain.class_type not in unknown:
        problems.append(f"nœud inconnu : {chain.class_type} (chargeur de LoRA)")
    return problems


def check_loras(presets: PresetRegistry, object_info: dict[str, Any], uses: Iterable[LoraUse]) -> list[str]:
    """LoRA des séries et des fiches absents de la liste d'un chargeur de LoRA des presets."""
    loaders = sorted(
        {
            (w.preset.lora_chain.class_type, w.preset.lora_chain.name_input)
            for w in presets.workflows.values()
            if w.preset.lora_chain is not None
        }
    )
    lists = [v for cls, name in loaders if (v := allowed_values(input_spec(object_info, cls, name))) is not None]
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for use in uses:
        if (use.name, use.source) in seen:
            continue
        seen.add((use.name, use.source))
        if any(use.name not in allowed for allowed in lists):
            problems.append(f"{missing_value_message('lora_name', use.name)} ({use.source})")
    return problems


def system_summary(stats: dict[str, Any]) -> dict[str, Any]:
    system = stats.get("system") if isinstance(stats.get("system"), dict) else {}
    devices = [
        {
            "name": str(d.get("name", "")),
            "type": str(d.get("type", "")),
            "vram_total": d.get("vram_total"),
            "vram_free": d.get("vram_free"),
        }
        for d in stats.get("devices") or []
        if isinstance(d, dict)
    ]
    return {
        "comfyui_version": system.get("comfyui_version"),
        "pytorch_version": system.get("pytorch_version"),
        "ram_total": system.get("ram_total"),
        "ram_free": system.get("ram_free"),
        "devices": devices,
    }


def build_report(
    presets: PresetRegistry,
    *,
    url: str | None,
    system_stats: dict[str, Any],
    object_info: dict[str, Any],
    loras: Sequence[LoraUse] = (),
) -> dict[str, Any]:
    workflows = [
        {"id": w.preset.id, "name": w.preset.name, "problems": check_workflow(w, object_info)}
        for w in presets.workflows.values()
    ]
    for w in workflows:
        w["ok"] = not w["problems"]
    lora_problems = check_loras(presets, object_info, loras)
    return {
        "provider": "http",
        "simulated": False,
        "url": url,
        "online": True,
        "error": None,
        "ok": all(w["ok"] for w in workflows) and not lora_problems,
        "system": system_summary(system_stats),
        "presets": workflows,
        "loras": {"checked": len({u.name for u in loras}), "problems": lora_problems},
    }


def offline_report(provider: str, url: str | None, error: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "simulated": False,
        "url": url,
        "online": False,
        "error": error,
        "ok": False,
        "system": None,
        "presets": [],
        "loras": {"checked": 0, "problems": []},
    }


def simulated_report() -> dict[str, Any]:
    return {
        "provider": "mock",
        "simulated": True,
        "url": None,
        "online": True,
        "error": None,
        "ok": True,
        "system": None,
        "presets": [],
        "loras": {"checked": 0, "problems": []},
    }


def run_check(
    client: ComfyUIClient, presets: PresetRegistry, *, url: str | None, loras: Sequence[LoraUse] = ()
) -> dict[str, Any]:
    """Interroge ComfyUI (`/system_stats` puis `/object_info`) et vérifie tous les presets."""
    if client.name == "mock":
        return simulated_report()
    try:
        stats = client.system_stats()
    except ComfyUIError as exc:
        return offline_report(client.name, url, str(exc))
    try:
        info = client.object_info()
    except ComfyUIError as exc:
        report = offline_report(client.name, url, f"liste des nœuds (/object_info) illisible : {exc}")
        return {**report, "online": True, "system": system_summary(stats)}
    return build_report(presets, url=url, system_stats=stats, object_info=info, loras=loras)
