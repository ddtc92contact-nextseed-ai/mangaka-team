"""Suppression de chapitres (un ou plusieurs) : le reste de la série ne bouge pas — ADN, fiches et leurs références,
variantes gardées, décors, objets, charte de couverture, palette, tomes —, la bible perd les résumés des chapitres
supprimés, les dossiers `chapitre-NN` de ComfyUI partent (jamais `old/`), et un travail en cours bloque."""

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
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.models import Job, JobStatus, Project, ReferenceVariant, SeriesBible
from tests.conftest import STYLE, png_bytes
from tests.test_cover_charter import PALETTE

# Tables d'un chapitre : le reste (série, fiches, variantes, tomes, couvertures, charte, savoir…) doit rester identique.
CHAPTER_TABLES = {
    "chapters",
    "chapter_scenes",
    "volume_chapters",
    "pages",
    "panels",
    "panel_dialog_turns",
    "panel_images",
    "panel_image_annotations",
    "bubbles",
    "jobs",
    "series_bibles",
    "page_directions",
    "page_name_validations",
    "chapter_crowd_marks",
    "qc_bench_runs",
    "llm_runs",
    "generation_events",
    "sqlite_sequence",
}


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def comfy_dir(tmp_path: Path) -> Path:
    root = tmp_path / "ComfyUI"
    for area in ("input", "output"):
        (root / area / "mangaka" / "old" / "chapitre-01").mkdir(parents=True)
        (root / area / "mangaka" / "old" / "chapitre-01" / "garde.png").write_bytes(b"x")
    return root


@pytest.fixture
def settings(make_settings: Callable[..., Settings], comfy_dir: Path) -> Settings:
    return make_settings(comfyui_dir=str(comfy_dir))


@pytest.fixture
def c(settings: Settings, comfy_dir: Path) -> Iterator[TestClient]:
    providers = Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=MockComfyUIClient(root=comfy_dir),
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(settings, providers=providers)) as client:
        yield client


def _idle(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(15)  # type: ignore[attr-defined]


def _db(c: TestClient) -> Any:
    return c.app.state.ctx.db.session_scope()  # type: ignore[attr-defined]


def _tables(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    con = sqlite3.connect(path)
    names = [n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out = {n: sorted(con.execute(f'SELECT * FROM "{n}"').fetchall(), key=repr) for n in names}
    con.close()
    return out


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _dirs(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()}


def _series(c: TestClient, title: str) -> dict[str, Any]:
    return _ok(c.post("/projects", json={**STYLE, "title": title}), 201)


def _chapter(c: TestClient, series_id: int, title: str, pages: int) -> dict[str, Any]:
    ch = _ok(c.post(f"/projects/{series_id}/chapters", json={"title": title}), 201)
    body = {"pages": [{"panels": [{"description": f"{title} {i}", "characters": ["Lucius"]}]} for i in range(pages)]}
    _ok(c.put(f"/chapters/{ch['id']}/pages", json=body))
    return ch


def _full_series(c: TestClient) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    _ok(c.post(f"/characters/{lucius['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    _ok(c.post(f"/projects/{s['id']}/objects", json={"name": "Épée"}), 201)
    decor = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "Forêt"}), 201)
    _ok(c.post(f"/projects/{s['id']}/locations", json={"name": "La forêt", "decor": decor["id"]}), 201)
    _ok(c.put(f"/projects/{s['id']}/identity/palette", json=PALETTE))
    _ok(c.put(f"/projects/{s['id']}/cover-charter", json={"shot": "portrait", "character_ids": [lucius["id"]]}))
    chapters = [_chapter(c, s["id"], title, n) for title, n in (("Un", 2), ("Deux", 1), ("Trois", 2))]
    volume = _ok(c.post(f"/projects/{s['id']}/volumes", json={"chapter_ids": [ch["id"] for ch in chapters]}), 201)
    for ch in chapters:
        [panel, *_] = _ok(c.get(f"/chapters/{ch['id']}/pages"))[0]["panels"]
        _ok(c.post(f"/panels/{panel['id']}/generate"), 202)
    _idle(c)
    with _db(c) as session:
        project = session.get(Project, s["id"])
        project.pre_direction = {"shots": {"wide": {"min": 2}}}  # ADN ajusté par la série
        session.add(
            ReferenceVariant(
                project_id=s["id"],
                entry_kind="character",
                entry_id=lucius["id"],
                sheet="personnage-portrait",
                path=f"projects/{s['id']}/variants/v.png",
                content_type="image/png",
                width=64,
                height=48,
                kept_image_id=1,
            )
        )
        session.add(
            SeriesBible(
                project_id=s["id"],
                world="Un monde de dragons",
                character_notes={str(lucius["id"]): "têtu"},
                chapter_summaries=[
                    {"chapter_id": ch["id"], "number": ch["number"], "title": ch["title"], "summary": f"Résumé {i}"}
                    for i, ch in enumerate(chapters, start=1)
                ],
            )
        )
        session.commit()
    return s, chapters, volume


def test_deleting_two_of_three_chapters_keeps_the_series(c: TestClient, settings: Settings, comfy_dir: Path) -> None:
    s, (one, two, three), volume = _full_series(c)
    other = _series(c, "Autre série")
    _chapter(c, other["id"], "Ailleurs", 1)
    data_dir = settings.data_dir
    three_pages = _ok(c.get(f"/chapters/{three['id']}/pages"))
    three_images = _ok(c.get(f"/panels/{three_pages[0]['panels'][0]['id']}/images"))
    assert three_images
    before = _tables(settings.database_path)
    comfy_before, data_before = _files(comfy_dir), _files(data_dir)
    assert any("lucius-et-stan/chapitre-01/" in f for f in comfy_before)
    assert any("lucius-et-stan/chapitre-03/" in f for f in comfy_before)

    assert (
        c.post(f"/projects/{s['id']}/chapters/delete", json={"chapter_ids": [one["id"], two["id"]]}).status_code == 204
    )

    after = _tables(settings.database_path)
    for table in before.keys() - CHAPTER_TABLES:
        assert after[table] == before[table], table
    # Le troisième chapitre, ses pages, cases et images restent ; il garde son numéro.
    assert [(ch["id"], ch["number"]) for ch in _ok(c.get(f"/projects/{s['id']}/chapters"))] == [(three["id"], 3)]
    assert _ok(c.get(f"/chapters/{three['id']}/pages")) == three_pages
    assert _ok(c.get(f"/panels/{three_pages[0]['panels'][0]['id']}/images")) == three_images
    assert c.get(three_images[0]["url"]).status_code == 200
    for gone in (one, two):
        assert c.get(f"/chapters/{gone['id']}").status_code == 404
    # Le tome reste, avec le seul troisième chapitre.
    assert [ch["id"] for ch in _ok(c.get(f"/volumes/{volume['id']}"))["chapters"]] == [three["id"]]
    # Bible : seul le résumé du troisième chapitre reste, le reste de la bible ne bouge pas.
    with _db(c) as session:
        bible = session.query(SeriesBible).filter_by(project_id=s["id"]).one()
        assert [e["chapter_id"] for e in bible.chapter_summaries] == [three["id"]]
        assert bible.world == "Un monde de dragons" and bible.character_notes
    # Fichiers : seuls ceux des chapitres 1 et 2 partent ; `old/` et la série restent ; pas de dossier vide.
    comfy_after = _files(comfy_dir)
    gone_comfy = {f for f in comfy_before if "lucius-et-stan/" in f and ("chapitre-01" in f or "chapitre-02" in f)}
    assert gone_comfy and comfy_after == comfy_before - gone_comfy
    assert {"output/mangaka/old/chapitre-01/garde.png", "input/mangaka/old/chapitre-01/garde.png"} <= comfy_after
    assert not [d for d in _dirs(comfy_dir) if not any((comfy_dir / d).iterdir())]
    data_after = _files(data_dir)
    for gone in (one, two):
        prefix = f"projects/{s['id']}/chapters/{gone['id']}/"
        assert not any(f.startswith(prefix) for f in data_after)
        assert not (data_dir / "projects" / str(s["id"]) / "chapters" / str(gone["id"])).exists()
    kept_data = {f for f in data_before if f"chapters/{one['id']}/" not in f and f"chapters/{two['id']}/" not in f}
    assert kept_data <= data_after

    # Un nouveau chapitre prend la suite (pas de collision de numéro).
    new = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Quatre"}), 201)
    assert new["number"] == 4 and new["id"] > three["id"]


def test_single_delete_also_drops_the_bible_summary(c: TestClient) -> None:
    s, (one, two, three), volume = _full_series(c)
    assert c.delete(f"/chapters/{two['id']}").status_code == 204
    with _db(c) as session:
        bible = session.query(SeriesBible).filter_by(project_id=s["id"]).one()
        assert [e["chapter_id"] for e in bible.chapter_summaries] == [one["id"], three["id"]]
    assert [ch["id"] for ch in _ok(c.get(f"/volumes/{volume['id']}"))["chapters"]] == [one["id"], three["id"]]
    assert [ch["number"] for ch in _ok(c.get(f"/projects/{s['id']}/chapters"))] == [1, 3]


@pytest.mark.parametrize("status", [JobStatus.pending, JobStatus.running])
def test_a_chapter_with_a_queued_or_running_job_is_refused(c: TestClient, status: JobStatus) -> None:
    s = _series(c, "Lucius et Stan")
    one = _chapter(c, s["id"], "Un", 1)
    two = _chapter(c, s["id"], "Deux", 1)
    with _db(c) as session:
        session.add(Job(project_id=s["id"], chapter_id=two["id"], step="generation", status=status))
        session.commit()

    r = c.post(f"/projects/{s['id']}/chapters/delete", json={"chapter_ids": [one["id"], two["id"]]})
    assert r.status_code == 409
    assert "chapitre 2 « Deux »" in r.json()["detail"] and "génération" in r.json()["detail"]
    assert c.delete(f"/chapters/{two['id']}").status_code == 409
    # Tout ou rien : le chapitre 1 n'a pas été supprimé.
    assert [ch["id"] for ch in _ok(c.get(f"/projects/{s['id']}/chapters"))] == [one["id"], two["id"]]

    with _db(c) as session:
        session.query(Job).filter_by(chapter_id=two["id"]).update({"status": JobStatus.succeeded})
        session.commit()
    assert c.post(f"/projects/{s['id']}/chapters/delete", json={"chapter_ids": [two["id"]]}).status_code == 204


def test_a_chapter_of_another_series_is_refused(c: TestClient) -> None:
    a = _series(c, "Lucius et Stan")
    b = _series(c, "Autre série")
    mine = _chapter(c, a["id"], "Un", 1)
    theirs = _chapter(c, b["id"], "Ailleurs", 1)

    r = c.post(f"/projects/{a['id']}/chapters/delete", json={"chapter_ids": [mine["id"], theirs["id"]]})
    assert r.status_code == 422 and "cette série" in r.text
    assert c.post(f"/projects/{a['id']}/chapters/delete", json={"chapter_ids": [999]}).status_code == 422
    assert c.post(f"/projects/{a['id']}/chapters/delete", json={"chapter_ids": []}).status_code == 422
    assert c.post("/projects/999/chapters/delete", json={"chapter_ids": [mine["id"]]}).status_code == 404
    assert len(_ok(c.get(f"/projects/{a['id']}/chapters"))) == 1
    assert len(_ok(c.get(f"/projects/{b['id']}/chapters"))) == 1
