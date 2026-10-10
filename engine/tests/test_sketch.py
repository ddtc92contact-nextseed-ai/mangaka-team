"""Palier croquis : graphes croquis / propre depuis croquis, croquer → trier → passer au propre (mock),
croquis jamais assemblés ni exportés, temps estimés."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.pipeline.generation import sketch_size
from mangaka_engine.presets import LoraSpec, PresetError, PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.store.models import ImageKind, PanelImage
from tests.conftest import PRESETS_DIR, STYLE
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
CLEAN = [
    ("qwen-image-turbo", "qwen-image-turbo-from-sketch", "qwen-image-edit-ref-turbo-from-sketch"),
    ("qwen-image-base-rapide", "qwen-image-base-rapide-from-sketch", "qwen-image-edit-ref-rapide-from-sketch"),
    ("qwen-image-base", "qwen-image-base-from-sketch", "qwen-image-edit-ref-from-sketch"),
]


# --- presets et graphes -----------------------------------------------------------------------
def test_sketch_presets_are_loaded_and_paired() -> None:
    assert REG.issues == []
    assert REG.defaults is not None and REG.defaults.sketch_enabled
    assert REG.defaults.workflow_sketch == "qwen-image-croquis"
    sketch = REG.workflow("qwen-image-croquis").preset
    assert sketch.role == "croquis" and sketch.long_side == 512 and sketch.estimated_s
    assert sketch.with_references == "qwen-image-edit-ref-croquis"
    assert REG.workflow("qwen-image-edit-ref-croquis").preset.reference_images
    for base, clean, clean_refs in CLEAN:
        assert REG.workflow(base).preset.from_sketch == clean
        assert REG.workflow(clean).preset.role == "propre"
        assert REG.workflow(clean).preset.with_references == clean_refs
        assert REG.workflow(clean).preset.tier == REG.workflow(base).preset.tier.model_copy(
            update={"choice": None, "order": 0}
        )
        assert REG.workflow(clean_refs).preset.reference_images
        assert REG.workflow(clean).preset.estimated_s


def test_sketch_graph_same_model_as_turbo_small_and_few_steps() -> None:
    """Croquis = graphe et modèle Turbo, 6 étapes, LoRA et références conservés."""
    turbo = REG.workflow("qwen-image-turbo").workflow
    for preset_id, refs in (("qwen-image-croquis", []), ("qwen-image-edit-ref-croquis", ["mangaka/perso1_img1.png"])):
        loaded = REG.workflow(preset_id)
        size = sketch_size({"width": 832, "height": 1216}, loaded.preset.long_side or 0, 16)
        built = build_workflow(loaded, {**PARAMS, **size}, reference_images=refs, loras=LORAS)
        wf = built.workflow
        assert wf["1"]["inputs"]["unet_name"] == turbo["1"]["inputs"]["unet_name"]
        assert (wf["8"]["inputs"]["width"], wf["8"]["inputs"]["height"]) == (352, 512)
        assert wf["9"]["inputs"]["steps"] == 6 and wf["9"]["inputs"]["seed"] == 777
        assert wf["9"]["inputs"]["denoise"] == 1
        assert [n["inputs"]["lora_name"] for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"] == [
            "encre.safetensors",
            "aiko-v3.safetensors",
        ]
        if refs:
            assert wf["20"]["inputs"]["image"] == refs[0] and "21" not in wf


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ({"width": 832, "height": 1216}, {"width": 352, "height": 512}),
        ({"width": 1216, "height": 832}, {"width": 512, "height": 352}),
        ({"width": 1024, "height": 1024}, {"width": 512, "height": 512}),
        ({"width": 2048, "height": 256}, {"width": 512, "height": 64}),
    ],
)
def test_sketch_size_keeps_ratio_long_side_and_multiple(target: dict[str, int], expected: dict[str, int]) -> None:
    size = sketch_size(target, 512, 16)
    assert size == expected
    assert size["width"] % 16 == 0 and size["height"] % 16 == 0


@pytest.mark.parametrize(("base", "clean", "clean_refs"), CLEAN)
def test_clean_graph_is_img2img_from_the_sketch(base: str, clean: str, clean_refs: str) -> None:
    """Propre = même modèle que le palier, latent = VAEEncode du croquis agrandi, denoise partiel."""
    tier = REG.workflow(base).workflow
    for preset_id in (clean, clean_refs):
        loaded = REG.workflow(preset_id)
        refs = ["mangaka/perso1_img1.png"] if loaded.preset.reference_images else []
        built = build_workflow(
            loaded, {**PARAMS, "denoise": 0.6}, reference_images=refs, loras=LORAS, source_image="mangaka/croquis.png"
        )
        wf = built.workflow
        assert wf["1"]["inputs"]["unet_name"] == tier["1"]["inputs"]["unet_name"]
        assert wf["9"]["inputs"]["steps"] == tier["9"]["inputs"]["steps"]
        assert "8" not in wf  # plus de latent vide
        assert wf["30"]["class_type"] == "LoadImage" and wf["30"]["inputs"]["image"] == "mangaka/croquis.png"
        assert wf["31"]["class_type"] == "ImageScale" and wf["31"]["inputs"]["image"] == ["30", 0]
        assert (wf["31"]["inputs"]["width"], wf["31"]["inputs"]["height"]) == (832, 1216)
        assert wf["32"]["class_type"] == "VAEEncode" and wf["32"]["inputs"]["pixels"] == ["31", 0]
        assert wf["9"]["inputs"]["latent_image"] == ["32", 0]
        assert (wf["9"]["inputs"]["denoise"], wf["9"]["inputs"]["seed"]) == (0.6, 777)
        assert {n["inputs"]["lora_name"] for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"} == {
            "encre.safetensors",
            "aiko-v3.safetensors",
        }
        assert built.source_image == "mangaka/croquis.png"
    assert REG.workflow(clean).preset.defaults["denoise"] == pytest.approx(0.65)


def test_clean_graph_requires_a_source_image() -> None:
    with pytest.raises(PresetError, match="image de composition"):
        build_workflow(REG.workflow("qwen-image-turbo-from-sketch"), PARAMS)
    with pytest.raises(PresetError, match="n'accepte pas"):
        build_workflow(REG.workflow("qwen-image-turbo"), PARAMS, source_image="x.png")


# --- croquer → trier → passer au propre (mock) -------------------------------------------------
def _panels(c: TestClient, chapter_id: int) -> list[dict[str, Any]]:
    return [p for page in _ok(c.get(f"/chapters/{chapter_id}/pages")) for p in page["panels"]]


def _images(c: TestClient, panel_id: int) -> list[dict[str, Any]]:
    return _ok(c.get(f"/panels/{panel_id}/images"))


def test_sketch_page_then_triage_then_clean(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    chapter_id = data["chapter"]["id"]
    page1 = data["pages"][0]
    p1, p2, p3 = data["panels"]

    # Estimation avant : 2 cases à croquer sur la page 1 (≈ 10 s avec références + 6 s), rien à passer au propre.
    est = _ok(c.get(f"/pages/{page1['id']}/sketch-estimate"))
    assert (est["to_sketch"], est["validated"], est["to_clean"]) == (2, 0, 0)
    assert est["sketch"]["total_s"] == pytest.approx(16) and not est["sketch"]["measured"]
    assert est["clean"]["remaining_panels"] == 0

    # « Croquer la page » : un croquis par case, preset croquis (avec références pour Aiko).
    res = _ok(c.post(f"/pages/{page1['id']}/sketch"), 202)
    assert res["panel_ids"] == [p1["id"], p2["id"]] and res["skipped"] == 0
    assert [j["params"]["preset"] for j in res["jobs"]] == ["qwen-image-edit-ref-croquis", "qwen-image-croquis"]
    _wait(c)
    panels = {p["id"]: p for p in _panels(c, chapter_id)}
    for pid in (p1["id"], p2["id"]):
        panel = panels[pid]
        assert panel["sketch_count"] == 1 and panel["sketch_image_url"] and not panel["sketch_validated"]
        assert panel["selected_image_id"] is None and panel["image_count"] == 0
        assert panel["state"] == "draft"  # un croquis n'est pas une version de la case
        [img] = _images(c, pid)
        assert img["kind"] == "croquis" and not img["selected"] and img["tier"] == "Croquis"
        assert max(img["width"], img["height"]) == 512
    assert panels[p3["id"]]["sketch_count"] == 0
    # LoRA de la série et des personnages conservés dans le croquis.
    sketch_wf = next(wf for wf in comfy.prompts.values() if wf.get("20"))
    assert {n["inputs"]["lora_name"] for n in sketch_wf.values() if n["class_type"] == "LoraLoaderModelOnly"} == {
        "encre.safetensors",
        "aiko-v3.safetensors",
    }

    # Un croquis ne peut pas être choisi comme version de la case.
    [sk1] = _images(c, p1["id"])
    assert c.post(f"/panel-images/{sk1['id']}/select").status_code == 422

    # Re-croquer p2 : nouvelle graine, la validation saute.
    _ok(c.post(f"/panels/{p2['id']}/sketch/validate"))
    _ok(c.post(f"/panels/{p2['id']}/sketch"), 202)
    _wait(c)
    p2_sketches = _images(c, p2["id"])
    assert len(p2_sketches) == 2 and p2_sketches[0]["seed"] != p2_sketches[1]["seed"]
    assert not next(p for p in _panels(c, chapter_id) if p["id"] == p2["id"])["sketch_validated"]

    # Tri : seule la case 1 est validée → seule elle passe au propre.
    detail = _ok(c.post(f"/panels/{p1['id']}/sketch/validate"))
    assert detail["sketch_image_id"] == sk1["id"]
    est = _ok(c.get(f"/pages/{page1['id']}/sketch-estimate"))
    assert (est["to_sketch"], est["validated"], est["to_clean"]) == (1, 1, 1)
    assert est["clean"]["total_s"] == pytest.approx(160)  # Rapide avec références depuis croquis
    # « Croquer la page » ne re-croque pas une case validée.
    again = _ok(c.post(f"/pages/{page1['id']}/sketch"), 202)
    assert again["panel_ids"] == [p2["id"]]
    _wait(c)

    res = _ok(c.post(f"/pages/{page1['id']}/clean"), 202)
    assert res["panel_ids"] == [p1["id"]]
    [job] = res["jobs"]
    assert job["params"]["preset"] == "qwen-image-edit-ref-rapide-from-sketch"
    assert job["params"]["seed"] == sk1["seed"] and job["params"]["source_image_id"] == sk1["id"]
    assert job["params"]["denoise"] == pytest.approx(0.65)
    _wait(c)

    final = next(i for i in _images(c, p1["id"]) if i["kind"] == "final")
    assert final["selected"]  # 1re version propre choisie d'office (#45)
    assert final["seed"] == sk1["seed"] and final["tier"] == "Rapide"
    assert final["params"]["prompt"] == sk1["params"]["prompt"]
    comp = final["params"]["composition"]
    assert comp["image_id"] == sk1["id"] and comp["source"] == "croquis" and comp["method"] == "img2img"
    assert comp["denoise"] == pytest.approx(0.65) and final["params"]["sketch_image_id"] == sk1["id"]
    # Taille finale = celle de la mise en page ; le croquis envoyé à ComfyUI est bien le croquis validé.
    wf = comfy.prompts[final["params"]["comfyui_prompt_id"]]
    assert comfy.uploads[wf["30"]["inputs"]["image"]] == c.get(sk1["url"]).content
    page = _ok(c.get(f"/chapters/{chapter_id}/pages"))[0]
    lp = next(p for p in page["layout"]["panels"] if p["panel_id"] == p1["id"])
    assert (final["width"], final["height"]) == (lp["target"]["width"], lp["target"]["height"])
    with Image.open(io.BytesIO(c.get(final["url"]).content)) as im:
        assert im.size == (final["width"], final["height"])
    panel = next(p for p in page["panels"] if p["id"] == p1["id"])
    assert panel["selected_image_id"] == final["id"] and panel["sketch_cleaned"] and panel["state"] == "review"

    # Une deuxième demande ne repasse pas au propre la même composition.
    assert _ok(c.post(f"/pages/{page1['id']}/clean"), 202)["panel_ids"] == []
    # La case 2 (non validée) n'a toujours aucune version propre.
    assert all(i["kind"] == "croquis" for i in _images(c, p2["id"]))


def test_sketches_never_reach_assembly_lettering_or_export(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    page = data["pages"][1]
    [p3] = page["panels"]
    _ok(c.post(f"/pages/{page['id']}/sketch"), 202)
    _wait(c)
    lettering = _ok(c.get(f"/pages/{page['id']}/lettering"))
    assert [p["image_url"] for p in lettering["panels"]] == [None]
    # Même un croquis marqué « choisi » par erreur n'est jamais assemblé.
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        img = session.query(PanelImage).filter(PanelImage.panel_id == p3["id"]).one()
        assert img.kind == ImageKind.croquis
        img.selected = True
        session.commit()
    lettering = _ok(c.get(f"/pages/{page['id']}/lettering"))
    assert [p["image_url"] for p in lettering["panels"]] == [None]
    assert any(w["code"] == "missing_image" for w in lettering["warnings"])


def test_denoise_panel_over_series_over_preset(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    _, p2, p3 = data["panels"]
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"sketch_denoise": 0.5}))
    _ok(c.patch(f"/panels/{p3['id']}", json={"sketch_denoise": 0.72}))
    for pid in (p2["id"], p3["id"]):
        _ok(c.post(f"/panels/{pid}/sketch"), 202)
    _wait(c)
    for pid in (p2["id"], p3["id"]):
        _ok(c.post(f"/panels/{pid}/sketch/validate"))
    [j2] = _ok(c.post(f"/panels/{p2['id']}/clean"), 202)
    [j3] = _ok(c.post(f"/panels/{p3['id']}/clean"), 202)
    assert (j2["params"]["denoise"], j3["params"]["denoise"]) == (0.5, 0.72)
    [j3b] = _ok(c.post(f"/panels/{p3['id']}/clean", json={"denoise": 0.4}), 202)
    assert j3b["params"]["denoise"] == 0.4
    assert c.post(f"/panels/{p3['id']}/clean", json={"denoise": 1.5}).status_code == 422
    _wait(c)
    wf_denoise = sorted(
        i["params"]["composition"]["denoise"]
        for pid in (p2["id"], p3["id"])
        for i in _images(c, pid)
        if i["kind"] == "final"
    )
    assert wf_denoise == [0.4, 0.5, 0.72]


def test_edit_description_then_resketch(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p3 = data["panels"][2]
    _ok(c.post(f"/panels/{p3['id']}/sketch"), 202)
    _wait(c)
    detail = _ok(c.patch(f"/panels/{p3['id']}", json={"description": "La ville sous la neige"}))
    assert "neige" in detail["final_prompt"]
    _ok(c.post(f"/panels/{p3['id']}/sketch"), 202)
    _wait(c)
    first, second = _images(c, p3["id"])
    assert "pluie" in first["params"]["prompt"] and "neige" in second["params"]["prompt"]


def test_validate_and_clean_errors(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1 = data["panels"][0]
    res = c.post(f"/panels/{p1['id']}/sketch/validate")
    assert res.status_code == 422 and "croque-la d'abord" in res.text
    res = c.post(f"/panels/{p1['id']}/clean")
    assert res.status_code == 422 and "aucun croquis validé" in res.text
    # Palier croquis désactivé pour la série : boutons refusés avec un message clair.
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"sketch_enabled": False}))
    res = c.post(f"/pages/{data['pages'][0]['id']}/sketch")
    assert res.status_code == 422 and "désactivé" in res.text
    assert c.post(f"/panels/{p1['id']}/sketch").status_code == 422


def test_new_series_gets_sketch_enabled_by_default(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**STYLE, "title": "Neuve"}), 201)
    assert s["sketch_enabled"] is True and s["sketch_denoise"] is None
    s = _ok(client.post("/projects", json={**STYLE, "title": "Sans", "sketch_enabled": False}), 201)
    assert s["sketch_enabled"] is False


def test_chapter_sketch_and_clean_keep_regenerate_quality(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    chapter_id = data["chapter"]["id"]
    res = _ok(c.post(f"/chapters/{chapter_id}/sketch"), 202)
    assert len(res["panel_ids"]) == 3
    _wait(c)
    for p in data["panels"]:
        _ok(c.post(f"/panels/{p['id']}/sketch/validate"))
    est = _ok(c.get(f"/chapters/{chapter_id}/sketch-estimate"))
    assert (est["to_sketch"], est["validated"], est["to_clean"]) == (0, 3, 3)
    assert est["clean"]["total_s"] == pytest.approx(160 + 40 + 40)
    assert len(_ok(c.post(f"/chapters/{chapter_id}/clean"), 202)["panel_ids"]) == 3
    _wait(c)
    p3 = data["panels"][2]
    # « Régénérer en Qualité » fonctionne toujours, sans toucher à la version choisie.
    [job] = _ok(c.post(f"/panels/{p3['id']}/regenerate-quality"), 202)
    assert job["params"]["preset"] == "qwen-image-base" and "source_image_id" not in job["params"]
    _wait(c)
    imgs = _images(c, p3["id"])
    assert [i["kind"] for i in imgs] == ["croquis", "final", "final"]
    assert [i["selected"] for i in imgs] == [False, True, False]


def test_sketch_cannot_be_repaired(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    """La réparation ciblée (#50) s'applique aux versions propres, jamais aux croquis."""
    from mangaka_engine.pipeline.generation import GenerationError
    from mangaka_engine.pipeline.repair import enqueue_repair

    c = make_client()
    data = setup_chapter(c)
    p3 = data["panels"][2]
    _ok(c.post(f"/panels/{p3['id']}/sketch"), 202)
    _wait(c)
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    with ctx.db.session_scope() as session:
        img = session.query(PanelImage).filter(PanelImage.panel_id == p3["id"]).one()
        with pytest.raises(GenerationError, match="croquis"):
            enqueue_repair(session, ctx.presets, ctx.files, img, target="zone")
