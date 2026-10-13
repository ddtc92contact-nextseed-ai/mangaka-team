"""Statistiques et export du journal des générations (page « Statistiques », `GET /stats/export`).

Une génération est **jugée** quand l'auteur l'a gardée ou rejetée (son dernier verdict de ce type compte) ;
le taux de validation = gardées / jugées. Les ventilations (palier, CFG, plan, fiche de savoir-faire,
finition, longueur du prompt, sorte) donnent l'effectif de chaque groupe et le signalent « peu de données »
sous `low_data_below` jugées (presets/journal.yaml). Tout reste local : rien ne quitte la machine.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry
from ..store.models import GenerationLog
from .journal import KINDS, MEASURES, PANEL_KINDS, event_counts, latest_events, tonality_gaps

# Colonnes de l'export, dans l'ordre (CSV et JSON).
EXPORT_COLUMNS = (
    "id",
    "created_at",
    "kind",
    "status",
    "error",
    "job_id",
    "project_id",
    "chapter_id",
    "page_id",
    "panel_id",
    "image_kind",
    "image_id",
    "version",
    "preset",
    "tier",
    "model",
    "steps",
    "cfg",
    "seed",
    "width",
    "height",
    "denoise",
    "prompt_source",
    "writer_hash",
    "positive_chars",
    "positive_words",
    "negative_chars",
    "negative_words",
    "prompt_length",
    "framing",
    "angle",
    "mood",
    "finish",
    "duration_ms",
    *MEASURES,
    "dark_gap",
    "black_gap",
    "ab_group",
    "ab_arm",
    "ab_mode",
    "verdict",
    "verdict_reason",
    "verdict_note",
    "verdict_at",
    "regenerated",
    "edited",
    "references",
    "loras",
    "knowledge",
    "positive_prompt",
    "negative_prompt",
)

NONE_LABEL = "—"
NO_KNOWLEDGE = "Aucune fiche"


@dataclass
class StatsFilter:
    project_id: int | None = None
    chapter_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None  # inclus
    tier: str | None = None
    kind: str | None = None  # une sorte de KINDS ; None : toutes (export) / celles d'une case (statistiques)


def query_logs(session: Session, f: StatsFilter, *, panel_only: bool = False) -> list[GenerationLog]:
    q = select(GenerationLog)
    if f.project_id is not None:
        q = q.where(GenerationLog.project_id == f.project_id)
    if f.chapter_id is not None:
        q = q.where(GenerationLog.chapter_id == f.chapter_id)
    if f.date_from is not None:
        q = q.where(GenerationLog.created_at >= datetime.combine(f.date_from, time.min))
    if f.date_to is not None:
        q = q.where(GenerationLog.created_at < datetime.combine(f.date_to + timedelta(days=1), time.min))
    if f.tier:
        q = q.where(GenerationLog.tier == f.tier)
    if f.kind:
        q = q.where(GenerationLog.kind == f.kind)
    elif panel_only:
        q = q.where(GenerationLog.kind.in_(PANEL_KINDS))
    return list(session.scalars(q.order_by(GenerationLog.id)))


# --- export -----------------------------------------------------------------------------------
def export_rows(session: Session, presets: PresetRegistry, logs: Sequence[GenerationLog]) -> list[dict[str, Any]]:
    """Une ligne par génération, avec son dernier verdict, ses mesures et l'écart à la cible."""
    ids = [g.id for g in logs]
    verdicts = latest_events(session, ids)
    counts = event_counts(session, ids)
    rows: list[dict[str, Any]] = []
    for g in logs:
        event = verdicts.get(g.id)
        gaps = tonality_gaps({k: getattr(g, k) for k in MEASURES}, presets.tonality)
        row = {c: getattr(g, c) for c in EXPORT_COLUMNS if hasattr(GenerationLog, c)}
        row.update(
            created_at=g.created_at.isoformat() if g.created_at else None,
            prompt_length=presets.journal.bucket(g.positive_words) if g.status == "succeeded" else None,
            dark_gap=gaps["dark_pct"],
            black_gap=gaps["black_pct"],
            verdict=event.verdict if event else None,
            verdict_reason=event.reason if event else None,
            verdict_note=event.note if event else None,
            verdict_at=event.created_at.isoformat() if event and event.created_at else None,
            regenerated=counts.get(g.id, {}).get("regenerated", 0),
            edited=counts.get(g.id, {}).get("edited", 0),
        )
        rows.append({c: row.get(c) for c in EXPORT_COLUMNS})
    return rows


def to_csv(rows: Iterable[dict[str, Any]]) -> str:
    """CSV (séparateur virgule, UTF-8) ; listes et objets en JSON dans leur cellule."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(EXPORT_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, list | dict) else ("" if v is None else v)
                for k, v in row.items()
            }
        )
    return buf.getvalue()


# --- statistiques -------------------------------------------------------------------------------
@dataclass
class _Item:
    log: GenerationLog
    verdict: str | None
    regenerated: int
    edited: int


def _group(items: Sequence[_Item], low_data_below: int) -> dict[str, Any]:
    judged = [i for i in items if i.verdict in ("validated", "rejected")]
    validated = sum(1 for i in judged if i.verdict == "validated")
    means: dict[str, float | None] = {}
    for key in MEASURES:
        values = [v for i in items if (v := getattr(i.log, key)) is not None]
        means[key] = round(sum(values) / len(values), 2) if values else None
    return {
        "generations": len(items),
        "judged": len(judged),
        "validated": validated,
        "rejected": len(judged) - validated,
        "validation_rate": round(100 * validated / len(judged), 1) if judged else None,
        "regenerated": sum(i.regenerated for i in items),
        "edited": sum(i.edited for i in items),
        "low_data": len(judged) < low_data_below,
        "means": means,
    }


def _cfg_label(value: float | None) -> str:
    return NONE_LABEL if value is None else f"{value:g}".replace(".", ",")


def compute_stats(session: Session, presets: PresetRegistry, f: StatsFilter) -> dict[str, Any]:
    """Taux de validation et moyennes des mesures, au total et par palier, CFG, plan, fiche de savoir-faire,
    finition (si le réglage existe), longueur du prompt et sorte de génération. Générations réussies d'une
    case seulement (sauf filtre `kind`)."""
    logs = [g for g in query_logs(session, f, panel_only=True) if g.status == "succeeded"]
    ids = [g.id for g in logs]
    verdicts = latest_events(session, ids)
    counts = event_counts(session, ids)
    items = [
        _Item(
            g,
            verdicts[g.id].verdict if g.id in verdicts else None,
            counts.get(g.id, {}).get("regenerated", 0),
            counts.get(g.id, {}).get("edited", 0),
        )
        for g in logs
    ]
    threshold = presets.journal.low_data_below
    bucket_order = [b.label for b in presets.journal.prompt_length_buckets]

    def breakdown(
        key: str, label: str, keys: Callable[[GenerationLog], list[str]], order: list[str] | None = None
    ) -> dict[str, Any]:
        groups: dict[str, list[_Item]] = {}
        for item in items:
            for k in keys(item.log):
                groups.setdefault(k, []).append(item)
        rank = {k: i for i, k in enumerate(order or [])}
        names = sorted(groups, key=lambda k: (rank.get(k, len(rank)), k == NONE_LABEL, -len(groups[k]), k))
        return {"key": key, "label": label, "rows": [{"value": n, **_group(groups[n], threshold)} for n in names]}

    def knowledge(g: GenerationLog) -> list[str]:
        titles = [str(d.get("title") or f"fiche {d.get('document_id')}") for d in g.knowledge or []]
        return list(dict.fromkeys(titles)) or [NO_KNOWLEDGE]

    breakdowns = [
        breakdown("tier", "Palier", lambda g: [g.tier or NONE_LABEL]),
        breakdown("cfg", "CFG", lambda g: [_cfg_label(g.cfg)]),
        breakdown("framing", "Plan", lambda g: [g.framing or NONE_LABEL]),
        breakdown("knowledge", "Fiche de savoir-faire", knowledge),
    ]
    if any(g.finish for g in logs):
        breakdowns.append(breakdown("finish", "Finition", lambda g: [g.finish or NONE_LABEL]))
    breakdowns += [
        breakdown(
            "prompt_length",
            "Longueur du prompt",
            lambda g: [presets.journal.bucket(g.positive_words) or NONE_LABEL],
            bucket_order,
        ),
        breakdown("kind", "Sorte de génération", lambda g: [KINDS.get(g.kind, g.kind)], list(KINDS.values())),
    ]
    total = _group(items, threshold)
    return {
        "total": total,
        "low_data": total["low_data"],
        "low_data_below": threshold,
        "breakdowns": breakdowns,
    }
