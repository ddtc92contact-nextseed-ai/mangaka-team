"""Packs de style : chargement des presets, composition de $style, validation API, consignes des LLM."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from mangaka_engine.pipeline import art_direction as da
from mangaka_engine.pipeline import script as sc
from mangaka_engine.pipeline.style import StyleError, check_style, series_style, style_brief
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.models import Chapter, Project
from tests.conftest import PRESETS_DIR

REG = PresetRegistry.load(PRESETS_DIR)
SEINEN_DARK = {"style_genre": "seinen", "style_rendering": "nb-trames", "style_tone": "dark"}


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _errors(resp: Any) -> dict[str, str]:
    assert resp.status_code == 422, resp.text
    return {e["field"]: e["message"] for e in resp.json()["errors"]}


def _series(**kw: Any) -> Project:
    values: dict[str, Any] = {
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


# --- presets ---------------------------------------------------------------------------------
def test_v1_packs_are_loaded_in_order_with_their_defaults() -> None:
    assert not [i for i in REG.issues if "style" in i.file], REG.issues
    assert list(REG.style_genres) == [
        "shonen",
        "seinen",
        "shojo",
        "jeunesse",
        "magical-girl",
        "tranche-de-vie",
        "franco-belge",
    ]
    assert list(REG.style_renderings) == ["nb-trames", "nb-encre", "couleur", "couleur-douce"]
    assert list(REG.style_tones) == ["lumineux", "neutre", "dark", "humour"]
    assert (REG.default_style_rendering, REG.default_style_tone) == ("nb-trames", "neutre")
    assert {k: list(o.choices) for k, o in REG.style_options.options.items()} == {
        "trait": ["fin", "moyen", "epais"],
        "trames": ["legeres", "moyennes", "denses"],
        "detail": ["simple", "moyen", "riche"],
    }
    assert REG.style_options.options["trames"].monochrome_only
    fb = REG.style_genres["franco-belge"]
    assert fb.reading_direction == "ltr" and fb.layout_style in REG.layout_styles
    assert REG.style_genres["jeunesse"].allowed_tones is not None
    assert "dark" not in REG.style_genres["jeunesse"].allowed_tones
    for genre in REG.style_genres.values():
        assert genre.llm_guidelines and genre.fonts.dialogue in REG.fonts.fonts  # type: ignore[union-attr]


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    return root


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_a_new_pack_is_a_file_and_invalid_packs_fail_with_a_clear_message(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    base = yaml.safe_load((root / "style_genres" / "shonen.yaml").read_text(encoding="utf-8"))
    _write(root / "style_genres" / "sport.yaml", {**base, "id": "sport", "name": "Sport", "order": 80})
    _write(root / "style_genres" / "negatif.yaml", {**base, "id": "negatif", "prompt_keywords": ["no color"]})
    _write(root / "style_genres" / "ton-inconnu.yaml", {**base, "id": "ton-inconnu", "allowed_tones": ["gore"]})
    _write(root / "style_genres" / "police.yaml", {**base, "id": "police", "fonts": {"dialogue": "x", "shout": "y"}})
    _write(root / "style_genres" / "sans-consignes.yaml", {k: v for k, v in base.items() if k != "llm_guidelines"})
    _write(root / "style_tones" / "epique.yaml", {"id": "epique", "name": "Épique", "description": "d", "order": 5})
    reg = PresetRegistry.load(root)
    issues = {i.file: i.message for i in reg.issues}
    assert "sport" in reg.style_genres and list(reg.style_genres)[-1] == "sport"
    assert "formulations positives uniquement" in issues["style_genres/negatif.yaml"]
    assert "« no color »" in issues["style_genres/negatif.yaml"]
    assert issues["style_genres/ton-inconnu.yaml"] == "allowed_tones : ton inconnu « gore » (style_tones/)"
    assert "fonts.dialogue : police inconnue « x »" in issues["style_genres/police.yaml"]
    assert "llm_guidelines" in issues["style_genres/sans-consignes.yaml"]
    assert "prompt_keywords" in issues["style_tones/epique.yaml"]
    assert not {"negatif", "ton-inconnu", "police"} & set(reg.style_genres)
    assert "epique" not in reg.style_tones


# --- composition de $style -----------------------------------------------------------------------
def test_style_is_lora_then_genre_rendering_tone_and_fine_settings_in_a_fixed_order() -> None:
    series = _series(
        style_options={"detail": "riche", "trait": "epais", "trames": "denses"},
        style_lora_name="encre-seinen_v2.safetensors",
    )
    words = series_style(REG, series).split(", ")
    g, r, t = REG.style_genres["seinen"], REG.style_renderings["nb-trames"], REG.style_tones["dark"]
    opts = REG.style_options.options
    assert words == [
        "ink seinen style",
        *g.prompt_keywords,
        *r.prompt_keywords,
        *t.prompt_keywords,
        *opts["trait"].choices["epais"].prompt_keywords,
        *opts["trames"].choices["denses"].prompt_keywords,
        *opts["detail"].choices["riche"].prompt_keywords,
    ]


def test_style_combinations_lora_out_of_catalog_and_color() -> None:
    # Hors catalogue : appliqué sans mots déclencheurs.
    plain = series_style(REG, _series(style_lora_name="perso/inconnu.safetensors"))
    assert plain.startswith("seinen manga style")
    # Couleur : les trames (réservées au N&B) n'ajoutent rien, même si elles traînent en base.
    color = series_style(REG, _series(style_rendering="couleur", style_options={"trames": "denses"}))
    assert "full color" in color and "screentone" not in color
    # Un pack disparu des presets est ignoré ; le rendu revient au rendu par défaut.
    gone = series_style(REG, _series(style_genre="disparu", style_rendering="disparu"))
    assert "black and white manga" in gone and "seinen" not in gone
    # Ancien texte libre : utilisé tant qu'aucun pack n'est choisi, ignoré ensuite.
    legacy = _series(legacy_style="Aquarelle pastel", style_genre=None, style_rendering=None, style_tone=None)
    assert series_style(REG, legacy).startswith("Aquarelle pastel, black and white manga")
    assert "Aquarelle" not in series_style(REG, _series(legacy_style="Aquarelle pastel"))


@pytest.mark.parametrize(
    ("genre", "rendering", "tone", "options", "field", "message"),
    [
        ("inconnu", "nb-trames", "neutre", {}, "style_genre", "genre inconnu"),
        ("seinen", "inconnu", "neutre", {}, "style_rendering", "rendu inconnu"),
        ("seinen", "nb-trames", "inconnu", {}, "style_tone", "ton inconnu"),
        ("jeunesse", "nb-trames", "dark", {}, "style_tone", "n'est pas proposé pour le genre « Jeunesse »"),
        ("seinen", "couleur", "dark", {"trames": "denses"}, "style_options", "réservé aux rendus noir et blanc"),
        ("seinen", "couleur-douce", "dark", {"trames": "legeres"}, "style_options", "réservé aux rendus noir et blanc"),
        ("seinen", "nb-trames", "dark", {"trame": "denses"}, "style_options", "réglage inconnu"),
        ("seinen", "nb-trames", "dark", {"trait": "gras"}, "style_options", "valeur inconnue « gras »"),
        ("seinen", None, "dark", {}, "style_rendering", "choisis le rendu"),
    ],
)
def test_forbidden_combinations(
    genre: str, rendering: str | None, tone: str, options: dict[str, str], field: str, message: str
) -> None:
    with pytest.raises(StyleError) as exc:
        check_style(REG, genre, rendering, tone, options)
    assert exc.value.field == field and message in exc.value.message


# --- API -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({"style_genre": "inconnu"}, "style_genre", "genre inconnu : « inconnu »"),
        ({"style_rendering": "sepia"}, "style_rendering", "rendu inconnu : « sepia »"),
        ({"style_tone": "gore"}, "style_tone", "ton inconnu : « gore »"),
        ({"style_genre": "jeunesse", "style_tone": "dark"}, "style_tone", "n'est pas proposé"),
        ({"style_rendering": "couleur", "style_options": {"trames": "denses"}}, "style_options", "noir et blanc"),
        ({"style_options": {"trait": "gras"}}, "style_options", "valeur inconnue"),
        ({"style": "Seinen sombre"}, "style", "champ inconnu"),
        ({"style_lora_trigger_words": "ink"}, "style_lora_trigger_words", "champ inconnu"),
        ({"dialogue_font": "papyrus"}, "dialogue_font", "police inconnue"),
    ],
)
def test_create_refuses_each_forbidden_combination(
    client: TestClient, body: dict[str, Any], field: str, message: str
) -> None:
    errors = _errors(client.post("/projects", json={**SEINEN_DARK, "title": "x", **body}))
    assert message in errors[field]
    assert client.get("/projects").json() == []  # rien de créé


def test_create_requires_the_three_packs(client: TestClient) -> None:
    errors = _errors(client.post("/projects", json={"title": "x"}))
    assert set(errors) == {"style_genre", "style_rendering", "style_tone"}


def test_patch_refuses_forbidden_combinations_and_keeps_the_series(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**SEINEN_DARK, "title": "x", "style_options": {"trames": "denses"}}), 201)
    url = f"/projects/{s['id']}"
    assert "noir et blanc" in _errors(client.patch(url, json={"style_rendering": "couleur"}))["style_options"]
    assert "n'est pas proposé" in _errors(client.patch(url, json={"style_genre": "jeunesse"}))["style_tone"]
    assert "ne peut pas être vide" in _errors(client.patch(url, json={"style_genre": None}))["style_genre"]
    assert _ok(client.get(url))["style_options"] == {"trames": "denses"}
    # Couleur avec les trames retirées : accepté.
    ok = _ok(client.patch(url, json={"style_rendering": "couleur", "style_options": {"trait": "fin"}}))
    assert (ok["style_rendering"], ok["style_options"]) == ("couleur", {"trait": "fin"})
    assert ok["style_label"] == "Seinen · Couleur cel-shading · Dark"


def test_genre_prefills_layout_direction_and_fonts(client: TestClient) -> None:
    fb = _ok(
        client.post(
            "/projects",
            json={"title": "BD", "style_genre": "franco-belge", "style_rendering": "couleur", "style_tone": "humour"},
        ),
        201,
    )
    genre = REG.style_genres["franco-belge"]
    assert (fb["reading_direction"], fb["layout_style"]) == ("ltr", genre.layout_style)
    assert (fb["dialogue_font"], fb["shout_font"]) == (genre.fonts.dialogue, genre.fonts.shout)
    # Les polices vont dans les réglages de série du lettreur : le lettrage les applique.
    presets = client.app.state.ctx.agents.presets_for(fb["id"])  # type: ignore[attr-defined]
    assert presets.fonts.styles["speech"].font == genre.fonts.dialogue
    # Tout reste modifiable dans ses listes.
    own = _ok(
        client.post(
            "/projects",
            json={
                "title": "BD rtl",
                "style_genre": "franco-belge",
                "style_rendering": "couleur",
                "style_tone": "humour",
                "reading_direction": "rtl",
                "layout_style": "nerveuse",
                "dialogue_font": "baloo2",
            },
        ),
        201,
    )
    assert (own["reading_direction"], own["layout_style"], own["dialogue_font"]) == ("rtl", "nerveuse", "baloo2")
    changed = _ok(client.patch(f"/projects/{own['id']}", json={"shout_font": "titan-one"}))
    assert (changed["dialogue_font"], changed["shout_font"]) == ("baloo2", "titan-one")


def test_presets_endpoint_lists_the_packs(client: TestClient) -> None:
    data = client.get("/presets").json()
    assert [g["id"] for g in data["style_genres"]][:2] == ["shonen", "seinen"]
    jeunesse = next(g for g in data["style_genres"] if g["id"] == "jeunesse")
    assert "dark" not in jeunesse["allowed_tones"]
    assert [r["id"] for r in data["style_renderings"] if r["is_default"]] == ["nb-trames"]
    assert {r["id"]: r["monochrome"] for r in data["style_renderings"]}["couleur"] is False
    assert [o["id"] for o in data["style_options"]] == ["trait", "trames", "detail"]
    assert any(lo["file"] == "encre-seinen_v2.safetensors" for lo in data["style_loras"])


def test_generated_panel_prompt_carries_the_three_packs(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**SEINEN_DARK, "title": "Les Lames"}), 201)
    ch = _ok(client.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    [page] = _ok(client.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "Un duel"}]}]}))
    panel = page["panels"][0]
    _ok(client.post(f"/panels/{panel['id']}/generate"), 202)
    assert client.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]
    [img] = _ok(client.get(f"/panels/{panel['id']}/images"))
    prompt = img["params"]["prompt"]
    for pack in (REG.style_genres["seinen"], REG.style_renderings["nb-trames"], REG.style_tones["dark"]):
        assert all(k in prompt for k in pack.prompt_keywords), (pack.id, prompt)


# --- prompt image : aucune mention de rendu en dur -------------------------------------------------
def test_image_prompt_preset_has_no_hardcoded_rendering() -> None:
    raw = yaml.safe_load((PRESETS_DIR / "image_prompt.yaml").read_text(encoding="utf-8"))
    rendering = re.compile(r"encr|manga|couleur|noir|blanc|trame|aquarelle|ink|colou?r|monochrome", re.IGNORECASE)
    assert not [p for p in raw["parts"] if rendering.search(p)]
    assert not [p for p in REG.image_prompt.parts if rendering.search(p)]
    for wf in REG.workflows.values():
        if wf.preset.inpaint is not None:
            assert not [p for p in wf.preset.inpaint.prompt_parts if rendering.search(p)], wf.preset.id


# --- LLM : scénario et direction artistique reçoivent les packs et leurs consignes -----------------
def test_script_and_art_direction_prompts_carry_genre_guidelines(client: TestClient) -> None:
    s = _ok(
        client.post(
            "/projects",
            json={
                "title": "Petit Robot",
                "style_genre": "jeunesse",
                "style_rendering": "couleur-douce",
                "style_tone": "humour",
                "style_options": {"detail": "simple"},
            },
        ),
        201,
    )
    ch = _ok(client.post(f"/projects/{s['id']}/chapters", json={"title": "Un", "synopsis": "Un robot perdu."}), 201)
    _ok(client.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "a"}]}]}))
    genre, tone = REG.style_genres["jeunesse"], REG.style_tones["humour"]
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    llm = MockLLMProvider()
    with ctx.db.session_scope() as session:
        chapter = session.get(Chapter, ch["id"])
        prompt = ctx.presets.prompt("script")
        sctx = sc.build_context(session, ctx.presets, chapter, max_previous=prompt.max_previous_chapters)
        dprompt = ctx.presets.prompt(da.PROMPT_ID)
        dctx = da.build_context(session, ctx.presets, chapter, dprompt)
    sc.run_script(llm, prompt, sctx, lambda _p, _m: None)
    user = llm.calls[0][1].content
    da_user = da.render_messages(dprompt, dctx)[1].content
    for text in (user, da_user):
        assert "Genre : Jeunesse" in text and "Rendu : Couleur douce" in text and "Ton : Humour" in text
        assert "détail des décors simple" in text
        assert genre.llm_guidelines in text and tone.llm_guidelines in text
        assert "$" not in text.replace("$$", "")
    assert json.loads(json.dumps(sctx.as_json()))["series"]["style_guidelines"].startswith(genre.llm_guidelines)


def test_legacy_series_brief_uses_old_text_until_a_pack_is_chosen() -> None:
    legacy = _series(legacy_style="Seinen sombre", style_genre=None, style_rendering=None, style_tone=None)
    brief = style_brief(REG, legacy)
    assert brief.packs == "Seinen sombre (ancien style libre)" and "à choisir" in brief.guidelines
    assert style_brief(REG, _series(legacy_style="Seinen sombre")).packs.startswith("Genre : Seinen")
