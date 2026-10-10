"""Palier croquis : brouillon de page en quelques secondes, tri, passage au propre.

1. **Croquer** (`enqueue_sketch`) : une version `kind = croquis` par case encore à faire, avec le workflow
   `defaults.workflow_sketch` (ou son `with_references`) : même modèle que Turbo, petite image, peu
   d'étapes, mêmes LoRA et mêmes références que la version propre. File ComfyUI habituelle.
2. **Trier** : l'auteur valide la composition d'un croquis (`Panel.sketch_image_id`), en redemande un
   (nouvelle graine) ou modifie la description puis re-croque.
3. **Passer au propre** (`enqueue_clean`) : version finale au palier de la série (`from_sketch` de son
   preset, rôle `propre`), en image → image depuis le croquis validé : même graine, même prompt,
   débruitage partiel (`denoise` : case > série > preset). Le croquis source est noté sur la version.

Un croquis n'est jamais choisi : ni assemblage, ni lettrage, ni export, ni QC automatique. La source
de composition est une donnée de la version (`params.composition`), pas un cas codé en dur.

Mode du passage au propre (fiche série, `Project.clean_mode`) : `img2img` (défaut, ci-dessus) ou
`controlnet` — le pendant ControlNet du palier (`with_control`, rôle `controle`) avec le croquis validé
comme image guide (type `Project.clean_control`, sinon celui du preset), même graine, même prompt.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry
from ..store.models import ImageKind, Job, Page, Panel, PanelImage
from .generation import (
    ACTIVE,
    STEP,
    GenerationError,
    LibraryEntry,
    control_variant,
    enqueue_panel,
    panel_cast,
    scene_prompt,
)
from .knowledge import KnowledgeBase

KIND_SKETCH = ImageKind.croquis.value
CLEAN_MODES = ("img2img", "controlnet")


def require_sketch_enabled(panel: Panel) -> None:
    if not panel.page.chapter.project.sketch_enabled:
        raise GenerationError("palier croquis désactivé pour cette série (fiche série)")


def sketch_preset_id(presets: PresetRegistry, entries: Sequence[LibraryEntry]) -> str:
    """Workflow des croquis : `defaults.workflow_sketch`, ou son pendant « avec références »."""
    defaults = presets.defaults
    sketch_id = defaults.workflow_sketch if defaults else None
    loaded = presets.workflows.get(sketch_id) if sketch_id else None
    if loaded is None:
        raise GenerationError("aucun palier croquis configuré (workflow_sketch de presets/defaults.yaml)")
    if any(e.reference_images for e in entries) and not loaded.preset.reference_images:
        if not loaded.preset.with_references:
            raise GenerationError(f"le workflow croquis {loaded.preset.id} ne déclare pas de with_references")
        return loaded.preset.with_references
    return loaded.preset.id


def clean_preset_id(presets: PresetRegistry, panel: Panel, entries: Sequence[LibraryEntry]) -> str:
    """Workflow « propre depuis croquis » du palier de la case (preset imposé) ou de la série : img2img
    (`from_sketch`) ou ControlNet (`with_control`) selon le mode de passage au propre de la série."""
    base_id = panel.generation_preset or panel.page.chapter.project.workflow_preset
    if panel.page.chapter.project.clean_mode == "controlnet":
        return control_variant(presets, base_id, entries)
    base = presets.workflows.get(base_id)
    if base is None:
        raise GenerationError(f"workflow inconnu : « {base_id} »")
    clean = presets.workflows.get(base.preset.from_sketch or "")
    if clean is None:
        tier = base.preset.tier.name if base.preset.tier else base.preset.id
        raise GenerationError(
            f"le palier {tier} ({base.preset.id}) ne propose pas de passage au propre depuis un croquis (from_sketch)"
        )
    if any(e.reference_images for e in entries) and not clean.preset.reference_images:
        if not clean.preset.with_references:
            raise GenerationError(f"le workflow {clean.preset.id} ne déclare pas de with_references")
        return clean.preset.with_references
    return clean.preset.id


def clean_denoise(presets: PresetRegistry, panel: Panel, preset_id: str, override: float | None = None) -> float | None:
    """Débruitage du passage au propre : demande > case > série > `denoise` du preset."""
    for value in (override, panel.sketch_denoise, panel.page.chapter.project.sketch_denoise):
        if value is not None:
            return float(value)
    loaded = presets.workflows.get(preset_id)
    value = loaded.preset.defaults.get("denoise") if loaded is not None else None
    return float(value) if isinstance(value, int | float) else None


# --- lecture ------------------------------------------------------------------------------
def latest_sketch(panel: Panel) -> PanelImage | None:
    sketches = [i for i in panel.images if i.kind == ImageKind.croquis]
    return sketches[-1] if sketches else None


def validated_sketch(panel: Panel) -> PanelImage | None:
    """Croquis validé au tri (None si aucun, ou s'il a été supprimé)."""
    if panel.sketch_image_id is None:
        return None
    return next((i for i in panel.images if i.id == panel.sketch_image_id and i.kind == ImageKind.croquis), None)


def cleaned_from(panel: Panel, sketch: PanelImage) -> PanelImage | None:
    """Version propre déjà tirée de ce croquis."""
    for img in panel.images:
        comp = (img.params or {}).get("composition")
        if img.kind == ImageKind.final and isinstance(comp, dict) and comp.get("image_id") == sketch.id:
            return img
    return None


def _busy(session: Session, panels: Sequence[Panel]) -> set[int]:
    if not panels:
        return set()
    ids = [p.id for p in panels]
    return set(
        session.scalars(select(Job.panel_id).where(Job.panel_id.in_(ids), Job.step == STEP, Job.status.in_(ACTIVE)))
    )


def has_final(panel: Panel) -> bool:
    return any(i.selected and i.kind == ImageKind.final for i in panel.images)


def panels_to_sketch(session: Session, pages: Iterable[Page], *, include_busy: bool = False) -> list[Panel]:
    """Cases « non encore validées » : sans version propre choisie ni croquis validé (et sans job en cours)."""
    panels = [p for page in pages for p in page.panels if not has_final(p) and validated_sketch(p) is None]
    if include_busy:
        return panels
    busy = _busy(session, panels)
    return [p for p in panels if p.id not in busy]


def panels_to_clean(session: Session, pages: Iterable[Page], *, include_busy: bool = False) -> list[Panel]:
    """Cases au croquis validé qui n'ont pas encore de version propre tirée de ce croquis."""
    panels = []
    for page in pages:
        for p in page.panels:
            sketch = validated_sketch(p)
            if sketch is not None and cleaned_from(p, sketch) is None:
                panels.append(p)
    if include_busy:
        return panels
    busy = _busy(session, panels)
    return [p for p in panels if p.id not in busy]


# --- mise en file -------------------------------------------------------------------------
def enqueue_sketch(
    session: Session,
    presets: PresetRegistry,
    panel: Panel,
    *,
    seed: int | None = None,
    knowledge: KnowledgeBase | None = None,
) -> Job:
    """Un croquis de la case (graine tirée au hasard sauf `seed`). Re-croquer annule la validation."""
    require_sketch_enabled(panel)
    preset = sketch_preset_id(presets, panel_cast(session, panel, presets).entries)
    panel.sketch_image_id = None
    return enqueue_panel(
        session,
        presets,
        panel,
        count=1,
        seed=seed,
        preset=preset,
        knowledge=knowledge,
        extra_params={"kind": KIND_SKETCH},
    )[0]


def enqueue_clean(
    session: Session,
    presets: PresetRegistry,
    panel: Panel,
    *,
    denoise: float | None = None,
    knowledge: KnowledgeBase | None = None,
) -> Job:
    """Version propre au palier de la série depuis le croquis validé : même graine, même prompt."""
    require_sketch_enabled(panel)
    sketch = validated_sketch(panel)
    if sketch is None:
        raise GenerationError("aucun croquis validé : valide d'abord une composition au tri")
    preset = clean_preset_id(presets, panel, panel_cast(session, panel, presets).entries)
    extra: dict[str, Any] = {
        "kind": ImageKind.final.value,
        "source_image_id": sketch.id,
        "sketch_prompt": scene_prompt(sketch),
    }
    settings = presets.workflow(preset).preset.control
    if settings is not None:
        # Passage au propre par ControlNet : le croquis validé est l'image guide (pas de débruitage).
        project = panel.page.chapter.project
        control_type = project.clean_control if project.clean_control in settings.types else settings.default_type
        extra["control"] = {
            "source": "croquis",
            "image_id": sketch.id,
            "version": sketch.version,
            "path": None,
            "type": control_type,
            "strength": settings.default_strength,
        }
    else:
        extra["denoise"] = clean_denoise(presets, panel, preset, denoise)
    return enqueue_panel(
        session, presets, panel, count=1, seed=sketch.seed, preset=preset, knowledge=knowledge, extra_params=extra
    )[0]


def validate_sketch(panel: Panel, image: PanelImage | None = None) -> PanelImage:
    """Retient la composition d'un croquis (le plus récent par défaut)."""
    image = image or latest_sketch(panel)
    if image is None or image.panel_id != panel.id or image.kind != ImageKind.croquis:
        raise GenerationError("aucun croquis à valider pour cette case : croque-la d'abord")
    panel.sketch_image_id = image.id
    return image
