from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.providers.llm import MockLLMProvider


@pytest.fixture
def app_client(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as c:
        yield c


def _series(c: TestClient, **body: Any) -> dict:
    resp = c.post("/projects", json={"title": "Les Lames de Kyoto", **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _chapter(c: TestClient, sid: int, **body: Any) -> dict:
    resp = c.post(f"/projects/{sid}/chapters", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _script(c: TestClient, chapter_id: int) -> dict:
    resp = c.post(f"/chapters/{chapter_id}/script")
    assert resp.status_code == 202, resp.text
    job = resp.json()
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    return c.get(f"/jobs/{job['id']}").json()


# --- séries -------------------------------------------------------------------------
def test_series_status_and_style_lora(app_client: TestClient) -> None:
    s = _series(app_client, style_lora_name="  ", status="paused")
    assert s["status"] == "paused" and s["style_lora_name"] is None and s["style_lora_weight"] == 0.8
    assert s["chapter_count"] == 0
    r = app_client.patch(f"/projects/{s['id']}", json={"status": "completed", "style_lora_name": "ink-v2.safetensors"})
    assert r.status_code == 200
    assert r.json()["status"] == "completed" and r.json()["style_lora_name"] == "ink-v2.safetensors"
    r = app_client.patch(f"/projects/{s['id']}", json={"status": "fini"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "status"


# --- chapitres ------------------------------------------------------------------------
def test_chapter_crud_numbering_and_defaults(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    c1 = _chapter(app_client, sid, title="L'arrivée")
    c2 = _chapter(app_client, sid, title="La pluie", planned_date="2026-10-12")
    assert (c1["number"], c2["number"]) == (1, 2)
    assert c1["target_page_count"] == 15 and c1["status"] == "draft" and c1["planned_date"] is None
    assert c2["planned_date"] == "2026-10-12"
    r = app_client.post(f"/projects/{sid}/chapters", json={"number": 2})
    assert r.status_code == 422 and "existe déjà" in r.json()["errors"][0]["message"]

    r = app_client.patch(f"/chapters/{c1['id']}", json={"status": "published", "synopsis": "  Aiko arrive.  "})
    assert r.json()["status"] == "published" and r.json()["synopsis"] == "Aiko arrive."
    assert app_client.patch(f"/chapters/{c1['id']}", json={"status": "fini"}).status_code == 422
    assert app_client.patch(f"/chapters/{c1['id']}", json={"target_page_count": 0}).status_code == 422
    assert app_client.get(f"/projects/{sid}").json()["chapter_count"] == 2

    assert app_client.delete(f"/chapters/{c1['id']}").status_code == 204
    assert app_client.get(f"/chapters/{c1['id']}").json() == {"detail": "Chapitre introuvable"}
    assert [c["number"] for c in app_client.get(f"/projects/{sid}/chapters").json()] == [2]


def test_reorder_chapters(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    ids = [_chapter(app_client, sid, title=t)["id"] for t in ("A", "B", "C")]
    r = app_client.post(f"/projects/{sid}/chapters/reorder", json={"chapter_ids": [ids[2], ids[0], ids[1]]})
    assert r.status_code == 200
    assert [(c["title"], c["number"]) for c in r.json()] == [("C", 1), ("A", 2), ("B", 3)]
    bad = app_client.post(f"/projects/{sid}/chapters/reorder", json={"chapter_ids": [ids[0], ids[0], ids[1]]})
    assert bad.status_code == 422
    assert app_client.post(f"/projects/{sid}/chapters/reorder", json={"chapter_ids": ids[:2]}).status_code == 422


def test_upcoming_chapters_of_the_week(app_client: TestClient) -> None:
    today = date.today()
    a = _series(app_client, title="A")["id"]
    b = _series(app_client, title="B")["id"]
    _chapter(app_client, a, title="dans 3 jours", planned_date=str(today + timedelta(days=3)))
    _chapter(app_client, b, title="aujourd'hui", planned_date=str(today))
    _chapter(app_client, b, title="dans 7 jours", planned_date=str(today + timedelta(days=7)))
    _chapter(app_client, a, title="dans 8 jours", planned_date=str(today + timedelta(days=8)))
    _chapter(app_client, a, title="hier", planned_date=str(today - timedelta(days=1)))
    _chapter(app_client, a, title="sans date")
    rows = app_client.get("/chapters/upcoming").json()
    assert [r["title"] for r in rows] == ["aujourd'hui", "dans 3 jours", "dans 7 jours"]
    assert rows[0]["series_title"] == "B"


# --- étape 1 : scénario -----------------------------------------------------------------
def test_breakdown_chapter_2_uses_chapter_1_summary(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    app_client.post(f"/projects/{sid}/characters", json={"name": "Aiko", "visual_description": "rônin"})
    c1 = _chapter(app_client, sid, title="L'arrivée", synopsis="Aiko arrive à Kyoto. Elle perd son sabre.")
    c2 = _chapter(app_client, sid, title="La pluie", synopsis="Aiko cherche son sabre.", target_page_count=4)

    job = _script(app_client, c1["id"])
    assert job["status"] == "succeeded", job
    summary1 = app_client.get(f"/chapters/{c1['id']}").json()["summary"]
    assert "Elle perd son sabre" in summary1

    llm: MockLLMProvider = app_client.app.state.ctx.providers.llm  # type: ignore[attr-defined]
    llm.calls.clear()
    job = _script(app_client, c2["id"])
    assert job["status"] == "succeeded" and job["progress"] == 100 and job["error"] is None
    assert job["message"].startswith("4 pages")
    prompt = llm.calls[0][1].content
    assert summary1 in prompt and "Chapitre 1 — L'arrivée" in prompt

    chapter = app_client.get(f"/chapters/{c2['id']}").json()
    assert chapter["status"] == "script" and chapter["page_count"] == 4 and chapter["panel_count"] > 4
    pages = app_client.get(f"/chapters/{c2['id']}/pages").json()
    assert [p["number"] for p in pages] == [1, 2, 3, 4]
    first = pages[0]["panels"][0]
    assert first["description"] and first["shot_type"] and first["dialogues"]
    assert first["dialogues"][0]["kind"] == "narration"
    # mise en page automatique après le découpage
    assert all(p["layout"] and not p["layout_stale"] for p in pages)
    assert all(pa["bbox"] for p in pages for pa in p["panels"])


def test_script_job_events_stream(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel.", target_page_count=2)
    job = _script(app_client, ch["id"])
    with app_client.stream("GET", f"/jobs/{job['id']}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.read().decode()
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert events[-1]["status"] == "succeeded"  # le flux se ferme une fois le job terminé
    assert app_client.get("/jobs/999/events").status_code == 404
    jobs = app_client.get(f"/chapters/{ch['id']}/jobs?step=script").json()
    assert [j["id"] for j in jobs] == [job["id"]]


def test_mock_invalid_twice_then_valid_succeeds(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel. [mock:invalide:2]", target_page_count=2)
    job = _script(app_client, ch["id"])
    assert job["status"] == "succeeded", job
    assert "3 essais" in job["message"]


def test_mock_three_invalid_answers_end_in_visible_error(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(mock_llm_invalid_attempts=3))) as c:
        sid = _series(c)["id"]
        ch = _chapter(c, sid, synopsis="Un duel.")
        job = _script(c, ch["id"])
        assert job["status"] == "failed"
        assert "invalide 3 fois de suite" in job["error"]
        assert job["finished_at"] is not None  # pas de spinner infini
        assert c.get(f"/chapters/{ch['id']}/pages").json() == []
        # un nouvel essai est possible tout de suite
        assert c.post(f"/chapters/{ch['id']}/script").status_code == 202


def test_script_requires_synopsis(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    ch = _chapter(app_client, sid)
    r = app_client.post(f"/chapters/{ch['id']}/script")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "synopsis"


def test_script_with_broken_llm_config_is_503(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(llm_provider="deepseek"))) as c:
        sid = _series(c)["id"]
        ch = _chapter(c, sid, synopsis="x")
        r = c.post(f"/chapters/{ch['id']}/script")
        assert r.status_code == 503 and "DEEPSEEK_API_KEY" in r.json()["detail"]


def test_rerun_keeps_bonus_pages(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel.", target_page_count=2)
    _script(app_client, ch["id"])
    pages = app_client.get(f"/chapters/{ch['id']}/pages").json()
    body = {"pages": [*_as_input(pages), {"kind": "bonus", "panels": []}]}
    assert app_client.put(f"/chapters/{ch['id']}/pages", json=body).status_code == 200
    _script(app_client, ch["id"])
    kinds = [p["kind"] for p in app_client.get(f"/chapters/{ch['id']}/pages").json()]
    assert kinds == ["story", "story", "bonus"]


# --- édition du découpage ------------------------------------------------------------------
def _as_input(pages: list[dict]) -> list[dict]:
    return [
        {
            "id": p["id"],
            "kind": p["kind"],
            "panels": [
                {
                    "id": pa["id"],
                    "description": pa["description"],
                    "characters": pa["characters"],
                    "shot_type": pa["shot_type"],
                    "importance": pa["importance"],
                    "dialogues": [
                        {"speaker": d["speaker"], "text": d["text"], "kind": d["kind"]} for d in pa["dialogues"]
                    ],
                }
                for pa in p["panels"]
            ],
        }
        for p in pages
    ]


def test_edit_breakdown_add_remove_reorder(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    app_client.post(f"/projects/{sid}/characters", json={"name": "Aiko"})
    ch = _chapter(app_client, sid, synopsis="Un duel. Une fuite. Un aveu.", target_page_count=3)
    _script(app_client, ch["id"])
    pages = app_client.get(f"/chapters/{ch['id']}/pages").json()
    body = _as_input(pages)
    p1, p2, p3 = body
    first_panel_id = p1["panels"][0]["id"]
    # page 3 supprimée, pages 1 et 2 inversées, une case retirée, une case ajoutée, dialogues édités
    removed = p1["panels"].pop()
    p1["panels"][0].update(description="Nouvelle description", importance=3, characters=["Aiko", "Inconnu"])
    p1["panels"][0]["dialogues"] = [{"speaker": "Aiko", "text": "Qui va là ?", "kind": "speech"}]
    p1["panels"].append({"description": "Ajoutée", "shot_type": "gros plan", "dialogues": []})
    resp = app_client.put(f"/chapters/{ch['id']}/pages", json={"pages": [p2, p1]})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert [p["id"] for p in out] == [p2["id"], p1["id"]] and [p["number"] for p in out] == [1, 2]
    edited = out[1]["panels"][0]
    assert edited["id"] == first_panel_id and edited["description"] == "Nouvelle description"
    assert edited["characters"] == ["Aiko", "Inconnu"]
    assert edited["dialogues"][0]["text"] == "Qui va là ?" and edited["dialogues"][0]["speaker"] == "Aiko"
    assert out[1]["panels"][-1]["description"] == "Ajoutée"
    assert removed["id"] not in [pa["id"] for p in out for pa in p["panels"]]
    assert [pa["index"] for pa in out[1]["panels"]] == list(range(len(out[1]["panels"])))
    # pages modifiées remises en page automatiquement
    assert all(p["layout"] and not p["layout_stale"] for p in out)
    assert len(out[1]["layout"]["panels"]) == len(out[1]["panels"])
    # personnage connu relié à sa fiche
    ctx_session = app_client.app.state.ctx.db  # type: ignore[attr-defined]
    from mangaka_engine.store.models import Panel

    with ctx_session.session_scope() as s:
        assert len(s.get(Panel, first_panel_id).character_ids) == 1


def test_edit_breakdown_rejects_foreign_ids(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    a = _chapter(app_client, sid, synopsis="A.", target_page_count=1)
    b = _chapter(app_client, sid, synopsis="B.", target_page_count=1)
    _script(app_client, a["id"])
    other = app_client.get(f"/chapters/{a['id']}/pages").json()[0]
    r = app_client.put(f"/chapters/{b['id']}/pages", json={"pages": [{"id": other["id"], "panels": []}]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "pages.0.id"
    r = app_client.put(
        f"/chapters/{b['id']}/pages",
        json={"pages": [{"panels": [{"id": other["panels"][0]["id"], "description": "x"}]}]},
    )
    assert r.status_code == 422


# --- étape 2 : mise en page ------------------------------------------------------------------
def test_layout_endpoints(app_client: TestClient) -> None:
    sid = _series(app_client, reading_direction="ltr")["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel.", target_page_count=2)
    _script(app_client, ch["id"])
    page = app_client.get(f"/chapters/{ch['id']}/pages").json()[0]
    n = len(page["panels"])
    templates = app_client.get("/layout/templates").json()
    same = [t["id"] for t in templates if t["panel_count"] == n]
    other = next(t["id"] for t in templates if t["panel_count"] != n)

    # gabarit imposé
    forced = same[-1]
    r = app_client.post(f"/pages/{page['id']}/layout", json={"template_id": forced})
    assert r.status_code == 200 and r.json()["grid_template"] == forced
    assert r.json()["layout"]["template_id"] == forced and r.json()["layout"]["direction"] == "ltr"
    r = app_client.post(f"/pages/{page['id']}/layout", json={"template_id": other})
    assert r.status_code == 422
    r = app_client.post(f"/pages/{page['id']}/layout", json={"template_id": "nope"})
    assert r.status_code == 422

    # déplacement d'une gouttière
    layout = app_client.post(f"/pages/{page['id']}/layout", json={}).json()["layout"]
    g = layout["gutters"][0]
    r = app_client.post(
        f"/pages/{page['id']}/gutters", json={"path": g["path"], "index": g["index"], "position": g["position"] + 120}
    )
    assert r.status_code == 200, r.text
    moved = r.json()["layout"]
    assert moved["template_id"] == forced
    assert moved["panels"] != layout["panels"]
    r = app_client.post(f"/pages/{page['id']}/gutters", json={"path": [7], "index": 0, "position": 1})
    assert r.status_code == 422

    # changement du format de la série → mise en page obsolète, « Recalculer » la refait
    app_client.patch(f"/projects/{sid}", json={"page_format": "b4-300dpi"})
    pages = app_client.get(f"/chapters/{ch['id']}/pages").json()
    assert all(p["layout_stale"] for p in pages)
    r = app_client.post(f"/pages/{page['id']}/gutters", json={"path": g["path"], "index": g["index"], "position": 1})
    assert r.status_code == 422 and "Recalculer" in r.json()["errors"][0]["message"]
    app_client.patch(f"/projects/{sid}", json={"reading_direction": "rtl"})
    pages = app_client.post(f"/chapters/{ch['id']}/layout").json()
    assert not any(p["layout_stale"] for p in pages)
    assert pages[0]["layout"]["direction"] == "rtl"
    # null = retour au choix automatique
    r = app_client.post(f"/pages/{page['id']}/layout", json={"template_id": None})
    assert r.json()["grid_template"] is None


def _first_row(layout: dict) -> list[dict]:
    """Cases de la première bande (même y1 que la case 1), dans l'ordre de lecture."""
    panels = sorted(layout["panels"], key=lambda p: p["reading_order"])
    top = min(p["y1"] for p in panels)
    return [p for p in panels if p["y1"] == top]


def test_ltr_series_lays_out_left_to_right_end_to_end(app_client: TestClient) -> None:
    """Mock : une série BD donne un script prévenu du sens et des pages lues de gauche à droite."""
    sid = _series(app_client, reading_direction="ltr")["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel sous la pluie.", target_page_count=3)
    llm: MockLLMProvider = app_client.app.state.ctx.providers.llm  # type: ignore[attr-defined]
    llm.calls.clear()
    assert _script(app_client, ch["id"])["status"] == "succeeded"
    assert "de gauche à droite" in llm.calls[0][1].content
    pages = app_client.get(f"/chapters/{ch['id']}/pages").json()
    rows = [_first_row(p["layout"]) for p in pages]
    assert all(p["layout"]["direction"] == "ltr" for p in pages)
    assert any(len(r) > 1 for r in rows)
    for row in rows:
        assert [p["x1"] for p in row] == sorted(p["x1"] for p in row)


def test_switching_rtl_to_ltr_mirrors_existing_layouts(app_client: TestClient) -> None:
    sid = _series(app_client, reading_direction="rtl")["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel.", target_page_count=2)
    _script(app_client, ch["id"])
    page = app_client.get(f"/chapters/{ch['id']}/pages").json()[0]
    # une gouttière déplacée et une bulle placée à la main doivent survivre au changement de sens
    g = next(g for g in page["layout"]["gutters"] if g["orientation"] == "vertical")
    page = app_client.post(
        f"/pages/{page['id']}/gutters", json={"path": g["path"], "index": g["index"], "position": g["position"] - 90}
    ).json()
    panel = page["panels"][0]
    bubble = panel["dialogues"][0]
    box = panel["bbox"]
    pos = {"x": box["x2"] - 260, "y": box["y1"] + 40, "w": 200, "h": 120}  # coin haut droit (début en manga)
    assert app_client.patch(f"/bubbles/{bubble['id']}", json={"position": pos}).status_code == 200
    before = app_client.get(f"/chapters/{ch['id']}/pages").json()
    assert all(p["layout"]["direction"] == "rtl" for p in before)
    for row in (_first_row(p["layout"]) for p in before):
        assert [p["x1"] for p in row] == sorted((p["x1"] for p in row), reverse=True)
    assert app_client.get(f"/projects/{sid}").json()["laid_out_page_count"] == len(before)

    r = app_client.patch(f"/projects/{sid}", json={"reading_direction": "ltr"})
    assert r.status_code == 200 and r.json()["reading_direction"] == "ltr"
    after = app_client.get(f"/chapters/{ch['id']}/pages").json()
    for b, a in zip(before, after, strict=True):
        assert a["layout"]["direction"] == "ltr" and not a["layout_stale"]
        assert a["layout"]["template_id"] == b["layout"]["template_id"]
        assert a["layout"]["tree"] == b["layout"]["tree"]  # gouttière déplacée conservée
        width = a["layout"]["page"]["width"]
        for pb, pa in zip(b["layout"]["panels"], a["layout"]["panels"], strict=True):
            # même case, même ordre de lecture, position en miroir sur la page
            assert pa["reading_order"] == pb["reading_order"] and pa["panel_id"] == pb["panel_id"]
            assert (pa["x1"], pa["x2"]) == (width - pb["x2"], width - pb["x1"])
            assert (pa["y1"], pa["y2"]) == (pb["y1"], pb["y2"])
        row = _first_row(a["layout"])
        assert [p["x1"] for p in row] == sorted(p["x1"] for p in row)
        for pb, pa in zip(b["panels"], a["panels"], strict=True):
            assert pa["bbox"]["x1"] == width - pb["bbox"]["x2"]
    # la bulle placée à la main passe dans le coin haut gauche de sa case
    new_box = after[0]["panels"][0]["bbox"]
    lettering = app_client.get(f"/pages/{after[0]['id']}/lettering").json()
    moved = next(x for x in lettering["bubbles"] if x["id"] == bubble["id"])
    assert moved["manual"] and moved["box"]["x"] == new_box["x1"] + 60 and moved["box"]["y"] == pos["y"]

    # aller-retour : on retombe exactement sur la mise en page d'origine
    app_client.patch(f"/projects/{sid}", json={"reading_direction": "rtl"})
    back = app_client.get(f"/chapters/{ch['id']}/pages").json()
    assert [p["layout"]["panels"] for p in back] == [p["layout"]["panels"] for p in before]


def test_series_page_format_drives_layout(app_client: TestClient) -> None:
    sid = _series(app_client, page_format="b4-300dpi")["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel.", target_page_count=1)
    _script(app_client, ch["id"])
    page = app_client.get(f"/chapters/{ch['id']}/pages").json()[0]
    assert page["layout"]["page"] == {"width": 3035, "height": 4299}


def test_deleting_series_removes_chapters_pages_and_jobs(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel.", target_page_count=1)
    job = _script(app_client, ch["id"])
    assert app_client.delete(f"/projects/{sid}").status_code == 204
    assert app_client.get(f"/chapters/{ch['id']}").status_code == 404
    assert app_client.get(f"/jobs/{job['id']}").status_code == 404


def test_move_panel_between_pages_keeps_its_id(app_client: TestClient) -> None:
    sid = _series(app_client)["id"]
    ch = _chapter(app_client, sid, synopsis="Un duel. Une fuite.", target_page_count=2)
    _script(app_client, ch["id"])
    p1, p2 = _as_input(app_client.get(f"/chapters/{ch['id']}/pages").json())
    moved = p2["panels"].pop(0)
    p1["panels"].insert(0, moved)
    out = app_client.put(f"/chapters/{ch['id']}/pages", json={"pages": [p1, p2]}).json()
    assert out[0]["panels"][0]["id"] == moved["id"]
    assert moved["id"] not in [pa["id"] for pa in out[1]["panels"]]
    # et une page vidée puis supprimée emporte ses cases
    out = app_client.put(f"/chapters/{ch['id']}/pages", json={"pages": [_as_input(out)[0]]}).json()
    assert len(out) == 1
