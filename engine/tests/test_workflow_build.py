"""Construction des workflows : emplacements de référence (0/1/3/4/5) et chaîne LoRA (0/2), tous les paliers."""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest
import yaml

from mangaka_engine.presets import LoadedWorkflow, LoraChain, LoraSpec, PresetError, PresetRegistry, build_workflow
from mangaka_engine.presets.workflow import is_link
from tests.conftest import PRESETS_DIR

REG = PresetRegistry.load(PRESETS_DIR)
EDIT = REG.workflow("qwen-image-edit-ref")
BASE = REG.workflow("qwen-image-base")
EDIT_TIERS = [
    "qwen-image-edit-ref",
    "qwen-image-edit-ref-qualite",
    "qwen-image-edit-ref-rapide",
    "qwen-image-edit-ref-turbo",
]
PARAMS = {"positive_prompt": "Aiko sur un toit", "width": 832, "height": 1216, "seed": 1234}
SLOTS = ["20", "21", "22", "23", "24"]  # LoadImage du preset, branchés sur images.image_1…5 de l'encodeur (nœud 6)
OBJECT_INFO = Path(__file__).parent / "fixtures" / "comfyui" / "object_info.json"
LORAS = [LoraSpec("encre-seinen.safetensors", 0.7, "style"), LoraSpec("aiko-v3.safetensors", 0.9, "Aiko")]


def _links_to(wf: dict, node_id: str) -> list[tuple[str, str]]:
    return [(nid, k) for nid, n in wf.items() for k, v in n["inputs"].items() if is_link(v) and v[0] == node_id]


def _dangling(wf: dict) -> list[tuple[str, str]]:
    return [(nid, k) for nid, n in wf.items() for k, v in n["inputs"].items() if is_link(v) and v[0] not in wf]


def test_edit_preset_is_valid_and_declares_slots_and_chain() -> None:
    preset = EDIT.preset
    assert [s.node for s in preset.reference_images] == SLOTS
    assert all(not s.remove for s in preset.reference_images)
    assert preset.lora_chain is not None and preset.lora_chain.class_type == "LoraLoaderModelOnly"
    assert preset.timeout_s == 1500
    assert REG.defaults is not None and REG.defaults.workflow_with_references == "qwen-image-edit-ref-qualite"


@pytest.mark.parametrize("preset_id", EDIT_TIERS)
@pytest.mark.parametrize("n_refs", [0, 1, 3, 4, 5])
@pytest.mark.parametrize("n_loras", [0, 2])
def test_reference_slots_and_lora_chain(preset_id: str, n_refs: int, n_loras: int) -> None:
    loaded = REG.workflow(preset_id)
    refs = [f"mangaka/perso{i}.png" for i in range(n_refs)]
    built = build_workflow(loaded, PARAMS, reference_images=refs, loras=LORAS[:n_loras])
    wf = built.workflow

    # paramètres mappés + seed enregistrée
    assert wf["6"]["inputs"]["prompt"] == "Aiko sur un toit"
    assert wf["9"]["inputs"]["seed"] == 1234 and built.params["seed"] == 1234
    assert (wf["8"]["inputs"]["width"], wf["8"]["inputs"]["height"]) == (832, 1216)

    # emplacements remplis dans l'ordre, les autres retirés avec leurs nœuds propres
    for i, load in enumerate(SLOTS):
        if i < n_refs:
            assert wf[load]["inputs"]["image"] == refs[i]
            assert wf["6"]["inputs"][f"images.image_{i + 1}"] == [load, 0]
        else:
            assert load not in wf
            assert f"images.image_{i + 1}" not in wf["6"]["inputs"]
    assert sorted(built.removed_nodes) == sorted(SLOTS[n_refs:])
    assert _dangling(wf) == []

    # chaîne LoRA : 1 → lora1 → lora2 → consommateurs d'origine (nœud 4, cache Qwen-Image 2.1)
    loras = [nid for nid, n in wf.items() if n["class_type"] == "LoraLoaderModelOnly"]
    assert len(loras) == n_loras
    if n_loras:
        first, second = loras
        assert wf[first]["inputs"] == {
            "lora_name": "encre-seinen.safetensors",
            "strength_model": 0.7,
            "model": ["1", 0],
        }
        assert wf[second]["inputs"] == {"lora_name": "aiko-v3.safetensors", "strength_model": 0.9, "model": [first, 0]}
        assert wf["4"]["inputs"]["model"] == [second, 0]
        assert _links_to(wf, "1") == [(first, "model")]
    else:
        assert wf["4"]["inputs"]["model"] == ["1", 0]
    assert [lo.name for lo in built.loras] == [lo.name for lo in LORAS[:n_loras]]

    json.dumps(wf)  # sérialisable pour /prompt
    assert loaded.workflow["4"]["inputs"]["model"] == ["1", 0]  # le preset chargé n'est pas modifié


def test_base_preset_supports_loras_but_no_references() -> None:
    built = build_workflow(BASE, PARAMS, loras=LORAS[:1])
    lora = next(nid for nid, n in built.workflow.items() if n["class_type"] == "LoraLoaderModelOnly")
    assert built.workflow["4"]["inputs"]["model"] == [lora, 0]
    with pytest.raises(PresetError, match="au plus 0 image"):
        build_workflow(BASE, PARAMS, reference_images=["x.png"])


def test_every_reference_preset_declares_the_same_slots_wired_to_the_encoder() -> None:
    """Tous les presets avec références (edit-ref : Turbo, Rapide, Qualité, croquis, propre, ControlNet ;
    et les réparations) ont 5 emplacements, chacun branché sur images.image_N de TextEncodeQwenImage21,
    dans la limite de l'encodeur réel (object_info enregistré)."""
    info = json.loads(OBJECT_INFO.read_text())["TextEncodeQwenImage21"]
    accepted = info["input"]["required"]["images"][1]["template"]["names"]
    with_refs = {pid: lw for pid, lw in REG.workflows.items() if lw.preset.reference_images}
    assert {pid for pid in REG.workflows if "edit-ref" in pid} <= set(with_refs)
    assert {len(lw.preset.reference_images) for lw in with_refs.values()} == {len(SLOTS)}
    assert len(SLOTS) <= len(accepted)
    for pid, lw in with_refs.items():
        assert [s.node for s in lw.preset.reference_images] == SLOTS, pid
        encoder = next(n for n in lw.workflow.values() if n["class_type"] == "TextEncodeQwenImage21")
        for i, node in enumerate(SLOTS, start=1):
            assert f"image_{i}" in accepted
            assert encoder["inputs"][f"images.image_{i}"] == [node, 0], pid
        assert "jusqu'à 3" not in lw.preset.description, pid


def test_too_many_references_or_no_lora_chain() -> None:
    with pytest.raises(PresetError, match="au plus 5"):
        build_workflow(EDIT, PARAMS, reference_images=["a", "b", "c", "d", "e", "f"])
    no_chain = LoadedWorkflow(
        preset=BASE.preset.model_copy(update={"lora_chain": None}), workflow=BASE.workflow, source=BASE.source
    )
    with pytest.raises(PresetError, match="lora_chain"):
        build_workflow(no_chain, PARAMS, loras=LORAS)


def test_lora_chain_with_clip() -> None:
    assert EDIT.preset.lora_chain is not None
    chain = LoraChain.model_validate(
        {**EDIT.preset.lora_chain.model_dump(), "class_type": "LoraLoader", "clip_from": {"node": "2", "output": 0}}
    )
    loaded = LoadedWorkflow(
        preset=EDIT.preset.model_copy(update={"lora_chain": chain}), workflow=EDIT.workflow, source=EDIT.source
    )
    wf = build_workflow(loaded, PARAMS, loras=LORAS, rng=random.Random(0)).workflow
    first, second = [nid for nid, n in wf.items() if n["class_type"] == "LoraLoader"]
    assert wf[first]["inputs"]["clip"] == ["2", 0] and wf[first]["inputs"]["strength_clip"] == 0.7
    assert wf[second]["inputs"]["clip"] == [first, 1]
    assert wf["6"]["inputs"]["clip"] == [second, 1]


@pytest.fixture
def presets_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, dest)
    return dest


def test_invalid_reference_slot_and_chain_are_reported(presets_copy: Path) -> None:
    path = presets_copy / "workflows" / "qwen-image-edit-ref-turbo.yaml"
    data = yaml.safe_load(path.read_text())
    data["reference_images"][0] = {"node": "99", "input": "image"}
    data["reference_images"][1]["remove"] = ["6"]  # nœud mappé : interdit
    data["lora_chain"]["model_from"] = {"node": "77"}
    path.write_text(yaml.safe_dump(data))
    reg = PresetRegistry.load(presets_copy)
    assert "qwen-image-edit-ref-turbo" not in reg.workflows
    msg = next(i.message for i in reg.issues if i.file.endswith("qwen-image-edit-ref-turbo.yaml"))
    assert "référence 1 : nœud 99 absent" in msg
    assert "le nœud 6 est mappé" in msg
    assert "lora_chain.model_from : nœud 77 absent" in msg
    # le défaut « avec références » (Qualité) n'est pas touché
    assert reg.defaults is not None and reg.defaults.workflow_with_references == "qwen-image-edit-ref-qualite"
    # le workflow Turbo qui l'appariait reste chargé, avec un avertissement (pas de repli)
    assert reg.workflow("qwen-image-turbo").preset.with_references == "qwen-image-edit-ref-turbo"
    assert any(i.file.endswith("qwen-image-turbo.yaml") and "with_references" in i.message for i in reg.issues)


# --- vrai CFG : le prompt négatif n'est lu qu'au-dessus de cfg 1, jamais par un modèle distillé ----------
PANEL_NEGATIVE = (
    "text, letters, speech bubble, caption, watermark, signature, multiple panels, comic page layout, collage, "
    "split screen, character sheet, turnaround, model sheet, white background, duplicate character, extra people, "
    "extra limbs, deformed hands, blurry, low quality"
)


@pytest.mark.parametrize("preset_id", ["qwen-image-base-qualite", "qwen-image-edit-ref-qualite"])
def test_quality_tier_sends_true_cfg_steps_and_the_panel_negative(preset_id: str) -> None:
    """Palier Qualité : mêmes fichiers int8 que Rapide, cfg 2,5, 35 étapes, euler/simple, et le négatif des
    cases arrive sur l'entrée négative de l'encodeur (TextEncodeQwenImage21, nœud 6)."""
    loaded = REG.workflow(preset_id)
    preset = loaded.preset
    assert not preset.distilled and preset.cfg == 2.5 and preset.negative_active()
    assert preset.tier is not None and preset.tier.name == "Qualité"
    assert preset.defaults["negative_prompt"] == PANEL_NEGATIVE
    refs = ["mangaka/perso1.png"] if preset.reference_images else []
    wf = build_workflow(loaded, PARAMS, reference_images=refs).workflow
    sampler = wf["9"]["inputs"]
    assert (sampler["cfg"], sampler["steps"], sampler["sampler_name"], sampler["scheduler"]) == (
        2.5,
        35,
        "euler",
        "simple",
    )
    assert wf["6"]["class_type"] == "TextEncodeQwenImage21"
    assert wf["6"]["inputs"]["negative_prompt"] == PANEL_NEGATIVE
    rapide = REG.workflow(preset_id.replace("qualite", "rapide")).workflow
    assert wf["1"]["inputs"]["unet_name"] == rapide["1"]["inputs"]["unet_name"]  # int8, non distillé
    assert wf["2"]["inputs"]["clip_name"] == rapide["2"]["inputs"]["clip_name"]


def test_every_preset_declares_distillation_and_cfg_one_means_negative_inactive() -> None:
    for wf_id, loaded in REG.workflows.items():
        preset = loaded.preset
        is_turbo = "turbo" in loaded.workflow["1"]["inputs"].get("unet_name", "")
        assert preset.distilled == is_turbo, wf_id  # Turbo et croquis : modèle distillé
        assert preset.negative_active() == (preset.cfg > 1), wf_id
        if preset.distilled:
            assert preset.cfg == 1, wf_id


def test_distilled_preset_refuses_cfg_above_one() -> None:
    turbo = REG.workflow("qwen-image-turbo")
    with pytest.raises(PresetError, match="distillé"):
        build_workflow(turbo, {**PARAMS, "cfg": 2.5})
    assert build_workflow(turbo, {**PARAMS, "cfg": 1}).params["cfg"] == 1
    with pytest.raises(PresetError, match="hors limites"):
        build_workflow(REG.workflow("qwen-image-base-qualite"), {**PARAMS, "cfg": 5})


def test_preset_file_with_distilled_and_cfg_above_one_is_reported(presets_copy: Path) -> None:
    path = presets_copy / "workflows" / "qwen-image-croquis.yaml"
    data = yaml.safe_load(path.read_text())
    data["defaults"]["cfg"] = 2
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    reg = PresetRegistry.load(presets_copy)
    assert "qwen-image-croquis" not in reg.workflows
    msg = next(i.message for i in reg.issues if i.file.endswith("qwen-image-croquis.yaml"))
    assert "distillé" in msg and "cfg 1 obligatoire" in msg
