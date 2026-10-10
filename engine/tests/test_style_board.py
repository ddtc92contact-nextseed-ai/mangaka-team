"""Planche de style : scène test du genre (preset), 4 essais au palier croquis, choix → référence de style
(SeriesAsset `style`, une seule active), jointe aux fiches de référence et aux cases (emplacement libre),
série sans planche inchangée. ComfyUI en mock."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import pick_references
from mangaka_engine.pipeline.style import series_style
from mangaka_engine.presets import PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.models import (
    AssetKind,
    Character,
    CharacterImage,
    PanelImage,
    Project,
    SeriesAsset,
    SeriesAssetImage,
)
from tests.conftest import PRESETS_DIR, STYLE, png_bytes

REG = PresetRegistry.load(PRESETS_DIR)
SKETCH = REG.defaults.workflow_sketch  # type: ignore[union-attr]


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _providers(comfy: MockComfyUIClient | None) -> Providers:
    return Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=comfy,
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={} if comfy is not None else {"comfyui": "connexion refusée"},
    )


@pytest.fixture
def comfy() -> MockComfyUIClient:
    return MockComfyUIClient()


@pytest.fixture
def c(make_settings: Callable[..., Settings], comfy: MockComfyUIClient) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(), providers=_providers(comfy))) as client:
        yield client


def _idle(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(15)  # type: ignore[attr-defined]


def _series(c: TestClient, **extra: Any) -> dict[str, Any]:
    return _ok(c.post("/projects", json={**STYLE, "title": "Robo Lycée", **extra}), 201)


def _board(c: TestClient, series_id: int) -> dict[str, Any]:
    return _ok(c.get(f"/projects/{series_id}/style-board"))


def _make_style_reference(c: TestClient, series_id: int, trial_index: int = 0) -> dict[str, Any]:
    _ok(c.post(f"/projects/{series_id}/style-board/trials"), 202)
    _idle(c)
    trial = _board(c, series_id)["trials"][trial_index]
    _ok(c.post(f"/style-trials/{trial['id']}/choose"), 202)
    _idle(c)
    active = _board(c, series_id)["active"]
    assert active is not None
    return active


def _project(c: TestClient, series_id: int) -> Project:
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        project = session.get(Project, series_id)
        assert project is not None
        session.expunge(project)
        return project


# --- presets : la scène test vient du genre --------------------------------------------
def test_every_genre_has_a_french_scene_test() -> None:
    assert REG.style_genres and not [i for i in REG.issues if i.file.startswith("style_genres")]
    for genre in REG.style_genres.values():
        assert len(genre.scene_test) > 30, genre.id
    settings = REG.defaults.style_board  # type: ignore[union-attr]
    assert settings is not None and settings.trials == 4
    assert (settings.reference_sheets, settings.panels) == ("with_subject", "with_subject")


def test_a_genre_without_scene_test_is_refused_at_load(tmp_path: Path) -> None:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    path = root / "style_genres" / "seinen.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["scene_test"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(root)
    assert "seinen" not in reg.style_genres and "shonen" in reg.style_genres
    [issue] = [i for i in reg.issues if i.file == "style_genres/seinen.yaml"]
    assert "scene_test" in issue.message


def test_a_style_board_prompt_with_unknown_variables_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    path = root / "defaults.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["style_board"]["prompt"] = ["Scène : $scene, héros : $name."]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(root)
    assert any("variables inconnues : name" in i.message for i in reg.issues if i.file == "defaults.yaml")


# --- essais ------------------------------------------------------------------------------
def test_four_sketch_trials_with_distinct_seeds_and_the_series_style(c: TestClient, comfy: MockComfyUIClient) -> None:
    s = _series(c, style_lora_name="encre-seinen_v2.safetensors")
    board = _board(c, s["id"])
    assert board["active"] is None and board["trials"] == [] and board["problem"] is None
    scene = REG.style_genres["shonen"].scene_test
    assert board["scene_test"] == scene and board["trials_per_batch"] == 4

    jobs = _ok(c.post(f"/projects/{s['id']}/style-board/trials"), 202)
    assert len(jobs) == 4 and all(j["step"] == "style_board" and j["status"] == "pending" for j in jobs)
    assert {j["params"]["preset"] for j in jobs} == {SKETCH}
    seeds = [j["params"]["seed"] for j in jobs]
    assert len(set(seeds)) == 4
    style = series_style(REG, _project(c, s["id"]))
    prompt = jobs[0]["params"]["prompt"]
    assert {j["params"]["prompt"] for j in jobs} == {prompt}
    assert f"scène test : {scene}." in prompt and f"Style : {style}." in prompt
    # Chaque essai est un job visible dans la file de production.
    queue = _ok(c.get("/queue"))
    labels = [i["label"] for i in ([queue["running"]] if queue["running"] else []) + queue["pending"]]
    assert all(label == "Robo Lycée · Planche de style · essai" for label in labels if "Planche" in label)
    _idle(c)

    sent = list(comfy.prompts.values())[-4:]
    assert sorted(wf["9"]["inputs"]["seed"] for wf in sent) == sorted(seeds)
    assert {wf["6"]["inputs"]["prompt"] for wf in sent} == {prompt}
    assert all("20" not in wf for wf in sent)  # aucune image de référence
    long_side = REG.workflow(SKETCH).preset.long_side
    assert {(wf["8"]["inputs"]["width"], wf["8"]["inputs"]["height"]) for wf in sent} == {(long_side, long_side)}
    loras = [n["inputs"]["lora_name"] for n in sent[0].values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert loras == ["encre-seinen_v2.safetensors"]

    board = _board(c, s["id"])
    assert board["active_jobs"] == []
    trials = board["trials"]
    assert len(trials) == 4 and {t["batch"] for t in trials} == {1}
    assert sorted(t["seed"] for t in trials) == sorted(seeds) and not any(t["chosen"] for t in trials)
    assert c.get(trials[0]["url"]).headers["content-type"] == "image/png"

    # « Relancer » : 4 autres essais, les premiers restent dans l'historique.
    again = _ok(c.post(f"/projects/{s['id']}/style-board/trials"), 202)
    assert {j["params"]["batch"] for j in again} == {2}
    _idle(c)
    assert len(_board(c, s["id"])["trials"]) == 8


def test_choosing_a_trial_cleans_it_and_makes_the_only_active_style_reference(
    c: TestClient, comfy: MockComfyUIClient
) -> None:
    s = _series(c)
    _ok(c.post(f"/projects/{s['id']}/style-board/trials"), 202)
    _idle(c)
    trials = _board(c, s["id"])["trials"]
    chosen = trials[2]
    job = _ok(c.post(f"/style-trials/{chosen['id']}/choose"), 202)
    clean_id = REG.workflow(s["workflow_preset"]).preset.from_sketch
    assert job["step"] == "style_board" and job["params"]["mode"] == "clean"
    assert job["params"]["preset"] == clean_id and job["params"]["seed"] == chosen["seed"]
    _idle(c)
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    wf = list(comfy.prompts.values())[-1]
    assert wf["9"]["inputs"]["seed"] == chosen["seed"] and wf["6"]["inputs"]["prompt"] == chosen["prompt"]
    assert wf["30"]["inputs"]["image"] in comfy.uploads  # l'essai retenu, image de composition

    board = _board(c, s["id"])
    first = board["active"]
    assert first["trial_id"] == chosen["id"] and first["active"] and not first["outdated"]
    assert (first["width"], first["height"]) == (1024, 1024)
    assert [t["chosen"] for t in board["trials"]] == [False, False, True, False]
    assert c.get(first["url"]).status_code == 200

    # Un autre choix : nouvelle référence active, l'ancienne passe dans l'historique.
    _ok(c.post(f"/style-trials/{trials[0]['id']}/choose"), 202)
    _idle(c)
    board = _board(c, s["id"])
    assert board["active"]["trial_id"] == trials[0]["id"]
    assert [(h["id"], h["active"]) for h in board["history"]] == [(first["id"], False)]
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        rows = session.scalars(select(SeriesAsset).where(SeriesAsset.kind == AssetKind.style)).all()
        assert sorted(a.active for a in rows) == [False, True]

    # Reprendre l'ancienne depuis l'historique.
    board = _ok(c.post(f"/style-references/{first['id']}/activate"))
    assert board["active"]["id"] == first["id"] and [h["active"] for h in board["history"]] == [False]
    # Les références de style ne sont ni des objets ni des décors.
    assert _ok(c.get(f"/projects/{s['id']}/objects")) == [] and _ok(c.get(f"/projects/{s['id']}/decors")) == []

    # Changer de pack : la référence est signalée comme d'un autre style.
    _ok(c.patch(f"/projects/{s['id']}", json={"style_tone": "dark"}))
    assert _board(c, s["id"])["active"]["outdated"] is True


def test_errors_series_without_pack_and_engine_offline(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(), providers=_providers(None))) as c:
        s = _series(c)
        off = c.post(f"/projects/{s['id']}/style-board/trials")
        assert off.status_code == 503 and "ComfyUI indisponible" in off.json()["detail"]
    with TestClient(create_app(make_settings(), providers=_providers(MockComfyUIClient()))) as c:
        s = _series(c)
        with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
            project = session.get(Project, s["id"])
            project.style_genre = project.style_rendering = project.style_tone = None
            session.commit()
        board = _board(c, s["id"])
        assert board["scene_test"] is None and "genre" in board["problem"]
        bad = c.post(f"/projects/{s['id']}/style-board/trials")
        assert bad.status_code == 409 and "genre" in bad.json()["detail"]
        assert c.post("/style-trials/999/choose").status_code == 404
        assert c.get("/projects/999/style-board").status_code == 404


# --- fiches de référence : la référence de style seulement après l'image du sujet -----------
STYLE_ROLE = "référence de style uniquement — trait, trames, encrage ; ne pas reprendre son personnage"


def _sheet_client(make_settings: Callable[..., Settings], tmp_path: Path, mode: str | None) -> TestClient:
    """Client dont `style_board.reference_sheets` vaut `mode` (None : presets du dépôt)."""
    if mode is None:
        return TestClient(create_app(make_settings(), providers=_providers(MockComfyUIClient())))
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    path = root / "defaults.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("reference_sheets: with_subject", f"reference_sheets: {mode}"),
        encoding="utf-8",
    )
    settings = make_settings(mangaka_presets_dir=root)
    return TestClient(create_app(settings, providers=_providers(MockComfyUIClient())))


def _dragon(c: TestClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Série avec une référence de style active et un personnage décrit, sans image."""
    s = _series(c)
    style = _make_style_reference(c, s["id"])
    entry = _ok(
        c.post(
            f"/projects/{s['id']}/characters",
            json={"name": "Petit dragon rondouillard", "visual_description": "petit dragon vert, ventre rond"},
        ),
        201,
    )
    return s, style, entry


def _sheet(c: TestClient, entry_id: int, **body: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    [job] = _ok(
        c.post(f"/characters/{entry_id}/reference-variants", json={"sheet": "personnage-portrait", "count": 1, **body}),
        202,
    )
    _idle(c)
    variant = _ok(c.get(f"/characters/{entry_id}/reference-variants"))["variants"][0]
    return job, variant


def test_defaults_join_style_only_with_a_subject() -> None:
    settings = REG.defaults.style_board  # type: ignore[union-attr]
    assert settings is not None and settings.reference_sheets == "with_subject"


def test_sheet_from_scratch_is_text_to_image_despite_the_style_board(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    with _sheet_client(make_settings, tmp_path, None) as c:
        s, _style, entry = _dragon(c)
        job, variant = _sheet(c, entry["id"])
        assert job["params"]["preset"] == s["workflow_preset"] == "qwen-image-turbo"
        assert job["params"]["style_asset_id"] is None and job["params"]["start_image_id"] is None
        assert variant["params"]["reference_images"] == []
        assert "petit dragon vert, ventre rond." in variant["prompt"]
        assert "Image de départ" not in variant["prompt"] and "Dernière image" not in variant["prompt"]
        sent = list(c.app.state.ctx.providers.comfyui.prompts.values())[-1]  # type: ignore[attr-defined]
        assert not [n for n in sent.values() if n["class_type"] == "LoadImage"]


def test_starting_image_then_style_reference(make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    with _sheet_client(make_settings, tmp_path, None) as c:
        _s, style, entry = _dragon(c)
        updated = _ok(
            c.post(f"/characters/{entry['id']}/images", files=[("files", ("croquis.png", png_bytes(), "image/png"))]),
            201,
        )
        sketch = updated["reference_images"][0]
        job, variant = _sheet(c, entry["id"], start_image_id=sketch["id"])
        assert job["params"]["preset"] == "qwen-image-edit-ref-turbo"
        assert job["params"]["start_image_id"] == sketch["id"] and job["params"]["style_asset_id"] == style["id"]
        refs = variant["params"]["reference_images"]
        assert [r["kind"] for r in refs] == ["start", "style"]
        assert refs[0]["image_id"] == sketch["id"] and refs[1]["asset_id"] == style["id"]
        assert "Image de départ (image 1) : garder le sujet, sa silhouette et sa pose" in variant["prompt"]
        assert f"Dernière image (image 2) : {STYLE_ROLE}" in variant["prompt"]
        assert "petit dragon vert, ventre rond." in variant["prompt"]
        wf = list(c.app.state.ctx.providers.comfyui.prompts.values())[-1]  # type: ignore[attr-defined]
        assert wf["20"]["inputs"]["image"] == refs[0]["comfyui_name"]
        assert wf["21"]["inputs"]["image"] == refs[1]["comfyui_name"] and "22" not in wf

        # « Affiner » : la variante en image 1, puis la référence de style.
        _ok(c.post(f"/reference-variants/{variant['id']}/refine", json={"instruction": "plus sombre", "count": 1}), 202)
        _idle(c)
        refined = _ok(c.get(f"/characters/{entry['id']}/reference-variants"))["variants"][0]
        assert [r["kind"] for r in refined["params"]["reference_images"]] == ["variant", "style"]
        assert f"Dernière image (image 2) : {STYLE_ROLE}" in refined["prompt"]
        assert "Image de départ" not in refined["prompt"]

        # Une image d'une autre fiche n'est pas une image de départ.
        other = _ok(c.post(f"/projects/{_s['id']}/characters", json={"name": "Autre", "visual_description": "x"}), 201)
        bad = c.post(
            f"/characters/{other['id']}/reference-variants",
            json={"sheet": "personnage-portrait", "count": 1, "start_image_id": sketch["id"]},
        )
        assert bad.status_code == 422 and "image de départ" in bad.text


def test_starting_image_without_style_board(make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    with _sheet_client(make_settings, tmp_path, None) as c:
        s = _series(c)
        entry = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko", "visual_description": "x"}), 201)
        updated = _ok(
            c.post(f"/characters/{entry['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201
        )
        _job, variant = _sheet(c, entry["id"], start_image_id=updated["reference_images"][0]["id"])
        assert [r["kind"] for r in variant["params"]["reference_images"]] == ["start"]
        assert "Dernière image" not in variant["prompt"]


@pytest.mark.parametrize(
    ("mode", "scratch", "with_start", "refine"),
    [
        ("never", [], ["start"], ["variant"]),
        ("always", ["style"], ["start", "style"], ["variant", "style"]),
    ],
)
def test_reference_sheets_setting_never_and_always(
    make_settings: Callable[..., Settings],
    tmp_path: Path,
    mode: str,
    scratch: list[str],
    with_start: list[str],
    refine: list[str],
) -> None:
    with _sheet_client(make_settings, tmp_path, mode) as c:
        s, style, entry = _dragon(c)
        job, variant = _sheet(c, entry["id"])
        kinds = [r["kind"] for r in variant["params"]["reference_images"]]
        assert kinds == scratch
        if mode == "always":  # comportement d'avant : la référence de style seule, workflow « avec références »
            assert (
                job["params"]["preset"] == "qwen-image-edit-ref-turbo"
                and job["params"]["style_asset_id"] == style["id"]
            )
            assert f"Dernière image (image 1) : {STYLE_ROLE}" in variant["prompt"]
        else:
            assert job["params"]["preset"] == s["workflow_preset"] and "Dernière image" not in variant["prompt"]
        _ok(c.post(f"/reference-variants/{variant['id']}/refine", json={"instruction": "plus sombre", "count": 1}), 202)
        _idle(c)
        refined = _ok(c.get(f"/characters/{entry['id']}/reference-variants"))["variants"][0]
        assert [r["kind"] for r in refined["params"]["reference_images"]] == refine
        updated = _ok(
            c.post(f"/characters/{entry['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201
        )
        _job, started = _sheet(c, entry["id"], start_image_id=updated["reference_images"][0]["id"])
        assert [r["kind"] for r in started["params"]["reference_images"]] == with_start


# --- cases : seulement s'il reste un emplacement libre, jamais seule ------------------------
@pytest.mark.parametrize(("images", "taken"), [(0, 0), (1, 1), (3, 1)])
def test_style_reference_takes_a_free_panel_slot_only(c: TestClient, images: int, taken: int) -> None:
    """with_subject : jamais la seule image (case sans référence → workflow texte, sans style) ;
    principale : une image par fiche, même si la fiche en a trois."""
    s = _series(c)
    style = _make_style_reference(c, s["id"])
    panel_body: dict[str, Any] = {"description": "Une case"}
    if images:
        char = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
        files = [("files", (f"{i}.png", png_bytes(), "image/png")) for i in range(images)]
        _ok(c.post(f"/characters/{char['id']}/images", files=files), 201)
        panel_body["characters"] = ["Aiko"]
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel_body]}]}))
    [job] = _ok(c.post(f"/panels/{page['panels'][0]['id']}/generate"), 202)
    _idle(c)
    used = _ok(c.get(f"/jobs/{job['id']}"))["params"]["references"]
    if not images:
        assert job["params"]["preset"] == s["workflow_preset"] and used == []  # texte → image, sans style
        return
    assert job["params"]["preset"] == "qwen-image-edit-ref-turbo"  # workflow à références existant
    assert [r["kind"] for r in used] == ["character"] * taken + ["style"]
    assert used[-1]["id"] == style["id"] and used[-1]["slot"] == taken + 1


def test_pick_references_puts_style_last_after_every_other_image() -> None:
    def char(i: int, n: int) -> Character:
        return Character(id=i, name=f"P{i}", reference_images=[CharacterImage(id=i * 10 + k) for k in range(n)])

    style = SeriesAsset(id=99, kind=AssetKind.style, name="Style", reference_images=[SeriesAssetImage(id=990)])
    decor = SeriesAsset(id=5, kind=AssetKind.decor, name="Labo", reference_images=[SeriesAssetImage(id=50)])
    # Le style ne passe pas devant la 2e image d'un personnage (priorité inchangée).
    picked = pick_references([char(1, 2), style], 3)
    assert [img.id for _, img in picked] == [10, 11, 990]
    picked = pick_references([char(1, 2), decor, style], 3)
    assert [img.id for _, img in picked] == [10, 50, 11]
    assert [img.id for _, img in pick_references([style], 3)] == [990]
    assert pick_references([style], 0) == []
    # `principale` : une seule image par fiche (la 1re), le style prend la place libre.
    picked = pick_references([char(1, 3), char(2, 2), style], 3, "principale")
    assert [img.id for _, img in picked] == [10, 20, 990]


# --- série sans planche : graphes identiques à aujourd'hui ----------------------------------
def test_series_without_style_board_keeps_identical_graphs(c: TestClient, comfy: MockComfyUIClient) -> None:
    s = _series(c)
    other = _series(c)
    _make_style_reference(c, other["id"])  # une autre série a sa planche : sans effet ici
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "Une case"}]}]}))
    panel_id = page["panels"][0]["id"]
    [job] = _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    assert job["params"]["preset"] == s["workflow_preset"]
    _idle(c)
    sent = list(comfy.prompts.values())[-1]
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        image = session.scalars(select(PanelImage).where(PanelImage.panel_id == panel_id)).one()
        params = dict(image.params)
    assert params["reference_images"] == []
    loaded = REG.workflow(s["workflow_preset"])
    assert sent == build_workflow(loaded, params["workflow_params"]).workflow

    entry = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "Le labo", "visual_description": "x"}), 201)
    [job] = _ok(
        c.post(f"/decors/{entry['id']}/reference-variants", json={"sheet": "decor-plan-large", "count": 1}), 202
    )
    assert job["params"]["preset"] == s["workflow_preset"] and job["params"]["style_asset_id"] is None
    _idle(c)
    sent = list(comfy.prompts.values())[-1]
    assert not [n for n in sent.values() if n["class_type"] == "LoadImage"]
