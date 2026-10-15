"""Unité de lieu (#170) : lieux de la série, regroupement des variantes des chapitres d'avant, case
d'établissement (ADN de la série, contrôle de la direction artistique), référence de lieu à la génération,
alertes de l'écran Atelier."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import PanelCast, choose_references
from mangaka_engine.pipeline.locations import heuristic_groups, place_head, place_name
from mangaka_engine.presets import PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import AssetKind, Character, CharacterImage, SeriesAsset, SeriesAssetImage
from tests.conftest import PRESETS_DIR, STYLE, png_bytes, start_script
from tests.fixtures.islands import CRIQUE, PETITE_ILE, distinct, pages
from tests.test_migrations import _columns, _version

REG = PresetRegistry.load(PRESETS_DIR)


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


def _wait_job(c: TestClient, job_id: int) -> dict[str, Any]:
    c.app.state.ctx.jobs.wait(job_id, 20)  # type: ignore[attr-defined]
    return _ok(c.get(f"/jobs/{job_id}"))


def _panels(c: TestClient, chapter_id: int) -> list[dict[str, Any]]:
    return [p for page in _ok(c.get(f"/chapters/{chapter_id}/pages")) for p in page["panels"]]


def _islands(c: TestClient) -> dict[str, Any]:
    """La série des deux chapitres mesurés, tels qu'en base avant l'unité de lieu (texte libre seulement)."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Lilo des îles"}), 201)
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lilo"}), 201)
    chapters = []
    for title, settings in (("La petite île", PETITE_ILE), ("La crique au pirate", CRIQUE)):
        ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": title}), 201)
        _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": pages(settings)}))
        chapters.append(ch)
    return {"series": s, "chapters": chapters}


# --- noms de lieu tirés d'un texte libre (LLM factice) ------------------------------------------
def test_place_head_keeps_the_place_and_drops_the_precision() -> None:
    assert place_head("Clairière au centre de l'île, herbes hautes") == "clairiere"
    assert place_head("la clairière, des papillons") == "clairiere"
    assert place_head("cabane du vieux pêcheur, filets aux murs") == "cabane"
    assert place_name("la Crique au pirate, épave") == "Crique"
    assert place_name("navire pirate, cale") == "Navire pirate"


def test_heuristic_groups_rank_every_variant_once() -> None:
    ctx = {
        "settings": [{"n": i + 1, "text": t} for i, t in enumerate(["clairière", "clairière au centre", "grotte"])],
        "locations": [{"id": 9, "name": "La grotte", "decor": None}],
        "decors": [{"id": 4, "name": "Clairière enchantée"}],
    }
    groups = heuristic_groups(ctx)["locations"]
    assert [(g["name"], g["settings"], g["existing"], g["decor"]) for g in groups] == [
        ("Clairière", [1, 2], None, 4),
        ("La grotte", [3], 9, None),
    ]


# --- les deux chapitres existants migrent ---------------------------------------------------------
def test_both_existing_chapters_migrate_to_fewer_places_with_every_panel_attached(c: TestClient) -> None:
    data = _islands(c)
    s = data["series"]
    before = {ch["id"]: _panels(c, ch["id"]) for ch in data["chapters"]}
    assert [distinct(PETITE_ILE), distinct(CRIQUE)] == [24, 24]
    assert [len(p) for p in before.values()] == [38, 40]
    assert all(p["location"] is None for ps in before.values() for p in ps)

    proposal = _ok(c.post(f"/projects/{s['id']}/locations/proposal", json={}))
    assert proposal["unattached"] == 78
    assert len(proposal["variants"]) == 48  # aucune variante commune aux deux chapitres
    groups = proposal["groups"]
    ranked = [t for g in groups for t in g["settings"]]
    assert sorted(ranked) == sorted(v["text"] for v in proposal["variants"])  # chaque variante, une fois
    assert {g["name"] for g in groups} == {
        "Plage", "Clairière", "Forêt", "Grotte", "Cabane", "Crique", "Navire pirate", "Falaise", "Taverne", "Port"
    }  # fmt: skip
    # L'auteur corrige avant de valider : renomme un lieu et en fusionne deux.
    by_name = {g["name"]: g for g in groups}
    by_name["Navire pirate"]["name"] = "Le Sans-Pitié"
    by_name["Falaise"]["settings"] += by_name.pop("Crique")["settings"]
    by_name["Falaise"]["name"] = "La crique et sa falaise"
    applied = _ok(c.post(f"/projects/{s['id']}/locations/apply", json={"groups": list(by_name.values())}))
    assert applied["created"] == 9 and applied["unattached"] == 0
    assert applied["attached"] + applied["inherited"] == 78 and applied["inherited"] == 7

    for ch in data["chapters"]:
        after = _panels(c, ch["id"])
        settings = PETITE_ILE if ch["title"] == "La petite île" else CRIQUE
        assert all(p["location"] is not None for p in after)  # toutes les cases rattachées
        # Aucune donnée perdue : texte, personnages et décor de chaque case inchangés.
        old = before[ch["id"]]
        assert [p["setting"] for p in after] == [p["setting"] for p in old] == settings
        assert [p["characters"] for p in after] == [p["characters"] for p in old]
        assert [p["decor"] for p in after] == [p["decor"] for p in old]
        assert len({p["location"] for p in after}) == 5 if ch["title"] == "La petite île" else 4
        assert len({p["location"] for p in after}) < distinct(settings)
    # Une case sans texte prend le lieu de la case qui la précède.
    small = _panels(c, data["chapters"][0]["id"])
    assert small[4]["setting"] == "" and small[4]["location"] == small[3]["location"]
    names = {loc["name"]: loc for loc in _ok(c.get(f"/projects/{s['id']}/locations"))}
    assert names["Le Sans-Pitié"]["panel_count"] == 8 and names["Le Sans-Pitié"]["chapters"] == [2]
    # Plus rien à regrouper.
    assert _ok(c.post(f"/projects/{s['id']}/locations/proposal", json={})) == {
        "variants": [],
        "groups": [],
        "unattached": 0,
    }


def test_apply_refuses_an_unknown_decor_or_location(c: TestClient) -> None:
    s = _islands(c)["series"]
    r = c.post(f"/projects/{s['id']}/locations/apply", json={"groups": [{"name": "X", "settings": [], "decor": 4242}]})
    assert r.status_code == 422 and "décor inconnu" in r.text
    r = c.post(f"/projects/{s['id']}/locations/apply", json={"groups": [{"existing": 4242, "settings": []}]})
    assert r.status_code == 422 and "lieu inconnu" in r.text


def test_v35_database_gets_places_with_no_panel_attached(make_settings: Callable[..., Settings]) -> None:
    """v35 → v36 : lieux de la série et lieu de chaque case ; aucune case rattachée, texte de lieu intact. La
    base neuve a les mêmes colonnes."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        data = _islands(c)
    con = sqlite3.connect(settings.database_path)
    # Table des cases d'avant la v36 (sans la colonne ni sa clé étrangère), reconstruite avec ses lignes.
    (ddl,) = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'panels'").fetchone()
    lines = [line for line in ddl.splitlines() if "location_id" not in line]
    ddl = re.sub(r",\s*\)\s*$", "\n)", "\n".join(lines)).replace("CREATE TABLE panels", "CREATE TABLE panels__old", 1)
    columns = ", ".join(f'"{row[1]}"' for row in con.execute("PRAGMA table_info(panels)") if row[1] != "location_id")
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute(ddl)
    con.execute(f"INSERT INTO panels__old ({columns}) SELECT {columns} FROM panels")
    con.execute("DROP TABLE panels")
    con.execute("ALTER TABLE panels__old RENAME TO panels")
    con.execute("DROP TABLE series_locations")
    con.execute("PRAGMA user_version = 35")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        panels = _panels(c, data["chapters"][0]["id"])
        assert [p["setting"] for p in panels] == PETITE_ILE and all(p["location"] is None for p in panels)
        assert _ok(c.get(f"/projects/{data['series']['id']}/locations")) == []
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)


# --- lieux : CRUD, scénariste, direction artistique -----------------------------------------------
def test_crud_and_deleting_a_place_or_its_decor_keeps_the_panels(c: TestClient) -> None:
    s = _islands(c)["series"]
    decor = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "Grotte bleue"}), 201)
    loc = _ok(c.post(f"/projects/{s['id']}/locations", json={"name": "La grotte", "decor": decor["id"]}), 201)
    assert loc["decor_name"] == "Grotte bleue" and loc["decor_image_url"] is None and loc["panel_count"] == 0
    assert c.post(f"/projects/{s['id']}/locations", json={"name": "la Grotte"}).status_code == 422  # même nom
    ch = _ok(c.get(f"/projects/{s['id']}/chapters"))[0]
    pages_ = _ok(c.get(f"/chapters/{ch['id']}/pages"))
    body = {
        "pages": [
            {"id": pg["id"], "panels": [{"id": p["id"], "description": p["description"], "location": loc["id"]}]}
            for pg in pages_[:1]
            for p in pg["panels"][:1]
        ]
    }
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json=body))
    assert page["panels"][0]["location"] == loc["id"] and page["panels"][0]["location_name"] == "La grotte"
    assert c.delete(f"/decors/{decor['id']}").status_code == 204
    assert _ok(c.get(f"/projects/{s['id']}/locations"))[0]["decor"] is None  # décor supprimé : retiré du lieu
    assert c.delete(f"/locations/{loc['id']}").status_code == 204
    [panel] = _panels(c, ch["id"])
    assert panel["location"] is None and panel["description"] == "Case 1"


def test_the_writer_attaches_every_panel_to_a_place_and_reuses_it_next_chapter(c: TestClient) -> None:
    s = _ok(c.post("/projects", json={**STYLE, "title": "Dragons"}), 201)
    for name in ("Urus", "Kaël"):
        _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
    ids = []
    for n in (1, 2):
        body = {"title": f"Ch {n}", "synopsis": "Urus retrouve Kaël.", "target_page_count": 4}
        ch = _ok(c.post(f"/projects/{s['id']}/chapters", json=body), 201)
        job = _ok(start_script(c, ch["id"]), 202)
        assert _wait_job(c, job["id"])["status"] == "succeeded"
        ids.append(ch["id"])
    places = _ok(c.get(f"/projects/{s['id']}/locations"))
    # 4 pages : la clairière (pages 1 à 3), puis la falaise ; le chapitre 2 reprend les mêmes lieux.
    assert [p["name"] for p in places] == ["La clairière", "La falaise"]
    assert {p["name"]: p["chapters"] for p in places} == {"La clairière": [1, 2], "La falaise": [1, 2]}
    assert all(p["location"] is not None for ch in ids for p in _panels(c, ch))


def _directed(c: TestClient, synopsis: str) -> dict[str, Any]:
    s = _ok(c.post("/projects", json={**STYLE, "title": "Dragons"}), 201)
    for name in ("Urus", "Kaël"):
        _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
    ch = _ok(
        c.post(f"/projects/{s['id']}/chapters", json={"title": "Le vol", "synopsis": synopsis, "target_page_count": 7}),
        201,
    )
    assert _wait_job(c, _ok(start_script(c, ch["id"]), 202)["id"])["status"] == "succeeded"
    job = _ok(c.post(f"/chapters/{ch['id']}/direction", json={}), 202)
    assert _wait_job(c, job["id"])["status"] == "succeeded"
    return _ok(c.get(f"/chapters/{ch['id']}/direction"))


def _establishing_warnings(direction: dict[str, Any]) -> list[str]:
    return [w for p in direction["pages"] for w in p["warnings"] if "case d'établissement" in w]


def test_mock_place_change_without_establishing_panel_gets_a_retry_then_a_warning(c: TestClient) -> None:
    llm: MockLLMProvider = c.app.state.ctx.providers.llm  # type: ignore[attr-defined]
    # Le LLM n'installe jamais les nouveaux lieux : relance ciblée, puis avertissement visible.
    direction = _directed(c, "Urus s'envole. Kaël le suit. [mock:sans-etablissement:9]")
    retry = llm.calls[-1][-1].content
    assert "changement de lieu sans case d'établissement" in retry and "plan large" in retry
    warnings = _establishing_warnings(direction)
    assert warnings and "« La falaise »" in warnings[0] and "page 4 case 1" in warnings[0]
    # Il installe chaque lieu d'emblée : pas de relance pour cette règle.
    calls = len(llm.calls)
    direction = _directed(c, "Urus s'envole. Kaël le suit.")
    assert _establishing_warnings(direction) == []
    retries = [m.content for call in llm.calls[calls:] for m in call if m.role == "user"]
    assert not any("changement de lieu sans case d'établissement" in m for m in retries)


# --- référence de lieu à la génération --------------------------------------------------------------
def _char(i: int, images: int = 1) -> Character:
    return Character(id=i, name=f"P{i}", reference_images=[CharacterImage(id=i * 10 + k) for k in range(images)])


def _decor() -> SeriesAsset:
    return SeriesAsset(id=50, kind=AssetKind.decor, name="La crique", reference_images=[SeriesAssetImage(id=500)])


@pytest.mark.parametrize(
    ("characters", "expected"),
    [
        ([_char(1, 3), _char(2, 3)], ["P1", "P2", "La crique", "P1", "P2"]),  # lieu avant les 2es images
        ([_char(i) for i in range(1, 5)], ["P1", "P2", "P3", "P4", "La crique"]),  # dernier emplacement libre
        ([_char(i) for i in range(1, 6)], ["P1", "P2", "P3", "P4", "P5"]),  # aucun : l'identité d'abord
    ],
)
def test_place_reference_takes_a_free_slot_without_removing_identity(
    characters: list[Character], expected: list[str]
) -> None:
    cast = PanelCast(characters=characters, decor=_decor())
    choice = choose_references(cast.reference_entries, 5)
    assert [e.name for e, _ in choice.sent] == expected and len(choice.sent) <= 5
    refs = [f"mangaka/{e.name}-{img.id}.png" for e, img in choice.sent]
    wf = build_workflow(
        REG.workflow("qwen-image-edit-ref-qualite"),
        {"positive_prompt": "Lilo", "width": 832, "height": 1216, "seed": 1},
        reference_images=refs,
    ).workflow
    loads = [wf[wf["6"]["inputs"][f"images.image_{i}"][0]]["inputs"]["image"] for i in range(1, len(refs) + 1)]
    assert loads == refs
    assert "images.image_6" not in wf["6"]["inputs"]


def test_generated_panel_of_a_place_with_a_decor_sends_the_place_reference(
    c: TestClient, comfy: MockComfyUIClient
) -> None:
    s = _ok(c.post("/projects", json={**STYLE, "title": "Lilo", "ai_prompt": False}), 201)
    for name in ("Lilo", "Stitch"):
        who = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
        files = [("files", (f"{i}.png", png_bytes(), "image/png")) for i in range(3)]
        _ok(c.post(f"/characters/{who['id']}/images", files=files), 201)
    decor = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "Crique turquoise"}), 201)
    _ok(c.post(f"/decors/{decor['id']}/images", files=[("files", ("d.png", png_bytes(), "image/png"))]), 201)
    loc = _ok(c.post(f"/projects/{s['id']}/locations", json={"name": "La crique", "decor": decor["id"]}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Plage"}), 201)
    panel = {"description": "Lilo et Stitch", "characters": ["Lilo", "Stitch"], "location": loc["id"]}
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel]}]}))
    assert page["panels"][0]["decor"] is None  # aucun décor propre : celui du lieu
    [job] = _ok(c.post(f"/panels/{page['panels'][0]['id']}/generate"), 202)
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]
    done = _ok(c.get(f"/jobs/{job['id']}"))
    assert done["status"] == "succeeded", done
    used = [(r["slot"], r["kind"], r["name"]) for r in done["params"]["references"]]
    assert used[:3] == [(1, "character", "Lilo"), (2, "character", "Stitch"), (3, "decor", "Crique turquoise")]
    assert len(used) <= 5 and {u[2] for u in used} >= {"Lilo", "Stitch"}
    [submitted] = comfy.prompts.values()
    sent = [v for k, v in submitted["6"]["inputs"].items() if k.startswith("images.image_")]
    assert len(sent) == len(used) <= 5


# --- alertes de l'écran de génération ---------------------------------------------------------------
def test_alerts_panels_without_reference_and_places_without_decor(c: TestClient) -> None:
    data = _islands(c)
    s, ch = data["series"], data["chapters"][0]
    alerts = _ok(c.get(f"/chapters/{ch['id']}/reference-alerts"))
    # Lilo n'a pas d'image : chaque case où il est à l'image est sans aucune référence.
    assert len(alerts["panels_without_reference"]) == 19 and alerts["locations_without_decor"] == []
    assert alerts["panels_without_reference"][0] == {
        "panel_id": alerts["panels_without_reference"][0]["panel_id"],
        "page_id": alerts["panels_without_reference"][0]["page_id"],
        "page": 1,
        "panel": 1,
        "characters": ["Lilo"],
    }
    assert len(alerts["unattached"]) == 38
    proposal = _ok(c.post(f"/projects/{s['id']}/locations/proposal", json={"chapter_id": ch["id"]}))
    _ok(c.post(f"/projects/{s['id']}/locations/apply", json={"chapter_id": ch["id"], "groups": proposal["groups"]}))
    alerts = _ok(c.get(f"/chapters/{ch['id']}/reference-alerts"))
    assert alerts["unattached"] == []
    assert {a["name"] for a in alerts["locations_without_decor"]} == {"Plage", "Clairière", "Forêt", "Grotte", "Cabane"}
    assert all(a["reason"] == "no_decor" for a in alerts["locations_without_decor"])
    # Un décor avec image pour la plage : ses cases ont désormais une référence (le lieu), et la plage n'est plus
    # signalée.
    decor = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "Plage blanche"}), 201)
    plage = next(loc for loc in _ok(c.get(f"/projects/{s['id']}/locations")) if loc["name"] == "Plage")
    _ok(c.patch(f"/locations/{plage['id']}", json={"decor": decor["id"]}))
    alerts = _ok(c.get(f"/chapters/{ch['id']}/reference-alerts"))
    assert next(a for a in alerts["locations_without_decor"] if a["name"] == "Plage")["reason"] == "decor_without_image"
    _ok(c.post(f"/decors/{decor['id']}/images", files=[("files", ("p.png", png_bytes(), "image/png"))]), 201)
    after = _ok(c.get(f"/chapters/{ch['id']}/reference-alerts"))
    assert "Plage" not in {a["name"] for a in after["locations_without_decor"]}
    assert len(after["panels_without_reference"]) < len(alerts["panels_without_reference"])
