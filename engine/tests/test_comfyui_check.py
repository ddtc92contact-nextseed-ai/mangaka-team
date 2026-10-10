"""Test de connexion ComfyUI et case d'essai, sur des réponses enregistrées d'un vrai ComfyUI.

Aucun ComfyUI réel ici : `fixtures/comfyui/` contient un `/object_info` réduit aux classes
utilisées, un `/system_stats` et des refus de `/prompt` enregistrés sur la GX10. Aucun nom de
fichier de modèle n'est écrit dans ce module : ils sont lus dans les presets.
"""

from __future__ import annotations

import copy
import io
import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.comfy_check import LoraUse, allowed_values, build_report, run_check
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import (
    ComfyUIClient,
    ComfyUIOutOfMemoryError,
    ComfyUIWorkflowError,
    HttpComfyUIClient,
    MockComfyUIClient,
)
from mangaka_engine.providers.comfyui.base import images_from_history
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from tests.conftest import COMFY_FIXTURES, PRESETS_DIR

REG = PresetRegistry.load(PRESETS_DIR)
OBJECT_INFO: dict[str, Any] = json.loads((COMFY_FIXTURES / "object_info.json").read_text())
SYSTEM_STATS: dict[str, Any] = json.loads((COMFY_FIXTURES / "system_stats.json").read_text())


def _object_info() -> dict[str, Any]:
    return copy.deepcopy(OBJECT_INFO)


def _report(object_info: dict[str, Any], loras: list[LoraUse] | None = None) -> dict[str, Any]:
    return build_report(
        REG, url="http://127.0.0.1:8188", system_stats=SYSTEM_STATS, object_info=object_info, loras=loras or []
    )


def _problems(report: dict[str, Any]) -> dict[str, list[str]]:
    return {p["id"]: p["problems"] for p in report["presets"]}


def _choices(info: dict[str, Any], cls: str, name: str) -> list[str]:
    return info[cls]["input"]["required"][name][0]


def _preset_value(preset_id: str, node: str, name: str) -> str:
    return REG.workflow(preset_id).workflow[node]["inputs"][name]


def _installed_lora() -> str:
    return _choices(OBJECT_INFO, "LoraLoaderModelOnly", "lora_name")[0]


# --- vérification pure ----------------------------------------------------------------
def test_check_ok_with_recorded_object_info() -> None:
    assert REG.issues == []
    report = _report(_object_info(), [LoraUse(_installed_lora(), "série « Les Lames », style")])
    assert report["ok"] and report["online"] and not report["simulated"]
    assert set(_problems(report)) == set(REG.workflows)
    assert set(REG.workflows) >= {
        "qwen-image-base",
        "qwen-image-base-rapide",
        "qwen-image-edit-ref",
        "qwen-image-edit-ref-rapide",
        "qwen-image-turbo",
        "qwen-image-edit-ref-turbo",
        "qwen-image-croquis",
        "qwen-image-turbo-from-sketch",
        "qwen-image-inpaint",
        "qwen-image-inpaint-rapide",
        "qwen-image-inpaint-turbo",
    }
    assert all(p["ok"] and p["problems"] == [] for p in report["presets"])
    assert report["loras"] == {"checked": 1, "problems": []}
    system = report["system"]
    assert system["comfyui_version"] == SYSTEM_STATS["system"]["comfyui_version"]
    [device] = system["devices"]
    assert device["type"] == "cuda" and "GB10" in device["name"] and device["vram_total"] > 0


def test_every_preset_file_name_is_known_to_the_recorded_comfyui() -> None:
    """Les fichiers des presets sont bien ceux installés sur la GX10 (au moment de l'enregistrement)."""
    for wf in REG.workflows.values():
        for node in wf.workflow.values():
            for name, value in node["inputs"].items():
                if name.endswith("_name") and isinstance(value, str):
                    spec = OBJECT_INFO[node["class_type"]]["input"]["required"][name]
                    assert value in (allowed_values(spec) or []), (wf.preset.id, name, value)


def test_missing_model_file_is_reported_per_preset() -> None:
    info = _object_info()
    missing = _preset_value("qwen-image-base-rapide", "1", "unet_name")
    _choices(info, "UNETLoader", "unet_name").remove(missing)
    report = _report(info)
    problems = _problems(report)
    assert not report["ok"]
    expected = f"modèle introuvable dans ComfyUI : {missing} — à placer dans ComfyUI/models/diffusion_models/ (nœud 1, UNETLoader)"
    assert problems["qwen-image-base-rapide"] == [expected]
    assert problems["qwen-image-edit-ref-rapide"] == [expected]
    assert problems["qwen-image-base"] == [] and problems["qwen-image-edit-ref"] == []


def test_missing_turbo_file_names_the_file_and_the_folder() -> None:
    """Fichier Turbo absent de la GX10 : message lisible pour les presets Turbo (croquis et propre depuis
    croquis compris : même modèle), et eux seuls."""
    info = _object_info()
    missing = _preset_value("qwen-image-turbo", "1", "unet_name")
    assert missing == _preset_value("qwen-image-edit-ref-turbo", "1", "unet_name")
    _choices(info, "UNETLoader", "unet_name").remove(missing)
    problems = _problems(_report(info))
    expected = (
        f"modèle introuvable dans ComfyUI : {missing} — à placer dans ComfyUI/models/diffusion_models/"
        " (nœud 1, UNETLoader)"
    )
    assert problems["qwen-image-turbo"] == [expected]
    assert problems["qwen-image-edit-ref-turbo"] == [expected]
    assert problems["qwen-image-croquis"] == [expected] and problems["qwen-image-turbo-from-sketch"] == [expected]
    assert all(not v for k, v in problems.items() if "turbo" not in k and "croquis" not in k)


def test_missing_encoder_and_vae_are_named() -> None:
    info = _object_info()
    encoder = _preset_value("qwen-image-base", "2", "clip_name")
    vae = _preset_value("qwen-image-base", "3", "vae_name")
    _choices(info, "CLIPLoader", "clip_name").remove(encoder)
    _choices(info, "VAELoader", "vae_name").remove(vae)
    problems = _problems(_report(info))["qwen-image-base"]
    assert problems == [
        f"encodeur de texte introuvable dans ComfyUI : {encoder} — à placer dans ComfyUI/models/text_encoders/"
        " (nœud 2, CLIPLoader)",
        f"VAE introuvable dans ComfyUI : {vae} — à placer dans ComfyUI/models/vae/ (nœud 3, VAELoader)",
    ]


def test_unknown_node_class() -> None:
    info = _object_info()
    del info["QwenImage21Cache"]
    report = _report(info)
    for problems in _problems(report).values():
        assert problems == ["nœud inconnu : QwenImage21Cache (nœud 4)"]
    del info["LoraLoaderModelOnly"]
    assert "nœud inconnu : LoraLoaderModelOnly (chargeur de LoRA)" in _problems(_report(info))["qwen-image-base"]


def test_missing_lora_from_series_and_characters() -> None:
    uses = [
        LoraUse(_installed_lora(), "série « Les Lames », style"),
        LoraUse("absent/aiko-v9.safetensors", "personnage Aiko (série « Les Lames »)"),
    ]
    report = _report(_object_info(), uses)
    assert not report["ok"]
    assert all(p["ok"] for p in report["presets"])  # les presets eux-mêmes sont bons
    assert report["loras"] == {
        "checked": 2,
        "problems": [
            "LoRA introuvable dans ComfyUI : absent/aiko-v9.safetensors — à placer dans ComfyUI/models/loras/"
            " (personnage Aiko (série « Les Lames »))"
        ],
    }


# --- client HTTP ------------------------------------------------------------------------
def _fixture_server(object_info: dict[str, Any] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/system_stats":
            return httpx.Response(200, json=SYSTEM_STATS)
        if req.url.path == "/object_info":
            return httpx.Response(200, json=object_info if object_info is not None else OBJECT_INFO)
        if req.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        return httpx.Response(404)

    return handler


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> HttpComfyUIClient:
    return HttpComfyUIClient("http://127.0.0.1:8188", transport=httpx.MockTransport(handler))


def test_run_check_against_recorded_server() -> None:
    report = run_check(_http(_fixture_server()), REG, url="http://127.0.0.1:8188")
    assert report["ok"] and report["system"]["devices"][0]["vram_free"] > 0


def test_server_down() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée")

    report = run_check(_http(down), REG, url="http://127.0.0.1:8188")
    assert report["online"] is False and report["ok"] is False
    assert report["error"] == "ComfyUI hors ligne (127.0.0.1:8188)"
    assert report["presets"] == [] and report["system"] is None


def test_object_info_unreadable_but_server_up() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/object_info":
            return httpx.Response(500, text="boom")
        return _fixture_server()(req)

    report = run_check(_http(handler), REG, url="http://127.0.0.1:8188")
    assert report["online"] is True and report["ok"] is False
    assert report["error"].startswith("liste des nœuds (/object_info) illisible")
    assert report["system"]["comfyui_version"]


def test_mock_provider_is_simulated() -> None:
    report = run_check(MockComfyUIClient(), REG, url=None)
    assert report["simulated"] is True and report["provider"] == "mock" and report["presets"] == []


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (
            "prompt_400_missing_model.json",
            "workflow refusé par ComfyUI : le workflow ne passe pas la validation de ComfyUI — "
            "nœud 1 (UNETLoader) : modèle introuvable dans ComfyUI : absent.safetensors"
            " — à placer dans ComfyUI/models/diffusion_models/",
        ),
        (
            "prompt_400_unknown_node.json",
            "workflow refusé par ComfyUI : nœud inconnu : NoeudInexistant (nœud 4) — "
            "nœud personnalisé non installé ou ComfyUI pas à jour ?",
        ),
    ],
)
def test_prompt_400_is_translated(fixture: str, expected: str) -> None:
    recorded = json.loads((COMFY_FIXTURES / fixture).read_text())
    client = _http(lambda req: httpx.Response(400, json=recorded))
    with pytest.raises(ComfyUIWorkflowError) as info:
        client.queue_prompt({})
    assert str(info.value) == expected
    assert info.value.node_errors == recorded["node_errors"]


def test_prompt_400_other_validation_errors_in_french() -> None:
    body = {
        "error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"},
        "node_errors": {
            "9": {
                "class_type": "KSampler",
                "errors": [
                    {
                        "type": "value_smaller_than_min",
                        "message": "Value -1 smaller than min of 0",
                        "details": "seed",
                        "extra_info": {"input_name": "seed", "received_value": -1},
                    }
                ],
            },
            "6": {
                "class_type": "TextEncodeQwenImage21",
                "errors": [
                    {
                        "type": "required_input_missing",
                        "message": "Required input is missing",
                        "details": "clip",
                        "extra_info": {"input_name": "clip"},
                    }
                ],
            },
        },
    }
    with pytest.raises(ComfyUIWorkflowError) as info:
        _http(lambda req: httpx.Response(400, json=body)).queue_prompt({})
    message = str(info.value)
    assert "nœud 9 (KSampler) : valeur trop petite (seed) — Value -1 smaller than min of 0" in message
    assert "nœud 6 (TextEncodeQwenImage21) : entrée obligatoire manquante (clip)" in message


def test_out_of_memory_is_explained() -> None:
    entry = {
        "outputs": {},
        "status": {
            "status_str": "error",
            "completed": False,
            "messages": [
                [
                    "execution_error",
                    {
                        "node_type": "KSampler",
                        "exception_type": "torch.OutOfMemoryError",
                        "exception_message": "Allocation on device \nThis error means you ran out of memory on your GPU.",
                    },
                ]
            ],
        },
    }
    with pytest.raises(ComfyUIOutOfMemoryError, match="mémoire GPU insuffisante dans ComfyUI \\(KSampler\\)"):
        images_from_history(entry, "11")


# --- API --------------------------------------------------------------------------------
def _providers(comfy: ComfyUIClient) -> Providers:
    return Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=comfy,
        names={"llm": "mock", "vision": "mock", "comfyui": comfy.name},
    )


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[[ComfyUIClient], TestClient]]:
    clients: list[TestClient] = []

    def _make(comfy: ComfyUIClient) -> TestClient:
        c = TestClient(create_app(make_settings(), providers=_providers(comfy)))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def test_check_endpoint_mock_and_http(make_client: Callable[[ComfyUIClient], TestClient]) -> None:
    mock = make_client(MockComfyUIClient()).get("/comfyui/check").json()
    assert mock["simulated"] is True and mock["ok"] is True

    info = _object_info()
    c = make_client(_http(_fixture_server(info)))
    series = c.post("/projects", json={"title": "Les Lames", "style_lora_name": _installed_lora()}).json()
    c.post(f"/projects/{series['id']}/characters", json={"name": "Aiko", "lora_name": "aiko-absent.safetensors"})
    report = c.get("/comfyui/check").json()
    assert report["online"] and report["url"] == "http://127.0.0.1:8188"
    assert all(p["ok"] for p in report["presets"])
    assert report["loras"] == {
        "checked": 2,
        "problems": [
            "LoRA introuvable dans ComfyUI : aiko-absent.safetensors — à placer dans ComfyUI/models/loras/"
            " (personnage Aiko (série « Les Lames »))"
        ],
    }


def _wait_done(c: TestClient, job_id: int, timeout: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = c.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("case d'essai non terminée")


def test_trial_generation_mock(make_client: Callable[[ComfyUIClient], TestClient]) -> None:
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    resp = c.post("/comfyui/trial", json={"preset": "qwen-image-base-rapide"})
    assert resp.status_code == 202, resp.text
    job = _wait_done(c, resp.json()["id"])
    assert job["status"] == "succeeded" and job["step"] == "comfyui_trial"
    params = job["params"]
    trial = REG.workflow("qwen-image-base-rapide").preset.trial
    assert (params["image_width"], params["image_height"]) == (trial["width"], trial["height"])
    assert params["duration_s"] >= 0 and params["steps"] == trial["steps"]
    assert job["message"].startswith(f"Case d'essai {trial['width']}×{trial['height']} générée en ")
    [wf] = comfy.prompts.values()
    assert wf["6"]["inputs"]["prompt"] == trial["positive_prompt"]
    img = c.get(f"/comfyui/trial/{job['id']}/image")
    assert img.status_code == 200
    assert Image.open(io.BytesIO(img.content)).size == (trial["width"], trial["height"])

    # sans preset : workflow par défaut des séries
    default = c.post("/comfyui/trial", json={}).json()
    assert default["params"]["preset"] == "qwen-image-turbo"
    _wait_done(c, default["id"])


def test_trial_errors(make_client: Callable[[ComfyUIClient], TestClient]) -> None:
    c = make_client(MockComfyUIClient())
    resp = c.post("/comfyui/trial", json={"preset": "inconnu"})
    assert resp.status_code == 422 and "workflow inconnu" in resp.json()["errors"][0]["message"]
    assert c.get("/comfyui/trial/999/image").status_code == 404

    recorded = json.loads((COMFY_FIXTURES / "prompt_400_missing_model.json").read_text())

    def refuse(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/prompt":
            return httpx.Response(400, json=recorded)
        return _fixture_server()(req)

    c = make_client(_http(refuse))
    job = _wait_done(c, c.post("/comfyui/trial", json={"preset": "qwen-image-base"}).json()["id"])
    assert job["status"] == "failed"
    assert job["error"].startswith("Workflow refusé par ComfyUI : le workflow ne passe pas la validation")
    assert "modèle introuvable dans ComfyUI : absent.safetensors" in job["error"]

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée")

    c = make_client(_http(down))
    job = _wait_done(c, c.post("/comfyui/trial", json={"preset": "qwen-image-base"}).json()["id"])
    assert job["status"] == "failed" and job["error"] == "ComfyUI hors ligne (127.0.0.1:8188)"
