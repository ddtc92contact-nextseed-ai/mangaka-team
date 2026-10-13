"""Atelier : dialogue avec l'IA sur une case (consigne → proposition → Appliquer / Annuler), LLM et ComfyUI factices."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.prompt import PromptCharacter, ReferenceSlot
from mangaka_engine.pipeline.prompt_dialog import (
    DialogBrief,
    DialogTurnBrief,
    PromptDialogError,
    ReferenceOption,
    parse_dialog,
    propose,
    render_messages,
)
from mangaka_engine.pipeline.prompt_writer import PromptBrief, PromptValidationError
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import ChatMessage, MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_dialog
from tests.conftest import PRESETS_DIR, STYLE, force_stages, png_bytes

CLOSE_UP = "gros plan sur le visage de Lucius, en contre-plongée"


def _dialog_calls(llm: MockLLMProvider) -> list[list[ChatMessage]]:
    return [m for m in llm.calls if any('"task": "image_prompt_dialog"' in x.content for x in m)]


class Env:
    def __init__(self, c: TestClient, llm: MockLLMProvider, comfy: MockComfyUIClient) -> None:
        self.c, self.llm, self.comfy = c, llm, comfy


@pytest.fixture
def env(make_settings: Callable[..., Settings]) -> Iterator[Env]:
    llm, comfy = MockLLMProvider(), MockComfyUIClient()
    providers = Providers(
        llm=llm,
        vision=None,
        comfyui=comfy,
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(make_settings(), providers=providers)) as c:
        yield Env(c, llm, comfy)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _wait(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]


def _setup(c: TestClient, **series: Any) -> dict[str, Any]:
    """Série : Lucius (planche en pied, puis portrait), Stan (une image), Mira absente. Deux cases."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Veilleurs", **series}), 201)
    lucius = _ok(
        c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius", "visual_description": "cape noire"}), 201
    )
    files = [("files", ("pied.png", png_bytes(), "image/png")), ("files", ("portrait.png", png_bytes(), "image/png"))]
    _ok(c.post(f"/characters/{lucius['id']}/images", files=files), 201)
    stan = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Stan", "visual_description": "roux"}), 201)
    _ok(c.post(f"/characters/{stan['id']}/images", files=[("files", ("stan.png", png_bytes(), "image/png"))]), 201)
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Mira"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Nuit"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {
                                "description": "Lucius fait face à Stan sur le pont.",
                                "characters": ["Lucius", "Stan"],
                                "shot_type": "plan moyen",
                                "setting": "pont de pierre, la nuit",
                            },
                            {"description": "Stan s'enfuit.", "characters": ["Stan"], "shot_type": "plan large"},
                        ]
                    }
                ]
            },
        )
    )
    images = _ok(c.get(f"/characters/{lucius['id']}"))["reference_images"]
    return {
        "series": s,
        "chapter": ch,
        "panels": pages[0]["panels"],
        "lucius": lucius,
        "full_body": images[0]["id"],
        "portrait": images[1]["id"],
    }


# --- de bout en bout (API) -------------------------------------------------------------------------------
def test_close_up_instruction_is_previewed_then_applied(env: Env) -> None:
    c = env.c
    data = _setup(c)
    pid = data["panels"][0]["id"]
    before = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))  # prompt rédigé par l'IA, plan moyen

    turn = _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": CLOSE_UP}), 201)
    assert turn["status"] == "proposed" and turn["instruction"] == CLOSE_UP
    assert turn["prompt_before"] == before["final_prompt"]
    assert "close-up" in turn["prompt_after"] and "Lucius" in turn["prompt_after"] and "Stan" in turn["prompt_after"]
    assert "Mira" not in turn["prompt_after"]
    changes = {ch["field"]: ch for ch in turn["changes"]}
    assert changes["plan"] == {"field": "plan", "label": "Plan", "before": "plan moyen", "after": "gros plan"}
    assert changes["angle"]["after"] == "en contre-plongée"
    ref = changes[f"reference.{data['lucius']['id']}"]
    assert ref["label"] == "Référence de Lucius" and ref["after"].startswith("portrait.png (image 2")
    assert ref["before"].startswith("pied.png (image 1")
    assert turn["explanation"].startswith("J'ai changé")

    # aperçu seulement : la case n'a pas bougé
    panel = _ok(c.get(f"/panels/{pid}"))
    assert panel["final_prompt"] == before["final_prompt"] and panel["dialog_overrides"] == []

    # le LLM a reçu la consigne, le prompt actuel, la direction, les références au choix
    [call] = _dialog_calls(env.llm)
    user = call[1].content
    assert CLOSE_UP in user and before["final_prompt"] in user and "plan: plan moyen" in user
    assert f"Lucius: image_id {data['portrait']} = portrait.png" in user
    assert "gros plan = close-up" in user and "(first request on this panel)" in user

    out = _ok(c.post(f"/panel-dialog/{turn['id']}/apply"))
    assert out["jobs"] == [] and out["turn"]["status"] == "applied" and out["turn"]["applied_at"]
    panel = out["panel"]
    assert panel["final_prompt"] == turn["prompt_after"] and panel["final_prompt_manual"] is True
    assert panel["dialog_overrides"][:2] == ["Plan : gros plan", "Angle : en contre-plongée"]
    assert panel["dialog_overrides"][2].startswith("Référence de Lucius : portrait.png")
    assert panel["images"] == []  # « Appliquer » seul ne génère rien

    # historique gardé ; la consigne suivante le reçoit
    history = _ok(c.get(f"/panels/{pid}/dialog"))
    assert [(t["id"], t["status"]) for t in history] == [(turn["id"], "applied")]
    _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": "Stan doit être en train de courir"}), 201)
    user = _dialog_calls(env.llm)[-1][1].content
    assert f"- Author: {CLOSE_UP}" in user and "(applied)" in user and "plan: gros plan" in user


def test_apply_and_generate_sends_the_portrait_and_touches_only_this_panel(env: Env) -> None:
    c = env.c
    data = _setup(c)
    pid, other = data["panels"][0]["id"], data["panels"][1]["id"]
    turn = _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": CLOSE_UP}), 201)
    out = _ok(c.post(f"/panel-dialog/{turn['id']}/apply", json={"generate": True}))
    assert len(out["jobs"]) == 1 and out["jobs"][0]["panel_id"] == pid
    _wait(c)

    [img] = _ok(c.get(f"/panels/{pid}/images"))
    assert img["params"]["panel_prompt"] == turn["prompt_after"]
    assert _ok(c.get(f"/panels/{other}/images")) == []
    # le workflow envoyé à ComfyUI charge le portrait de Lucius, plus sa planche en pied
    [wf] = env.comfy.prompts.values()
    loaded = [n["inputs"]["image"] for n in wf.values() if n["class_type"] == "LoadImage"]
    lucius_dir = f"personnages/{data['lucius']['slug']}"
    assert any(name.endswith(f"{lucius_dir}/reference-{data['portrait']}.png") for name in loaded)
    assert not any(f"{lucius_dir}/reference-{data['full_body']}." in name for name in loaded)
    assert img["params"]["reference_images"][0]["image_id"] == data["portrait"]

    # une 2e génération garde le choix ; la version 1 reste
    _ok(c.post(f"/panels/{pid}/generate"), 202)
    _wait(c)
    images = _ok(c.get(f"/panels/{pid}/images"))
    assert [i["version"] for i in images] == [1, 2]
    assert images[1]["params"]["reference_images"][0]["image_id"] == data["portrait"]


def test_without_a_choice_the_full_body_sheet_is_sent(env: Env) -> None:
    c = env.c
    data = _setup(c)
    pid = data["panels"][0]["id"]
    _ok(c.post(f"/panels/{pid}/generate"), 202)
    _wait(c)
    [img] = _ok(c.get(f"/panels/{pid}/images"))
    assert img["params"]["reference_images"][0]["image_id"] == data["full_body"]


def test_invalid_output_is_retried_then_a_french_error_and_nothing_changes(env: Env) -> None:
    c = env.c
    pid = _setup(c)["panels"][0]["id"]
    before = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    resp = c.post(f"/panels/{pid}/dialog", json={"instruction": f"{CLOSE_UP} [mock:dialogue-invalide:9]"})
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail.startswith("L'IA n'a pas pu proposer de changement : réponse invalide 3 fois de suite")
    assert "La case n'a pas changé" in detail
    calls = _dialog_calls(env.llm)
    assert len(calls) == 3  # 1 essai + 2 relances (max_retries: 2), jamais plus
    assert "plan" in calls[1][-1].content and "valeur non autorisée" in calls[1][-1].content
    panel = _ok(c.get(f"/panels/{pid}"))
    assert panel["final_prompt"] == before["final_prompt"] and panel["dialog_overrides"] == []
    assert _ok(c.get(f"/panels/{pid}/dialog")) == []

    # une seule réponse invalide : corrigée à la relance
    turn = _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": f"{CLOSE_UP} [mock:dialogue-invalide:1]"}), 201)
    assert any(ch["after"] == "gros plan" for ch in turn["changes"]) and len(_dialog_calls(env.llm)) == 5


def test_cancel_leaves_the_panel_as_it_was(env: Env) -> None:
    c = env.c
    pid = _setup(c)["panels"][0]["id"]
    before = _ok(c.get(f"/panels/{pid}"))
    turn = _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": CLOSE_UP}), 201)
    assert _ok(c.post(f"/panel-dialog/{turn['id']}/cancel"))["status"] == "cancelled"
    after = _ok(c.get(f"/panels/{pid}"))
    assert (after["final_prompt"], after["final_prompt_manual"]) == (before["final_prompt"], False)
    assert after["dialog_overrides"] == []
    resp = c.post(f"/panel-dialog/{turn['id']}/apply")
    assert resp.status_code == 422 and "annulée" in resp.text

    # une nouvelle consigne annule la proposition précédente restée en attente
    first = _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": CLOSE_UP}), 201)
    _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": "plan large"}), 201)
    statuses = [t["status"] for t in _ok(c.get(f"/panels/{pid}/dialog")) if t["id"] >= first["id"]]
    assert statuses == ["cancelled", "proposed"]


def test_dialog_edit_survives_chapter_rebuilds_until_rebuild_prompt(env: Env) -> None:
    c = env.c
    data = _setup(c)
    pid = data["panels"][0]["id"]
    turn = _ok(c.post(f"/panels/{pid}/dialog", json={"instruction": CLOSE_UP}), 201)
    _ok(c.post(f"/panel-dialog/{turn['id']}/apply"))

    # génération du chapitre, série repassée aux fragments puis à l'IA : le prompt du dialogue reste
    force_stages(c, data["chapter"]["id"])
    _ok(c.post(f"/chapters/{data['chapter']['id']}/generate", json={}), 202)
    _wait(c)
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"ai_prompt": False}))
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"ai_prompt": True}))
    panel = _ok(c.get(f"/panels/{pid}"))
    assert panel["final_prompt"] == turn["prompt_after"] and panel["final_prompt_manual"] is True
    assert panel["prompt_pending"] is False and "Plan : gros plan" in panel["dialog_overrides"]
    [img] = panel["images"]
    assert img["params"]["panel_prompt"] == turn["prompt_after"]

    # « Reconstruire le prompt » : retour à la direction de la page et au prompt rédigé
    panel = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    assert panel["final_prompt_manual"] is False and panel["dialog_overrides"] == []
    assert panel["prompt_source"] == "ia" and "close-up" not in panel["final_prompt"]


def test_rebuild_prompt_accepts_an_instruction(env: Env) -> None:
    c = env.c
    pid = _setup(c)["panels"][0]["id"]
    panel = _ok(c.post(f"/panels/{pid}/prompt/rebuild", json={"instruction": CLOSE_UP}))
    assert panel["prompt_source"] == "ia" and panel["final_prompt_manual"] is False
    assert "close-up" in panel["final_prompt"] and panel["prompt_pending"] is False
    assert "Plan : gros plan" in panel["dialog_overrides"]
    [call] = _dialog_calls(env.llm)
    assert "(first request on this panel)" in call[1].content
    assert "(none yet: write it from the panel data)" in call[1].content
    [turn] = _ok(c.get(f"/panels/{pid}/dialog"))
    assert turn["status"] == "applied" and turn["instruction"] == CLOSE_UP

    # en échec : erreur lisible, case inchangée (choix du dialogue précédent compris)
    resp = c.post(f"/panels/{pid}/prompt/rebuild", json={"instruction": "plan large [mock:dialogue-invalide:9]"})
    assert resp.status_code == 502 and "La case n'a pas changé" in resp.json()["detail"]
    after = _ok(c.get(f"/panels/{pid}"))
    assert after["final_prompt"] == panel["final_prompt"] and after["dialog_overrides"] == panel["dialog_overrides"]

    # sans consigne : comme avant (pas de dialogue)
    plain = _ok(c.post(f"/panels/{pid}/prompt/rebuild", json={}))
    assert plain["dialog_overrides"] == [] and len(_dialog_calls(env.llm)) == 4


def test_dialog_works_for_a_fragment_series_and_is_kept(env: Env) -> None:
    c = env.c
    pid = _setup(c, ai_prompt=False)["panels"][0]["id"]
    panel = _ok(c.post(f"/panels/{pid}/prompt/rebuild", json={"instruction": "plan large, de dos"}))
    assert panel["final_prompt_manual"] is True and "wide shot" in panel["final_prompt"]
    _ok(c.post(f"/panels/{pid}/generate"), 202)
    _wait(c)
    assert _ok(c.get(f"/panels/{pid}"))["final_prompt"] == panel["final_prompt"]


def test_empty_instruction_is_refused(env: Env) -> None:
    pid = _setup(env.c)["panels"][0]["id"]
    resp = env.c.post(f"/panels/{pid}/dialog", json={"instruction": "  "})
    assert resp.status_code == 422 and resp.json()["errors"][0]["field"] == "instruction"


# --- validation (fonctions pures) ---------------------------------------------------------------------------
def _dialog(**kw: Any) -> DialogBrief:
    reg = PresetRegistry.load(PRESETS_DIR)
    brief = PromptBrief.build(
        description="Lucius fait face à Stan.",
        plan="plan moyen",
        characters=[PromptCharacter("Lucius", "cape noire"), PromptCharacter("Stan", "roux")],
        absent=["Mira"],
        references=[ReferenceSlot("character", "Lucius"), ReferenceSlot("character", "Stan")],
        style="seinen manga",
        prompt=reg.prompt("redacteur-image"),
        settings=reg.image_prompt,
    )
    options = [
        ReferenceOption(1, "Lucius", 10, "Plein pied (image 1, principale)", current=True),
        ReferenceOption(1, "Lucius", 11, "Portrait de face (image 2)"),
    ]
    values: dict[str, Any] = {
        "current_prompt": "<image1> is Lucius.",
        "direction": {"plan": "plan moyen"},
        "options": options,
        "presets": reg,
        **kw,
    }
    return DialogBrief.build(brief, "gros plan sur Lucius", **values)


def _answer(d: DialogBrief, **kw: Any) -> str:
    out = mock_dialog(d.as_json())
    out.update(kw)
    return json.dumps(out)


def test_parse_dialog_keeps_only_what_changes() -> None:
    d = _dialog()
    proposal = parse_dialog(_answer(d, direction={"plan": "Gros Plan", "angle": "contre-plongée"}), d)
    assert proposal.direction == {"plan": "gros plan", "angle": "en contre-plongée"}
    assert proposal.references == {1: 11}  # le portrait, choisi par le mock pour un gros plan
    assert proposal.prompt.rstrip(".").endswith("seinen manga")
    # même plan qu'aujourd'hui, image déjà envoyée : rien ne change
    same = parse_dialog(
        _answer(d, direction={"plan": "plan moyen"}, references=[{"character": "lucius", "image_id": 10}]), d
    )
    assert same.direction == {} and same.references == {} and same.changes == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"direction": {"plan": "plan drone"}}, "direction › plan : valeur non autorisée"),
        ({"direction": {"angle": "de biais"}}, "direction › angle : valeur non autorisée"),
        ({"references": [{"character": "Lucius", "image_id": 99}]}, "image 99 inconnue pour Lucius (images : 10, 11)"),
        ({"references": [{"character": "Stan", "image_id": 10}]}, "« Stan » n'a pas d'image à choisir"),
        ({"explanation": ""}, "explanation : ne doit pas être vide"),
        ({"prompt": "Lucius alone in close-up."}, "images de référence non citées"),
    ],
)
def test_parse_dialog_refuses_invalid_values(change: dict[str, Any], message: str) -> None:
    d = _dialog()
    with pytest.raises(PromptValidationError) as exc:
        parse_dialog(_answer(d, **change), d)
    assert message in str(exc.value)


def test_propose_retries_at_most_twice_then_fails() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    d = _dialog(history=[DialogTurnBrief("plus sombre", "J'ai assombri la scène.", "applied")])
    llm = MockLLMProvider(invalid_attempts=9)
    with pytest.raises(PromptDialogError, match="réponse invalide 3 fois de suite"):
        propose(llm, reg.prompt("redacteur-image-dialogue"), d)
    assert len(llm.calls) == 3
    run = propose(MockLLMProvider(invalid_attempts=2), reg.prompt("redacteur-image-dialogue"), d)
    assert run.attempts == 3 and run.proposal.direction["plan"] == "gros plan"


def test_dialog_messages_come_from_the_preset() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    d = _dialog(history=[DialogTurnBrief("plus sombre", "J'ai assombri la scène.", "cancelled")])
    system, user = render_messages(reg.prompt("redacteur-image-dialogue"), d)
    assert "plan large, plan moyen, plan rapproché, gros plan" in system.content
    assert "en contre-plongée" in system.content
    assert "Author's instruction (French): gros plan sur Lucius" in user.content
    assert "- Lucius: image_id 11 = Portrait de face (image 2)" in user.content
    assert "(cancelled by the author)" in user.content
    ctx = json.loads(user.content.split("<contexte>")[1].split("</contexte>")[0])
    assert ctx["task"] == "image_prompt_dialog" and ctx["allowed"]["plan"][0] == "plan large"
