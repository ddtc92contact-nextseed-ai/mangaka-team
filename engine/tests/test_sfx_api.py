"""Onomatopées et options de cadre par l'API, tout en mock : scénario, lettrage, mise en page, rendu."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastapi.testclient import TestClient

from mangaka_engine.store.models import Bubble, BubbleKind


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _setup(c: TestClient, style: str = "sage") -> dict[str, Any]:
    s = _ok(c.post("/projects", json={"title": "Moto", "reading_direction": "ltr", "layout_style": style}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Départ"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {
                                "description": "La moto démarre en trombe",
                                "importance": 3,
                                "dialogues": [{"speaker": "Aiko", "text": "On y va !"}],
                                "sfx": [{"text": "VROUM !", "intensity": "choc"}],
                            },
                            {"description": "Ren sursaute", "shot_type": "gros plan", "importance": 1},
                            {"description": "La rue"},
                        ]
                    }
                ]
            },
        )
    )
    for panel in pages[0]["panels"]:
        _ok(c.post(f"/panels/{panel['id']}/generate"), 202)
    assert c.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]
    return {"chapter": ch, "page": pages[0]}


def test_breakdown_keeps_sfx_apart_from_dialogues(client: TestClient) -> None:
    data = _setup(client)
    panel = data["page"]["panels"][0]
    assert [d["text"] for d in panel["dialogues"]] == ["On y va !"]
    assert [(x["text"], x["intensity"]) for x in panel["sfx"]] == [("VROUM !", "choc")]
    # la longueur des dialogues (zone de bulles) ignore l'onomatopée
    lp = data["page"]["layout"]["panels"][0]
    assert lp["bubble_zone"] is not None
    # ré-enregistrer le découpage sans « sfx » garde l'onomatopée et ses réglages de lettrage
    let = _ok(client.get(f"/pages/{data['page']['id']}/lettering"))
    sfx_id = let["sfx"][0]["id"]
    _ok(client.patch(f"/bubbles/{sfx_id}", json={"sfx": {"angle": 12, "x": 900, "y": 900}}))
    body = {
        "pages": [
            {
                "id": data["page"]["id"],
                "panels": [
                    {"id": p["id"], "description": p["description"], "importance": p["importance"],
                     "dialogues": [{"id": d["id"], "speaker": d["speaker"], "text": d["text"], "kind": d["kind"]} for d in p["dialogues"]]}
                    for p in data["page"]["panels"]
                ],
            }
        ]
    }  # fmt: skip
    pages = _ok(client.put(f"/chapters/{data['chapter']['id']}/pages", json=body))
    assert [x["text"] for x in pages[0]["panels"][0]["sfx"]] == ["VROUM !"]
    let = _ok(client.get(f"/pages/{data['page']['id']}/lettering"))
    assert let["sfx"][0]["angle"] == 12 and let["sfx"][0]["manual"]
    # avec « sfx » : remplacées (réglages gardés par id)
    body["pages"][0]["panels"][0]["sfx"] = [{"id": let["sfx"][0]["id"], "text": "VRAOUM !"}, {"text": "bip"}]
    pages = _ok(client.put(f"/chapters/{data['chapter']['id']}/pages", json=body))
    assert [x["text"] for x in pages[0]["panels"][0]["sfx"]] == ["VRAOUM !", "bip"]
    let = _ok(client.get(f"/pages/{data['page']['id']}/lettering"))
    assert let["sfx"][0]["angle"] == 12 and let["sfx"][0]["text"] == "VRAOUM !"


def test_add_move_rotate_resize_and_delete_sfx(client: TestClient) -> None:
    data = _setup(client)
    page, panel = data["page"], data["page"]["panels"][1]
    let = _ok(client.post(f"/panels/{panel['id']}/sfx", json={"text": "baïe !", "intensity": "calme"}), 201)
    assert len(let["sfx"]) == 2
    fx = next(x for x in let["sfx"] if x["panel_id"] == panel["id"])
    assert fx["text"] == "baïe !" and fx["lines"][0]["text"].startswith("BAÏE")
    assert fx["font"]["family"].startswith("mk-") and not fx["manual"]
    assert set(let["sfx_fonts"]) >= {"bowlby-one", "titan-one", "lilita-one"}
    font = client.get(let["sfx_fonts"]["bowlby-one"]["url"])
    assert font.status_code == 200 and font.headers["content-type"] == "font/ttf"
    assert client.get("/lettering/sfx-fonts/inconnue.ttf").status_code == 404
    bad = client.patch(f"/bubbles/{fx['id']}", json={"sfx": {"font": "inconnue"}})
    assert bad.status_code == 422, bad.text
    # déplacer, tourner, agrandir : au centre de la case (sa place automatique dépend des images générées)
    box = page["layout"]["panels"][1]
    x, y = (box["x1"] + box["x2"]) / 2 + 0.25, (box["y1"] + box["y2"]) / 2 - 0.25
    let = _ok(
        client.patch(
            f"/bubbles/{fx['id']}", json={"sfx": {"x": x, "y": y, "angle": -25.5, "size_pt": 40, "font": "titan-one"}}
        )
    )
    fx2 = next(f for f in let["sfx"] if f["id"] == fx["id"])
    assert fx2["center"] == {"x": round(x, 1), "y": round(y, 1)} and fx2["manual"]
    assert (
        fx2["angle"] == -25.5
        and fx2["manual_angle"]
        and fx2["font"]["size_pt"] == 40
        and fx2["font"]["id"] == "titan-one"
    )
    assert "rotate(-25.50)" in fx2["transform"]
    # x sans y : refusé ; type de bulle ou queue : refusés
    assert client.patch(f"/bubbles/{fx['id']}", json={"sfx": {"x": 10}}).status_code == 422
    assert client.patch(f"/bubbles/{fx['id']}", json={"kind": "speech"}).status_code == 422
    # un réglage à null revient au calcul automatique
    let = _ok(client.patch(f"/bubbles/{fx['id']}", json={"sfx": {"angle": None}}))
    fx3 = next(f for f in let["sfx"] if f["id"] == fx["id"])
    assert not fx3["manual_angle"] and fx3["manual"]
    # recalculer le lettrage : position, taille, angle oubliés ; police gardée
    let = _ok(client.post(f"/pages/{page['id']}/lettering/reset"))
    fx4 = next(f for f in let["sfx"] if f["id"] == fx["id"])
    assert not fx4["manual"] and not fx4["manual_size"] and fx4["font"]["id"] == "titan-one"
    # rendu : l'onomatopée reste du texte dans le SVG
    info = _ok(client.post(f"/pages/{page['id']}/render", json={"bleed": True, "crop_marks": True}))
    svg = client.get(info["svg_url"]).text
    root = ET.fromstring(svg)
    groups = [g for g in root.iter("{http://www.w3.org/2000/svg}g") if "onomatopee" in (g.get("class") or "")]
    assert len(groups) == 2 and any("BAÏE" in "".join(g.itertext()) for g in groups)
    assert all(g.get("transform", "").startswith("translate(") for g in groups)
    # supprimer : seulement une onomatopée
    let = _ok(client.delete(f"/bubbles/{fx['id']}"))
    assert [f["id"] for f in let["sfx"]] != [fx["id"]] and len(let["sfx"]) == 1
    speech = let["bubbles"][0]["id"]
    assert client.delete(f"/bubbles/{speech}").status_code == 422


def test_image_prompt_never_asks_to_draw_sfx(client: TestClient) -> None:
    data = _setup(client)
    panel = data["page"]["panels"][0]
    detail = _ok(client.post(f"/panels/{panel['id']}/prompt/rebuild"))
    prompt = detail["final_prompt"]
    assert "VROUM" not in prompt.upper()
    assert "sans aucun texte" in prompt
    negative = client.app.state.ctx.presets.image_prompt.forbidden_text_terms  # type: ignore[attr-defined]
    assert "onomatopées" in negative
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        sfx = session.query(Bubble).filter(Bubble.kind == BubbleKind.sfx).all()
        assert [b.text for b in sfx] == ["VROUM !"]


def test_panel_frame_overrides_keep_the_page_fresh(client: TestClient) -> None:
    data = _setup(client, style="sage")
    page = data["page"]
    first, second, third = page["panels"]
    # sage : aucune option tirée
    assert [p["frame"] for p in page["layout"]["panels"]] == ["border"] * 3
    assert "frames" not in page["layout"]
    # sans bord
    out = _ok(client.put(f"/panels/{second['id']}/frame", json={"frame": "fade"}))
    assert out["layout"]["panels"][1]["frame"] == "fade" and not out["layout_stale"]
    assert out["panels"][1]["frame"] == {"frame": "fade", "bleed": None, "inset": None}
    # fond perdu sur la première case (en haut, au bord de la zone utile)
    out = _ok(client.put(f"/panels/{first['id']}/frame", json={"bleed": True}))
    lp = out["layout"]["panels"][0]
    assert lp["bleed"] and lp["y1"] == 0 and lp["live_polygon"] and not out["layout_stale"]
    assert out["layout"]["panels"][1]["frame"] == "fade"  # option précédente gardée
    # lettrage et rendu en tiennent compte
    let = _ok(client.get(f"/pages/{page['id']}/lettering"))
    assert let["panels"][0]["bleed"] and let["panels"][1]["frame"] == "fade"
    b = let["bubbles"][0]["box"]
    assert b["y"] >= out["layout"]["live_area"]["y1"]  # bulle dans la zone utile
    info = _ok(client.post(f"/pages/{page['id']}/render", json={"bleed": True}))
    svg = client.get(info["svg_url"]).text
    assert 'mask="url(#fondu-' in svg
    # incrustation : la case 2 se pose dans la case 1
    out = _ok(client.put(f"/panels/{second['id']}/frame", json={"inset": True}))
    lp = out["layout"]["panels"][1]
    assert lp["inset"] and lp["host_index"] == 0 and len(out["layout"]["gutters"]) == 1
    let = _ok(client.get(f"/pages/{page['id']}/lettering"))
    assert let["panels"][1]["inset"]
    info = _ok(client.post(f"/pages/{page['id']}/render", json={}))
    svg = client.get(info["svg_url"]).text
    assert svg.index('<g id="case-3"') < svg.index('<g id="case-2"')  # dessinée après les autres
    # tout rendre au style
    out = _ok(client.put(f"/panels/{second['id']}/frame", json={}))
    assert not out["layout"]["panels"][1]["inset"] and out["panels"][1]["frame"] is None
    assert client.put("/panels/99999/frame", json={}).status_code == 404
    assert client.put(f"/panels/{third['id']}/frame", json={"frame": "ondulé"}).status_code == 422


def test_bleed_toggle_keeps_hand_slanted_cuts(client: TestClient) -> None:
    data = _setup(client, style="sage")
    page = data["page"]
    g = page["layout"]["gutters"][0]
    tilted = _ok(
        client.post(
            f"/pages/{page['id']}/cuts",
            json={"path": g["path"], "index": g["index"], "ends": [g["ends"][0] - 60, g["ends"][1] + 60]},
        )
    )
    angle = tilted["layout"]["gutters"][0]["angle_deg"]
    assert angle != 0
    out = _ok(client.put(f"/panels/{page['panels'][0]['id']}/frame", json={"bleed": True}))
    assert out["layout"]["gutters"][0]["angle_deg"] == angle and out["layout"]["panels"][0]["bleed"]
