"""Bibliothèque lisible (`ComfyUI/output/mangaka/<série>/`) : arborescence créée avec la série et les fiches (un
sous-dossier par type de fiche), images gardées nommées d'après leur type, corbeille (`trash/`) de ce qui n'est pas
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

from mangaka_engine.pipeline.comfy_library import ComfyLibrary, sheet_folders
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.store.comfy_folders import ComfyFolders
from mangaka_engine.store.files import FileStore
from mangaka_engine.store.models import AssetKind, Project, ReferenceVariant, SeriesAsset, SeriesAssetImage
from tests.conftest import png_bytes
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
def test_new_series_creates_its_tree_and_trash(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    root = _lib(comfy_dir)
    assert _dirs(root) == {
        "references",
        "references/personnages",
        "references/objets",
        "references/decors",
        "references/style",
        "trash",
    }
    assert _files(root) == set()
    _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
    assert (root / "chapitre-01" / "planches").is_dir()


def test_entry_folders_have_one_subfolder_per_sheet_preset(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Lucius"}), 201)
    _ok(c.post(f"/projects/{s['id']}/objects", json={"name": "Épée de Feu"}), 201)
    _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "La Forêt"}), 201)
    refs = _lib(comfy_dir) / "references"
    assert _dirs(refs / "personnages" / "lucius") == {"portrait", "plein-pied", "expressions", "angles", "imports"}
    assert _dirs(refs / "objets" / "epee-de-feu") == {"trois-quarts", "imports"}
    assert _dirs(refs / "decors" / "la-foret") == {"plan-large", "autre-angle", "imports"}
    assert _files(_lib(comfy_dir)) == set()


def test_sheet_folders_follow_the_presets(tmp_path: Path) -> None:
    presets = PresetRegistry.load(Path(__file__).resolve().parents[2] / "presets")
    assert sheet_folders("character", presets) == ["portrait", "plein-pied", "expressions", "angles", "imports"]
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
    assert sheet_folders("object", loaded) == ["trois-quarts", "eclate", "imports"]


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

    # Supprimer le personnage supprime ses dossiers (corbeille comprise) ; les dossiers de base restent.
    assert c.delete(f"/characters/{lucius['id']}").status_code == 204
    assert _files(_lib(comfy_dir)) == set()
    assert not (_lib(comfy_dir) / "references" / "personnages" / "lucius-le-grand").exists()
    assert (_lib(comfy_dir) / "references" / "personnages").is_dir() and (_lib(comfy_dir) / "trash").is_dir()


def test_objects_decors_and_style_board(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    epee = _ok(c.post(f"/projects/{s['id']}/objects", json={"name": "Épée de Feu"}), 201)
    foret = _ok(c.post(f"/projects/{s['id']}/decors", json={"name": "La Forêt"}), 201)
    assert (_lib(comfy_dir) / "references" / "objets" / "epee-de-feu").is_dir()
    assert (_lib(comfy_dir) / "references" / "decors" / "la-foret").is_dir()
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


def test_panels_sketches_and_plates(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    ch, [page] = _chapter(c, s)
    page_dir = _lib(comfy_dir) / "chapitre-01" / "page-01"
    assert page_dir.is_dir() and (_lib(comfy_dir) / "chapitre-01" / "planches").is_dir()
    p1, p2 = page["panels"]

    # Croquis validé → case-01-croquis.png ; non validé → corbeille, avec son numéro de version.
    _wait_jobs(c, [_ok(c.post(f"/panels/{p1['id']}/sketch"), 202)[0]])
    assert _lib_files(comfy_dir) == set()
    assert _trash(comfy_dir) == {"chapitre-01/page-01/case-01-croquis-v1.png"}
    _ok(c.post(f"/panels/{p1['id']}/sketch/validate"))
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-01-croquis.png"}
    assert _trash(comfy_dir) == set()
    _ok(c.delete(f"/panels/{p1['id']}/sketch/validate"))
    assert _lib_files(comfy_dir) == set()
    assert _trash(comfy_dir) == {"chapitre-01/page-01/case-01-croquis-v1.png"}

    # Version propre choisie → case-NN.png, les autres dans la corbeille ; changer de version les échange.
    for _ in range(2):
        _wait_jobs(c, [_ok(c.post(f"/panels/{p2['id']}/generate"), 202)])
    v1, v2 = sorted(_ok(c.get(f"/panels/{p2['id']}/images")), key=lambda i: i["version"])
    assert v1["selected"]
    case = page_dir / "case-02.png"
    trash = _lib(comfy_dir) / "trash" / "chapitre-01" / "page-01"
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-02.png"}
    assert _trash(comfy_dir) == {
        "chapitre-01/page-01/case-01-croquis-v1.png",
        f"chapitre-01/page-01/case-02-v{v2['version']}.png",
    }
    assert case.read_bytes() == c.get(v1["url"]).content
    _ok(c.post(f"/panel-images/{v2['id']}/select"))
    assert case.read_bytes() == c.get(v2["url"]).content
    assert _lib_files(comfy_dir) == {"chapitre-01/page-01/case-02.png"}
    assert _trash(comfy_dir) == {
        "chapitre-01/page-01/case-01-croquis-v1.png",
        f"chapitre-01/page-01/case-02-v{v1['version']}.png",
    }
    assert (trash / f"case-02-v{v1['version']}.png").read_bytes() == c.get(v1["url"]).content

    # Rendu de la page → planches/page-01.png + .svg.
    _ok(c.post(f"/pages/{page['id']}/render"))
    assert _lib_files(comfy_dir) == {
        "chapitre-01/page-01/case-02.png",
        "chapitre-01/planches/page-01.png",
        "chapitre-01/planches/page-01.svg",
    }
    # Supprimer le chapitre supprime son dossier (corbeille comprise).
    assert c.delete(f"/chapters/{ch['id']}").status_code == 204
    assert not (_lib(comfy_dir) / "chapitre-01").exists()
    assert not (_lib(comfy_dir) / "trash" / "chapitre-01").exists()


def test_chapter_export_writes_the_plates(c: TestClient, comfy_dir: Path) -> None:
    s = _series(c, "Lucius et Stan")
    ch, [page] = _chapter(c, s, panels=1)
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
    assert (_lib(comfy_dir) / "references" / "objets").is_dir()
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
    assert _dirs(flat) == {"portrait", "plein-pied", "expressions", "angles", "imports"}
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
    assert (_lib(comfy_dir, "les-aventures") / "trash").is_dir()


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
