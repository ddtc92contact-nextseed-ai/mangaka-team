"""« Créer des références » : types de fiches (presets), construction du workflow, parcours en mock
(générer 4 variantes, affiner, garder, réordonner, utilisé par les cases), historique, migration."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import GenerationError
from mangaka_engine.pipeline.reference_sheets import (
    MAX_KEPT,
    sheet_loras,
    sheet_params,
    sheet_preset_id,
    sheet_prompt,
)
from mangaka_engine.presets import PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.models import AssetKind, Character, Project, SeriesAsset
from tests.conftest import PRESETS_DIR, png_bytes
from tests.test_migrations import _columns

REG = PresetRegistry.load(PRESETS_DIR)
SHEETS_DIR = PRESETS_DIR / "reference_sheets"
SEGMENTS = {"character": "characters", "object": "objects", "decor": "decors"}


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


# --- presets : des fichiers, jamais du code ---------------------------------------------
def test_every_sheet_preset_file_loads_and_builds_a_workflow() -> None:
    files = sorted(SHEETS_DIR.glob("*.y*ml"))
    assert len(files) >= 6
    assert not [i for i in REG.issues if i.file.startswith("reference_sheets")], REG.issues
    ids = [yaml.safe_load(f.read_text(encoding="utf-8"))["id"] for f in files]
    assert sorted(ids) == sorted(REG.reference_sheets)
    for kind in ("character", "object", "decor"):
        assert any(kind in s.kinds for s in REG.reference_sheets.values()), kind
    names = {s.name for s in REG.reference_sheets.values()}
    assert {"Portrait de face", "Plein pied face / profil / dos (turnaround)", "Expressions"} <= names
    assert {"Vue 3/4 + détails", "Plan large", "Autre angle"} <= names

    series = Project(title="S", style="encre", page_format="a4-300dpi", workflow_preset="qwen-image-turbo")
    for sheet in REG.reference_sheets.values():
        entry = _entry(sheet.kinds[0])
        for refine in (False, True):
            loaded = REG.workflow(sheet_preset_id(REG, sheet, series, refine=refine))
            prompt = sheet_prompt(sheet, entry, series, "plus grand" if refine else "")
            built = build_workflow(
                loaded,
                sheet_params(loaded, sheet, prompt, REG, seed=1),
                reference_images=["mangaka/v.png"] if refine else [],
            )
            assert (built.params["width"], built.params["height"]) == (sheet.width, sheet.height), sheet.id
            assert entry.name in built.params["positive_prompt"], sheet.id


def test_a_new_sheet_type_is_a_file_and_bad_files_are_reported(tmp_path: Path) -> None:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    folder = root / "reference_sheets"
    (folder / "objet-eclate.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "objet-eclate",
                "name": "Vue éclatée",
                "kinds": ["object"],
                "prompt": ["Vue éclatée de $name.", "$description."],
                "width": 1024,
                "height": 768,
                "workflow": "qwen-image-base",
            }
        ),
        encoding="utf-8",
    )
    bad = {"id": "x", "name": "X", "kinds": ["character"], "width": 1024, "height": 1024}
    (folder / "z-variable.yaml").write_text(yaml.safe_dump({**bad, "id": "z1", "prompt": ["$visage"]}))
    (folder / "z-workflow.yaml").write_text(yaml.safe_dump({**bad, "id": "z2", "prompt": ["$name"], "workflow": "?"}))
    (folder / "z-sorte.yaml").write_text(yaml.safe_dump({**bad, "id": "z3", "prompt": ["$name"], "kinds": ["lieu"]}))
    (folder / "z-taille.yaml").write_text(yaml.safe_dump({**bad, "id": "z4", "prompt": ["$name"], "width": 1001}))

    reg = PresetRegistry.load(root)
    assert reg.reference_sheet("objet-eclate").workflow == "qwen-image-base"
    problems = {i.file: i.message for i in reg.issues if i.file.startswith("reference_sheets")}
    assert "variables inconnues : visage" in problems["reference_sheets/z-variable.yaml"]
    assert "workflow inconnu" in problems["reference_sheets/z-workflow.yaml"]
    assert "kinds" in problems["reference_sheets/z-sorte.yaml"]
    assert "width" in problems["reference_sheets/z-taille.yaml"]
    assert not {"z1", "z2", "z3", "z4"} & set(reg.reference_sheets)


def test_sheets_are_listed_per_kind(c: TestClient) -> None:
    sheets = _ok(c.get("/presets/reference-sheets", params={"kind": "decor"}))
    assert [s["name"] for s in sheets] == ["Plan large", "Autre angle"]
    assert {s["id"] for s in _ok(c.get("/presets/reference-sheets"))} == set(REG.reference_sheets)


# --- construction du workflow ---------------------------------------------------------------
def _entry(kind: str, **overrides: Any) -> Character | SeriesAsset:
    values: dict[str, Any] = {
        "id": 7,
        "project_id": 1,
        "name": "Aiko",
        "visual_description": "jeune femme, cheveux noirs courts, kimono rouge",
        "prompt_keywords": ["katana", "cicatrice"],
        "lora_name": None,
        "lora_weight": 0.8,
        "lora_trigger_words": "",
        **overrides,
    }
    if kind == "character":
        return Character(**values)
    return SeriesAsset(kind=AssetKind(kind), **values)


def _series(**overrides: Any) -> Project:
    values: dict[str, Any] = {
        "title": "Robo Lycée",
        "style": "shōnen lumineux",
        "page_format": "a4-300dpi",
        "workflow_preset": "qwen-image-turbo",
        "style_lora_name": None,
        "style_lora_weight": 0.8,
        "style_lora_trigger_words": "",
        **overrides,
    }
    return Project(**values)


def test_sheet_builds_prompt_size_and_lora_chain() -> None:
    sheet = REG.reference_sheet("personnage-portrait")
    entry = _entry("character", lora_name="aiko_v1.safetensors", lora_weight=0.7, lora_trigger_words="aiko_v1")
    series = _series(style_lora_name="encre.safetensors", style_lora_weight=0.6, style_lora_trigger_words="inkstyle")
    prompt = sheet_prompt(sheet, entry, series)
    assert prompt.startswith("Fiche de référence de personnage : portrait de face de Aiko")
    assert "jeune femme, cheveux noirs courts, kimono rouge." in prompt
    assert "Détails : katana, cicatrice, aiko_v1." in prompt
    assert "Style : inkstyle, shōnen lumineux." in prompt
    assert "Modification demandée" not in prompt  # pas de consigne : morceau omis

    preset_id = sheet_preset_id(REG, sheet, series)
    assert preset_id == "qwen-image-turbo"  # palier de la série
    loaded = REG.workflow(preset_id)
    loras = sheet_loras(series, entry)
    assert [(lo.name, lo.weight, lo.source) for lo in loras] == [
        ("encre.safetensors", 0.6, "style"),
        ("aiko_v1.safetensors", 0.7, "Aiko"),
    ]
    built = build_workflow(loaded, sheet_params(loaded, sheet, prompt, REG, seed=42), loras=loras)
    wf = built.workflow
    assert wf["8"]["inputs"]["width"] == 1024 and wf["8"]["inputs"]["height"] == 1024
    assert wf["6"]["inputs"]["prompt"] == prompt
    assert "plusieurs personnages" in wf["6"]["inputs"]["negative_prompt"]  # négatif du type de fiche
    assert "texte" in wf["6"]["inputs"]["negative_prompt"]  # toujours : jamais de texte dessiné
    chain = [n for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert [n["inputs"]["lora_name"] for n in chain] == ["encre.safetensors", "aiko_v1.safetensors"]
    assert chain[0]["inputs"]["model"] == ["1", 0]  # style d'abord, branché sur le modèle
    assert built.reference_images == [] and "20" not in wf  # aucune image de référence


def test_sheet_without_lora_or_style_keeps_a_clean_prompt() -> None:
    sheet = REG.reference_sheet("decor-plan-large")
    entry = _entry("decor", name="Le labo", visual_description="", prompt_keywords=[])
    prompt = sheet_prompt(sheet, entry, _series(style=""))
    assert "Le labo en plan large" in prompt and "Détails" not in prompt and "Style" not in prompt
    assert sheet_loras(_series(), entry) == []
    loaded = REG.workflow(sheet_preset_id(REG, sheet, _series()))
    built = build_workflow(loaded, sheet_params(loaded, sheet, prompt, REG, seed=1))
    assert (built.workflow["8"]["inputs"]["width"], built.workflow["8"]["inputs"]["height"]) == (1536, 864)
    assert not [n for n in built.workflow.values() if n["class_type"] == "LoraLoaderModelOnly"]


def test_refine_uses_the_variant_as_reference_with_the_instruction() -> None:
    sheet = REG.reference_sheet("personnage-portrait")
    series = _series(style_lora_name="encre.safetensors")
    entry = _entry("character", lora_name="aiko_v1.safetensors")
    preset_id = sheet_preset_id(REG, sheet, series, refine=True)
    assert preset_id == "qwen-image-edit-ref-turbo"  # pendant « avec références » du palier de la série
    loaded = REG.workflow(preset_id)
    prompt = sheet_prompt(sheet, entry, series, "cheveux plus courts")
    assert "Modification demandée : cheveux plus courts." in prompt
    built = build_workflow(
        loaded,
        sheet_params(loaded, sheet, prompt, REG, seed=3),
        reference_images=["mangaka/personnage7_variante12.png"],
        loras=sheet_loras(series, entry),
    )
    wf = built.workflow
    assert wf["20"]["inputs"]["image"] == "mangaka/personnage7_variante12.png"
    assert wf["6"]["inputs"]["images.image_1"] == ["20", 0]
    assert "21" not in wf and "22" not in wf  # emplacements inutilisés retirés
    assert [n["inputs"]["lora_name"] for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"] == [
        "encre.safetensors",
        "aiko_v1.safetensors",
    ]


def test_quality_tier_and_imposed_workflow() -> None:
    sheet = REG.reference_sheet("objet-trois-quarts")
    series = _series(workflow_preset="qwen-image-base-rapide")
    assert sheet_preset_id(REG, sheet, series) == "qwen-image-base-rapide"
    quality = REG.defaults.workflow_quality  # type: ignore[union-attr]
    assert sheet_preset_id(REG, sheet, series, quality=True) == quality
    assert (
        sheet_preset_id(REG, sheet, series, quality=True, refine=True) == REG.workflow(quality).preset.with_references
    )
    imposed = sheet.model_copy(update={"workflow": "qwen-image-base"})
    assert sheet_preset_id(REG, imposed, series, quality=False) == "qwen-image-base"
    no_pair = REG.workflow("qwen-image-base").preset.model_copy(update={"with_references": None})
    reg = PresetRegistry(root=REG.root, workflows={**REG.workflows}, defaults=None)
    reg.workflows["qwen-image-base"] = REG.workflow("qwen-image-base").__class__(
        preset=no_pair, workflow=REG.workflow("qwen-image-base").workflow, source=REG.workflow("qwen-image-base").source
    )
    with pytest.raises(GenerationError, match="Affiner"):
        sheet_preset_id(reg, imposed, series, refine=True)


# --- parcours complet en mock --------------------------------------------------------------
def _create_entry(c: TestClient, kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    s = _ok(
        c.post(
            "/projects",
            json={"title": "Robo Lycée", "style": "Shōnen lumineux", "style_lora_name": "encre-seinen_v2.safetensors"},
        ),
        201,
    )
    names = {"character": "Aiko", "object": "Robot R-2", "decor": "Le labo"}
    entry = _ok(
        c.post(
            f"/projects/{s['id']}/{SEGMENTS[kind]}",
            json={"name": names[kind], "visual_description": "description visuelle", "lora_name": "lora.safetensors"},
        ),
        201,
    )
    return s, entry


FIRST_SHEET = {"character": "personnage-portrait", "object": "objet-trois-quarts", "decor": "decor-plan-large"}


@pytest.mark.parametrize("kind", ["character", "object", "decor"])
def test_generate_refine_keep_reorder_then_used_by_panels(c: TestClient, comfy: MockComfyUIClient, kind: str) -> None:
    segment = SEGMENTS[kind]
    s, entry = _create_entry(c, kind)
    eid = entry["id"]

    jobs = _ok(c.post(f"/{segment}/{eid}/reference-variants", json={"sheet": FIRST_SHEET[kind]}), 202)
    assert len(jobs) == 4  # 4 variantes par défaut
    assert all(j["step"] == "reference" and j["status"] == "pending" for j in jobs)
    assert [j["params"]["variant"] for j in jobs] == [1, 2, 3, 4]
    assert jobs[0]["params"]["preset"] == "qwen-image-turbo" and jobs[0]["params"]["tier"] == "Turbo"
    _idle(c)

    finished = [_ok(c.get(f"/jobs/{j['id']}")) for j in jobs]
    assert all(j["status"] == "succeeded" for j in finished), finished
    # Une variante par job, enregistrée dès la fin de son job (elles apparaissent une à une).
    variant_ids = [j["params"]["variant_id"] for j in finished]
    assert variant_ids == sorted(variant_ids) and len(set(variant_ids)) == 4
    studio = _ok(c.get(f"/{segment}/{eid}/reference-variants"))
    assert studio["active_jobs"] == [] and studio["max_kept"] == MAX_KEPT and studio["reference_slots"] == 3
    variants = studio["variants"]
    assert [v["id"] for v in variants] == variant_ids[::-1]  # plus récentes d'abord
    first = variants[-1]
    assert first["width"] == REG.reference_sheet(FIRST_SHEET[kind]).width and first["kept"] is False
    assert [lo["source"] for lo in first["params"]["loras"]] == ["style", entry["name"]]
    file = c.get(first["url"])
    assert file.status_code == 200 and file.headers["content-type"] == "image/png"

    # Affiner une variante : envoyée à ComfyUI comme image de référence, avec la consigne.
    refine = _ok(
        c.post(f"/reference-variants/{first['id']}/refine", json={"instruction": "plus de détails", "count": 1}), 202
    )
    assert refine[0]["params"]["preset"] == "qwen-image-edit-ref-turbo"
    assert refine[0]["params"]["parent_id"] == first["id"]
    _idle(c)
    refined = _ok(c.get(f"/{segment}/{eid}/reference-variants"))["variants"][0]
    assert refined["parent_id"] == first["id"] and refined["instruction"] == "plus de détails"
    assert "Modification demandée : plus de détails." in refined["prompt"]
    [sent] = refined["params"]["reference_images"]
    assert sent["variant_id"] == first["id"] and sent["comfyui_name"] in comfy.uploads
    wf = list(comfy.prompts.values())[-1]
    assert wf["20"]["inputs"]["image"] == sent["comfyui_name"]

    # Garder deux images ; la deuxième passe en tête (référence principale).
    kept = _ok(c.post(f"/reference-variants/{refined['id']}/keep"), 201)
    kept = _ok(c.post(f"/reference-variants/{variants[0]['id']}/keep"), 201)
    assert len(kept["reference_images"]) == 2
    again = c.post(f"/reference-variants/{refined['id']}/keep")
    assert again.status_code == 409 and "déjà gardée" in again.json()["detail"]
    ids = [img["id"] for img in kept["reference_images"]]
    reordered = _ok(c.put(f"/{segment}/{eid}/images/order", json={"image_ids": ids[::-1]}))
    assert [img["id"] for img in reordered["reference_images"]] == ids[::-1]
    assert c.put(f"/{segment}/{eid}/images/order", json={"image_ids": ids[:1]}).status_code == 422
    studio = _ok(c.get(f"/{segment}/{eid}/reference-variants"))
    assert sum(v["kept"] for v in studio["variants"]) == 2 and studio["kept_count"] == 2
    assert len(studio["variants"]) == 5  # les variantes non gardées restent dans l'historique

    # Une case qui cite la fiche est générée avec sa référence principale en premier.
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    panel_body: dict[str, Any] = {"description": "Une case"}
    if kind == "character":
        panel_body["characters"] = [entry["name"]]
    elif kind == "decor":
        panel_body["decor"] = eid
    else:
        panel_body["objets"] = [eid]
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel_body]}]}))
    panel_id = page["panels"][0]["id"]
    [job] = _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    _idle(c)
    used = _ok(c.get(f"/jobs/{job['id']}"))["params"]["references"]
    assert [(r["kind"], r["image_id"]) for r in used] == [(kind, ids[1]), (kind, ids[0])]


def test_cancel_a_pending_variant_and_queue_label(
    make_settings: Callable[..., Settings], comfy: MockComfyUIClient
) -> None:
    providers = Providers(llm=MockLLMProvider(), vision=None, comfyui=comfy, names={"comfyui": "mock"}, errors={})
    with TestClient(create_app(make_settings(), providers=providers)) as c:
        c.app.state.ctx.generation.shutdown()  # file à l'arrêt : les jobs restent en attente
        s, entry = _create_entry(c, "character")
        jobs = _ok(
            c.post(
                f"/characters/{entry['id']}/reference-variants", json={"sheet": "personnage-expressions", "count": 2}
            ),
            202,
        )
        queue = _ok(c.get("/queue"))
        assert [i["label"] for i in queue["pending"]] == [
            "Robo Lycée · Références · Aiko (personnage) · Expressions"
        ] * 2
        assert queue["pending"][0]["project_id"] == s["id"]
        studio = _ok(c.get(f"/characters/{entry['id']}/reference-variants"))
        assert [j["id"] for j in studio["active_jobs"]] == [j["id"] for j in jobs]
        cancelled = _ok(c.post(f"/jobs/{jobs[0]['id']}/cancel"))
        assert cancelled["status"] == "cancelled"
        assert len(_ok(c.get(f"/characters/{entry['id']}/reference-variants"))["active_jobs"]) == 1


def test_errors_are_readable(c: TestClient) -> None:
    _, entry = _create_entry(c, "object")
    bad = c.post(f"/objects/{entry['id']}/reference-variants", json={"sheet": "personnage-portrait"})
    assert bad.status_code == 422 and "ne s'applique pas à un objet" in bad.text
    assert c.post(f"/objects/{entry['id']}/reference-variants", json={"sheet": "inconnue"}).status_code == 422
    assert (
        c.post(
            f"/objects/{entry['id']}/reference-variants", json={"sheet": "objet-trois-quarts", "count": 5}
        ).status_code
        == 422
    )
    assert c.get("/decors/999/reference-variants").status_code == 404
    assert c.get(f"/decors/{entry['id']}/reference-variants").status_code == 404  # un objet n'est pas un décor
    assert c.post("/reference-variants/999/keep").status_code == 404


def test_quality_option_and_history_cleanup(c: TestClient) -> None:
    _, entry = _create_entry(c, "decor")
    [job] = _ok(
        c.post(
            f"/decors/{entry['id']}/reference-variants",
            json={"sheet": "decor-autre-angle", "count": 1, "quality": True},
        ),
        202,
    )
    assert job["params"]["preset"] == REG.defaults.workflow_quality  # type: ignore[union-attr]
    _idle(c)
    [variant] = _ok(c.get(f"/decors/{entry['id']}/reference-variants"))["variants"]
    assert variant["tier"] == "Qualité"
    data_dir: Path = c.app.state.ctx.settings.data_dir  # type: ignore[attr-defined]
    kept = _ok(c.post(f"/reference-variants/{variant['id']}/keep"), 201)
    # Supprimer la variante ne retire pas la référence gardée (copie).
    assert c.delete(f"/reference-variants/{variant['id']}").status_code == 204
    assert c.get(variant["url"]).status_code == 404
    assert c.get(kept["reference_images"][0]["url"]).status_code == 200

    [job] = _ok(
        c.post(f"/decors/{entry['id']}/reference-variants", json={"sheet": "decor-plan-large", "count": 1}), 202
    )
    _idle(c)
    [variant] = _ok(c.get(f"/decors/{entry['id']}/reference-variants"))["variants"]
    assert c.delete(f"/decors/{entry['id']}").status_code == 204
    assert c.get(variant["url"]).status_code == 404  # historique supprimé avec la fiche
    variants_dir = data_dir / "projects" / str(entry["project_id"]) / "decors" / str(entry["id"]) / "variantes"
    assert not any(variants_dir.glob("*")) if variants_dir.exists() else True


def test_a_deleted_variant_id_is_never_reused(c: TestClient) -> None:
    # /reference-variants/{id}/file est mis en cache « immutable » : un id recyclé servirait l'image supprimée.
    _, entry = _create_entry(c, "decor")
    url = f"/decors/{entry['id']}/reference-variants"
    _ok(c.post(url, json={"sheet": "decor-plan-large", "count": 1}), 202)
    _idle(c)
    [deleted] = _ok(c.get(url))["variants"]
    assert c.delete(f"/reference-variants/{deleted['id']}").status_code == 204  # la plus récente

    _ok(c.post(url, json={"sheet": "decor-autre-angle", "count": 1}), 202)
    _idle(c)
    [variant] = _ok(c.get(url))["variants"]
    assert variant["id"] > deleted["id"] and variant["url"] != deleted["url"]
    assert c.get(deleted["url"]).status_code == 404


def test_refine_with_a_sheet_of_another_kind_is_a_sheet_error(c: TestClient) -> None:
    _, entry = _create_entry(c, "object")
    _ok(c.post(f"/objects/{entry['id']}/reference-variants", json={"sheet": "objet-trois-quarts", "count": 1}), 202)
    _idle(c)
    [variant] = _ok(c.get(f"/objects/{entry['id']}/reference-variants"))["variants"]
    for sheet in ("personnage-portrait", "inconnue"):
        bad = c.post(f"/reference-variants/{variant['id']}/refine", json={"sheet": sheet, "instruction": "plus sombre"})
        assert bad.status_code == 422, bad.text
        assert [e["field"] for e in bad.json()["errors"]] == ["sheet"]


def test_max_kept_is_enforced(c: TestClient) -> None:
    _, entry = _create_entry(c, "character")
    files = [("files", (f"{i}.png", png_bytes(), "image/png")) for i in range(MAX_KEPT)]
    _ok(c.post(f"/characters/{entry['id']}/images", files=files), 201)
    more = c.post(f"/characters/{entry['id']}/images", files=[("files", ("x.png", png_bytes(), "image/png"))])
    assert more.status_code == 422 and f"{MAX_KEPT} images de référence au plus" in more.text
    _ok(c.post(f"/characters/{entry['id']}/reference-variants", json={"sheet": "personnage-portrait", "count": 1}), 202)
    _idle(c)
    [variant] = _ok(c.get(f"/characters/{entry['id']}/reference-variants"))["variants"]
    full = c.post(f"/reference-variants/{variant['id']}/keep")
    assert full.status_code == 409 and f"{MAX_KEPT} images de référence au plus" in full.json()["detail"]


def test_uploaded_images_keep_their_order_after_a_reorder(c: TestClient) -> None:
    _, entry = _create_entry(c, "object")
    files = [("files", (f"{i}.png", png_bytes(), "image/png")) for i in range(2)]
    ids = [i["id"] for i in _ok(c.post(f"/objects/{entry['id']}/images", files=files), 201)["reference_images"]]
    _ok(c.put(f"/objects/{entry['id']}/images/order", json={"image_ids": ids[::-1]}))
    up = _ok(c.post(f"/objects/{entry['id']}/images", files=[("files", ("c.png", png_bytes(), "image/png"))]), 201)
    assert [i["original_name"] for i in up["reference_images"]] == ["1.png", "0.png", "c.png"]  # ajoutée à la fin


# --- migration ------------------------------------------------------------------------------
def test_database_v11_keeps_reference_order(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    with TestClient(create_app(settings)) as client:
        _, entry = _create_entry(client, "character")
        files = [("files", (f"{i}.png", png_bytes(), "image/png")) for i in range(3)]
        _ok(client.post(f"/characters/{entry['id']}/images", files=files), 201)
    con = sqlite3.connect(settings.database_path)
    for table, column in [
        ("panels", "composition_lock"),  # v15 : verrouillage de composition
        ("projects", "clean_mode"),
        ("projects", "clean_control"),
        ("panel_images", "kind"),
        ("panels", "sketch_image_id"),
        ("panels", "sketch_denoise"),
        ("projects", "sketch_enabled"),
        ("projects", "sketch_denoise"),
    ]:  # colonnes du palier croquis (v14)
        con.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    con.execute("ALTER TABLE panel_images DROP COLUMN finish")  # v13 : finition d'impression
    con.execute("ALTER TABLE projects DROP COLUMN upscaler")
    con.execute("DROP TABLE reference_variants")
    con.execute("ALTER TABLE character_images DROP COLUMN position")
    con.execute("ALTER TABLE series_asset_images DROP COLUMN position")
    con.execute("PRAGMA user_version = 11")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as client:
        images = _ok(client.get(f"/characters/{entry['id']}"))["reference_images"]
        assert [i["original_name"] for i in images] == ["0.png", "1.png", "2.png"]
        assert _ok(client.get(f"/characters/{entry['id']}/reference-variants"))["variants"] == []
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
    for db in (settings.database_path, fresh):  # ids de variantes jamais réutilisés, migrée comme neuve
        con = sqlite3.connect(db)
        [(sql,)] = con.execute("SELECT sql FROM sqlite_master WHERE name = 'reference_variants'").fetchall()
        con.close()
        assert "AUTOINCREMENT" in sql
