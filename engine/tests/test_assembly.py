"""Étape 5 : assemblage de la planche, PNG 300 DPI, SVG vectoriel, fond perdu, image de référence.

Image de référence (« golden ») : `tests/golden/planche-reference.png`, une page A5 à 100 DPI avec
les cinq types de bulle, une case sans image, un visage à éviter, fond perdu et repères de coupe.
Le rendu doit être identique d'un run à l'autre (comparaison exacte) et rester identique à la
référence ; seule une infime marge d'anticrénelage est tolérée (≤ 0,05 % des pixels écartés de plus de
24 niveaux), pour ne pas dépendre de l'architecture du processeur. Toute PR qui change la référence
doit le justifier ; pour la régénérer : `MANGAKA_UPDATE_GOLDEN=1 npm run test:engine`.
"""

from __future__ import annotations

import base64
import io
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw

from mangaka_engine.pipeline.assembly import (
    PageArt,
    PanelArt,
    canvas_geometry,
    png_bytes,
    render_png,
    render_svg,
)
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.lettering import Box, BubbleSpec, Letterer, PanelSpec
from mangaka_engine.pipeline.render import faces_on_page
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import Gutters, Margins, PageFormat
from tests.conftest import PRESETS_DIR

GOLDEN = Path(__file__).parent / "golden" / "planche-reference.png"
ACCENTS = "Élan : « Où ça ? » — à l'œuvre, ça déçoit, garçon ! È Ç Œ ê ë ï ô ù"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


@pytest.fixture(scope="module")
def presets() -> PresetRegistry:
    reg = PresetRegistry.load(PRESETS_DIR)
    assert reg.issues == []
    return reg


@pytest.fixture(scope="module")
def fonts(presets: PresetRegistry) -> FontBook:
    return FontBook(presets)


# --- géométrie -------------------------------------------------------------------------------
def test_bleed_geometry_a4_300dpi(presets: PresetRegistry) -> None:
    a4 = presets.page_format("a4-300dpi")
    plain = canvas_geometry(a4, presets.lettering)
    assert (plain.width, plain.height, plain.ox, plain.oy) == (2480, 3508, 0, 0)
    bleed = canvas_geometry(a4, presets.lettering, bleed=True)
    # (210 + 2 × 3) / 25,4 × 300 = 2551,18 → 2551 ; (297 + 6) / 25,4 × 300 = 3578,74 → 3579
    assert (bleed.width, bleed.height) == (2551, 3579)
    assert (bleed.ox, bleed.oy, bleed.bleed) == (35, 35, 35)  # 3 / 25,4 × 300 = 35,43
    assert (bleed.trim_w, bleed.trim_h) == (2480, 3508)
    marks = canvas_geometry(a4, presets.lettering, bleed=True, crop_marks=True)
    # + 9 mm de bande pour les repères de chaque côté : (210 + 24) / 25,4 × 300 = 2763,78 → 2764
    assert (marks.width, marks.height, marks.ox) == (2764, 3791, 142)
    b4 = canvas_geometry(presets.page_format("b4-300dpi"), presets.lettering, bleed=True)
    assert (b4.width, b4.height) == (3106, 4370)


def test_bleed_value_lives_in_page_format_preset(presets: PresetRegistry) -> None:
    for fmt in presets.page_formats.values():
        assert fmt.bleed_mm == 3


# --- page de référence --------------------------------------------------------------------------
def _fmt() -> PageFormat:
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


def _synthetic(
    path: Path, size: tuple[int, int], colors: tuple[tuple[int, int, int], tuple[int, int, int]], face: Box
) -> Path:
    """Image de case déterministe : deux aplats en diagonale + un « visage » clair (`face`, en px de l'image)."""
    img = Image.new("RGB", size, colors[0])
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.polygon([(0, h), (w, h * 0.35), (w, h)], fill=colors[1])
    draw.ellipse((face.x1, face.y1, face.x2, face.y2), fill=(250, 220, 190), outline=(40, 40, 40), width=3)
    img.save(path, format="PNG")
    return path


# Visage de la case 1, en px de l'image : en haut à droite, là où irait la 1re bulle en rtl.
FACE_1 = Box(560, 40, 760, 300)


def reference_page(tmp: Path, presets: PresetRegistry, fonts: FontBook, *, direction: str = "rtl") -> PageArt:
    fmt = _fmt()
    p1 = Box(39, 39, 551, 400)  # pleine largeur en haut
    p2 = Box(318, 416, 551, 788)
    p3 = Box(39, 416, 306, 788)  # case sans image
    img1 = _synthetic(tmp / "c1.png", (832, 576), ((70, 110, 160), (30, 60, 90)), FACE_1)
    img2 = _synthetic(tmp / "c2.png", (544, 864), ((180, 90, 70), (120, 50, 40)), Box(300, 420, 460, 640))
    face = faces_on_page([FACE_1], (832, 576), p1)[0]  # boîte du QC ramenée en px de la page
    specs = [
        PanelSpec(
            id=1,
            index=0,
            box=p1,
            zone=Box(255, 47, 543, 190),
            faces=[face],
            characters=["Aiko", "Ren"],
            bubbles=[
                BubbleSpec(1, "speech", "« Où est passé le cœur de la forêt ? » C'est incompréhensible !", "Aiko", 0),
                BubbleSpec(2, "thought", "Je me demande s'il viendra…", "Aiko", 1),
            ],
        ),
        PanelSpec(
            id=2,
            index=1,
            box=p2,
            zone=Box(326, 424, 543, 560),
            characters=["Ren"],
            bubbles=[
                BubbleSpec(3, "shout", "Attention !!", "Ren", 0),
                BubbleSpec(4, "off", "Ça suffit, garçon !", "Voix", 1),
            ],
        ),
        PanelSpec(
            id=3,
            index=2,
            box=p3,
            zone=Box(47, 424, 260, 540),
            bubbles=[BubbleSpec(5, "narration", "Pendant ce temps, à l'autre bout de la ville…", "", 0)],
        ),
    ]
    lettering = Letterer(fonts, presets.lettering, fmt.dpi).letter_page(specs, direction)  # type: ignore[arg-type]
    return PageArt(
        number=1,
        fmt=fmt,
        panels=[
            PanelArt(1, 0, p1, img1, (832, 576)),
            PanelArt(2, 1, p2, img2, (544, 864)),
            PanelArt(3, 2, p3, None, None),
        ],
        lettering=lettering,
        warnings=lettering.warnings,
    )


def _render(tmp: Path, presets: PresetRegistry, fonts: FontBook) -> Image.Image:
    art = reference_page(tmp, presets, fonts)
    canvas = canvas_geometry(art.fmt, presets.lettering, bleed=True, crop_marks=True)
    return render_png(art, fonts, presets.lettering, canvas)


def test_golden_reference_page(tmp_path: Path, presets: PresetRegistry, fonts: FontBook) -> None:
    first = _render(tmp_path, presets, fonts)
    second = _render(tmp_path, presets, fonts)
    assert first.tobytes() == second.tobytes(), "le rendu n'est pas déterministe"
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
    total = first.width * first.height
    if changed > total * 0.0005:
        first.save(tmp_path / "rendu.png")
        pytest.fail(
            f"la planche de référence a changé ({changed} px sur {total}) — rendu : {tmp_path / 'rendu.png'} ; "
            "si c'est voulu, régénère-la (MANGAKA_UPDATE_GOLDEN=1) et justifie-le dans la PR"
        )


def test_reference_page_avoids_face_and_flags_missing_panel(
    tmp_path: Path, presets: PresetRegistry, fonts: FontBook
) -> None:
    art = reference_page(tmp_path, presets, fonts)
    face = faces_on_page([FACE_1], (832, 576), art.panels[0].box)[0]
    assert not any(b.box.intersects(face) for b in art.lettering.bubbles if b.panel_id == 1)
    assert not any(b.overflow for b in art.lettering.bubbles)
    first = next(b for b in art.lettering.bubbles if b.id == 1)
    assert first.tail is not None


# --- PNG -------------------------------------------------------------------------------------
def test_png_has_300_dpi_metadata() -> None:
    data = png_bytes(Image.new("RGB", (10, 10), "white"), 300)
    with Image.open(io.BytesIO(data)) as im:
        dpi = im.info["dpi"]
    assert tuple(round(v) for v in dpi) == (300, 300)


def test_french_accents_have_real_glyphs_in_every_style(fonts: FontBook) -> None:
    """Chaque caractère accentué existe dans la police et n'est pas dessiné comme sa lettre de base."""
    pairs = [("é", "e"), ("è", "e"), ("à", "a"), ("ç", "c"), ("œ", "o"), ("«", "<"), ("»", ">"), ("É", "E"), ("Ç", "C")]
    styles = [*fonts.preset.styles.values(), fonts.preset.missing_panel]
    for style in styles:
        font = fonts.pil(style, 60)
        for accented, base in pairs:
            assert fonts.has_char(style, accented), f"{style.font} : « {accented} » absent"
            masks = []
            for ch in (accented, base):
                im = Image.new("L", (90, 110), 0)
                ImageDraw.Draw(im).text((10, 90), ch, font=font, fill=255, anchor="ls")
                masks.append(im)
            assert ImageChops.difference(*masks).getbbox() is not None, f"{style.font} : « {accented} » = « {base} »"


def test_png_draws_the_accented_text(tmp_path: Path, presets: PresetRegistry, fonts: FontBook) -> None:
    """Le texte accentué est bien posé dans le PNG : le même texte sans accents donne une autre image."""
    art = reference_page(tmp_path, presets, fonts)
    canvas = canvas_geometry(art.fmt, presets.lettering)
    with_accents = render_png(art, fonts, presets.lettering, canvas)
    bubble = next(b for b in art.lettering.bubbles if b.id == 1)
    for line in bubble.lines:
        object.__setattr__(
            line, "text", line.text.replace("ù", "u").replace("ê", "e").replace("œ", "oe").replace("é", "e")
        )
    without = render_png(art, fonts, presets.lettering, canvas)
    box = bubble.box
    region = (round(box.x1), round(box.y1), round(box.x2), round(box.y2))
    assert ImageChops.difference(with_accents.crop(region), without.crop(region)).getbbox() is not None


# --- SVG -------------------------------------------------------------------------------------
def _svg(tmp: Path, presets: PresetRegistry, fonts: FontBook, text: str | None = None) -> tuple[str, ET.Element]:
    art = reference_page(tmp, presets, fonts)
    if text is not None:
        spec = PanelSpec(id=9, index=3, box=Box(39, 39, 551, 400), bubbles=[BubbleSpec(9, "speech", text, "Aiko", 0)])
        lettering = Letterer(fonts, presets.lettering, art.fmt.dpi).letter_page([spec], "ltr")
        art.lettering.bubbles = lettering.bubbles
    svg = render_svg(art, fonts, presets.lettering, canvas_geometry(art.fmt, presets.lettering, bleed=True))
    return svg, ET.fromstring(svg.encode("utf-8"))


def test_svg_text_is_real_selectable_text_with_embedded_fonts(
    tmp_path: Path, presets: PresetRegistry, fonts: FontBook
) -> None:
    svg, root = _svg(tmp_path, presets, fonts)
    # A5 + 2 × 3 mm ; même taille physique que le PNG (606 × 850 px à 100 DPI).
    assert root.get("width") == f"{606 / 100 * 25.4:.3f}mm" and root.get("height") == f"{850 / 100 * 25.4:.3f}mm"
    assert root.get("viewBox") == "0 0 606 850"
    texts = root.findall(".//svg:g[@id='bulles']//svg:text", SVG_NS)
    assert len(texts) == 5
    spoken = " ".join("".join(t.itertext()) for t in texts)
    assert "incompréhen" in spoken and "cœur" in spoken and "forêt" in spoken
    assert "Ça suffit" in spoken or "ÇA SUFFIT" in spoken
    style = root.find(".//svg:style", SVG_NS)
    assert style is not None and style.text and "@font-face" in style.text
    for t in texts:
        assert t.get("font-family", "").startswith("mk-")
        assert t.get("font-family") in style.text
    images = root.findall(".//svg:image", SVG_NS)
    assert len(images) == 2 and all(i.get("preserveAspectRatio") == "xMidYMid slice" for i in images)
    assert "case manquante" in svg.lower()
    assert "<text" in svg and svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_svg_keeps_french_accents_and_embeds_their_glyphs(
    tmp_path: Path, presets: PresetRegistry, fonts: FontBook
) -> None:
    svg, root = _svg(tmp_path, presets, fonts, text=ACCENTS)
    text = next(iter(root.findall(".//svg:g[@id='bulles']//svg:text", SVG_NS)))
    drawn = "".join(text.itertext()).replace(" ", " ")
    for ch in "ÉàçœÈÇŒêëïôù«»—":
        assert ch in drawn, ch
    style = root.find(".//svg:style", SVG_NS)
    assert style is not None and style.text
    family = text.get("font-family")
    chunk = style.text.split(f'font-family:"{family}";src:url(data:font/ttf;base64,', 1)[1].split(")", 1)[0]
    font = TTFont(io.BytesIO(base64.b64decode(chunk)))
    cmap = font.getBestCmap()
    for ch in "ÉàçœÈÇŒêëïôù«»":
        assert ord(ch) in cmap, ch
    # Nom de la police embarquée : pas de nom réservé (OFL, clause 3).
    assert font["name"].getDebugName(1) == family
