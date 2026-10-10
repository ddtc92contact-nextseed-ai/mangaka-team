"""Verrouillage de composition : ControlNet Union de Qwen-Image (patch de modèle) depuis une image guide.

1. **Verrouiller** (`lock_composition`) : la case retient une image guide — son croquis validé, une de
   ses versions, ou une image importée par l'auteur (croquis à la main, photo de pose) — un type de
   contrôle (trait, profondeur, pose…) et une force. Un aperçu de la carte de contrôle est mis en file
   (job `control_map` : image guide → prétraitement → carte, sans modèle ni échantillonneur).
2. **Générer** : tant que la case est verrouillée, toute génération d'un palier passe par son pendant
   ControlNet (`with_control`, voir `pipeline/generation.py`), avec l'image guide du verrou.
3. **Déverrouiller** : la case retrouve une composition libre (les versions déjà produites gardent la
   trace de leur source dans `params.composition`).

Disponibilité (`ControlCatalog`) : les nœuds `ModelPatchLoader` / `QwenImageDiffsynthControlnet`, le
fichier du patch et les prétraitements doivent figurer dans `/object_info` ; sinon un message clair
est renvoyé et l'atelier masque le verrouillage. Le ComfyUI factice (mock) a tout.

Aucun nom de nœud ni de fichier ici : tout vient des presets (bloc `control`).
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..presets import PresetRegistry, build_control_map_workflow
from ..presets.schemas import ControlSettings
from ..providers.comfyui import ComfyUIClient, ComfyUIError, ComfyUIInterruptedError, ComfyUITimeoutError
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import ImageKind, Job, JobStatus, Panel, PanelImage
from .comfy_check import check_control
from .generation import (
    UPLOAD_SUBFOLDER,
    GenerationError,
    control_variant,
    guide_image,
    panel_cast,
    panel_target,
    resolve_preset_id,
)
from .jobs import JobReporter

STEP = "control_map"
SOURCES = ("croquis", "version", "import")
SOURCE_LABELS = {"croquis": "croquis", "version": "version", "import": "image importée"}
PREVIEW_TIMEOUT_S = 300.0
CACHE_TTL_S = 30.0
ERROR_TTL_S = 5.0


# --- disponibilité ----------------------------------------------------------------------------
def fetch_control(client: ComfyUIClient, presets: PresetRegistry) -> dict[str, Any]:
    """Verrouillage disponible ? (nœuds, fichier du patch, prétraitements dans `/object_info`)."""
    if client.name == "mock":
        return {**check_control(presets, None), "provider": client.name, "simulated": True, "error": None}
    try:
        info = client.object_info()
    except ComfyUIError as exc:
        report = check_control(presets, {})
        return {
            **report,
            "available": False,
            "message": f"Verrouillage de composition indisponible : ComfyUI ne répond pas ({exc}).",
            "provider": client.name,
            "simulated": False,
            "error": str(exc),
        }
    return {**check_control(presets, info), "provider": client.name, "simulated": False, "error": None}


def unavailable_control(provider: str, error: str) -> dict[str, Any]:
    return {
        "available": False,
        "problems": [],
        "message": f"Verrouillage de composition indisponible : {error}.",
        "default_type": None,
        "default_strength": None,
        "types": [],
        "provider": provider,
        "simulated": False,
        "error": error,
    }


class ControlCatalog:
    """Cache court de `fetch_control` (un seul ComfyUI par moteur) ; vidé par « Tester la connexion »."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._value: dict[str, Any] | None = None
        self._expires = 0.0

    def get(self, client: ComfyUIClient, presets: PresetRegistry, *, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if not refresh and self._value is not None and self._clock() < self._expires:
                return self._value
            value = fetch_control(client, presets)
            self._value = value
            self._expires = self._clock() + (CACHE_TTL_S if value["error"] is None else ERROR_TTL_S)
            return value

    def store(self, value: dict[str, Any]) -> None:
        with self._lock:
            self._value = value
            self._expires = self._clock() + CACHE_TTL_S

    def clear(self) -> None:
        with self._lock:
            self._value = None


def type_problem(availability: dict[str, Any], type_id: str) -> str | None:
    """Message si ce type de contrôle n'est pas utilisable d'après la disponibilité (None : utilisable)."""
    if not availability.get("available"):
        return str(availability.get("message") or "Verrouillage de composition indisponible.")
    for t in availability.get("types") or []:
        if t.get("id") == type_id:
            return None if t.get("available") else f"Type « {t.get('name')} » indisponible : {t.get('problem')}."
    return None  # type propre à un preset : vérifié à la construction


# --- verrou -----------------------------------------------------------------------------------
def lock_preset_id(session: Session, presets: PresetRegistry, panel: Panel) -> str:
    """Preset ControlNet qu'utilisera la case : pendant `with_control` de son palier résolu."""
    entries = panel_cast(session, panel, presets).entries
    return control_variant(presets, resolve_preset_id(presets, panel, entries), entries)


def control_settings(presets: PresetRegistry, preset_id: str) -> ControlSettings:
    settings = presets.workflow(preset_id).preset.control
    if settings is None:
        raise GenerationError(f"le workflow {preset_id} n'est pas un preset ControlNet")
    return settings


def check_type(settings: ControlSettings, type_id: str) -> str:
    if type_id not in settings.types:
        known = ", ".join(f"{k} ({t.name})" for k, t in settings.types.items())
        raise GenerationError(f"type de contrôle inconnu : « {type_id} » (possibles : {known})")
    return type_id


def check_strength(value: float) -> float:
    if not 0 <= value <= 2:
        raise GenerationError("force du contrôle : entre 0 et 2")
    return float(value)


def _source_image(panel: Panel, source: str, image_id: int | None) -> PanelImage:
    if source == "croquis" and image_id is None:
        sketch = next((i for i in panel.images if i.id == panel.sketch_image_id), None)
        if sketch is None:
            raise GenerationError("aucun croquis validé pour cette case : valide un croquis ou choisis une version")
        return sketch
    img = next((i for i in panel.images if i.id == image_id), None)
    if img is None:
        raise GenerationError("version introuvable pour cette case")
    if source == "croquis" and img.kind != ImageKind.croquis:
        raise GenerationError(f"la version {img.version} n'est pas un croquis")
    return img


def lock_composition(
    session: Session,
    presets: PresetRegistry,
    files: FileStore,
    panel: Panel,
    *,
    source: str,
    image_id: int | None = None,
    upload: bytes | None = None,
    control_type: str | None = None,
    strength: float | None = None,
) -> dict[str, Any]:
    """Verrouille la composition de la case (sans commit) et met en file l'aperçu de la carte."""
    if source not in SOURCES:
        raise GenerationError(f"source de composition inconnue : « {source} » (croquis, version ou import)")
    preset_id = lock_preset_id(session, presets, panel)
    settings = control_settings(presets, preset_id)
    lock: dict[str, Any] = {
        "source": source,
        "image_id": None,
        "version": None,
        "path": None,
        "type": check_type(settings, control_type or settings.default_type),
        "strength": check_strength(strength if strength is not None else settings.default_strength),
        "locked_at": datetime.now(UTC).isoformat(),
    }
    if source == "import":
        if not upload:
            raise GenerationError("aucune image importée")
        chapter = panel.page.chapter
        stored = files.save_image(
            upload, f"projects/{chapter.project_id}/chapters/{chapter.id}/panels/{panel.id}/guides"
        )
        lock.update(path=stored.path, width=stored.width, height=stored.height)
    else:
        img = _source_image(panel, source, image_id)
        if source == "version" and img.kind == ImageKind.croquis:
            lock["source"] = "croquis"
        params = img.params or {}
        lock.update(
            image_id=img.id,
            version=img.version,
            width=params.get("image_width"),
            height=params.get("image_height"),
        )
    previous = panel.composition_lock if isinstance(panel.composition_lock, dict) else None
    _drop_files(files, previous, keep=lock.get("path"))
    panel.composition_lock = lock
    enqueue_preview(session, presets, panel, preset_id)
    return panel.composition_lock


def update_lock(
    session: Session,
    presets: PresetRegistry,
    panel: Panel,
    *,
    control_type: str | None = None,
    strength: float | None = None,
) -> dict[str, Any]:
    """Change le type et/ou la force du verrou ; un nouveau type redemande l'aperçu de la carte."""
    lock = panel.composition_lock
    if not isinstance(lock, dict):
        raise GenerationError("la composition de cette case n'est pas verrouillée")
    preset_id = lock_preset_id(session, presets, panel)
    settings = control_settings(presets, preset_id)
    new = dict(lock)
    if strength is not None:
        new["strength"] = check_strength(strength)
    retype = control_type is not None and control_type != lock.get("type")
    if control_type is not None:
        new["type"] = check_type(settings, control_type)
    panel.composition_lock = new
    if retype:
        enqueue_preview(session, presets, panel, preset_id)
    return panel.composition_lock


def unlock_composition(files: FileStore, panel: Panel) -> None:
    """Déverrouille : composition libre. L'image importée et l'aperçu sont effacés (les versions
    produites gardent leur trace dans `params.composition`)."""
    _drop_files(files, panel.composition_lock if isinstance(panel.composition_lock, dict) else None)
    panel.composition_lock = None


def drop_lock_on_delete(files: FileStore, panel: Panel, image_id: int) -> bool:
    """Version supprimée : si c'était l'image guide du verrou, la case est déverrouillée."""
    lock = panel.composition_lock
    if isinstance(lock, dict) and lock.get("image_id") == image_id and lock.get("source") != "import":
        unlock_composition(files, panel)
        return True
    return False


def _drop_files(files: FileStore, lock: dict[str, Any] | None, *, keep: str | None = None) -> None:
    if lock is None:
        return
    preview = lock.get("preview") or {}
    for rel in (lock.get("path"), preview.get("path") if isinstance(preview, dict) else None):
        if isinstance(rel, str) and rel and rel != keep:
            files.delete(rel)


def enqueue_preview(session: Session, presets: PresetRegistry, panel: Panel, preset_id: str) -> Job | None:
    """Met en file l'aperçu de la carte de contrôle du verrou (aucun si le preset n'en déclare pas)."""
    lock = panel.composition_lock
    if not isinstance(lock, dict) or control_settings(presets, preset_id).map_output is None:
        return None
    chapter = panel.page.chapter
    job = Job(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        panel_id=panel.id,
        step=STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={"preset": preset_id, "control": {k: lock.get(k) for k in ("source", "image_id", "path", "type")}},
    )
    session.add(job)
    session.flush()
    # La carte en place (path, type, map_job_id) reste affichée jusqu'à ce que ce job la remplace.
    old = lock.get("preview") if isinstance(lock.get("preview"), dict) else {}
    panel.composition_lock = {**lock, "preview": {**old, "job_id": job.id}}
    return job


# --- aperçu de la carte de contrôle (file ComfyUI) --------------------------------------------
class ControlMapExecutor:
    """Exécute un job `control_map` : image guide → prétraitement du type → carte (aperçu de l'atelier)."""

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

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        if self.comfyui is None:
            raise GenerationError(f"ComfyUI indisponible : {self.comfyui_error or 'client non configuré'}")
        comfy = self.comfyui
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            panel = session.get(Panel, job.panel_id) if job is not None and job.panel_id is not None else None
            if job is None or panel is None:
                raise GenerationError("case introuvable (supprimée entre-temps ?)")
            panel_id = panel.id
            lock = panel.composition_lock if isinstance(panel.composition_lock, dict) else None
            if lock is None or (lock.get("preview") or {}).get("job_id") != job_id:
                return "Aperçu sans objet : composition déverrouillée ou modifiée entre-temps"
            presets = self.presets_for(panel.page.chapter.project_id)
            loaded = presets.workflow(str(job.params.get("preset") or ""))
            size = panel_target(presets, panel.page, panel) or {"width": 1024, "height": 1024}
            _, data, filename = guide_image(session, self.files, panel, lock)
            chapter = panel.page.chapter
            folder = f"projects/{chapter.project_id}/chapters/{chapter.id}/panels/{panel.id}/guides"
            prefix = f"mangaka/serie-{chapter.project_id}/chapitre-{chapter.number}/page-{panel.page.number}"
            prefix += f"/controle-case-{panel.index + 1}"
            type_id = str(lock.get("type"))

        report(5, "Envoi de l'image guide à ComfyUI…")
        name = comfy.upload_image(data, filename, subfolder=UPLOAD_SUBFOLDER)
        built = build_control_map_workflow(loaded, name, type_id, size["width"], size["height"], filename_prefix=prefix)
        if cancel.is_set():
            raise ComfyUIInterruptedError("aperçu annulé")
        label = (built.control or {}).get("name") or type_id
        report(10, f"Carte de contrôle « {label} » en cours dans ComfyUI…")
        prompt_id = comfy.queue_prompt(built.workflow)
        self._prompt_ids[job_id] = prompt_id
        try:
            refs = comfy.wait_for_images(
                prompt_id,
                built.output_node,
                timeout_s=PREVIEW_TIMEOUT_S,
                poll_s=self.poll_s,
                on_progress=lambda value, maximum: report(10 + int(80 * value / maximum), "Prétraitement…"),
                should_stop=cancel.is_set,
            )
        except ComfyUITimeoutError:
            with contextlib.suppress(ComfyUIError):
                comfy.interrupt(prompt_id)
            raise GenerationError(f"ComfyUI n'a pas produit la carte en {PREVIEW_TIMEOUT_S:.0f} s") from None
        finally:
            self._prompt_ids.pop(job_id, None)
        report(92, "Récupération de la carte…")
        stored = self.files.save_image(comfy.fetch_image(refs[0]), folder)

        with self.db.session_scope() as session:
            panel = session.get(Panel, panel_id)
            lock = panel.composition_lock if panel is not None else None
            if panel is None or not isinstance(lock, dict) or (lock.get("preview") or {}).get("job_id") != job_id:
                self.files.delete(stored.path)
                return "Aperçu sans objet : composition déverrouillée ou modifiée entre-temps"
            old = lock.get("preview") or {}
            if isinstance(old.get("path"), str) and old["path"] != stored.path:
                self.files.delete(old["path"])
            panel.composition_lock = {
                **lock,
                "preview": {
                    "job_id": job_id,
                    "map_job_id": job_id,  # job qui a produit `path`
                    "type": type_id,
                    "path": stored.path,
                    "width": stored.width,
                    "height": stored.height,
                },
            }
            session.commit()
        return f"Carte de contrôle « {label} » prête ({stored.width}×{stored.height})"
