"""JSON API envoyé à ComfyUI pour chaque palier (Qualité / Rapide), comparé à des fichiers de référence.

Prompts, seed, taille, images de référence et LoRA injectés : toute différence avec
`golden/workflows/<preset>.json` fait échouer le test. Après une modification voulue des presets,
régénérer avec `UPDATE_GOLDEN=1 npm run test:engine` puis relire le diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mangaka_engine.presets import LoraSpec, PresetRegistry, build_workflow
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

PRESETS = ["qwen-image-base", "qwen-image-base-rapide", "qwen-image-edit-ref", "qwen-image-edit-ref-rapide"]


def _build(preset_id: str) -> dict:
    loaded = REG.workflow(preset_id)
    refs = REFERENCES if loaded.preset.reference_images else []
    return build_workflow(loaded, PARAMS, reference_images=refs, loras=LORAS).workflow


@pytest.mark.parametrize("preset_id", PRESETS)
def test_workflow_matches_golden(preset_id: str) -> None:
    built = _build(preset_id)
    path = GOLDEN / f"{preset_id}.json"
    text = json.dumps(built, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == built


@pytest.mark.parametrize("tier", ["", "-rapide"])
def test_tiers_share_the_graph_and_differ_by_files_and_steps(tier: str) -> None:
    """Rapide = mêmes nœuds et liaisons que Qualité ; seuls les fichiers modèle / encodeur et les étapes changent."""
    for base in ("qwen-image-base", "qwen-image-edit-ref"):
        qualite, rapide = REG.workflow(base).workflow, REG.workflow(f"{base}-rapide").workflow
        assert {k: n["class_type"] for k, n in qualite.items()} == {k: n["class_type"] for k, n in rapide.items()}
        diff = {
            (k, name)
            for k, n in qualite.items()
            for name, value in n["inputs"].items()
            if rapide[k]["inputs"].get(name) != value
        }
        assert diff == {("1", "unet_name"), ("2", "clip_name"), ("9", "steps")}
    rapide_steps = REG.workflow("qwen-image-base-rapide").preset.defaults["steps"]
    assert rapide_steps < REG.workflow("qwen-image-base").preset.defaults["steps"]
    built = _build(f"qwen-image-edit-ref{tier}")
    assert built["6"]["inputs"]["images.image_1"] == ["20", 0] and "images.image_3" not in built["6"]["inputs"]


def test_tier_pairing_and_defaults() -> None:
    assert REG.defaults is not None and REG.defaults.workflow == "qwen-image-base"  # Qualité par défaut
    assert REG.workflow("qwen-image-base").preset.with_references == "qwen-image-edit-ref"
    assert REG.workflow("qwen-image-base-rapide").preset.with_references == "qwen-image-edit-ref-rapide"
    for preset_id in PRESETS:
        assert REG.workflow(preset_id).preset.trial["positive_prompt"]
    assert list(REG.workflows)[:2] == ["qwen-image-base", "qwen-image-base-rapide"]  # ordre des listes
