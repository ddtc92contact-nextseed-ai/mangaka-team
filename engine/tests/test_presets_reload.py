"""« Recharger les flux » (Réglages) : `POST /presets/reload` relit presets/ sans redémarrer le moteur.

Le registre est remplacé sur place : exécuteurs, agents et savoir-faire voient les nouveaux flux. Refusé (409)
pendant un job de la file ComfyUI. Tout est simulé, sur une copie temporaire de presets/.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.conftest import PRESETS_DIR
from tests.test_generation import GatedComfy, _ok, _wait, make_client, setup_chapter  # noqa: F401 — fixture

WORKFLOWS = "workflows"


@pytest.fixture
def presets_copy(tmp_path: Path) -> Path:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    return root


def _add_workflow(root: Path, new_id: str, **changes: Any) -> None:
    """Nouveau flux FLUX 3 Klein, copié de flux3-klein-qualite (même JSON), sans palier ni liens."""
    data = yaml.safe_load((root / WORKFLOWS / "flux3-klein-qualite.yaml").read_text(encoding="utf-8"))
    for key in ("tier", "with_references", "from_sketch", "sketch", "quality"):
        data.pop(key, None)
    data.update(id=new_id, name=f"Essai {new_id}", **changes)
    (root / WORKFLOWS / f"{new_id}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _ids(c: TestClient) -> set[str]:
    return {w["id"] for w in _ok(c.get("/presets"))["workflows"]}


def test_added_workflow_appears_after_reload(make_client: Callable[..., TestClient], presets_copy: Path) -> None:  # noqa: F811
    c = make_client(mangaka_presets_dir=presets_copy)
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    before = len(ctx.presets.workflows)
    _add_workflow(presets_copy, "flux3-klein-essai")
    assert "flux3-klein-essai" not in _ids(c)  # rien ne change sans rechargement

    out = _ok(c.post("/presets/reload"))
    assert out["workflows"] == before + 1
    assert out["issues"] == []
    flux = next(e for e in out["engines"] if e["engine"] == "flux3-klein")
    assert flux["name"] == "FLUX 3 Klein" and flux["workflows"] == 7
    assert "flux3-klein-essai" in _ids(c)
    # Propagé partout : même registre pour les exécuteurs, presets effectifs des agents recalculés.
    assert "flux3-klein-essai" in ctx.agents.presets_for(None).workflows
    assert ctx.knowledge.settings is ctx.presets.knowledge


def test_invalid_workflow_is_reported_without_dropping_others(
    make_client: Callable[..., TestClient],  # noqa: F811
    presets_copy: Path,
) -> None:
    c = make_client(mangaka_presets_dir=presets_copy)
    _add_workflow(presets_copy, "flux3-klein-bon")
    _add_workflow(presets_copy, "flux3-klein-casse", workflow_file="introuvable.json")

    out = _ok(c.post("/presets/reload"))
    assert len(out["issues"]) == 1
    issue = out["issues"][0]
    assert issue["file"] == "workflows/flux3-klein-casse.yaml"
    assert "introuvable.json" in issue["message"]
    ids = _ids(c)
    assert "flux3-klein-bon" in ids and "flux3-klein-casse" not in ids
    assert "qwen-image-turbo" in ids and out["workflows"] == len(ids)


def test_reload_refused_while_a_generation_runs(make_client: Callable[..., TestClient], presets_copy: Path) -> None:  # noqa: F811
    comfy = GatedComfy()
    c = make_client(comfy, mangaka_presets_dir=presets_copy)
    data = setup_chapter(c)
    panel = data["panels"][0]
    _ok(c.post(f"/panels/{panel['id']}/generate", json={"count": 1}), 202)
    assert comfy.started.acquire(timeout=5)
    _add_workflow(presets_copy, "flux3-klein-pendant")

    r = c.post("/presets/reload")
    assert r.status_code == 409
    assert r.json()["detail"].startswith("Une génération est en cours")
    assert "flux3-klein-pendant" not in _ids(c)  # rien n'a été relu

    comfy.gate.set()
    _wait(c)
    _ok(c.post("/presets/reload"))  # file vide : accepté
    assert "flux3-klein-pendant" in _ids(c)


def test_switching_a_panel_engine_keeps_every_version(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    """« Cette case passe mal, je la refais sur l'autre moteur » : seul le flux de la case change."""
    c = make_client()
    data = setup_chapter(c)
    p1, p2 = data["panels"][0], data["panels"][1]
    for p in (p1, p2):
        _ok(c.post(f"/panels/{p['id']}/generate", json={"count": 1}), 202)
    _wait(c)
    before = {p["id"]: _ok(c.get(f"/panels/{p['id']}/images")) for p in (p1, p2)}
    assert all(len(images) == 1 for images in before.values())

    panel = _ok(c.patch(f"/panels/{p1['id']}", json={"generation_preset": "flux3-klein-edit-ref-qualite"}))
    assert panel["generation_preset"] == "flux3-klein-edit-ref-qualite"
    assert {p["id"]: _ok(c.get(f"/panels/{p['id']}/images")) for p in (p1, p2)} == before
    assert _ok(c.get(f"/panels/{p2['id']}"))["generation_preset"] is None
