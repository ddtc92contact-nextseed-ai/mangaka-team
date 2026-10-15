"""Densité des dialogues du scénariste (`dialogue_rules`, pipeline/dialogues.py) — chapitre 3 « vulcano »."""

from __future__ import annotations

import json
import re
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
from mangaka_engine.presets.schemas import DialogueRoom, DialogueRules
from mangaka_engine.providers.llm import ChatMessage, LLMAuthError, LLMResult, MockLLMProvider
from tests.conftest import PRESETS_DIR, STYLE, start_script
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
    # Compté par planche : 3, 3, 1, 3 et 5 répliques pour 3, 4, 4, 4 et 5 cases.
    assert "page 1 : 3 répliques (au moins 4 par planche, onomatopées à part)" in text
    assert "page 3 : 1 réplique (au moins 4 par planche" in text
    assert "page 2 : 3 répliques (au moins 4 par planche" in text
    assert "page 4 : 3 répliques (au moins 4 par planche" in text
    assert not [p for p in problems if p.startswith("page 5 : ") and "répliques (au moins" in p]
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
    for page in range(1, 6):
        replies = sum(len(p.replies) for p in panels if p.page == page)
        assert 4 <= replies <= 8, (page, replies)
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
    assert (RULES.target_per_panel, RULES.max_words, RULES.max_mean_words) == (2, 22, 14)
    assert (RULES.min_per_page, RULES.max_per_page, RULES.min_silent_panels_per_page) == (4, 8, 1)
    panels = [_panel(1), _panel(1), _panel(1)]
    problems = check_dialogues(panels, RULES)
    assert any("page 1 : 3 répliques (au moins 4 par planche" in p for p in problems)
    assert any("page 1 : aucune case muette" in p for p in problems)
    lenient = RULES.model_copy(
        update={"min_per_page": 3, "min_silent_panels_per_page": 0, "require_inner_voice": False}
    )
    assert check_dialogues(panels, lenient) == []
    assert check_dialogues(panels, None) == []


def _page(*replies: int, page: int = 1, **kw: Any) -> list[DialoguePanel]:
    out = []
    for i, n in enumerate(replies, start=1):
        p = _panel(n, panels_on_page=len(replies), **kw)
        p.page, p.index = page, i
        out.append(p)
    return out


def test_dialogue_is_counted_per_page_from_4_to_8_with_a_silent_panel() -> None:
    rules = RULES.model_copy(update={"require_inner_voice": False})
    assert check_dialogues(_page(2, 2, 0, 1), rules) == []  # 5 répliques, une case muette
    few = check_dialogues(_page(1, 1, 0, 1), rules)
    assert few == [
        "page 1 : 3 répliques (au moins 4 par planche, onomatopées à part) : ajoute des répliques "
        "courtes là où un personnage présent peut parler (cases en dessous : 1, 2, 3, 4)"
    ]
    many = check_dialogues(_page(3, 3, 3, 0), rules)
    assert any("page 1 : 9 répliques (8 au plus par planche)" in p for p in many)
    mute = check_dialogues(_page(2, 1, 1, 1), rules)
    assert mute and "page 1 : aucune case muette (au moins 1 case sans aucune réplique par planche)" in mute[0]
    # Chaque planche compte pour elle-même : la page 2, maigre, est signalée seule.
    two = check_dialogues([*_page(2, 2, 0, 1), *_page(1, 0, 1, page=2)], rules)
    assert [p.split(" : ")[0] for p in two] == ["page 2"]
    # Les onomatopées ne comptent pas comme répliques ; une case qui n'a qu'une onomatopée est muette.
    sfx = _page(1, 1, 0, 1)
    sfx[2].sfx = ["BOUM !"]
    sfx[2].characters = []
    assert any("3 répliques" in p for p in check_dialogues(sfx, rules))


def test_silent_panel_never_contradicts_an_action_panel() -> None:
    """Planche tout en action (chaque case parle, `action_needs_voice`) : pas de case muette exigée."""
    rules = RULES.model_copy(update={"require_inner_voice": False})
    combat = _page(2, 2, 2, 2, intensity="choc")
    assert check_dialogues(combat, rules) == []
    assert check_dialogues(combat, rules.model_copy(update={"action_needs_voice": False})) != []


def test_per_page_minimum_bends_to_the_room_table() -> None:
    """Deux cases dont la place n'admet qu'une réplique chacune : 2 répliques suffisent sur la planche."""
    rules = RULES.model_copy(
        update={
            "room": [DialogueRoom(max_panels=9, replies=1)],
            "big_panel_bonus": 0,
            "min_silent_panels_per_page": 0,
            "require_inner_voice": False,
        }
    )
    assert check_dialogues(_page(1, 1), rules) == []
    assert any("au moins 2 par planche" in p for p in check_dialogues(_page(1, 0), rules))


def test_per_page_values_are_validated() -> None:
    with pytest.raises(ValueError, match="min_per_page"):
        DialogueRules(min_per_page=9, max_per_page=8)


def test_inner_voice_can_be_disabled_by_the_author() -> None:
    panels = [_panel(2), _panel(2), _panel(0)]
    assert any("pensée" in p for p in check_dialogues(panels, RULES))
    assert check_dialogues(panels, RULES.model_copy(update={"require_inner_voice": False})) == []
    panels[0].replies[0] = Reply("off", "On l'appelait le volcan maudit.")
    assert check_dialogues(panels, RULES) == []


def test_action_panel_needs_a_voice_not_only_narration() -> None:
    rules = RULES.model_copy(update={"min_per_page": 0, "min_silent_panels_per_page": 0, "require_inner_voice": False})
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
    rules = RULES.model_copy(update={"require_inner_voice": False, "max_per_page": 12})
    # Page de 9 cases : une réplique par case au plus ; 1 par case suffit (et une case muette).
    crowded = [_panel(1, panels_on_page=9) for _ in range(8)] + [_panel(0, panels_on_page=9)]
    assert check_dialogues(crowded, rules) == []
    too_many = [_panel(3, panels_on_page=6)]
    assert any("3 répliques pour la place d'au plus 2" in p for p in check_dialogues(too_many, rules))
    assert RULES.room_for(6, importance=3) == 3  # case forte : une de plus
    assert RULES.room_for(4) == 3 and RULES.room_for(9) == 1


def test_room_counts_the_words_not_only_the_replies() -> None:
    """Place recalibrée sur la longueur réelle (#191) : budget en mots par case selon le nombre de cases."""
    quiet = {"require_inner_voice": False, "min_per_page": 0, "min_silent_panels_per_page": 0, "max_mean_words": 22}
    rules = RULES.model_copy(update=quiet)
    assert (rules.room_words_for(4), rules.room_words_for(6), rules.room_words_for(9)) == (46, 36, 22)
    assert rules.room_words_for(6, importance=3) == 36 + rules.big_panel_bonus_words
    # Jamais sous le plafond par réplique : une réplique permise tient toujours seule dans sa case.
    assert rules.model_copy(update={"max_words": 30}).room_words_for(9) == 30

    def case(*words: int, panels_on_page: int = 6) -> DialoguePanel:
        p = _panel(0, panels_on_page=panels_on_page)
        p.replies = [Reply("speech", " ".join(["mot"] * n), "Angus") for n in words]
        return p

    assert check_dialogues([case(22, 14)], rules) == []  # 36 mots : la place d'une case de planche à 6 cases
    assert check_dialogues([case(22, panels_on_page=9)], rules) == []  # une réplique de 22 mots, même serrée
    heavy = check_dialogues([case(22, 20)], rules)
    assert heavy == [
        "page 1 › case 1 : 42 mots de répliques pour la place d'au plus 36 (page de 6 cases) : coupe la tirade "
        "sur la case suivante ou garde l'essentiel"
    ]
    strong = case(22, 20)
    strong.importance = 3
    assert check_dialogues([strong], rules) == []  # case forte : 14 mots de plus


def test_long_replies_are_flagged_one_by_one_and_on_average() -> None:
    rules = RULES.model_copy(update={"require_inner_voice": False, "min_per_page": 0})
    p = _panel(0)
    p.replies = [Reply("speech", " ".join(["mot"] * 22))]
    assert check_dialogues([p], rules) == [
        "répliques trop longues : 22,0 mots en moyenne (14,0 au plus) : laisse l'image raconter, coupe les longues "
        "tirades en plusieurs bulles"
    ]
    p.replies = [Reply("speech", " ".join(["mot"] * 23))]
    problems = check_dialogues([p], rules)
    assert any("trop longue (23 mots, 22 au plus)" in x for x in problems)
    assert any("23,0 mots en moyenne (14,0 au plus)" in x for x in problems)


def test_prompt_states_the_rules() -> None:
    _, user = render_messages(PROMPT, _ctx())
    text = dialogue_text(RULES)
    assert text in user.content
    assert "vise 2 répliques dans chaque case" in text
    assert "4 à 8 répliques par planche" in text and "au moins 1 case sans aucune réplique par planche" in text
    assert (
        "1 à 4 cases → 3 répliques, 46 mots en tout ; 5 à 6 cases → 2 répliques, 36 mots en tout ; "
        "7 à 9 cases → 1 réplique, 22 mots en tout (+1 réplique, +14 mots pour une case forte, importance 3)"
    ) in text
    assert "jamais plus de la moitié de la case" in text
    # Plus « la brièveté fait le rythme » : une phrase entière, l'image d'abord, la tirade coupée.
    assert "22 mots au plus, 14,0 en moyenne" in text
    assert "phrase entière" in text and "l'image raconte d'abord" in text and "plusieurs bulles" in text
    assert "brièveté" not in user.content and "courtes" not in text
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
    assert "ajoute, coupe ou retire des répliques" in retry.content
    assert "page 3 : 1 réplique (au moins 4 par planche" in retry.content
    assert check_dialogues(script_panels(run.output), RULES) == []


def test_still_sparse_after_two_retries_is_kept_with_warnings() -> None:
    llm = _sequence(MAIGRE, MAIGRE, MAIGRE, DENSE)
    run = _run(llm)
    assert len(llm.calls) == 3  # 2 relances au plus, jamais bloquant
    assert run.attempts == 3
    assert any("au moins 4 par planche" in w for w in run.warnings)
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
    job = _ok(start_script(c, chapter_id), 202)
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
    assert report["stats"]["per_panel"] >= 1 and report["stats"]["inner_voice"] >= 1
    assert report["stats"]["sfx_only"] == 0 and report["stats"]["mean_words"] <= 7


def test_sparse_llm_retries_then_warns_without_blocking(client: TestClient) -> None:
    ch = _series(client, "Combat au volcan. [mock:dialogues-maigres:3]")
    done = _decouper(client, ch["id"])
    assert "en 3 essais" in done["message"] and "avertissements de dialogues" in done["message"]
    report = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))
    assert report["stats"]["per_panel"] < 1
    assert any("par planche" in w for w in report["warnings"])
    assert any("aucune pensée" in w for w in report["warnings"])

    ch2 = _series(client, "Combat au volcan. [mock:dialogues-maigres:1]")
    done = _decouper(client, ch2["id"])
    assert "en 2 essais" in done["message"] and "avertissement" not in done["message"]


def test_dense_chapter_3_letters_inside_its_bubble_zones(client: TestClient) -> None:
    """Combat (planches 2 à 4) réécrit avec deux répliques par case : chaque bulle reste dans la zone de
    bulles de sa case, sans texte trop long, et les accents français sont rendus tels quels."""
    ch = _series(client, "Vulcano")
    # Planche 1 de trois cases : la série l'admet dans son ADN (shōnen : 4 à 6 cases par planche).
    # Planche 3 : huit répliques de combat, la série les admet aussi (shōnen : 7 au plus).
    overrides = {"panels.min_per_page": 3, "dialogue.max_per_page": 8}
    _ok(client.put(f"/projects/{ch['project_id']}/pre-direction", json={"overrides": overrides}))
    pages = _ok(client.put(f"/chapters/{ch['id']}/pages", json=vulcano.breakdown(dense=True)))
    report = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))
    assert report["warnings"] == [], report["warnings"]
    seen = ""
    for n in vulcano.COMBAT_PAGES:
        let = _ok(client.get(f"/pages/{pages[n - 1]['id']}/lettering"))
        zones = {p["id"]: p["bubble_zone"] for p in let["panels"]}
        assert not [w for w in let["warnings"] if w["code"] == "text_overflow"]
        assert len(let["bubbles"]) == {2: 6, 3: 8, 4: 6}[n]
        for b in let["bubbles"]:
            z, box = zones[b["panel_id"]], b["box"]
            assert not b["overflow"]
            assert z["x1"] - 1 <= box["x"] and box["x"] + box["w"] <= z["x2"] + 1, (b["text"], box, z)
            assert z["y1"] - 1 <= box["y"] and box["y"] + box["h"] <= z["y2"] + 1, (b["text"], box, z)
            seen += " ".join(line["text"] for line in b["lines"]) + " "
    # Cris en capitales, accents gardés ; paroles telles qu'écrites.
    assert "RATÉ" in seen and "AÏE" in seen and "LÂCHE" in seen
    assert "joué" in seen and "ÇA" in seen


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


# --- dialogue réglable par série : famille « dialogue » de l'ADN (#187) -------------------------------------
def _charter(**overrides: Any):  # type: ignore[no-untyped-def]
    from mangaka_engine.pipeline.pre_direction import Charter, apply_overrides

    settings = PRESETS.pre_direction
    assert settings is not None
    dna = apply_overrides(PRESETS.genre_dna(None), overrides)  # type: ignore[arg-type]
    return Charter(dna, settings, tuple(PRESETS.layout_templates.values()), None)


def _with_reply(words: int) -> str:
    """Le découpage dense, sa première réplique allongée à `words` mots."""
    out = vulcano.script_output(dense=True)
    first = next(d for p in out["pages"] for pa in p["panels"] for d in pa["dialogues"] if d["kind"] == "speech")
    first["text"] = " ".join(["mot"] * words)
    return json.dumps(out, ensure_ascii=False)


def _length_problems(retry: str) -> list[str]:
    """« N mots, M au plus » de chaque réplique trop longue citée par la relance."""
    return [f"{n} mots, {m} au plus" for n, m in re.findall(r"trop longue \((\d+) mots, (\d+) au plus\)", retry)]


def test_dna_dialogue_defaults_are_22_words_and_14_on_average() -> None:
    """#191 : 22 mots au plus, 14 en moyenne pour tous les genres, sauf la jeunesse (lecteurs débutants)."""
    from mangaka_engine.pipeline.pre_direction import dialogue_rules_for, flatten

    assert RULES is not None
    assert (RULES.max_words, RULES.max_mean_words) == (22, 14)
    for genre in (None, *PRESETS.pre_direction.genres):  # type: ignore[union-attr]
        flat = flatten(PRESETS.genre_dna(genre))  # type: ignore[arg-type]
        expected = (14, 8) if genre == "jeunesse" else (22, 14)
        assert (flat["dialogue.max_words"], flat["dialogue.max_mean_words"]) == expected, genre
        assert flat["dialogue.target_per_panel"] == RULES.target_per_panel == 2
        assert flat["dialogue.action_needs_voice"] is RULES.action_needs_voice is True
    rules = dialogue_rules_for(RULES, _charter())
    assert rules is not None
    values = (rules.max_words, rules.max_mean_words, rules.target_per_panel, rules.action_needs_voice)
    assert values == (22, 14, 2, True)


def test_series_max_words_drives_the_scriptwriter_retry() -> None:
    """Une série réglée à 12 mots par réplique — une réplique de 18 mots relance le scénariste avec ce plafond ;
    sans réglage, le défaut de 22 laisse passer 18 mots et relance à 25."""
    ctx = _ctx()
    ctx.charter = _charter(**{"dialogue.max_words": 12, "dialogue.max_mean_words": 7})
    _, user = render_messages(PROMPT, ctx)
    assert "12 mots au plus" in user.content
    llm = _sequence(_with_reply(18), DENSE, DENSE)
    run_script(llm, PROMPT, ctx, lambda _p, _m: None)
    assert _length_problems(llm.calls[1][-1].content) == ["18 mots, 12 au plus"]

    ctx.charter = _charter()
    _, user = render_messages(PROMPT, ctx)
    assert "22 mots au plus" in user.content

    llm = _sequence(_with_reply(18), DENSE, DENSE)
    run_script(llm, PROMPT, ctx, lambda _p, _m: None)
    retries = [m[-1].content for m in llm.calls[1:]]
    assert not any(_length_problems(r) for r in retries)

    llm = _sequence(_with_reply(25), DENSE, DENSE)
    run_script(llm, PROMPT, ctx, lambda _p, _m: None)
    assert len(llm.calls) >= 2
    assert _length_problems(llm.calls[1][-1].content) == ["25 mots, 22 au plus"]


def test_series_can_allow_a_silent_action_panel() -> None:
    from mangaka_engine.pipeline.pre_direction import dialogue_rules_for

    choc = _panel(0, intensity="choc")
    base = {"min_per_page": 0, "min_silent_panels_per_page": 0, "require_inner_voice": False}
    loud = dialogue_rules_for(RULES, _charter(**{"dialogue.min_per_page": 0, "dialogue.min_silent_panels": 0}))
    assert any("case d'action muette" in p for p in check_dialogues([choc], loud.model_copy(update=base)))  # type: ignore[union-attr]
    silent = dialogue_rules_for(
        RULES,
        _charter(**{"dialogue.min_per_page": 0, "dialogue.min_silent_panels": 0, "dialogue.action_needs_voice": False}),
    )
    assert check_dialogues([choc], silent.model_copy(update=base)) == []  # type: ignore[union-attr]


def test_dna_card_exposes_the_dialogue_settings(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**STYLE, "title": "Bavards"}), 201)
    dna = _ok(client.get(f"/projects/{s['id']}/pre-direction"))
    fields = {f["path"]: f for f in dna["fields"]}
    for path, kind in (
        ("dialogue.max_words", "int"),
        ("dialogue.max_mean_words", "int"),
        ("dialogue.target_per_panel", "int"),
        ("dialogue.action_needs_voice", "bool"),
    ):
        assert fields[path]["group"] == "dialogue" and fields[path]["kind"] == kind and fields[path]["label"]
    assert dna["inherited"]["dialogue.max_words"] == 22 and dna["inherited"]["dialogue.action_needs_voice"] is True
    tuned = _ok(
        client.put(
            f"/projects/{s['id']}/pre-direction",
            json={"overrides": {"dialogue.max_words": 30, "dialogue.action_needs_voice": False}},
        )
    )
    assert tuned["effective"]["dialogue.max_words"] == 30 and tuned["effective"]["dialogue.action_needs_voice"] is False
    bad = client.put(
        f"/projects/{s['id']}/pre-direction",
        json={"overrides": {"dialogue.max_words": 5, "dialogue.max_mean_words": 9}},
    )
    assert bad.status_code == 422 and "moyenne" in bad.text


# --- répliques plus longues par défaut (#191) ----------------------------------------------------------------
LONG_22 = (
    "Je t'avais bien prévenu, Kenji : si tu remontes au vieux phare cette nuit, la marée haute te coupera "
    "la route du village."
)
LONG_19 = "Écoute-moi bien, on n'a plus que dix minutes avant que le dernier train ne quitte la gare du port."


def test_new_series_gets_22_words_and_a_tuned_series_keeps_its_values(client: TestClient) -> None:
    new = _ok(client.post("/projects", json={**STYLE, "title": "Nuit du pari"}), 201)
    dna = _ok(client.get(f"/projects/{new['id']}/pre-direction"))
    assert (dna["effective"]["dialogue.max_words"], dna["effective"]["dialogue.max_mean_words"]) == (22, 14)

    # Série d'avant #191 qui avait réglé ses répliques : ses valeurs ne bougent pas.
    tuned = _ok(client.post("/projects", json={**STYLE, "title": "Ancienne série"}), 201)
    old = {"dialogue.max_words": 12, "dialogue.max_mean_words": 7}
    _ok(client.put(f"/projects/{tuned['id']}/pre-direction", json={"overrides": old}))
    dna = _ok(client.get(f"/projects/{tuned['id']}/pre-direction"))
    assert dna["overrides"] == old
    assert (dna["effective"]["dialogue.max_words"], dna["effective"]["dialogue.max_mean_words"]) == (12, 7)


def test_a_series_ceiling_below_the_new_mean_is_kept() -> None:
    """Une série qui n'avait réglé que le plafond (10 mots) : la moyenne héritée (14) le suit, l'ajustement
    n'est pas rejeté (sinon tout l'ADN de la série retomberait sur celui du genre)."""
    charter = _charter(**{"dialogue.max_words": 10})
    assert (charter.dna.dialogue.max_words, charter.dna.dialogue.max_mean_words) == (10, 10)


def _six_panel_page(dialogues: list[list[dict[str, str]]]) -> dict[str, Any]:
    panels = [
        {
            "description": f"Kenji et Aiko sur la jetée, case {i + 1}.",
            "characters": ["Angus", "Seku"],
            "importance": 2,
            "intensity": "normal",
            "dialogues": d,
        }
        for i, d in enumerate(dialogues)
    ]
    return {"pages": [{"rythme": "normal", "panels": panels}]}


def test_a_22_word_reply_fits_a_medium_panel_at_its_normal_size(client: TestClient) -> None:
    """Planche de 6 cases (taille moyenne) : une réplique de 22 mots, accents compris, tient dans la zone de
    bulles de sa case et dans la case, sans débordement ni police réduite ; deux longues répliques aussi."""
    assert count_words(LONG_22) == 22
    ch = _series(client, "Nuit du pari")
    speech = [{"speaker": "Angus", "text": LONG_22, "kind": "speech"}]
    two = [*speech, {"speaker": "Seku", "text": "Tant pis, j'y vais quand même.", "kind": "speech"}]
    pages = _ok(client.put(f"/chapters/{ch['id']}/pages", json=_six_panel_page([speech, two, [], speech, [], []])))
    let = _ok(client.get(f"/pages/{pages[0]['id']}/lettering"))
    assert not [w for w in let["warnings"] if w["code"] == "text_overflow"]
    panels = {p["id"]: p for p in let["panels"]}
    assert len(let["bubbles"]) == 4
    for b in let["bubbles"]:
        panel, zone, box = panels[b["panel_id"]], panels[b["panel_id"]]["bubble_zone"], b["box"]
        assert not b["overflow"]
        assert b["font"]["size_pt"] == b["font"]["style_size_pt"]  # taille normale, jamais réduite
        for frame in (zone, panel["box"]):  # dans la zone de bulles, donc dans la case
            assert frame["x1"] - 1 <= box["x"] and box["x"] + box["w"] <= frame["x2"] + 1, (b["text"], box, frame)
            assert frame["y1"] - 1 <= box["y"] and box["y"] + box["h"] <= frame["y2"] + 1, (b["text"], box, frame)
    text = " ".join(line["text"] for b in let["bubbles"] for line in b["lines"])
    assert "prévenu" in text and "marée" in text and "même" in text
    # Contrôle de place : rien à redire (la moyenne de 18 mots, elle, dépasse les 14 du chapitre).
    warnings = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))["warnings"]
    assert not [w for w in warnings if "zone de bulles" in w or "couvrent" in w or "pour la place" in w], warnings


def test_bubbles_covering_more_than_half_a_panel_warn(client: TestClient) -> None:
    """Planche de 9 cases : trois répliques de 19 à 22 mots dans une même case couvriraient plus de la moitié de
    la case — l'avertissement de place le dit (et la relance du scénariste avec)."""
    ch = _series(client, "Nuit du pari")
    tirade = [
        {"speaker": "Angus", "text": LONG_22, "kind": "speech"},
        {"speaker": "Seku", "text": LONG_19, "kind": "speech"},
        {"speaker": "Angus", "text": LONG_22, "kind": "speech"},
    ]
    page = _six_panel_page([tirade, *[[] for _ in range(8)]])
    _ok(client.put(f"/chapters/{ch['id']}/pages", json=page))
    warnings = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))["warnings"]
    assert any(
        w.startswith("page 1 › case 1 : les bulles couvrent") and "(la moitié au plus)" in w for w in warnings
    ), warnings
    assert any(w.startswith("page 1 › case 1") and "zone de bulles" in w for w in warnings)
    assert any("page 1 › case 1 : 3 répliques pour la place d'au plus 1" in w for w in warnings)
