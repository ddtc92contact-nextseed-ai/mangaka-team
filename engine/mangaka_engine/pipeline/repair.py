"""Réparation ciblée (inpainting) : repeindre une main ou un visage raté sans régénérer la case.

- la zone vient des détections du QC (`PanelImage.detections` : boîtes en px de l'image), de
  rectangles tracés ou d'un masque peint dans l'atelier → `build_mask` (binaire, taille de l'image) ;
- `soften_mask` l'agrandit d'une marge (`grow_px`) et en fond les bords (`feather_px`) : hors de
  « zone + marge + adoucissement » (`influence_zone`), le masque vaut exactement 0 ;
- ComfyUI repeint la zone (preset avec bloc `inpaint`), puis `recompose` recolle seulement la zone
  masquée sur l'original : là où le masque vaut 0, les pixels sont ceux de l'original, au pixel près ;
- masque, adoucissement et recollage : `pipeline/inpaint.py` (fonctions pures) ;
- `enqueue_repair` met en file un job `generation` marqué `repair` (même file, même progression) ;
  le résultat est une nouvelle version de la case, liée à sa source (`params.repair`).

Aucun nom de modèle ni de nœud ici : tout vient du preset de réparation.
"""

from __future__ import annotations

import string
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image
from sqlalchemy.orm import Session

from ..presets import ImagePromptSettings, LoadedWorkflow, PresetError, PresetRegistry
from ..presets.schemas import REPAIR_TARGETS, InpaintSettings
from ..store.files import FileStore
from ..store.models import ChapterStatus, Character, Job, JobStatus, PageState, PanelImage, PanelState
from .generation import STEP, GenerationError, _prompt_entry, panel_cast, panel_target, style_with_triggers
from .inpaint import MaskError, Region, build_mask, is_sketch, png_bytes
from .prompt import PromptCharacter, _clean, describe_character, strip_quoted


# --- preset et prompt ---------------------------------------------------------------------
def inpaint_preset_id(presets: PresetRegistry, source_preset: str | None, series_preset: str | None) -> str:
    """Preset de réparation : celui du workflow de la version source (`inpaint_with`), sinon celui du
    workflow de la série, sinon `defaults.workflow_inpaint` — même palier, mêmes modèles."""
    for pid in (source_preset, series_preset):
        loaded = presets.workflows.get(pid) if pid else None
        if loaded is not None and loaded.preset.inpaint_with:
            return loaded.preset.inpaint_with
    fallback = presets.defaults.workflow_inpaint if presets.defaults else None
    if fallback:
        return fallback
    raise GenerationError(
        "aucun preset de réparation configuré (inpaint_with du workflow ou workflow_inpaint de presets/defaults.yaml)"
    )


def inpaint_workflow(presets: PresetRegistry, preset_id: str) -> tuple[LoadedWorkflow, InpaintSettings]:
    loaded = presets.workflow(preset_id)
    if loaded.preset.inpaint is None:
        raise PresetError(f"le workflow {preset_id} n'est pas un preset de réparation (bloc inpaint absent)")
    return loaded, loaded.preset.inpaint


def repair_prompt(
    settings: InpaintSettings,
    *,
    target: str,
    character: PromptCharacter | None,
    description: str,
    style: str,
    image_prompt: ImagePromptSettings | None = None,
) -> str:
    """Prompt de réparation prérempli : zone visée, personnage concerné, description de la case, style."""
    values = {
        "target": _clean(settings.targets.get(target, "")),
        "character": describe_character(character, image_prompt or ImagePromptSettings()) if character else "",
        "description": _clean(strip_quoted(description or "")),
        "style": _clean(style),
    }
    parts: list[str] = []
    for part in settings.prompt_parts:
        tpl = string.Template(part)
        if any(not values[v] for v in tpl.get_identifiers()):
            continue
        parts.append(tpl.substitute(values).strip())
    return " ".join(p for p in parts if p)


@dataclass
class RepairContext:
    """Ce qu'il faut pour préremplir puis lancer une réparation sur une version."""

    preset_id: str
    loaded: LoadedWorkflow
    settings: InpaintSettings
    characters: list[Character]


def repair_context(session: Session, presets: PresetRegistry, image: PanelImage) -> RepairContext:
    if is_sketch(image.params):
        raise GenerationError("la réparation s'applique aux versions propres, pas aux croquis")
    panel = image.panel
    preset_id = inpaint_preset_id(
        presets, (image.params or {}).get("preset"), panel.page.chapter.project.workflow_preset
    )
    loaded, settings = inpaint_workflow(presets, preset_id)
    return RepairContext(preset_id, loaded, settings, panel_cast(session, panel).characters)


def concerned_character(ctx: RepairContext, character_id: int | None) -> Character | None:
    if character_id is None:
        return None
    found = next((c for c in ctx.characters if c.id == character_id), None)
    if found is None:
        raise GenerationError(f"personnage {character_id} absent de la case")
    return found


def default_repair_prompt(
    presets: PresetRegistry, ctx: RepairContext, image: PanelImage, target: str, character: Character | None
) -> str:
    series = image.panel.page.chapter.project
    return repair_prompt(
        ctx.settings,
        target=target,
        character=_prompt_entry(character) if character is not None else None,
        description=image.panel.description,
        style=style_with_triggers(series.style, series.style_lora_trigger_words if series.style_lora_name else ""),
        image_prompt=presets.image_prompt,
    )


# --- mise en file -----------------------------------------------------------------------------
def enqueue_repair(
    session: Session,
    presets: PresetRegistry,
    files: FileStore,
    image: PanelImage,
    *,
    regions: Sequence[Region] = (),
    painted: bytes | None = None,
    target: str = "zone",
    character_id: int | None = None,
    prompt: str | None = None,
    grow_px: int | None = None,
    feather_px: int | None = None,
    denoise: float | None = None,
    seed: int | None = None,
) -> Job:
    """Crée le job de réparation d'une version (sans commit). Le masque brut est gardé dans data/."""
    if target not in REPAIR_TARGETS:
        raise GenerationError(f"zone inconnue : {target} (possibles : {', '.join(REPAIR_TARGETS)})")
    ctx = repair_context(session, presets, image)
    character = concerned_character(ctx, character_id)
    panel = image.panel
    page = panel.page
    if panel_target(presets, page, panel) is None:
        raise GenerationError(f"la page {page.number} n'est pas mise en page : lance « Recalculer » d'abord")
    path = files.absolute(image.path)
    if not path.is_file():
        raise GenerationError(f"image de la version {image.version} absente de data/ ({image.path})")
    with Image.open(path) as src:
        size = src.size
    try:
        mask = build_mask(size, regions, painted)
    except MaskError as exc:
        raise GenerationError(str(exc)) from None
    if mask.getbbox() is None:
        raise GenerationError("zone vide : choisis une détection, trace un rectangle ou peins la zone à réparer")
    text = (prompt or "").strip() or default_repair_prompt(presets, ctx, image, target, character)
    if not text:
        raise GenerationError("prompt de réparation vide")
    defaults = ctx.loaded.preset.defaults
    chapter = page.chapter
    stored = files.save_image(
        png_bytes(mask), f"projects/{chapter.project_id}/chapters/{chapter.id}/panels/{panel.id}/masques"
    )
    job = Job(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        panel_id=panel.id,
        step=STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={
            "preset": ctx.preset_id,
            "seed": seed,
            "variant": 1,
            "count": 1,
            "repair": {
                "source_image_id": image.id,
                "source_version": image.version,
                "target": target,
                "character_id": character.id if character is not None else None,
                "character_name": character.name if character is not None else None,
                "regions": [{"x1": r.x1, "y1": r.y1, "x2": r.x2, "y2": r.y2} for r in regions],
                "painted": painted is not None,
                "mask_path": stored.path,
                "mask_bbox": list(mask.getbbox() or ()),
                "grow_px": ctx.settings.grow_px if grow_px is None else grow_px,
                "feather_px": ctx.settings.feather_px if feather_px is None else feather_px,
                "denoise": float(defaults.get("denoise", 0.45)) if denoise is None else denoise,
                "prompt": text,
            },
        },
    )
    session.add(job)
    if panel.state != PanelState.generating:
        panel.state = PanelState.queued
    page.state = PageState.generating
    if chapter.status in (ChapterStatus.draft, ChapterStatus.script, ChapterStatus.layout):
        chapter.status = ChapterStatus.generation
    return job
