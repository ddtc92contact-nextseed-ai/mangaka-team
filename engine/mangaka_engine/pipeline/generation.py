"""Étape 3 — génération des cases via ComfyUI, une à la fois.

- `enqueue_panel` : prépare le prompt final, choisit le workflow et crée `count` jobs
  `generation` (variantes) en attente ;
- `GenerationExecutor` : exécuté par la file sérielle (`pipeline/queue.py`) pour un job :
  envoi des images de référence, construction du workflow (références + LoRA via le preset),
  file ComfyUI, progression, récupération de l'image → nouvelle `PanelImage` (version n+1) ;
- `refresh_states` : états des cases et des pages (queued → generating → review, puis selon le
  verdict QC de la version choisie : approved / flagged ; `qc` pendant un contrôle).

Aucun nom de modèle, de LoRA ni de nœud ici : tout vient des presets et des fiches.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..presets import LoadedWorkflow, LoraSpec, PresetError, PresetRegistry, build_workflow
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
    Chapter,
    ChapterStatus,
    Character,
    CharacterImage,
    Job,
    JobStatus,
    Page,
    PageState,
    Panel,
    PanelImage,
    PanelState,
    QCVerdict,
)
from .art_direction import applied_panel_direction
from .jobs import JobReporter
from .knowledge import KnowledgeBase
from .layout import target_size
from .prompt import PromptCharacter, build_negative_prompt, build_prompt

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


def panel_knowledge(
    session: Session, knowledge: KnowledgeBase | None, panel: Panel, characters: Sequence[Character]
) -> tuple[str, str]:
    """($savoir_faire, $bible) du prompt image ; une panne du savoir-faire ne bloque jamais une génération."""
    if knowledge is None:
        return "", ""
    query = " ".join(p for p in (panel.shot_type or "", panel.description, *(c.name for c in characters)) if p)
    try:
        return knowledge.for_panel(session, panel.page.chapter.project_id, query, [c.id for c in characters])
    except Exception:  # noqa: BLE001 — le prompt se construit sans notes plutôt que d'échouer
        log.warning("savoir-faire indisponible pour le prompt de la case %s", panel.id, exc_info=True)
        return "", ""


def build_panel_prompt(
    presets: PresetRegistry,
    panel: Panel,
    characters: Sequence[Character],
    notes: tuple[str, str] = ("", ""),
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
        characters=[PromptCharacter(c.name, c.visual_description, tuple(c.prompt_keywords or [])) for c in characters],
        style=series.style,
        savoir_faire=savoir_faire,
        bible=bible,
        settings=presets.image_prompt,
    )


def resolve_preset_id(
    presets: PresetRegistry, panel: Panel, characters: Sequence[Character], requested: str | None = None
) -> str:
    """Demande > preset de la case > workflow « avec références » si besoin > workflow de la série.

    Le workflow « avec références » est celui du palier de la série (`with_references` de son
    preset) ; `defaults.workflow_with_references` ne sert qu'aux presets qui n'en déclarent pas.
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


def pick_references(characters: Sequence[Character], slots: int) -> list[tuple[Character, CharacterImage]]:
    """Remplit les emplacements à tour de rôle : 1re image de chaque personnage, puis 2e…"""
    out: list[tuple[Character, CharacterImage]] = []
    depth = 0
    while len(out) < slots and any(depth < len(c.reference_images) for c in characters):
        for c in characters:
            if depth < len(c.reference_images) and len(out) < slots:
                out.append((c, c.reference_images[depth]))
        depth += 1
    return out


def collect_loras(panel: Panel, characters: Sequence[Character]) -> list[LoraSpec]:
    """LoRA de style de la série puis LoRA d'identité de chaque personnage, dans l'ordre."""
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
        characters = panel_characters(session, panel)
        notes = panel_knowledge(session, knowledge, panel, characters)
        panel.final_prompt = build_panel_prompt(presets, panel, characters, notes)
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
    characters = panel_characters(session, panel)
    preset_id = resolve_preset_id(presets, panel, characters, preset)
    presets.workflow(preset_id)  # PresetError si inconnu
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
                **(extra_params or {}),
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
        n_images = session.scalar(select(func.count()).where(PanelImage.panel_id == panel.id)) or 0
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
        with_images = set(session.scalars(select(PanelImage.panel_id).where(PanelImage.panel_id.in_(ids)).distinct()))
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
    references: list[tuple[int, int, str, bytes]]  # (personnage, image, nom de fichier, contenu)
    loras: list[LoraSpec]
    folder: str
    prompt: str
    panel_id: int


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
            characters = panel_characters(session, panel)
            presets = self.presets_for(chapter.project_id)
            preset_id = str(job.params.get("preset") or resolve_preset_id(presets, panel, characters))
            loaded = presets.workflow(preset_id)
            prompt = update_panel_prompt(presets, session, panel, self.knowledge)
            size = panel_target(presets, page, panel)
            if size is None:
                raise GenerationError(f"la page {page.number} n'est pas mise en page")
            references: list[tuple[int, int, str, bytes]] = []
            for character, image in pick_references(characters, len(loaded.preset.reference_images)):
                path = self.files.absolute(image.path)
                if not path.is_file():
                    raise GenerationError(f"image de référence de {character.name} absente de data/ ({image.path})")
                ext = PurePosixPath(image.path).suffix or ".png"
                references.append(
                    (character.id, image.id, f"perso{character.id}_img{image.id}{ext}", path.read_bytes())
                )
            params: dict[str, Any] = {
                "positive_prompt": prompt,
                "negative_prompt": build_negative_prompt(
                    str(loaded.preset.defaults.get("negative_prompt", "")), presets.image_prompt
                ),
                "seed": job.params.get("seed"),
                **size,
            }
            if "filename_prefix" in loaded.preset.mapping:
                params["filename_prefix"] = (
                    f"mangaka/serie-{chapter.project_id}/chapitre-{chapter.number}/page-{page.number}"
                    f"/case-{panel.index + 1}"
                )
            plan = _Plan(
                loaded=loaded,
                params=params,
                references=references,
                loras=collect_loras(panel, characters),
                folder=f"projects/{chapter.project_id}/chapters/{chapter.id}/panels/{panel.id}",
                prompt=prompt,
                panel_id=panel.id,
            )
            session.commit()  # prompt final éventuellement reconstruit
            return plan

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
        for i, (_, _, filename, data) in enumerate(plan.references, start=1):
            report(4, f"Envoi de l'image de référence {i}/{len(plan.references)} à ComfyUI…")
            uploaded.append(comfy.upload_image(data, filename, subfolder=UPLOAD_SUBFOLDER))
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
            image = PanelImage(
                panel_id=panel.id,
                version=version,
                path=stored.path,
                seed=built.params["seed"],
                selected=has_selected is None,  # la première version est choisie d'office
                params={
                    "preset": preset.id,
                    "preset_name": preset.name,
                    "prompt": built.params["positive_prompt"],
                    "negative_prompt": built.params["negative_prompt"],
                    "seed": built.params["seed"],
                    "width": built.params["width"],
                    "height": built.params["height"],
                    "workflow_params": built.params,
                    "loras": [lo.as_dict() for lo in built.loras],
                    "reference_images": [
                        {"character_id": cid, "image_id": iid, "comfyui_name": name}
                        for (cid, iid, _, _), name in zip(plan.references, uploaded, strict=True)
                    ],
                    "removed_nodes": built.removed_nodes,
                    "image_width": stored.width,
                    "image_height": stored.height,
                    "content_type": stored.content_type,
                    "duration_ms": duration_ms,
                    "job_id": job_id,
                    "comfyui_prompt_id": prompt_id,
                    "comfyui": comfy.name,
                },
            )
            session.add(image)
            session.flush()
            job = session.get(Job, job_id)
            if self.on_generated is not None and job is not None:
                try:
                    self.on_generated(session, job, image)
                except Exception:  # noqa: BLE001 — la version est gardée même si le QC ne peut être mis en file
                    log.exception("job %s : mise en file du contrôle qualité impossible", job_id)
            session.commit()
        return f"Version {version} — {stored.width}×{stored.height}, seed {built.params['seed']}"
