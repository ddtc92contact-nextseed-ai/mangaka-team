"""Densité des dialogues du scénariste (`dialogue_rules`, pipeline/dialogues.py) — chapitre 3 « vulcano »."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.pipeline.dialogues import (
    DialoguePanel,
    Reply,
    check_dialogues,
    count_words,
    dialogue_stats,
    dialogue_text,
)
from mangaka_engine.pipeline.layout import Rect, bubble_zone
from mangaka_engine.pipeline.script import ScriptContext, parse_script, render_messages, run_script, script_panels
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import DialogueRules
from mangaka_engine.providers.llm import ChatMessage, LLMAuthError, LLMResult, MockLLMProvider
from tests.conftest import PRESETS_DIR, STYLE
from tests.fixtures import vulcano

PRESETS = PresetRegistry.load(PRESETS_DIR)
PROMPT = PRESETS.prompt("script")
RULES = PROMPT.dialogue_rules
assert RULES is not None

MAIGRE = json.dumps(vulcano.script_output(dense=False), ensure_ascii=False)
DENSE = json.dumps(vulcano.script_output(dense=True), ensure_ascii=False)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _ctx() -> ScriptContext:
    return ScriptContext(
        series={"title": "Ecoloman", "style": "shonen", "reading_direction": "rtl"},
        characters=[{"name": n, "description": ""} for n in vulcano.CHARACTERS],
        previous_chapters=[],
        chapter={"number": 3, "title": "Vulcano", "synopsis": "Les trafiquants polluent le volcan.", "target_pages": 5},
    )


def _panels(text: str) -> list[DialoguePanel]:
    return script_panels(parse_script(text))


def _combat_sfx_only(panels: list[DialoguePanel]) -> list[str]:
    return [p.label for p in panels if p.page in vulcano.COMBAT_PAGES and p.sfx and not p.replies]


# --- mesure -------------------------------------------------------------------------
def test_count_words_ignores_punctuation() -> None:
    assert count_words("Tu vas voir ! — Quoi ?!") == 4
    assert count_words("Non… restez où vous êtes !") == 5
    assert count_words("…") == 0


def test_real_chapter_3_is_measured_like_the_audit() -> None:
    stats = dialogue_stats(_panels(MAIGRE), RULES)
    assert (stats.panels, stats.replies, stats.sfx) == (20, 15, 6)
    assert stats.per_panel == 0.75
    assert stats.inner_voice == 0
    assert stats.sfx_only == 5
    assert _combat_sfx_only(_panels(MAIGRE)) == [
        "page 2 › case 4",
        "page 3 › case 1",
        "page 3 › case 2",
        "page 3 › case 4",
        "page 4 › case 2",
    ]


def test_real_chapter_3_breaks_every_rule() -> None:
    problems = check_dialogues(_panels(MAIGRE), RULES)
    text = " ; ".join(problems)
    assert "trop peu de répliques : 15 pour 20 cases (0,75 par case, au moins 1,30 visées)" in text
    for label, sfx in [
        ("page 2 › case 4", "TCHAK !"),
        ("page 3 › case 1", "RATATATA !"),
        ("page 4 › case 2", "CRAC !"),
    ]:
        assert f"{label} (action) : seulement l'onomatopée « {sfx} »" in text
    assert "aucune pensée, voix off ni narration" in text


def test_dense_rewrite_meets_the_acceptance_criteria() -> None:
    panels = _panels(DENSE)
    stats = dialogue_stats(panels, RULES)
    assert stats.per_panel >= 1.3
    assert not _combat_sfx_only(panels)
    assert any(r.kind in ("thought", "off") for p in panels for r in p.replies)
    assert stats.mean_words <= 7
    assert check_dialogues(panels, RULES) == []


# --- règles (preset, pas de seuil en dur) ------------------------------------------------
def _panel(replies: int, *, panels_on_page: int = 4, sfx: list[str] | None = None, **kw: Any) -> DialoguePanel:
    return DialoguePanel(
        page=1,
        index=1,
        panels_on_page=panels_on_page,
        characters=kw.pop("characters", ["Angus"]),
        replies=[Reply("speech", "Tiens bon !", "Angus") for _ in range(replies)],
        sfx=sfx or [],
        **kw,
    )


def test_thresholds_come_from_the_preset() -> None:
    assert (RULES.target_per_panel, RULES.min_per_panel, RULES.max_mean_words) == (2, 1.3, 7)
    panels = [_panel(1), _panel(1)]
    assert any("trop peu" in p for p in check_dialogues(panels, RULES))
    lenient = RULES.model_copy(update={"min_per_panel": 1.0, "require_inner_voice": False})
    assert check_dialogues(panels, lenient) == []
    assert check_dialogues(panels, None) == []


def test_inner_voice_can_be_disabled_by_the_author() -> None:
    panels = [_panel(2), _panel(2)]
    assert any("pensée" in p for p in check_dialogues(panels, RULES))
    assert check_dialogues(panels, RULES.model_copy(update={"require_inner_voice": False})) == []
    panels[0].replies[0] = Reply("off", "On l'appelait le volcan maudit.")
    assert check_dialogues(panels, RULES) == []


def test_action_panel_needs_a_voice_not_only_narration() -> None:
    rules = RULES.model_copy(update={"min_per_panel": 0, "require_inner_voice": False})
    choc = _panel(0, intensity="choc")
    assert any("case d'action muette" in p for p in check_dialogues([choc], rules))
    narrated = _panel(0, sfx=["BOUM !"])
    narrated.replies = [Reply("narration", "Plus tard.")]
    assert any("« BOUM ! »" in p for p in check_dialogues([narrated], rules))
    voiced = _panel(1, sfx=["BOUM !"])
    assert check_dialogues([voiced], rules) == []
    nobody = _panel(0, sfx=["BOUM !"], characters=[])  # décor seul : personne pour parler
    assert check_dialogues([nobody], rules) == []
    assert check_dialogues([choc], rules.model_copy(update={"action_needs_voice": False})) == []


def test_density_bends_to_the_room_table() -> None:
    rules = RULES.model_copy(update={"require_inner_voice": False})
    # Page de 9 cases : une réplique par case au plus ; 1 par case suffit, la cible de 1,3 ne s'applique pas.
    crowded = [_panel(1, panels_on_page=9) for _ in range(9)]
    assert check_dialogues(crowded, rules) == []
    too_many = [_panel(3, panels_on_page=6)]
    assert any("3 répliques pour la place d'au plus 2" in p for p in check_dialogues(too_many, rules))
    assert RULES.room_for(6, importance=3) == 3  # case forte : une de plus
    assert RULES.room_for(4) == 3 and RULES.room_for(9) == 1


def test_long_replies_are_flagged_one_by_one_and_on_average() -> None:
    rules = RULES.model_copy(update={"require_inner_voice": False, "min_per_panel": 0})
    p = _panel(0)
    p.replies = [Reply("speech", "un deux trois quatre cinq six sept huit neuf dix onze douze treize")]
    problems = check_dialogues([p], rules)
    assert any("trop longue (13 mots, 12 au plus)" in x for x in problems)
    assert any("13,0 mots en moyenne (7,0 au plus)" in x for x in problems)


def test_prompt_states_the_rules() -> None:
    _, user = render_messages(PROMPT, _ctx())
    text = dialogue_text(RULES)
    assert text in user.content
    assert "vise 2 répliques dans chaque case" in text
    assert "1 à 4 cases → 3 ; 5 à 6 cases → 2 ; 7 à 9 cases → 1" in text
    assert "jamais réduite à son onomatopée" in text
    assert "pensée, voix off, narration" in text
    assert dialogue_text(None) == "(aucune règle imposée)"
    assert "seulement quand la situation" in dialogue_text(RULES.model_copy(update={"require_inner_voice": False}))


# --- relance --------------------------------------------------------------------------
def _sequence(*answers: str) -> MockLLMProvider:
    it = iter(answers)
    return MockLLMProvider(lambda _m, _j: next(it))


def _run(llm: MockLLMProvider, **kw: Any):  # type: ignore[no-untyped-def]
    return run_script(llm, PROMPT, _ctx(), lambda _p, _m: None, **kw)


def test_sparse_answer_triggers_a_corrective_retry() -> None:
    llm = _sequence(MAIGRE, DENSE)
    run = _run(llm)
    assert run.attempts == 2 and run.warnings == []
    retry = llm.calls[1][-1]
    assert retry.role == "user" and "dialogues à revoir" in retry.content
    assert "seulement l'onomatopée « RATATATA ! »" in retry.content
    assert "ajoute ou retire des répliques courtes" in retry.content
    assert dialogue_stats(script_panels(run.output), RULES).per_panel >= 1.3


def test_still_sparse_after_two_retries_is_kept_with_warnings() -> None:
    llm = _sequence(MAIGRE, MAIGRE, MAIGRE, DENSE)
    run = _run(llm)
    assert len(llm.calls) == 3  # 2 relances au plus, jamais bloquant
    assert run.attempts == 3
    assert any("trop peu de répliques" in w for w in run.warnings)
    assert dialogue_stats(script_panels(run.output), RULES).replies == 15


def test_invalid_last_answer_keeps_the_sparse_but_valid_one() -> None:
    run = _run(_sequence(MAIGRE, "pas du JSON", "pas du JSON"))
    assert run.attempts == 1 and run.warnings


def test_llm_error_during_a_dialogue_retry_keeps_the_valid_answer() -> None:
    class Broken(MockLLMProvider):
        def complete(self, messages: list[ChatMessage], **kw: Any) -> LLMResult:
            self.calls.append(messages)
            if len(self.calls) == 1:
                return LLMResult(text=MAIGRE, model="mock")
            raise LLMAuthError("clé refusée")

    run = _run(Broken())
    assert run.attempts == 1 and run.warnings


def test_room_check_feeds_the_retry() -> None:
    seen: list[int] = []

    def room(output):  # type: ignore[no-untyped-def]
        seen.append(len(output.pages))
        return (
            ["page 3 › case 2 : 1 bulle sur 2 ne tient pas dans la zone de bulles de la case"] if len(seen) == 1 else []
        )

    llm = _sequence(DENSE, DENSE)
    run = _run(llm, check=room)
    assert run.attempts == 2 and run.warnings == [] and seen == [5, 5]
    assert "zone de bulles" in llm.calls[1][-1].content


# --- zone de bulles ------------------------------------------------------------------------
def test_bubble_zone_grows_with_the_number_of_bubbles_up_to_max_fraction() -> None:
    fmt = PRESETS.page_format("a4-300dpi")
    settings = PRESETS.layout
    panel = Rect(0, 0, 1050, 1070)  # case d'une planche à 6 cases (A4, 300 DPI)

    def area(chars: int, bubbles: int) -> int:
        z = bubble_zone(panel, chars, "rtl", fmt, settings, None, bubbles)
        assert z is not None
        return z.w * z.h

    assert area(60, 2) > area(30, 1)
    assert area(60, 3) > area(60, 2)
    assert area(400, 9) <= settings.bubble_zone.max_fraction * panel.w * panel.h * 1.01
    legacy = settings.model_copy(
        update={"bubble_zone": settings.bubble_zone.model_copy(update={"bubble_mm2": 0, "char_mm2": 0})}
    )
    z = bubble_zone(panel, 30, "rtl", fmt, legacy, None, 2)
    assert z is not None and z.w * z.h < area(30, 2)


# --- de bout en bout (API, mock) -----------------------------------------------------------------
def _series(c: TestClient, synopsis: str, pages: int = 5) -> dict[str, Any]:
    s = _ok(c.post("/projects", json={**STYLE, "title": "Ecoloman", "reading_direction": "rtl"}), 201)
    for name in vulcano.CHARACTERS:
        _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
    return _ok(
        c.post(
            f"/projects/{s['id']}/chapters", json={"title": "Vulcano", "synopsis": synopsis, "target_page_count": pages}
        ),
        201,
    )


def _decouper(c: TestClient, chapter_id: int) -> dict[str, Any]:
    job = _ok(c.post(f"/chapters/{chapter_id}/script"), 202)
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    done = _ok(c.get(f"/jobs/{job['id']}"))
    assert done["status"] == "succeeded", done["error"]
    return done


def test_mock_chapter_passes_the_rules_and_the_room_check(client: TestClient) -> None:
    ch = _series(client, "Angus et Seku montent au volcan. Les trafiquants tirent. Le volcan gronde.")
    done = _decouper(client, ch["id"])
    assert "avertissement" not in (done["message"] or "") and "essais" not in (done["message"] or "")
    report = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))
    assert report["warnings"] == []
    assert report["stats"]["per_panel"] >= 1.3 and report["stats"]["inner_voice"] >= 1
    assert report["stats"]["sfx_only"] == 0 and report["stats"]["mean_words"] <= 7


def test_sparse_llm_retries_then_warns_without_blocking(client: TestClient) -> None:
    ch = _series(client, "Combat au volcan. [mock:dialogues-maigres:3]")
    done = _decouper(client, ch["id"])
    assert "en 3 essais" in done["message"] and "avertissements de dialogues" in done["message"]
    report = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))
    assert report["stats"]["per_panel"] < 1.3
    assert any("trop peu de répliques" in w for w in report["warnings"])
    assert any("aucune pensée" in w for w in report["warnings"])

    ch2 = _series(client, "Combat au volcan. [mock:dialogues-maigres:1]")
    done = _decouper(client, ch2["id"])
    assert "en 2 essais" in done["message"] and "avertissement" not in done["message"]


def test_dense_chapter_3_letters_inside_its_bubble_zones(client: TestClient) -> None:
    """Combat (planches 2 à 4) réécrit avec deux répliques par case : chaque bulle reste dans la zone de
    bulles de sa case, sans texte trop long, et les accents français sont rendus tels quels."""
    ch = _series(client, "Vulcano")
    pages = _ok(client.put(f"/chapters/{ch['id']}/pages", json=vulcano.breakdown(dense=True)))
    report = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))
    assert report["warnings"] == [], report["warnings"]
    seen = ""
    for n in vulcano.COMBAT_PAGES:
        let = _ok(client.get(f"/pages/{pages[n - 1]['id']}/lettering"))
        zones = {p["id"]: p["bubble_zone"] for p in let["panels"]}
        assert not [w for w in let["warnings"] if w["code"] == "text_overflow"]
        assert len(let["bubbles"]) == 8
        for b in let["bubbles"]:
            z, box = zones[b["panel_id"]], b["box"]
            assert not b["overflow"]
            assert z["x1"] - 1 <= box["x"] and box["x"] + box["w"] <= z["x2"] + 1, (b["text"], box, z)
            assert z["y1"] - 1 <= box["y"] and box["y"] + box["h"] <= z["y2"] + 1, (b["text"], box, z)
            seen += " ".join(line["text"] for line in b["lines"]) + " "
    # Cris en capitales, accents gardés ; paroles telles qu'écrites.
    assert "RATÉ" in seen and "AÏE" in seen and "LÂCHE" in seen
    assert "joué" in seen and "où" in seen


def test_room_check_flags_bubbles_that_leave_their_zone(client: TestClient) -> None:
    ch = _series(client, "Vulcano")
    crowded = vulcano.breakdown(dense=True)
    long_line = "Je vous préviens, cette île est sous ma protection éternelle"
    for panel in crowded["pages"][4]["panels"]:  # planche 5 : cinq cases
        panel["dialogues"] = [{"speaker": "Angus", "text": long_line, "kind": "speech"}] * 3
    _ok(client.put(f"/chapters/{ch['id']}/pages", json=crowded))
    warnings = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))["warnings"]
    assert any(w.startswith("page 5 › case") and "zone de bulles" in w for w in warnings), warnings


def test_dialogue_report_404(client: TestClient) -> None:
    assert client.get("/chapters/999/dialogues").status_code == 404


def test_dialogue_rules_schema_rejects_unknown_kinds() -> None:
    with pytest.raises(ValueError, match="cri"):
        DialogueRules(inner_voice_kinds=["cri"])
