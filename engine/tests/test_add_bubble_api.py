"""Bulle de dialogue ajoutée (et supprimée) depuis l'écran Lettrage, tout en mock (#238)."""

from __future__ import annotations

import io
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.store.models import Bubble
from tests.conftest import force_stages
from tests.test_lettering_api import _ok, _setup


def _panel_bubbles(let: dict[str, Any], panel_id: int) -> list[dict[str, Any]]:
    return [b for b in let["bubbles"] if b["panel_id"] == panel_id]


def _scenario_panel(c: TestClient, chapter_id: int, panel_id: int) -> dict[str, Any]:
    pages = _ok(c.get(f"/chapters/{chapter_id}/pages"))
    return next(p for page in pages for p in page["panels"] if p["id"] == panel_id)


def test_add_bubble_with_and_without_speaker_and_frame(client: TestClient) -> None:
    data = _setup(client)
    _ok(client.post(f"/projects/{data['series']['id']}/characters", json={"name": "Aiko"}), 201)
    page, panel = data["page"], data["page"]["panels"][0]
    _ok(client.post(f"/panels/{panel['id']}/sfx", json={"text": "PLOC"}), 201)
    before = {b["id"]: b for b in _ok(client.get(f"/pages/{page['id']}/lettering"))["bubbles"]}

    # avec locuteur, sans cadre : placement automatique, queue vers le personnage
    let = _ok(
        client.post(f"/panels/{panel['id']}/bubbles", json={"text": "  Là-haut, regarde !  ", "speaker": "Aiko"}), 201
    )
    mine = _panel_bubbles(let, panel["id"])
    assert [b["text"] for b in mine] == [
        "« Où est passé le cœur de la forêt ? »",
        "Je me demande…",
        "Là-haut, regarde !",
    ]
    added = mine[-1]
    assert added["kind"] == "speech" and added["speaker"] == "Aiko" and added["tail"] is not None
    assert not added["manual"] and added["font"]["family"].startswith("mk-")
    # sans locuteur, avec cadre : posé à la main (borné à la page), sans queue
    box = {"x": -5000, "y": 400, "w": 600, "h": 300}
    let = _ok(
        client.post(f"/panels/{panel['id']}/bubbles", json={"text": "Silence…", "kind": "narration", "position": box}),
        201,
    )
    mask = _panel_bubbles(let, panel["id"])[-1]
    assert mask["text"] == "Silence…" and mask["speaker"] == "" and mask["tail"] is None and mask["manual"]
    assert mask["box"]["x"] == -590 and mask["box"]["y"] == 400
    let = _ok(
        client.post(
            f"/panels/{panel['id']}/bubbles",
            json={"text": "Chut.", "position": {"x": 300, "y": 300, "w": 400, "h": 200}},
        ),
        201,
    )
    quiet = _panel_bubbles(let, panel["id"])[-1]
    assert quiet["kind"] == "speech" and quiet["tail"] is None  # parole sans locuteur : pas de queue
    # les bulles des autres cases n'ont pas bougé
    for b in let["bubbles"]:
        if b["id"] in before and b["panel_id"] != panel["id"]:
            assert b["box"] == before[b["id"]]["box"] and b["tail"] == before[b["id"]]["tail"]

    # ordre : après les répliques, l'onomatopée reste dernière ; locuteur relié à sa fiche
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        rows = session.query(Bubble).filter(Bubble.panel_id == panel["id"]).order_by(Bubble.order).all()
        assert [(r.order, r.text) for r in rows][-4:] == [
            (2, "Là-haut, regarde !"),
            (3, "Silence…"),
            (4, "Chut."),
            (5, "PLOC"),
        ]
        assert rows[2].speaker_id is not None and rows[3].speaker_id is None

    # une réplique comme les autres : visible au Scénario
    sc = _scenario_panel(client, data["chapter"]["id"], panel["id"])
    assert [d["text"] for d in sc["dialogues"]][-3:] == ["Là-haut, regarde !", "Silence…", "Chut."]
    assert [x["text"] for x in sc["sfx"]] == ["PLOC"]

    # rendu PNG avec la nouvelle bulle
    force_stages(client, data["chapter"]["id"])
    rendered = _ok(client.post(f"/pages/{page['id']}/render", json={}))
    png = client.get(rendered["png_url"])
    assert png.status_code == 200 and Image.open(io.BytesIO(png.content)).size == (2480, 3508)
    svg = client.get(rendered["svg_url"]).text
    assert "Silence…" in svg and "Là-haut, regarde !" in svg


def test_add_bubble_refusals_in_french(client: TestClient) -> None:
    data = _setup(client)
    panel = data["page"]["panels"][0]
    for body, field in (
        ({"text": "   "}, "text"),
        ({}, "text"),
        ({"text": "BAM", "kind": "sfx"}, "kind"),
        ({"text": "Oh", "kind": "chant"}, "kind"),
        ({"text": "Oh", "position": {"x": 0, "y": 0, "w": 5, "h": 5}}, "position"),
    ):
        res = client.post(f"/panels/{panel['id']}/bubbles", json=body)
        assert res.status_code == 422, (body, res.text)
        errors = res.json()["errors"]
        assert any(e["field"].startswith(field) for e in errors), errors
    res = client.post(f"/panels/{panel['id']}/bubbles", json={"text": "BAM", "kind": "sfx"})
    assert "onomatopée" in res.json()["errors"][0]["message"]
    res = client.post(f"/panels/{panel['id']}/bubbles", json={"text": ""})
    assert "vide" in res.json()["errors"][0]["message"]
    res = client.post("/panels/999999/bubbles", json={"text": "Oh"})
    assert res.status_code == 404 and res.json()["detail"] == "Case introuvable"


def test_added_bubble_survives_scenario_save_reset_and_delete(client: TestClient) -> None:
    data = _setup(client)
    page, panel = data["page"], data["page"]["panels"][1]
    box = {"x": 1500, "y": 500, "w": 500, "h": 260}
    let = _ok(client.post(f"/panels/{panel['id']}/bubbles", json={"text": "Cache-misère", "position": box}), 201)
    added = _panel_bubbles(let, panel["id"])[-1]
    _ok(client.post(f"/panels/{panel['id']}/bubbles", json={"text": "Et après ?", "speaker": "Ren"}), 201)

    # ré-enregistrer le Scénario (dialogues renvoyés par id) garde la bulle, son cadre et l'absence de queue
    body = {
        "pages": [
            {
                "id": p["id"],
                "panels": [
                    {"id": pa["id"], "description": pa["description"],
                     "dialogues": [{"id": d["id"], "speaker": d["speaker"], "text": d["text"], "kind": d["kind"]} for d in pa["dialogues"]]}
                    for pa in _ok(client.get(f"/chapters/{data['chapter']['id']}/pages"))[i]["panels"]
                ],
            }
            for i, p in enumerate(data["pages"])
        ]
    }  # fmt: skip
    pages = _ok(client.put(f"/chapters/{data['chapter']['id']}/pages", json=body))
    sc = next(p for p in pages[0]["panels"] if p["id"] == panel["id"])
    assert [d["text"] for d in sc["dialogues"]] == ["Attention !", "Cache-misère", "Et après ?"]
    let = _ok(client.get(f"/pages/{page['id']}/lettering"))
    kept = next(b for b in _panel_bubbles(let, panel["id"]) if b["text"] == "Cache-misère")
    assert kept["manual"] and kept["box"] == added["box"] and kept["tail"] is None

    # « Recalculer le lettrage » : le cadre est oublié, la bulle reste sans queue
    let = _ok(client.post(f"/pages/{page['id']}/lettering/reset"))
    kept = next(b for b in _panel_bubbles(let, panel["id"]) if b["text"] == "Cache-misère")
    assert not kept["manual"] and kept["tail"] is None
    # « Replacer automatiquement » non plus ; un locuteur lui rend sa queue
    let = _ok(client.patch(f"/bubbles/{kept['id']}", json={"position": None, "tail": None}))
    assert next(b for b in let["bubbles"] if b["id"] == kept["id"])["tail"] is None
    let = _ok(client.patch(f"/bubbles/{kept['id']}", json={"speaker": "Ren"}))
    assert next(b for b in let["bubbles"] if b["id"] == kept["id"])["tail"] is not None

    # supprimer la réplique : les suivantes se resserrent
    let = _ok(client.delete(f"/bubbles/{kept['id']}/reply"))
    assert [b["text"] for b in _panel_bubbles(let, panel["id"])] == ["Attention !", "Et après ?"]
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        rows = session.query(Bubble).filter(Bubble.panel_id == panel["id"]).order_by(Bubble.order).all()
        assert [(r.order, r.text) for r in rows] == [(0, "Attention !"), (1, "Et après ?")]
