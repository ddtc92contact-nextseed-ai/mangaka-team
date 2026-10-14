"""Bibliothèque lisible (`ComfyUI/output/mangaka/<série>/`) : aucun dossier créé d'avance ni laissé vide (un
sous-dossier par type de fiche dès qu'il contient une image), croquis retenu de chaque case, images gardées nommées d'après leur type, corbeille (`trash/`) de ce qui n'est pas
retenu, cases validées et choisies, planches, renommage, suppression, « Reconstruire » (conversion de l'ancienne
disposition à plat), idempotence, confinement. Faux ComfyUI sur disque (mock), aucun GPU."""

# ruff: noqa: F811 — fixtures du faux ComfyUI reprises de test_storage.py

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from mangaka_engine.pipeline.comfy_library import ComfyLibrary, sheet_folder
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.store.comfy_folders import ComfyFolders
from mangaka_engine.store.files import FileStore
from mangaka_engine.store.models import (
    AssetKind,
    PanelImage,
    Project,
    ReferenceVariant,
    SeriesAsset,
    SeriesAssetImage,
)
from tests.conftest import force_stages, png_bytes
from tests.test_storage import _files, _idle, _ok, _series, c, comfy, comfy_dir, make_client  # noqa: F401 — fixtures


def _lib(comfy_dir: Path, slug: str = "lucius-et-stan") -> Path:
    return comfy_dir / "output" / "mangaka" / slug


def _lib_files(comfy_dir: Path, slug: str = "lucius-et-stan") -> set[str]:
    """Fichiers retenus de la bibliothèque (hors transit et corbeille)."""
    root = _lib(comfy_dir, slug)
    return {f for f in _files(root) if not f.startswith(("_transit/", "trash/"))} if root.is_dir() else set()


def _trash(comfy_dir: Path, slug: str = "lucius-et-stan") -> set[str]:
    """Fichiers de la corbeille, relatifs à `trash/`."""
    root = _lib(comfy_dir, slug) / "trash"
    return _files(root) if root.is_dir() else set()


def _dirs(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()}


def _empty_dirs(root: Path) -> set[str]:
    """Dossiers vides sous `root` (compris)."""
    if not root.is_dir():
        return set()
    return {str(p.relative_to(root)) for p in [root, *root.rglob("*")] if p.is_dir() and not any(p.iterdir())}


def _wait_jobs(c: TestClient, jobs: list[Any]) -> None:
    jobs = [j for item in jobs for j in (item if isinstance(item, list) else [item])]
    _idle(c)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if all(_ok(c.get(f"/jobs/{j['id']}"))["status"] in ("succeeded", "failed") for j in jobs):
            return
        time.sleep(0.05)
    raise AssertionError("jobs pas finis")


# --- arborescence et fiches -----------------------------------------------------------------
def test_no_folder_is_created_in_advance(c: TestClient, comfy_dir: Path) -> None:
    """Une série, un personnage sans image, un chapitre : aucun dossier (vide) sous `output/mangaka/<série>/`."""
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    _ok(c.post(f"/projects/{s['id']}/objects", json={"name": "Épée de Feu"}), 201)
    _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "La Forêt"}), 201)
    _chapter(c, s)
    assert not _lib(comfy_dir).exists()
    assert not (comfy_dir / "input" / "mangaka" / "lucius-et-stan").exists()
    assert _ok(c.post(f"/projects/{s['id']}/library"))["written"] == 0
    assert not _lib(comfy_dir).exists()
    # Une image envoyée : seuls les dossiers qui la mènent existent.
    _ok(c.post(f"/characters/{lucius['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    assert _dirs(_lib(comfy_dir)) == {
        "references",
        "references/personnages",
        "references/personnages/lucius",
        "references/personnages/lucius/imports",
    }
    assert (comfy_dir / "output" / "mangaka" / "old" / "garde.png").exists()


def test_sheet_folder_follows_the_presets(tmp_path: Path) -> None:
    presets = PresetRegistry.load(Path(__file__).resolve().parents[2] / "presets")
    assert sheet_folder("personnage-portrait", presets) == "portrait"
    # Un nouveau type de fiche = un nouveau sous-dossier (son `folder`, sinon l'id sans la sorte).
    root = tmp_path / "presets"
    shutil.copytree(Path(__file__).resolve().parents[2] / "presets", root)
    sheet = (root / "reference_sheets" / "objet-trois-quarts.yaml").read_text(encoding="utf-8")
    (root / "reference_sheets" / "objet-eclate.yaml").write_text(
        sheet.replace("id: objet-trois-quarts", "id: objet-eclate").replace("order: 10", "order: 30"),
        encoding="utf-8",
    )
    loaded = PresetRegistry.load(root)
    assert "objet-eclate" in loaded.reference_sheets, loaded.issues
    assert sheet_folder("objet-eclate", loaded) == "eclate"


def test_kept_variants_go_to_their_type_folder_the_others_to_the_trash(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius", "visual_description": "roux"}), 201)
    folder = _lib(comfy_dir) / "references" / "personnages" / "lucius"
    jobs = _ok(
        c.post(f"/characters/{lucius['id']}/reference-variants", json={"sheet": "personnage-portrait", "count": 4}),
        202,
    )
    _wait_jobs(c, jobs)
    # Rien de gardé : les 4 variantes sont dans la corbeille, numérotées dans l'ordre de création.
    assert _lib_files(comfy_dir) == set()
    trash = "personnages/lucius/portrait/lucius-portrait"
    assert _trash(comfy_dir) == {f"{trash}-v{n}.png" for n in (1, 2, 3, 4)}

    variants = sorted(_ok(c.get(f"/characters/{lucius['id']}/reference-variants"))["variants"], key=lambda v: v["id"])
    _ok(c.post(f"/reference-variants/{variants[1]['id']}/keep"), 201)
    assert _lib_files(comfy_dir) == {"references/personnages/lucius/portrait/lucius-portrait.png"}
    assert _trash(comfy_dir) == {f"{trash}-v{n}.png" for n in (1, 3, 4)}
    images = _ok(c.get(f"/characters/{lucius['id']}"))["reference_images"]
    assert (folder / "portrait" / "lucius-portrait.png").read_bytes() == c.get(images[0]["url"]).content
    assert (_lib(comfy_dir) / "trash" / f"{trash}-v1.png").read_bytes() == c.get(variants[0]["url"]).content

    # Deuxième gardée → `-2` ; image envoyée à la main → imports/.
    _ok(c.post(f"/reference-variants/{variants[3]['id']}/keep"), 201)
    _ok(c.post(f"/characters/{lucius['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    assert _lib_files(comfy_dir) == {
        "references/personnages/lucius/portrait/lucius-portrait.png",
        "references/personnages/lucius/portrait/lucius-portrait-2.png",
        "references/personnages/lucius/imports/lucius-import.png",
    }
    assert _trash(comfy_dir) == {f"{trash}-v{n}.png" for n in (1, 3)}

    # Renommer le personnage déplace ses dossiers, corbeille comprise.
    _ok(c.patch(f"/characters/{lucius['id']}", json={"name": "Lucius le Grand"}))
    assert _lib_files(comfy_dir) == {
        "references/personnages/lucius-le-grand/portrait/lucius-le-grand-portrait.png",
        "references/personnages/lucius-le-grand/portrait/lucius-le-grand-portrait-2.png",
        "references/personnages/lucius-le-grand/imports/lucius-le-grand-import.png",
    }
    assert _trash(comfy_dir) == {
        f"personnages/lucius-le-grand/portrait/lucius-le-grand-portrait-v{n}.png" for n in (1, 3)
    }
    assert not folder.exists() and not (_lib(comfy_dir) / "trash" / "personnages" / "lucius").exists()

    # Retirer une image gardée (n'est plus retenue) : sa variante retourne à la corbeille.
    images = _ok(c.get(f"/characters/{lucius['id']}"))["reference_images"]
    assert c.delete(f"/characters/{lucius['id']}/images/{images[0]['id']}").status_code == 204
    assert _lib_files(comfy_dir) == {
        "references/personnages/lucius-le-grand/portrait/lucius-le-grand-portrait.png",
        "references/personnages/lucius-le-grand/imports/lucius-le-grand-import.png",
    }
    assert _trash(comfy_dir) == {
        f"personnages/lucius-le-grand/portrait/lucius-le-grand-portrait-v{n}.png" for n in (1, 2, 3)
    }

    # Supprimer le personnage supprime ses dossiers (corbeille comprise) et ne laisse aucun dossier vide.
    assert c.delete(f"/characters/{lucius['id']}").status_code == 204
    assert _files(_lib(comfy_dir)) == set()
    assert not _lib(comfy_dir).exists()
    assert not (comfy_dir / "input" / "mangaka" / "lucius-et-stan").exists()


def test_objects_decors_and_style_board(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    epee = _ok(c.post(f"/projects/{s['id']}/objects", json={"name": "Épée de Feu"}), 201)
    foret = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "La Forêt"}), 201)
    assert not _lib(comfy_dir).exists()
    _ok(c.post(f"/objects/{epee['id']}/images", files=[("files", ("e.png", png_bytes(), "image/png"))]), 201)
    jobs = _ok(c.post(f"/decors/{foret['id']}/reference-variants", json={"sheet": "decor-plan-large", "count": 1}), 202)
    _wait_jobs(c, jobs)
    [variant] = _ok(c.get(f"/decors/{foret['id']}/reference-variants"))["variants"]
    _ok(c.post(f"/reference-variants/{variant['id']}/keep", json={"accept_people": True}), 201)

    # Planche de style retenue (référence de style active), écrite comme le fait la planche de style.
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    stored = ctx.files.save_image(png_bytes(), f"projects/{s['id']}/style")
    with ctx.db.session_scope() as session:
        old = SeriesAsset(project_id=s["id"], kind=AssetKind.style, name="Ancienne", active=False)
        board = SeriesAsset(project_id=s["id"], kind=AssetKind.style, name="Planche", active=True)
        for asset in (old, board):
            asset.reference_images.append(
                SeriesAssetImage(path=stored.path, original_name="s.png", content_type="image/png", width=8, height=8)
            )
        session.add_all([old, board])
        session.commit()
    assert _lib_files(comfy_dir) == {
        "references/objets/epee-de-feu/imports/epee-de-feu-import.png",
        "references/decors/la-foret/plan-large/la-foret-plan-large.png",
        "references/style/planche-de-style.png",
    }
    # Ancienne référence de style (inactive) : dans la corbeille.
    assert _trash(comfy_dir) == {"style/planche-de-style-ancienne.png"}
    _ok(c.patch(f"/objects/{epee['id']}", json={"name": "Épée"}))
    assert "references/objets/epee/imports/epee-import.png" in _lib_files(comfy_dir)
    assert c.delete(f"/decors/{foret['id']}").status_code == 204
    assert not any(f.startswith("references/decors/la-foret") for f in _lib_files(comfy_dir))
    assert not (_lib(comfy_dir) / "references" / "decors").exists()
    assert _empty_dirs(_lib(comfy_dir)) == set()


# --- chapitres, cases, planches ---------------------------------------------------------------
def _chapter(c: TestClient, s: dict[str, Any], panels: int = 2) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={"pages": [{"panels": [{"description": f"case {i}"} for i in range(panels)]}]},
        )
    )
    return ch, pages


def test_validating_another_sketch_swaps_library_and_trash(c: TestClient, comfy_dir: Path) -> None:
    """Valider un croquis plus ancien que le dernier (« Valider ce croquis » des versions) remplace
    case-NN-croquis.png ; l'autre croquis passe dans la corbeille avec son numéro de version."""
    s = _series(c, "Lucius et Stan")
    _, [page] = _chapter(c, s)
    p1, _ = page["panels"]
    for _ in range(2):
        _wait_jobs(c, [_ok(c.post(f"/panels/{p1['id']}/sketch"), 202)[0]])
    s1, s2 = sorted(_ok(c.get(f"/panels/{p1['id']}/images")), key=lambda i: i["version"])
    sketch_file = _lib(comfy_dir) / "chapitre-01" / "page-01" / "case-01-croquis.png"
    for kept, other in ((s2, s1), (s1, s2), (s2, s1)):
        _ok(c.post(f"/panels/{p1['id']}/sketch/validate", json={"image_id": kept["id"]}))
        assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png"}
        assert sketch_file.read_bytes() == c.get(kept["url"]).content
        assert _trash(comfy_dir) == {f"chapitre-01/page-01/case-01-croquis-v{other['version']}.png"}


def test_panels_sketches_and_plates(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    ch, [page] = _chapter(c, s)
    page_dir = _lib(comfy_dir) / "chapitre-01" / "page-01"
    assert not _lib(comfy_dir).exists()  # aucun dossier d'avance
    p1, p2 = page["panels"]

    # Un seul croquis, validé ou non : c'est le croquis retenu, case-01-croquis.png.
    _wait_jobs(c, [_ok(c.post(f"/panels/{p1['id']}/sketch"), 202)[0]])
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png"}
    assert _trash(comfy_dir) == set()
    _ok(c.post(f"/panels/{p1['id']}/sketch/validate"))
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png"}
    _ok(c.delete(f"/panels/{p1['id']}/sketch/validate"))
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png"}
    assert _trash(comfy_dir) == set()

    # Version propre choisie → case-NN.png, les autres dans la corbeille ; changer de version les échange.
    for _ in range(2):
        _wait_jobs(c, [_ok(c.post(f"/panels/{p2['id']}/generate"), 202)])
    v1, v2 = sorted(_ok(c.get(f"/panels/{p2['id']}/images")), key=lambda i: i["version"])
    assert v1["selected"]
    case = page_dir / "case-02.png"
    trash = _lib(comfy_dir) / "trash" / "chapitre-01" / "page-01"
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png", "chapitre-01/page-01/case-02.png"}
    assert _trash(comfy_dir) == {f"chapitre-01/page-01/case-02-v{v2['version']}.png"}
    assert case.read_bytes() == c.get(v1["url"]).content
    _ok(c.post(f"/panel-images/{v2['id']}/select"))
    assert case.read_bytes() == c.get(v2["url"]).content
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png", "chapitre-01/page-01/case-02.png"}
    assert _trash(comfy_dir) == {f"chapitre-01/page-01/case-02-v{v1['version']}.png"}
    assert (trash / f"case-02-v{v1['version']}.png").read_bytes() == c.get(v1["url"]).content

    # Rendu de la page → planches/page-01.png + .svg.
    force_stages(c, ch["id"])
    _ok(c.post(f"/pages/{page['id']}/render"))
    assert _lib_files(comfy_dir) == {
        "chapitre-01/page-01/case-01-croquis.png",
        "chapitre-01/page-01/case-02.png",
        "chapitre-01/planches/page-01.png",
        "chapitre-01/planches/page-01.svg",
    }
    # Retirer une case (la page garde l'autre) : ses fichiers partent, aucun dossier vide ne reste.
    _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"id": p2["id"], "description": "case 1"}]}]}))
    assert "chapitre-01/page-01/case-01-croquis.png" not in _lib_files(comfy_dir)
    assert _empty_dirs(_lib(comfy_dir)) == set()
    # Supprimer le chapitre supprime son dossier (corbeille comprise) ; la série vide ne laisse aucun dossier.
    assert c.delete(f"/chapters/{ch['id']}").status_code == 204
    assert not (_lib(comfy_dir) / "chapitre-01").exists()
    assert not (_lib(comfy_dir) / "trash" / "chapitre-01").exists()
    assert not _lib(comfy_dir).exists()


def test_a_finished_panel_keeps_its_sketch_even_without_validation(c: TestClient, comfy_dir: Path) -> None:
    """Croquis retenu : le validé, sinon celui dont est issue la version choisie, sinon le plus récent — une case
    passée en finition sans valider son croquis a son case-NN-croquis.png à côté d'elle."""
    s = _series(c, "Lucius et Stan")
    _, [page] = _chapter(c, s, panels=1)
    panel = page["panels"][0]
    for _ in range(2):
        _wait_jobs(c, [_ok(c.post(f"/panels/{panel['id']}/sketch"), 202)[0]])
    _wait_jobs(c, [_ok(c.post(f"/panels/{panel['id']}/generate"), 202)])
    images = sorted(_ok(c.get(f"/panels/{panel['id']}/images")), key=lambda i: i["version"])
    s1, s2, final = images
    assert (s1["kind"], s2["kind"], final["kind"]) == ("croquis", "croquis", "final") and final["selected"]
    sketch = _lib(comfy_dir) / "chapitre-01" / "page-01" / "case-01-croquis.png"

    # Rien de validé : le plus récent.
    assert sketch.read_bytes() == c.get(s2["url"]).content
    assert _trash(comfy_dir) == {f"chapitre-01/page-01/case-01-croquis-v{s1['version']}.png"}

    # Version choisie issue du premier croquis, puis finalisée (agrandie) : c'est lui qui est montré.
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    finished = ctx.files.save_image(png_bytes(), f"projects/{s['id']}/finish")
    with ctx.db.session_scope() as session:
        image = session.get(PanelImage, final["id"])
        image.params = {**image.params, "sketch_image_id": s1["id"]}
        image.finish = {"path": finished.path, "width": 8, "height": 8}
        session.commit()
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png", "chapitre-01/page-01/case-01.png"}
    assert sketch.read_bytes() == c.get(s1["url"]).content
    assert (_lib(comfy_dir) / "chapitre-01" / "page-01" / "case-01.png").read_bytes() == png_bytes()
    assert _trash(comfy_dir) == {f"chapitre-01/page-01/case-01-croquis-v{s2['version']}.png"}

    # Un croquis validé passe avant tout.
    _ok(c.post(f"/panels/{panel['id']}/sketch/validate", json={"image_id": s2["id"]}))
    assert sketch.read_bytes() == c.get(s2["url"]).content


def test_chapter_export_writes_the_plates(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    ch, [page] = _chapter(c, s, panels=1)
    force_stages(c, ch["id"])
    job = _ok(c.post(f"/chapters/{ch['id']}/export", json={}), 202)
    _wait_jobs(c, [job])
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    assert {"chapitre-01/planches/page-01.png", "chapitre-01/planches/page-01.svg"} <= _lib_files(comfy_dir)


def test_raw_comfyui_outputs_go_to_transit_and_never_pollute_the_library(
    c: TestClient, comfy: MockComfyUIClient, comfy_dir: Path
) -> None:
    s = _series(c, "Lucius et Stan")
    _, [page] = _chapter(c, s, panels=1)
    _wait_jobs(c, [_ok(c.post(f"/panels/{page['panels'][0]['id']}/generate"), 202)])
    prefixes = {
        n["inputs"]["filename_prefix"]
        for wf in comfy.prompts.values()
        for n in wf.values()
        if "filename_prefix" in n["inputs"]
    }
    assert prefixes == {"mangaka/lucius-et-stan/_transit/chapitre-01/page-01/case-01"}
    assert _files(_lib(comfy_dir)) == {"chapitre-01/page-01/case-01.png"}  # transit vidé après copie


# --- reconstruire, idempotence, série supprimée ---------------------------------------------
def test_rebuild_regenerates_everything_and_is_idempotent(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    _ok(c.post(f"/characters/{lucius['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    _, [page] = _chapter(c, s, panels=1)
    _wait_jobs(c, [_ok(c.post(f"/panels/{page['panels'][0]['id']}/generate"), 202)])
    expected = {"references/personnages/lucius/imports/lucius-import.png", "chapitre-01/page-01/case-01.png"}
    assert _lib_files(comfy_dir) == expected

    again = _ok(c.post(f"/projects/{s['id']}/library"))
    assert again["enabled"] and (again["written"], again["removed"]) == (0, 0)  # rien à refaire
    assert again["folder"] == "output/mangaka/lucius-et-stan"
    assert again["path"] == str(comfy_dir / "output" / "mangaka" / "lucius-et-stan")

    # Bibliothèque effacée à la main, fichier abîmé, fichier en trop : tout est remis d'accord.
    shutil.rmtree(_lib(comfy_dir) / "references")
    (_lib(comfy_dir) / "chapitre-01" / "page-01" / "case-01.png").write_bytes(b"abime")
    (_lib(comfy_dir) / "chapitre-01" / "page-01" / "case-07.png").write_bytes(b"plus retenue")
    rebuilt = _ok(c.post(f"/projects/{s['id']}/library"))
    assert (rebuilt["written"], rebuilt["removed"]) == (2, 1)
    assert _lib_files(comfy_dir) == expected
    assert _empty_dirs(_lib(comfy_dir)) == set()
    before = {p: (_lib(comfy_dir) / p).stat().st_mtime_ns for p in expected}
    _ok(c.post(f"/projects/{s['id']}/library"))
    assert {p: (_lib(comfy_dir) / p).stat().st_mtime_ns for p in expected} == before

    # « Nettoyer » vide le transit mais garde la bibliothèque.
    cleanup = _ok(c.post(f"/projects/{s['id']}/cleanup"))
    assert cleanup["comfyui_cleaned"]
    assert _lib_files(comfy_dir) == expected

    # Série supprimée : son dossier part, old/ reste.
    assert c.delete(f"/projects/{s['id']}").status_code == 204
    assert not _lib(comfy_dir).exists()
    assert (comfy_dir / "output" / "mangaka" / "old" / "garde.png").exists()


def test_rebuild_converts_the_flat_layout_and_restores_the_trash(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    jobs = _ok(
        c.post(f"/characters/{lucius['id']}/reference-variants", json={"sheet": "personnage-turnaround", "count": 2}),
        202,
    )
    _wait_jobs(c, jobs)
    variants = sorted(_ok(c.get(f"/characters/{lucius['id']}/reference-variants"))["variants"], key=lambda v: v["id"])
    _ok(c.post(f"/reference-variants/{variants[0]['id']}/keep"), 201)
    _ok(c.post(f"/characters/{lucius['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    # Essais de la planche de style : non choisis → corbeille.
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    stored = ctx.files.save_image(png_bytes(), f"projects/{s['id']}/style")
    with ctx.db.session_scope() as session:
        session.add(
            ReferenceVariant(
                project_id=s["id"],
                entry_kind="style",
                entry_id=s["id"],
                sheet="planche-de-style",
                path=stored.path,
                content_type="image/png",
                width=8,
                height=8,
            )
        )
        session.commit()
    expected = {
        "references/personnages/lucius/plein-pied/lucius-plein-pied.png",
        "references/personnages/lucius/imports/lucius-import.png",
    }
    expected_trash = {"personnages/lucius/plein-pied/lucius-plein-pied-v2.png", "style/essai-v1.png"}
    assert (_lib_files(comfy_dir), _trash(comfy_dir)) == (expected, expected_trash)

    # Bibliothèque d'avant (#108) : tout à plat dans le dossier de la fiche, sans corbeille.
    root = _lib(comfy_dir)
    shutil.rmtree(root)
    flat = root / "references" / "personnages" / "lucius"
    flat.mkdir(parents=True)
    for name in ("lucius-turnaround.png", "lucius-reference.png"):
        (flat / name).write_bytes(png_bytes())

    out = _ok(c.post("/library"))
    assert out["enabled"] and out["folder"] == "output/mangaka" and out["removed"] == 2
    assert out["path"] == str(comfy_dir / "output" / "mangaka")
    assert (_lib_files(comfy_dir), _trash(comfy_dir)) == (expected, expected_trash)
    assert _dirs(flat) == {"plein-pied", "imports"}  # seuls les sous-dossiers qui ont une image
    again = _ok(c.post("/library"))
    assert (again["written"], again["removed"]) == (0, 0)

    # Corbeille effacée à la main : rien ne casse, la reconstruction la refait.
    shutil.rmtree(root / "trash")
    assert _ok(c.get(f"/characters/{lucius['id']}"))["reference_images"]
    rebuilt = _ok(c.post(f"/projects/{s['id']}/library"))
    assert (rebuilt["written"], rebuilt["removed"]) == (2, 0)
    assert _trash(comfy_dir) == expected_trash
    assert (comfy_dir / "output" / "mangaka" / "old" / "garde.png").exists()


def test_series_rename_moves_the_library(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    lucius = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    _ok(c.post(f"/characters/{lucius['id']}/images", files=[("files", ("l.png", png_bytes(), "image/png"))]), 201)
    _ok(c.patch(f"/projects/{s['id']}", json={"title": "Les Aventures"}))
    assert not _lib(comfy_dir).exists()
    assert _lib_files(comfy_dir, "les-aventures") == {"references/personnages/lucius/imports/lucius-import.png"}
    assert not (_lib(comfy_dir, "les-aventures") / "trash").exists()  # rien de non retenu : pas de corbeille


def test_without_comfyui_dir_nothing_is_written_and_the_reason_is_given(
    make_client: Callable[..., TestClient], tmp_path: Path
) -> None:
    c = make_client(comfyui_dir=str(tmp_path / "absent"))
    s = _series(c, "Lucius et Stan")
    out = _ok(c.post(f"/projects/{s['id']}/library"))
    assert out["enabled"] is False and "introuvable" in out["warning"] and out["written"] == 0
    assert not (tmp_path / "absent").exists()
    assert c.post("/projects/999/library").status_code == 404


# --- confinement ------------------------------------------------------------------------------
def test_library_is_confined_to_the_series(comfy_dir: Path, tmp_path: Path) -> None:
    folders = ComfyFolders.from_settings(str(comfy_dir), provider="http")
    library = ComfyLibrary(folders, FileStore(tmp_path / "data"))
    for slug in ("..", "old", "a/b", "../old", ".cache", "Majuscule"):
        report = library.sync(None, Project(id=1, title="x", slug=slug))  # type: ignore[arg-type]
        assert report.warning == "chemin refusé" and report.written == [], slug
    assert folders.target("output", ["serie", "..", "old"]) is None
    assert folders.target("output", ["serie", "references", "_transit"]) is None
    assert folders.target("output", ["serie", "_transit", "chapitre-01"]) is not None

    # Un lien symbolique dans la série n'est jamais suivi.
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    (comfy_dir / "output" / "mangaka" / "serie").mkdir()
    (comfy_dir / "output" / "mangaka" / "serie" / "references").symlink_to(outside)
    assert folders.target("output", ["serie", "references", "personnages"]) is None
    assert list(outside.iterdir()) == []
    assert (comfy_dir / "output" / "mangaka" / "old" / "garde.png").exists()


def test_removing_a_page_leaves_no_empty_folder(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    pages = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "a"}]}] * 2}))
    for page in pages:
        _wait_jobs(c, [_ok(c.post(f"/panels/{page['panels'][0]['id']}/sketch"), 202)[0]])
    assert {"chapitre-01/page-01/case-01-croquis.png", "chapitre-01/page-02/case-01-croquis.png"} == _lib_files(
        comfy_dir
    )
    keep = pages[0]
    _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={"pages": [{"id": keep["id"], "panels": [{"id": keep["panels"][0]["id"], "description": "a"}]}]},
        )
    )
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png"}
    assert not (_lib(comfy_dir) / "chapitre-01" / "page-02").exists()
    assert _empty_dirs(_lib(comfy_dir)) == set()
    assert _empty_dirs(comfy_dir / "input" / "mangaka" / "lucius-et-stan") == set()


# --- « Ranger le dossier ComfyUI » -------------------------------------------------------------
def test_tidy_moves_orphan_folders_to_old_and_never_touches_known_series(c: TestClient, comfy_dir: Path) -> None:
    mangaka = comfy_dir / "output" / "mangaka"
    a = _series(c, "Lucius et Stan")
    b = _series(c, "Space Voyage")
    for s in (a, b):
        ch, [page] = _chapter(c, s, panels=1)
        _wait_jobs(c, [_ok(c.post(f"/panels/{page['panels'][0]['id']}/sketch"), 202)[0]])
    known_before = {slug: _files(mangaka / slug) for slug in ("lucius-et-stan", "space-voyage")}
    assert all(known_before.values())
    # Restes de tests : une série inconnue avec une image, un dossier vide ; un dossier vide dans une série connue.
    (mangaka / "les-lames-3" / "references" / "personnages" / "aiko" / "imports").mkdir(parents=True)
    (mangaka / "les-lames-3" / "references" / "personnages" / "aiko" / "imports" / "aiko-import.png").write_bytes(b"x")
    (mangaka / "dragons").mkdir()
    (comfy_dir / "input" / "mangaka" / "dragons" / "decors").mkdir(parents=True)
    (mangaka / "space-voyage" / "references" / "personnages").mkdir(parents=True)

    preview = _ok(c.get("/comfyui/orphans"))
    assert preview["enabled"] and preview["warning"] is None
    assert preview["orphans"] == [
        {"area": "output", "name": "dragons", "files": 0},
        {"area": "output", "name": "les-lames-3", "files": 1},
        {"area": "input", "name": "dragons", "files": 0},
    ]
    stamp = preview["archive"]
    assert stamp.startswith("old/orphelins-")

    # Une série connue glissée dans la confirmation n'est jamais déplacée.
    folders = [{"area": o["area"], "name": o["name"]} for o in preview["orphans"]]
    out = _ok(c.post("/comfyui/tidy", json={"folders": [*folders, {"area": "output", "name": "space-voyage"}]}))
    assert out["enabled"] and sorted(out["moved"]) == sorted(
        [
            f"output/mangaka/{stamp}/dragons",
            f"output/mangaka/{stamp}/les-lames-3",
            f"input/mangaka/{stamp}/dragons",
        ]
    )
    assert out["removed_empty"] >= 1
    assert (
        mangaka / stamp / "les-lames-3" / "references" / "personnages" / "aiko" / "imports" / "aiko-import.png"
    ).exists()
    assert (mangaka / stamp / "dragons").is_dir() and (comfy_dir / "input" / "mangaka" / stamp / "dragons").is_dir()
    assert not (mangaka / "les-lames-3").exists() and not (mangaka / "dragons").exists()
    assert {slug: _files(mangaka / slug) for slug in known_before} == known_before
    assert not (mangaka / "space-voyage" / "references").exists()  # dossier vide retiré
    assert (mangaka / "old" / "garde.png").exists() and (comfy_dir / "input" / "mangaka" / "old" / "garde.png").exists()
    assert _ok(c.get("/comfyui/orphans"))["orphans"] == []

    # Rejouer le même jour avec un nouveau reste : rien n'est écrasé.
    (mangaka / "dragons").mkdir()
    again = _ok(c.post("/comfyui/tidy", json={"folders": [{"area": "output", "name": "dragons"}]}))
    assert again["moved"] == [f"output/mangaka/{stamp}/dragons-2"]


def test_tidy_without_comfyui_dir_does_nothing_and_says_why(
    make_client: Callable[..., TestClient], tmp_path: Path
) -> None:
    c = make_client(comfyui_dir=str(tmp_path / "absent"))
    preview = _ok(c.get("/comfyui/orphans"))
    assert preview["enabled"] is False and "introuvable" in preview["warning"] and preview["orphans"] == []
    out = _ok(c.post("/comfyui/tidy", json={"folders": [{"area": "output", "name": "x"}]}))
    assert out["enabled"] is False and out["moved"] == [] and out["warning"]
    assert not (tmp_path / "absent").exists()


def test_mock_mode_refuses_a_real_comfyui_install(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    """Mode mock + COMFYUI_DIR = vraie installation (main.py) : rien n'y est écrit, la raison est donnée (fiche
    série : `storage.warning` de /health), le rangement est désactivé."""
    real = tmp_path / "VraiComfyUI"
    for area in ("input", "output"):
        (real / area).mkdir(parents=True)
    (real / "main.py").write_text("# ComfyUI\n", encoding="utf-8")
    (real / "output" / "mangaka" / "inconnue").mkdir(parents=True)
    before = {str(p.relative_to(real)) for p in real.rglob("*")}

    c = make_client(comfyui_dir=str(real))
    s = _series(c, "Les Lames de Kyoto")
    aiko = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    _, [page] = _chapter(c, s, panels=1)
    _wait_jobs(c, [_ok(c.post(f"/panels/{page['panels'][0]['id']}/sketch"), 202)[0]])

    storage = _ok(c.get("/health"))["storage"]
    assert storage["enabled"] is False and storage["mock"] is True
    assert "vraie installation de ComfyUI" in storage["warning"] and "main.py" in storage["warning"]
    library = _ok(c.post(f"/projects/{s['id']}/library"))
    assert library["enabled"] is False and "vraie installation" in library["warning"]
    preview = _ok(c.get("/comfyui/orphans"))
    assert preview["enabled"] is False and "vraie installation" in preview["warning"]
    assert _ok(c.post("/comfyui/tidy", json={"folders": [{"area": "output", "name": "inconnue"}]}))["moved"] == []
    assert {str(p.relative_to(real)) for p in real.rglob("*")} == before


def test_the_test_comfyui_is_never_a_real_install(comfy_dir: Path) -> None:
    """Les tests passent un faux ComfyUI temporaire, sans main.py : il est accepté en mode mock."""
    assert not (comfy_dir / "main.py").exists()
    assert ComfyFolders.from_settings(str(comfy_dir), provider="mock").enabled
    (comfy_dir / "main.py").write_text("", encoding="utf-8")
    assert not ComfyFolders.from_settings(str(comfy_dir), provider="mock").enabled
    assert ComfyFolders.from_settings(str(comfy_dir), provider="http").enabled  # le vrai ComfyUI : accepté
