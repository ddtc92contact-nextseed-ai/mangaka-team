"""Réglage « Finition » d'une série (style_options.yaml › finition) : pièce réservée `$finition` juste après la
phrase de style, dans chaque prompt de case, jamais dans `$style` ; négatif de finition ; « propre » ne change
rien (golden : prompts identiques, octet pour octet, à ceux d'avant le réglage)."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mangaka_engine.pipeline.generation import _prompt_entry, build_panel_prompt
from mangaka_engine.pipeline.prompt_writer import PromptBrief, finish_paragraph
from mangaka_engine.pipeline.style import (
    series_finition,
    series_finition_negative,
    series_monochrome,
    series_style,
    series_style_lead,
    style_groups,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import StyleOption
from mangaka_engine.store.models import Chapter, Character, Page, Panel, Project
from tests.conftest import LEAD, PRESETS_DIR, STYLE
from tests.test_prompt_writer import Env, _generate, _ok, _setup, _wait, env  # noqa: F401 — fixture

REG = PresetRegistry.load(PRESETS_DIR)
GOLDEN = Path(__file__).parent / "golden" / "prompts-avant-finition.json"
SCAN = (
    "Printed on cheap paper, coarse halftone dots, paper grain, off-white paper, faint ghosting, "
    "slight ink misregistration"
)
ANTI_SMOOTH = [
    "clean digital line art",
    "smooth vector lines",
    "glossy airbrush",
    "over-rendered",
    "polished 3d render",
    "perfect gradients",
    "slick illustration",
]


def _series(**kw: Any) -> Project:
    values: dict[str, Any] = {
        "id": 1,
        "title": "S",
        "legacy_style": "",
        "style_genre": "seinen",
        "style_rendering": "nb-trames",
        "style_tone": "dark",
        "style_options": {},
        "style_lora_name": None,
        **kw,
    }
    return Project(**values)


# --- accès -------------------------------------------------------------------------------------------
def test_finition_option_is_a_reserved_piece_with_four_choices() -> None:
    option = REG.style_options.options["finition"]
    assert option.name == "Finition" and option.piece == "finition" and not option.monochrome_only
    assert list(option.choices) == ["propre", "croquis", "pinceau-nerveux", "scan"]
    assert option.choices["propre"].prompt_keywords == [] and option.choices["propre"].negative_keywords == []
    assert all(c.lang == "en" for c in option.choices.values())


@pytest.mark.parametrize(
    ("choice", "expected", "negative"),
    [
        ("scan", SCAN, ANTI_SMOOTH),
        (
            "croquis",
            "Rough hand-drawn ink sketch, visible pencil underdrawing, unclosed lines, quick loose strokes, "
            "the artist's hand is visible, deliberately unfinished",
            ANTI_SMOOTH,
        ),
        (
            "pinceau-nerveux",
            "Confident rough brush inking, dry brush strokes, ink splatter, rough hatching, visible stroke ends, "
            "uneven ink density",
            [],
        ),
        ("propre", "", []),
    ],
)
def test_series_finition_and_its_negative(choice: str, expected: str, negative: list[str]) -> None:
    series = _series(style_options={"finition": choice})
    assert series_finition(REG, series) == expected
    assert series_finition_negative(REG, series) == negative


def test_no_finition_unknown_choice_or_colour_rendering() -> None:
    assert series_finition(REG, _series()) == "" and series_finition_negative(REG, _series()) == []
    unknown = _series(style_options={"finition": "aquarelle"})
    assert series_finition(REG, unknown) == "" and series_finition_negative(REG, unknown) == []
    # pas réservé au N&B : un croquis sert aussi une série en couleur
    colour = _series(style_rendering="couleur", style_options={"finition": "croquis"})
    assert series_finition(REG, colour).startswith("Rough hand-drawn ink sketch")
    assert series_finition_negative(REG, colour) == ANTI_SMOOTH


def test_schema_keeps_empty_keywords_and_negatives_for_reserved_pieces_only() -> None:
    choice = {"name": "Vide", "lang": "en", "prompt_keywords": []}
    StyleOption.model_validate({"name": "F", "piece": "finition", "choices": {"vide": choice}})
    with pytest.raises(ValidationError, match="sans mot-clé"):
        StyleOption.model_validate({"name": "Trait", "choices": {"vide": choice}})
    neg = {"name": "N", "lang": "en", "prompt_keywords": ["thin lines"], "negative_keywords": ["blur"]}
    with pytest.raises(ValidationError, match="negative_keywords permis seulement avec `piece`"):
        StyleOption.model_validate({"name": "Trait", "choices": {"n": neg}})
    with pytest.raises(ValidationError):
        StyleOption.model_validate({"name": "F", "piece": "style", "choices": {"vide": choice}})


# --- $style garde ses 240 caractères ------------------------------------------------------------------
@pytest.mark.parametrize("choice", ["propre", "croquis", "pinceau-nerveux", "scan"])
def test_finition_never_enters_style(choice: str) -> None:
    fine = {"trait": "epais", "trames": "denses", "detail": "riche"}
    for genre, rendering in itertools.product(REG.style_genres, REG.style_renderings):
        base = _series(style_genre=genre, style_rendering=rendering, style_options=dict(fine))
        chosen = _series(style_genre=genre, style_rendering=rendering, style_options={**fine, "finition": choice})
        style = series_style(REG, chosen)
        assert style == series_style(REG, base) and len(style) <= REG.image_prompt.style_max_chars
        words = {w.casefold() for _, g in style_groups(REG, chosen) for w in g}
        option = REG.style_options.options["finition"].choices[choice]
        assert not words & {k.casefold() for k in option.prompt_keywords}, (genre, rendering)


# --- prompt de case -------------------------------------------------------------------------------------
def _panel(series: Project) -> tuple[Panel, Character]:
    panel = Panel(
        id=1,
        description="Aiko esquive le sabre « Trop lent ! »",
        shot_type="gros plan",
        setting="ruelle sous la pluie",
        staging="Aiko à gauche, le rival à droite",
    )
    panel.page = Page(chapter=Chapter(project=series))
    aiko = Character(name="Aiko", visual_description="cheveux noirs, manteau long", prompt_keywords=["red scarf"])
    return panel, aiko


PARAGRAPH = "Aiko dodges the blade under the rain, her coat whipping behind her, the rival lunging from the left."


def _prompts(series: Project) -> tuple[str, str, str]:
    """Prompt par fragments, prompt du rédacteur (paragraphe fixe) et empreinte du brief — comme le golden."""
    panel, aiko = _panel(series)
    fragments = build_panel_prompt(REG, panel, [aiko], ("cadrage serré", "Aiko est gauchère"))
    brief = PromptBrief.build(
        description=panel.description,
        shot_type="gros plan",
        characters=[_prompt_entry(aiko)],
        style=series_style(REG, series),
        style_lead=series_style_lead(REG, series),
        finition=series_finition(REG, series),
        settings=REG.image_prompt,
        monochrome=series_monochrome(REG, series),
    )
    return fragments, finish_paragraph(PARAGRAPH, brief), brief.key()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("finition", [None, "propre"])
def test_golden_propre_prompts_are_byte_identical_to_before(finition: str | None) -> None:
    """Golden figé avant le réglage (56 séries : genre × rendu × ton × réglages fins) : sans finition ou en
    « propre », prompt par fragments, prompt du rédacteur et empreinte du brief (rien à réécrire) inchangés."""
    golden = json.loads(GOLDEN.read_text())
    tones = list(REG.style_tones)
    options = [{}, {"trait": "epais", "trames": "denses", "detail": "riche"}]
    seen = 0
    for i, (genre, rendering) in enumerate(itertools.product(REG.style_genres, REG.style_renderings)):
        for j, opts in enumerate(options):
            tone = tones[i % len(tones)]
            chosen = {**opts, **({"finition": finition} if finition else {})}
            series = _series(style_genre=genre, style_rendering=rendering, style_tone=tone, style_options=chosen)
            fragments, writer, key = _prompts(series)
            expected = golden[f"{genre}/{rendering}/{tone}/{j}"]
            assert _sha(fragments) == expected["fragments"], (genre, rendering, tone, j)
            assert _sha(writer) == expected["writer"], (genre, rendering, tone, j)
            assert key == expected["brief_key"], (genre, rendering, tone, j)
            if "fragments_text" in expected:
                assert fragments == expected["fragments_text"] and writer == expected["writer_text"]
            seen += 1
    assert seen == len(golden) == 56


def test_scan_goes_right_after_the_style_sentence_in_fragments_and_writer() -> None:
    series = _series(style_options={"finition": "scan"})
    lead = series_style_lead(REG, series)
    fragments, writer, key = _prompts(series)
    assert fragments.startswith(f"{lead} {SCAN}. Close-up, the face fills the frame")
    assert writer.startswith(f"{lead} {SCAN}. Aiko dodges the blade")
    style_part = fragments.split("Style: ")[1]
    assert "halftone dots" not in style_part and fragments.count("coarse halftone dots") == 1
    assert key != _prompts(_series())[2]  # changer de finition fait réécrire les prompts rédigés


def test_writer_moves_lead_and_finition_to_the_head_without_duplicates() -> None:
    series = _series(style_options={"finition": "croquis"})
    lead, fin = series_style_lead(REG, series), series_finition(REG, series)
    brief = PromptBrief.build(description="x", style_lead=lead, finition=fin, settings=REG.image_prompt)
    head = f"{lead} {fin}."
    for paragraph in (
        PARAGRAPH,
        f"{lead} {fin}. {PARAGRAPH}",  # déjà en place : inchangé
        f"{lead} {PARAGRAPH} {fin}.",  # finition en fin de paragraphe : remontée
        f"{fin}. {lead} {PARAGRAPH}",  # ordre inversé
    ):
        out = finish_paragraph(paragraph, brief)
        assert out == f"{head} {PARAGRAPH}", paragraph


# --- de bout en bout : chaque palier (mock) -------------------------------------------------------------
def _scan_series(c: TestClient, **series: Any) -> int:
    data = _setup(c, style_options={"finition": "scan"}, **series)
    return int(data["panel"]["id"])


@pytest.mark.parametrize("ai_prompt", [False, True])
def test_every_tier_gets_the_finition_and_its_negative(env: Env, ai_prompt: bool) -> None:  # noqa: F811
    """Croquis, Turbo, Qualité et passage au propre : `$finition` juste après la phrase de style dans le
    prompt de la case, et le négatif anti-lisse dans le négatif envoyé (prompt par fragments et rédacteur)."""
    c = env.c
    pid = _scan_series(c, ai_prompt=ai_prompt)
    head = f"{LEAD}{SCAN}."

    def check(image: dict[str, Any]) -> None:
        assert head in image["params"]["prompt"], image["tier"]
        negative = [t.strip() for t in image["params"]["negative_prompt"].split(",")]
        for term in ANTI_SMOOTH:
            assert negative.count(term) == 1, (image["tier"], term)

    # croquis
    _ok(c.post(f"/panels/{pid}/sketch"), 202)
    _wait(c)
    [sketch] = _ok(c.get(f"/panels/{pid}/images"))
    assert sketch["kind"] == "croquis"
    check(sketch)
    # Turbo et Qualité
    for preset, tier in (("qwen-image-edit-ref-turbo", "Turbo"), ("qwen-image-edit-ref-qualite", "Qualité")):
        _ok(c.post(f"/panels/{pid}/generate", json={"preset": preset}), 202)
        _wait(c)
        image = next(i for i in _ok(c.get(f"/panels/{pid}/images")) if i["params"].get("preset") == preset)
        assert image["tier"] == tier
        check(image)
    panel = _ok(c.get(f"/panels/{pid}"))
    assert panel["final_prompt"].startswith(head)
    assert panel["prompt_source"] == ("ia" if ai_prompt else "fragments")
    # passage au propre depuis le croquis validé
    _ok(c.post(f"/panels/{pid}/sketch/validate"))
    _ok(c.post(f"/panels/{pid}/clean"), 202)
    _wait(c)
    clean = next(i for i in _ok(c.get(f"/panels/{pid}/images")) if i["params"].get("sketch_image_id"))
    assert clean["params"]["prompt"] == sketch["params"]["prompt"]
    check(clean)


def test_propre_series_sends_no_finish_negative(env: Env) -> None:  # noqa: F811
    c = env.c
    data = _setup(c, style_options={"finition": "propre"}, ai_prompt=False)
    image = _generate(c, data["panel"]["id"])["images"][0]
    assert "clean digital line art" not in image["params"]["negative_prompt"]
    assert image["params"]["prompt"].count(LEAD.strip()) == 1


def test_series_sheet_api_accepts_finition_and_lists_it(env: Env) -> None:  # noqa: F811
    c = env.c
    presets = _ok(c.get("/presets"))
    option = next(o for o in presets["style_options"] if o["id"] == "finition")
    assert [ch["name"] for ch in option["choices"]] == [
        "Propre (rendu actuel)",
        "Croquis visible",
        "Pinceau nerveux",
        "Scan années 90",
    ]
    s = _ok(c.post("/projects", json={**STYLE, "title": "Scan", "style_options": {"finition": "scan"}}), 201)
    assert s["style_options"] == {"finition": "scan"}
    r = c.patch(f"/projects/{s['id']}", json={"style_options": {"finition": "aquarelle"}})
    assert r.status_code == 422 and "Finition" in r.text
