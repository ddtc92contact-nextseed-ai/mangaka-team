"""Second moteur d'image : FLUX 3 Image Klein (presets de Morigane, 16/10/2026).

Croquis, Qualité et passage au propre suivent le preset de la case, sinon celui de la série ; un flux sans
`lora_chain` ne reçoit aucun LoRA et le dit sur le job et la version. Tout est simulé (ComfyUI factice).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from mangaka_engine.pipeline.generation import quality_preset_id, usable_loras
from mangaka_engine.pipeline.sketch import clean_preset_id, sketch_preset_id
from mangaka_engine.presets import LoraSpec, PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from tests.conftest import PRESETS_DIR, force_stages
from tests.test_generation import _job, _ok, _wait, make_client, setup_chapter  # noqa: F401 — fixture

REG = PresetRegistry.load(PRESETS_DIR)
FLUX = [
    "flux3-klein-croquis",
    "flux3-klein-edit-ref-croquis",
    "flux3-klein-qualite",
    "flux3-klein-edit-ref-qualite",
    "flux3-klein-qualite-from-sketch",
    "flux3-klein-edit-ref-qualite-from-sketch",
]
REFS = [SimpleNamespace(reference_images=[object()])]  # une fiche de la case a une image de référence
NO_REFS = [SimpleNamespace(reference_images=[])]


def _panel(series: str, panel: str | None = None, clean_mode: str = "img2img") -> Any:
    project = SimpleNamespace(workflow_preset=series, clean_mode=clean_mode)
    return SimpleNamespace(generation_preset=panel, page=SimpleNamespace(chapter=SimpleNamespace(project=project)))


# --- presets ----------------------------------------------------------------------------------
def test_flux_presets_load_without_issue_and_declare_their_engine() -> None:
    assert REG.issues == []
    for preset_id in FLUX:
        preset = REG.workflow(preset_id).preset
        assert preset.engine == "flux3-klein" and preset.engine_name == "FLUX 3 Klein"
        assert preset.lora_chain is None and not preset.supports_lora  # licence FLUX Kommunity : pas de LoRA
    # Tous les presets livrés, Qwen compris, déclarent leur moteur.
    assert {w.preset.engine for w in REG.workflows.values()} == {"qwen-image", "flux3-klein"}
    assert all(w.preset.supports_lora for w in REG.workflows.values() if w.preset.engine == "qwen-image")


def test_flux_quality_reads_its_negative_at_cfg_2_5_and_has_no_max_tier() -> None:
    for preset_id in FLUX:
        preset = REG.workflow(preset_id).preset
        if preset.role == "croquis":
            assert preset.distilled and preset.cfg == 1 and preset.defaults["steps"] == 6
        else:
            # cfg 1 = score 68 rejeté, cfg 2,5 = 96 ok (mesuré) : déclarés non distillés pour lire le négatif.
            assert not preset.distilled and preset.cfg == 2.5 and preset.negative_active()
            assert preset.tier is not None and preset.tier.name == "Qualité" and preset.defaults["steps"] == 15
    assert not any(REG.workflow(p).preset.tier.name == "Qualité max" for p in FLUX)  # type: ignore[union-attr]
    comment = (PRESETS_DIR / "workflows" / "flux3-klein-edit-ref-qualite.yaml").read_text(encoding="utf-8")
    assert "score qualité 96 ok à cfg 2,5 contre 68 rejeté à cfg 1" in comment
    # Proposé comme palier de série, après les paliers Qwen.
    tier = REG.workflow("flux3-klein-qualite").preset.tier
    assert tier is not None and tier.choice and tier.order > REG.workflow("qwen-image-base").preset.tier.order  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("link", "target", "message"),
    [
        ("sketch", "inconnu", "sketch : workflow inconnu ou invalide : inconnu"),
        (
            "sketch",
            "flux3-klein-edit-ref-qualite",
            "sketch : le workflow flux3-klein-edit-ref-qualite n'a pas le rôle « croquis »",
        ),
        ("quality", "flux3-klein-croquis", "quality : le workflow flux3-klein-croquis n'a pas le rôle « generation »"),
        ("quality", "qwen-image-inpaint", "quality : le workflow qwen-image-inpaint n'a pas le rôle « generation »"),
    ],
)
def test_loader_checks_sketch_and_quality_links(tmp_path: Path, link: str, target: str, message: str) -> None:
    presets = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, presets)
    path = presets / "workflows" / "flux3-klein-qualite.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data[link] = target
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(presets)
    assert [i.message for i in reg.issues] == [message]
    assert "flux3-klein-qualite" in reg.workflows  # le workflow reste chargé, l'erreur est lisible


# --- résolution des paliers ---------------------------------------------------------------------
def test_flux_series_sketches_and_regenerates_on_flux() -> None:
    panel = _panel("flux3-klein-qualite")
    assert sketch_preset_id(REG, panel, NO_REFS) == "flux3-klein-croquis"
    assert quality_preset_id(REG, panel, NO_REFS) == "flux3-klein-qualite"
    # Avec une fiche : les variantes « edit-ref ».
    assert sketch_preset_id(REG, panel, REFS) == "flux3-klein-edit-ref-croquis"
    assert quality_preset_id(REG, panel, REFS) == "flux3-klein-edit-ref-qualite"
    # Passage au propre : « …from-sketch ».
    assert clean_preset_id(REG, panel, NO_REFS) == "flux3-klein-qualite-from-sketch"
    assert clean_preset_id(REG, panel, REFS) == "flux3-klein-edit-ref-qualite-from-sketch"


def test_flux_panel_in_a_qwen_series_and_the_reverse() -> None:
    flux_panel = _panel("qwen-image-base-qualite", panel="flux3-klein-qualite")
    assert sketch_preset_id(REG, flux_panel, REFS) == "flux3-klein-edit-ref-croquis"
    assert quality_preset_id(REG, flux_panel, NO_REFS) == "flux3-klein-qualite"
    assert clean_preset_id(REG, flux_panel, REFS) == "flux3-klein-edit-ref-qualite-from-sketch"
    # La case a choisi la variante avec références : son croquis et sa Qualité restent FLUX.
    edit_panel = _panel("qwen-image-base-qualite", panel="flux3-klein-edit-ref-qualite")
    assert sketch_preset_id(REG, edit_panel, NO_REFS) == "flux3-klein-croquis"
    assert quality_preset_id(REG, edit_panel, REFS) == "flux3-klein-edit-ref-qualite"

    qwen_panel = _panel("flux3-klein-qualite", panel="qwen-image-base-rapide")
    assert sketch_preset_id(REG, qwen_panel, NO_REFS) == "qwen-image-croquis"
    assert sketch_preset_id(REG, qwen_panel, REFS) == "qwen-image-edit-ref-croquis"
    assert quality_preset_id(REG, qwen_panel, REFS) == "qwen-image-edit-ref"
    assert clean_preset_id(REG, qwen_panel, NO_REFS) == "qwen-image-base-rapide-from-sketch"


@pytest.mark.parametrize(
    "series", ["qwen-image-turbo", "qwen-image-base-rapide", "qwen-image-base-qualite", "qwen-image-base"]
)
def test_qwen_series_keeps_the_defaults_tiers(series: str) -> None:
    defaults = REG.defaults
    assert defaults is not None
    panel = _panel(series)
    assert sketch_preset_id(REG, panel, NO_REFS) == defaults.workflow_sketch == "qwen-image-croquis"
    assert sketch_preset_id(REG, panel, REFS) == "qwen-image-edit-ref-croquis"
    assert quality_preset_id(REG, panel, NO_REFS) == defaults.workflow_quality == "qwen-image-base"
    assert quality_preset_id(REG, panel, REFS) == "qwen-image-edit-ref"
    assert all(
        REG.workflow(w).preset.sketch is None and REG.workflow(w).preset.quality is None
        for w in REG.workflows
        if w.startswith("qwen")
    )


# --- LoRA -----------------------------------------------------------------------------------------
def test_usable_loras_drops_and_explains_for_a_flow_without_lora_chain() -> None:
    loras = [LoraSpec("encre.safetensors", 0.8, "style"), LoraSpec("aiko-v3.safetensors", 0.9, "Aiko")]
    kept, warning = usable_loras(REG.workflow("flux3-klein-qualite"), loras)
    assert kept == [] and warning is not None
    assert warning.startswith("LoRA ignorés : le flux FLUX 3 Klein ne prend pas de LoRA")
    assert "encre.safetensors (style)" in warning and "aiko-v3.safetensors (Aiko)" in warning
    assert usable_loras(REG.workflow("qwen-image-base-qualite"), loras) == (loras, None)
    assert usable_loras(REG.workflow("flux3-klein-qualite"), []) == ([], None)  # rien à signaler


def _lora_nodes(wf: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in wf.values() if "lora" in n["class_type"].lower()]


def test_flux_series_with_style_lora_generates_without_lora_and_says_so(
    make_client: Callable[..., TestClient],  # noqa: F811
) -> None:
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)  # LoRA de style « encre », Aiko : référence + LoRA
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"workflow_preset": "flux3-klein-qualite"}))
    p1, p2, _ = data["panels"]
    [job1] = _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    [job2] = _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    assert (job1["params"]["preset"], job2["params"]["preset"]) == (
        "flux3-klein-edit-ref-qualite",
        "flux3-klein-qualite",
    )
    _wait(c)
    for job, panel in ((job1, p1), (job2, p2)):
        done = _job(c, job["id"])
        assert done["status"] == "succeeded", done["error"]
        assert done["params"]["lora_warning"].startswith("LoRA ignorés : le flux FLUX 3 Klein ne prend pas de LoRA")
        [img] = _ok(c.get(f"/panels/{panel['id']}/images"))
        assert img["params"]["loras"] == [] and img["params"]["lora_warning"] == done["params"]["lora_warning"]
    assert "aiko-v3.safetensors" in _job(c, job1["id"])["params"]["lora_warning"]
    for wf in comfy.prompts.values():
        assert _lora_nodes(wf) == []  # aucun LoRA dans le graphe envoyé
        assert (
            wf["1"]["inputs"]["unet_name"] == REG.workflow("flux3-klein-qualite").workflow["1"]["inputs"]["unet_name"]
        )
    # La référence d'Aiko passe par la clé pointée images.image0 ; les 4 autres emplacements sont retirés.
    ref_wf = next(wf for wf in comfy.prompts.values() if "6" in wf)
    assert [k for k in ref_wf["6"]["inputs"] if k.startswith("images")] == ["images.image0"]
    assert not {"21", "22", "23", "24"} & set(ref_wf)

    # Série remise en Qwen : le LoRA de style est de nouveau appliqué, sans avertissement.
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"workflow_preset": "qwen-image-base-qualite"}))
    [job3] = _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
    done = _job(c, job3["id"])
    assert done["status"] == "succeeded" and "lora_warning" not in done["params"]
    sent = list(comfy.prompts.values())[-1]
    assert [n["inputs"]["lora_name"] for n in _lora_nodes(sent)] == ["encre.safetensors"]


def test_flux_series_sketch_clean_and_quality_stay_on_flux(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"workflow_preset": "flux3-klein-qualite"}))
    page1 = data["pages"][0]
    p1, p2, _ = data["panels"]

    # L'estimation suit la même résolution que la mise en file (estimated_s des presets FLUX : 12 + 10 s).
    est = _ok(c.get(f"/pages/{page1['id']}/sketch-estimate"))
    assert sorted(b["preset"] for b in est["sketch"]["by_preset"]) == [
        "flux3-klein-croquis",
        "flux3-klein-edit-ref-croquis",
    ]
    assert est["sketch"]["total_s"] == pytest.approx(22)

    res = _ok(c.post(f"/pages/{page1['id']}/sketch"), 202)
    assert [j["params"]["preset"] for j in res["jobs"]] == ["flux3-klein-edit-ref-croquis", "flux3-klein-croquis"]
    _wait(c)
    for pid in (p1["id"], p2["id"]):
        _ok(c.post(f"/panels/{pid}/sketch/validate"))
    force_stages(c, data["chapter"]["id"], "name")
    [clean1] = _ok(c.post(f"/panels/{p1['id']}/clean", json={"denoise": 0.4}), 202)
    [clean2] = _ok(c.post(f"/panels/{p2['id']}/clean"), 202)
    assert clean1["params"]["preset"] == "flux3-klein-edit-ref-qualite-from-sketch"
    assert clean2["params"]["preset"] == "flux3-klein-qualite-from-sketch"
    _wait(c)
    # `denoise` transmis au KSampler (nœud 7) : celui demandé, sinon celui du preset (0,65).
    sent = list(comfy.prompts.values())[-2:]
    assert [wf["7"]["inputs"]["denoise"] for wf in sent] == [0.4, 0.65]
    assert all(_job(c, j["id"])["status"] == "succeeded" for j in (clean1, clean2))

    [q1] = _ok(c.post(f"/panels/{p1['id']}/regenerate-quality"), 202)
    [q2] = _ok(c.post(f"/panels/{p2['id']}/regenerate-quality"), 202)
    assert (q1["params"]["preset"], q2["params"]["preset"]) == ("flux3-klein-edit-ref-qualite", "flux3-klein-qualite")

    # Une case passée sur Qwen dans cette série FLUX croque sur Qwen.
    _ok(c.patch(f"/panels/{p2['id']}", json={"generation_preset": "qwen-image-base-qualite"}))
    [sk] = _ok(c.post(f"/panels/{p2['id']}/sketch"), 202)
    assert sk["params"]["preset"] == "qwen-image-croquis"
    _wait(c)


def test_workflow_presets_endpoints_expose_engine_and_lora_support(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    listed = {w["id"]: w for w in _ok(c.get("/presets/workflows"))}
    assert (listed["flux3-klein-qualite"]["engine"], listed["flux3-klein-qualite"]["engine_name"]) == (
        "flux3-klein",
        "FLUX 3 Klein",
    )
    assert listed["flux3-klein-qualite"]["supports_lora"] is False
    assert (listed["qwen-image-base-qualite"]["engine"], listed["qwen-image-base-qualite"]["supports_lora"]) == (
        "qwen-image",
        True,
    )
    presets = {w["id"]: w for w in _ok(c.get("/presets"))["workflows"]}
    assert (
        presets["flux3-klein-qualite"]["supports_lora"] is False
        and presets["flux3-klein-qualite"]["engine"] == "flux3-klein"
    )
    assert (
        presets["qwen-image-turbo"]["supports_lora"] is True
        and presets["qwen-image-turbo"]["engine_name"] == "Qwen-Image"
    )


# --- build_workflow des 6 flux FLUX ---------------------------------------------------------------
PARAMS = {
    "positive_prompt": "plan moyen, Aiko sur un toit au crépuscule",
    "negative_prompt": "text, speech bubble",
    "seed": 424242,
    "width": 832,
    "height": 1216,
    "filename_prefix": "mangaka/serie-1/chapitre-1/page-1/case-1",
}


@pytest.mark.parametrize("preset_id", FLUX)
def test_build_flux_workflows(preset_id: str) -> None:
    loaded = REG.workflow(preset_id)
    preset = loaded.preset
    slots = len(preset.reference_images)
    refs = ["mangaka/perso1_img1.png", "mangaka/perso2_img4.png"][: min(2, slots)]
    params = dict(PARAMS)
    if preset.role == "propre":
        params["denoise"] = 0.42
    source = "mangaka/croquis_case1_v1.png" if preset.source_image is not None else None
    built = build_workflow(loaded, params, reference_images=refs, source_image=source)
    wf = built.workflow
    sampler = wf["7"]["inputs"]
    assert (sampler["seed"], sampler["cfg"]) == (424242, preset.cfg)
    assert (
        wf["4"]["inputs"]["text"] == PARAMS["positive_prompt"]
        and wf["5"]["inputs"]["text"] == PARAMS["negative_prompt"]
    )
    assert _lora_nodes(wf) == [] and built.loras == []
    if slots:
        # Références branchées sur les clés POINTÉES images.imageN (une forme imbriquée serait ignorée).
        node = wf["6"]["inputs"]
        assert "images" not in node
        assert {k: v for k, v in node.items() if k.startswith("images.")} == {
            "images.image0": ["20", 0],
            "images.image1": ["21", 0],
        }
        assert (wf["20"]["inputs"]["image"], wf["21"]["inputs"]["image"]) == tuple(refs)
        # Emplacements vides retirés, avec leur entrée images.imageN.
        assert not {"22", "23", "24"} & set(wf) and sorted(built.removed_nodes) == ["22", "23", "24"]
        assert (sampler["positive"], sampler["negative"]) == (["6", 0], ["6", 1])
    else:
        assert not any(n["class_type"] == "ReferenceMultiLatent" for n in wf.values())
    if preset.role == "propre":
        assert sampler["denoise"] == 0.42  # denoise du « propre » transmis au KSampler
        assert wf["30"]["inputs"]["image"] == source
        assert (wf["31"]["inputs"]["width"], wf["31"]["inputs"]["height"]) == (832, 1216)
        assert sampler["latent_image"] == ["32", 0]
    else:
        assert sampler["denoise"] == 1.0
        assert (wf["12"]["inputs"]["width"], wf["12"]["inputs"]["height"]) == (832, 1216)


def test_build_flux_workflow_without_references_removes_every_slot() -> None:
    built = build_workflow(REG.workflow("flux3-klein-edit-ref-qualite"), PARAMS, reference_images=["mangaka/a.png"])
    assert [k for k in built.workflow["6"]["inputs"] if k.startswith("images")] == ["images.image0"]
    assert sorted(built.removed_nodes) == ["21", "22", "23", "24"]


def test_build_flux_propre_keeps_preset_denoise_by_default() -> None:
    built = build_workflow(REG.workflow("flux3-klein-qualite-from-sketch"), PARAMS, source_image="mangaka/c.png")
    assert built.workflow["7"]["inputs"]["denoise"] == 0.65
