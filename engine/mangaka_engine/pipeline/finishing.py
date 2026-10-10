"""Finition d'impression : agrandir la version retenue d'une case jusqu'au dpi cible, avant l'assemblage.

Les cases sont générées à ≈ 1 Mpx : imprimée, une case pleine page A4 sort à ≈ 115 dpi. La finition
agrandit l'image retenue avec un modèle (preset `presets/upscalers/`) — quelques secondes, composition
gardée — au lieu de la régénérer.

- `finish_plan` : facteur **calculé par case** depuis la boîte imprimée (format de page + dpi du format,
  fond perdu compris) et la taille de l'image ; aucun agrandissement si l'image atteint déjà
  `finishing_tolerance` × le dpi cible (defaults.yaml) ;
- `enqueue_finish` : un job `finishing` par case, dans la file sérielle de ComfyUI (une seule
  génération ou finition à la fois) ;
- `FinishingExecutor` : envoie l'image à ComfyUI, construit le workflow du preset (taille finale
  exacte), récupère l'image et la range comme **dérivé** de la version (`PanelImage.finish`) ;
- `drop_finishes` : retenir une autre version d'une case efface la finition des autres versions de
  cette case (et seulement de celle-ci) ;
- `finished_art` : image utilisée par l'assemblage (finalisée si elle existe, sinon la version).

Aucun nom de modèle ici : tout vient des presets.
"""

from __future__ import annotations

import contextlib
import math
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import LoadedUpscaler, PageFormat, PresetError, PresetRegistry, build_upscale_workflow
from ..providers.comfyui import ComfyUIClient, ComfyUIError, ComfyUIInterruptedError, ComfyUITimeoutError
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import Job, JobStatus, Page, Panel, PanelImage, Project
from .generation import UPLOAD_SUBFOLDER, GenerationError
from .jobs import JobReporter

STEP = "finishing"
ACTIVE = (JobStatus.pending, JobStatus.running)


class FinishingError(GenerationError):
    """Erreur lisible (en français) d'une finition."""


# --- calcul du facteur (pur) ---------------------------------------------------------------
def printed_box(bbox: dict[str, Any], fmt: PageFormat) -> tuple[int, int]:
    """Taille imprimée de la case en px au dpi du format, fond perdu compris.

    `bbox` est en px de la page finie ; un bord posé sur un bord de la page (case à fond perdu)
    déborde du fond perdu du format à l'export, comme à l'assemblage.
    """
    bleed = fmt.mm_to_px(fmt.bleed_mm)
    x1, y1, x2, y2 = (int(bbox[k]) for k in ("x1", "y1", "x2", "y2"))
    w = x2 - x1 + (bleed if x1 <= 0 else 0) + (bleed if x2 >= fmt.width_px else 0)
    h = y2 - y1 + (bleed if y1 <= 0 else 0) + (bleed if y2 >= fmt.height_px else 0)
    return max(1, w), max(1, h)


def effective_dpi(image_w: int, image_h: int, box_w: int, box_h: int, dpi: int) -> float:
    """Dpi de l'image une fois posée « au remplissage » dans la boîte (recadrage centré, sans déformation)."""
    return dpi / max(box_w / image_w, box_h / image_h)


@dataclass(frozen=True)
class FinishPlan:
    dpi: float  # dpi effectif de l'image à l'impression
    target_dpi: int  # dpi du format de page
    min_dpi: float  # seuil : en dessous, la case est à finaliser
    factor: float  # agrandissement qui amène l'image au dpi cible
    width: int  # taille finale exacte (image × facteur) : couvre juste la boîte imprimée
    height: int
    needed: bool


def finish_plan(image_w: int, image_h: int, box_w: int, box_h: int, dpi: int, tolerance: float) -> FinishPlan:
    """Facteur nécessaire pour que l'image couvre la boîte imprimée au dpi cible (jamais un facteur fixe)."""
    if image_w <= 0 or image_h <= 0:
        raise FinishingError(f"taille d'image invalide : {image_w}×{image_h}")
    factor = max(box_w / image_w, box_h / image_h)
    current = dpi / factor
    min_dpi = tolerance * dpi
    # Le côté qui fixe le facteur tombe exactement sur la boîte (ceil : jamais 1 px de moins).
    width, height = math.ceil(image_w * factor - 1e-6), math.ceil(image_h * factor - 1e-6)
    return FinishPlan(
        dpi=current,
        target_dpi=dpi,
        min_dpi=min_dpi,
        factor=factor,
        width=width,
        height=height,
        needed=current < min_dpi - 1e-9,
    )


# --- case en base -------------------------------------------------------------------------
def page_format_of(presets: PresetRegistry, page: Page) -> PageFormat:
    return presets.page_format((page.layout or {}).get("page_format") or page.chapter.project.page_format)


def tolerance_of(presets: PresetRegistry) -> float:
    return presets.defaults.finishing_tolerance if presets.defaults else 0.9


def selected_of(panel: Panel) -> PanelImage | None:
    return next((i for i in panel.images if i.selected), None)


def source_size(img: PanelImage, files: FileStore) -> tuple[int, int] | None:
    params = img.params or {}
    w, h = params.get("image_width"), params.get("image_height")
    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
        return w, h
    try:
        with Image.open(files.absolute(img.path)) as im:
            return im.size
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def finished_art(img: PanelImage, files: FileStore) -> tuple[Path, tuple[int, int]] | None:
    """Fichier et taille de l'image finalisée de la version (None : pas de finition utilisable)."""
    finish = img.finish or {}
    rel, w, h = finish.get("path"), finish.get("width"), finish.get("height")
    if not isinstance(rel, str) or not isinstance(w, int) or not isinstance(h, int):
        return None
    path = files.absolute(rel)
    return (path, (w, h)) if path.is_file() else None


def resolve_upscaler(presets: PresetRegistry, project: Project) -> LoadedUpscaler:
    """Agrandisseur de la série, sinon celui de defaults.yaml."""
    if project.upscaler and project.upscaler in presets.upscalers:
        return presets.upscalers[project.upscaler]
    default = presets.default_upscaler
    if default is None:
        raise FinishingError("aucun agrandisseur configuré (upscaler de presets/defaults.yaml ou de la série)")
    return presets.upscalers[default]


def panel_print_info(
    presets: PresetRegistry, files: FileStore, panel: Panel, image: PanelImage | None = None
) -> dict[str, Any] | None:
    """Dpi effectif de la version retenue d'une case (et de sa finition), pour l'atelier et la vue page.

    `status` : `ok` (déjà au dpi cible), `finished` (finalisée au dpi cible), `low` (sous le seuil).
    None : pas de version retenue, pas de géométrie ou format inconnu.
    """
    image = image if image is not None else selected_of(panel)
    bbox = panel.bbox
    if image is None or not bbox or not all(k in bbox for k in ("x1", "y1", "x2", "y2")):
        return None
    size = source_size(image, files)
    if size is None:
        return None
    try:
        fmt = page_format_of(presets, panel.page)
    except PresetError:
        return None
    box_w, box_h = printed_box(bbox, fmt)
    plan = finish_plan(size[0], size[1], box_w, box_h, fmt.dpi, tolerance_of(presets))
    finished = finished_art(image, files)
    finished_dpi = effective_dpi(*finished[1], box_w, box_h, fmt.dpi) if finished else None
    if not plan.needed:
        status = "ok"
    elif finished_dpi is not None and finished_dpi >= plan.min_dpi - 1e-9:
        status = "finished"
    else:
        status = "low"
    finish = image.finish or {}
    return {
        "image_id": image.id,
        "status": status,
        "target_dpi": fmt.dpi,
        "min_dpi": round(plan.min_dpi),
        "box_width": box_w,
        "box_height": box_h,
        "width_mm": round(box_w / fmt.dpi * 25.4, 1),
        "height_mm": round(box_h / fmt.dpi * 25.4, 1),
        "source_width": size[0],
        "source_height": size[1],
        "dpi": round(plan.dpi),
        "factor": round(plan.factor, 3),
        "target_width": plan.width,
        "target_height": plan.height,
        "needed": plan.needed,
        "finished": finished is not None,
        "finished_dpi": round(finished_dpi) if finished_dpi is not None else None,
        "finished_width": finished[1][0] if finished else None,
        "finished_height": finished[1][1] if finished else None,
        "finished_upscaler": finish.get("upscaler_name") if finished else None,
    }


def active_finishing(session: Session, panel_ids: Iterable[int]) -> dict[int, Job]:
    """Finitions en cours ou en attente, par case."""
    ids = list(panel_ids)
    if not ids:
        return {}
    jobs = session.scalars(
        select(Job).where(Job.panel_id.in_(ids), Job.step == STEP, Job.status.in_(ACTIVE)).order_by(Job.id)
    )
    out: dict[int, Job] = {}
    for job in jobs:
        if job.panel_id is not None:
            out.setdefault(job.panel_id, job)
    return out


def enqueue_finish(session: Session, presets: PresetRegistry, files: FileStore, panel: Panel) -> Job:
    """Met en file la finition de la version retenue de la case (sans commit).

    Lève `FinishingError` si rien n'est à faire : pas de version retenue, déjà au dpi cible, déjà
    finalisée, ou finition déjà en file.
    """
    label = f"case {panel.index + 1} de la page {panel.page.number}"
    image = selected_of(panel)
    if image is None:
        raise FinishingError(f"{label} : aucune version retenue à finaliser")
    info = panel_print_info(presets, files, panel, image)
    if info is None:
        raise FinishingError(f"{label} : pas de mise en page ou image illisible, dpi impossible à calculer")
    if info["status"] == "ok":
        raise FinishingError(f"{label} : déjà à {info['dpi']} dpi, aucun agrandissement nécessaire")
    if info["status"] == "finished":
        raise FinishingError(f"{label} : déjà finalisée ({info['finished_dpi']} dpi)")
    if active_finishing(session, [panel.id]):
        raise FinishingError(f"{label} : finition déjà en file")
    upscaler = resolve_upscaler(presets, panel.page.chapter.project)
    chapter = panel.page.chapter
    job = Job(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        panel_id=panel.id,
        step=STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={
            "image_id": image.id,
            "version": image.version,
            "upscaler": upscaler.preset.id,
            "upscaler_name": upscaler.preset.name,
            "source_dpi": info["dpi"],
            "target_dpi": info["target_dpi"],
            "factor": info["factor"],
            "width": info["target_width"],
            "height": info["target_height"],
        },
    )
    session.add(job)
    return job


def enqueue_pages(
    session: Session, presets_for: Callable[[int | None], PresetRegistry], files: FileStore, pages: Iterable[Page]
) -> tuple[list[Job], int]:
    """« Finaliser la page / le chapitre » : finitions des cases sous le seuil ; renvoie (jobs, cases ignorées)."""
    jobs: list[Job] = []
    skipped = 0
    for page in pages:
        presets = presets_for(page.chapter.project_id)
        busy = active_finishing(session, [p.id for p in page.panels])
        for panel in page.panels:
            info = panel_print_info(presets, files, panel)
            if info is None or info["status"] != "low" or panel.id in busy:
                skipped += 1
                continue
            jobs.append(enqueue_finish(session, presets, files, panel))
    return jobs, skipped


def drop_finishes(files: FileStore, panel: Panel, keep_image_id: int | None) -> int:
    """Efface la finition des versions de la case autres que `keep_image_id` (fichiers compris)."""
    dropped = 0
    for img in panel.images:
        if img.id != keep_image_id and img.finish:
            path = (img.finish or {}).get("path")
            if isinstance(path, str):
                files.delete(path)
            img.finish = None
            dropped += 1
    return dropped


# --- exécution d'un job --------------------------------------------------------------------
@dataclass
class _Plan:
    loaded: LoadedUpscaler
    image_id: int
    panel_id: int
    panel_index: int
    data: bytes
    filename: str
    folder: str
    prefix: str
    box: tuple[int, int]
    source: tuple[int, int]
    dpi: int
    source_dpi: int
    width: int
    height: int
    factor: float


class FinishingExecutor:
    """Exécute un job `finishing` (appelé par la file sérielle, un à la fois)."""

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
        self.files = files
        self.comfyui = comfyui
        self.comfyui_error = comfyui_error
        self.poll_s = poll_s
        self.presets_for = presets_for or (lambda _project_id: presets)
        self._prompt_ids: dict[int, str] = {}

    def interrupt(self, job_id: int) -> None:
        prompt_id = self._prompt_ids.get(job_id)
        if self.comfyui is not None and prompt_id is not None:
            self.comfyui.interrupt(prompt_id)

    def _plan(self, job_id: int) -> _Plan | str:
        """Ce qu'il faut agrandir, ou le message final si plus rien n'est à faire."""
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            image = session.get(PanelImage, (job.params or {}).get("image_id")) if job is not None else None
            if job is None or image is None:
                raise FinishingError("version introuvable (supprimée entre-temps ?)")
            if not image.selected:
                raise FinishingError("la version retenue a changé depuis la demande : relance « Finaliser »")
            panel = image.panel
            page = panel.page
            chapter = page.chapter
            presets = self.presets_for(chapter.project_id)
            info = panel_print_info(presets, self.files, panel, image)
            if info is None:
                raise FinishingError("pas de mise en page ou image illisible : dpi impossible à calculer")
            if info["status"] == "ok":
                return f"Déjà à {info['dpi']} dpi : aucun agrandissement nécessaire"
            if info["status"] == "finished":
                return f"Déjà finalisée ({info['finished_dpi']} dpi)"
            wanted = str((job.params or {}).get("upscaler") or "")
            loaded = presets.upscalers.get(wanted) or resolve_upscaler(presets, chapter.project)
            path = self.files.absolute(image.path)
            if not path.is_file():
                raise FinishingError(f"fichier de la version absent de data/ ({image.path})")
            ext = PurePosixPath(image.path).suffix or ".png"
            return _Plan(
                loaded=loaded,
                image_id=image.id,
                panel_id=panel.id,
                panel_index=panel.index,
                data=path.read_bytes(),
                filename=f"finition_case{panel.id}_v{image.version}{ext}",
                folder=f"projects/{chapter.project_id}/chapters/{chapter.id}/panels/{panel.id}/finitions",
                prefix=(
                    f"mangaka/serie-{chapter.project_id}/chapitre-{chapter.number}/page-{page.number}"
                    f"/finition-case-{panel.index + 1}"
                ),
                box=(info["box_width"], info["box_height"]),
                source=(info["source_width"], info["source_height"]),
                dpi=info["target_dpi"],
                source_dpi=info["dpi"],
                width=info["target_width"],
                height=info["target_height"],
                factor=info["factor"],
            )

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        if self.comfyui is None:
            raise FinishingError(f"ComfyUI indisponible : {self.comfyui_error or 'client non configuré'}")
        comfy = self.comfyui
        t0 = time.monotonic()
        report(2, "Préparation de la finition…")
        plan = self._plan(job_id)
        if isinstance(plan, str):
            return plan
        preset = plan.loaded.preset
        report(5, "Envoi de la version retenue à ComfyUI…")
        uploaded = comfy.upload_image(plan.data, plan.filename, subfolder=UPLOAD_SUBFOLDER)
        built = build_upscale_workflow(plan.loaded, uploaded, plan.width, plan.height, filename_prefix=plan.prefix)
        if cancel.is_set():
            raise ComfyUIInterruptedError("finition annulée")

        report(8, f"Agrandissement « {preset.name} » ×{plan.factor:.2f} → {plan.width}×{plan.height}…")
        prompt_id = comfy.queue_prompt(built.workflow)
        self._prompt_ids[job_id] = prompt_id
        last = [-1]

        def on_progress(value: int, maximum: int) -> None:
            pct = 10 + int(80 * value / maximum)
            if pct != last[0]:
                last[0] = pct
                report(pct, f"Agrandissement : étape {value}/{maximum}")

        try:
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
            raise FinishingError(
                f"ComfyUI n'a pas terminé l'agrandissement en {preset.timeout_s:.0f} s "
                f"(délai réglable : timeout_s de presets/upscalers/{preset.id}.yaml)"
            ) from None
        finally:
            self._prompt_ids.pop(job_id, None)

        report(92, "Récupération de l'image agrandie…")
        stored = self.files.save_image(comfy.fetch_image(refs[0]), plan.folder)
        dpi_after = round(effective_dpi(stored.width, stored.height, *plan.box, plan.dpi))
        with self.db.session_scope() as session:
            image = session.get(PanelImage, plan.image_id)
            if image is None or not image.selected:
                self.files.delete(stored.path)
                raise FinishingError("la version retenue a changé pendant la finition : résultat écarté")
            old = (image.finish or {}).get("path")
            image.finish = {
                "path": stored.path,
                "width": stored.width,
                "height": stored.height,
                "content_type": stored.content_type,
                "upscaler": preset.id,
                "upscaler_name": preset.name,
                "factor": round(plan.factor, 3),
                "source_width": plan.source[0],
                "source_height": plan.source[1],
                "target_dpi": plan.dpi,
                "dpi": dpi_after,
                "job_id": job_id,
                "comfyui": comfy.name,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "created_at": datetime.now(UTC).isoformat(),
            }
            session.commit()
        if isinstance(old, str) and old != stored.path:
            self.files.delete(old)
        return (
            f"Case {plan.panel_index + 1} finalisée — {stored.width}×{stored.height}, "
            f"{plan.source_dpi} → {dpi_after} dpi ({preset.name})"
        )
