"""Étape 3 : génération case par case, file ComfyUI unique, versions, erreurs (tout simulé)."""

from __future__ import annotations

import io
import json
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.providers.comfyui import (
    ComfyUIClient,
    ComfyUIInterruptedError,
    HttpComfyUIClient,
    MockComfyUIClient,
)
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.models import Job, JobStatus, Panel, PanelState
from tests.conftest import COMFY_FIXTURES, PRESETS_DIR, png_bytes


# --- outillage ------------------------------------------------------------------------
class GatedComfy(MockComfyUIClient):
    """ComfyUI factice qui bloque chaque génération à mi-parcours jusqu'à `gate.set()`."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        self.started = threading.Semaphore(0)
        self._lock = threading.Lock()
        self.running = 0
        self.max_running = 0
        self.order: list[str] = []

    def wait_for_images(self, prompt_id: str, output_node: str, **kw: Any):  # type: ignore[no-untyped-def]
        with self._lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.order.append(self.prompts[prompt_id]["9"]["inputs"]["seed"])
        try:
            on_progress, should_stop = kw.get("on_progress"), kw.get("should_stop")
            if on_progress:
                on_progress(4, 8)
            self.started.release()
            while not self.gate.wait(0.01):
                if self._interrupted.is_set() or (should_stop and should_stop()):
                    raise ComfyUIInterruptedError("génération interrompue dans ComfyUI")
            return super().wait_for_images(prompt_id, output_node, **kw)
        finally:
            with self._lock:
                self.running -= 1


def _providers(comfy: ComfyUIClient | None) -> Providers:
    # Aucune couche de QC : pas de contrôle automatique après génération (couvert par test_qc.py).
    return Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=comfy,
        names={"llm": "mock", "vision": "mock", "comfyui": getattr(comfy, "name", "http")},
        errors={} if comfy is not None else {"comfyui": "client ComfyUI inconnu"},
    )


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(comfy: ComfyUIClient | None = None, **settings: Any) -> TestClient:
        comfy = comfy if comfy is not None else MockComfyUIClient()
        c = TestClient(create_app(make_settings(**settings), providers=_providers(comfy)))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def setup_chapter(c: TestClient) -> dict[str, Any]:
    """Série (style + LoRA de style), Aiko (référence + LoRA), Kenji (sans), 2 pages / 3 cases."""
    s = _ok(
        c.post(
            "/projects",
            json={"title": "Les Lames", "style": "Seinen sombre", "style_lora_name": "encre.safetensors"},
        ),
        201,
    )
    aiko = _ok(
        c.post(
            f"/projects/{s['id']}/characters",
            json={
                "name": "Aiko",
                "visual_description": "cheveux noirs courts",
                "prompt_keywords": ["kimono rouge"],
                "lora_name": "aiko-v3.safetensors",
                "lora_weight": 0.9,
            },
        ),
        201,
    )
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Kenji"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {"description": "Aiko sur un toit", "characters": ["Aiko"], "shot_type": "plan large"},
                            {"description": "Kenji court", "characters": ["Kenji"]},
                        ]
                    },
                    {"panels": [{"description": "La ville sous la pluie"}]},
                ]
            },
        )
    )
    return {
        "series": s,
        "chapter": ch,
        "pages": pages,
        "aiko": aiko,
        "panels": [p for pg in pages for p in pg["panels"]],
    }


def _wait(c: TestClient, timeout: float = 10) -> None:
    assert c.app.state.ctx.generation.wait_idle(timeout)  # type: ignore[attr-defined]


def _job(c: TestClient, job_id: int) -> dict[str, Any]:
    return _ok(c.get(f"/jobs/{job_id}"))


def _wait_status(c: TestClient, job_id: int, status: str, timeout: float = 5) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = _job(c, job_id)
        if job["status"] == status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} : {job['status']} au lieu de {status}")


def _target(page: dict[str, Any], panel_id: int) -> tuple[int, int]:
    lp = next(p for p in page["layout"]["panels"] if p["panel_id"] == panel_id)
    return lp["target"]["width"], lp["target"]["height"]


# --- génération d'une case ------------------------------------------------------------
def test_rapide_series_keeps_its_tier_for_reference_panels(make_client: Callable[..., TestClient]) -> None:
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"workflow_preset": "qwen-image-base-rapide"}))
    p1, p2, _ = data["panels"]
    [job1] = _ok(c.post(f"/panels/{p1['id']}/generate"), 202)  # Aiko a une planche de référence
    [job2] = _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    assert job1["params"]["preset"] == "qwen-image-edit-ref-rapide"
    assert job2["params"]["preset"] == "qwen-image-base-rapide"
    _wait(c)
    reg = c.app.state.ctx.presets  # type: ignore[attr-defined]
    expected = {
        reg.workflow(pid).workflow["1"]["inputs"]["unet_name"]
        for pid in ("qwen-image-edit-ref-rapide", "qwen-image-base-rapide")
    }
    qualite = reg.workflow("qwen-image-edit-ref").workflow["1"]["inputs"]["unet_name"]
    sent = {
        n["inputs"]["unet_name"]
        for wf in comfy.prompts.values()
        for n in wf.values()
        if n["class_type"] == "UNETLoader"
    }
    assert sent == expected and qualite not in sent  # jamais le modèle bf16 pour une série Rapide


def test_generate_panel_mock_end_to_end(make_client: Callable[..., TestClient]) -> None:
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    p1, p2, p3 = data["panels"]
    [job] = _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    assert job["step"] == "generation" and job["panel_id"] == p1["id"] and job["status"] in ("pending", "running")
    assert job["params"]["preset"] == "qwen-image-edit-ref"  # Aiko a une planche de référence
    _wait(c)
    done = _job(c, job["id"])
    assert done["status"] == "succeeded" and done["progress"] == 100 and done["message"].startswith("Version 1")

    [img] = _ok(c.get(f"/panels/{p1['id']}/images"))
    w, h = _target(data["pages"][0], p1["id"])
    assert (img["version"], img["selected"], img["width"], img["height"]) == (1, True, w, h)
    assert w % 16 == 0 and h % 16 == 0 and 0.9e6 < w * h < 1.1e6
    params = img["params"]
    assert params["preset"] == "qwen-image-edit-ref" and params["seed"] == img["seed"]
    assert [lo["name"] for lo in params["loras"]] == ["encre.safetensors", "aiko-v3.safetensors"]
    assert params["loras"][1]["weight"] == 0.9
    assert len(params["reference_images"]) == 1 and params["reference_images"][0]["comfyui_name"] in comfy.uploads
    assert "Aiko" in params["prompt"] and "kimono rouge" in params["prompt"] and "Seinen sombre" in params["prompt"]
    assert "bulles" in params["negative_prompt"] and "texte" in params["negative_prompt"]
    assert params["duration_ms"] >= 0 and params["workflow_params"]["width"] == w

    # le workflow envoyé : référence chargée, 2 emplacements retirés, 2 LoRA chaînés
    [wf] = comfy.prompts.values()
    assert sum(n["class_type"] == "LoadImage" for n in wf.values()) == 1
    assert sum(n["class_type"] == "LoraLoaderModelOnly" for n in wf.values()) == 2

    resp = c.get(img["url"])
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(resp.content)).size == (w, h)

    panel = _ok(c.get(f"/panels/{p1['id']}"))
    assert panel["state"] == "review" and panel["final_prompt"] == params["prompt"]
    assert panel["final_prompt_manual"] is False and panel["label"].endswith("p. 1 · case 1")
    pages = _ok(c.get(f"/chapters/{data['chapter']['id']}/pages"))
    assert pages[0]["panels"][0]["selected_image_url"] == img["url"] and pages[0]["panels"][0]["state"] == "review"
    assert pages[0]["panels"][1]["state"] == "draft" and pages[0]["panels"][1]["image_count"] == 0
    assert _ok(c.get(f"/chapters/{data['chapter']['id']}"))["status"] == "generation"

    # case sans référence → workflow de la série
    [job2] = _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    assert job2["params"]["preset"] == "qwen-image-base"
    _wait(c)
    [img2] = _ok(c.get(f"/panels/{p2['id']}/images"))
    assert img2["params"]["reference_images"] == [] and [lo["source"] for lo in img2["params"]["loras"]] == ["style"]
    # page 1 complète → à relire ; la page 2 n'a pas bougé
    pages = _ok(c.get(f"/chapters/{data['chapter']['id']}/pages"))
    assert pages[0]["state"] == "review" and pages[1]["state"] == "layout"
    assert _ok(c.get(f"/panels/{p3['id']}/images")) == []


def test_mock_image_shows_panel_number(make_client: Callable[..., TestClient]) -> None:
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    data = setup_chapter(c)
    p2 = data["panels"][1]
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    _wait(c)
    [wf] = comfy.prompts.values()
    assert wf["11"]["inputs"]["filename_prefix"].endswith("/page-1/case-2")
    [img] = _ok(c.get(f"/panels/{p2['id']}/images"))
    pixels = Image.open(io.BytesIO(c.get(img["url"]).content)).convert("RGB")
    # le libellé est écrit en blanc sur un fond uni (cadre blanc exclu)
    w, h = pixels.size
    inner = pixels.crop((20, 20, w - 20, h - 20))
    white = sum(n for n, rgb in inner.getcolors(w * h) or [] if rgb == (255, 255, 255))
    assert white > 1000


def test_variants_seed_select_delete(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    data = setup_chapter(c)
    p1, p2, _ = data["panels"]
    jobs = _ok(c.post(f"/panels/{p1['id']}/generate", json={"count": 3, "seed": 42}), 202)
    assert [j["params"]["variant"] for j in jobs] == [1, 2, 3]
    _wait(c)
    imgs = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert [(i["version"], i["seed"], i["selected"]) for i in imgs] == [(1, 42, True), (2, 43, False), (3, 44, False)]

    # choisir une version : une seule choisie par case
    imgs = _ok(c.post(f"/panel-images/{imgs[2]['id']}/select"))
    assert [i["selected"] for i in imgs] == [False, False, True]

    # même seed : relance identique, nouvelle version
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"seed": 44}), 202)
    _wait(c)
    imgs = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert [(i["version"], i["seed"]) for i in imgs][-1] == (4, 44)
    assert imgs[3]["params"]["prompt"] == imgs[2]["params"]["prompt"]
    assert c.get(imgs[3]["url"]).content == c.get(imgs[2]["url"]).content

    # suppression de la version choisie : fichier effacé, plus aucune version choisie
    assert c.delete(f"/panel-images/{imgs[2]['id']}").status_code == 204
    assert c.get(imgs[2]["url"]).status_code == 404
    left = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert [i["version"] for i in left] == [1, 2, 4] and not any(i["selected"] for i in left)
    # les autres cases ne sont jamais touchées
    assert _ok(c.get(f"/panels/{p2['id']}/images")) == []
    assert _ok(c.get(f"/panels/{p2['id']}"))["state"] == "draft"

    # tout supprimer → la case repasse en brouillon
    for i in left:
        assert c.delete(f"/panel-images/{i['id']}").status_code == 204
    assert _ok(c.get(f"/panels/{p1['id']}"))["state"] == "draft"
    assert c.delete(f"/panel-images/{imgs[0]['id']}").status_code == 404


def test_manual_prompt_is_kept_until_rebuilt(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    data = setup_chapter(c)
    p1 = data["panels"][0]
    panel = _ok(c.patch(f"/panels/{p1['id']}", json={"final_prompt": "  Ninja en contre-jour  "}))
    assert panel["final_prompt"] == "Ninja en contre-jour" and panel["final_prompt_manual"] is True
    [job] = _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    [img] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert img["params"]["prompt"] == "Ninja en contre-jour"

    panel = _ok(c.post(f"/panels/{p1['id']}/prompt/rebuild"))
    assert panel["final_prompt_manual"] is False and panel["final_prompt"].startswith("Plan large. Aiko sur un toit.")

    _ok(c.post(f"/panels/{p1['id']}/generate", json={"prompt_override": "Toit vide"}), 202)
    _wait(c)
    panel = _ok(c.get(f"/panels/{p1['id']}"))
    assert panel["final_prompt"] == "Toit vide" and panel["final_prompt_manual"] is True
    assert panel["images"][-1]["params"]["prompt"] == "Toit vide"

    # imposer un workflow à la case
    panel = _ok(c.patch(f"/panels/{p1['id']}", json={"generation_preset": "qwen-image-base"}))
    assert panel["resolved_preset"] == "qwen-image-base"
    r = c.patch(f"/panels/{p1['id']}", json={"generation_preset": "inconnu"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "generation_preset"


def test_chapter_and_page_generation_skip_panels_already_done(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    data = setup_chapter(c)
    p1, p2, p3 = data["panels"]
    ch = data["chapter"]["id"]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)

    out = _ok(c.post(f"/chapters/{ch}/generate"), 202)
    assert out["panel_ids"] == [p2["id"], p3["id"]] and out["skipped"] == 1 and len(out["jobs"]) == 2
    _wait(c)
    assert [len(_ok(c.get(f"/panels/{p['id']}/images"))) for p in (p1, p2, p3)] == [1, 1, 1]

    out = _ok(c.post(f"/chapters/{ch}/generate"), 202)
    assert out == {"jobs": [], "panel_ids": [], "skipped": 3}
    out = _ok(c.post(f"/pages/{data['pages'][0]['id']}/generate", json={"force": True}), 202)
    assert out["panel_ids"] == [p1["id"], p2["id"]]
    _wait(c)
    assert [len(_ok(c.get(f"/panels/{p['id']}/images"))) for p in (p1, p2, p3)] == [2, 2, 1]
    # les versions choisies restent celles d'avant
    assert _ok(c.get(f"/panels/{p1['id']}/images"))[0]["selected"] is True


def test_generate_validation_errors(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    data = setup_chapter(c)
    p1 = data["panels"][0]
    r = c.post(f"/panels/{p1['id']}/generate", json={"count": 5})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "count"
    r = c.post(f"/panels/{p1['id']}/generate", json={"preset": "inconnu"})
    assert r.status_code == 422 and "workflow inconnu" in r.json()["errors"][0]["message"]
    r = c.post(f"/panels/{p1['id']}/generate", json={"seed": -1})
    assert r.status_code == 422
    assert c.post("/panels/9999/generate").json() == {"detail": "Case introuvable"}
    assert c.get("/panel-images/9999/file").json() == {"detail": "Version introuvable"}
    assert "Traceback" not in r.text


def test_no_comfyui_client_gives_503(
    make_client: Callable[..., TestClient], make_settings: Callable[..., Settings]
) -> None:
    with TestClient(create_app(make_settings(), providers=_providers(None))) as c:
        data = setup_chapter(c)
        r = c.post(f"/panels/{data['panels'][0]['id']}/generate")
        assert r.status_code == 503 and r.json()["detail"].startswith("ComfyUI indisponible")


# --- file unique ------------------------------------------------------------------------
def test_queue_runs_one_job_at_a_time_in_order(make_client: Callable[..., TestClient]) -> None:
    comfy = GatedComfy()
    c = make_client(comfy)
    data = setup_chapter(c)
    p1, p2, _ = data["panels"]
    first = _ok(c.post(f"/panels/{p1['id']}/generate", json={"count": 2, "seed": 10}), 202)
    second = _ok(c.post(f"/panels/{p2['id']}/generate", json={"seed": 20}), 202)
    assert comfy.started.acquire(timeout=5)

    q = _ok(c.get("/queue"))
    assert q["running"]["job"]["id"] == first[0]["id"] and q["running"]["position"] == 0
    assert q["running"]["job"]["progress"] == 50 and "étape 4/8" in q["running"]["job"]["message"]
    assert [i["job"]["id"] for i in q["pending"]] == [first[1]["id"], second[0]["id"]]
    assert [i["position"] for i in q["pending"]] == [1, 2]
    assert q["pending"][1]["label"] == "Les Lames · ch. 1 · p. 1 · case 2"
    assert q["pending"][0]["preset"] == "qwen-image-edit-ref" and q["pending"][1]["preset"] == "qwen-image-base"
    assert q["running"]["eta_s"] is None  # aucune durée connue encore
    assert q["comfyui"] == "mock"
    assert _ok(c.get(f"/panels/{p1['id']}"))["state"] == "generating"
    assert _ok(c.get(f"/panels/{p2['id']}"))["state"] == "queued"
    time.sleep(0.1)
    assert comfy.max_running == 1

    comfy.gate.set()
    _wait(c)
    assert comfy.max_running == 1 and comfy.order == [10, 11, 20]
    jobs = [_job(c, j["id"]) for j in [*first, *second]]
    assert all(j["status"] == "succeeded" for j in jobs)
    assert jobs[0]["finished_at"] <= jobs[1]["started_at"] and jobs[1]["finished_at"] <= jobs[2]["started_at"]
    assert _ok(c.get("/queue")) == {"running": None, "pending": [], "total_eta_s": 0.0, "comfyui": "mock"}

    # ETA : médiane des durées du preset
    comfy.gate.clear()
    later = _ok(c.post(f"/panels/{p2['id']}/generate", json={"count": 2}), 202)
    assert comfy.started.acquire(timeout=5)
    q = _ok(c.get("/queue"))
    assert q["pending"][0]["estimated_duration_s"] is not None and q["pending"][0]["eta_s"] is not None
    assert q["total_eta_s"] == q["pending"][-1]["eta_s"]
    comfy.gate.set()
    _wait(c)
    assert _job(c, later[1]["id"])["status"] == "succeeded"


def test_cancel_pending_and_running_jobs(make_client: Callable[..., TestClient]) -> None:
    comfy = GatedComfy()
    c = make_client(comfy)
    data = setup_chapter(c)
    p1 = data["panels"][0]
    jobs = _ok(c.post(f"/panels/{p1['id']}/generate", json={"count": 3}), 202)
    assert comfy.started.acquire(timeout=5)

    cancelled = _ok(c.post(f"/jobs/{jobs[2]['id']}/cancel"))
    assert cancelled["status"] == "cancelled"
    _ok(c.post(f"/jobs/{jobs[0]['id']}/cancel"))
    done = _wait_status(c, jobs[0]["id"], "cancelled")
    assert done["error"] is None and done["message"] == "Annulé"
    assert comfy.interrupts  # /interrupt envoyé à ComfyUI

    # le job 2 démarre ensuite, puis se termine normalement
    assert comfy.started.acquire(timeout=5)
    comfy.gate.set()
    _wait(c)
    assert _job(c, jobs[1]["id"])["status"] == "succeeded"
    assert [i["version"] for i in _ok(c.get(f"/panels/{p1['id']}/images"))] == [1]
    assert _ok(c.get(f"/panels/{p1['id']}"))["state"] == "review"
    r = c.post(f"/jobs/{jobs[1]['id']}/cancel")
    assert r.status_code == 409 and r.json()["detail"] == "Ce job est déjà terminé"
    assert c.post("/jobs/9999/cancel").status_code == 404


def test_job_sse_shows_generation_progress(make_client: Callable[..., TestClient]) -> None:
    comfy = GatedComfy()
    c = make_client(comfy)
    data = setup_chapter(c)
    [job] = _ok(c.post(f"/panels/{data['panels'][1]['id']}/generate"), 202)
    assert comfy.started.acquire(timeout=5)
    threading.Timer(0.6, comfy.gate.set).start()
    events = []
    with c.stream("GET", f"/jobs/{job['id']}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert events[0]["status"] == "running" and events[0]["progress"] == 50
    assert events[-1]["status"] == "succeeded" and events[-1]["progress"] == 100


def test_cancel_pending_llm_job_or_refuse_running(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    data = setup_chapter(c)
    _ok(c.patch(f"/chapters/{data['chapter']['id']}", json={"synopsis": "Aiko arrive."}))
    job = _ok(c.post(f"/chapters/{data['chapter']['id']}/script"), 202)
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    assert c.post(f"/jobs/{job['id']}/cancel").status_code == 409


# --- erreurs ----------------------------------------------------------------------------
def _http(handler: Callable[[httpx.Request], httpx.Response], **kw: Any) -> HttpComfyUIClient:
    return HttpComfyUIClient("http://127.0.0.1:8188", transport=httpx.MockTransport(handler), **kw)


def _generate_and_fail(c: TestClient, panel_index: int = 1) -> dict[str, Any]:
    data = setup_chapter(c)
    panel = data["panels"][panel_index]
    [job] = _ok(c.post(f"/panels/{panel['id']}/generate"), 202)
    _wait(c)
    out = _job(c, job["id"])
    assert out["status"] == "failed", out
    assert out["finished_at"] is not None and "Traceback" not in (out["error"] or "")
    panel_out = _ok(c.get(f"/panels/{panel['id']}"))
    assert panel_out["state"] == "draft" and panel_out["images"] == [] and panel_out["active_jobs"] == []
    return out


def test_comfyui_offline_fails_fast(make_client: Callable[..., TestClient]) -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        raise httpx.ConnectError("Connection refused", request=req)

    c = make_client(_http(handler))
    t0 = time.monotonic()
    job = _generate_and_fail(c)
    assert job["error"] == "ComfyUI hors ligne (127.0.0.1:8188)"
    assert time.monotonic() - t0 < 5 and calls == ["/prompt"]


def test_comfyui_offline_during_reference_upload(make_client: Callable[..., TestClient]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=req)

    job = _generate_and_fail(make_client(_http(handler)), panel_index=0)
    assert job["error"] == "ComfyUI hors ligne (127.0.0.1:8188)"


def test_workflow_refused_gives_node_errors(make_client: Callable[..., TestClient]) -> None:
    # Réponse 400 enregistrée sur un vrai ComfyUI (UNETLoader avec un fichier absent).
    recorded = json.loads((COMFY_FIXTURES / "prompt_400_missing_model.json").read_text())

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=recorded)

    job = _generate_and_fail(make_client(_http(handler)))
    assert job["error"].startswith("Workflow refusé par ComfyUI : le workflow ne passe pas la validation de ComfyUI")
    assert "nœud 1 (UNETLoader) : modèle introuvable dans ComfyUI : absent.safetensors" in job["error"]


def test_generation_timeout_from_preset(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    presets = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, presets)
    path = presets / "workflows" / "qwen-image-base.yaml"
    data = yaml.safe_load(path.read_text())
    data["timeout_s"] = 3
    path.write_text(yaml.safe_dump(data, allow_unicode=True))

    now = [0.0]
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        return httpx.Response(200, json={})  # /history vide, /interrupt

    def sleep(s: float) -> None:
        now[0] += s

    client = _http(handler, sleep=sleep, clock=lambda: now[0])
    job = _generate_and_fail(make_client(client, mangaka_presets_dir=presets))
    assert job["error"] == (
        "ComfyUI n'a pas terminé la génération en 3 s (délai réglable : timeout_s du preset qwen-image-base)"
    )
    assert "/interrupt" in paths


def test_execution_error_is_readable(make_client: Callable[..., TestClient]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        return httpx.Response(
            200,
            json={
                "p-1": {
                    "outputs": {},
                    "status": {
                        "status_str": "error",
                        "messages": [["execution_error", {"node_type": "KSampler", "exception_message": "OOM"}]],
                    },
                }
            },
        )

    job = _generate_and_fail(make_client(_http(handler)))
    assert job["error"] == "ComfyUI : exécution ComfyUI en échec : KSampler — OOM"


# --- redémarrage ------------------------------------------------------------------------
def test_restart_recovers_generation_jobs_and_states(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    with TestClient(create_app(settings, providers=_providers(MockComfyUIClient()))) as c:
        data = setup_chapter(c)
        panel_id = data["panels"][0]["id"]
        # arrêt brutal en pleine génération : file stoppée, un job en cours et un en attente en base
        c.app.state.ctx.generation.shutdown()  # type: ignore[attr-defined]
        with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
            panel = session.get(Panel, panel_id)
            assert panel is not None
            panel.state = PanelState.generating
            for status in (JobStatus.running, JobStatus.pending):
                session.add(Job(step="generation", panel_id=panel_id, status=status, params={"preset": "x"}))
            session.commit()

    with TestClient(create_app(settings, providers=_providers(MockComfyUIClient()))) as c:
        with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
            jobs = session.query(Job).filter(Job.step == "generation").all()
            assert [j.status for j in jobs] == [JobStatus.failed, JobStatus.failed]
            assert all(j.error == "Interrompu par un redémarrage du moteur" for j in jobs)
        assert _ok(c.get("/queue"))["pending"] == []
        assert _ok(c.get(f"/panels/{panel_id}"))["state"] == "draft"
        # la file fonctionne de nouveau
        _ok(c.post(f"/panels/{panel_id}/generate"), 202)
        _wait(c)
        assert _ok(c.get(f"/panels/{panel_id}"))["state"] == "review"


def test_workflow_presets_endpoint(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    presets = {p["id"]: p for p in _ok(c.get("/presets/workflows"))}
    assert presets["qwen-image-base"]["is_default"] and presets["qwen-image-base"]["reference_slots"] == 0
    edit = presets["qwen-image-edit-ref"]
    assert edit["is_reference_default"] and edit["reference_slots"] == 3 and edit["supports_lora"]
    assert edit["lora_loader"] == "LoraLoaderModelOnly" and edit["timeout_s"] == 1500
    assert presets["qwen-image-base"]["with_references"] == "qwen-image-edit-ref"
    assert presets["qwen-image-base-rapide"]["with_references"] == "qwen-image-edit-ref-rapide"
    assert all(p["has_trial"] for p in presets.values())
