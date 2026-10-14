"""Identité visuelle de la série : palettes et logos proposés par l'IA (mock), rendu du logo, API.

Image de référence : `tests/golden/logo-loeil-de-l-ete.png` (« Lœil de l'été », effet dégradé, échelle 1) ; même
règle de comparaison et de régénération que la planche de référence (`MANGAKA_UPDATE_GOLDEN=1 npm run test:engine`).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops

from mangaka_engine.pipeline import identity as identity_mod
from mangaka_engine.pipeline import logo as logo_mod
from mangaka_engine.pipeline.identity import (
    IdentityBrief,
    IdentityError,
    Palette,
    parse_concepts,
    propose_logos,
    propose_palettes,
)
from mangaka_engine.pipeline.logo import (
    LogoSpec,
    contrast,
    fix_contrast,
    logo_contrast,
    render_png,
    render_png_image,
    render_svg,
    spec_problems,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm.mock import MockLLMProvider
from tests.conftest import PRESETS_DIR, STYLE

GOLDEN = Path(__file__).parent / "golden" / "logo-loeil-de-l-ete.png"
TITLE = "Lœil de l'été"
PALETTE = {
    "name": "Été brûlant",
    "explanation": "Rouge et or d'un été caniculaire.",
    "colors": [
        {"role": "dominante", "hex": "#e74c3c"},
        {"role": "accent", "hex": "#f1c40f"},
        {"role": "fond", "hex": "#fdf2e9"},
        {"role": "texte-clair", "hex": "#ffffff"},
        {"role": "texte-sombre", "hex": "#1b1b1b"},
    ],
}


@pytest.fixture(scope="module")
def presets() -> PresetRegistry:
    reg = PresetRegistry.load(PRESETS_DIR)
    assert reg.issues == []
    return reg


def _brief(title: str = TITLE) -> IdentityBrief:
    return IdentityBrief(
        title=title,
        style_packs="Genre : Shōnen",
        style_guidelines="",
        characters=[{"name": "Aiko", "description": "cheveux roses, veste bleue"}],
        reference=None,
        bible="",
    )


def _spec(**changes: object) -> LogoSpec:
    data: dict[str, object] = {
        "font": "righteous",
        "style": "degrade",
        "lines": [{"text": "Lœil de", "scale": 0.55}, {"text": "l'été", "scale": 1}],
        "subtitle": "Tome 1 — Ça commence",
        "slant": -5,
        "letter_spacing": 0.03,
        "colors": {
            "fill": "#e74c3c",
            "fill_end": "#f1c40f",
            "outline": "#1b1b1b",
            "outer": "#ffffff",
            "subtitle": "#ffffff",
        },
    }
    data.update(changes)
    return LogoSpec.model_validate(data)


# --- presets ---------------------------------------------------------------------------------------------
def test_identity_presets_load(presets: PresetRegistry) -> None:
    identity = presets.require_identity()
    assert identity.palette.count.min == 3 and identity.palette.count.max == 5
    assert identity.palette.colors.min == 5 and identity.palette.colors.max == 7
    assert len(presets.logo_styles) >= 4
    fonts = presets.require_fonts().fonts
    for font_id in identity.logo.fonts:
        cmap = TTFont(PRESETS_DIR / fonts[font_id].file).getBestCmap()
        assert all(ord(c) in cmap for c in "éèàçœÉÈÀÇŒ'"), font_id
    licence = (PRESETS_DIR / "fonts" / "OFL.txt").read_text()
    for name in ("Bangers", "Bungee", "Righteous", "RussoOne"):
        assert f"{name}.ttf" in licence
        assert (PRESETS_DIR / "fonts" / f"OFL-{name}.txt").is_file()


def test_no_font_nor_effect_hardcoded_in_the_pipeline(presets: PresetRegistry) -> None:
    sources = Path(logo_mod.__file__).read_text() + Path(identity_mod.__file__).read_text()
    names = [*presets.require_fonts().fonts, *presets.logo_styles]
    names += [f.name for f in presets.require_fonts().fonts.values()] + [s.name for s in presets.logo_styles.values()]
    found = [n for n in names if re.search(rf"[\"'«]{re.escape(n)}[\"'»]", sources)]
    assert found == []
    assert ".ttf" not in sources


# --- palettes ---------------------------------------------------------------------------------------------
def test_palettes_are_proposed_and_validated(presets: PresetRegistry) -> None:
    llm = MockLLMProvider()
    run = propose_palettes(llm, presets, _brief(), [])
    assert run.attempts == 1
    assert 3 <= len(run.output) <= 5
    required = presets.require_identity().palette.required_roles
    for palette in run.output:
        assert 5 <= len(palette.colors) <= 7
        assert set(required) <= {c.role for c in palette.colors}
        assert all(re.fullmatch(r"#[0-9a-f]{6}", c.hex) for c in palette.colors)
        assert palette.explanation
    request = llm.requests[0]
    assert request["json_mode"] is True
    user = request["messages"][1].content
    assert "cheveux roses, veste bleue" in user and TITLE in user
    other = propose_palettes(MockLLMProvider(), presets, _brief(), [p.name for p in run.output])
    assert {p.name for p in other.output}.isdisjoint({p.name for p in run.output})


def test_invalid_palette_json_is_retried_then_readable_error(presets: PresetRegistry) -> None:
    llm = MockLLMProvider(invalid_attempts=2)
    run = propose_palettes(llm, presets, _brief(), [])
    assert run.attempts == 3
    # La relance renvoie l'erreur à l'agent.
    retry = llm.calls[1][-1].content
    assert "JSON illisible" in retry
    assert "invalide" in llm.calls[2][-1].content

    with pytest.raises(IdentityError, match=r"réponse invalide 3 fois de suite pour les palettes"):
        propose_palettes(MockLLMProvider(invalid_attempts=3), presets, _brief(), [])


def test_palette_rules_reject_missing_roles_and_bad_counts(presets: PresetRegistry) -> None:
    identity = presets.require_identity()
    bad = {
        "palettes": [
            {"name": "A", "colors": [{"role": "dominante", "hex": "#000000"}], "explanation": "."},
        ]
    }
    with pytest.raises(identity_mod.IdentityValidationError) as exc:
        identity_mod.parse_palettes(json.dumps(bad), identity)
    message = str(exc.value)
    assert "1 palettes, entre 3 et 5" in message and "rôle obligatoire absent" in message
    with pytest.raises(identity_mod.IdentityValidationError, match="hex"):
        identity_mod.parse_palettes(
            json.dumps({"palettes": [{"name": "A", "colors": [{"role": "accent", "hex": "rouge"}]}]}), identity
        )


# --- logos ----------------------------------------------------------------------------------------------
def test_logos_are_proposed_with_palette_colors(presets: PresetRegistry) -> None:
    palette = Palette.model_validate(PALETTE)
    run = propose_logos(MockLLMProvider(), presets, _brief(), palette, [])
    assert 4 <= len(run.output) <= 6
    hexes = {c.hex for c in palette.colors} | {"#000000", "#ffffff"}
    minimum = presets.require_identity().logo.min_contrast
    for concept in run.output:
        spec = concept.spec
        assert identity_mod.normalize_title(spec.text) == identity_mod.normalize_title(TITLE)
        assert spec.font in presets.require_identity().logo.fonts
        used = {v for v in spec.colors.model_dump().values() if v}
        assert used <= hexes
        ratio = logo_contrast(spec, presets.logo_styles[spec.style])
        assert ratio is None or ratio >= minimum
        assert spec_problems(presets, spec) == []


def test_invalid_logo_json_is_retried_then_readable_error(presets: PresetRegistry) -> None:
    palette = Palette.model_validate(PALETTE)
    run = propose_logos(MockLLMProvider(invalid_attempts=1), presets, _brief(), palette, [])
    assert run.attempts == 2
    with pytest.raises(IdentityError, match=r"réponse invalide 3 fois de suite pour les logos"):
        propose_logos(MockLLMProvider(invalid_attempts=3), presets, _brief(), palette, [])


def test_logo_concept_that_changes_the_title_or_uses_unknown_font_is_refused(presets: PresetRegistry) -> None:
    roles = Palette.model_validate(PALETTE).by_role()
    concept = {"font": "comic-sans", "style": "contour-epais", "lines": [{"text": "L'œil de l'été", "scale": 1}]}
    answer = json.dumps({"concepts": [concept] * 4})
    with pytest.raises(identity_mod.IdentityValidationError) as exc:
        parse_concepts(answer, presets, TITLE, roles)
    assert "ne redonnent pas le titre" in str(exc.value)
    assert "n'est pas une police permise" in str(exc.value)

    # Rôle inconnu de la palette : refusé ; rôle écrit en clair (« texte sombre ») : accepté.
    ok = {"font": "bangers", "style": "contour-epais", "lines": [{"text": "LŒIL DE L'ÉTÉ", "scale": 1}]}
    with pytest.raises(identity_mod.IdentityValidationError, match="ni un rôle de la palette"):
        parse_concepts(json.dumps({"concepts": [{**ok, "colors": {"fill": "turquoise"}}] * 4}), presets, TITLE, roles)
    concepts = parse_concepts(
        json.dumps({"concepts": [{**ok, "colors": {"outline": "Texte sombre"}}] * 4}), presets, TITLE, roles
    )
    assert concepts[0].spec.colors.outline == "#1b1b1b"


# --- contraste ---------------------------------------------------------------------------------------------
def test_contrast_of_logo_text_on_its_outline(presets: PresetRegistry) -> None:
    style = presets.logo_styles["contour-epais"]
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#777777", "#777777") == pytest.approx(1)
    dull = _spec(style="contour-epais", subtitle=None, colors={"fill": "#2c3e50", "outline": "#1b1b1b"})
    ratio = logo_contrast(dull, style)
    assert ratio is not None and ratio < 3
    candidates = [c["hex"] for c in PALETTE["colors"]]  # type: ignore[index]
    fixed, note = fix_contrast(dull, style, candidates, 3.0)
    assert note is not None and "contour passé en" in note
    assert fixed.colors.outline == "#ffffff"  # la couleur de la palette la plus contrastée
    assert logo_contrast(fixed, style) >= 3  # type: ignore[operator]
    # Contraste suffisant : rien ne change.
    same, none = fix_contrast(fixed, style, candidates, 3.0)
    assert same == fixed and none is None
    # Sans contour (effet sobre) : pas de contraste à tenir.
    assert (
        logo_contrast(
            _spec(style="sobre", colors={"fill": "#000000", "subtitle": "#ffffff"}), presets.logo_styles["sobre"]
        )
        is None
    )
    # Concept de l'IA au contour illisible : corrigé et signalé.
    roles = {
        "dominante": "#2c3e50",
        "accent": "#34495e",
        "fond": "#2c3e51",
        "texte-clair": "#ecf0f1",
        "texte-sombre": "#1b1b1b",
    }
    concept = {"font": "bangers", "style": "contour-epais", "lines": [{"text": TITLE, "scale": 1}]}
    out = parse_concepts(json.dumps({"concepts": [concept] * 4}), presets, TITLE, roles)
    assert out[0].spec.colors.outline == "#ecf0f1" and out[0].notes


# --- rendu -----------------------------------------------------------------------------------------------
def test_logo_svg_embeds_a_renamed_font_with_french_accents(presets: PresetRegistry) -> None:
    svg = render_svg(presets, _spec())
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<title>Lœil de l&apos;été</title>" in svg or "<title>Lœil de l'été</title>" in svg
    assert ">Lœil de</text>" in svg and ">l'été</text>" in svg and "Ça commence" in svg
    assert 'font-family="mk-righteous"' in svg and "linearGradient" in svg and "skewX(5)" in svg
    data = re.search(r"base64,([A-Za-z0-9+/=]+)", svg)
    assert data is not None
    font = TTFont(io.BytesIO(base64.b64decode(data.group(1))))
    cmap = font.getBestCmap()
    assert all(ord(c) in cmap for c in "œéÇ'")
    assert font["name"].getDebugName(1) == "mk-righteous"  # OFL, clause 3 : pas de nom réservé
    # Une abscisse par caractère : SVG et PNG posent chaque lettre au même endroit.
    first = re.search(r'<text x="([^"]+)"[^>]*>Lœil de</text>', svg)
    assert first is not None and len(first.group(1).split()) == len("Lœil de")


def test_logo_png_is_transparent_and_high_definition(presets: PresetRegistry) -> None:
    data = render_png(presets, _spec())
    img = Image.open(io.BytesIO(data))
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0  # fond transparent
    svg = render_svg(presets, _spec())
    width = float(re.search(r'width="([\d.]+)"', svg).group(1))  # type: ignore[union-attr]
    scale = presets.require_identity().logo.png_scale
    assert img.width == pytest.approx(width * scale, abs=1)


def test_accents_are_drawn(presets: PresetRegistry) -> None:
    """« Lœil de l'été » ≠ « Loeil de l'ete » : œ, é et l'apostrophe sont bien dessinés."""
    accented = render_png_image(presets, _spec(lines=[{"text": "l'été", "scale": 1}], subtitle=None, slant=0), scale=1)
    plain = render_png_image(presets, _spec(lines=[{"text": "l'ete", "scale": 1}], subtitle=None, slant=0), scale=1)
    assert accented.size[1] > plain.size[1]  # les accents montent au-dessus des lettres
    oe = render_png_image(presets, _spec(lines=[{"text": "Lœil", "scale": 1}], subtitle=None, slant=0), scale=1)
    oe2 = render_png_image(presets, _spec(lines=[{"text": "Loeil", "scale": 1}], subtitle=None, slant=0), scale=1)
    assert oe.size != oe2.size or ImageChops.difference(oe, oe2).getbbox() is not None


def test_golden_logo(tmp_path: Path, presets: PresetRegistry) -> None:
    first = render_png_image(presets, _spec(), scale=1)
    second = render_png_image(presets, _spec(), scale=1)
    assert first.tobytes() == second.tobytes(), "le rendu n'est pas déterministe"
    if os.environ.get("MANGAKA_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        first.save(GOLDEN, format="PNG")
        pytest.skip("image de référence régénérée")
    assert GOLDEN.is_file(), "référence absente : MANGAKA_UPDATE_GOLDEN=1 npm run test:engine"
    with Image.open(GOLDEN) as ref:
        expected = ref.convert("RGBA")
    assert expected.size == first.size
    diff = ImageChops.difference(first, expected).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = sum(diff.histogram()[255:])
    total = first.width * first.height
    if changed > total * 0.0005:
        first.save(tmp_path / "logo.png")
        pytest.fail(
            f"le logo de référence a changé ({changed} px sur {total}) — rendu : {tmp_path / 'logo.png'} ; "
            "si c'est voulu, régénère-le (MANGAKA_UPDATE_GOLDEN=1) et justifie-le dans la PR"
        )


def test_spec_bounds_come_from_the_presets(presets: PresetRegistry) -> None:
    problems = spec_problems(presets, _spec(slant=30, letter_spacing=2, font="baloo2", style="neon"))
    text = " ".join(problems)
    assert "slant" in text and "letter_spacing" in text and "police permise" in text and "effet inconnu" in text


# --- API (mode mock) -------------------------------------------------------------------------------------
def test_identity_flow_in_mock_mode(client: TestClient) -> None:
    project = client.post("/projects", json={**STYLE, "title": TITLE}).json()
    base = f"/projects/{project['id']}/identity"
    empty = client.get(base).json()
    assert empty["palette"] is None and empty["palette_proposals"] == [] and empty["logo"] is None
    assert empty["roles"]["texte-clair"] == "Texte clair"

    # Pas de logo sans palette retenue.
    r = client.post(f"{base}/logos", json={})
    assert r.status_code == 422 and "palette" in r.text

    proposals = client.post(f"{base}/palettes", json={}).json()["palette_proposals"]
    assert 3 <= len(proposals) <= 5
    chosen = proposals[1]
    chosen["colors"][0]["hex"] = "#123abc"  # couleur modifiée à la main
    r = client.put(f"{base}/palette", json=chosen)
    assert r.status_code == 200, r.text

    # Conservé après rechargement.
    again = client.get(base).json()
    assert again["palette"]["name"] == chosen["name"]
    assert again["palette"]["colors"][0]["hex"] == "#123abc"
    assert len(again["palette_proposals"]) == len(proposals)

    # « Proposer d'autres palettes » : nouvelles propositions, palette retenue intacte.
    other = client.post(f"{base}/palettes", json={"more": True}).json()
    assert {p["name"] for p in other["palette_proposals"]}.isdisjoint({p["name"] for p in proposals})
    assert other["palette"]["colors"][0]["hex"] == "#123abc"

    # Palette invalide (rôle obligatoire retiré) : refusée.
    broken = {**chosen, "colors": [c for c in chosen["colors"] if c["role"] != "accent"]}
    assert client.put(f"{base}/palette", json=broken).status_code == 422

    logos = client.post(f"{base}/logos", json={}).json()
    concepts = logos["logo_proposals"]
    assert 4 <= len(concepts) <= 6
    palette_hexes = {c["hex"] for c in again["palette"]["colors"]} | {"#000000", "#ffffff"}
    for concept in concepts:
        assert concept["svg"].lstrip().startswith("<?xml") and "<svg" in concept["svg"]
        used = {v for v in concept["spec"]["colors"].values() if v}
        assert used <= palette_hexes
        assert concept["contrast_ok"]

    # Réglage à la main avec aperçu, puis enregistrement (versions conservées).
    spec = {**concepts[0]["spec"], "letter_spacing": 0.1, "outline_scale": 1.5}
    preview = client.post(f"{base}/logo/preview", json=spec)
    assert preview.status_code == 200 and "<svg" in preview.json()["svg"]
    bad = client.post(f"{base}/logo/preview", json={**spec, "slant": 40})
    assert bad.status_code == 422
    first = client.post(f"{base}/logo", json=concepts[0]["spec"])
    assert first.status_code == 201
    saved = client.post(f"{base}/logo", json=spec).json()
    assert saved["logo"]["version"] == 2 and len(saved["logo_versions"]) == 2
    assert saved["logo"]["spec"]["letter_spacing"] == 0.1

    reloaded = client.get(base).json()
    assert reloaded["logo"]["version"] == 2

    png = client.get(reloaded["logo"]["png_url"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert "attachment" in png.headers["content-disposition"]
    img = Image.open(io.BytesIO(png.content))
    assert img.mode == "RGBA" and img.getpixel((0, 0))[3] == 0
    svg = client.get(reloaded["logo"]["svg_url"])
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert "été" in svg.text and "œ" in svg.text.lower()
    assert client.get("/logos/999/file").status_code == 404


def test_identity_llm_failure_is_readable(client: TestClient) -> None:
    project = client.post("/projects", json={**STYLE, "title": "Titre [mock:identite-invalide:3]"}).json()
    r = client.post(f"/projects/{project['id']}/identity/palettes", json={})
    assert r.status_code == 502
    assert "L'IA n'a pas pu proposer de palettes" in r.json()["detail"]
    assert client.get(f"/projects/{project['id']}/identity").json()["palette_proposals"] == []
