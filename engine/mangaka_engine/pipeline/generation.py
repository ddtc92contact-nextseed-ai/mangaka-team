"""Étape 3 — génération des cases via ComfyUI, une à la fois.

- `enqueue_panel` : prépare le prompt final, choisit le workflow et crée `count` jobs
  `generation` (variantes) en attente ;
- `pick_references` : emplacements d'images de référence du workflow (3 au plus), remplis par
  ordre de priorité — personnages de la case, puis son décor, puis ses objets, puis la référence de
  style de la série s'il reste un emplacement libre (voir la fonction) ;
  les emplacements retenus sont notés sur le job (`params.references`) et sur la version produite ;
- `GenerationExecutor` : exécuté par la file sérielle (`pipeline/queue.py`) pour un job :
  envoi des images de référence, construction du workflow (références + LoRA via le preset),
  file ComfyUI, progression, récupération de l'image → nouvelle `PanelImage` (version n+1) ;
- `refresh_states` : états des cases et des pages (queued → generating → review, puis selon le
  verdict QC de la version choisie : approved / flagged ; `qc` pendant un contrôle).

Palier croquis (voir `pipeline/sketch.py`) : un job dont le preset a le rôle `croquis` produit une
version `kind = croquis` (petite image, jamais choisie, sans QC automatique) ; un preset `propre`
reçoit l'image de composition (le croquis validé, `params.source_image_id`) et la version produite
garde sa source dans `params.composition`.

Composition verrouillée (voir `pipeline/composition.py`) : tant qu'une case est verrouillée, chaque
génération d'un palier passe par son pendant ControlNet (`with_control`, rôle `controle`) avec l'image
guide du verrou (`params.control` du job) ; la version produite note sa source et son contrôle
(`params.composition`, méthode `controlnet`, et `params.control`).

Aucun nom de modèle, de LoRA ni de nœud ici : tout vient des presets et des fiches.
"""

from __future__ import annotations

import contextlib
import io
import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..presets import ControlInput, LoadedWorkflow, LoraSpec, PresetError, PresetRegistry, build_workflow
from ..providers.comfyui import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIInterruptedError,
    ComfyUITimeoutError,
    ComfyUIUnavailableError,
    ComfyUIWorkflowError,
)
from ..store.db import Database
from ..store.files import FileStore, InvalidImageError
from ..store.models import (
    AssetKind,
    Chapter,
    ChapterStatus,
    Character,
    CharacterImage,
    ImageKind,
    Job,
    JobStatus,
    Page,
    PageState,
    Panel,
    PanelImage,
    PanelState,
    QCVerdict,
    SeriesAsset,
    SeriesAssetImage,
)
from .art_direction import applied_panel_direction
from .inpaint import png_bytes, recompose, soften_mask
from .jobs import JobReporter
from .knowledge import KnowledgeBase
from .layout import target_size
from .library import panel_assets, style_for
from .prompt import PromptCharacter, build_negative_prompt, build_prompt
from .style import series_style

log = logging.getLogger("mangaka_engine")

STEP = "generation"
QC_STEP = "qc"
ACTIVE = (JobStatus.pending, JobStatus.running)
MAX_VARIANTS = 4
UPLOAD_SUBFOLDER = "mangaka"


class GenerationError(Exception):
    """Erreur lisible (en français) d'une génération."""


# --- préparation (pur / lecture seule) ------------------------------------------------
def panel_characters(session: Session, panel: Panel) -> list[Character]:
    """Fiches des personnages de la case, dans l'ordre de la case."""
    ids = [i for i in panel.character_ids or [] if isinstance(i, int)]
    if not ids:
        return []
    found = {
        c.id: c
        for c in session.scalars(
            select(Character).where(Character.id.in_(ids)).options(selectinload(Character.reference_images))
        )
    }
    return [found[i] for i in dict.fromkeys(ids) if i in found]


# Une fiche de la bibliothèque citée par une case : personnage, décor ou objet.
LibraryEntry = Character | SeriesAsset


@dataclass
class PanelCast:
    """Ce que la case cite dans la bibliothèque de la série."""

    characters: list[Character] = field(default_factory=list)
    decor: SeriesAsset | None = None
    objects: list[SeriesAsset] = field(default_factory=list)
    # Référence de style de la série (planche de style), jointe seulement s'il reste un emplacement.
    style: SeriesAsset | None = None

    @property
    def entries(self) -> list[LibraryEntry]:
        """Fiches dans l'ordre de priorité des images de référence : personnages, décor, objets, style."""
        return [
            *self.characters,
            *([self.decor] if self.decor is not None else []),
            *self.objects,
            *([self.style] if self.style is not None else []),
        ]


def panel_cast(session: Session, panel: Panel, presets: PresetRegistry | None = None) -> PanelCast:
    """Fiches citées par la case ; avec `presets`, la référence de style de la série si `style_board.panels`
    de defaults.yaml le permet (sans `presets` : jamais, pour qui ne lit que les personnages)."""
    project_id = panel.page.chapter.project_id
    decor, objects = panel_assets(session, panel, project_id)
    style = style_for(session, presets, project_id, "panels") if presets is not None else None
    return PanelCast(characters=panel_characters(session, panel), decor=decor, objects=objects, style=style)


def entry_kind(entry: LibraryEntry) -> str:
    return "character" if isinstance(entry, Character) else entry.kind.value


def is_style(entry: LibraryEntry) -> bool:
    return isinstance(entry, SeriesAsset) and entry.kind == AssetKind.style


def _prompt_entry(entry: LibraryEntry) -> PromptCharacter:
    triggers = split_trigger_words(entry.lora_trigger_words) if entry.lora_name else ()
    return PromptCharacter(entry.name, entry.visual_description, (*(entry.prompt_keywords or []), *triggers))


def panel_knowledge(
    session: Session, knowledge: KnowledgeBase | None, panel: Panel, characters: Sequence[Character]
) -> tuple[str, str]:
    """($savoir_faire, $bible) du prompt image ; une panne du savoir-faire ne bloque jamais une génération."""
    if knowledge is None:
        return "", ""
    query = " ".join(p for p in (panel.shot_type or "", panel.description, *(c.name for c in characters)) if p)
    decor, objects = panel_assets(session, panel, panel.page.chapter.project_id)
    query = " ".join([query, *(a.name for a in ([decor] if decor else []) + objects)])
    try:
        return knowledge.for_panel(session, panel.page.chapter.project_id, query, [c.id for c in characters])
    except Exception:  # noqa: BLE001 — le prompt se construit sans notes plutôt que d'échouer
        log.warning("savoir-faire indisponible pour le prompt de la case %s", panel.id, exc_info=True)
        return "", ""


def split_trigger_words(raw: str | None) -> tuple[str, ...]:
    """Mots déclencheurs d'un LoRA (« aiko_v1, red kimono ») → mots-clés de prompt."""
    return tuple(w.strip() for w in (raw or "").split(",") if w.strip())


def build_panel_prompt(
    presets: PresetRegistry,
    panel: Panel,
    characters: Sequence[Character],
    notes: tuple[str, str] = ("", ""),
    decor: SeriesAsset | None = None,
    objects: Sequence[SeriesAsset] = (),
) -> str:
    series = panel.page.chapter.project
    savoir_faire, bible = notes
    da = applied_panel_direction(panel)
    return build_prompt(
        description=panel.description,
        shot_type=panel.shot_type,
        plan=da.get("plan"),
        angle=da.get("angle"),
        ambiance=da.get("ambiance"),
        characters=[_prompt_entry(c) for c in characters],
        decor=_prompt_entry(decor) if decor is not None else None,
        objects=[_prompt_entry(o) for o in objects],
        style=series_style(presets, series),
        savoir_faire=savoir_faire,
        bible=bible,
        settings=presets.image_prompt,
    )


def resolve_preset_id(
    presets: PresetRegistry, panel: Panel, characters: Sequence[LibraryEntry], requested: str | None = None
) -> str:
    """Demande > preset de la case > workflow « avec références » si besoin > workflow de la série.

    Le workflow « avec références » est celui du palier de la série (`with_references` de son
    preset) ; `defaults.workflow_with_references` ne sert qu'aux presets qui n'en déclarent pas.
    `characters` : fiches de la case (personnages, et aussi décor et objets : `PanelCast.entries`).
    """
    if requested:
        return requested
    if panel.generation_preset:
        return panel.generation_preset
    series_id = panel.page.chapter.project.workflow_preset
    if not any(c.reference_images for c in characters):
        return series_id
    series = presets.workflows.get(series_id)
    if series is not None:
        if series.preset.reference_images:
            return series_id
        if series.preset.with_references:
            return series.preset.with_references
    defaults = presets.defaults
    with_refs = defaults.workflow_with_references if defaults else None
    if with_refs and with_refs in presets.workflows:
        return with_refs
    return series_id


def quality_preset_id(presets: PresetRegistry, characters: Sequence[LibraryEntry]) -> str:
    """Preset de « Régénérer en Qualité » : `defaults.workflow_quality`, ou son pendant « avec
    références » (`with_references`) si un personnage de la case a une planche de référence."""
    defaults = presets.defaults
    quality_id = defaults.workflow_quality if defaults else None
    quality = presets.workflows.get(quality_id) if quality_id else None
    if quality is None:
        raise GenerationError("aucun palier Qualité configuré (workflow_quality de presets/defaults.yaml)")
    if any(c.reference_images for c in characters) and not quality.preset.reference_images:
        if not quality.preset.with_references:
            raise GenerationError(f"le workflow Qualité {quality.preset.id} ne déclare pas de with_references")
        return quality.preset.with_references
    return quality.preset.id


def preset_tier(presets: PresetRegistry, preset_id: str | None) -> str | None:
    """Nom du palier (« Turbo », « Rapide », « Qualité ») d'un preset, s'il en déclare un."""
    loaded = presets.workflows.get(preset_id) if preset_id else None
    return loaded.preset.tier.name if loaded is not None and loaded.preset.tier is not None else None


def panel_target(presets: PresetRegistry, page: Page, panel: Panel) -> dict[str, int] | None:
    """Taille de génération calculée par la mise en page (même ratio que la case, ≈ 1 Mpx)."""
    for lp in (page.layout or {}).get("panels", []):
        target = lp.get("target") if isinstance(lp, dict) else None
        if lp.get("panel_id") == panel.id and isinstance(target, dict):
            return {"width": int(target["width"]), "height": int(target["height"])}
    box = panel.bbox
    if box and box.get("x2", 0) > box.get("x1", 0) and box.get("y2", 0) > box.get("y1", 0):
        return target_size(box["x2"] - box["x1"], box["y2"] - box["y1"], presets.layout)
    return None


def sketch_size(target: dict[str, int], long_side: int, multiple: int) -> dict[str, int]:
    """Taille d'un croquis : même ratio que la case, grand côté ≈ `long_side`, côtés multiples de `multiple`."""
    w, h = target["width"], target["height"]
    scale = long_side / max(w, h)

    def snap(v: int) -> int:
        return max(multiple, round(v * scale / multiple) * multiple)

    return {"width": snap(w), "height": snap(h)}


# Clés d'un contrôle (verrou de composition) recopiées dans les paramètres d'un job.
CONTROL_KEYS = ("source", "image_id", "version", "path", "type", "strength")


def composition_params(img: PanelImage) -> dict[str, Any]:
    """Paramètres de job qui rejouent la source de composition d'une version (croquis validé, image
    guide d'un verrou) : un nouvel essai automatique du QC repart de la même composition, avec une
    nouvelle graine."""
    comp = (img.params or {}).get("composition")
    if isinstance(comp, dict) and comp.get("method") == "controlnet":
        out: dict[str, Any] = {"control": {k: comp.get(k) for k in CONTROL_KEYS}, "locked": bool(comp.get("locked"))}
        if not comp.get("locked"):  # passage au propre par ControlNet : même prompt que le croquis
            out["sketch_prompt"] = (img.params or {}).get("prompt")
        return out
    if not isinstance(comp, dict) or comp.get("image_id") is None:
        return {}
    return {
        "source_image_id": comp["image_id"],
        "denoise": comp.get("denoise"),
        "sketch_prompt": (img.params or {}).get("prompt"),
    }


def control_variant(presets: PresetRegistry, base_id: str, entries: Sequence[LibraryEntry]) -> str:
    """Pendant ControlNet (`with_control`) d'un palier ; son `with_references` si la case a des références."""
    base = presets.workflows.get(base_id)
    if base is None:
        raise GenerationError(f"workflow inconnu : « {base_id} »")
    loaded = base if base.preset.control is not None else presets.workflows.get(base.preset.with_control or "")
    if loaded is None or loaded.preset.control is None:
        tier = base.preset.tier.name if base.preset.tier else base.preset.id
        raise GenerationError(
            f"le palier {tier} ({base.preset.id}) ne propose pas de verrouillage de composition (with_control)"
        )
    if any(e.reference_images for e in entries) and not loaded.preset.reference_images:
        refs = presets.workflows.get(loaded.preset.with_references or "")
        if refs is None or refs.preset.control is None:
            raise GenerationError(f"le workflow {loaded.preset.id} ne déclare pas de with_references ControlNet")
        return refs.preset.id
    return loaded.preset.id


def lock_control_params(lock: dict[str, Any]) -> dict[str, Any]:
    """Paramètres de job d'un verrou de composition (source, image guide, type, force)."""
    return {k: lock.get(k) for k in CONTROL_KEYS}


def guide_image(
    session: Session, files: FileStore, panel: Panel, control: dict[str, Any]
) -> tuple[dict[str, Any], bytes, str]:
    """Image guide d'un contrôle : (source décrite, octets, nom du fichier envoyé à ComfyUI)."""
    source = control.get("source")
    if source in ("croquis", "version"):
        image_id = control.get("image_id")
        img = session.get(PanelImage, int(image_id)) if isinstance(image_id, int) else None
        if img is None or img.panel_id != panel.id:
            raise GenerationError(
                "image guide introuvable (version supprimée entre-temps ?) : déverrouille puis reverrouille la case"
            )
        rel = img.path
        info: dict[str, Any] = {"source": source, "image_id": img.id, "version": img.version}
        filename = f"guide_case{panel.id}_v{img.version}{PurePosixPath(rel).suffix or '.png'}"
    elif source == "import":
        rel = str(control.get("path") or "")
        info = {"source": source, "path": rel}
        filename = f"guide_case{panel.id}_{PurePosixPath(rel).name}"
    else:
        raise GenerationError(f"source de composition inconnue : « {source} »")
    path = files.absolute(rel)
    if not rel or not path.is_file():
        raise GenerationError(f"fichier de l'image guide absent de data/ ({rel or '?'})")
    return info, path.read_bytes(), filename


def pick_references(
    characters: Sequence[LibraryEntry], slots: int
) -> list[tuple[LibraryEntry, CharacterImage | SeriesAssetImage]]:
    """Remplit les emplacements par tours, dans l'ordre de priorité des fiches.

    Ordre de priorité (`PanelCast.entries`) : personnages de la case (dans l'ordre de la case), puis
    son décor, puis ses objets. 1er tour : la 1re image de chaque fiche, dans cet ordre ; 2e tour :
    la 2e image… jusqu'à remplir les emplacements (3 au plus dans les presets livrés). Ainsi chaque
    personnage passe avant le décor, qui passe avant les objets, et une fiche n'a une 2e image que si
    toutes les autres ont déjà leur 1re.

    La référence de style (planche de style) ne prend qu'un emplacement resté libre une fois toutes
    les images des autres fiches servies.
    """
    fiches = [c for c in characters if not is_style(c)]
    out: list[tuple[LibraryEntry, CharacterImage | SeriesAssetImage]] = []
    depth = 0
    while len(out) < slots and any(depth < len(c.reference_images) for c in fiches):
        for c in fiches:
            if depth < len(c.reference_images) and len(out) < slots:
                out.append((c, c.reference_images[depth]))
        depth += 1
    for style in (c for c in characters if is_style(c)):
        if len(out) < slots and style.reference_images:
            out.append((style, style.reference_images[0]))
    return out


def collect_loras(panel: Panel, characters: Sequence[LibraryEntry]) -> list[LoraSpec]:
    """LoRA de style de la série puis LoRA de chaque fiche (personnages, décor, objets), dans l'ordre."""
    series = panel.page.chapter.project
    loras: list[LoraSpec] = []
    if series.style_lora_name:
        loras.append(LoraSpec(series.style_lora_name, series.style_lora_weight, "style"))
    for c in characters:
        if c.lora_name and all(lo.name != c.lora_name for lo in loras):
            loras.append(LoraSpec(c.lora_name, c.lora_weight, c.name))
    return loras


def panel_label(panel: Panel) -> str:
    page = panel.page
    chapter = page.chapter
    return f"{chapter.project.title} · ch. {chapter.number} · p. {page.number} · case {panel.index + 1}"


# --- mise en file ---------------------------------------------------------------------
def update_panel_prompt(
    presets: PresetRegistry, session: Session, panel: Panel, knowledge: KnowledgeBase | None = None
) -> str:
    """Reconstruit le prompt final, sauf s'il a été édité à la main."""
    if not panel.final_prompt_manual or not (panel.final_prompt or "").strip():
        cast = panel_cast(session, panel)
        notes = panel_knowledge(session, knowledge, panel, cast.characters)
        panel.final_prompt = build_panel_prompt(presets, panel, cast.characters, notes, cast.decor, cast.objects)
        panel.final_prompt_manual = False
    return panel.final_prompt or ""


def enqueue_panel(
    session: Session,
    presets: PresetRegistry,
    panel: Panel,
    *,
    count: int = 1,
    seed: int | None = None,
    preset: str | None = None,
    prompt_override: str | None = None,
    extra_params: dict[str, Any] | None = None,
    knowledge: KnowledgeBase | None = None,
) -> list[Job]:
    """Crée `count` jobs de génération en attente pour une case (sans commit)."""
    if not 1 <= count <= MAX_VARIANTS:
        raise GenerationError(f"entre 1 et {MAX_VARIANTS} variantes par demande")
    page = panel.page
    if panel_target(presets, page, panel) is None:
        raise GenerationError(f"la page {page.number} n'est pas mise en page : lance « Recalculer » d'abord")
    entries = panel_cast(session, panel, presets).entries
    preset_id = resolve_preset_id(presets, panel, entries, preset)
    loaded = presets.workflow(preset_id)  # PresetError si inconnu
    if loaded.preset.inpaint is not None:
        raise GenerationError(f"le workflow {preset_id} sert à réparer une version, pas à générer une case")
    extra = dict(extra_params or {})
    lock = panel.composition_lock
    if isinstance(lock, dict) and loaded.preset.role == "generation" and "control" not in extra:
        # Composition verrouillée : le pendant ControlNet du palier demandé, jusqu'au déverrouillage.
        extra = {**extra, "control": lock_control_params(lock), "locked": True, "base_preset": preset_id}
        preset_id = control_variant(presets, preset_id, entries)
    if presets.workflow(preset_id).preset.control is not None and not isinstance(extra.get("control"), dict):
        raise GenerationError(
            f"le workflow {preset_id} verrouille la composition : verrouille d'abord la case (source, type, force)"
        )
    if prompt_override is not None and prompt_override.strip():
        panel.final_prompt = prompt_override.strip()
        panel.final_prompt_manual = True
    prompt = update_panel_prompt(presets, session, panel, knowledge)
    if not prompt.strip():
        raise GenerationError("prompt vide : décris la case ou écris son prompt final")

    chapter = page.chapter
    jobs: list[Job] = []
    for i in range(count):
        job = Job(
            project_id=chapter.project_id,
            chapter_id=chapter.id,
            panel_id=panel.id,
            step=STEP,
            status=JobStatus.pending,
            message="En attente…",
            params={
                "preset": preset_id,
                "seed": seed + i if seed is not None else None,
                "variant": i + 1,
                "count": count,
                **extra,
            },
        )
        session.add(job)
        jobs.append(job)
    if panel.state != PanelState.generating:
        panel.state = PanelState.queued
    page.state = PageState.generating
    if chapter.status in (ChapterStatus.draft, ChapterStatus.script, ChapterStatus.layout):
        chapter.status = ChapterStatus.generation
    return jobs


def panels_to_generate(session: Session, pages: Iterable[Page], *, force: bool) -> list[Panel]:
    """Cases d'une page/d'un chapitre à générer : sans version choisie (sauf `force`), sans job actif."""
    panels = [p for page in pages for p in page.panels]
    if not panels:
        return []
    ids = [p.id for p in panels]
    busy = set(
        session.scalars(select(Job.panel_id).where(Job.panel_id.in_(ids), Job.step == STEP, Job.status.in_(ACTIVE)))
    )
    done = set(session.scalars(select(PanelImage.panel_id).where(PanelImage.panel_id.in_(ids), PanelImage.selected)))
    return [p for p in panels if p.id not in busy and (force or p.id not in done)]


# --- états ------------------------------------------------------------------------------
QC_STATES = {
    None: PanelState.review,
    QCVerdict.ok: PanelState.approved,
    QCVerdict.review: PanelState.flagged,
    QCVerdict.reject: PanelState.flagged,
}


def refresh_states(session: Session, panel_ids: Iterable[int]) -> None:
    """Recalcule l'état des cases (et de leurs pages) d'après leurs jobs, leurs versions et le QC.

    Génération en cours > en file > contrôle qualité en cours > verdict de la version choisie.
    """
    panels = list(session.scalars(select(Panel).where(Panel.id.in_(list(panel_ids)))))
    pages: dict[int, Page] = {}
    for panel in panels:
        active = {
            (step, status)
            for step, status in session.execute(
                select(Job.step, Job.status).where(
                    Job.panel_id == panel.id, Job.step.in_([STEP, QC_STEP]), Job.status.in_(ACTIVE)
                )
            )
        }
        # Les croquis ne comptent pas : une case qui n'a que des croquis reste « à générer ».
        n_images = (
            session.scalar(
                select(func.count()).where(PanelImage.panel_id == panel.id, PanelImage.kind == ImageKind.final)
            )
            or 0
        )
        chosen = session.scalar(select(PanelImage).where(PanelImage.panel_id == panel.id, PanelImage.selected))
        panel.qc_score = chosen.qc_score if chosen is not None else None
        if (STEP, JobStatus.running) in active:
            panel.state = PanelState.generating
        elif (STEP, JobStatus.pending) in active:
            panel.state = PanelState.queued
        elif (QC_STEP, JobStatus.running) in active:
            panel.state = PanelState.qc
        elif n_images == 0:
            panel.state = PanelState.draft
        else:
            panel.state = QC_STATES[chosen.qc_verdict if chosen is not None else None]
        pages[panel.page_id] = panel.page
    for page in pages.values():
        states = [p.state for p in page.panels]
        ids = [p.id for p in page.panels]
        with_images = set(
            session.scalars(
                select(PanelImage.panel_id)
                .where(PanelImage.panel_id.in_(ids), PanelImage.kind == ImageKind.final)
                .distinct()
            )
        )
        if any(s in (PanelState.queued, PanelState.generating) for s in states):
            page.state = PageState.generating
        elif ids and len(with_images) == len(ids):
            if page.state in (PageState.draft, PageState.layout, PageState.generating):
                page.state = PageState.review
        elif page.state in (PageState.generating, PageState.review):
            page.state = PageState.layout if page.layout else PageState.draft


def recover_states(db: Database) -> None:
    """Au démarrage, après `JobRunner.recover()` : plus aucun job actif, on remet les états d'aplomb."""
    with db.session_scope() as session:
        stuck = list(
            session.scalars(
                select(Panel.id).where(Panel.state.in_([PanelState.queued, PanelState.generating, PanelState.qc]))
            )
        )
        if stuck:
            refresh_states(session, stuck)
            session.commit()


# --- exécution d'un job -----------------------------------------------------------------
@dataclass
class _Plan:
    loaded: LoadedWorkflow
    params: dict[str, Any]
    references: list[dict[str, Any]]  # emplacements retenus : {kind, id, name, image_id, filename}, dans l'ordre
    reference_data: list[bytes]
    loras: list[LoraSpec]
    folder: str
    prompt: str
    panel_id: int
    # Réparation ciblée : version source, masque adouci (PNG) et réglages (`params.repair` du job).
    repair: dict[str, Any] | None = None
    source_data: bytes = b""
    mask_data: bytes = b""
    # Image de composition (preset `propre`) : {image_id, version, method, denoise, filename} + son contenu.
    sketch: dict[str, Any] | None = None
    sketch_data: bytes | None = None
    # Composition verrouillée (preset `controle`) : {source, image_id, version, path, type, strength,
    # locked, filename} + contenu de l'image guide.
    control: dict[str, Any] | None = None
    control_data: bytes | None = None


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def describe_error(exc: Exception) -> str | None:
    """Message lisible d'une erreur de génération (None : erreur interne)."""
    if isinstance(exc, ComfyUIUnavailableError | ComfyUIWorkflowError):
        return _capitalize(str(exc))
    if isinstance(exc, ComfyUIError):
        return f"ComfyUI : {exc}"
    if isinstance(exc, GenerationError | PresetError | InvalidImageError):
        return _capitalize(str(exc))
    return None


class GenerationExecutor:
    """Exécute un job `generation` (appelé par la file sérielle, un à la fois)."""

    def __init__(
        self,
        db: Database,
        presets: PresetRegistry,
        files: FileStore,
        comfyui: ComfyUIClient | None,
        *,
        comfyui_error: str | None = None,
        poll_s: float = 1.0,
        on_generated: Callable[[Session, Job, PanelImage], None] | None = None,
        presets_for: Callable[[int | None], PresetRegistry] | None = None,
        knowledge: KnowledgeBase | None = None,
    ) -> None:
        self.db = db
        self.knowledge = knowledge
        # Presets effectifs d'une série (profils des agents, écran « L'équipe ») ; sans profil : `presets`.
        self.presets_for = presets_for or (lambda _project_id: presets)
        # Appelé avec la nouvelle version, avant le commit (mise en file du QC automatique).
        self.on_generated = on_generated
        self.presets = presets
        self.files = files
        self.comfyui = comfyui
        self.comfyui_error = comfyui_error
        self.poll_s = poll_s
        self._prompt_ids: dict[int, str] = {}

    # Appelé par SerialJobQueue.cancel pour un job en cours.
    def interrupt(self, job_id: int) -> None:
        prompt_id = self._prompt_ids.get(job_id)
        if self.comfyui is not None and prompt_id is not None:
            self.comfyui.interrupt(prompt_id)

    def after(self, job_id: int) -> None:
        """Recalcule les états de la case du job (au démarrage et à la fin)."""
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None and job.panel_id is not None:
                refresh_states(session, [job.panel_id])
                session.commit()

    def _plan(self, job_id: int) -> _Plan:
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            if job is None or job.panel_id is None:
                raise GenerationError("case introuvable (supprimée entre-temps ?)")
            panel = session.get(Panel, job.panel_id)
            if panel is None:
                raise GenerationError("case introuvable (supprimée entre-temps ?)")
            page = panel.page
            chapter: Chapter = page.chapter
            presets = self.presets_for(chapter.project_id)
            cast = panel_cast(session, panel, presets)
            entries = cast.entries
            preset_id = str(job.params.get("preset") or resolve_preset_id(presets, panel, entries))
            loaded = presets.workflow(preset_id)
            repair = job.params.get("repair") if isinstance(job.params.get("repair"), dict) else None
            source_data = mask_data = b""
            size: dict[str, int] | None
            if repair is not None:
                if loaded.preset.inpaint is None:
                    raise GenerationError(f"le workflow {preset_id} n'est pas un preset de réparation")
                source, source_data, mask_data, size = self._repair_inputs(session, panel.id, repair)
                prompt = str(repair.get("prompt") or "")
                concerned = [c for c in cast.characters if c.id == repair.get("character_id")]
                if concerned:
                    # Le personnage concerné d'abord (références et LoRA d'identité), puis le style de la série.
                    entries = concerned
            else:
                if loaded.preset.inpaint is not None:
                    raise GenerationError(f"le workflow {preset_id} sert à réparer une version, pas à générer une case")
                # Passage au propre : même prompt que le croquis validé (sinon le prompt final de la case).
                prompt = str(job.params.get("sketch_prompt") or "").strip() or update_panel_prompt(
                    presets, session, panel, self.knowledge
                )
                size = panel_target(presets, page, panel)
            if size is None:
                raise GenerationError(f"la page {page.number} n'est pas mise en page")
            if repair is None and loaded.preset.role == "croquis" and loaded.preset.long_side:
                size = sketch_size(size, loaded.preset.long_side, presets.layout.generation.multiple)
            sketch, sketch_data = self._sketch_source(session, job, panel, loaded)
            control, control_data = self._control_source(session, job, panel, loaded)
            references: list[dict[str, Any]] = []
            reference_data: list[bytes] = []
            for entry, image in pick_references(entries, len(loaded.preset.reference_images)):
                path = self.files.absolute(image.path)
                if not path.is_file():
                    raise GenerationError(f"image de référence de {entry.name} absente de data/ ({image.path})")
                ext = PurePosixPath(image.path).suffix or ".png"
                kind = entry_kind(entry)
                prefix = {"character": "perso", "decor": "decor", "object": "objet", "style": "style"}[kind]
                references.append(
                    {
                        "slot": len(references) + 1,
                        "kind": kind,
                        "id": entry.id,
                        "name": entry.name,
                        "image_id": image.id,
                        "filename": f"{prefix}{entry.id}_img{image.id}{ext}",
                    }
                )
                reference_data.append(path.read_bytes())
            # « Références utilisées » : notées sur le job dès la préparation (visibles dans l'atelier).
            job.params = {**(job.params or {}), "references": references}
            params: dict[str, Any] = {
                "positive_prompt": prompt,
                "negative_prompt": build_negative_prompt(
                    str(loaded.preset.defaults.get("negative_prompt", "")), presets.image_prompt
                ),
                "seed": job.params.get("seed"),
            }
            if repair is not None:
                params["denoise"] = float(repair.get("denoise") or loaded.preset.defaults.get("denoise") or 0.45)
            else:
                params.update(size)
            if sketch is not None and "denoise" in loaded.preset.mapping:
                params["denoise"] = sketch["denoise"]
            if "filename_prefix" in loaded.preset.mapping:
                params["filename_prefix"] = (
                    f"mangaka/serie-{chapter.project_id}/chapitre-{chapter.number}/page-{page.number}"
                    f"/{'croquis-' if loaded.preset.role == 'croquis' else ''}case-{panel.index + 1}"
                )
            plan = _Plan(
                loaded=loaded,
                params=params,
                references=references,
                reference_data=reference_data,
                loras=collect_loras(panel, entries),
                folder=f"projects/{chapter.project_id}/chapters/{chapter.id}/panels/{panel.id}",
                prompt=prompt,
                panel_id=panel.id,
                repair={**repair, "image_width": size["width"], "image_height": size["height"]} if repair else None,
                source_data=source_data,
                mask_data=mask_data,
                sketch=sketch,
                sketch_data=sketch_data,
                control=control,
                control_data=control_data,
            )
            session.commit()  # prompt final éventuellement reconstruit
            return plan

    def _sketch_source(
        self, session: Session, job: Job, panel: Panel, loaded: LoadedWorkflow
    ) -> tuple[dict[str, Any] | None, bytes | None]:
        """Image de composition d'un preset `propre` : le croquis désigné par le job (`source_image_id`)."""
        if loaded.preset.source_image is None:
            return None, None
        source_id = job.params.get("source_image_id")
        sketch = session.get(PanelImage, int(source_id)) if source_id is not None else None
        if sketch is None or sketch.panel_id != panel.id:
            raise GenerationError(
                "croquis source introuvable (supprimé entre-temps ?) : valide un croquis puis relance"
            )
        path = self.files.absolute(sketch.path)
        if not path.is_file():
            raise GenerationError(f"fichier du croquis absent de data/ ({sketch.path})")
        denoise = job.params.get("denoise")
        if denoise is None:
            denoise = loaded.preset.defaults.get("denoise")
        source = {
            "source": sketch.kind.value,
            "image_id": sketch.id,
            "version": sketch.version,
            "seed": sketch.seed,
            "method": "img2img",
            "denoise": denoise,
            "filename": f"croquis_case{panel.id}_v{sketch.version}{PurePosixPath(sketch.path).suffix or '.png'}",
        }
        return source, path.read_bytes()

    def _control_source(
        self, session: Session, job: Job, panel: Panel, loaded: LoadedWorkflow
    ) -> tuple[dict[str, Any] | None, bytes | None]:
        """Image guide d'un preset ControlNet : celle du verrou (ou du croquis validé) notée sur le job."""
        settings = loaded.preset.control
        if settings is None:
            return None, None
        params = job.params.get("control")
        if not isinstance(params, dict):
            raise GenerationError(
                f"le workflow {loaded.preset.id} verrouille la composition : aucune image guide pour ce job"
            )
        type_id = str(params.get("type") or settings.default_type)
        if type_id not in settings.types:
            raise GenerationError(
                f"type de contrôle inconnu pour le workflow {loaded.preset.id} : « {type_id} » "
                f"(possibles : {', '.join(settings.types)})"
            )
        strength = params.get("strength")
        info, data, filename = guide_image(session, self.files, panel, params)
        return {
            **info,
            "type": type_id,
            "strength": float(strength) if isinstance(strength, int | float) else settings.default_strength,
            "locked": bool(job.params.get("locked")),
            "filename": filename,
        }, data

    def _repair_inputs(
        self, session: Session, panel_id: int, repair: dict[str, Any]
    ) -> tuple[PanelImage, bytes, bytes, dict[str, int]]:
        """Version source (octets), masque agrandi et adouci (PNG) et taille de l'image source."""
        source = session.get(PanelImage, repair.get("source_image_id"))
        if source is None or source.panel_id != panel_id:
            raise GenerationError("version source introuvable (supprimée entre-temps ?)")
        source_path = self.files.absolute(source.path)
        mask_path = self.files.absolute(str(repair.get("mask_path") or ""))
        if not source_path.is_file():
            raise GenerationError(f"image de la version {source.version} absente de data/ ({source.path})")
        if not mask_path.is_file():
            raise GenerationError("masque de la réparation absent de data/")
        source_data = source_path.read_bytes()
        with Image.open(io.BytesIO(source_data)) as img:
            width, height = img.size
        with Image.open(mask_path) as raw:
            mask = raw.convert("L").resize((width, height), Image.Resampling.NEAREST)
        soft = soften_mask(mask, int(repair.get("grow_px") or 0), int(repair.get("feather_px") or 0))
        return source, source_data, png_bytes(soft), {"width": width, "height": height}

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        if self.comfyui is None:
            raise GenerationError(f"ComfyUI indisponible : {self.comfyui_error or 'client non configuré'}")
        comfy = self.comfyui
        t0 = time.monotonic()
        self.after(job_id)  # case et page → « generating »
        report(2, "Préparation du prompt et du workflow…")
        plan = self._plan(job_id)
        preset = plan.loaded.preset

        uploaded: list[str] = []
        for i, (ref, data) in enumerate(zip(plan.references, plan.reference_data, strict=True), start=1):
            report(4, f"Envoi de l'image de référence {i}/{len(plan.references)} à ComfyUI…")
            uploaded.append(comfy.upload_image(data, ref["filename"], subfolder=UPLOAD_SUBFOLDER))
        sketch_name: str | None = None
        if plan.sketch is not None and plan.sketch_data is not None:
            report(6, f"Envoi du croquis validé (version {plan.sketch['version']}) à ComfyUI…")
            sketch_name = comfy.upload_image(plan.sketch_data, plan.sketch["filename"], subfolder=UPLOAD_SUBFOLDER)
        control: ControlInput | None = None
        if plan.control is not None and plan.control_data is not None:
            report(6, "Envoi de l'image guide (composition verrouillée) à ComfyUI…")
            name = comfy.upload_image(plan.control_data, plan.control["filename"], subfolder=UPLOAD_SUBFOLDER)
            control = ControlInput(image=name, type=plan.control["type"], strength=plan.control["strength"])
        inpaint_images: tuple[str, str] | None = None
        if plan.repair is not None:
            report(6, "Envoi de la version source et du masque à ComfyUI…")
            source_id = plan.repair.get("source_image_id")
            inpaint_images = (
                comfy.upload_image(plan.source_data, f"source_img{source_id}.png", subfolder=UPLOAD_SUBFOLDER),
                comfy.upload_image(plan.mask_data, f"masque_job{job_id}.png", subfolder=UPLOAD_SUBFOLDER),
            )
        built = build_workflow(
            plan.loaded,
            plan.params,
            reference_images=uploaded,
            loras=plan.loras,
            inpaint_images=inpaint_images,
            source_image=sketch_name,
            control=control,
        )
        if cancel.is_set():
            raise ComfyUIInterruptedError("génération annulée")

        report(8, f"Envoi du workflow « {preset.name} » à ComfyUI…")
        prompt_id = comfy.queue_prompt(built.workflow)
        self._prompt_ids[job_id] = prompt_id
        last = [-1]

        def on_progress(value: int, maximum: int) -> None:
            pct = 10 + int(80 * value / maximum)
            if pct != last[0]:
                last[0] = pct
                report(pct, f"Génération : étape {value}/{maximum}")

        try:
            report(10, "Génération en cours dans ComfyUI…")
            refs = comfy.wait_for_images(
                prompt_id,
                built.output_node,
                timeout_s=preset.timeout_s,
                poll_s=self.poll_s,
                on_progress=on_progress,
                should_stop=cancel.is_set,
            )
        except ComfyUITimeoutError:
            with contextlib.suppress(ComfyUIError):
                comfy.interrupt(prompt_id)
            raise GenerationError(
                f"ComfyUI n'a pas terminé la génération en {preset.timeout_s:.0f} s "
                f"(délai réglable : timeout_s du preset {preset.id})"
            ) from None
        finally:
            self._prompt_ids.pop(job_id, None)

        report(92, "Récupération de l'image…")
        data = comfy.fetch_image(refs[0])
        if plan.repair is not None:
            # Seule la zone masquée (adoucie) est reprise : le reste est l'original, au pixel près.
            report(95, "Recollage de la zone réparée sur l'original…")
            try:
                with (
                    Image.open(io.BytesIO(plan.source_data)) as source,
                    Image.open(io.BytesIO(data)) as generated,
                    Image.open(io.BytesIO(plan.mask_data)) as soft,
                ):
                    data = png_bytes(recompose(source, generated, soft))
            except (UnidentifiedImageError, OSError) as exc:
                raise GenerationError(f"image renvoyée par ComfyUI illisible : {exc}") from None
        stored = self.files.save_image(data, plan.folder)
        duration_ms = int((time.monotonic() - t0) * 1000)

        with self.db.session_scope() as session:
            panel = session.get(Panel, plan.panel_id)
            if panel is None:
                self.files.delete(stored.path)
                raise GenerationError("case supprimée pendant la génération")
            version = (
                session.scalar(select(func.max(PanelImage.version)).where(PanelImage.panel_id == panel.id)) or 0
            ) + 1
            has_selected = session.scalar(
                select(PanelImage.id).where(PanelImage.panel_id == panel.id, PanelImage.selected)
            )
            kind = ImageKind.croquis if preset.role == "croquis" else ImageKind.final
            composition = (
                {
                    **{k: v for k, v in plan.sketch.items() if k != "filename"},
                    "denoise": built.params.get("denoise", plan.sketch["denoise"]),
                    "comfyui_name": sketch_name,
                }
                if plan.sketch is not None
                else None
            )
            if plan.control is not None and built.control is not None:
                composition = {
                    **{k: v for k, v in plan.control.items() if k != "filename"},
                    "method": "controlnet",
                    "type_name": built.control["name"],
                    "preprocessor": built.control["preprocessor"],
                    "comfyui_name": built.control["image"],
                }
            from_sketch = composition is not None and composition.get("source") == "croquis"
            image = PanelImage(
                panel_id=panel.id,
                version=version,
                kind=kind,
                path=stored.path,
                seed=built.params["seed"],
                # La première version est choisie d'office ; un croquis ne l'est jamais (jamais assemblé).
                selected=has_selected is None and kind == ImageKind.final,
                params={
                    "kind": kind.value,
                    **({"composition": composition} if composition else {}),
                    **({"sketch_image_id": composition["image_id"]} if composition and from_sketch else {}),
                    **({"control": built.control} if built.control is not None else {}),
                    "preset": preset.id,
                    "preset_name": preset.name,
                    "tier": preset.tier.name if preset.tier else None,
                    "prompt": built.params["positive_prompt"],
                    "negative_prompt": built.params["negative_prompt"],
                    "seed": built.params["seed"],
                    "width": built.params.get("width", stored.width),
                    "height": built.params.get("height", stored.height),
                    "workflow_params": built.params,
                    "loras": [lo.as_dict() for lo in built.loras],
                    "reference_images": [
                        {
                            **{k: v for k, v in ref.items() if k != "filename"},
                            **({"character_id": ref["id"]} if ref["kind"] == "character" else {}),
                            "comfyui_name": name,
                        }
                        for ref, name in zip(plan.references, uploaded, strict=True)
                    ],
                    "removed_nodes": built.removed_nodes,
                    "image_width": stored.width,
                    "image_height": stored.height,
                    "content_type": stored.content_type,
                    "duration_ms": duration_ms,
                    "job_id": job_id,
                    "comfyui_prompt_id": prompt_id,
                    "comfyui": comfy.name,
                    **({"repair": _repair_params(plan.repair)} if plan.repair is not None else {}),
                },
            )
            session.add(image)
            session.flush()
            job = session.get(Job, job_id)
            # Pas de QC automatique sur un croquis : c'est l'œil de l'auteur qui trie.
            if self.on_generated is not None and job is not None and kind == ImageKind.final:
                try:
                    self.on_generated(session, job, image)
                except Exception:  # noqa: BLE001 — la version est gardée même si le QC ne peut être mis en file
                    log.exception("job %s : mise en file du contrôle qualité impossible", job_id)
            session.commit()
        if plan.repair is not None:
            return f"Version {version} — réparation de la v{plan.repair.get('source_version')}, seed {built.params['seed']}"
        label = "Croquis" if kind == ImageKind.croquis else "Version"
        return f"{label} {version} — {stored.width}×{stored.height}, seed {built.params['seed']}"


def _repair_params(repair: dict[str, Any]) -> dict[str, Any]:
    """Lien d'une version réparée vers sa source et réglages de la réparation (sans le prompt, déjà noté)."""
    keys = (
        "source_image_id",
        "source_version",
        "target",
        "character_id",
        "character_name",
        "regions",
        "painted",
        "mask_path",
        "mask_bbox",
        "grow_px",
        "feather_px",
        "denoise",
    )
    return {k: repair.get(k) for k in keys}
