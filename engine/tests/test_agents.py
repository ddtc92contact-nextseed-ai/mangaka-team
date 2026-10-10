"""Écran « L'équipe » : registre des agents, profils versionnés, résolution série > global > presets."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.providers.llm import MockLLMProvider

SECRET = "sk-test-ne-jamais-afficher-42"


@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(deepseek_api_key=SECRET))) as client:
        yield client


def _ctx(c: TestClient) -> Any:
    return c.app.state.ctx  # type: ignore[attr-defined]


def _series(c: TestClient, title: str = "Série") -> int:
    r = c.post("/projects", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _setting(detail: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in detail["settings"] if s["key"] == key)


def _save(c: TestClient, agent: str, values: dict[str, Any], project_id: int | None = None, **extra: Any) -> Any:
    q = f"?project_id={project_id}" if project_id else ""
    return c.put(f"/agents/{agent}/profile{q}", json={"values": values, **extra})


def _script(c: TestClient, series_id: int) -> dict[str, Any]:
    ch = c.post(f"/projects/{series_id}/chapters", json={"synopsis": "Aiko défie Ren.", "target_page_count": 1})
    r = c.post(f"/chapters/{ch.json()['id']}/script")
    assert r.status_code == 202, r.text
    _ctx(c).jobs.wait(r.json()["id"])
    job = c.get(f"/jobs/{r.json()['id']}").json()
    assert job["status"] == "succeeded", job
    return job


# --- registre --------------------------------------------------------------------------------
def test_registry_lists_the_six_agents_ready_in_mock_mode(c: TestClient) -> None:
    agents = c.get("/agents").json()
    assert [a["id"] for a in agents] == [
        "scenariste",
        "directeur-artistique",
        "metteur-en-page",
        "dessinateur",
        "controleur-qualite",
        "lettreur",
    ]
    assert [a["name"] for a in agents][0] == "Scénariste"
    assert all(a["status"]["state"] == "ready" for a in agents), agents
    scen = agents[0]
    assert scen["step"] == 1 and scen["model"] == "Factice (mode mock)" and scen["last_run"] is None
    assert not _ctx(c).presets.issues, _ctx(c).presets.issues


def test_agent_detail_shows_settings_with_their_preset_source(c: TestClient) -> None:
    d = c.get("/agents/scenariste").json()
    temp = _setting(d, "temperature")
    assert temp["value"] == 0.7 and temp["origin"] == "preset" and temp["source"].startswith("presets/prompts/script")
    system = _setting(d, "system")
    assert system["type"] == "prompt" and "series_title" in system["variables"]
    shipped = {"collections": ["Écriture de scénario", "Rythme et découpage", "Humour jeunesse"], "top_k": 6}
    assert d["knowledge"] == {"value": shipped, "origin": "preset", "inherited": shipped}  # knowledge.yaml
    assert d["secrets"] == [{"env": "DEEPSEEK_API_KEY", "label": "Clé d'API DeepSeek", "present": True}]
    templates = _setting(c.get("/agents/metteur-en-page").json(), "templates")
    assert templates["type"] == "yaml" and "1-pleine-page" in templates["value"]
    assert c.get("/agents/inconnu").status_code == 404


def test_no_profile_keeps_the_loaded_presets(c: TestClient) -> None:
    ctx = _ctx(c)
    sid = _series(c)
    assert ctx.agents.presets_for(None) is ctx.presets
    assert ctx.agents.presets_for(sid) is ctx.presets


# --- résolution ------------------------------------------------------------------------------
def test_resolution_order_series_over_global_over_preset(c: TestClient) -> None:
    a, b = _series(c, "A"), _series(c, "B")
    assert _save(c, "scenariste", {"temperature": 0.3}).status_code == 200
    assert _save(c, "scenariste", {"temperature": 0.5}, a).status_code == 200

    glob = _setting(c.get("/agents/scenariste").json(), "temperature")
    assert (glob["value"], glob["origin"], glob["preset"]) == (0.3, "global", 0.7)
    in_a = _setting(c.get(f"/agents/scenariste?project_id={a}").json(), "temperature")
    assert (in_a["value"], in_a["origin"], in_a["inherited"]) == (0.5, "series", 0.3)
    in_b = _setting(c.get(f"/agents/scenariste?project_id={b}").json(), "temperature")
    assert (in_b["value"], in_b["origin"]) == (0.3, "global")
    # Un réglage non modifié reste celui du preset partout.
    assert _setting(c.get(f"/agents/scenariste?project_id={a}").json(), "max_retries")["origin"] == "preset"

    agents = _ctx(c).agents
    assert agents.presets_for(a).prompt("script").temperature == 0.5
    assert agents.presets_for(b).prompt("script").temperature == 0.3
    assert agents.presets_for(None).prompt("script").temperature == 0.3
    assert _ctx(c).presets.prompt("script").temperature == 0.7  # presets livrés intacts


def test_series_override_does_not_affect_another_series(c: TestClient) -> None:
    a, b = _series(c, "A"), _series(c, "B")
    r = _save(c, "lettreur", {"speech_font": "comic-neue", "speech_size": 10}, a)
    assert r.status_code == 200, r.text
    agents = _ctx(c).agents
    assert agents.presets_for(a).require_fonts().styles["speech"].font == "comic-neue"
    assert agents.presets_for(a).require_fonts().styles["speech"].size_pt == 10
    assert agents.presets_for(b).require_fonts().styles["speech"].font == "baloo2"
    assert agents.presets_for(None).require_fonts().styles["speech"].font == "baloo2"
    assert _setting(c.get(f"/agents/lettreur?project_id={b}").json(), "speech_font")["origin"] == "preset"

    overrides = c.get(f"/projects/{a}/agents").json()
    assert [o["agent_id"] for o in overrides] == ["lettreur"]
    assert {s["key"] for s in overrides[0]["settings"]} == {"speech_font", "speech_size"}
    assert c.get(f"/projects/{b}/agents").json() == []


def test_value_equal_to_inherited_is_not_stored(c: TestClient) -> None:
    sid = _series(c)
    _save(c, "scenariste", {"temperature": 0.3})
    r = _save(c, "scenariste", {"temperature": 0.3, "max_retries": 2}, sid)  # identiques à l'héritage
    assert r.json()["saved_version"] is None and r.json()["version"] == 0
    assert c.get(f"/projects/{sid}/agents").json() == []


def test_global_only_setting_cannot_be_overridden_per_series(c: TestClient) -> None:
    sid = _series(c)
    r = _save(c, "metteur-en-page", {"page_format": "b4-300dpi"}, sid)
    assert r.status_code == 422
    assert r.json()["errors"] == [
        {"field": "page_format", "message": "réglage commun à toutes les séries : modifie le profil global"}
    ]
    assert _save(c, "metteur-en-page", {"page_format": "b4-300dpi"}).status_code == 200
    assert c.post("/projects", json={"title": "Nouvelle"}).json()["page_format"] == "b4-300dpi"


# --- versions --------------------------------------------------------------------------------
def test_every_change_creates_a_version_and_rollback_works(c: TestClient) -> None:
    r1 = _save(c, "scenariste", {"temperature": 0.3}, author="David")
    assert r1.json()["saved_version"] == 1
    r2 = _save(c, "scenariste", {"temperature": 0.4, "max_retries": 1})
    assert r2.json()["saved_version"] == 2

    versions = c.get("/agents/scenariste/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[1]["author"] == "David" and versions[1]["created_at"]
    assert versions[1]["diff"] == [{"key": "temperature", "label": "Température", "before": 0.7, "after": 0.3}]
    assert {d["key"] for d in versions[0]["diff"]} == {"temperature", "max_retries"}

    r3 = c.post("/agents/scenariste/versions/1/restore", json={"author": "David"})
    assert r3.status_code == 200 and r3.json()["saved_version"] == 3
    d = r3.json()
    assert _setting(d, "temperature")["value"] == 0.3 and _setting(d, "max_retries")["origin"] == "preset"
    assert c.get("/agents/scenariste/versions").json()[0]["action_label"] == "Retour à une version 1"
    assert _ctx(c).agents.presets_for(None).prompt("script").temperature == 0.3

    r4 = c.post("/agents/scenariste/reset", json={})
    assert r4.json()["saved_version"] == 4
    assert _setting(r4.json(), "temperature")["origin"] == "preset"
    assert _ctx(c).agents.presets_for(None) is _ctx(c).presets
    assert c.post("/agents/scenariste/reset").json()["saved_version"] is None  # déjà d'origine
    assert c.post("/agents/scenariste/versions/99/restore").status_code == 404


def test_series_reset_returns_to_the_global_profile(c: TestClient) -> None:
    sid = _series(c)
    _save(c, "scenariste", {"temperature": 0.3})
    _save(c, "scenariste", {"temperature": 0.9}, sid)
    r = c.post(f"/agents/scenariste/reset?project_id={sid}")
    assert _setting(r.json(), "temperature")["value"] == 0.3
    assert _setting(r.json(), "temperature")["origin"] == "global"
    assert [v["version"] for v in c.get(f"/agents/scenariste/versions?project_id={sid}").json()] == [2, 1]
    assert [v["version"] for v in c.get("/agents/scenariste/versions").json()] == [1]


def test_knowledge_is_stored_even_without_a_knowledge_base(c: TestClient) -> None:
    r = _save(c, "dessinateur", {}, knowledge={"collections": ["style-shonen", "anatomie"], "top_k": 8})
    assert r.status_code == 200, r.text
    assert r.json()["knowledge"]["value"] == {"collections": ["style-shonen", "anatomie"], "top_k": 8}
    bad = _save(c, "dessinateur", {}, knowledge={"collections": [], "top_k": 0})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "knowledge.top_k"


# --- validation ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("agent", "values", "field", "message"),
    [
        ("scenariste", {"temperature": 5}, "temperature", "doit être inférieur ou égal à 2"),
        ("scenariste", {"temperature": "chaud"}, "temperature", "nombre attendu"),
        (
            "scenariste",
            {"system": "Tu écris pour $serie_inconnue."},
            "system",
            "variable inconnue : $serie_inconnue (disponibles : $series_title",
        ),
        ("scenariste", {"user": "Prix : 5 $ ."}, "user", "un « $ » isolé doit s'écrire « $$ »"),
        ("scenariste", {"provider": "openai"}, "provider", "valeur non autorisée"),
        ("lettreur", {"speech_min_size": 20}, "speech_min_size", "min_size_pt doit être ≤ size_pt"),
        ("lettreur", {"speech_font": "arial"}, "speech_font", "valeur non autorisée"),
        ("controleur-qualite", {"reject_below": 90}, "reject_below", "reject_below doit être inférieur ou égal"),
        ("metteur-en-page", {"templates": "- id: [cassé"}, "templates", "YAML invalide"),
        ("metteur-en-page", {"templates": "- id: x\n  name: X\n"}, "templates", "champ obligatoire"),
        ("dessinateur", {"parts": ["$shot.", "Avec $meteo."]}, "parts", "ligne 2 : variable inconnue : $meteo"),
        ("scenariste", {"inconnu": 1}, "inconnu", "réglage inconnu"),
    ],
)
def test_invalid_profile_is_rejected_with_a_readable_422(
    c: TestClient, agent: str, values: dict[str, Any], field: str, message: str
) -> None:
    r = _save(c, agent, values)
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["detail"] == "Réglages invalides"
    assert body["errors"][0]["field"] == field, body
    assert message in body["errors"][0]["message"], body
    assert c.get(f"/agents/{agent}/versions").json() == []  # rien d'enregistré


# --- le pipeline utilise les réglages ----------------------------------------------------------
def test_scenariste_prompt_and_temperature_are_used_by_step_1(c: TestClient) -> None:
    llm: MockLLMProvider = _ctx(c).providers.llm
    a, b = _series(c, "A"), _series(c, "B")
    system = "Tu es le scénariste maison de « $series_title ». Réponds en JSON."
    assert _save(c, "scenariste", {"system": system, "temperature": 0.25}).status_code == 200
    assert _save(c, "scenariste", {"temperature": 0.9}, a).status_code == 200

    llm.requests.clear()
    _script(c, b)
    sent = llm.requests[-1]
    assert sent["temperature"] == 0.25 and sent["json_mode"] is True
    assert sent["messages"][0].content == "Tu es le scénariste maison de « B ». Réponds en JSON."

    llm.requests.clear()
    _script(c, a)
    assert llm.requests[-1]["temperature"] == 0.9  # surcharge de la série A
    assert llm.requests[-1]["messages"][0].content.startswith("Tu es le scénariste maison de « A »")

    scen = c.get("/agents").json()[0]
    assert scen["last_run"]["status"] == "succeeded" and scen["last_run"]["duration_ms"] is not None


def test_without_profile_step_1_uses_the_preset(c: TestClient) -> None:
    llm: MockLLMProvider = _ctx(c).providers.llm
    llm.requests.clear()
    _script(c, _series(c))
    assert llm.requests[-1]["temperature"] == 0.7
    assert llm.requests[-1]["messages"][0].content.startswith("Tu es scénariste et storyboarder")


def test_dessinateur_settings_reach_the_panel_prompt(c: TestClient) -> None:
    sid = _series(c)
    r = _save(c, "dessinateur", {"parts": ["$description.", "Style maison."], "steps": 31})
    assert r.status_code == 200, r.text
    presets = _ctx(c).agents.presets_for(sid)
    assert presets.image_prompt.parts == ["$description.", "Style maison."]
    # Tous les workflows… sauf le croquis, qui garde ses quelques étapes (c'est tout son intérêt).
    assert all(w.preset.defaults["steps"] == 31 for w in presets.workflows.values() if w.preset.role != "croquis")
    assert presets.workflow("qwen-image-croquis").preset.defaults["steps"] == 6


def test_provider_without_key_is_misconfigured(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings())) as c:
        assert _save(c, "scenariste", {"provider": "deepseek"}).status_code == 200
        scen = c.get("/agents").json()[0]
        assert scen["status"]["state"] == "misconfigured"
        assert "DEEPSEEK_API_KEY" in scen["status"]["detail"]
        assert scen["model"] == "DeepSeek · deepseek-chat"
        ch = c.post(f"/projects/{_series(c)}/chapters", json={"synopsis": "Un duel."}).json()
        r = c.post(f"/chapters/{ch['id']}/script")
        assert r.status_code == 503 and "DEEPSEEK_API_KEY" in r.json()["detail"]
        secrets = c.get("/agents/scenariste").json()["secrets"]
        assert secrets[0]["present"] is False


# --- secrets ---------------------------------------------------------------------------------
def test_no_secret_is_ever_returned(c: TestClient) -> None:
    sid = _series(c)
    _save(c, "scenariste", {"provider": "deepseek", "temperature": 0.2})
    _save(c, "scenariste", {"temperature": 0.4}, sid)
    responses = [
        c.get("/agents"),
        c.get("/agents/scenariste"),
        c.get(f"/agents/scenariste?project_id={sid}"),
        c.get("/agents/scenariste/versions"),
        c.get("/agents/scenariste/export"),
        c.get(f"/projects/{sid}/agents"),
        c.get("/health"),
        c.get("/presets"),
    ]
    for r in responses:
        assert r.status_code == 200, r.text
        assert SECRET not in r.text and "sk-test" not in r.text
    assert c.get("/agents/scenariste").json()["secrets"][0]["present"] is True
    assert "api_key" not in str(c.get("/agents/scenariste").json()["settings"])


# --- essais ----------------------------------------------------------------------------------
@pytest.mark.parametrize("agent", ["scenariste", "metteur-en-page", "dessinateur", "controleur-qualite", "lettreur"])
def test_trial_runs_on_a_sample_without_touching_the_series(c: TestClient, agent: str) -> None:
    detail = c.get(f"/agents/{agent}").json()
    form = {s["key"]: s["value"] for s in detail["settings"]}
    r = c.post(f"/agents/{agent}/trial", json={"values": form})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None, body
    assert body["input"] and body["output"]
    assert c.get("/projects").json() == []
    assert c.get("/agents/scenariste/versions").json() == []
    assert c.get("/queue").json()["running"] is None


def test_scenariste_trial_uses_the_unsaved_form(c: TestClient) -> None:
    llm: MockLLMProvider = _ctx(c).providers.llm
    llm.requests.clear()
    r = c.post(
        "/agents/scenariste/trial",
        json={"values": {"system": "Consigne d'essai pour $series_title.", "temperature": 0.1}},
    )
    body = r.json()
    assert body["error"] is None
    assert llm.requests[-1]["temperature"] == 0.1
    assert body["input"][1]["text"] == "Consigne d'essai pour La Lame du vent (série d'essai)."
    assert body["output"][0]["text"].startswith("1 page(s)")
    assert c.get("/agents/scenariste/versions").json() == []  # rien d'enregistré
    bad = c.post("/agents/scenariste/trial", json={"values": {"system": "$oups"}})
    assert bad.status_code == 422 and "variable inconnue" in bad.json()["errors"][0]["message"]


def test_qc_trial_reflects_thresholds(c: TestClient) -> None:
    strict = c.post("/agents/controleur-qualite/trial", json={"values": {"ok_min": 100, "reject_below": 99}}).json()
    verdicts = [v["verdict"] for v in strict["output"][1]["data"]]
    assert verdicts == ["rejet", "rejet", "rejet"]
    default = c.post("/agents/controleur-qualite/trial", json={"values": {}}).json()
    assert default["output"][1]["data"][0]["verdict"] == "ok"


# --- export ----------------------------------------------------------------------------------
def test_export_yaml_produces_preset_files(c: TestClient) -> None:
    _save(c, "scenariste", {"temperature": 0.35, "system": "Ligne 1\nLigne 2 pour $series_title\n"})
    r = c.get("/agents/scenariste/export")
    assert r.status_code == 200
    assert (
        "attachment" in r.headers["content-disposition"] and "agent-scenariste.yaml" in r.headers["content-disposition"]
    )
    docs = list(yaml.safe_load_all(r.text))
    assert docs[0]["agent"] == "scenariste" and docs[0]["provider"] == "mock"
    assert "# presets/prompts/script.yaml" in r.text and "# presets/providers.yaml" in r.text
    script = next(d for d in docs if isinstance(d, dict) and d.get("id") == "script")
    assert script["temperature"] == 0.35 and script["system"] == "Ligne 1\nLigne 2 pour $series_title\n"
    # Le fichier exporté est un preset valide.
    from mangaka_engine.presets import PromptPreset

    assert PromptPreset.model_validate(script).temperature == 0.35


def test_unknown_series_scope_is_404(c: TestClient) -> None:
    assert c.get("/agents/scenariste?project_id=999").status_code == 404
    assert _save(c, "scenariste", {"temperature": 0.2}, 999).status_code == 404


def test_series_deletion_removes_its_overrides(c: TestClient) -> None:
    sid = _series(c)
    _save(c, "scenariste", {"temperature": 0.2}, sid)
    assert c.delete(f"/projects/{sid}").status_code == 204
    sid2 = _series(c)
    assert _ctx(c).agents.presets_for(sid2).prompt("script").temperature == 0.7


def test_qc_vision_model_from_profile_is_used(make_settings: Callable[..., Settings]) -> None:
    from mangaka_engine.providers.factory import build_providers
    from mangaka_engine.providers.vision import OllamaVisionProvider

    settings = make_settings(vision_provider="ollama")
    with TestClient(create_app(settings)) as c:
        ctx = _ctx(c)
        assert isinstance(ctx.providers.vision, OllamaVisionProvider)
        assert _save(c, "controleur-qualite", {"vision_model": "qwen3-vl:8b"}).status_code == 200
        presets = ctx.agents.presets_for(None)
        assert presets.providers.ollama.vision_model == "qwen3-vl:8b"
        vision = ctx.qc.vision_provider(presets.providers.ollama.vision_model)
        assert vision.model == "qwen3-vl:8b" and ctx.providers.vision.model == "qwen3-vl:4b"
        assert build_providers(settings, ctx.presets).vision.model == "qwen3-vl:4b"


def test_knowledge_profile_drives_the_rag_per_series(c: TestClient) -> None:
    ctx = _ctx(c)
    a, b = _series(c, "A"), _series(c, "B")
    for name in ("Rythme et découpage", "Gags maison"):
        assert c.post("/knowledge/collections", json={"name": name}).status_code in (200, 201)
    with ctx.db.session_scope() as s:
        assert ctx.knowledge.for_agent(s, "script", a, "rythme").collections == ["Rythme et découpage"]
    knowledge = {"collections": ["gags MAISON"], "top_k": 3}
    assert _save(c, "scenariste", {}, a, knowledge=knowledge).status_code == 200
    with ctx.db.session_scope() as s:
        assert ctx.knowledge.for_agent(s, "script", a, "gag").collections == ["Gags maison"]
        assert ctx.agents.knowledge_top_k(s, "script", a) == 3
        assert ctx.knowledge.for_agent(s, "script", b, "rythme").collections == ["Rythme et découpage"]
    status = c.get("/knowledge/status").json()
    script = next(a for a in status["agents"] if a["role"] == "script")
    assert script["source"] == "preset"  # profil global inchangé
    _save(c, "scenariste", {}, knowledge=knowledge)
    script = next(a for a in c.get("/knowledge/status").json()["agents"] if a["role"] == "script")
    assert (script["source"], script["collections"], script["top_k"]) == ("profile", ["gags MAISON"], 3)
