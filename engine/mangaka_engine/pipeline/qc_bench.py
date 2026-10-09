"""Banc d'essai du contrôle qualité : mesurer chaque couche sur des cases annotées à la main.

Avant tout fine-tuning d'un modèle de vision, on vérifie si les couches de `pipeline/qc.py`
suffisent. Vérité terrain : l'annotation humaine « bonne » / « mauvaise » de chaque version
(table `panel_image_annotations`, indépendante du verdict QC).

Convention : la classe « positive » est la **mauvaise case**. Une couche « signale » une case
quand elle la juge douteuse (verdict autre que ok). Donc :

- vrai positif (VP) : mauvaise case signalée ; faux négatif (FN) : mauvaise case laissée passer
  (le cas à éviter) ; faux positif (FP) : bonne case signalée à tort (relecture inutile) ;
- précision = VP / (VP + FP) ; rappel = VP / (VP + FN).

Chaque couche est lancée séparément sur chaque case (la vision est forcée), puis le verdict
combiné est rejoué comme le ferait le QC réel (vision seulement si les couches 1-2 hésitent).
Balayage de seuil : une case est signalée si sa valeur < seuil (ou si une règle impose « au moins
à revoir »). Valeur = score de la couche, sauf la cohérence des personnages où c'est la similarité
minimale × 100 (le seuil correspond alors directement à `identity.min_similarity`).

Le job `qc_bench` passe par la file sérielle de la génération : sa couche vision ne tourne
jamais pendant une génération ComfyUI (même règle que le QC, voir `pipeline/qc.py`).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetError, PresetRegistry, QCSettings
from ..presets.loader import format_validation_error
from ..store.db import Database
from ..store.models import (
    AnnotationLabel,
    Chapter,
    Job,
    Page,
    Panel,
    PanelImage,
    PanelImageAnnotation,
    QCBenchRun,
    QCVerdict,
    utcnow,
)
from .generation import ACTIVE
from .jobs import JobReporter
from .qc import LAYERS, VERDICT_LABEL, LayerResult, QCError, QCExecutor, combine, vision_decision

STEP = "qc_bench"
COMBINED = "combined"
BENCH_LAYERS = (*LAYERS, COMBINED)
LAYER_LABEL = {
    "detectors": "Détecteurs",
    "identity": "Cohérence des personnages",
    "vision": "Vision",
    COMBINED: "QC combiné",
}

# Étiquettes de défaut d'une annotation « mauvaise » (identifiants stables, libellés pour l'export).
DEFECTS: dict[str, str] = {
    "face": "visage raté",
    "hands": "mains",
    "identity": "perso pas reconnaissable",
    "description": "ne colle pas à la description",
    "text": "texte parasite",
    "other": "autre",
}

THRESHOLDS = range(0, 101)  # balayage : signalée si valeur < seuil


def _fr_pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f} %"


# --- calculs (purs) --------------------------------------------------------------------------
@dataclass(frozen=True)
class Sample:
    """Une case vue par une couche : vérité terrain, valeur balayée, règle bloquante, verdict actuel."""

    bad: bool
    value: float | None
    floor: bool = False  # une règle impose « au moins à revoir » : signalée quel que soit le seuil
    flagged: bool | None = None  # verdict actuel de la couche (None : pris au seuil actuel)

    @property
    def evaluated(self) -> bool:
        return self.value is not None or self.floor


def flagged_at(sample: Sample, threshold: float) -> bool:
    return sample.floor or (sample.value is not None and sample.value < threshold)


def confusion(pairs: Iterable[tuple[bool, bool]]) -> dict[str, int]:
    """(mauvaise ?, signalée ?) → {tp, fp, fn, tn}."""
    c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for bad, flagged in pairs:
        if bad:
            c["tp" if flagged else "fn"] += 1
        else:
            c["fp" if flagged else "tn"] += 1
    return c


def precision(c: Mapping[str, int]) -> float | None:
    """VP / (VP + FP) ; None si la couche ne signale rien."""
    n = c["tp"] + c["fp"]
    return c["tp"] / n if n else None


def recall(c: Mapping[str, int]) -> float | None:
    """VP / (VP + FN) ; None s'il n'y a aucune mauvaise case."""
    n = c["tp"] + c["fn"]
    return c["tp"] / n if n else None


def _point(c: dict[str, int], threshold: float) -> dict[str, Any]:
    p, r = precision(c), recall(c)
    return {
        "threshold": threshold,
        **c,
        "precision": None if p is None else round(p, 4),
        "recall": None if r is None else round(r, 4),
    }


def sweep(samples: Sequence[Sample], thresholds: Iterable[float] = THRESHOLDS) -> list[dict[str, Any]]:
    """Précision / rappel pour chaque seuil (cases évaluées seulement)."""
    evaluated = [s for s in samples if s.evaluated]
    return [_point(confusion((s.bad, flagged_at(s, t)) for s in evaluated), t) for t in thresholds]


def suggest_threshold(
    points: Sequence[Mapping[str, Any]], target_recall: float, *, current: float | None = None
) -> dict[str, Any] | None:
    """Seuil qui attrape au moins `target_recall` des mauvaises cases avec la meilleure précision.

    À précision égale : le plus proche du seuil actuel (on ne bouge le preset que si les données le
    justifient), puis le plus bas (le moins de cases signalées). None si inatteignable ou sans mauvaise case."""
    ok = [p for p in points if p["recall"] is not None and p["recall"] >= target_recall - 1e-9]
    if not ok:
        return None

    def rank(p: Mapping[str, Any]) -> tuple[float, float, float]:
        distance = abs(p["threshold"] - current) if current is not None else 0.0
        return (p["precision"] if p["precision"] is not None else -1.0, -distance, -p["threshold"])

    return dict(max(ok, key=rank))


def layer_metrics(
    samples: Sequence[Sample],
    *,
    current_threshold: float | None,
    target_recall: float,
    durations_ms: Sequence[int] = (),
) -> dict[str, Any]:
    """Métriques d'une couche : matrice de confusion au réglage actuel, balayage, seuil suggéré, temps moyen."""
    evaluated = [s for s in samples if s.evaluated]
    current = confusion(
        (
            s.bad,
            s.flagged
            if s.flagged is not None
            else flagged_at(s, current_threshold if current_threshold is not None else 0),
        )
        for s in evaluated
    )
    points = sweep(evaluated)
    suggested = suggest_threshold(points, target_recall, current=current_threshold)
    bad = sum(1 for s in evaluated if s.bad)
    if not evaluated:
        note = "aucune case évaluée par cette couche"
    elif not bad:
        note = "aucune mauvaise case annotée : rappel non mesurable"
    elif suggested is None:
        note = f"objectif de rappel {_fr_pct(target_recall)} inatteignable avec cette couche"
    else:
        note = None
    p, r = precision(current), recall(current)
    return {
        "evaluated": len(evaluated),
        "missing": len(samples) - len(evaluated),
        "good": len(evaluated) - bad,
        "bad": bad,
        "confusion": current,
        "precision": None if p is None else round(p, 4),
        "recall": None if r is None else round(r, 4),
        "current_threshold": current_threshold,
        "sweep": points,
        "suggested": suggested,
        "suggestion_note": note,
        "mean_ms": round(sum(durations_ms) / len(durations_ms)) if durations_ms else None,
    }


# --- une case passée au banc -----------------------------------------------------------------
def _standalone_flag(res: LayerResult, cfg: QCSettings) -> bool | None:
    """Verdict de la couche seule (seuils du preset + règles) : signalée ?"""
    if res.status != "done" or res.score is None:
        return None
    return res.at_least is not None or res.score < cfg.verdict.ok_min


def evaluate_item(layers: Mapping[str, LayerResult], cfg: QCSettings) -> dict[str, dict[str, Any]]:
    """Valeur, règle bloquante et verdict de chaque couche seule, puis du QC combiné rejoué."""
    out: dict[str, dict[str, Any]] = {}
    for name in LAYERS:
        res = layers.get(name)
        if res is None:
            continue
        done = res.status == "done" and res.score is not None
        value: float | None = float(res.score) if done and res.score is not None else None
        if name == "identity" and done:
            sims = [c["similarity"] for c in res.extra.get("characters", []) if "similarity" in c]
            value = round(min(sims) * 100, 1) if sims else None
        out[name] = {
            "status": res.status,
            "score": res.score if done else None,
            "value": value,
            "floor": bool(done and res.at_least is not None and name != "identity"),
            "flagged": _standalone_flag(res, cfg),
            "duration_ms": res.duration_ms,
            "message": res.message,
            "reasons": list(res.reasons),
        }

    # QC combiné : couches 1-2, puis la vision seulement si le QC réel l'aurait lancée.
    base = {k: v for k, v in layers.items() if k in ("detectors", "identity")}
    prelim = combine(base, cfg.weights, cfg.verdict)
    wants_vision, why = vision_decision(prelim, cfg.vision, "auto")
    vision = layers.get("vision")
    effective = dict(base)
    vision_used = wants_vision and vision is not None and vision.status == "done"
    if vision_used and vision is not None:
        effective["vision"] = vision
    result = combine(effective, cfg.weights, cfg.verdict)
    out[COMBINED] = {
        "status": "done" if result is not None else "unavailable",
        "score": result.score if result else None,
        "value": float(result.score) if result else None,
        "floor": bool(result and result.floor is not None),
        "flagged": (result.verdict != QCVerdict.ok) if result else None,
        "verdict": result.verdict.value if result else None,
        "vision_wanted": wants_vision,
        "vision_used": vision_used,
        "vision_why": why,
        "duration_ms": sum(layers[k].duration_ms for k in effective),
        "message": None if result else "aucune couche n'a pu tourner",
        "reasons": list(result.reasons) if result else [],
    }
    return out


def current_threshold(layer: str, cfg: QCSettings) -> float:
    if layer == "identity":
        return round(cfg.identity.min_similarity * 100, 1)
    return float(cfg.verdict.ok_min)


def compute_metrics(items: Sequence[Mapping[str, Any]], cfg: QCSettings) -> dict[str, Any]:
    """Métriques de toutes les couches à partir des cases mesurées (items de `evaluate_item`)."""
    target = cfg.bench.target_recall
    layers: dict[str, Any] = {}
    for name in BENCH_LAYERS:
        samples: list[Sample] = []
        durations: list[int] = []
        for item in items:
            r = (item.get("layers") or {}).get(name)
            if r is None:
                samples.append(Sample(bad=item["bad"], value=None))
                continue
            samples.append(Sample(bad=item["bad"], value=r["value"], floor=r["floor"], flagged=r["flagged"]))
            if r["status"] == "done":
                durations.append(int(r["duration_ms"]))
        m = layer_metrics(
            samples, current_threshold=current_threshold(name, cfg), target_recall=target, durations_ms=durations
        )
        m["label"] = LAYER_LABEL[name]
        m["threshold_key"] = APPLY_KEYS.get(name)
        layers[name] = m
    measured = [i for i in items if i.get("layers")]
    totals = [sum(int(r["duration_ms"]) for k, r in i["layers"].items() if k in LAYERS) for i in measured]
    return {
        "target_recall": target,
        "samples": len(items),
        "good": sum(1 for i in items if not i["bad"]),
        "bad": sum(1 for i in items if i["bad"]),
        "errors": sum(1 for i in items if i.get("error")),
        "mean_ms_per_case": round(sum(totals) / len(totals)) if totals else None,
        "layers": layers,
    }


def strip_timings(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Métriques sans les durées (seule partie non déterministe d'un run)."""
    out = {k: v for k, v in metrics.items() if k != "mean_ms_per_case"}
    out["layers"] = {k: {kk: vv for kk, vv in v.items() if kk != "mean_ms"} for k, v in metrics["layers"].items()}
    return out


# --- ensemble annoté ---------------------------------------------------------------------------
@dataclass
class AnnotatedImage:
    image_id: int
    panel_id: int
    page_id: int
    chapter_id: int
    project_id: int
    label: str
    bad: bool
    defects: list[str]
    note: str


def annotated_query(project_id: int | None = None, chapter_id: int | None = None):  # type: ignore[no-untyped-def]
    q = (
        select(PanelImageAnnotation, PanelImage, Panel, Page, Chapter)
        .join(PanelImage, PanelImage.id == PanelImageAnnotation.image_id)
        .join(Panel, Panel.id == PanelImage.panel_id)
        .join(Page, Page.id == Panel.page_id)
        .join(Chapter, Chapter.id == Page.chapter_id)
    )
    if project_id is not None:
        q = q.where(Chapter.project_id == project_id)
    if chapter_id is not None:
        q = q.where(Chapter.id == chapter_id)
    return q.order_by(PanelImageAnnotation.image_id)


def annotated_images(
    session: Session, project_id: int | None = None, chapter_id: int | None = None
) -> list[AnnotatedImage]:
    out: list[AnnotatedImage] = []
    for ann, img, panel, page, chapter in session.execute(annotated_query(project_id, chapter_id)).all():
        out.append(
            AnnotatedImage(
                image_id=img.id,
                panel_id=panel.id,
                page_id=page.id,
                chapter_id=chapter.id,
                project_id=chapter.project_id,
                label=f"{chapter.project.title} · ch. {chapter.number} · p. {page.number} · case {panel.index + 1} · v{img.version}",
                bad=ann.label == AnnotationLabel.bad,
                defects=list(ann.defects or []),
                note=ann.note or "",
            )
        )
    return out


def dataset_stats(session: Session, project_id: int | None = None, chapter_id: int | None = None) -> dict[str, Any]:
    images = annotated_images(session, project_id, chapter_id)
    by_defect = {k: 0 for k in DEFECTS}
    for i in images:
        for d in i.defects:
            if d in by_defect:
                by_defect[d] += 1
    return {
        "good": sum(1 for i in images if not i.bad),
        "bad": sum(1 for i in images if i.bad),
        "total": len(images),
        "by_defect": by_defect,
    }


def preset_hash(cfg: QCSettings) -> str:
    """Version du preset qc.yaml utilisé : empreinte de ses valeurs validées."""
    raw = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def active_bench_job(session: Session) -> Job | None:
    return session.scalar(select(Job).where(Job.step == STEP, Job.status.in_(ACTIVE)).order_by(Job.id))


# --- exécution --------------------------------------------------------------------------------
class QCBenchExecutor:
    """Exécute un job `qc_bench` (file sérielle de la génération : jamais pendant ComfyUI)."""

    def __init__(self, db: Database, presets: PresetRegistry, qc: QCExecutor) -> None:
        self.db = db
        self.presets = presets
        self.qc = qc

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        cfg = self.presets.require_qc()
        with self.db.session_scope() as session:
            run = session.scalar(select(QCBenchRun).where(QCBenchRun.job_id == job_id))
            if run is None:
                raise QCError("run du banc d'essai introuvable")
            run_id, vision = run.id, run.vision
            images = annotated_images(session, run.project_id, run.chapter_id)
            run.preset = cfg.model_dump(mode="json")
            run.preset_hash = preset_hash(cfg)
            run.sample_count = len(images)
            session.commit()
        if not images:
            raise QCError("aucune case annotée dans cet ensemble")

        items: list[dict[str, Any]] = []
        n = len(images)
        for i, a in enumerate(images):
            if cancel.is_set():
                raise QCError("banc d'essai annulé")
            report(int(100 * i / n), f"Case {i + 1}/{n}…")
            item: dict[str, Any] = {
                "image_id": a.image_id,
                "panel_id": a.panel_id,
                "page_id": a.page_id,
                "chapter_id": a.chapter_id,
                "project_id": a.project_id,
                "label": a.label,
                "bad": a.bad,
                "defects": a.defects,
                "note": a.note,
                "layers": {},
                "error": None,
            }
            try:
                with self.db.session_scope() as session:
                    target = self.qc._load(session, a.image_id, cfg)
                if target is None:
                    raise QCError("version supprimée depuis l'annotation")
                t0 = time.monotonic()
                layers, _, _, _ = self.qc.run_layers(target, cfg, vision="force" if vision else "skip", cancel=cancel)
                item["layers"] = evaluate_item(layers, cfg)
                item["duration_ms"] = int((time.monotonic() - t0) * 1000)
            except QCError as exc:
                item["error"] = str(exc)
            items.append(item)

        metrics = compute_metrics(items, cfg)
        with self.db.session_scope() as session:
            run = session.get(QCBenchRun, run_id)
            if run is not None:
                run.items = items
                run.metrics = metrics
                run.finished_at = utcnow()
                session.commit()
        combined = metrics["layers"][COMBINED]
        msg = (
            f"{n} case{'s' if n > 1 else ''} mesurée{'s' if n > 1 else ''} · QC combiné : "
            f"précision {_fr_pct(combined['precision'])}, rappel {_fr_pct(combined['recall'])}"
        )
        if metrics["errors"]:
            msg += f" · {metrics['errors']} en erreur"
        return msg


# --- export ------------------------------------------------------------------------------------
CSV_COLUMNS = [
    "image_id",
    "case",
    "annotation",
    "defauts",
    "note",
    *[f"{layer}_{col}" for layer in BENCH_LAYERS for col in ("score", "signalee", "ms")],
    "verdict_combine",
    "erreur",
]


def export_csv(items: Sequence[Mapping[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(CSV_COLUMNS)
    for it in items:
        row: list[Any] = [
            it["image_id"],
            it["label"],
            "mauvaise" if it["bad"] else "bonne",
            ", ".join(DEFECTS.get(d, d) for d in it.get("defects") or []),
            it.get("note") or "",
        ]
        layers = it.get("layers") or {}
        for layer in BENCH_LAYERS:
            r = layers.get(layer) or {}
            flagged = r.get("flagged")
            row += [
                "" if r.get("value") is None else r["value"],
                "" if flagged is None else ("oui" if flagged else "non"),
                "" if r.get("status") != "done" else r.get("duration_ms", ""),
            ]
        verdict = (layers.get(COMBINED) or {}).get("verdict")
        row += [VERDICT_LABEL[QCVerdict(verdict)] if verdict else "", it.get("error") or ""]
        w.writerow(row)
    return buf.getvalue()


# --- appliquer les seuils suggérés à presets/qc.yaml -------------------------------------------
# Couche → clé du preset que son seuil règle directement (les autres seuils sont indicatifs).
APPLY_KEYS: dict[str, str] = {COMBINED: "verdict.ok_min", "identity": "identity.min_similarity"}


def planned_changes(metrics: Mapping[str, Any], cfg: QCSettings) -> list[dict[str, Any]]:
    """Modifications de qc.yaml qu'appliquerait « appliquer les seuils suggérés »."""
    changes: list[dict[str, Any]] = []
    layers = metrics.get("layers") or {}
    combined = (layers.get(COMBINED) or {}).get("suggested")
    if combined is not None:
        ok_min = int(combined["threshold"])
        if ok_min != cfg.verdict.ok_min:
            changes.append(
                {
                    "key": "verdict.ok_min",
                    "label": "Score minimal « ok » du QC combiné",
                    "before": cfg.verdict.ok_min,
                    "after": ok_min,
                }
            )
        if cfg.verdict.reject_below > ok_min:
            changes.append(
                {
                    "key": "verdict.reject_below",
                    "label": "Score de rejet (abaissé pour rester ≤ score ok)",
                    "before": cfg.verdict.reject_below,
                    "after": ok_min,
                }
            )
    identity = (layers.get("identity") or {}).get("suggested")
    if identity is not None:
        sim = round(float(identity["threshold"]) / 100, 2)
        if abs(sim - cfg.identity.min_similarity) > 1e-9:
            changes.append(
                {
                    "key": "identity.min_similarity",
                    "label": "Similarité minimale d'un personnage à sa fiche",
                    "before": cfg.identity.min_similarity,
                    "after": sim,
                }
            )
    return changes


def set_yaml_scalar(text: str, dotted: str, value: Any) -> str:
    """Remplace la valeur d'une clé `section.cle` dans le YAML en gardant commentaires et mise en forme."""
    section, key = dotted.split(".")
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", line)), None)
    if start is None:
        raise PresetError(f"section « {section} » introuvable dans qc.yaml")
    pattern = re.compile(
        rf"^(?P<indent>[ ]+){re.escape(key)}:(?P<sp>[ ]*)(?P<value>[^#\n]*?)(?P<rest>[ ]*(#[^\n]*)?\r?\n?)$"
    )
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line.startswith((" ", "\t", "#")):
            break  # section suivante
        m = pattern.match(line)
        if m and len(m.group("indent")) == 2:
            lines[i] = f"{m.group('indent')}{key}:{m.group('sp') or ' '}{value}{m.group('rest')}"
            return "".join(lines)
    raise PresetError(f"clé « {dotted} » introuvable dans qc.yaml (attendue sur une ligne à part)")


def apply_changes(registry: PresetRegistry, changes: Sequence[Mapping[str, Any]]) -> QCSettings:
    """Écrit les seuils dans presets/qc.yaml (commentaires conservés), vérifie que le fichier reste
    valide, puis recharge le preset en mémoire. Rien n'est écrit si le résultat serait invalide."""
    path = Path(registry.root) / "qc.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PresetError(f"presets/qc.yaml illisible : {exc}") from None
    for change in changes:
        text = set_yaml_scalar(text, change["key"], change["after"])
    try:
        new = QCSettings.model_validate(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        raise PresetError(f"qc.yaml deviendrait invalide : {exc}") from None
    except ValidationError as exc:
        raise PresetError(f"qc.yaml deviendrait invalide : {format_validation_error(exc)}") from None
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    registry.qc = new
    registry.issues = [i for i in registry.issues if not i.file.startswith("qc.")]
    return new
