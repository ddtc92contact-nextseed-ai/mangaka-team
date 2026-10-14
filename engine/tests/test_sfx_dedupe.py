"""Onomatopées de la direction artistique : une quasi-doublure d'une onomatopée du scénario la remplace
au lieu d'ajouter une deuxième bulle ; une onomatopée placée à la main n'est jamais touchée (#167)."""

from __future__ import annotations

from typing import Any

import pytest

from mangaka_engine.pipeline.art_direction import DA_SOURCE, _apply_sfx, sfx_key
from mangaka_engine.store.models import Bubble, BubbleKind, Panel


def _panel(*bubbles: Bubble) -> Panel:
    panel = Panel(index=0, description="")
    for b in bubbles:
        panel.bubbles.append(b)
    return panel


def _script_sfx(text: str, order: int = 0, **position: Any) -> Bubble:
    return Bubble(order=order, text=text, kind=BubbleKind.sfx, sfx=None, position=position or None)


def _sfx(panel: Panel) -> list[tuple[str, str | None]]:
    return [(b.text, (b.sfx or {}).get("intensity")) for b in panel.bubbles if b.kind == BubbleKind.sfx]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("GRAAA !", "GRAAA"),
        ("Bam…", "BAM"),
        ("KRRR", "KRRRR"),
        ("GRAAA", "graaaa"),
        ("Swoosh !", "SWOOOSH"),
        ("BI-IIP", "biiip"),
        ("Crunch.", "CRUNCH !!"),
    ],
)
def test_near_duplicates_share_a_key(a: str, b: str) -> None:
    assert sfx_key(a) == sfx_key(b)


def test_different_sfx_keep_different_keys() -> None:
    assert sfx_key("BAM") != sfx_key("BOUM")
    assert sfx_key("!!!")  # que de la ponctuation : clé non vide


@pytest.mark.parametrize(("script", "proposed"), [("GRAAA !", "GRAAA"), ("Bam…", "BAM"), ("KRRR", "KRRRR")])
def test_da_near_duplicate_replaces_script_sfx(script: str, proposed: str) -> None:
    panel = _panel(_script_sfx(script))
    _apply_sfx(panel, [{"text": proposed, "intensity": "fort"}])
    assert _sfx(panel) == [(proposed, "choc")]  # une seule bulle, texte et intensité de la DA
    # Réappliquer ne double rien et ne retire pas l'onomatopée du scénario.
    _apply_sfx(panel, [{"text": proposed, "intensity": "léger"}])
    assert _sfx(panel) == [(proposed, "calme")]
    _apply_sfx(panel, [])
    assert len(_sfx(panel)) == 1


def test_da_duplicates_within_its_own_list_are_dropped() -> None:
    panel = _panel()
    _apply_sfx(panel, [{"text": "BAM !", "intensity": "fort"}, {"text": "bam", "intensity": "léger"}])
    assert _sfx(panel) == [("BAM !", "choc")]


def test_hand_placed_sfx_is_never_replaced_nor_removed() -> None:
    manual = _script_sfx("GRAAA !", x=0.4, y=0.5, manual=True)
    manual.sfx = {"intensity": "calme", "source": DA_SOURCE}
    panel = _panel(manual)
    _apply_sfx(panel, [{"text": "GRAAAA", "intensity": "fort"}])
    assert _sfx(panel) == [("GRAAA !", "calme")]
    assert manual.position == {"x": 0.4, "y": 0.5, "manual": True}
    _apply_sfx(panel, [])
    assert _sfx(panel) == [("GRAAA !", "calme")]


def test_new_sfx_is_added_after_existing_bubbles() -> None:
    panel = _panel(_script_sfx("GRAAA !", order=3))
    _apply_sfx(panel, [{"text": "BAM", "intensity": "moyen"}])
    assert _sfx(panel) == [("GRAAA !", None), ("BAM", "normal")]
    assert panel.bubbles[-1].order == 4 and panel.bubbles[-1].sfx == {"intensity": "normal", "source": DA_SOURCE}
