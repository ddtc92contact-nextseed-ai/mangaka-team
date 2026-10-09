from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from PIL import Image

from mangaka_engine.config import Settings
from mangaka_engine.presets import PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import (
    ComfyUIError,
    ComfyUIExecutionError,
    ComfyUIInterruptedError,
    ComfyUITimeoutError,
    ComfyUIUnavailableError,
    ComfyUIWorkflowError,
    HttpComfyUIClient,
    ImageRef,
    MockComfyUIClient,
)
from mangaka_engine.providers.factory import (
    ProviderSelectionError,
    build_comfyui,
    build_detectors,
    build_identity,
    build_llm,
    build_providers,
    build_vision,
)
from mangaka_engine.providers.llm import (
    ChatMessage,
    DeepSeekProvider,
    LLMAuthError,
    LLMBadRequestError,
    LLMConfigError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    MockLLMProvider,
)
from mangaka_engine.providers.qc import MockDetectorProvider, MockIdentityProvider
from mangaka_engine.providers.vision import MockVisionProvider, OllamaVisionProvider, VisionUnavailableError
from tests.conftest import PRESETS_DIR, png_bytes

PRESETS = PresetRegistry.load(PRESETS_DIR)
MESSAGES = [ChatMessage("system", "Tu es scénariste."), ChatMessage("user", "Écris une page.")]


# --- sélection des fournisseurs ---------------------------------------------
def test_defaults_are_mock_without_env(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(llm_provider=None, vision_provider=None, comfyui_provider=None)
    p = build_providers(s, PRESETS)
    assert p.errors == {}
    assert isinstance(p.llm, MockLLMProvider)
    assert isinstance(p.vision, MockVisionProvider)
    assert isinstance(p.comfyui, MockComfyUIClient)
    assert isinstance(p.detectors, MockDetectorProvider) and isinstance(p.identity, MockIdentityProvider)
    assert p.names == {
        "llm": "mock",
        "vision": "mock",
        "comfyui": "mock",
        "detectors": "mock",
        "identity": "mock",
        "embedding": "mock",
    }


def test_key_alone_does_not_leave_mock_mode(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(llm_provider=None, deepseek_api_key="sk-test")
    assert isinstance(build_llm(s, PRESETS), MockLLMProvider)


def test_deepseek_selected_explicitly(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(llm_provider="deepseek", deepseek_api_key="sk-test")
    llm = build_llm(s, PRESETS)
    assert isinstance(llm, DeepSeekProvider)
    assert llm.model == PRESETS.require_providers().deepseek.model


def test_deepseek_model_env_overrides_preset(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(llm_provider="DeepSeek", deepseek_api_key="sk-test", deepseek_model="deepseek-reasoner")
    llm = build_llm(s, PRESETS)
    assert isinstance(llm, DeepSeekProvider) and llm.model == "deepseek-reasoner"


def test_explicit_deepseek_without_key_is_reported_not_fatal(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(llm_provider="deepseek")
    with pytest.raises(ProviderSelectionError, match="DEEPSEEK_API_KEY"):
        build_llm(s, PRESETS)
    p = build_providers(s, PRESETS)
    assert p.llm is None and "DEEPSEEK_API_KEY" in p.errors["llm"]
    assert p.names["llm"] == "deepseek"


@pytest.mark.parametrize(
    ("field", "value", "builder", "match"),
    [
        ("llm_provider", "gpt", "llm", "inconnu"),
        ("llm_provider", "ollama", "llm", "pas encore disponible"),
        ("llm_provider", "claude", "llm", "pas encore disponible"),
        ("vision_provider", "deepseek", "vision", "n'accepte pas d'images"),
        ("vision_provider", "gpt4v", "vision", "inconnu"),
        ("comfyui_provider", "grpc", "comfyui", "inconnu"),
        ("qc_detectors_provider", "yolo", "detectors", "inconnu"),
        ("qc_identity_provider", "arcface", "identity", "inconnu"),
    ],
)
def test_unknown_or_unimplemented_providers(
    make_settings: Callable[..., Settings], field: str, value: str, builder: str, match: str
) -> None:
    s = make_settings(**{field: value})
    build = {
        "llm": lambda: build_llm(s, PRESETS),
        "vision": lambda: build_vision(s, PRESETS),
        "comfyui": lambda: build_comfyui(s),
        "detectors": lambda: build_detectors(s),
        "identity": lambda: build_identity(s),
    }
    with pytest.raises(ProviderSelectionError, match=match):
        build[builder]()


def test_comfyui_http_selected(make_settings: Callable[..., Settings]) -> None:
    client = build_comfyui(make_settings(comfyui_provider="http", comfyui_url="http://127.0.0.1:9999/"))
    assert isinstance(client, HttpComfyUIClient) and client.base_url == "http://127.0.0.1:9999"


# --- DeepSeek (HTTP simulé) ----------------------------------------------------
def deepseek(handler: Callable[[httpx.Request], httpx.Response]) -> DeepSeekProvider:
    return DeepSeekProvider(
        api_key="sk-test",
        base_url="https://api.deepseek.test/",
        model="deepseek-chat",
        timeout_s=3,
        transport=httpx.MockTransport(handler),
    )


def test_deepseek_success_and_payload() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"role": "assistant", "content": '{"pages": []}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
            },
        )

    result = deepseek(handler).complete(MESSAGES, json_mode=True, temperature=0.2)
    assert result.text == '{"pages": []}'
    assert result.usage["total_tokens"] == 17
    assert seen["url"] == "https://api.deepseek.test/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["messages"][1] == {"role": "user", "content": "Écris une page."}


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, LLMAuthError),
        (402, LLMAuthError),
        (403, LLMAuthError),
        (429, LLMRateLimitError),
        (400, LLMBadRequestError),
        (422, LLMBadRequestError),
        (500, LLMUnavailableError),
        (503, LLMUnavailableError),
    ],
)
def test_deepseek_http_errors_are_mapped(status: int, exc: type[Exception]) -> None:
    client = deepseek(lambda req: httpx.Response(status, json={"error": {"message": "détail API"}}))
    with pytest.raises(exc) as info:
        client.complete(MESSAGES)
    assert f"HTTP {status}" in str(info.value) and "détail API" in str(info.value)
    assert "sk-test" not in str(info.value)


def test_deepseek_timeout() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("trop long", request=req)

    with pytest.raises(LLMTimeoutError, match="timeout") as info:
        deepseek(handler).complete(MESSAGES)
    assert info.value.retryable


def test_deepseek_connection_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=req)

    with pytest.raises(LLMUnavailableError, match="injoignable"):
        deepseek(handler).complete(MESSAGES)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>pas du json</html>"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    ],
)
def test_deepseek_malformed_response(response: httpx.Response) -> None:
    with pytest.raises(LLMResponseError):
        deepseek(lambda req: response).complete(MESSAGES)


def test_deepseek_requires_key() -> None:
    with pytest.raises(LLMConfigError):
        DeepSeekProvider(api_key="", base_url="https://x", model="m")


def test_mock_llm_is_deterministic() -> None:
    llm = MockLLMProvider()
    assert json.loads(llm.complete(MESSAGES, json_mode=True).text) == {"mock": True, "echo": "Écris une page."}
    custom = MockLLMProvider(lambda msgs, json_mode: "ok")
    assert custom.complete(MESSAGES).text == "ok" and len(custom.calls) == 1


def test_mock_vision() -> None:
    v = json.loads(MockVisionProvider(score=72).ask(b"png", "x"))
    assert v["score"] == 72 and v["raisons"]
    assert json.loads(MockVisionProvider().ask(b"", "x"))["score"] == 0
    flaky = MockVisionProvider(invalid_attempts=1)
    with pytest.raises(json.JSONDecodeError):
        json.loads(flaky.ask(b"png", "x"))
    assert json.loads(flaky.ask(b"png", "x"))["score"] == 80 and flaky.calls == 2


def test_ollama_vision_selected_from_preset(make_settings: Callable[..., Settings]) -> None:
    v = build_vision(make_settings(vision_provider="ollama"), PRESETS)
    assert isinstance(v, OllamaVisionProvider) and v.model == "qwen3-vl:4b" and v.keep_alive == 0


def test_dghs_without_extra_is_reported_not_fatal(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mangaka_engine.providers.qc.dghs.imgutils_installed", lambda: False)
    s = make_settings(qc_detectors_provider="dghs", qc_identity_provider="dghs")
    p = build_providers(s, PRESETS)
    assert p.detectors is None and p.identity is None
    assert "détecteurs non installés" in p.errors["detectors"] and "engine[qc]" in p.errors["identity"]
    assert p.names["detectors"] == "dghs"


def ollama(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaVisionProvider:
    return OllamaVisionProvider(
        base_url="http://ollama.test/", model="qwen3-vl:4b", keep_alive=0, transport=httpx.MockTransport(handler)
    )


def test_ollama_vision_request_and_errors() -> None:
    seen: list[dict[str, Any]] = []

    def ok(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"score": 66, "raisons": []}'}})

    assert json.loads(ollama(ok).ask(b"img", "Décris", schema={"type": "object"}))["score"] == 66
    body = seen[0]
    assert body["model"] == "qwen3-vl:4b" and body["keep_alive"] == 0 and body["stream"] is False
    assert body["messages"][0]["images"] == ["aW1n"] and body["format"] == {"type": "object"}

    with pytest.raises(VisionUnavailableError, match="ollama pull qwen3-vl:4b"):
        ollama(lambda r: httpx.Response(404, json={"error": "model not found"})).ask(b"x", "p")

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(VisionUnavailableError, match="ollama serve"):
        ollama(down).ask(b"x", "p")


# --- ComfyUI mock ----------------------------------------------------------
def test_mock_comfyui_returns_image_of_requested_size() -> None:
    built = build_workflow(
        PRESETS.workflow("qwen-image-base"), {"positive_prompt": "x", "width": 320, "height": 200, "seed": 7}
    )
    client = MockComfyUIClient()
    assert client.health().online
    prompt_id = client.queue_prompt(built.workflow)
    [ref] = client.wait_for_images(prompt_id, built.output_node)
    img = Image.open(io.BytesIO(client.fetch_image(ref)))
    assert img.size == (320, 200) and img.format == "PNG"


def test_mock_comfyui_offline() -> None:
    client = MockComfyUIClient(online=False)
    assert not client.health().online


# --- ComfyUI HTTP (simulé) -----------------------------------------------------
class FakeComfy:
    """Simule l'API HTTP de ComfyUI pour httpx.MockTransport."""

    def __init__(self, polls_before_done: int = 2) -> None:
        self.polls_before_done = polls_before_done
        self.history_calls = 0
        self.prompts: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/system_stats":
            return httpx.Response(200, json={"system": {"os": "posix"}, "devices": []})
        if path == "/queue":
            return httpx.Response(200, json={"queue_running": [[1, "a"]], "queue_pending": [[2, "b"], [3, "c"]]})
        if path == "/prompt" and req.method == "POST":
            body = json.loads(req.content)
            self.prompts.append(body)
            return httpx.Response(200, json={"prompt_id": "p-1", "number": 1, "node_errors": {}})
        if path == "/history/p-1":
            self.history_calls += 1
            if self.history_calls <= self.polls_before_done:
                return httpx.Response(200, json={})
            return httpx.Response(
                200,
                json={
                    "p-1": {
                        "outputs": {
                            "11": {"images": [{"filename": "case_0001.png", "subfolder": "mangaka", "type": "output"}]}
                        },
                        "status": {"status_str": "success", "completed": True, "messages": []},
                    }
                },
            )
        if path == "/view":
            assert dict(req.url.params) == {"filename": "case_0001.png", "subfolder": "mangaka", "type": "output"}
            return httpx.Response(200, content=b"\x89PNG-fake")
        return httpx.Response(404)


def http_client(handler: Callable[[httpx.Request], httpx.Response], **kw) -> HttpComfyUIClient:
    return HttpComfyUIClient("http://comfy.test:8188", transport=httpx.MockTransport(handler), client_id="cid", **kw)


def test_http_comfyui_health_online() -> None:
    status = http_client(FakeComfy()).health()
    assert status.online and status.queue_running == 1 and status.queue_pending == 2


def test_http_comfyui_health_offline() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=req)

    status = http_client(handler).health()
    assert not status.online and "hors ligne (comfy.test:8188)" in (status.detail or "")


def test_http_comfyui_full_cycle() -> None:
    fake = FakeComfy(polls_before_done=2)
    sleeps: list[float] = []
    client = http_client(fake, sleep=sleeps.append)
    prompt_id = client.queue_prompt({"1": {"class_type": "X", "inputs": {}}})
    assert prompt_id == "p-1"
    assert fake.prompts[0]["client_id"] == "cid"
    refs = client.wait_for_images(prompt_id, "11", poll_s=0.5)
    assert refs == [ImageRef("case_0001.png", "mangaka", "output")]
    assert sleeps == [0.5, 0.5]
    assert client.fetch_image(refs[0]) == b"\x89PNG-fake"


def test_http_comfyui_workflow_rejected() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"},
                "node_errors": {"1": {"errors": [{"message": "Value not in list"}]}},
            },
        )

    with pytest.raises(ComfyUIWorkflowError, match="ne passe pas la validation de ComfyUI") as info:
        http_client(handler).queue_prompt({})
    assert "1" in info.value.node_errors


def test_http_comfyui_execution_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "p-1": {
                    "outputs": {},
                    "status": {
                        "status_str": "error",
                        "completed": False,
                        "messages": [["execution_error", {"node_type": "KSampler", "exception_message": "OOM"}]],
                    },
                }
            },
        )

    with pytest.raises(ComfyUIExecutionError, match="KSampler — OOM"):
        http_client(handler).wait_for_images("p-1", "11")


def test_http_comfyui_wait_timeout() -> None:
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    client = http_client(lambda req: httpx.Response(200, json={}), sleep=sleep, clock=lambda: now[0])
    with pytest.raises(ComfyUITimeoutError):
        client.wait_for_images("p-1", "11", timeout_s=3, poll_s=1)


def test_http_comfyui_unreachable_on_prompt() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=req)

    with pytest.raises(ComfyUIUnavailableError):
        http_client(handler).queue_prompt({})


# --- ComfyUI : websocket de progression, upload, interruption ------------------------
class FakeWs:
    """Websocket ComfyUI simulé : renvoie les messages prévus puis expire."""

    def __init__(self, messages: list[str | bytes], fail_after: bool = False) -> None:
        self.messages = list(messages)
        self.fail_after = fail_after
        self.closed = False

    def recv(self, timeout: float | None = None) -> str | bytes:
        if self.messages:
            return self.messages.pop(0)
        if self.fail_after:
            raise ConnectionError("fermé")
        raise TimeoutError

    def close(self) -> None:
        self.closed = True


def _ws_msg(kind: str, **data: object) -> str:
    return json.dumps({"type": kind, "data": data})


def test_http_comfyui_progress_over_websocket() -> None:
    fake = FakeComfy(polls_before_done=1)
    ws = FakeWs(
        [
            _ws_msg("status", status={}),
            b"\x00\x01preview",
            _ws_msg("progress", value=1, max=4, prompt_id="p-1"),
            _ws_msg("progress", value=9, max=9, prompt_id="autre"),
            _ws_msg("progress", value=4, max=4, prompt_id="p-1"),
            _ws_msg("executing", node=None, prompt_id="p-1"),
        ]
    )
    urls: list[str] = []

    def connect(url: str) -> FakeWs:
        urls.append(url)
        return ws

    client = http_client(fake, ws_connect=connect, sleep=lambda s: None)
    progress: list[tuple[int, int]] = []
    refs = client.wait_for_images("p-1", "11", on_progress=lambda v, m: progress.append((v, m)))
    assert refs == [ImageRef("case_0001.png", "mangaka", "output")]
    assert progress == [(1, 4), (4, 4)]
    assert urls == ["ws://comfy.test:8188/ws?clientId=cid"] and ws.closed


def test_http_comfyui_websocket_falls_back_to_polling() -> None:
    sleeps: list[float] = []
    # connexion impossible
    client = http_client(
        FakeComfy(polls_before_done=2),
        ws_connect=lambda url: (_ for _ in ()).throw(OSError("refus")),
        sleep=sleeps.append,
    )
    assert client.wait_for_images("p-1", "11", poll_s=0.5, on_progress=lambda v, m: None)
    assert sleeps == [0.5, 0.5]
    # websocket coupé en cours de route
    sleeps.clear()
    ws = FakeWs([_ws_msg("progress", value=1, max=2, prompt_id="p-1")], fail_after=True)
    client = http_client(FakeComfy(polls_before_done=3), ws_connect=lambda url: ws, sleep=sleeps.append)
    progress: list[tuple[int, int]] = []
    assert client.wait_for_images("p-1", "11", poll_s=0.5, on_progress=lambda v, m: progress.append((v, m)))
    assert progress == [(1, 2)] and ws.closed and sleeps == [0.5, 0.5]


def test_http_comfyui_stop_and_interrupted_history() -> None:
    client = http_client(FakeComfy(polls_before_done=99), sleep=lambda s: None)
    with pytest.raises(ComfyUIInterruptedError):
        client.wait_for_images("p-1", "11", should_stop=lambda: True)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "p-1": {"outputs": {}, "status": {"status_str": "error", "messages": [["execution_interrupted", {}]]}}
            },
        )

    with pytest.raises(ComfyUIInterruptedError):
        http_client(handler).wait_for_images("p-1", "11")


def test_http_comfyui_upload_and_interrupt() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "perso1_img2.png", "subfolder": "mangaka", "type": "input"})
        if req.url.path == "/interrupt":
            return httpx.Response(200)
        return httpx.Response(404)

    client = http_client(handler)
    assert client.upload_image(b"\x89PNG", "perso1_img2.png") == "mangaka/perso1_img2.png"
    body = seen[0].content
    assert b'name="image"; filename="perso1_img2.png"' in body and b"image/png" in body
    assert b'name="subfolder"' in body and b"mangaka" in body and b'name="overwrite"' in body
    client.interrupt("p-1")
    assert seen[1].url.path == "/interrupt" and json.loads(seen[1].content) == {"prompt_id": "p-1"}

    with pytest.raises(ComfyUIError, match="refusé"):
        http_client(lambda req: httpx.Response(500)).upload_image(b"x", "a.png")


def test_mock_comfyui_progress_upload_and_missing_reference() -> None:
    reg_wf = PRESETS.workflow("qwen-image-edit-ref")
    client = MockComfyUIClient()
    name = client.upload_image(png_bytes(), "perso1_img1.png")
    built = build_workflow(
        reg_wf, {"positive_prompt": "x", "width": 256, "height": 384, "seed": 3, "steps": 5}, reference_images=[name]
    )
    prompt_id = client.queue_prompt(built.workflow)
    progress: list[tuple[int, int]] = []
    [ref] = client.wait_for_images(prompt_id, built.output_node, on_progress=lambda v, m: progress.append((v, m)))
    assert progress == [(i, 5) for i in range(1, 6)]
    assert Image.open(io.BytesIO(client.fetch_image(ref))).size == (256, 384)

    missing = build_workflow(
        reg_wf, {"positive_prompt": "x", "width": 256, "height": 256}, reference_images=["absent.png"]
    )
    with pytest.raises(ComfyUIWorkflowError, match="nœud 20 \\(LoadImage\\)"):
        client.queue_prompt(missing.workflow)

    client.interrupt()
    prompt_id = client.queue_prompt(built.workflow)  # une nouvelle génération repart de zéro
    client.interrupt(prompt_id)
    with pytest.raises(ComfyUIInterruptedError):
        client.wait_for_images(prompt_id, built.output_node)
    assert client.interrupts == [None, prompt_id]
