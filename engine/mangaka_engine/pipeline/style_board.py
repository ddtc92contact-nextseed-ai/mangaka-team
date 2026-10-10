"""Planche de style d'une série : voir le style avant de lancer la série, puis le tenir d'une page à l'autre.

1. **Essais** (`enqueue_trials`) : `style_board.trials` jobs (4) au palier croquis (`defaults.workflow_sketch`)
   d'une **scène test** du genre (`scene_test` de presets/style_genres/, jamais de texte libre), avec le
   `$style` de la série et une graine différente par essai. Chaque essai est une `ReferenceVariant`
   (`entry_kind = style`, `entry_id` = id de la série) : « Relancer » en ajoute 4 autres, l'historique reste.
2. **Choix** (`enqueue_choice`) : l'essai retenu passe au propre (`from_sketch` du palier de la série,
   image → image depuis l'essai, même graine, même prompt) ; le résultat devient la **référence de
   style** de la série : un `SeriesAsset` de sorte `style`, seul actif (`activate`), les précédents gardés
   en historique.
3. **Utilisation** (`style_board` de defaults.yaml) : jointe aux fiches de référence
   (`pipeline/reference_sheets.py`) et, s'il reste un emplacement libre, aux cases
   (`pipeline/generation.py`, `pick_references`).

Tous les jobs passent par la file ComfyUI unique (étape `style_board`), visibles dans la file de production.
Aucun nom de modèle ni de nœud ici : tout vient des presets.
"""

from __future__ import annotations

import contextlib
import random
import string
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..presets import LoadedWorkflow, LoraSpec, PresetRegistry, build_workflow
from ..presets.schemas import StyleBoardSettings
from ..providers.comfyui import ComfyUIClient, ComfyUIError, ComfyUIInterruptedError, ComfyUITimeoutError
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import AssetKind, Job, JobStatus, Project, ReferenceVariant, SeriesAsset, SeriesAssetImage
from .generation import UPLOAD_SUBFOLDER, GenerationError, sketch_size
from .jobs import JobReporter
from .prompt import build_negative_prompt
from .style import series_style, style_names

STEP = "style_board"
ACTIVE = (JobStatus.pending, JobStatus.running)
ENTRY_KIND = "style"  # ReferenceVariant.entry_kind d'un essai (entry_id = id de la série)
SHEET = "planche-de-style"  # ReferenceVariant.sheet d'un essai
MAX_SEED = 2**31 - 1


def board_settings(presets: PresetRegistry) -> StyleBoardSettings:
    settings = presets.defaults.style_board if presets.defaults else None
    if settings is None:
        raise GenerationError("aucune planche de style configurée (style_board de presets/defaults.yaml)")
    return settings


def style_folder(project_id: int) -> str:
    return f"projects/{project_id}/style"


# --- lecture ------------------------------------------------------------------------------
def style_assets(session: Session, project_id: int) -> list[SeriesAsset]:
    """Références de style de la série, la plus récente d'abord (l'active et l'historique)."""
    return list(
        session.scalars(
            select(SeriesAsset)
            .where(SeriesAsset.project_id == project_id, SeriesAsset.kind == AssetKind.style)
            .options(selectinload(SeriesAsset.reference_images))
            .order_by(SeriesAsset.id.desc())
        )
    )


def trials(session: Session, project_id: int) -> list[ReferenceVariant]:
    """Essais de la planche de style, les plus récents d'abord."""
    return list(
        session.scalars(
            select(ReferenceVariant)
            .where(ReferenceVariant.entry_kind == ENTRY_KIND, ReferenceVariant.entry_id == project_id)
            .order_by(ReferenceVariant.id.desc())
        )
    )


def active_jobs(session: Session, project_id: int) -> list[Job]:
    """Essais et passages au propre en cours ou en attente pour la série, dans l'ordre de la file."""
    return list(
        session.scalars(
            select(Job).where(Job.step == STEP, Job.status.in_(ACTIVE), Job.project_id == project_id).order_by(Job.id)
        )
    )


def scene_test(presets: PresetRegistry, series: Project) -> str | None:
    genre = presets.style_genres.get(series.style_genre or "")
    return genre.scene_test if genre is not None else None


# --- préparation (pur) --------------------------------------------------------------------
def _clean(text: str | None) -> str:
    return " ".join((text or "").split()).rstrip(" .;,:")


def board_prompt(settings: StyleBoardSettings, scene: str, style: str) -> str:
    """Prompt des essais : morceaux du preset, un morceau dont une variable est vide est omis."""
    values = {"scene": _clean(scene), "style": _clean(style)}
    parts: list[str] = []
    for part in settings.prompt:
        tpl = string.Template(part)
        if any(not values[v] for v in tpl.get_identifiers()):
            continue
        parts.append(tpl.substitute(values).strip())
    return " ".join(p for p in parts if p)


def board_loras(series: Project) -> list[LoraSpec]:
    """LoRA de style de la série seulement (aucun personnage dans la scène test)."""
    if not series.style_lora_name:
        return []
    return [LoraSpec(series.style_lora_name, series.style_lora_weight, "style")]


def sketch_preset(presets: PresetRegistry) -> LoadedWorkflow:
    """Palier croquis des essais (`defaults.workflow_sketch`, texte → image, sans référence)."""
    sketch_id = presets.defaults.workflow_sketch if presets.defaults else None
    loaded = presets.workflows.get(sketch_id) if sketch_id else None
    if loaded is None:
        raise GenerationError("aucun palier croquis configuré (workflow_sketch de presets/defaults.yaml)")
    return loaded


def clean_preset(presets: PresetRegistry, series: Project) -> LoadedWorkflow:
    """Passage au propre de l'essai retenu : `from_sketch` du palier de la série (image → image)."""
    base = presets.workflows.get(series.workflow_preset)
    if base is None:
        raise GenerationError(f"workflow inconnu : « {series.workflow_preset} »")
    clean = presets.workflows.get(base.preset.from_sketch or "")
    if clean is None:
        tier = base.preset.tier.name if base.preset.tier else base.preset.id
        raise GenerationError(f"le palier {tier} ({base.preset.id}) ne propose pas de passage au propre (from_sketch)")
    return clean


def trial_size(presets: PresetRegistry, settings: StyleBoardSettings, loaded: LoadedWorkflow) -> dict[str, int]:
    """Taille d'un essai : ratio de la planche, grand côté `long_side` du palier croquis."""
    full = {"width": settings.width, "height": settings.height}
    if not loaded.preset.long_side:
        return full
    return sketch_size(full, loaded.preset.long_side, presets.layout.generation.multiple)


def distinct_seeds(count: int, rng: random.Random | None = None) -> list[int]:
    return (rng or random.SystemRandom()).sample(range(1, MAX_SEED), count)


# --- mise en file -------------------------------------------------------------------------
def enqueue_trials(
    session: Session, presets: PresetRegistry, series: Project, *, seeds: list[int] | None = None
) -> list[Job]:
    """Crée les jobs d'essai en attente (sans commit) : même prompt, une graine distincte par essai."""
    settings = board_settings(presets)
    scene = scene_test(presets, series)
    if scene is None:
        raise GenerationError("choisis d'abord le genre, le rendu et le ton de la série (Paramètres)")
    loaded = sketch_preset(presets)
    style = series_style(presets, series)
    prompt = board_prompt(settings, scene, style)
    seeds = seeds if seeds is not None else distinct_seeds(settings.trials)
    if len(seeds) != settings.trials or len(set(seeds)) != len(seeds):
        raise GenerationError(f"{settings.trials} graines distinctes attendues")
    size = trial_size(presets, settings, loaded)
    # Numéro de la série d'essais : après les essais déjà faits et ceux encore en file.
    used = [(v.params or {}).get("batch") for v in trials(session, series.id)]
    used += [(j.params or {}).get("batch") for j in active_jobs(session, series.id)]
    batch = max((b for b in used if isinstance(b, int)), default=0) + 1
    jobs: list[Job] = []
    for i, seed in enumerate(seeds):
        job = Job(
            project_id=series.id,
            step=STEP,
            status=JobStatus.pending,
            message="En attente…",
            params={
                "mode": "trial",
                "batch": batch,
                "variant": i + 1,
                "count": len(seeds),
                "preset": loaded.preset.id,
                "tier": loaded.preset.tier.name if loaded.preset.tier else None,
                "prompt": prompt,
                "style": style,
                "style_names": style_names(presets, series),
                "scene": scene,
                "seed": seed,
                **size,
            },
        )
        session.add(job)
        jobs.append(job)
    return jobs


def enqueue_choice(session: Session, presets: PresetRegistry, series: Project, trial: ReferenceVariant) -> Job:
    """L'essai retenu passe au propre (sans commit) ; à la fin du job, il devient la référence de style."""
    settings = board_settings(presets)
    if trial.entry_kind != ENTRY_KIND or trial.entry_id != series.id:
        raise GenerationError("cet essai n'appartient pas à la planche de style de cette série")
    loaded = clean_preset(presets, series)
    denoise = series.sketch_denoise
    if denoise is None:
        value = loaded.preset.defaults.get("denoise")
        denoise = float(value) if isinstance(value, int | float) else None
    params = trial.params or {}
    job = Job(
        project_id=series.id,
        step=STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={
            "mode": "clean",
            "trial_id": trial.id,
            "variant": params.get("variant"),
            "batch": params.get("batch"),
            "preset": loaded.preset.id,
            "tier": loaded.preset.tier.name if loaded.preset.tier else None,
            "prompt": params.get("prompt") or "",
            "style": params.get("style") or series_style(presets, series),
            "style_names": params.get("style_names") or style_names(presets, series),
            "scene": params.get("scene"),
            "seed": trial.seed,
            "denoise": denoise,
            "width": settings.width,
            "height": settings.height,
        },
    )
    session.add(job)
    return job


def activate(session: Session, project_id: int, asset: SeriesAsset) -> None:
    """Fait de `asset` la seule référence de style active de la série (sans commit)."""
    for other in style_assets(session, project_id):
        other.active = other.id == asset.id
    asset.active = True


# --- exécution d'un job -------------------------------------------------------------------
@dataclass
class _Plan:
    mode: str
    loaded: LoadedWorkflow
    params: dict[str, Any]
    loras: list[LoraSpec]
    source: dict[str, Any] | None  # essai retenu (passage au propre) : {trial_id, filename}
    source_data: bytes | None
    project_id: int


class StyleBoardExecutor:
    """Exécute un job `style_board` (appelé par la file sérielle de ComfyUI, un à la fois)."""

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
            series = session.get(Project, job.project_id) if job is not None and job.project_id else None
            if job is None or series is None:
                raise GenerationError("série introuvable (supprimée entre-temps ?)")
            params = dict(job.params or {})
            presets = self.presets_for(series.id)
            settings = board_settings(presets)
            loaded = presets.workflow(str(params.get("preset")))
            mode = str(params.get("mode") or "trial")
            source: dict[str, Any] | None = None
            source_data: bytes | None = None
            if mode == "clean":
                trial = session.get(ReferenceVariant, int(params.get("trial_id") or 0))
                path = self.files.absolute(trial.path) if trial is not None else None
                if trial is None or trial.entry_kind != ENTRY_KIND or path is None or not path.is_file():
                    raise GenerationError("essai introuvable (supprimé entre-temps ?)")
                ext = PurePosixPath(trial.path).suffix or ".png"
                source = {"trial_id": trial.id, "filename": f"style_serie{series.id}_essai{trial.id}{ext}"}
                source_data = path.read_bytes()
            base_negative = str(loaded.preset.defaults.get("negative_prompt", ""))
            negative = ", ".join(t for t in (base_negative.strip(), settings.negative_prompt.strip()) if t)
            wf_params: dict[str, Any] = {
                "positive_prompt": str(params.get("prompt") or ""),
                "negative_prompt": build_negative_prompt(negative, presets.image_prompt),
                "seed": params.get("seed"),
                "width": int(params.get("width") or settings.width),
                "height": int(params.get("height") or settings.height),
            }
            if mode == "clean" and params.get("denoise") is not None and "denoise" in loaded.preset.mapping:
                wf_params["denoise"] = float(params["denoise"])
            if "filename_prefix" in loaded.preset.mapping:
                name = f"essai-{params.get('batch')}-{params.get('variant')}" if mode == "trial" else "reference"
                wf_params["filename_prefix"] = f"mangaka/serie-{series.id}/planche-de-style/{name}"
            return _Plan(
                mode=mode,
                loaded=loaded,
                params=wf_params,
                loras=board_loras(series),
                source=source,
                source_data=source_data,
                project_id=series.id,
            )

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        if self.comfyui is None:
            raise GenerationError(f"ComfyUI indisponible : {self.comfyui_error or 'client non configuré'}")
        comfy = self.comfyui
        t0 = time.monotonic()
        report(2, "Préparation du prompt et du workflow…")
        plan = self._plan(job_id)
        preset = plan.loaded.preset

        source_name: str | None = None
        if plan.source is not None and plan.source_data is not None:
            report(4, "Envoi de l'essai retenu à ComfyUI…")
            source_name = comfy.upload_image(plan.source_data, plan.source["filename"], subfolder=UPLOAD_SUBFOLDER)
        built = build_workflow(plan.loaded, plan.params, loras=plan.loras, source_image=source_name)
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
        folder = style_folder(plan.project_id) + ("/essais" if plan.mode == "trial" else "")
        stored = self.files.save_image(data, folder)
        record = {
            "preset": preset.id,
            "preset_name": preset.name,
            "tier": preset.tier.name if preset.tier else None,
            "prompt": built.params["positive_prompt"],
            "negative_prompt": built.params["negative_prompt"],
            "seed": built.params["seed"],
            "width": built.params.get("width", stored.width),
            "height": built.params.get("height", stored.height),
            "loras": [lo.as_dict() for lo in built.loras],
            "removed_nodes": built.removed_nodes,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "comfyui_prompt_id": prompt_id,
            "comfyui": comfy.name,
        }

        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            series = session.get(Project, plan.project_id)
            if job is None or series is None:
                self.files.delete(stored.path)
                raise GenerationError("série supprimée pendant la génération")
            params = dict(job.params or {})
            if plan.mode == "trial":
                message = self._save_trial(session, job, params, stored, record)
            else:
                message = self._save_reference(session, job, params, series, stored, record, source_name)
            session.commit()
        return message

    def _save_trial(self, session: Session, job: Job, params: dict[str, Any], stored: Any, record: dict) -> str:
        variant = ReferenceVariant(
            project_id=job.project_id,
            entry_kind=ENTRY_KIND,
            entry_id=job.project_id,
            job_id=job.id,
            sheet=SHEET,
            path=stored.path,
            content_type=stored.content_type,
            width=stored.width,
            height=stored.height,
            seed=record["seed"],
            params={
                **record,
                "sheet_name": "Planche de style",
                "batch": params.get("batch"),
                "variant": params.get("variant"),
                "count": params.get("count"),
                "style": params.get("style"),
                "style_names": params.get("style_names"),
                "scene": params.get("scene"),
            },
        )
        session.add(variant)
        session.flush()
        job.params = {**params, "trial_id": variant.id}
        return (
            f"Essai {params.get('variant', 1)}/{params.get('count', 1)} — {stored.width}×{stored.height}, "
            f"seed {record['seed']}"
        )

    def _save_reference(
        self,
        session: Session,
        job: Job,
        params: dict[str, Any],
        series: Project,
        stored: Any,
        record: dict,
        source_name: str | None,
    ) -> str:
        trial = session.get(ReferenceVariant, int(params.get("trial_id") or 0))
        label = f"essai {params.get('variant')} de la série d'essais {params.get('batch')}"
        asset = SeriesAsset(
            project_id=series.id,
            kind=AssetKind.style,
            name=f"Planche de style · {params.get('style_names') or series.title}"[:120],
            # `$style` au moment des essais : la fiche série signale une référence d'un autre style.
            visual_description=str(params.get("style") or ""),
            prompt_keywords=[],
            active=True,
        )
        session.add(asset)
        session.flush()
        image = SeriesAssetImage(
            asset_id=asset.id,
            path=stored.path,
            original_name=f"Planche de style · {label}{PurePosixPath(stored.path).suffix}"[:255],
            content_type=stored.content_type,
            width=stored.width,
            height=stored.height,
            position=0,
        )
        session.add(image)
        session.flush()
        activate(session, series.id, asset)
        if trial is not None:
            trial.kept_image_id = image.id
        job.params = {**params, "asset_id": asset.id, "image_id": image.id, "result": record, "source": source_name}
        return f"Référence de style — {stored.width}×{stored.height}, seed {record['seed']} ({label})"
