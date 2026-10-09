"""Mise en page dynamique : cases polygonales, découpes en biais, grammaire de mise en page par série.

Images de référence : `tests/golden/planche-sage.png` (produite par le moteur d'avant les styles :
une page « sage » doit rester identique), `planche-dynamique.png` et `planche-nerveuse.png`.
Régénération : `MANGAKA_UPDATE_GOLDEN=1 npm run test:engine` (à justifier dans la PR).
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageChops

from mangaka_engine.pipeline import geometry as geo
from mangaka_engine.pipeline.assembly import PageArt, PanelArt, canvas_geometry, render_png, render_svg
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.layout import (
    LayoutError,
    PanelSpec,
    choose_template,
    compute_layout,
    move_gutter,
    set_cut_slant,
)
from mangaka_engine.pipeline.layout_style import plan_page, styled_layout
from mangaka_engine.pipeline.lettering import Box, BubbleSpec, Letterer
from mangaka_engine.pipeline.lettering import PanelSpec as LetterSpec
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import SplitNode
from tests.conftest import PRESETS_DIR
from tests.layout_render import IMPORTANCES, dialogue_chars, golden_format, render_layout

PRESETS = PresetRegistry.load(PRESETS_DIR)
TEMPLATES = list(PRESETS.layout_templates.values())
SETTINGS = PRESETS.layout
A4 = PRESETS.page_format("a4-300dpi")
STYLES = ["sage", "dynamique", "nerveuse"]
GOLDEN = Path(__file__).parent / "golden"


def _random_specs(rng: random.Random, n: int | None = None) -> list[PanelSpec]:
    n = n or rng.choice([2, 3, 4, 5, 6, 7])
    return [
        PanelSpec(
            importance=rng.choice([1, 2, 2, 3]),
            dialogue_chars=rng.choice([0, 40, 160]),
            panel_id=i + 1,
            intensity=rng.choice([None, None, "calme", "normal", "choc"]),
        )
        for i in range(n)
    ]


def _page(style: str, seed: int, specs: list[PanelSpec], *, direction: str = "rtl", page: int = 1, **kw: Any):  # type: ignore[no-untyped-def]
    return styled_layout(
        A4,
        SETTINGS,
        PRESETS.layout_style(style),
        TEMPLATES,
        specs,
        direction=direction,  # type: ignore[arg-type]
        page_number=page,
        seed=seed,
        **kw,
    )


def _polys(layout: dict[str, Any]) -> list[geo.Polygon]:
    return [[(float(x), float(y)) for x, y in p["polygon"]] for p in layout["panels"]]


def _sat_gap(a: geo.Polygon, b: geo.Polygon) -> float:
    """Plus grand écart le long des normales des bords (> 0 : polygones convexes disjoints)."""
    best = -math.inf
    for poly in (a, b):
        for nx, ny, _ in geo.edges(poly):
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            best = max(best, min(pb) - max(pa), min(pa) - max(pb))
    return best


def _check_frames(layout: dict[str, Any]) -> None:
    """Fond perdu jusqu'au bord exact de la page ; incrustation contenue dans son hôte."""
    W, H = layout["page"]["width"], layout["page"]["height"]
    live = layout["live_area"]
    panels = layout["panels"]
    for p in panels:
        assert p.get("frame", "border") in ("border", "none", "fade")
        if p.get("bleed"):
            poly = [(float(x), float(y)) for x, y in p["polygon"]]
            inner = [(float(x), float(y)) for x, y in p["live_polygon"]]
            x1, y1, x2, y2 = geo.bbox(inner)
            bx1, by1, bx2, by2 = geo.bbox(poly)
            touched = []
            if abs(y1 - live["y1"]) < 0.05:
                touched.append(by1 == 0)
            if abs(y2 - live["y2"]) < 0.05:
                touched.append(by2 == H)
            if abs(x1 - live["x1"]) < 0.05 and layout["inner_side"] != "left":
                touched.append(bx1 == 0)
            if abs(x2 - live["x2"]) < 0.05 and layout["inner_side"] != "right":
                touched.append(bx2 == W)
            assert touched and all(touched), p
            # la case agrandie contient sa partie dans la zone utile
            assert all(geo.contains(geo.edges(poly), x, y, tol=0.2) for x, y in inner), p
        if p.get("inset"):
            host = panels[p["host_index"]]
            assert not host.get("inset")
            hpoly = [(float(x), float(y)) for x, y in (host.get("live_polygon") or host["polygon"])]
            assert geo.contains_box(geo.edges(hpoly), p["x1"], p["y1"], p["x2"], p["y2"]), (p, host)


def _check(layout: dict[str, Any]) -> None:
    """Dans les marges, convexes, sans chevauchement, gouttières perpendiculaires constantes, ordre de lecture."""
    live = layout["live_area"]
    gh, gv = layout["gutters_px"]["horizontal"], layout["gutters_px"]["vertical"]
    _check_frames(layout)
    # Cases de l'arbre, dans la zone utile (fond perdu : leur partie dans la zone utile) ; les
    # incrustations, posées sur leur hôte, sont vérifiées par _check_frames.
    tree_panels = [p for p in layout["panels"] if not p.get("inset")]
    polys = [[(float(x), float(y)) for x, y in (p.get("live_polygon") or p["polygon"])] for p in tree_panels]
    for p, poly in zip(tree_panels, polys, strict=True):
        assert len(poly) >= 3 and geo.area(poly) > 0, p
        if p.get("bleed"):
            x1, y1, x2, y2 = geo.bbox([(float(x), float(y)) for x, y in p["polygon"]])
            assert (p["x1"], p["y1"], p["x2"], p["y2"]) == (
                math.floor(x1 + 1e-6),
                math.floor(y1 + 1e-6),
                math.ceil(x2 - 1e-6),
                math.ceil(y2 - 1e-6),
            )
            continue
        for x, y in poly:
            assert live["x1"] - 0.05 <= x <= live["x2"] + 0.05 and live["y1"] - 0.05 <= y <= live["y2"] + 0.05, p
        x1, y1, x2, y2 = geo.bbox(poly)
        assert (p["x1"], p["y1"], p["x2"], p["y2"]) == (
            math.floor(x1 + 1e-6),
            math.floor(y1 + 1e-6),
            math.ceil(x2 - 1e-6),
            math.ceil(y2 - 1e-6),
        )
        assert p["slanted"] == (not geo.is_axis_rect(poly))
        # zone de bulles entièrement dans le polygone
        z = p["bubble_zone"]
        if z is not None:
            assert geo.contains_box(geo.edges(poly), z["x1"], z["y1"], z["x2"], z["y2"]), (p, z)
    # aucun chevauchement : au moins une gouttière entre deux cases
    for a, b in itertools.combinations(polys, 2):
        assert _sat_gap(a, b) >= min(gh, gv) - 0.3
    # largeur perpendiculaire constante le long de chaque découpe
    for g in layout["gutters"]:
        (x0, y0), (x1, y1) = g["line"]
        width = gh if g["orientation"] == "horizontal" else gv
        dx, dy = x1 - x0, y1 - y0
        norm = math.hypot(dx, dy)
        ux, uy = dx / norm, dy / norm
        nx, ny = -uy, ux
        offsets = []
        for poly in polys:
            for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
                ex, ey = bx - ax, by - ay
                length = math.hypot(ex, ey)
                if length < 5 or abs(ex * uy - ey * ux) / length > 1e-3:
                    continue  # bord non parallèle à la découpe
                off = (ax - x0) * nx + (ay - y0) * ny
                along = ((ax + bx) / 2 - x0) * ux + ((ay + by) / 2 - y0) * uy
                if abs(off) <= width and 0 < along < norm:  # bord qui borde cette gouttière
                    offsets.append(off)
        assert offsets, g
        for off in offsets:
            assert abs(abs(off) - width / 2) <= 0.2, (g, offsets)
        assert min(offsets) < 0 < max(offsets)
    _check_reading_order(layout)


def _check_reading_order(layout: dict[str, Any]) -> None:
    panels = layout["panels"]
    rtl = layout["direction"] == "rtl"
    assert [p["reading_order"] for p in panels] == list(range(1, len(panels) + 1))
    for a, b in itertools.combinations(panels, 2):  # a avant b
        overlap = min(a["y2"], b["y2"]) - max(a["y1"], b["y1"])
        if overlap > 0.5 * min(a["height"], b["height"]):  # même bande : sens de lecture
            ca, cb = (a["x1"] + a["x2"]) / 2, (b["x1"] + b["x2"]) / 2
            assert (ca > cb) if rtl else (ca < cb), (a, b)
        else:
            assert (a["y1"] + a["y2"]) / 2 < (b["y1"] + b["y2"]) / 2, (a, b)


# --- géométrie ---------------------------------------------------------------------------------
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_styled_pages_are_valid_polygons(style: str, direction: str) -> None:
    rng = random.Random(f"{style}-{direction}")
    for k in range(40):
        layout = _page(style, rng.randrange(10**6), _random_specs(rng), direction=direction, page=k + 1)
        _check(layout)


def test_every_template_with_steep_slants_stays_valid() -> None:
    for tpl in TEMPLATES:
        if not isinstance(tpl.tree, SplitNode):
            continue
        for direction in ("ltr", "rtl"):
            specs = [
                PanelSpec(importance=3, intensity="choc", dialogue_chars=80, panel_id=i) for i in range(tpl.panel_count)
            ]
            layout = _page("nerveuse", 3, specs, direction=direction, forced=(tpl.id, tpl.tree))
            assert layout["template_id"] == tpl.id
            _check(layout)


def test_slanted_cut_keeps_perpendicular_gutter_and_mirrors_for_rtl() -> None:
    tree = SplitNode(rows=[1, 1], slants=[(-6, 6)])
    specs = [PanelSpec(panel_id=1), PanelSpec(panel_id=2)]
    ltr = compute_layout(A4, SETTINGS, tree, specs, direction="ltr", page_number=1, template_id="t")
    rtl = compute_layout(A4, SETTINGS, tree, specs, direction="rtl", page_number=2, template_id="t")
    _check(ltr)
    _check(rtl)
    assert all(p["slanted"] for p in ltr["panels"])
    # même côté de reliure : rtl = miroir de ltr dans la zone utile
    L, R = ltr["live_area"]["x1"], ltr["live_area"]["x2"]
    for a, b in zip(_polys(ltr), _polys(rtl), strict=True):
        assert sorted((round(L + R - x, 1), y) for x, y in a) == sorted((round(x, 1), y) for x, y in b)
    # la découpe descend vers la droite en lecture ltr : 12 mm entre ses deux extrémités
    g = ltr["gutters"][0]
    assert g["ends"][1] - g["ends"][0] == pytest.approx(12 * 300 / 25.4, abs=0.2)
    assert g["slant_mm"] == [-6, 6] and g["angle_deg"] > 0


def test_straight_tree_is_identical_to_rectangles() -> None:
    """Sans biais : les polygones sont exactement les rectangles entiers d'avant."""
    for tpl in TEMPLATES:
        layout = compute_layout(
            A4, SETTINGS, tpl.tree, [PanelSpec(panel_id=i) for i in range(tpl.panel_count)],
            direction="rtl", page_number=1, template_id=tpl.id,
        )  # fmt: skip
        for p in layout["panels"]:
            assert p["polygon"] == [[p["x1"], p["y1"]], [p["x2"], p["y1"]], [p["x2"], p["y2"]], [p["x1"], p["y2"]]]
            assert p["slanted"] is False
        assert "slants" not in str(layout["tree"])


def test_same_seed_same_layout_other_seed_other_layout() -> None:
    rng = random.Random(5)
    specs = _random_specs(rng, 5)
    a = _page("nerveuse", 42, specs)
    b = _page("nerveuse", 42, specs)
    assert a == b
    others = {str(_page("nerveuse", s, specs)["tree"]) for s in range(43, 53)}
    assert len(others) > 3


def test_sage_page_is_the_legacy_layout() -> None:
    """« sage » = choix du gabarit et géométrie d'avant les styles, à l'identique."""
    rng = random.Random(9)
    for _ in range(30):
        specs = _random_specs(rng)
        tid, tree = choose_template(TEMPLATES, [s.importance for s in specs])
        legacy = compute_layout(A4, SETTINGS, tree, specs, direction="rtl", page_number=1, template_id=tid)
        sage = _page("sage", rng.randrange(1000), specs)
        assert sage["template_id"] == tid
        sage.pop("style")
        assert sage == legacy


def test_styles_give_visibly_different_distributions() -> None:
    """50 pages par style : biais (fréquence, angle) et contraste des tailles croissent de sage à nerveuse."""
    stats: dict[str, dict[str, float]] = {}
    for style in STYLES:
        rng = random.Random(2026)
        slanted = cuts = 0
        angles: list[float] = []
        contrast: list[float] = []
        previous = None
        for k in range(50):
            layout = _page(
                style, rng.randrange(10**6), _random_specs(rng), page=k + 1, exclude=[previous] if previous else []
            )
            previous = layout["template_id"]
            for g in layout["gutters"]:
                cuts += 1
                if abs(g["angle_deg"]) > 0.1:
                    slanted += 1
                    angles.append(abs(g["angle_deg"]))
            areas = [abs(geo.area(p)) for p in _polys(layout)]
            contrast.append(statistics.pstdev(areas) / statistics.mean(areas))
        stats[style] = {
            "slanted": slanted / cuts,
            "angle": statistics.mean(angles) if angles else 0.0,
            "contrast": statistics.mean(contrast),
        }
    sage, dyn, ner = stats["sage"], stats["dynamique"], stats["nerveuse"]
    assert sage["slanted"] == 0 and sage["angle"] == 0
    assert 0.1 < dyn["slanted"] < ner["slanted"], stats
    assert ner["slanted"] - dyn["slanted"] > 0.15, stats
    assert dyn["angle"] < ner["angle"], stats
    assert sage["contrast"] < ner["contrast"], stats


@pytest.mark.parametrize("style", STYLES)
def test_never_two_identical_layouts_in_a_row(style: str) -> None:
    rng = random.Random(f"repeat-{style}")
    previous = None
    for k in range(50):
        specs = _random_specs(rng, 4)  # toujours 4 cases : la répétition serait tentante
        layout = _page(style, rng.randrange(10**6), specs, page=k + 1, exclude=[previous] if previous else [])
        assert layout["template_id"] != previous
        previous = layout["template_id"]


def test_intensity_and_rythme_drive_slants_and_big_panels() -> None:
    style = PRESETS.layout_style("dynamique")
    calm = [PanelSpec(importance=2, intensity="calme", panel_id=i) for i in range(4)]
    shock = [PanelSpec(importance=2, intensity="choc" if i == 0 else "calme", panel_id=i) for i in range(4)]

    def slants(specs: list[PanelSpec], rythme: str | None) -> int:
        n = 0
        for seed in range(40):
            plan = plan_page(
                A4, SETTINGS, style, TEMPLATES, specs, direction="ltr", page_number=1, seed=seed, rythme=rythme
            )
            lay = compute_layout(A4, SETTINGS, plan.tree, specs, direction="ltr", page_number=1, template_id="t")
            n += sum(1 for g in lay["gutters"] if abs(g["angle_deg"]) > 0.1)
        return n

    assert slants(calm, None) == 0  # calme : probabilité 0 dans « dynamique »
    assert slants(shock, "rapide") > slants(shock, "lent") > 0

    # la case « choc » en tête obtient en moyenne une plus grande part de la page
    def first_share(specs: list[PanelSpec]) -> float:
        shares = []
        for seed in range(30):
            areas = [abs(geo.area(p)) for p in _polys(_page("dynamique", seed, specs))]
            shares.append(areas[0] / sum(areas))
        return statistics.mean(shares)

    assert first_share(shock) > first_share(calm) + 0.05


def test_no_style_or_angle_constant_in_python() -> None:
    """Les valeurs de style vivent dans presets/layout_styles/ : aucun champ par défaut dans le schéma."""
    from mangaka_engine.presets.schemas import FrameRule, FrameTable, InsetRule, LayoutStyle, SlantRule

    for model in (LayoutStyle, SlantRule, FrameRule, FrameTable, InsetRule):
        defaults = [
            name
            for name, f in model.model_fields.items()
            if not f.is_required() and name not in ("description", "template_weights")
        ]
        assert defaults == [], defaults


# --- découpes manipulées à la main ---------------------------------------------------------------
@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_dragging_cut_ends_changes_slant_within_min_size(direction: str) -> None:
    tree = PRESETS.layout_template("3-grand-cote").tree  # cols : grande case | 2 cases empilées
    specs = [PanelSpec(panel_id=i) for i in range(3)]
    lay = compute_layout(A4, SETTINGS, tree, specs, direction=direction, page_number=1, template_id="3-grand-cote")  # type: ignore[arg-type]
    g = next(x for x in lay["gutters"] if x["path"] == [] and x["index"] == 0)
    assert g["orientation"] == "vertical" and g["angle_deg"] == 0
    top, bottom = g["ends"]
    # haut vers la gauche de la page, bas vers la droite
    after = set_cut_slant(A4, SETTINGS, lay, specs, path=[], index=0, ends=[top - 150, bottom + 150])
    _check(after)
    ng = next(x for x in after["gutters"] if x["path"] == [] and x["index"] == 0)
    assert ng["ends"] == pytest.approx([top - 150, bottom + 150], abs=0.6)
    assert ng["angle_deg"] != 0
    # tirer une extrémité très loin : bornée par la taille minimale des cases voisines
    extreme = set_cut_slant(A4, SETTINGS, after, specs, path=[], index=0, ends=[-50_000, 50_000])
    _check(extreme)
    eg = next(x for x in extreme["gutters"] if x["path"] == [] and x["index"] == 0)
    assert eg["ends"][0] == pytest.approx(eg["ends_min"][0], abs=0.6) or eg["ends"][0] == pytest.approx(
        eg["ends_max"][0], abs=0.6
    )
    min_px = A4.mm_to_px(SETTINGS.min_panel_mm)
    for p in extreme["panels"]:
        assert p["width"] >= min_px and p["height"] >= min_px
    # déplacer la gouttière garde le biais
    moved = move_gutter(A4, SETTINGS, after, specs, path=[], index=0, position=ng["position"] + 40)
    mg = next(x for x in moved["gutters"] if x["path"] == [] and x["index"] == 0)
    assert mg["slant_mm"] == ng["slant_mm"]
    _check(moved)
    with pytest.raises(LayoutError, match="introuvable"):
        set_cut_slant(A4, SETTINGS, lay, specs, path=[5], index=0, ends=[0, 0])


def test_unknown_or_overlapping_slants_are_rejected() -> None:
    specs = [PanelSpec(panel_id=1), PanelSpec(panel_id=2)]
    with pytest.raises(LayoutError, match="incliné"):
        compute_layout(
            A4,
            SETTINGS,
            SplitNode(rows=[1, 1], slants=[(-400, 400)]),
            specs,
            direction="ltr",
            page_number=1,
            template_id="t",
        )


# --- lettrage dans un polygone ----------------------------------------------------------------
@pytest.fixture(scope="module")
def fonts() -> FontBook:
    return FontBook(PRESETS)


def _slanted_panel(direction: str) -> tuple[dict[str, Any], dict[str, Any]]:
    tree = SplitNode(cols=[1, 1], slants=[(-12, 12)])
    specs = [PanelSpec(panel_id=1, dialogue_chars=120), PanelSpec(panel_id=2, dialogue_chars=120)]
    lay = compute_layout(A4, SETTINGS, tree, specs, direction=direction, page_number=1, template_id="t")  # type: ignore[arg-type]
    return lay, lay["panels"][0]


@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_bubbles_and_tails_stay_inside_slanted_panel(direction: str, fonts: FontBook) -> None:
    lay, lp = _slanted_panel(direction)
    poly = [(float(x), float(y)) for x, y in lp["polygon"]]
    assert lp["slanted"]
    box = Box(lp["x1"], lp["y1"], lp["x2"], lp["y2"])
    z = lp["bubble_zone"]
    face = Box(box.cx - 150, box.cy - 150, box.cx + 150, box.cy + 150)
    spec = LetterSpec(
        id=1,
        index=0,
        box=box,
        zone=Box(z["x1"], z["y1"], z["x2"], z["y2"]),
        faces=[face],
        characters=["Aiko"],
        polygon=poly,
        bubbles=[
            BubbleSpec(1, "speech", "Tu vois cette lumière au loin, derrière la colline ?", "Aiko", 0),
            BubbleSpec(2, "shout", "Attention !", "Aiko", 1),
            BubbleSpec(3, "off", "Je suis là !", "Ren", 2),
            BubbleSpec(4, "narration", "Le soir tombe sur la vallée.", "", 3),
        ],
    )
    res = Letterer(fonts, PRESETS.lettering, A4.dpi).letter_page([spec], direction)  # type: ignore[arg-type]
    planes = geo.edges(poly)
    assert not any(w.code == "text_overflow" for w in res.warnings)
    for b in res.bubbles:
        assert geo.contains_box(planes, b.box.x1, b.box.y1, b.box.x2, b.box.y2), b.box
        assert not b.box.intersects(face), b.kind
        if b.tail is not None:
            assert geo.contains(planes, *b.tail, tol=0.2), (b.kind, b.tail)
    off = next(b for b in res.bubbles if b.kind == "off")
    assert off.tail is not None and geo.nearest_on_boundary(poly, *off.tail) == pytest.approx(off.tail, abs=0.2)
    speech = next(b for b in res.bubbles if b.id == 1)
    assert speech.tail is not None  # vers le visage


def test_bounding_box_bubble_would_leave_slanted_panel(fonts: FontBook) -> None:
    """Sans polygone, la bulle irait dans le coin coupé par le biais : la contrainte sert bien."""
    lay, lp = _slanted_panel("ltr")
    poly = [(float(x), float(y)) for x, y in lp["polygon"]]
    box = Box(lp["x1"], lp["y1"], lp["x2"], lp["y2"])
    bubble = [BubbleSpec(1, "speech", "Une réplique assez longue pour remplir la largeur de la case.", "", 0)]
    letterer = Letterer(fonts, PRESETS.lettering, A4.dpi)
    loose = letterer.letter_page([LetterSpec(id=1, index=0, box=box, bubbles=bubble)], "rtl").bubbles[0]
    tight = letterer.letter_page([LetterSpec(id=1, index=0, box=box, bubbles=bubble, polygon=poly)], "rtl").bubbles[0]
    planes = geo.edges(poly)
    assert not geo.contains_box(planes, loose.box.x1, loose.box.y1, loose.box.x2, loose.box.y2)
    assert geo.contains_box(planes, tight.box.x1, tight.box.y1, tight.box.x2, tight.box.y2)


# --- assemblage --------------------------------------------------------------------------------
def test_slanted_panel_is_clipped_with_border_along_edges(tmp_path: Path, fonts: FontBook) -> None:
    fmt = golden_format()
    tree = SplitNode(cols=[1, 1], slants=[(-10, 10)])
    lay = compute_layout(
        fmt,
        SETTINGS,
        tree,
        [PanelSpec(panel_id=1), PanelSpec(panel_id=2)],
        direction="ltr",
        page_number=1,
        template_id="t",
    )
    panels = []
    for lp in lay["panels"]:
        img = tmp_path / f"{lp['index']}.png"
        Image.new("RGB", (lp["target"]["width"], lp["target"]["height"]), (200, 0, 0)).save(img)
        poly = [(float(x), float(y)) for x, y in lp["polygon"]]
        panels.append(
            PanelArt(lp["index"] + 1, lp["index"], Box(lp["x1"], lp["y1"], lp["x2"], lp["y2"]), img, (8, 8), poly)
        )
    panels[1].image = None  # case manquante en biais
    art = PageArt(
        number=1, fmt=fmt, panels=panels, lettering=Letterer(fonts, PRESETS.lettering, fmt.dpi).letter_page([], "ltr")
    )
    canvas = canvas_geometry(fmt, PRESETS.lettering)
    png = render_png(art, fonts, PRESETS.lettering, canvas)
    left = lay["panels"][0]
    poly = [(float(x), float(y)) for x, y in left["polygon"]]
    cx, cy = geo.centroid(poly)
    assert png.getpixel((round(cx), round(cy))) == (200, 0, 0)
    # l'image ne déborde pas du polygone : coin de la boîte englobante coupé par le biais, gouttière blanche
    corner = next((x, y) for x, y in [(left["x2"] - 2, left["y1"] + 2), (left["x2"] - 2, left["y2"] - 3)]
                  if not geo.contains(geo.edges(poly), x, y, tol=8))  # fmt: skip
    assert png.getpixel(corner) != (200, 0, 0)
    g = lay["gutters"][0]
    (x0, y0), (x1, y1) = g["line"]
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    assert png.getpixel((round(mx), round(my))) == (255, 255, 255)
    # bordure noire le long du bord en biais
    gv = lay["gutters_px"]["vertical"]
    edge_px = png.getpixel((round(mx - gv / 2 - 1), round(my)))
    assert max(edge_px) < 80, edge_px
    # case manquante : aplat gris dans le polygone
    right = [(float(x), float(y)) for x, y in lay["panels"][1]["polygon"]]
    rx, ry = geo.centroid(right)
    assert png.getpixel((round(rx), round(ry) - 40)) == (0x9E, 0x9E, 0x9E)
    svg = render_svg(art, fonts, PRESETS.lettering, canvas_geometry(fmt, PRESETS.lettering, bleed=True))
    assert svg.count("<clipPath") == 2 and svg.count("<polygon") == 4  # 2 découpes + 2 bordures


# --- images de référence -----------------------------------------------------------------------
def _specs() -> list[PanelSpec]:
    return [
        PanelSpec(
            importance=imp, dialogue_chars=dialogue_chars(i), panel_id=i + 1, intensity="choc" if i == 0 else None
        )
        for i, imp in enumerate(IMPORTANCES)
    ]


def _golden_layout(style: str) -> dict[str, Any]:
    return styled_layout(
        golden_format(), SETTINGS, PRESETS.layout_style(style), TEMPLATES,
        _specs() if style != "sage" else [PanelSpec(importance=i, dialogue_chars=dialogue_chars(k), panel_id=k + 1) for k, i in enumerate(IMPORTANCES)],
        direction="rtl", page_number=1, seed=7,
    )  # fmt: skip


@pytest.mark.parametrize("style", STYLES)
def test_golden_styled_pages(style: str, tmp_path: Path, fonts: FontBook) -> None:
    layout = _golden_layout(style)
    if style != "sage":
        assert any(p["slanted"] for p in layout["panels"])
    first = render_layout(tmp_path, PRESETS, fonts, layout)
    second = render_layout(tmp_path, PRESETS, fonts, layout)
    assert first.tobytes() == second.tobytes(), "le rendu n'est pas déterministe"
    path = GOLDEN / f"planche-{style}.png"
    if os.environ.get("MANGAKA_UPDATE_GOLDEN") == "1" and style != "sage":
        first.save(path, format="PNG", dpi=(100, 100))
        pytest.skip("image de référence régénérée")
    with Image.open(path) as ref:
        expected = ref.convert("RGB")
    assert expected.size == first.size
    diff = ImageChops.difference(first, expected).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = sum(diff.histogram()[255:])
    if changed > first.width * first.height * 0.0005:
        first.save(tmp_path / "rendu.png")
        pytest.fail(f"planche « {style} » modifiée ({changed} px) — rendu : {tmp_path / 'rendu.png'}")
