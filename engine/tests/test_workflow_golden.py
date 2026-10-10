"""JSON API envoyé à ComfyUI pour chaque palier (Qualité / Rapide / Turbo), comparé à des fichiers de référence.

Prompts, seed, taille, images de référence et LoRA injectés : toute différence avec
`golden/workflows/<preset>.json` fait échouer le test. Après une modification voulue des presets,
régénérer avec `UPDATE_GOLDEN=1 npm run test:engine` puis relire le diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mangaka_engine.presets import (
    ControlInput,
    LoraSpec,
    PresetRegistry,
    build_control_map_workflow,
    build_workflow,
)
from tests.conftest import PRESETS_DIR

REG = PresetRegistry.load(PRESETS_DIR)
GOLDEN = Path(__file__).parent / "golden" / "workflows"
PARAMS = {
    "positive_prompt": "plan moyen, Aiko sur un toit au crépuscule, encre et trames",
    "negative_prompt": "texte, bulles",
    "seed": 424242,
    "width": 832,
    "height": 1216,
    "filename_prefix": "mangaka/serie-1/chapitre-1/page-1/case-1",
}
LORAS = [LoraSpec("encre-seinen.safetensors", 0.7, "style"), LoraSpec("aiko-v3.safetensors", 0.9, "Aiko")]
REFERENCES = ["mangaka/perso1_img1.png", "mangaka/perso2_img4.png"]

PRESETS = [
    "qwen-image-base",
    "qwen-image-base-rapide",
    "qwen-image-turbo",
    "qwen-image-edit-ref",
    "qwen-image-edit-ref-rapide",
    "qwen-image-edit-ref-turbo",
    # Palier croquis et passage au propre (image → image depuis le croquis validé).
    "qwen-image-croquis",
    "qwen-image-edit-ref-croquis",
    "qwen-image-turbo-from-sketch",
    "qwen-image-edit-ref-turbo-from-sketch",
    "qwen-image-base-rapide-from-sketch",
    "qwen-image-edit-ref-rapide-from-sketch",
    "qwen-image-base-from-sketch",
    "qwen-image-edit-ref-from-sketch",
    # Composition verrouillée (ControlNet Union : patch de modèle, image guide, prétraitement).
    "qwen-image-turbo-controlnet",
    "qwen-image-edit-ref-turbo-controlnet",
    "qwen-image-base-rapide-controlnet",
    "qwen-image-edit-ref-rapide-controlnet",
    "qwen-image-base-controlnet",
    "qwen-image-edit-ref-controlnet",
]
SOURCE = "mangaka/croquis_case1_v1.png"
CONTROL = ControlInput(image="mangaka/guide_case1_v2.png", type="lineart", strength=0.85)
# Paliers (texte → image, avec références) : Qualité, Rapide, Turbo.
TIERS = {
    "": ("qwen-image-base", "qwen-image-edit-ref"),
    "-rapide": ("qwen-image-base-rapide", "qwen-image-edit-ref-rapide"),
    "-turbo": ("qwen-image-turbo", "qwen-image-edit-ref-turbo"),
}


def _build(preset_id: str) -> dict:
    loaded = REG.workflow(preset_id)
    refs = REFERENCES if loaded.preset.reference_images else []
    source = SOURCE if loaded.preset.source_image else None
    control = CONTROL if loaded.preset.control else None
    return build_workflow(
        loaded, PARAMS, reference_images=refs, loras=LORAS, source_image=source, control=control
    ).workflow


@pytest.mark.parametrize("preset_id", PRESETS)
def test_workflow_matches_golden(preset_id: str) -> None:
    built = _build(preset_id)
    path = GOLDEN / f"{preset_id}.json"
    text = json.dumps(built, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == built


CONTROL_PRESETS = [p for p in PRESETS if p.endswith("-controlnet")]
# Types sans post-traitement de la carte : graphe figé (le golden a été produit avant l'inversion de « Trait »).
PLAIN_CONTROL_TYPES = ["depth", "pose", "scribble", "canny", "carte"]


@pytest.mark.parametrize("preset_id", CONTROL_PRESETS)
def test_control_types_match_golden(preset_id: str) -> None:
    """Workflow de génération et aperçu de carte de chaque type autre que « Trait », comparés au golden."""
    loaded = REG.workflow(preset_id)
    refs = REFERENCES if loaded.preset.reference_images else []
    built = {}
    for type_id in PLAIN_CONTROL_TYPES:
        control = ControlInput(image=CONTROL.image, type=type_id, strength=CONTROL.strength)
        built[type_id] = {
            "generation": build_workflow(loaded, PARAMS, reference_images=refs, loras=LORAS, control=control).workflow,
            "map": build_control_map_workflow(loaded, CONTROL.image, type_id, 832, 1216).workflow,
        }
    path = GOLDEN / f"{preset_id}.types.json"
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(json.dumps(built, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == built


def _diff(a: dict, b: dict) -> set[tuple[str, str]]:
    return {(k, name) for k, n in a.items() for name, value in n["inputs"].items() if b[k]["inputs"].get(name) != value}


@pytest.mark.parametrize("tier", list(TIERS))
def test_tiers_share_the_graph_and_differ_by_files_and_steps(tier: str) -> None:
    """Rapide et Turbo = mêmes nœuds et liaisons que Qualité ; seuls les fichiers modèle / encodeur et les
    étapes changent (Turbo : mêmes encodeur int8 et VAE que Rapide, seul le modèle distillé diffère)."""
    for i, other in enumerate(TIERS[tier]):
        qualite, wf = REG.workflow(TIERS[""][i]).workflow, REG.workflow(other).workflow
        assert {k: n["class_type"] for k, n in qualite.items()} == {k: n["class_type"] for k, n in wf.items()}
        assert _diff(qualite, wf) == (set() if not tier else {("1", "unet_name"), ("2", "clip_name"), ("9", "steps")})
        if tier == "-turbo":
            assert _diff(REG.workflow(TIERS["-rapide"][i]).workflow, wf) == {("1", "unet_name"), ("9", "steps")}
    steps = [REG.workflow(TIERS[t][0]).preset.defaults["steps"] for t in ("-turbo", "-rapide", "")]
    assert steps == sorted(steps) and len(set(steps)) == 3
    built = _build(TIERS[tier][1])
    assert built["6"]["inputs"]["images.image_1"] == ["20", 0] and "images.image_3" not in built["6"]["inputs"]


@pytest.mark.parametrize("preset_id", ["qwen-image-turbo", "qwen-image-edit-ref-turbo"])
def test_turbo_presets_sampler_and_files(preset_id: str) -> None:
    """Turbo : modèle distillé int8 (pas de LoRA d'accélération ni de nœud personnalisé), 8 étapes, cfg 1,
    euler + simple, denoise 1 ; LoRA de série / personnages chaînés après le modèle comme ailleurs."""
    loaded = REG.workflow(preset_id)
    built = build_workflow(
        loaded, PARAMS, reference_images=REFERENCES[: len(loaded.preset.reference_images)], loras=LORAS
    )
    wf = built.workflow
    assert "turbo" in wf["1"]["inputs"]["unet_name"] and "int8" in wf["1"]["inputs"]["unet_name"]
    assert "int8" in wf["2"]["inputs"]["clip_name"]
    sampler = wf["9"]["inputs"]
    assert (sampler["steps"], sampler["cfg"], sampler["sampler_name"], sampler["scheduler"], sampler["denoise"]) == (
        8,
        1,
        "euler",
        "simple",
        1,
    )
    assert {n["class_type"] for n in wf.values()} == {
        n["class_type"] for n in REG.workflow("qwen-image-base").workflow.values()
    } | {"LoraLoaderModelOnly"} | ({"LoadImage"} if loaded.preset.reference_images else set())
    assert REG.workflow(preset_id).preset.lora_chain == REG.workflow("qwen-image-base-rapide").preset.lora_chain
    assert loaded.preset.tier is not None and loaded.preset.tier.name == "Turbo"


def test_tier_pairing_and_defaults() -> None:
    # Rapide par défaut (10/10/2026) ; Turbo pour les fiches de référence et la planche de style
    assert REG.defaults is not None and REG.defaults.workflow == "qwen-image-base-rapide"
    assert REG.defaults.workflow_with_references == "qwen-image-edit-ref-rapide"
    assert REG.defaults.workflow_library == "qwen-image-turbo"
    assert REG.defaults.workflow_sketch == "qwen-image-croquis"
    assert REG.defaults.workflow_quality == "qwen-image-base"
    for base, edit in TIERS.values():
        assert REG.workflow(base).preset.with_references == edit
    for preset_id in PRESETS:
        if REG.workflow(preset_id).preset.role not in ("propre", "controle"):  # demandent une image source
            assert REG.workflow(preset_id).preset.trial["positive_prompt"]
    # ordre des listes
    assert list(REG.workflows)[:3] == ["qwen-image-base", "qwen-image-base-rapide", "qwen-image-turbo"]
    # trois paliers proposés dans la fiche série, dans l'ordre Turbo, Rapide, Qualité
    choices = sorted(
        (w.preset.tier.order, w.preset.tier.choice)
        for w in REG.workflows.values()
        if w.preset.tier and w.preset.tier.choice
    )
    assert [c for _, c in choices] == [
        "Turbo (production en volume, ~35 s par case)",
        "Rapide (recommandé pour la qualité, ~1 min par case)",
        "Qualité (finitions)",
    ]
    # estimations des presets (s / case) : Turbo 20, Rapide 60, Qualité 70, ×4 avec références
    for (base, edit), seconds in zip(TIERS.values(), (70, 60, 20), strict=True):
        assert REG.workflow(base).preset.estimated_s == seconds
        assert REG.workflow(edit).preset.estimated_s == seconds * 4


# Réparation ciblée (inpainting) : image source, masque, denoise, seed, références et LoRA injectés.
INPAINT_PRESETS = ["qwen-image-inpaint", "qwen-image-inpaint-rapide", "qwen-image-inpaint-turbo"]
INPAINT_PARAMS = {
    "positive_prompt": "Main bien dessinée, cinq doigts. Personnage : Aiko (cheveux noirs).",
    "negative_prompt": "texte, bulles",
    "seed": 424242,
    "denoise": 0.4,
    "filename_prefix": "mangaka/serie-1/chapitre-1/page-1/case-1",
}


@pytest.mark.parametrize("preset_id", INPAINT_PRESETS)
def test_inpaint_workflow_matches_golden(preset_id: str) -> None:
    built = build_workflow(
        REG.workflow(preset_id),
        INPAINT_PARAMS,
        reference_images=REFERENCES[:1],
        loras=LORAS,
        inpaint_images=("mangaka/source_img12.png", "mangaka/masque_job34.png"),
    ).workflow
    path = GOLDEN / f"{preset_id}.json"
    text = json.dumps(built, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text, encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == built
