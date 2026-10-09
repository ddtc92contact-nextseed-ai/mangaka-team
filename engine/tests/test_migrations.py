from __future__ import annotations

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


def _drop_v5_tables(con: sqlite3.Connection) -> None:
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
    assert _version(settings.database_path) == SCHEMA_VERSION == 5


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
