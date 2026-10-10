"""Temps estimé d'un chapitre (ou d'une série) : cases encore à générer × durée par case.

Durée par case d'un preset = médiane des dernières générations réussies de ce preset (durées des
jobs) dès qu'il y en a `MIN_MEASURED` ; avant, `estimated_s` du preset (YAML) et l'estimation est
signalée comme telle.

Le palier croquis réutilise ce calcul avec un autre choix de preset (`resolve`) : « croquis de la page »
(preset croquis de chaque case) et « passage au propre des cases validées » (preset `propre`).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry
from ..store.models import ImageKind, Job, JobStatus, Page, Panel, PanelImage
from .generation import STEP, GenerationError, LibraryEntry, panel_cast, preset_tier, resolve_preset_id

# Choix du preset d'une case : (presets de la série, case, fiches citées) → id du preset.
Resolver = Callable[[PresetRegistry, Panel, list[LibraryEntry]], str]
UNKNOWN = "?"  # cases dont le preset ne peut pas être déterminé (palier sans passage au propre…)

MIN_MEASURED = 3  # en dessous : `estimated_s` du preset
SAMPLE = 20  # dernières générations prises en compte par preset


@dataclass
class PresetEstimate:
    preset: str
    tier: str | None
    panels: int
    per_panel_s: float | None
    measured: bool  # True : médiane de vraies durées ; False : valeur du preset (ou inconnue)
    samples: int


@dataclass
class Estimate:
    remaining_panels: int = 0
    total_s: float | None = 0.0  # None : un preset n'a ni durées ni `estimated_s`
    measured: bool = True  # False tant qu'au moins un preset se rabat sur `estimated_s`
    by_preset: list[PresetEstimate] = field(default_factory=list)


def measured_durations(session: Session, sample: int = SAMPLE) -> dict[str, list[float]]:
    """Durées (s) des dernières générations réussies, par preset, de la plus récente à la plus ancienne."""
    rows = session.execute(
        select(Job.params, Job.duration_ms)
        .where(Job.step == STEP, Job.status == JobStatus.succeeded, Job.duration_ms.is_not(None))
        .order_by(Job.id.desc())
        .limit(500)
    ).all()
    out: dict[str, list[float]] = {}
    for params, duration_ms in rows:
        preset = (params or {}).get("preset")
        if isinstance(preset, str) and len(out.setdefault(preset, [])) < sample:
            out[preset].append(duration_ms / 1000)
    return out


def remaining_panels(session: Session, pages: Iterable[Page]) -> list[Panel]:
    """Cases encore à générer : sans version choisie (qu'elles soient en file ou non)."""
    panels = [p for page in pages for p in page.panels]
    if not panels:
        return []
    done = set(
        session.scalars(
            select(PanelImage.panel_id).where(
                PanelImage.panel_id.in_([p.id for p in panels]), PanelImage.selected, PanelImage.kind == ImageKind.final
            )
        )
    )
    return [p for p in panels if p.id not in done]


def estimate_panels(
    session: Session,
    presets_for: Callable[[int], PresetRegistry],
    panels: Iterable[Panel],
    resolve: Resolver | None = None,
) -> Estimate:
    """Somme, preset par preset, des cases à générer × durée par case de ce preset (`resolve` : choix du
    preset, par défaut celui d'une génération normale)."""
    counts: dict[str, int] = {}
    registries: dict[str, PresetRegistry] = {}
    for panel in panels:
        presets = presets_for(panel.page.chapter.project_id)
        entries = panel_cast(session, panel).entries
        try:
            preset_id = resolve(presets, panel, entries) if resolve else resolve_preset_id(presets, panel, entries)
        except GenerationError:
            preset_id = UNKNOWN
        counts[preset_id] = counts.get(preset_id, 0) + 1
        registries.setdefault(preset_id, presets)
    durations = measured_durations(session) if counts else {}
    est = Estimate(remaining_panels=sum(counts.values()))
    for preset_id, n in counts.items():
        presets = registries[preset_id]
        samples = durations.get(preset_id, [])
        loaded = presets.workflows.get(preset_id)
        if len(samples) >= MIN_MEASURED:
            per_panel: float | None = statistics.median(samples)
            measured = True
        else:
            per_panel = loaded.preset.estimated_s if loaded is not None else None
            measured = False
            est.measured = False
        est.by_preset.append(
            PresetEstimate(
                preset=preset_id,
                tier=preset_tier(presets, preset_id),
                panels=n,
                per_panel_s=per_panel,
                measured=measured,
                samples=len(samples),
            )
        )
        if per_panel is None or est.total_s is None:
            est.total_s = None
        else:
            est.total_s += per_panel * n
    return est
