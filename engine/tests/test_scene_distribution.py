"""Distribution par scène (#197) : personnages et lieu de la scène descendus sur ses cases, contradiction « hors cadre »
signalée et résolue, pic du chapitre sur une scène calme, migration v39."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import build_panel_prompt
from mangaka_engine.pipeline.names import CharacterMatcher, visible_actions, without_actions
from mangaka_engine.pipeline.scenes import script_scenes
from mangaka_engine.pipeline.script import parse_script, save_script
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import Chapter, Character, Panel
from tests.conftest import STYLE
from tests.test_migrations import _columns, _version


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


def _wait(c: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    c.app.state.ctx.jobs.wait(job["id"], 60)  # type: ignore[attr-defined]
    return _ok(c.get(f"/jobs/{job['id']}"))


def _db(c: TestClient) -> Any:
    return c.app.state.ctx.db  # type: ignore[attr-defined]


def _presets(c: TestClient) -> Any:
    return c.app.state.ctx.presets  # type: ignore[attr-defined]


SYNOPSIS = "Aiko arrive au dojo au petit matin. Le Gorille frappe Aiko de toutes ses forces."


def _series(c: TestClient, synopsis: str = SYNOPSIS, target: int = 4) -> dict[str, Any]:
    """Série OSU : Aiko, le Gorille (alias « le singe ») et Rônin ; un dojo (lieu avec sa fiche de décor) et une forêt."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "OSU"}), 201)
    ids = {
        name: _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name, "aliases": aliases}), 201)["id"]
        for name, aliases in (("Aiko", []), ("Gorille", ["le singe"]), ("Rônin", []))
    }
    decor = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "Dojo"}), 201)
    dojo = _ok(c.post(f"/projects/{s['id']}/locations", json={"name": "Le dojo", "decor": decor["id"]}), 201)
    forest = _ok(c.post(f"/projects/{s['id']}/locations", json={"name": "La forêt"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"synopsis": synopsis, "target_page_count": target}), 201)
    return {"series": s, "chapter": ch, "ids": ids, "decor": decor["id"], "dojo": dojo["id"], "forest": forest["id"]}


def _scenes(c: TestClient, w: dict[str, Any], *, last: str = "combat") -> dict[str, Any]:
    ids = w["ids"]
    body = {
        "scenes": [
            {
                "title": "L'arrivée",
                "summary": "Aiko arrive au dojo.",
                "type": "calme",
                "pages": 2,
                "location_id": w["dojo"],
                "characters": [ids["Aiko"], ids["Gorille"]],
            },
            {
                "title": "OSU",
                "summary": "Le coup de poing final.",
                "type": last,
                "pages": 2,
                "characters": [ids["Gorille"]],
            },
        ]
    }
    _ok(c.put(f"/chapters/{w['chapter']['id']}/scenes", json=body))
    return _ok(c.post(f"/chapters/{w['chapter']['id']}/scenes/validate"))


def _panel(description: str, characters: list[str], offscreen: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"description": description, "characters": characters, "offscreen": offscreen or [], **extra}


# Scénario d'une scène par page : la scène 1 (calme, dojo, Aiko + Gorille) et la scène 2 (combat, Gorille).
SCRIPT = {
    "summary": "Aiko au dojo, le Gorille frappe.",
    "pages": [
        {
            "scene": 1,
            "panels": [
                _panel("Le singe abat son poing devant Aiko.", ["Aiko"]),  # alias, non déclaré → à l'image
                _panel("Aiko sourit, le Gorille la regarde.", ["Aiko"], ["Gorille"]),  # déclaré hors cadre : intact
                _panel("Rônin entre, Aiko se retourne.", ["Aiko"]),  # pas dans la distribution : rien
            ],
        },
        {"scene": 1, "panels": [_panel("Le Gorille salue.", [], lieu="La forêt")]},  # lieu donné par la case
        {"scene": 2, "panels": [_panel("Gorille frappe.", [])]},
        {"scene": 2, "panels": [_panel("OSU !", ["Gorille"])]},
    ],
}


def _write(c: TestClient, w: dict[str, Any], script: dict[str, Any] = SCRIPT) -> None:
    with _db(c).session_scope() as session:
        chapter = session.get(Chapter, w["chapter"]["id"])
        output = parse_script(json.dumps(script, ensure_ascii=False))
        save_script(session, chapter, output, script_scenes(_presets(c), chapter))
        session.commit()


def _pages(c: TestClient, w: dict[str, Any]) -> list[dict[str, Any]]:
    return _ok(c.get(f"/chapters/{w['chapter']['id']}/pages"))


def _kinds(panel: dict[str, Any]) -> list[str]:
    return [n["kind"] for n in panel["name_notes"]]


# --- distribution proposée, éditée, validée --------------------------------------------------------------------
def test_scenes_agent_proposes_the_cast_of_each_scene(c: TestClient) -> None:
    w = _series(c)
    job = _wait(c, _ok(c.post(f"/chapters/{w['chapter']['id']}/scenes/propose"), 202))
    assert job["status"] == "succeeded", job
    data = _ok(c.get(f"/chapters/{w['chapter']['id']}/scenes"))
    casts = [[x["name"] for x in s["characters"]] for s in data["scenes"]]
    assert casts == [["Aiko"], ["Aiko", "Gorille"]]
    assert not data["validated"]
    # Le prompt demande la distribution, avec les noms exacts des fiches (alias compris).
    calls = [call for call in c.app.state.ctx.providers.llm.calls if '"task": "scenes"' in call[1].content]  # type: ignore[attr-defined]
    prompt = calls[-1][1].content
    assert "« personnages »" in prompt and "« Gorille »" in prompt and "le singe" in prompt


def test_cast_is_edited_kept_and_validated_by_the_author(c: TestClient) -> None:
    w = _series(c)
    ch, ids = w["chapter"]["id"], w["ids"]
    data = _scenes(c, w)
    assert data["validated"]
    assert [[x["name"] for x in s["characters"]] for s in data["scenes"]] == [["Aiko", "Gorille"], ["Gorille"]]
    # Retouche : la distribution change, la validation est retirée ; une scène renvoyée sans distribution la garde.
    scenes = [
        {"id": s["id"], "title": s["title"], "summary": s["summary"], "type": s["type"], "pages": s["pages"]}
        for s in data["scenes"]
    ]
    scenes[1]["characters"] = [ids["Gorille"], ids["Rônin"]]
    edited = _ok(c.put(f"/chapters/{ch}/scenes", json={"scenes": scenes}))
    assert not edited["validated"]
    assert [x["id"] for x in edited["scenes"][0]["characters"]] == [ids["Aiko"], ids["Gorille"]]
    assert [x["name"] for x in edited["scenes"][1]["characters"]] == ["Gorille", "Rônin"]
    assert _ok(c.post(f"/chapters/{ch}/scenes/validate"))["validated"]
    # Une fiche d'une autre série est refusée.
    other = _ok(c.post("/projects", json={**STYLE, "title": "Autre"}), 201)
    stranger = _ok(c.post(f"/projects/{other['id']}/characters", json={"name": "Intrus"}), 201)["id"]
    scenes[0]["characters"] = [stranger]
    resp = c.put(f"/chapters/{ch}/scenes", json={"scenes": scenes})
    assert resp.status_code == 422 and "scenes.0.characters" in resp.text


def test_scenario_and_art_direction_receive_the_scene_cast(c: TestClient) -> None:
    w = _series(c)
    _scenes(c, w)
    job = _wait(c, _ok(c.post(f"/chapters/{w['chapter']['id']}/script"), 202))
    assert job["status"] == "succeeded", job
    calls = c.app.state.ctx.providers.llm.calls  # type: ignore[attr-defined]
    scripts = [call[1].content for call in calls if '"task": "script"' in call[1].content]
    assert "Distribution de la scène : Aiko, Gorille" in scripts[0] and "lieu : Le dojo" in scripts[0]
    assert "Distribution de la scène : Gorille" in scripts[1]
    job = _wait(c, _ok(c.post(f"/chapters/{w['chapter']['id']}/direction"), 202))
    assert job["status"] == "succeeded", job
    directions = [call[1].content for call in calls if '"task": "art_direction"' in call[1].content]
    assert any("Distribution de la scène : Aiko, Gorille" in d for d in directions)


# --- descente sur les cases -----------------------------------------------------------------------------------
def test_cast_and_location_descend_on_the_panels_of_the_scene(c: TestClient) -> None:
    w = _series(c)
    _scenes(c, w)
    _write(c, w)
    pages = _pages(c, w)
    first = pages[0]["panels"]
    # Nommé par un alias, non déclaré : déclaré dans l'image (sa fiche part).
    assert first[0]["characters"] == ["Aiko", "Gorille"] and "non déclaré" not in _kinds(first[0])
    # Déjà déclaré hors cadre : la descente n'y touche pas.
    assert first[1]["characters"] == ["Aiko"] and first[1]["offscreen_characters"] == ["Gorille"]
    # Pas dans la distribution : toujours signalé, jamais ajouté.
    assert first[2]["characters"] == ["Aiko"] and "non déclaré" in _kinds(first[2])
    # Combat : le Gorille nommé par son nom.
    assert pages[2]["panels"][0]["characters"] == ["Gorille"]
    # Lieu : celui de la scène pour les cases sans lieu (scène 1 : le dojo, et donc sa fiche de décor) ; celui de
    # la case quand elle en donne un ; aucun pour la scène 2 (sans lieu).
    assert [p["location"] for p in first] == [w["dojo"]] * 3
    assert pages[1]["panels"][0]["location"] == w["forest"]
    assert pages[2]["panels"][0]["location"] is None
    detail = _ok(c.get(f"/panels/{first[0]['id']}"))
    assert detail["decor"]["id"] == w["decor"]
    with _db(c).session_scope() as session:
        gorille = session.get(Character, w["ids"]["Gorille"])
        assert gorille is not None and gorille.id in session.get(Panel, first[0]["id"]).character_ids


def test_author_choices_on_a_panel_are_never_overwritten(c: TestClient) -> None:
    w = _series(c)
    ch = w["chapter"]["id"]
    data = _scenes(c, w)
    script = json.loads(json.dumps(SCRIPT))
    script["pages"][0]["panels"][0]["characters"] = ["Aiko"]
    _write(c, w, script)
    pages = _pages(c, w)
    target = pages[0]["panels"][0]
    assert target["characters"] == ["Aiko", "Gorille"]
    # L'auteur retire le Gorille de la case, et retire le lieu d'une autre case (écran Scénario).
    _ok(c.patch(f"/panels/{target['id']}", json={"characters": ["Aiko"]}))
    body = {
        "pages": [
            {
                "id": p["id"],
                "kind": p["kind"],
                "rythme": p["rythme"],
                "panels": [
                    {
                        "id": pa["id"],
                        "description": pa["description"],
                        "characters": ["Aiko"] if pa["id"] == target["id"] else pa["characters"],
                        "offscreen_characters": pa["offscreen_characters"],
                        **({"location": None} if pa["id"] == pages[0]["panels"][1]["id"] else {}),
                    }
                    for pa in p["panels"]
                ],
            }
            for p in pages
        ]
    }
    _ok(c.put(f"/chapters/{ch}/pages", json=body))
    # La liste est retouchée puis revalidée : la descente repasse sur les cases déjà écrites.
    scenes = [{k: s[k] for k in ("id", "title", "summary", "type", "pages", "location_id")} for s in data["scenes"]]
    _ok(c.put(f"/chapters/{ch}/scenes", json={"scenes": scenes}))
    _ok(c.post(f"/chapters/{ch}/scenes/validate"))
    after = _pages(c, w)[0]["panels"]
    assert after[0]["characters"] == ["Aiko"]  # choix manuel préservé
    assert after[1]["location"] is None  # lieu retiré à la main : préservé
    assert after[2]["location"] == w["dojo"]


def test_validation_brings_the_cast_down_on_panels_written_before(c: TestClient) -> None:
    """Une case écrite sans distribution (ou avant qu'elle change) la reçoit à la validation de la liste."""
    w = _series(c)
    ch = w["chapter"]["id"]
    data = _scenes(c, w)
    _write(c, w)
    with _db(c).session_scope() as session:
        panel = session.get(Chapter, ch).pages[2].panels[0]
        panel.description = "Le singe et Rônin s'affrontent."
        panel.character_names = []
        panel.character_ids = []
        session.commit()
        panel_id = panel.id
    scenes = [{k: s[k] for k in ("id", "title", "summary", "type", "pages")} for s in data["scenes"]]
    scenes[1]["characters"] = [w["ids"]["Gorille"], w["ids"]["Rônin"]]
    _ok(c.put(f"/chapters/{ch}/scenes", json={"scenes": scenes}))
    _ok(c.post(f"/chapters/{ch}/scenes/validate"))
    assert _ok(c.get(f"/panels/{panel_id}"))["characters"] == ["Gorille", "Rônin"]


# --- contradiction « hors cadre » ------------------------------------------------------------------------------
def test_visible_action_of_an_offscreen_character() -> None:
    m = CharacterMatcher(
        [Character(id=1, name="Gorille", aliases=["le singe"]), Character(id=2, name="Aiko", aliases=[])]
    )
    text = "Le singe abat son poing sur la table. Aiko sursaute."
    assert list(visible_actions(m, text, [1])) == [1]
    assert without_actions(m, text, [1]) == "Aiko sursaute."
    # Pas d'action visible : la phrase dit qu'il n'est pas vu, ou il est le spectateur (vue subjective).
    for quiet in (
        "On entend le Gorille rugir.",
        "La voix du Gorille résonne.",
        "Le Gorille regarde Aiko s'entraîner.",
        "Aiko pense au Gorille.",
        "Le Gorille, hors champ, grogne.",
    ):
        assert visible_actions(m, quiet, [1]) == {}, quiet
    assert without_actions(m, "On entend le Gorille rugir.", [1]) == "On entend le Gorille rugir."


def _offscreen_chapter(c: TestClient) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    w = _series(c)
    body = {
        "pages": [
            {
                "kind": "story",
                "panels": [
                    {
                        "description": "Le Gorille abat son poing sur la table. Aiko sursaute.",
                        "characters": ["Aiko"],
                        "offscreen_characters": ["Gorille"],
                    },
                    {
                        "description": "Aiko recule.",
                        "staging": "Le singe lève le bras, prêt à frapper.",
                        "characters": ["Aiko"],
                        "offscreen_characters": ["Gorille"],
                    },
                    {
                        "description": "On entend le Gorille rugir. Aiko frissonne.",
                        "characters": ["Aiko"],
                        "offscreen_characters": ["Gorille"],
                    },
                ],
            }
        ]
    }
    _ok(c.put(f"/chapters/{w['chapter']['id']}/pages", json=body))
    return w, _pages(c, w)[0]["panels"]


def test_offscreen_with_a_visible_action_is_flagged(c: TestClient) -> None:
    w, panels = _offscreen_chapter(c)
    note = next(n for n in panels[0]["name_notes"] if n["kind"] == "hors cadre en action")
    assert note["source"] == "description" and note["chosen"] == [{"id": w["ids"]["Gorille"], "name": "Gorille"}]
    assert "hors cadre" in note["message"] and "action visible" in note["message"]
    assert [n["source"] for n in panels[1]["name_notes"] if n["kind"] == "hors cadre en action"] == ["mise en scène"]
    assert "hors cadre en action" not in _kinds(panels[2])  # « on entend » : pas d'action visible
    detail = _ok(c.get(f"/panels/{panels[0]['id']}"))
    assert "hors cadre en action" in _kinds(detail) and detail["offscreen_kept"] == []


def test_put_in_the_image_resolves_the_alert_and_sends_the_card(c: TestClient) -> None:
    w, panels = _offscreen_chapter(c)
    out = _ok(c.patch(f"/panels/{panels[0]['id']}", json={"characters": ["Aiko", "Gorille"]}))
    assert out["characters"] == ["Aiko", "Gorille"] and out["offscreen_characters"] == []
    assert w["ids"]["Gorille"] in out["character_ids"] and "hors cadre en action" not in _kinds(out)


def test_keep_offscreen_resolves_the_alert_and_strips_the_action_from_the_prompt(c: TestClient) -> None:
    w, panels = _offscreen_chapter(c)
    gorille = w["ids"]["Gorille"]
    with _db(c).session_scope() as session:
        before = build_panel_prompt(_presets(c), session.get(Panel, panels[0]["id"]), [])
    assert "abat son poing" in before
    out = _ok(c.patch(f"/panels/{panels[0]['id']}", json={"offscreen_kept": [gorille]}))
    assert out["offscreen_kept"] == [gorille] and "hors cadre en action" not in _kinds(out)
    assert out["offscreen_characters"] == ["Gorille"]  # toujours hors cadre, sans référence
    assert gorille not in out["character_ids"]
    # Le choix est retenu : plus d'alerte dans le chapitre, et le prompt envoyé n'a plus l'action.
    assert "hors cadre en action" not in _kinds(_pages(c, w)[0]["panels"][0])
    with _db(c).session_scope() as session:
        prompt = build_panel_prompt(_presets(c), session.get(Panel, panels[0]["id"]), [])
    assert "abat son poing" not in prompt and "Aiko sursaute" in prompt
    if out["final_prompt"]:
        assert "abat son poing" not in out["final_prompt"]
    # Mise en scène : l'action retirée du prompt aussi.
    _ok(c.patch(f"/panels/{panels[1]['id']}", json={"offscreen_kept": [gorille]}))
    with _db(c).session_scope() as session:
        staged = build_panel_prompt(_presets(c), session.get(Panel, panels[1]["id"]), [])
    assert "lève le bras" not in staged and "Aiko recule" in staged
    # Remis à l'image plus tard : il n'est plus « laissé hors cadre ».
    out = _ok(c.patch(f"/panels/{panels[0]['id']}", json={"characters": ["Aiko", "Gorille"]}))
    assert out["offscreen_kept"] == []


# --- pic du chapitre --------------------------------------------------------------------------------------------
def test_peak_on_a_calm_scene_is_a_warning_only(c: TestClient) -> None:
    w = _series(c)
    data = _scenes(c, w, last="calme")  # le coup de poing final « OSU » classé calme
    assert data["validated"]  # jamais bloquant
    last = data["scenes"][-1]
    warnings = [x for x in data["peak_warnings"] if x["scene_id"] == last["id"]]
    assert warnings and "pic final" in warnings[0]["message"] and "profil calme" in warnings[0]["message"]
    # Le premier pic (25 à 40 % : page 2) tombe aussi sur une scène calme.
    assert any("premier pic" in x["message"] for x in data["peak_warnings"] if x["scene_id"] == data["scenes"][0]["id"])
    # Une scène de combat au bout : plus d'avertissement du pic final.
    fixed = _scenes(c, w, last="combat")
    assert not [x for x in fixed["peak_warnings"] if "pic final" in x["message"]]


# --- migration ---------------------------------------------------------------------------------------------------
def test_v38_database_fills_scene_casts_from_their_panels(make_settings: Callable[..., Settings]) -> None:
    """v38 → v39 : distribution des scènes existantes d'après les personnages déclarés de leurs cases (présents, hors
    cadre, locuteurs), choix de l'auteur vides ; la base neuve a les mêmes colonnes."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        w = _series(c)
        _scenes(c, w)
        _write(c, w)
        scene_ids = [s["id"] for s in _ok(c.get(f"/chapters/{w['chapter']['id']}/scenes"))["scenes"]]
    con = sqlite3.connect(settings.database_path)
    con.execute("ALTER TABLE chapter_scenes DROP COLUMN character_ids")
    for column in ("cast_manual", "location_manual", "offscreen_kept"):
        con.execute(f"ALTER TABLE panels DROP COLUMN {column}")
    con.execute("PRAGMA user_version = 38")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        data = _ok(c.get(f"/chapters/{w['chapter']['id']}/scenes"))
        casts = {s["id"]: [x["name"] for x in s["characters"]] for s in data["scenes"]}
        assert casts[scene_ids[0]] == ["Aiko", "Gorille"]  # Rônin, seulement nommé dans un texte : pas déclaré
        assert casts[scene_ids[1]] == ["Gorille"]
        panel = _pages(c, w)[0]["panels"][0]
        detail = _ok(c.get(f"/panels/{panel['id']}"))
        assert detail["offscreen_kept"] == []
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
