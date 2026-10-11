"""Planche de démonstration des queues : python demo.py <racine du dépôt> <sortie sans extension>."""
import sys
from pathlib import Path

root, out = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(root / "engine"))
from mangaka_engine.pipeline.assembly import PageArt, PanelArt, canvas_geometry, render_png, render_svg
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.lettering import Box, BubbleSpec, Letterer, PanelSpec
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import Gutters, Margins, PageFormat

presets = PresetRegistry.load(root / "presets")
fonts = FontBook(presets)
fmt = PageFormat(id="demo", name="demo", width_mm=105, height_mm=148, dpi=200, bleed_mm=0,
                 margins_mm=Margins(top=6, bottom=6, inner=6, outer=6), gutters_mm=Gutters(horizontal=3, vertical=3))
W, H = 827, 1165
boxes = [Box(40, 40, 410, 560), Box(420, 40, 787, 560), Box(40, 570, 410, 1125), Box(420, 570, 787, 1125)]
T = "Où est passé l'élève ? Ça m'inquiète…"
bubbles = [
    [BubbleSpec(1, "speech", T, "Aiko", 0), BubbleSpec(2, "speech", "Là-bas !", "Ren", 1,
        manual_box=Box(220, 330, 390, 430), manual_tail=(250, 530))],
    [BubbleSpec(3, "shout", "ARRÊTE ÇA !", "Ren", 0), BubbleSpec(4, "shout", "NON !", "Aiko", 1,
        manual_box=Box(600, 380, 760, 480), manual_tail=(480, 520))],
    [BubbleSpec(5, "thought", "Peut-être qu'il a raison…", "Aiko", 0)],
    [BubbleSpec(6, "off", "Je suis là, derrière !", "Ren", 0), BubbleSpec(7, "speech", "Hein ?", "Aiko", 1,
        manual_box=Box(470, 850, 620, 940), manual_tail=(760, 900))],
]
specs = [PanelSpec(id=i + 1, index=i, box=b, bubbles=bb) for i, (b, bb) in enumerate(zip(boxes, bubbles))]
lettering = Letterer(fonts, presets.lettering, fmt.dpi).letter_page(specs, "ltr")
art = PageArt(number=1, fmt=fmt, panels=[PanelArt(s.id, s.index, s.box) for s in specs], lettering=lettering)
canvas = canvas_geometry(fmt, presets.lettering)
render_png(art, fonts, presets.lettering, canvas).convert("RGB").save(out + ".png")
Path(out + ".svg").write_text(render_svg(art, fonts, presets.lettering, canvas))
