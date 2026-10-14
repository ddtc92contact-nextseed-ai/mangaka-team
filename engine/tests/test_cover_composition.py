"""Composition de la couverture d'un tome (#161) : résumé de 4e par l'IA (mock), 1re composée (logo, tome, auteur),
4e (gabarits, résumé ajusté au cadre, petite illustration), dos (largeur selon les pages), couverture à plat
(ordre ltr / rtl), export ZIP (PNG + SVG), accents. ComfyUI et LLM en mock.

Images de référence : `tests/golden/couverture-1re.png` et `tests/golden/couverture-4e.png` (13 × 18 rendu à
100 dpi, entrées synthétiques) ; même règle de comparaison et de régénération que la planche de référence
(`MANGAKA_UPDATE_GOLDEN=1 npm run test:engine`).
"""

from __future__ import annotations

import base64
import io
import os
import re
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.back_cover import (
    BackCoverError,
    SummaryBrief,
    shared_run,
    sign_count,
    write_summary,
)
from mangaka_engine.pipeline.cover_composition import (
    CoverInputs,
    Text,
    build_sheet,
    compose,
    flat_order,
    render_png,
    render_sheet,
    sheet_for,
    spine_width_mm,
)
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.logo import LogoSpec
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from tests.conftest import PRESETS_DIR, STYLE

REG = PresetRegistry.load(PRESETS_DIR)
GOLDEN = Path(__file__).parent / "golden"
MANGA = "manga-13x18-300dpi"
PALETTE = {
    "dominante": "#7c1d2b",
    "secondaire": "#2d3a5c",
    "accent": "#f2b134",
    "fond": "#fbf3e4",
    "texte-clair": "#ffffff",
    "texte-sombre": "#1b1420",
}
SUMMARY = (
    "Dans la cité d'Ébène, où les lanternes ne s'éteignent jamais, Aïko découvre qu'un pacte oublié lie sa "
    "famille aux esprits du fleuve. Quand son frère disparaît à la fête de l'été, elle n'a plus le choix : "
    "suivre les traces laissées par un renard à trois queues, quitte à défier les gardiens du sanctuaire.\n\n"
    "Épaulée par Kenji, apprenti forgeron au cœur trop grand, elle traverse ruelles, marchés flottants et "
    "forêts de bambous. Mais chaque pas vers la vérité réveille une menace bien plus ancienne… Jusqu'où "
    "ira-t-elle pour sauver ceux qu'elle aime ?"
)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


# --- entrées synthétiques ----------------------------------------------------------------------------------
def _gradient(path: Path, size: tuple[int, int], a: tuple[int, int, int], b: tuple[int, int, int]) -> Path:
    img = Image.new("RGB", size, a)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        draw.line((0, y, size[0], y), fill=tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    draw.ellipse((size[0] * 0.3, size[1] * 0.45, size[0] * 0.7, size[1] * 0.85), fill=(240, 200, 120))
    img.save(path, format="PNG")
    return path


def _logo() -> LogoSpec:
    return LogoSpec.model_validate(
        {
            "font": "righteous",
            "style": "contour-epais",
            "lines": [{"text": "Le Sceau", "scale": 0.55}, {"text": "d'Ébène", "scale": 1}],
            "slant": -4,
            "letter_spacing": 0.03,
            "colors": {"fill": "#f2b134", "outline": "#1b1420"},
        }
    )


def _inputs(tmp_path: Path, **changes: Any) -> CoverInputs:
    settings = REG.require_composition()
    fmt = REG.cover_format(MANGA)
    if "dpi" in changes:
        fmt = fmt.model_copy(update={"dpi": changes.pop("dpi")})
    front = _gradient(tmp_path / "front.png", fmt.full_px, (40, 90, 170), (230, 120, 60))
    back = _gradient(tmp_path / "back.png", (400, 300), (30, 120, 90), (200, 220, 90))
    data: dict[str, Any] = {
        "fmt": fmt,
        "settings": settings,
        "layout": REG.back_layouts["illustration-haut"],
        "palette": PALETTE,
        "palette_name": "Braises",
        "title": "Le Sceau d'Ébène",
        "number": 3,
        "author": "Hélène Côté",
        "logo": _logo(),
        "logo_note": None,
        "logo_placement": None,
        "front_image": front,
        "back_image": back,
        "back_image_note": None,
        "tagline": "Un pacte oublié, un frère disparu : l'été sera brûlant !",
        "summary": SUMMARY,
        "pages": 192,
        "direction": "rtl",
    }
    data.update(changes)
    return CoverInputs(**data)


# --- presets ---------------------------------------------------------------------------------------------
def test_composition_presets_load_with_french_fonts() -> None:
    assert not [i for i in REG.issues if i.file.startswith(("cover_composition", "back_layouts", "prompts/resume"))]
    settings = REG.require_composition()
    assert (settings.summary.min_chars, settings.summary.max_chars) == (600, 900)
    assert 2 <= len(REG.back_layouts) <= 3 and settings.default_back_layout in REG.back_layouts
    assert settings.summary.prompt in REG.prompts and REG.prompts[settings.summary.prompt].max_retries == 2
    fonts = REG.require_fonts().fonts
    for name, style in settings.texts:
        cmap = TTFont(PRESETS_DIR / fonts[style.font].file).getBestCmap()
        assert all(ord(c) in cmap for c in "éèêàâçœîôûÉÈÀÇŒ«»’…"), name


# --- résumé de 4e ------------------------------------------------------------------------------------------
def _brief(**changes: Any) -> SummaryBrief:
    data: dict[str, Any] = {
        "series": "Le Sceau d'Ébène",
        "volume": "Tome 3 — Les lanternes",
        "chapters": [
            {"number": 7, "title": "Le fleuve", "summary": "Aïko suit un renard jusqu'au sanctuaire du fleuve."},
            {"number": 8, "title": "Le pacte", "summary": "Kenji révèle que le pacte a été scellé par sa propre mère."},
        ],
        "ending": "Kenji révèle que le pacte a été scellé par sa propre mère.",
        "bible": "",
        "settings": REG.require_composition().summary,
    }
    data.update(changes)
    return SummaryBrief(**data)


def test_summary_is_written_within_bounds_without_the_ending() -> None:
    run = write_summary(MockLLMProvider(), REG.prompt("resume-quatrieme"), _brief())
    out = run.output
    assert run.attempts == 1
    assert 600 <= sign_count(out.summary) <= 900
    assert out.tagline and len(out.tagline) <= 90 and "\n" not in out.tagline
    assert shared_run(out.summary, _brief().ending, 7) is None
    assert "Aïko suit un renard" in out.summary  # chapitres du tome, sauf le dernier (sa fin)
    # « Réécrire » : un autre texte.
    again = write_summary(MockLLMProvider(), REG.prompt("resume-quatrieme"), _brief(previous=out.summary)).output
    assert again.summary != out.summary and 600 <= sign_count(again.summary) <= 900


def test_invalid_summary_is_retried_twice_then_readable_error() -> None:
    llm = MockLLMProvider()
    run = write_summary(llm, REG.prompt("resume-quatrieme"), _brief(volume="Tome 3 [mock:resume-invalide:2]"))
    assert run.attempts == 3
    retry = llm.calls[-1][-1].content
    assert "invalide" in retry and "signes" in retry
    with pytest.raises(BackCoverError, match=r"réponse invalide 3 fois de suite pour le résumé de 4e"):
        write_summary(MockLLMProvider(), REG.prompt("resume-quatrieme"), _brief(volume="T [mock:resume-invalide:3]"))


def test_a_summary_that_reveals_the_ending_is_refused() -> None:
    import json

    filler = "Une aventure palpitante commence au bord du fleuve et rien ne sera plus comme avant. " * 8
    spoiler = filler + "À la fin, Kenji révèle que le pacte a été scellé par sa propre mère."

    def responder(messages: list[Any], json_mode: bool) -> str:
        return json.dumps({"tagline": "Le pacte !", "summary": spoiler[:880]}, ensure_ascii=False)

    with pytest.raises(BackCoverError, match="reprend la fin du tome"):
        write_summary(MockLLMProvider(responder), REG.prompt("resume-quatrieme"), _brief())


# --- 4e : le résumé ne déborde jamais ---------------------------------------------------------------------
def test_back_summary_shrinks_to_fit_then_readable_error(tmp_path: Path) -> None:
    style = REG.require_composition().texts.summary
    ok = compose(REG, _inputs(tmp_path))
    [text] = [i for i in ok.back.items if isinstance(i, Text) and i.name == "resume"]
    assert not ok.problems
    # Plus long : la taille diminue (jamais sous le minimum), tout le texte reste.
    longer = compose(REG, _inputs(tmp_path, summary=SUMMARY + "\n\n" + SUMMARY[:700]))
    [shrunk] = [i for i in longer.back.items if isinstance(i, Text) and i.name == "resume"]
    assert shrunk.size < text.size and shrunk.size >= style.min_size_pt / 72 * 300 - 1e-6
    words = " ".join(ln.text for ln in shrunk.lines).replace("-", "").split()
    assert len(words) >= len((SUMMARY + " " + SUMMARY[:700]).split()) - 2
    assert any(w.code == "summary_shrunk" for w in longer.warnings)
    # Beaucoup trop long : erreur lisible, rien n'est coupé ni dessiné.
    huge = compose(REG, _inputs(tmp_path, summary=(SUMMARY + "\n\n") * 6))
    [problem] = [p for p in huge.problems if p.code == "summary_overflow"]
    assert f"même en {style.min_size_pt:g} pt" in problem.message and "raccourcis-le" in problem.message
    assert not [i for i in huge.back.items if isinstance(i, Text) and i.name == "resume"]
    # Chaque ligne tient dans le cadre.
    fonts = FontBook(REG)
    font = fonts.pil(style, text.size)
    frame_w = (REG.cover_format(MANGA).trim_px[0] - 2 * 5 / 25.4 * 300) - 2 * 3.5 / 25.4 * 300
    assert max(font.getlength(ln.text) for ln in text.lines) <= frame_w + 0.5


def test_every_back_layout_composes(tmp_path: Path) -> None:
    for layout in REG.back_layouts.values():
        comp = compose(REG, _inputs(tmp_path, layout=layout))
        assert not comp.problems, layout.id
        names = {getattr(i, "name", "") for i in comp.back.items}
        assert {"accroche", "illustration", "resume", "titre"} <= names, layout.id


# --- dos et couverture à plat --------------------------------------------------------------------------------
def test_spine_width_follows_the_page_count() -> None:
    spine = REG.require_composition().spine
    assert spine_width_mm(spine, 0) == spine.min_width_mm
    assert spine_width_mm(spine, 192) == round(96 * spine.sheet_thickness_mm + spine.cover_mm, 2)
    widths = [spine_width_mm(spine, n) for n in (40, 100, 200, 400)]
    assert widths == sorted(widths) and widths[-1] > widths[0]
    assert spine_width_mm(spine, 201) == spine_width_mm(spine, 202)  # une feuille = deux pages


def test_flat_cover_swaps_front_and_back_with_reading_direction(tmp_path: Path) -> None:
    assert flat_order("ltr") == ["back", "spine", "front"]
    assert flat_order("rtl") == ["front", "spine", "back"]
    for direction in ("ltr", "rtl"):
        comp = compose(REG, _inputs(tmp_path, direction=direction, dpi=60))
        sheet = sheet_for(comp, "flat", REG, bleed=True, crop_marks=False)
        kinds = [s.part.kind for s in sheet.slots]
        assert kinds == flat_order(direction)
        front = next(s for s in sheet.slots if s.part.kind == "front")
        spine = next(s for s in sheet.slots if s.part.kind == "spine")
        assert (front.x < spine.x) == (direction == "rtl")  # en rtl, la 1re est à gauche du dos
        assert sheet.folds == [spine.x, spine.x + spine.part.width]
        # Le pixel au milieu de la face de gauche vient bien de cette face.
        img = render_png(sheet, REG, FontBook(REG))
        left = sheet.slots[0]
        px = img.getpixel((left.x + 3, left.y + left.part.height // 2))
        if direction == "rtl":
            assert px != tuple(int(PALETTE["dominante"][i : i + 2], 16) for i in (1, 3, 5))  # illustration
        fmt = comp.inputs.fmt
        assert sheet.width == 2 * fmt.trim_px[0] + spine.part.width + 2 * fmt.bleed_px


def test_spine_is_wider_with_more_pages(tmp_path: Path) -> None:
    thin = compose(REG, _inputs(tmp_path, pages=40, dpi=60))
    thick = compose(REG, _inputs(tmp_path, pages=400, dpi=60))
    assert thick.spine.width > thin.spine.width
    assert thick.spine_mm > thin.spine_mm
    # Dos épais : titre vertical et numéro ; dos très fin : numéro seul, avertissement.
    assert {getattr(i, "name", "") for i in thick.spine.items} >= {"titre", "numero"}
    title = next(i for i in thick.spine.items if isinstance(i, Text) and i.name == "titre")
    assert title.rotate is not None
    assert any(w.code == "spine_narrow" for w in thin.warnings)


# --- 1re ---------------------------------------------------------------------------------------------------
def test_front_logo_stays_in_the_safety_margin(tmp_path: Path) -> None:
    fmt = REG.cover_format(MANGA)
    safe = 5 / 25.4 * 300
    for placement in (None, {"cx": 0.0, "cy": 0.0, "scale": 1.0}, {"cx": 1.0, "cy": 1.0, "scale": 5.0}):
        comp = compose(REG, _inputs(tmp_path, logo_placement=placement))
        [logo] = [i for i in comp.front.items if getattr(i, "name", "") == "logo"]
        r = logo.rect
        assert r.x >= safe - 0.01 and r.y >= safe - 0.01
        assert r.x2 <= fmt.trim_px[0] - safe + 0.01 and r.y2 <= fmt.trim_px[1] - safe + 0.01
    small = compose(REG, _inputs(tmp_path, logo_placement={"cx": 0.5, "cy": 0.3, "scale": 0.3}))
    big = compose(REG, _inputs(tmp_path, logo_placement={"cx": 0.5, "cy": 0.3, "scale": 1.0}))
    w = [next(i for i in c.front.items if getattr(i, "name", "") == "logo").rect.w for c in (small, big)]
    assert w[0] < w[1]


def test_front_without_logo_falls_back_to_a_composed_title(tmp_path: Path) -> None:
    comp = compose(REG, _inputs(tmp_path, logo=None))
    assert not [i for i in comp.front.items if getattr(i, "name", "") == "logo"]
    [title] = [i for i in comp.front.items if isinstance(i, Text) and i.name == "titre"]
    assert "ÉBÈNE" in " ".join(ln.text for ln in title.lines).upper()
    [warning] = [w for w in comp.warnings if w.code == "no_logo"]
    assert "police par défaut" in warning.message
    svg = render_sheet(sheet_for(comp, "front", REG, bleed=False, crop_marks=False), REG, "1re").svg
    assert "d’Ébène" in svg or "d'Ébène" in svg or "d&apos;Ébène" in svg


def _font_chars(svg: str) -> set[str]:
    out: set[str] = set()
    for data in re.findall(r"base64,([A-Za-z0-9+/=]+)\) format", svg):
        out |= {chr(c) for c in TTFont(io.BytesIO(base64.b64decode(data))).getBestCmap()}
    return out


def test_french_accents_in_logo_summary_and_spine_png_and_svg(tmp_path: Path) -> None:
    comp = compose(REG, _inputs(tmp_path, dpi=100))
    flat = render_sheet(sheet_for(comp, "flat", REG, bleed=True, crop_marks=True), REG, "à plat")
    svg = flat.svg
    # SVG : texte réel (sélectionnable), polices embarquées qui ont bien les glyphes accentués.
    assert "Ébène" in svg and "Hélène Côté" in svg and "cœur" in svg and "brûlant" in svg
    chars = _font_chars(svg)
    assert {"É", "è", "é", "ô", "œ", "û", "ï"} <= chars
    assert 'class="logo"' in svg and "-logo" in svg  # logo vectoriel, police renommée (pas de conflit)
    assert svg.count('id="premiere"') == svg.count('id="quatrieme"') == svg.count('id="dos"') == 1
    assert 'id="reperes-de-coupe"' in svg
    # PNG : « É » n'est pas « E ».
    plain = compose(REG, _inputs(tmp_path, dpi=100, title="Le Sceau d'Ebene", logo=None))
    accent = compose(REG, _inputs(tmp_path, dpi=100, logo=None))
    a = render_png(sheet_for(plain, "spine", REG, bleed=False, crop_marks=False), REG, FontBook(REG))
    b = render_png(sheet_for(accent, "spine", REG, bleed=False, crop_marks=False), REG, FontBook(REG))
    assert a.size == b.size and ImageChops.difference(a, b).getbbox() is not None


def test_no_image_model_text_only_vector_text(tmp_path: Path) -> None:
    """Tout le texte de la couverture est posé par le moteur : `<text>` du SVG, jamais dans une image générée."""
    comp = compose(REG, _inputs(tmp_path, dpi=60))
    svg = render_sheet(sheet_for(comp, "back", REG, bleed=False, crop_marks=False), REG, "4e").svg
    assert svg.count("<text ") >= 5 and "Un pacte oublié" in svg


# --- golden ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("which", ["front", "back"])
def test_golden_front_and_back(tmp_path: Path, which: str) -> None:
    golden = GOLDEN / f"couverture-{'1re' if which == 'front' else '4e'}.png"
    comp = compose(REG, _inputs(tmp_path, dpi=100))
    sheet = sheet_for(comp, which, REG, bleed=True, crop_marks=False)
    first = render_png(sheet, REG, FontBook(REG))
    second = render_png(sheet, REG, FontBook(REG))
    assert first.tobytes() == second.tobytes(), "le rendu n'est pas déterministe"
    if os.environ.get("MANGAKA_UPDATE_GOLDEN") == "1":
        first.save(golden, format="PNG")
        pytest.skip("image de référence régénérée")
    assert golden.is_file(), "référence absente : MANGAKA_UPDATE_GOLDEN=1 npm run test:engine"
    with Image.open(golden) as ref:
        expected = ref.convert("RGB")
    assert expected.size == first.size
    diff = ImageChops.difference(first, expected).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = sum(diff.histogram()[255:])
    total = first.width * first.height
    if changed > total * 0.0005:
        first.save(tmp_path / golden.name)
        pytest.fail(
            f"la {which} de référence a changé ({changed} px sur {total}) — rendu : {tmp_path / golden.name} ; "
            "si c'est voulu, régénère-la (MANGAKA_UPDATE_GOLDEN=1) et justifie-le dans la PR"
        )


def test_sheet_sizes_bleed_and_marks(tmp_path: Path) -> None:
    comp = compose(REG, _inputs(tmp_path, dpi=60))
    fmt = comp.inputs.fmt
    plain = build_sheet("front", [comp.front], fmt, REG, bleed=False, crop_marks=False)
    assert (plain.width, plain.height) == fmt.trim_px
    bled = sheet_for(comp, "front", REG, bleed=True, crop_marks=False)
    assert (bled.width, bled.height) == (fmt.trim_px[0] + 2 * fmt.bleed_px, fmt.trim_px[1] + 2 * fmt.bleed_px)
    marked = sheet_for(comp, "flat", REG, bleed=True, crop_marks=True)
    assert marked.width > bled.width
    svg = render_sheet(marked, REG, "à plat").svg
    assert svg.count("<line ") == 8 + 4  # coins + plis du dos


# --- API (mode mock) -----------------------------------------------------------------------------------------
@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    providers = Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=MockComfyUIClient(),
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(make_settings(), providers=providers)) as client:
        yield client


def _idle(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(30)  # type: ignore[attr-defined]


def _wait_job(c: TestClient, job_id: int) -> dict[str, Any]:
    c.app.state.ctx.jobs.wait(job_id, timeout=120)  # type: ignore[attr-defined]
    return _ok(c.get(f"/jobs/{job_id}"))


def _tome(c: TestClient, *, direction: str = "rtl", identity: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    s = _ok(c.post("/projects", json={**STYLE, "title": "Le Sceau d'Ébène", "reading_direction": direction}), 201)
    chapters = [
        _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": t, "synopsis": syn}), 201)
        for t, syn in (
            ("Le fleuve", "Aïko suit un renard à trois queues jusqu'au sanctuaire du fleuve."),
            ("Le pacte", "Kenji révèle que le pacte a été scellé par sa propre mère."),
        )
    ]
    v = _ok(c.post(f"/projects/{s['id']}/volumes", json={"chapter_ids": [ch["id"] for ch in chapters]}), 201)
    if identity:
        base = f"/projects/{s['id']}/identity"
        palette = _ok(c.post(f"{base}/palettes", json={}))["palette_proposals"][0]
        _ok(c.put(f"{base}/palette", json=palette))
        concept = _ok(c.post(f"{base}/logos", json={}))["logo_proposals"][0]
        _ok(c.post(f"{base}/logo", json=concept["spec"]), 201)
    return s, v


def test_mock_tome_with_two_chapters_gives_summary_back_front_and_zip(c: TestClient) -> None:
    s, v = _tome(c)
    vid = v["id"]
    # Illustration de 1re (flux de couverture, mock).
    _ok(c.post(f"/volumes/{vid}/cover/prompt", json={"intent": "Aïko face au fleuve"}))
    _ok(c.post(f"/volumes/{vid}/cover/generate", json={}), 202)
    _idle(c)
    comp = _ok(c.get(f"/volumes/{vid}/composition"))
    assert comp["has_front_image"] and comp["logo"]["present"] and comp["palette_name"]
    assert any(p["code"] == "no_summary" for p in comp["problems"])
    r = c.post(f"/volumes/{vid}/cover/export", json={})
    assert r.status_code == 422 and "Résumé de 4e vide" in r.text

    # Résumé de 4e par l'IA, éditable, « Réécrire ».
    comp = _ok(c.post(f"/volumes/{vid}/back/summary", json={}))
    assert comp["summary_source"] == "ai" and 600 <= comp["summary_chars"] <= 900 and comp["tagline"]
    assert "scellé par sa propre mère" not in comp["summary"]
    rewritten = _ok(c.post(f"/volumes/{vid}/back/summary", json={"rewrite": True}))
    assert rewritten["summary"] != comp["summary"]
    edited = _ok(c.patch(f"/volumes/{vid}/composition", json={"tagline": "L'été sera brûlant !"}))
    assert edited["tagline"] == "L'été sera brûlant !" and edited["summary_source"] == "manual"

    # Petite illustration de 4e : génération par le flux de couverture (ratio de la 4e, aucun texte).
    job = _ok(
        c.post(f"/volumes/{vid}/back/generate", json={"prompt": "Le renard à trois queues sous les lanternes."}), 202
    )
    assert job["params"]["kind"] == "back"
    assert "no text" in job["params"]["prompt"].casefold()
    aw, ah = REG.require_composition().back_illustration.aspect
    assert abs(job["params"]["width"] / job["params"]["height"] - aw / ah) < 0.02
    _idle(c)
    comp = _ok(c.get(f"/volumes/{vid}/composition"))
    assert comp["back_image"]["source"] == "generated" and len(comp["back_versions"]) == 1
    assert comp["back_versions"][0]["selected"]
    studio = _ok(c.get(f"/volumes/{vid}/cover"))
    assert len(studio["versions"]) == 1  # la 4e ne se mêle pas aux versions de la 1re
    assert not comp["problems"], comp["problems"]
    assert comp["order"] == ["front", "spine", "back"]  # manga : rtl

    # Aperçus.
    for which in ("front", "back", "spine", "flat"):
        r = c.get(f"/volumes/{vid}/composition/{which}.png?width=300")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(r.content)).width == min(300, Image.open(io.BytesIO(r.content)).width)

    # Export : job avec progression, ZIP 1re / 4e / à plat, PNG 300 dpi + SVG.
    job = _ok(c.post(f"/volumes/{vid}/cover/export", json={"bleed": True, "crop_marks": True}), 202)
    assert job["step"] == "cover_export"
    done = _wait_job(c, job["id"])
    assert done["status"] == "succeeded", done
    r = c.get(f"/cover-exports/{job['id']}/file")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = set(zf.namelist())
        assert {
            f"{stem}.{ext}"
            for stem in ("1re-de-couverture", "4e-de-couverture", "couverture-a-plat")
            for ext in ("png", "svg")
        } <= names
        with Image.open(io.BytesIO(zf.read("1re-de-couverture.png"))) as im:
            assert round(im.info["dpi"][0]) == 300
        with Image.open(io.BytesIO(zf.read("couverture-a-plat.png"))) as im:
            flat_w = im.width
        assert "Ébène" in zf.read("4e-de-couverture.svg").decode("utf-8")
        assert "4e-de-couverture-texte.txt" in names
    assert flat_w > 2 * REG.cover_format(MANGA).trim_px[0]
    last = _ok(c.get(f"/volumes/{vid}/composition"))["last_export"]
    assert last["job_id"] == job["id"] and last["url"] == f"/cover-exports/{job['id']}/file"


def test_api_back_image_from_a_panel_layout_author_and_logo(c: TestClient) -> None:
    s, v = _tome(c, identity=False)
    vid = v["id"]
    comp = _ok(c.get(f"/volumes/{vid}/composition"))
    assert comp["panel_choices"] == []
    assert any(w["code"] == "no_logo" for w in comp["warnings"])
    assert any(w["code"] == "no_palette" for w in comp["warnings"])
    # Case qui n'est pas du tome : refusée.
    r = c.patch(f"/volumes/{vid}/composition", json={"back_image": {"source": "panel", "id": 999}})
    assert r.status_code == 422
    r = c.patch(f"/volumes/{vid}/composition", json={"back_layout": "inconnu"})
    assert r.status_code == 422
    comp = _ok(c.patch(f"/volumes/{vid}/composition", json={"back_layout": "encart", "series_author": "Hélène  Côté"}))
    assert comp["back_layout"] == "encart" and comp["series_author"] == "Hélène Côté"
    comp = _ok(c.patch(f"/volumes/{vid}/composition", json={"author": "Studio Ébène"}))
    assert comp["author"] == "Studio Ébène"
    # Texte très long saisi à la main : gardé, mais problème lisible et export refusé.
    comp = _ok(c.patch(f"/volumes/{vid}/composition", json={"summary": SUMMARY * 5, "tagline": "Vite !"}))
    [problem] = [p for p in comp["problems"] if p["code"] == "summary_overflow"]
    assert "ne tient pas dans le cadre" in problem["message"]
    r = c.post(f"/volumes/{vid}/cover/export", json={})
    assert r.status_code == 422 and "ne tient pas" in r.text
    # Le logo, s'il existe, reste dans la marge de sécurité.
    base = f"/projects/{s['id']}/identity"
    palette = _ok(c.post(f"{base}/palettes", json={}))["palette_proposals"][0]
    _ok(c.put(f"{base}/palette", json=palette))
    _ok(c.post(f"{base}/logo", json=_ok(c.post(f"{base}/logos", json={}))["logo_proposals"][0]["spec"]), 201)
    comp = _ok(c.patch(f"/volumes/{vid}/composition", json={"logo": {"cx": 0, "cy": 1, "scale": 0.5}}))
    logo = comp["logo"]
    assert logo["present"] and logo["placement"]["scale"] == 0.5
    rect, safe = logo["rect"], logo["safe"]
    assert rect["x"] >= safe["x"] - 1e-6 and rect["y"] + rect["height"] <= safe["y"] + safe["height"] + 1e-6
    comp = _ok(c.patch(f"/volumes/{vid}/composition", json={"reset_logo": True}))
    assert comp["logo"]["placement"]["scale"] == comp["logo"]["default_scale"]


def test_api_flat_order_follows_the_series_direction(c: TestClient) -> None:
    _, v = _tome(c, direction="ltr", identity=False)
    assert _ok(c.get(f"/volumes/{v['id']}/composition"))["order"] == ["back", "spine", "front"]
