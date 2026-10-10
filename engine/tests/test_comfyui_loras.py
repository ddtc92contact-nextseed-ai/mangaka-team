"""Liste des LoRA vus par ComfyUI (`GET /comfyui/loras`) et mots déclencheurs dans le prompt.

Aucun ComfyUI réel : le `/object_info` enregistré sur la GX10 (`fixtures/comfyui/`) contient des
LoRA en sous-dossier (`ltx2/…`), servis ici classe par classe comme `/object_info/<classe>`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.comfy_loras import (
    LoraCatalog,
    fetch_loras,
    lora_choices,
    lora_loaders,
    split_lora_name,
)
from mangaka_engine.pipeline.generation import split_trigger_words
from mangaka_engine.presets import LoraSpec, PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import ComfyUIClient, HttpComfyUIClient, MockComfyUIClient
from mangaka_engine.providers.comfyui.mock import MOCK_LORAS
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from tests.conftest import COMFY_FIXTURES, PRESETS_DIR, STYLE
from tests.test_generation import _ok, _wait, setup_chapter

REG = PresetRegistry.load(PRESETS_DIR)
OBJECT_INFO: dict[str, Any] = json.loads((COMFY_FIXTURES / "object_info.json").read_text())
FIXTURE_LORAS: list[str] = OBJECT_INFO["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
URL = "http://127.0.0.1:8188"


# --- lecture de /object_info ---------------------------------------------------------
def test_loaders_come_from_presets() -> None:
    assert lora_loaders(REG) == [("LoraLoaderModelOnly", "lora_name")]


def test_choices_from_recorded_object_info_keep_subfolders() -> None:
    names = lora_choices(OBJECT_INFO, lora_loaders(REG))
    assert names == FIXTURE_LORAS and len(names) == 35
    sub = [n for n in names if "/" in n]
    assert sub == [
        "ltx2/ltx-2.3-22b-distilled-lora-384.safetensors",
        "ltx2/ltx-2.3-22b-distilled-lora-dynamic_fro09_avg_rank_105_bf16.safetensors",
    ]


def test_choices_combo_format_and_duplicates() -> None:
    info = {
        "LoraLoaderModelOnly": {"input": {"required": {"lora_name": ["COMBO", {"options": ["a.safetensors"]}]}}},
        "LoraLoader": {"input": {"required": {"lora_name": [["a.safetensors", "b/c.safetensors"], {}]}}},
    }
    loaders = [("LoraLoader", "lora_name"), ("LoraLoaderModelOnly", "lora_name")]
    assert lora_choices(info, loaders) == ["a.safetensors", "b/c.safetensors"]
    assert lora_choices({}, loaders) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("aiko_v1.safetensors", ("", "aiko_v1.safetensors")),
        ("ltx2/ltx-2.3.safetensors", ("ltx2", "ltx-2.3.safetensors")),
        ("styles/aquarelle/lavis.safetensors", ("styles/aquarelle", "lavis.safetensors")),
        ("persos\\aiko.safetensors", ("persos", "aiko.safetensors")),  # ComfyUI sous Windows
    ],
)
def test_split_lora_name(name: str, expected: tuple[str, str]) -> None:
    assert split_lora_name(name) == expected


# --- client HTTP -----------------------------------------------------------------------
def _server(calls: list[str] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req.url.path)
        prefix = "/object_info/"
        if req.url.path.startswith(prefix):
            cls = req.url.path[len(prefix) :]
            return httpx.Response(200, json={cls: OBJECT_INFO[cls]} if cls in OBJECT_INFO else {})
        return httpx.Response(404)

    return handler


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> HttpComfyUIClient:
    return HttpComfyUIClient(URL, transport=httpx.MockTransport(handler))


def test_fetch_from_recorded_server() -> None:
    calls: list[str] = []
    report = fetch_loras(_http(_server(calls)), REG)
    assert calls == ["/object_info/LoraLoaderModelOnly"]  # une seule classe, pas tout /object_info
    assert report["available"] and not report["simulated"] and report["error"] is None
    assert report["loader"] == "LoraLoaderModelOnly"
    assert [e["name"] for e in report["loras"]] == FIXTURE_LORAS
    entry = next(e for e in report["loras"] if e["folder"])
    assert entry == {
        "name": "ltx2/ltx-2.3-22b-distilled-lora-384.safetensors",
        "folder": "ltx2",
        "file": "ltx-2.3-22b-distilled-lora-384.safetensors",
    }


def test_fetch_server_down() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée")

    report = fetch_loras(_http(down), REG)
    assert report == {
        "provider": "http",
        "available": False,
        "simulated": False,
        "error": "ComfyUI hors ligne (127.0.0.1:8188)",
        "loader": None,
        "loras": [],
    }


def test_fetch_unknown_loader_or_error() -> None:
    report = fetch_loras(_http(lambda req: httpx.Response(200, json={})), REG)
    assert not report["available"]
    assert report["error"] == "chargeur de LoRA inconnu de ce ComfyUI : LoraLoaderModelOnly"
    report = fetch_loras(_http(lambda req: httpx.Response(500, text="boom")), REG)
    assert not report["available"] and report["error"].startswith("liste des LoRA illisible")


def test_mock_fixture_list_and_offline() -> None:
    report = fetch_loras(MockComfyUIClient(), REG)
    assert report["available"] and report["simulated"]
    assert [e["name"] for e in report["loras"]] == list(MOCK_LORAS)
    assert {e["folder"] for e in report["loras"]} == {"", "personnages", "styles/aquarelle"}
    offline = fetch_loras(MockComfyUIClient(online=False), REG)
    assert not offline["available"] and offline["error"] == "ComfyUI hors ligne (mock)"


def test_catalog_cache_and_refresh() -> None:
    now = [0.0]
    calls: list[str] = []
    catalog = LoraCatalog(clock=lambda: now[0])
    client = _http(_server(calls))
    first = catalog.get(client, REG)
    assert catalog.get(client, REG) is first and len(calls) == 1
    catalog.get(client, REG, refresh=True)
    assert len(calls) == 2
    now[0] = 31.0
    catalog.get(client, REG)
    assert len(calls) == 3


def test_catalog_retries_sooner_when_offline() -> None:
    now = [0.0]
    comfy = MockComfyUIClient(online=False)
    catalog = LoraCatalog(clock=lambda: now[0])
    assert not catalog.get(comfy, REG)["available"]
    comfy.online = True
    now[0] = 2.0
    assert not catalog.get(comfy, REG)["available"]  # encore en cache
    now[0] = 6.0
    assert catalog.get(comfy, REG)["available"]


# --- API -------------------------------------------------------------------------------
def _providers(comfy: ComfyUIClient | None) -> Providers:
    return Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=comfy,
        names={"llm": "mock", "vision": "mock", "comfyui": getattr(comfy, "name", "http")},
        errors={} if comfy is not None else {"comfyui": "client ComfyUI inconnu"},
    )


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(comfy: ComfyUIClient | None) -> TestClient:
        c = TestClient(create_app(make_settings(), providers=_providers(comfy)))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def test_endpoint_mock_http_offline(make_client: Callable[..., TestClient]) -> None:
    mock = _ok(make_client(MockComfyUIClient()).get("/comfyui/loras"))
    assert mock["simulated"] and [e["name"] for e in mock["loras"]] == list(MOCK_LORAS)

    http = _ok(make_client(_http(_server())).get("/comfyui/loras?refresh=true"))
    assert http["available"] and len(http["loras"]) == 35

    offline = _ok(make_client(MockComfyUIClient(online=False)).get("/comfyui/loras"))
    assert offline["available"] is False and offline["error"] == "ComfyUI hors ligne (mock)"

    none = _ok(make_client(None).get("/comfyui/loras"))
    assert none["available"] is False and none["error"] == "client ComfyUI inconnu"


def test_trigger_words_saved_and_cleared(make_client: Callable[..., TestClient]) -> None:
    c = make_client(MockComfyUIClient(online=False))
    # ComfyUI hors ligne : le nom tapé à la main est enregistré tel quel ; hors catalogue, pas de mots déclencheurs.
    s = _ok(
        c.post("/projects", json={**STYLE, "title": "Les Lames", "style_lora_name": "persos/encre.safetensors"}), 201
    )
    assert (s["style_lora_name"], s["style_lora_trigger_words"], s["style_lora_in_catalog"]) == (
        "persos/encre.safetensors",
        [],
        False,
    )
    # Les mots déclencheurs du LoRA de style ne se tapent plus : champ refusé.
    bad = c.patch(f"/projects/{s['id']}", json={"style_lora_trigger_words": "encre seinen"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "style_lora_trigger_words"
    # LoRA du catalogue (style_loras.yaml) : mots déclencheurs et poids conseillé.
    s = _ok(c.patch(f"/projects/{s['id']}", json={"style_lora_name": "encre-seinen_v2.safetensors"}))
    assert s["style_lora_trigger_words"] == ["ink seinen style"] and s["style_lora_in_catalog"] is True
    assert s["style_prompt"].startswith("ink seinen style, shonen manga style")
    a = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko", "lora_trigger_words": "aiko_v1"}), 201)
    assert a["lora_trigger_words"] == "aiko_v1"
    a = _ok(c.patch(f"/characters/{a['id']}", json={"lora_trigger_words": ""}))
    assert a["lora_trigger_words"] == ""


# --- prompt et graphe ---------------------------------------------------------------------
def test_trigger_word_helpers() -> None:
    assert split_trigger_words(" aiko_v1, , red kimono ") == ("aiko_v1", "red kimono")
    assert split_trigger_words(None) == ()


def test_builder_keeps_subfolder_lora_name() -> None:
    name = "ltx2/ltx-2.3-22b-distilled-lora-384.safetensors"
    built = build_workflow(
        REG.workflow("qwen-image-turbo"),
        {"positive_prompt": "x", "width": 512, "height": 512, "seed": 1},
        loras=[LoraSpec(name, 0.7, "style")],
    )
    [node] = [n for n in built.workflow.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert node["inputs"]["lora_name"] == name and node["inputs"]["strength_model"] == 0.7


def test_picked_mock_lora_reaches_workflow_graph(make_client: Callable[..., TestClient]) -> None:
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    names = [e["name"] for e in _ok(c.get("/comfyui/loras"))["loras"]]
    style, aiko_lora = names[-1], "personnages/aiko_v1.safetensors"
    assert aiko_lora in names
    data = setup_chapter(c)
    _ok(
        c.patch(
            f"/projects/{data['series']['id']}",
            json={"style_lora_name": style, "style_lora_weight": 0.6},
        )
    )
    _ok(c.patch(f"/characters/{data['aiko']['id']}", json={"lora_name": aiko_lora, "lora_trigger_words": "aiko_v1"}))
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    [img] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert [(lo["name"], lo["weight"]) for lo in img["params"]["loras"]] == [(style, 0.6), (aiko_lora, 0.9)]
    assert style == "styles/aquarelle/lavis-doux.safetensors"  # catalogue : « soft wash painting »
    assert "soft wash painting, seinen manga style" in img["params"]["prompt"] and "aiko_v1" in img["params"]["prompt"]
    [wf] = comfy.prompts.values()
    sent = [n["inputs"]["lora_name"] for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert sent == [style, aiko_lora]
