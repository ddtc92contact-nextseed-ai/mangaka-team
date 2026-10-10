"""Construction d'un workflow ComfyUI prêt à envoyer à `/prompt` à partir d'un preset.

Tout ce qui dépend du workflow (nœuds, classes, entrées) vient du preset : ce module ne
connaît aucun nom de modèle, de LoRA ni de nœud.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .loader import LoadedUpscaler, LoadedWorkflow, PresetError
from .schemas import ControlSettings, LoraChain

MAX_SEED = 2**63 - 1


@dataclass(frozen=True)
class LoraSpec:
    name: str  # fichier dans ComfyUI/models/loras
    weight: float
    source: str = ""  # « style » ou nom du personnage (pour l'affichage)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "weight": self.weight, "source": self.source}


@dataclass(frozen=True)
class ControlInput:
    """Composition verrouillée : image guide (nom côté ComfyUI), type de contrôle et force du patch."""

    image: str
    type: str
    strength: float


@dataclass
class BuiltWorkflow:
    workflow: dict[str, Any]
    params: dict[str, Any]  # paramètres effectivement appliqués (seed comprise)
    output_node: str
    reference_images: list[str] = field(default_factory=list)  # noms côté ComfyUI, dans l'ordre des emplacements
    loras: list[LoraSpec] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    source_image: str | None = None  # image de composition (nom côté ComfyUI)
    # Contrôle appliqué : {type, name, strength, preprocessor, patch, image[, post]} (preset ControlNet).
    control: dict[str, Any] | None = None


def is_link(value: Any) -> bool:
    """Une entrée `[id_du_nœud, index_de_sortie]` du format API."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    )


def build_workflow(
    loaded: LoadedWorkflow,
    params: dict[str, Any],
    rng: random.Random | None = None,
    *,
    reference_images: Sequence[str] = (),
    loras: Sequence[LoraSpec] = (),
    source_image: str | None = None,
    inpaint_images: tuple[str, str] | None = None,
    control: ControlInput | None = None,
) -> BuiltWorkflow:
    """Applique `defaults` puis `params` sur une copie du JSON API.

    - un paramètre absent du mapping lève `PresetError` ;
    - `seed` absente ou None → tirée au hasard puis renvoyée (pour être enregistrée) ;
    - `reference_images` remplissent les emplacements dans l'ordre, les emplacements vides
      sont retirés ;
    - `loras` sont chaînés au point d'insertion `lora_chain`, dans l'ordre ;
    - `source_image` (nom côté ComfyUI de l'image de composition, ex. le croquis validé) est écrite
      dans le nœud `source_image` du preset : obligatoire pour un workflow qui en déclare un.
    - preset de réparation (bloc `inpaint`) : `inpaint_images` = (image source, masque), noms côté
      ComfyUI ; pas de taille à fournir (celle de l'image source).
    - preset ControlNet (bloc `control`) : `control` = image guide, type et force ; le prétraitement
      du type remplace le nœud `preprocessor`, la carte est mise à la taille de la case, le nœud
      d'aperçu (`map_output`) est retiré. Les LoRA restent chaînés AVANT le patch (le patch consomme
      la sortie du modèle, comme le reste : la chaîne LoRA s'insère entre les deux).
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

    inpaint = preset.inpaint
    if inpaint is not None and inpaint_images is None:
        raise PresetError(f"le workflow de réparation {preset.id} demande une image source et un masque")
    if inpaint is None and inpaint_images is not None:
        raise PresetError(f"le workflow {preset.id} n'est pas un preset de réparation (bloc inpaint absent)")
    missing = [p for p in ("width", "height") if p not in resolved] if inpaint is None else []
    if missing:
        raise PresetError(f"paramètres manquants : {', '.join(missing)}")

    slots = preset.reference_images
    if len(reference_images) > len(slots):
        raise PresetError(
            f"le workflow {preset.id} accepte au plus {len(slots)} image(s) de référence "
            f"({len(reference_images)} fournie(s))"
        )
    if preset.source_image is not None and not source_image:
        raise PresetError(f"le workflow {preset.id} attend une image de composition (croquis validé)")
    if source_image and preset.source_image is None:
        raise PresetError(f"le workflow {preset.id} n'accepte pas d'image de composition (source_image)")
    if loras and preset.lora_chain is None:
        raise PresetError(f"le workflow {preset.id} ne déclare pas de point d'insertion LoRA (lora_chain)")
    if preset.control is not None and control is None:
        raise PresetError(f"le workflow {preset.id} verrouille la composition : il attend une image guide")
    if control is not None and preset.control is None:
        raise PresetError(f"le workflow {preset.id} n'accepte pas d'image guide (bloc control)")

    workflow = copy.deepcopy(loaded.workflow)
    for name, value in resolved.items():
        target = preset.mapping[name]
        workflow[target.node]["inputs"][target.input] = value
    if inpaint is not None and inpaint_images is not None:
        source, mask = inpaint_images
        workflow[inpaint.source_image.node]["inputs"][inpaint.source_image.input] = source
        workflow[inpaint.mask_image.node]["inputs"][inpaint.mask_image.input] = mask

    if preset.source_image is not None:
        workflow[preset.source_image.node]["inputs"][preset.source_image.input] = source_image

    applied: dict[str, Any] | None = None
    removed: list[str] = []
    if preset.control is not None and control is not None:
        applied = apply_control(workflow, preset.id, preset.control, control, resolved)
        if preset.control.map_output is not None:
            removed.append(preset.control.map_output)  # l'aperçu de la carte n'est pas enregistré ici
    for i, slot in enumerate(slots):
        if i < len(reference_images):
            workflow[slot.node]["inputs"][slot.input] = reference_images[i]
        else:
            removed += [n for n in (slot.node, *slot.remove) if n not in removed]
    remove_nodes(workflow, removed)

    if loras:
        assert preset.lora_chain is not None
        # Numérotation après le JSON d'origine : jamais l'id d'un emplacement retiré.
        insert_loras(workflow, preset.lora_chain, loras, first_id=_next_id(loaded.workflow))

    return BuiltWorkflow(
        workflow=workflow,
        params=resolved,
        output_node=preset.output_node,
        reference_images=list(reference_images),
        loras=list(loras),
        removed_nodes=removed,
        source_image=source_image,
        control=applied,
    )


def control_type(settings: ControlSettings, preset_id: str, type_id: str) -> Any:
    try:
        return settings.types[type_id]
    except KeyError:
        known = ", ".join(settings.types)
        raise PresetError(
            f"type de contrôle inconnu pour le workflow {preset_id} : « {type_id} » (possibles : {known})"
        ) from None


def apply_control(
    workflow: dict[str, Any],
    preset_id: str,
    settings: ControlSettings,
    control: ControlInput,
    size: dict[str, Any],
) -> dict[str, Any]:
    """Branche l'image guide, le prétraitement du type choisi, la taille et la force du patch."""
    ctype = control_type(settings, preset_id, control.type)
    if not 0 <= control.strength <= 2:
        raise PresetError(f"force du contrôle hors limites (0 à 2) : {control.strength}")
    workflow[settings.image.node]["inputs"][settings.image.input] = control.image
    workflow[settings.apply.node]["inputs"][settings.apply.input] = control.strength
    if settings.resize is not None:
        for key in ("width", "height"):
            if size.get(key) is not None:
                workflow[settings.resize]["inputs"][key] = size[key]
    image_link = [settings.image.node, 0]
    pre = settings.preprocessor
    users = _consumers(workflow, [pre, 0])
    if ctype.class_type is None:
        # Pas de prétraitement : l'image guide est déjà une carte (croquis à la main, scribble).
        workflow.pop(pre, None)
        source = image_link
    else:
        workflow[pre] = {
            "class_type": ctype.class_type,
            "inputs": {**copy.deepcopy(ctype.inputs), ctype.image_input: image_link},
            "_meta": {"title": f"Prétraitement : {ctype.name}"},
        }
        source = [pre, 0]
    # Post-traitements de la carte (ex. inversion) : chaînés après le prétraitement, avant la mise à la taille.
    for step in ctype.post:
        node_id = str(_next_id(workflow))
        workflow[node_id] = {
            "class_type": step.class_type,
            "inputs": {**copy.deepcopy(step.inputs), step.image_input: source},
            "_meta": {"title": f"Carte ({ctype.name}) : {step.name or step.class_type}"},
        }
        source = [node_id, 0]
    if source != [pre, 0]:
        for node_id, key in users:
            workflow[node_id]["inputs"][key] = source
    patch = workflow[settings.patch.node]["inputs"].get(settings.patch.input)
    applied = {
        "type": control.type,
        "name": ctype.name,
        "strength": control.strength,
        "preprocessor": ctype.class_type,
        "patch": patch,
        "image": control.image,
    }
    if ctype.post:
        applied["post"] = [step.class_type for step in ctype.post]
    return applied


def build_control_map_workflow(
    loaded: LoadedWorkflow,
    image: str,
    type_id: str,
    width: int,
    height: int,
    *,
    filename_prefix: str | None = None,
) -> BuiltWorkflow:
    """Aperçu de la carte de contrôle : seuls les nœuds qui mènent à `map_output` (image guide,
    prétraitement, mise à la taille, enregistrement) ; ni modèle, ni patch, ni échantillonneur."""
    preset = loaded.preset
    settings = preset.control
    if settings is None or settings.map_output is None:
        raise PresetError(f"le workflow {preset.id} ne déclare pas d'aperçu de carte de contrôle (control.map_output)")
    workflow = copy.deepcopy(loaded.workflow)
    applied = apply_control(
        workflow,
        preset.id,
        settings,
        ControlInput(image=image, type=type_id, strength=settings.default_strength),
        {"width": int(width), "height": int(height)},
    )
    keep = _ancestors(workflow, settings.map_output)
    for node_id in [k for k in workflow if k not in keep]:
        del workflow[node_id]
    out = workflow[settings.map_output]["inputs"]
    if filename_prefix is not None and "filename_prefix" in out:
        out["filename_prefix"] = filename_prefix
    return BuiltWorkflow(
        workflow=workflow,
        params={"width": int(width), "height": int(height)},
        output_node=settings.map_output,
        control=applied,
    )


def _ancestors(workflow: dict[str, Any], node_id: str) -> set[str]:
    seen: set[str] = set()
    todo = [node_id]
    while todo:
        current = todo.pop()
        if current in seen or not isinstance(workflow.get(current), dict):
            continue
        seen.add(current)
        todo += [v[0] for v in workflow[current].get("inputs", {}).values() if is_link(v)]
    return seen


def build_upscale_workflow(
    loaded: LoadedUpscaler,
    image: str,
    width: int,
    height: int,
    *,
    filename_prefix: str | None = None,
) -> BuiltWorkflow:
    """Workflow d'agrandissement : image source (nom côté ComfyUI) → taille finale exacte `width` × `height`."""
    preset = loaded.preset
    if width <= 0 or height <= 0:
        raise PresetError(f"taille finale invalide : {width}×{height}")
    resolved: dict[str, Any] = {**preset.defaults, "image": image, "width": int(width), "height": int(height)}
    if filename_prefix is not None and "filename_prefix" in preset.mapping:
        resolved["filename_prefix"] = filename_prefix
    workflow = copy.deepcopy(loaded.workflow)
    for name, value in resolved.items():
        target = preset.mapping[name]
        workflow[target.node]["inputs"][target.input] = value
    return BuiltWorkflow(workflow=workflow, params=resolved, output_node=preset.output_node)


def remove_nodes(workflow: dict[str, Any], nodes: Sequence[str]) -> None:
    """Retire des nœuds et toutes les entrées des autres nœuds qui pointaient vers eux."""
    gone = set(nodes)
    for node_id in gone:
        workflow.pop(node_id, None)
    for node in workflow.values():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        for key in [k for k, v in inputs.items() if is_link(v) and v[0] in gone]:
            del inputs[key]


def _consumers(workflow: dict[str, Any], source: list[Any]) -> list[tuple[str, str]]:
    return [
        (node_id, key)
        for node_id, node in workflow.items()
        if isinstance(node, dict)
        for key, value in node.get("inputs", {}).items()
        if is_link(value) and value == source
    ]


def _next_id(workflow: dict[str, Any]) -> int:
    return max((int(k) for k in workflow if k.isdigit()), default=0) + 1


def insert_loras(
    workflow: dict[str, Any], chain: LoraChain, loras: Sequence[LoraSpec], *, first_id: int | None = None
) -> list[str]:
    """Insère un chargeur par LoRA entre `model_from` (et `clip_from`) et leurs consommateurs."""
    model_src = [chain.model_from.node, chain.model_from.output]
    clip_src = [chain.clip_from.node, chain.clip_from.output] if chain.clip_from else None
    model_users = _consumers(workflow, model_src)
    clip_users = _consumers(workflow, clip_src) if clip_src else []

    next_id = max(first_id or 0, _next_id(workflow))
    prev_model, prev_clip = model_src, clip_src
    created: list[str] = []
    for lora in loras:
        node_id = str(next_id)
        next_id += 1
        inputs: dict[str, Any] = {
            **copy.deepcopy(chain.extra_inputs),
            chain.name_input: lora.name,
            chain.strength_input: lora.weight,
            chain.model_input: prev_model,
        }
        if prev_clip is not None:
            inputs[chain.clip_input] = prev_clip
            inputs[chain.clip_strength_input] = lora.weight
        title = f"LoRA {lora.source}".strip() if lora.source else "LoRA"
        workflow[node_id] = {"class_type": chain.class_type, "inputs": inputs, "_meta": {"title": title}}
        prev_model = [node_id, 0]
        if prev_clip is not None:
            prev_clip = [node_id, chain.clip_output]
        created.append(node_id)

    for node_id, key in model_users:
        workflow[node_id]["inputs"][key] = prev_model
    for node_id, key in clip_users:
        workflow[node_id]["inputs"][key] = prev_clip
    return created
