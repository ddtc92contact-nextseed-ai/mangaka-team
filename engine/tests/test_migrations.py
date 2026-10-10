from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION, MigrationError

V1_SCHEMA = (Path(__file__).parent / "fixtures" / "schema_v1.sql").read_text()
NOW = "2026-10-01 10:00:00.000000"


def _v1_db(path: Path, *, with_pages: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(V1_SCHEMA)
    con.execute(
        "INSERT INTO projects (id, title, style, reading_direction, page_format, workflow_preset, created_at, updated_at)"
        " VALUES (1, 'Ancienne série', 'encre', 'rtl', 'a4-300dpi', 'qwen-image-base', ?, ?)",
        (NOW, NOW),
    )
    con.execute(
        "INSERT INTO characters (id, project_id, name, visual_description, prompt_keywords, lora_name, lora_weight,"
        " created_at, updated_at) VALUES (1, 1, 'Aiko', '', '[]', NULL, 0.8, ?, ?)",
        (NOW, NOW),
    )
    if with_pages:
        con.execute(
            "INSERT INTO pages (id, project_id, number, grid_template, state, created_at, updated_at)"
            " VALUES (7, 1, 1, NULL, 'draft', ?, ?)",
            (NOW, NOW),
        )
        con.execute(
            'INSERT INTO panels (id, page_id, "index", description, character_ids, shot_type, dialogues, importance,'
            " bbox, bubble_zone, final_prompt, generation_preset, qc_score, state, created_at, updated_at)"
            " VALUES (3, 7, 0, 'Une case', '[]', NULL, '[]', 1, NULL, NULL, NULL, NULL, NULL, 'draft', ?, ?)",
            (NOW, NOW),
        )
    con.commit()
    con.close()


def _columns(path: Path) -> dict[str, set[str]]:
    con = sqlite3.connect(path)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out = {t: {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')} for t in tables}
    con.close()
    return out


def _version(path: Path) -> int:
    con = sqlite3.connect(path)
    v = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()
    return v


def _drop_v13_sketch(con: sqlite3.Connection) -> None:
    con.execute("ALTER TABLE panel_images DROP COLUMN kind")
    con.execute("ALTER TABLE panels DROP COLUMN sketch_image_id")
    con.execute("ALTER TABLE panels DROP COLUMN sketch_denoise")
    con.execute("ALTER TABLE projects DROP COLUMN sketch_enabled")
    con.execute("ALTER TABLE projects DROP COLUMN sketch_denoise")


def _drop_v12_references(con: sqlite3.Connection) -> None:
    _drop_v13_sketch(con)
    con.execute("DROP TABLE reference_variants")
    con.execute("ALTER TABLE character_images DROP COLUMN position")
    con.execute("ALTER TABLE series_asset_images DROP COLUMN position")


def _drop_v11_library(con: sqlite3.Connection) -> None:
    _drop_v12_references(con)
    con.execute("ALTER TABLE panels DROP COLUMN decor_id")
    con.execute("ALTER TABLE panels DROP COLUMN object_ids")
    con.execute("DROP TABLE series_asset_images")
    con.execute("DROP TABLE series_assets")


def _drop_v10_columns(con: sqlite3.Connection) -> None:
    _drop_v11_library(con)
    con.execute("ALTER TABLE projects DROP COLUMN style_lora_trigger_words")
    con.execute("ALTER TABLE characters DROP COLUMN lora_trigger_words")


def _drop_v9_columns(con: sqlite3.Connection) -> None:
    _drop_v10_columns(con)
    con.execute("ALTER TABLE panels DROP COLUMN frame")
    con.execute("ALTER TABLE bubbles DROP COLUMN sfx")


def _drop_v8_columns(con: sqlite3.Connection) -> None:
    _drop_v9_columns(con)
    con.execute("ALTER TABLE projects DROP COLUMN layout_style")
    for column in ("layout_seed", "layout_style", "rythme"):
        con.execute(f"ALTER TABLE pages DROP COLUMN {column}")
    con.execute("ALTER TABLE panels DROP COLUMN intensity")


def _drop_v6_tables(con: sqlite3.Connection) -> None:
    _drop_v7_tables(con)
    con.execute("DROP TABLE knowledge_fts")  # (ses triggers partent avec knowledge_chunks)
    for table in ("llm_runs", "series_bibles", "knowledge_chunks", "knowledge_documents", "knowledge_collections"):
        con.execute(f"DROP TABLE {table}")


def _drop_v7_tables(con: sqlite3.Connection) -> None:
    _drop_v8_columns(con)
    con.execute("DROP TABLE agent_profile_versions")
    con.execute("DROP TABLE agent_profiles")


def _drop_v5_tables(con: sqlite3.Connection) -> None:
    _drop_v6_tables(con)
    con.execute("DROP TABLE qc_bench_runs")
    con.execute("DROP TABLE panel_image_annotations")


def test_fresh_database_is_created_at_latest_version(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    create_db_engine(db).dispose()
    assert _version(db) == SCHEMA_VERSION


def test_v1_database_is_migrated(tmp_path: Path, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path)
    with TestClient(create_app(settings)) as c:
        [series] = c.get("/projects").json()
        assert series["title"] == "Ancienne série" and series["status"] == "ongoing"
        assert series["style_lora_name"] is None and series["chapter_count"] == 0
        assert c.get("/projects/1/chapters").json() == []  # une série sans chapitre
        assert [ch["name"] for ch in c.get("/projects/1/characters").json()] == ["Aiko"]
        # le nouveau schéma fonctionne : chapitre + découpage
        ch = c.post("/projects/1/chapters", json={"synopsis": "Un duel.", "target_page_count": 1}).json()
        job = c.post(f"/chapters/{ch['id']}/script").json()
        c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
        assert c.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"
    assert _version(settings.database_path) == SCHEMA_VERSION

    fresh = tmp_path / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)


def test_legacy_pages_are_grouped_in_an_imported_chapter(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path, with_pages=True)
    with TestClient(create_app(settings)) as c:
        [chapter] = c.get("/projects/1/chapters").json()
        assert chapter["number"] == 1 and chapter["title"] == "Pages importées"
        [page] = c.get(f"/chapters/{chapter['id']}/pages").json()
        assert page["id"] == 7 and page["kind"] == "story" and page["panels"][0]["description"] == "Une case"
        assert c.delete("/projects/1").status_code == 204  # les cascades suivent la table reconstruite
        con = sqlite3.connect(settings.database_path)
        assert con.execute("SELECT count(*) FROM panels").fetchone()[0] == 0
        con.close()


def test_migration_is_idempotent(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path)
    create_db_engine(settings.database_path).dispose()
    create_db_engine(settings.database_path).dispose()
    assert _version(settings.database_path) == SCHEMA_VERSION


def test_newer_database_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "future.db"
    create_db_engine(db).dispose()
    con = sqlite3.connect(db)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    con.close()
    with pytest.raises(MigrationError, match="plus récente"):
        create_db_engine(db)


def test_v2_database_gets_generation_columns(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path, with_pages=True)
    create_db_engine(settings.database_path).dispose()
    # retour à un schéma v2 (avant la génération), avec un job existant
    con = sqlite3.connect(settings.database_path)
    _drop_v5_tables(con)
    con.execute("ALTER TABLE jobs DROP COLUMN params")
    con.execute("ALTER TABLE panels DROP COLUMN final_prompt_manual")
    for column in ("qc_verdict", "qc_details", "detections"):
        con.execute(f"ALTER TABLE panel_images DROP COLUMN {column}")
    con.execute(
        "INSERT INTO jobs (id, step, status, progress, message, created_at) VALUES (5, 'script', 'succeeded', 100, '', ?)",
        (NOW,),
    )
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        assert c.get("/jobs/5").json()["params"] == {}
        panel = c.get("/panels/3").json()
        assert panel["final_prompt_manual"] is False and panel["images"] == []
    assert _version(settings.database_path) == SCHEMA_VERSION


def test_v3_database_gets_qc_columns(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path, with_pages=True)
    create_db_engine(settings.database_path).dispose()
    # retour à un schéma v3 (avant le contrôle qualité), avec une version d'image existante
    con = sqlite3.connect(settings.database_path)
    _drop_v5_tables(con)
    for column in ("qc_verdict", "qc_details", "detections"):
        con.execute(f"ALTER TABLE panel_images DROP COLUMN {column}")
    con.execute(
        "INSERT INTO panel_images (id, panel_id, version, path, params, qc_reasons, selected, created_at)"
        " VALUES (1, 3, 1, 'x.png', '{}', '[]', 1, ?)",
        (NOW,),
    )
    con.execute("PRAGMA user_version = 3")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        img = c.get("/panels/3").json()["images"][0]
        assert img["qc_verdict"] is None and img["qc"] == {} and img["detections"] is None
    assert _version(settings.database_path) == SCHEMA_VERSION


def test_v4_database_gets_bench_tables(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path, with_pages=True)
    create_db_engine(settings.database_path).dispose()
    # retour à un schéma v4 (avant le banc d'essai du QC), avec une version d'image contrôlée
    con = sqlite3.connect(settings.database_path)
    _drop_v5_tables(con)
    con.execute(
        "INSERT INTO panel_images (id, panel_id, version, path, params, qc_reasons, qc_verdict, qc_details, selected,"
        " created_at) VALUES (1, 3, 1, 'x.png', '{}', '[]', 'ok', '{}', 1, ?)",
        (NOW,),
    )
    con.execute("PRAGMA user_version = 4")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        img = c.get("/panels/3").json()["images"][0]
        assert img["qc_verdict"] == "ok" and img["annotation"] is None
        ann = c.put("/panel-images/1/annotation", json={"label": "bad", "defects": ["hands"]}).json()
        assert ann["label"] == "bad" and ann["defects"] == ["hands"]
        assert c.get("/qc/bench/runs").json() == []
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)


def test_v5_database_gets_knowledge_tables(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path)
    create_db_engine(settings.database_path).dispose()
    con = sqlite3.connect(settings.database_path)
    _drop_v6_tables(con)
    con.execute("PRAGMA user_version = 5")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        col = c.post("/knowledge/collections", json={"name": "Rythme"}).json()
        doc = c.post(
            f"/knowledge/collections/{col['id']}/documents",
            json={"title": "Fiche", "content": "# Cliffhanger\nFinir fort."},
        ).json()
        assert doc["chunks"] and c.get("/projects/1/bible").json()["world"] == ""
        hits = c.post("/knowledge/search", json={"query": "cliffhanger", "collection_ids": [col["id"]]}).json()
        assert hits["passages"][0]["document_title"] == "Fiche"
        assert c.delete("/projects/1").status_code == 204
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)


def test_v6_database_gets_agent_profile_tables(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    _v1_db(settings.database_path, with_pages=True)
    create_db_engine(settings.database_path).dispose()
    # retour à un schéma v6 (savoir-faire, avant les profils d'agents)
    con = sqlite3.connect(settings.database_path)
    _drop_v7_tables(con)
    con.execute("PRAGMA user_version = 6")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        assert c.get("/projects/1/agents").json() == []
        res = c.put("/agents/scenariste/profile", json={"values": {"temperature": 0.3}})
        assert res.status_code == 200, res.text
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)


def test_v7_database_keeps_its_layouts_straight_and_fresh(make_settings: Callable[..., Settings]) -> None:
    """v7 → v8 : la série existante passe en style « sage », ses mises en page restent à jour et identiques."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        project = c.post("/projects", json={"title": "Série v7", "layout_style": "sage"}).json()
        chapter = c.post(f"/projects/{project['id']}/chapters", json={"title": "Un", "synopsis": "x"}).json()
        pages = c.put(
            f"/chapters/{chapter['id']}/pages",
            json={"pages": [{"panels": [{"description": "a", "importance": 3}, {"description": "b"}]}]},
        ).json()
    page_id = pages[0]["id"]
    before = pages[0]["layout"]
    # Retour à un schéma v7 : colonnes v8 retirées, signature à l'ancien format.
    con = sqlite3.connect(settings.database_path)
    raw = json.loads(con.execute("SELECT layout FROM pages WHERE id = ?", (page_id,)).fetchone()[0])
    sig = json.loads(raw["signature"])
    raw["signature"] = json.dumps([*sig[:4], [spec[:3] for spec in sig[4]]], separators=(",", ":"))
    for key in ("style",):
        raw.pop(key, None)
    con.execute("UPDATE pages SET layout = ? WHERE id = ?", (json.dumps(raw), page_id))
    _drop_v8_columns(con)
    con.execute("PRAGMA user_version = 7")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        assert c.get(f"/projects/{project['id']}").json()["layout_style"] == "sage"
        page = c.get(f"/chapters/{chapter['id']}/pages").json()[0]
        assert page["layout_stale"] is False
        assert [p["polygon"] for p in page["layout"]["panels"]] == [p["polygon"] for p in before["panels"]]
        # Recalculer en « sage » redonne les mêmes cases droites.
        again = c.post(f"/pages/{page_id}/layout", json={}).json()["layout"]
        assert [p["polygon"] for p in again["panels"]] == [p["polygon"] for p in before["panels"]]
        assert not any(p["slanted"] for p in again["panels"])
    assert _version(settings.database_path) == SCHEMA_VERSION


def test_v8_database_gets_frame_and_sfx_columns(make_settings: Callable[..., Settings]) -> None:
    """v8 → v9 : options de cadre par case et réglages d'onomatopée ; les mises en page restent à jour."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        project = c.post("/projects", json={"title": "Série v8", "layout_style": "sage"}).json()
        chapter = c.post(f"/projects/{project['id']}/chapters", json={"title": "Un", "synopsis": "x"}).json()
        pages = c.put(
            f"/chapters/{chapter['id']}/pages",
            json={"pages": [{"panels": [{"description": "a", "importance": 3}, {"description": "b"}]}]},
        ).json()
    before = pages[0]["layout"]
    con = sqlite3.connect(settings.database_path)
    _drop_v9_columns(con)
    con.execute("PRAGMA user_version = 8")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        page = c.get(f"/chapters/{chapter['id']}/pages").json()[0]
        assert page["layout_stale"] is False
        assert page["layout"]["panels"] == before["panels"]
        panel = page["panels"][0]
        assert panel["frame"] is None and panel["sfx"] == []
        res = c.put(f"/panels/{panel['id']}/frame", json={"frame": "none"})
        assert res.status_code == 200, res.text
        assert res.json()["layout"]["panels"][0]["frame"] == "none"
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)


def test_v12_database_gets_sketch_columns(make_settings: Callable[..., Settings]) -> None:
    """v12 → v13 : palier croquis. Les versions existantes sont « final », le croquis est activé."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        project = c.post("/projects", json={"title": "Série v12"}).json()
    con = sqlite3.connect(settings.database_path)
    _drop_v13_sketch(con)
    con.execute("PRAGMA user_version = 12")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        got = c.get(f"/projects/{project['id']}").json()
        assert got["sketch_enabled"] is True and got["sketch_denoise"] is None
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
