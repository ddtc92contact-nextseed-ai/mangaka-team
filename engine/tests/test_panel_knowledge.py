"""Savoir-faire d'une case : deux budgets coupés dans la même recherche — passages entiers pour le rédacteur
de prompt (LLM), note courte pour le prompt par fragments — collections de la série, requête enrichie de la
direction artistique, budget réglable dans « L'équipe ». LLM, embeddings et ComfyUI factices."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import panel_cast, panel_query
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import ChatMessage, MockLLMProvider
from mangaka_engine.store.models import Panel
from tests.conftest import STYLE

PASSAGE = re.compile(r"^\[(\d+)\] « ([^»]+) »", re.MULTILINE)


class Env:
    def __init__(self, c: TestClient, llm: MockLLMProvider) -> None:
        self.c, self.llm = c, llm

    @property
    def ctx(self) -> Any:
        return self.c.app.state.ctx  # type: ignore[attr-defined]


@pytest.fixture
def env(make_settings: Callable[..., Settings]) -> Iterator[Env]:
    llm = MockLLMProvider()
    providers = Providers(
        llm=llm,
        vision=None,
        comfyui=MockComfyUIClient(),
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(make_settings(), providers=providers)) as c:
        yield Env(c, llm)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _writer_calls(llm: MockLLMProvider) -> list[list[ChatMessage]]:
    return [m for m in llm.calls if any('"task": "image_prompt"' in x.content for x in m)]


def _fiche(subject: str) -> str:
    """Fiche d'environ 150 jetons (≈ 600 caractères) sur un sujet de cadrage."""
    sentence = f"Pour un {subject}, le cadrage serre le visage du sabreur et la pluie tombe en diagonale. "
    return (sentence * 8)[:600]


# 7 fiches pertinentes (≈ 1 050 jetons au total : la collection dépasse le seuil « petite collection » de
# 1 200 jetons avec les 2 fiches hors sujet, donc la recherche s'applique).
RELEVANT = [f"Gros plan {i}" for i in range(1, 8)]
OFF_TOPIC = {
    "Recettes": "Mélanger la farine et le beurre, puis enfourner vingt minutes à four chaud. " * 7,
    "Jardinage": "Arroser les tomates le soir et tailler les gourmands chaque semaine au potager. " * 7,
}


def _knowledge(c: TestClient, name: str = "Mise en page", project_id: int | None = None) -> dict:
    col = _ok(c.post("/knowledge/collections", json={"name": name, "project_id": project_id}), 201)
    for title in RELEVANT:
        body = {"title": title, "content": _fiche("gros plan en contre-plongée")}
        _ok(c.post(f"/knowledge/collections/{col['id']}/documents", json=body), 201)
    for title, content in OFF_TOPIC.items():
        _ok(c.post(f"/knowledge/collections/{col['id']}/documents", json={"title": title, "content": content}), 201)
    return col


def _series(c: TestClient, title: str = "Les Lames", **kw: Any) -> dict:
    s = _ok(c.post("/projects", json={**STYLE, "title": title, **kw}), 201)
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko", "visual_description": "cheveux noirs"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    panel = {
        "description": "Gros plan sur le sabreur Aiko sous la pluie, en contre-plongée",
        "characters": ["Aiko"],
        "shot_type": "gros plan",
    }
    pages = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel]}]}))
    return {"series": s, "panel": pages[0]["panels"][0]}


def _note(prompt: str) -> str:
    match = re.search(r"Style notes: (.*?)\. (?:[A-Z]|$)", prompt)
    return match.group(1) if match else ""


# --- deux budgets ---------------------------------------------------------------------------
def test_writer_gets_full_passages_with_sources_and_fragments_keep_the_short_note(env: Env) -> None:
    c = env.c
    _knowledge(c)
    data = _series(c)
    pid = data["panel"]["id"]

    seen = _ok(c.get(f"/panels/{pid}/knowledge"))
    writer, fragments = seen["writer"], seen["fragments"]
    assert (writer["budget_tokens"], writer["top_k"]) == (1200, 5)  # presets/knowledge.yaml
    assert (fragments["budget_tokens"], fragments["top_k"]) == (160, 2)
    assert len(writer["passages"]) == 5 and writer["tokens"] <= writer["budget_tokens"]
    assert {p["document_title"] for p in writer["passages"]} <= set(RELEVANT)
    assert 1 <= len(fragments["passages"]) <= 2 and fragments["text_tokens"] <= fragments["budget_tokens"]
    assert "\n" not in fragments["text"] and "«" not in fragments["text"]

    _ok(c.post(f"/panels/{pid}/prompt/rebuild"))  # rédaction par le LLM factice
    [call] = _writer_calls(env.llm)
    user = call[-1].content
    found = PASSAGE.findall(user)
    assert [int(n) for n, _ in found] == [1, 2, 3, 4, 5]
    assert [t for _, t in found] == [p["document_title"] for p in writer["passages"]]
    assert f"({'Mise en page'})\n" + _fiche("gros plan en contre-plongée").strip() in user  # passage entier
    assert not any(t in user for t in OFF_TOPIC)


def test_writer_disabled_or_failing_gives_today_fragment_prompt(env: Env) -> None:
    c = env.c
    _knowledge(c)
    data = _series(c, ai_prompt=False)
    pid = data["panel"]["id"]
    fragments = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))["final_prompt"]
    note = _note(fragments)
    assert note and len(note) <= 160 * 4 + 1 and "Gros plan" not in fragments.split("Style notes:")[1][:20]

    # mêmes réglages qu'avant les budgets du rédacteur : prompt par fragments identique au caractère près
    settings = env.ctx.knowledge.settings
    old = settings.model_copy(deep=True)
    agent = old.agents["image_prompt"]
    agent.writer_budget_tokens = agent.writer_top_k = agent.writer_bible_max_tokens = None
    env.ctx.knowledge.settings = old
    assert _ok(c.post(f"/panels/{pid}/prompt/rebuild"))["final_prompt"] == fragments
    env.ctx.knowledge.settings = settings

    # rédacteur en panne : repli sur ce même prompt par fragments, sans les passages entiers
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"ai_prompt": True}))
    env.llm._responder = lambda _m, _j: "pas du JSON"
    panel = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    assert panel["prompt_source"] == "fragments" and panel["prompt_warning"]
    assert panel["final_prompt"] == fragments
    assert len(_writer_calls(env.llm)) == 2 and "[1] «" in _writer_calls(env.llm)[0][-1].content


# --- collections de la série ------------------------------------------------------------------
def test_series_collection_feeds_only_the_panels_of_its_series(env: Env) -> None:
    c = env.c
    a, b = _series(c, "Série A"), _series(c, "Série B")
    _knowledge(c, "Lore de A", project_id=a["series"]["id"])
    seen_a = _ok(c.get(f"/panels/{a['panel']['id']}/knowledge"))
    seen_b = _ok(c.get(f"/panels/{b['panel']['id']}/knowledge"))
    assert seen_a["collections"] == ["Lore de A"] and seen_a["writer"]["passages"]
    assert {p["collection_name"] for p in seen_a["writer"]["passages"]} == {"Lore de A"}
    assert seen_b["collections"] == [] and seen_b["writer"]["passages"] == []
    assert seen_b["fragments"]["passages"] == []


# --- requête ----------------------------------------------------------------------------------
def test_panel_query_includes_the_art_direction(env: Env) -> None:
    c = env.c
    data = _series(c)
    pid = data["panel"]["id"]
    with env.ctx.db.session_scope() as session:
        panel = session.get(Panel, pid)
        assert panel is not None
        panel.dialog_direction = {
            "plan": "plan américain",
            "angle": "contre-plongée",
            "ambiance": "nuit orageuse",
            "action": "dégaine son sabre",
        }
        query = panel_query(session, panel, panel_cast(session, panel).characters)
        session.commit()
    for value in ("plan américain", "contre-plongée", "nuit orageuse", "dégaine son sabre", "Aiko"):
        assert value in query
    assert query.startswith("plan américain ")  # le plan suivi (dialogue) remplace celui du scénario
    assert "plan américain" in _ok(c.get(f"/panels/{pid}/knowledge"))["query"]


# --- réglable dans « L'équipe » ---------------------------------------------------------------
def test_budget_edited_in_the_team_changes_what_the_writer_receives(env: Env) -> None:
    c = env.c
    _knowledge(c)
    data = _series(c)
    pid, sid = data["panel"]["id"], data["series"]["id"]
    detail = _ok(c.get("/agents/dessinateur"))
    assert detail["knowledge"]["value"]["budget_tokens"] == 1200 and detail["knowledge"]["value"]["top_k"] == 5

    knowledge = {**detail["knowledge"]["value"], "budget_tokens": 320}
    _ok(c.put(f"/agents/dessinateur/profile?project_id={sid}", json={"values": {}, "knowledge": knowledge}))
    seen = _ok(c.get(f"/panels/{pid}/knowledge"))
    assert seen["writer"]["budget_tokens"] == 320 and len(seen["writer"]["passages"]) == 2
    assert seen["writer"]["tokens"] <= 320
    assert seen["fragments"]["budget_tokens"] == 160  # la note des fragments ne bouge pas

    _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    assert [int(n) for n, _ in PASSAGE.findall(_writer_calls(env.llm)[-1][-1].content)] == [1, 2]

    # une autre série garde le budget livré
    other = _series(c, "Autre")
    assert _ok(c.get(f"/panels/{other['panel']['id']}/knowledge"))["writer"]["budget_tokens"] == 1200
    # budget vidé (null) : celui de knowledge.yaml
    reset = {**knowledge, "budget_tokens": None}
    saved = _ok(c.put(f"/agents/dessinateur/profile?project_id={sid}", json={"values": {}, "knowledge": reset}))
    assert saved["knowledge"]["value"]["budget_tokens"] == 1200


@pytest.mark.parametrize("budget", [-1, 999_999, "beaucoup", 12.5])
def test_invalid_budget_is_refused_in_french(env: Env, budget: Any) -> None:
    knowledge = {"collections": ["Mise en page"], "top_k": 5, "budget_tokens": budget}
    r = env.c.put("/agents/dessinateur/profile", json={"values": {}, "knowledge": knowledge})
    assert r.status_code == 422, r.text
    [error] = r.json()["errors"]
    assert error["field"] == "knowledge.budget_tokens"
    assert re.search(r"[àéèêç]|doit|nombre|entier", error["message"]), error["message"]


def test_script_and_art_direction_budgets_follow_the_profile_too(env: Env) -> None:
    c = env.c
    for agent_id, role in (("scenariste", "script"), ("directeur-artistique", "art_direction")):
        detail = _ok(c.get(f"/agents/{agent_id}"))
        knowledge = {**detail["knowledge"]["value"], "budget_tokens": 700}
        _ok(c.put(f"/agents/{agent_id}/profile", json={"values": {}, "knowledge": knowledge}))
        with env.ctx.db.session_scope() as session:
            assert env.ctx.knowledge.budget_tokens(session, role, None) == 700
        status = _ok(c.get("/knowledge/status"))
        assert next(a for a in status["agents"] if a["role"] == role)["budget_tokens"] == 700
