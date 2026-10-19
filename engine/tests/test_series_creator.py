"""Créateur de série (pipeline/series_creator.py, api/series_creator.py) : échange guidé avec l'auteur, ADN proposé
par rapport au genre, bible rédigée, différentiel sans écrasement — en mock uniquement."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.pipeline.pre_direction import DnaError, apply_overrides, flatten
from mangaka_engine.pipeline.series_creator import (
    Answer,
    CreatorBrief,
    CreatorError,
    ProposalValidationError,
    conflicts,
    creator_messages,
    merge_dna,
    parse_proposal,
    propose,
    resolve_answers,
    suggested_dna,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_series_creation
from tests.conftest import PRESETS_DIR, STYLE, start_script

PRESETS = PresetRegistry.load(PRESETS_DIR)
SETTINGS = PRESETS.series_creator
assert SETTINGS is not None
PROMPT = PRESETS.prompt(SETTINGS.prompt)
SHONEN = PRESETS.genre_dna("shonen")
assert SHONEN is not None
# Réponses : la première question au choix donné, les autres au choix « neutre » (le 2e).
NEUTRAL = {q.id: {"choice": q.choices[1].id} for q in SETTINGS.questions}


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _answers(**picked: str) -> dict[str, dict[str, str]]:
    return {**NEUTRAL, **{q: {"choice": c} for q, c in picked.items()}}


def _brief(answers: list[Answer], characters: list[dict[str, Any]] | None = None, pitch: str = "") -> CreatorBrief:
    return CreatorBrief(
        project_id=1,
        title="L'île",
        genre="Shōnen",
        style_packs="Shōnen",
        style_guidelines="",
        reading_direction="de droite à gauche (manga)",
        pitch=pitch,
        answers=answers,
        suggestions=suggested_dna(SHONEN, answers),
        base=SHONEN,
        characters=characters if characters is not None else [{"id": 7, "name": "Aiko", "description": "", "note": ""}],
        chapters=[],
        bible={"synopsis": "", "world": "", "tone": "", "rules": "", "motifs": ""},
        settings=SETTINGS,
    )


def _valid(**overrides: Any) -> dict[str, Any]:
    return {
        "dna": [{"path": "dialogue.max_per_page", "value": 5, "why": "Tu veux des personnages peu bavards."}],
        "bible": {
            "synopsis": "Aiko veut quitter l'île ; elle y reste pour la sauver.",
            "world": "Une île.",
            "tone": "Doux.",
            "rules": "Pas de magie.",
            "motifs": "Un chat roux.",
        },
        "characters": [{"name": "aiko", "note": "Têtue. « Allons-y ! »"}],
        **overrides,
    }


# --- le preset et l'agent -----------------------------------------------------------------------------------
def test_the_creator_is_a_seventh_agent_with_its_own_knowledge_role() -> None:
    agent = PRESETS.agents["createur-serie"]
    assert agent.knowledge_role == "series_creation" and agent.step == 0 and agent.llm is not None
    k = PRESETS.knowledge.agents["series_creation"]  # type: ignore[union-attr]
    assert "Structure · Fins de chapitre" in k.collections and "Écriture de scénario" in k.collections
    assert k.bible is False  # la bible actuelle lui est donnée à part
    assert not [i for i in PRESETS.issues if "series_creator" in i.path or "createur" in i.path], PRESETS.issues
    ids = [q.id for q in SETTINGS.questions]
    assert {"rythme", "dialogue", "monde", "humour", "plans", "nervosite", "voix", "fin"} <= set(ids)
    assert all(2 <= len(q.choices) <= 6 for q in SETTINGS.questions)


def test_answers_need_a_choice_for_each_question() -> None:
    answers = resolve_answers(SETTINGS, _answers(dialogue="peu"))
    assert [a.question.id for a in answers] == [q.id for q in SETTINGS.questions]
    with pytest.raises(ValueError, match="choisis une réponse"):
        resolve_answers(SETTINGS, {**NEUTRAL, "rythme": {}})
    with pytest.raises(ValueError, match="choix inconnu"):
        resolve_answers(SETTINGS, _answers(rythme="supersonique"))
    with pytest.raises(ValueError, match="question inconnue"):
        resolve_answers(SETTINGS, {**NEUTRAL, "couleur": {"choice": "rouge"}})


# --- fusion ADN / défauts du genre --------------------------------------------------------------------------
def test_suggestions_shift_the_genre_values_within_bounds() -> None:
    inherited = flatten(SHONEN)
    talky = suggested_dna(SHONEN, resolve_answers(SETTINGS, _answers(dialogue="bavard")))
    assert {s.path: s.value for s in talky} == {
        "dialogue.min_per_page": inherited["dialogue.min_per_page"] + 1,
        "dialogue.max_per_page": inherited["dialogue.max_per_page"] + 2,
    }
    assert talky[0].choice.startswith("Beaucoup")
    # Neutre partout : aucun écart au genre.
    assert suggested_dna(SHONEN, resolve_answers(SETTINGS, NEUTRAL)) == []
    # Fin apaisée : valeur prise (0 = fin libre) ; « cliffhanger » au genre (1 en shōnen) n'est pas un écart.
    calm = suggested_dna(SHONEN, resolve_answers(SETTINGS, _answers(fin="apaisee")))
    assert [(s.path, s.value) for s in calm] == [("rhythm.final_peak_last_pages", 0)]
    assert suggested_dna(SHONEN, resolve_answers(SETTINGS, _answers(fin="cliffhanger"))) == []
    # Toujours un ADN valide (minimum sous le maximum), quel que soit le mélange de réponses.
    every = {q.id: {"choice": q.choices[-1].id} for q in SETTINGS.questions}
    for genre in PRESETS.pre_direction.genres:  # type: ignore[union-attr]
        base = PRESETS.genre_dna(genre)
        for picked in (every, {q.id: {"choice": q.choices[0].id} for q in SETTINGS.questions}):
            apply_overrides(base, {s.path: s.value for s in suggested_dna(base, resolve_answers(SETTINGS, picked))})  # type: ignore[arg-type]


def test_merge_keeps_the_series_adjustments_and_drops_genre_values() -> None:
    inherited = flatten(SHONEN)
    current = {"shots.wide.min": 0.25}
    merged = merge_dna(
        SHONEN, current, {"dialogue.max_per_page": 5, "panels.min_per_page": inherited["panels.min_per_page"]}
    )
    assert merged == {"shots.wide.min": 0.25, "dialogue.max_per_page": 5}  # la valeur du genre reste héritée
    # Revenir à la valeur du genre retire l'ajustement : elle suit le genre.
    assert merge_dna(SHONEN, merged, {"shots.wide.min": inherited["shots.wide.min"]}) == {"dialogue.max_per_page": 5}
    with pytest.raises(DnaError):
        merge_dna(SHONEN, {}, {"shots.wide.min": 0.6, "shots.wide.max": 0.3})


# --- schéma de la réponse -----------------------------------------------------------------------------------
def test_proposal_schema_and_dna_checks() -> None:
    brief = _brief(resolve_answers(SETTINGS, _answers(dialogue="peu")))
    out = parse_proposal(json.dumps(_valid()), brief)
    assert out.overrides() == {"dialogue.max_per_page": 5} and out.notes_by_id == {7: "Têtue. « Allons-y ! »"}
    # Une valeur égale au genre n'est pas un écart : ignorée, sans explication exigée.
    same = flatten(SHONEN)["panels.min_per_page"]
    out = parse_proposal(json.dumps(_valid(dna=[{"path": "panels.min_per_page", "value": same}])), brief)
    assert out.dna == []
    # En bloc de code, entier écrit 5.0 : accepté.
    fenced = (
        "```json\n" + json.dumps(_valid(dna=[{"path": "dialogue.max_per_page", "value": 5.0, "why": "x"}])) + "\n```"
    )
    assert parse_proposal(fenced, brief).overrides() == {"dialogue.max_per_page": 5}

    bad = [
        ("pas du JSON", "JSON illisible"),
        (json.dumps({"dna": []}), "bible"),
        (json.dumps(_valid(dna=[{"path": "rythme.global", "value": 3, "why": "x"}])), "réglage inconnu"),
        (json.dumps(_valid(dna=[{"path": "dialogue.max_per_page", "value": 5}])), "sans explication"),
        (json.dumps(_valid(dna=[{"path": "shots.wide.min", "value": 0.6, "why": "x"}])), "minimum"),
        (json.dumps(_valid(dna=[{"path": "panels.max_per_page", "value": 99, "why": "x"}])), "panels.max_per_page"),
        (
            json.dumps(_valid(bible={"synopsis": "s", "world": "Une île.", "tone": "", "rules": "x", "motifs": "y"})),
            "Ton) : vide",
        ),
        (
            json.dumps(_valid(bible={"world": "w", "tone": "t", "rules": "r", "motifs": "m"})),
            "(Synopsis de la série) : vide",
        ),
        (json.dumps(_valid(characters=[{"name": "Bob", "note": "x"}])), "n'est pas une fiche"),
        (json.dumps(_valid(characters=[])), "il manque la note de « Aiko »"),
        (
            json.dumps(_valid(bible={"synopsis": "s", "world": "x" * 5000, "tone": "a", "rules": "b", "motifs": "c"})),
            "au plus",
        ),
        (
            json.dumps(_valid(bible={**_valid()["bible"], "synopsis": "x" * (SETTINGS.max_synopsis_chars + 1)})),
            f"bible.synopsis (Synopsis de la série) : {SETTINGS.max_synopsis_chars + 1} signes",
        ),
    ]
    for text, message in bad:
        with pytest.raises(ProposalValidationError, match=re.escape(message)):
            parse_proposal(text, brief)


def test_prompt_carries_answers_genre_dna_and_hints() -> None:
    brief = _brief(resolve_answers(SETTINGS, _answers(dialogue="peu")), pitch="Une île volcanique.")
    [system, user] = creator_messages(PROMPT, brief)
    assert "JSON" in system.content and "Une île volcanique." in user.content
    assert "Les personnages parlent-ils beaucoup ? → Peu, les images racontent" in user.content
    assert "pistes : dialogue.min_per_page = 2" in user.content
    assert "- dialogue.max_per_page — Répliques par planche, au plus : 7 [1 à" in user.content
    assert "- Aiko : (sans description)" in user.content and '"task": "series_creation"' in user.content


def test_invalid_answers_retry_then_fail_readably() -> None:
    answers = resolve_answers(SETTINGS, _answers(dialogue="peu"))
    run = propose(MockLLMProvider(), PROMPT, _brief(answers, pitch="Île [mock:createur-invalide:2]"))
    assert run.attempts == 3 and run.output.overrides()
    llm = MockLLMProvider()
    with pytest.raises(CreatorError, match="réponse invalide 3 fois de suite"):
        propose(llm, PROMPT, _brief(answers, pitch="Île [mock:createur-invalide:3]"))
    assert len(llm.calls) == 3  # 1 essai + 2 relances, jamais plus
    retry = llm.calls[-1][-1]
    assert retry.role == "user" and "invalide" in retry.content


def test_mock_proposal_reads_the_hints() -> None:
    answers = resolve_answers(SETTINGS, _answers(plans="visages", fin="apaisee"))
    brief = _brief(answers)
    out = mock_series_creation(brief.as_json())
    paths = {d["path"] for d in out["dna"]}
    assert "rhythm.final_peak_last_pages" in paths and "shots.close_up.min" in paths
    assert all("Tu as répondu" in d["why"] for d in out["dna"])
    parse_proposal(json.dumps(out), brief)  # valide


# --- non-écrasement ---------------------------------------------------------------------------------------
def test_conflicts_list_only_what_the_author_wrote() -> None:
    found = conflicts(
        base=SHONEN,
        current_overrides={"shots.wide.min": 0.25},
        current_bible={"synopsis": "", "world": "Mon île.", "tone": "", "rules": "", "motifs": ""},
        current_notes={7: "Têtue."},
        dna={"shots.wide.min": 0.3, "dialogue.max_per_page": 5},
        bible={"world": "Une autre île.", "tone": "Doux."},
        notes={7: "Têtue.", 8: "Calme."},
        names={7: "Aiko", 8: "Kenji"},
    )
    assert [c.key for c in found] == ["bible.world", "dna.shots.wide.min"]


# --- API : création, échange, proposition, enregistrement, relance -------------------------------------------
def _series(client: TestClient, title: str = "Île") -> tuple[int, int, int]:
    s = _ok(client.post("/projects", json={**STYLE, "title": title}), 201)
    aiko = _ok(client.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
    kenji = _ok(client.post(f"/projects/{s['id']}/characters", json={"name": "Kenji"}), 201)
    return s["id"], aiko["id"], kenji["id"]


def _accept_all(proposal: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "dna": {d["path"]: d["proposed"] for d in proposal["dna"]},
        "bible": {b["key"]: b["proposed"] for b in proposal["bible"]},
        "character_notes": {str(c["id"]): c["proposed"] for c in proposal["characters"]},
        "overwrite": [],
    }
    if overwrite:
        body["overwrite"] = (
            [f"bible.{b['key']}" for b in proposal["bible"] if b["conflict"]]
            + [f"character.{c['id']}" for c in proposal["characters"] if c["conflict"]]
            + [f"dna.{d['path']}" for d in proposal["dna"] if d["conflict"]]
        )
    return body


def test_create_answer_propose_then_save_dna_and_bible(client: TestClient) -> None:
    pid, aiko, kenji = _series(client)
    info = _ok(client.get(f"/projects/{pid}/series-creator"))
    assert info["available"] and info["genre_name"] == "Shōnen" and info["agent_name"] == "Créateur de série"
    assert info["bible_filled"] == [] and info["characters"] == 2 and info["notes_filled"] == 0
    assert info["questions"][0]["choices"][0]["label"]

    missing = client.post(f"/projects/{pid}/series-creator/proposal", json={"answers": {}})
    assert missing.status_code == 422 and "choisis une réponse" in missing.text

    answers = _answers(dialogue="peu", fin="apaisee")
    answers["dialogue"]["note"] = "Les silences comptent."
    proposal = _ok(
        client.post(
            f"/projects/{pid}/series-creator/proposal", json={"pitch": "Une île volcanique.", "answers": answers}
        )
    )
    # Rien n'est enregistré tant que l'auteur n'a pas validé.
    assert _ok(client.get(f"/projects/{pid}/bible"))["world"] == ""
    assert _ok(client.get(f"/projects/{pid}/pre-direction"))["overrides"] == {}
    dna = {d["path"]: d for d in proposal["dna"]}
    assert dna["dialogue.max_per_page"]["genre_value"] == 7 and dna["dialogue.max_per_page"]["proposed"] == 5
    assert dna["dialogue.max_per_page"]["why"] and not dna["dialogue.max_per_page"]["conflict"]
    assert all(not b["conflict"] and b["proposed"] for b in proposal["bible"])
    assert "Une île volcanique." in proposal["bible"][0]["proposed"]
    assert "Les silences comptent" in next(b for b in proposal["bible"] if b["key"] == "rules")["proposed"]
    assert {c["name"] for c in proposal["characters"]} == {"Aiko", "Kenji"}

    # L'auteur corrige avant d'enregistrer.
    body = _accept_all(proposal)
    body["bible"]["world"] = "Une île volcanique, corrigée par l'auteur."
    saved = _ok(client.post(f"/projects/{pid}/series-creator/apply", json=body))
    assert saved["pre_direction"]["overrides"]["dialogue.max_per_page"] == 5
    assert saved["bible"]["world"] == "Une île volcanique, corrigée par l'auteur."
    notes = {c["id"]: c["note"] for c in saved["bible"]["characters"]}
    assert notes[aiko] and notes[kenji] and "bible.world" in saved["written"]
    assert _ok(client.get(f"/projects/{pid}/pre-direction"))["effective"]["dialogue.max_per_page"] == 5

    # Le prompt du scénariste suivant contient la bible et la note de chaque personnage présent.
    ch = _ok(client.post(f"/projects/{pid}/chapters", json={"title": "Un", "synopsis": "Aiko et Kenji arrivent."}), 201)
    brief = _ok(client.get(f"/chapters/{ch['id']}/script-brief"))
    assert brief["bible_empty"] is False and brief["characters_without_note"] == []
    job = _ok(start_script(client, ch["id"]), 202)
    client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    user = client.app.state.ctx.providers.llm.calls[-1][1].content  # type: ignore[attr-defined]
    assert "Une île volcanique, corrigée par l'auteur." in user
    assert f"- Aiko : {notes[aiko]}" in user and f"- Kenji : {notes[kenji]}" in user
    sources = _ok(client.get(f"/chapters/{ch['id']}/sources"))
    assert f"Aiko : {notes[aiko]}" in sources["bible"]["text"]  # visible à l'écran Scénario


def test_relaunch_shows_a_diff_and_never_overwrites_without_confirmation(client: TestClient) -> None:
    pid, aiko, kenji = _series(client)
    _ok(
        client.put(
            f"/projects/{pid}/bible",
            json={"world": "Mon île à moi.", "character_notes": {str(aiko): "Ma note sur Aiko."}},
        )
    )
    _ok(client.put(f"/projects/{pid}/pre-direction", json={"overrides": {"dialogue.max_per_page": 6}}))
    info = _ok(client.get(f"/projects/{pid}/series-creator"))
    assert info["bible_filled"] == ["world"] and info["notes_filled"] == 1 and info["dna_adjusted"] == 1

    proposal = _ok(client.post(f"/projects/{pid}/series-creator/proposal", json={"answers": _answers(dialogue="peu")}))
    world = next(b for b in proposal["bible"] if b["key"] == "world")
    assert world["current"] == "Mon île à moi." and world["conflict"] and world["proposed"] != world["current"]
    assert next(b for b in proposal["bible"] if b["key"] == "tone")["conflict"] is False
    notes = {c["id"]: c for c in proposal["characters"]}
    assert notes[aiko]["conflict"] and notes[aiko]["current"] == "Ma note sur Aiko." and not notes[kenji]["conflict"]
    dna = {d["path"]: d for d in proposal["dna"]}
    assert dna["dialogue.max_per_page"]["adjusted"] and dna["dialogue.max_per_page"]["current_value"] == 6
    assert dna["dialogue.max_per_page"]["conflict"]
    # La bible actuelle est donnée à l'agent.
    user = client.app.state.ctx.providers.llm.calls[-1][1].content  # type: ignore[attr-defined]
    assert "Mon île à moi." in user and "note actuelle : Ma note sur Aiko." in user

    # Tout accepter sans confirmer : 409, rien n'est écrit.
    refused = client.post(f"/projects/{pid}/series-creator/apply", json=_accept_all(proposal))
    assert refused.status_code == 409 and "Rien n'a été enregistré" in refused.text and "Univers" in refused.text
    bible = _ok(client.get(f"/projects/{pid}/bible"))
    assert bible["world"] == "Mon île à moi." and bible["tone"] == ""
    assert _ok(client.get(f"/projects/{pid}/pre-direction"))["overrides"] == {"dialogue.max_per_page": 6}

    # Ne garder que les nouveautés : les sections vides se remplissent, le reste ne bouge pas.
    body = _accept_all(proposal)
    body["bible"].pop("world")
    body["character_notes"].pop(str(aiko))
    body["dna"].pop("dialogue.max_per_page")
    saved = _ok(client.post(f"/projects/{pid}/series-creator/apply", json=body))
    assert saved["bible"]["world"] == "Mon île à moi." and saved["bible"]["tone"]
    notes_after = {c["id"]: c["note"] for c in saved["bible"]["characters"]}
    assert notes_after[aiko] == "Ma note sur Aiko." and notes_after[kenji]
    assert saved["pre_direction"]["overrides"]["dialogue.max_per_page"] == 6

    # Confirmé : remplacé.
    saved = _ok(client.post(f"/projects/{pid}/series-creator/apply", json=_accept_all(proposal, overwrite=True)))
    assert saved["bible"]["world"] == world["proposed"]
    assert saved["pre_direction"]["overrides"]["dialogue.max_per_page"] == dna["dialogue.max_per_page"]["proposed"]


def test_invalid_llm_answers_give_a_readable_error(client: TestClient) -> None:
    pid, *_ = _series(client)
    resp = client.post(
        f"/projects/{pid}/series-creator/proposal",
        json={"pitch": "Une île [mock:createur-invalide:3]", "answers": _answers()},
    )
    assert resp.status_code == 502
    assert "Le créateur de série n'a pas pu proposer" in resp.json()["detail"]
    ok = _ok(
        client.post(
            f"/projects/{pid}/series-creator/proposal",
            json={"pitch": "Une île [mock:createur-invalide:1]", "answers": _answers()},
        )
    )
    assert ok["attempts"] == 2


def test_apply_rejects_unknown_targets(client: TestClient) -> None:
    pid, *_ = _series(client)
    url = f"/projects/{pid}/series-creator/apply"
    assert client.post(url, json={"bible": {"lore": "x"}}).status_code == 422
    assert client.post(url, json={"character_notes": {"999": "x"}}).status_code == 422
    bad = client.post(url, json={"dna": {"shots.wide.min": 0.6, "shots.wide.max": 0.3}})
    assert bad.status_code == 422 and "minimum" in bad.text
    assert client.post(url, json={"dna": {"rythme.global": 3}}).status_code == 422
    assert client.get("/projects/999/series-creator").status_code == 404


# --- synopsis de la série (#243) ----------------------------------------------------------------------------
def test_mock_synopsis_expands_the_pitch_without_growing_on_relaunch() -> None:
    brief = _brief(resolve_answers(SETTINGS, NEUTRAL), pitch="Aiko veut quitter l'île.")
    synopsis = mock_series_creation(brief.as_json())["bible"]["synopsis"]
    assert synopsis.startswith("Aiko veut quitter l'île.") and "Fin visée" in synopsis
    again = _brief(resolve_answers(SETTINGS, NEUTRAL), pitch=synopsis)
    assert mock_series_creation(again.as_json())["bible"]["synopsis"] == synopsis
    assert mock_series_creation(_brief(resolve_answers(SETTINGS, NEUTRAL)).as_json())["bible"]["synopsis"]


def test_conflicts_cover_the_series_synopsis() -> None:
    found = conflicts(
        base=SHONEN,
        current_overrides={},
        current_bible={"synopsis": "Mon histoire.", "world": "", "tone": "", "rules": "", "motifs": ""},
        current_notes={},
        dna={},
        bible={"synopsis": "Une autre histoire.", "world": "Une île."},
        notes={},
        names={},
    )
    assert [(c.key, c.label) for c in found] == [("bible.synopsis", "Synopsis de la série")]
    same = conflicts(
        base=SHONEN,
        current_overrides={},
        current_bible={"synopsis": "Mon histoire."},
        current_notes={},
        dna={},
        bible={"synopsis": " Mon   histoire. "},
        notes={},
        names={},
    )
    assert same == []


def test_the_pitch_becomes_the_series_synopsis_read_by_every_agent(client: TestClient) -> None:
    """Série sans chapitre : l'idée de l'auteur devient le synopsis de la série (1re section de la bible), gardé
    après rechargement, puis reçu en tête de bible par le découpage en scènes et le scénariste."""
    pid, *_ = _series(client)
    assert _ok(client.get(f"/projects/{pid}/series-creator"))["synopsis"] == ""
    pitch = "Aiko, forgeronne sans magie, veut entrer à l'Académie des sabres pour retrouver son frère."
    proposal = _ok(
        client.post(f"/projects/{pid}/series-creator/proposal", json={"pitch": pitch, "answers": _answers()})
    )
    first = proposal["bible"][0]
    assert first["key"] == "synopsis" and first["label"] == "Synopsis de la série" and first["current"] == ""
    assert first["proposed"].startswith(pitch) and not first["conflict"]
    user = client.app.state.ctx.providers.llm.calls[-1][1].content  # type: ignore[attr-defined]
    assert "(bible vide)" in user and pitch in user

    saved = _ok(client.post(f"/projects/{pid}/series-creator/apply", json=_accept_all(proposal)))
    assert "bible.synopsis" in saved["written"] and saved["bible"]["synopsis"] == first["proposed"]
    bible = _ok(client.get(f"/projects/{pid}/bible"))  # rechargement
    assert bible["synopsis"] == first["proposed"]
    assert bible["rendered"]["text"].startswith(f"Synopsis de la série :\n{first['proposed']}\n\nUnivers :")
    info = _ok(client.get(f"/projects/{pid}/series-creator"))
    assert info["synopsis"] == first["proposed"] and info["bible_filled"][0] == "synopsis"
    assert info["bible_sections"] == 5

    calls = client.app.state.ctx.providers.llm.calls  # type: ignore[attr-defined]
    ch = _ok(client.post(f"/projects/{pid}/chapters", json={"title": "Un", "synopsis": "Aiko arrive."}), 201)
    job = _ok(client.post(f"/chapters/{ch['id']}/scenes/propose"), 202)
    client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    scenes_user = next(m.content for m in calls[-1] if m.role == "user")
    assert pitch in scenes_user
    assert scenes_user.index("Synopsis de la série :") < scenes_user.index("Univers :")
    job = _ok(start_script(client, ch["id"]), 202)
    client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    script_user = calls[-1][1].content
    assert pitch in script_user and script_user.index("Synopsis de la série :") < script_user.index("Univers :")


def test_relaunch_with_a_synopsis_shows_it_and_overwrites_it_only_when_confirmed(client: TestClient) -> None:
    pid, *_ = _series(client)
    saved = _ok(client.put(f"/projects/{pid}/bible", json={"synopsis": "Mon histoire.", "world": "Mon île."}))
    assert saved["synopsis"] == "Mon histoire." and _ok(client.get(f"/projects/{pid}/chapters")) == []
    info = _ok(client.get(f"/projects/{pid}/series-creator"))
    assert info["synopsis"] == "Mon histoire." and info["bible_filled"] == ["synopsis", "world"]

    proposal = _ok(
        client.post(f"/projects/{pid}/series-creator/proposal", json={"pitch": info["synopsis"], "answers": _answers()})
    )
    user = client.app.state.ctx.providers.llm.calls[-1][1].content  # type: ignore[attr-defined]
    assert "Synopsis de la série :\nMon histoire." in user  # donné à l'agent comme texte actuel
    synopsis = proposal["bible"][0]
    assert synopsis["key"] == "synopsis" and synopsis["current"] == "Mon histoire." and synopsis["conflict"]
    assert synopsis["proposed"].startswith("Mon histoire.")

    body = {"bible": {"synopsis": synopsis["proposed"]}}
    refused = client.post(f"/projects/{pid}/series-creator/apply", json=body)
    assert refused.status_code == 409 and "Synopsis de la série" in refused.text
    after = _ok(client.get(f"/projects/{pid}/bible"))
    assert after["synopsis"] == "Mon histoire." and after["world"] == "Mon île." and after["tone"] == ""

    done = _ok(client.post(f"/projects/{pid}/series-creator/apply", json={**body, "overwrite": ["bible.synopsis"]}))
    assert done["written"] == ["bible.synopsis"] and done["bible"]["synopsis"] == synopsis["proposed"]
    assert done["bible"]["world"] == "Mon île." and done["bible"]["tone"] == ""
