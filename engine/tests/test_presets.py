from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest
import yaml

from mangaka_engine.presets import PresetError, PresetRegistry, build_workflow
from tests.conftest import PRESETS_DIR


@pytest.fixture
def presets_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, dest)
    return dest


def test_repo_presets_are_valid() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    assert reg.issues == []
    fmt = reg.page_format("a4-300dpi")
    assert (fmt.width_px, fmt.height_px) == (2480, 3508)
    assert "qwen-image-base" in reg.workflows
    assert reg.defaults is not None
    assert reg.providers is not None and reg.providers.deepseek.model


def test_unknown_preset_ids_raise_readable_errors() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    with pytest.raises(PresetError, match="format de page inconnu"):
        reg.page_format("nope")
    with pytest.raises(PresetError, match="workflow inconnu"):
        reg.workflow("nope")


def test_invalid_page_format_is_skipped_with_issue(presets_copy: Path) -> None:
    bad = presets_copy / "page_formats" / "bad.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "id": "bad",
                "name": "Marges trop grandes",
                "width_mm": 100,
                "height_mm": 100,
                "dpi": 300,
                "margins_mm": {"top": 10, "bottom": 10, "inner": 60, "outer": 60},
                "gutters_mm": {"horizontal": 5, "vertical": 5},
            }
        )
    )
    reg = PresetRegistry.load(presets_copy)
    assert "bad" not in reg.page_formats
    assert "a4-300dpi" in reg.page_formats
    [issue] = reg.issues
    assert issue.file == "page_formats/bad.yaml"
    assert "largeur" in issue.message


def test_page_format_rejects_unknown_fields_and_bad_dpi(presets_copy: Path) -> None:
    path = presets_copy / "page_formats" / "a4-300dpi.yaml"
    data = yaml.safe_load(path.read_text())
    data["dpi"] = 10
    data["colour"] = "rouge"
    path.write_text(yaml.safe_dump(data))
    reg = PresetRegistry.load(presets_copy)
    assert reg.page_formats == {}
    messages = " ".join(i.message for i in reg.issues)
    assert "dpi" in messages and "colour" in messages
    # les défauts pointent vers un format désormais absent
    assert reg.defaults is None


def test_invalid_yaml_is_reported(presets_copy: Path) -> None:
    (presets_copy / "page_formats" / "broken.yaml").write_text("id: [oops")
    reg = PresetRegistry.load(presets_copy)
    assert any("YAML invalide" in i.message for i in reg.issues)


def test_duplicate_ids_are_reported(presets_copy: Path) -> None:
    shutil.copy(presets_copy / "page_formats" / "a4-300dpi.yaml", presets_copy / "page_formats" / "z-copy.yaml")
    reg = PresetRegistry.load(presets_copy)
    assert any("double" in i.message for i in reg.issues)


def _workflow_yaml(presets_copy: Path) -> tuple[Path, dict]:
    path = presets_copy / "workflows" / "qwen-image-base.yaml"
    return path, yaml.safe_load(path.read_text())


def test_workflow_mapping_must_point_to_existing_nodes(presets_copy: Path) -> None:
    path, data = _workflow_yaml(presets_copy)
    data["mapping"]["seed"] = {"node": "999", "input": "seed"}
    data["mapping"]["width"] = {"node": "8", "input": "largeur"}
    path.write_text(yaml.safe_dump(data))
    reg = PresetRegistry.load(presets_copy)
    assert "qwen-image-base" not in reg.workflows
    msg = next(i.message for i in reg.issues if i.file.endswith("qwen-image-base.yaml"))
    assert "nœud 999 absent" in msg and "largeur" in msg


def test_workflow_requires_core_params(presets_copy: Path) -> None:
    path, data = _workflow_yaml(presets_copy)
    del data["mapping"]["positive_prompt"]
    path.write_text(yaml.safe_dump(data))
    reg = PresetRegistry.load(presets_copy)
    assert any("positive_prompt" in i.message for i in reg.issues)


def test_workflow_missing_or_broken_json(presets_copy: Path) -> None:
    (presets_copy / "workflows" / "qwen-image-base.json").write_text("{not json")
    reg = PresetRegistry.load(presets_copy)
    assert any("JSON du workflow invalide" in i.message for i in reg.issues)
    (presets_copy / "workflows" / "qwen-image-base.json").unlink()
    reg = PresetRegistry.load(presets_copy)
    assert any("introuvable" in i.message for i in reg.issues)


def test_missing_presets_dir(tmp_path: Path) -> None:
    reg = PresetRegistry.load(tmp_path / "absent")
    assert reg.issues and "introuvable" in reg.issues[0].message


# --- construction de workflow ---------------------------------------------
def test_build_workflow_applies_mapping_and_defaults() -> None:
    loaded = PresetRegistry.load(PRESETS_DIR).workflow("qwen-image-base")
    built = build_workflow(loaded, {"positive_prompt": "une ninja sur un toit", "seed": 42, "width": 832})
    wf = built.workflow
    assert wf["6"]["inputs"]["text"] == "une ninja sur un toit"
    assert wf["9"]["inputs"]["seed"] == 42
    assert wf["8"]["inputs"]["width"] == 832
    assert wf["8"]["inputs"]["height"] == loaded.preset.defaults["height"]
    assert wf["7"]["inputs"]["text"] == loaded.preset.defaults["negative_prompt"]
    assert built.params["seed"] == 42
    assert built.output_node == "11"
    # le preset chargé n'est pas modifié
    assert loaded.workflow["6"]["inputs"]["text"] == ""
    json.dumps(wf)  # sérialisable pour /prompt


def test_build_workflow_draws_and_records_seed() -> None:
    loaded = PresetRegistry.load(PRESETS_DIR).workflow("qwen-image-base")
    built = build_workflow(loaded, {"positive_prompt": "x"}, rng=random.Random(1))
    assert isinstance(built.params["seed"], int)
    assert built.workflow["9"]["inputs"]["seed"] == built.params["seed"]


def test_build_workflow_rejects_unknown_or_missing_params() -> None:
    loaded = PresetRegistry.load(PRESETS_DIR).workflow("qwen-image-base")
    with pytest.raises(PresetError, match="inconnus"):
        build_workflow(loaded, {"positive_prompt": "x", "denoise": 0.4})
    with pytest.raises(PresetError, match="positive_prompt"):
        build_workflow(loaded, {})
