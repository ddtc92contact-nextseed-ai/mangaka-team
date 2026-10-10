"""Images jamais périmées : ids jamais réutilisés et URLs versionnées (`?v=<nom du fichier>`).

Une image servie est gardée en cache par le navigateur sous son URL : un id recyclé après suppression (ou
une URL qui ne change pas quand un autre fichier prend la place) montrerait l'ancienne image.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.store.files import cache_headers, file_version, versioned_url
from tests.conftest import STYLE, png_bytes
from tests.test_generation import _ok, _wait, make_client, setup_chapter  # noqa: F401 — fixture


def _upload(c: TestClient, base: str, count: int, color: int) -> list[dict[str, Any]]:
    files = [("files", (f"{color}-{i}.png", _png(color + i), "image/png")) for i in range(count)]
    return _ok(c.post(f"{base}/images", files=files), 201)["reference_images"]


def _png(shade: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (shade, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


def test_versioned_url_and_cache_headers() -> None:
    rel = "projects/1/characters/2/0123abcd.png"
    assert file_version(rel) == "0123abcd"
    assert versioned_url("/characters/2/images/3/file", rel) == "/characters/2/images/3/file?v=0123abcd"
    assert versioned_url("/x?project_id=1", rel) == "/x?project_id=1&v=0123abcd"
    assert "immutable" in cache_headers(rel, "0123abcd")["Cache-Control"]
    # Sans version, ou avec une version qui n'est plus la bonne : revalidé à chaque affichage.
    assert cache_headers(rel, None) == {"Cache-Control": "no-cache"}
    assert cache_headers(rel, "ancien") == {"Cache-Control": "no-cache"}


@pytest.mark.parametrize(
    ("create", "segment"),
    [("characters", "characters"), ("decors", "decors"), ("objects", "objects")],
)
def test_deleted_entry_and_images_never_give_their_ids_or_urls(client: TestClient, create: str, segment: str) -> None:
    """Créer « urus », garder 3 images, le supprimer, le recréer avec 2 images : rien de l'ancien."""
    series = _ok(client.post("/projects", json={**STYLE, "title": "Ids"}), 201)
    old = _ok(client.post(f"/projects/{series['id']}/{create}", json={"name": "urus"}), 201)
    old_images = _upload(client, f"/{segment}/{old['id']}", 3, 10)
    assert client.delete(f"/{segment}/{old['id']}").status_code == 204

    new = _ok(client.post(f"/projects/{series['id']}/{create}", json={"name": "urus"}), 201)
    assert new["id"] > old["id"]
    new_images = _upload(client, f"/{segment}/{new['id']}", 2, 100)
    assert min(i["id"] for i in new_images) > max(i["id"] for i in old_images)
    assert not {i["url"] for i in new_images} & {i["url"] for i in old_images}

    shown = _ok(client.get(f"/{segment}/{new['id']}"))["reference_images"]
    assert [i["original_name"] for i in shown] == ["100-0.png", "100-1.png"]  # seulement les nouvelles, dans l'ordre
    for img, shade in zip(shown, (100, 101), strict=True):
        served = client.get(img["url"])
        assert served.status_code == 200 and served.content == _png(shade)
        assert "immutable" in served.headers["cache-control"]
    for img in old_images:
        assert client.get(img["url"]).status_code == 404
    # Sans `?v=` (ancien lien) : servi mais jamais gardé tel quel.
    bare = client.get(shown[0]["url"].split("?")[0])
    assert bare.status_code == 200 and bare.headers["cache-control"] == "no-cache"


def test_regenerated_panel_image_never_gets_an_old_url(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = setup_chapter(c)
    chapter_id = data["chapter"]["id"]
    p1 = data["panels"][0]

    def panel_row() -> dict[str, Any]:
        pages = _ok(c.get(f"/chapters/{chapter_id}/pages"))
        return next(p for pg in pages for p in pg["panels"] if p["id"] == p1["id"])

    # Croquis : supprimer le plus récent puis en tirer un autre.
    _ok(c.post(f"/panels/{p1['id']}/sketch"), 202)
    _wait(c)
    [sketch] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert panel_row()["sketch_image_url"] == sketch["url"]
    assert c.delete(f"/panel-images/{sketch['id']}").status_code == 204
    _ok(c.post(f"/panels/{p1['id']}/sketch"), 202)
    _wait(c)
    [again] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert again["id"] > sketch["id"] and again["url"] != sketch["url"]
    assert panel_row()["sketch_image_url"] == again["url"]
    assert c.delete(f"/panel-images/{again['id']}").status_code == 204

    # Versions : supprimer la plus récente (choisie) puis générer à nouveau.
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"seed": 1}), 202)
    _wait(c)
    [first] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert panel_row()["selected_image_url"] == first["url"]
    assert c.delete(f"/panel-images/{first['id']}").status_code == 204
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"seed": 2}), 202)
    _wait(c)
    [second] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert second["version"] == first["version"]  # même numéro de version…
    assert second["id"] > first["id"] and second["url"] != first["url"]  # … mais jamais la même URL
    assert panel_row()["selected_image_url"] == second["url"]
    assert c.get(first["url"]).status_code == 404
    served = c.get(second["url"])
    assert served.status_code == 200 and "immutable" in served.headers["cache-control"]

    # Lettrage / production : l'aperçu de la page pointe sur la version servie.
    page_id = data["pages"][0]["id"]
    lettering = _ok(c.get(f"/pages/{page_id}/lettering"))
    assert lettering["panels"][0]["image_url"] == second["url"]


def test_trial_image_is_cached_only_under_its_version(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    job = _ok(c.post("/comfyui/trial", json={}), 202)
    _wait(c)
    rel = _ok(c.get(f"/jobs/{job['id']}"))["params"]["image_path"]
    url = f"/comfyui/trial/{job['id']}/image"
    assert c.get(url).headers["cache-control"] == "no-cache"
    assert "immutable" in c.get(f"{url}?v={Path(rel).stem}").headers["cache-control"]


def test_reference_upload_still_works_after_unversioned_request(client: TestClient) -> None:
    series = _ok(client.post("/projects", json={**STYLE, "title": "Ids"}), 201)
    entry = _ok(client.post(f"/projects/{series['id']}/characters", json={"name": "Aiko"}), 201)
    [img] = _ok(
        client.post(f"/characters/{entry['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]),
        201,
    )["reference_images"]
    stale = client.get(img["url"].split("?")[0] + "?v=ancien")
    assert stale.status_code == 200 and stale.headers["cache-control"] == "no-cache"
