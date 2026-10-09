"""Comic Neue : famille statique (Regular / Bold / Italic) choisie par la graisse et l'italique du style.

Les styles par défaut ne l'utilisent pas : ces tests basculent des styles sur Comic Neue en mémoire.
Image de référence : `tests/golden/bulle-comic-neue.png` (trois bulles, A6 à 100 DPI) ; même règle de
comparaison et de régénération que la planche de référence (`MANGAKA_UPDATE_GOLDEN=1 npm run test:engine`).
"""

from __future__ import annotations

import base64
import dataclasses
import io
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw, ImageFont

from mangaka_engine.pipeline.assembly import PageArt, PanelArt, canvas_geometry, render_png, render_svg
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.lettering import Box, BubbleSpec, Letterer, PanelSpec
from mangaka_engine.presets import PresetError, PresetRegistry
from mangaka_engine.presets.schemas import FontsPreset, Gutters, Margins, PageFormat
from tests.conftest import PRESETS_DIR

GOLDEN = Path(__file__).parent / "golden" / "bulle-comic-neue.png"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
FONTS_DIR = PRESETS_DIR / "fonts"
TEXT = "« Élève ! » Ça ? Garçon, à l'œuvre : c'est déçu."
# Style de la bulle → (fichier Comic Neue attendu, graisse, italique)
VARIANTS = {
    "speech": ("ComicNeue-Regular.ttf", 400, False),
    "shout": ("ComicNeue-Bold.ttf", 700, False),
    "thought": ("ComicNeue-Italic.ttf", 400, True),
}


@pytest.fixture(scope="module")
def presets() -> PresetRegistry:
    reg = PresetRegistry.load(PRESETS_DIR)
    assert reg.issues == []
    return reg


@pytest.fixture(scope="module")
def comic(presets: PresetRegistry) -> FontBook:
    """Registre dont parole / cri / pensée sont passés en Comic Neue Regular / Bold / Italic."""
    preset = presets.require_fonts()
    styles = dict(preset.styles)
    for kind, (_, weight, italic) in VARIANTS.items():
        styles[kind] = styles[kind].model_copy(
            update={"font": "comic-neue", "weight": weight, "italic": italic, "uppercase": False}
        )
    reg = PresetRegistry(root=presets.root, lettering=presets.lettering)
    reg.fonts = FontsPreset.model_validate(
        {**preset.model_dump(), "styles": {k: v.model_dump() for k, v in styles.items()}}
    )
    return FontBook(reg)


# --- preset ----------------------------------------------------------------------------------
def test_comic_neue_is_registered_with_its_family_and_license(presets: PresetRegistry) -> None:
    font = presets.require_fonts().fonts["comic-neue"]
    assert font.name == "Comic Neue"
    for name in ("ComicNeue-Regular.ttf", "ComicNeue-Bold.ttf", "ComicNeue-Italic.ttf", "ComicNeue-BoldItalic.ttf"):
        assert (FONTS_DIR / name).is_file()
    assert "Comic Neue Project Authors" in (FONTS_DIR / "OFL-ComicNeue.txt").read_text()
    assert "Comic Neue Project Authors" in (FONTS_DIR / "OFL.txt").read_text()
    # Graisse ≥ 600 → gras ; italique → italique ; les deux → gras italique.
    path = presets.font_path
    assert path("comic-neue").name == "ComicNeue-Regular.ttf"
    assert path("comic-neue", 400).name == "ComicNeue-Regular.ttf"
    assert path("comic-neue", 700).name == "ComicNeue-Bold.ttf"
    assert path("comic-neue", 400, True).name == "ComicNeue-Italic.ttf"
    assert path("comic-neue", 700, True).name == "ComicNeue-BoldItalic.ttf"
    # Police variable : un seul fichier, la graisse est instanciée.
    assert path("baloo2", 700).name == "Baloo2.ttf"
    with pytest.raises(PresetError, match="italique"):
        path("baloo2", 400, True)


def test_default_styles_are_unchanged(presets: PresetRegistry) -> None:
    styles = presets.require_fonts().styles
    assert (styles["speech"].font, styles["speech"].weight) == ("baloo2", 600)
    assert not any(s.font == "comic-neue" or s.italic for s in styles.values())


def test_italic_style_requires_an_italic_file(presets: PresetRegistry) -> None:
    data = presets.require_fonts().model_dump()
    data["styles"]["speech"]["italic"] = True  # Baloo 2 n'a pas d'italique
    with pytest.raises(ValueError, match="pas de fichier italique"):
        FontsPreset.model_validate(data)


# --- rendu -----------------------------------------------------------------------------------
def _fmt() -> PageFormat:
    return PageFormat(
        id="golden-a6",
        name="A6 — 100 DPI (tests)",
        width_mm=105,
        height_mm=148,
        dpi=100,
        bleed_mm=3,
        margins_mm=Margins(top=6, bottom=6, inner=6, outer=6),
        gutters_mm=Gutters(horizontal=3, vertical=3),
    )


def sample_page(fonts: FontBook, presets: PresetRegistry) -> PageArt:
    """Trois cases sans image, une bulle chacune : Regular (parole), Bold (cri), Italic (pensée)."""
    fmt = _fmt()
    boxes = [Box(24, 24, 389, 196), Box(24, 208, 389, 380), Box(24, 392, 389, 559)]
    specs = [
        PanelSpec(
            id=i + 1,
            index=i,
            box=box,
            zone=Box(box.x1 + 8, box.y1 + 8, box.x2 - 8, box.y2 - 8),
            bubbles=[BubbleSpec(i + 1, kind, TEXT, "Aiko", 0)],
        )
        for i, (box, kind) in enumerate(zip(boxes, VARIANTS, strict=True))
    ]
    lettering = Letterer(fonts, presets.lettering, fmt.dpi).letter_page(specs, "ltr")
    panels = [PanelArt(s.id, s.index, s.box) for s in specs]
    return PageArt(number=1, fmt=fmt, panels=panels, lettering=lettering, warnings=lettering.warnings)


def test_styles_use_the_right_comic_neue_file(comic: FontBook) -> None:
    """La police servie au rendu a les contours du bon fichier Comic Neue (pas d'un autre, pas d'un repli)."""
    drawn = {}
    for kind, (file, _, _) in VARIANTS.items():
        style = comic.style(kind)
        assert comic.name(style) == "Comic Neue"
        assert comic.family(style).startswith("mk-comic-neue-")
        ours = comic.pil(style, 48)
        original = ImageFont.truetype(str(FONTS_DIR / file), size=48, layout_engine=ImageFont.Layout.BASIC)
        images = []
        for font in (ours, original):
            im = Image.new("L", (1400, 70), 0)
            ImageDraw.Draw(im).text((5, 55), comic.drawable(style, TEXT), font=font, fill=255, anchor="ls")
            images.append(im)
        assert ImageChops.difference(*images).getbbox() is None, f"{kind} : glyphes ≠ {file}"
        for ch in "éèàçœ«»ÉÇŒ":
            assert comic.has_char(style, ch), f"{kind} : « {ch} » absent"
        drawn[kind] = images[0]
    # Regular, Bold et Italic sont bien trois dessins différents.
    assert ImageChops.difference(drawn["speech"], drawn["shout"]).getbbox() is not None
    assert ImageChops.difference(drawn["speech"], drawn["thought"]).getbbox() is not None


def test_png_and_svg_embed_comic_neue_with_french_accents(
    tmp_path: Path, presets: PresetRegistry, comic: FontBook
) -> None:
    art = sample_page(comic, presets)
    assert len(art.lettering.bubbles) == 3 and not any(b.overflow for b in art.lettering.bubbles)
    canvas = canvas_geometry(art.fmt, presets.lettering, bleed=True)

    # PNG : chaque bulle est dessinée en Comic Neue — les mêmes lignes posées en Baloo 2 donnent une autre image.
    png = render_png(art, comic, presets.lettering, canvas)
    swapped = [
        dataclasses.replace(b, style=b.style.model_copy(update={"font": "baloo2", "italic": False}))
        for b in art.lettering.bubbles
    ]
    other = dataclasses.replace(art, lettering=dataclasses.replace(art.lettering, bubbles=swapped))
    baloo = render_png(other, comic, presets.lettering, canvas)
    for b in art.lettering.bubbles:
        region = (round(b.box.x1 + canvas.ox), round(b.box.y1 + canvas.oy))
        region += (round(b.box.x2 + canvas.ox), round(b.box.y2 + canvas.oy))
        assert ImageChops.difference(png.crop(region), baloo.crop(region)).getbbox() is not None

    # SVG : texte réel en `mk-comic-neue-…`, police embarquée = sous-ensemble du bon fichier.
    svg = render_svg(art, comic, presets.lettering, canvas)
    root = ET.fromstring(svg.encode("utf-8"))
    style = root.find(".//svg:style", SVG_NS)
    assert style is not None and style.text
    texts = root.findall(".//svg:g[@id='bulles']//svg:text", SVG_NS)
    assert len(texts) == 3
    by_family = {t.get("font-family"): "".join(t.itertext()).replace(" ", " ") for t in texts}
    for kind, (file, _, _) in VARIANTS.items():
        family = comic.family(comic.style(kind))
        assert family in by_family, family
        for ch in "ÉèàçœÇ«»":
            assert ch in by_family[family], (kind, ch)
        chunk = style.text.split(f'font-family:"{family}";src:url(data:font/ttf;base64,', 1)[1].split(")", 1)[0]
        embedded = TTFont(io.BytesIO(base64.b64decode(chunk)))
        source = TTFont(FONTS_DIR / file)
        assert "Comic Neue Project Authors" in embedded["name"].getDebugName(0)
        assert embedded["name"].getDebugName(1) == family  # renommée (OFL, clause 3)
        cmap, src_cmap = embedded.getBestCmap(), source.getBestCmap()
        for ch in "éèàçœ«»ÉÇ":
            assert ord(ch) in cmap, (kind, ch)
            ours = embedded["glyf"][cmap[ord(ch)]]
            theirs = source["glyf"][src_cmap[ord(ch)]]
            ours.expand(embedded["glyf"])
            theirs.expand(source["glyf"])
            assert ours.getCoordinates(embedded["glyf"])[0] == theirs.getCoordinates(source["glyf"])[0], (kind, ch)


def test_golden_comic_neue_bubbles(tmp_path: Path, presets: PresetRegistry, comic: FontBook) -> None:
    art = sample_page(comic, presets)
    canvas = canvas_geometry(art.fmt, presets.lettering, bleed=True)
    first = render_png(art, comic, presets.lettering, canvas)
    assert first.tobytes() == render_png(art, comic, presets.lettering, canvas).tobytes(), "rendu non déterministe"
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
        pytest.fail(f"la bulle Comic Neue de référence a changé ({changed} px sur {total}) : {tmp_path / 'rendu.png'}")
