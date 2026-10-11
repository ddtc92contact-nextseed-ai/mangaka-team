"""Marge extérieure inviolable (#88) : aucune case, image, bordure, bulle ou onomatopée hors de la zone utile.

Test de propriété : tous les styles × tous les gabarits (et le choix du style) × 1 à 9 cases × plusieurs
graines × ltr / rtl, incrustations et débordements imposés ou non, retouches de gouttières et de biais
poussées à l'extrême. Chaque polygone de case et chaque boîte d'image est dans la zone utile, à 0 px
près ; deux cases de l'arbre qui ne débordent pas ne se recouvrent jamais ; une incrustation reste dans
sa case hôte.
"""

from __future__ import annotations

import itertools
import random
from pathlib import Path
from typing import Any

import pytest

from mangaka_engine.pipeline import geometry as geo
from mangaka_engine.pipeline.assembly import PageArt, PanelArt, canvas_geometry, render_png, render_svg
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.layout import (
    LayoutError,
    PanelSpec,
    clamp_to_live,
    move_gutter,
    set_cut_slant,
)
from mangaka_engine.pipeline.layout_style import styled_layout
from mangaka_engine.pipeline.lettering import Box, Letterer, SfxSpec
from mangaka_engine.presets import PresetRegistry
from tests.conftest import PRESETS_DIR
from tests.layout_render import COLORS, golden_format, synthetic_image

PRESETS = PresetRegistry.load(PRESETS_DIR)
SETTINGS = PRESETS.layout
A4 = PRESETS.page_format("a4-300dpi")
STYLES = ["sage", "dynamique", "nerveuse"]
INTENSITIES = [None, "calme", "normal", "choc"]
SHOTS = ["plan large", "plan moyen", "gros plan", "très gros plan"]


def _specs(n: int, rng: random.Random, *, break_out: bool, insets: bool) -> list[PanelSpec]:
    out = []
    for i in range(n):
        frame: dict[str, Any] = {}
        if break_out and rng.random() < 0.35:
            frame["break_out"] = True
        if insets and n >= 3 and rng.random() < 0.2:
            frame["inset"] = True
        if rng.random() < 0.1:
            frame["bleed"] = True  # ancienne option : ignorée
        out.append(
            PanelSpec(
                importance=rng.choice([1, 2, 2, 3]),
                dialogue_chars=rng.choice([0, 30, 200]),
                panel_id=i + 1,
                intensity=rng.choice(INTENSITIES),
                shot_type=rng.choice(SHOTS),
                frame=frame or None,
            )
        )
    return out


def assert_inside_live(layout: dict[str, Any]) -> None:
    live = layout["live_area"]
    lx1, ly1, lx2, ly2 = live["x1"], live["y1"], live["x2"], live["y2"]
    panels = layout["panels"]
    polys = []
    for p in panels:
        assert "bleed" not in p and "live_polygon" not in p, p
        poly = [(float(x), float(y)) for x, y in p["polygon"]]
        polys.append(poly)
        for x, y in poly + [(float(x), float(y)) for x, y in p.get("base_polygon") or []]:
            assert lx1 <= x <= lx2 and ly1 <= y <= ly2, (p, live)
        # boîte de l'image posée « au remplissage » : celle de la case
        assert lx1 <= p["x1"] < p["x2"] <= lx2 and ly1 <= p["y1"] < p["y2"] <= ly2, (p, live)
        z = p.get("bubble_zone")
        if z:
            assert p["x1"] <= z["x1"] and z["x2"] <= p["x2"] and p["y1"] <= z["y1"] and z["y2"] <= p["y2"], p
    # sans débordement, deux cases de l'arbre ne se recouvrent jamais
    plain = [i for i, p in enumerate(panels) if not p.get("inset") and not p.get("break_out")]
    for a, b in itertools.combinations(plain, 2):
        assert not geo.convex_overlap(polys[a], polys[b]), (panels[a], panels[b])
    # une incrustation est posée dans sa case hôte, jamais sur une autre case sans débordement
    for i, p in enumerate(panels):
        if p.get("inset"):
            host = panels[p["host_index"]]
            hpoly = [(float(x), float(y)) for x, y in (host.get("base_polygon") or host["polygon"])]
            assert geo.contains_box(geo.edges(hpoly), p["x1"], p["y1"], p["x2"], p["y2"]), (p, host)
            for j in plain:
                if j != p["host_index"]:
                    assert not geo.convex_overlap(polys[i], polys[j]), (p, panels[j])


def _pages() -> list[tuple[str, int, str, int, bool, bool, str | None]]:
    cases = []
    templates = list(PRESETS.layout_templates.values())
    for style in STYLES:
        for n in range(1, 10):
            ids: list[str | None] = [None, *(t.id for t in templates if t.panel_count == n)]
            for k, template in enumerate(ids):
                for direction in ("ltr", "rtl"):
                    for seed in range(6):
                        cases.append((style, n, direction, seed * 7 + k, seed % 2 == 0, seed % 3 != 1, template))
    return cases


PAGES = _pages()


@pytest.fixture(scope="module")
def fonts() -> FontBook:
    return FontBook(PRESETS)


@pytest.mark.parametrize("style", STYLES)
def test_every_page_stays_inside_the_live_area(style: str) -> None:
    checked = 0
    for st, n, direction, seed, break_out, insets, template in PAGES:
        if st != style:
            continue
        rng = random.Random(f"{st}:{n}:{direction}:{seed}:{template}")
        specs = _specs(n, rng, break_out=break_out, insets=insets)
        forced = (template, PRESETS.layout_templates[template].tree) if template else None
        try:
            layout = styled_layout(
                A4,
                SETTINGS,
                PRESETS.layout_style(style),
                list(PRESETS.layout_templates.values()),
                specs,
                direction=direction,  # type: ignore[arg-type]
                page_number=seed % 4 + 1,
                seed=seed,
                rythme=rng.choice([None, "lent", "rapide"]),
                forced=forced,
                page_choc=rng.random() < 0.3,
            )
        except LayoutError:
            continue  # gabarit imposé incompatible avec une incrustation : refusé, rien à dessiner
        assert_inside_live(layout)
        checked += 1
        # retouches à la main poussées à l'extrême : toujours dans la zone utile
        if layout["gutters"] and seed % 3 == 0:
            g = rng.choice(layout["gutters"])
            try:
                moved = move_gutter(
                    A4, SETTINGS, layout, specs, path=g["path"], index=g["index"], position=rng.choice([-1e5, 1e5])
                )
            except LayoutError:
                continue  # retouche refusée (incrustation qui ne tiendrait plus) : la page ne change pas
            assert_inside_live(moved)
            g = rng.choice(moved["gutters"])
            try:
                tilted = set_cut_slant(A4, SETTINGS, moved, specs, path=g["path"], index=g["index"], ends=[-1e5, 1e5])
            except LayoutError:
                continue
            assert_inside_live(tilted)
    assert checked > 100


def test_clamp_brings_an_old_bleed_page_back_inside() -> None:
    """Page stockée avant le garde-fou (case à fond perdu jusqu'au bord de la page) : coupée à la zone utile ;
    une case déjà dans la zone utile ne bouge pas."""
    specs = [PanelSpec(panel_id=i + 1, dialogue_chars=40) for i in range(3)]
    layout = styled_layout(
        A4,
        SETTINGS,
        PRESETS.layout_style("sage"),
        list(PRESETS.layout_templates.values()),
        specs,
        direction="ltr",
        page_number=1,
        seed=3,
    )
    live = layout["live_area"]
    old = {**layout, "panels": [dict(p) for p in layout["panels"]]}
    top = old["panels"][0]
    W = layout["page"]["width"]
    top.update(
        bleed=True,
        bleed_possible=True,
        live_polygon=top["polygon"],
        polygon=[[0, 0], [W, 0], [W, top["y2"]], [0, top["y2"]]],
        x1=0,
        y1=0,
        x2=W,
        y2=top["y2"],
    )
    old["frames"] = [{"frame": "border", "bleed": True, "inset": False}] + [
        {"frame": "border", "bleed": False, "inset": False}
    ] * 2
    fixed = clamp_to_live(old, SETTINGS)
    assert_inside_live(fixed)
    assert fixed["panels"][1:] == layout["panels"][1:]  # aucun saut pour les autres cases
    assert (fixed["panels"][0]["x1"], fixed["panels"][0]["y1"]) == (live["x1"], live["y1"])
    assert all("bleed" not in f for f in fixed["frames"])
    assert clamp_to_live(layout, SETTINGS) == layout  # déjà dans la zone utile : inchangée
    assert old["panels"][0]["x1"] == 0  # la mise en page d'origine n'est pas modifiée


def test_rendered_page_has_only_paper_in_the_margin_band(tmp_path: Path, fonts: FontBook) -> None:
    """Assemblage (PNG et SVG) : rien hors de la zone utile, même une case, une bulle ou une onomatopée
    qui en sortirait."""
    fmt = golden_format()
    specs = [PanelSpec(panel_id=i + 1, importance=3 if i == 0 else 2, frame={"break_out": i == 0}) for i in range(4)]
    layout = styled_layout(
        fmt,
        SETTINGS,
        PRESETS.layout_style("nerveuse"),
        list(PRESETS.layout_templates.values()),
        specs,
        direction="rtl",
        page_number=2,
        seed=11,
        page_choc=True,
    )
    assert_inside_live(layout)
    la = layout["live_area"]
    live = Box(la["x1"], la["y1"], la["x2"], la["y2"])
    panels = []
    for p in layout["panels"]:
        size = (p["target"]["width"], p["target"]["height"])
        img = synthetic_image(tmp_path / f"{p['index']}.png", size, COLORS[p["index"] % len(COLORS)])
        panels.append(
            PanelArt(
                p["index"] + 1,
                p["index"],
                Box(p["x1"], p["y1"], p["x2"], p["y2"]),
                img,
                polygon=[tuple(q) for q in p["polygon"]],
                inset=bool(p.get("inset")),
                break_out=bool(p.get("break_out")),
            )
        )
    # une case qui sortirait quand même (mise en page corrompue) : coupée au rendu
    panels.append(PanelArt(99, len(panels), Box(0, 0, 80, 80), None))
    from mangaka_engine.pipeline.lettering import PanelSpec as LetterSpec

    first = layout["panels"][0]
    lspec = LetterSpec(
        id=1,
        index=0,
        box=Box(first["x1"], first["y1"], first["x2"], first["y2"]),
        polygon=[tuple(q) for q in first["polygon"]],
        # onomatopée placée à la main dans le coin de la page : ramenée dans la zone utile
        sfx=[SfxSpec(id=7, text="BADABOUM !", intensity="choc", center=(2.0, 2.0))],
    )
    lettering = Letterer(fonts, PRESETS.lettering, fmt.dpi).letter_page([lspec], "rtl", live)
    for s in lettering.sfx:
        for x, y in s.quad:
            assert live.x1 - 1e-6 <= x <= live.x2 + 1e-6 and live.y1 - 1e-6 <= y <= live.y2 + 1e-6
    art = PageArt(number=2, fmt=fmt, panels=panels, lettering=lettering, live=live)
    for bleed in (False, True):
        canvas = canvas_geometry(fmt, PRESETS.lettering, bleed=bleed)
        img = render_png(art, fonts, PRESETS.lettering, canvas)
        x1, y1 = round(live.x1) + canvas.ox, round(live.y1) + canvas.oy
        x2, y2 = round(live.x2) + canvas.ox, round(live.y2) + canvas.oy
        paper = (255, 255, 255)
        px = img.load()
        for y in range(img.height):
            for x in range(img.width):
                if x1 <= x < x2 and y1 <= y < y2:
                    continue
                assert px[x, y] == paper, (bleed, x, y)
        # la zone utile, elle, est dessinée
        assert px[(x1 + x2) // 2, (y1 + y2) // 2] != paper
        svg = render_svg(art, fonts, PRESETS.lettering, canvas)
        assert 'clip-path="url(#zone-utile)"' in svg
        assert f'<clipPath id="zone-utile"><rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}"/>' in svg
