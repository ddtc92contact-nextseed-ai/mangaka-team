"""Texte côté image en anglais (langue de Qwen-Image 2.1) : aucun mot français dans les presets qui
entrent dans un prompt image. Ce que lit l'auteur (noms, descriptions, scènes test affichées) reste en
français."""

from __future__ import annotations

import re

import pytest

from mangaka_engine.presets import PresetRegistry
from tests.conftest import PRESETS_DIR

REG = PresetRegistry.load(PRESETS_DIR)

# Mots français qui n'existent pas en anglais (mots-outils et vocabulaire des anciens presets).
FRENCH = set(
    [
        "le",
        "la",
        "les",
        "des",
        "une",
        "est",
        "sont",
        "dans",
        "avec",
        "sur",
        "sous",
        "qui",
        "que",
        "pour",
        "du",
        "au",
        "aux",
        "et",
        "ou",
        "son",
        "sa",
        "ses",
        "leur",
        "elle",
        "il",
        "ils",
        "ce",
        "cette",
        "ces",
        "par",
        "vers",
        "pas",
        "aucun",
        "aucune",
        "personnage",
        "personnages",
        "texte",
        "lettres",
        "bulles",
        "bulle",
        "trames",
        "trame",
        "décor",
        "fond",
        "case",
        "image",
        "référence",
        "style",
        "manga",
        "plan",
    ]
) - {"style", "manga", "image", "plan"}
# Termes d'art reçus tels quels en anglais.
ALLOWED = ("ligne claire",)
ACCENTS = re.compile(r"[àâäéèêëîïôöùûüÿçœæ]", re.IGNORECASE)


def french_words(text: str) -> list[str]:
    text = text.lower()
    for term in ALLOWED:
        text = text.replace(term, " ")
    text = re.sub(r"\$[a-z_]+|<image\d+>", " ", text)  # variables de gabarit
    found = [w for w in re.findall(r"[^\W\d_]+", text) if w in FRENCH]
    return found + ACCENTS.findall(text)


def _image_side_texts() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for kind, packs in (("genre", REG.style_genres), ("rendu", REG.style_renderings), ("ton", REG.style_tones)):
        for pack in packs.values():
            out += [(f"{kind} {pack.id}", k) for k in pack.prompt_keywords]
    for genre in REG.style_genres.values():
        out.append((f"genre {genre.id} scene_prompt", genre.scene_prompt or ""))
    for oid, option in REG.style_options.options.items():
        for cid, choice in option.choices.items():
            out += [(f"réglage {oid}.{cid}", k) for k in choice.prompt_keywords]
    for sheet in REG.reference_sheets.values():
        out += [(f"fiche {sheet.id}", p) for p in sheet.prompt] + [(f"fiche {sheet.id} négatif", sheet.negative_prompt)]
    ip = REG.image_prompt
    out += [("image_prompt parts", p) for p in ip.parts]
    refs = ip.references
    out += [("image_prompt references", t) for t in (refs.character, refs.decor, refs.object, refs.style)]
    out += [("image_prompt references", t) for t in (*refs.before, *refs.after)]
    out += [("image_prompt forbidden_text_terms", t) for t in ip.forbidden_text_terms]
    out += [("image_prompt camera_terms", t) for t in ip.camera_terms.values()]
    board = REG.defaults.style_board  # type: ignore[union-attr]
    assert board is not None
    out += [("planche de style", p) for p in board.prompt] + [("planche de style négatif", board.negative_prompt)]
    for wf in REG.workflows.values():
        out.append((f"workflow {wf.preset.id} négatif", str(wf.preset.defaults.get("negative_prompt", ""))))
        if wf.preset.inpaint is not None:
            out += [(f"réparation {wf.preset.id}", p) for p in wf.preset.inpaint.prompt_parts]
            out += [(f"réparation {wf.preset.id}", t) for t in wf.preset.inpaint.targets.values()]
    return out


def test_the_scanner_catches_french() -> None:
    assert french_words("Aucun texte ni bulle dans l'image")
    assert french_words("trames en points de densité moyenne")
    assert not french_words("European ligne claire comic, flat colours, <image1> is $name")


@pytest.mark.parametrize(("where", "text"), _image_side_texts())
def test_no_french_left_in_image_side_presets(where: str, text: str) -> None:
    assert not french_words(text), f"{where} : « {text} »"


def test_every_pack_is_marked_english() -> None:
    packs = [*REG.style_genres.values(), *REG.style_renderings.values(), *REG.style_tones.values()]
    options = [c for o in REG.style_options.options.values() for c in o.choices.values()]
    assert {p.lang for p in [*packs, *options]} == {"en"}
    franco = ", ".join(REG.style_genres["franco-belge"].prompt_keywords)
    assert franco.startswith("European ligne claire comic, flat colours, uniform outlines, not Japanese anime style")


def test_what_the_author_reads_stays_french() -> None:
    for genre in REG.style_genres.values():
        assert ACCENTS.search(genre.scene_test) or " et " in genre.scene_test or " un" in genre.scene_test, genre.id
    assert REG.style_genres["franco-belge"].name == "Franco-belge"
    assert REG.reference_sheet("personnage-portrait").name == "Portrait de face"
