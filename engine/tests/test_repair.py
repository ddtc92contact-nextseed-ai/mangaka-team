"""Réparation ciblée (inpainting) : masque, recollage au pixel près, graphe ComfyUI, API (tout simulé)."""

from __future__ import annotations

import base64
import io
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.inpaint import (
    Region,
    build_mask,
    decode_png,
    influence_zone,
    is_sketch,
    recompose,
    soften_mask,
)
from mangaka_engine.pipeline.prompt import PromptCharacter
from mangaka_engine.pipeline.repair import inpaint_preset_id, repair_prompt
from mangaka_engine.presets import LoraSpec, PresetError, PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.store.models import PanelImage
from tests.conftest import PRESETS_DIR
from tests.test_generation import _job, _ok, _providers, _wait, setup_chapter

REG = PresetRegistry.load(PRESETS_DIR)


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(comfy: MockComfyUIClient | None = None) -> TestClient:
        c = TestClient(create_app(make_settings(), providers=_providers(comfy or MockComfyUIClient())))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


INPAINT = ("qwen-image-inpaint", "qwen-image-inpaint-rapide", "qwen-image-inpaint-turbo")


def _noise(size: tuple[int, int], seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8), "RGB")


# --- masque et recollage (fonctions pures) ----------------------------------------------------
@pytest.mark.parametrize(("grow", "feather"), [(0, 0), (12, 0), (0, 9), (24, 16), (5, 40)])
def test_pixels_outside_mask_and_feather_are_identical(grow: int, feather: int) -> None:
    """Critère d'acceptation : hors masque (et hors marge d'adoucissement), pixels identiques à l'original."""
    size = (320, 240)
    source, generated = _noise(size, 1), _noise(size, 2)
    raw = build_mask(size, [Region(100, 60, 160, 130), Region(250, 200, 400, 300)])
    soft = soften_mask(raw, grow, feather)
    out = np.asarray(recompose(source, generated, soft))
    zone = np.asarray(influence_zone(raw, grow, feather)) > 0
    src, gen = np.asarray(source), np.asarray(generated)
    assert (out[~zone] == src[~zone]).all()  # au pixel près hors de la zone d'influence
    core = np.asarray(raw) > 0
    assert (out[core] == gen[core]).all()  # la zone demandée est entièrement repeinte
    assert zone.sum() > core.sum() or (grow, feather) == (0, 0)


def test_soft_mask_grows_and_feathers() -> None:
    raw = build_mask((200, 200), [Region(80, 80, 120, 120)])
    soft = np.asarray(soften_mask(raw, 10, 12))
    assert soft[100, 100] == 255 and soft[100, 75] == 255  # marge de 10 px : encore pleine
    edge = soft[100, 90 - 10 : 80 - 10 - 12 : -1]  # du bord de la marge vers l'extérieur
    assert 0 < soft[100, 66] < 255  # bords fondus : valeurs intermédiaires
    assert list(edge) == sorted(edge, reverse=True)  # décroissant vers l'extérieur
    assert soft[100, 80 - 10 - 12 - 1] == 0 and soft[0, 0] == 0  # rien au-delà de marge + adoucissement
    assert (soften_mask(raw, 0, 0).tobytes()) == raw.tobytes()


def test_build_mask_from_painted_png_alpha_and_luminance() -> None:
    painted = Image.new("RGBA", (50, 40), (0, 0, 0, 0))  # canvas de l'atelier, plus petit que l'image
    ImageDraw.Draw(painted).rectangle((10, 10, 19, 19), fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    painted.save(buf, format="PNG")
    mask = np.asarray(build_mask((100, 80), [Region(-20, 70, 5, 500)], buf.getvalue()))
    assert mask[30, 30] == 255 and mask[50, 50] == 0  # peint (agrandi ×2)
    assert mask[75, 0] == 255 and mask[75, 6] == 0  # rectangle borné à l'image
    gray = Image.new("L", (100, 80), 0)
    ImageDraw.Draw(gray).rectangle((0, 0, 9, 9), fill=255)
    buf = io.BytesIO()
    gray.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    mask = np.asarray(build_mask((100, 80), painted=decode_png(data_url)))
    assert mask[5, 5] == 255 and mask[20, 20] == 0
    assert build_mask((10, 10), [Region(3, 3, 3.4, 9)]).getbbox() is None  # rectangle trop fin : ignoré


def test_recompose_recenters_a_slightly_smaller_comfyui_output() -> None:
    """ComfyUI rogne au multiple du VAE (recadrage centré) : l'image est replacée, pas étirée."""
    source = _noise((101, 99), 3)
    generated = source.crop((2, 1, 98, 97))  # 96 × 96, centré
    soft = soften_mask(build_mask(source.size, [Region(40, 40, 60, 60)]), 0, 0)
    assert recompose(source, generated, soft).tobytes() == source.tobytes()


def test_is_sketch() -> None:
    assert is_sketch({"kind": "croquis"}) and is_sketch({"tier": "Croquis"}) and is_sketch({"sketch": True})
    assert not is_sketch({"tier": "Turbo"}) and not is_sketch(None)


# --- presets et graphe ------------------------------------------------------------------------
def test_inpaint_presets_load_and_each_tier_points_to_its_own() -> None:
    assert REG.issues == []
    for pid in INPAINT:
        assert REG.workflow(pid).preset.is_inpaint
    tiers = {
        "qwen-image-turbo": "qwen-image-inpaint-turbo",
        "qwen-image-edit-ref-turbo": "qwen-image-inpaint-turbo",
        "qwen-image-base-rapide": "qwen-image-inpaint-rapide",
        "qwen-image-edit-ref-rapide": "qwen-image-inpaint-rapide",
        "qwen-image-base": "qwen-image-inpaint",
        "qwen-image-edit-ref": "qwen-image-inpaint",
    }
    for pid, inpaint in tiers.items():
        assert inpaint_preset_id(REG, pid, None) == inpaint
        # mêmes fichiers de modèle que le palier d'origine
        src, rep = REG.workflow(pid).workflow, REG.workflow(inpaint).workflow
        assert src["1"]["inputs"]["unet_name"] == rep["1"]["inputs"]["unet_name"]
        assert src["2"]["inputs"]["clip_name"] == rep["2"]["inputs"]["clip_name"]
    assert inpaint_preset_id(REG, "inconnu", "qwen-image-base-rapide") == "qwen-image-inpaint-rapide"
    assert inpaint_preset_id(REG, None, None) == REG.defaults.workflow_inpaint  # type: ignore[union-attr]


def test_build_inpaint_graph_image_mask_denoise_seed_loras() -> None:
    loaded = REG.workflow("qwen-image-inpaint-turbo")
    inp = loaded.preset.inpaint
    assert inp is not None
    built = build_workflow(
        loaded,
        {"positive_prompt": "main bien dessinée", "negative_prompt": "texte", "seed": 77, "denoise": 0.35},
        reference_images=["mangaka/perso1_img1.png"],
        loras=[LoraSpec("encre.safetensors", 0.7, "style"), LoraSpec("aiko.safetensors", 0.9, "Aiko")],
        inpaint_images=("mangaka/source_img4.png", "mangaka/masque_job9.png"),
    )
    wf = built.workflow
    assert wf[inp.source_image.node]["inputs"]["image"] == "mangaka/source_img4.png"
    assert wf[inp.mask_image.node]["inputs"]["image"] == "mangaka/masque_job9.png"
    sampler = wf["9"]["inputs"]
    assert (sampler["seed"], sampler["denoise"], sampler["steps"]) == (77, 0.35, loaded.preset.defaults["steps"])
    assert wf["6"]["inputs"]["prompt"] == "main bien dessinée"
    # source → VAEEncode → SetLatentNoiseMask (masque) → KSampler
    latent = wf[sampler["latent_image"][0]]
    assert latent["class_type"] == "SetLatentNoiseMask" and latent["inputs"]["mask"] == [inp.mask_image.node, 0]
    encode = wf[latent["inputs"]["samples"][0]]
    assert encode["class_type"] == "VAEEncode" and encode["inputs"]["pixels"] == [inp.source_image.node, 0]
    assert not any(n["class_type"] == "EmptyLatentImage" for n in wf.values())
    # LoRA chaînés entre le modèle et le cache, références inutilisées retirées
    loras = [n for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert [n["inputs"]["lora_name"] for n in loras] == ["encre.safetensors", "aiko.safetensors"]
    assert wf["4"]["inputs"]["model"][0] != "1"
    assert set(built.removed_nodes) == {"21", "22"} and "images.image_2" not in wf["6"]["inputs"]
    assert built.params["denoise"] == 0.35 and "width" not in built.params
    # denoise par défaut du preset (aucune valeur codée dans le moteur)
    default = build_workflow(
        loaded, {"positive_prompt": "x", "seed": 1}, inpaint_images=("mangaka/a.png", "mangaka/b.png")
    )
    assert default.workflow["9"]["inputs"]["denoise"] == loaded.preset.defaults["denoise"]


def test_inpaint_graph_requires_images_and_generation_refuses_them() -> None:
    with pytest.raises(PresetError, match="image source et un masque"):
        build_workflow(REG.workflow("qwen-image-inpaint"), {"positive_prompt": "x", "seed": 1})
    with pytest.raises(PresetError, match="pas un preset de réparation"):
        build_workflow(
            REG.workflow("qwen-image-turbo"),
            {"positive_prompt": "x", "seed": 1, "width": 64, "height": 64},
            inpaint_images=("a", "b"),
        )


@pytest.mark.parametrize("tier", ["", "-rapide", "-turbo"])
def test_inpaint_tiers_share_the_graph(tier: str) -> None:
    qualite, wf = REG.workflow("qwen-image-inpaint").workflow, REG.workflow(f"qwen-image-inpaint{tier}").workflow
    assert {k: n["class_type"] for k, n in qualite.items()} == {k: n["class_type"] for k, n in wf.items()}


def test_inpaint_preset_validation(tmp_path: Path) -> None:
    presets = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, presets)
    path = presets / "workflows" / "qwen-image-inpaint-rapide.yaml"
    data = yaml.safe_load(path.read_text())
    del data["mapping"]["denoise"]
    del data["defaults"]["denoise"]
    data["inpaint"]["mask_image"]["node"] = "99"
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    defaults = presets / "defaults.yaml"
    d = yaml.safe_load(defaults.read_text())
    d["workflow_inpaint"] = "qwen-image-turbo"  # pas un preset de réparation
    defaults.write_text(yaml.safe_dump(d, allow_unicode=True))
    reg = PresetRegistry.load(presets)
    messages = " | ".join(i.message for i in reg.issues)
    assert "qwen-image-inpaint-rapide" not in reg.workflows
    assert "denoise" in messages
    assert "inpaint_with : workflow inconnu ou sans bloc inpaint : qwen-image-inpaint-rapide" in messages
    assert "workflow_inpaint" in messages and reg.defaults is not None and reg.defaults.workflow_inpaint is None


def test_repair_prompt_from_preset_parts() -> None:
    inp = REG.workflow("qwen-image-inpaint-turbo").preset.inpaint
    assert inp is not None
    text = repair_prompt(
        inp,
        target="hand",
        character=PromptCharacter("Aiko", "cheveux noirs", ("kimono rouge", "aiko_v1")),
        description="Aiko « Fuyez ! » tend la main",
        style="Seinen sombre",
    )
    assert text.startswith(inp.targets["hand"])
    assert "Aiko (cheveux noirs, kimono rouge, aiko_v1)" in text and "Fuyez" not in text
    assert "Seinen sombre" in text
    bare = repair_prompt(inp, target="zone", character=None, description="", style="")
    assert "Personnage" not in bare and "Case" not in bare


# --- API de bout en bout (ComfyUI factice) ---------------------------------------------------
def _first_version(c: TestClient, panel_id: int) -> dict[str, Any]:
    _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    _wait(c)
    [img] = _ok(c.get(f"/panels/{panel_id}/images"))
    return img


def _file(c: TestClient, img: dict[str, Any]) -> np.ndarray:
    resp = c.get(img["url"])
    assert resp.status_code == 200
    return np.asarray(Image.open(io.BytesIO(resp.content)).convert("RGB"))


def test_repair_creates_a_linked_version_and_keeps_the_rest(make_client: Callable[..., TestClient]) -> None:
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    p1 = data["panels"][0]
    v1 = _first_version(c, p1["id"])
    w, h = v1["width"], v1["height"]
    # « Réparer cette main » : boîte d'une détection du QC (px de l'image)
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        img = session.get(PanelImage, v1["id"])
        img.detections = {
            "width": w,
            "height": h,
            "faces": [],
            "hands": [
                {"x1": w // 4, "y1": h // 3, "x2": w // 4 + 60, "y2": h // 3 + 50, "score": 0.4, "label": "hand"}
            ],
            "text": [],
        }
        session.commit()
    hand = _ok(c.get(f"/panels/{p1['id']}"))["images"][0]["detections"]["hands"][0]

    info = _ok(c.get(f"/panel-images/{v1['id']}/repair", params={"target": "hand"}))
    assert info["available"] and info["preset"] == "qwen-image-inpaint-rapide"  # palier de la version (Rapide)
    assert info["character_id"] == data["aiko"]["id"]  # seul personnage de la case : concerné d'office
    assert "Aiko (cheveux noirs courts, kimono rouge)" in info["prompt"] and "Aiko sur un toit" in info["prompt"]
    none = _ok(c.get(f"/panel-images/{v1['id']}/repair", params={"target": "hand", "auto_character": False}))
    assert none["character_id"] is None and "Aiko (" not in none["prompt"]
    assert info["denoise"] == REG.workflow("qwen-image-inpaint-rapide").preset.defaults["denoise"]

    [job] = _ok(
        c.post(
            f"/panel-images/{v1['id']}/repair",
            json={
                "regions": [{k: hand[k] for k in ("x1", "y1", "x2", "y2")}],
                "target": "hand",
                "character_id": data["aiko"]["id"],
                "prompt": info["prompt"],
                "grow_px": 8,
                "feather_px": 6,
                "denoise": 0.5,
                "seed": 1234,
            },
        ),
        202,
    )
    assert (
        job["params"]["preset"] == "qwen-image-inpaint-rapide"
        and job["params"]["repair"]["source_image_id"] == v1["id"]
    )
    _wait(c)
    assert _job(c, job["id"])["status"] == "succeeded"

    v1_after, v2 = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert v1_after["selected"] and not v2["selected"]  # l'auteur choisit de la retenir ou non
    assert v2["version"] == 2 and v2["seed"] == 1234 and v2["tier"] == "Rapide"
    repair = v2["params"]["repair"]
    assert (repair["source_image_id"], repair["source_version"], repair["target"]) == (v1["id"], 1, "hand")
    assert (repair["grow_px"], repair["feather_px"], repair["denoise"]) == (8, 6, 0.5)
    assert (v2["width"], v2["height"]) == (w, h)
    assert [lo["name"] for lo in v2["params"]["loras"]] == ["encre.safetensors", "aiko-v3.safetensors"]
    assert len(v2["params"]["reference_images"]) == 1  # planche d'Aiko

    sent = list(comfy.prompts.values())[-1]
    assert sent["9"]["inputs"]["denoise"] == 0.5 and sent["9"]["inputs"]["seed"] == 1234
    assert sent["30"]["inputs"]["image"] in comfy.uploads and sent["31"]["inputs"]["image"] in comfy.uploads

    # le mock modifie toute l'image (dérive VAE) : seul le recollage garde le reste intact
    before, after = _file(c, v1), _file(c, v2)
    raw = build_mask((w, h), [Region(hand["x1"], hand["y1"], hand["x2"], hand["y2"])])
    zone = np.asarray(influence_zone(raw, 8, 6)) > 0
    assert (after[~zone] == before[~zone]).all()
    assert (after[np.asarray(raw) > 0] != before[np.asarray(raw) > 0]).any()

    # suppression de la version réparée : son masque disparaît aussi
    mask_path = c.app.state.ctx.files.absolute(repair["mask_path"])  # type: ignore[attr-defined]
    assert mask_path.is_file()
    assert c.delete(f"/panel-images/{v2['id']}").status_code == 204
    assert not mask_path.is_file()


def test_repair_with_painted_mask_and_errors(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    data = setup_chapter(c)
    p2 = data["panels"][1]
    v1 = _first_version(c, p2["id"])
    painted = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(painted).ellipse((20, 20, 40, 40), fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    painted.save(buf, format="PNG")
    mask_png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    [job] = _ok(c.post(f"/panel-images/{v1['id']}/repair", json={"mask_png": mask_png}), 202)
    assert job["params"]["repair"]["painted"] is True and job["params"]["repair"]["prompt"]  # prompt prérempli
    _wait(c)
    assert _job(c, job["id"])["status"] == "succeeded"
    assert len(_ok(c.get(f"/panels/{p2['id']}/images"))) == 2

    def error(body: dict[str, Any], image_id: int = v1["id"]) -> str:
        resp = c.post(f"/panel-images/{image_id}/repair", json=body)
        assert resp.status_code == 422, resp.text
        return resp.json()["errors"][0]["message"]

    assert "Zone vide" in error({"regions": []})
    assert "absent de la case" in error({"regions": [{"x1": 0, "y1": 0, "x2": 9, "y2": 9}], "character_id": 99999})
    assert "illisible" in error({"mask_png": "pas du base64 !"})
    assert c.post("/panel-images/999999/repair", json={"regions": []}).status_code == 404
    assert c.post(f"/panel-images/{v1['id']}/repair", json={"denoise": 2}).status_code == 422

    # croquis : la réparation s'applique aux versions propres seulement
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        img = session.get(PanelImage, v1["id"])
        img.params = {**img.params, "kind": "croquis"}
        session.commit()
    assert "pas aux croquis" in error({"regions": [{"x1": 0, "y1": 0, "x2": 9, "y2": 9}]})
    info = _ok(c.get(f"/panel-images/{v1['id']}/repair"))
    assert not info["available"] and "croquis" in info["problem"]


def test_inpaint_presets_are_never_used_to_generate(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    p1 = setup_chapter(c)["panels"][0]
    ids = {w["id"] for w in _ok(c.get("/presets/workflows"))}
    assert ids and not ids & set(INPAINT)
    resp = c.patch(f"/panels/{p1['id']}", json={"generation_preset": "qwen-image-inpaint"})
    assert resp.status_code == 422 and "preset de réparation" in resp.json()["errors"][0]["message"]
    resp = c.post(f"/panels/{p1['id']}/generate", json={"preset": "qwen-image-inpaint-turbo"})
    assert resp.status_code == 422 and "sert à réparer" in resp.json()["errors"][0]["message"]
