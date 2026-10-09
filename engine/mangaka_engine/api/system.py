"""État du moteur, de ComfyUI et des presets."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import __version__
from .deps import AppContext, get_ctx

router = APIRouter(tags=["système"])


@router.get("/health")
def health(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    providers = ctx.providers
    if providers.comfyui is not None:
        status = providers.comfyui.health()
        comfyui = {
            "online": status.online,
            "provider": status.provider,
            "url": status.url,
            "queue_running": status.queue_running,
            "queue_pending": status.queue_pending,
            "detail": status.detail,
        }
    else:
        comfyui = {
            "online": False,
            "provider": providers.names.get("comfyui"),
            "url": None,
            "queue_running": 0,
            "queue_pending": 0,
            "detail": providers.errors.get("comfyui"),
        }
    return {
        "engine": {"status": "ok", "version": __version__},
        "comfyui": comfyui,
        "providers": {
            kind: {
                "name": providers.names.get(kind),
                "ok": kind not in providers.errors,
                "detail": providers.errors.get(kind),
            }
            for kind in ("llm", "vision", "comfyui")
        },
        "mock": all(providers.names.get(k) == "mock" for k in ("llm", "vision", "comfyui")),
        "presets": {
            "page_formats": len(ctx.presets.page_formats),
            "workflows": len(ctx.presets.workflows),
            "issues": len(ctx.presets.issues),
        },
    }


@router.get("/presets")
def list_presets(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    reg = ctx.presets
    return {
        "defaults": reg.defaults.model_dump() if reg.defaults else None,
        "page_formats": [
            {
                "id": f.id,
                "name": f.name,
                "width_mm": f.width_mm,
                "height_mm": f.height_mm,
                "dpi": f.dpi,
                "width_px": f.width_px,
                "height_px": f.height_px,
            }
            for f in reg.page_formats.values()
        ],
        "workflows": [
            {
                "id": w.preset.id,
                "name": w.preset.name,
                "description": w.preset.description,
                "params": sorted(w.preset.mapping),
            }
            for w in reg.workflows.values()
        ],
        "issues": [{"file": i.file, "message": i.message} for i in reg.issues],
    }
