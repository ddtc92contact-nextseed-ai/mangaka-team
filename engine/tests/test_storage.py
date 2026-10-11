"""Rangement des fichiers : slugs des séries et des fiches, dossiers de ComfyUI (préfixes, envois, renommage,
suppression confinée, sortie effacée après copie), ids jamais réutilisés, ménage des variantes, migration v24."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.comfyui.base import ImageRef
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.comfy_folders import ComfyFolders
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.slugs import slugify, unique_slug
from tests.conftest import STYLE, png_bytes
from tests.test_migrations import _columns, _version


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def comfy_dir(tmp_path: Path) -> Path:
    """Faux ComfyUI : `input/` et `output/`, avec les archives `mangaka/old/` gardées à la main."""
    root = tmp_path / "ComfyUI"
    for area in ("input", "output"):
        (root / area / "mangaka" / "old").mkdir(parents=True)
        (root / area / "mangaka" / "old" / "garde.png").write_bytes(b"x")
    return root


@pytest.fixture
def comfy(comfy_dir: Path) -> MockComfyUIClient:
    return MockComfyUIClient(root=comfy_dir)


@pytest.fixture
def make_client(
    make_settings: Callable[..., Settings], comfy: MockComfyUIClient, comfy_dir: Path
) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(**overrides: Any) -> TestClient:
        providers = Providers(
            llm=MockLLMProvider(),
            vision=None,
            comfyui=comfy,
            names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
            errors={},
        )
        settings = make_settings(**{"comfyui_dir": str(comfy_dir), **overrides})
        client = TestClient(create_app(settings, providers=providers))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def c(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def _idle(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(15)  # type: ignore[attr-defined]


def _series(c: TestClient, title: str) -> dict[str, Any]:
    return _ok(c.post("/projects", json={**STYLE, "title": title}), 201)


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- slugs --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Lucius et Stan", "lucius-et-stan"),
        ("Élève modèle", "eleve-modele"),
        ("Très chère sœur", "tres-chere-soeur"),
        ("Garçon façonné", "garcon-faconne"),
        ("Cœur d'Été !", "coeur-d-ete"),
        ("  L'épée — du roi…  ", "l-epee-du-roi"),
        ("Robot R-2", "robot-r-2"),
        ("Æther & Straße", "aether-strasse"),
        ("???", "sans-nom"),
        ("", "sans-nom"),
    ],
)
def test_slugify_removes_accents_spaces_and_punctuation(text: str, slug: str) -> None:
    assert slugify(text) == slug


def test_slug_is_short_and_collisions_get_a_number() -> None:
    long = slugify("Une très longue histoire " * 10)
    assert len(long) <= 60 and not long.endswith("-")
    assert unique_slug("lucius", set()) == "lucius"
    assert unique_slug("lucius", {"lucius"}) == "lucius-2"
    assert unique_slug("lucius", {"lucius", "lucius-2"}) == "lucius-3"


def test_series_and_entry_slugs_are_unique_and_never_old(c: TestClient) -> None:
    a = _series(c, "Lucius et Stan")
    b = _series(c, "Lucius & Stan")
    old = _series(c, "Old")
    assert (a["slug"], b["slug"], old["slug"]) == ("lucius-et-stan", "lucius-stan", "old-2")
    again = _series(c, "lucius et stan")
    assert again["slug"] == "lucius-et-stan-2"

    lucius = _ok(c.post(f"/projects/{a['id']}/characters", json={"name": "Lucius"}), 201)
    lucius2 = _ok(c.post(f"/projects/{a['id']}/characters", json={"name": "Lucïus"}), 201)
    other = _ok(c.post(f"/projects/{b['id']}/characters", json={"name": "Lucius"}), 201)
    assert (lucius["slug"], lucius2["slug"], other["slug"]) == ("lucius", "lucius-2", "lucius")
    # Un objet et un décor peuvent porter le même nom qu'un personnage : dossiers distincts par sorte.
    obj = _ok(c.post(f"/projects/{a['id']}/objects", json={"name": "Lucius"}), 201)
    decor = _ok(c.post(f"/projects/{a['id']}/decors", json={"name": "La forêt d'Émeraude"}), 201)
    assert (obj["slug"], decor["slug"]) == ("lucius", "la-foret-d-emeraude")


def test_rename_changes_the_slug_and_moves_the_comfyui_folders(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    ch = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    for area in ("output", "input"):
        folder = comfy_dir / area / "mangaka" / "lucius-et-stan" / "personnages" / "lucius"
        folder.mkdir(parents=True)
        (folder / "a.png").write_bytes(b"a")

    # Même nom, autre casse : le slug ne bouge pas.
    assert _ok(c.patch(f"/projects/{s['id']}", json={"title": "LUCIUS ET STAN"}))["slug"] == "lucius-et-stan"
    renamed = _ok(c.patch(f"/projects/{s['id']}", json={"title": "Les Aventures de Lucius"}))
    assert renamed["slug"] == "les-aventures-de-lucius"
    renamed_ch = _ok(c.patch(f"/characters/{ch['id']}", json={"name": "Lucius le Grand"}))
    assert renamed_ch["slug"] == "lucius-le-grand"
    for area in ("output", "input"):
        base = comfy_dir / area / "mangaka"
        assert not (base / "lucius-et-stan").exists()
        assert (base / "les-aventures-de-lucius" / "personnages" / "lucius-le-grand" / "a.png").read_bytes() == b"a"
        assert (base / "old" / "garde.png").exists()


def test_a_folder_already_in_comfyui_is_never_reused(c: TestClient, comfy_dir: Path) -> None:
    (comfy_dir / "output" / "mangaka" / "lucius-et-stan").mkdir()
    assert _series(c, "Lucius et Stan")["slug"] == "lucius-et-stan-2"


# --- préfixes et envois dans ComfyUI (mode mock) --------------------------------------------
def test_reference_sheet_files_go_under_the_series_and_character_names(
    c: TestClient, comfy: MockComfyUIClient, comfy_dir: Path
) -> None:
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius", "visual_description": "roux"}), 201)
    jobs = _ok(
        c.post(f"/characters/{lucius['id']}/reference-variants", json={"sheet": "personnage-portrait", "count": 2}),
        202,
    )
    _idle(c)
    prefixes = [
        wf[k]["inputs"]["filename_prefix"]
        for wf in comfy.prompts.values()
        for k in wf
        if "filename_prefix" in wf[k]["inputs"]
    ]
    assert prefixes == [
        "mangaka/lucius-et-stan/_transit/personnages/lucius/personnage-portrait/variante-1",
        "mangaka/lucius-et-stan/_transit/personnages/lucius/personnage-portrait/variante-2",
    ]
    # Résultat copié dans data/ : la copie de ComfyUI (zone de transit `_transit/`) est effacée.
    assert all(_ok(c.get(f"/jobs/{j['id']}"))["status"] == "succeeded" for j in jobs)
    # Non gardées : seulement leur copie dans la corbeille de la bibliothèque (pipeline/comfy_library.py).
    assert _files(comfy_dir / "output" / "mangaka" / "lucius-et-stan") == {
        "trash/personnages/lucius/portrait/lucius-portrait-v1.png",
        "trash/personnages/lucius/portrait/lucius-portrait-v2.png",
    }
    assert (comfy_dir / "output" / "mangaka" / "old" / "garde.png").exists()

    # « Affiner » : la variante de départ est envoyée dans le dossier du personnage.
    variant = _ok(c.get(f"/characters/{lucius['id']}/reference-variants"))["variants"][0]
    _ok(c.post(f"/reference-variants/{variant['id']}/refine", json={"instruction": "sourire", "count": 1}), 202)
    _idle(c)
    assert f"mangaka/lucius-et-stan/personnages/lucius/variante-{variant['id']}.png" in comfy.uploads
    assert (comfy_dir / "input" / "mangaka" / "lucius-et-stan" / "personnages" / "lucius").is_dir()


def test_panel_files_go_in_the_page_folder_with_readable_names(c: TestClient, comfy: MockComfyUIClient) -> None:
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    _ok(c.post(f"/characters/{lucius['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {"panels": [{"description": "a"}]},
                    {"panels": [{"description": "Lucius", "characters": ["Lucius"]}, {"description": "c"}]},
                ]
            },
        )
    )
    panel = pages[1]["panels"][1]
    _ok(c.post(f"/panels/{panel['id']}/generate"), 202)
    cited = pages[1]["panels"][0]
    _ok(c.post(f"/panels/{cited['id']}/generate"), 202)
    _idle(c)
    prefixes = sorted(
        wf[k]["inputs"]["filename_prefix"]
        for wf in comfy.prompts.values()
        for k in wf
        if "filename_prefix" in wf[k]["inputs"]
    )
    assert prefixes == [
        "mangaka/lucius-et-stan/_transit/chapitre-01/page-02/case-01",
        "mangaka/lucius-et-stan/_transit/chapitre-01/page-02/case-02",
    ]
    [image] = _ok(c.get(f"/characters/{lucius['id']}"))["reference_images"]
    assert f"mangaka/lucius-et-stan/personnages/lucius/reference-{image['id']}.png" in comfy.uploads
    # Les versions de la case restent (dans data/) même si la sortie de ComfyUI est effacée.
    [version] = _ok(c.get(f"/panels/{panel['id']}/images"))
    assert c.get(version["url"]).status_code == 200


# --- ids jamais réutilisés, suppression confinée ---------------------------------------------
def test_deleted_series_is_never_reused(c: TestClient) -> None:
    old = _series(c, "Petits dragons")
    ch = _ok(c.post(f"/projects/{old['id']}/chapters", json={"title": "Un"}), 201)
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "a"}]}]}))
    _ok(c.post(f"/projects/{old['id']}/characters", json={"name": "Urus"}), 201)
    assert c.delete(f"/projects/{old['id']}").status_code == 204

    new = _series(c, "Lucius et Stan")
    assert new["id"] > old["id"] and new["slug"] != old["slug"]
    assert _ok(c.get(f"/projects/{new['id']}/characters")) == []
    assert _ok(c.get(f"/projects/{new['id']}/chapters")) == []
    ch2 = _ok(c.post(f"/projects/{new['id']}/chapters", json={"title": "Un"}), 201)
    [page2] = _ok(c.put(f"/chapters/{ch2['id']}/pages", json={"pages": [{"panels": [{"description": "b"}]}]}))
    assert ch2["id"] > ch["id"] and page2["id"] > page["id"]
    data_dir: Path = c.app.state.ctx.settings.data_dir  # type: ignore[attr-defined]
    assert not (data_dir / "projects" / str(old["id"])).exists()


def _fill(comfy_dir: Path, *relative: str) -> None:
    for area in ("output", "input"):
        for rel in relative:
            path = comfy_dir / area / "mangaka" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")


def test_deleting_removes_exactly_its_comfyui_folders(c: TestClient, comfy_dir: Path) -> None:
    a = _series(c, "Lucius et Stan")
    b = _series(c, "Autre série")
    lucius = _ok(c.post(f"/projects/{a['id']}/characters", json={"name": "Lucius"}), 201)
    stan = _ok(c.post(f"/projects/{a['id']}/characters", json={"name": "Stan"}), 201)
    epee = _ok(c.post(f"/projects/{a['id']}/objects", json={"name": "Épée"}), 201)
    ch1 = _ok(c.post(f"/projects/{a['id']}/chapters", json={"title": "Un"}), 201)
    ch2 = _ok(c.post(f"/projects/{a['id']}/chapters", json={"title": "Deux"}), 201)
    _ok(
        c.put(
            f"/chapters/{ch2['id']}/pages",
            json={"pages": [{"panels": [{"description": "a"}]}, {"panels": [{"description": "b"}]}]},
        )
    )
    _fill(
        comfy_dir,
        "lucius-et-stan/personnages/lucius/personnage-portrait/variante-1_00001_.png",
        "lucius-et-stan/personnages/stan/reference-3.png",
        "lucius-et-stan/objets/epee/reference-4.png",
        "lucius-et-stan/chapitre-01/page-01/case-01_00001_.png",
        "lucius-et-stan/chapitre-02/page-01/case-01_00001_.png",
        "lucius-et-stan/chapitre-02/page-02/case-01_00001_.png",
        "lucius-et-stan/style/essais/essai-1-1_00001_.png",
        "autre-serie/personnages/lucius/reference-1.png",
    )
    before = _files(comfy_dir)

    assert c.delete(f"/characters/{lucius['id']}").status_code == 204
    assert c.delete(f"/objects/{epee['id']}").status_code == 204
    gone = {f for f in before if "lucius-et-stan/personnages/lucius/" in f or "/objets/epee/" in f}
    assert _files(comfy_dir) == before - gone

    # Page retirée du chapitre 2 (la 2e), puis chapitre 1 supprimé.
    pages = _ok(c.get(f"/chapters/{ch2['id']}/pages"))
    _ok(
        c.put(
            f"/chapters/{ch2['id']}/pages",
            json={
                "pages": [{"id": pages[0]["id"], "panels": [{"id": pages[0]["panels"][0]["id"], "description": "a"}]}]
            },
        )
    )
    assert c.delete(f"/chapters/{ch1['id']}").status_code == 204
    gone |= {f for f in before if "chapitre-02/page-02" in f or "chapitre-01/" in f}
    assert _files(comfy_dir) == before - gone

    assert c.delete(f"/projects/{a['id']}").status_code == 204
    left = _files(comfy_dir)
    assert left == {f for f in before if "lucius-et-stan" not in f}
    assert {"output/mangaka/old/garde.png", "input/mangaka/old/garde.png"} <= left
    assert any("autre-serie/personnages/lucius" in f for f in left)
    assert c.get(f"/characters/{stan['id']}").status_code == 404
    assert _ok(c.get(f"/projects/{b['id']}"))["slug"] == "autre-serie"


def test_without_a_comfyui_folder_nothing_outside_data_is_deleted(
    make_client: Callable[..., TestClient], comfy_dir: Path, tmp_path: Path
) -> None:
    c = make_client(comfyui_dir=str(tmp_path / "absent"))
    health = _ok(c.get("/health"))["storage"]
    assert health["enabled"] is False and "introuvable" in health["warning"]
    s = _series(c, "Lucius et Stan")
    _fill(comfy_dir, "lucius-et-stan/chapitre-01/page-01/case-01_00001_.png")
    before = _files(comfy_dir)
    assert c.delete(f"/projects/{s['id']}").status_code == 204
    assert _files(comfy_dir) == before
    cleanup = _ok(c.post(f"/projects/{_series(c, 'B')['id']}/cleanup"))
    assert cleanup["comfyui_cleaned"] is False and "introuvable" in cleanup["warning"]


def test_comfy_folders_refuse_anything_outside_a_series(comfy_dir: Path, tmp_path: Path) -> None:
    folders = ComfyFolders.from_settings(str(comfy_dir), provider="http")
    assert folders.enabled
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    (outside / "f.png").write_bytes(b"x")
    (comfy_dir / "output" / "mangaka" / "lien").symlink_to(outside)
    _fill(comfy_dir, "serie/a.png")
    before = _files(comfy_dir)
    for segments in (
        ("old",),
        ("..",),
        ("serie", ".."),
        ("../serie",),
        ("lien",),
        ("serie/../old",),
        ("",),
        ("Serie",),
    ):
        assert folders.remove(*segments).removed == [], segments
    assert folders.remove().removed == []
    assert _files(comfy_dir) == before and (outside / "f.png").exists()
    # Sortie effacée seulement dans une série, jamais dans old/ ni ailleurs.
    assert not folders.discard_output(ImageRef("garde.png", "mangaka/old", "output"))
    assert not folders.discard_output(ImageRef("f.png", "mangaka/lien", "output"))
    assert not folders.discard_output(ImageRef("a.png", "mangaka/serie", "input"))
    assert not folders.discard_output(ImageRef("../old/garde.png", "mangaka/serie", "output"))
    assert folders.discard_output(ImageRef("a.png", "mangaka/serie", "output"))
    assert not (comfy_dir / "output" / "mangaka" / "serie" / "a.png").exists()
    assert (comfy_dir / "input" / "mangaka" / "serie" / "a.png").exists()


def test_comfy_folder_setting(tmp_path: Path) -> None:
    assert not ComfyFolders.from_settings(None, provider="mock").enabled
    assert ComfyFolders.from_settings(None, provider="mock").warning() is None  # mock : rien à nettoyer
    assert "vide" in (ComfyFolders.from_settings("", provider="http").warning() or "")
    assert "introuvable" in (ComfyFolders.from_settings(str(tmp_path / "x"), provider="http").warning() or "")
    (tmp_path / "pas-comfy").mkdir()
    assert "ComfyUI" in (ComfyFolders.from_settings(str(tmp_path / "pas-comfy"), provider="http").warning() or "")
    assert "absolu" in (ComfyFolders.from_settings("ComfyUI", provider="http").warning() or "")


# --- variantes non retenues -----------------------------------------------------------------
def test_unkept_variants_are_capped_and_cleaned(make_client: Callable[..., TestClient]) -> None:
    c = make_client(reference_variants_kept=2)
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius", "visual_description": "roux"}), 201)
    url = f"/characters/{lucius['id']}/reference-variants"
    _ok(c.post(url, json={"sheet": "personnage-portrait", "count": 2}), 202)
    _idle(c)
    first = _ok(c.get(url))["variants"]
    kept = _ok(c.post(f"/reference-variants/{first[-1]['id']}/keep"), 201)
    _ok(c.post(url, json={"sheet": "personnage-portrait", "count": 3}), 202)
    _ok(c.post(url, json={"sheet": "personnage-expressions", "count": 1}), 202)
    _idle(c)
    variants = _ok(c.get(url))["variants"]
    # Au plus 2 non gardées par type de fiche, plus la gardée.
    portrait = [v for v in variants if v["sheet"] == "personnage-portrait"]
    assert len([v for v in portrait if not v["kept"]]) == 2 and any(v["kept"] for v in portrait)
    assert c.get(first[0]["url"]).status_code == 404  # la plus ancienne non gardée est effacée

    out = _ok(c.post(f"/projects/{s['id']}/cleanup"))
    assert out["variants_deleted"] == 3 and out["comfyui_cleaned"] is True and out["warning"] is None
    variants = _ok(c.get(url))["variants"]
    assert [v["kept"] for v in variants] == [True]
    # Références gardées intactes.
    [image] = _ok(c.get(f"/characters/{lucius['id']}"))["reference_images"]
    assert image["id"] == kept["reference_images"][0]["id"] and c.get(image["url"]).status_code == 200


# --- migration v23 → v24 --------------------------------------------------------------------
def test_v23_database_gets_slugs_and_never_reused_ids(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        a = _series(c, "Lucius et Stan")
        b = _series(c, "Lucius et Stan")
        _ok(c.post(f"/projects/{a['id']}/characters", json={"name": "Lucius"}), 201)
        _ok(c.post(f"/projects/{a['id']}/characters", json={"name": "Lucius"}), 201)
        _ok(c.post(f"/projects/{a['id']}/decors", json={"name": "Forêt"}), 201)
        ch = _ok(c.post(f"/projects/{a['id']}/chapters", json={"title": "Un"}), 201)
    con = sqlite3.connect(settings.database_path)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("PRAGMA legacy_alter_table=ON")  # les clés étrangères des autres tables gardent leur cible
    for table in ("projects", "chapters", "pages"):
        [(sql,)] = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchall()
        con.execute(f'ALTER TABLE "{table}" RENAME TO "{table}__v23"')
        con.execute(sql.replace(" AUTOINCREMENT", ""))
        con.execute(f'INSERT INTO "{table}" SELECT * FROM "{table}__v23"')
        con.execute(f'DROP TABLE "{table}__v23"')
        con.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    for table in ("projects", "characters", "series_assets"):
        con.execute(f"UPDATE {table} SET slug = ''")
    con.execute("PRAGMA user_version = 23")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        assert [_ok(c.get(f"/projects/{p['id']}"))["slug"] for p in (a, b)] == ["lucius-et-stan", "lucius-et-stan-2"]
        assert [x["slug"] for x in _ok(c.get(f"/projects/{a['id']}/characters"))] == ["lucius", "lucius-2"]
        assert _ok(c.get(f"/projects/{a['id']}/decors"))[0]["slug"] == "foret"
        assert c.delete(f"/projects/{b['id']}").status_code == 204
        assert _series(c, "Nouvelle")["id"] > b["id"]
        assert c.delete(f"/chapters/{ch['id']}").status_code == 204
        assert _ok(c.post(f"/projects/{a['id']}/chapters", json={"title": "Deux"}), 201)["id"] > ch["id"]
    assert _version(settings.database_path) == SCHEMA_VERSION
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()
    assert _columns(settings.database_path) == _columns(fresh)
    con = sqlite3.connect(settings.database_path)
    for table in ("projects", "chapters", "pages"):
        [(sql,)] = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchall()
        assert "AUTOINCREMENT" in sql, table
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()
