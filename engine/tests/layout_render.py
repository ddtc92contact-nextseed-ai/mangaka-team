"""Rendu d'une mise en page complète (découpage → images synthétiques → lettrage → PNG) pour les tests « golden ».

Une page A5 à 100 DPI, quatre cases d'importance 3, 2, 2, 1, des bulles dans trois cases, des images de
case déterministes générées à la taille cible de chaque case (comme ComfyUI le ferait).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from mangaka_engine.pipeline.assembly import PageArt, PanelArt, canvas_geometry, render_png
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.lettering import Box, BubbleSpec, Letterer, SfxSpec
from mangaka_engine.pipeline.lettering import PanelSpec as LetterSpec
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import Gutters, Margins, PageFormat

IMPORTANCES = [3, 2, 2, 1]
BUBBLES = {
    0: [("speech", "Tu as vu ça ? Le ciel se déchire !", "Aiko"), ("thought", "Encore lui…", "Ren")],
    1: [("shout", "Cours !!", "Ren")],
    2: [("narration", "Au même instant, de l'autre côté du fleuve…", "")],
}
COLORS = [
    ((70, 110, 160), (30, 60, 90)),
    ((180, 90, 70), (120, 50, 40)),
    ((90, 150, 90), (40, 90, 50)),
    ((150, 120, 170), (90, 60, 110)),
]


def golden_format() -> PageFormat:
    return PageFormat(
        id="golden-a5",
        name="A5 — 100 DPI (tests)",
        width_mm=148,
        height_mm=210,
        dpi=100,
        bleed_mm=3,
        margins_mm=Margins(top=10, bottom=10, inner=10, outer=8),
        gutters_mm=Gutters(horizontal=4, vertical=3),
    )


def dialogue_chars(i: int) -> int:
    return sum(len(text) for _, text, _ in BUBBLES.get(i, []))


def synthetic_image(path: Path, size: tuple[int, int], colors: tuple[tuple[int, int, int], ...]) -> Path:
    img = Image.new("RGB", size, colors[0])
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.polygon([(0, h), (w, h * 0.35), (w, h)], fill=colors[1])
    draw.ellipse((w * 0.4, h * 0.3, w * 0.6, h * 0.6), fill=(250, 220, 190), outline=(40, 40, 40), width=3)
    img.save(path, format="PNG")
    return path


def render_layout(
    tmp: Path,
    presets: PresetRegistry,
    fonts: FontBook,
    layout: dict[str, Any],
    *,
    sfx: dict[int, list[SfxSpec]] | None = None,
    bubbles: dict[int, list[tuple[str, str, str]]] | None = None,
    crop_marks: bool = False,
) -> Image.Image:
    fmt = golden_format()
    panels: list[PanelArt] = []
    specs: list[LetterSpec] = []
    bubbles = BUBBLES if bubbles is None else bubbles
    for lp in layout["panels"]:
        i = lp["index"]
        box = Box(lp["x1"], lp["y1"], lp["x2"], lp["y2"])
        size = (lp["target"]["width"], lp["target"]["height"])
        img = synthetic_image(tmp / f"case-{i}.png", size, COLORS[i % len(COLORS)])
        polygon = lp.get("polygon")
        extra: dict[str, Any] = {"polygon": [tuple(p) for p in polygon]} if polygon else {}
        panels.append(
            PanelArt(i + 1, i, box, img, size, frame=lp.get("frame", "border"), inset=bool(lp.get("inset")), **extra)
        )
        # Lettrage dans la zone utile (fond perdu : partie de la case dans la zone utile).
        live = lp.get("live_polygon")
        lbox, lextra = box, extra
        if live:
            xs, ys = [p[0] for p in live], [p[1] for p in live]
            lbox, lextra = Box(min(xs), min(ys), max(xs), max(ys)), {"polygon": [tuple(p) for p in live]}
        zone = lp.get("bubble_zone")
        insets = [
            Box(q["x1"], q["y1"], q["x2"], q["y2"])
            for q in layout["panels"]
            if q.get("inset") and q.get("host_index") == i
        ]
        specs.append(
            LetterSpec(
                id=i + 1,
                index=i,
                box=lbox,
                zone=Box(zone["x1"], zone["y1"], zone["x2"], zone["y2"]) if zone else None,
                bubbles=[
                    BubbleSpec(10 * (i + 1) + j, kind, text, who, j)
                    for j, (kind, text, who) in enumerate(bubbles.get(i, []))
                ],
                sfx=list((sfx or {}).get(i, [])),
                obstacles=insets,
                **lextra,
            )
        )
    page = Box(0, 0, fmt.width_px, fmt.height_px)
    lettering = Letterer(fonts, presets.lettering, fmt.dpi).letter_page(specs, layout["direction"], page)
    art = PageArt(number=layout["page_number"], fmt=fmt, panels=panels, lettering=lettering)
    canvas = canvas_geometry(fmt, presets.lettering, bleed=True, crop_marks=crop_marks)
    return render_png(art, fonts, presets.lettering, canvas)
