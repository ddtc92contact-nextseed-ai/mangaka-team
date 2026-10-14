"""Tomes et couverture : schéma et migration v32, CRUD des tomes (chapitres inclus, un chapitre dans un seul tome,
13 × 18 par défaut), géométrie des formats de couverture (mm → px, fond perdu, zones dans la marge de sécurité),
flux ComfyUI dédié (entrées des nœuds, références, seed enregistrée), prompt toujours en couleur, génération en
mode mock au bon ratio. ComfyUI et LLM en mock."""

from __future__ import annotations

import io
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.covers import (
    clear_zone_text,
    cover_rules,
    cover_style,
    finish_cover_prompt,
    fit_exact,
    generation_size,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import Project
from tests.conftest import PRESETS_DIR, STYLE, png_bytes

REG = PresetRegistry.load(PRESETS_DIR)
COVER = REG.cover
MANGA = "manga-13x18-300dpi"
A4 = "a4-300dpi"


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def comfy() -> MockComfyUIClient:
    return MockComfyUIClient()


@pytest.fixture
def llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
def c(make_settings: Callable[..., Settings], comfy: MockComfyUIClient, llm: MockLLMProvider) -> Iterator[TestClient]:
    providers = Providers(
        llm=llm, vision=None, comfyui=comfy, names={"llm": "mock", "vision": "mock", "comfyui": "mock"}, errors={}
    )
    with TestClient(create_app(make_settings(), providers=providers)) as client:
        yield client


def _idle(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(15)  # type: ignore[attr-defined]


def _series(c: TestClient, **extra: Any) -> dict[str, Any]:
    return _ok(c.post("/projects", json={**STYLE, "title": "Lame de Kaito", **extra}), 201)


def _chapters(c: TestClient, series_id: int, n: int) -> list[dict[str, Any]]:
    return [_ok(c.post(f"/projects/{series_id}/chapters", json={"title": f"Ch {i}"}), 201) for i in range(1, n + 1)]


def _character(c: TestClient, series_id: int, name: str, *, image: bool = True) -> dict[str, Any]:
    entry = _ok(
        c.post(f"/projects/{series_id}/characters", json={"name": name, "visual_description": "spiky black hair"}),
        201,
    )
    if image:
        _ok(c.post(f"/characters/{entry['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    return entry


# --- presets : formats et réglages ------------------------------------------------------------
def test_cover_presets_load_without_issue() -> None:
    assert not [i for i in REG.issues if i.file.startswith(("cover", "workflows/qwen-image-couverture"))]
    assert COVER is not None and COVER.workflow in REG.workflows
    assert REG.default_cover_format == MANGA
    assert set(REG.cover_formats) == {MANGA, A4}
    # Le rendu de la couverture est en couleur, et le flux dédié n'est jamais proposé comme palier de série.
    assert not REG.style_renderings[COVER.rendering].monochrome
    wf = REG.workflows[COVER.workflow].preset
    assert wf.tier is not None and wf.tier.choice is None and wf.reference_images and not wf.distilled


def test_format_geometry_mm_to_px_bleed_and_zones() -> None:
    manga = REG.cover_format(MANGA)
    assert (manga.width_mm, manga.height_mm, manga.dpi, manga.bleed_mm) == (130, 180, 300, 3)
    # round(mm / 25,4 × 300) : 130 mm → 1535 px, 180 mm → 2126 px ; fond perdu 3 mm → 35 px de chaque côté.
    assert manga.trim_px == (1535, 2126)
    assert manga.bleed_px == 35
    assert manga.full_mm == (136, 186) and manga.full_px == (1606, 2197)
    # A4 : dimensions reprises du format de page existant.
    a4 = REG.cover_format(A4)
    page = REG.page_format("a4-300dpi")
    assert (a4.width_mm, a4.height_mm, a4.dpi, a4.bleed_mm) == (page.width_mm, page.height_mm, page.dpi, page.bleed_mm)
    assert a4.trim_px == (page.width_px, page.height_px) == (2480, 3508)
    assert a4.full_px == (2551, 3579)
    for fmt in (manga, a4):
        ids = {z.id for z in fmt.zones}
        assert {"logo", "tome", "auteur"} <= ids
        logo = next(z for z in fmt.zones if z.id == "logo")
        assert logo.clear and fmt.clear_zone is logo
        # Bandeau du logo en haut, ~25 % de la hauteur.
        assert 0.2 <= logo.height_mm / fmt.height_mm <= 0.3 and logo.y_mm <= fmt.safety_mm + 1
        w, h = fmt.full_px
        safe = fmt.mm_to_px(fmt.bleed_mm + fmt.safety_mm)
        for z in fmt.zones:
            px = fmt.zone_px(z)
            # Zones dans la marge de sécurité, décalées du fond perdu dans l'image complète.
            assert px["x"] >= safe - 1 and px["y"] >= safe - 1
            assert px["x"] + px["width"] <= w - safe + 1 and px["y"] + px["height"] <= h - safe + 1
    assert clear_zone_text(manga) == "the top 29% of the image"


def test_a_zone_outside_the_safety_margin_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    path = root / "cover_formats" / "manga-13x18-300dpi.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["zones"][2]["y_mm"] = 170  # nom de l'auteur jusqu'à 182 mm : hors du format
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(root)
    assert MANGA not in reg.cover_formats and A4 in reg.cover_formats
    [issue] = [i for i in reg.issues if i.file == "cover_formats/manga-13x18-300dpi.yaml"]
    assert "marge de sécurité" in issue.message
    assert reg.default_cover_format == A4


def test_cover_yaml_refuses_a_black_and_white_rendering(tmp_path: Path) -> None:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    path = root / "cover.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["rendering"] = "nb-trames"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(root)
    assert reg.cover is None
    assert any("toujours en couleur" in i.message for i in reg.issues if i.file == "cover.yaml")


def test_generation_size_keeps_the_ratio_with_bleed() -> None:
    assert COVER is not None
    for fmt in REG.cover_formats.values():
        w, h = generation_size(fmt, COVER.long_side, COVER.multiple)
        assert h == COVER.long_side and w % COVER.multiple == 0
        fw, fh = fmt.full_px
        assert abs(w / h - fw / fh) < 0.01


def test_fit_exact_crops_to_the_exact_size_at_the_format_dpi() -> None:
    out = fit_exact(png_bytes((1000, 1300)), 1606, 2197, 300)
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (1606, 2197)
        assert round(im.info["dpi"][0]) == 300


# --- couleur, même en N&B ----------------------------------------------------------------------
def test_black_and_white_series_gets_a_colour_cover_prompt() -> None:
    assert COVER is not None
    series = Project(title="Lame", **{**STYLE, "style_rendering": "nb-trames"}, style_options={"trames": "denses"})
    series.style_lora_name = None
    style = cover_style(REG, series, COVER)
    assert style.monochrome_series
    colour = REG.style_renderings[COVER.rendering]
    for word in colour.prompt_keywords:
        assert word in style.style
    for word in REG.style_renderings["nb-trames"].prompt_keywords:
        assert word not in style.style
    assert "black and white" not in style.style.casefold() and "screentone" not in style.style.casefold()
    fmt = REG.cover_format(MANGA)
    prompt = finish_cover_prompt("Kaito raises his crimson sword under a golden sky.", style, cover_rules(COVER, fmt))
    # Jamais le filtre des mots de couleur des séries N&B : « crimson », « golden » restent.
    assert "crimson" in prompt and "golden" in prompt
    assert prompt.startswith(COVER.lead)
    assert "the top 29% of the image" in prompt and "no text" in prompt.casefold()
    # La série N&B garde ses cases en noir et blanc.
    assert "black and white" in REG.style_renderings[series.style_rendering].lead.casefold()


# --- tomes : CRUD -----------------------------------------------------------------------------
def test_volume_crud_chapters_and_default_format(c: TestClient) -> None:
    s = _series(c)
    ch = _chapters(c, s["id"], 4)
    v1 = _ok(c.post(f"/projects/{s['id']}/volumes", json={"chapter_ids": [ch[1]["id"], ch[0]["id"]]}), 201)
    assert v1["number"] == 1 and v1["cover_format"] == MANGA and v1["cover_format_name"].startswith("Manga 13")
    # Liste ordonnée, dans l'ordre donné.
    assert [x["number"] for x in v1["chapters"]] == [2, 1]
    v2 = _ok(c.post(f"/projects/{s['id']}/volumes", json={"title": "La ville", "cover_format": A4}), 201)
    assert (v2["number"], v2["title"], v2["cover_format"]) == (2, "La ville", A4)
    # Un chapitre dans un seul tome.
    r = c.patch(f"/volumes/{v2['id']}", json={"chapter_ids": [ch[0]["id"], ch[2]["id"]]})
    assert r.status_code == 422 and "déjà dans le tome 1" in r.text
    v2 = _ok(c.patch(f"/volumes/{v2['id']}", json={"chapter_ids": [ch[2]["id"], ch[3]["id"]]}))
    assert [x["number"] for x in v2["chapters"]] == [3, 4]
    # Numéro unique dans la série, format connu.
    assert c.patch(f"/volumes/{v2['id']}", json={"number": 1}).status_code == 422
    assert c.patch(f"/volumes/{v2['id']}", json={"cover_format": "b5"}).status_code == 422
    assert c.post(f"/projects/{s['id']}/volumes", json={"number": 2}).status_code == 422
    v1 = _ok(c.patch(f"/volumes/{v1['id']}", json={"cover_format": A4, "chapter_ids": [ch[0]["id"]]}))
    assert v1["cover_format"] == A4 and [x["number"] for x in v1["chapters"]] == [1]
    # Un chapitre d'une autre série est refusé.
    other = _series(c, title="Autre")
    [foreign] = _chapters(c, other["id"], 1)
    assert c.patch(f"/volumes/{v1['id']}", json={"chapter_ids": [foreign["id"]]}).status_code == 422
    assert [v["number"] for v in _ok(c.get(f"/projects/{s['id']}/volumes"))] == [1, 2]
    # Supprimer un tome garde ses chapitres ; supprimer un chapitre le retire du tome.
    assert c.delete(f"/volumes/{v2['id']}").status_code == 204
    assert len(_ok(c.get(f"/projects/{s['id']}/chapters"))) == 4
    c.delete(f"/chapters/{ch[0]['id']}")
    assert _ok(c.get(f"/volumes/{v1['id']}"))["chapters"] == []


def test_chapters_are_unchanged_by_volumes(c: TestClient) -> None:
    s = _series(c)
    [ch] = _chapters(c, s["id"], 1)
    before = _ok(c.get(f"/chapters/{ch['id']}"))
    _ok(c.post(f"/projects/{s['id']}/volumes", json={"chapter_ids": [ch["id"]]}), 201)
    after = _ok(c.get(f"/chapters/{ch['id']}"))
    assert {k: v for k, v in after.items() if k != "updated_at"} == {
        k: v for k, v in before.items() if k != "updated_at"
    }


def test_cover_formats_endpoint_gives_px_and_zones(c: TestClient) -> None:
    formats = {f["id"]: f for f in _ok(c.get("/presets/cover-formats"))}
    manga = formats[MANGA]
    assert manga["default"] and (manga["full_width_px"], manga["full_height_px"]) == (1606, 2197)
    logo = next(z for z in manga["zones"] if z["id"] == "logo")
    assert logo["clear"] and abs(logo["rel"]["y"] - 8 / 186) < 1e-6
    assert (manga["generation_width"], manga["generation_height"]) == generation_size(
        REG.cover_format(MANGA),
        COVER.long_side,  # type: ignore[union-attr]
        COVER.multiple,  # type: ignore[union-attr]
    )


# --- couverture : prompt, génération ------------------------------------------------------------
def test_cover_prompt_written_by_ai_then_generated_at_the_format_ratio(
    c: TestClient, comfy: MockComfyUIClient, llm: MockLLMProvider
) -> None:
    s = _series(c)  # N&B à trames
    kaito = _character(c, s["id"], "Kaito")
    rin = _character(c, s["id"], "Rin")
    nobody = _character(c, s["id"], "Sans image", image=False)
    v = _ok(c.post(f"/projects/{s['id']}/volumes", json={"title": "La ville en feu"}), 201)
    studio = _ok(
        c.post(
            f"/volumes/{v['id']}/cover/prompt",
            json={
                "intent": "Kaito de face, sabre levé, ville en feu derrière",
                "character_ids": [kaito["id"], rin["id"], nobody["id"]],
            },
        )
    )
    assert studio["monochrome_series"] and studio["problem"] is None
    vol = studio["volume"]
    assert vol["cover_prompt_source"] == "ai" and vol["cover_character_ids"] == [kaito["id"], rin["id"], nobody["id"]]
    prompt = vol["cover_prompt"]
    assert prompt.startswith(COVER.lead)  # type: ignore[union-attr]
    assert "<image1>" in prompt and "<image2>" in prompt and "<image3>" not in prompt
    assert "crimson" in prompt  # couleur gardée, série N&B ou pas
    sent = llm.requests[-1]["messages"]
    assert "Kaito de face" in sent[1].content and "cover_prompt" in sent[1].content
    assert "black and white" not in sent[0].content.casefold() + sent[1].content.casefold()

    # Le prompt reste éditable : retouché à la main avant génération.
    edited = prompt + " Embers drift across the sky."
    job = _ok(c.post(f"/volumes/{v['id']}/cover/generate", json={"prompt": edited, "seed": 1234}), 202)
    assert job["step"] == "cover"
    # Une génération à la fois par tome.
    second = c.post(f"/volumes/{v['id']}/cover/generate", json={})
    assert second.status_code in (202, 409)
    _idle(c)
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"

    studio = _ok(c.get(f"/volumes/{v['id']}/cover"))
    assert studio["volume"]["cover_prompt_source"] == "manual"
    first = next(x for x in studio["versions"] if x["seed"] == 1234)
    assert first["selected"] and studio["volume"]["selected_cover_id"] == first["id"]
    # Image au bon ratio, fond perdu compris : la taille exacte du format à 300 DPI.
    assert (first["width"], first["height"]) == (1606, 2197)
    data = c.get(first["url"]).content
    with Image.open(io.BytesIO(data)) as im:
        assert im.size == (1606, 2197) and round(im.info["dpi"][0]) == 300
    assert (first["generated_width"], first["generated_height"]) == generation_size(
        REG.cover_format(MANGA),
        COVER.long_side,  # type: ignore[union-attr]
        COVER.multiple,  # type: ignore[union-attr]
    )
    assert first["upscaler_name"]
    assert "Embers drift" in first["prompt"] and "no text" in first["prompt"].casefold()

    # Workflow envoyé : flux dédié, prompts, taille, seed, deux références (personnages avec image).
    wf = REG.workflow(COVER.workflow)  # type: ignore[union-attr]
    gen = next(
        p for p in comfy.prompts.values() if str(_prefix(p, wf.preset.output_node)).endswith("tome-01/couverture")
    )
    mapping = wf.preset.mapping
    get = lambda name: gen[mapping[name].node]["inputs"][mapping[name].input]  # noqa: E731
    assert get("seed") == 1234 and "Embers drift" in get("positive_prompt")
    assert (get("width"), get("height")) == (first["generated_width"], first["generated_height"])
    assert "monochrome" in get("negative_prompt") and "text" in get("negative_prompt")
    loads = [n for n in gen.values() if n.get("class_type") == "LoadImage"]
    assert len(loads) == 2

    # Régénérer : nouvelle version (nouvelle seed), la retenue ne change pas tant qu'on n'en choisit pas une autre.
    _idle(c)
    if second.status_code == 409:
        _ok(c.post(f"/volumes/{v['id']}/cover/generate", json={}), 202)
        _idle(c)
    studio = _ok(c.get(f"/volumes/{v['id']}/cover"))
    assert len(studio["versions"]) == 2
    other = next(x for x in studio["versions"] if x["id"] != first["id"])
    assert other["seed"] is not None and not other["selected"]
    studio = _ok(c.post(f"/volume-covers/{other['id']}/select"))
    assert studio["volume"]["selected_cover_id"] == other["id"]
    assert c.delete(f"/volume-covers/{other['id']}").status_code == 204
    assert _ok(c.get(f"/volumes/{v['id']}/cover"))["volume"]["selected_cover_id"] is None


def test_a4_cover_and_errors(c: TestClient) -> None:
    s = _series(c, style_rendering="couleur")
    v = _ok(c.post(f"/projects/{s['id']}/volumes", json={"cover_format": A4}), 201)
    r = c.post(f"/volumes/{v['id']}/cover/generate", json={})
    assert r.status_code == 409 and "prompt vide" in r.text.casefold()
    _ok(c.patch(f"/volumes/{v['id']}", json={"cover_prompt": "A lone samurai on a hill at dawn."}))
    studio = _ok(c.get(f"/volumes/{v['id']}/cover"))
    assert not studio["monochrome_series"] and studio["volume"]["cover_prompt_source"] == "manual"
    assert studio["format"]["id"] == A4 and len(studio["format"]["zones"]) == 3
    job = _ok(c.post(f"/volumes/{v['id']}/cover/generate", json={}), 202)
    _idle(c)
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    [version] = _ok(c.get(f"/volumes/{v['id']}/cover"))["versions"]
    assert (version["width"], version["height"]) == (2551, 3579) and version["seed"] is not None
    # Trop de personnages, personnage d'une autre série.
    chars = [_character(c, s["id"], f"P{i}", image=False) for i in range(COVER.max_characters + 1)]  # type: ignore[union-attr]
    r = c.patch(f"/volumes/{v['id']}", json={"cover_character_ids": [x["id"] for x in chars]})
    assert r.status_code == 422
    # Supprimer la série supprime ses tomes.
    assert c.delete(f"/projects/{s['id']}").status_code == 204
    assert c.get(f"/volumes/{v['id']}").status_code == 404


def _prefix(workflow: dict[str, Any], node: str) -> str:
    return str((workflow.get(node) or {}).get("inputs", {}).get("filename_prefix") or "")


# --- schéma et migration -----------------------------------------------------------------------
def _columns(path: Path) -> dict[str, set[str]]:
    con = sqlite3.connect(path)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out = {t: {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')} for t in tables}
    con.close()
    return out


def test_fresh_database_has_the_volume_tables(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    create_db_engine(path).dispose()
    cols = _columns(path)
    assert {"volumes", "volume_chapters", "volume_covers"} <= set(cols)
    assert {"project_id", "number", "title", "cover_format", "cover_prompt", "selected_cover_id"} <= cols["volumes"]
    assert {"volume_id", "chapter_id", "position"} <= cols["volume_chapters"]
    assert {"volume_id", "path", "width", "height", "seed", "params"} <= cols["volume_covers"]
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 32
    con.close()


def test_v31_database_gets_empty_volume_tables(make_settings: Callable[..., Settings]) -> None:
    """v31 → v32 : tables des tomes créées, vides ; les chapitres existants ne changent pas."""
    settings = make_settings()
    with TestClient(create_app(settings)) as client:
        s = client.post("/projects", json={**STYLE, "title": "Ancienne"}).json()
        ch = client.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}).json()
    con = sqlite3.connect(settings.database_path)
    for table in ("volume_covers", "volume_chapters", "volumes"):
        con.execute(f"DROP TABLE {table}")
    con.execute("PRAGMA user_version = 31")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as client:
        assert client.get(f"/projects/{s['id']}/volumes").json() == []
        assert client.get(f"/chapters/{ch['id']}").json()["title"] == "Un"
        v = client.post(f"/projects/{s['id']}/volumes", json={"chapter_ids": [ch["id"]]})
        assert v.status_code == 201 and v.json()["cover_format"] == MANGA
    con = sqlite3.connect(settings.database_path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    con.close()
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
