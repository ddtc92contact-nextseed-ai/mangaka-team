"""Une seule phrase de rôle par image envoyée (« <image1> is the identity reference for Aiko: keep… ») : le moteur
l'écrit seul, d'après image_prompt.yaml (`references`, `references.monochrome`) ou cover_charter.yaml
(`identity_prompt`) ; le rédacteur de prompt ne l'écrit plus, et un paragraphe hérité qui la contient déjà ne la
reçoit pas une seconde fois (elle était doublée dans 457 prompts envoyés sur 765)."""

from __future__ import annotations

import re

import pytest

from mangaka_engine.pipeline.cover_charter import identity_lines
from mangaka_engine.pipeline.covers import CoverStyle, finish_cover_prompt, parse_cover, write_cover_prompt
from mangaka_engine.pipeline.prompt import (
    PromptCharacter,
    ReferenceSlot,
    frame_references,
    image_tags,
    role_tags,
    strip_roles,
)
from mangaka_engine.pipeline.prompt_writer import PromptBrief, image_tag, parse_written, write_prompt
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm.mock import MockLLMProvider
from tests.conftest import PRESETS_DIR
from tests.test_prompt_writer import WORDS, _answer

REG = PresetRegistry.load(PRESETS_DIR)
NAMES = ("Aiko", "Kenji", "Ren")
LEAD = "Black and white manga panel, seinen manga style."
ROLE = re.compile(r"<image(\d+)> is (?:the|a) [^.]*reference")


def _roles(text: str) -> list[int]:
    """Numéros des images dont le texte donne une phrase de rôle, une entrée par phrase."""
    return [int(n) for n in ROLE.findall(text)]


def _brief(count: int, *, monochrome: bool) -> tuple[PromptBrief, list[ReferenceSlot]]:
    slots = [ReferenceSlot("character", n) for n in NAMES[:count]]
    brief = PromptBrief.build(
        description=" et ".join(NAMES[:count]) + " traversent le pont",
        characters=[PromptCharacter(n, "cheveux noirs") for n in NAMES[:count]],
        references=slots,
        style="shonen manga, halftone screentone dots",
        style_lead=LEAD,
        settings=REG.image_prompt,
        prompt=REG.prompt("redacteur-image"),
        monochrome=monochrome,
    )
    return brief, slots


@pytest.mark.parametrize("monochrome", [False, True], ids=["couleur", "nb"])
@pytest.mark.parametrize("count", [1, 2, 3])
def test_panel_with_one_to_three_sheets_gets_exactly_one_role_per_tag(count: int, monochrome: bool) -> None:
    brief, slots = _brief(count, monochrome=monochrome)
    run = write_prompt(MockLLMProvider(), REG.prompt("redacteur-image"), brief)
    stored = run.output.prompt
    assert _roles(stored) == []  # le rédacteur n'écrit plus de phrase de rôle
    sent = frame_references(stored, slots, REG.image_prompt, monochrome=monochrome)
    assert _roles(sent) == list(range(1, count + 1))
    for i, name in enumerate(NAMES[:count], start=1):
        line = f"<image{i}> is the identity reference for {name}: keep the face, hair"
        assert sent.count(line) == 1
    # la couleur reste juste : « and colours » en couleur, jamais en noir et blanc
    assert (sent.count("hair, outfit and colours;") == count) is not monochrome
    assert ("colours" in sent) is not monochrome


@pytest.mark.parametrize("monochrome", [False, True], ids=["couleur", "nb"])
def test_legacy_paragraph_with_its_role_sentences_is_not_doubled(monochrome: bool) -> None:
    slots = [ReferenceSlot("character", "Aiko"), ReferenceSlot("character", "Kenji")]
    legacy = (
        f"{LEAD} <image1> is the identity reference for Aiko: keep her face, hair and outfit; ignore its pose, "
        "framing and background. <image2> is the identity reference for Kenji: keep his face, hair and outfit; "
        "ignore its pose, framing and background. Aiko (<image1>) runs across the bridge while Kenji waits."
    )
    sent = frame_references(legacy, slots, REG.image_prompt, monochrome=monochrome)
    assert _roles(sent) == [1, 2] and sent.count("keep the face") == 0
    assert sent.startswith(legacy)
    # seule <image1> a sa phrase : <image2> reçoit celle du moteur, une seule fois
    partial = f"{LEAD} <image1> is the identity reference for Aiko: keep her face. Aiko and Kenji run."
    sent = frame_references(partial, slots, REG.image_prompt, monochrome=monochrome)
    assert sorted(_roles(sent)) == [1, 2] and sent.startswith("<image2> is the identity reference for Kenji")


def test_role_sentence_written_by_the_llm_is_removed_from_the_paragraph() -> None:
    brief, slots = _brief(2, monochrome=True)
    text = (
        f"{LEAD} <image1> is the identity reference for Aiko: keep her face, hair and outfit; ignore its pose, "
        f"framing and background. <image2> is Kenji. Aiko and Kenji cross the bridge, {WORDS}."
    )
    stored = parse_written(_answer(text), brief).prompt
    assert _roles(stored) == [] and role_tags(stored) == set()
    assert stored.startswith(f"{LEAD} Aiko and Kenji cross the bridge")
    assert _roles(frame_references(stored, slots, REG.image_prompt, monochrome=True)) == [1, 2]


def test_a_tag_cited_in_the_body_is_not_a_role_sentence() -> None:
    text = "Aiko (<image1>) runs. <image2> shows the bridge."
    assert role_tags(text) == set() and strip_roles(text) == text
    # deux images dans une phrase : rien n'est retiré, l'image en trop reste visible pour la validation
    both = "<image1> is Aiko, <image2> is Kenji. Aiko runs."
    assert image_tags(strip_roles(both)) == [1, 2]


# --- couvertures ---------------------------------------------------------------------------------------------
COVER = CoverStyle(lead="Full-colour manga volume cover illustration.", style="shonen manga", monochrome_series=False)
TAGS = [(image_tag(1), "Kaito"), (image_tag(2), "Rin")]


def _identity() -> list[tuple[str, str]]:
    return list(zip([t for t, _ in TAGS], identity_lines(None, TAGS), strict=True))


def test_cover_gets_exactly_one_role_per_tag() -> None:
    text = f"{COVER.lead} Kaito (<image1>) and Rin stand on the roof under a crimson sky."
    out = finish_cover_prompt(text, COVER, [], identity=_identity())
    assert _roles(out) == [1, 2]
    assert out.startswith(f"{COVER.lead} <image1> is the identity reference for Kaito: keep the face")


def test_legacy_cover_prompt_with_its_role_sentences_is_not_doubled() -> None:
    text = (
        f"{COVER.lead} <image1> is the identity reference for Kaito: keep his face, hair and outfit; ignore its "
        "pose, framing and background. Kaito and Rin stand on the roof under a crimson sky."
    )
    out = finish_cover_prompt(text, COVER, [], identity=_identity())
    assert sorted(_roles(out)) == [1, 2] and out.count("<image1> is") == 1
    assert out.count("<image2> is the identity reference for Rin") == 1


def test_cover_writer_no_longer_writes_the_roles() -> None:
    from mangaka_engine.pipeline.covers import CoverBrief

    brief = CoverBrief(
        series="Les Lames",
        volume="Tome 1",
        intent="",
        characters=[{"name": "Kaito", "details": ""}, {"name": "Rin", "details": ""}],
        references=[{"tag": t, "name": n} for t, n in TAGS],
        bible="",
        style=COVER,
        clear_zone="the top quarter of the image",
        charter=[],
        language="en",
        min_words=90,
        max_words=260,
    )
    run = write_cover_prompt(MockLLMProvider(), REG.prompt("redacteur-couverture"), brief)
    assert _roles(run.prompt) == []
    written = f"<image1> is the identity reference for Kaito: keep his face. Kaito and Rin stand tall, {WORDS}."
    assert _roles(parse_cover(_answer(written), brief).prompt) == []
    assert _roles(finish_cover_prompt(run.prompt, COVER, [], identity=_identity())) == [1, 2]
