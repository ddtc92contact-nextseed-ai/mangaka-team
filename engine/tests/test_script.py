from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

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
from tests.conftest import PRESETS_DIR, STYLE

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


# --- indices de direction artistique (mise en page) -----------------------------------------
def test_intensity_and_rythme_are_optional_and_normalized() -> None:
    payload = {
        "pages": [
            {
                "rythme": " Rapide ",
                "panels": [
                    {"description": "Coup de sabre", "shot_type": "gros plan", "importance": 3, "intensity": "CHOC"},
                    {"description": "Silence", "shot_type": "plan large", "intensity": ""},
                    {"description": "Suite", "shot_type": "plan moyen"},
                ],
            },
            {"panels": [{"description": "x", "shot_type": "insert"}]},
        ],
        "summary": "Résumé.",
    }
    out = parse_script(json.dumps(payload))
    assert out.pages[0].rythme == "rapide" and out.pages[1].rythme is None
    assert [p.intensity for p in out.pages[0].panels] == ["choc", None, None]
    with pytest.raises(ScriptValidationError, match="intensity"):
        parse_script(
            json.dumps(
                {**payload, "pages": [{"panels": [{"description": "x", "shot_type": "insert", "intensity": "épique"}]}]}
            )
        )


def test_mock_script_fills_layout_hints() -> None:
    out = parse_script(json.dumps(mock_script(_ctx().as_json())))
    assert all(p.rythme in ("lent", "normal", "rapide") for p in out.pages)
    intensities = {pa.intensity for p in out.pages for pa in p.panels}
    assert intensities <= {"calme", "normal", "choc"} and "choc" in intensities


def test_prompt_documents_layout_hints() -> None:
    _, user = render_messages(PROMPT, _ctx())
    assert "intensity" in user.content and "calme, normal, choc" in user.content
    assert "rythme" in user.content and "lent, normal, rapide" in user.content


def test_sfx_per_panel_is_optional_and_validated() -> None:
    payload = {
        "pages": [
            {
                "panels": [
                    {
                        "description": "La moto démarre",
                        "shot_type": "plan large",
                        "sfx": [{"text": " VROUM ! ", "intensity": "Choc"}, {"text": "clic"}],
                    },
                    {"description": "Silence", "shot_type": "plan moyen"},
                ]
            }
        ],
        "summary": "Résumé.",
    }
    out = parse_script(json.dumps(payload))
    first, second = out.pages[0].panels
    assert [(s.text, s.intensity) for s in first.sfx] == [("VROUM !", "choc"), ("clic", None)]
    assert second.sfx == []
    bad = {**payload, "pages": [{"panels": [{"description": "x", "shot_type": "insert", "sfx": [{"text": ""}]}]}]}
    with pytest.raises(ScriptValidationError, match="onomatopée"):
        parse_script(json.dumps(bad))


def test_mock_script_fills_some_sfx_and_prompt_documents_them() -> None:
    out = parse_script(json.dumps(mock_script(_ctx().as_json())))
    sfx = [s for p in out.pages for pa in p.panels for s in pa.sfx]
    assert sfx and all(s.intensity in ("calme", "normal", "choc") for s in sfx)
    assert any(pa.sfx == [] for p in out.pages for pa in p.panels)  # quelques-unes seulement
    _, user = render_messages(PROMPT, _ctx())
    assert "« sfx »" in user.content and '"sfx": [{"text": "VROUM !"' in user.content
    assert "sfx" not in _ctx().as_json()["bubble_kinds"]  # pas un type de réplique


def test_second_decoupage_replaces_story_pages_and_is_persisted(client: TestClient) -> None:
    """Re-« Découper » un chapitre déjà découpé (et mis en page) : le nouveau découpage est enregistré."""
    project = client.post("/projects", json={**STYLE, "title": "Redécoupe"}).json()
    ch = client.post(
        f"/projects/{project['id']}/chapters",
        json={"synopsis": "Aiko arrive à Kyoto sous la pluie.", "target_page_count": 3},
    ).json()
    jobs = client.app.state.ctx.jobs  # type: ignore[attr-defined]
    for _ in range(2):
        job = client.post(f"/chapters/{ch['id']}/script").json()
        jobs.wait(job["id"])
        done = client.get(f"/jobs/{job['id']}").json()
        assert done["status"] == "succeeded", done["error"]
    pages = client.get(f"/chapters/{ch['id']}/pages").json()
    assert pages and all(p["kind"] == "story" for p in pages)
    assert [p["number"] for p in pages] == list(range(1, len(pages) + 1))
