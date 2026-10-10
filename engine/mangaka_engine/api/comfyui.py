"""ComfyUI : test de connexion (nœuds et fichiers des presets) et case d'essai."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.comfy_check import LoraUse, offline_report, run_check
from ..pipeline.comfy_loras import unavailable
from ..pipeline.comfy_trial import STEP as TRIAL_STEP
from ..store.models import Character, Job, JobStatus, Project
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import ComfyTrialIn, JobOut

router = APIRouter(tags=["comfyui"])


def lora_uses(session: Session) -> list[LoraUse]:
    """LoRA saisis dans les séries (style) et les fiches personnages."""
    uses = [
        LoraUse(name, f"série « {title} », style")
        for name, title in session.execute(select(Project.style_lora_name, Project.title).order_by(Project.id))
        if name
    ]
    uses += [
        LoraUse(name, f"personnage {char} (série « {title} »)")
        for name, char, title in session.execute(
            select(Character.lora_name, Character.name, Project.title)
            .join(Project, Character.project_id == Project.id)
            .order_by(Project.id, Character.id)
        )
        if name
    ]
    return uses


@router.get("/comfyui/check")
def check_comfyui(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Interroge ComfyUI (`/system_stats`, `/object_info`) et vérifie chaque preset de workflow :
    nœuds connus, modèles / encodeurs / VAE / LoRA présents. Problèmes en français, par preset."""
    client = ctx.providers.comfyui
    if client is None:
        return offline_report(
            ctx.providers.names.get("comfyui") or "?",
            None,
            ctx.providers.errors.get("comfyui") or "ComfyUI non configuré",
        )
    url = ctx.settings.comfyui_url if client.name != "mock" else None
    report = run_check(client, ctx.presets, url=url, loras=lora_uses(session))
    # Le verrouillage de composition de l'atelier suit le dernier test (nœud ou fichier du patch absent).
    if isinstance(report.get("control"), dict):
        ctx.control_catalog.store({**report["control"], "provider": client.name, "simulated": False, "error": None})
    else:
        ctx.control_catalog.clear()
    return report


@router.get("/comfyui/control")
def control_availability(refresh: bool = False, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Verrouillage de composition (ControlNet Union, patch de modèle) disponible dans ComfyUI ?

    `available`, `message` en français sinon (nœud `QwenImageDiffsynthControlnet` ou fichier du patch
    absent…), et l'état de chaque type de contrôle (prétraitement installé ou non). Gardé 30 s."""
    return ctx.control_status(refresh=refresh)


@router.get("/comfyui/loras")
def list_loras(refresh: bool = False, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """LoRA que ComfyUI accepte (valeurs permises du chargeur de `lora_chain`), sous-dossiers compris.

    Gardés 30 s (`refresh=true` pour relire) ; `available: false` et `error` si ComfyUI ne répond pas.
    Le mock renvoie une petite liste factice (`simulated: true`)."""
    client = ctx.providers.comfyui
    if client is None:
        return unavailable(
            ctx.providers.names.get("comfyui") or "?", ctx.providers.errors.get("comfyui") or "ComfyUI non configuré"
        )
    return ctx.lora_catalog.get(client, ctx.presets, refresh=refresh)


@router.post("/comfyui/trial", response_model=JobOut, status_code=202)
def start_trial(
    body: ComfyTrialIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> JobOut:
    """Met en file une case d'essai (bloc `trial` du preset) ; suivre `GET /jobs/{id}/events`."""
    defaults = ctx.presets.defaults
    preset_id = body.preset or (defaults.workflow if defaults else None)
    loaded = ctx.presets.workflows.get(preset_id or "")
    if loaded is None:
        raise FieldError("preset", f"workflow inconnu : « {preset_id} »")
    if not loaded.preset.trial:
        raise FieldError("preset", f"le workflow {loaded.preset.id} ne définit pas de case d'essai (bloc trial)")
    job = Job(
        step=TRIAL_STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={"preset": loaded.preset.id, "preset_name": loaded.preset.name},
    )
    session.add(job)
    session.commit()
    ctx.generation.notify()
    return job_out(job)


@router.get("/comfyui/trial/{job_id}/image")
def trial_image(
    job_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    job = session.get(Job, job_id)
    rel = (job.params or {}).get("image_path") if job is not None and job.step == TRIAL_STEP else None
    if not isinstance(rel, str):
        raise HTTPException(status_code=404, detail="Image d'essai introuvable")
    path = ctx.files.absolute(rel)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})
