"""Étape 5 : texte (retour à la ligne, césure, taille), placement des bulles, queues."""

from __future__ import annotations

import pytest

from mangaka_engine.pipeline.fonts import NBSP, FontBook
from mangaka_engine.pipeline.lettering import (
    Box,
    BubbleSpec,
    Letterer,
    PanelSpec,
    normalize_text,
    split_options,
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
