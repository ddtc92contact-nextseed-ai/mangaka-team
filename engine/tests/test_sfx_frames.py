"""Mise en page dynamique v2 : onomatopées (sfx), cases sans bord, fond perdu, incrustations.

Image de référence : `tests/golden/planche-cadres-sfx.png` (A5, 100 DPI) — une onomatopée à cheval sur
une bordure, une case qui se fond au papier, une case sans bord, une case à fond perdu et une
incrustation. Pour la régénérer : `MANGAKA_UPDATE_GOLDEN=1 npm run test:engine` (et le justifier).
"""

from __future__ import annotations

import io
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops

from mangaka_engine.pipeline import geometry as geo
from mangaka_engine.pipeline.assembly import (
    PageArt,
    PanelArt,
    canvas_geometry,
    draw_order,
    panel_polygon,
    render_png,
    render_svg,
)
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.layout import LayoutError, PanelSpec, compute_layout
from mangaka_engine.pipeline.layout_style import decide_frames
from mangaka_engine.pipeline.lettering import Box, BubbleSpec, Letterer, SfxSpec, normalize_text
from mangaka_engine.pipeline.lettering import PanelSpec as LetterSpec
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import SplitNode
from tests.conftest import PRESETS_DIR
from tests.layout_render import COLORS, golden_format, render_layout, synthetic_image

PRESETS = PresetRegistry.load(PRESETS_DIR)
SETTINGS = PRESETS.layout
A4 = PRESETS.page_format("a4-300dpi")
GOLDEN = Path(__file__).parent / "golden" / "planche-cadres-sfx.png"
# Une grande case en haut, deux en bas.
TREE = SplitNode(rows=[1.2, 1.0], children=["panel", SplitNode(cols=[1.0, 1.0])])


@pytest.fixture(scope="module")
def fonts() -> FontBook:
    return FontBook(PRESETS)


@pytest.fixture(scope="module")
def letterer(fonts: FontBook) -> Letterer:
    return Letterer(fonts, PRESETS.lettering, 300)


def _sfx_panel(*sfx: SfxSpec, **kw: Any) -> LetterSpec:
    values: dict[str, Any] = {"id": 1, "index": 0, "box": Box(300, 300, 1500, 1300)}
    values.update(kw)
    return LetterSpec(sfx=list(sfx), **values)


def _limit() -> float:
    return PRESETS.lettering.sfx.max_overflow_mm / 25.4 * 300


# --- onomatopées : géométrie ------------------------------------------------------------------
def test_sfx_rotation_and_skew_follow_the_requested_angles(letterer: Letterer) -> None:
    spec = SfxSpec(id=1, text="VROUM !", angle=20, skew=0, center=(900, 800))
    lay = letterer.letter_page([_sfx_panel(spec)], "ltr").sfx[0]
    (x0, y0), (x1, y1) = lay.quad[0], lay.quad[1]
    assert math.degrees(math.atan2(y1 - y0, x1 - x0)) == pytest.approx(20, abs=0.01)
    assert lay.center == (900, 800) and lay.manual and lay.manual_angle
    # centre du contour = centre demandé ; rectangle (sans cisaillement)
    cx = sum(x for x, _ in lay.quad) / 4
    cy = sum(y for _, y in lay.quad) / 4
    assert (cx, cy) == pytest.approx((900, 800), abs=0.01)
    assert math.dist(lay.quad[0], lay.quad[1]) == pytest.approx(2 * lay.half[0], abs=0.01)

    skewed = letterer.letter_page(
        [_sfx_panel(SfxSpec(id=1, text="VROUM !", angle=0, skew=12, center=(900, 800)))], "ltr"
    )
    q = skewed.sfx[0].quad
    # cisaillement horizontal (skewX) : les bords haut / bas restent horizontaux, les côtés penchent de 12°
    assert q[0][1] == pytest.approx(q[1][1]) and q[2][1] == pytest.approx(q[3][1])
    assert math.degrees(math.atan2(q[3][0] - q[0][0], q[3][1] - q[0][1])) == pytest.approx(12, abs=0.01)
    assert skewed.sfx[0].svg_transform() == "translate(900.0 800.0) rotate(0.00) skewX(12.00)"


def test_auto_angle_skew_and_size_come_from_the_preset(letterer: Letterer) -> None:
    c = PRESETS.lettering.sfx
    small = _sfx_panel(SfxSpec(id=7, text="BAM !", intensity="choc"), box=Box(300, 300, 900, 900))
    big = _sfx_panel(SfxSpec(id=7, text="BAM !", intensity="choc"), box=Box(100, 100, 2300, 2300))
    calm = _sfx_panel(SfxSpec(id=7, text="BAM !", intensity="calme"), box=Box(100, 100, 2300, 2300))
    a, b, d = (letterer.letter_page([p], "ltr").sfx[0] for p in (small, big, calm))
    for lay in (a, b, d):
        assert c.angle_deg.min <= abs(lay.angle) <= c.angle_deg.max
        assert c.skew_deg.min <= abs(lay.skew) <= c.skew_deg.max
        assert c.min_size_pt <= lay.size_pt <= c.max_size_pt
        assert not lay.manual and not lay.manual_angle
    assert b.size_pt > a.size_pt  # taille selon la case
    assert b.size_pt > d.size_pt  # et selon l'intensité
    assert a.angle == b.angle  # graine = l'onomatopée : même tirage, quelle que soit la case
    # déterministe
    again = letterer.letter_page([big], "ltr").sfx[0]
    assert (again.center, again.angle, again.size_pt) == (b.center, b.angle, b.size_pt)


def test_sfx_overflow_is_limited_by_the_preset(letterer: Letterer) -> None:
    panel = _sfx_panel(SfxSpec(id=3, text="CLIC", angle=-10, center=(1490, 1290)), box=Box(300, 300, 1500, 1300))
    lay = letterer.letter_page([panel], "ltr").sfx[0]
    planes = geo.edges(panel.outline())
    # posée sur le coin : elle chevauche la bordure, sans dépasser la limite
    assert 0 < geo.overflow(planes, lay.quad) <= _limit() + 1e-6
    assert lay.overflow_px == pytest.approx(geo.overflow(planes, lay.quad))
    # demandée loin dehors : ramenée vers la case jusqu'à la limite
    far = _sfx_panel(SfxSpec(id=3, text="CLIC", angle=-10, center=(2600, 2600)), box=Box(300, 300, 1500, 1300))
    lay = letterer.letter_page([far], "ltr").sfx[0]
    assert geo.overflow(planes, lay.quad) == pytest.approx(_limit(), abs=1.0)
    # jamais hors de la page
    page = Box(0, 0, 1600, 1400)
    lay = letterer.letter_page([far], "ltr", page).sfx[0]
    assert geo.overflow(geo.edges(geo.rect_polygon(0, 0, 1600, 1400)), lay.quad) <= 1e-6


def test_auto_sfx_avoids_faces_bubbles_and_insets(letterer: Letterer) -> None:
    free = letterer.letter_page([_sfx_panel(SfxSpec(id=5, text="VROUM !", intensity="normal"))], "ltr").sfx[0]
    x1, y1, x2, y2 = geo.bbox(free.quad)
    face = Box(x1, y1, x2, y2)  # un visage exactement là où elle allait
    panel = _sfx_panel(
        SfxSpec(id=5, text="VROUM !", intensity="normal"),
        faces=[face],
        bubbles=[BubbleSpec(id=9, kind="speech", text="Attends-moi !", speaker="Aiko")],
        obstacles=[Box(320, 320, 600, 600)],
    )
    res = letterer.letter_page([panel], "ltr")
    lay = res.sfx[0]
    margin = PRESETS.lettering.sfx.face_margin_mm / 25.4 * 300
    assert not geo.convex_overlap(lay.quad, geo.rect_polygon(*vars(face.expand(margin)).values()))
    bubble = res.bubbles[0].box
    assert not geo.convex_overlap(lay.quad, geo.rect_polygon(bubble.x1, bubble.y1, bubble.x2, bubble.y2))
    assert not geo.convex_overlap(lay.quad, geo.rect_polygon(320, 320, 600, 600))
    assert geo.overflow(geo.edges(panel.outline()), lay.quad) <= _limit() + 1e-6
    assert not [w for w in res.warnings if w.code.startswith("sfx")]
    # deux onomatopées ne se recouvrent pas
    two = _sfx_panel(SfxSpec(id=1, text="BAM !", intensity="choc"), SfxSpec(id=2, text="BOUM !", intensity="choc"))
    a, b = letterer.letter_page([two], "ltr").sfx
    assert not geo.convex_overlap(a.quad, b.quad)


def test_french_accents_in_sfx(letterer: Letterer, fonts: FontBook) -> None:
    assert normalize_text("ça", uppercase=True) == "ÇA"
    panel = _sfx_panel(
        SfxSpec(id=1, text="baïe !", angle=0, skew=0, center=(900, 800)), SfxSpec(id=2, text="ça", intensity="choc")
    )
    res = letterer.letter_page([panel], "ltr")
    baie, ca = res.sfx
    assert baie.lines[0].text in ("BAÏE !", "BAÏE !")  # espace insécable avant « ! » (si la police l'a)
    assert ca.lines[0].text == "ÇA"
    for lay in (baie, ca):
        for ch in lay.lines[0].text.replace("!", "").replace(" ", "").replace(" ", ""):
            assert fonts.has_char(lay.style, ch), (lay.font_id, ch)
    # le contour tient compte du tréma : plus haut que sans accent
    plain = letterer.letter_page([_sfx_panel(SfxSpec(id=1, text="BAIE !", angle=0, skew=0, center=(900, 800)))], "ltr")
    assert baie.half[1] > plain.sfx[0].half[1]

    # PNG : toute l'encre (tréma compris) est dans le contour
    fmt = A4
    art = PageArt(number=1, fmt=fmt, panels=[], lettering=res)
    canvas = canvas_geometry(fmt, PRESETS.lettering)
    img = render_png(art, fonts, PRESETS.lettering, canvas)
    ink = ImageChops.invert(img.convert("L")).point(lambda v: 255 if v > 40 else 0).getbbox()
    assert ink is not None
    x1, y1, x2, y2 = geo.bbox(baie.quad + ca.quad)
    assert x1 - 2 <= ink[0] and y1 - 2 <= ink[1] and ink[2] <= x2 + 2 and ink[3] <= y2 + 2
    # SVG : le texte reste du texte, police réduite embarquée avec Ï et Ç
    svg = render_svg(art, fonts, PRESETS.lettering, canvas)
    root = ET.fromstring(svg)
    ns = {"s": "http://www.w3.org/2000/svg"}
    groups = root.findall(".//s:g[@class]", ns)
    sfx_groups = [g for g in groups if "onomatopee" in g.get("class", "")]
    assert len(sfx_groups) == 2
    texts = ["".join(t.itertext()) for t in sfx_groups[0].findall("s:text", ns)]
    assert texts and all("BAÏE" in t for t in texts)
    style = root.find(".//s:style", ns)
    assert style is not None and style.text
    import base64
    import re

    families = dict(re.findall(r'font-family:"([^"]+)";src:url\(data:font/ttf;base64,([^)]+)\)', style.text))
    cmap = TTFont(io.BytesIO(base64.b64decode(families[baie.family]))).getBestCmap()
    assert ord("Ï") in cmap
    cmap = TTFont(io.BytesIO(base64.b64decode(families[ca.family]))).getBestCmap()
    assert ord("Ç") in cmap


# --- options de cadre : géométrie --------------------------------------------------------------
def _frames(**by_index: dict[str, Any]) -> list[dict[str, Any]]:
    out = [{"frame": "border", "bleed": False, "inset": False} for _ in range(4)]
    for k, v in by_index.items():
        out[int(k[1:])].update(v)
    return out


def _layout(
    frames: list[dict[str, Any]] | None, *, direction: str = "ltr", fmt: Any = A4, page: int = 1
) -> dict[str, Any]:
    specs = [PanelSpec(importance=2, dialogue_chars=30, panel_id=i + 1) for i in range(4)]
    return compute_layout(
        fmt,
        SETTINGS,
        TREE,
        specs,
        direction=direction,
        page_number=page,
        template_id="essai",
        frames=frames,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_bleed_panel_reaches_the_page_and_bleed_edge_exactly(direction: str, fonts: FontBook) -> None:
    frames = _frames(p0={"bleed": True}, p3={"inset": True, "host": 2, "size": 0.4, "margin_mm": 3, "min_side_mm": 12})
    lay = _layout(frames, direction=direction)
    top = lay["panels"][0]
    W = lay["page"]["width"]
    assert top["bleed"] and top["bleed_possible"]
    x1, y1, x2, y2 = geo.bbox([tuple(p) for p in top["polygon"]])
    live = lay["live_area"]
    # haut et côté extérieur (opposé à la reliure) jusqu'au bord de la page ; reliure inchangée
    assert y1 == 0 and top["y1"] == 0
    if lay["inner_side"] == "left":
        assert x2 == W and x1 == live["x1"]
    else:
        assert x1 == 0 and x2 == live["x2"]
    # la gouttière avec les cases du bas ne bouge pas
    assert y2 == geo.bbox([tuple(p) for p in top["live_polygon"]])[3]
    assert top["bubble_zone"]["y1"] >= live["y1"]  # bulles dans la zone utile
    # à l'export avec fond perdu : jusqu'au bord du fond perdu, exactement
    canvas = canvas_geometry(A4, PRESETS.lettering, bleed=True, crop_marks=True)
    art = PanelArt(1, 0, Box(top["x1"], top["y1"], top["x2"], top["y2"]), polygon=[tuple(p) for p in top["polygon"]])
    sheet = panel_polygon(art, canvas)
    sx1, sy1, sx2, sy2 = geo.bbox(sheet)
    assert sy1 == canvas.oy - canvas.bleed
    if lay["inner_side"] == "left":
        assert sx2 == canvas.ox + canvas.trim_w + canvas.bleed
    else:
        assert sx1 == canvas.ox - canvas.bleed
    # une case ordinaire ne bouge pas
    assert not lay["panels"][1]["bleed"] and "live_polygon" not in lay["panels"][1]


def test_bleed_render_keeps_crop_marks_clean(tmp_path: Path, fonts: FontBook) -> None:
    fmt = golden_format()
    lay = _layout(_frames(p0={"bleed": True}, p3={"inset": True, "host": 2}), fmt=fmt)
    top = lay["panels"][0]
    img_path = synthetic_image(tmp_path / "a.png", (top["target"]["width"], top["target"]["height"]), COLORS[0])
    art = PageArt(
        number=1,
        fmt=fmt,
        panels=[
            PanelArt(
                1,
                0,
                Box(top["x1"], top["y1"], top["x2"], top["y2"]),
                img_path,
                polygon=[tuple(p) for p in top["polygon"]],
            )
        ],
        lettering=Letterer(fonts, PRESETS.lettering, fmt.dpi).letter_page([], "ltr"),
    )
    canvas = canvas_geometry(fmt, PRESETS.lettering, bleed=True, crop_marks=True)
    img = render_png(art, fonts, PRESETS.lettering, canvas)
    edge_y = canvas.oy - canvas.bleed  # bord du fond perdu
    mid_x = round(geo.centroid(panel_polygon(art.panels[0], canvas))[0])
    assert img.getpixel((mid_x, edge_y)) != (255, 255, 255)  # l'image va jusqu'au bord du fond perdu…
    assert img.getpixel((mid_x, edge_y - 2)) == (255, 255, 255)  # … et pas au-delà (bande des repères)
    # repères de coupe toujours dessinés, en noir, hors du fond perdu
    assert img.getpixel((canvas.ox - canvas.bleed - 5, canvas.oy)) == (0, 0, 0) or img.getpixel(
        (canvas.ox, canvas.oy - canvas.bleed - 5)
    ) == (0, 0, 0)
    # pas de bordure le long du bord rogné : la ligne de coupe est dans l'image, pas noire
    assert img.getpixel((mid_x, canvas.oy + 1)) != (0, 0, 0)


def test_inset_is_inside_its_host_and_drawn_after_it(tmp_path: Path, fonts: FontBook) -> None:
    frames = _frames(p3={"inset": True, "host": 2, "size": 0.4, "margin_mm": 3, "min_side_mm": 12})
    for direction in ("ltr", "rtl"):
        lay = _layout(frames, direction=direction)
        host, inset = lay["panels"][2], lay["panels"][3]
        assert inset["inset"] and inset["host_index"] == 2 and inset["reading_order"] == 4
        hpoly = [tuple(p) for p in host["polygon"]]
        margin = 3 / 25.4 * 300
        planes = geo.edges(geo.inset(hpoly, margin - 0.5))
        assert geo.contains_box(planes, inset["x1"], inset["y1"], inset["x2"], inset["y2"])
        # en bas, côté fin de lecture
        assert inset["y2"] > (host["y1"] + host["y2"]) / 2
        end_right = direction == "ltr"
        assert (
            (inset["x1"] + inset["x2"]) / 2 > (host["x1"] + host["x2"]) / 2
            if end_right
            else (inset["x1"] + inset["x2"]) / 2 < (host["x1"] + host["x2"]) / 2
        )
        # trois cases dans l'arbre
        assert len(lay["gutters"]) == 2
    # rendu : l'incrustation après son hôte (PNG et SVG)
    fmt = golden_format()
    lay = _layout(frames, fmt=fmt)
    arts = []
    for lp in lay["panels"]:
        i = lp["index"]
        path = synthetic_image(tmp_path / f"c{i}.png", (lp["target"]["width"], lp["target"]["height"]), COLORS[i])
        arts.append(
            PanelArt(
                i + 1,
                i,
                Box(lp["x1"], lp["y1"], lp["x2"], lp["y2"]),
                path,
                inset=lp["inset"],
                polygon=[tuple(p) for p in lp["polygon"]],
            )
        )
    arts = [arts[3], arts[0], arts[1], arts[2]]  # ordre des cases indifférent : l'incrustation passe à la fin
    assert [a.index for a in draw_order(arts)] == [0, 1, 2, 3]
    art = PageArt(
        number=1, fmt=fmt, panels=arts, lettering=Letterer(fonts, PRESETS.lettering, fmt.dpi).letter_page([], "ltr")
    )
    canvas = canvas_geometry(fmt, PRESETS.lettering)
    img = render_png(art, fonts, PRESETS.lettering, canvas)
    ins = lay["panels"][3]
    # au centre de l'incrustation : son image (couleur 3), pas celle de l'hôte
    cx, cy = (ins["x1"] + ins["x2"]) // 2, ins["y1"] + 3
    assert img.getpixel((cx, cy)) == COLORS[3][0]
    # liseré blanc juste autour
    outline = round(PRESETS.lettering.frames.inset_outline_mm / 25.4 * fmt.dpi)
    assert outline >= 2
    assert img.getpixel((cx, ins["y1"] - outline + 1)) == (255, 255, 255)
    svg = render_svg(art, fonts, PRESETS.lettering, canvas)
    assert svg.index('<g id="case-3"') < svg.index('<g id="case-4"')
    assert svg.index("liseré") < svg.index('<g id="case-4"') and 'class="case case-border incrustation"' in svg


def test_inset_needs_a_host_and_the_tree_has_one_panel_less() -> None:
    with pytest.raises(LayoutError, match="hôte"):
        _layout(_frames(p3={"inset": True}))
    with pytest.raises(LayoutError, match="incrustée"):
        # 4 cases dans l'arbre, mais une seule incrustation demandée : gabarit incohérent
        compute_layout(
            A4, SETTINGS, SplitNode(cols=[1, 1, 1, 1]), [PanelSpec(panel_id=i) for i in range(4)],
            direction="ltr", page_number=1, template_id="x", frames=_frames(p3={"inset": True, "host": 2}),
        )  # fmt: skip


def test_style_weights_for_frames() -> None:
    """« sage » n'en tire jamais ; « nerveuse » bien plus souvent que « dynamique » sur les cases fortes."""
    strong = [
        PanelSpec(importance=3, intensity="choc", panel_id=1),
        PanelSpec(importance=2, panel_id=2),
        PanelSpec(importance=1, intensity="calme", shot_type="gros plan", panel_id=3),
        PanelSpec(importance=2, panel_id=4),
    ]

    def counts(style: str) -> dict[str, int]:
        out = {"bleed": 0, "frameless": 0, "inset": 0}
        for seed in range(200):
            fr = decide_frames(PRESETS.layout_style(style), strong, seed)
            out["bleed"] += fr[0]["bleed"]
            out["frameless"] += sum(f["frame"] != "border" for f in fr)
            out["inset"] += sum(f["inset"] for f in fr)
            assert sum(f["inset"] for f in fr) <= PRESETS.layout_style(style).frames.inset.max_per_page
            for i, f in enumerate(fr):
                if f["inset"]:
                    assert f["host"] in (i - 1, i + 1) and not fr[f["host"]]["inset"]
        return out

    sage, dyn, nerv = counts("sage"), counts("dynamique"), counts("nerveuse")
    assert sage == {"bleed": 0, "frameless": 0, "inset": 0}
    assert nerv["bleed"] > dyn["bleed"] > 0
    assert nerv["frameless"] > dyn["frameless"] > 0
    assert nerv["inset"] > 0 and dyn["inset"] > 0
    # même graine : mêmes décisions ; options imposées : elles gagnent
    assert decide_frames(PRESETS.layout_style("nerveuse"), strong, 4) == decide_frames(
        PRESETS.layout_style("nerveuse"), strong, 4
    )
    forced = [
        PanelSpec(importance=3, intensity="choc", panel_id=1, frame={"bleed": False, "frame": "fade"}),
        *strong[1:],
    ]
    for seed in range(20):
        f = decide_frames(PRESETS.layout_style("nerveuse"), forced, seed)[0]
        assert f["bleed"] is False and f["frame"] == "fade"
    sage_forced = decide_frames(
        PRESETS.layout_style("sage"), [*strong[:2], PanelSpec(panel_id=3, frame={"inset": True}), strong[3]], 1
    )
    assert sage_forced[2]["inset"] and sage_forced[2]["host"] == 1


# --- planche de référence -----------------------------------------------------------------------
def _golden_page(fonts: FontBook, tmp: Path) -> tuple[Image.Image, dict[str, Any]]:
    fmt = golden_format()
    frames = _frames(
        p0={"bleed": True},
        p1={"frame": "fade"},
        p2={"frame": "none"},
        p3={"inset": True, "host": 2, "size": 0.42, "margin_mm": 3, "min_side_mm": 12},
    )
    lay = _layout(frames, fmt=fmt)
    top, host = lay["panels"][0], lay["panels"][2]
    # « VROUM ! » à cheval sur la gouttière entre la grande case et la case de droite
    gutter_y = (geo.bbox([tuple(p) for p in top["live_polygon"]])[3] + host["y1"]) / 2
    sfx = {
        0: [SfxSpec(id=101, text="VROUM !", intensity="choc", angle=-8, center=(host["x1"] + 40, gutter_y - 12))],
        1: [SfxSpec(id=102, text="baïe…", intensity="calme")],
        3: [SfxSpec(id=103, text="ça !", intensity="normal")],
    }
    bubbles = {0: [("speech", "Tu as vu ça ? Le ciel se déchire !", "Aiko")], 2: [("shout", "Cours !!", "Ren")]}
    img = render_layout(tmp, PRESETS, fonts, lay, sfx=sfx, bubbles=bubbles, crop_marks=True)
    return img, lay


def test_golden_page_with_sfx_frameless_bleed_and_inset(tmp_path: Path, fonts: FontBook) -> None:
    first, lay = _golden_page(fonts, tmp_path)
    second, _ = _golden_page(fonts, tmp_path)
    assert first.tobytes() == second.tobytes(), "le rendu n'est pas déterministe"
    assert [p.get("frame") for p in lay["panels"]] == ["border", "fade", "none", "border"]
    assert lay["panels"][0]["bleed"] and lay["panels"][3]["inset"]
    if os.environ.get("MANGAKA_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        first.save(GOLDEN, format="PNG", dpi=(100, 100))
        pytest.skip("image de référence régénérée")
    assert GOLDEN.is_file(), "référence absente : MANGAKA_UPDATE_GOLDEN=1 npm run test:engine"
    with Image.open(GOLDEN) as ref:
        expected = ref.convert("RGB")
    assert expected.size == first.size
    diff = ImageChops.difference(first, expected).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = sum(diff.histogram()[255:])
    if changed > first.width * first.height * 0.0005:
        first.save(tmp_path / "rendu.png")
        pytest.fail(f"planche « cadres et onomatopées » modifiée ({changed} px) — rendu : {tmp_path / 'rendu.png'}")
