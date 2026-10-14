"""Étape 5 : texte (retour à la ligne, césure, taille), placement des bulles, queues."""

from __future__ import annotations

import math

import pytest

from mangaka_engine.pipeline.fonts import NBSP, FontBook
from mangaka_engine.pipeline.lettering import (
    Box,
    BubbleLayout,
    BubbleSpec,
    Letterer,
    PanelSpec,
    SfxSpec,
    miter_ratio,
    normalize_text,
    split_options,
    stroke_outline,
    wrap_text,
)
from mangaka_engine.presets import PresetRegistry
from tests.conftest import PRESETS_DIR


@pytest.fixture(scope="module")
def presets() -> PresetRegistry:
    return PresetRegistry.load(PRESETS_DIR)


@pytest.fixture(scope="module")
def letterer(presets: PresetRegistry) -> Letterer:
    return Letterer(FontBook(presets), presets.lettering, 300)


def _joined(lines: list[str]) -> str:
    """Texte reconstitué : une coupure par césure (« -» ajouté) recolle le mot."""
    out = ""
    for line in lines:
        if out.endswith("-") and not out.endswith(" -") and out[-2:-1].isalpha():
            out = out[:-1] + line
        else:
            out = f"{out} {line}" if out else line
    return out


# --- texte -----------------------------------------------------------------------------------
def test_french_typography_uses_non_breaking_spaces() -> None:
    assert normalize_text("« Bonjour ! »  Ça va ?") == f"«{NBSP}Bonjour{NBSP}!{NBSP}» Ça va{NBSP}?"
    assert normalize_text("«Salut»: oui;non") == f"«{NBSP}Salut{NBSP}»{NBSP}: oui{NBSP};non"
    assert normalize_text("cri", uppercase=True) == "CRI"
    assert normalize_text("Œuvre à cœur", uppercase=True) == "ŒUVRE À CŒUR"


def test_wrap_breaks_on_spaces_and_never_on_non_breaking_spaces() -> None:
    text = normalize_text("Il a dit « oui » puis il est parti ! Vraiment ?")
    lines = wrap_text(text, len, 14)
    assert all(len(line) <= 14 for line in lines)
    assert _joined(lines) == text
    for line in lines:
        assert not line.startswith(("!", "?", "»", NBSP))
        assert not line.endswith("«")


def test_wrap_hyphenates_long_french_words_with_pyphen() -> None:
    lines = wrap_text("incompréhensiblement", len, 10)
    assert len(lines) > 1
    assert all(len(line) <= 10 for line in lines)
    assert lines[0].endswith("-")
    assert _joined(lines) == "incompréhensiblement"
    # Points de césure du dictionnaire français : jamais au milieu d'une syllabe.
    heads = [h for h, _ in split_options("extraordinairement")]
    assert "extraordinaire-" in heads and "ex-" in heads
    assert all(not h.startswith("e-") for h in heads)


def test_wrap_does_not_hyphenate_short_words_or_when_line_is_nearly_full() -> None:
    assert split_options("chaton") != [] and split_options("chat") == []
    # « magnifique » tient seul : la ligne « Une maison » est assez pleine, on passe à la ligne.
    assert wrap_text("Une maison magnifique", len, 12) == ["Une maison", "magnifique"]
    # Ligne presque vide : on coupe plutôt que de laisser un trou.
    lines = wrap_text("Va extraordinairement vite", len, 16)
    assert lines[0].startswith("Va extra") and lines[0].endswith("-")


def test_wrap_keeps_existing_hyphen_as_break_point() -> None:
    lines = wrap_text("arc-en-ciel", len, 7)
    assert lines == ["arc-en-", "ciel"]


def test_wrap_never_drops_text_even_when_a_word_cannot_fit() -> None:
    lines = wrap_text("Zzzzzzzzzzzzzzz ok", len, 5)
    assert "Zzzzzzzzzzzzzzz" in lines[0].replace("-", "") or _joined(lines).replace("-", "").startswith("Zzz")
    assert "ok" in lines[-1]


def test_fit_prefers_largest_size_then_shrinks(letterer: Letterer) -> None:
    text = "Je ne te laisserai jamais seul face à eux, tu m'entends ?"
    big = letterer.fit("speech", text, 9, 2000, 2000)
    assert big is not None and big.size_pt == 9
    sizes = letterer.sizes("speech")
    assert sizes[0] == 9 and sizes[-1] == 6.5 and sizes == sorted(sizes, reverse=True)
    # Zone étroite : la taille de départ ne tient pas, une plus petite oui.
    fits = [(s, letterer.fit("speech", text, s, 340, 210)) for s in sizes]
    ok = [s for s, f in fits if f is not None]
    assert ok and ok[0] < 9
    chosen = next(f for _, f in fits if f is not None)
    assert chosen.outer[0] <= 340 and chosen.outer[1] <= 210


def test_minimum_readable_size_comes_from_preset(presets: PresetRegistry, letterer: Letterer) -> None:
    for kind, style in presets.require_fonts().styles.items():
        assert letterer.sizes(kind)[-1] == style.min_size_pt


# --- placement -------------------------------------------------------------------------------
def _panel(bubbles: list[BubbleSpec], **kw: object) -> PanelSpec:
    values: dict[str, object] = {
        "id": 1,
        "index": 0,
        "box": Box(100, 100, 1300, 1100),
        "zone": Box(124, 124, 824, 524),
        "characters": ["Aiko", "Ren"],
    }
    values.update(kw)
    return PanelSpec(bubbles=bubbles, **values)  # type: ignore[arg-type]


def _bubbles(n: int = 2) -> list[BubbleSpec]:
    texts = ["Tu es en retard !", "Désolé, le train…", "Encore ?"]
    return [BubbleSpec(id=i + 1, kind="speech", text=texts[i], speaker="Aiko", order=i) for i in range(n)]


def test_bubbles_stay_in_the_reserved_zone(letterer: Letterer) -> None:
    zone = Box(124, 124, 824, 524)
    res = letterer.letter_panel(_panel(_bubbles(2), zone=zone), "ltr")
    assert not res.warnings
    inner = zone.intersection(Box(100, 100, 1300, 1100).inset(letterer.mm(1.5)))
    assert inner is not None
    for b in res.bubbles:
        assert inner.x1 - 0.1 <= b.box.x1 and b.box.x2 <= inner.x2 + 0.1
        assert inner.y1 - 0.1 <= b.box.y1 and b.box.y2 <= inner.y2 + 0.1
        assert not b.overflow
    a, c = res.bubbles
    assert not a.box.intersects(c.box)


def test_reading_order_ltr_vs_rtl(letterer: Letterer) -> None:
    ltr = letterer.letter_panel(_panel(_bubbles(2), zone=None), "ltr").bubbles
    rtl = letterer.letter_panel(_panel(_bubbles(2), zone=None), "rtl").bubbles
    panel = Box(100, 100, 1300, 1100)
    # 1re bulle lue : en haut, côté début de lecture.
    assert ltr[0].box.x1 < panel.cx and rtl[0].box.x2 > panel.cx
    assert ltr[0].box.y1 == rtl[0].box.y1 == min(b.box.y1 for b in [*ltr, *rtl])
    # La suivante : plus bas, ou à la même hauteur plus loin dans le sens de lecture.
    for first, second, after in (
        (ltr[0], ltr[1], lambda a, b: b.box.x1 >= a.box.x2),
        (rtl[0], rtl[1], lambda a, b: b.box.x2 <= a.box.x1),
    ):
        assert second.box.y1 >= first.box.y1
        if second.box.y1 < first.box.y2:
            assert after(first, second)


def test_bubbles_avoid_detected_faces(letterer: Letterer) -> None:
    free = letterer.letter_panel(_panel(_bubbles(1)), "ltr").bubbles[0]
    face = Box(free.box.x1 + 20, free.box.y1 + 20, free.box.x1 + 260, free.box.y1 + 300)
    res = letterer.letter_panel(_panel(_bubbles(1), faces=[face]), "ltr")
    placed = res.bubbles[0]
    assert free.box.intersects(face)  # sans QC, la bulle serait sur le visage
    assert not placed.box.intersects(face)
    assert not res.warnings
    # La queue part vers le visage du locuteur et s'arrête avant lui.
    assert placed.tail is not None
    assert not face.contains_point(*placed.tail)
    d_tip = abs(placed.tail[0] - face.cx) + abs(placed.tail[1] - face.cy)
    d_center = abs(placed.box.cx - face.cx) + abs(placed.box.cy - face.cy)
    assert d_tip < d_center


def test_tail_default_direction_and_kinds(letterer: Letterer) -> None:
    bubbles = [
        BubbleSpec(1, "speech", "Bonjour", "Aiko", 0),
        BubbleSpec(2, "narration", "Le lendemain.", "", 1),
        BubbleSpec(3, "off", "Hé !", "Voix", 2),
    ]
    panel = _panel(bubbles, zone=None)
    res = {b.kind: b for b in letterer.letter_panel(panel, "ltr").bubbles}
    speech, narration, off = res["speech"], res["narration"], res["off"]
    assert narration.tail is None
    assert speech.tail is not None and speech.tail[1] > speech.box.cy  # vers le centre de la case (en bas)
    assert off.tail is not None
    p = panel.box
    assert off.tail[0] in (p.x1, p.x2) or off.tail[1] in (p.y1, p.y2)  # hors-champ : au bord de la case


# --- queues ----------------------------------------------------------------------------------
def _manual(letterer: Letterer, kind: str, tip: tuple[float, float], box: Box | None = None) -> BubbleLayout:
    box = box or Box(500, 400, 900, 640)
    spec = BubbleSpec(1, kind, "Ici !", "Aiko", 0, manual_box=box, manual_tail=tip)
    return letterer.letter_panel(_panel([spec]), "ltr").bubbles[0]


def _turn(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """Changement de direction du contour au sommet b (degrés, 0 = tout droit)."""
    d = math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(b[1] - a[1], b[0] - a[0])
    return abs(math.degrees((d + math.pi) % (2 * math.pi) - math.pi))


@pytest.mark.parametrize("tip", [(700, 900), (380, 760), (1050, 300), (560, 180)])
def test_speech_tail_is_one_closed_outline_with_a_sharp_mitered_tip(
    letterer: Letterer, tip: tuple[float, float]
) -> None:
    b = _manual(letterer, "speech", tip)
    shape, box = b.shape, b.box
    assert len(shape.polygons) == 1  # corps + queue : un seul contour, pas de trait à la base
    poly = shape.polygons[0]
    assert len(poly) > 96
    # Aucun sommet dans l'ellipse : rien ne traverse la base de la queue.
    for x, y in poly:
        assert ((x - box.cx) / (box.w / 2)) ** 2 + ((y - box.cy) / (box.h / 2)) ** 2 >= 0.98
    # La pointe du remplissage est le sommet le plus éloigné, et le contour s'y retourne (pointe vive).
    center = (box.cx, box.cy)
    i = max(range(len(poly)), key=lambda k: math.dist(poly[k], center))
    assert _turn(poly[i - 1], poly[i], poly[(i + 1) % len(poly)]) > 150
    # Joint en onglet à la pointe : le contour du trait n'est pas biseauté (un seul sommet par sommet) et
    # son onglet tombe exactement sur la pointe voulue, point le plus éloigné de toute la bulle.
    assert shape.miter_limit >= miter_ratio(poly)
    outer = stroke_outline(poly, shape.stroke_px, shape.miter_limit)
    assert len(outer) == len(poly)
    apex = max(outer, key=lambda p: math.dist(p, center))
    assert math.dist(apex, tip) < 1.5
    # La queue coule du contour : pas d'angle vif à la jonction avec la bulle (seule la pointe en a un).
    turns = sorted(_turn(poly[k - 1], poly[k], poly[(k + 1) % len(poly)]) for k in range(len(poly)))
    assert turns[-2] < 45


def test_tail_shape_comes_from_the_preset(presets: PresetRegistry) -> None:
    def tail_of(**changes: float) -> tuple[tuple[float, float], ...]:
        settings = presets.lettering.model_copy(update={"tail": presets.lettering.tail.model_copy(update=changes)})
        return _manual(Letterer(FontBook(presets), settings, 300), "speech", (720, 740)).shape.polygons[0]

    def tip_angle(poly: tuple[tuple[float, float], ...]) -> float:
        i = max(range(len(poly)), key=lambda k: poly[k][1])
        return 180 - _turn(poly[i - 1], poly[i], poly[i + 1])

    default = tail_of()
    assert tail_of(bend=0.0) != default and tail_of(bend=-0.3) != tail_of(bend=0.3)
    assert tip_angle(tail_of(tip_angle_deg=40)) > tip_angle(default) + 10
    narrow = tail_of(base_mm=2)
    wide = tail_of(base_mm=8)
    xs = [x for x, y in wide if y > 645]
    assert max(xs) - min(xs) > max(x for x, y in narrow if y > 645) - min(x for x, y in narrow if y > 645)


def test_other_kinds_keep_their_tails(letterer: Letterer) -> None:
    shout = _manual(letterer, "shout", (700, 950))
    assert len(shout.shape.polygons) == 1  # cri : queue en éclair fondue dans les pointes
    poly = shout.shape.polygons[0]
    outer = stroke_outline(poly, shout.shape.stroke_px, shout.shape.miter_limit)
    assert len(outer) == len(poly)  # aucune pointe biseautée, ni sur la queue ni sur le contour
    assert math.dist(max(outer, key=lambda p: p[1]), (700, 950)) < 1.5
    thought = _manual(letterer, "thought", (700, 950))
    circles = thought.shape.polygons[1:]
    assert len(circles) == letterer.s.cloud.tail_bubbles  # pensée : bulles décroissantes
    radii = [max(x for x, _ in c) - min(x for x, _ in c) for c in circles]
    assert radii == sorted(radii, reverse=True)
    inside = _manual(letterer, "speech", (700, 520))
    assert len(inside.shape.polygons) == 1 and len(inside.shape.polygons[0]) == 96  # pointe dans la bulle


def test_off_panel_tail_touches_the_panel_edge(letterer: Letterer) -> None:
    panel = _panel([BubbleSpec(1, "off", "Hé !", "Voix", 0)], zone=None)
    b = letterer.letter_panel(panel, "ltr").bubbles[0]
    assert b.tail is not None
    shape = b.shape
    assert len(shape.polygons) == 1
    outer = stroke_outline(shape.polygons[0], shape.stroke_px, shape.miter_limit)
    apex = min(outer, key=lambda p: math.dist(p, b.tail))  # onglet de la pointe
    assert math.dist(apex, b.tail) < 1.5
    p = panel.box
    assert min(abs(apex[0] - p.x1), abs(apex[0] - p.x2), abs(apex[1] - p.y1), abs(apex[1] - p.y2)) < 1.0


def test_too_much_text_is_flagged_never_cut(letterer: Letterer) -> None:
    long = "C'est une très longue réplique qui ne tiendra jamais dans une case aussi petite, même en tout petit. " * 3
    panel = _panel([BubbleSpec(1, "speech", long, "Aiko", 0)], box=Box(0, 0, 300, 200), zone=Box(10, 10, 200, 120))
    res = letterer.letter_panel(panel, "ltr")
    b = res.bubbles[0]
    assert b.overflow
    assert b.size_pt == letterer.sizes("speech")[-1]
    assert [w.code for w in res.warnings] == ["text_overflow"]
    assert "trop long" in res.warnings[0].message
    drawn = _joined([ln.text.replace(NBSP, " ") for ln in b.lines]).replace(" ", "")
    assert drawn == normalize_text(long).replace(NBSP, " ").replace(" ", "")


def test_manual_box_is_kept_and_text_refitted(letterer: Letterer) -> None:
    box = Box(500, 600, 900, 820)
    res = letterer.letter_panel(
        _panel([BubbleSpec(1, "speech", "Ici !", "Aiko", 0, manual_box=box, manual_tail=(700, 1000))]), "ltr"
    )
    b = res.bubbles[0]
    assert b.box == box and b.manual and b.manual_tail
    assert b.tail == (700, 1000)
    assert all(box.x1 < ln.x < box.x2 and box.y1 < ln.y < box.y2 for ln in b.lines)


def test_lettering_is_deterministic(letterer: Letterer) -> None:
    panel = _panel(_bubbles(3), faces=[Box(400, 300, 600, 500)])
    a = [b.to_json() for b in letterer.letter_panel(panel, "rtl").bubbles]
    b = [b.to_json() for b in letterer.letter_panel(panel, "rtl").bubbles]
    assert a == b


def test_face_boxes_read_qc_detections() -> None:
    """Les boîtes enregistrées par le QC (#10) dans `PanelImage.detections` sont évitées."""
    from mangaka_engine.pipeline.render import face_boxes
    from mangaka_engine.providers.qc.base import Box as QCBox
    from mangaka_engine.providers.qc.base import Detections
    from mangaka_engine.store.models import PanelImage

    det = Detections(800, 600, faces=[QCBox(100, 50, 300, 250, 0.9, "face")], hands=[QCBox(1, 2, 30, 40, 0.8)])
    img = PanelImage(params={}, detections=det.as_dict() | {"provider": "mock"})
    assert face_boxes(img, (800, 600)) == [Box(100, 50, 300, 250)]


def test_big_sfx_beyond_dialogue_cap_letters(presets: PresetRegistry) -> None:
    """Régression #117 : une onomatopée > 72 pt (plafond du dialogue) se lettre, à la main comme en auto."""
    sfx = presets.lettering.sfx.model_copy(update={"scale_max": 5.0})  # taille auto = max_size_pt (96)
    letterer = Letterer(FontBook(presets), presets.lettering.model_copy(update={"sfx": sfx}), 300)
    big = Box(100, 100, 2400, 3400)
    panel = _panel(
        [],
        box=big,
        zone=None,
        sfx=[
            SfxSpec(id=1, text="BOUM !", intensity="choc", size_pt=98.0, center=(1250, 1200)),
            SfxSpec(id=2, text="CRAC", intensity="choc"),
        ],
    )
    res = letterer.letter_page([panel], "ltr")
    sizes = {s.id: s.size_pt for s in res.sfx}
    assert sizes[1] == 98.0 and sizes[2] == sfx.max_size_pt == 96
    assert not [w for w in res.warnings if w.code == "sfx_failed"]
    assert all(s.style.size_pt > 72 for s in res.sfx)


def test_an_element_that_cannot_be_lettered_is_a_warning_not_a_crash(letterer: Letterer) -> None:
    bubbles = [*_bubbles(2), BubbleSpec(id=9, kind="inconnu", text="Fantôme", order=2)]
    panel = _panel(bubbles, sfx=[SfxSpec(id=20, text="BAM", size_pt=500.0), SfxSpec(id=21, text="PAF")])
    res = letterer.letter_page([panel], "ltr")
    assert [b.id for b in res.bubbles] == [1, 2]
    assert [s.id for s in res.sfx] == [21]
    failed = {w.code: w for w in res.warnings if w.code in ("bubble_failed", "sfx_failed")}
    assert failed["bubble_failed"].bubble_id == 9 and "impossible à lettrer" in failed["bubble_failed"].message
    assert failed["sfx_failed"].bubble_id == 20 and "« BAM »" in failed["sfx_failed"].message


# --- cadre ajusté à la main : le texte remplit la bulle -----------------------------------------
LINE = "« Où est passé le cœur de la forêt ? » Ça m'étonne, à vrai dire."


def _scaled(box: Box, k: float) -> Box:
    return Box(box.cx - box.w * k / 2, box.cy - box.h * k / 2, box.cx + box.w * k / 2, box.cy + box.h * k / 2)


def _in_box(letterer: Letterer, kind: str, box: Box, text: str = LINE, size: float | None = None) -> BubbleLayout:
    spec = BubbleSpec(1, kind, text, "Aiko", 0, manual_box=box, manual_tail=(box.cx, box.y2 + 80), size_pt=size)
    return letterer.letter_panel(_panel([spec], box=Box(0, 0, 2400, 2400), zone=None), "ltr").bubbles[0]


def _auto_box(letterer: Letterer, kind: str, text: str = LINE) -> BubbleLayout:
    panel = _panel([BubbleSpec(1, kind, text, "Aiko", 0)], box=Box(0, 0, 2400, 2400), zone=None)
    return letterer.letter_panel(panel, "ltr").bubbles[0]


def _assert_text_inside(letterer: Letterer, b: BubbleLayout, text: str = LINE) -> None:
    """Chaque ligne (encre : hauteur de capitale + jambages) tient dans la forme, rien n'est coupé."""
    st = letterer.fonts.style(b.kind)
    font = letterer.fonts.pil(st, b.size_px)
    cap, desc = -font.getbbox("H", anchor="ls")[1], font.getbbox("gjpq", anchor="ls")[3]
    box = b.box
    for ln in b.lines:
        width = max(ln.width, font.getlength(ln.text))  # largeur réellement dessinée
        corners = [(ln.x + sx * width / 2, ln.y + dy) for sx in (-1, 1) for dy in (-cap, desc)]
        for x, y in corners:
            if b.kind == "narration":
                assert box.x1 <= x <= box.x2 and box.y1 <= y <= box.y2, (ln.text, x, y)
            else:
                nx, ny = (x - box.cx) / (box.w / 2), (y - box.cy) / (box.h / 2)
                assert nx * nx + ny * ny <= 1.0, (b.kind, ln.text, round(nx * nx + ny * ny, 3))
    drawn = _joined([ln.text for ln in b.lines]).replace(NBSP, " ")
    expected = normalize_text(text, uppercase=st.uppercase).replace(NBSP, " ")
    assert drawn == expected


@pytest.mark.parametrize("kind", ["speech", "thought", "shout", "narration", "off"])
def test_enlarged_manual_box_grows_the_text_up_to_the_preset_cap(
    presets: PresetRegistry, letterer: Letterer, kind: str
) -> None:
    st = presets.require_fonts().styles[kind]
    auto = _auto_box(letterer, kind)
    assert not auto.manual and auto.size_pt <= st.size_pt
    bigger = _in_box(letterer, kind, _scaled(auto.box, 1.5))
    assert bigger.manual and not bigger.overflow and not bigger.to_json()["font"]["manual_size"]
    assert auto.size_pt < bigger.size_pt <= st.max_size_pt
    assert bigger.size_px > auto.size_px
    _assert_text_inside(letterer, bigger)
    # Bulle énorme : plafonnée, pas de texte géant.
    huge = _in_box(letterer, kind, _scaled(auto.box, 6))
    assert huge.size_pt == st.max_size_pt
    assert huge.to_json()["font"]["max_size_pt"] == st.max_size_pt
    _assert_text_inside(letterer, huge)


@pytest.mark.parametrize("kind", ["speech", "narration"])
def test_shrunk_manual_box_lowers_the_text_down_to_the_minimum(
    presets: PresetRegistry, letterer: Letterer, kind: str
) -> None:
    st = presets.require_fonts().styles[kind]
    auto = _auto_box(letterer, kind)
    sizes = [_in_box(letterer, kind, _scaled(auto.box, k)) for k in (1.5, 1.2, 1.0, 0.9, 0.8)]
    pts = [b.size_pt for b in sizes]
    assert pts == sorted(pts, reverse=True) and pts[0] > pts[-1]
    for b in sizes:
        assert st.min_size_pt <= b.size_pt <= st.max_size_pt
        if not b.overflow:
            _assert_text_inside(letterer, b)
    # Trop petit même au minimum : taille minimale, tout le texte gardé, avertissement.
    tiny = _in_box(letterer, kind, _scaled(auto.box, 0.4))
    assert tiny.size_pt == st.min_size_pt and tiny.overflow
    assert _joined([ln.text for ln in tiny.lines]).replace(NBSP, " ") == normalize_text(LINE).replace(NBSP, " ")


def test_manual_box_keeps_french_accents_and_hyphenates_like_auto_placement(letterer: Letterer) -> None:
    text = "Extraordinairement incompréhensible, ce cœur de forêt ! Où es-tu, Hélène ?"
    auto = _auto_box(letterer, "speech", text)
    big = _in_box(letterer, "speech", _scaled(auto.box, 1.5), text)
    drawn = " ".join(ln.text for ln in big.lines)
    for word in ("cœur", "forêt", "Où", "Hélène"):
        assert word in drawn
    style = letterer.fonts.style("speech")
    assert all(letterer.fonts.has_char(style, ch) for ch in "œêùèÉÀÇ")
    _assert_text_inside(letterer, big, text)
    shout = _in_box(letterer, "shout", _scaled(_auto_box(letterer, "shout", text).box, 1.5), text)
    assert "CŒUR" in " ".join(ln.text for ln in shout.lines) and "HÉLÈNE" in " ".join(ln.text for ln in shout.lines)


def test_typed_size_wins_over_the_fill_until_back_to_auto(letterer: Letterer) -> None:
    auto = _auto_box(letterer, "speech")
    box = _scaled(auto.box, 1.5)
    typed = _in_box(letterer, "speech", box, size=7.5)
    assert typed.size_pt == 7.5 and typed.to_json()["font"]["manual_size"]
    assert _in_box(letterer, "speech", box).size_pt > 7.5
    # Taille saisie sur une bulle placée automatiquement : gardée aussi.
    panel = _panel([BubbleSpec(1, "speech", LINE, "Aiko", 0, size_pt=11)], box=Box(0, 0, 2400, 2400), zone=None)
    placed = letterer.letter_panel(panel, "ltr").bubbles[0]
    assert placed.size_pt == 11 and not placed.manual
    # Trop grande pour son cadre : gardée, avertissement (rien de coupé).
    res = letterer.letter_panel(
        _panel([BubbleSpec(1, "speech", LINE, "Aiko", 0, manual_box=auto.box, size_pt=30)], box=Box(0, 0, 2400, 2400)),
        "ltr",
    )
    assert res.bubbles[0].size_pt == 30 and res.bubbles[0].overflow
    assert [w.code for w in res.warnings] == ["text_overflow"]


def test_auto_placed_bubbles_keep_their_usual_sizes(letterer: Letterer) -> None:
    """Le plafond ne vaut que pour un cadre ajusté à la main : le placement automatique part de size_pt."""
    for kind in ("speech", "thought", "shout", "narration", "off"):
        assert _auto_box(letterer, kind, "Oui.").size_pt == letterer.fonts.style(kind).size_pt


def test_auto_frame_kept_as_manual_keeps_its_text_size(letterer: Letterer) -> None:
    """Cadre automatique enregistré tel quel (arrondi au pixel, comme l'écran Lettrage) : même taille de texte."""
    for kind in ("speech", "thought", "shout", "narration", "off"):
        auto = _auto_box(letterer, kind)
        xywh = auto.box.as_xywh()
        box = Box(xywh["x"], xywh["y"], xywh["x"] + xywh["w"], xywh["y"] + xywh["h"])
        assert _in_box(letterer, kind, box).size_pt >= auto.size_pt


# --- le texte grandit en proportion du cadre (marges proportionnelles) ---------------------------
def _preview_pt(font: dict, src: Box, dst: Box, *, filled: bool) -> float:
    """Même calcul que l'aperçu de l'écran Lettrage (web/src/lib/bubble-size.ts, `previewSizePt`)."""
    base, size = font["style_size_pt"], font["size_pt"]
    scale = size / base if filled else 1.0

    def side(f: float, t: float, margin: float) -> float:
        return t / (max(1.0, f - margin * scale) / size + margin / base)

    m = font["margin_px"]
    pt = min(side(src.w, dst.w, m["w"]), side(src.h, dst.h, m["h"]))
    lo, hi = min(font["min_size_pt"], size), max(font["max_size_pt"], size)
    return math.floor(min(hi, max(lo, pt)) * 2 + 0.5) / 2


def _rounded(box: Box, k: float) -> Box:
    """Cadre agrandi ×k depuis son coin, arrondi au pixel (comme l'enregistre l'écran Lettrage)."""
    xywh = box.as_xywh()
    return Box(xywh["x"], xywh["y"], xywh["x"] + round(xywh["w"] * k), xywh["y"] + round(xywh["h"] * k))


@pytest.mark.parametrize("kind", ["speech", "thought", "shout", "narration", "off"])
def test_enlarged_manual_box_grows_the_text_in_proportion(letterer: Letterer, kind: str) -> None:
    auto = _auto_box(letterer, kind)
    double = _in_box(letterer, kind, _rounded(auto.box, 2))
    triple = _in_box(letterer, kind, _rounded(auto.box, 3))
    assert not double.overflow and not triple.overflow
    assert abs(double.size_pt - 2 * auto.size_pt) <= 0.5, (double.size_pt, auto.size_pt)
    assert abs(triple.size_pt - 3 * auto.size_pt) <= 0.5, (triple.size_pt, auto.size_pt)
    assert triple.size_pt > double.size_pt
    _assert_text_inside(letterer, double)
    _assert_text_inside(letterer, triple)
    # Le bloc de texte occupe la bulle comme dans la bulle automatique (même retour à la ligne).
    assert [ln.text for ln in double.lines] == [ln.text for ln in auto.lines]


def test_speech_text_is_no_longer_stuck_at_the_old_cap(letterer: Letterer) -> None:
    auto = _auto_box(letterer, "speech")
    assert auto.size_pt == 9
    assert _in_box(letterer, "speech", _rounded(auto.box, 2)).size_pt >= 17.5  # ancien plafond : 14 pt


@pytest.mark.parametrize("kind", ["speech", "thought", "shout", "narration", "off"])
@pytest.mark.parametrize("k", [0.75, 0.9, 1.25, 1.5, 2, 2.5, 3])
def test_resize_preview_matches_the_engine(letterer: Letterer, kind: str, k: float) -> None:
    """L'aperçu pendant le glissé et la taille calculée au lâcher : à 0,5 pt près, depuis une bulle placée
    automatiquement comme depuis un cadre déjà ajusté à la main."""
    auto = _auto_box(letterer, kind)
    dst = _rounded(auto.box, k)
    after = _in_box(letterer, kind, dst)
    if not after.overflow:
        assert abs(_preview_pt(auto.to_json()["font"], auto.box, dst, filled=False) - after.size_pt) <= 0.5
    manual = _in_box(letterer, kind, _rounded(auto.box, 1.5))
    dst = _rounded(manual.box, k)
    after = _in_box(letterer, kind, dst)
    if not after.overflow:
        assert abs(_preview_pt(manual.to_json()["font"], manual.box, dst, filled=True) - after.size_pt) <= 0.5


@pytest.mark.parametrize("size", [7.0, 8.0])
def test_preview_matches_the_engine_for_a_bubble_shrunk_by_auto_placement(letterer: Letterer, size: float) -> None:
    """Bulle réduite par le placement automatique (case chargée) : ses marges sont celles de la taille
    normale ; l'aperçu le sait et suit encore le moteur."""
    fit = letterer.fit("speech", LINE, size, 2000, 2000)
    assert fit is not None
    src = Box(100, 100, 100 + fit.outer[0], 100 + fit.outer[1])
    font = {**_auto_box(letterer, "speech").to_json()["font"], "size_pt": size}
    for k in (1, 1.5, 2, 3):
        dst = _rounded(src, k)
        after = _in_box(letterer, "speech", dst)
        assert abs(_preview_pt(font, src, dst, filled=False) - after.size_pt) <= 0.5, (k, after.size_pt)


def test_enlarging_auto_placed_bubbles_only_changes_resized_ones(letterer: Letterer) -> None:
    """Le remplissage proportionnel ne touche que les cadres ajustés à la main."""
    a, b = BubbleSpec(1, "speech", LINE, "Aiko", 0), BubbleSpec(2, "speech", "Oui.", "Aiko", 1)
    before = letterer.letter_panel(_panel([a, b], box=Box(0, 0, 2400, 2400), zone=None), "ltr").bubbles
    big = _rounded(before[0].box, 2)
    a2 = BubbleSpec(1, "speech", LINE, "Aiko", 0, manual_box=big, manual_tail=(big.cx, big.y2 + 80))
    after = letterer.letter_panel(_panel([a2, b], box=Box(0, 0, 2400, 2400), zone=None), "ltr").bubbles
    assert after[0].size_pt == 18 and after[1].size_pt == before[1].size_pt == 9
