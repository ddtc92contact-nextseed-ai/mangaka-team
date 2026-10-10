"""Rédacteur de prompt : le LLM (factice) écrit le prompt image de chaque case en un paragraphe."""

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
from mangaka_engine.pipeline.prompt_writer import (
    PromptBrief,
    PromptValidationError,
    PromptWriterError,
    parse_written,
    write_prompt,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import ChatMessage, LLMUnavailableError, MockLLMProvider
from tests.conftest import PRESETS_DIR, STYLE, png_bytes


def _writer_calls(llm: MockLLMProvider) -> list[list[ChatMessage]]:
    """Appels du LLM pour la rédaction d'un prompt image (et non pour le scénario)."""
    return [m for m in llm.calls if any('"task": "image_prompt"' in x.content for x in m)]


class Env:
    def __init__(self, c: TestClient, llm: MockLLMProvider) -> None:
        self.c, self.llm = c, llm


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


def _wait(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]


def _setup(c: TestClient, description: str = "Aiko bondit vers Kenji. « Fuyez ! » crie-t-elle.", **series: Any) -> dict:
    """Série (Aiko avec référence, Kenji, Ren absent de la case), une case à deux personnages."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames", **series}), 201)
    aiko = _ok(
        c.post(
            f"/projects/{s['id']}/characters",
            json={"name": "Aiko", "visual_description": "cheveux noirs courts", "prompt_keywords": ["kimono rouge"]},
        ),
        201,
    )
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Kenji", "visual_description": "grand, lunettes"}), 201)
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Ren", "visual_description": "manteau gris"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {
                                "description": description,
                                "characters": ["Aiko", "Kenji"],
                                "shot_type": "plan large",
                                "setting": "toit d'un lycée sous la pluie",
                                "staging": "Aiko à gauche, Kenji à droite",
                            }
                        ]
                    }
                ]
            },
        )
    )
    return {"series": s, "chapter": ch, "panel": pages[0]["panels"][0]}


def _generate(c: TestClient, panel_id: int) -> dict:
    _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    _wait(c)
    return _ok(c.get(f"/panels/{panel_id}"))


# --- de bout en bout (API, LLM et ComfyUI factices) ---------------------------------------
def test_new_series_defaults_to_ai_prompt(env: Env) -> None:
    presets = _ok(env.c.get("/presets"))
    assert presets["ai_prompt_default"] is True
    s = _ok(env.c.post("/projects", json={**STYLE, "title": "Neuve"}), 201)
    assert s["ai_prompt"] is True
    s = _ok(env.c.post("/projects", json={**STYLE, "title": "Fragments", "ai_prompt": False}), 201)
    assert s["ai_prompt"] is False


def test_written_prompt_is_stored_on_the_panel_and_used_for_generation(env: Env) -> None:
    c = env.c
    data = _setup(c)
    pid = data["panel"]["id"]
    before = _ok(c.get(f"/panels/{pid}"))
    assert before["ai_prompt"] is True and before["prompt_pending"] is True

    panel = _generate(c, pid)
    prompt = panel["final_prompt"]
    assert panel["prompt_source"] == "ia" and panel["final_prompt_manual"] is False
    assert panel["prompt_pending"] is False and panel["prompt_warning"] is None
    # chaque personnage de la case nommé, avec ses traits ; la référence citée par son emplacement
    assert "Aiko" in prompt and "Kenji" in prompt and "kimono rouge" in prompt and "lunettes" in prompt
    assert "l'image 1" in prompt
    # aucun personnage hors de la case, aucune réplique entre guillemets
    assert "Ren" not in prompt.split() and "manteau gris" not in prompt
    assert "Fuyez" not in prompt and "«" not in prompt and "»" not in prompt
    # un paragraphe, dans la langue du preset, qui finit par les mots-clés de style de la série
    assert "\n" not in prompt and "Lieu :" not in prompt
    assert prompt.rstrip(".").endswith(_ok(c.get(f"/projects/{data['series']['id']}"))["style_prompt"])

    # le LLM a reçu les données structurées de la case, sans la réplique
    [call] = _writer_calls(env.llm)
    user = call[1].content
    assert "toit d'un lycée sous la pluie" in user and "Aiko à gauche" in user and "Fuyez" not in user
    assert "- image 1 : identité de Aiko" in user and "Ren" in user  # Ren : absent, à ne pas nommer

    # prompt envoyé à ComfyUI : le rédigé, cadré par les références ; négatif « pas de texte » inchangé
    [img] = panel["images"]
    assert img["params"]["panel_prompt"] == prompt
    assert img["params"]["prompt"].startswith("Image 1 : référence d'identité de Aiko. " + prompt)
    assert "ne pas reproduire la mise en page des fiches de référence" in img["params"]["prompt"]
    assert "bulles" in img["params"]["negative_prompt"] and "texte" in img["params"]["negative_prompt"]


def test_written_once_per_panel_not_on_every_regeneration(env: Env) -> None:
    c = env.c
    pid = _setup(c)["panel"]["id"]
    first = _generate(c, pid)["final_prompt"]
    _ok(c.post(f"/panels/{pid}/generate", json={"count": 2}), 202)
    _ok(c.post(f"/panels/{pid}/regenerate-quality"), 202)
    _wait(c)
    panel = _ok(c.get(f"/panels/{pid}"))
    assert len(panel["images"]) == 4 and panel["final_prompt"] == first
    assert len(_writer_calls(env.llm)) == 1
    assert {i["params"]["panel_prompt"] for i in panel["images"]} == {first}

    # « Reconstruire le prompt » le redemande au LLM
    rebuilt = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    assert rebuilt["prompt_source"] == "ia" and len(_writer_calls(env.llm)) == 2

    # la case change (description) : rédigé de nouveau à la prochaine génération, une fois
    edited = _ok(c.patch(f"/panels/{pid}", json={"description": "Aiko et Kenji s'enfuient sous la pluie."}))
    assert edited["prompt_pending"] is True and edited["prompt_source"] == "fragments"
    panel = _generate(c, pid)
    assert panel["prompt_source"] == "ia" and "s'enfuient" in panel["final_prompt"]
    assert len(_writer_calls(env.llm)) == 3


def test_invalid_output_twice_falls_back_to_fragments_with_a_warning(env: Env) -> None:
    c = env.c
    pid = _setup(c, description="Aiko bondit vers Kenji [mock:prompt-invalide:9]")["panel"]["id"]
    panel = _generate(c, pid)
    # 2 tentatives au plus (max_retries: 1), puis repli : la génération a bien eu lieu
    assert len(_writer_calls(env.llm)) == 2
    assert panel["images"][0]["params"]["panel_prompt"] == panel["final_prompt"]
    assert panel["prompt_source"] == "fragments" and panel["final_prompt"].startswith("Plan large.")
    assert "Lieu : toit d'un lycée sous la pluie." in panel["final_prompt"]
    warning = panel["prompt_warning"]
    assert warning.startswith("Prompt rédigé par l'IA indisponible (réponse invalide 2 fois de suite")
    assert "Reconstruire le prompt" in warning and panel["prompt_pending"] is False
    # la relance a envoyé l'erreur au LLM
    retry = _writer_calls(env.llm)[1]
    assert retry[-1].role == "user" and "invalide" in retry[-1].content

    # pas de nouvel essai à chaque génération : le repli tient jusqu'à « Reconstruire le prompt »
    _generate(c, pid)
    assert len(_writer_calls(env.llm)) == 2
    again = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    assert len(_writer_calls(env.llm)) == 4 and again["prompt_warning"]


def test_a_named_absent_character_is_refused_then_corrected(env: Env) -> None:
    c = env.c
    pid = _setup(c, description="Aiko bondit vers Kenji [mock:prompt-intrus:1]")["panel"]["id"]
    panel = _generate(c, pid)
    calls = _writer_calls(env.llm)
    assert len(calls) == 2 and "Ren" in calls[1][-1].content  # l'erreur nomme l'intrus
    assert panel["prompt_source"] == "ia" and "Ren" not in panel["final_prompt"].split()


def test_llm_unavailable_falls_back_to_fragments(env: Env) -> None:
    c = env.c
    pid = _setup(c)["panel"]["id"]

    def down(_messages: list[ChatMessage], _json: bool) -> str:
        raise LLMUnavailableError("DeepSeek injoignable : ConnectError")

    env.llm._responder = down
    panel = _generate(c, pid)
    assert panel["images"] and panel["prompt_source"] == "fragments"
    assert "DeepSeek injoignable" in panel["prompt_warning"]


def test_setting_off_gives_exactly_the_fragment_prompt(env: Env) -> None:
    c = env.c
    data = _setup(c, ai_prompt=False)
    pid = data["panel"]["id"]
    panel = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    style = data["series"]["style_prompt"]
    # golden : l'assemblage par fragments actuel, inchangé (presets/image_prompt.yaml#parts)
    assert panel["final_prompt"] == (
        "Plan large. Aiko bondit vers Kenji. crie-t-elle. Lieu : toit d'un lycée sous la pluie. "
        "Mise en scène : Aiko à gauche, Kenji à droite. "
        "Deux personnages : Aiko (cheveux noirs courts, kimono rouge) ; Kenji (grand, lunettes). "
        f"Style : {style}. Aucun texte ni bulle dans l'image."
    )
    assert panel["prompt_source"] == "fragments" and panel["ai_prompt"] is False and panel["prompt_pending"] is False
    _generate(c, pid)
    assert _writer_calls(env.llm) == []


def test_turning_the_setting_off_brings_back_the_fragment_prompt(env: Env) -> None:
    c = env.c
    data = _setup(c)
    pid = data["panel"]["id"]
    assert _generate(c, pid)["prompt_source"] == "ia"
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"ai_prompt": False}))
    panel = _ok(c.get(f"/panels/{pid}"))
    assert panel["prompt_source"] == "fragments" and panel["final_prompt"].startswith("Plan large. Aiko bondit")
    # et de nouveau oui : rédigé à la prochaine génération
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"ai_prompt": True}))
    assert _ok(c.get(f"/panels/{pid}"))["prompt_pending"] is True
    assert _generate(c, pid)["prompt_source"] == "ia"


def test_manual_edit_is_kept_until_rebuilt(env: Env) -> None:
    c = env.c
    pid = _setup(c)["panel"]["id"]
    _generate(c, pid)
    panel = _ok(c.patch(f"/panels/{pid}", json={"final_prompt": "Aiko et Kenji en contre-jour."}))
    assert panel["final_prompt_manual"] is True and panel["prompt_pending"] is False
    panel = _generate(c, pid)
    assert panel["final_prompt"] == "Aiko et Kenji en contre-jour." and len(_writer_calls(env.llm)) == 1
    panel = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    assert panel["final_prompt_manual"] is False and panel["prompt_source"] == "ia"
    assert len(_writer_calls(env.llm)) == 2


def test_dessinateur_trial_shows_written_and_fragment_prompts(env: Env) -> None:
    out = _ok(env.c.post("/agents/dessinateur/trial", json={"values": {}}))
    titles = [s["title"] for s in out["output"]]
    assert titles[:3] == ["Prompt rédigé par l'IA", "Rédaction", "Prompt par fragments"]
    written = out["output"][0]["text"]
    assert "Aiko" in written and "Ren" in written and "Je n'ai pas peur" not in written
    assert "Sensei Okada" not in written


# --- validation (fonctions pures) -----------------------------------------------------------
def _brief(**kw: Any) -> PromptBrief:
    reg = PresetRegistry.load(PRESETS_DIR)
    values: dict[str, Any] = {
        "description": "Aiko lève son sabre. « Je n'ai pas peur ! »",
        "characters": [PromptCharacter("Aiko", "cheveux noirs", ("bandeau rouge",))],
        "absent": ["Ren", "Aiko"],
        "references": [ReferenceSlot("character", "Aiko")],
        "style": "manga shonen, halftone screentone dots",
        "prompt": reg.prompt("redacteur-image"),
    }
    values.update(kw)
    return PromptBrief.build(**values)


def _answer(prompt: str, language: str = "fr") -> str:
    return json.dumps({"prompt": prompt, "language": language, "notes": ""})


WORDS = " ".join(["la scène reste lisible et dynamique"] * 15)


def test_brief_strips_dialogue_and_never_lists_a_present_character_as_absent() -> None:
    brief = _brief()
    assert brief.description == "Aiko lève son sabre" and brief.absent == ["Ren"]
    assert brief.language == "fr" and (brief.min_words, brief.max_words) == (80, 160)


def test_parse_strips_quotes_and_adds_missing_style_keywords() -> None:
    brief = _brief()
    out = parse_written(_answer(f"Aiko, la personne de l'image 1, crie « Je n'ai pas peur ! » et {WORDS}."), brief)
    assert "peur" not in out.prompt and "«" not in out.prompt
    assert out.prompt.endswith("manga shonen, halftone screentone dots.") and out.notes is None


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("pas du JSON", "JSON illisible"),
        (json.dumps({"prompt": "Aiko."}), "language"),
        (_answer(f"Une case {WORDS}."), "non nommés : Aiko"),
        (_answer(f"Aiko et Ren {WORDS}."), "absents de la case nommés .à retirer. : Ren"),
        (_answer("Aiko court."), "trop court"),
        (_answer(f"Aiko {WORDS}", "en"), "« en » au lieu de « fr »"),
    ],
    ids=["json", "schema", "personnage-manquant", "intrus", "trop-court", "langue"],
)
def test_parse_refuses_invalid_answers(text: str, error: str) -> None:
    with pytest.raises(PromptValidationError, match=error):
        parse_written(text, _brief())


def test_write_prompt_gives_up_after_two_attempts() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    llm = MockLLMProvider(lambda _m, _j: "pas du JSON")
    with pytest.raises(PromptWriterError, match="2 fois de suite"):
        write_prompt(llm, reg.prompt("redacteur-image"), _brief())
    assert len(llm.calls) == 2


def test_english_preset_language() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    prompt = reg.prompt("redacteur-image").model_copy(update={"language": "en"})
    run = write_prompt(MockLLMProvider(), prompt, _brief(prompt=prompt))
    assert run.output.language == "en" and run.output.prompt.startswith("Featuring Aiko, the person from image 1")
    assert "halftone screentone dots" in run.output.prompt
