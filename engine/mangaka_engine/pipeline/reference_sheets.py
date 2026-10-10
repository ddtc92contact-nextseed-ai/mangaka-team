"""« Créer des références » : fiches de référence d'un personnage, d'un objet ou d'un décor via ComfyUI.

- `sheet_prompt` / `sheet_loras` / `sheet_preset_id` / `sheet_params` (purs) : prompt du type de fiche
  (`presets/reference_sheets/*.yaml`) rempli avec la fiche de la bibliothèque et la série, chaîne de
  LoRA (style de la série puis LoRA de la fiche), workflow (palier de la série, Qualité sur demande,
  pendant « avec références » pour « Affiner »), paramètres mappés (taille de la fiche) ;
- `enqueue_sheet` : crée `count` jobs `reference` en attente dans la file ComfyUI unique (même
  progression, même annulation que les cases) ; « Affiner » = mêmes jobs avec une variante de départ
  envoyée comme image de référence et une consigne ;
- `ReferenceExecutor` : exécute un job → nouvelle `ReferenceVariant` dans l'historique de la fiche ;
- `keep_variant` : « Garder comme référence » copie la variante parmi les images de référence de la
  fiche (en dernière position ; l'ordre se règle ensuite à la main).

Aucun nom de modèle, de LoRA ni de nœud ici : tout vient des presets et des fiches.
"""

from __future__ import annotations

import contextlib
import string
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..presets import LoadedWorkflow, LoraSpec, PresetRegistry, build_workflow
from ..presets.schemas import ReferenceSheet
from ..providers.comfyui import ComfyUIClient, ComfyUIError, ComfyUIInterruptedError, ComfyUITimeoutError
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import (
    AssetKind,
    Character,
    CharacterImage,
    Job,
    JobStatus,
    Project,
    ReferenceVariant,
    SeriesAsset,
    SeriesAssetImage,
)
from .generation import UPLOAD_SUBFOLDER, GenerationError, split_trigger_words, style_with_triggers
from .jobs import JobReporter
from .prompt import build_negative_prompt

STEP = "reference"
ACTIVE = (JobStatus.pending, JobStatus.running)
DEFAULT_VARIANTS = 4
MAX_VARIANTS = 4
# Images de référence gardées au plus par fiche (« Garder comme référence »).
MAX_KEPT = 8

LibraryEntry = Character | SeriesAsset
ReferenceImage = CharacterImage | SeriesAssetImage
ENTRY_KINDS = ("character", "object", "decor")
# Sorte → dossier sous data/projects/{id}/ (le même que les images envoyées).
FOLDERS = {"character": "characters", "object": "objects", "decor": "decors"}
KIND_LABELS = {"character": "personnage", "object": "objet", "decor": "décor"}


def entry_kind(entry: LibraryEntry) -> str:
    return "character" if isinstance(entry, Character) else entry.kind.value


def load_entry(session: Session, kind: str, entry_id: int) -> LibraryEntry | None:
    """Fiche de la bibliothèque (avec ses images de référence), None si absente ou d'une autre sorte."""
    if kind == "character":
        return session.get(Character, entry_id, options=[selectinload(Character.reference_images)])
    asset = session.get(SeriesAsset, entry_id, options=[selectinload(SeriesAsset.reference_images)])
    return asset if asset is not None and asset.kind == AssetKind(kind) else None


def entry_folder(entry: LibraryEntry) -> str:
    return f"projects/{entry.project_id}/{FOLDERS[entry_kind(entry)]}/{entry.id}"


def sheets_for(presets: PresetRegistry, kind: str) -> list[ReferenceSheet]:
    return [s for s in presets.reference_sheets.values() if kind in s.kinds]


# --- préparation (pur) -----------------------------------------------------------------
def _clean(text: str | None) -> str:
    return " ".join((text or "").split()).rstrip(" .;,:")


def sheet_prompt(sheet: ReferenceSheet, entry: LibraryEntry, series: Project, instruction: str = "") -> str:
    """Prompt positif : morceaux du type de fiche, un morceau dont une variable est vide est omis."""
    triggers = split_trigger_words(entry.lora_trigger_words) if entry.lora_name else ()
    keywords = list(dict.fromkeys(k for k in (_clean(k) for k in (*(entry.prompt_keywords or []), *triggers)) if k))
    style_triggers = series.style_lora_trigger_words if series.style_lora_name else ""
    values = {
        "name": _clean(entry.name),
        "description": _clean(entry.visual_description),
        "keywords": ", ".join(keywords),
        "style": _clean(style_with_triggers(series.style or "", style_triggers)),
        "instruction": _clean(instruction),
    }
    parts: list[str] = []
    for part in sheet.prompt:
        tpl = string.Template(part)
        if any(not values[v] for v in tpl.get_identifiers()):
            continue
        parts.append(tpl.substitute(values).strip())
    return " ".join(p for p in parts if p)


def sheet_loras(series: Project, entry: LibraryEntry) -> list[LoraSpec]:
    """LoRA de style de la série puis LoRA de la fiche (comme pour une case)."""
    loras: list[LoraSpec] = []
    if series.style_lora_name:
        loras.append(LoraSpec(series.style_lora_name, series.style_lora_weight, "style"))
    if entry.lora_name and all(lo.name != entry.lora_name for lo in loras):
        loras.append(LoraSpec(entry.lora_name, entry.lora_weight, entry.name))
    return loras


def sheet_preset_id(
    presets: PresetRegistry, sheet: ReferenceSheet, series: Project, *, quality: bool = False, refine: bool = False
) -> str:
    """Workflow d'une génération de fiche.

    Workflow imposé par le type de fiche > palier Qualité (`defaults.workflow_quality`) si demandé >
    palier de la série. Pour « Affiner » (une image de référence), son pendant « avec références »
    (`with_references`, sinon `defaults.workflow_with_references`).
    """
    defaults = presets.defaults
    if sheet.workflow:
        base_id = sheet.workflow
    elif quality:
        if not (defaults and defaults.workflow_quality):
            raise GenerationError("aucun palier Qualité configuré (workflow_quality de presets/defaults.yaml)")
        base_id = defaults.workflow_quality
    else:
        base_id = series.workflow_preset
    base = presets.workflow(base_id)
    if not refine or base.preset.reference_images:
        return base_id
    if base.preset.with_references:
        return base.preset.with_references
    fallback = defaults.workflow_with_references if defaults else None
    if fallback and fallback in presets.workflows:
        return fallback
    raise GenerationError(f"le workflow {base_id} n'a pas de pendant avec image de référence : « Affiner » impossible")


def sheet_params(
    loaded: LoadedWorkflow,
    sheet: ReferenceSheet,
    prompt: str,
    presets: PresetRegistry,
    *,
    seed: int | None = None,
    filename_prefix: str | None = None,
) -> dict[str, Any]:
    """Paramètres mappés du workflow : prompts, seed, taille du type de fiche."""
    base_negative = str(loaded.preset.defaults.get("negative_prompt", ""))
    negative = ", ".join(t for t in (base_negative.strip(), sheet.negative_prompt.strip()) if t)
    params: dict[str, Any] = {
        "positive_prompt": prompt,
        "negative_prompt": build_negative_prompt(negative, presets.image_prompt),
        "seed": seed,
        "width": sheet.width,
        "height": sheet.height,
    }
    if filename_prefix and "filename_prefix" in loaded.preset.mapping:
        params["filename_prefix"] = filename_prefix
    return params


# --- mise en file ----------------------------------------------------------------------
def enqueue_sheet(
    session: Session,
    presets: PresetRegistry,
    entry: LibraryEntry,
    sheet_id: str,
    *,
    count: int = DEFAULT_VARIANTS,
    quality: bool = False,
    seed: int | None = None,
    parent: ReferenceVariant | None = None,
    instruction: str = "",
) -> list[Job]:
    """Crée `count` jobs `reference` en attente (sans commit). `parent` : « Affiner » depuis cette variante."""
    if not 1 <= count <= MAX_VARIANTS:
        raise GenerationError(f"entre 1 et {MAX_VARIANTS} variantes par demande")
    kind = entry_kind(entry)
    sheet = presets.reference_sheet(sheet_id)
    if kind not in sheet.kinds:
        raise GenerationError(f"la fiche « {sheet.name} » ne s'applique pas à un {KIND_LABELS[kind]}")
    instruction = _clean(instruction)
    if parent is not None and not instruction:
        raise GenerationError("décris ce qu'il faut changer (ex. « cheveux plus courts »)")
    series = session.get(Project, entry.project_id)
    if series is None:
        raise GenerationError("série introuvable")
    preset_id = sheet_preset_id(presets, sheet, series, quality=quality, refine=parent is not None)
    loaded = presets.workflow(preset_id)
    prompt = sheet_prompt(sheet, entry, series, instruction)
    if not prompt.strip():
        raise GenerationError("prompt vide : décris la fiche (description visuelle ou mots-clés)")
    jobs: list[Job] = []
    for i in range(count):
        job = Job(
            project_id=entry.project_id,
            step=STEP,
            status=JobStatus.pending,
            message="En attente…",
            params={
                "entry_kind": kind,
                "entry_id": entry.id,
                "entry_name": entry.name,
                "sheet": sheet.id,
                "sheet_name": sheet.name,
                "preset": preset_id,
                "tier": loaded.preset.tier.name if loaded.preset.tier else None,
                "quality": quality,
                "prompt": prompt,
                "seed": seed + i if seed is not None else None,
                "variant": i + 1,
                "count": count,
                "parent_id": parent.id if parent is not None else None,
                "instruction": instruction,
            },
        )
        session.add(job)
        jobs.append(job)
    return jobs


def active_jobs(session: Session, kind: str, entry_id: int, project_id: int) -> list[Job]:
    """Générations de fiches en cours ou en attente pour cette fiche, dans l'ordre de la file."""
    rows = session.scalars(
        select(Job).where(Job.step == STEP, Job.status.in_(ACTIVE), Job.project_id == project_id).order_by(Job.id)
    )
    return [
        j for j in rows if (j.params or {}).get("entry_kind") == kind and (j.params or {}).get("entry_id") == entry_id
    ]


# --- garder / supprimer ------------------------------------------------------------------
def kept_image(entry: LibraryEntry, variant: ReferenceVariant) -> ReferenceImage | None:
    if variant.kept_image_id is None:
        return None
    return next((img for img in entry.reference_images if img.id == variant.kept_image_id), None)


def next_position(entry: LibraryEntry) -> int:
    return max((img.position for img in entry.reference_images), default=-1) + 1


def keep_variant(session: Session, files: FileStore, entry: LibraryEntry, variant: ReferenceVariant) -> ReferenceImage:
    """Copie la variante parmi les images de référence de la fiche (dernière position) ; sans commit."""
    if kept_image(entry, variant) is not None:
        raise GenerationError("cette variante est déjà gardée comme référence")
    if len(entry.reference_images) >= MAX_KEPT:
        raise GenerationError(
            f"{MAX_KEPT} images de référence au plus par fiche : supprimes-en une avant d'en garder une autre"
        )
    source = files.absolute(variant.path)
    if not source.is_file():
        raise GenerationError("fichier de la variante absent de data/")
    stored = files.save_image(source.read_bytes(), entry_folder(entry))
    sheet_name = str((variant.params or {}).get("sheet_name") or variant.sheet)
    values = {
        "path": stored.path,
        "original_name": f"{sheet_name} · variante {variant.id}{PurePosixPath(stored.path).suffix}"[:255],
        "content_type": stored.content_type,
        "width": stored.width,
        "height": stored.height,
        "position": next_position(entry),
    }
    image: ReferenceImage
    if isinstance(entry, Character):
        image = CharacterImage(**values)
        entry.reference_images.append(image)
    else:
        image = SeriesAssetImage(**values)
        entry.reference_images.append(image)
    try:
        session.flush()
    except Exception:
        files.delete(stored.path)
        raise
    variant.kept_image_id = image.id
    return image


def delete_entry_variants(session: Session, kind: str, entry_id: int) -> list[str]:
    """Supprime l'historique d'une fiche (sans commit) ; renvoie les fichiers à effacer après le commit."""
    rows = list(
        session.scalars(
            select(ReferenceVariant).where(ReferenceVariant.entry_kind == kind, ReferenceVariant.entry_id == entry_id)
        )
    )
    paths = [v.path for v in rows]
    for v in rows:
        session.delete(v)
    return paths


# --- exécution d'un job -------------------------------------------------------------------
@dataclass
class _Plan:
    loaded: LoadedWorkflow
    params: dict[str, Any]
    loras: list[LoraSpec]
    reference: dict[str, Any] | None  # variante de départ d'« Affiner » : {variant_id, filename}
    reference_data: bytes | None
    folder: str


class ReferenceExecutor:
    """Exécute un job `reference` (appelé par la file sérielle de ComfyUI, un à la fois)."""

    def __init__(
        self,
        db: Database,
        presets: PresetRegistry,
        files: FileStore,
        comfyui: ComfyUIClient | None,
        *,
        comfyui_error: str | None = None,
        poll_s: float = 1.0,
        presets_for: Callable[[int | None], PresetRegistry] | None = None,
    ) -> None:
        self.db = db
        self.presets_for = presets_for or (lambda _project_id: presets)
        self.files = files
        self.comfyui = comfyui
        self.comfyui_error = comfyui_error
        self.poll_s = poll_s
        self._prompt_ids: dict[int, str] = {}

    def interrupt(self, job_id: int) -> None:
        prompt_id = self._prompt_ids.get(job_id)
        if self.comfyui is not None and prompt_id is not None:
            self.comfyui.interrupt(prompt_id)

    def _plan(self, job_id: int) -> _Plan:
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            params = dict(job.params or {}) if job is not None else {}
            entry = load_entry(session, str(params.get("entry_kind")), int(params.get("entry_id") or 0))
            if job is None or entry is None:
                raise GenerationError("fiche introuvable (supprimée entre-temps ?)")
            series = session.get(Project, entry.project_id)
            assert series is not None
            presets = self.presets_for(entry.project_id)
            sheet = presets.reference_sheet(str(params.get("sheet")))
            loaded = presets.workflow(str(params.get("preset")))
            reference: dict[str, Any] | None = None
            reference_data: bytes | None = None
            parent_id = params.get("parent_id")
            if parent_id is not None:
                parent = session.get(ReferenceVariant, int(parent_id))
                path = self.files.absolute(parent.path) if parent is not None else None
                if parent is None or path is None or not path.is_file():
                    raise GenerationError("variante de départ introuvable (supprimée entre-temps ?)")
                if not loaded.preset.reference_images:
                    raise GenerationError(f"le workflow {loaded.preset.id} n'accepte pas d'image de référence")
                ext = PurePosixPath(parent.path).suffix or ".png"
                reference = {
                    "variant_id": parent.id,
                    "filename": f"{FOLDERS[entry_kind(entry)][:-1]}{entry.id}_variante{parent.id}{ext}",
                }
                reference_data = path.read_bytes()
            slug = f"{FOLDERS[entry_kind(entry)][:-1]}-{entry.id}"
            prefix = (
                f"mangaka/serie-{entry.project_id}/references/{slug}/{sheet.id}/variante-{params.get('variant', 1)}"
            )
            return _Plan(
                loaded=loaded,
                params=sheet_params(
                    loaded,
                    sheet,
                    str(params.get("prompt") or ""),
                    presets,
                    seed=params.get("seed"),
                    filename_prefix=prefix,
                ),
                loras=sheet_loras(series, entry),
                reference=reference,
                reference_data=reference_data,
                folder=f"{entry_folder(entry)}/variantes",
            )

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        if self.comfyui is None:
            raise GenerationError(f"ComfyUI indisponible : {self.comfyui_error or 'client non configuré'}")
        comfy = self.comfyui
        t0 = time.monotonic()
        report(2, "Préparation du prompt et du workflow…")
        plan = self._plan(job_id)
        preset = plan.loaded.preset

        uploaded: list[str] = []
        if plan.reference is not None and plan.reference_data is not None:
            report(4, "Envoi de la variante de départ à ComfyUI…")
            uploaded.append(
                comfy.upload_image(plan.reference_data, plan.reference["filename"], subfolder=UPLOAD_SUBFOLDER)
            )
        built = build_workflow(plan.loaded, plan.params, reference_images=uploaded, loras=plan.loras)
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
        stored = self.files.save_image(data, plan.folder)
        duration_ms = int((time.monotonic() - t0) * 1000)

        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            params = dict(job.params or {}) if job is not None else {}
            entry = load_entry(session, str(params.get("entry_kind")), int(params.get("entry_id") or 0))
            if job is None or entry is None:
                self.files.delete(stored.path)
                raise GenerationError("fiche supprimée pendant la génération")
            variant = ReferenceVariant(
                project_id=entry.project_id,
                entry_kind=entry_kind(entry),
                entry_id=entry.id,
                job_id=job_id,
                sheet=str(params.get("sheet")),
                path=stored.path,
                content_type=stored.content_type,
                width=stored.width,
                height=stored.height,
                seed=built.params["seed"],
                parent_id=params.get("parent_id"),
                instruction=str(params.get("instruction") or ""),
                params={
                    "sheet_name": params.get("sheet_name"),
                    "preset": preset.id,
                    "preset_name": preset.name,
                    "tier": preset.tier.name if preset.tier else None,
                    "prompt": built.params["positive_prompt"],
                    "negative_prompt": built.params["negative_prompt"],
                    "seed": built.params["seed"],
                    "width": built.params["width"],
                    "height": built.params["height"],
                    "loras": [lo.as_dict() for lo in built.loras],
                    "reference_images": (
                        [{**{k: v for k, v in plan.reference.items() if k != "filename"}, "comfyui_name": uploaded[0]}]
                        if plan.reference is not None
                        else []
                    ),
                    "removed_nodes": built.removed_nodes,
                    "duration_ms": duration_ms,
                    "comfyui_prompt_id": prompt_id,
                    "comfyui": comfy.name,
                },
            )
            session.add(variant)
            session.flush()
            job.params = {**params, "variant_id": variant.id}
            n = session.scalar(
                select(func.count()).where(
                    ReferenceVariant.entry_kind == variant.entry_kind, ReferenceVariant.entry_id == variant.entry_id
                )
            )
            session.commit()
        return f"Variante {params.get('variant', 1)}/{params.get('count', 1)} — {stored.width}×{stored.height}, seed {built.params['seed']} ({n} dans l'historique)"
