"""LoRA Multiple-Angles et Cohérence anime (presets/camera_loras.yaml) : construction du workflow, choix de la
vue de référence la plus proche de l'angle de la case, « Changer l'angle », « Nouvel angle », interrupteur de
la série. Tout en mock : aucun ComfyUI réel, aucun GPU. Noms de fichiers et mots déclencheurs lus dans le preset."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from mangaka_engine.pipeline.camera import (
    QUALITY_TIER_LABEL,
    angle_prompt,
    camera_plan,
    closest_view,
    direction_target,
    merge_loras,
)
from mangaka_engine.presets import LoraSpec, PresetRegistry, build_workflow
from mangaka_engine.presets.workflow import is_link
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.store.models import PageDirection, Panel
from tests.conftest import PRESETS_DIR, png_bytes
from tests.test_generation import _ok, _wait, make_client, setup_chapter  # noqa: F401 — fixture

REG = PresetRegistry.load(PRESETS_DIR)
CATALOG = REG.camera_loras
MVA = CATALOG.default_angle_lora
ANIME = CATALOG.identity_lora
QUALITE = REG.workflow("qwen-image-edit-ref-qualite")
PARAMS = {"width": 1024, "height": 1024, "seed": 7}


def _loaders(wf: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {nid: n for nid, n in wf.items() if n["class_type"] == "LoraLoaderModelOnly"}


def _build(preset_id: str, *, angle: str | None = "front-right-eye", anime: bool = False, weight: float | None = None):  # type: ignore[no-untyped-def]
    loaded = REG.workflow(preset_id)
    plan = camera_plan(CATALOG, loaded, angle_id=angle, weight=weight, anime=anime)
    prompt = angle_prompt(CATALOG.prompts.panel, plan, scene="Aiko court sur un toit") if angle else "Aiko"
    refs = ["mangaka/case.png"] if loaded.preset.reference_images else []
    built = build_workflow(loaded, {**PARAMS, "positive_prompt": prompt}, reference_images=refs, loras=plan.loras)
    return plan, built


# --- preset -----------------------------------------------------------------------------
def test_catalog_declares_the_three_verified_files() -> None:
    assert REG.issues == []
    assert MVA is not None and ANIME is not None
    angles = CATALOG.angle_loras
    assert [lo.default for lo in angles].count(True) == 1 and len(angles) == 2
    assert all(lo.trigger and lo.weight == 1.0 for lo in angles)
    assert ANIME.trigger == "" and ANIME.weight == 1.0
    for lo in CATALOG.loras:
        assert lo.file.endswith(".safetensors") and "qualite" in lo.tiers
        assert "turbo" not in lo.tiers and "rapide" not in lo.tiers
    assert CATALOG.workflow == "qwen-image-edit-ref-qualite"
    assert CATALOG.angle(CATALOG.main_view) is not None


# --- construction du workflow -------------------------------------------------------------
def test_multiple_angles_adds_a_loader_with_the_preset_file_and_the_trigger_opens_the_prompt() -> None:
    assert MVA is not None
    plan, built = _build("qwen-image-edit-ref-qualite")
    [(node_id, node)] = _loaders(built.workflow).items()
    assert node["inputs"]["lora_name"] == MVA.file
    assert node["inputs"]["strength_model"] == MVA.weight
    assert node["inputs"]["model"] == ["1", 0]  # après le UNETLoader
    assert built.workflow["4"]["inputs"]["model"] == [node_id, 0]  # avant le cache, donc avant l'échantillonneur
    prompt = built.workflow["6"]["inputs"]["prompt"]
    camera = CATALOG.angle("front-right-eye").camera  # type: ignore[union-attr]
    assert prompt.startswith(f"{MVA.trigger} {camera}")
    assert "Aiko court sur un toit" in prompt
    assert plan.skipped == []


def test_weight_is_editable() -> None:
    _, built = _build("qwen-image-edit-ref-qualite", weight=0.8)
    [node] = _loaders(built.workflow).values()
    assert node["inputs"]["strength_model"] == 0.8


def test_anime_consistency_chains_a_second_loader() -> None:
    assert MVA is not None and ANIME is not None
    _, built = _build("qwen-image-edit-ref-qualite", anime=True)
    loaders = _loaders(built.workflow)
    assert [n["inputs"]["lora_name"] for n in loaders.values()] == [MVA.file, ANIME.file]
    first, second = loaders
    assert loaders[second]["inputs"]["model"] == [first, 0]
    assert loaders[second]["inputs"]["strength_model"] == ANIME.weight
    assert built.workflow["4"]["inputs"]["model"] == [second, 0]
    # Sans angle : le LoRA d'identité seul, et le prompt ne reçoit aucun mot déclencheur.
    _, alone = _build("qwen-image-base-qualite", angle=None, anime=True)
    assert [n["inputs"]["lora_name"] for n in _loaders(alone.workflow).values()] == [ANIME.file]
    assert alone.workflow["6"]["inputs"]["prompt"] == "Aiko"


@pytest.mark.parametrize("preset_id", ["qwen-image-edit-ref-turbo", "qwen-image-edit-ref-rapide", "qwen-image-turbo"])
def test_turbo_and_rapide_get_no_lora_node_and_the_reason(preset_id: str) -> None:
    plan, built = _build(preset_id, anime=True)
    assert _loaders(built.workflow) == {}
    assert plan.loras == [] and plan.prefix == ""
    assert len(plan.skipped) == 2 and all(QUALITY_TIER_LABEL.lower() in s for s in plan.skipped)
    assert plan.as_dict()["skipped"] == plan.skipped
    assert all(not is_link(v) or v[0] in built.workflow for n in built.workflow.values() for v in n["inputs"].values())


def test_series_and_entry_loras_come_first_and_are_not_doubled() -> None:
    assert MVA is not None
    plan = camera_plan(CATALOG, QUALITE, angle_id="back-eye")
    base = [LoraSpec("encre.safetensors", 0.7, "style"), LoraSpec(MVA.file, 0.5, "x")]
    assert [lo.name for lo in merge_loras(base, plan.loras)] == ["encre.safetensors", MVA.file]


# --- vue de référence la plus proche --------------------------------------------------------
@dataclass
class _View:
    name: str
    angle: str | None = None


VIEWS = [_View("principale"), _View("sans étiquette"), _View("profil", "right-eye"), _View("dos", "back-eye")]
VIEWS += [_View("plongée", "front-elevated"), _View("3/4", "front-left-eye")]


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ({"angle": "de profil"}, "profil"),
        ({"angle": "de dos"}, "dos"),
        ({"angle": "de trois quarts"}, "3/4"),  # le côté ne compte pas
        ({"angle": "en plongée"}, "plongée"),
        ({"angle": "de face"}, "principale"),
        ({"angle": "vue subjective"}, "principale"),  # pas d'angle : la principale
        ({}, "principale"),
        ({"angle": "de face", "plan": "plongée"}, "plongée"),
    ],
)
def test_closest_tagged_view_is_chosen(direction: dict[str, str], expected: str) -> None:
    view = closest_view(VIEWS, CATALOG, direction_target(CATALOG, direction))
    assert view is not None and view.name == expected


def test_no_tagged_view_falls_back_to_the_main_one() -> None:
    views = [_View("principale"), _View("autre")]
    assert closest_view(views, CATALOG, direction_target(CATALOG, {"angle": "de dos"})) is views[0]
    assert closest_view([], CATALOG, None) is None


# --- API (mock) -----------------------------------------------------------------------------
def _presets_with(tmp_path: Path, **changes: Any) -> Path:
    presets = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, presets)
    path = presets / "camera_loras.yaml"
    data = yaml.safe_load(path.read_text())
    data.update(changes)
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    return presets


def test_camera_loras_endpoint(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    out = _ok(c.get("/presets/camera-loras"))
    assert out["angle_problem"] is None and out["workflow_tier"] == "Qualité"
    assert out["tier_label"] == QUALITY_TIER_LABEL and "0,8" in out["weight_hint"]
    by_id = {lo["id"]: lo for lo in out["loras"]}
    assert {lo.file for lo in CATALOG.loras} == {lo["file"] for lo in out["loras"]}
    assert "qwen-image-edit-ref-qualite" in by_id["anime-consistency"]["workflows"]
    assert "qwen-image-turbo" not in by_id["anime-consistency"]["workflows"]
    assert [a["id"] for a in out["angles"]] == [a.id for a in CATALOG.angles]


def test_change_angle_adds_one_version_and_keeps_the_others(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    assert MVA is not None
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    p1, p2, _ = data["panels"]
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"count": 2}), 202)
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
    before = _ok(c.get(f"/panels/{p1['id']}/images"))
    other = _ok(c.get(f"/panels/{p2['id']}/images"))
    chosen = next(i for i in before if i["selected"])

    [job] = _ok(c.post(f"/panels/{p1['id']}/change-angle", json={"angle": "right-elevated", "weight": 0.8}), 202)
    assert job["params"]["preset"] == CATALOG.workflow and job["params"]["angle"] == "right-elevated"
    _wait(c)
    after = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert after[:2] == before  # versions existantes intactes (choix compris)
    new = after[2]
    assert (new["version"], new["selected"], new["tier"]) == (3, False, "Qualité")
    camera = CATALOG.angle("right-elevated").camera  # type: ignore[union-attr]
    assert new["params"]["prompt"].startswith(f"{MVA.trigger} {camera}")
    assert new["params"]["camera"]["angle"]["id"] == "right-elevated"
    [ref] = new["params"]["reference_images"]
    assert (ref["kind"], ref["image_id"]) == ("panel", chosen["id"])
    sent = list(comfy.prompts.values())[-1]
    [loader] = [
        n for n in sent.values() if n["class_type"] == "LoraLoaderModelOnly" and n["inputs"]["lora_name"] == MVA.file
    ]
    assert loader["inputs"]["strength_model"] == 0.8
    assert sent["9"]["inputs"]["steps"] == CATALOG.steps
    assert _ok(c.get(f"/panels/{p2['id']}/images")) == other  # les autres cases ne bougent pas

    # Depuis une version précise ; le LoRA v1 de repli.
    v1 = next(lo for lo in CATALOG.angle_loras if not lo.default)
    [job2] = _ok(
        c.post(
            f"/panels/{p1['id']}/change-angle",
            json={"angle": "back-eye", "source_image_id": before[1]["id"], "lora": v1.id},
        ),
        202,
    )
    _wait(c)
    sent = list(comfy.prompts.values())[-1]
    assert v1.file in [n["inputs"].get("lora_name") for n in sent.values()]
    assert _ok(c.get(f"/jobs/{job2['id']}"))["status"] == "succeeded"


def test_change_angle_errors(make_client: Callable[..., TestClient], tmp_path: Path) -> None:  # noqa: F811
    c = make_client()
    p1 = setup_chapter(c)["panels"][0]
    resp = c.post(f"/panels/{p1['id']}/change-angle", json={"angle": "back-eye"})
    assert resp.status_code == 422 and "génère d'abord" in resp.json()["errors"][0]["message"]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    resp = c.post(f"/panels/{p1['id']}/change-angle", json={"angle": "nulle-part"})
    assert resp.status_code == 422 and "angle de caméra inconnu" in resp.json()["errors"][0]["message"]

    # Palier non testé (Turbo) : refusé avec la raison, rien en file.
    turbo = make_client(mangaka_presets_dir=_presets_with(tmp_path, workflow="qwen-image-edit-ref-turbo"))
    q1 = setup_chapter(turbo)["panels"][0]
    _ok(turbo.post(f"/panels/{q1['id']}/generate"), 202)
    _wait(turbo)
    assert _ok(turbo.get("/presets/camera-loras"))["angle_problem"] == QUALITY_TIER_LABEL
    resp = turbo.post(f"/panels/{q1['id']}/change-angle", json={"angle": "back-eye"})
    assert resp.status_code == 422 and QUALITY_TIER_LABEL.lower() in resp.json()["errors"][0]["message"].lower()
    assert len(_ok(turbo.get(f"/panels/{q1['id']}/images"))) == 1


def test_new_angle_view_waits_for_validation_then_is_stored_and_tagged(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    assert MVA is not None
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    aiko = data["aiko"]
    main = _ok(c.get(f"/characters/{aiko['id']}"))["reference_images"][0]
    assert main["angle"] is None
    [job] = _ok(c.post(f"/characters/{aiko['id']}/angle-views", json={"angle": "right-eye"}), 202)
    assert job["params"]["start_image_id"] == main["id"] and job["params"]["preset"] == CATALOG.workflow
    _wait(c)
    done = _ok(c.get(f"/jobs/{job['id']}"))
    assert done["status"] == "succeeded"
    assert "en attente de validation" in done["message"] and "rangée dans la fiche" not in done["message"]
    # Candidate de l'historique, pas encore parmi les vues de la fiche.
    views = _ok(c.get(f"/characters/{aiko['id']}"))["reference_images"]
    assert [v["angle"] for v in views] == [None]
    sent = list(comfy.prompts.values())[-1]
    assert sent["6"]["inputs"]["prompt"].startswith(MVA.trigger)
    assert MVA.file in [n["inputs"].get("lora_name") for n in sent.values()]
    studio = _ok(c.get(f"/characters/{aiko['id']}/reference-variants"))
    [variant] = studio["variants"]
    assert not variant["kept"] and variant["params"]["camera"]["angle"]["id"] == "right-eye"

    # « Valider » : rangée parmi les vues, étiquetée par son angle.
    kept = _ok(c.post(f"/reference-variants/{variant['id']}/keep"), 201)
    assert [v["angle"] for v in kept["reference_images"]] == [None, "right-eye"]
    [variant] = _ok(c.get(f"/characters/{aiko['id']}/reference-variants"))["variants"]
    assert variant["kept"]

    # Étiquette posée à la main, puis retirée ; angle inconnu refusé.
    tagged = _ok(c.put(f"/characters/{aiko['id']}/images/{main['id']}/angle", json={"angle": "front-eye"}))
    assert tagged["reference_images"][0]["angle"] == "front-eye"
    bad = c.put(f"/characters/{aiko['id']}/images/{main['id']}/angle", json={"angle": "nulle-part"})
    assert bad.status_code == 422
    cleared = _ok(c.put(f"/characters/{aiko['id']}/images/{main['id']}/angle", json={"angle": None}))
    assert cleared["reference_images"][0]["angle"] is None

    # Fiche sans image : rien à faire tourner.
    kenji = next(ch for ch in _ok(c.get(f"/projects/{data['series']['id']}/characters")) if ch["name"] == "Kenji")
    resp = c.post(f"/characters/{kenji['id']}/angle-views", json={"angle": "right-eye"})
    assert resp.status_code == 422 and "aucune image" in resp.json()["errors"][0]["message"]


def test_panel_uses_the_view_closest_to_its_art_direction_angle(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    aiko, p1 = data["aiko"], data["panels"][0]
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("dos.png", png_bytes(), "image/png"))]), 201)
    views = _ok(c.get(f"/characters/{aiko['id']}"))["reference_images"]
    _ok(c.put(f"/characters/{aiko['id']}/images/{views[1]['id']}/angle", json={"angle": "back-eye"}))

    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    [first] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert [r["image_id"] for r in first["params"]["reference_images"]] == [views[0]["id"]]  # pas d'angle : principale

    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        panel = session.get(Panel, p1["id"])
        assert panel is not None
        page = panel.page
        session.add(
            PageDirection(
                page_id=page.id,
                chapter_id=page.chapter_id,
                project_id=page.chapter.project_id,
                values={},
                applied={"panels": [{"panel_id": panel.id, "angle": "de dos"}]},
            )
        )
        session.commit()
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    second = _ok(c.get(f"/panels/{p1['id']}/images"))[1]
    [ref] = second["params"]["reference_images"]
    assert (ref["image_id"], ref["angle"]) == (views[1]["id"], "back-eye")


def test_anime_consistency_switch_per_series(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    assert ANIME is not None
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    series, p1 = data["series"], data["panels"][1]  # Kenji : sans référence (palier Qualité texte → image)
    assert series["anime_consistency"] is False and series["anime_consistency_problem"] is None
    on = _ok(c.patch(f"/projects/{series['id']}", json={"anime_consistency": True}))
    assert on["anime_consistency"] is True
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    [v] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert ANIME.file in [lo["name"] for lo in v["params"]["loras"]]
    sent = list(comfy.prompts.values())[-1]
    assert ANIME.file in [n["inputs"].get("lora_name") for n in sent.values()]

    # Série en Turbo : pas de LoRA, la raison est donnée par la série et notée sur la version.
    turbo = _ok(c.patch(f"/projects/{series['id']}", json={"workflow_preset": "qwen-image-turbo"}))
    assert turbo["anime_consistency_problem"] == QUALITY_TIER_LABEL
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    v2 = _ok(c.get(f"/panels/{p1['id']}/images"))[1]
    assert ANIME.file not in [lo["name"] for lo in v2["params"]["loras"]]
    assert QUALITY_TIER_LABEL.lower() in v2["params"]["camera"]["skipped"][0]
    assert c.patch(f"/projects/{series['id']}", json={"anime_consistency": None}).status_code == 422
