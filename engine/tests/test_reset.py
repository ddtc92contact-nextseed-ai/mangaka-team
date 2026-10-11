"""Remise à zéro de l'atelier : sauvegarde d'abord, séries et fichiers effacés, réglages gardés (sauf --all),
refus pendant un job, suppressions confinées (liens symboliques, noms `..`), CLI."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine import reset as reset_mod
from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import Base, Job, JobStatus
from tests.conftest import STYLE, png_bytes


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def comfy_dir(tmp_path: Path) -> Path:
    """Faux ComfyUI avec `mangaka/old/` (jamais touché), un ancien dossier par id et un fichier hors mangaka/."""
    root = tmp_path / "ComfyUI"
    for area in ("input", "output"):
        base = root / area / "mangaka"
        (base / "old").mkdir(parents=True)
        (base / "old" / "garde.png").write_bytes(b"x")
        (base / "serie-1" / "chapitre-1").mkdir(parents=True)
        (base / "serie-1" / "chapitre-1" / "case.png").write_bytes(b"x")
        (base / "lucius-et-stan" / "personnages").mkdir(parents=True)
        (base / "a-plat.png").write_bytes(b"x")
        (root / area / "autre.png").write_bytes(b"x")
    return root


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(**overrides: Any) -> TestClient:
        client = TestClient(create_app(make_settings(**overrides)))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def _settings(c: TestClient) -> Settings:
    return c.app.state.ctx.settings  # type: ignore[attr-defined,no-any-return]


def _populate(c: TestClient) -> dict[str, Any]:
    """Une série avec personnage (+ image), chapitre, savoir-faire et réglage d'agent de série ; plus un
    réglage global d'agent et une collection globale de savoir-faire."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Lucius et Stan"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    _ok(c.post(f"/characters/{ch['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    _ok(c.post(f"/projects/{s['id']}/chapters", json={"synopsis": "Un départ.", "target_page_count": 1}), 201)
    glob = _ok(c.post("/knowledge/collections", json={"name": "Méthode globale"}), 201)
    _ok(
        c.post(f"/knowledge/collections/{glob['id']}/documents", json={"title": "Rythme", "content": "kamishibai"}), 201
    )
    _ok(c.post("/knowledge/collections", json={"name": "Notes de série", "project_id": s["id"]}), 201)
    _ok(c.put("/agents/scenariste/profile", json={"values": {"temperature": 0.3}}))
    _ok(c.put(f"/agents/scenariste/profile?project_id={s['id']}", json={"values": {"temperature": 0.5}}))
    return s


def _count(db: Path, table: str, where: str = "") -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0])
    finally:
        conn.close()


def _reset(c: TestClient, **body: Any) -> httpx.Response:
    return c.post("/reset", json={"confirm": "RÉINITIALISER", **body})


def test_every_table_is_either_wiped_or_kept() -> None:
    """Une nouvelle table doit être classée : effacée avec les séries, ou réglage global gardé."""
    tables = set(Base.metadata.tables)
    assert tables == set(reset_mod.SERIES_TABLES) | set(reset_mod.GLOBAL_TABLES)


def test_reset_wipes_series_keeps_settings_and_backs_up(
    make_client: Callable[..., TestClient], comfy_dir: Path
) -> None:
    c = make_client(comfyui_dir=str(comfy_dir))
    settings = _settings(c)
    s = _populate(c)
    data = settings.data_dir
    assert (data / "projects" / str(s["id"])).is_dir()
    (data / "backups" / "ancienne").mkdir(parents=True)
    (data / "backups" / "ancienne" / "garde.txt").write_text("x")

    out = _ok(_reset(c))
    assert out["series_deleted"] == 1 and out["all"] is False
    assert "projects" in out["data_removed"]
    assert out["comfyui_warning"] is None
    assert "output/mangaka/serie-1" in out["comfyui_removed"]

    db = settings.database_path
    for table in reset_mod.SERIES_TABLES:
        assert _count(db, table) == 0, table
    # Réglages globaux et savoir-faire de l'équipe gardés, ceux de la série partis.
    assert _count(db, "agent_profiles") == 1
    assert _count(db, "agent_profiles", "WHERE project_id IS NOT NULL") == 0
    assert _count(db, "knowledge_collections") == 1
    assert _count(db, "knowledge_documents") == 1
    assert _count(db, "knowledge_chunks") >= 1
    temp = next(x for x in c.get("/agents/scenariste").json()["settings"] if x["key"] == "temperature")
    assert (temp["value"], temp["origin"]) == (0.3, "global")

    # Fichiers : data/ vidé sauf la base et backups/ ; ComfyUI vidé sauf old/ (et hors mangaka/).
    assert sorted(p.name for p in data.iterdir() if not p.name.startswith("mangaka.db")) == ["backups"]
    assert (data / "backups" / "ancienne" / "garde.txt").exists()
    for area in ("input", "output"):
        assert sorted(p.name for p in (comfy_dir / area / "mangaka").iterdir()) == ["old"]
        assert (comfy_dir / area / "mangaka" / "old" / "garde.png").exists()
        assert (comfy_dir / area / "autre.png").exists()

    # Sauvegarde : base cohérente avec la série d'avant, archive de data/ sans les sauvegardes.
    backup = Path(out["backup"])
    assert backup.parent == data / "backups" and backup.name.startswith("reset-")
    conn = sqlite3.connect(backup / "mangaka.db")
    assert conn.execute("SELECT title FROM projects").fetchall() == [("Lucius et Stan",)]
    conn.close()
    with tarfile.open(backup / "data.tar.gz") as tar:
        names = tar.getnames()
    assert any(n.startswith(f"projects/{s['id']}/characters/") for n in names)
    assert not any(n.startswith("backups") or n.startswith("mangaka.db") for n in names)

    # Après : liste vide, schéma à jour, ids repartis de 1.
    assert _ok(c.get("/projects")) == []
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
    again = _ok(c.post("/projects", json={**STYLE, "title": "Nouvelle"}), 201)
    assert again["id"] == 1 and again["slug"] == "nouvelle"


def test_app_restarts_on_an_empty_series_list(
    make_client: Callable[..., TestClient], make_settings: Callable[..., Settings]
) -> None:
    c = make_client()
    _populate(c)
    _ok(_reset(c))
    c.__exit__(None, None, None)
    with TestClient(create_app(make_settings())) as fresh:
        assert _ok(fresh.get("/projects")) == []
        assert _ok(fresh.get("/health"))["engine"]["status"] == "ok"


def test_all_resets_global_settings_and_savoir_faire(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    _populate(c)
    out = _ok(_reset(c, all=True))
    assert out["all"] is True
    db = _settings(c).database_path
    for table in reset_mod.GLOBAL_TABLES:
        assert _count(db, table) == 0, table
    assert _count(db, "knowledge_fts") == 0
    temp = next(x for x in c.get("/agents/scenariste").json()["settings"] if x["key"] == "temperature")
    assert temp["origin"] == "preset"
    assert _ok(c.get("/knowledge/collections")) == []


def test_mock_mode_without_comfyui_dir_skips_comfyui_and_says_so(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    _populate(c)
    out = _ok(_reset(c))
    assert out["comfyui_removed"] == []
    assert "COMFYUI_DIR" in out["comfyui_warning"]


def test_missing_comfyui_dir_is_skipped(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    c = make_client(comfyui_dir=str(tmp_path / "nulle-part"))
    out = _ok(_reset(c))
    assert "introuvable" in out["comfyui_warning"]


def test_confirmation_word_is_required(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    _populate(c)
    r = c.post("/reset", json={"confirm": "oui"})
    assert r.status_code == 422
    assert "RÉINITIALISER" in r.json()["errors"][0]["message"]
    assert len(_ok(c.get("/projects"))) == 1
    assert not (_settings(c).data_dir / "backups").exists()


def test_reset_refused_while_a_job_is_running(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    s = _populate(c)
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        session.add(Job(project_id=s["id"], step="generation", status=JobStatus.running))
        session.commit()
    r = _reset(c)
    assert r.status_code == 409
    assert "en cours" in r.json()["detail"] and "refusée" in r.json()["detail"]
    assert len(_ok(c.get("/projects"))) == 1
    assert not (_settings(c).data_dir / "backups").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root écrit partout")
def test_backup_failure_deletes_nothing(make_client: Callable[..., TestClient], comfy_dir: Path) -> None:
    c = make_client(comfyui_dir=str(comfy_dir))
    s = _populate(c)
    data = _settings(c).data_dir
    backups = data / "backups"
    backups.mkdir()
    backups.chmod(0o500)
    try:
        r = _reset(c)
    finally:
        backups.chmod(0o700)
    assert r.status_code == 500
    assert "sauvegarde impossible" in r.json()["detail"] and "rien n'a été supprimé" in r.json()["detail"]
    assert len(_ok(c.get("/projects"))) == 1
    assert (data / "projects" / str(s["id"])).is_dir()
    assert (comfy_dir / "output" / "mangaka" / "serie-1").is_dir()
    assert list(backups.iterdir()) == []


def test_symlinks_are_removed_without_following_them(
    make_client: Callable[..., TestClient], comfy_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "dehors"
    outside.mkdir()
    (outside / "precieux.png").write_bytes(b"x")
    (comfy_dir / "output" / "mangaka" / "lien").symlink_to(outside, target_is_directory=True)
    (comfy_dir / "output" / "mangaka" / "serie-1" / "lien-interne").symlink_to(outside, target_is_directory=True)
    c = make_client(comfyui_dir=str(comfy_dir))
    data = _settings(c).data_dir
    (data / "lien-data").symlink_to(outside, target_is_directory=True)
    _populate(c)
    _ok(_reset(c))
    assert (outside / "precieux.png").exists()
    assert not (comfy_dir / "output" / "mangaka" / "lien").exists()
    assert not (data / "lien-data").is_symlink()


def test_symlinked_mangaka_folder_is_left_alone(comfy_dir: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "ailleurs"
    (elsewhere / "serie").mkdir(parents=True)
    out = comfy_dir / "output" / "mangaka"
    shutil.rmtree(out)
    out.symlink_to(elsewhere, target_is_directory=True)
    removed, warning = reset_mod.wipe_comfyui(comfy_dir)
    assert (elsewhere / "serie").is_dir()
    assert warning and "lien symbolique" in warning
    assert all(r.startswith("input/") for r in removed)


@pytest.mark.parametrize("name", ["..", ".", "", "../data", "a/b", "a\\b"])
def test_unsafe_names_are_refused(tmp_path: Path, name: str) -> None:
    parent = tmp_path / "mangaka"
    parent.mkdir()
    (tmp_path / "voisin.png").write_bytes(b"x")
    with pytest.raises(reset_mod.UnsafePathError):
        reset_mod.remove_child(parent, name)
    assert (tmp_path / "voisin.png").exists() and parent.is_dir()


def test_cli_requires_confirmation_and_resets(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        _populate(c)
    monkeypatch.setattr(reset_mod, "get_settings", lambda: settings)

    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(reset_mod.sys, "stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda _prompt: "non")
    assert reset_mod.main([]) == 1
    assert _count(settings.database_path, "projects") == 1

    monkeypatch.setattr("builtins.input", lambda _prompt: "RÉINITIALISER")
    assert reset_mod.main(["--all"]) == 0
    out = capsys.readouterr().out
    assert "Sauvegarde :" in out and "Atelier remis à zéro" in out
    assert _count(settings.database_path, "projects") == 0
    assert _count(settings.database_path, "agent_profiles") == 0


def test_cli_outside_a_terminal_needs_yes(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings()
    monkeypatch.setattr(reset_mod, "get_settings", lambda: settings)

    class _Pipe:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(reset_mod.sys, "stdin", _Pipe())
    assert reset_mod.main([]) == 2
    assert reset_mod.main(["--yes"]) == 0
