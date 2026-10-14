"""Charte des couvertures d'une série (#171) : couleur, cohérence des personnages, cadrage et accroche, lus par la
génération de la 1re et de la petite illustration de 4e ; contrôle d'identité en avertissement."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.cover_charter import charter_format, colour_name, series_charter
from mangaka_engine.pipeline.covers import clear_zone_text
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.providers.qc.mock import MockDetectorProvider
from mangaka_engine.store.models import CoverCharter, Project
from tests.conftest import PRESETS_DIR, STYLE, png_bytes

REG = PresetRegistry.load(PRESETS_DIR)
CHARTER = REG.cover_charter
COVER = REG.cover
MANGA = "manga-13x18-300dpi"
PALETTE = {
    "name": "Braises",
    "explanation": "",
    "colors": [
        {"role": "dominante", "hex": "#1e3a8a"},
        {"role": "secondaire", "hex": "#334155"},
        {"role": "accent", "hex": "#f97316"},
        {"role": "fond", "hex": "#fef3c7"},
        {"role": "texte-clair", "hex": "#ffffff"},
        {"role": "texte-sombre", "hex": "#0f172a"},
    ],
}


class StubIdentity:
    """Identité « QC mock » réglable : similarité donnée par personnage (défaut 0,95)."""

    name = "stub"

    def __init__(self, sims: dict[str, float] | None = None) -> None:
        self.sims = sims or {}
        self.calls: list[dict[str, list[bytes]]] = []

    def compare(self, image: bytes, crops: Any, references: dict[str, list[bytes]], *, crop_scale: float) -> dict:
        self.calls.append(references)
        return {name: self.sims.get(name, 0.95) for name in references}


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def comfy() -> MockComfyUIClient:
    return MockComfyUIClient()


@pytest.fixture
def identity() -> StubIdentity:
    return StubIdentity()


@pytest.fixture
def c(make_settings: Callable[..., Settings], comfy: MockComfyUIClient, identity: StubIdentity) -> Iterator[TestClient]:
    providers = Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=comfy,
        detectors=MockDetectorProvider(),
        identity=identity,  # type: ignore[arg-type]
        names={"llm": "mock", "vision": "mock", "comfyui": "mock", "identity": "stub"},
        errors={},
    )
    with TestClient(create_app(make_settings(), providers=providers)) as client:
        yield client


def _idle(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(15)  # type: ignore[attr-defined]


def _character(c: TestClient, series_id: int, name: str, *, image: bool = True) -> dict[str, Any]:
    entry = _ok(
        c.post(f"/projects/{series_id}/characters", json={"name": name, "visual_description": "red scarf"}), 201
    )
    if image:
        _ok(c.post(f"/characters/{entry['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    return entry


def _setup(c: TestClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Série N&B à trames avec palette, trois personnages (Kaito, Rin avec image ; Mei sans) et un tome."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Lame de Kaito"}), 201)
    _ok(c.put(f"/projects/{s['id']}/identity/palette", json=PALETTE))
    kaito = _character(c, s["id"], "Kaito")
    rin = _character(c, s["id"], "Rin")
    mei = _character(c, s["id"], "Mei", image=False)
    v = _ok(c.post(f"/projects/{s['id']}/volumes", json={"title": "La ville en feu"}), 201)
    return s, v, kaito, rin, mei


def _generated(comfy: MockComfyUIClient, suffix: str) -> dict[str, Any]:
    wf = REG.workflow(COVER.workflow).preset  # type: ignore[union-attr]
    node = wf.mapping["filename_prefix"]
    return next(
        p
        for p in reversed(list(comfy.prompts.values()))
        if str(p.get(node.node, {}).get("inputs", {}).get(node.input, "")).endswith(suffix)
    )


def _positive(workflow: dict[str, Any]) -> str:
    m = REG.workflow(COVER.workflow).preset.mapping["positive_prompt"]  # type: ignore[union-attr]
    return str(workflow[m.node]["inputs"][m.input])


def _negative(workflow: dict[str, Any]) -> str:
    m = REG.workflow(COVER.workflow).preset.mapping["negative_prompt"]  # type: ignore[union-attr]
    return str(workflow[m.node]["inputs"][m.input])


def _loads(workflow: dict[str, Any]) -> list[str]:
    return [str(n["inputs"]["image"]) for n in workflow.values() if n.get("class_type") == "LoadImage"]


# --- presets ---------------------------------------------------------------------------------------------------
def test_charter_presets_load_with_bounded_choices() -> None:
    assert CHARTER is not None
    assert not [i for i in REG.issues if i.file.startswith("cover_charter")]
    assert {"imposee", "suggeree", "libre"} <= set(CHARTER.palette_modes)
    assert {"portrait", "plan-americain", "plan-ensemble"} <= set(CHARTER.shots)
    assert {"lumineuse", "sombre", "contrastee"} <= set(CHARTER.moods)
    # Toujours en couleur : aucune phrase de la charte ne parle de noir et blanc.
    phrases = [
        ch.prompt
        for group in (CHARTER.palette_modes, CHARTER.moods, CHARTER.shots, CHARTER.subjects)
        for ch in group.values()
    ]
    for text in phrases:
        assert not any(w in text.casefold() for w in ("black and white", "monochrome", "greyscale", "screentone"))


def test_unknown_default_or_variable_is_a_preset_issue(tmp_path: Path) -> None:
    import shutil

    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    data = yaml.safe_load((root / "cover_charter.yaml").read_text(encoding="utf-8"))
    data["defaults"]["shot"] = "contre-plongee"
    data["moods"]["sombre"]["prompt"] = "Dark $nowhere"
    (root / "cover_charter.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(root)
    assert reg.cover_charter is None
    issue = next(i for i in reg.issues if i.file.startswith("cover_charter"))
    assert "nowhere" in issue.message or "contre-plongee" in issue.message


def test_colour_names_are_readable() -> None:
    assert colour_name("#1e3a8a").endswith("blue")
    assert colour_name("#f97316").endswith("orange")
    assert colour_name("#ffffff") == "white" and colour_name("#000000") == "black"
    assert "grey" in colour_name("#808080")


def test_logo_band_moves_the_clear_zone_for_the_prompt() -> None:
    fmt = REG.cover_format(MANGA)
    series = Project(title="x", page_format="a", workflow_preset="b", palette=None)
    charter = series_charter(REG, series)
    assert charter is not None and charter_format(fmt, charter) is fmt  # zone du format par défaut
    charter.values["logo_place"] = "bas"
    moved = charter_format(fmt, charter)
    zone = moved.clear_zone
    assert zone is not None and zone.y_mm > fmt.height_mm / 2
    author = next(z for z in fmt.zones if z.id == "auteur")
    assert zone.y_mm + zone.height_mm <= author.y_mm + 1e-6
    assert clear_zone_text(moved).startswith("the bottom")
    assert [z.id for z in moved.zones].count("logo") == 1
    charter.values["logo_place"] = "haut"
    assert clear_zone_text(charter_format(fmt, charter)).startswith("the top")


# --- API : réglages ---------------------------------------------------------------------------------------------
def test_charter_defaults_save_validate_and_reset(c: TestClient) -> None:
    s, v, kaito, rin, mei = _setup(c)
    out = _ok(c.get(f"/projects/{s['id']}/cover-charter"))
    assert out["available"] and not out["saved"] and out["values"] == CHARTER.defaults.model_dump()  # type: ignore[union-attr]
    assert out["monochrome_series"] and out["palette_name"] == "Braises"
    # Rôles de texte de la palette jamais envoyés à l'illustration.
    assert {p["role"] for p in out["palette"] if not p["sent"]} == {"texte-clair", "texte-sombre"}
    assert {o["id"] for o in out["options"]["shot"]} >= {"portrait", "plan-americain", "plan-ensemble"}

    r = c.put(f"/projects/{s['id']}/cover-charter", json={"mood": "nocturne"})
    assert r.status_code == 422 and "ambiance inconnu" in r.text
    r = c.put(f"/projects/{s['id']}/cover-charter", json={"character_ids": [999]})
    assert r.status_code == 422

    out = _ok(
        c.put(
            f"/projects/{s['id']}/cover-charter",
            json={"palette_mode": "imposee", "shot": "portrait", "character_ids": [kaito["id"], mei["id"]]},
        )
    )
    assert out["saved"] and out["values"]["palette_mode"] == "imposee" and out["values"]["mood"] == "lumineuse"
    assert out["character_ids"] == [kaito["id"], mei["id"]]
    assert any("Mei" in w for w in out["warnings"])  # sans image de référence : signalé
    assert any("#1e3a8a" in line and "strictly" in line for line in out["front_lines"])
    assert any("close-up portrait" in line for line in out["front_lines"])

    # Hors charte : refusé sur le tome ; signalé dans l'écran « Couverture ».
    r = c.patch(f"/volumes/{v['id']}", json={"cover_character_ids": [rin["id"]]})
    assert r.status_code == 422 and "hors de la charte" in r.text
    studio = _ok(c.get(f"/volumes/{v['id']}/cover"))
    assert studio["charter"]["present"] == ["Kaito", "Mei"]
    assert {ch["name"]: ch["in_charter"] for ch in studio["characters"]} == {"Kaito": True, "Mei": True, "Rin": False}

    out = _ok(c.delete(f"/projects/{s['id']}/cover-charter"))
    assert not out["saved"] and out["character_ids"] == []


def test_charter_survives_a_reload_from_the_database(c: TestClient) -> None:
    s, _, kaito, *_ = _setup(c)
    _ok(c.put(f"/projects/{s['id']}/cover-charter", json={"mood": "sombre", "character_ids": [kaito["id"]]}))
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        row = session.query(CoverCharter).one()
        assert row.project_id == s["id"] and row.settings["mood"] == "sombre" and row.character_ids == [kaito["id"]]


# --- application : 1re et 4e -------------------------------------------------------------------------------------
def test_front_cover_workflow_carries_charter_references_colour_and_framing(
    c: TestClient, comfy: MockComfyUIClient, identity: StubIdentity
) -> None:
    s, v, kaito, rin, _ = _setup(c)
    _ok(
        c.put(
            f"/projects/{s['id']}/cover-charter",
            json={
                "palette_mode": "imposee",
                "mood": "sombre",
                "shot": "portrait",
                "subject": "duo",
                "character_ids": [kaito["id"], rin["id"]],
            },
        )
    )
    # Aucun personnage choisi sur le tome : ceux de la charte ; prompt écrit à la main, sans citer d'image.
    job = _ok(c.post(f"/volumes/{v['id']}/cover/generate", json={"prompt": "Two heroes on a burning rooftop."}), 202)
    assert job["params"]["character_ids"] == [kaito["id"], rin["id"]]
    _idle(c)
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"

    wf = _generated(comfy, "tome-01/couverture")
    loads = _loads(wf)
    assert len(loads) == 2 and all("reference-" in name for name in loads)
    positive = _positive(wf)
    assert "<image1> is the identity reference for Kaito" in positive
    assert "<image2> is the identity reference for Rin" in positive
    assert "strictly limited to the series palette" in positive and "#1e3a8a" in positive and "#f97316" in positive
    assert "#ffffff" not in positive  # couleur de texte : pour le lettrage
    assert "Dark, moody lighting" in positive
    assert "close-up portrait" in positive
    assert "Kaito and Rin as a duo" in positive
    # Série en noir et blanc : la couverture reste en couleur.
    assert positive.startswith(COVER.lead)  # type: ignore[union-attr]
    assert "black and white" not in positive.casefold() and "monochrome" in _negative(wf)
    # Contrôle d'identité : les deux personnages comparés à leur référence, tout va bien.
    assert set(identity.calls[-1]) == {"Kaito", "Rin"}
    studio = _ok(c.get(f"/volumes/{v['id']}/cover"))
    version = studio["versions"][0]
    assert version["identity"]["status"] == "done" and version["identity"]["warnings"] == []
    assert studio["charter"]["saved"] and "plan de la 1re : portrait" in studio["charter"]["summary"]


def test_ai_prompt_brief_includes_the_charter(c: TestClient) -> None:
    s, v, kaito, *_ = _setup(c)
    _ok(c.put(f"/projects/{s['id']}/cover-charter", json={"shot": "plan-ensemble", "character_ids": [kaito["id"]]}))
    llm = c.app.state.ctx.providers.llm  # type: ignore[attr-defined]
    _ok(c.post(f"/volumes/{v['id']}/cover/prompt", json={"intent": "Kaito seul"}))
    user = llm.requests[-1]["messages"][1].content
    assert "Series cover charter" in user and "Framing: wide shot" in user


def test_back_illustration_workflow_carries_charter_references_colour_and_framing(
    c: TestClient, comfy: MockComfyUIClient
) -> None:
    s, v, kaito, rin, _ = _setup(c)
    _ok(
        c.put(
            f"/projects/{s['id']}/cover-charter",
            json={"palette_mode": "suggeree", "mood": "chaude", "back_shot": "plan-americain"},
        )
    )
    _ok(c.patch(f"/volumes/{v['id']}", json={"cover_character_ids": [rin["id"]]}))
    job = _ok(c.post(f"/volumes/{v['id']}/back/generate", json={"prompt": "Rin under the lanterns."}), 202)
    assert job["params"]["kind"] == "back" and job["params"]["character_ids"] == [rin["id"]]
    _idle(c)
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    wf = _generated(comfy, "tome-01/quatrieme")
    assert len(_loads(wf)) == 1
    positive = _positive(wf)
    assert "<image1> is the identity reference for Rin" in positive
    assert "inspired by the series palette" in positive and "#1e3a8a" in positive
    assert "Warm golden lighting" in positive and "American shot" in positive
    assert "Main subject" not in positive  # le sujet principal est celui de la 1re
    assert "no text" in positive.casefold() and "black and white" not in positive.casefold()
    comp = _ok(c.get(f"/volumes/{v['id']}/composition"))
    assert comp["back_versions"][0]["identity"]["status"] == "done"


# --- vérification : avertissement, jamais de blocage --------------------------------------------------------------
def test_a_character_unlike_its_reference_gives_a_visible_warning(
    c: TestClient, comfy: MockComfyUIClient, identity: StubIdentity
) -> None:
    s, v, kaito, rin, _ = _setup(c)
    identity.sims = {"Rin": 0.41}
    _ok(c.put(f"/projects/{s['id']}/cover-charter", json={"character_ids": [kaito["id"], rin["id"]]}))
    _ok(c.post(f"/volumes/{v['id']}/cover/generate", json={"prompt": "Kaito and Rin back to back."}), 202)
    _ok(c.post(f"/volumes/{v['id']}/back/generate", json={"prompt": "Rin alone at dawn."}), 202)
    _idle(c)
    studio = _ok(c.get(f"/volumes/{v['id']}/cover"))
    version = studio["versions"][0]
    # Pas de blocage : la version existe et est retenue d'office.
    assert version["selected"]
    ident = version["identity"]
    assert ident["status"] == "done"
    assert {x["name"]: x["ok"] for x in ident["characters"]} == {"Kaito": True, "Rin": False}
    assert any("Rin ne ressemble pas assez à sa fiche" in w for w in ident["warnings"])
    comp = _ok(c.get(f"/volumes/{v['id']}/composition"))
    notes = [w["message"] for w in comp["warnings"] if w["code"] == "identity"]
    assert any(n.startswith("1re de couverture : Rin") for n in notes)
    assert any(n.startswith("illustration de 4e : Rin") for n in notes)
    assert not [p for p in comp["problems"] if p["code"] == "identity"]


def test_without_identity_provider_the_cover_is_still_generated(
    make_settings: Callable[..., Settings], comfy: MockComfyUIClient
) -> None:
    providers = Providers(llm=MockLLMProvider(), vision=None, comfyui=comfy, names={}, errors={"identity": "absent"})
    with TestClient(create_app(make_settings(), providers=providers)) as client:
        s, v, kaito, *_ = _setup(client)
        _ok(client.put(f"/projects/{s['id']}/cover-charter", json={"character_ids": [kaito["id"]]}))
        _ok(client.post(f"/volumes/{v['id']}/cover/generate", json={"prompt": "Kaito."}), 202)
        _idle(client)
        version = _ok(client.get(f"/volumes/{v['id']}/cover"))["versions"][0]
        assert version["identity"]["status"] == "unavailable" and "absent" in version["identity"]["message"]
        assert len(_loads(_generated(comfy, "tome-01/couverture"))) == 1
