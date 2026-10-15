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


def test_fragment_prompt_opens_on_the_style_sentence() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    lead = (
        "Black and white manga panel, hand-drawn inked line art with halftone screentone shading, seinen manga style."
    )
    prompt = build_prompt(description="Aiko court", shot_type="plan large", style_lead=lead, settings=reg.image_prompt)
    assert prompt.startswith(lead + " Wide shot. Aiko court.")
    # sans phrase de style (série d'avant les packs sans rendu) : le morceau est omis
    assert build_prompt(description="Aiko court", shot_type="plan large", settings=reg.image_prompt).startswith(
        "Wide shot."
    )


def test_camera_terms_carry_no_photographic_vocabulary() -> None:
    import re

    settings = PresetRegistry.load(PRESETS_DIR).image_prompt
    terms = " ".join(settings.camera_terms.values())
    found = [t for t in settings.forbidden_photo_terms if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", terms, re.I)]
    assert found == []


def test_negative_prompt_fights_photorealism_without_duplicates() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    neg = build_negative_prompt("blurry, Photo, text", reg.image_prompt)
    terms = [t.strip() for t in neg.split(",")]
    for term in ("photorealistic", "photograph", "3d render", "cgi", "realistic skin texture", "film grain"):
        assert terms.count(term) == 1
    assert [t.casefold() for t in terms].count("photo") == 1 and len(terms) == len({t.casefold() for t in terms})


def test_reference_framing_is_skipped_after_the_style_sentence() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    slots = [ReferenceSlot("character", "Aiko")]
    written = "Black and white manga panel, seinen manga style. <image1> is Aiko. Aiko runs."
    framed = frame_references(written, slots, reg.image_prompt)
    assert defines_references(written, 1) and framed.startswith(written)
    assert framed.count("<image1> is") == 1
    assert "drawn in the same manga style as the reference images" in framed


# --- plafond de mentions par personnage (#187, essai « Nuit du pari » du 15/10) -----------------------------
NUIT = [PromptCharacter("Voyou 1", "blouson de cuir"), PromptCharacter("Voyou 2"), PromptCharacter("Kaï")]
NUIT_NAMES = ["Voyou 1", "Voyou 2", "Voyou 3", "Kaï"]


def test_cap_mentions_keeps_the_first_mention_of_each_name() -> None:
    from mangaka_engine.pipeline.prompt import cap_mentions, mention_count

    text = "Voyou 1 attrape Voyou 2 par le col, Voyou 1 le plaque au mur, voyou 1 rit. Voyou 10 regarde."
    out = cap_mentions(text, ["Voyou 1", "Voyou 2", "Voyou"], 1)
    assert out == "Voyou 1 attrape Voyou 2 par le col, le plaque au mur, rit. Voyou 10 regarde."
    assert mention_count(out, "Voyou 1") == 1 and mention_count(out, "Voyou 10") == 1  # « Voyou 10 » : un autre
    assert mention_count(cap_mentions(text, ["Voyou 1"], 2), "Voyou 1") == 2
    assert cap_mentions(text, ["Voyou 1"], 0) == text  # 0 : pas de plafond
    assert cap_mentions(text, ["Voyou 1"], 1, "he").startswith("Voyou 1 attrape Voyou 2 par le col, he le plaque")


def test_a_panel_naming_four_characters_names_each_once_per_field() -> None:
    """Critère d'acceptation : une case qui nomme 4 personnages → chaque nom au plus une fois par champ."""
    from mangaka_engine.pipeline.prompt import mention_count

    reg = PresetRegistry.load(PRESETS_DIR)
    assert reg.image_prompt.mentions.max_per_field == 1
    fields = {
        "description": "Voyou 1 jette les dés, Voyou 2 et Voyou 3 se penchent, Kaï fixe Voyou 1, Voyou 1 sourit à "
        "Voyou 2, Voyou 3 recule et Kaï se lève",
        "action": "Voyou 1 frappe la table, Voyou 1 pointe Kaï, Kaï repousse Voyou 1",
        "staging": "Voyou 1 à gauche, Voyou 2 derrière Voyou 1, Voyou 3 à droite de Voyou 2, Kaï face à Voyou 1",
        "setting": "le tripot où Voyou 1 et Voyou 2 jouent, la table de Voyou 1",
        "ambiance": "néon rouge sur Voyou 1, ombre sur Kaï et sur Voyou 1",
    }
    prompt = build_prompt(
        **fields,
        plan="plan moyen",
        characters=NUIT,
        bible="Voyou 1 : chef. Voyou 2 : suit Voyou 1. Kaï : joueur.",
        settings=reg.image_prompt,
        names=NUIT_NAMES,
    )
    parts = {
        "description": prompt.split("Action and pose:")[0],
        "action": prompt.split("Action and pose: ")[1].split("Setting:")[0],
        "setting": prompt.split("Setting: ")[1].split("Staging:")[0],
        "staging": prompt.split("Staging: ")[1].split("Mood and lighting:")[0],
        "ambiance": prompt.split("Mood and lighting: ")[1].split("Three characters:")[0],
        "characters": prompt.split("Three characters: ")[1].split("Series bible notes:")[0],
        "bible": prompt.split("Series bible notes: ")[1].split("A single continuous")[0],
    }
    for field, text in parts.items():
        for name in NUIT_NAMES:
            assert mention_count(text, name) <= 1, (field, name, text)
    assert "Voyou 1 jette les dés, Voyou 2 et Voyou 3 se penchent, Kaï fixe" in prompt


def test_writer_brief_names_each_character_once_per_field_and_states_the_cap() -> None:
    from mangaka_engine.pipeline.prompt import mention_count
    from mangaka_engine.pipeline.prompt_writer import PromptBrief, render_messages

    reg = PresetRegistry.load(PRESETS_DIR)
    brief = PromptBrief.build(
        description="Voyou 1 jette les dés, Voyou 1 rit, Kaï fixe Voyou 1",
        action="Voyou 1 frappe la table, Voyou 1 pointe Kaï",
        staging="Voyou 1 à gauche, Kaï face à Voyou 1",
        characters=NUIT,
        extras=["Voyou 3"],
        settings=reg.image_prompt,
        prompt=reg.prompt("redacteur-image"),
    )
    for text in (brief.description, brief.action, brief.staging):
        assert mention_count(text, "Voyou 1") == 1 and mention_count(text, "Kaï") <= 1
    system, _ = render_messages(reg.prompt("redacteur-image"), brief)
    assert f"name each character at most {reg.image_prompt.mentions.writer_max} times" in system.content
