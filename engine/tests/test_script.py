from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from mangaka_engine.pipeline.script import (
    ScriptContext,
    ScriptError,
    ScriptValidationError,
    parse_script,
    render_messages,
    run_script,
)
from mangaka_engine.presets import PresetError, PresetRegistry
from mangaka_engine.providers.llm import ChatMessage, LLMAuthError, LLMResult, LLMTimeoutError, MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_script
from tests.conftest import PRESETS_DIR

PRESETS = PresetRegistry.load(PRESETS_DIR)
PROMPT = PRESETS.prompt("script")

VALID = {
    "pages": [
        {
            "panels": [
                {
                    "description": "Kyoto sous la pluie, vue des toits.",
                    "characters": [],
                    "shot_type": "plan large",
                    "importance": 3,
                    "dialogues": [{"speaker": "", "text": "Kyoto, 1864.", "kind": "narration"}],
                },
                {
                    "description": "Aiko dégaine.",
                    "characters": ["Aiko", "Aiko"],
                    "shot_type": "Contre plongée",
                    "dialogues": [{"speaker": "Aiko", "text": "Recule !", "kind": "SHOUT"}],
                    "camera": "ignoré",
                },
            ]
        }
    ],
    "summary": "Aiko arrive à Kyoto et affronte un rônin.",
}


def _ctx(previous: list[dict] | None = None) -> ScriptContext:
    return ScriptContext(
        series={"title": "Les Lames de Kyoto", "style": "encre", "reading_direction": "rtl"},
        characters=[{"name": "Aiko", "description": "rônin aux cheveux courts"}],
        previous_chapters=previous or [],
        chapter={"number": 2, "title": "La pluie", "synopsis": "Aiko poursuit le voleur.", "target_pages": 3},
    )


# --- schéma ------------------------------------------------------------------------
def test_valid_script_is_parsed_and_normalized() -> None:
    out = parse_script(json.dumps(VALID))
    p2 = out.pages[0].panels[1]
    assert p2.shot_type == "contre-plongée"
    assert p2.characters == ["Aiko"]
    assert p2.dialogues[0].kind == "shout"
    assert p2.importance == 2  # défaut
    assert out.pages[0].panels[0].dialogues[0].kind == "narration"


def test_code_fences_are_accepted() -> None:
    assert parse_script("```json\n" + json.dumps(VALID) + "\n```").summary


@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        ("pas du JSON", "JSON illisible"),
        ("[1, 2]", "racine"),
        (json.dumps({"pages": []}), "summary"),
        (json.dumps({**VALID, "pages": []}), "pages"),
        (
            json.dumps({**VALID, "pages": [{"panels": [{"description": "x", "shot_type": "travelling"}]}]}),
            "page 1 › case 1 › shot_type",
        ),
        (
            json.dumps(
                {**VALID, "pages": [{"panels": [{"description": "x", "shot_type": "gros plan", "importance": 5}]}]}
            ),
            "importance",
        ),
        (
            json.dumps(
                {
                    **VALID,
                    "pages": [
                        {
                            "panels": [
                                {
                                    "description": "x",
                                    "shot_type": "gros plan",
                                    "dialogues": [{"text": "a", "kind": "cri"}],
                                }
                            ]
                        }
                    ],
                }
            ),
            "réplique 1 › kind",
        ),
        (
            json.dumps({**VALID, "pages": [{"panels": [{"description": "x", "shot_type": "plan large"}] * 10}]}),
            "au plus 9",
        ),
    ],
)
def test_invalid_scripts_are_rejected_with_readable_errors(payload: str, needle: str) -> None:
    with pytest.raises(ScriptValidationError) as info:
        parse_script(payload)
    assert needle in str(info.value)


def test_mock_script_is_valid() -> None:
    ctx = _ctx().as_json()
    out = parse_script(json.dumps(mock_script(ctx)))
    assert len(out.pages) == 3


# --- prompt et contexte ---------------------------------------------------------------
def test_prompt_comes_from_presets_and_includes_previous_summaries() -> None:
    ctx = _ctx([{"number": 1, "title": "L'arrivée", "summary": "Aiko perd son sabre dans le Kamo."}])
    system, user = render_messages(PROMPT, ctx)
    assert system.role == "system" and "JSON" in system.content
    assert "Aiko perd son sabre dans le Kamo." in user.content
    assert "Chapitre 1 — L'arrivée" in user.content
    assert "Chapitre 2 — « La pluie »" in user.content
    assert "rônin aux cheveux courts" in user.content
    assert "contre-plongée" in user.content
    assert '"task": "script"' in user.content


def test_first_chapter_has_no_previous_summary() -> None:
    _, user = render_messages(PROMPT, _ctx())
    assert "premier chapitre" in user.content


def test_unknown_template_variable_is_a_preset_error() -> None:
    bad = PROMPT.model_copy(update={"user": "Bonjour $inconnu"})
    with pytest.raises(PresetError, match="inconnu"):
        render_messages(bad, _ctx())


# --- relances --------------------------------------------------------------------------
def _sequence(*answers: str) -> Callable[[list[ChatMessage], bool], str]:
    it = iter(answers)
    return lambda _m, _j: next(it)


def _run(llm: MockLLMProvider) -> tuple[object, list[tuple[int, str]]]:
    events: list[tuple[int, str]] = []
    return run_script(llm, PROMPT, _ctx(), lambda p, m: events.append((p, m))), events


def test_invalid_twice_then_valid_succeeds() -> None:
    llm = MockLLMProvider(_sequence("oups", json.dumps({"pages": []}), json.dumps(VALID)))
    run, events = _run(llm)
    assert run.attempts == 3  # type: ignore[attr-defined]
    assert len(llm.calls) == 3
    # l'erreur de validation est renvoyée au LLM
    third = llm.calls[2]
    assert [m.role for m in third] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert "JSON illisible" in third[3].content
    assert "summary" in third[5].content and third[4].content == json.dumps({"pages": []})
    assert any("nouvel essai" in m for _, m in events)
    assert any("essai 3/3" in m for _, m in events)


def test_three_invalid_answers_fail_with_readable_error() -> None:
    llm = MockLLMProvider(_sequence("a", "b", "c", json.dumps(VALID)))
    with pytest.raises(ScriptError, match="invalide 3 fois de suite.*JSON illisible"):
        _run(llm)
    assert len(llm.calls) == 3  # max 2 relances


def test_mock_provider_invalid_attempts_knob() -> None:
    ok = MockLLMProvider(invalid_attempts=2)
    run, _ = _run(ok)
    assert run.attempts == 3  # type: ignore[attr-defined]
    with pytest.raises(ScriptError):
        _run(MockLLMProvider(invalid_attempts=3))


def test_non_retryable_llm_error_fails_immediately() -> None:
    class Broken(MockLLMProvider):
        def complete(self, messages, **kw):  # type: ignore[no-untyped-def]
            self.calls.append(messages)
            raise LLMAuthError("clé DeepSeek refusée (HTTP 401)")

    llm = Broken()
    with pytest.raises(ScriptError, match="401"):
        _run(llm)
    assert len(llm.calls) == 1


def test_retryable_llm_error_uses_a_retry() -> None:
    answers = iter([LLMTimeoutError("timeout"), json.dumps(VALID)])

    class Flaky(MockLLMProvider):
        def complete(self, messages, **kw):  # type: ignore[no-untyped-def]
            self.calls.append(messages)
            a = next(answers)
            if isinstance(a, Exception):
                raise a
            return LLMResult(text=a, model="mock")

    run, _ = _run(Flaky())
    assert run.attempts == 2  # type: ignore[attr-defined]
