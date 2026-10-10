"""Verrouillage de composition (ControlNet Union de Qwen-Image, patch de modèle) : graphes, verrou en mock,
passage au propre img2img / ControlNet, ComfyUI sans le patch."""

from __future__ import annotations

import io
import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageStat

from mangaka_engine.pipeline.composition import unavailable_control
from mangaka_engine.pipeline.generation import composition_params
from mangaka_engine.presets import (
    ControlInput,
    LoraSpec,
    PresetError,
    PresetRegistry,
    build_control_map_workflow,
    build_workflow,
)
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.store.models import PanelImage
from tests.conftest import PRESETS_DIR, png_bytes
from tests.test_generation import _ok, _wait, make_client, setup_chapter  # noqa: F401 — fixture

REG = PresetRegistry.load(PRESETS_DIR)
PARAMS = {
    "positive_prompt": "plan moyen, Aiko sur un toit",
    "negative_prompt": "texte",
    "seed": 777,
    "width": 832,
    "height": 1216,
}
LORAS = [LoraSpec("encre.safetensors", 0.7, "style"), LoraSpec("aiko-v3.safetensors", 0.9, "Aiko")]
GUIDE = "mangaka/guide_case1_v2.png"
# Palier → (pendant ControlNet sans références, avec références).
TIERS = {
    "qwen-image-turbo": ("qwen-image-turbo-controlnet", "qwen-image-edit-ref-turbo-controlnet"),
    "qwen-image-base-rapide": ("qwen-image-base-rapide-controlnet", "qwen-image-edit-ref-rapide-controlnet"),
    "qwen-image-base": ("qwen-image-base-controlnet", "qwen-image-edit-ref-controlnet"),
}
CONTROLNET = [p for pair in TIERS.values() for p in pair]


# --- presets et graphes -----------------------------------------------------------------------
def test_controlnet_presets_are_loaded_and_paired() -> None:
    assert REG.issues == []
    for base, (control, control_refs) in TIERS.items():
        assert REG.workflow(base).preset.with_control == control
        refs = REG.workflow(base).preset.with_references
        assert refs is not None and REG.workflow(refs).preset.with_control == control_refs
        assert REG.workflow(control).preset.with_references == control_refs
        for preset_id in (control, control_refs):
            preset = REG.workflow(preset_id).preset
            assert preset.role == "controle" and preset.control is not None
            assert preset.tier is not None and preset.tier.name == REG.workflow(base).preset.tier.name
            assert preset.tier.choice is None  # jamais proposé comme palier de série
            assert preset.control.default_type == "lineart" and preset.control.default_strength == 1.0
            assert {"lineart", "depth", "pose", "scribble"} <= set(preset.control.types)
        assert REG.workflow(control_refs).preset.reference_images


@pytest.mark.parametrize("preset_id", CONTROLNET)
def test_controlnet_graph_patch_between_model_and_sampler(preset_id: str) -> None:
    """Mêmes ids que le palier (1 modèle, 2 encodeur, 6 prompt, 8 latent, 9 sampler, 11 sortie) ; patch,
    prétraitement, image guide, force et graine injectés ; LoRA chaînés AVANT le patch."""
    loaded = REG.workflow(preset_id)
    refs = ["mangaka/perso1_img1.png"] if loaded.preset.reference_images else []
    built = build_workflow(loaded, PARAMS, reference_images=refs, loras=LORAS, control=ControlInput(GUIDE, "pose", 0.8))
    wf = built.workflow
    tier = REG.workflow(preset_id.removesuffix("-controlnet")).workflow
    for node in ("1", "2", "3", "6", "8", "9", "10", "11"):
        assert wf[node]["class_type"] == tier[node]["class_type"], node
    assert wf["1"]["inputs"]["unet_name"] == tier["1"]["inputs"]["unet_name"]
    assert (wf["8"]["inputs"]["width"], wf["8"]["inputs"]["height"]) == (832, 1216)
    assert wf["9"]["inputs"]["seed"] == 777 and wf["9"]["inputs"]["steps"] == tier["9"]["inputs"]["steps"]
    assert wf["9"]["inputs"]["latent_image"] == ["8", 0] and wf["9"]["inputs"]["denoise"] == 1
    # Patch : chargeur (fichier du patch), application entre modèle et cache / échantillonneur.
    assert wf["40"]["class_type"] == "ModelPatchLoader"
    assert wf["40"]["inputs"]["name"] == "qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors"
    apply = wf["44"]
    assert apply["class_type"] == "QwenImageDiffsynthControlnet"
    assert apply["inputs"]["model_patch"] == ["40", 0] and apply["inputs"]["vae"] == ["3", 0]
    assert apply["inputs"]["strength"] == 0.8 and apply["inputs"]["image"] == ["43", 0]
    assert wf["4"]["inputs"]["model"] == ["44", 0] and wf["9"]["inputs"]["model"] == ["4", 0]
    # Image guide → prétraitement du type choisi → carte à la taille de la case.
    assert wf["41"]["class_type"] == "LoadImage" and wf["41"]["inputs"]["image"] == GUIDE
    assert wf["42"]["class_type"] == "DWPreprocessor" and wf["42"]["inputs"]["image"] == ["41", 0]
    assert wf["43"]["class_type"] == "ImageScale" and wf["43"]["inputs"]["image"] == ["42", 0]
    assert (wf["43"]["inputs"]["width"], wf["43"]["inputs"]["height"]) == (832, 1216)
    assert "45" not in wf and "45" in built.removed_nodes  # aperçu de la carte : pas dans la génération
    # LoRA : modèle → style → Aiko → patch (jamais après le patch).
    chain = [k for k, n in wf.items() if n["class_type"] == "LoraLoaderModelOnly"]
    assert [wf[k]["inputs"]["lora_name"] for k in chain] == ["encre.safetensors", "aiko-v3.safetensors"]
    assert wf[chain[0]]["inputs"]["model"] == ["1", 0] and wf[chain[1]]["inputs"]["model"] == [chain[0], 0]
    assert apply["inputs"]["model"] == [chain[1], 0]
    assert built.control == {
        "type": "pose",
        "name": "Pose",
        "strength": 0.8,
        "preprocessor": "DWPreprocessor",
        "patch": wf["40"]["inputs"]["name"],
        "image": GUIDE,
    }
    if refs:
        assert wf["20"]["inputs"]["image"] == refs[0] and "21" not in wf


def test_control_types_and_errors() -> None:
    loaded = REG.workflow("qwen-image-turbo-controlnet")
    settings = loaded.preset.control
    assert settings is not None
    for type_id, ctype in settings.types.items():
        wf = build_workflow(loaded, PARAMS, control=ControlInput(GUIDE, type_id, 1.0)).workflow
        if ctype.class_type is None:  # « carte déjà prête » : pas de prétraitement
            assert "42" not in wf and wf["43"]["inputs"]["image"] == ["41", 0]
        else:
            assert wf["42"]["class_type"] == ctype.class_type
            assert wf["42"]["inputs"] == {**ctype.inputs, ctype.image_input: ["41", 0]}
        if not ctype.post:
            assert "ImageInvert" not in {n["class_type"] for n in wf.values()}, type_id
    # Seul « Trait » inverse sa carte ; « Carte déjà prête » n'est jamais retouchée.
    assert [t for t, c in settings.types.items() if c.post] == ["lineart"]
    with pytest.raises(PresetError, match="attend une image guide"):
        build_workflow(loaded, PARAMS)
    with pytest.raises(PresetError, match="type de contrôle inconnu"):
        build_workflow(loaded, PARAMS, control=ControlInput(GUIDE, "aquarelle", 1.0))
    with pytest.raises(PresetError, match="force du contrôle"):
        build_workflow(loaded, PARAMS, control=ControlInput(GUIDE, "lineart", 3))
    with pytest.raises(PresetError, match="n'accepte pas d'image guide"):
        build_workflow(REG.workflow("qwen-image-turbo"), PARAMS, control=ControlInput(GUIDE, "lineart", 1.0))


def test_control_map_workflow_keeps_only_the_preprocessing() -> None:
    built = build_control_map_workflow(
        REG.workflow("qwen-image-edit-ref-turbo-controlnet"), GUIDE, "depth", 640, 960, filename_prefix="x/controle"
    )
    wf = built.workflow
    assert {k: n["class_type"] for k, n in wf.items()} == {
        "41": "LoadImage",
        "42": "DepthAnythingV2Preprocessor",
        "43": "ImageScale",
        "45": "SaveImage",
    }
    assert built.output_node == "45" and wf["45"]["inputs"]["filename_prefix"] == "x/controle"
    assert (wf["43"]["inputs"]["width"], wf["43"]["inputs"]["height"]) == (640, 960)


@pytest.mark.parametrize("preset_id", CONTROLNET)
def test_lineart_map_is_inverted_before_resize(preset_id: str) -> None:
    """« Trait » : LineArtPreprocessor (trait blanc sur fond noir) → ImageInvert → ImageScale → patch."""
    loaded = REG.workflow(preset_id)
    settings = loaded.preset.control
    assert settings is not None and settings.default_type == "lineart"
    refs = ["mangaka/ref1.png"] if loaded.preset.reference_images else []
    built = build_workflow(
        loaded, PARAMS, reference_images=refs, loras=LORAS, control=ControlInput(GUIDE, "lineart", 1.0)
    )
    wf = built.workflow
    [inv] = [k for k, n in wf.items() if n["class_type"] == "ImageInvert"]
    assert wf[inv]["inputs"] == {"image": [settings.preprocessor, 0]}
    assert wf[settings.preprocessor]["class_type"] == "LineArtPreprocessor"
    assert settings.resize is not None and wf[settings.resize]["inputs"]["image"] == [inv, 0]
    assert wf[settings.apply.node]["inputs"]["image"] == [settings.resize, 0]
    assert not any(v == [settings.preprocessor, 0] for k, n in wf.items() if k != inv for v in n["inputs"].values())
    assert built.control is not None and built.control["post"] == ["ImageInvert"]
    assert all(isinstance(n, dict) and "class_type" in n and "inputs" in n for n in wf.values())

    # Aperçu de la carte : la carte réellement envoyée au modèle, donc inversée.
    preview = build_control_map_workflow(loaded, GUIDE, "lineart", 640, 960)
    assert {k: n["class_type"] for k, n in preview.workflow.items()} == {
        "41": "LoadImage",
        "42": "LineArtPreprocessor",
        inv: "ImageInvert",
        "43": "ImageScale",
        "45": "SaveImage",
    }
    assert preview.workflow["43"]["inputs"]["image"] == [inv, 0]
    assert preview.workflow["45"]["inputs"]["images"] == ["43", 0]


def test_composition_params_replays_the_control() -> None:
    img = PanelImage(
        params={
            "prompt": "p",
            "composition": {
                "source": "croquis",
                "image_id": 4,
                "version": 1,
                "path": None,
                "type": "lineart",
                "strength": 0.9,
                "method": "controlnet",
                "locked": False,
            },
        }
    )
    assert composition_params(img) == {
        "control": {"source": "croquis", "image_id": 4, "version": 1, "path": None, "type": "lineart", "strength": 0.9},
        "locked": False,
        "sketch_prompt": "p",
    }


# --- verrouiller → régénérer (mock) ------------------------------------------------------------
def _images(c: TestClient, panel_id: int) -> list[dict[str, Any]]:
    return _ok(c.get(f"/panels/{panel_id}/images"))


def _sketch_and_validate(c: TestClient, panel_id: int) -> dict[str, Any]:
    _ok(c.post(f"/panels/{panel_id}/sketch"), 202)
    _wait(c)
    [sketch] = [i for i in _images(c, panel_id) if i["kind"] == "croquis"][-1:]
    _ok(c.post(f"/panels/{panel_id}/sketch/validate"))
    return sketch


def test_lock_from_sketch_then_regenerate(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    p1, p2, _ = data["panels"]
    sketch = _sketch_and_validate(c, p2["id"])

    detail = _ok(c.post(f"/panels/{p2['id']}/composition-lock", json={"source": "croquis"}))
    lock = detail["composition_lock"]
    assert lock["source"] == "croquis" and lock["image_id"] == sketch["id"]
    assert lock["source_label"] == f"croquis v{sketch['version']}" and lock["source_url"] == sketch["url"]
    assert (lock["type"], lock["type_name"], lock["strength"]) == ("lineart", "Trait", 1.0)
    assert lock["preset"] == "qwen-image-turbo-controlnet" and lock["problem"] is None
    assert lock["preview"]["status"] in ("pending", "running", "ready") and lock["preview"]["job_id"]

    # Aperçu de la carte de contrôle : prétraitement seul, enregistré sur le verrou.
    _wait(c)
    lock = _ok(c.get(f"/panels/{p2['id']}"))["composition_lock"]
    assert lock["preview"]["status"] == "ready" and lock["preview"]["type"] == "lineart"
    preview = c.get(lock["preview"]["url"])
    assert preview.status_code == 200
    map_wf = next(wf for wf in comfy.prompts.values() if "9" not in wf)
    assert {n["class_type"] for n in map_wf.values()} == {
        "LoadImage",
        "LineArtPreprocessor",
        "ImageInvert",
        "ImageScale",
        "SaveImage",
    }
    # Carte inversée : trait noir sur fond clair (le patch encode la carte avec le VAE).
    with Image.open(io.BytesIO(preview.content)) as img:
        assert ImageStat.Stat(img.convert("L")).mean[0] > 128
    # Badge « composition verrouillée » dans la liste des pages.
    pages = _ok(c.get(f"/chapters/{data['chapter']['id']}/pages"))
    flags = {p["id"]: p["composition_lock"] for pg in pages for p in pg["panels"]}
    assert flags == {p1["id"]: None, p2["id"]: "lineart", data["panels"][2]["id"]: None}

    # Régénérer : pendant ControlNet du palier, image guide = le croquis verrouillé.
    [job] = _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    assert job["params"]["preset"] == "qwen-image-turbo-controlnet" and job["params"]["locked"] is True
    assert job["params"]["base_preset"] == "qwen-image-turbo"
    assert job["params"]["control"]["image_id"] == sketch["id"] and job["params"]["control"]["type"] == "lineart"
    _wait(c)
    final = next(i for i in _images(c, p2["id"]) if i["kind"] == "final")
    comp = final["params"]["composition"]
    assert comp["method"] == "controlnet" and comp["source"] == "croquis" and comp["image_id"] == sketch["id"]
    assert comp["type"] == "lineart" and comp["type_name"] == "Trait" and comp["strength"] == 1.0
    assert comp["locked"] is True and final["params"]["sketch_image_id"] == sketch["id"]
    assert final["params"]["control"]["preprocessor"] == "LineArtPreprocessor"
    assert final["params"]["control"]["patch"].endswith(".safetensors")
    wf = comfy.prompts[final["params"]["comfyui_prompt_id"]]
    assert comfy.uploads[wf["41"]["inputs"]["image"]] == c.get(sketch["url"]).content
    assert wf["44"]["class_type"] == "QwenImageDiffsynthControlnet" and wf["44"]["inputs"]["strength"] == 1.0
    assert (final["width"], final["height"]) == (wf["8"]["inputs"]["width"], wf["8"]["inputs"]["height"])

    # « Régénérer en Qualité » aussi : pendant ControlNet du palier Qualité.
    [job] = _ok(c.post(f"/panels/{p2['id']}/regenerate-quality"), 202)
    assert job["params"]["preset"] == "qwen-image-base-controlnet"
    # La case 1 (Aiko, références) verrouillée sur une image importée → variante avec références.
    upload = {"file": ("pose.png", png_bytes((300, 400)), "image/png")}
    detail = _ok(c.post(f"/panels/{p1['id']}/composition-lock/import", files=upload, data={"type": "pose"}))
    lock = detail["composition_lock"]
    assert lock["source"] == "import" and lock["source_label"] == "image importée" and lock["type"] == "pose"
    assert lock["preset"] == "qwen-image-edit-ref-turbo-controlnet"
    assert c.get(lock["source_url"]).status_code == 200
    [job] = _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    assert job["params"]["preset"] == "qwen-image-edit-ref-turbo-controlnet"
    assert job["params"]["control"]["source"] == "import" and job["params"]["control"]["path"]
    _wait(c)
    final1 = next(i for i in _images(c, p1["id"]) if i["kind"] == "final")
    assert final1["params"]["composition"]["source"] == "import" and "sketch_image_id" not in final1["params"]
    assert final1["params"]["reference_images"]  # les références d'Aiko sont toujours envoyées

    # Déverrouiller : composition libre, palier normal.
    detail = _ok(c.delete(f"/panels/{p2['id']}/composition-lock"))
    assert detail["composition_lock"] is None
    [job] = _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    assert job["params"]["preset"] == "qwen-image-turbo" and "control" not in job["params"]
    _wait(c)


class MapGatedComfy(MockComfyUIClient):
    """ComfyUI factice qui retient chaque carte de contrôle (graphe sans KSampler) tant que `hold` est posé."""

    def __init__(self) -> None:
        super().__init__()
        self.hold = threading.Event()
        self.release = threading.Event()
        self.started = threading.Event()
        self.fetched = 0

    def wait_for_images(self, prompt_id: str, output_node: str, **kw: Any):  # type: ignore[no-untyped-def]
        if self.hold.is_set() and "9" not in self.prompts[prompt_id]:
            self.started.set()
            assert self.release.wait(10)
        return super().wait_for_images(prompt_id, output_node, **kw)

    def fetch_image(self, ref: Any) -> bytes:  # chaque image diffère, pour reconnaître la carte servie
        self.fetched += 1
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (self.fetched * 40 % 256, 30, 30)).save(buf, format="PNG")
        return buf.getvalue()


def test_preview_url_follows_the_served_map(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    """L'aperçu est servi « immutable » : son URL ne change qu'avec la carte réellement servie."""
    comfy = MapGatedComfy()
    c = make_client(comfy)
    data = setup_chapter(c)
    p2 = data["panels"][1]
    _sketch_and_validate(c, p2["id"])
    _ok(c.post(f"/panels/{p2['id']}/composition-lock", json={"source": "croquis"}))
    _wait(c)
    before = _ok(c.get(f"/panels/{p2['id']}"))["composition_lock"]["preview"]
    assert before["status"] == "ready" and (before["type"], before["type_name"]) == ("lineart", "Trait")
    old_map = c.get(before["url"])
    assert "immutable" in old_map.headers["cache-control"]

    # Changement de type : tant que la nouvelle carte n'est pas prête, l'ancienne reste servie sous la même URL.
    comfy.hold.set()
    lock = _ok(c.patch(f"/panels/{p2['id']}/composition-lock", json={"type": "pose"}))["composition_lock"]
    assert comfy.started.wait(10)
    for preview in (lock["preview"], _ok(c.get(f"/panels/{p2['id']}"))["composition_lock"]["preview"]):
        assert preview["job_id"] != before["job_id"] and preview["status"] in ("pending", "running")
        assert (preview["url"], preview["type"], preview["type_name"]) == (before["url"], "lineart", "Trait")
    assert c.get(before["url"]).content == old_map.content

    # Carte terminée : nouvelle URL, nouveau type, et le fichier servi est bien la nouvelle carte.
    comfy.release.set()
    _wait(c)
    after = _ok(c.get(f"/panels/{p2['id']}"))["composition_lock"]["preview"]
    assert after["status"] == "ready" and (after["type"], after["type_name"]) == ("pose", "Pose")
    assert after["url"] != before["url"] and after["url"].endswith(f"?v={after['job_id']}")
    assert c.get(after["url"]).content != old_map.content


def test_lock_from_version_update_and_delete_source(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p3 = data["panels"][2]
    _ok(c.post(f"/panels/{p3['id']}/generate"), 202)
    _wait(c)
    [v1] = _images(c, p3["id"])
    detail = _ok(
        c.post(
            f"/panels/{p3['id']}/composition-lock",
            json={"source": "version", "image_id": v1["id"], "type": "depth", "strength": 0.6},
        )
    )
    lock = detail["composition_lock"]
    assert (lock["source_label"], lock["type_name"], lock["strength"]) == ("version 1", "Profondeur", 0.6)
    _wait(c)
    first_job = _ok(c.get(f"/panels/{p3['id']}"))["composition_lock"]["preview"]["job_id"]

    # Changer la force ne recalcule pas la carte ; changer de type, si.
    lock = _ok(c.patch(f"/panels/{p3['id']}/composition-lock", json={"strength": 1.3}))["composition_lock"]
    assert lock["strength"] == 1.3 and lock["preview"]["job_id"] == first_job
    lock = _ok(c.patch(f"/panels/{p3['id']}/composition-lock", json={"type": "pose"}))["composition_lock"]
    assert lock["type"] == "pose" and lock["preview"]["job_id"] != first_job
    _wait(c)
    lock = _ok(c.get(f"/panels/{p3['id']}"))["composition_lock"]
    assert lock["preview"]["status"] == "ready" and lock["preview"]["type"] == "pose"

    job, second = _ok(c.post(f"/panels/{p3['id']}/generate", json={"count": 2}), 202)
    assert second["params"]["control"] == job["params"]["control"]
    assert job["params"]["control"] == {
        "source": "version",
        "image_id": v1["id"],
        "version": 1,
        "path": None,
        "type": "pose",
        "strength": 1.3,
    }
    _wait(c)
    v2 = _images(c, p3["id"])[1]
    assert v2["params"]["composition"]["source"] == "version" and v2["params"]["composition"]["image_id"] == v1["id"]
    with Image.open(io.BytesIO(c.get(v2["url"]).content)) as im:
        assert im.size == (v2["width"], v2["height"])

    # Erreurs lisibles.
    bad = c.post(f"/panels/{p3['id']}/composition-lock", json={"source": "version"})
    assert bad.status_code == 422 and "choisis la version" in bad.text
    bad = c.post(f"/panels/{p3['id']}/composition-lock", json={"source": "croquis"})
    assert bad.status_code == 422 and "Aucun croquis validé" in bad.text
    bad = c.patch(f"/panels/{p3['id']}/composition-lock", json={"type": "aquarelle"})
    assert bad.status_code == 422 and "Type de contrôle inconnu" in bad.text
    bad = c.patch(f"/panels/{p3['id']}", json={"generation_preset": "qwen-image-turbo-controlnet"})
    assert bad.status_code == 422 and "verrouille plutôt" in bad.text

    # Supprimer l'image guide déverrouille la case (jamais de case cassée).
    assert c.delete(f"/panel-images/{v1['id']}").status_code == 204
    assert _ok(c.get(f"/panels/{p3['id']}"))["composition_lock"] is None
    [job] = _ok(c.post(f"/panels/{p3['id']}/generate"), 202)
    assert job["params"]["preset"] == "qwen-image-turbo"
    _wait(c)


# --- passage au propre : img2img ou ControlNet --------------------------------------------------
def test_clean_mode_img2img_or_controlnet(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    series = data["series"]
    p1, p2, p3 = data["panels"]
    assert series["clean_mode"] == "img2img" and series["clean_control"] is None
    for pid in (p2["id"], p3["id"], p1["id"]):
        _sketch_and_validate(c, pid)

    # img2img (défaut de #51).
    [job] = _ok(c.post(f"/panels/{p3['id']}/clean"), 202)
    assert job["params"]["preset"] == "qwen-image-turbo-from-sketch" and "control" not in job["params"]

    # ControlNet : pendant ControlNet du palier, croquis validé comme image guide, même graine.
    bad = c.patch(f"/projects/{series['id']}", json={"clean_mode": "controlnet", "clean_control": "aquarelle"})
    assert bad.status_code == 422 and "type de contrôle inconnu" in bad.text
    got = _ok(c.patch(f"/projects/{series['id']}", json={"clean_mode": "controlnet", "clean_control": "scribble"}))
    assert (got["clean_mode"], got["clean_control"]) == ("controlnet", "scribble")
    sketch2 = [i for i in _images(c, p2["id"]) if i["kind"] == "croquis"][-1]
    [job] = _ok(c.post(f"/panels/{p2['id']}/clean"), 202)
    params = job["params"]
    assert params["preset"] == "qwen-image-turbo-controlnet" and "denoise" not in params
    assert params["seed"] == sketch2["seed"] and params["source_image_id"] == sketch2["id"]
    assert params["control"]["source"] == "croquis" and params["control"]["image_id"] == sketch2["id"]
    assert params["control"]["type"] == "scribble"
    # Case avec références : variante ControlNet avec références.
    res = _ok(c.post(f"/pages/{data['pages'][0]['id']}/clean"), 202)
    assert [j["params"]["preset"] for j in res["jobs"]] == ["qwen-image-edit-ref-turbo-controlnet"]
    _wait(c)
    final = next(i for i in _images(c, p2["id"]) if i["kind"] == "final")
    assert final["params"]["prompt"] == sketch2["params"]["prompt"] and final["seed"] == sketch2["seed"]
    comp = final["params"]["composition"]
    assert comp["method"] == "controlnet" and comp["image_id"] == sketch2["id"] and comp["locked"] is False
    assert final["params"]["control"]["preprocessor"] == "ScribblePreprocessor"
    page = _ok(c.get(f"/chapters/{data['chapter']['id']}/pages"))[0]
    assert next(p for p in page["panels"] if p["id"] == p2["id"])["sketch_cleaned"]


# --- ComfyUI sans le patch ControlNet -----------------------------------------------------------
def _unavailable(c: TestClient) -> None:
    status = unavailable_control("http", "nœud QwenImageDiffsynthControlnet absent de ce ComfyUI")
    c.app.state.ctx.control_catalog.store(status)  # type: ignore[attr-defined]


def test_missing_controlnet_never_breaks_a_panel(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1, p2, p3 = data["panels"]
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
    [v1] = _images(c, p2["id"])
    _ok(c.post(f"/panels/{p2['id']}/composition-lock", json={"source": "version", "image_id": v1["id"]}))
    _wait(c)

    _unavailable(c)
    status = _ok(c.get("/comfyui/control"))
    assert not status["available"] and "QwenImageDiffsynthControlnet" in status["message"]
    # Verrouiller : refusé, message clair en français.
    res = c.post(f"/panels/{p3['id']}/composition-lock", json={"source": "version", "image_id": v1["id"]})
    assert res.status_code == 422
    assert "Verrouillage de composition indisponible" in res.json()["errors"][0]["message"]
    # Régénérer une case déjà verrouillée : refusé avec la marche à suivre.
    res = c.post(f"/panels/{p2['id']}/generate")
    assert res.status_code == 422 and "Déverrouille la case" in res.json()["errors"][0]["message"]
    # La page se génère quand même : la case verrouillée est laissée de côté, les autres partent.
    out = _ok(c.post(f"/pages/{data['pages'][0]['id']}/generate", json={"force": True}), 202)
    assert out["panel_ids"] == [p1["id"]] and out["skipped"] == 1
    # Passage au propre par ControlNet refusé ; en img2img, il marche.
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"clean_mode": "controlnet"}))
    _sketch_and_validate(c, p3["id"])
    res = c.post(f"/panels/{p3['id']}/clean")
    assert res.status_code == 422 and "img2img" in res.json()["errors"][0]["message"]
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"clean_mode": "img2img"}))
    _ok(c.post(f"/panels/{p3['id']}/clean"), 202)
    # Déverrouiller rend la case générable.
    _ok(c.delete(f"/panels/{p2['id']}/composition-lock"))
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
