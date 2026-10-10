from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from tests.conftest import png_bytes


def _project(client: TestClient, **body) -> dict:
    resp = client.post("/projects", json={"title": "Les Lames de Kyoto", **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- santé / presets ---------------------------------------------------------
def test_health_in_mock_mode(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data["engine"]["status"] == "ok"
    assert data["comfyui"]["online"] is True and data["comfyui"]["provider"] == "mock"
    assert data["mock"] is True
    assert data["providers"]["llm"] == {"name": "mock", "ok": True, "detail": None}
    assert data["presets"]["issues"] == 0


def test_health_reports_provider_config_error(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(llm_provider="deepseek", comfyui_provider="nope"))) as c:
        data = c.get("/health").json()
    assert data["engine"]["status"] == "ok"
    assert data["providers"]["llm"]["ok"] is False
    assert "DEEPSEEK_API_KEY" in data["providers"]["llm"]["detail"]
    assert data["comfyui"]["online"] is False and "inconnu" in data["comfyui"]["detail"]


def test_health_never_leaks_api_key(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(llm_provider="deepseek", deepseek_api_key="sk-secret-123"))) as c:
        body = c.get("/health").text + c.get("/presets").text
    assert "sk-secret-123" not in body


def test_presets_endpoint(client: TestClient) -> None:
    data = client.get("/presets").json()
    assert data["defaults"] == {
        "page_format": "a4-300dpi",
        "workflow": "qwen-image-turbo",
        "workflow_with_references": "qwen-image-edit-ref-turbo",
        "workflow_quality": "qwen-image-base",
        "workflow_inpaint": "qwen-image-inpaint-turbo",
        "layout_style": "dynamique",
        "upscaler": "realesrgan-x4plus-anime-6b",
        "finishing_tolerance": 0.9,
    }
    assert {st["id"] for st in data["layout_styles"]} >= {"sage", "dynamique", "nerveuse"}
    assert [st["id"] for st in data["layout_styles"] if st["is_default"]] == ["dynamique"]
    formats = {f["id"]: f for f in data["page_formats"]}
    assert formats["a4-300dpi"]["width_px"] == 2480
    assert formats["b4-300dpi"]["dpi"] == 300
    assert any(t["panel_count"] == 6 for t in data["layout_templates"])
    assert data["prompts"] == ["direction-artistique", "script"]
    assert data["workflows"][0]["id"] == "qwen-image-base"
    assert data["issues"] == []


# --- projets -------------------------------------------------------------------
def test_project_crud(client: TestClient) -> None:
    created = _project(client, style="encre, trames", reading_direction="ltr")
    assert created["page_format"] == "a4-300dpi"
    assert created["workflow_preset"] == "qwen-image-turbo"  # Turbo par défaut pour les nouvelles séries
    assert created["reading_direction"] == "ltr"
    pid = created["id"]

    assert [p["id"] for p in client.get("/projects").json()] == [pid]
    resp = client.patch(f"/projects/{pid}", json={"title": "  Nouveau titre ", "reading_direction": "rtl"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Nouveau titre" and resp.json()["reading_direction"] == "rtl"
    assert client.get(f"/projects/{pid}").json()["style"] == "encre, trames"

    assert client.delete(f"/projects/{pid}").status_code == 204
    resp = client.get(f"/projects/{pid}")
    assert resp.status_code == 404 and resp.json() == {"detail": "Série introuvable"}


def test_project_default_reading_direction_is_rtl(client: TestClient) -> None:
    assert _project(client)["reading_direction"] == "rtl"


def test_project_validation_errors_are_readable(client: TestClient) -> None:
    resp = client.post("/projects", json={"title": "   ", "reading_direction": "ttb", "extra": 1})
    assert resp.status_code == 422
    data = resp.json()
    assert data["detail"] == "Données invalides"
    errors = {e["field"]: e["message"] for e in data["errors"]}
    assert errors["title"] == "ne doit pas être vide"
    assert "valeur non autorisée" in errors["reading_direction"]
    assert errors["extra"] == "champ inconnu"
    assert "Traceback" not in resp.text


def test_project_missing_title_and_bad_json(client: TestClient) -> None:
    resp = client.post("/projects", json={})
    assert resp.status_code == 422
    assert resp.json()["errors"] == [{"field": "title", "message": "champ obligatoire"}]
    resp = client.post("/projects", content=b"{oops", headers={"content-type": "application/json"})
    assert resp.status_code == 422 and resp.json()["detail"] == "Données invalides"


def test_project_unknown_presets_are_422(client: TestClient) -> None:
    resp = client.post("/projects", json={"title": "x", "page_format": "b9-12dpi"})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "page_format"
    pid = _project(client)["id"]
    resp = client.patch(f"/projects/{pid}", json={"workflow_preset": "inexistant"})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "workflow_preset"
    resp = client.patch(f"/projects/{pid}", json={"title": None})
    assert resp.status_code == 422


def test_unknown_route_is_french_404(client: TestClient) -> None:
    assert client.get("/nope").json() == {"detail": "Ressource introuvable"}
    assert client.get("/projects/abc").status_code == 422


# --- personnages -------------------------------------------------------------
def test_character_crud(client: TestClient) -> None:
    pid = _project(client)["id"]
    resp = client.post(
        f"/projects/{pid}/characters",
        json={
            "name": "Aiko",
            "visual_description": "cheveux noirs courts, cicatrice sur la joue gauche",
            "prompt_keywords": ["aiko", " kimono rouge ", "", "aiko"],
            "lora_name": "",
        },
    )
    assert resp.status_code == 201, resp.text
    char = resp.json()
    assert char["prompt_keywords"] == ["aiko", "kimono rouge"]
    assert char["lora_name"] is None and char["lora_weight"] == 0.8
    cid = char["id"]

    assert client.get(f"/projects/{pid}").json()["character_count"] == 1
    resp = client.patch(f"/characters/{cid}", json={"lora_name": "aiko_v2.safetensors", "lora_weight": 1.1})
    assert resp.json()["lora_name"] == "aiko_v2.safetensors" and resp.json()["lora_weight"] == 1.1
    assert [c["name"] for c in client.get(f"/projects/{pid}/characters").json()] == ["Aiko"]

    assert client.delete(f"/characters/{cid}").status_code == 204
    assert client.get(f"/characters/{cid}").status_code == 404


def test_character_validation(client: TestClient) -> None:
    pid = _project(client)["id"]
    resp = client.post(f"/projects/{pid}/characters", json={"name": "", "lora_weight": 5})
    assert resp.status_code == 422
    errors = {e["field"]: e["message"] for e in resp.json()["errors"]}
    assert errors["name"] == "ne doit pas être vide"
    assert errors["lora_weight"] == "doit être inférieur ou égal à 2"
    assert client.post("/projects/999/characters", json={"name": "x"}).status_code == 404


def test_reference_image_upload_and_download(client: TestClient) -> None:
    pid = _project(client)["id"]
    cid = client.post(f"/projects/{pid}/characters", json={"name": "Aiko"}).json()["id"]
    files = [
        ("files", ("face.png", png_bytes((64, 48)), "image/png")),
        ("files", ("profil.jpg", png_bytes((30, 40), "JPEG"), "image/jpeg")),
    ]
    resp = client.post(f"/characters/{cid}/images", files=files)
    assert resp.status_code == 201, resp.text
    images = resp.json()["reference_images"]
    assert [(i["original_name"], i["width"], i["height"]) for i in images] == [
        ("face.png", 64, 48),
        ("profil.jpg", 30, 40),
    ]
    file_resp = client.get(images[0]["url"])
    assert file_resp.status_code == 200 and file_resp.headers["content-type"] == "image/png"
    assert file_resp.content == png_bytes((64, 48))

    assert client.delete(f"/characters/{cid}/images/{images[0]['id']}").status_code == 204
    assert client.get(images[0]["url"]).status_code == 404
    assert len(client.get(f"/characters/{cid}").json()["reference_images"]) == 1


def test_reference_image_rejects_non_images(client: TestClient) -> None:
    pid = _project(client)["id"]
    cid = client.post(f"/projects/{pid}/characters", json={"name": "Aiko"}).json()["id"]
    files = [
        ("files", ("ok.png", png_bytes(), "image/png")),
        ("files", ("virus.png", b"MZ\x90\x00 pas une image", "image/png")),
    ]
    resp = client.post(f"/characters/{cid}/images", files=files)
    assert resp.status_code == 422
    [err] = resp.json()["errors"]
    assert err["field"] == "files" and "virus.png" in err["message"]
    # tout ou rien : la première image n'a pas été conservée
    assert client.get(f"/characters/{cid}").json()["reference_images"] == []
    assert client.post(f"/characters/{cid}/images").status_code == 422


def test_reference_image_too_large(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(max_upload_mb=0))) as c:
        pid = _project(c)["id"]
        cid = c.post(f"/projects/{pid}/characters", json={"name": "Aiko"}).json()["id"]
        resp = c.post(f"/characters/{cid}/images", files=[("files", ("a.png", png_bytes(), "image/png"))])
    assert resp.status_code == 422 and "dépasse" in resp.json()["errors"][0]["message"]


def test_data_survives_restart(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        pid = _project(c)["id"]
        cid = c.post(f"/projects/{pid}/characters", json={"name": "Aiko"}).json()["id"]
        c.post(f"/characters/{cid}/images", files=[("files", ("a.png", png_bytes(), "image/png"))])
    with TestClient(create_app(settings)) as c:
        char = c.get(f"/characters/{cid}").json()
        assert char["name"] == "Aiko"
        assert c.get(char["reference_images"][0]["url"]).status_code == 200


def test_deleting_project_removes_characters_and_files(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        pid = _project(c)["id"]
        cid = c.post(f"/projects/{pid}/characters", json={"name": "Aiko"}).json()["id"]
        c.post(f"/characters/{cid}/images", files=[("files", ("a.png", png_bytes(), "image/png"))])
        assert (settings.data_dir / "projects" / str(pid)).exists()
        c.delete(f"/projects/{pid}")
        assert c.get(f"/characters/{cid}").status_code == 404
    assert not (settings.data_dir / "projects" / str(pid)).exists()


# --- fournisseurs actifs (badge de l'en-tête) ----------------------------------------
def test_providers_default_env_is_simulated(client: TestClient) -> None:
    data = _ok(client.get("/providers"))
    assert set(data) == {"llm", "vision", "comfyui"}
    llm = data["llm"]
    assert (llm["name"], llm["label"], llm["mock"], llm["env"]) == ("mock", "simulé", True, "LLM_PROVIDER")
    assert data["comfyui"]["label"] == "simulé" and data["comfyui"]["env"] == "COMFYUI_PROVIDER"
    assert data["vision"]["mock"] is True and data["vision"]["env"] == "VISION_PROVIDER"
    assert client.get("/health").json()["active"] == data


def test_providers_real_llm_never_leaks_key(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(llm_provider="deepseek", deepseek_api_key="sk-secret-456")
    with TestClient(create_app(settings)) as c:
        resp = c.get("/providers")
        health = c.get("/health").text
    data = _ok(resp)
    llm = data["llm"]
    assert (llm["name"], llm["label"], llm["mock"], llm["ok"]) == ("deepseek", "DeepSeek", False, True)
    assert (llm["key_env"], llm["key_set"]) == ("DEEPSEEK_API_KEY", True)
    assert "sk-secret-456" not in resp.text and "sk-secret-456" not in health


def test_providers_real_llm_without_key(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(llm_provider="deepseek"))) as c:
        llm = _ok(c.get("/providers"))["llm"]
    assert llm["name"] == "deepseek" and llm["ok"] is False and llm["key_set"] is False
    assert "DEEPSEEK_API_KEY" in llm["detail"]


def _ok(resp) -> dict:  # type: ignore[no-untyped-def]
    assert resp.status_code == 200, resp.text
    return resp.json()
