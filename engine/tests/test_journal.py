"""Traçabilité : journal des générations, verdicts de l'auteur, tonalité, export, A/B, statistiques (tout simulé)."""

from __future__ import annotations

import base64
import csv
import io
import json
import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.journal import measure_tonality, tonality_gaps
from mangaka_engine.pipeline.stats import EXPORT_COLUMNS
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import JournalSettings, TonalitySettings
from mangaka_engine.providers.comfyui import ComfyUIUnavailableError, MockComfyUIClient
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import GenerationEvent, GenerationLog, ReferenceVariant
from tests.conftest import PRESETS_DIR, STYLE, force_stages, png_bytes
from tests.test_generation import _ok, _wait, make_client, setup_chapter  # noqa: F401 — fixture
from tests.test_migrations import _columns

REG = PresetRegistry.load(PRESETS_DIR)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _logs(c: TestClient) -> list[GenerationLog]:
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        return list(session.scalars(select(GenerationLog).order_by(GenerationLog.id)))


def _events(c: TestClient) -> list[GenerationEvent]:
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        return list(session.scalars(select(GenerationEvent).order_by(GenerationEvent.id)))


def _images(c: TestClient, panel_id: int) -> list[dict[str, Any]]:
    return sorted(_ok(c.get(f"/panels/{panel_id}/images")), key=lambda i: i["version"])


# --- tonalité ------------------------------------------------------------------------------------
SETTINGS = TonalitySettings()


def test_tonality_all_white() -> None:
    m = measure_tonality(_png(Image.new("RGB", (40, 30), (255, 255, 255))), SETTINGS)
    assert m == {"dark_pct": 0, "black_pct": 0, "white_pct": 100, "saturation_pct": 0, "line_density_pct": 0}


def test_tonality_all_black() -> None:
    m = measure_tonality(_png(Image.new("L", (40, 30), 0)), SETTINGS)
    assert m == {"dark_pct": 100, "black_pct": 100, "white_pct": 0, "saturation_pct": 0, "line_density_pct": 0}


def test_tonality_half_black_half_white() -> None:
    img = Image.new("RGB", (40, 30), (255, 255, 255))
    ImageDraw.Draw(img).rectangle((0, 0, 19, 29), fill=(0, 0, 0))
    m = measure_tonality(_png(img), SETTINGS)
    assert (m["dark_pct"], m["black_pct"], m["white_pct"], m["saturation_pct"]) == (50, 50, 50, 0)
    # Une seule frontière verticale : 30 écarts de 255 sur 39×30 horizontaux + 40×29 verticaux.
    assert m["line_density_pct"] == pytest.approx(100 * 30 / (39 * 30 + 40 * 29), abs=0.01)


def test_tonality_grey_levels_saturation_and_lines() -> None:
    # Gris 100 : sombre (< 128) mais pas noir (≥ 32), pas blanc.
    m = measure_tonality(_png(Image.new("L", (10, 10), 100)), SETTINGS)
    assert (m["dark_pct"], m["black_pct"], m["white_pct"]) == (100, 0, 0)
    # Rouge pur : saturation maximale.
    assert measure_tonality(_png(Image.new("RGB", (10, 10), (255, 0, 0))), SETTINGS)["saturation_pct"] == 100
    # Damier au pixel : chaque voisin diffère de 255 → densité de trait maximale.
    board = Image.new("L", (8, 8), 0)
    for x in range(8):
        for y in range(8):
            if (x + y) % 2:
                board.putpixel((x, y), 255)
    assert measure_tonality(_png(board), SETTINGS)["line_density_pct"] == 100
    # Transparence : posée sur du papier blanc.
    clear = measure_tonality(_png(Image.new("RGBA", (10, 10), (0, 0, 0, 0))), SETTINGS)
    assert clear["white_pct"] == 100 and clear["dark_pct"] == 0


def test_tonality_target_and_gaps_from_preset() -> None:
    assert REG.tonality.target.dark_pct == 21.7 and REG.tonality.target.black_pct == 9.5
    gaps = tonality_gaps({"dark_pct": 30.0, "black_pct": 9.5, "white_pct": 50.0}, REG.tonality)
    assert gaps["dark_pct"] == pytest.approx(8.3) and gaps["black_pct"] == 0
    assert gaps["white_pct"] is None and gaps["saturation_pct"] is None  # pas de cible / pas de mesure


def test_journal_preset_validation() -> None:
    assert [r.id for r in REG.journal.reasons][:3] == ["style-pas-manga", "visage-rate", "mauvais-cadrage"]
    assert REG.journal.reasons[-1].id == "autre" and REG.journal.low_data_below == 20
    assert REG.journal.bucket(10) == "≤ 60 mots" and REG.journal.bucket(500) == "> 200 mots"
    with pytest.raises(ValueError):
        JournalSettings.model_validate({"reasons": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]})
    with pytest.raises(ValueError):
        JournalSettings.model_validate({"prompt_length_buckets": [{"label": "x"}, {"label": "y", "max_words": 3}]})


# --- journal ---------------------------------------------------------------------------------------
def test_each_generation_adds_a_full_row_never_overwritten(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"seed": 7}), 202)
    _wait(c)
    [row] = _logs(c)
    [v1] = _images(c, p1["id"])
    assert row.kind == "panel" and row.status == "succeeded" and row.error is None
    assert (row.project_id, row.chapter_id, row.panel_id) == (data["series"]["id"], data["chapter"]["id"], p1["id"])
    assert row.page_id == data["pages"][0]["id"]
    assert (row.image_kind, row.image_id, row.version) == ("panel_image", v1["id"], 1)
    assert row.preset == v1["preset"] and row.tier == v1["tier"] and row.seed == 7
    assert row.model and row.model.endswith(".safetensors")
    assert row.steps and row.steps > 0 and row.cfg is not None
    assert (row.width, row.height) == (v1["width"], v1["height"])
    # Prompts réellement envoyés (après tous les filtres) et leur longueur.
    assert row.positive_prompt == v1["params"]["prompt"] and row.negative_prompt == v1["params"]["negative_prompt"]
    assert row.positive_chars == len(row.positive_prompt) and row.positive_words == len(row.positive_prompt.split())
    assert row.negative_chars == len(row.negative_prompt) and row.negative_words > 0
    # Références (sorte + id) et LoRA.
    assert row.references and row.references[0]["kind"] == "character" and "filename" not in row.references[0]
    assert row.references[0]["id"] == data["aiko"]["id"] and row.references[0]["image_id"]
    assert {lo["name"] for lo in row.loras} == {"encre.safetensors", "aiko-v3.safetensors"}
    assert row.framing == "plan large" and row.prompt_source == "fragments" and row.knowledge == []
    assert row.duration_ms is not None and row.duration_ms >= 0
    for key in ("dark_pct", "black_pct", "white_pct", "saturation_pct", "line_density_pct"):
        assert getattr(row, key) is not None
    assert row.finish is None  # pas de réglage « finition » : colonne vide

    # Régénération : une ligne de plus, la première ne bouge pas.
    before = {k: getattr(row, k) for k in ("id", "seed", "image_id", "positive_prompt", "dark_pct", "created_at")}
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"seed": 8}), 202)
    _wait(c)
    first, second = _logs(c)
    assert {k: getattr(first, k) for k in before} == before
    assert second.id > first.id and second.seed == 8 and second.version == 2 and second.image_id != first.image_id
    # Même seed : nouvelle ligne quand même.
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"seed": 8}), 202)
    _wait(c)
    assert len(_logs(c)) == 3


def test_failed_generation_is_logged(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    class Offline(MockComfyUIClient):
        def queue_prompt(self, workflow: dict[str, Any]) -> str:
            raise ComfyUIUnavailableError("ComfyUI hors ligne (test)")

    c = make_client(Offline())
    data = setup_chapter(c)
    p2 = data["panels"][1]
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
    [row] = _logs(c)
    assert row.status == "failed" and row.error == "ComfyUI hors ligne (test)"
    assert row.panel_id == p2["id"] and row.image_id is None and row.dark_pct is None
    assert row.positive_prompt and row.preset and row.seed is not None  # préparé avant l'échec


def test_sketch_clean_repair_angle_reference_and_style_kinds(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1, p2, _ = data["panels"]
    _ok(c.post(f"/panels/{p1['id']}/sketch"), 202)
    _wait(c)
    [sketch] = _images(c, p1["id"])
    _ok(c.post(f"/panels/{p1['id']}/sketch/validate"))
    force_stages(c, data["chapter"]["id"], "name")  # name non relue ici
    _ok(c.post(f"/panels/{p1['id']}/clean"), 202)
    _wait(c)
    final = next(i for i in _images(c, p1["id"]) if i["kind"] == "final")
    # Réparation d'une version de la case 2.
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
    [v1] = _images(c, p2["id"])
    mask = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(mask).ellipse((20, 20, 40, 40), fill=(255, 255, 255, 255))
    mask_png = "data:image/png;base64," + base64.b64encode(_png(mask)).decode()
    _ok(c.post(f"/panel-images/{v1['id']}/repair", json={"mask_png": mask_png}), 202)
    _wait(c)
    # Fiche de référence et essais de style.
    aiko = data["aiko"]
    _ok(c.post(f"/characters/{aiko['id']}/reference-variants", json={"sheet": "personnage-portrait", "count": 1}), 202)
    _ok(c.post(f"/projects/{data['series']['id']}/style-board/trials"), 202)
    _wait(c)

    rows = _logs(c)
    kinds = [r.kind for r in rows]
    assert kinds[:4] == ["croquis", "from_sketch", "panel", "inpaint"]
    assert kinds.count("reference_sheet") == 1 and kinds.count("style_trial") == 4
    assert all(r.status == "succeeded" and r.dark_pct is not None for r in rows)
    by_kind = {r.kind: r for r in rows}
    assert by_kind["croquis"].image_id == sketch["id"] and by_kind["from_sketch"].image_id == final["id"]
    assert by_kind["from_sketch"].denoise is not None
    # Passage au propre : origine du prompt reprise du croquis.
    assert by_kind["from_sketch"].prompt_source == by_kind["croquis"].prompt_source == "fragments"
    assert by_kind["inpaint"].prompt_source == "reparation" and by_kind["inpaint"].panel_id == p2["id"]
    ref = by_kind["reference_sheet"]
    assert ref.image_kind == "reference_variant" and ref.project_id == data["series"]["id"] and ref.panel_id is None
    trial = by_kind["style_trial"]
    assert trial.image_kind == "reference_variant" and trial.project_id == data["series"]["id"]
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        assert session.get(ReferenceVariant, ref.image_id) is not None


# --- verdicts ----------------------------------------------------------------------------------------
def test_every_action_records_a_verdict(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1, p2, _ = data["panels"]
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"count": 2}), 202)
    _wait(c)
    v1, v2 = _images(c, p1["id"])
    assert _events(c) == []  # la 1re version choisie d'office n'est pas un verdict

    _ok(c.post(f"/panel-images/{v2['id']}/select"))  # garder
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)  # régénérer
    _wait(c)
    _ok(c.post(f"/panels/{p1['id']}/regenerate-quality"), 202)
    _wait(c)
    _ok(c.put(f"/panels/{p1['id']}/crop", json={"x": 0.5, "y": 0.5, "zoom": 1.2}))  # recadrer
    assert c.delete(f"/panel-images/{v1['id']}").status_code == 204  # supprimer
    _ok(c.post(f"/panel-images/{v2['id']}/qc/override", json={"note": "ok pour moi"}))
    _ok(c.put(f"/panel-images/{v2['id']}/annotation", json={"label": "bad", "defects": [], "note": "main"}))
    # Croquis : valider, re-croquer.
    _ok(c.post(f"/panels/{p2['id']}/sketch"), 202)
    _wait(c)
    [sk] = _images(c, p2["id"])
    _ok(c.post(f"/panels/{p2['id']}/sketch/validate"))
    _ok(c.post(f"/panels/{p2['id']}/sketch"), 202)
    _wait(c)

    logs = {r.image_id: r for r in _logs(c) if r.image_kind == "panel_image"}
    got = [(e.verdict, e.action, e.image_id) for e in _events(c)]
    assert got == [
        ("validated", "select", v2["id"]),
        ("regenerated", "regenerate", v2["id"]),
        ("regenerated", "regenerate_quality", v2["id"]),
        ("edited", "crop", v2["id"]),
        ("rejected", "delete", v1["id"]),
        ("validated", "qc_override", v2["id"]),
        ("rejected", "annotate", v2["id"]),
        ("validated", "validate_sketch", sk["id"]),
        ("regenerated", "resketch", sk["id"]),
    ]
    # Chaque événement est lié à la génération qui a produit l'image (même supprimée).
    assert all(e.log_id == logs[e.image_id].id for e in _events(c))
    assert all(e.panel_id in (p1["id"], p2["id"]) for e in _events(c))
    assert logs[v1["id"]].status == "succeeded"  # la ligne du journal survit à la suppression


def test_repair_angle_and_reference_actions_record_verdicts(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p2 = data["panels"][1]
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
    [v1] = _images(c, p2["id"])
    mask = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(mask).rectangle((10, 10, 30, 30), fill=(255, 255, 255, 255))
    mask_png = "data:image/png;base64," + base64.b64encode(_png(mask)).decode()
    _ok(c.post(f"/panel-images/{v1['id']}/repair", json={"mask_png": mask_png}), 202)
    _wait(c)
    angle = REG.camera_loras.angles[0].id
    _ok(c.post(f"/panels/{p2['id']}/change-angle", json={"angle": angle, "source_image_id": v1["id"]}), 202)
    _wait(c)
    aiko = data["aiko"]
    _ok(c.post(f"/characters/{aiko['id']}/reference-variants", json={"sheet": "personnage-portrait", "count": 2}), 202)
    _wait(c)
    variants = [r for r in _logs(c) if r.kind == "reference_sheet"]
    keep, drop = variants[0].image_id, variants[1].image_id
    _ok(c.post(f"/reference-variants/{keep}/keep"), 201)
    assert c.delete(f"/reference-variants/{drop}").status_code == 204
    got = [(e.verdict, e.action, e.image_kind, e.image_id) for e in _events(c)]
    assert got == [
        ("edited", "repair", "panel_image", v1["id"]),
        ("edited", "change_angle", "panel_image", v1["id"]),
        ("validated", "keep", "reference_variant", keep),
        ("rejected", "delete", "reference_variant", drop),
    ]
    assert [r.kind for r in _logs(c) if r.panel_id == p2["id"]] == ["panel", "inpaint", "angle"]


def test_one_click_verdict_with_reason_and_journal(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    [v1] = _images(c, p1["id"])
    out = _ok(
        c.post(
            f"/panel-images/{v1['id']}/verdict", json={"verdict": "rejected", "reason": "visage-rate", "note": " yeux "}
        ),
        201,
    )["log"]
    assert out["verdict"] == "rejected" and out["kind"] == "panel" and out["image_id"] == v1["id"]
    [event] = out["events"]
    assert (event["verdict"], event["action"], event["reason"], event["reason_label"], event["note"]) == (
        "rejected",
        "judge",
        "visage-rate",
        "Visage raté",
        "yeux",
    )
    assert set(out["measures"]) == {"dark_pct", "black_pct", "white_pct", "saturation_pct", "line_density_pct"}
    assert out["gaps"]["dark_pct"] == pytest.approx(out["measures"]["dark_pct"] - 21.7, abs=0.011)
    assert out["gaps"]["white_pct"] is None
    # Changer d'avis : un verdict de plus, le dernier compte ; la version choisie ne change pas.
    out = _ok(c.post(f"/panel-images/{v1['id']}/verdict", json={"verdict": "validated"}), 201)["log"]
    assert out["verdict"] == "validated" and len(out["events"]) == 2
    assert _ok(c.get(f"/panel-images/{v1['id']}/journal"))["log"]["verdict"] == "validated"
    # Raison hors liste : refusée.
    bad = c.post(f"/panel-images/{v1['id']}/verdict", json={"verdict": "rejected", "reason": "moche"})
    assert bad.status_code == 422 and "raison inconnue" in bad.text
    assert c.post(f"/panel-images/{v1['id']}/verdict", json={"verdict": "edited"}).status_code == 422
    settings = _ok(c.get("/journal/settings"))
    assert settings["reasons"][0] == {"id": "style-pas-manga", "label": "Style pas manga"}
    assert next(m for m in settings["measures"] if m["key"] == "black_pct")["target"] == 9.5


# --- export ------------------------------------------------------------------------------------------
def test_export_csv_and_json_with_filters(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1, p2, _ = data["panels"]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _ok(c.post(f"/panels/{p2['id']}/generate", json={"preset": "qwen-image-turbo"}), 202)
    _wait(c)
    [v1] = _images(c, p1["id"])
    _ok(c.post(f"/panel-images/{v1['id']}/verdict", json={"verdict": "rejected", "reason": "anatomie"}), 201)
    # Une autre série, un autre chapitre.
    other = _ok(c.post("/projects", json={"title": "Autre", **STYLE}), 201)
    ch = _ok(c.post(f"/projects/{other['id']}/chapters", json={"title": "Un"}), 201)
    pages = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "Mer"}]}]}))
    _ok(c.post(f"/panels/{pages[0]['panels'][0]['id']}/generate"), 202)
    _wait(c)

    res = c.get("/stats/export", params={"format": "json"})
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    rows = res.json()
    assert len(rows) == 3 and list(rows[0]) == list(EXPORT_COLUMNS)
    first = rows[0]
    assert first["verdict"] == "rejected" and first["verdict_reason"] == "anatomie" and first["dark_pct"] is not None
    assert first["prompt_length"] and isinstance(first["references"], list)

    res = c.get("/stats/export", params={"format": "csv", "project_id": data["series"]["id"]})
    assert res.headers["content-type"].startswith("text/csv")
    parsed = list(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert len(parsed) == 2 and list(parsed[0]) == list(EXPORT_COLUMNS)
    assert parsed[0]["verdict"] == "rejected" and json.loads(parsed[0]["loras"])
    assert parsed[1]["verdict"] == ""

    def count(**params: Any) -> int:
        return len(c.get("/stats/export", params={"format": "json", **params}).json())

    assert count(chapter_id=ch["id"]) == 1
    assert count(tier="Turbo") == 1
    assert count(date_from="2000-01-01", date_to="2999-12-31") == 3
    assert count(date_to="2000-01-01") == 0
    assert count(kind="croquis") == 0
    assert c.get("/stats/export", params={"format": "xml"}).status_code == 422
    assert c.get("/stats/export", params={"kind": "nimporte"}).status_code == 422
    assert c.get("/stats/export", params={"date_from": "2026-02-01", "date_to": "2026-01-01"}).status_code == 422


# --- A/B ----------------------------------------------------------------------------------------------
def test_ab_same_seed_both_arms_and_choice(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    p2 = data["panels"][1]
    start = _ok(c.post(f"/panels/{p2['id']}/ab", json={"mode": "prompt", "prompt_b": "Kenji runs, heavy ink"}), 202)
    current = _ok(c.get(f"/panels/{p2['id']}"))["final_prompt"]  # prompt de la case, figé pour le bras A
    a, b = start["jobs"]
    assert a["params"]["seed"] == b["params"]["seed"] == start["seed"]
    assert a["params"]["ab"] == {"group": start["group"], "arm": "A", "mode": "prompt"}
    _wait(c)
    [group] = _ok(c.get(f"/panels/{p2['id']}/ab"))
    assert group["group"] == start["group"] and not group["pending"] and group["choice"] is None
    arm_a, arm_b = group["arms"]
    assert arm_a["log"]["seed"] == arm_b["log"]["seed"] == start["seed"]
    assert arm_a["log"]["tier"] == arm_b["log"]["tier"]
    assert current in arm_a["log"]["positive_prompt"]
    assert "heavy ink" in arm_b["log"]["positive_prompt"] and "heavy ink" not in arm_a["log"]["positive_prompt"]
    assert arm_b["log"]["prompt_source"] == "variante" and arm_a["image"]["seed"] == start["seed"]
    # Le prompt de la case ne change pas.
    assert _ok(c.get(f"/panels/{p2['id']}"))["final_prompt"] == current

    out = _ok(c.post(f"/ab/{start['group']}/choice", json={"winner": "B", "reason": "style-pas-manga"}))
    assert out["choice"] == "B"
    events = [(e.log_id, e.verdict, e.action, e.reason) for e in _events(c)]
    assert events == [
        (arm_a["log"]["id"], "rejected", "ab_choice", "style-pas-manga"),
        (arm_b["log"]["id"], "validated", "ab_choice", None),
    ]
    imgs = {i["id"]: i for i in _images(c, p2["id"])}
    assert imgs[arm_b["image"]["id"]]["selected"]  # le bras retenu devient la version choisie


def test_ab_tier_and_cfg_modes(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p2 = data["panels"][1]
    start = _ok(
        c.post(
            f"/panels/{p2['id']}/ab", json={"mode": "tier", "presets": ["qwen-image-turbo", "qwen-image-base-qualite"]}
        ),
        202,
    )
    assert [j["params"]["preset"] for j in start["jobs"]] == ["qwen-image-turbo", "qwen-image-base-qualite"]
    _wait(c)
    start = _ok(c.post(f"/panels/{p2['id']}/ab", json={"mode": "cfg", "cfgs": [1.5, 3], "seed": 99}), 202)
    _wait(c)
    groups = _ok(c.get(f"/panels/{p2['id']}/ab"))
    assert [g["mode"] for g in groups] == ["cfg", "tier"]
    cfg_group = groups[0]
    assert [a["log"]["cfg"] for a in cfg_group["arms"]] == [1.5, 3]
    assert {a["log"]["seed"] for a in cfg_group["arms"]} == {99}
    assert [a["log"]["tier"] for a in groups[1]["arms"]] == ["Turbo", "Qualité"]
    # Erreurs lisibles.
    assert c.post(f"/panels/{p2['id']}/ab", json={"mode": "prompt", "prompt_b": ""}).status_code == 422
    assert c.post(f"/panels/{p2['id']}/ab", json={"mode": "cfg", "cfgs": [2, 2]}).status_code == 422
    assert c.post(f"/panels/{p2['id']}/ab", json={"mode": "tier", "presets": ["x", "y"]}).status_code == 422
    # Choix impossible tant qu'un bras manque.
    assert c.post("/ab/inconnu/choice", json={"winner": "A"}).status_code == 404


# --- statistiques -------------------------------------------------------------------------------------
def test_stats_breakdowns_sample_sizes_and_low_data(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    p1, p2, p3 = data["panels"]
    empty = _ok(c.get("/stats"))
    assert empty["total"]["generations"] == 0 and empty["low_data"] and empty["low_data_below"] == 20
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"count": 2}), 202)
    _ok(c.post(f"/panels/{p2['id']}/generate", json={"preset": "qwen-image-turbo"}), 202)
    _ok(c.post(f"/panels/{p3['id']}/generate"), 202)
    _wait(c)
    v1, v2 = _images(c, p1["id"])
    [w] = _images(c, p2["id"])
    _ok(c.post(f"/panel-images/{v1['id']}/verdict", json={"verdict": "validated"}), 201)
    _ok(c.post(f"/panel-images/{v2['id']}/verdict", json={"verdict": "rejected", "reason": "anatomie"}), 201)
    _ok(c.post(f"/panel-images/{w['id']}/verdict", json={"verdict": "validated"}), 201)

    stats = _ok(c.get("/stats"))
    total = stats["total"]
    assert (total["generations"], total["judged"], total["validated"], total["rejected"]) == (4, 3, 2, 1)
    assert total["validation_rate"] == pytest.approx(66.7) and total["low_data"] and stats["low_data"]
    assert total["means"]["dark_pct"] is not None
    keys = [b["key"] for b in stats["breakdowns"]]
    assert keys == ["tier", "cfg", "framing", "knowledge", "prompt_length", "kind"]  # pas de finition : pas de ligne
    tiers = {r["value"]: r for r in next(b for b in stats["breakdowns"] if b["key"] == "tier")["rows"]}
    assert tiers["Turbo"]["generations"] == 1 and tiers["Turbo"]["validation_rate"] == 100
    assert sum(r["generations"] for r in tiers.values()) == 4 and all(r["low_data"] for r in tiers.values())
    framing = {r["value"]: r for r in next(b for b in stats["breakdowns"] if b["key"] == "framing")["rows"]}
    assert framing["plan large"]["judged"] == 2 and framing["plan large"]["validation_rate"] == 50
    knowledge = next(b for b in stats["breakdowns"] if b["key"] == "knowledge")["rows"]
    assert [r["value"] for r in knowledge] == ["Aucune fiche"]
    # Filtres.
    assert _ok(c.get("/stats", params={"tier": "Turbo"}))["total"]["generations"] == 1
    assert _ok(c.get("/stats", params={"project_id": 999}))["total"]["generations"] == 0


def test_stats_without_low_data_warning(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    c.app.state.ctx.presets.journal.low_data_below = 2  # type: ignore[attr-defined]
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"count": 2}), 202)
    _wait(c)
    for img in _images(c, p1["id"]):
        _ok(c.post(f"/panel-images/{img['id']}/verdict", json={"verdict": "validated"}), 201)
    stats = _ok(c.get("/stats"))
    assert not stats["low_data"] and stats["total"]["validation_rate"] == 100


# --- migration ------------------------------------------------------------------------------------------
def test_v28_database_gets_the_journal_without_loss(make_settings: Callable[..., Settings]) -> None:
    """v28 → v29 : tables du journal créées, vides ; séries, cases et versions existantes intactes."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        s = c.post("/projects", json={**STYLE, "title": "Ancienne"}).json()
        ch = c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}).json()
        pages = c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "Aiko"}]}]}).json()
        pid = pages[0]["panels"][0]["id"]
        aiko = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
        _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    con = sqlite3.connect(settings.database_path)
    con.execute("DROP TABLE generation_events")
    con.execute("DROP TABLE generation_logs")
    con.execute("PRAGMA user_version = 28")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        panel = c.get(f"/panels/{pid}").json()
        assert panel["description"] == "Aiko"
        assert c.get("/stats").json()["total"]["generations"] == 0
        assert c.get("/stats/export", params={"format": "json"}).json() == []
        assert c.get(f"/projects/{s['id']}/characters").json()[0]["name"] == "Aiko"
    con = sqlite3.connect(settings.database_path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 29
    con.close()
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
