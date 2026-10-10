"""Test de connexion à un vrai ComfyUI : les nœuds et les fichiers des presets existent-ils ?

À partir de `/object_info` (classes de nœuds, entrées, valeurs permises) et `/system_stats`
(versions, VRAM), vérifie pour chaque workflow chargé :

- que chaque `class_type` du JSON (et le chargeur de LoRA de `lora_chain`) est connu ;
- que chaque valeur fixe d'une entrée à liste (modèle, encodeur, VAE, échantillonneur…) figure
  parmi les valeurs permises — les entrées remplies par le moteur (mapping, références) sont
  ignorées ;
- que chaque LoRA saisi dans les séries et les fiches figure dans la liste du chargeur ;
- verrouillage de composition (presets `controle`) : chargeur du patch, nœud qui l'applique et
  fichier du patch présents (sinon message clair : ComfyUI à mettre à jour, fichier à placer), et
  prétraitement de chaque type de contrôle connu. Ces presets sont optionnels : leur absence ne
  rend pas le test « en échec », elle masque seulement le verrouillage dans l'atelier.

Aucun nom de fichier ici : tout vient des presets et de la base.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ..presets import LoadedUpscaler, LoadedWorkflow, PresetRegistry
from ..presets.schemas import ControlSettings
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


def check_workflow(loaded: LoadedWorkflow | LoadedUpscaler, object_info: dict[str, Any]) -> list[str]:
    """Problèmes lisibles d'un workflow face aux nœuds et fichiers du ComfyUI interrogé."""
    preset = loaded.preset
    runtime = {(t.node, t.input) for t in preset.mapping.values()}
    runtime |= {(s.node, s.input) for s in preset.reference_images}
    if preset.source_image is not None:  # croquis validé, envoyé à chaque passage au propre
        runtime.add((preset.source_image.node, preset.source_image.input))
    if preset.inpaint is not None:  # image source et masque : envoyés par le moteur
        runtime |= {(t.node, t.input) for t in (preset.inpaint.source_image, preset.inpaint.mask_image)}
    control = preset.control
    if control is not None:  # image guide : envoyée par le moteur ; prétraitement : selon le type
        runtime.add((control.image.node, control.image.input))
    problems: list[str] = []
    unknown: set[str] = set()
    for node_id in sorted(loaded.workflow, key=_node_order):
        node = loaded.workflow[node_id]
        if not isinstance(node, dict) or (control is not None and node_id == control.preprocessor):
            continue
        cls = str(node.get("class_type") or "")
        if cls not in object_info:
            if cls not in unknown:
                hint = (
                    " — ComfyUI à mettre à jour (verrouillage de composition)"
                    if control is not None and node_id in (control.patch.node, control.apply.node)
                    else ""
                )
                problems.append(f"nœud inconnu : {cls or '(sans class_type)'} (nœud {node_id}){hint}")
                unknown.add(cls)
            continue
        for name, value in (node.get("inputs") or {}).items():
            if (node_id, name) in runtime or not isinstance(value, str):
                continue
            allowed = allowed_values(input_spec(object_info, cls, name))
            if allowed is not None and value not in allowed:
                if control is not None and (node_id, name) == (control.patch.node, control.patch.input):
                    problems.append(patch_missing_message(value, node_id, cls))
                    continue
                problems.append(f"{missing_value_message(name, value)} (nœud {node_id}, {cls})")
    chain = preset.lora_chain
    if chain is not None and chain.class_type not in object_info and chain.class_type not in unknown:
        problems.append(f"nœud inconnu : {chain.class_type} (chargeur de LoRA)")
    return problems


def patch_missing_message(value: str, node_id: str, cls: str) -> str:
    return (
        f"fichier du patch ControlNet introuvable dans ComfyUI : {value} — à placer dans "
        f"ComfyUI/models/model_patches/ (nœud {node_id}, {cls})"
    )


def control_core_problems(loaded: LoadedWorkflow, object_info: dict[str, Any]) -> list[str]:
    """Ce qui empêche tout verrouillage avec ce preset : chargeur du patch, nœud qui l'applique, fichier."""
    control = loaded.preset.control
    if control is None:
        return []
    problems: list[str] = []
    for target in (control.patch, control.apply):
        node = loaded.workflow.get(target.node) or {}
        cls = str(node.get("class_type") or "")
        if cls not in object_info:
            problems.append(f"nœud {cls} absent de ce ComfyUI (mise à jour de ComfyUI nécessaire)")
    patch_node = loaded.workflow.get(control.patch.node) or {}
    patch_cls = str(patch_node.get("class_type") or "")
    value = (patch_node.get("inputs") or {}).get(control.patch.input)
    if patch_cls in object_info and isinstance(value, str):
        allowed = allowed_values(input_spec(object_info, patch_cls, control.patch.input))
        if allowed is not None and value not in allowed:
            problems.append(f"fichier du patch {value} absent de ComfyUI/models/model_patches/")
    return problems


def control_type_problems(control: ControlSettings, object_info: dict[str, Any]) -> dict[str, str | None]:
    """Type de contrôle → problème (None : utilisable) : son prétraitement est-il connu de ComfyUI ?"""
    return {
        key: (
            f"prétraitement {t.class_type} absent de ce ComfyUI (comfyui_controlnet_aux à installer ou à mettre à jour)"
            if t.class_type is not None and t.class_type not in object_info
            else None
        )
        for key, t in control.types.items()
    }


def control_types(presets: PresetRegistry) -> dict[str, tuple[ControlSettings, str]]:
    """Types de contrôle des presets ControlNet (le premier preset qui déclare un type fait foi)."""
    out: dict[str, tuple[ControlSettings, str]] = {}
    for loaded in presets.control_presets():
        assert loaded.preset.control is not None
        for key in loaded.preset.control.types:
            out.setdefault(key, (loaded.preset.control, key))
    return out


def check_control(presets: PresetRegistry, object_info: dict[str, Any] | None) -> dict[str, Any]:
    """Verrouillage de composition : disponible ? Message clair sinon, et état de chaque type.

    `object_info` None : ComfyUI simulé (mock) — tout est disponible."""
    controls = presets.control_presets()
    types = control_types(presets)
    problems: list[str] = []
    if not controls:
        problems.append("aucun preset ControlNet (rôle « controle ») dans presets/workflows/")
    elif object_info is not None:
        for loaded in controls:
            problems += [p for p in control_core_problems(loaded, object_info) if p not in problems]
    first = controls[0].preset.control if controls else None
    type_out = []
    for key, (settings, _) in sorted(types.items(), key=lambda kv: (kv[1][0].types[kv[0]].order, kv[0])):
        t = settings.types[key]
        problem = control_type_problems(settings, object_info).get(key) if object_info is not None else None
        type_out.append(
            {
                "id": key,
                "name": t.name,
                "description": t.description,
                "preprocessor": t.class_type,
                "available": problem is None,
                "problem": problem,
            }
        )
    available = not problems and any(t["available"] for t in type_out)
    message = None
    if problems:
        message = "Verrouillage de composition indisponible : " + " ; ".join(problems) + "."
    elif not available:
        message = "Verrouillage de composition indisponible : aucun prétraitement de contrôle n'est installé."
    return {
        "available": available,
        "problems": problems,
        "message": message,
        "default_type": first.default_type if first else None,
        "default_strength": first.default_strength if first else None,
        "types": type_out,
    }


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
        {
            "id": w.preset.id,
            "name": w.preset.name,
            "problems": check_workflow(w, object_info),
            # Presets ControlNet : optionnels (verrouillage masqué dans l'atelier s'ils ne passent pas).
            "optional": w.preset.control is not None,
        }
        for w in [*presets.workflows.values(), *presets.upscalers.values()]
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
        "ok": all(w["ok"] for w in workflows if not w["optional"]) and not lora_problems,
        "system": system_summary(system_stats),
        "presets": workflows,
        "loras": {"checked": len({u.name for u in loras}), "problems": lora_problems},
        "control": check_control(presets, object_info),
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
        "control": None,
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
        "control": None,
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
