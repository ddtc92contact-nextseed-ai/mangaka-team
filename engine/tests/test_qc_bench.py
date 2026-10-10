# ruff: noqa: F401, F811 — fixtures pytest importées de test_qc
"""Banc d'essai du QC : annotations, calculs (précision, rappel, balayage, seuil suggéré), runs, seuils appliqués."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from mangaka_engine.pipeline.qc import LayerResult
from mangaka_engine.pipeline.qc_bench import (
    Sample,
    apply_changes,
    compute_metrics,
    confusion,
    evaluate_item,
    flagged_at,
    layer_metrics,
    precision,
    recall,
    set_yaml_scalar,
    strip_timings,
    suggest_threshold,
    sweep,
)
from mangaka_engine.presets import PresetError, PresetRegistry
from mangaka_engine.providers.qc import Box, Detections
from mangaka_engine.store.models import QCVerdict
from tests.conftest import PRESETS_DIR, STYLE
from tests.test_generation import GatedComfy, _job, _ok, _wait, setup_chapter
from tests.test_qc import (  # fixtures make_client, presets_copy comprises
    QC,
    RecordingVision,
    ScriptedIdentity,
    edit_qc,
    make_client,
    presets_copy,
    providers,
)


# --- calculs sur des cas connus -------------------------------------------------------------
def test_confusion_precision_recall() -> None:
    c = confusion([(True, True), (True, False), (False, True), (False, False), (False, False)])
    assert c == {"tp": 1, "fp": 1, "fn": 1, "tn": 2}
    assert precision(c) == 0.5 and recall(c) == 0.5
    assert precision({"tp": 0, "fp": 0, "fn": 3, "tn": 0}) is None  # rien de signalé
    assert recall({"tp": 0, "fp": 2, "fn": 0, "tn": 1}) is None  # aucune mauvaise case
    assert precision({"tp": 3, "fp": 1, "fn": 0, "tn": 0}) == 0.75


KNOWN = [
    Sample(bad=True, value=10),
    Sample(bad=True, value=50),
    Sample(bad=False, value=60),
    Sample(bad=False, value=90),
]


def test_threshold_sweep_on_known_case() -> None:
    points = {p["threshold"]: p for p in sweep(KNOWN)}
    assert len(points) == 101 and min(points) == 0 and max(points) == 100
    # signalée si valeur < seuil
    assert (points[0]["tp"], points[0]["fp"], points[0]["precision"], points[0]["recall"]) == (0, 0, None, 0.0)
    assert (points[11]["tp"], points[11]["recall"], points[11]["precision"]) == (1, 0.5, 1.0)
    assert (points[51]["tp"], points[51]["fp"], points[51]["precision"], points[51]["recall"]) == (2, 0, 1.0, 1.0)
    assert (points[61]["fp"], points[61]["precision"]) == (1, round(2 / 3, 4))
    assert (points[100]["tp"], points[100]["fp"], points[100]["tn"], points[100]["precision"]) == (2, 2, 0, 0.5)
    # rappel croissant avec le seuil
    recalls = [p["recall"] for p in sweep(KNOWN)]
    assert recalls == sorted(recalls)


def test_suggested_threshold_lets_almost_no_bad_panel_through() -> None:
    best = suggest_threshold(sweep(KNOWN), 0.95)
    assert best is not None and best["threshold"] == 51 and best["recall"] == 1.0 and best["precision"] == 1.0
    # objectif plus lâche : le seuil le plus bas qui l'atteint (moins de cases signalées)
    assert suggest_threshold(sweep(KNOWN), 0.5)["threshold"] == 11  # type: ignore[index]
    # chevauchement : la meilleure précision au rappel visé
    overlap = [Sample(True, 30), Sample(True, 70), Sample(False, 40), Sample(False, 80), Sample(False, 95)]
    best = suggest_threshold(sweep(overlap), 0.95)
    assert best is not None and best["threshold"] == 71 and (best["tp"], best["fp"]) == (2, 1)
    # à précision égale, on reste au plus près du seuil actuel (ici 51 à 60 se valent)
    assert suggest_threshold(sweep(KNOWN), 0.95, current=58)["threshold"] == 58  # type: ignore[index]
    assert suggest_threshold(sweep(KNOWN), 0.95, current=70)["threshold"] == 60  # type: ignore[index]
    # règles qui signalent déjà toutes les mauvaises cases : le seuil actuel est gardé (pas de saut à 0)
    floors = [Sample(True, 90, floor=True), Sample(False, 95), Sample(False, 85)]
    assert suggest_threshold(sweep(floors), 0.95, current=70)["threshold"] == 70  # type: ignore[index]
    # inatteignable : une mauvaise case à 100 n'est jamais signalée (seuil max 100)
    assert suggest_threshold(sweep([Sample(True, 100), Sample(False, 20)]), 0.95) is None
    # aucune mauvaise case : rappel non mesurable
    assert suggest_threshold(sweep([Sample(False, 20)]), 0.95) is None


def test_rule_floor_is_flagged_whatever_the_threshold() -> None:
    s = Sample(bad=False, value=100, floor=True)
    assert flagged_at(s, 0) and flagged_at(s, 100)
    assert Sample(bad=True, value=None, floor=True).evaluated and not Sample(bad=True, value=None).evaluated


def test_layer_metrics_current_threshold_and_missing() -> None:
    samples = [*KNOWN, Sample(bad=True, value=None)]  # couche indisponible sur une case
    m = layer_metrics(samples, current_threshold=70, target_recall=0.95, durations_ms=[10, 30])
    assert (m["evaluated"], m["missing"], m["good"], m["bad"]) == (4, 1, 2, 2)
    assert m["confusion"] == {"tp": 2, "fp": 1, "fn": 0, "tn": 1}  # 60 < 70 : bonne case signalée
    assert (m["precision"], m["recall"], m["mean_ms"]) == (round(2 / 3, 4), 1.0, 20)
    assert m["suggested"]["threshold"] == 60 and m["suggestion_note"] is None  # 51–60 se valent : au plus près de 70
    # verdict actuel fourni par la couche : prioritaire sur le seuil
    m = layer_metrics([Sample(True, 90, flagged=True)], current_threshold=70, target_recall=0.95)
    assert m["confusion"]["tp"] == 1
    m = layer_metrics([Sample(False, 50)], current_threshold=70, target_recall=0.95)
    assert m["suggested"] is None and "rappel non mesurable" in m["suggestion_note"]
    m = layer_metrics([Sample(True, 100)], current_threshold=70, target_recall=0.95)
    assert "inatteignable" in m["suggestion_note"]


def test_evaluate_item_layers_and_combined_replay() -> None:
    det = LayerResult("done", score=100)
    ide = LayerResult(
        "done",
        score=80,
        at_least=QCVerdict.review,
        extra={"characters": [{"name": "A", "similarity": 0.95}, {"name": "B", "similarity": 0.7}]},
    )
    vis = LayerResult("done", score=20, duration_ms=500)
    out = evaluate_item({"detectors": det, "identity": ide, "vision": vis}, QC)
    assert out["detectors"]["value"] == 100 and out["detectors"]["flagged"] is False
    assert out["identity"]["value"] == 70.0 and out["identity"]["floor"] is False  # similarité min. × 100
    assert out["identity"]["flagged"] is True  # règle « au moins à revoir » du preset
    assert out["vision"]["flagged"] is True
    # couches 1-2 hors de la zone de doute : le QC réel n'aurait pas lancé la vision
    prelim = round(
        (QC.weights.detectors * 100 + QC.weights.identity * 80) / (QC.weights.detectors + QC.weights.identity)
    )
    assert prelim >= QC.vision.doubt_band.max
    assert out["combined"]["vision_used"] is False and out["combined"]["score"] == prelim
    assert out["combined"]["verdict"] == "review" and out["combined"]["flagged"] is True
    # couches 1-2 dans la zone de doute : la vision compte
    doubt = LayerResult("done", score=QC.vision.doubt_band.min)
    out = evaluate_item({"detectors": doubt, "vision": vis}, QC)
    assert out["combined"]["vision_used"] is True and out["combined"]["duration_ms"] == 500
    # couche en erreur : non évaluée
    out = evaluate_item({"detectors": LayerResult("error", message="x"), "vision": vis}, QC)
    assert out["detectors"]["value"] is None and out["detectors"]["flagged"] is None


def test_compute_metrics_is_deterministic_on_fixture_items() -> None:
    def item(bad: bool, det: int, vis: int) -> dict[str, Any]:
        layers = {"detectors": LayerResult("done", score=det, duration_ms=5), "vision": LayerResult("done", score=vis)}
        return {"bad": bad, "layers": evaluate_item(layers, QC)}

    items = [item(True, 20, 30), item(True, 65, 90), item(False, 95, 85), item(False, 75, 50), item(False, 100, 95)]
    m = compute_metrics(items, QC)
    assert (m["samples"], m["good"], m["bad"]) == (5, 3, 2)
    assert m["layers"]["detectors"]["confusion"] == {"tp": 2, "fp": 0, "fn": 0, "tn": 3}
    assert m["layers"]["vision"]["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 2}
    assert m["layers"]["detectors"]["mean_ms"] == 5 and m["layers"]["identity"]["evaluated"] == 0
    assert m["layers"]["combined"]["threshold_key"] == "verdict.ok_min"
    assert m["layers"]["identity"]["threshold_key"] == "identity.min_similarity"
    assert strip_timings(compute_metrics(items, QC)) == strip_timings(m)


# --- écriture de qc.yaml ----------------------------------------------------------------------
def test_set_yaml_scalar_keeps_comments() -> None:
    text = (PRESETS_DIR / "qc.yaml").read_text(encoding="utf-8")
    out = set_yaml_scalar(text, "verdict.ok_min", 63)
    out = set_yaml_scalar(out, "identity.min_similarity", 0.77)
    assert "  ok_min: 63        # score combiné ≥ 70 → ok" in out
    assert "  min_similarity: 0.77\n" in out
    assert out.count("\n") == text.count("\n") and out.count("#") == text.count("#")
    data = yaml.safe_load(out)
    assert data["verdict"]["ok_min"] == 63 and data["identity"]["min_similarity"] == 0.77
    assert data["detectors"]["face"]["min_confidence"] == 0.35  # rien d'autre ne bouge
    with pytest.raises(PresetError, match="introuvable"):
        set_yaml_scalar(text, "verdict.inexistant", 1)


def test_apply_changes_refuses_an_invalid_result(presets_copy: Path) -> None:
    reg = PresetRegistry.load(presets_copy)
    before = (presets_copy / "qc.yaml").read_text(encoding="utf-8")
    with pytest.raises(PresetError, match="reject_below"):
        apply_changes(reg, [{"key": "verdict.ok_min", "after": 10}])  # < reject_below
    assert (presets_copy / "qc.yaml").read_text(encoding="utf-8") == before


# --- API : fixtures de cases annotées --------------------------------------------------------
class FixtureDetectors:
    """Détecteurs au résultat imposé par image : texte parasite sur les images listées."""

    name = "fixture"

    def __init__(self) -> None:
        self.text_on: set[bytes] = set()

    def detect(self, image: bytes, **kw: Any) -> Detections:
        faces = [Box(10, 10, 30, 30, 0.9, "face")]
        text = [Box(50, 50, 70, 60, 0.9, "text")] if image in self.text_on else []
        return Detections(width=100, height=100, faces=faces, text=text)


def _annotated_chapter(c: TestClient, det: FixtureDetectors | None = None) -> dict[str, Any]:
    """3 cases × 2 versions ; versions 1 « mauvaises », versions 2 « bonnes ».
    Les détecteurs voient du texte sur 2 mauvaises et 1 bonne → VP 2, FN 1, FP 1, VN 2."""
    data = setup_chapter(c)
    for p in data["panels"]:
        _ok(c.post(f"/panels/{p['id']}/generate", json={"seed": 100 + p["index"] * 10, "count": 2}), 202)
    _wait(c)
    images: list[dict[str, Any]] = []
    for p in data["panels"]:
        images += _ok(c.get(f"/panels/{p['id']}/images"))
    bad = [i for i in images if i["version"] == 1]
    good = [i for i in images if i["version"] == 2]
    for i in bad:
        _ok(c.put(f"/panel-images/{i['id']}/annotation", json={"label": "bad", "defects": ["text"], "note": "lettres"}))
    for i in good:
        _ok(c.put(f"/panel-images/{i['id']}/annotation", json={"label": "good"}))
    if det is not None:
        for i in [*bad[:2], good[0]]:
            det.text_on.add(c.get(f"/panel-images/{i['id']}/file").content)
    return {**data, "bad": bad, "good": good}


def _run(c: TestClient, **body: Any) -> dict[str, Any]:
    run = _ok(c.post("/qc/bench/runs", json=body), 202)
    _wait(c)
    return _ok(c.get(f"/qc/bench/runs/{run['id']}"))


def test_annotation_api(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    c = make_client(mangaka_presets_dir=presets_copy)
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    [img] = _ok(c.get(f"/panels/{p1['id']}/images"))
    assert img["annotation"] is None
    url = f"/panel-images/{img['id']}/annotation"
    ann = _ok(c.put(url, json={"label": "bad", "defects": ["hands", "face", "hands"], "note": "  doigts  "}))
    assert ann["label"] == "bad" and ann["defects"] == ["hands", "face"] and ann["note"] == "doigts"
    assert _ok(c.get(f"/panels/{p1['id']}"))["images"][0]["annotation"]["defects"] == ["hands", "face"]
    # indépendant du verdict QC
    assert _ok(c.get(f"/panels/{p1['id']}/images"))[0]["qc_verdict"] is None
    # « bonne » : les défauts disparaissent
    assert _ok(c.put(url, json={"label": "good", "defects": ["text"]}))["defects"] == []
    errors = _ok(c.put(url, json={"label": "moyenne"}), 422)["errors"]
    assert errors[0]["field"] == "label"
    assert _ok(c.put(url, json={"label": "bad", "defects": ["pieds"]}), 422)["errors"][0]["field"].startswith("defects")
    assert _ok(c.put("/panel-images/9999/annotation", json={"label": "bad"}), 404)
    stats = _ok(c.get("/qc/bench/dataset"))
    assert (stats["good"], stats["bad"], stats["total"]) == (1, 0, 1)
    assert (stats["goal_min"], stats["goal_max"], stats["target_recall"]) == (50, 100, 0.95)
    assert c.delete(url).status_code == 204 and _ok(c.get("/qc/bench/dataset"))["total"] == 0
    # l'annotation part avec la version
    _ok(c.put(url, json={"label": "bad"}))
    assert c.delete(f"/panel-images/{img['id']}").status_code == 204
    assert _ok(c.get("/qc/bench/dataset"))["total"] == 0


def test_bench_run_on_fixture_gives_known_metrics(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    det = FixtureDetectors()
    vision = RecordingVision(score=90)
    c = make_client(
        providers(detectors=det, identity=ScriptedIdentity(0.95), vision=vision), mangaka_presets_dir=presets_copy
    )
    data = _annotated_chapter(c, det)
    chapter_id = data["chapter"]["id"]
    assert _ok(c.get(f"/qc/bench/dataset?chapter_id={chapter_id}"))["by_defect"]["text"] == 3

    run = _run(c, chapter_id=chapter_id)
    assert run["status"] == "succeeded" and run["sample_count"] == 6 and (run["good"], run["bad"]) == (3, 3)
    assert run["scope"] == "Les Lames · ch. 1" and run["project_id"] is None and run["chapter_id"] == chapter_id
    assert run["preset_hash"] and run["preset_hash"] == run["current_preset_hash"]
    assert run["preset"]["verdict"]["ok_min"] == QC.verdict.ok_min
    assert run["job"]["status"] == "succeeded" and "6 cases mesurées" in run["job"]["message"]
    layers = run["metrics"]["layers"]
    assert layers["detectors"]["confusion"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 2}
    assert (layers["detectors"]["precision"], layers["detectors"]["recall"]) == (round(2 / 3, 4), round(2 / 3, 4))
    # texte → rejet imposé : le QC combiné voit la même chose
    assert layers["combined"]["confusion"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 2}
    # vision factice (90 partout) et identité (0,95) ne signalent rien
    assert layers["vision"]["confusion"] == {"tp": 0, "fp": 0, "fn": 3, "tn": 3} and vision.calls == 6
    assert layers["identity"]["evaluated"] == 2  # seules les cases d'Aiko ont une référence
    # une mauvaise case sans défaut détecté : objectif 95 % de rappel inatteignable au mieux à 100
    assert layers["detectors"]["suggested"] is None and "inatteignable" in layers["detectors"]["suggestion_note"]
    assert all(isinstance(m["mean_ms"], int) for m in (layers["detectors"], layers["vision"]))
    assert isinstance(run["metrics"]["mean_ms_per_case"], int)
    # erreurs cliquables : chaque case porte page / chapitre / case
    fn = [i for i in run["items"] if i["bad"] and not i["layers"]["combined"]["flagged"]]
    assert len(fn) == 1 and fn[0]["chapter_id"] == chapter_id and fn[0]["page_id"] and fn[0]["panel_id"]
    assert fn[0]["label"].startswith("Les Lames · ch. 1 · p. ") and fn[0]["defects"] == ["text"]

    # déterministe : un 2e run donne les mêmes métriques (hors durées), et devient le « précédent »
    again = _run(c, chapter_id=chapter_id)
    assert strip_timings(again["metrics"]) == strip_timings(run["metrics"])
    assert again["previous"]["id"] == run["id"] and again["previous"]["layers"]["combined"]["fn"] == 1
    listed = _ok(c.get("/qc/bench/runs"))
    assert [r["id"] for r in listed] == [again["id"], run["id"]]
    assert listed[0]["layers"]["combined"]["precision"] == round(2 / 3, 4)


def test_bench_run_mock_providers_is_deterministic(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    c = make_client(mangaka_presets_dir=presets_copy)
    _annotated_chapter(c)
    a, b = _run(c), _run(c)
    assert a["scope"] == "toutes les séries" and a["sample_count"] == 6
    assert strip_timings(a["metrics"]) == strip_timings(b["metrics"])
    for name in ("detectors", "identity", "vision", "combined"):
        m = a["metrics"]["layers"][name]
        c_ = m["confusion"]
        assert sum(c_.values()) == m["evaluated"] and len(m["sweep"]) == 101


def test_bench_run_errors_and_states(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    c = make_client(mangaka_presets_dir=presets_copy)
    assert _ok(c.post("/qc/bench/runs", json={}), 422)["errors"][0]["field"] == "dataset"
    data = _annotated_chapter(c)
    assert _ok(c.post("/qc/bench/runs", json={"project_id": 999}), 422)["errors"][0]["field"] == "project_id"
    other = _ok(c.post("/projects", json={**STYLE, "title": "Autre"}), 201)
    body = {"project_id": other["id"], "chapter_id": data["chapter"]["id"]}
    assert _ok(c.post("/qc/bench/runs", json=body), 422)["errors"][0]["field"] == "chapter_id"
    assert _ok(c.get(f"/qc/bench/dataset?project_id={other['id']}"))["total"] == 0
    assert _ok(c.get("/qc/bench/runs/999"), 404)
    # une version supprimée après le lancement : la case est comptée en erreur, le run continue
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    run = _ok(c.post("/qc/bench/runs", json={"vision": False}), 202)
    assert _ok(c.post("/qc/bench/runs", json={}), 409)["detail"].startswith("Un banc d'essai est déjà en cours")
    assert run["status"] in ("pending", "running") and run["vision"] is False
    _wait(c)
    detail = _ok(c.get(f"/qc/bench/runs/{run['id']}"))
    assert detail["status"] == "succeeded"
    assert all(i["layers"]["vision"]["status"] == "skipped" for i in detail["items"])
    assert detail["metrics"]["layers"]["vision"]["evaluated"] == 0
    assert ctx.generation.wait_idle(1)


def test_bench_job_shows_in_queue_and_vision_never_runs_during_generation(
    make_client: Callable[..., TestClient],
    presets_copy: Path,
) -> None:
    """Le banc passe par la file de la génération : sa vision ne tourne jamais pendant ComfyUI."""
    edit_qc(presets_copy, auto_after_generation=False)
    comfy = GatedComfy()
    comfy.gate.set()
    vision = RecordingVision(busy=lambda: comfy.running)
    c = make_client(providers(comfy=comfy, vision=vision), mangaka_presets_dir=presets_copy)
    data = _annotated_chapter(c)
    comfy.gate.clear()
    while comfy.started.acquire(blocking=False):
        pass
    _ok(c.post(f"/panels/{data['panels'][0]['id']}/generate"), 202)
    assert comfy.started.acquire(timeout=5)  # une génération tourne
    run = _ok(c.post("/qc/bench/runs", json={}), 202)
    queue = _ok(c.get("/queue"))
    assert queue["running"]["job"]["step"] == "generation"
    [pending] = [i for i in queue["pending"] if i["job"]["step"] == "qc_bench"]
    assert pending["label"] == "Banc d'essai QC · toutes les séries (6 cases)"
    assert _job(c, run["job"]["id"])["status"] == "pending" and vision.calls == 0
    comfy.gate.set()
    _wait(c)
    assert _ok(c.get(f"/qc/bench/runs/{run['id']}"))["status"] == "succeeded"
    assert vision.calls == 6 and set(vision.busy_at_call) == {0}


class FixtureVision:
    """Vision au score imposé par image."""

    name = "fixture"

    def __init__(self) -> None:
        self.scores: dict[bytes, int] = {}

    def ask(self, image: bytes, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        return json.dumps({"score": self.scores.get(image, 50), "raisons": []})


def test_apply_suggested_thresholds_after_confirmation(
    make_client: Callable[..., TestClient], presets_copy: Path
) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    original = (presets_copy / "qc.yaml").read_text(encoding="utf-8")
    vision = FixtureVision()
    # vision seule : mauvaises 10–20, bonnes 25–35 → seuil combiné suggéré 25 (21–25 se valent : au plus près de 70 ; < reject_below 40)
    c = make_client(providers(detectors=None, identity=None, vision=vision), mangaka_presets_dir=presets_copy)
    data = _annotated_chapter(c)
    for img, score in zip([*data["bad"], *data["good"]], [10, 15, 20, 25, 30, 35], strict=True):
        vision.scores[c.get(f"/panel-images/{img['id']}/file").content] = score
    run = _run(c)
    combined = run["metrics"]["layers"]["combined"]
    assert combined["suggested"]["threshold"] == 25 and combined["suggested"]["recall"] == 1.0
    assert combined["suggested"]["precision"] == 1.0
    url = f"/qc/bench/runs/{run['id']}/apply"

    preview = _ok(c.post(url, json={}))
    assert preview["applied"] is False and preview["preset_changed"] is False
    keys = {ch["key"]: ch for ch in preview["changes"]}
    assert keys["verdict.ok_min"] == {**keys["verdict.ok_min"], "before": QC.verdict.ok_min, "after": 25}
    assert keys["verdict.reject_below"]["after"] == 25  # reste ≤ ok_min : le fichier reste valide
    assert (presets_copy / "qc.yaml").read_text(encoding="utf-8") == original  # rien d'écrit sans confirmation

    done = _ok(c.post(url, json={"confirm": True}))
    assert done["applied"] is True and "rechargé" in done["message"]
    reloaded = PresetRegistry.load(presets_copy)  # le fichier reste valide au rechargement
    assert reloaded.qc is not None and (reloaded.qc.verdict.ok_min, reloaded.qc.verdict.reject_below) == (25, 25)
    assert not [i for i in reloaded.issues if i.file == "qc.yaml"]
    text = (presets_copy / "qc.yaml").read_text(encoding="utf-8")
    assert text.count("#") == original.count("#")  # commentaires conservés
    assert _ok(c.get("/qc/status"))["ok_min"] == 25  # preset rechargé en mémoire
    assert _ok(c.get(f"/qc/bench/runs/{run['id']}"))["applied_at"] is not None
    # le preset a changé depuis ce run ; réappliquer ne change plus rien
    again = _ok(c.post(url, json={"confirm": True}))
    assert again["applied"] is False and again["changes"] == [] and again["preset_changed"] is True


def test_export_json_and_csv(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    c = make_client(mangaka_presets_dir=presets_copy)
    _annotated_chapter(c)
    run = _run(c, vision=False)
    resp = c.get(f"/qc/bench/runs/{run['id']}/export?format=json")
    assert resp.status_code == 200 and "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["id"] == run["id"] and len(data["items"]) == 6 and "sweep" in data["metrics"]["layers"]["combined"]
    resp = c.get(f"/qc/bench/runs/{run['id']}/export?format=csv")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))
    assert rows[0][:3] == ["image_id", "case", "annotation"] and len(rows) == 7
    assert {r[2] for r in rows[1:]} == {"bonne", "mauvaise"}
    assert any(r[3] == "texte parasite" for r in rows[1:])
    assert c.get(f"/qc/bench/runs/{run['id']}/export?format=xml").status_code == 422
