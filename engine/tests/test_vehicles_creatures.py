"""Véhicules et créatures dans la bibliothèque (#180) : la vue qui correspond au cadrage passe en tête, une case
dont le scénario cite le vaisseau reçoit sa référence, une créature n'entre pas dans la distribution, les agents
les voient avec les objets, et la migration garde les fiches existantes."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import pick_references, view_ranks
from mangaka_engine.pipeline.library import SeriesLibrary
from mangaka_engine.pipeline.pages import layout_pages
from mangaka_engine.pipeline.script import parse_script, save_script
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import AngleTarget
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import AssetKind, Chapter, Character, CharacterImage, SeriesAsset, SeriesAssetImage
from tests.conftest import PRESETS_DIR, STYLE, png_bytes
from tests.test_migrations import _columns, _version
from tests.test_reference_sheets import _idle, _ok

REG = PresetRegistry.load(PRESETS_DIR)


@pytest.fixture
def comfy() -> MockComfyUIClient:
    return MockComfyUIClient()


@pytest.fixture
def c(make_settings: Callable[..., Settings], comfy: MockComfyUIClient) -> Iterator[TestClient]:
    providers = Providers(llm=MockLLMProvider(), vision=None, comfyui=comfy, names={"comfyui": "mock"}, errors={})
    with TestClient(create_app(make_settings(), providers=providers)) as client:
        yield client


# --- priorité des références : la vue qui correspond au cadrage d'abord ----------------------------------
def _vehicle(*images: SeriesAssetImage) -> SeriesAsset:
    return SeriesAsset(id=5, kind=AssetKind.vehicle, name="Le Faucon", reference_images=list(images))


def _order(vehicle: SeriesAsset, framing: list[str | None], sheets: dict[int, str], target: Any = None) -> list[int]:
    tags = {img.id: img.angle for img in vehicle.reference_images}
    ranks = view_ranks(REG, framing, sheets, tags, target)
    sent = pick_references([vehicle], 5, "toutes", catalog=REG.camera_loras, framing_ranks=ranks)
    return [img.id for _, img in sent]


def test_the_profile_view_of_a_vehicle_comes_first_for_a_profile_panel() -> None:
    three_quarters, turnaround = SeriesAssetImage(id=101), SeriesAssetImage(id=102)
    vehicle = _vehicle(three_quarters, turnaround)
    sheets = {101: "vehicule-trois-quarts", 102: "vehicule-turnaround"}
    # Case de profil : le turnaround (profil, face, dessus, arrière) passe devant la vue 3/4 principale.
    assert _order(vehicle, ["de profil", "plan moyen"], sheets) == [102, 101]
    assert _order(vehicle, ["de dos", None], sheets) == [102, 101]
    # Case de trois quarts : la vue 3/4 reste en tête.
    assert _order(vehicle, ["de trois quarts", "plan large"], sheets) == [101, 102]
    # Sans cadrage, ou sans vue de profil : l'ordre de la fiche, rien n'est écarté.
    assert _order(vehicle, [None, ""], sheets) == [101, 102]
    assert _order(_vehicle(three_quarters), ["de profil"], {101: "vehicule-trois-quarts"}) == [101]
    # « principale » : une seule image par fiche, celle qui correspond au cadrage.
    ranks = view_ranks(REG, ["de profil"], sheets)
    assert [img.id for _, img in pick_references([vehicle], 5, "principale", framing_ranks=ranks)] == [102]


def test_a_profile_view_tagged_by_new_angle_also_comes_first() -> None:
    """Une vue étiquetée « Profil droit » (« Nouvel angle ») sert une case de profil autant que le turnaround."""
    main, side = SeriesAssetImage(id=201), SeriesAssetImage(id=202, angle="right-eye")
    vehicle = _vehicle(main, side)
    profile = AngleTarget(azimuth=90)
    assert _order(vehicle, ["de profil"], {201: "vehicule-trois-quarts"}, profile) == [202, 201]
    assert _order(vehicle, ["de face"], {201: "vehicule-trois-quarts"}, AngleTarget(azimuth=0)) == [201, 202]


def test_a_character_image_id_never_reorders_a_vehicle() -> None:
    """Les ids d'images de personnage et de véhicule viennent de tables différentes : `shots` (personnages) ne
    touche jamais un véhicule, `framing_ranks` jamais un personnage."""
    vehicle = _vehicle(SeriesAssetImage(id=1), SeriesAssetImage(id=2))
    sent = pick_references([vehicle], 5, "toutes", shots={2: 0, 1: 2})
    assert [img.id for _, img in sent] == [1, 2]
    aiko = Character(id=3, name="Aiko", reference_images=[CharacterImage(id=1), CharacterImage(id=2)])
    sent = pick_references([aiko], 5, "toutes", framing_ranks={2: 0})
    assert [img.id for _, img in sent] == [1, 2]


# --- agents : la bibliothèque des agents -----------------------------------------------------------------
def _series(c: TestClient) -> dict[str, Any]:
    return _ok(c.post("/projects", json={**STYLE, "title": "Étoiles"}), 201)


def _add(c: TestClient, project_id: int, segment: str, name: str, *, image: bool = True) -> dict[str, Any]:
    entry = _ok(
        c.post(f"/projects/{project_id}/{segment}", json={"name": name, "visual_description": f"{name} décrit"}), 201
    )
    if image:
        entry = _ok(
            c.post(f"/{segment}/{entry['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201
        )
    return entry


def test_agents_see_vehicles_and_creatures_with_the_objects(c: TestClient) -> None:
    s = _series(c)
    sword = _add(c, s["id"], "objects", "Épée", image=False)
    ship = _add(c, s["id"], "vehicles", "Le Faucon", image=False)
    cat = _add(c, s["id"], "creatures", "Momo", image=False)
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        library = SeriesLibrary.load(session, s["id"])
    text = library.text("objets")
    assert text.splitlines() == [
        f"- id {sword['id']} · Épée : Épée décrit",
        f"- id {ship['id']} · Le Faucon (véhicule) : Le Faucon décrit",
        f"- id {cat['id']} · Momo (créature) : Momo décrit",
    ]
    assert library.text("objets", "véhicule") == f"- id {ship['id']} · Le Faucon (véhicule) : Le Faucon décrit"
    assert library.check_refs(None, [ship["id"], cat["id"]]) == []
    [problem] = library.check_refs(None, [999])
    assert problem.startswith("objets : id(s) 999 inconnu(s) (ids possibles : ") and str(cat["id"]) in problem
    bible = _ok(c.get(f"/projects/{s['id']}/bible"))
    assert [v["name"] for v in bible["vehicules"]] == ["Le Faucon"]
    assert [v["name"] for v in bible["creatures"]] == ["Momo"]
    assert [v["name"] for v in bible["objets"]] == ["Épée"]


def test_a_script_that_cites_the_ship_gives_its_panel_the_reference(c: TestClient, comfy: MockComfyUIClient) -> None:
    """Critère d'acceptation : une case dont le scénario cite le vaisseau reçoit sa référence. Le chat cité parmi
    les personnages est rattaché à la case comme une créature : il n'entre pas dans la distribution."""
    s = _series(c)
    _add(c, s["id"], "characters", "Aiko")
    ship = _add(c, s["id"], "vehicles", "Le Faucon")
    cat = _add(c, s["id"], "creatures", "Momo")
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Départ"}), 201)
    panels = [
        # Le vaisseau cité par son id, et le chat mis (à tort) parmi les personnages.
        {"description": "Aiko monte à bord", "characters": ["Aiko", "momo"], "objets": [ship["id"]]},
        # Le vaisseau seulement nommé dans la description.
        {"description": "Le Faucon décolle dans un nuage de poussière", "characters": []},
    ]
    output = parse_script(json.dumps({"pages": [{"panels": panels}], "summary": "Départ."}))
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        chapter = session.get(Chapter, ch["id"])
        assert chapter is not None
        layout_pages(c.app.state.ctx.presets, save_script(session, chapter, output))  # type: ignore[attr-defined]
        session.commit()
    [page] = _ok(c.get(f"/chapters/{ch['id']}/pages"))
    first, second = (_ok(c.get(f"/panels/{p['id']}")) for p in page["panels"])
    assert first["characters"] == ["Aiko"] and first["unmatched_characters"] == []
    assert [(o["kind"], o["id"]) for o in first["objets"]] == [("vehicle", ship["id"]), ("creature", cat["id"])]
    assert [(o["kind"], o["id"]) for o in second["objets"]] == [("vehicle", ship["id"])]
    [job] = _ok(c.post(f"/panels/{second['id']}/generate"), 202)
    _idle(c)
    used = _ok(c.get(f"/jobs/{job['id']}"))["params"]["references"]
    assert [(r["kind"], r["id"]) for r in used] == [("vehicle", ship["id"])]
    sent = list(comfy.prompts.values())[-1]["6"]["inputs"]["prompt"]
    assert "is the design reference for the vehicle Le Faucon" in sent


def test_deleting_a_vehicle_removes_it_from_panels(c: TestClient) -> None:
    s = _series(c)
    ship = _add(c, s["id"], "vehicles", "Le Faucon", image=False)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    body = {"pages": [{"panels": [{"description": "x", "objets": [ship["id"]]}]}]}
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json=body))
    assert c.delete(f"/vehicles/{ship['id']}").status_code == 204
    assert _ok(c.get(f"/panels/{page['panels'][0]['id']}"))["objets"] == []


# --- migration -------------------------------------------------------------------------------------------
def test_v36_database_keeps_its_references_and_accepts_vehicles(make_settings: Callable[..., Settings]) -> None:
    """v36 → v37 : objets et décors existants intacts ; une table créée avec une contrainte CHECK sur la sorte
    (ancien SQLAlchemy) est reconstruite sans elle, ids gardés ; une base neuve a le même schéma."""
    settings = make_settings()
    with TestClient(create_app(settings)) as client:
        s = _series(client)
        sword = _add(client, s["id"], "objects", "Épée")
        lab = _add(client, s["id"], "decors", "Le labo", image=False)
    con = sqlite3.connect(settings.database_path)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("PRAGMA legacy_alter_table=ON")  # les clés étrangères vers series_assets restent telles quelles
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='series_assets'").fetchone()[0]
    con.execute("ALTER TABLE series_assets RENAME TO series_assets_old")
    con.execute(
        sql.replace(
            "kind VARCHAR(20) NOT NULL,", "kind VARCHAR(20) NOT NULL CHECK (kind IN ('object', 'decor', 'style')),"
        )
    )
    con.execute("INSERT INTO series_assets SELECT * FROM series_assets_old")
    con.execute("DROP TABLE series_assets_old")
    con.execute("CREATE INDEX ix_series_assets_project_id ON series_assets (project_id)")
    con.execute("PRAGMA user_version = 36")
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):  # la contrainte d'avant refuse un véhicule
        con.execute(
            "INSERT INTO series_assets (project_id, kind, name, slug, visual_description, prompt_keywords,"
            " lora_weight, lora_trigger_words, active, created_at, updated_at)"
            " VALUES (?, 'vehicle', 'x', 'x', '', '[]', 0.8, '', 1, '2026-10-14', '2026-10-14')",
            (s["id"],),
        )
    con.close()

    with TestClient(create_app(settings)) as client:
        assert _ok(client.get(f"/objects/{sword['id']}"))["reference_images"][0]["url"]
        assert _ok(client.get(f"/decors/{lab['id']}"))["name"] == "Le labo"
        ship = _add(client, s["id"], "vehicles", "Le Faucon")
        assert ship["id"] > lab["id"] and ship["kind"] == "vehicle"
        assert _ok(client.post(f"/objects/{sword['id']}/kind", json={"kind": "creature"}))["kind"] == "creature"
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
    con = sqlite3.connect(settings.database_path)
    assert "CHECK" not in con.execute("SELECT sql FROM sqlite_master WHERE name='series_assets'").fetchone()[0]
    con.close()
