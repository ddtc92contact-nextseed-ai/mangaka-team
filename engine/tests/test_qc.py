"""Étape 4 : contrôle qualité en couches (détecteurs, cohérence des personnages, vision), tout simulé."""

from __future__ import annotations

import os
import shutil
import threading
import time
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from packaging.requirements import Requirement

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.qc import (
    LayerResult,
    combine,
    evaluate_detections,
    evaluate_identity,
    filter_detections,
    parse_vision_answer,
    run_vision,
    vision_decision,
)
from mangaka_engine.presets import PresetError, PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.providers.qc import Box, Detections, MockDetectorProvider, MockIdentityProvider
from mangaka_engine.providers.qc.dghs import DETECTOR_MODELS, _call_onnx, check_detector_options
from mangaka_engine.providers.vision import MockVisionProvider, VisionResponseError
from mangaka_engine.store.models import Job, JobStatus, QCVerdict
from tests.conftest import PRESETS_DIR, png_bytes
from tests.test_generation import GatedComfy, _job, _ok, _wait, setup_chapter

QC = PresetRegistry.load(PRESETS_DIR).require_qc()


# --- outillage ------------------------------------------------------------------------------
class ScriptedDetectors:
    """Détecteurs factices au résultat imposé (nombre de visages, texte, confiance des mains)."""

    name = "test"

    def __init__(self, faces: int = 1, text: int = 0, hands: tuple[float, ...] = ()) -> None:
        self.faces, self.text, self.hands = faces, text, hands
        self.calls = 0

    def detect(self, image: bytes, **kw: Any) -> Detections:
        self.calls += 1
        return Detections(
            width=100,
            height=100,
            faces=[Box(10 * i, 10, 10 * i + 20, 30, 0.9, "face") for i in range(self.faces)],
            hands=[Box(50, 50, 60, 60, s, "hand") for s in self.hands],
            text=[Box(70, 70, 90, 80, 0.8, "text") for _ in range(self.text)],
        )


class ScriptedIdentity:
    name = "test"

    def __init__(self, similarity: float = 0.95) -> None:
        self.similarity = similarity

    def compare(
        self, image: bytes, crops: list[Box], references: dict[str, list[bytes]], **kw: Any
    ) -> dict[str, float]:
        return {name: self.similarity for name in references}


class RecordingVision(MockVisionProvider):
    """Vision factice qui note l'instant de chaque appel."""

    def __init__(self, score: int = 80, invalid_attempts: int = 0, busy: Callable[[], int] | None = None) -> None:
        super().__init__(score=score, invalid_attempts=invalid_attempts)
        self.times: list[float] = []
        self.busy = busy or (lambda: 0)
        self.busy_at_call: list[int] = []

    def ask(self, image: bytes, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        self.times.append(time.monotonic())
        self.busy_at_call.append(self.busy())
        return super().ask(image, prompt, schema=schema)


def providers(
    comfy: Any = None,
    detectors: Any = "mock",
    identity: Any = "mock",
    vision: Any = "mock",
) -> Providers:
    det = MockDetectorProvider() if detectors == "mock" else detectors
    ide = MockIdentityProvider() if identity == "mock" else identity
    vis = MockVisionProvider() if vision == "mock" else vision
    errors = {}
    if det is None:
        errors["detectors"] = 'détecteurs non installés : pip install -e "engine[qc]" (voir README)'
    if ide is None:
        errors["identity"] = 'détecteurs non installés : pip install -e "engine[qc]" (voir README)'
    if vis is None:
        errors["vision"] = "Ollama injoignable"
    return Providers(
        llm=MockLLMProvider(),
        vision=vis,
        comfyui=comfy if comfy is not None else MockComfyUIClient(),
        detectors=det,
        identity=ide,
        names={"llm": "mock", "vision": "mock", "comfyui": "mock", "detectors": "mock", "identity": "mock"},
        errors=errors,
    )


@pytest.fixture
def presets_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, dest)
    return dest


def edit_qc(presets_dir: Path, **changes: Any) -> None:
    path = presets_dir / "qc.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for dotted, value in changes.items():
        node = data
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(p: Providers | None = None, **settings: Any) -> TestClient:
        c = TestClient(create_app(make_settings(**settings), providers=p or providers()))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _images(c: TestClient, panel_id: int) -> list[dict[str, Any]]:
    return _ok(c.get(f"/panels/{panel_id}/images"))


def _panel(c: TestClient, panel_id: int) -> dict[str, Any]:
    return _ok(c.get(f"/panels/{panel_id}"))


# --- couche 1 : règles des détecteurs ----------------------------------------------------------
def _det(faces: int = 0, text: int = 0, hands: tuple[float, ...] = ()) -> Detections:
    return ScriptedDetectors(faces, text, hands).detect(b"")


def test_detectors_missing_face_is_at_least_review() -> None:
    res = evaluate_detections(_det(faces=1), expected_faces=2, shot_type="plan moyen", cfg=QC.detectors)
    assert res.at_least == QCVerdict.review
    assert res.score == 100 - QC.detectors.rules.missing_face.penalty
    assert res.reasons == ["Visage manquant : 1 détecté pour 2 personnages attendus"]
    assert res.extra["counts"] == {"faces": 1, "hands": 0, "text": 0}


def test_detectors_text_is_a_defect_and_forces_reject() -> None:
    res = evaluate_detections(_det(faces=1, text=2), expected_faces=1, shot_type=None, cfg=QC.detectors)
    assert res.at_least == QCVerdict.reject and "Texte parasite détecté (2 zones)" in res.reasons[0]
    combined = combine({"detectors": res}, QC.weights, QC.verdict)
    assert combined is not None and combined.verdict == QCVerdict.reject


def test_detectors_suspect_hands_and_extra_faces_and_ignored_shots() -> None:
    rules = QC.detectors.rules
    res = evaluate_detections(
        _det(faces=1, hands=(0.4, 0.45, 0.42, 0.9)), expected_faces=1, shot_type=None, cfg=QC.detectors
    )
    assert res.score == 100 - min(rules.suspect_hand.max_penalty, 3 * rules.suspect_hand.penalty)
    assert res.reasons[0].startswith("Mains douteuses (3, confiance min. 0,40)")
    extra = 1 + rules.extra_face.tolerance + 2
    res = evaluate_detections(_det(faces=extra), expected_faces=1, shot_type=None, cfg=QC.detectors)
    assert res.score == 100 - 2 * rules.extra_face.penalty and "Visages en trop" in res.reasons[0]
    # insert : le nombre de visages n'est pas vérifié
    res = evaluate_detections(_det(faces=0), expected_faces=2, shot_type="Insert", cfg=QC.detectors)
    assert res.score == 100 and res.reasons == [] and res.extra["face_count_checked"] is False


def test_low_confidence_boxes_are_ignored() -> None:
    det = Detections(100, 100, faces=[Box(0, 0, 5, 5, QC.detectors.face.min_confidence - 0.01)])
    assert filter_detections(det, QC.detectors).faces == []


# --- couche 2 et combinaison ------------------------------------------------------------------
def test_identity_below_threshold_is_review() -> None:
    low = QC.identity.min_similarity - 0.1
    res = evaluate_identity({"Aiko": 0.97, "Kenji": low}, without_references=["Mei"], cfg=QC.identity)
    assert res.at_least == QCVerdict.review and res.score == round((97 + low * 100) / 2)
    assert res.reasons[0].startswith("Kenji ne ressemble pas assez à sa fiche")
    assert evaluate_identity({}, without_references=["Mei"], cfg=QC.identity).status == "skipped"


def test_combine_weights_thresholds_and_floors() -> None:
    w, t = QC.weights, QC.verdict
    det = LayerResult("done", score=100)
    ide = LayerResult("done", score=50)
    combined = combine({"detectors": det, "identity": ide}, w, t)
    expected = round((w.detectors * 100 + w.identity * 50) / (w.detectors + w.identity))
    assert combined is not None and combined.score == expected
    # couches non notées ignorées, poids renormalisés
    combined = combine({"detectors": det, "vision": LayerResult("unavailable", message="x")}, w, t)
    assert combined is not None and (combined.score, combined.verdict) == (100, QCVerdict.ok)
    # seuils
    for score, verdict in ((t.ok_min, "ok"), (t.ok_min - 1, "review"), (t.reject_below - 1, "reject")):
        got = combine({"vision": LayerResult("done", score=score)}, w, t)
        assert got is not None and got.verdict == QCVerdict(verdict)
    # une règle durcit le verdict, jamais l'inverse
    floored = combine({"detectors": LayerResult("done", score=100, at_least=QCVerdict.review)}, w, t)
    assert floored is not None and floored.verdict == QCVerdict.review and floored.score == 100
    assert combine({"vision": LayerResult("skipped")}, w, t) is None


def test_vision_decision_uses_doubt_band() -> None:
    band = QC.vision.doubt_band
    doubt = combine({"detectors": LayerResult("done", score=band.min)}, QC.weights, QC.verdict)
    sure = combine({"detectors": LayerResult("done", score=band.max)}, QC.weights, QC.verdict)
    rejected = combine(
        {"detectors": LayerResult("done", score=band.min, at_least=QCVerdict.reject)}, QC.weights, QC.verdict
    )
    assert vision_decision(doubt, QC.vision, "auto")[0] is True
    assert vision_decision(sure, QC.vision, "auto")[0] is False
    assert vision_decision(rejected, QC.vision, "auto")[0] is False
    assert vision_decision(None, QC.vision, "auto")[0] is True
    assert vision_decision(sure, QC.vision, "force")[0] is True
    assert vision_decision(doubt, QC.vision, "skip")[0] is False


# --- couche 3 : réponse de la vision ----------------------------------------------------------
def test_vision_answer_validation() -> None:
    assert parse_vision_answer('```json\n{"score": 55, "raisons": ["main floue"]}\n```').score == 55
    assert parse_vision_answer('{"score": 90, "reasons": ["ok"]}').raisons == ["ok"]
    with pytest.raises(ValueError, match="pas du JSON"):
        parse_vision_answer("bonne case")
    with pytest.raises(ValueError, match="score"):
        parse_vision_answer('{"score": 140, "raisons": []}')


def test_invalid_vision_answer_is_retried_once() -> None:
    vision = MockVisionProvider(score=64, invalid_attempts=1)
    answer, attempts = run_vision(vision, b"img", "p", max_retries=QC.vision.max_retries)
    assert (answer.score, attempts, vision.calls) == (64, 2, 2)


def test_invalid_vision_answer_twice_gives_readable_error() -> None:
    vision = MockVisionProvider(invalid_attempts=5)
    with pytest.raises(VisionResponseError, match="réponse invalide du modèle de vision après 2 essais : pas du JSON"):
        run_vision(vision, b"img", "p", max_retries=1)
    assert vision.calls == 2


# --- preset -------------------------------------------------------------------------------
def test_qc_preset_is_validated_at_load(presets_copy: Path) -> None:
    edit_qc(presets_copy, verdict__reject_below=90)
    reg = PresetRegistry.load(presets_copy)
    assert reg.qc is None and any(i.file == "qc.yaml" and "reject_below" in i.message for i in reg.issues)

    data = yaml.safe_load((presets_copy / "qc.yaml").read_text(encoding="utf-8"))
    data["verdict"]["reject_below"] = 40
    del data["detectors"]["rules"]["text"]  # aucun seuil par défaut dans le code
    (presets_copy / "qc.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(presets_copy)
    assert reg.qc is None and any("detectors.rules.text" in i.message for i in reg.issues)

    (presets_copy / "qc.yaml").unlink()
    reg = PresetRegistry.load(presets_copy)
    assert reg.qc is None and any(i.file == "qc.yaml" for i in reg.issues)


def test_qc_preset_detector_options_are_published_by_deepghs() -> None:
    data = yaml.safe_load((PRESETS_DIR / "qc.yaml").read_text(encoding="utf-8"))
    for kind in ("face", "hand", "text"):
        options = data["detectors"][kind]["options"]
        assert check_detector_options(kind, options) == [], f"detectors.{kind}.options"
        spec = DETECTOR_MODELS[kind]
        if "level" in options:
            assert options["level"] in spec["models"][options.get("version", spec["default_version"])]


def test_unknown_detector_level_is_a_readable_preset_error(presets_copy: Path) -> None:
    data = yaml.safe_load((presets_copy / "qc.yaml").read_text(encoding="utf-8"))
    data["detectors"]["hand"]["options"] = {"level": "m"}
    data["detectors"]["text"]["options"] = {"modle": "dbnet"}
    (presets_copy / "qc.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    reg = PresetRegistry.load(presets_copy)
    assert reg.qc is None
    msg = next(i.message for i in reg.issues if i.file == "qc.yaml")
    assert "detectors.hand.options" in msg and "« m »" in msg and "valeurs permises : n, s" in msg
    assert "detectors.text.options" in msg and "modle : option inconnue" in msg
    with pytest.raises(PresetError, match="contrôle qualité indisponible"):
        reg.require_qc()

    assert check_detector_options("face", {"version": "v1.2", "level": "n"})[0].startswith("level : « n »")
    assert "version : « v9 »" in check_detector_options("hand", {"version": "v9"})[0]
    assert "model : « x »" in check_detector_options("text", {"model": "x"})[0]


def test_qc_extra_installs_cpu_onnxruntime() -> None:
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    qc = [Requirement(r).name for r in pyproject["project"]["optional-dependencies"]["qc"]]
    assert "onnxruntime" in qc and "onnxruntime-gpu" not in qc


def test_detector_gpu_load_error_falls_back_to_cpu(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ONNX_MODE", "gpu")
    calls: list[str] = []

    def load() -> str:
        calls.append(os.environ["ONNX_MODE"])
        if os.environ["ONNX_MODE"] != "cpu":
            raise RuntimeError("libcudnn.so.9: cannot open shared object file")
        return "ok"

    assert _call_onnx(load) == "ok" and calls == ["gpu", "cpu"]
    assert "repli sur CPUExecutionProvider" in caplog.text

    with pytest.raises(ValueError, match="autre"):  # une autre erreur n'est pas masquée
        _call_onnx(lambda: (_ for _ in ()).throw(ValueError("autre")))


# --- API ------------------------------------------------------------------------------------
def test_auto_qc_after_generation_ok(make_client: Callable[..., TestClient]) -> None:
    det = ScriptedDetectors(faces=1)
    c = make_client(providers(detectors=det, identity=ScriptedIdentity(0.95), vision=RecordingVision()))
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    [img] = _images(c, p1["id"])
    assert img["qc_verdict"] == "ok" and img["qc_score"] is not None and img["qc_reasons"] == ["Aucun défaut détecté"]
    qc = img["qc"]
    assert qc["source"] == "auto" and qc["layers"]["detectors"]["status"] == "done"
    assert qc["layers"]["identity"]["characters"][0]["name"] == "Aiko"
    assert qc["layers"]["vision"]["status"] == "skipped"  # couches 1-2 sûres d'elles
    assert all(isinstance(layer["duration_ms"], int) for layer in qc["layers"].values())
    assert img["detections"]["faces"][0]["x1"] == 0 and img["detections"]["provider"] == "test"
    panel = _panel(c, p1["id"])
    assert panel["state"] == "approved"
    jobs = _ok(c.get(f"/chapters/{data['chapter']['id']}/jobs?step=qc"))
    assert len(jobs) == 1 and jobs[0]["status"] == "succeeded" and jobs[0]["message"] == "Verdict : ok"
    page = _ok(c.get(f"/chapters/{data['chapter']['id']}/pages"))[0]
    assert page["panels"][0]["qc_verdict"] == "ok"


def test_reject_triggers_one_auto_retry_then_review(make_client: Callable[..., TestClient]) -> None:
    det = ScriptedDetectors(faces=1, text=1)  # texte parasite → rejet à chaque fois
    c = make_client(providers(detectors=det, identity=ScriptedIdentity(0.95), vision=RecordingVision()))
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate", json={"seed": 7}), 202)
    _wait(c)
    images = _images(c, p1["id"])
    assert [i["version"] for i in images] == [1, 2]  # rien n'est supprimé
    v1, v2 = images
    assert v1["qc_verdict"] == "reject" and v1["qc"]["auto_retry"]["attempt"] == 1
    assert any("nouvel essai automatique lancé (1/1" in r for r in v1["qc_reasons"])
    assert v2["seed"] != 7 and v2["params"]["job_id"] == v1["qc"]["auto_retry"]["job_id"]
    assert v2["qc_verdict"] == "review" and v2["qc"]["computed_verdict"] == "reject" and v2["qc"]["attempt"] == 1
    assert any(r.startswith("Rejet confirmé après 1 nouvel essai automatique") for r in v2["qc_reasons"])
    gens = _ok(c.get(f"/chapters/{data['chapter']['id']}/jobs?step=generation"))
    assert len(gens) == 2 and any(
        j["params"].get("qc_attempt") == 1 and j["params"].get("retry_of") == v1["id"] for j in gens
    )
    assert len(_ok(c.get(f"/chapters/{data['chapter']['id']}/jobs?step=qc"))) == 2  # pas de 3e génération
    assert v2["selected"] and not v1["selected"]  # « à revoir » vaut mieux que « rejet »
    assert _panel(c, p1["id"])["state"] == "flagged"


def test_auto_qc_disabled_in_preset(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    c = make_client(mangaka_presets_dir=presets_copy)
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    assert _images(c, p1["id"])[0]["qc_verdict"] is None and _panel(c, p1["id"])["state"] == "review"


def test_manual_panel_qc_with_vision_and_override(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    vision = RecordingVision(score=30)
    c = make_client(
        providers(detectors=ScriptedDetectors(faces=0), identity=ScriptedIdentity(0.95), vision=vision),
        mangaka_presets_dir=presets_copy,
    )
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    assert _ok(c.post(f"/panels/{p1['id']}/qc", json={"image_id": 999}), 422)["errors"][0]["field"] == "image_id"
    job = _ok(c.post(f"/panels/{p1['id']}/qc", json={"vision": "force"}), 202)
    assert job["step"] == "qc" and job["panel_id"] == p1["id"]
    _wait(c)
    assert _job(c, job["id"])["status"] == "succeeded"
    [img] = _images(c, p1["id"])
    layers = img["qc"]["layers"]
    assert layers["vision"]["status"] == "done" and layers["vision"]["score"] == 30 and vision.calls == 1
    assert (
        img["qc"]["source"] == "manual" and "Vision : [mock] la case correspond à sa description" in img["qc_reasons"]
    )
    w = QC.weights
    det_score = 100 - QC.detectors.rules.missing_face.penalty  # Aiko attendue, aucun visage
    expected = round(
        (w.detectors * det_score + w.identity * 95 + w.vision * 30) / (w.detectors + w.identity + w.vision)
    )
    assert img["qc_score"] == expected and img["qc_verdict"] == "review"
    assert _panel(c, p1["id"])["state"] == "flagged"

    # « valider quand même » : décision humaine tracée, verdict précédent conservé
    out = _ok(c.post(f"/panel-images/{img['id']}/qc/override", json={"note": "voulu"}))
    assert out["qc_verdict"] == "ok" and out["qc"]["source"] == "human"
    assert out["qc"]["override"]["previous_verdict"] == "review" and out["qc"]["override"]["note"] == "voulu"
    assert out["qc"]["history"][-1]["verdict"] == "review"
    assert _panel(c, p1["id"])["state"] == "approved"

    # relancer le QC remplace la décision (gardée dans l'historique)
    _ok(c.post(f"/panels/{p1['id']}/qc", json={"vision": "skip"}), 202)
    _wait(c)
    [img] = _images(c, p1["id"])
    assert img["qc"]["override"] is None and img["qc"]["layers"]["vision"]["status"] == "skipped"
    assert img["qc"]["history"][-1]["source"] == "human"


def test_chapter_qc_job_and_summary(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    c = make_client(
        providers(detectors=ScriptedDetectors(faces=0), identity=ScriptedIdentity(0.95), vision=RecordingVision()),
        mangaka_presets_dir=presets_copy,
    )
    data = setup_chapter(c)
    chapter_id = data["chapter"]["id"]
    _ok(c.post(f"/chapters/{chapter_id}/generate"), 202)
    _wait(c)
    assert _ok(c.get(f"/chapters/{chapter_id}/qc")) == {
        "ok": 0, "review": 0, "reject": 0, "unchecked": 3, "no_image": 0, "total": 3
    }  # fmt: skip
    out = _ok(c.post(f"/chapters/{chapter_id}/qc"), 202)
    assert out["job"]["step"] == "qc" and len(out["panel_ids"]) == 3 and out["skipped"] == 0
    _wait(c)
    job = _job(c, out["job"]["id"])
    assert job["status"] == "succeeded" and job["progress"] == 100
    summary = _ok(c.get(f"/chapters/{chapter_id}/qc"))
    # cases 1-2 : un personnage attendu, aucun visage → à revoir ; case 3 (sans personnage) → ok
    assert (summary["ok"], summary["review"], summary["unchecked"]) == (1, 2, 0)
    assert job["message"] == "1 ok · 2 à revoir · 0 rejet"
    # déjà contrôlées : rien à refaire sans `force`
    again = _ok(c.post(f"/chapters/{chapter_id}/qc"), 202)
    assert again["job"] is None and again["skipped"] == 3
    forced = _ok(c.post(f"/chapters/{chapter_id}/qc", json={"force": True}), 202)
    assert len(forced["panel_ids"]) == 3


def test_qc_jobs_wait_in_the_generation_queue(make_client: Callable[..., TestClient]) -> None:
    comfy = GatedComfy()
    comfy.gate.set()
    c = make_client(providers(comfy=comfy))
    data = setup_chapter(c)
    p1, p2 = data["panels"][:2]
    assert _ok(c.post(f"/panels/{p1['id']}/qc"), 422)["errors"][0]["field"] == "panel"  # pas encore de version
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    comfy.gate.clear()
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    assert comfy.started.acquire(timeout=5)
    while comfy.started.acquire(blocking=False):
        pass
    job = _ok(c.post(f"/panels/{p1['id']}/qc"), 202)
    assert _ok(c.post(f"/panels/{p1['id']}/qc"), 202)["id"] == job["id"]  # pas de doublon
    queue = _ok(c.get("/queue"))
    assert queue["running"]["job"]["step"] == "generation"
    [pending] = [i for i in queue["pending"] if i["job"]["id"] == job["id"]]
    assert pending["label"].startswith("Contrôle qualité · Les Lames · ch. 1 · p. 1 · case 1")
    assert _job(c, job["id"])["status"] == "pending"
    comfy.gate.set()
    _wait(c)
    assert _job(c, job["id"])["status"] == "succeeded"


def test_vision_never_runs_while_a_comfyui_generation_runs(make_client: Callable[..., TestClient]) -> None:
    """Le QC (et sa vision) passe par la file de génération : jamais pendant qu'une génération tourne."""
    comfy = GatedComfy()
    vision = RecordingVision(busy=lambda: comfy.running)
    c = make_client(providers(comfy=comfy, detectors=None, identity=None, vision=vision))
    data = setup_chapter(c)
    p1, p2 = data["panels"][:2]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    assert comfy.started.acquire(timeout=5)
    _ok(c.post(f"/panels/{p2['id']}/generate"), 202)
    comfy.gate.set()
    _wait(c)
    assert vision.calls == 2 and vision.busy_at_call == [0, 0] and comfy.max_running == 1
    db = c.app.state.ctx.db  # type: ignore[attr-defined]
    with db.session_scope() as session:
        steps = [j.step for j in session.query(Job).order_by(Job.started_at)]
    assert steps == ["generation", "generation", "qc", "qc"]


def test_vision_waits_for_running_generation_job(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    """Garde explicite : un job de génération « en cours » en base bloque la vision jusqu'à sa fin."""
    edit_qc(presets_copy, auto_after_generation=False, vision__wait_idle_s=5)
    vision = RecordingVision()
    c = make_client(providers(detectors=None, identity=None, vision=vision), mangaka_presets_dir=presets_copy)
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    with ctx.db.session_scope() as session:
        fake = Job(step="generation", status=JobStatus.running, params={})
        session.add(fake)
        session.commit()
        fake_id = fake.id
    released: list[float] = []

    def release() -> None:
        time.sleep(0.3)
        released.append(time.monotonic())
        with ctx.db.session_scope() as session:
            session.get(Job, fake_id).status = JobStatus.succeeded
            session.commit()

    ctx.qc.poll_s = 0.02
    threading.Thread(target=release).start()
    img_id = _images(c, p1["id"])[0]["id"]
    verdict = ctx.qc.check_image(img_id, ctx.presets.require_qc(), vision="force")
    assert verdict == QCVerdict.ok and len(vision.times) == 1 and vision.times[0] >= released[0]


def test_vision_skipped_if_comfyui_stays_busy(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False, vision__wait_idle_s=0)
    vision = RecordingVision()
    c = make_client(
        providers(detectors=ScriptedDetectors(faces=1), identity=None, vision=vision), mangaka_presets_dir=presets_copy
    )
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    with ctx.db.session_scope() as session:
        session.add(Job(step="generation", status=JobStatus.running, params={}))
        session.commit()
    img_id = _images(c, p1["id"])[0]["id"]
    ctx.qc.check_image(img_id, ctx.presets.require_qc(), vision="force")
    assert vision.calls == 0
    vision_layer = _images(c, p1["id"])[0]["qc"]["layers"]["vision"]
    assert vision_layer["status"] == "skipped" and "ComfyUI occupé" in vision_layer["message"]


def test_vision_invalid_twice_is_reported_in_layer(make_client: Callable[..., TestClient], presets_copy: Path) -> None:
    edit_qc(presets_copy, auto_after_generation=False)
    vision = MockVisionProvider(invalid_attempts=10)
    c = make_client(
        providers(detectors=ScriptedDetectors(faces=1), identity=None, vision=vision), mangaka_presets_dir=presets_copy
    )
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    _ok(c.post(f"/panels/{p1['id']}/qc", json={"vision": "force"}), 202)
    _wait(c)
    img = _images(c, p1["id"])[0]
    layer = img["qc"]["layers"]["vision"]
    assert layer["status"] == "error" and "après 2 essais" in layer["message"] and vision.calls == 2
    assert img["qc_verdict"] == "review"  # la vision n'a pas pu confirmer


def test_without_qc_extra_app_starts_and_reports(make_client: Callable[..., TestClient]) -> None:
    c = make_client(providers(detectors=None, identity=None, vision=None))
    status = _ok(c.get("/qc/status"))
    assert status["available"] is False and status["layers"]["detectors"]["available"] is False
    assert "détecteurs non installés" in status["layers"]["detectors"]["detail"]
    health = _ok(c.get("/health"))
    assert health["providers"]["detectors"]["ok"] is False
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    assert _images(c, p1["id"])[0]["qc_verdict"] is None  # pas de QC automatique, la génération marche
    assert _ok(c.post(f"/panels/{p1['id']}/qc"), 503)["detail"].startswith("Contrôle qualité indisponible")
    assert _ok(c.post(f"/chapters/{data['chapter']['id']}/qc"), 503)["detail"].startswith(
        "Contrôle qualité indisponible"
    )


def test_detectors_unavailable_other_layers_still_decide(make_client: Callable[..., TestClient]) -> None:
    c = make_client(providers(detectors=None, identity=ScriptedIdentity(0.95), vision=RecordingVision()))
    data = setup_chapter(c)
    p1 = data["panels"][0]
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)
    _wait(c)
    img = _images(c, p1["id"])[0]
    assert img["qc"]["layers"]["detectors"]["status"] == "unavailable"
    assert "détecteurs non installés" in img["qc"]["layers"]["detectors"]["message"]
    assert img["qc_verdict"] == "ok" and img["detections"] is None


def test_mock_providers_are_deterministic() -> None:
    a, b = png_bytes((64, 48)), png_bytes((80, 48))
    det = MockDetectorProvider()
    assert det.detect(a) == det.detect(a)
    assert MockIdentityProvider().compare(b, [], {"Aiko": [a]}, crop_scale=2) == MockIdentityProvider().compare(
        b, [], {"Aiko": [a]}, crop_scale=2
    )
