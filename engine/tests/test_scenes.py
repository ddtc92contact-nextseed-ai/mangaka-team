"""Étape « Scènes » (#189) : types de scène en liste fermée et profils de tempo (héritage profil → ADN), agent
« Découpage en scènes » (somme des pages = cible, relances), écran Scènes (retouches, validation), garde d'étapes
(scénario refusé sans scènes validées, passer-outre, ancien mode) et branchement sur le scénariste."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.pre_direction import DnaError, apply_tempo, tempo_profile
from mangaka_engine.pipeline.scenes import (
    ScenesValidationError,
    assign_scenes,
    parse_scenes,
    scene_page_problems,
    type_key,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import SCENE_TYPES, SceneType, SceneTypesSettings
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import Project
from tests.conftest import PRESETS_DIR, STYLE
from tests.fixtures.islands import PETITE_ILE, pages
from tests.test_migrations import _columns, _version

REG = PresetRegistry.load(PRESETS_DIR)
SYNOPSIS = (
    "Aiko arrive à Kyoto sous la pluie. Un rônin la frappe et lui vole son sabre. Elle le poursuit dans les ruelles. "
    "Il révèle qu'il est son frère. Ils discutent toute la nuit ? Au matin, ils partent ensemble."
)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


def _wait(c: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    c.app.state.ctx.jobs.wait(job["id"], 30)  # type: ignore[attr-defined]
    return _ok(c.get(f"/jobs/{job['id']}"))


def _chapter(c: TestClient, *, synopsis: str = SYNOPSIS, target: int = 12, genre: str = "shonen") -> dict[str, Any]:
    s = _ok(c.post("/projects", json={**STYLE, "style_genre": genre, "title": "Le sabre"}), 201)
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
    return _ok(c.post(f"/projects/{s['id']}/chapters", json={"synopsis": synopsis, "target_page_count": target}), 201)


def _propose(c: TestClient, chapter_id: int) -> dict[str, Any]:
    return _wait(c, _ok(c.post(f"/chapters/{chapter_id}/scenes/propose"), 202))


def _stage(c: TestClient, chapter_id: int) -> dict[str, Any]:
    return next(s for s in _ok(c.get(f"/chapters/{chapter_id}/stages"))["stages"] if s["key"] == "scenes")


# --- preset : liste fermée, profils écrits en curseurs de l'ADN ------------------------------------------
def test_preset_has_the_closed_list_and_valid_profiles() -> None:
    settings = REG.scene_types
    assert settings is not None and tuple(settings.types) == SCENE_TYPES
    assert not [i for i in REG.issues if "scene_types" in i.path]
    combat = settings.types["combat"].tempo
    assert combat["panels.min_per_page"] == combat["panels.max_per_page"] == 6
    assert combat["motion_lines.required"] is True and combat["dialogue.min_silent_panels"] == 2
    assert settings.types["calme"].tempo["motion_lines.forbidden"] is True


def test_preset_refuses_a_missing_type_an_unknown_value_and_both_motion_rules() -> None:
    types = {t: {"name": t} for t in SCENE_TYPES if t != "revelation"}
    with pytest.raises(ValidationError, match="type absent : revelation"):
        SceneTypesSettings.model_validate({"types": types})
    with pytest.raises(ValidationError, match="valeur inconnue du profil"):
        SceneType.model_validate({"name": "x", "tempo": {"panels": {"most": 3}}})
    with pytest.raises(ValidationError, match="part entre 0 et 1"):
        SceneType.model_validate({"name": "x", "tempo": {"shots": {"wide": {"max": 1.5}}}})
    with pytest.raises(ValidationError, match="imposées et interdites"):
        SceneType.model_validate({"name": "x", "tempo": {"motion_lines": {"required": True, "forbidden": True}}})
    with pytest.raises(ValidationError):
        SceneTypesSettings.model_validate({"types": {**types, "revelation": {"name": "r"}, "bagarre": {"name": "b"}}})


# --- héritage profil → ADN ---------------------------------------------------------------------------------
def test_profile_narrows_the_series_dna_without_replacing_it() -> None:
    shonen = REG.genre_dna("shonen")
    assert shonen is not None
    combat = REG.scene_types.types["combat"].tempo  # type: ignore[union-attr]
    dna = apply_tempo(shonen, combat)
    # Ce que le profil écrit : précisé.
    assert (dna.panels.min_per_page, dna.panels.max_per_page) == (6, 6)
    assert (dna.dialogue.min_per_page, dna.dialogue.max_per_page, dna.dialogue.min_silent_panels) == (2, 4, 2)
    assert dna.shots.close_up.min == 0.5 and dna.shots.wide.max == 0.17
    # Le reste : hérité de la série, intact (jamais remplacé en bloc).
    assert dna.shots.wide.min == shonen.shots.wide.min and dna.rhythm == shonen.rhythm
    assert dna.shapes == shonen.shapes and dna.presence == shonen.presence


def test_a_profile_bound_crossing_the_inherited_one_drags_it_along() -> None:
    jeunesse = REG.genre_dna("jeunesse")  # 3 à 5 cases, plans larges au moins 20 %
    assert jeunesse is not None and jeunesse.panels.max_per_page == 5
    dna = apply_tempo(jeunesse, REG.scene_types.types["combat"].tempo)  # type: ignore[union-attr]
    assert (dna.panels.min_per_page, dna.panels.max_per_page) == (6, 6)
    assert dna.shots.wide.min == dna.shots.wide.max == 0.17
    revelation = apply_tempo(REG.genre_dna("shonen"), REG.scene_types.types["revelation"].tempo)  # type: ignore[arg-type, union-attr]
    assert revelation.shapes.big_panel_share.min == revelation.shapes.big_panel_share.max == 1.0


def test_series_adjustment_of_a_profile_wins_and_an_invalid_one_is_refused() -> None:
    settings = REG.scene_types
    project = Project(title="x", scene_tempo={"combat.panels.max_per_page": 7, "combat.unknown.path": 3})
    profile = tempo_profile(settings, project, "combat")
    assert profile["panels.max_per_page"] == 7 and "unknown.path" not in profile
    assert tempo_profile(settings, project, "calme") == settings.types["calme"].tempo  # type: ignore[union-attr]
    with pytest.raises(DnaError):
        apply_tempo(REG.genre_dna("shonen"), {"panels.min_per_page": 12})  # type: ignore[arg-type]


def test_series_tempo_is_adjusted_in_the_dna_screen(c: TestClient) -> None:
    ch = _chapter(c)
    pid = ch["project_id"]
    dna = _ok(c.get(f"/projects/{pid}/pre-direction"))
    assert dna["groups"]["tempo.combat"] == "Tempo — Combat"
    fields = {f["path"]: f for f in dna["fields"]}
    assert fields["tempo.combat.panels.max_per_page"]["group"] == "tempo.combat"
    assert dna["inherited"]["tempo.combat.panels.max_per_page"] == 6
    out = _ok(c.put(f"/projects/{pid}/pre-direction", json={"overrides": {"tempo.combat.panels.max_per_page": 7}}))
    assert out["overrides"] == {"tempo.combat.panels.max_per_page": 7}
    assert out["effective"]["tempo.combat.panels.max_per_page"] == 7
    scenes = _ok(c.get(f"/chapters/{ch['id']}/scenes"))
    assert "6 à 7 cases par planche" in next(t["tempo"] for t in scenes["types"] if t["id"] == "combat")
    bad = c.put(f"/projects/{pid}/pre-direction", json={"overrides": {"tempo.combat.panels.min_per_page": 12}})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "tempo.combat.panels.min_per_page"
    bad = c.put(f"/projects/{pid}/pre-direction", json={"overrides": {"tempo.combat.rhythm.max_peaks_in_a_row": 1}})
    assert bad.status_code == 422 and "valeur inconnue du profil" in bad.text
    # Rien à reprendre du preset : le profil retombe sur ses valeurs.
    out = _ok(c.put(f"/projects/{pid}/pre-direction", json={"overrides": {}}))
    assert out["overrides"] == {} and out["effective"]["tempo.combat.panels.max_per_page"] == 6


# --- validation de la réponse de l'agent ---------------------------------------------------------------------
def _answer(*scenes: tuple[str, int], deferred: list[str] | None = None) -> str:
    import json

    return json.dumps(
        {
            "scenes": [{"summary": f"Scène {i}.", "type": t, "pages": p} for i, (t, p) in enumerate(scenes, 1)],
            "deferred": deferred or [],
        }
    )


def test_parse_refuses_an_out_of_list_type_and_a_wrong_page_sum() -> None:
    settings = REG.scene_types
    assert settings is not None
    out = parse_scenes(_answer(("calme", 3), ("Combat", 5), ("sport collectif", 4)), target=12, settings=settings)
    assert [s.type for s in out.scenes] == ["calme", "combat", "sport_collectif"]
    with pytest.raises(ScenesValidationError, match="type « bagarre » hors liste"):
        parse_scenes(_answer(("calme", 6), ("bagarre", 6)), target=12, settings=settings)
    with pytest.raises(ScenesValidationError, match="somme des pages des scènes vaut 14, elle doit être égale à 12"):
        parse_scenes(_answer(("calme", 6), ("combat", 8)), target=12, settings=settings)
    with pytest.raises(ScenesValidationError, match="vaut 10.*ajoute une scène"):
        parse_scenes(_answer(("calme", 5), ("combat", 5)), target=12, settings=settings)
    with pytest.raises(ScenesValidationError, match="JSON illisible"):
        parse_scenes("Voici les scènes…", target=12, settings=settings)
    assert type_key("Révélation") == "revelation"


# --- agent « Découpage en scènes » (mock) ---------------------------------------------------------------------
def test_mock_proposes_scenes_whose_pages_equal_the_target(c: TestClient) -> None:
    ch = _chapter(c, target=12)
    job = _propose(c, ch["id"])
    assert job["status"] == "succeeded", job
    data = _ok(c.get(f"/chapters/{ch['id']}/scenes"))
    assert data["total_pages"] == data["target_page_count"] == 12
    assert all(s["type"] in SCENE_TYPES for s in data["scenes"])
    assert {s["type"] for s in data["scenes"]} >= {"combat", "poursuite", "revelation"}
    # Ce qui ne rentre pas est reporté, jamais tassé.
    assert data["deferred"] and data["problem"] is None and not data["validated"]
    assert len(data["types"]) == 6 and all(t["tempo"] for t in data["types"])


def test_scene_agent_retries_then_fails_with_a_readable_error(c: TestClient) -> None:
    ch = _chapter(c, synopsis=SYNOPSIS + " [mock:scenes-invalide:2]")
    job = _propose(c, ch["id"])
    assert job["status"] == "succeeded" and "en 3 essais" in job["message"]
    ch = _chapter(c, synopsis=SYNOPSIS + " [mock:scenes-invalide:3]")
    job = _propose(c, ch["id"])
    assert job["status"] == "failed"
    assert "liste de scènes invalide 3 fois de suite" in job["error"]
    assert _ok(c.get(f"/chapters/{ch['id']}/scenes"))["scenes"] == []


def test_scenes_need_a_synopsis(c: TestClient) -> None:
    ch = _chapter(c, synopsis="")
    r = c.post(f"/chapters/{ch['id']}/scenes/propose")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "synopsis"


# --- écran Scènes : retouches et validation ------------------------------------------------------------------
def test_author_edits_merges_and_validates_the_scenes(c: TestClient) -> None:
    ch = _chapter(c, target=12)
    _propose(c, ch["id"])
    data = _ok(c.get(f"/chapters/{ch['id']}/scenes"))
    first, second, *rest = data["scenes"]
    # Fusion des deux premières (la première garde son id), changement de type, ordre inversé du reste.
    merged = {**first, "type": "dialogue", "pages": first["pages"] + second["pages"], "summary": "Fusion."}
    body = {
        "scenes": [
            {k: s[k] for k in ("id", "title", "summary", "type", "pages", "location_id")}
            for s in [merged, *reversed(rest)]
        ],
        "deferred": ["La suite au chapitre 2."],
    }
    out = _ok(c.put(f"/chapters/{ch['id']}/scenes", json=body))
    assert [s["id"] for s in out["scenes"]] == [first["id"], *(s["id"] for s in reversed(rest))]
    assert out["scenes"][0]["type"] == "dialogue" and out["total_pages"] == 12
    assert out["deferred"] == ["La suite au chapitre 2."]
    # Ajout d'une scène : 13 pages pour 12, validation refusée avec un message qui le dit.
    body["scenes"].append({"title": "Bonus", "summary": "Une de plus.", "type": "calme", "pages": 1})
    out = _ok(c.put(f"/chapters/{ch['id']}/scenes", json=body))
    assert out["total_pages"] == 13 and "vaut 13, elle doit être égale à 12" in out["problem"]
    r = c.post(f"/chapters/{ch['id']}/scenes/validate", json={"author": "Ouro"})
    assert r.status_code == 422 and "égale à 12" in r.json()["errors"][0]["message"]
    # Suppression : retour à 12, validation acceptée.
    body["scenes"].pop()
    _ok(c.put(f"/chapters/{ch['id']}/scenes", json=body))
    out = _ok(c.post(f"/chapters/{ch['id']}/scenes/validate", json={"author": "Ouro"}))
    assert out["validated"] and out["validated_by"] == "Ouro" and out["validated_at"]
    assert _stage(c, ch["id"])["complete"]
    # Toute retouche retire la validation.
    out = _ok(c.put(f"/chapters/{ch['id']}/scenes", json=body))
    assert not out["validated"] and not _stage(c, ch["id"])["complete"]


def test_editing_refuses_an_out_of_list_type_and_foreign_ids(c: TestClient) -> None:
    ch = _chapter(c)
    r = c.put(f"/chapters/{ch['id']}/scenes", json={"scenes": [{"summary": "x", "type": "bagarre", "pages": 12}]})
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert err["field"] == "scenes.0.type" and "hors liste" in err["message"]
    r = c.put(f"/chapters/{ch['id']}/scenes", json={"scenes": [{"id": 999, "type": "calme", "pages": 12}]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "scenes.0.id"
    r = c.put(f"/chapters/{ch['id']}/scenes", json={"scenes": [{"type": "calme", "pages": 13}]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "scenes.0.pages"
    r = c.post(f"/chapters/{ch['id']}/scenes/validate")
    assert r.status_code == 422 and "aucune scène" in r.json()["errors"][0]["message"]


# --- garde d'étapes --------------------------------------------------------------------------------------------
def test_script_is_refused_until_scenes_are_validated_with_a_message_naming_the_step(c: TestClient) -> None:
    ch = _chapter(c)
    r = c.post(f"/chapters/{ch['id']}/script")
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert err["field"] == "stage.scenes" and "Scènes non validées" in err["message"]
    assert "onglet Scènes" in err["message"] and "avant d'écrire le scénario" in err["message"]
    stage = _stage(c, ch["id"])
    assert not stage["passed"] and stage["blocks"] == ["écrire le scénario"] and stage["screen"] == "scenes"
    _propose(c, ch["id"])
    r = c.post(f"/chapters/{ch['id']}/script")
    assert r.status_code == 422 and "pas encore validée" in r.json()["errors"][0]["message"]
    _ok(c.post(f"/chapters/{ch['id']}/scenes/validate"))
    assert _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))["status"] == "succeeded"


def test_override_lets_the_script_run_without_scenes(c: TestClient) -> None:
    ch = _chapter(c)
    _ok(c.post(f"/chapters/{ch['id']}/stages/scenes/override", json={"author": "Ouro", "note": "pressé"}))
    assert _stage(c, ch["id"])["forced"]
    job = _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))
    assert job["status"] == "succeeded"
    # Sans liste validée : découpage libre, aucune page rattachée.
    assert all(p["scene_id"] is None for p in _ok(c.get(f"/chapters/{ch['id']}/pages")))


def test_a_chapter_written_without_scenes_is_not_blocked(c: TestClient) -> None:
    ch = _chapter(c)
    _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": pages(PETITE_ILE)}))
    stage = _stage(c, ch["id"])
    assert stage["complete"] and stage["summary"] == "chapitre écrit sans scènes (ancien mode)"
    assert _ok(c.get(f"/chapters/{ch['id']}/scenes"))["legacy"]
    assert _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))["status"] == "succeeded"


# --- scénariste ------------------------------------------------------------------------------------------------
def _validated(c: TestClient, synopsis: str = SYNOPSIS) -> dict[str, Any]:
    ch = _chapter(c, synopsis=synopsis)
    _propose(c, ch["id"])
    _ok(c.post(f"/chapters/{ch['id']}/scenes/validate"))
    return ch


def test_the_writer_gets_the_scene_list_and_attaches_every_page(c: TestClient) -> None:
    ch = _validated(c)
    llm = c.app.state.ctx.providers.llm  # type: ignore[attr-defined]
    job = _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))
    assert job["status"] == "succeeded" and "essais" not in job["message"]
    user = next(m.content for m in llm.calls[-1] if m.role == "user")
    assert "Scènes du chapitre, validées par l'éditeur" in user
    assert re.search(r"scène 2 « [^»]+ » — Combat \(combat\), \d pages \(pages \d+ à \d+\)", user)
    assert "Tempo : 6 cases par planche" in user and "lignes de mouvement imposées" in user
    scenes = _ok(c.get(f"/chapters/{ch['id']}/scenes"))["scenes"]
    story = [p for p in _ok(c.get(f"/chapters/{ch['id']}/pages")) if p["kind"] == "story"]
    assert len(story) == 12 and all(p["scene_id"] is not None for p in story)
    for s in scenes:
        assert len(s["page_numbers"]) == s["pages"]
    assert [p["number"] for s in scenes for p in story if p["scene_id"] == s["id"]] == list(range(1, 13))


def test_wrong_pages_per_scene_are_retried_then_kept_with_a_warning(c: TestClient) -> None:
    ch = _validated(c, SYNOPSIS + " [mock:scenes-pages:1]")
    job = _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))
    assert job["status"] == "succeeded" and "en 2 essais" in job["message"]
    llm = c.app.state.ctx.providers.llm  # type: ignore[attr-defined]
    retry = llm.calls[-1][-1].content
    assert "pages par scène hors de la liste validée" in retry and "au lieu de" in retry

    ch = _validated(c, SYNOPSIS + " [mock:scenes-pages:3]")
    job = _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))
    assert job["status"] == "succeeded" and "avertissement" in job["message"]
    # Gardé quand même (name scène par scène) : chaque page reste à la scène qui l'a écrite, l'écart est mesuré.
    scenes = _ok(c.get(f"/chapters/{ch['id']}/scenes"))["scenes"]
    assert [len(s["page_numbers"]) for s in scenes] == [s["pages"] + 1 for s in scenes]
    measure = _ok(c.get(f"/chapters/{ch['id']}/scenes/measure"))["scenes"]
    assert all(any("écrites pour" in w for w in m["warnings"]) for m in measure)


def test_scene_page_checks_and_assignment() -> None:
    scenes = [
        {"id": 10, "number": 1, "pages": 2, "first_page": 1, "last_page": 2, "type_name": "Calme"},
        {"id": 11, "number": 2, "pages": 1, "first_page": 3, "last_page": 3, "type_name": "Combat"},
    ]
    assert scene_page_problems([1, 1, 2], scenes) == []
    assert scene_page_problems([1, 2, 2], scenes) == [
        "scène 1 (Calme) : 1 page au lieu de 2",
        "scène 2 (Combat) : 2 pages au lieu de 1",
    ]
    assert "sans scène valable" in scene_page_problems([1, None, 2], scenes)[0]
    assert "ordre des scènes" in scene_page_problems([2, 1, 1], scenes)[0]
    assert assign_scenes([1, 1, 2], scenes) == [10, 10, 11]
    assert assign_scenes([2, 1, 1, 1], scenes) == [10, 10, 11, 11]  # par la place, la dernière au-delà
    assert scene_page_problems([None, None], []) == [] and assign_scenes([None], []) == [None]


# --- migration -------------------------------------------------------------------------------------------------
def test_v37_database_keeps_its_chapters_in_the_old_mode(make_settings: Callable[..., Settings]) -> None:
    """v37 → v38 : table des scènes, validation et suite reportée des chapitres, scène des pages, tempo de la série.
    Un chapitre déjà écrit s'ouvre et se génère comme avant ; la base neuve a les mêmes colonnes."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        ch = _chapter(c)
        _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": pages(PETITE_ILE)}))
    con = sqlite3.connect(settings.database_path)
    con.execute("PRAGMA foreign_keys = OFF")
    (ddl,) = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pages'").fetchone()
    lines = [line for line in ddl.splitlines() if "scene_id" not in line and "chapter_scenes" not in line]
    ddl = re.sub(r",\s*\)\s*$", "\n)", "\n".join(lines)).replace("CREATE TABLE pages", "CREATE TABLE pages__old", 1)
    columns = ", ".join(f'"{row[1]}"' for row in con.execute("PRAGMA table_info(pages)") if row[1] != "scene_id")
    con.execute(ddl)
    con.execute(f"INSERT INTO pages__old ({columns}) SELECT {columns} FROM pages")
    con.execute("DROP TABLE pages")
    con.execute("ALTER TABLE pages__old RENAME TO pages")
    con.execute("DROP TABLE chapter_scenes")
    for column in ("scenes_validated_at", "scenes_validated_by", "scenes_deferred"):
        con.execute(f"ALTER TABLE chapters DROP COLUMN {column}")
    con.execute("ALTER TABLE projects DROP COLUMN scene_tempo")
    con.execute("PRAGMA user_version = 37")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        assert len(_ok(c.get(f"/chapters/{ch['id']}/pages"))) == len(pages(PETITE_ILE))
        data = _ok(c.get(f"/chapters/{ch['id']}/scenes"))
        assert data["scenes"] == [] and data["legacy"] and data["deferred"] == []
        assert _stage(c, ch["id"])["complete"]
        assert _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))["status"] == "succeeded"
    assert _version(settings.database_path) == SCHEMA_VERSION == 38
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
