"""Réglage « Dessin des personnages » d'une série (style_options.yaml › dessin) : « Épuré » REMPLACE les mots de
détail du genre, du rendu et des réglages fins au lieu d'en ajouter (mesuré le 14/10/2026 : ajouter ne change
rien) ; ses mots anti-détail vont aux fiches ($subject) et aux cases ($finition), son négatif aux deux ;
« Détaillé (genre) » ne change rien (golden). Une fiche créée avant le passage en Épuré le dit, et « Refaire la
base » repart sans image de départ en gardant l'ancienne version."""

from __future__ import annotations

import dataclasses
import itertools
import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.reference_sheets import sheet_params, sheet_prompt
from mangaka_engine.pipeline.style import (
    drawing_record,
    series_finition,
    series_style,
    series_style_lead,
    series_style_negative,
    series_subject,
    stale_drawing,
    style_groups,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import StyleOption, StyleOptionChoice, StylePack
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.models import Project
from tests.conftest import PRESETS_DIR, STYLE, png_bytes
from tests.test_finition import GOLDEN, _prompts, _sha
from tests.test_reference_sheets import _entry

REG = PresetRegistry.load(PRESETS_DIR)
EPURE = REG.style_options.options["dessin"].choices["epure"]
RECIPE = (
    "clean simple manga line art, thin uniform black outlines, flat white paper, a few flat grey screentone areas, "
    "no shading, no gradients, no hatching, minimal detail, simplified facial features, large empty white areas, "
    "uncluttered"
)
DETAIL = ["mature detailed ink style", "thick bold linework, heavy inking", "medium-density halftone"]
SUBJECT = "plain smooth untextured surfaces, no mechanical panel lines, no rivets, no greebles"
SENTENCE = SUBJECT[:1].upper() + SUBJECT[1:]  # en tête de phrase : `$finition` des cases, `$subject` des fiches
NEGATIVE = ["mechanical panel lines", "rivets", "sci-fi greebles", "intricate details", "cross-hatching"]


def _series(**kw: Any) -> Project:
    values: dict[str, Any] = {
        "id": 1,
        "title": "Space voyage",
        "legacy_style": "",
        "style_genre": "seinen",
        "style_rendering": "nb-trames",
        "style_tone": "neutre",
        "style_options": {},
        "style_lora_name": None,
        "page_format": "a4-300dpi",
        "workflow_preset": "qwen-image-turbo",
        "style_lora_weight": 0.8,
        **kw,
    }
    return Project(**values)


def _uncapped() -> PresetRegistry:
    return dataclasses.replace(REG, image_prompt=REG.image_prompt.model_copy(update={"style_max_chars": None}))


# --- le réglage : des presets, pas du code ------------------------------------------------------------
def test_dessin_option_offers_detailed_and_clean_with_the_measured_recipe() -> None:
    option = REG.style_options.options["dessin"]
    assert option.name == "Dessin des personnages" and option.piece is None and not option.monochrome_only
    assert "Épuré : traits fins et simples, peu de détails, pour que la série ne ressemble pas aux autres" in (
        option.description
    )
    assert [c.name for c in option.choices.values()] == ["Détaillé (genre)", "Épuré"]
    neutral = option.choices["detaille"]
    assert neutral.prompt_keywords == [] and neutral.replaces == [] and neutral.negative_keywords == []
    assert ", ".join(EPURE.prompt_keywords) == RECIPE
    assert EPURE.monochrome_keywords == [
        "flat white paper",
        "a few flat grey screentone areas",
        "large empty white areas",
    ]
    assert ", ".join(EPURE.subject_keywords) == SUBJECT and EPURE.negative_keywords == NEGATIVE
    # Rien de propre à une série ou à un costume (« spacesuit », « mecha » des essais du 14/10).
    words = " ".join([*EPURE.prompt_keywords, *EPURE.subject_keywords, *EPURE.negative_keywords]).casefold()
    assert "spacesuit" not in words and "mecha " not in words


def test_schema_rules_for_replacing_choices() -> None:
    choice = {"name": "E", "lang": "en", "prompt_keywords": ["thin lines"], "replaces": ["thick lines"]}
    empty = {"name": "D", "lang": "en", "prompt_keywords": []}
    # Le choix neutre d'un réglage qui remplace peut être vide ; sans `replaces` dans le réglage, non.
    StyleOption.model_validate({"name": "Dessin", "choices": {"d": empty, "e": choice}})
    with pytest.raises(ValidationError, match="sans mot-clé"):
        StyleOption.model_validate({"name": "Dessin", "choices": {"d": empty}})
    # Négatif permis avec `replaces`, toujours refusé sur un choix ordinaire.
    StyleOption.model_validate({"name": "Dessin", "choices": {"e": {**choice, "negative_keywords": ["rivets"]}}})
    with pytest.raises(ValidationError, match="negative_keywords permis seulement"):
        StyleOption.model_validate(
            {"name": "T", "choices": {"n": {**empty, "prompt_keywords": ["a"], "negative_keywords": ["b"]}}}
        )
    with pytest.raises(ValidationError, match="pièce réservée"):
        StyleOption.model_validate({"name": "F", "piece": "finition", "choices": {"e": choice}})
    with pytest.raises(ValidationError, match="subject_keywords permis seulement avec `replaces`"):
        StyleOptionChoice.model_validate({**empty, "prompt_keywords": ["a"], "subject_keywords": ["plain"]})
    with pytest.raises(ValidationError, match="propres mots-clés"):
        StyleOptionChoice.model_validate({**empty, "replaces": ["thick lines"]})
    with pytest.raises(ValidationError, match="virgule"):
        StyleOptionChoice.model_validate({**choice, "replaces": ["thick, bold"]})
    # `{text, monochrome}` : réservé aux choix des réglages fins, pas aux packs.
    mono = StyleOptionChoice.model_validate(
        {**choice, "prompt_keywords": [{"text": "white paper", "monochrome": True}]}
    )
    assert mono.monochrome_keywords == ["white paper"]
    pack = {"id": "x", "name": "X", "description": "x", "lang": "en"}
    with pytest.raises(ValidationError):
        StylePack.model_validate({**pack, "prompt_keywords": [{"text": "white paper", "monochrome": True}]})


# --- $style : remplacer, pas ajouter ---------------------------------------------------------------------
def test_clean_seinen_screentone_style_replaces_the_detail_words() -> None:
    """Critère d'acceptation : Seinen + N&B à trames + Épuré (+ trait épais, trames moyennes, la série du 14/10)."""
    fine = {"trait": "epais", "trames": "moyennes"}
    detailed = series_style(REG, _series(style_options=fine))
    assert all(d in detailed for d in DETAIL)  # la chaîne du job 643
    style = series_style(REG, _series(style_options={**fine, "dessin": "epure"}))
    assert not [d for d in DETAIL if d in style], style
    assert style == RECIPE  # la recette mesurée part entière, en tête
    assert len(style) <= REG.image_prompt.style_max_chars == 240
    # Fiche de personnage (création : aucune image de départ) : le même $style.
    sheet = REG.reference_sheet("personnage-portrait")
    prompt = sheet_prompt(REG, sheet, _entry("character"), _series(style_options={**fine, "dessin": "epure"}))
    assert f"Style: {RECIPE}." in prompt and not [d for d in DETAIL if d in prompt]


def test_replacing_is_not_adding() -> None:
    """P1 (chaîne complète + mots épurés à la suite) sortait détaillé : les mots de détail ne doivent plus y être,
    même sans plafond, et les mots épurés passent devant, pas derrière."""
    reg = _uncapped()
    fine = {"trait": "epais", "trames": "moyennes", "detail": "riche"}
    added = series_style(reg, _series(style_options=fine)) + ", " + RECIPE  # P1
    replaced = series_style(reg, _series(style_options={**fine, "dessin": "epure"}))
    assert replaced != added and replaced.startswith(RECIPE)
    removed = {w.casefold() for w in EPURE.replaces}
    assert not [w for w in replaced.split(", ") if w.casefold() in removed], replaced
    # Ce qui n'est pas du détail reste : genre, rendu, ton, décor riche.
    for word in ("seinen manga", "black and white manga", "no cross-hatching", "neutral calm atmosphere"):
        assert word in replaced
    assert "richly detailed background" in replaced and "many intricate details" not in replaced
    kinds = [k for k, _ in style_groups(reg, _series(style_options={**fine, "dessin": "epure"}))]
    assert kinds[:3] == ["lora", "replacing", "genre"]


@pytest.mark.parametrize(
    ("fine", "kept", "gone"),
    [
        ({"trait": "fin"}, ["thin linework", "delicate lines"], []),
        ({"trait": "epais"}, [], ["thick bold linework", "heavy inking"]),
        ({"trames": "legeres"}, ["light screentone", "subtly grey"], []),
        ({"trames": "denses"}, [], ["dense dark screentone"]),
    ],
)
def test_clean_drawing_combines_with_trait_and_trames(fine: dict[str, str], kept: list[str], gone: list[str]) -> None:
    style = series_style(_uncapped(), _series(style_options={**fine, "dessin": "epure"}))
    assert style.startswith(RECIPE)
    assert all(k in style for k in kept) and not [g for g in gone if g in style], style


def test_clean_drawing_combines_with_finition() -> None:
    """La finition (pièce réservée, choisie exprès) reste entière ; les mots anti-détail la suivent dans `$finition`
    et les deux négatifs s'additionnent."""
    series = _series(style_options={"dessin": "epure", "finition": "croquis"})
    croquis = REG.style_options.options["finition"].choices["croquis"]
    finition = series_finition(REG, series)
    assert finition == "Rough hand-drawn ink sketch, " + ", ".join(croquis.prompt_keywords[1:]) + ", " + SUBJECT
    assert series_style_negative(REG, series) == [*croquis.negative_keywords, *NEGATIVE]
    assert series_style(REG, series) == RECIPE  # la finition n'entre jamais dans $style
    # Épuré seul : `$finition` = les mots anti-détail ; Détaillé : rien.
    assert series_finition(REG, _series(style_options={"dessin": "epure"})) == SENTENCE
    assert series_finition(REG, _series(style_options={"dessin": "detaille"})) == ""
    assert series_subject(REG, _series()) == "" and series_style_negative(REG, _series()) == []


def test_style_lead_drops_the_detail_part_of_the_rendering_sentence() -> None:
    assert series_style_lead(REG, _series()) == (
        "Black and white manga panel, hand-drawn inked line art with halftone screentone shading, seinen manga style."
    )
    assert series_style_lead(REG, _series(style_options={"dessin": "epure"})) == (
        "Black and white manga panel, seinen manga style."
    )
    encre = _series(style_rendering="nb-encre", style_options={"dessin": "epure"})
    assert series_style_lead(REG, encre) == "Black and white manga panel, seinen manga style."
    assert "cross-hatching" not in series_style(REG, encre)


def test_jeunesse_and_franco_belge_keep_their_identity() -> None:
    jeunesse = _series(style_genre="jeunesse", style_tone="lumineux", style_options={"dessin": "epure"})
    style = series_style(_uncapped(), jeunesse)
    assert style.startswith(RECIPE) and "children's manga" in style and "simple cute style" in style
    assert series_style_lead(REG, jeunesse).endswith("children's manga style.")
    # Franco-belge en couleur : pas de papier blanc ni de trames grises (mots N&B), pas d'aplat ombré « cel ».
    fb = _series(style_genre="franco-belge", style_rendering="couleur", style_options={"dessin": "epure"})
    style = series_style(REG, fb)
    assert len(style) <= REG.image_prompt.style_max_chars
    assert style.startswith("clean simple manga line art, thin uniform black outlines, no shading")
    assert not [w for w in EPURE.monochrome_keywords if w in style] and "cel shading" not in style
    assert "European ligne claire comic" in style and "color manga" in style
    assert series_style_lead(REG, fb) == (
        "Colour comic panel, hand-drawn inked line art with flat cel-shaded colours, European ligne claire comic style."
    )


def test_legacy_series_text_is_replaced_too() -> None:
    """Série d'avant les packs (ancien texte libre `legacy_style` à la place du genre)."""
    legacy = dict(style_genre=None, style_rendering=None, style_tone=None)
    text = "mature detailed ink style, dramatic shadows"
    before = series_style(REG, _series(**legacy, legacy_style=text))
    assert before.startswith("mature detailed ink style")
    after = series_style(_uncapped(), _series(**legacy, legacy_style=text, style_options={"dessin": "epure"}))
    assert after.startswith(RECIPE) and "dramatic shadows" in after and "mature detailed ink style" not in after
    lead = series_style_lead(REG, _series(**legacy, legacy_style=text, style_options={"dessin": "epure"}))
    assert lead == "Black and white manga panel, dramatic shadows style."


# --- « Détaillé » : rien ne change ----------------------------------------------------------------------
def test_detailed_or_unset_style_is_strictly_identical_for_every_combination() -> None:
    fine = [{}, {"trait": "epais", "trames": "denses", "detail": "riche", "finition": "scan"}]
    for genre, rendering, tone in itertools.product(REG.style_genres, REG.style_renderings, REG.style_tones):
        for opts in fine:
            base = _series(style_genre=genre, style_rendering=rendering, style_tone=tone, style_options=opts)
            same = _series(
                style_genre=genre,
                style_rendering=rendering,
                style_tone=tone,
                style_options={**opts, "dessin": "detaille"},
            )
            for people in (True, False):
                assert series_style(REG, same, people=people) == series_style(REG, base, people=people)
            assert series_style_lead(REG, same) == series_style_lead(REG, base)
            assert series_finition(REG, same) == series_finition(REG, base)
            assert series_style_negative(REG, same) == series_style_negative(REG, base)
            assert series_subject(REG, same) == ""


def test_golden_prompts_are_byte_identical_with_the_detailed_drawing() -> None:
    """Golden des cases figé avant la finition (56 séries) : en « Détaillé (genre) », prompt par fragments, prompt
    du rédacteur et empreinte du brief inchangés."""
    golden = json.loads(GOLDEN.read_text())
    tones = list(REG.style_tones)
    options = [{}, {"trait": "epais", "trames": "denses", "detail": "riche"}]
    for i, (genre, rendering) in enumerate(itertools.product(REG.style_genres, REG.style_renderings)):
        for j, opts in enumerate(options):
            tone = tones[i % len(tones)]
            series = _series(
                style_genre=genre,
                style_rendering=rendering,
                style_tone=tone,
                style_options={**opts, "dessin": "detaille"},
            )
            fragments, writer, key = _prompts(series)
            expected = golden[f"{genre}/{rendering}/{tone}/{j}"]
            assert (_sha(fragments), _sha(writer), key) == (
                expected["fragments"],
                expected["writer"],
                expected["brief_key"],
            ), (genre, rendering, tone, j)


@pytest.mark.parametrize("kind", ["character", "object", "decor"])
def test_sheets_carry_the_subject_words_and_negative_only_when_clean(kind: str) -> None:
    sheet = next(s for s in REG.reference_sheets.values() if kind in s.kinds)
    entry = _entry(kind)
    loaded = REG.workflow("qwen-image-base-qualite")
    detailed, clean = _series(style_options={"dessin": "detaille"}), _series(style_options={"dessin": "epure"})
    before = sheet_prompt(REG, sheet, entry, _series())
    assert sheet_prompt(REG, sheet, entry, detailed) == before and SUBJECT not in before
    after = sheet_prompt(REG, sheet, entry, clean)
    assert f"Style: {series_style(REG, clean, people=kind == 'character')}. {SENTENCE}." in after
    neg_before = sheet_params(loaded, sheet, before, REG, series=_series())["negative_prompt"]
    assert sheet_params(loaded, sheet, before, REG)["negative_prompt"] == neg_before
    assert sheet_params(loaded, sheet, before, REG, series=detailed)["negative_prompt"] == neg_before
    neg_after = sheet_params(loaded, sheet, after, REG, series=clean)["negative_prompt"]
    terms = [t.strip() for t in neg_after.split(",")]
    assert all(terms.count(t) == 1 for t in NEGATIVE) and neg_after.startswith(neg_before.split(",")[0])


# --- fiches existantes : « ancien rendu », « Refaire la base » --------------------------------------------
def test_stale_drawing_detection() -> None:
    clean = _series(style_options={"dessin": "epure"})
    assert drawing_record(REG, clean) == {"dessin": "epure"} and drawing_record(REG, _series()) == {}
    assert stale_drawing(REG, _series(), {}) is None  # série en Détaillé : rien à dire
    for before in (None, {}, {"dessin": "detaille"}):
        stale = stale_drawing(REG, clean, before)
        assert stale is not None, before
        assert stale.message == "Créée avec l'ancien rendu (détaillé)"
        assert stale.action == "Refaire la base en épuré"
    assert stale_drawing(REG, clean, {"dessin": "epure"}) is None


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def comfy() -> MockComfyUIClient:
    return MockComfyUIClient()


@pytest.fixture
def c(make_settings: Callable[..., Settings], comfy: MockComfyUIClient) -> Iterator[TestClient]:
    providers = Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=comfy,
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(make_settings(), providers=providers)) as client:
        yield client


def _idle(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(15)  # type: ignore[attr-defined]


SEINEN = {"style_genre": "seinen", "style_rendering": "nb-trames", "style_tone": "neutre"}


def test_old_base_is_flagged_and_rebuilt_from_scratch_keeping_the_old_version(c: TestClient) -> None:
    s = _ok(c.post("/projects", json={**SEINEN, "title": "Space voyage", "style_options": {"trait": "epais"}}), 201)
    alan = _ok(
        c.post(
            f"/projects/{s['id']}/characters",
            json={"name": "alan", "visual_description": "combinaison spatiale style mechatronique"},
        ),
        201,
    )
    url = f"/characters/{alan['id']}/reference-variants"
    [job] = _ok(c.post(url, json={"sheet": "personnage-portrait", "count": 1}), 202)
    assert job["params"]["drawing"] == {}
    _idle(c)
    [old] = _ok(c.get(url))["variants"]
    assert "mature detailed ink style" in old["prompt"]  # MOCK : le prompt de fiche envoyé, avant
    kept = _ok(c.post(f"/reference-variants/{old['id']}/keep"), 201)
    [old_image] = kept["reference_images"]
    assert _ok(c.get(url))["stale_drawing"] is None  # série en Détaillé

    # La série passe en Épuré : la fiche garde son trait et le dit.
    _ok(c.patch(f"/projects/{s['id']}", json={"style_options": {"trait": "epais", "dessin": "epure"}}))
    stale = _ok(c.get(url))["stale_drawing"]
    assert stale == {
        "option": "dessin",
        "message": "Créée avec l'ancien rendu (détaillé)",
        "action": "Refaire la base en épuré",
        "image_id": old_image["id"],
        "sheet": "personnage-portrait",
    }

    # « Refaire la base en épuré » : jamais d'image de départ.
    refused = c.post(url, json={"sheet": "personnage-portrait", "rebase": True, "start_image_id": old_image["id"]})
    assert refused.status_code == 422
    [job] = _ok(c.post(url, json={"sheet": "personnage-portrait", "count": 1, "rebase": True}), 202)
    assert job["params"]["start_image_id"] is None and job["params"]["parent_id"] is None
    assert job["params"]["rebase"] is True and job["params"]["drawing"] == {"dessin": "epure"}
    _idle(c)
    new = _ok(c.get(url))["variants"][0]
    assert new["params"]["reference_images"] == []  # rien envoyé : ni image de départ, ni planche de style
    # MOCK : le prompt de fiche envoyé, après (même série) — la recette, plus les mots de détail.
    assert f"Style: {RECIPE}. {SENTENCE}." in new["prompt"]
    assert not [d for d in DETAIL if d in new["prompt"]]
    assert all(t in new["params"]["negative_prompt"] for t in NEGATIVE)

    # Gardée : elle devient l'image principale, l'ancienne base reste (rien d'effacé).
    kept = _ok(c.post(f"/reference-variants/{new['id']}/keep"), 201)
    assert [img["id"] for img in kept["reference_images"]][1:] == [old_image["id"]]
    assert len(kept["reference_images"]) == 2
    studio = _ok(c.get(url))
    assert studio["stale_drawing"] is None and len(studio["variants"]) == 2


def test_uploaded_base_is_not_flagged(c: TestClient) -> None:
    s = _ok(c.post("/projects", json={**STYLE, "title": "S", "style_options": {"dessin": "epure"}}), 201)
    aiko = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko", "visual_description": "x"}), 201)
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    assert _ok(c.get(f"/characters/{aiko['id']}/reference-variants"))["stale_drawing"] is None


def test_clean_panels_get_the_subject_words_and_the_negative_at_quality(c: TestClient) -> None:
    s = _ok(
        c.post("/projects", json={**SEINEN, "title": "S", "ai_prompt": False, "style_options": {"dessin": "epure"}}),
        201,
    )
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "Un couloir"}]}]}))
    pid = page["panels"][0]["id"]
    for preset in ("qwen-image-turbo", "qwen-image-base-qualite"):
        _ok(c.post(f"/panels/{pid}/generate", json={"preset": preset}), 202)
        _idle(c)
    images = _ok(c.get(f"/panels/{pid}/images"))
    for image in images:
        prompt = image["params"]["prompt"]
        assert prompt.startswith(f"Black and white manga panel, seinen manga style. {SENTENCE}.")
        assert f"Style: {RECIPE}." in prompt
        terms = [t.strip() for t in image["params"]["negative_prompt"].split(",")]
        assert all(terms.count(t) == 1 for t in NEGATIVE), image["tier"]
    assert {i["tier"] for i in images} >= {"Qualité"}


def test_presets_and_series_api_offer_the_drawing(c: TestClient) -> None:
    option = next(o for o in _ok(c.get("/presets"))["style_options"] if o["id"] == "dessin")
    assert [ch["name"] for ch in option["choices"]] == ["Détaillé (genre)", "Épuré"]
    s = _ok(c.post("/projects", json={**STYLE, "title": "S", "style_options": {"dessin": "epure"}}), 201)
    assert s["style_options"] == {"dessin": "epure"}
    assert s["style_prompt"].startswith("clean simple manga line art")
    bad = c.patch(f"/projects/{s['id']}", json={"style_options": {"dessin": "minimaliste"}})
    assert bad.status_code == 422 and "Dessin des personnages" in bad.text
