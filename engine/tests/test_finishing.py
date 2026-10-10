"""Finition d'impression : facteur calculé par case, graphe d'agrandissement, parcours complet (mock)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.pipeline.finishing import effective_dpi, finish_plan, printed_box
from mangaka_engine.pipeline.fonts import FontBook
from mangaka_engine.pipeline.layout import target_size
from mangaka_engine.pipeline.render import load_chapter_pages, page_inputs
from mangaka_engine.presets import PresetRegistry, build_upscale_workflow
from mangaka_engine.store.models import PanelImage
from tests.conftest import PRESETS_DIR, STYLE

REG = PresetRegistry.load(PRESETS_DIR)
A4 = REG.page_format("a4-300dpi")
TOL = REG.defaults.finishing_tolerance if REG.defaults else 0.9
BLEED = A4.mm_to_px(A4.bleed_mm)  # 3 mm à 300 dpi = 35 px
# Zone utile A4 300 dpi : (210 − 15 − 12) × (297 − 15 − 15) mm = 2161 × 3154 px.
LIVE_W = A4.mm_to_px(A4.width_mm - A4.margins_mm.inner - A4.margins_mm.outer)
LIVE_H = A4.mm_to_px(A4.height_mm - A4.margins_mm.top - A4.margins_mm.bottom)
GUT_H = A4.mm_to_px(A4.gutters_mm.horizontal)
GUT_V = A4.mm_to_px(A4.gutters_mm.vertical)
X0 = A4.mm_to_px(A4.margins_mm.inner)
Y0 = A4.mm_to_px(A4.margins_mm.top)


def _plan_for_box(w: int, h: int) -> Any:
    """Plan de finition d'une case de w × h px (zone utile) générée à la taille de la mise en page (≈ 1 Mpx)."""
    gen = target_size(w, h, REG.layout)
    bbox = {"x1": X0, "y1": Y0, "x2": X0 + w, "y2": Y0 + h}
    box = printed_box(bbox, A4)
    return gen, box, finish_plan(gen["width"], gen["height"], *box, A4.dpi, TOL)


# --- calcul du facteur ------------------------------------------------------------------
def test_live_area_matches_the_issue() -> None:
    assert (LIVE_W, LIVE_H) == (2161, 3154)


def test_full_page_panel_is_about_115_dpi() -> None:
    gen, box, plan = _plan_for_box(LIVE_W, LIVE_H)
    assert box == (2161, 3154)  # dans la zone utile : pas de fond perdu
    assert 110 <= plan.dpi <= 120
    assert plan.needed
    assert plan.factor == pytest.approx(300 / plan.dpi)
    assert 2.4 < plan.factor < 2.8  # calculé, pas un ×3 aveugle
    # La taille finale couvre exactement la boîte (un côté juste, l'autre ≥) sans déformer l'image.
    assert plan.width >= box[0] and plan.height >= box[1]
    assert min(plan.width - box[0], plan.height - box[1]) <= 1
    assert plan.width / plan.height == pytest.approx(gen["width"] / gen["height"], rel=2e-3)
    assert effective_dpi(plan.width, plan.height, *box, A4.dpi) == pytest.approx(300, abs=0.5)


def test_two_bands_is_about_164_dpi() -> None:
    _, box, plan = _plan_for_box(LIVE_W, (LIVE_H - GUT_H) // 2)
    assert 158 <= plan.dpi <= 170
    assert plan.needed and plan.factor == pytest.approx(300 / plan.dpi)


def test_three_bands() -> None:
    _, box, plan = _plan_for_box(LIVE_W, (LIVE_H - 2 * GUT_H) // 3)
    full = _plan_for_box(LIVE_W, LIVE_H)[2]
    two = _plan_for_box(LIVE_W, (LIVE_H - GUT_H) // 2)[2]
    assert two.dpi < plan.dpi < 300 * TOL  # plus petite case → meilleur dpi, mais encore sous le seuil
    assert full.factor > two.factor > plan.factor > 1
    assert plan.needed


def test_grid_2x2() -> None:
    _, box, plan = _plan_for_box((LIVE_W - GUT_V) // 2, (LIVE_H - GUT_H) // 2)
    assert box == ((LIVE_W - GUT_V) // 2, (LIVE_H - GUT_H) // 2)
    assert 200 <= plan.dpi <= 240
    assert plan.needed
    assert plan.width >= box[0] and plan.height >= box[1]


def test_panel_already_at_target_dpi_is_not_upscaled() -> None:
    plan = finish_plan(2200, 3200, LIVE_W, LIVE_H, A4.dpi, TOL)
    assert plan.dpi >= 300 and not plan.needed
    # Tolérance : ≥ 0,9 × 300 = 270 dpi suffit, en dessous il faut agrandir.
    ok = finish_plan(round(LIVE_W * 0.92), round(LIVE_H * 0.92), LIVE_W, LIVE_H, A4.dpi, 0.9)
    low = finish_plan(round(LIVE_W * 0.85), round(LIVE_H * 0.85), LIVE_W, LIVE_H, A4.dpi, 0.9)
    assert not ok.needed and 270 <= ok.dpi < 300
    assert low.needed and low.dpi < 270
    # Une tolérance plus stricte (réglable dans defaults.yaml) fait finaliser la même case.
    assert finish_plan(round(LIVE_W * 0.92), round(LIVE_H * 0.92), LIVE_W, LIVE_H, A4.dpi, 1.0).needed


def test_bleed_is_counted_in_the_printed_box() -> None:
    # Pleine page à fond perdu : la case touche les 4 bords de la page → + 3 mm de chaque côté.
    bbox = {"x1": 0, "y1": 0, "x2": A4.width_px, "y2": A4.height_px}
    assert printed_box(bbox, A4) == (A4.width_px + 2 * BLEED, A4.height_px + 2 * BLEED)
    # Bande du haut à fond perdu côté extérieur seulement : haut + côté droit.
    band = {"x1": X0, "y1": 0, "x2": A4.width_px, "y2": 1500}
    assert printed_box(band, A4) == (A4.width_px - X0 + BLEED, 1500 + BLEED)
    # Le fond perdu agrandit la boîte, donc baisse le dpi effectif de la même image.
    gen = target_size(A4.width_px, A4.height_px, REG.layout)
    with_bleed = finish_plan(gen["width"], gen["height"], *printed_box(bbox, A4), A4.dpi, TOL)
    without = finish_plan(gen["width"], gen["height"], A4.width_px, A4.height_px, A4.dpi, TOL)
    assert with_bleed.dpi < without.dpi and with_bleed.factor > without.factor
    assert with_bleed.width >= A4.width_px + 2 * BLEED and with_bleed.height >= A4.height_px + 2 * BLEED


# --- graphe d'agrandissement ----------------------------------------------------------------
def test_default_upscaler_is_declared_in_defaults() -> None:
    assert REG.issues == []
    assert REG.default_upscaler == "realesrgan-x4plus-anime-6b"
    assert set(REG.upscalers) == {"realesrgan-x4plus-anime-6b", "ultrasharp-4x", "remacri-4x", "seedvr2-7b"}
    assert REG.upscaler("seedvr2-7b").preset.high_fidelity
    assert not any(REG.upscaler(i).preset.high_fidelity for i in REG.upscalers if i != "seedvr2-7b")


@pytest.mark.parametrize("upscaler_id", ["realesrgan-x4plus-anime-6b", "ultrasharp-4x", "remacri-4x"])
def test_build_esrgan_upscale_workflow(upscaler_id: str) -> None:
    loaded = REG.upscaler(upscaler_id)
    built = build_upscale_workflow(loaded, "mangaka/finition_case3_v1.png", 2161, 3155, filename_prefix="mangaka/x")
    wf = built.workflow
    by_class = {n["class_type"]: (k, n) for k, n in wf.items()}
    load_id, load = by_class["LoadImage"]
    model_id, model = by_class["UpscaleModelLoader"]
    _, up = by_class["ImageUpscaleWithModel"]
    scale_id, scale = by_class["ImageScale"]
    save_id, save = by_class["SaveImage"]
    # Image source et modèle (celui du JSON du preset, jamais du code).
    assert load["inputs"]["image"] == "mangaka/finition_case3_v1.png"
    assert model["inputs"]["model_name"] == loaded.workflow[model_id]["inputs"]["model_name"]
    assert up["inputs"] == {"upscale_model": [model_id, 0], "image": [load_id, 0]}
    # Taille finale exacte, après le modèle.
    assert (scale["inputs"]["width"], scale["inputs"]["height"]) == (2161, 3155)
    assert scale["inputs"]["image"][0] == by_class["ImageUpscaleWithModel"][0]
    assert save["inputs"]["images"] == [scale_id, 0] and save["inputs"]["filename_prefix"] == "mangaka/x"
    assert built.output_node == save_id
    assert loaded.workflow[scale_id]["inputs"]["width"] != 2161  # le JSON du preset n'est pas modifié


def test_build_seedvr2_upscale_workflow() -> None:
    loaded = REG.upscaler("seedvr2-7b")
    wf = build_upscale_workflow(loaded, "mangaka/src.png", 1200, 1800).workflow
    by_class = {n["class_type"]: (k, n) for k, n in wf.items()}
    assert by_class["LoadImage"][1]["inputs"]["image"] == "mangaka/src.png"
    scale_id, scale = by_class["ImageScale"]
    assert (scale["inputs"]["width"], scale["inputs"]["height"]) == (1200, 1800)
    # La restauration part de l'image à la taille finale et s'y recale (post-traitement).
    assert by_class["SeedVR2Preprocess"][1]["inputs"]["resized_images"] == [scale_id, 0]
    assert by_class["SeedVR2PostProcessing"][1]["inputs"]["original_resized_images"] == [scale_id, 0]
    assert by_class["UNETLoader"][1]["inputs"]["unet_name"] == loaded.workflow["8"]["inputs"]["unet_name"]


def test_no_model_name_in_engine_code() -> None:
    names = {
        v
        for up in REG.upscalers.values()
        for node in up.workflow.values()
        for k, v in node["inputs"].items()
        if k in ("model_name", "unet_name", "vae_name")
    }
    assert names
    engine = Path(__file__).resolve().parents[1] / "mangaka_engine"
    code = "\n".join(p.read_text(encoding="utf-8") for p in engine.rglob("*.py"))
    assert [n for n in names if n in code] == []


# --- parcours complet (ComfyUI factice) ----------------------------------------------------
def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _wait(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]


def _setup(c: TestClient, upscaler: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {**STYLE, "title": "Les Lames", "layout_style": "sage"}
    if upscaler:
        body["upscaler"] = upscaler
    s = _ok(c.post("/projects", json=body), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={"pages": [{"panels": [{"description": "Un toit sous la pluie"}, {"description": "Une ruelle"}]}]},
        )
    )
    page = pages[0]
    res = _ok(c.post(f"/pages/{page['id']}/generate"), 202)
    assert len(res["jobs"]) == 2
    _wait(c)
    return {"series": s, "chapter": ch, "page": page}


def _page(c: TestClient, chapter_id: int) -> dict[str, Any]:
    return _ok(c.get(f"/chapters/{chapter_id}/pages"))[0]


def _export_warnings(c: TestClient, chapter_id: int) -> list[dict[str, Any]]:
    job = _ok(c.post(f"/chapters/{chapter_id}/export"), 202)
    c.app.state.ctx.jobs.wait(job["id"], timeout=60)  # type: ignore[attr-defined]
    job = _ok(c.get(f"/jobs/{job['id']}"))
    assert job["status"] == "succeeded", job
    zf = zipfile.ZipFile(io.BytesIO(c.get(f"/exports/{job['id']}/file").content))
    assert "page-001.png" in zf.namelist()
    return [w for w in job["params"]["warnings"] if w["code"] == "low_dpi"]


def test_finish_page_end_to_end(client: TestClient) -> None:
    c = client
    comfy = c.app.state.ctx.providers.comfyui  # type: ignore[attr-defined]
    data = _setup(c)
    chapter_id = data["chapter"]["id"]
    page = _page(c, chapter_id)
    before = {p["id"]: p["print_info"] for p in page["panels"]}
    assert all(info["status"] == "low" and info["dpi"] < info["min_dpi"] for info in before.values())
    assert len(_export_warnings(c, chapter_id)) == 2  # export d'impression : cases sous le seuil signalées

    res = _ok(c.post(f"/pages/{page['id']}/finish"), 202)
    assert len(res["jobs"]) == 2 and res["skipped"] == 0
    assert {j["step"] for j in res["jobs"]} == {"finishing"}
    assert res["jobs"][0]["params"]["upscaler"] == "realesrgan-x4plus-anime-6b"
    _wait(c)

    page = _page(c, chapter_id)
    for p in page["panels"]:
        info = p["print_info"]
        assert info["status"] == "finished", info
        assert info["finished_dpi"] >= 299 and info["dpi"] == before[p["id"]]["dpi"]  # dpi « 115 → 300 »
        assert (info["finished_width"], info["finished_height"]) == (info["target_width"], info["target_height"])
    # Le ComfyUI factice a reçu la taille finale exacte et a agrandi l'image envoyée.
    upscales = [wf for wf in comfy.prompts.values() if any(n["class_type"] == "ImageScale" for n in wf.values())]
    assert len(upscales) == 2
    sizes = {
        (n["inputs"]["width"], n["inputs"]["height"]) for wf in upscales for n in wf.values() if "width" in n["inputs"]
    }
    assert sizes == {(p["print_info"]["target_width"], p["print_info"]["target_height"]) for p in page["panels"]}

    # L'assemblage (export PNG) prend les images finalisées ; l'aperçu écran garde l'image légère.
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    with ctx.db.session_scope() as session:
        [db_page] = load_chapter_pages(session, chapter_id)
        presets = ctx.agents.presets_for(db_page.chapter.project_id)
        inputs = page_inputs(presets, ctx.files, db_page, FontBook(presets))
        for art in inputs.art.panels:
            img = next(i for i in next(p for p in db_page.panels if p.id == art.id).images if i.selected)
            assert art.image == ctx.files.absolute(img.finish["path"])
            assert art.image_size == (img.finish["width"], img.finish["height"])
            assert inputs.image_urls[art.id] == f"/panel-images/{img.id}/file?v={Path(img.path).stem}"
    assert _export_warnings(c, chapter_id) == []
    render = _ok(c.post(f"/pages/{page['id']}/render"))
    assert render["warnings"] == [] or all(w["code"] != "low_dpi" for w in render["warnings"])

    # Plus rien à faire : la page est ignorée, la case refuse une deuxième finition.
    assert _ok(c.post(f"/pages/{page['id']}/finish"), 202) == {"jobs": [], "panel_ids": [], "skipped": 2}
    res = c.post(f"/panels/{page['panels'][0]['id']}/finish")
    assert res.status_code == 422 and "déjà finalisée" in res.text


def test_changing_selected_version_invalidates_only_that_panel(client: TestClient) -> None:
    c = client
    data = _setup(c)
    chapter_id = data["chapter"]["id"]
    page = _page(c, chapter_id)
    _ok(c.post(f"/pages/{page['id']}/finish"), 202)
    _wait(c)
    a, b = page["panels"]
    finished_a = next(i for i in _ok(c.get(f"/panels/{a['id']}"))["images"] if i["selected"])["finish"]
    assert finished_a and finished_a["upscaler"] == "realesrgan-x4plus-anime-6b"
    path_a = c.app.state.ctx.files.absolute(finished_a["path"])  # type: ignore[attr-defined]
    assert path_a.is_file()
    with Image.open(path_a) as im:
        assert im.size == (finished_a["width"], finished_a["height"])

    _ok(c.post(f"/panels/{a['id']}/generate"), 202)
    _wait(c)
    detail = _ok(c.get(f"/panels/{a['id']}"))
    v2 = max(detail["images"], key=lambda i: i["version"])
    images = _ok(c.post(f"/panel-images/{v2['id']}/select"))
    assert all(i["finish"] is None for i in images)  # finition de la v1 effacée…
    assert not path_a.exists()  # … fichier compris
    page = _page(c, chapter_id)
    info = {p["id"]: p["print_info"] for p in page["panels"]}
    assert info[a["id"]]["status"] == "low" and info[a["id"]]["image_id"] == v2["id"]
    assert info[b["id"]]["status"] == "finished"  # l'autre case garde sa finition

    # « Finaliser cette case » : seule la case a est remise en file.
    job = _ok(c.post(f"/panels/{a['id']}/finish"), 202)
    assert job["step"] == "finishing" and job["params"]["image_id"] == v2["id"]
    _wait(c)
    assert {p["print_info"]["status"] for p in _page(c, chapter_id)["panels"]} == {"finished"}


def test_series_upscaler_override_and_queue_label(client: TestClient) -> None:
    c = client
    comfy = c.app.state.ctx.providers.comfyui  # type: ignore[attr-defined]
    data = _setup(c, upscaler="ultrasharp-4x")
    assert data["series"]["upscaler"] == "ultrasharp-4x"
    page = _page(c, data["chapter"]["id"])
    detail = _ok(c.get(f"/panels/{page['panels'][0]['id']}"))
    assert detail["upscaler"] == "4x-UltraSharp" and detail["print_info"]["status"] == "low"
    res = _ok(c.post(f"/chapters/{data['chapter']['id']}/finish"), 202)
    assert {j["params"]["upscaler"] for j in res["jobs"]} == {"ultrasharp-4x"}
    queue = _ok(c.get("/queue"))
    labels = [i["label"] for i in ([queue["running"]] if queue["running"] else []) + queue["pending"]]
    _wait(c)
    assert not labels or all(label.startswith("Finition d'impression") for label in labels)
    expected = REG.upscaler("ultrasharp-4x").workflow["2"]["inputs"]["model_name"]
    sent = {
        n["inputs"]["model_name"]
        for wf in comfy.prompts.values()
        for n in wf.values()
        if n["class_type"] == "UpscaleModelLoader"
    }
    assert sent == {expected}
    res = c.patch(f"/projects/{data['series']['id']}", json={"upscaler": "inconnu"})
    assert res.status_code == 422 and "agrandisseur inconnu" in res.text
    assert _ok(c.patch(f"/projects/{data['series']['id']}", json={"upscaler": None}))["upscaler"] is None


def test_finish_errors_are_readable(client: TestClient) -> None:
    c = client
    s = _ok(c.post("/projects", json={**STYLE, "title": "Vide"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    page = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "a"}]}]}))[0]
    res = c.post(f"/panels/{page['panels'][0]['id']}/finish")
    assert res.status_code == 422 and "aucune version retenue" in res.text
    assert _ok(c.post(f"/pages/{page['id']}/finish"), 202) == {"jobs": [], "panel_ids": [], "skipped": 1}
    ups = _ok(c.get("/presets/upscalers"))
    assert ups[0]["id"] == "realesrgan-x4plus-anime-6b" and ups[0]["is_default"]
    assert ups[-1]["id"] == "seedvr2-7b" and ups[-1]["high_fidelity"]
    assert json.dumps(_ok(c.get(f"/pages/{page['id']}/finishing"))["panels"]) == json.dumps(
        {str(page["panels"][0]["id"]): None}
    )


def test_finished_version_deleted_with_its_file(client: TestClient) -> None:
    c = client
    data = _setup(c)
    page = _page(c, data["chapter"]["id"])
    panel_id = page["panels"][0]["id"]
    _ok(c.post(f"/panels/{panel_id}/finish"), 202)
    _wait(c)
    img = next(i for i in _ok(c.get(f"/panels/{panel_id}"))["images"] if i["selected"])
    path = c.app.state.ctx.files.absolute(img["finish"]["path"])  # type: ignore[attr-defined]
    assert path.is_file()
    assert c.delete(f"/panel-images/{img['id']}").status_code == 204
    assert not path.exists()
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        assert session.get(PanelImage, img["id"]) is None
