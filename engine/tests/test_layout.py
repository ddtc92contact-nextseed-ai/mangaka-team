from __future__ import annotations

import itertools
from typing import Any

import pytest

from mangaka_engine.pipeline.layout import (
    LayoutError,
    PanelSpec,
    auto_tree,
    choose_template,
    compute_layout,
    move_gutter,
    page_frame,
    target_size,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import SplitNode, count_panels
from tests.conftest import PRESETS_DIR

PRESETS = PresetRegistry.load(PRESETS_DIR)
TEMPLATES = list(PRESETS.layout_templates.values())
FORMATS = list(PRESETS.page_formats.values())
SETTINGS = PRESETS.layout


def _specs(n: int, chars: int = 60) -> list[PanelSpec]:
    return [PanelSpec(importance=2, dialogue_chars=chars * (i % 3), panel_id=i + 1) for i in range(n)]


def _layout(tpl_tree: Any, n: int, *, direction: str = "ltr", page: int = 1, fmt=None, chars: int = 60):  # type: ignore[no-untyped-def]
    return compute_layout(
        fmt or PRESETS.page_format("a4-300dpi"),
        SETTINGS,
        tpl_tree,
        _specs(n, chars),
        direction=direction,  # type: ignore[arg-type]
        page_number=page,
        template_id="t",
    )


def _separated(a: dict[str, int], b: dict[str, int], gap_x: int, gap_y: int) -> bool:
    """Les deux rectangles sont séparés d'au moins une gouttière, horizontalement ou verticalement."""
    return (
        b["x1"] - a["x2"] >= gap_x
        or a["x1"] - b["x2"] >= gap_x
        or b["y1"] - a["y2"] >= gap_y
        or a["y1"] - b["y2"] >= gap_y
    )


def _check_geometry(layout: dict[str, Any]) -> None:
    live = layout["live_area"]
    gx, gy = layout["gutters_px"]["vertical"], layout["gutters_px"]["horizontal"]
    panels = layout["panels"]
    for p in panels:
        # dans les marges
        assert live["x1"] <= p["x1"] < p["x2"] <= live["x2"], p
        assert live["y1"] <= p["y1"] < p["y2"] <= live["y2"], p
        assert p["width"] == p["x2"] - p["x1"] and p["height"] == p["y2"] - p["y1"]
        # zone de bulles dans sa case
        z = p["bubble_zone"]
        if z is not None:
            assert p["x1"] <= z["x1"] < z["x2"] <= p["x2"], (p, z)
            assert p["y1"] <= z["y1"] < z["y2"] <= p["y2"], (p, z)
        # taille cible : ratio conservé, multiples de 16
        t = p["target"]
        assert t["width"] % 16 == 0 and t["height"] % 16 == 0
        assert abs(t["width"] / t["height"] - p["ratio"]) / p["ratio"] < 0.1
    # gouttières respectées, aucun chevauchement
    for a, b in itertools.combinations(panels, 2):
        assert _separated(a, b, gx, gy), (a, b)
    # la zone utile est entièrement couverte (cases + gouttières) : bords extrêmes atteints
    assert min(p["x1"] for p in panels) == live["x1"] and max(p["x2"] for p in panels) == live["x2"]
    assert min(p["y1"] for p in panels) == live["y1"] and max(p["y2"] for p in panels) == live["y2"]
    assert [p["reading_order"] for p in panels] == list(range(1, len(panels) + 1))


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda t: t.id)
@pytest.mark.parametrize("direction", ["ltr", "rtl"])
@pytest.mark.parametrize("page", [1, 2])
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.id)
def test_every_template_geometry(tpl, direction, page, fmt) -> None:  # type: ignore[no-untyped-def]
    layout = _layout(tpl.tree, tpl.panel_count, direction=direction, page=page, fmt=fmt)
    assert len(layout["panels"]) == tpl.panel_count
    _check_geometry(layout)


@pytest.mark.parametrize("n", [1, 2, 4, 7, 10, 11, 12, 13])
def test_auto_tree_for_any_panel_count(n: int) -> None:
    tree = auto_tree(n)
    assert count_panels(tree) == n
    _check_geometry(_layout(tree, n))


def test_library_covers_one_to_six_plus_panels() -> None:
    counts = {t.panel_count for t in TEMPLATES}
    assert set(range(1, 10)) <= counts


def test_a4_is_default_and_margins_alternate_with_reading_direction() -> None:
    assert PRESETS.defaults is not None and PRESETS.defaults.page_format == "a4-300dpi"
    fmt = PRESETS.page_format("a4-300dpi")
    inner, outer = fmt.mm_to_px(fmt.margins_mm.inner), fmt.mm_to_px(fmt.margins_mm.outer)
    # BD (ltr) : page 1 = page de droite, reliure à gauche
    f = page_frame(fmt, SETTINGS, direction="ltr", page_number=1)
    assert f.inner_side == "left" and f.live.x1 == inner and fmt.width_px - f.live.x2 == outer
    assert page_frame(fmt, SETTINGS, direction="ltr", page_number=2).inner_side == "right"
    # manga (rtl) : page 1 = page de gauche, reliure à droite
    f = page_frame(fmt, SETTINGS, direction="rtl", page_number=1)
    assert f.inner_side == "right" and fmt.width_px - f.live.x2 == inner
    assert (f.width, f.height) == (2480, 3508)


def test_gutters_are_exact_mm() -> None:
    fmt = PRESETS.page_format("a4-300dpi")
    layout = _layout(PRESETS.layout_template("4-grille").tree, 4)
    p = layout["panels"]
    gv, gh = fmt.mm_to_px(fmt.gutters_mm.vertical), fmt.mm_to_px(fmt.gutters_mm.horizontal)
    assert p[1]["x1"] - p[0]["x2"] == gv
    assert p[2]["y1"] - p[0]["y2"] == gh


def test_ltr_and_rtl_are_mirrored_with_reading_order() -> None:
    tree = PRESETS.layout_template("3-grand-haut").tree
    # même côté de reliure pour comparer : ltr page 1 (reliure à gauche) vs rtl page 2 (reliure à gauche)
    ltr = _layout(tree, 3, direction="ltr", page=1)
    rtl = _layout(tree, 3, direction="rtl", page=2)
    assert ltr["live_area"] == rtl["live_area"]
    live = ltr["live_area"]
    for a, b in zip(ltr["panels"], rtl["panels"], strict=True):
        assert (a["y1"], a["y2"]) == (b["y1"], b["y2"])
        assert a["x1"] - live["x1"] == live["x2"] - b["x2"]
    # case 2 (en bas) : à gauche en ltr, à droite en rtl
    assert ltr["panels"][1]["x1"] < ltr["panels"][2]["x1"]
    assert rtl["panels"][1]["x1"] > rtl["panels"][2]["x1"]


def test_bubble_zone_follows_reading_direction_and_dialogue_length() -> None:
    tree = PRESETS.layout_template("1-pleine-page").tree
    fmt = PRESETS.page_format("a4-300dpi")
    pad = fmt.mm_to_px(SETTINGS.bubble_zone.padding_mm)

    def zone(direction: str, chars: int) -> tuple[dict[str, int], dict[str, int]]:
        lay = compute_layout(
            fmt, SETTINGS, tree, [PanelSpec(dialogue_chars=chars)], direction=direction, page_number=1, template_id="t"
        )  # type: ignore[arg-type]
        return lay["panels"][0], lay["panels"][0]["bubble_zone"]

    p, z = zone("ltr", 50)
    assert z["x1"] == p["x1"] + pad and z["y1"] == p["y1"] + pad  # en haut à gauche
    p, z = zone("rtl", 50)
    assert z["x2"] == p["x2"] - pad and z["y1"] == p["y1"] + pad  # en haut à droite
    _, short = zone("ltr", 10)
    _, long = zone("ltr", 600)
    area = lambda r: (r["x2"] - r["x1"]) * (r["y2"] - r["y1"])  # noqa: E731
    assert area(long) > area(short)
    pa = p["width"] * p["height"]
    assert area(long) <= SETTINGS.bubble_zone.max_fraction * pa * 1.01
    assert zone("ltr", 0)[1] is None  # case muette : pas de zone réservée


def test_template_choice_by_count_and_importance() -> None:
    assert choose_template(TEMPLATES, [2])[0] == "1-pleine-page"
    # une case forte en premier → grande case en haut
    assert choose_template(TEMPLATES, [3, 1, 1])[0] == "3-grand-haut"
    # la case forte à la fin → grande case en bas
    assert choose_template(TEMPLATES, [1, 1, 3])[0] == "3-grand-bas"
    # importance égale → cases égales
    assert choose_template(TEMPLATES, [2, 2, 2, 2])[0] == "4-grille"
    assert choose_template(TEMPLATES, [2] * 6)[0] == "6-grille"
    assert choose_template(TEMPLATES, [3, 1, 1, 1, 1, 1])[0] == "6-grand-haut"
    # au-delà de la bibliothèque : grille générée
    tid, tree = choose_template(TEMPLATES, [2] * 11)
    assert tid == "auto-11" and count_panels(tree) == 11
    with pytest.raises(LayoutError):
        choose_template(TEMPLATES, [])


def test_template_panel_count_mismatch_is_an_error() -> None:
    with pytest.raises(LayoutError, match="cases"):
        _layout(PRESETS.layout_template("4-grille").tree, 3)


def test_target_size() -> None:
    t = target_size(2000, 1000, SETTINGS)
    assert t["width"] % 16 == 0 and t["height"] % 16 == 0
    assert abs(t["width"] * t["height"] - 1_000_000) < 60_000
    assert abs(t["width"] / t["height"] - 2) < 0.05
    thin = target_size(4000, 100, SETTINGS)
    assert thin["height"] >= SETTINGS.generation.min_side


# --- gouttières -------------------------------------------------------------------
def _rects(layout: dict[str, Any]) -> list[tuple[int, int, int, int]]:
    return [(p["x1"], p["y1"], p["x2"], p["y2"]) for p in layout["panels"]]


@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_moving_a_gutter_only_changes_its_neighbours(direction: str) -> None:
    fmt = PRESETS.page_format("a4-300dpi")
    tree = PRESETS.layout_template("5-classique").tree  # rows: [cols 2], panel, [cols 2]
    specs = _specs(5)
    before = compute_layout(fmt, SETTINGS, tree, specs, direction=direction, page_number=1, template_id="5-classique")
    # gouttière verticale entre les cases 1 et 2 (bande du haut)
    g = next(g for g in before["gutters"] if g["path"] == [0] and g["index"] == 0)
    assert g["orientation"] == "vertical"
    # en rtl, la case 1 est à droite : agrandir la case 1 = déplacer la gouttière vers la gauche
    delta = 200 if direction == "ltr" else -200
    after = move_gutter(fmt, SETTINGS, before, specs, path=[0], index=0, position=g["position"] + delta)
    _check_geometry(after)
    b, a = _rects(before), _rects(after)
    assert a[2:] == b[2:]  # les autres bandes ne bougent pas
    assert after["panels"][0]["width"] == pytest.approx(before["panels"][0]["width"] + 200, abs=2)
    assert after["panels"][1]["width"] == pytest.approx(before["panels"][1]["width"] - 200, abs=2)
    ng = next(x for x in after["gutters"] if x["path"] == [0] and x["index"] == 0)
    assert ng["position"] == pytest.approx(g["position"] + delta, abs=1.5)

    # gouttière horizontale entre la bande 2 et la bande 3 : les cases 4 et 5 rétrécissent
    h = next(g for g in after["gutters"] if g["path"] == [] and g["index"] == 1)
    assert h["orientation"] == "horizontal"
    moved = move_gutter(fmt, SETTINGS, after, specs, path=[], index=1, position=h["position"] + 150)
    m = _rects(moved)
    assert m[:2] == a[:2]  # bande du haut intacte
    assert moved["panels"][2]["height"] == pytest.approx(after["panels"][2]["height"] + 150, abs=2)
    assert moved["panels"][3]["height"] == pytest.approx(after["panels"][3]["height"] - 150, abs=2)
    _check_geometry(moved)


def test_gutter_is_clamped_to_min_panel_size() -> None:
    fmt = PRESETS.page_format("a4-300dpi")
    tree = PRESETS.layout_template("2-colonnes").tree
    specs = _specs(2)
    lay = compute_layout(fmt, SETTINGS, tree, specs, direction="ltr", page_number=1, template_id="2-colonnes")
    after = move_gutter(fmt, SETTINGS, lay, specs, path=[], index=0, position=-10_000)
    min_px = fmt.mm_to_px(SETTINGS.min_panel_mm)
    assert after["panels"][0]["width"] >= min_px - 1
    _check_geometry(after)
    with pytest.raises(LayoutError, match="introuvable"):
        move_gutter(fmt, SETTINGS, lay, specs, path=[], index=3, position=10)
    with pytest.raises(LayoutError, match="introuvable"):
        move_gutter(fmt, SETTINGS, lay, specs, path=[0], index=0, position=10)


def test_nested_split_minimum_accounts_for_children() -> None:
    fmt = PRESETS.page_format("a4-300dpi")
    tree = PRESETS.layout_template("3-grand-cote").tree  # cols: panel | rows[2 cases]
    assert isinstance(tree, SplitNode)
    specs = _specs(3)
    lay = compute_layout(fmt, SETTINGS, tree, specs, direction="ltr", page_number=1, template_id="x")
    # on écrase la colonne de droite au maximum : ses deux sous-cases restent valides
    after = move_gutter(fmt, SETTINGS, lay, specs, path=[], index=0, position=99_999)
    _check_geometry(after)
    min_px = fmt.mm_to_px(SETTINGS.min_panel_mm)
    assert all(p["width"] >= min_px - 1 and p["height"] >= min_px - 1 for p in after["panels"])
