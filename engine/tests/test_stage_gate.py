"""Garde d'étapes (pipeline/stage_gate.py) : état des étapes vitales, refus des actions, « Passer outre » tracé,
migration, et ce qui reste libre (croquis, essais d'une case, atelier de références)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from mangaka_engine.pipeline.stage_gate import STAGES, StageSettings, StageState
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import ChapterStageDecision, GenerationEvent
from tests.conftest import STYLE, png_bytes


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _refused(resp: httpx.Response, field: str) -> str:
    assert resp.status_code == 422, resp.text
    [error] = resp.json()["errors"]
    assert error["field"] == field, error
    assert "Traceback" not in error["message"]
    return error["message"]


def _wait(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]


def _setup(c: TestClient, *, kenji_image: bool = True, empty_panel: bool = False) -> dict[str, Any]:
    """Série, Aiko et Kenji (images de référence), 2 pages / 3 cases dont 2 répliques, mises en page."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames"}), 201)
    for name, image in (("Aiko", True), ("Kenji", kenji_image)):
        ch = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
        if image:
            _ok(c.post(f"/characters/{ch['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    chapter = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{chapter['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {
                                "description": "Aiko sur un toit",
                                "characters": ["Aiko"],
                                "dialogues": [{"speaker": "Aiko", "text": "Il pleut encore."}],
                            },
                            {
                                "description": "" if empty_panel else "Kenji court",
                                "characters": ["Kenji"],
                                "dialogues": [{"speaker": "Kenji", "text": "Attends-moi !", "kind": "shout"}],
                            },
                        ]
                    },
                    {"panels": [{"description": "La ville sous la pluie"}]},
                ]
            },
        )
    )
    assert all(p["layout"] for p in pages)
    return {"series": s, "chapter": chapter, "pages": pages, "panels": [pa for p in pages for pa in p["panels"]]}


def _stages(c: TestClient, chapter_id: int) -> dict[str, dict[str, Any]]:
    return {s["key"]: s for s in _ok(c.get(f"/chapters/{chapter_id}/stages"))["stages"]}


def _apply_direction(c: TestClient, chapter_id: int) -> None:
    job = _ok(c.post(f"/chapters/{chapter_id}/direction", json={}), 202)
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    _ok(c.post(f"/chapters/{chapter_id}/direction/apply", json={}))


def _generate_all(c: TestClient, panels: list[dict[str, Any]]) -> None:
    for panel in panels:
        _ok(c.post(f"/panels/{panel['id']}/generate"), 202)  # essais d'une case : jamais gardés
    _wait(c)


# --- calcul des étapes ---------------------------------------------------------------------------
def test_fresh_chapter_lists_every_stage_with_counts(client: TestClient) -> None:
    data = _setup(client, kenji_image=False)
    out = _ok(client.get(f"/chapters/{data['chapter']['id']}/stages"))
    assert [s["key"] for s in out["stages"]] == list(STAGES)
    st = {s["key"]: s for s in out["stages"]}
    assert st["script"]["complete"] and st["script"]["summary"] == "0 case sans description sur 3"
    assert st["layout"]["complete"] and st["prompts"]["complete"]
    assert not st["direction"]["passed"] and st["direction"]["summary"] == "2 pages en attente sur 2"
    assert st["direction"]["blocks"] == ["générer"] and st["direction"]["screen"] == "direction"
    assert (st["references"]["faults"], st["references"]["total"], st["references"]["examples"]) == (1, 2, ["Kenji"])
    assert st["approved"]["summary"] == "3 cases sans version choisie sur 3"
    assert st["approved"]["blocks"] == ["lettrer", "exporter", "passer le chapitre en « prêt »"]
    assert st["lettering"]["complete"] and st["lettering"]["total"] == 2
    assert all(s["decision"] is None for s in out["stages"])  # rien n'est validé d'avance


def test_stage_summary_and_thresholds() -> None:
    state = StageState("direction", total=5, faults=5)
    assert state.summary() == "5 pages en attente sur 5" and not state.passed
    assert StageState("lettering", total=4, faults=1).summary() == "1 réplique hors de sa case sur 4"
    assert StageState("lettering", total=4, faults=2).summary() == "2 répliques hors de leur case sur 4"
    assert not StageState("script", total=0, faults=0).complete  # rien à générer sans case
    # Seuils (charte de série, à venir) : lus dans les réglages, zéro faute tolérée par défaut.
    settings = StageSettings.from_series({"stage_max_faults": {"approved": 2, "inconnue": 3}})
    assert settings.tolerated("approved") == 2 and settings.tolerated("direction") == 0
    assert StageState("approved", total=9, faults=2, tolerated=settings.tolerated("approved")).complete


# --- refus --------------------------------------------------------------------------------------
def test_generate_chapter_refused_until_direction_is_applied(client: TestClient) -> None:
    data = _setup(client)
    chapter_id = data["chapter"]["id"]
    message = _refused(client.post(f"/chapters/{chapter_id}/generate"), "stage.direction")
    assert message == (
        "Chapitre 1 — Direction artistique non appliquée : 2 pages en attente sur 2 (page 1, page 2). "
        "Applique-la avant de générer, ou passe outre cette étape."
    )
    # « Générer le chapitre » (un clic) : même refus, rien n'est mis en page ni en file.
    _refused(client.post(f"/chapters/{chapter_id}/produce"), "stage.direction")
    assert _ok(client.get("/queue"))["pending"] == []

    _apply_direction(client, chapter_id)
    assert _stages(client, chapter_id)["direction"]["complete"]
    out = _ok(client.post(f"/chapters/{chapter_id}/generate"), 202)
    assert len(out["panel_ids"]) == 3
    _wait(client)
    # Étapes franchies complètes : validation enregistrée (date, auteur), pas déduite.
    decision = _stages(client, chapter_id)["direction"]["decision"]
    assert decision["decision"] == "validated" and decision["at"]


def test_references_and_script_refusals_name_what_is_missing(client: TestClient) -> None:
    data = _setup(client, kenji_image=False, empty_panel=True)
    chapter_id = data["chapter"]["id"]
    message = _refused(client.post(f"/chapters/{chapter_id}/layout"), "stage.script")
    assert message.startswith("Chapitre 1 — Scénario incomplet : 1 case sans description sur 3 (case 2 de la page 1).")
    assert "avant de mettre en page" in message
    _ok(client.patch(f"/panels/{data['panels'][1]['id']}", json={"description": "Kenji court"}))
    _ok(client.post(f"/chapters/{chapter_id}/layout"))
    _apply_direction(client, chapter_id)
    message = _refused(client.post(f"/chapters/{chapter_id}/generate"), "stage.references")
    assert "Références manquantes : 1 fiche sans image (Kenji) sur 2 intervenants" in message
    # Génération d'une page : la garde ne regarde que la page.
    _ok(client.post(f"/pages/{data['pages'][1]['id']}/generate"), 202)
    _refused(client.post(f"/pages/{data['pages'][0]['id']}/generate"), "stage.references")
    _wait(client)


def test_panel_with_empty_prompt_never_reaches_comfyui(client: TestClient) -> None:
    data = _setup(client, empty_panel=True)
    panel = data["panels"][1]
    message = _refused(client.post(f"/panels/{panel['id']}/generate"), "final_prompt")
    assert message.startswith("case 2 de la page 1 : prompt vide et case sans description")
    assert _ok(client.get("/queue"))["pending"] == []
    st = _stages(client, data["chapter"]["id"])["prompts"]
    assert (st["faults"], st["examples"]) == (1, ["case 2 de la page 1"])
    # Un prompt écrit à la main suffit : la case part (essai isolé).
    _ok(client.post(f"/panels/{panel['id']}/generate", json={"prompt_override": "a runner in the rain"}), 202)
    _wait(client)
    assert _stages(client, data["chapter"]["id"])["prompts"]["complete"]


def test_lettering_refused_until_every_panel_has_a_selected_version(client: TestClient) -> None:
    data = _setup(client)
    page = data["pages"][0]
    _generate_all(client, page["panels"][:1])
    message = _refused(client.post(f"/pages/{page['id']}/render"), "stage.approved")
    assert message.startswith("Chapitre 1, page 1 — Cases non approuvées : 1 case sans version choisie sur 2")
    assert "avant de lettrer" in message
    _generate_all(client, page["panels"][1:])
    _ok(client.post(f"/pages/{page['id']}/render"))


def test_export_and_ready_refused_while_a_line_is_out_of_its_panel(client: TestClient) -> None:
    data = _setup(client)
    chapter_id = data["chapter"]["id"]
    _generate_all(client, data["panels"])
    lettering = _ok(client.get(f"/pages/{data['pages'][0]['id']}/lettering"))
    bubble = next(b for b in lettering["bubbles"] if b["panel_id"] == data["panels"][0]["id"])
    other = next(p for p in lettering["panels"] if p["id"] == data["panels"][1]["id"])
    # Réplique de la case 1 tirée au milieu de la case 2.
    box = other["box"]
    far = {"x": (box["x1"] + box["x2"]) // 2, "y": (box["y1"] + box["y2"]) // 2, "w": 200, "h": 120}
    _ok(client.patch(f"/bubbles/{bubble['id']}", json={"position": far}))

    message = _refused(client.post(f"/chapters/{chapter_id}/export", json={}), "stage.lettering")
    assert "Lettrage incomplet : 1 réplique hors de sa case sur 2 (réplique 1 de la case 1 de la page 1)" in message
    _refused(client.patch(f"/chapters/{chapter_id}", json={"status": "ready"}), "stage.lettering")
    _refused(client.patch(f"/chapters/{chapter_id}", json={"status": "published"}), "stage.lettering")
    assert _ok(client.get(f"/chapters/{chapter_id}"))["status"] != "ready"

    _ok(client.post(f"/pages/{data['pages'][0]['id']}/lettering/reset"))
    assert _ok(client.patch(f"/chapters/{chapter_id}", json={"status": "ready"}))["status"] == "ready"
    _ok(client.post(f"/chapters/{chapter_id}/export", json={}), 202)
    assert _stages(client, chapter_id)["lettering"]["decision"]["decision"] == "validated"


# --- passer outre ---------------------------------------------------------------------------------
def test_override_unblocks_only_that_stage_and_is_traced(client: TestClient) -> None:
    data = _setup(client, kenji_image=False)
    chapter_id, project_id = data["chapter"]["id"], data["series"]["id"]
    out = _ok(
        client.post(
            f"/chapters/{chapter_id}/stages/direction/override",
            json={"author": "Ouro", "note": "cadrage du scénario voulu"},
        )
    )
    direction = next(s for s in out["stages"] if s["key"] == "direction")
    assert direction["forced"] and direction["passed"] and not direction["complete"] and direction["blocks"] == []
    assert direction["decision"]["decision"] == "forced" and direction["decision"]["author"] == "Ouro"
    # Les autres étapes bloquent toujours.
    _refused(client.post(f"/chapters/{chapter_id}/generate"), "stage.references")

    # Trace : journal de traçabilité et page Statistiques.
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        [event] = session.scalars(select(GenerationEvent).where(GenerationEvent.action == "stage_override")).all()
        assert event.verdict == "validated"
        assert event.note.startswith("Chapitre 1 · Direction artistique appliquée forcée par Ouro (2 pages en attente")
        rows = session.scalars(select(ChapterStageDecision)).all()
        assert [(r.stage, r.decision, r.author, r.faults, r.total) for r in rows] == [
            ("direction", "forced", "Ouro", 2, 2)
        ]
    [row] = _ok(client.get("/stats", params={"project_id": project_id}))["stage_overrides"]
    assert row["stage_label"] == "Direction artistique appliquée" and row["chapter_number"] == 1
    assert row["author"] == "Ouro" and row["chapter_title"] == "Pluie" and row["note"] == "cadrage du scénario voulu"
    assert _ok(client.get("/stats", params={"project_id": project_id + 1}))["stage_overrides"] == []

    _refused(client.post(f"/chapters/{chapter_id}/stages/direction/override", json={}), "stage")  # déjà forcée
    _refused(client.post(f"/chapters/{chapter_id}/stages/script/override", json={}), "stage")  # déjà réglée
    assert client.post(f"/chapters/{chapter_id}/stages/tout/override", json={}).status_code == 422

    _ok(client.post(f"/chapters/{chapter_id}/stages/references/override", json={"author": "Ouro"}))
    _ok(client.post(f"/chapters/{chapter_id}/generate"), 202)
    _wait(client)
    # Lever le passer-outre : l'étape bloque de nouveau.
    _ok(client.delete(f"/chapters/{chapter_id}/stages/direction/override"))
    assert not _stages(client, chapter_id)["direction"]["passed"]
    _refused(client.post(f"/chapters/{chapter_id}/generate", json={"force": True}), "stage.direction")


# --- ce qui reste libre ---------------------------------------------------------------------------
def test_sketches_single_panels_and_reference_studio_stay_free(client: TestClient) -> None:
    data = _setup(client, kenji_image=False)
    chapter_id = data["chapter"]["id"]
    assert not _stages(client, chapter_id)["direction"]["passed"]
    _ok(client.post(f"/panels/{data['panels'][0]['id']}/sketch", json={}), 202)
    _ok(client.post(f"/chapters/{chapter_id}/sketch"), 202)
    _ok(client.post(f"/panels/{data['panels'][1]['id']}/generate"), 202)
    kenji = next(c for c in _ok(client.get(f"/projects/{data['series']['id']}/characters")) if c["name"] == "Kenji")
    _ok(client.post(f"/characters/{kenji['id']}/reference-variants", json={"sheet": "personnage-portrait"}), 202)
    _wait(client)


# --- migration ------------------------------------------------------------------------------------
def test_fresh_database_has_the_stage_table(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    create_db_engine(db).dispose()
    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 31
        cols = {r[1] for r in con.execute("PRAGMA table_info(chapter_stage_decisions)")}
        assert {"chapter_id", "stage", "decision", "author", "created_at", "faults", "total"} <= cols
    finally:
        con.close()


def test_v30_database_gets_the_stage_table(tmp_path: Path) -> None:
    db = tmp_path / "v30.db"
    create_db_engine(db).dispose()
    con = sqlite3.connect(db)
    con.execute("DROP TABLE chapter_stage_decisions")
    con.execute("PRAGMA user_version = 30")
    con.commit()
    con.close()
    create_db_engine(db).dispose()
    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 31
        assert con.execute("SELECT count(*) FROM chapter_stage_decisions").fetchone()[0] == 0
    finally:
        con.close()
