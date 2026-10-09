"""API de la mise en page dynamique : style de série, graine, nouvelle mise en page, découpes inclinées."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.store.models import Panel, PanelImage


@pytest.fixture
def app_client(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as c:
        yield c


def _scripted(c: TestClient, **series: Any) -> tuple[dict, list[dict]]:
    project = c.post("/projects", json={"title": "Série nerveuse", **series})
    assert project.status_code == 201, project.text
    sid = project.json()["id"]
    ch = c.post(
        f"/projects/{sid}/chapters",
        json={"synopsis": "Un duel sous la pluie. Le rival frappe.", "target_page_count": 6},
    ).json()
    job = c.post(f"/chapters/{ch['id']}/script").json()
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    assert c.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"
    return project.json(), c.get(f"/chapters/{ch['id']}/pages").json()


def test_series_layout_style_defaults_to_dynamique_and_is_validated(app_client: TestClient) -> None:
    c = app_client
    created = c.post("/projects", json={"title": "Sans style"}).json()
    assert created["layout_style"] == "dynamique"
    bad = c.post("/projects", json={"title": "x", "layout_style": "baroque"})
    assert bad.status_code == 422 and "style de mise en page inconnu" in bad.text
    upd = c.patch(f"/projects/{created['id']}", json={"layout_style": "nerveuse"})
    assert upd.json()["layout_style"] == "nerveuse"
    assert c.patch(f"/projects/{created['id']}", json={"layout_style": None}).status_code == 422
    styles = c.get("/layout/styles").json()
    assert {s["id"] for s in styles} == {"sage", "dynamique", "nerveuse"}
    assert next(s for s in styles if s["is_default"])["id"] == "dynamique"


def test_mock_chapter_in_nerveuse_series_gets_slanted_pages_with_stored_seeds(app_client: TestClient) -> None:
    project, pages = _scripted(app_client, layout_style="nerveuse")
    assert all(p["layout_seed"] is not None and not p["layout_stale"] for p in pages)
    assert any(p["slanted"] for page in pages for p in page["layout"]["panels"])
    assert all(page["layout"]["style"]["id"] == "nerveuse" for page in pages)
    # indices du scénario factice stockés
    assert {p["rythme"] for p in pages} <= {"lent", "normal", "rapide"}
    assert any(pa["intensity"] == "choc" for p in pages for pa in p["panels"])
    # jamais deux pages identiques d'affilée
    templates = [p["layout"]["template_id"] for p in pages]
    assert all(a != b for a, b in zip(templates, templates[1:], strict=False)), templates
    # recalculer garde la graine : même mise en page
    again = app_client.post(f"/pages/{pages[0]['id']}/layout", json={}).json()
    assert again["layout"]["panels"] == pages[0]["layout"]["panels"]


def test_reroll_style_and_template_per_page(app_client: TestClient) -> None:
    c = app_client
    _, pages = _scripted(c, layout_style="dynamique")
    page = pages[1]
    rolled = c.post(f"/pages/{page['id']}/layout", json={"reroll": True}).json()
    assert rolled["layout_seed"] != page["layout_seed"]
    assert rolled["layout"]["template_id"] != page["layout"]["template_id"]
    # style imposé à la page, puis retour au style de la série
    sage = c.post(f"/pages/{page['id']}/layout", json={"style": "sage"}).json()
    assert sage["layout_style"] == "sage" and not any(p["slanted"] for p in sage["layout"]["panels"])
    assert sage["layout"]["style"]["id"] == "sage"
    back = c.post(f"/pages/{page['id']}/layout", json={"style": None}).json()
    assert back["layout_style"] is None and back["layout"]["style"]["id"] == "dynamique"
    assert c.post(f"/pages/{page['id']}/layout", json={"style": "baroque"}).status_code == 422
    # gabarit imposé
    n = len(page["panels"])
    tpl = next(t for t in c.get("/layout/templates").json() if t["panel_count"] == n)
    forced = c.post(f"/pages/{page['id']}/layout", json={"template_id": tpl["id"]}).json()
    assert forced["grid_template"] == tpl["id"] and forced["layout"]["template_id"] == tpl["id"]
    # changer le style de la série rend les pages obsolètes
    c.patch(
        f"/projects/{c.get(f'/chapters/{page["chapter_id"]}').json()['project_id']}", json={"layout_style": "nerveuse"}
    )
    assert all(p["layout_stale"] for p in c.get(f"/chapters/{page['chapter_id']}/pages").json() if p["panels"])


def test_dragging_a_cut_keeps_images_and_flags_big_ratio_changes(app_client: TestClient) -> None:
    c = app_client
    _, pages = _scripted(c, layout_style="sage")
    page = next(p for p in pages if any(g["orientation"] == "vertical" for g in p["layout"]["gutters"]))
    g = next(g for g in page["layout"]["gutters"] if g["orientation"] == "vertical")
    # une image « générée » au ratio de la case de gauche du découpage
    lp = page["layout"]["panels"][0]
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    with ctx.db.session_scope() as s:
        for layout_panel in page["layout"]["panels"]:
            panel = s.get(Panel, layout_panel["panel_id"])
            s.add(PanelImage(panel_id=panel.id, version=1, path="x.png", selected=True,
                             params={"image_width": layout_panel["target"]["width"], "image_height": layout_panel["target"]["height"]}))  # fmt: skip
        s.commit()
    assert not any(
        p["regeneration_advised"]
        for p in c.get(f"/chapters/{page['chapter_id']}/pages").json()[pages.index(page)]["panels"]
    )
    top, bottom = g["ends"]
    small = c.post(
        f"/pages/{page['id']}/cuts", json={"path": g["path"], "index": g["index"], "ends": [top - 40, bottom + 40]}
    )
    assert small.status_code == 200, small.text
    out = small.json()
    ng = next(x for x in out["layout"]["gutters"] if x["path"] == g["path"] and x["index"] == g["index"])
    assert ng["angle_deg"] != 0 and any(p["slanted"] for p in out["layout"]["panels"])
    assert all(p["image_count"] == 1 for p in out["panels"])  # images gardées
    assert not any(p["regeneration_advised"] for p in out["panels"])  # petit biais : simple recadrage
    big = c.post(
        f"/pages/{page['id']}/cuts", json={"path": g["path"], "index": g["index"], "ends": [top - 900, bottom - 900]}
    ).json()
    assert any(p["regeneration_advised"] for p in big["panels"])
    with ctx.db.session_scope() as s:
        assert len(s.scalars(select(PanelImage)).all()) == len(page["panels"])
    bad = c.post(f"/pages/{page['id']}/cuts", json={"path": [9], "index": 0, "ends": [0, 0]})
    assert bad.status_code == 422 and "introuvable" in bad.text
    assert lp["polygon"]


def test_intensity_and_rythme_round_trip_through_breakdown_edit(app_client: TestClient) -> None:
    c = app_client
    _, pages = _scripted(c)
    body = {
        "pages": [
            {
                "id": pages[0]["id"],
                "rythme": "lent",
                "panels": [
                    {
                        "id": pa["id"],
                        "description": pa["description"],
                        "importance": pa["importance"],
                        "intensity": "calme",
                    }
                    for pa in pages[0]["panels"]
                ],
            }
        ]
    }
    out = c.put(f"/chapters/{pages[0]['chapter_id']}/pages", json=body).json()
    assert out[0]["rythme"] == "lent" and {p["intensity"] for p in out[0]["panels"]} == {"calme"}
    assert out[0]["layout"]["style"]["rythme"] == "lent"
    bad = c.put(f"/chapters/{pages[0]['chapter_id']}/pages", json={"pages": [{"rythme": "frénétique", "panels": []}]})
    assert bad.status_code == 422


def test_changing_reading_direction_mirrors_slanted_pages(app_client: TestClient) -> None:
    c = app_client
    project, pages = _scripted(c, layout_style="nerveuse", reading_direction="rtl")
    page = next(p for p in pages if any(lp["slanted"] for lp in p["layout"]["panels"]))
    c.patch(f"/projects/{project['id']}", json={"reading_direction": "ltr"})
    after = next(p for p in c.get(f"/chapters/{page['chapter_id']}/pages").json() if p["id"] == page["id"])
    assert after["layout"]["direction"] == "ltr" and not after["layout_stale"]
    assert after["layout"]["tree"] == page["layout"]["tree"]  # mêmes biais, mêmes proportions
    assert after["layout"]["style"] == page["layout"]["style"]
    assert [lp["slanted"] for lp in after["layout"]["panels"]] == [lp["slanted"] for lp in page["layout"]["panels"]]
