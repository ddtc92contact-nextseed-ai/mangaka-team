from __future__ import annotations

import io
import json
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from mangaka_engine.config import Settings
from mangaka_engine.presets import PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import (
    ComfyUIExecutionError,
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
from mangaka_engine.providers.vision import MockVisionProvider
from tests.conftest import PRESETS_DIR

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
    assert p.names == {"llm": "mock", "vision": "mock", "comfyui": "mock"}


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
        ("vision_provider", "ollama", "vision", "pas encore disponible"),
        ("comfyui_provider", "grpc", "comfyui", "inconnu"),
    ],
)
def test_unknown_or_unimplemented_providers(
    make_settings: Callable[..., Settings], field: str, value: str, builder: str, match: str
) -> None:
    s = make_settings(**{field: value})
    build = {
        "llm": lambda: build_llm(s, PRESETS),
        "vision": lambda: build_vision(s),
        "comfyui": lambda: build_comfyui(s),
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
    v = MockVisionProvider(score=72).score_image(b"png", prompt="x")
    assert v.score == 72 and v.reasons
    assert MockVisionProvider().score_image(b"", prompt="x").score == 0


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
    assert not status.online and "injoignable" in (status.detail or "")


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

    with pytest.raises(ComfyUIWorkflowError, match="failed validation") as info:
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
