from __future__ import annotations

from mangaka_engine.pipeline.prompt import PromptCharacter, build_negative_prompt, build_prompt, strip_quoted
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
        "Personnages : Aiko (jeune femme, cheveux noirs courts, kimono rouge, katana, cicatrice à la joue) ; Kenji."
        in prompt
    )
    assert "Style : Seinen sombre, trames lourdes." in prompt
    assert prompt.endswith("sans aucun texte ni bulle.")
    assert ".." not in prompt


def test_prompt_omits_empty_parts() -> None:
    prompt = build_prompt(description="Une ruelle vide", shot_type=None, characters=[], style="  ")
    assert prompt == "Une ruelle vide. Case de manga, dessin encré, sans aucun texte ni bulle."


def test_prompt_never_carries_dialogue_text() -> None:
    prompt = build_prompt(description='Aiko crie « Fuyez ! » vers la foule, puis "Vite" à Kenji.', characters=[AIKO])
    assert "Fuyez" not in prompt and "Vite" not in prompt
    assert "Aiko crie vers la foule, puis à Kenji." in prompt
    assert strip_quoted("« Bonjour », dit-il.") == "dit-il."


def test_prompt_uses_preset_template() -> None:
    settings = ImagePromptSettings(parts=["[$style]", "$description"], character="$name")
    assert build_prompt(description="Un chat", style="ligne claire", settings=settings) == "[ligne claire] Un chat"


def test_negative_prompt_always_forbids_text() -> None:
    neg = build_negative_prompt("flou, Texte, mains déformées")
    terms = [t.strip() for t in neg.split(",")]
    assert terms[:3] == ["flou", "Texte", "mains déformées"]
    for term in ("lettres", "bulles", "onomatopées", "filigrane"):
        assert term in terms
    assert sum(t.casefold() == "texte" for t in terms) == 1
    assert "bulles" in build_negative_prompt("")


def test_repo_image_prompt_preset_is_loaded() -> None:
    reg = PresetRegistry.load(PRESETS_DIR)
    assert reg.issues == []
    assert "texte" in reg.image_prompt.forbidden_text_terms
    assert any("$description" in p for p in reg.image_prompt.parts)
