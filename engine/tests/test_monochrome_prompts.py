"""Série en noir et blanc : aucun mot de couleur envoyé à ComfyUI (prompts déjà stockés compris) ; ambiance de
la case plus forte que le ton de la série (13/10/2026, chapitre 3)."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi.testclient import TestClient

from mangaka_engine.pipeline.prompt import (
    ReferenceSlot,
    build_negative_prompt,
    frame_references,
    mood_dropped_terms,
    remove_terms,
    term_pattern,
)
from mangaka_engine.pipeline.prompt_writer import PromptBrief, PromptValidationError, parse_written, render_messages
from mangaka_engine.pipeline.style import series_style
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.store.models import Panel, Project
from tests.conftest import PRESETS_DIR, STYLE, png_bytes

REG = PresetRegistry.load(PRESETS_DIR)
SETTINGS = REG.image_prompt
COLOUR_STYLE = {**STYLE, "style_rendering": "couleur"}
# Prompt d'avant ce changement, tel que stocké sur une case (rédigé par l'IA puis gardé) : rôle avec
# « colours », liquide vert, palette chaude.
OLD_PROMPT = (
    "<image1> is the identity reference for Aiko: keep the face, hair, outfit and colours; ignore its pose, "
    "framing and background. Aiko pours the thick green liquid into a golden bowl, in vibrant colors, "
    "under a warm color palette."
)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _colour_words(text: str) -> list[str]:
    return [t for t in SETTINGS.monochrome_forbidden_terms if term_pattern(t).search(text)]


# --- fonctions pures --------------------------------------------------------------------------------
def test_colour_terms_are_removed_and_punctuation_stitched() -> None:
    terms = SETTINGS.monochrome_forbidden_terms
    assert remove_terms("He pours the thick green liquid.", terms) == "He pours the thick liquid."
    assert (
        remove_terms("keep the face, hair, outfit and colours; ignore its pose", terms)
        == "keep the face, hair, outfit; ignore its pose"
    )
    assert remove_terms("(line work, inking, screentones, colours): x", terms) == "(line work, inking, screentones): x"
    assert remove_terms("(face, outfit, colours, materials)", terms) == "(face, outfit, materials)"
    assert remove_terms("A street in vibrant colors, with lanterns.", terms) == "A street, with lanterns."
    # Le reste du texte ne bouge pas (espace française avant « ; ») ; noir, blanc et gris restent.
    assert remove_terms("Urus (dragon bleu) ; Kaël à droite.", terms) == "Urus (dragon) ; Kaël à droite."
    assert remove_terms("Black and white manga, grey screentone.", terms) == "Black and white manga, grey screentone."
    # Mots entiers seulement, et jamais un nom de fiche de la case.
    assert remove_terms("A greenhouse, blue-green glass.", terms) == "A greenhouse, blue-green glass."
    assert remove_terms("Violet holds a red scarf.", terms, keep=["Violet"]) == "Violet holds a scarf."


def test_bw_reference_wording_has_no_colours_and_colour_series_keeps_it() -> None:
    slots = [ReferenceSlot("character", "Aiko"), ReferenceSlot("object", "Sabre"), ReferenceSlot("style", "Planche")]
    bw = frame_references("Scene.", slots, SETTINGS, monochrome=True)
    assert "colours" not in bw and not _colour_words(bw)
    assert "<image1> is the identity reference for Aiko: keep the face, hair and outfit;" in bw
    assert "<image2> is the design reference for the object Sabre: keep its shape and details." in bw
    assert "<image3> is a style reference only (line work, inking, screentones):" in bw
    colour = frame_references("Scene.", slots, SETTINGS)
    assert "keep the face, hair, outfit and colours;" in colour and "keep its shape, colours and details" in colour


def test_bw_negative_prompt_refuses_colour() -> None:
    bw = build_negative_prompt("blurry", SETTINGS, monochrome=True)
    assert bw.endswith("color, colored, colorful")
    assert "color" not in build_negative_prompt("blurry", SETTINGS)


def test_fear_mood_drops_the_bright_tone_keywords() -> None:
    dropped = mood_dropped_terms("Peur panique, lumière blafarde", SETTINGS)
    assert {"smiles", "bright joyful atmosphere", "warm light"} <= set(dropped)
    for mood in ("fear", "tension", "Tristesse", "colère", "menace", "terreur", "angoissant"):
        assert "bright joyful atmosphere" in mood_dropped_terms(mood, SETTINGS), mood
    assert mood_dropped_terms("matin calme, lumière de jour", SETTINGS) == []
    assert mood_dropped_terms("", SETTINGS) == []
    # Le ton « lumineux » n'impose plus de sourire à toute la série.
    assert "smiles" not in REG.style_tones["lumineux"].prompt_keywords
    series = Project(title="x", style_genre="shonen", style_rendering="nb-trames", style_tone="lumineux")
    assert "bright joyful atmosphere" in series_style(REG, series)
    assert "bright joyful" not in series_style(REG, series, drop=dropped)


# --- rédacteur de prompt ----------------------------------------------------------------------------
def _brief(monochrome: bool) -> PromptBrief:
    return PromptBrief.build(
        description="Aiko verse le liquide vert épais",
        references=[ReferenceSlot("character", "Aiko")],
        prompt=REG.prompt("redacteur-image"),
        settings=SETTINGS,
        monochrome=monochrome,
    )


def test_writer_is_told_and_forced_not_to_write_colour_words() -> None:
    bw, colour = _brief(True), _brief(False)
    assert bw.reference_lines()[0]["role"] == (
        "the identity reference for Aiko: keep the face, hair and outfit; ignore its pose, framing and background"
    )
    assert "outfit and colours" in colour.reference_lines()[0]["role"]
    assert bw.description == "Aiko verse le liquide épais"  # données de la case sans couleur
    assert colour.description == "Aiko verse le liquide vert épais"
    system = render_messages(REG.prompt("redacteur-image"), bw)[0].content
    assert "never write a colour word" in system
    assert "colour word" not in render_messages(REG.prompt("redacteur-image"), colour)[0].content

    words = " ".join(["Aiko draws a careful line across the page."] * 25)
    paragraph = f"<image1> is the identity reference for Aiko. Aiko pours the thick green liquid. {words}"
    answer = json.dumps({"prompt": paragraph, "language": "en"})
    try:
        parse_written(answer, bw)
        raise AssertionError("paragraphe avec « green » accepté pour une série en noir et blanc")
    except PromptValidationError as exc:
        assert "mots de couleur interdits : green" in str(exc)
    assert parse_written(answer, colour).prompt  # série en couleur : accepté


# --- de bout en bout (mock) --------------------------------------------------------------------------
def _panel_with_old_prompt(c: TestClient, style: dict[str, str], ambiance: str | None = None) -> dict[str, Any]:
    s = _ok(c.post("/projects", json={**style, "title": "Vert", "ai_prompt": False}), 201)
    aiko = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un", "synopsis": "Aiko verse le liquide."}), 201)
    from mangaka_engine.pipeline.pages import layout_pages
    from mangaka_engine.pipeline.script import ScriptOutput, save_script
    from mangaka_engine.store.models import Chapter

    output = ScriptOutput.model_validate(
        {
            "pages": [
                {
                    "panels": [
                        {"description": "Aiko verse le liquide.", "characters": ["Aiko"], "shot_type": "plan large"}
                    ]
                }
            ],
            "summary": "x",
        }
    )
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        chapter = session.get(Chapter, ch["id"])
        assert chapter is not None
        layout_pages(REG, save_script(session, chapter, output))
        session.commit()
    [panel] = _ok(c.get(f"/chapters/{ch['id']}/pages"))[0]["panels"]
    # Prompt stocké avant le changement (édité à la main : jamais reconstruit).
    _ok(c.patch(f"/panels/{panel['id']}", json={"final_prompt": OLD_PROMPT}))
    if ambiance is not None:
        with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
            row = session.get(Panel, panel["id"])
            assert row is not None
            row.dialog_direction = {"ambiance": ambiance}
            session.commit()
    return panel


def _generate(c: TestClient, panel_id: int) -> dict[str, Any]:
    [job] = _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    return next(i for i in _ok(c.get(f"/panels/{panel_id}/images")) if i["params"]["job_id"] == job["id"])["params"]


def test_bw_series_sends_no_colour_word_even_for_a_stored_prompt(client: TestClient) -> None:
    panel = _panel_with_old_prompt(client, STYLE)
    params = _generate(client, panel["id"])
    sent = params["prompt"]
    assert params["panel_prompt"] == OLD_PROMPT  # le prompt de la case n'est pas réécrit
    assert "colours" not in sent and _colour_words(sent) == [], _colour_words(sent)
    assert "Aiko pours the thick liquid into a bowl" in sent
    assert "keep the face, hair, outfit; ignore its pose" in sent
    assert re.search(r"\bcolor, colored, colorful\b", params["negative_prompt"])


def test_colour_series_sends_the_stored_prompt_unchanged(client: TestClient) -> None:
    panel = _panel_with_old_prompt(client, COLOUR_STYLE)
    params = _generate(client, panel["id"])
    assert OLD_PROMPT in params["prompt"]
    assert "colored" not in params["negative_prompt"]


def test_fear_panel_of_a_bright_series_gets_no_smile_nor_bright_joy(client: TestClient) -> None:
    style = {**STYLE, "style_tone": "lumineux"}
    stored = OLD_PROMPT + " Style: shonen manga, bright joyful atmosphere, warm light, smiles."
    fear = _panel_with_old_prompt(client, style, ambiance="Peur, le trafiquant blêmit de terreur")
    _ok(client.patch(f"/panels/{fear['id']}", json={"final_prompt": stored}))
    sent = _generate(client, fear["id"])["prompt"]
    assert "smiles" not in sent and "bright joyful" not in sent and "warm light" not in sent
    assert "Style: shonen manga." in sent

    calm = _panel_with_old_prompt(client, style, ambiance="Matin calme au village")
    _ok(client.patch(f"/panels/{calm['id']}", json={"final_prompt": stored}))
    assert "bright joyful atmosphere" in _generate(client, calm["id"])["prompt"]
