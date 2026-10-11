"""Recadrage manuel de l'image dans sa case : calcul (bornes, changement de boîte, image trop petite), rendu
assemblé PNG / SVG avec et sans cadrage, API (enregistrer, borner, recentrer, survivre à la mise en page)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.pipeline.assembly import PageArt, PanelArt, canvas_geometry, render_png, render_svg
from mangaka_engine.pipeline.crop import (
    UPSCALE_MAX,
    ZOOM_MAX,
    PanelCrop,
    bounded,
    crop_window,
    image_placement,
    max_zoom,
)
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.lettering import Box, PageLettering
from mangaka_engine.pipeline.render import faces_on_page
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import Gutters, Margins, PageFormat
from tests.conftest import PRESETS_DIR
from tests.test_lettering_api import _setup

SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


# --- calcul ---------------------------------------------------------------------------------
def test_default_crop_is_the_centred_cover() -> None:
    for iw, ih, w, h in ((832, 576, 500, 500), (544, 864, 233, 372), (1000, 1000, 1200, 300)):
        centred = crop_window(iw, ih, w, h)
        assert crop_window(iw, ih, w, h, PanelCrop()) == pytest.approx(centred)
        s0, x0, y0 = image_placement(iw, ih, 10, 20, w, h)
        assert image_placement(iw, ih, 10, 20, w, h, PanelCrop()) == pytest.approx((s0, x0, y0))


def test_zoom_and_move_stay_inside_the_image() -> None:
    # Image 1000 × 500 dans une case carrée 400 × 400 : remplissage = fenêtre 500 × 500.
    assert crop_window(1000, 500, 400, 400, PanelCrop(0.5, 0.5, 2.0)) == pytest.approx((375, 125, 625, 375))
    # Tout à gauche : la fenêtre s'arrête au bord de l'image, jamais de bande vide.
    assert crop_window(1000, 500, 400, 400, PanelCrop(0.0, 0.5, 1.0)) == pytest.approx((0, 0, 500, 500))
    assert crop_window(1000, 500, 400, 400, PanelCrop(1.0, 1.0, 2.0)) == pytest.approx((750, 250, 1000, 500))
    # Dézoom sous le remplissage impossible : ramené à 1 ; zoom au-delà du maximum : ramené à ZOOM_MAX.
    assert crop_window(1000, 500, 400, 400, PanelCrop(0.5, 0.5, 0.3)) == pytest.approx((250, 0, 750, 500))
    x1, _, x2, _ = crop_window(1000, 500, 400, 400, PanelCrop(0.5, 0.5, 99))
    assert x2 - x1 == pytest.approx(500 / ZOOM_MAX)


def test_placement_maps_the_window_onto_the_box() -> None:
    crop = PanelCrop(0.2, 0.7, 1.5)
    x1, y1, x2, y2 = crop_window(800, 600, 300, 200, crop)
    scale, x0, y0 = image_placement(800, 600, 50, 60, 300, 200, crop)
    assert (x0 + x1 * scale, y0 + y1 * scale) == pytest.approx((50, 60))
    assert (x0 + x2 * scale, y0 + y2 * scale) == pytest.approx((350, 260))


def test_crop_survives_a_box_change_bounded() -> None:
    crop = PanelCrop(0.9, 0.5, 1.0)
    # Case large : toute la largeur de l'image est visible, le centre demandé est ramené au milieu.
    assert crop_window(1000, 500, 800, 200, crop) == pytest.approx((0, 125, 1000, 375))
    # Case étroite : le centre demandé (90 %) est tenu tant que la fenêtre reste dans l'image.
    x1, _, x2, _ = crop_window(1000, 500, 100, 400, crop)
    assert ((x1 + x2) / 2) == pytest.approx(900) and x2 == pytest.approx(962.5)
    # Borné sur la nouvelle boîte : le centre stocké devient celui réellement montré.
    assert bounded(crop, 1000, 500, 800, 200) == PanelCrop(0.5, 0.5, 1.0)


def test_max_zoom_is_limited_by_the_image_resolution() -> None:
    # Image de 1000 px dans une case de 500 px : remplissage ×0,5, zoom permis jusqu'à ZOOM_MAX.
    assert max_zoom(1000, 1000, 500, 500) == ZOOM_MAX
    # Image de 1000 px dans une case de 2000 px : ×2 déjà, zoom ≤ UPSCALE_MAX / 2.
    assert max_zoom(1000, 1000, 2000, 2000) == pytest.approx(UPSCALE_MAX / 2)
    # Image trop petite : déjà au maximum en remplissage, aucun zoom.
    assert max_zoom(200, 200, 2000, 2000) == 1.0
    assert bounded(PanelCrop(0.5, 0.5, 3.0), 1000, 1000, 2000, 2000, max_zoom(1000, 1000, 2000, 2000)).zoom == 2.0


def test_stored_crop_is_parsed_defensively() -> None:
    assert PanelCrop.parse(None) is None and PanelCrop.parse("x") is None
    assert PanelCrop.parse({"x": "abc"}) is None and PanelCrop.parse({"x": float("nan")}) is None
    assert PanelCrop.parse({"x": -1, "y": 2, "zoom": 0.1}) == PanelCrop(0.0, 1.0, 1.0)
    assert PanelCrop.parse({"x": 0.25, "y": 0.5, "zoom": 2}) == PanelCrop(0.25, 0.5, 2.0)


def test_faces_follow_the_crop() -> None:
    box = Box(0, 0, 400, 400)
    face = Box(600, 100, 700, 200)  # px d'une image 1000 × 500
    [centred] = faces_on_page([face], (1000, 500), box)
    [right] = faces_on_page([face], (1000, 500), box, PanelCrop(1.0, 0.5, 1.0))
    assert centred.x1 == pytest.approx(280) and right.x1 == pytest.approx(80)
    assert faces_on_page([face], (1000, 500), box, PanelCrop(0.0, 0.5, 1.0)) == []  # hors de la fenêtre


# --- rendu assemblé -------------------------------------------------------------------------
@pytest.fixture(scope="module")
def presets() -> PresetRegistry:
    return PresetRegistry.load(PRESETS_DIR)


def _page(tmp: Path, crop: PanelCrop | None) -> PageArt:
    """Une case carrée et une image deux fois plus large : moitié gauche rouge, moitié droite bleue."""
    img = Image.new("RGB", (400, 200), (220, 30, 30))
    img.paste((30, 30, 220), (200, 0, 400, 200))
    path = tmp / "case.png"
    img.save(path)
    fmt = PageFormat(
        id="test-a6",
        name="A6 (tests)",
        width_mm=105,
        height_mm=148,
        dpi=100,
        bleed_mm=3,
        margins_mm=Margins(top=10, bottom=10, inner=10, outer=10),
        gutters_mm=Gutters(horizontal=4, vertical=3),
    )
    panel = PanelArt(1, 0, Box(50, 50, 250, 250), path, (400, 200), crop=crop)
    return PageArt(number=1, fmt=fmt, panels=[panel], lettering=PageLettering(bubbles=[], sfx=[], warnings=[]))


@pytest.mark.parametrize(
    ("crop", "colour"),
    [(None, None), (PanelCrop(0.0, 0.5, 1.0), (220, 30, 30)), (PanelCrop(1.0, 0.5, 1.0), (30, 30, 220))],
)
def test_png_uses_the_crop(tmp_path: Path, presets: PresetRegistry, crop: PanelCrop | None, colour: Any) -> None:
    fonts = FontBook(presets)
    art = _page(tmp_path, crop)
    canvas = canvas_geometry(art.fmt, presets.lettering)
    png = render_png(art, fonts, presets.lettering, canvas)
    left, right = png.getpixel((80, 150)), png.getpixel((220, 150))
    if crop is None:  # centrée : la frontière rouge / bleu passe au milieu de la case
        assert left == (220, 30, 30) and right == (30, 30, 220)
    else:
        assert left == colour and right == colour


def test_svg_places_the_whole_image_for_a_crop(tmp_path: Path, presets: PresetRegistry) -> None:
    fonts = FontBook(presets)
    for crop, expected in ((None, None), (PanelCrop(0.0, 0.5, 1.0), ("50", "50", "400", "200"))):
        art = _page(tmp_path, crop)
        svg = render_svg(art, fonts, presets.lettering, canvas_geometry(art.fmt, presets.lettering))
        [image] = ET.fromstring(svg).iterfind(".//svg:image", SVG_NS)
        if expected is None:
            assert image.get("preserveAspectRatio") == "xMidYMid slice" and image.get("width") == "200"
        else:
            assert image.get("preserveAspectRatio") == "none"
            assert (image.get("x"), image.get("y"), image.get("width"), image.get("height")) == expected


# --- API ------------------------------------------------------------------------------------
def _panel(c: TestClient, chapter_id: int, panel_id: int) -> dict[str, Any]:
    pages = _ok(c.get(f"/chapters/{chapter_id}/pages"))
    return next(p for page in pages for p in page["panels"] if p["id"] == panel_id)


def test_api_crop_save_bound_reset_and_survive_layout(client: TestClient) -> None:
    data = _setup(client)
    page, chapter = data["page"], data["chapter"]
    panel = page["panels"][0]
    before = _panel(client, chapter["id"], panel["id"])
    assert before["crop"] is None and before["crop_max_zoom"] >= 1
    let = _ok(client.get(f"/pages/{page['id']}/lettering"))
    centred = let["panels"][0]["image_rect"]

    out = _ok(client.put(f"/panels/{panel['id']}/crop", json={"x": 0.0, "y": 0.0, "zoom": 1.5}))
    saved = next(p for p in out["panels"] if p["id"] == panel["id"])["crop"]
    # Borné : la fenêtre reste dans l'image (le centre stocké est celui réellement montré).
    assert (
        0 < saved["x"] < 0.5
        and 0 < saved["y"] < 0.5
        and saved["zoom"] == pytest.approx(min(1.5, before["crop_max_zoom"]))
    )
    let = _ok(client.get(f"/pages/{page['id']}/lettering"))
    lp = let["panels"][0]
    rect, box = lp["image_rect"], lp["box"]
    assert rect != centred and lp["image_kind"] == "final"
    # Coin haut-gauche de l'image sur le coin haut-gauche de la case ; l'image déborde à droite et en bas.
    assert abs(rect["x1"] - box["x1"]) <= 1 and abs(rect["y1"] - box["y1"]) <= 1
    assert rect["x2"] > box["x2"] and rect["y2"] > box["y2"]

    # Hors bornes : refusé (pas de dézoom sous le remplissage).
    assert client.put(f"/panels/{panel['id']}/crop", json={"x": 0.5, "y": 0.5, "zoom": 0.5}).status_code == 422
    # Nouvelle mise en page : le cadrage est gardé, recalculé sur la nouvelle boîte.
    _ok(client.post(f"/pages/{page['id']}/layout", json={"reroll": True}))
    assert _panel(client, chapter["id"], panel["id"])["crop"] == saved
    lp = _ok(client.get(f"/pages/{page['id']}/lettering"))["panels"][0]
    assert lp["image_rect"]["x1"] <= lp["box"]["x1"] + 1 and lp["image_rect"]["x2"] >= lp["box"]["x2"] - 1
    assert lp["image_rect"]["y1"] <= lp["box"]["y1"] + 1 and lp["image_rect"]["y2"] >= lp["box"]["y2"] - 1

    # Recentrer : retour au centrage automatique.
    out = _ok(client.delete(f"/panels/{panel['id']}/crop"))
    assert next(p for p in out["panels"] if p["id"] == panel["id"])["crop"] is None


def test_api_crop_needs_an_image(client: TestClient) -> None:
    data = _setup(client)
    empty = data["page"]["panels"][2]  # case sans version
    resp = client.put(f"/panels/{empty['id']}/crop", json={"x": 0.5, "y": 0.5, "zoom": 1})
    assert resp.status_code == 422 and "aucune image" in resp.text
