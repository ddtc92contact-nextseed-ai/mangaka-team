"""Étape 5 par l'API, tout en mock : lettrage, édition des bulles, rendu PNG / SVG, export ZIP."""

from __future__ import annotations

import io
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import httpx
from fastapi.testclient import TestClient
from PIL import Image


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _setup(c: TestClient, *, generate: int = 2) -> dict[str, Any]:
    s = _ok(c.post("/projects", json={"title": "Les Lames", "reading_direction": "rtl"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {
                                "description": "Aiko sur un toit",
                                "characters": ["Aiko"],
                                "dialogues": [
                                    {"speaker": "Aiko", "text": "« Où est passé le cœur de la forêt ? »"},
                                    {"speaker": "Aiko", "text": "Je me demande…", "kind": "thought"},
                                ],
                            },
                            {
                                "description": "Ren crie",
                                "dialogues": [{"speaker": "Ren", "text": "Attention !", "kind": "shout"}],
                            },
                            {"description": "La ville", "dialogues": [{"text": "Le lendemain.", "kind": "narration"}]},
                        ]
                    },
                    {"panels": [{"description": "Sans dialogue"}]},
                ]
            },
        )
    )
    for panel in pages[0]["panels"][:generate]:
        _ok(c.post(f"/panels/{panel['id']}/generate"), 202)
    assert c.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]
    return {"series": s, "chapter": ch, "pages": pages, "page": pages[0]}


def test_lettering_of_a_page_with_missing_panel(client: TestClient) -> None:
    data = _setup(client)
    page = data["page"]
    let = _ok(client.get(f"/pages/{page['id']}/lettering"))
    assert (let["width"], let["height"], let["dpi"]) == (2480, 3508, 300)
    assert let["direction"] == "rtl" and let["bleed_mm"] == 3
    assert [p["image_url"] is not None for p in let["panels"]] == [True, True, False]
    kinds = [b["kind"] for b in let["bubbles"]]
    assert kinds == ["speech", "thought", "shout", "narration"]
    for b in let["bubbles"]:
        assert b["shape"]["path"].startswith("M") and b["lines"] and not b["manual"]
        assert b["font"]["family"].startswith("mk-")
    assert {b["kind"]: b["tail"] is None for b in let["bubbles"]}["narration"]
    codes = [w["code"] for w in let["warnings"]]
    assert codes == ["missing_image"] and "case manquante" in let["warnings"][0]["message"]
    assert set(let["styles"]) == {"speech", "thought", "shout", "narration", "off"}
    font = client.get(let["styles"]["speech"]["url"])
    assert font.status_code == 200 and font.headers["content-type"] == "font/ttf" and len(font.content) > 1000


def test_edit_bubble_move_resize_tail_and_reset(client: TestClient) -> None:
    data = _setup(client)
    page = data["page"]
    let = _ok(client.get(f"/pages/{page['id']}/lettering"))
    bubble = let["bubbles"][0]
    moved = _ok(
        client.patch(
            f"/bubbles/{bubble['id']}",
            json={
                "position": {"x": 300, "y": 400, "w": 500, "h": 300},
                "tail": {"x": 600, "y": 900},
                "text": "Ça va ?",
            },
        )
    )
    b = next(x for x in moved["bubbles"] if x["id"] == bubble["id"])
    assert b["box"] == {"x": 300, "y": 400, "w": 500, "h": 300}
    assert b["tail"] == {"x": 600, "y": 900}
    assert b["manual"] and b["manual_tail"] and b["text"] == "Ça va ?"
    # Le type change la forme et la police ; la position ajustée est conservée.
    shout = _ok(client.patch(f"/bubbles/{bubble['id']}", json={"kind": "shout"}))
    b = next(x for x in shout["bubbles"] if x["id"] == bubble["id"])
    assert b["kind"] == "shout" and b["box"]["x"] == 300 and b["lines"][0]["text"] == "ÇA VA ?"
    # La position survit à un nouvel enregistrement du découpage (même id de bulle).
    pages = _ok(client.get(f"/chapters/{data['chapter']['id']}/pages"))
    body = {
        "pages": [
            {
                "id": pg["id"],
                "kind": pg["kind"],
                "panels": [
                    {
                        "id": p["id"],
                        "description": p["description"],
                        "characters": p["characters"],
                        "importance": p["importance"],
                        "dialogues": p["dialogues"],
                    }
                    for p in pg["panels"]
                ],
            }
            for pg in pages
        ]
    }
    _ok(client.put(f"/chapters/{data['chapter']['id']}/pages", json=body))
    again = _ok(client.get(f"/pages/{page['id']}/lettering"))
    kept = again["bubbles"][0]
    assert kept["manual"] and kept["box"]["x"] == 300
    # « Recalculer le lettrage » rend la main au placement automatique.
    reset = _ok(client.post(f"/pages/{page['id']}/lettering/reset"))
    assert not any(x["manual"] or x["manual_tail"] for x in reset["bubbles"])
    # Validation
    assert client.patch(f"/bubbles/{bubble['id']}", json={"text": ""}).status_code == 422
    assert client.patch(f"/bubbles/{bubble['id']}", json={"kind": "chant"}).status_code == 422
    assert (
        client.patch(f"/bubbles/{bubble['id']}", json={"position": {"x": 0, "y": 0, "w": 5, "h": 5}}).status_code == 422
    )
    assert client.patch("/bubbles/999999", json={"text": "x"}).status_code == 404


def test_long_text_gives_visible_warning(client: TestClient) -> None:
    data = _setup(client)
    let = _ok(client.get(f"/pages/{data['page']['id']}/lettering"))
    bubble = let["bubbles"][0]
    long = "Une réplique interminable qui ne tiendra jamais dans une bulle aussi petite. " * 4
    res = _ok(
        client.patch(
            f"/bubbles/{bubble['id']}", json={"text": long, "position": {"x": 300, "y": 300, "w": 200, "h": 120}}
        )
    )
    b = next(x for x in res["bubbles"] if x["id"] == bubble["id"])
    assert b["overflow"]
    warn = next(w for w in res["warnings"] if w["code"] == "text_overflow")
    assert warn["bubble_id"] == bubble["id"] and "trop long" in warn["message"]


def test_render_page_png_300dpi_and_svg(client: TestClient) -> None:
    data = _setup(client)
    page = data["page"]
    assert client.get(f"/pages/{page['id']}/render").status_code == 404
    info = _ok(client.post(f"/pages/{page['id']}/render", json={"bleed": True}))
    assert (info["width"], info["height"]) == (2551, 3579) and info["bleed"] and not info["crop_marks"]
    png = client.get(info["png_url"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert 'filename="page-001.png"' in png.headers["content-disposition"]
    with Image.open(io.BytesIO(png.content)) as im:
        assert im.size == (2551, 3579)
        assert tuple(round(v) for v in im.info["dpi"]) == (300, 300)
    svg = client.get(info["svg_url"])
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(svg.content)
    texts = "".join("".join(t.itertext()) for t in root.iter("{http://www.w3.org/2000/svg}text"))
    assert "cœur" in texts and "forêt" in texts and "«" in texts
    assert _ok(client.get(f"/pages/{page['id']}/render"))["png_url"] == info["png_url"]
    # Sans fond perdu : format rogné exact.
    plain = _ok(client.post(f"/pages/{page['id']}/render"))
    assert (plain["width"], plain["height"]) == (2480, 3508)


def test_render_refuses_page_without_layout(client: TestClient) -> None:
    data = _setup(client, generate=0)
    empty_page = _ok(client.put(f"/chapters/{data['chapter']['id']}/pages", json={"pages": [{"panels": []}]}))[0]
    res = client.post(f"/pages/{empty_page['id']}/render")
    assert res.status_code == 422 and "sans case" in res.json()["errors"][0]["message"]
    assert client.post("/pages/99999/render").status_code == 404


def test_export_chapter_zip_with_numbered_pages(client: TestClient) -> None:
    data = _setup(client)
    chapter_id = data["chapter"]["id"]
    job = _ok(client.post(f"/chapters/{chapter_id}/export", json={"bleed": True, "crop_marks": True}), 202)
    assert job["step"] == "export" and job["params"] == {"bleed": True, "crop_marks": True}
    client.app.state.ctx.jobs.wait(job["id"], 60)  # type: ignore[attr-defined]
    deadline = time.monotonic() + 5
    while (done := _ok(client.get(f"/jobs/{job['id']}")))["status"] not in ("succeeded", "failed"):
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert done["status"] == "succeeded", done["error"]
    assert done["progress"] == 100 and "2 pages exportées" in done["message"]
    assert done["params"]["pages"] == 2 and done["params"]["warnings"]
    resp = client.get(f"/exports/{job['id']}/file")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
    assert "les-lames-ch001" in resp.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.namelist() == ["page-001.png", "page-001.svg", "page-002.png", "page-002.svg"]
    with Image.open(io.BytesIO(zf.read("page-002.png"))) as im:
        assert im.size == (2764, 3791)  # fond perdu + bande des repères de coupe
    # Le fichier vit dans data/, jamais dans le dépôt.
    files = client.app.state.ctx.files  # type: ignore[attr-defined]
    assert files.absolute(done["params"]["file"]).is_file()
    # Les événements SSE du job d'export fonctionnent comme les autres.
    with client.stream("GET", f"/jobs/{job['id']}/events") as stream:
        body = "".join(stream.iter_text())
    assert "event: job" in body and '"status":"succeeded"' in body


def test_export_refuses_chapter_without_layout(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={"title": "Vide"}), 201)
    ch = _ok(client.post(f"/projects/{s['id']}/chapters", json={}), 201)
    res = client.post(f"/chapters/{ch['id']}/export")
    assert res.status_code == 422
    assert client.get("/exports/99999/file").status_code == 404
