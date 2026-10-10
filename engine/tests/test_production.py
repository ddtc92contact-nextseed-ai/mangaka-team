"""« Générer le chapitre » en un clic (mise en page automatique avant génération, croquis d'abord) et
style de mise en page des séries (défaut « dynamique », remise en page des pages non générées)."""

from __future__ import annotations

import io
import random
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.layout import PanelSpec
from mangaka_engine.pipeline.layout_style import styled_layout
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.store.models import Page, PanelImage
from tests.conftest import PRESETS_DIR, STYLE
from tests.test_generation import _ok, _providers, _wait, make_client  # noqa: F401 — fixture

PRESETS = PresetRegistry.load(PRESETS_DIR)
A4 = PRESETS.page_format("a4-300dpi")


def _series(c: TestClient, **extra: Any) -> dict[str, Any]:
    return _ok(c.post("/projects", json={**STYLE, "title": "Dragons", **extra}), 201)


def _chapter(
    c: TestClient, series_id: int, panels_per_page: tuple[int, ...] = (4, 3, 5, 2), kinds: dict[int, str] | None = None
) -> dict[str, Any]:
    ch = _ok(c.post(f"/projects/{series_id}/chapters", json={"title": "Le nid"}), 201)
    pages = [
        {
            "kind": (kinds or {}).get(n, "story"),
            "panels": [{"description": f"Dragon {n}-{k}"} for k in range(count)],
        }
        for n, count in enumerate(panels_per_page, start=1)
    ]
    _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": pages}))
    return ch


def _pages(c: TestClient, chapter_id: int) -> list[dict[str, Any]]:
    return _ok(c.get(f"/chapters/{chapter_id}/pages"))


def _forget_layout(c: TestClient, page_ids: list[int]) -> None:
    """Pages sans mise en page (découpage arrivé sans géométrie)."""
    with c.app.state.ctx.db.session_scope() as s:  # type: ignore[attr-defined]
        for pid in page_ids:
            s.get(Page, pid).layout = None
        s.commit()


def _fake_image(c: TestClient, panel_id: int) -> None:
    with c.app.state.ctx.db.session_scope() as s:  # type: ignore[attr-defined]
        s.add(PanelImage(panel_id=panel_id, version=1, path="x.png", selected=True, params={}))
        s.commit()


# --- « Générer le chapitre » ---------------------------------------------------------------------
def test_one_click_lays_out_then_sketches_every_panel_of_every_page(
    make_client: Callable[..., TestClient],  # noqa: F811
) -> None:
    c = make_client()
    series = _series(c)
    assert series["sketch_enabled"] is True
    ch = _chapter(c, series["id"])
    pages = _pages(c, ch["id"])
    _forget_layout(c, [pages[1]["id"], pages[3]["id"]])
    every = [pa["id"] for p in pages for pa in p["panels"]]

    plan = _ok(c.get(f"/chapters/{ch['id']}/produce"))
    assert plan == {"mode": "sketch", "panels": 14, "to_clean": 0, "pages": 4, "unlaid_pages": [2, 4], "total": 14}
    assert all(p["layout"] is None for p in _pages(c, ch["id"])[1::2])  # le plan ne modifie rien

    out = _ok(c.post(f"/chapters/{ch['id']}/produce"), 202)
    assert out["mode"] == "sketch" and out["laid_out_pages"] == [2, 4]
    assert out["panel_ids"] == every and out["cleaned_panel_ids"] == [] and out["skipped"] == 0
    assert len(out["jobs"]) == 14 and all(j["params"]["kind"] == "croquis" for j in out["jobs"])
    assert all(p["layout"] is not None for p in _pages(c, ch["id"]))
    _wait(c)
    assert all(pa["sketch_count"] == 1 for p in _pages(c, ch["id"]) for pa in p["panels"])

    # Second clic : croquis présents mais non validés → rien n'est re-croqué tant qu'ils sont en file ;
    # une fois terminés, les cases non validées sont re-croquées, les validées passent au propre.
    first = pages[0]["panels"][0]["id"]
    _ok(c.post(f"/panels/{first}/sketch/validate"))
    again = _ok(c.post(f"/chapters/{ch['id']}/produce"), 202)
    assert again["laid_out_pages"] == [] and again["cleaned_panel_ids"] == [first]
    assert first not in again["panel_ids"] and len(again["panel_ids"]) == 13
    _wait(c)


def test_one_click_without_sketch_tier_generates_final_versions(
    make_client: Callable[..., TestClient],  # noqa: F811
) -> None:
    c = make_client()
    series = _series(c, sketch_enabled=False)
    # Page 3 : bonus (produite) ; page 4 : page de garde (elle se génère depuis sa page).
    ch = _chapter(c, series["id"], kinds={3: "bonus", 4: "chapter_cover"})
    pages = _pages(c, ch["id"])
    _forget_layout(c, [p["id"] for p in pages])

    out = _ok(c.post(f"/chapters/{ch['id']}/produce"), 202)
    assert out["mode"] == "final" and out["laid_out_pages"] == [1, 2, 3]
    assert out["panel_ids"] == [pa["id"] for p in pages[:3] for pa in p["panels"]]
    assert all("kind" not in j["params"] or j["params"]["kind"] != "croquis" for j in out["jobs"])
    _wait(c)
    after = _pages(c, ch["id"])
    assert all(pa["selected_image_id"] is not None for p in after[:3] for pa in p["panels"])
    assert after[3]["layout"] is None
    # Tout est généré : rien à relancer.
    again = _ok(c.post(f"/chapters/{ch['id']}/produce"), 202)
    assert again["panel_ids"] == [] and again["skipped"] == 12


def test_one_click_needs_comfyui_and_changes_nothing_without_it(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(), providers=_providers(None))) as c:
        series = _series(c)
        ch = _chapter(c, series["id"])
        pages = _pages(c, ch["id"])
        _forget_layout(c, [pages[0]["id"]])
        r = c.post(f"/chapters/{ch['id']}/produce")
        assert r.status_code == 503 and r.json()["detail"].startswith("ComfyUI indisponible")
        assert _pages(c, ch["id"])[0]["layout"] is None


# --- style de mise en page ------------------------------------------------------------------------
def test_new_series_default_to_dynamique_and_genres_never_suggest_sage(client: TestClient) -> None:
    for genre in PRESETS.style_genres:
        s = _ok(client.post("/projects", json={**STYLE, "style_genre": genre, "title": genre}), 201)
        assert s["layout_style"] != "sage", genre
        assert s["layout_style_notice"] is False
    assert _series(client)["layout_style"] == "dynamique"  # défaut de la suite de tests (shōnen)
    jeunesse = _ok(client.post("/projects", json={**STYLE, "style_genre": "jeunesse", "title": "J"}), 201)
    assert jeunesse["layout_style"] == PRESETS.defaults.layout_style == "dynamique"  # type: ignore[union-attr]
    genres = {g["id"]: g["layout_style"] for g in _ok(client.get("/presets"))["style_genres"]}
    assert "sage" not in genres.values() and genres["jeunesse"] is None and genres["seinen"] == "nerveuse"
    # « sage » reste un choix explicite.
    assert _series(client, layout_style="sage")["layout_style"] == "sage"


def test_dynamique_pages_of_four_panels_or_more_usually_have_a_slanted_cut() -> None:
    style = PRESETS.layout_style(PRESETS.genre_layout_style(STYLE["style_genre"]) or "")
    assert style.id == "dynamique"
    rng = random.Random(77)
    slanted = 0
    for k in range(20):
        specs = [PanelSpec(importance=2, panel_id=i + 1) for i in range(rng.choice([4, 5, 6]))]
        layout = styled_layout(
            A4,
            PRESETS.layout,
            style,
            list(PRESETS.layout_templates.values()),
            specs,
            direction="rtl",
            page_number=k + 1,
            seed=rng.randrange(10**6),
        )
        slanted += any(abs(g["angle_deg"]) > 0.1 for g in layout["gutters"])
    assert slanted > 10, slanted


def test_rendered_default_page_has_non_rectangular_panels(client: TestClient) -> None:
    """Pages de 4 cases d'une nouvelle série, rendues en PNG (/pages/{id}/render.png) : le trait de bordure
    suit une découpe oblique (encre sur le bord incliné, papier juste à côté, dans la gouttière)."""
    series = _series(client)
    ch = _chapter(client, series["id"], (4, 4, 4, 4, 4, 4))
    pages = _pages(client, ch["id"])
    slanted = [p for p in pages if any(g["angle_deg"] for g in p["layout"]["gutters"])]
    assert slanted and all(p["layout"]["style"]["id"] == "dynamique" for p in pages)
    page = slanted[0]
    _ok(client.post(f"/pages/{page['id']}/render"))
    res = client.get(f"/pages/{page['id']}/render.png")
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(res.content)).convert("L")
    assert image.size == (page["layout"]["page"]["width"], page["layout"]["page"]["height"])

    def darkest(x: float, y: float, r: int = 4) -> int:
        return min(image.getpixel((int(x) + dx, int(y) + dy)) for dx in range(-r, r + 1) for dy in range(-r, r + 1))

    checked = 0
    for lp in page["layout"]["panels"]:
        if not lp["slanted"] or lp.get("frame", "border") != "border" or lp.get("bleed") or lp.get("inset"):
            continue
        poly = [(float(x), float(y)) for x, y in lp["polygon"]]
        cx = sum(x for x, _ in poly) / len(poly)
        cy = sum(y for _, y in poly) / len(poly)
        for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
            if abs(ax - bx) < 1 or abs(ay - by) < 1:
                continue  # bord droit
            mx, my = (ax + bx) / 2, (ay + by) / 2
            assert darkest(mx, my) < 100, (lp["index"], mx, my)  # trait de bordure sur le bord incliné
            # Un peu à l'extérieur du bord (dans la gouttière) : papier blanc.
            nx, ny = mx - cx, my - cy
            norm = (nx * nx + ny * ny) ** 0.5
            gx, gy = mx + nx / norm * 12, my + ny / norm * 12
            assert image.getpixel((int(gx), int(gy))) > 200, (lp["index"], gx, gy)
            checked += 1
    assert checked > 0


def test_changing_style_relays_out_only_pages_without_images(client: TestClient) -> None:
    series = _series(client, layout_style="sage")
    ch = _chapter(client, series["id"])
    before = _pages(client, ch["id"])
    assert not any(pa["slanted"] for p in before for pa in p["layout"]["panels"])
    _fake_image(client, before[0]["panels"][0]["id"])  # page 1 : une case générée

    changed = _ok(client.patch(f"/projects/{series['id']}", json={"layout_style": "nerveuse"}))
    assert changed["relayout_page_count"] == 3 and changed["layout_style_notice"] is False
    # Le changement de style seul ne touche à aucune page.
    assert [p["layout"] for p in _pages(client, ch["id"])] == [p["layout"] for p in before]

    out = _ok(client.post(f"/projects/{series['id']}/relayout"))
    assert out == {"relaid_page_ids": [p["id"] for p in before[1:]], "kept_pages": 1}
    after = _pages(client, ch["id"])
    assert after[0]["layout"] == before[0]["layout"]  # page générée : inchangée
    assert all(p["layout"]["style"]["id"] == "nerveuse" for p in after[1:])
    assert after[1:] != before[1:]
    assert _ok(client.get(f"/projects/{series['id']}"))["relayout_page_count"] == 3
