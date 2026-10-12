from __future__ import annotations

from mangaka_engine.pipeline.prompt import (
    PromptCharacter,
    ReferenceSlot,
    build_negative_prompt,
    build_prompt,
    camera_term,
    defines_references,
    frame_references,
    image_tags,
    strip_quoted,
)
from mangaka_engine.presets import ImagePromptSettings, PresetRegistry
from tests.conftest import PRESETS_DIR

AIKO = PromptCharacter("Aiko", "jeune femme, cheveux noirs courts, kimono rouge", ("katana", "cicatrice à la joue"))


def test_prompt_combines_shot_description_characters_and_style() -> None:
    prompt = build_prompt(
        description="Aiko saute d'un toit à l'autre sous la pluie.",
        shot_type="plan large",
        characters=[AIKO, PromptCharacter("Kenji")],
        style="Seinen sombre, trames lourdes",
    )
    assert prompt.startswith("Plan large. Aiko saute d'un toit à l'autre sous la pluie.")
    assert (
        "Characters: Aiko (jeune femme, cheveux noirs courts, kimono rouge, katana, cicatrice à la joue); Kenji."
        in prompt
    )
    assert "Style: Seinen sombre, trames lourdes." in prompt
    assert prompt.endswith("No text or speech bubbles in the image.")
    assert ".." not in prompt


def test_prompt_omits_empty_parts() -> None:
    prompt = build_prompt(description="Une ruelle vide", shot_type=None, characters=[], style="  ")
    assert prompt == "Une ruelle vide. No text or speech bubbles in the image."


def test_prompt_never_carries_dialogue_text() -> None:
    prompt = build_prompt(description='Aiko crie « Fuyez ! » vers la foule, puis "Vite" à Kenji.', characters=[AIKO])
    assert "Fuyez" not in prompt and "Vite" not in prompt
    assert "Aiko crie vers la foule, puis à Kenji." in prompt
    assert strip_quoted("« Bonjour », dit-il.") == "dit-il."


def test_prompt_uses_preset_template() -> None:
    settings = ImagePromptSettings(parts=["[$style]", "$description"], character="$name")
    assert build_prompt(description="Un chat", style="ligne claire", settings=settings) == "[ligne claire] Un chat"


def test_negative_prompt_always_forbids_text() -> None:
    neg = build_negative_prompt("blurry, Text, deformed hands")
    terms = [t.strip() for t in neg.split(",")]
    assert terms[:3] == ["blurry", "Text", "deformed hands"]
    for term in ("letters", "speech bubble", "onomatopoeia", "watermark"):
        assert term in terms
    assert sum(t.casefold() == "text" for t in terms) == 1
    assert "speech bubble" in build_negative_prompt("")


def test_repo_image_prompt_preset_is_loaded() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    assert reg.issues == []
    assert "text" in reg.image_prompt.forbidden_text_terms  # en anglais, comme les négatifs des presets
    assert any("$description" in p for p in reg.image_prompt.parts)


def test_camera_terms_translate_plan_and_angle() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    assert camera_term("Contre-plongée", reg.image_prompt) == "low-angle shot"
    assert camera_term("cadre penché", reg.image_prompt) == "dutch angle (tilted frame)"
    assert camera_term("plan séquence", reg.image_prompt) == "plan séquence"  # inconnu : tel quel
    prompt = build_prompt(
        description="Aiko saute",
        plan="gros plan",
        angle="en contre-plongée",
        action="Aiko bondit, sabre levé",
        settings=reg.image_prompt,
    )
    assert prompt.startswith(
        "Close-up, the face fills the frame, shoulders cut by the frame edge. Camera angle: low-angle view looking up. "
        "Aiko saute."
    )
    assert "Action and pose: Aiko bondit, sabre levé." in prompt


def test_reference_framing_is_skipped_when_the_prompt_defines_the_roles() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    slots = [ReferenceSlot("character", "Aiko"), ReferenceSlot("decor", "Gare")]
    written = "<image1> is Aiko. <image2> is the station. Aiko runs."
    framed = frame_references(written, slots, reg.image_prompt)
    assert framed.startswith(written) and "Use the reference images for identity" in framed
    assert image_tags(framed) == [1, 2] and defines_references(written, 2)
    # ancien prompt (français, ou sans <imageN>) : les rôles sont ajoutés en tête, dans l'ordre
    old = frame_references("Image 1 : Aiko court.", slots, reg.image_prompt)
    assert old.startswith("<image1> is the identity reference for Aiko: keep the face")
    assert "<image2> is the location reference for Gare" in old and "Image 1 : Aiko court." in old
    # une image citée en trop, ou dans le désordre : les rôles sont redéfinis
    assert not defines_references("<image1> <image3> Aiko.", 2)
    assert not defines_references("<image2> <image1> Aiko.", 2)
