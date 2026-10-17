"""Modèles DeepSeek par agent : GET /providers/deepseek/models, modèles qui raisonnent, essai avec le modèle choisi.

Un faux serveur HTTP local (http.server) joue DeepSeek : l'API réelle n'est jamais appelée.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.providers.llm import ChatMessage, DeepSeekProvider

SECRET = "sk-test-ne-jamais-afficher-42"
MESSAGES = [ChatMessage("system", "Tu es scénariste."), ChatMessage("user", "Écris une page.")]


@dataclass
class FakeDeepSeek:
    """État du faux serveur : réponses à donner, requêtes reçues."""

    models: list[str] = field(default_factory=lambda: ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-preview"])
    models_status: int = 200
    chat: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]] | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def fake() -> Iterator[FakeDeepSeek]:
    state = FakeDeepSeek()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            state.requests.append({"method": "GET", "path": self.path, "auth": self.headers.get("authorization")})
            if self.path != "/models":
                return self._send(404, {"error": {"message": "inconnu"}})
            if state.models_status != 200:
                return self._send(state.models_status, {"error": {"message": "panne simulée"}})
            self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in state.models]})

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            state.requests.append({"method": "POST", "path": self.path, "body": body})
            assert state.chat is not None
            self._send(*state.chat(body))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def _client(make_settings: Callable[..., Settings], **overrides: Any) -> TestClient:
    return TestClient(create_app(make_settings(**overrides)))


def _ids(body: dict[str, Any]) -> list[str]:
    return [m["id"] for m in body["models"]]


# --- liste des modèles ---------------------------------------------------------------------------
def test_live_list_is_relayed_with_preset_labels_and_cached(
    make_settings: Callable[..., Settings], fake: FakeDeepSeek, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with _client(make_settings, llm_provider="deepseek", deepseek_api_key=SECRET, deepseek_base_url=fake.url) as c:
        r = c.get("/providers/deepseek/models")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "live" and body["source_label"] == "en direct" and body["detail"] is None
        assert _ids(body) == ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-preview"]
        chat, reasoner, unknown = body["models"]
        assert chat["note"] == "rapide, sans raisonnement" and not chat["reasoning"]
        assert reasoner["note"] == "raisonne avant de répondre, plus lent" and reasoner["reasoning"]
        assert unknown == {"id": "deepseek-v4-preview", "label": "deepseek-v4-preview", "note": "", "reasoning": False}
        assert fake.requests[0]["auth"] == f"Bearer {SECRET}"  # la clé part seulement vers DeepSeek

        # Cache de quelques minutes : un second appel ne réinterroge pas DeepSeek ; `refresh` si.
        fake.models = ["deepseek-chat"]
        assert _ids(c.get("/providers/deepseek/models").json()) == _ids(body)
        assert len(fake.requests) == 1
        assert _ids(c.get("/providers/deepseek/models?refresh=true").json()) == ["deepseek-chat"]
        assert SECRET not in r.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize("status", [401, 500])
def test_failure_falls_back_to_shipped_list_with_source(
    make_settings: Callable[..., Settings], fake: FakeDeepSeek, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake.models_status = status
    with _client(make_settings, llm_provider="deepseek", deepseek_api_key=SECRET, deepseek_base_url=fake.url) as c:
        r = c.get("/providers/deepseek/models")
    body = r.json()
    assert r.status_code == 200
    assert body["source"] == "preset" and body["source_label"] == "liste livrée"
    assert _ids(body) == ["deepseek-chat", "deepseek-reasoner", "deepseek-flash", "deepseek-v4-pro"]
    assert f"HTTP {status}" in body["detail"] and "panne simulée" in body["detail"]
    assert SECRET not in r.text and SECRET not in caplog.text


def test_unreachable_server_falls_back(make_settings: Callable[..., Settings]) -> None:
    with _client(
        make_settings, llm_provider="deepseek", deepseek_api_key=SECRET, deepseek_base_url="http://127.0.0.1:9"
    ) as c:
        body = c.get("/providers/deepseek/models").json()
    assert body["source"] == "preset" and "injoignable" in body["detail"]


def test_missing_key_or_mock_mode_uses_shipped_list_without_calling(
    make_settings: Callable[..., Settings], fake: FakeDeepSeek
) -> None:
    with _client(make_settings, llm_provider="deepseek", deepseek_base_url=fake.url) as c:
        no_key = c.get("/providers/deepseek/models").json()
    with _client(make_settings, deepseek_api_key=SECRET, deepseek_base_url=fake.url) as c:
        mock = c.get("/providers/deepseek/models").json()
    assert fake.requests == []
    assert no_key["source"] == mock["source"] == "preset"
    assert "DEEPSEEK_API_KEY absente" in no_key["detail"] and "mode mock" in mock["detail"]
    assert _ids(mock) == ["deepseek-chat", "deepseek-reasoner", "deepseek-flash", "deepseek-v4-pro"]
    assert SECRET not in json.dumps(mock)


def test_env_model_is_reported(make_settings: Callable[..., Settings]) -> None:
    with _client(make_settings, deepseek_model="deepseek-reasoner") as c:
        body = c.get("/providers/deepseek/models").json()
        model = next(s for s in c.get("/agents/scenariste").json()["settings"] if s["key"] == "model")
    assert body["env_model"] == "deepseek-reasoner" and body["default_model"] == "deepseek-reasoner"
    assert body["preset_model"] == "deepseek-chat"
    assert model["value"] == "deepseek-reasoner"
    assert model["options_from"] == "deepseek_models"
    assert model["env_override"] == "DEEPSEEK_MODEL" and model["env_value"] == "deepseek-reasoner"


@pytest.mark.parametrize("agent", ["scenariste", "directeur-artistique", "dessinateur", "createur-serie"])
def test_the_four_deepseek_agents_offer_the_model_list(client: TestClient, agent: str) -> None:
    model = next(s for s in client.get(f"/agents/{agent}").json()["settings"] if s["key"] == "model")
    assert model["type"] == "text" and model["options_from"] == "deepseek_models"
    assert model["env_value"] is None and model["value"] == "deepseek-chat"


# --- modèles qui raisonnent ----------------------------------------------------------------------
def _reply(content: str, **extra: Any) -> tuple[int, dict[str, Any]]:
    return 200, {
        "model": "deepseek-reasoner",
        "choices": [{"message": {"role": "assistant", "reasoning_content": "Je réfléchis…", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 8}},
        **extra,
    }


def test_reasoner_reads_content_only_and_sends_no_temperature(fake: FakeDeepSeek) -> None:
    fake.chat = lambda body: _reply('{"pages": []}')
    llm = DeepSeekProvider(api_key=SECRET, base_url=fake.url, model="deepseek-reasoner", reasoning=True)
    result = llm.complete(MESSAGES, json_mode=True, temperature=0.2)
    assert result.text == '{"pages": []}'
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 20}
    body = fake.requests[0]["body"]
    assert "temperature" not in body and body["model"] == "deepseek-reasoner"
    assert body["response_format"] == {"type": "json_object"}


def test_reasoning_is_guessed_from_a_typed_name(fake: FakeDeepSeek) -> None:
    fake.chat = lambda body: _reply("ok")
    DeepSeekProvider(api_key=SECRET, base_url=fake.url, model="deepseek-reasoner-2").complete(MESSAGES)
    DeepSeekProvider(api_key=SECRET, base_url=fake.url, model="deepseek-chat").complete(MESSAGES)
    assert "temperature" not in fake.requests[0]["body"]
    assert fake.requests[1]["body"]["temperature"] == 0.7


def test_json_mode_refused_goes_through_the_prompt(fake: FakeDeepSeek) -> None:
    def chat(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if "response_format" in body:
            return 400, {"error": {"message": "response_format is not supported by this model"}}
        return _reply('```json\n{"pages": []}\n```')

    fake.chat = chat
    llm = DeepSeekProvider(api_key=SECRET, base_url=fake.url, model="deepseek-reasoner", reasoning=True)
    assert llm.complete(MESSAGES, json_mode=True).text == '{"pages": []}'
    retry = fake.requests[1]["body"]
    assert "response_format" not in retry and "JSON" in retry["messages"][-1]["content"]


def test_unknown_model_error_is_readable(fake: FakeDeepSeek) -> None:
    fake.chat = lambda body: (400, {"error": {"message": "Model Not Exist"}})
    llm = DeepSeekProvider(api_key=SECRET, base_url=fake.url, model="deepseek-oups")
    with pytest.raises(Exception, match=r"Model Not Exist.*« deepseek-oups »") as info:
        llm.complete(MESSAGES)
    assert SECRET not in str(info.value)


def test_other_400_is_not_retried_nor_blamed_on_the_model(fake: FakeDeepSeek) -> None:
    fake.chat = lambda body: (400, {"error": {"message": "messages: content is too long"}})
    llm = DeepSeekProvider(api_key=SECRET, base_url=fake.url, model="deepseek-reasoner", reasoning=True)
    with pytest.raises(Exception, match=r"content is too long") as info:
        llm.complete(MESSAGES, json_mode=True)
    assert len(fake.requests) == 1
    assert "vérifie son nom" not in str(info.value)


def test_reasoning_only_answer_is_an_error(fake: FakeDeepSeek) -> None:
    fake.chat = lambda body: _reply("")
    llm = DeepSeekProvider(api_key=SECRET, base_url=fake.url, model="deepseek-reasoner")
    with pytest.raises(Exception, match="seulement le raisonnement"):
        llm.complete(MESSAGES)


def test_preset_timeout_and_reasoning_reach_the_provider(make_settings: Callable[..., Settings]) -> None:
    from mangaka_engine.presets import PresetRegistry
    from mangaka_engine.providers.factory import build_llm
    from tests.conftest import PRESETS_DIR

    presets = PresetRegistry.load(PRESETS_DIR)
    s = make_settings(llm_provider="deepseek", deepseek_api_key=SECRET)
    reasoner = build_llm(s, presets, model="deepseek-reasoner")
    chat = build_llm(s, presets)
    assert isinstance(reasoner, DeepSeekProvider) and isinstance(chat, DeepSeekProvider)
    assert reasoner.reasoning and not chat.reasoning
    assert reasoner._client.timeout.read == 900 and chat._client.timeout.read == 300


# --- setup par classe de modèle (température, préambule) ---------------------------------------------
PREAMBLE = "Modèle qui raisonne : pèse les contraintes de la consigne"


def _setup_llm(
    make_settings: Callable[..., Settings], model: str, chat: Callable[[dict[str, Any]], httpx.Response]
) -> tuple[DeepSeekProvider, list[Any]]:
    """Fournisseur construit comme en vrai (presets livrés), transport httpx simulé : aucun appel réseau."""
    from mangaka_engine.presets import PresetRegistry
    from mangaka_engine.providers.factory import build_llm
    from tests.conftest import PRESETS_DIR

    sent: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        return chat(body)

    s = make_settings(llm_provider="deepseek", deepseek_api_key=SECRET)
    llm = build_llm(s, PresetRegistry.load(PRESETS_DIR), model=model)
    assert isinstance(llm, DeepSeekProvider)
    llm._client._transport = httpx.MockTransport(handler)
    return llm, sent


def _ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=_reply('{"pages": []}')[1])


def _system(body: dict[str, Any]) -> list[str]:
    return [m["content"] for m in body["messages"] if m["role"] == "system"]


def test_v4_pro_sends_no_temperature_and_the_preamble_once(make_settings: Callable[..., Settings]) -> None:
    llm, sent = _setup_llm(make_settings, "deepseek-v4-pro", _ok)
    assert llm.reasoning and llm._client.timeout.read == 900
    llm.complete(MESSAGES, json_mode=True, temperature=0.2)
    body = sent[0]
    assert "temperature" not in body
    first = body["messages"][0]
    assert first["role"] == "system" and first["content"].startswith(PREAMBLE)
    assert first["content"].endswith("\n\nTu es scénariste.")
    assert json.dumps(body, ensure_ascii=False).count(PREAMBLE) == 1
    assert len(body["messages"]) == len(MESSAGES)  # fondu, pas de message en plus


def test_flash_keeps_the_temperature_and_has_no_preamble(make_settings: Callable[..., Settings]) -> None:
    llm, sent = _setup_llm(make_settings, "deepseek-flash", _ok)
    assert not llm.reasoning and llm.preamble == ""
    llm.complete(MESSAGES, json_mode=True, temperature=0.2)
    llm.complete(MESSAGES)
    assert sent[0]["temperature"] == 0.2 and sent[1]["temperature"] == 0.7
    assert sent[0]["messages"] == [{"role": m.role, "content": m.content} for m in MESSAGES]


@pytest.mark.parametrize("model", ["mon-deepseek-reasoner-x", "deepseek-v4-pro-0925", "maison-r1"])
def test_unknown_reasoning_name_gets_the_reasoning_setup(make_settings: Callable[..., Settings], model: str) -> None:
    llm, sent = _setup_llm(make_settings, model, _ok)
    llm.complete(MESSAGES)
    assert llm.reasoning and "temperature" not in sent[0]
    assert sent[0]["messages"][0]["content"].startswith(PREAMBLE)


def test_unknown_plain_name_stays_fast(make_settings: Callable[..., Settings]) -> None:
    llm, sent = _setup_llm(make_settings, "deepseek-v4-preview", _ok)
    llm.complete(MESSAGES)
    assert not llm.reasoning and sent[0]["temperature"] == 0.7 and PREAMBLE not in json.dumps(sent, ensure_ascii=False)


def test_retry_and_json_fallback_keep_a_single_preamble(make_settings: Callable[..., Settings]) -> None:
    def chat(body: dict[str, Any]) -> httpx.Response:
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
        return _ok(body)

    llm, sent = _setup_llm(make_settings, "deepseek-v4-pro", chat)
    llm.complete(MESSAGES, json_mode=True)
    # Relance d'un agent : la conversation repart avec la réponse refusée et la correction demandée.
    retry = [*MESSAGES, ChatMessage("assistant", "{}"), ChatMessage("user", "Corrige : champ manquant.")]
    llm.complete(retry, json_mode=True)
    # Messages déjà préfixés (relance qui réutilise la requête envoyée) : pas de doublon.
    llm.complete([ChatMessage("system", f"{llm.preamble}\n\nTu es scénariste."), MESSAGES[1]], json_mode=True)
    assert len(sent) == 6 and all("response_format" not in b for b in sent[1::2])
    assert "JSON" in sent[1]["messages"][-1]["content"]
    for body in sent:
        assert json.dumps(body, ensure_ascii=False).count(PREAMBLE) == 1
        assert _system(body)[0].startswith(PREAMBLE)


def test_setup_follows_the_agent_model_without_restart(
    make_settings: Callable[..., Settings], fake: FakeDeepSeek
) -> None:
    fake.chat = lambda body: _reply('{"oups": true}')
    with _client(make_settings, llm_provider="deepseek", deepseek_api_key=SECRET, deepseek_base_url=fake.url) as c:
        ctx = c.app.state.ctx  # type: ignore[attr-defined]
        for model, reasoning in (("deepseek-v4-pro", True), ("deepseek-flash", False)):
            r = c.put("/agents/scenariste/profile", json={"values": {"model": model}})
            assert r.status_code == 200, r.text
            llm, _ = ctx.agents.llm_for("scenariste", None)
            assert llm.model == model and llm.reasoning is reasoning
            assert llm.preamble.startswith(PREAMBLE) if reasoning else llm.preamble == ""


# --- choix par agent, essai ----------------------------------------------------------------------
def test_model_is_chosen_per_agent_and_used_by_the_trial(
    make_settings: Callable[..., Settings], fake: FakeDeepSeek
) -> None:
    fake.chat = lambda body: _reply('{"oups": true}')
    with _client(make_settings, llm_provider="deepseek", deepseek_api_key=SECRET, deepseek_base_url=fake.url) as c:
        r = c.put("/agents/scenariste/profile", json={"values": {"model": "deepseek-reasoner"}})
        assert r.status_code == 200, r.text
        ctx = c.app.state.ctx  # type: ignore[attr-defined]
        scenariste, _ = ctx.agents.llm_for("scenariste", None)
        artist, _ = ctx.agents.llm_for("directeur-artistique", None)
        assert scenariste.model == "deepseek-reasoner" and scenariste.reasoning
        assert artist.model == "deepseek-chat"
        assert c.get("/agents/scenariste").json()["model"] == "DeepSeek · deepseek-reasoner"

        # L'essai prend le modèle du formulaire, même non enregistré.
        trial = c.post("/agents/scenariste/trial", json={"values": {"model": "deepseek-chat"}}).json()
        assert trial["llm_model"] == "deepseek · deepseek-chat"
        assert {r["body"]["model"] for r in fake.requests if r["method"] == "POST"} == {"deepseek-chat"}
        fake.requests.clear()
        trial = c.post("/agents/scenariste/trial", json={"values": {"model": "deepseek-reasoner"}}).json()
        assert trial["llm_model"] == "deepseek · deepseek-reasoner"
        sent = [r["body"] for r in fake.requests if r["method"] == "POST"]
        assert sent and all(b["model"] == "deepseek-reasoner" and "temperature" not in b for b in sent)
        # Réponse invalide : l'erreur s'affiche en clair dans l'essai, rien n'échoue en silence.
        assert trial["error"]
