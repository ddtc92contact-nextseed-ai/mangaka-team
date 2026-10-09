"""« Générer une case d'essai » : une vraie génération peu coûteuse sur un preset choisi.

Passe par la file sérielle de ComfyUI (jamais deux générations à la fois) ; les paramètres
viennent du bloc `trial` du preset (petite taille, peu d'étapes, prompt d'essai). L'image est
gardée dans `data/comfyui-trials/` ; sa durée (envoi → image récupérée) est enregistrée dans
les paramètres du job.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Any

from ..presets import PresetRegistry, build_workflow
from ..providers.comfyui import ComfyUIClient, ComfyUIError, ComfyUIInterruptedError, ComfyUITimeoutError
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import Job
from .generation import GenerationError
from .jobs import JobReporter

STEP = "comfyui_trial"
FOLDER = "comfyui-trials"


def format_seconds(seconds: float) -> str:
    return f"{seconds:.1f}".replace(".", ",") + " s"


class TrialExecutor:
    def __init__(
        self,
        db: Database,
        presets: PresetRegistry,
        files: FileStore,
        comfyui: ComfyUIClient | None,
        *,
        comfyui_error: str | None = None,
        poll_s: float = 1.0,
    ) -> None:
        self.db = db
        self.presets = presets
        self.files = files
        self.comfyui = comfyui
        self.comfyui_error = comfyui_error
        self.poll_s = poll_s
        self._prompt_ids: dict[int, str] = {}

    def interrupt(self, job_id: int) -> None:
        prompt_id = self._prompt_ids.get(job_id)
        if self.comfyui is not None and prompt_id is not None:
            self.comfyui.interrupt(prompt_id)

    def _update_params(self, job_id: int, values: dict[str, Any]) -> None:
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.params = {**(job.params or {}), **values}
                session.commit()

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        if self.comfyui is None:
            raise GenerationError(f"ComfyUI indisponible : {self.comfyui_error or 'client non configuré'}")
        comfy = self.comfyui
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            preset_id = str((job.params or {}).get("preset") or "") if job is not None else ""
        loaded = self.presets.workflow(preset_id)
        preset = loaded.preset
        if not preset.trial:
            raise GenerationError(f"le workflow {preset.id} ne définit pas de case d'essai (bloc trial du preset)")
        built = build_workflow(loaded, dict(preset.trial))

        report(5, f"Envoi de la case d'essai « {preset.name} » à ComfyUI…")
        t0 = time.monotonic()
        prompt_id = comfy.queue_prompt(built.workflow)
        self._prompt_ids[job_id] = prompt_id
        last = [-1]

        def on_progress(value: int, maximum: int) -> None:
            pct = 10 + int(80 * value / maximum)
            if pct != last[0]:
                last[0] = pct
                report(pct, f"Case d'essai : étape {value}/{maximum}")

        try:
            report(10, "Chargement des modèles et génération dans ComfyUI…")
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
                f"ComfyUI n'a pas terminé la case d'essai en {preset.timeout_s:.0f} s "
                f"(délai réglable : timeout_s du preset {preset.id})"
            ) from None
        finally:
            self._prompt_ids.pop(job_id, None)
        if cancel.is_set():
            raise ComfyUIInterruptedError("case d'essai annulée")

        report(95, "Récupération de l'image…")
        data = comfy.fetch_image(refs[0])
        duration_s = time.monotonic() - t0
        stored = self.files.save_image(data, FOLDER)
        self._update_params(
            job_id,
            {
                "image_path": stored.path,
                "image_width": stored.width,
                "image_height": stored.height,
                "duration_s": round(duration_s, 1),
                "seed": built.params["seed"],
                "steps": built.params.get("steps"),
                "comfyui": comfy.name,
            },
        )
        return f"Case d'essai {stored.width}×{stored.height} générée en {format_seconds(duration_s)}"
