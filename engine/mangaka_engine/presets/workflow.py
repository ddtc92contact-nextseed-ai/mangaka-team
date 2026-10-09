"""Construction d'un workflow ComfyUI prêt à envoyer à `/prompt` à partir d'un preset."""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any

from .loader import LoadedWorkflow, PresetError

MAX_SEED = 2**63 - 1


@dataclass
class BuiltWorkflow:
    workflow: dict[str, Any]
    params: dict[str, Any]  # paramètres effectivement appliqués (seed comprise)
    output_node: str


def build_workflow(loaded: LoadedWorkflow, params: dict[str, Any], rng: random.Random | None = None) -> BuiltWorkflow:
    """Applique `defaults` puis `params` sur une copie du JSON API.

    - un paramètre absent du mapping lève `PresetError` ;
    - `seed` absente ou None → tirée au hasard puis renvoyée (pour être enregistrée).
    """
    preset = loaded.preset
    unknown = sorted(set(params) - set(preset.mapping))
    if unknown:
        raise PresetError(f"paramètres inconnus pour le workflow {preset.id} : {', '.join(unknown)}")

    resolved: dict[str, Any] = {**preset.defaults, **{k: v for k, v in params.items() if v is not None}}
    if resolved.get("seed") is None:
        resolved["seed"] = (rng or random.SystemRandom()).randint(0, MAX_SEED)
    if "positive_prompt" not in resolved:
        raise PresetError("positive_prompt est obligatoire")
    resolved.setdefault("negative_prompt", "")

    missing = [p for p in ("width", "height") if p not in resolved]
    if missing:
        raise PresetError(f"paramètres manquants : {', '.join(missing)}")

    workflow = copy.deepcopy(loaded.workflow)
    for name, value in resolved.items():
        target = preset.mapping[name]
        workflow[target.node]["inputs"][target.input] = value
    return BuiltWorkflow(workflow=workflow, params=resolved, output_node=preset.output_node)
