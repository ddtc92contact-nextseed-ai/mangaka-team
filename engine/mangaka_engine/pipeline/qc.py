"""Étape 4 — contrôle qualité des cases, en trois couches, pour ne relire que les cases douteuses.

1. **détecteurs** (rapide, CPU) : visages, mains, texte parasite → règles de `presets/qc.yaml` ;
2. **cohérence des personnages** : similarité CCIP entre la case et les images de référence ;
3. **vision** (lente) : « la case colle-t-elle à sa description ? » (Qwen3-VL via Ollama), seulement
   si les couches 1-2 hésitent (ou à la demande), jamais pendant une génération ComfyUI.

Score combiné 0–100 (moyenne pondérée des couches qui ont tourné) → verdict ok / à revoir / rejet,
que des règles peuvent durcir (texte parasite → rejet…). Après une génération, le QC automatique
relance une génération (nouvelle seed) sur un rejet, puis signale la case « à revoir ».
Rien n'est supprimé : toutes les versions restent. Aucun seuil ici : tout vient du preset.

Les jobs `qc` passent par la file sérielle de la génération (`pipeline/queue.py`).
"""

from __future__ import annotations

import copy
import json
import logging
import re
import string
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..presets import PresetError, PresetRegistry, QCSettings
from ..presets.schemas import QCDetectorsSettings, QCIdentitySettings, QCRule, QCVisionSettings, QCWeights
from ..providers.factory import Providers
from ..providers.qc import Detections, QCProviderError
from ..providers.vision import VisionError, VisionProvider, VisionResponseError
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import Character, Job, JobStatus, Page, Panel, PanelImage, PanelState, QCVerdict, utcnow
from .generation import ACTIVE, GenerationError, enqueue_panel, panel_characters, refresh_states
from .generation import QC_STEP as STEP
from .generation import STEP as GENERATION_STEP
from .jobs import JobReporter

log = logging.getLogger("mangaka_engine")

LAYERS = ("detectors", "identity", "vision")
SEVERITY = {QCVerdict.ok: 0, QCVerdict.review: 1, QCVerdict.reject: 2}
VERDICT_LABEL = {QCVerdict.ok: "ok", QCVerdict.review: "à revoir", QCVerdict.reject: "rejet"}
VisionMode = Literal["auto", "force", "skip"]
LayerStatus = Literal["done", "skipped", "unavailable", "error"]


class QCError(Exception):
    """Erreur lisible (en français) d'un contrôle qualité."""


def _fr(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


# --- résultat d'une couche -----------------------------------------------------------------
@dataclass
class LayerResult:
    status: LayerStatus
    score: int | None = None
    reasons: list[str] = field(default_factory=list)
    at_least: QCVerdict | None = None
    message: str | None = None  # couche sautée / indisponible / en erreur : pourquoi
    duration_ms: int = 0
    provider: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "reasons": list(self.reasons),
            "at_least": self.at_least.value if self.at_least else None,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "provider": self.provider,
            **self.extra,
        }


def _floor(current: QCVerdict | None, rule: QCRule) -> QCVerdict | None:
    if rule.at_least is None:
        return current
    new = QCVerdict(rule.at_least)
    return new if current is None or SEVERITY[new] > SEVERITY[current] else current


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


# --- couche 1 : règles des détecteurs ---------------------------------------------------------
def filter_detections(det: Detections, cfg: QCDetectorsSettings) -> Detections:
    """Ne garde que les boîtes au-dessus du seuil de confiance de leur détecteur."""
    return Detections(
        width=det.width,
        height=det.height,
        faces=[b for b in det.faces if b.score >= cfg.face.min_confidence],
        hands=[b for b in det.hands if b.score >= cfg.hand.min_confidence],
        text=[b for b in det.text if b.score >= cfg.text.min_confidence],
    )


def evaluate_detections(
    det: Detections, *, expected_faces: int, shot_type: str | None, cfg: QCDetectorsSettings
) -> LayerResult:
    """Applique les règles du preset aux boîtes (déjà filtrées) : score 0–100, raisons, verdict minimal."""
    rules = cfg.rules
    penalty = 0
    reasons: list[str] = []
    floor: QCVerdict | None = None
    n_faces = len(det.faces)
    count_faces = (shot_type or "").strip().lower() not in {s.strip().lower() for s in cfg.face_count_ignored_for_shots}

    if count_faces and expected_faces > 0 and n_faces < expected_faces:
        missing = expected_faces - n_faces
        penalty += rules.missing_face.penalty * missing
        floor = _floor(floor, rules.missing_face)
        reasons.append(
            f"Visage manquant : {n_faces} détecté{'s' if n_faces > 1 else ''} pour "
            f"{expected_faces} personnage{'s' if expected_faces > 1 else ''} attendu{'s' if expected_faces > 1 else ''}"
        )
    elif count_faces and n_faces > expected_faces + rules.extra_face.tolerance:
        extra = n_faces - expected_faces - rules.extra_face.tolerance
        penalty += rules.extra_face.penalty * extra
        floor = _floor(floor, rules.extra_face)
        reasons.append(
            f"Visages en trop : {n_faces} détectés pour {expected_faces} personnage{'s' if expected_faces > 1 else ''}"
        )

    if det.text:
        penalty += rules.text.penalty
        floor = _floor(floor, rules.text)
        n = len(det.text)
        reasons.append(
            f"Texte parasite détecté ({n} zone{'s' if n > 1 else ''}) : le modèle d'image ne doit rien écrire"
        )

    suspects = [b for b in det.hands if b.score < cfg.hand.suspect_below]
    if suspects:
        penalty += min(rules.suspect_hand.max_penalty, rules.suspect_hand.penalty * len(suspects))
        floor = _floor(floor, rules.suspect_hand)
        worst = min(b.score for b in suspects)
        reasons.append(
            f"Main{'s' if len(suspects) > 1 else ''} douteuse{'s' if len(suspects) > 1 else ''} "
            f"({len(suspects)}, confiance min. {_fr(worst)})"
        )

    return LayerResult(
        status="done",
        score=_clamp(100 - penalty),
        reasons=reasons,
        at_least=floor,
        extra={
            "counts": {"faces": n_faces, "hands": len(det.hands), "text": len(det.text)},
            "expected_faces": expected_faces,
            "face_count_checked": count_faces,
        },
    )


# --- couche 2 : cohérence des personnages -------------------------------------------------------
def evaluate_identity(
    similarities: Mapping[str, float], *, without_references: list[str], cfg: QCIdentitySettings
) -> LayerResult:
    characters: list[dict[str, Any]] = []
    reasons: list[str] = []
    floor: QCVerdict | None = None
    penalty = 0
    for name, sim in similarities.items():
        ok = sim >= cfg.min_similarity
        characters.append({"name": name, "similarity": round(sim, 3), "score": _clamp(sim * 100), "ok": ok})
        if not ok:
            floor = _floor(floor, cfg.below)
            penalty += cfg.below.penalty
            reasons.append(
                f"{name} ne ressemble pas assez à sa fiche (similarité {_fr(sim)} < {_fr(cfg.min_similarity)})"
            )
    if not characters:
        return LayerResult(
            status="skipped",
            message="aucun personnage de la case n'a d'image de référence",
            extra={"characters": [], "without_references": without_references},
        )
    score = _clamp(sum(c["score"] for c in characters) / len(characters) - penalty)
    return LayerResult(
        status="done",
        score=score,
        reasons=reasons,
        at_least=floor,
        extra={"characters": characters, "without_references": without_references},
    )


# --- couche 3 : vision --------------------------------------------------------------------------
class VisionAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: int = Field(ge=0, le=100)
    raisons: list[str] = Field(default_factory=list, validation_alias=AliasChoices("raisons", "reasons"))


VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "raisons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "raisons"],
}

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_vision_answer(text: str) -> VisionAnswer:
    """JSON {"score": 0-100, "raisons": [...]} ; ValueError lisible sinon."""
    raw = text.strip()
    m = _FENCE.match(raw)
    if m:
        raw = m.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"pas du JSON ({exc.msg})") from None
    try:
        return VisionAnswer.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "(racine)"
        raise ValueError(f"{loc} : {first['msg']}") from None


def run_vision(provider: VisionProvider, image: bytes, prompt: str, *, max_retries: int) -> tuple[VisionAnswer, int]:
    """Interroge le modèle ; réponse invalide → nouvel essai (`max_retries`) → VisionResponseError."""
    last = ""
    for attempt in range(1, max_retries + 2):
        text = provider.ask(image, prompt, schema=VISION_SCHEMA)
        try:
            return parse_vision_answer(text), attempt
        except ValueError as exc:
            last = str(exc)
            log.warning("QC vision : réponse invalide (essai %s) : %s", attempt, last)
    n = max_retries + 1
    raise VisionResponseError(f"réponse invalide du modèle de vision après {n} essai{'s' if n > 1 else ''} : {last}")


def vision_prompt(cfg: QCVisionSettings, *, description: str, characters: list[str], shot: str | None) -> str:
    return string.Template(cfg.prompt).safe_substitute(
        description=description.strip() or "(pas de description)",
        characters=", ".join(characters) or "aucun",
        shot=shot or "non précisé",
    )


def vision_decision(prelim: Combined | None, cfg: QCVisionSettings, mode: VisionMode) -> tuple[bool, str]:
    """Faut-il lancer la vision ? (oui/non, pourquoi)."""
    if mode == "force":
        return True, "demandée"
    if mode == "skip":
        return False, "non demandée"
    if cfg.mode == "never":
        return False, "désactivée dans le preset (mode never)"
    if cfg.mode == "always":
        return True, "toujours (preset)"
    if prelim is None:
        return True, "les couches 1-2 n'ont pas pu trancher"
    if prelim.floor == QCVerdict.reject:
        return False, "rejet déjà imposé par les couches 1-2"
    if cfg.doubt_band.min <= prelim.score < cfg.doubt_band.max:
        return True, f"score des couches 1-2 ({prelim.score}) dans la zone de doute"
    return False, f"les couches 1-2 suffisent (score {prelim.score})"


# --- verdict combiné ----------------------------------------------------------------------------
@dataclass
class Combined:
    score: int
    verdict: QCVerdict
    reasons: list[str]
    floor: QCVerdict | None


def combine(layers: Mapping[str, LayerResult], weights: QCWeights, thresholds: Any) -> Combined | None:
    """Moyenne pondérée des couches notées (poids renormalisés) → verdict par seuils, durci par les règles."""
    scored = [(name, r) for name, r in layers.items() if r.score is not None]
    total_w = sum(getattr(weights, name) for name, _ in scored)
    if not scored:
        return None
    if total_w > 0:
        score = _clamp(sum(getattr(weights, name) * r.score for name, r in scored) / total_w)  # type: ignore[operator]
    else:  # seules des couches de poids nul ont tourné : moyenne simple
        score = _clamp(sum(r.score for _, r in scored) / len(scored))  # type: ignore[misc]
    if score >= thresholds.ok_min:
        verdict = QCVerdict.ok
    elif score < thresholds.reject_below:
        verdict = QCVerdict.reject
    else:
        verdict = QCVerdict.review
    floor: QCVerdict | None = None
    for r in layers.values():
        if r.at_least is not None and (floor is None or SEVERITY[r.at_least] > SEVERITY[floor]):
            floor = r.at_least
    if floor is not None and SEVERITY[floor] > SEVERITY[verdict]:
        verdict = floor
    reasons = [reason for r in layers.values() for reason in r.reasons]
    return Combined(score=score, verdict=verdict, reasons=reasons, floor=floor)


# --- disponibilité ------------------------------------------------------------------------------
def layer_status(providers: Providers) -> dict[str, dict[str, Any]]:
    """Fournisseur de chaque couche, disponible ou non (avec la raison)."""
    out: dict[str, dict[str, Any]] = {}
    for layer, kind in (("detectors", "detectors"), ("identity", "identity"), ("vision", "vision")):
        available = getattr(providers, kind) is not None
        out[layer] = {
            "provider": providers.names.get(kind),
            "available": available,
            "detail": None if available else providers.errors.get(kind, "non configuré"),
        }
    return out


def any_layer_available(providers: Providers) -> bool:
    return any(getattr(providers, k) is not None for k in ("detectors", "identity", "vision"))


# --- mise en file -------------------------------------------------------------------------------
def active_qc_job(session: Session, panel_id: int) -> Job | None:
    return session.scalar(
        select(Job).where(Job.panel_id == panel_id, Job.step == STEP, Job.status.in_(ACTIVE)).order_by(Job.id)
    )


def make_qc_job(
    panel: Panel | None,
    image_ids: list[int],
    panel_ids: list[int],
    *,
    chapter_id: int,
    project_id: int,
    vision: VisionMode = "auto",
    auto: bool = False,
    attempt: int = 0,
) -> Job:
    return Job(
        project_id=project_id,
        chapter_id=chapter_id,
        panel_id=panel.id if panel is not None else None,
        step=STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={
            "image_ids": image_ids,
            "panel_ids": panel_ids,
            "vision": vision,
            "auto": auto,
            "attempt": attempt,
        },
    )


def target_image(panel: Panel) -> PanelImage | None:
    """Version contrôlée par défaut : la version choisie, sinon la plus récente."""
    chosen = next((i for i in panel.images if i.selected), None)
    return chosen or (panel.images[-1] if panel.images else None)


class AutoQC:
    """Crochet de `GenerationExecutor` : met en file le QC de chaque nouvelle version."""

    def __init__(
        self,
        presets: PresetRegistry,
        providers: Providers,
        *,
        presets_for: Callable[[int | None], PresetRegistry] | None = None,
    ) -> None:
        self.presets = presets
        self.providers = providers
        self.presets_for = presets_for or (lambda _project_id: presets)

    def __call__(self, session: Session, job: Job, image: PanelImage) -> None:
        panel = session.get(Panel, image.panel_id)
        if panel is None:
            return
        chapter = panel.page.chapter
        cfg = self.presets_for(chapter.project_id).qc
        if cfg is None or not cfg.auto_after_generation or not any_layer_available(self.providers):
            return
        session.add(
            make_qc_job(
                panel,
                [image.id],
                [panel.id],
                chapter_id=chapter.id,
                project_id=chapter.project_id,
                auto=True,
                attempt=int((job.params or {}).get("qc_attempt") or 0),
            )
        )


# --- exécution ----------------------------------------------------------------------------------
@dataclass
class _Target:
    image_id: int
    panel_id: int
    version: int
    data: bytes
    description: str
    shot_type: str | None
    character_names: list[str]
    references: dict[str, list[bytes]]
    without_references: list[str]


def describe_error(exc: Exception) -> str | None:
    if isinstance(exc, QCError | PresetError):
        msg = str(exc)
        return msg[:1].upper() + msg[1:]
    return None


class QCExecutor:
    """Exécute un job `qc` (appelé par la file sérielle, jamais en même temps qu'une génération)."""

    def __init__(
        self,
        db: Database,
        presets: PresetRegistry,
        files: FileStore,
        providers: Providers,
        *,
        comfy_busy: Callable[[], bool] | None = None,
        poll_s: float = 1.0,
        presets_for: Callable[[int | None], PresetRegistry] | None = None,
    ) -> None:
        self.db = db
        self.presets = presets
        # Presets effectifs d'une série (profils des agents) ; sans profil : `presets`.
        self.presets_for = presets_for or (lambda _project_id: presets)
        self.files = files
        self.providers = providers
        self.poll_s = poll_s
        self._comfy_busy = comfy_busy or (lambda: False)

    # --- garde ComfyUI ----------------------------------------------------------------------
    def comfy_busy(self) -> bool:
        """Une génération ComfyUI tourne-t-elle ? (job `generation` en cours, ou file ComfyUI non vide)."""
        with self.db.session_scope() as session:
            running = session.scalar(
                select(func.count()).where(Job.step == GENERATION_STEP, Job.status == JobStatus.running)
            )
        if running:
            return True
        try:
            return bool(self._comfy_busy())
        except Exception:  # noqa: BLE001 — ComfyUI injoignable : il ne génère rien pour nous
            return False

    def wait_comfy_idle(self, timeout_s: float, cancel: threading.Event) -> bool:
        deadline = time.monotonic() + timeout_s
        while self.comfy_busy():
            if cancel.is_set() or time.monotonic() >= deadline:
                return False
            cancel.wait(min(self.poll_s, max(0.0, deadline - time.monotonic())) or 0.01)
        return True

    # --- file -----------------------------------------------------------------------------
    def after(self, job_id: int) -> None:
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            ids = [i for i in (job.params or {}).get("panel_ids", []) if isinstance(i, int)]
            if job.panel_id is not None and job.panel_id not in ids:
                ids.append(job.panel_id)
            if ids:
                refresh_states(session, ids)
                session.commit()

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise QCError("job introuvable")
            params = dict(job.params or {})
            project_id = job.project_id
        presets = self.presets_for(project_id)
        cfg = presets.require_qc()
        image_ids = [i for i in params.get("image_ids", []) if isinstance(i, int)]
        vision: VisionMode = params.get("vision") if params.get("vision") in ("auto", "force", "skip") else "auto"
        auto = bool(params.get("auto"))
        attempt = int(params.get("attempt") or 0)
        if not image_ids:
            raise QCError("aucune version à contrôler")
        if not any_layer_available(self.providers):
            raise QCError(
                "aucune couche de contrôle disponible : "
                + " ; ".join(f"{k} : {v['detail']}" for k, v in layer_status(self.providers).items())
            )

        counts = {v: 0 for v in QCVerdict}
        errors: list[str] = []
        n = len(image_ids)
        self.after(job_id)
        for i, image_id in enumerate(image_ids):
            if cancel.is_set():
                raise QCError("contrôle annulé")
            report(int(100 * i / n), f"Contrôle {i + 1}/{n}…" if n > 1 else "Contrôle en cours…")
            try:
                verdict = self.check_image(
                    image_id, cfg, vision=vision, auto=auto, attempt=attempt, cancel=cancel, presets=presets
                )
            except QCError as exc:
                if n == 1:
                    raise
                errors.append(str(exc))
                continue
            if verdict is not None:
                counts[verdict] += 1
        done = sum(counts.values())
        if n > 1 and done == 0 and errors:
            raise QCError(f"aucune case contrôlée : {errors[0]}")
        summary = f"{counts[QCVerdict.ok]} ok · {counts[QCVerdict.review]} à revoir · {counts[QCVerdict.reject]} rejet"
        if errors:
            summary += f" · {len(errors)} en erreur"
        if n == 1 and done == 1:
            verdict = next(v for v, c in counts.items() if c)
            return f"Verdict : {VERDICT_LABEL[verdict]}"
        return summary

    def _load(self, session: Session, image_id: int, cfg: QCSettings) -> _Target | None:
        img = session.get(PanelImage, image_id)
        if img is None:
            return None
        panel = img.panel
        path = self.files.absolute(img.path)
        if not path.is_file():
            raise QCError(f"fichier de la version {img.version} absent de data/ ({img.path})")
        characters: list[Character] = panel_characters(session, panel)
        references: dict[str, list[bytes]] = {}
        without: list[str] = []
        for c in characters:
            refs = []
            for ref in c.reference_images[: cfg.identity.max_references]:
                ref_path = self.files.absolute(ref.path)
                if ref_path.is_file():
                    refs.append(ref_path.read_bytes())
            if refs:
                references[c.name] = refs
            else:
                without.append(c.name)
        return _Target(
            image_id=img.id,
            panel_id=panel.id,
            version=img.version,
            data=path.read_bytes(),
            description=panel.description,
            shot_type=panel.shot_type,
            character_names=list(panel.character_names or []),
            references=references,
            without_references=without,
        )

    def _set_panel_qc_state(self, panel_id: int) -> None:
        with self.db.session_scope() as session:
            panel = session.get(Panel, panel_id)
            if panel is not None:
                panel.state = PanelState.qc
                session.commit()

    def vision_provider(self, model: str | None = None) -> VisionProvider | None:
        """Fournisseur vision, avec le modèle choisi dans le profil du contrôleur qualité s'il diffère."""
        provider = self.providers.vision
        if provider is not None and model and getattr(provider, "model", model) != model:
            provider = copy.copy(provider)
            provider.model = model  # type: ignore[attr-defined]
        return provider

    def run_layers(
        self,
        t: _Target,
        cfg: QCSettings,
        *,
        vision: VisionMode,
        cancel: threading.Event,
        vision_model: str | None = None,
    ) -> tuple[dict[str, LayerResult], Detections | None, Combined | None, str]:
        """Fait tourner les couches (sans toucher la base). Renvoie couches, boîtes, verdict, motif vision."""
        p = self.providers
        vision_provider = self.vision_provider(vision_model)
        layers: dict[str, LayerResult] = {}
        detections: Detections | None = None

        # 1. détecteurs
        if p.detectors is None:
            layers["detectors"] = LayerResult(
                "unavailable", message=p.errors.get("detectors", "non configurés"), provider=p.names.get("detectors")
            )
        else:
            t0 = time.monotonic()
            try:
                raw = p.detectors.detect(
                    t.data,
                    face=cfg.detectors.face.options,
                    hand=cfg.detectors.hand.options,
                    text=cfg.detectors.text.options,
                )
                detections = filter_detections(raw, cfg.detectors)
                res = evaluate_detections(
                    detections,
                    expected_faces=len(t.character_names),
                    shot_type=t.shot_type,
                    cfg=cfg.detectors,
                )
            except QCProviderError as exc:
                res = LayerResult("error", message=str(exc))
            res.duration_ms = int((time.monotonic() - t0) * 1000)
            res.provider = p.detectors.name
            layers["detectors"] = res

        # 2. cohérence des personnages
        if not t.references:
            layers["identity"] = LayerResult(
                "skipped",
                message="aucun personnage de la case n'a d'image de référence",
                provider=p.names.get("identity"),
                extra={"characters": [], "without_references": t.without_references},
            )
        elif p.identity is None:
            layers["identity"] = LayerResult(
                "unavailable", message=p.errors.get("identity", "non configurée"), provider=p.names.get("identity")
            )
        else:
            t0 = time.monotonic()
            try:
                sims = p.identity.compare(
                    t.data,
                    detections.faces if detections is not None else [],
                    t.references,
                    crop_scale=cfg.identity.crop_scale,
                )
                res = evaluate_identity(sims, without_references=t.without_references, cfg=cfg.identity)
            except QCProviderError as exc:
                res = LayerResult("error", message=str(exc))
            res.duration_ms = int((time.monotonic() - t0) * 1000)
            res.provider = p.identity.name
            layers["identity"] = res

        # 3. vision
        prelim = combine(layers, cfg.weights, cfg.verdict)
        run, why = vision_decision(prelim, cfg.vision, vision)
        if not run:
            layers["vision"] = LayerResult("skipped", message=why, provider=p.names.get("vision"))
        elif vision_provider is None:
            layers["vision"] = LayerResult(
                "unavailable", message=p.errors.get("vision", "non configurée"), provider=p.names.get("vision")
            )
        elif not self.wait_comfy_idle(cfg.vision.wait_idle_s, cancel):
            layers["vision"] = LayerResult(
                "skipped",
                message="ComfyUI occupé : la vision ne tourne jamais pendant une génération",
                provider=vision_provider.name,
                at_least=QCVerdict.review if prelim is None else None,
            )
        else:
            t0 = time.monotonic()
            prompt = vision_prompt(
                cfg.vision, description=t.description, characters=t.character_names, shot=t.shot_type
            )
            try:
                answer, attempts = run_vision(vision_provider, t.data, prompt, max_retries=cfg.vision.max_retries)
                res = LayerResult(
                    "done",
                    score=answer.score,
                    reasons=[f"Vision : {r.strip()}" for r in answer.raisons if r.strip()][: cfg.vision.max_reasons],
                    extra={"attempts": attempts},
                )
            except VisionError as exc:
                res = LayerResult(
                    "error",
                    message=str(exc),
                    at_least=QCVerdict.review,
                    reasons=[f"Vision en erreur : {exc}"],
                )
            res.duration_ms = int((time.monotonic() - t0) * 1000)
            res.provider = vision_provider.name
            res.extra["why"] = why
            layers["vision"] = res
        return layers, detections, combine(layers, cfg.weights, cfg.verdict), why

    def check_image(
        self,
        image_id: int,
        cfg: QCSettings,
        *,
        vision: VisionMode = "auto",
        auto: bool = False,
        attempt: int = 0,
        cancel: threading.Event | None = None,
        presets: PresetRegistry | None = None,
    ) -> QCVerdict | None:
        """Contrôle une version et enregistre le résultat ; None si la version a disparu.

        `presets` : presets effectifs de la série (profils des agents) ; défaut : ceux du moteur.
        """
        presets = presets or self.presets
        ollama = presets.providers.ollama if presets.providers else None
        cancel = cancel or threading.Event()
        with self.db.session_scope() as session:
            t = self._load(session, image_id, cfg)
        if t is None:
            return None
        self._set_panel_qc_state(t.panel_id)
        t0 = time.monotonic()
        try:
            layers, detections, result, _ = self.run_layers(
                t, cfg, vision=vision, cancel=cancel, vision_model=ollama.vision_model if ollama else None
            )
        finally:
            self.after_panel(t.panel_id)
        if result is None:
            problems = [f"{name} : {r.message}" for name, r in layers.items() if r.message]
            raise QCError("aucune couche de contrôle n'a pu tourner — " + " ; ".join(problems))
        duration_ms = int((time.monotonic() - t0) * 1000)

        with self.db.session_scope() as session:
            img = session.get(PanelImage, image_id)
            if img is None:
                return None
            panel = img.panel
            verdict = result.verdict
            reasons = list(result.reasons)
            retry: dict[str, Any] | None = None
            if auto and verdict == QCVerdict.reject:
                if attempt < cfg.max_auto_retries:
                    retry = self._retry(session, panel, img, attempt + 1, cfg, presets)
                    if retry.get("job_id"):
                        reasons.append(
                            f"Rejet : nouvel essai automatique lancé ({attempt + 1}/{cfg.max_auto_retries}, nouvelle seed)"
                        )
                    else:
                        reasons.append(f"Nouvel essai automatique impossible : {retry.get('error')}")
                        verdict = QCVerdict.review
                else:
                    verdict = QCVerdict.review
                    reasons.append(
                        f"Rejet confirmé après {attempt} nouvel{'s' if attempt > 1 else ''} "
                        f"essai{'s' if attempt > 1 else ''} automatique{'s' if attempt > 1 else ''} : à revoir"
                        if attempt
                        else "Rejet : à revoir (pas de nouvel essai automatique dans le preset)"
                    )
            if not reasons and verdict == QCVerdict.ok:
                reasons.append("Aucun défaut détecté")
            previous = img.qc_details or {}
            history = list(previous.get("history") or [])
            if previous.get("verdict"):
                history.append(
                    {k: previous.get(k) for k in ("verdict", "score", "source", "at")}
                    | ({"override": True} if previous.get("override") else {})
                )
            details: dict[str, Any] = {
                "verdict": verdict.value,
                "score": result.score,
                "computed_verdict": result.verdict.value,
                "source": "auto" if auto else "manual",
                "attempt": attempt,
                "at": utcnow().isoformat(),
                "duration_ms": duration_ms,
                "layers": {name: layers[name].as_dict() for name in LAYERS if name in layers},
                "override": None,
                "history": history[-20:],
            }
            if retry is not None:
                details["auto_retry"] = retry
            img.qc_score = result.score
            img.qc_reasons = reasons
            img.qc_verdict = verdict
            img.qc_details = details
            if detections is not None:
                img.detections = detections.as_dict() | {"provider": layers["detectors"].provider}
            if auto and attempt > 0:
                self._maybe_select(panel, img)
            session.flush()
            refresh_states(session, [panel.id])
            session.commit()
            return verdict

    def after_panel(self, panel_id: int) -> None:
        with self.db.session_scope() as session:
            refresh_states(session, [panel_id])
            session.commit()

    def _retry(
        self, session: Session, panel: Panel, img: PanelImage, attempt: int, cfg: QCSettings, presets: PresetRegistry
    ) -> dict[str, Any]:
        try:
            jobs = enqueue_panel(
                session,
                presets,
                panel,
                count=1,
                preset=(img.params or {}).get("preset"),
                extra_params={"qc_attempt": attempt, "retry_of": img.id},
            )
        except (GenerationError, PresetError) as exc:
            return {"attempt": attempt, "error": str(exc)}
        session.flush()
        return {"attempt": attempt, "job_id": jobs[0].id}

    @staticmethod
    def _maybe_select(panel: Panel, img: PanelImage) -> None:
        """Après un nouvel essai automatique : choisir la nouvelle version si elle est meilleure."""
        chosen = next((i for i in panel.images if i.selected), None)
        if chosen is None or chosen.id == img.id or img.qc_verdict is None:
            return
        if chosen.qc_verdict is None or chosen.qc_verdict == QCVerdict.ok:
            return
        mine = (SEVERITY[img.qc_verdict], -(img.qc_score or 0))
        theirs = (SEVERITY[chosen.qc_verdict], -(chosen.qc_score or 0))
        if mine <= theirs:
            for other in panel.images:
                other.selected = other.id == img.id


def override_ok(session: Session, img: PanelImage, *, note: str | None = None) -> None:
    """« Valider quand même » : verdict forcé à ok, décision humaine tracée (sans commit)."""
    details = dict(img.qc_details or {})
    history = list(details.get("history") or [])
    if details.get("verdict"):
        history.append({k: details.get(k) for k in ("verdict", "score", "source", "at")})
    details["override"] = {
        "verdict": QCVerdict.ok.value,
        "by": "humain",
        "at": utcnow().isoformat(),
        "previous_verdict": img.qc_verdict.value if img.qc_verdict else None,
        "previous_score": img.qc_score,
        "note": note or None,
    }
    details["verdict"] = QCVerdict.ok.value
    details["source"] = "human"
    details["at"] = details["override"]["at"]
    details["history"] = history[-20:]
    img.qc_details = details
    img.qc_verdict = QCVerdict.ok
    img.qc_reasons = [*list(img.qc_reasons or []), "Validée à la main malgré le QC"]
    session.flush()
    refresh_states(session, [img.panel_id])


def chapter_summary(session: Session, chapter_id: int) -> dict[str, int]:
    """Compteurs du chapitre d'après le verdict QC de la version choisie de chaque case."""
    rows = session.execute(
        select(Panel.id, PanelImage.id, PanelImage.qc_verdict)
        .join(Page, Page.id == Panel.page_id)
        .outerjoin(PanelImage, (PanelImage.panel_id == Panel.id) & PanelImage.selected)
        .where(Page.chapter_id == chapter_id)
    ).all()
    out = {"ok": 0, "review": 0, "reject": 0, "unchecked": 0, "no_image": 0, "total": len(rows)}
    for _, image_id, verdict in rows:
        if image_id is None:
            out["no_image"] += 1
        elif verdict is None:
            out["unchecked"] += 1
        else:
            out[QCVerdict(verdict).value] += 1
    return out
