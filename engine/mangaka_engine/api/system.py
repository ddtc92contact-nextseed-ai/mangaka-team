"""État du moteur, de ComfyUI et des presets."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import __version__
from ..pipeline.generation import ai_prompt_default
from ..presets import PresetRegistry
from .deps import AppContext, PresetsBusy, get_ctx

log = logging.getLogger("mangaka_engine")

router = APIRouter(tags=["système"])

# Libellés affichés dans l'en-tête de l'interface ; « simulé » pour les fournisseurs factices.
_LABELS = {
    "llm": {"deepseek": "DeepSeek", "ollama": "Ollama", "claude": "Claude", "mock": "simulé"},
    "vision": {"ollama": "Ollama", "deepseek": "DeepSeek", "mock": "simulé"},
    "comfyui": {"http": "réel", "mock": "simulé"},
}
_ENV = {"llm": "LLM_PROVIDER", "vision": "VISION_PROVIDER", "comfyui": "COMFYUI_PROVIDER"}


def active_providers(ctx: AppContext) -> dict[str, dict[str, Any]]:
    """Fournisseurs actifs (LLM, vision, ComfyUI) : nom, mode simulé, variable `.env` à changer.

    Ne renvoie jamais de clé d'API : seulement si elle est renseignée (`key_set`).
    """
    providers, settings = ctx.providers, ctx.settings
    out: dict[str, dict[str, Any]] = {}
    for kind, env in _ENV.items():
        name = providers.names.get(kind) or "mock"
        entry: dict[str, Any] = {
            "name": name,
            "label": _LABELS[kind].get(name, name),
            "mock": name == "mock",
            "ok": kind not in providers.errors,
            "detail": providers.errors.get(kind),
            "env": env,
            "key_env": None,
            "key_set": None,
        }
        if kind == "llm" and name == "deepseek":
            key = settings.deepseek_api_key.get_secret_value().strip() if settings.deepseek_api_key else ""
            entry["key_env"] = "DEEPSEEK_API_KEY"
            entry["key_set"] = bool(key)
        if kind == "comfyui" and name == "http":
            entry["url"] = settings.comfyui_url
        out[kind] = entry
    return out


@router.get("/providers")
def get_providers(ctx: AppContext = Depends(get_ctx)) -> dict[str, dict[str, Any]]:
    """Fournisseurs actifs, pour le badge de l'en-tête (jamais la clé d'API elle-même)."""
    return active_providers(ctx)


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
            for kind in ("llm", "vision", "comfyui", "detectors", "identity", "embedding")
        },
        "active": active_providers(ctx),
        # Dossiers de ComfyUI (rangement et nettoyage) : `problem` = rien n'est supprimé hors de data/.
        "storage": {**ctx.folders.status(), "warning": ctx.folders.warning()},
        "mock": all(
            providers.names.get(k) == "mock" for k in ("llm", "vision", "comfyui", "detectors", "identity", "embedding")
        ),
        "presets": {
            "page_formats": len(ctx.presets.page_formats),
            "workflows": len(ctx.presets.workflows),
            "upscalers": len(ctx.presets.upscalers),
            "layout_templates": len(ctx.presets.layout_templates),
            "layout_styles": len(ctx.presets.layout_styles),
            "prompts": len(ctx.presets.prompts),
            "qc": ctx.presets.qc is not None,
            "issues": len(ctx.presets.issues),
        },
    }


@router.get("/presets")
def list_presets(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    reg = ctx.presets
    return {
        "defaults": reg.defaults.model_dump() if reg.defaults else None,
        # « Prompt rédigé par l'IA » des nouvelles séries (réglage global du dessinateur, « L'équipe »).
        "ai_prompt_default": ai_prompt_default(ctx.agents.presets_for(None)),
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
        "layout_templates": [
            {"id": t.id, "name": t.name, "panel_count": t.panel_count} for t in reg.layout_templates.values()
        ],
        "layout_styles": [
            {
                "id": st.id,
                "name": st.name,
                "description": st.description,
                "is_default": st.id == reg.default_layout_style,
            }
            for st in reg.layout_styles.values()
        ],
        # Packs de style (listes fermées de la fiche série), dans leur ordre d'affichage.
        "style_genres": [
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                # Suggestion du genre (jamais « sage ») ; null : style par défaut des nouvelles séries.
                "layout_style": g.layout_style if reg.genre_layout_style(g.id) == g.layout_style else None,
                "reading_direction": g.reading_direction,
                "fonts": {"dialogue": g.fonts.dialogue, "shout": g.fonts.shout},
                "allowed_tones": g.allowed_tones,
                "style_lora": g.style_lora,
            }
            for g in reg.style_genres.values()
        ],
        "style_renderings": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "monochrome": r.monochrome,
                "is_default": r.id == reg.default_style_rendering,
            }
            for r in reg.style_renderings.values()
        ],
        "style_tones": [
            {"id": t.id, "name": t.name, "description": t.description, "is_default": t.id == reg.default_style_tone}
            for t in reg.style_tones.values()
        ],
        "style_options": [
            {
                "id": key,
                "name": o.name,
                "description": o.description,
                "monochrome_only": o.monochrome_only,
                "choices": [{"id": cid, "name": c.name} for cid, c in o.choices.items()],
            }
            for key, o in reg.style_options.options.items()
        ],
        "style_loras": [
            {"file": lo.file, "name": lo.name, "trigger_words": lo.trigger_words, "weight": lo.weight}
            for lo in reg.style_loras.loras
        ],
        "prompts": sorted(reg.prompts),
        "workflows": [
            {
                "id": w.preset.id,
                "name": w.preset.name,
                "description": w.preset.description,
                "engine": w.preset.engine,
                "engine_name": w.preset.engine_name,
                # Sans point d'insertion LoRA (`lora_chain`) : la fiche série et les fiches le signalent.
                "supports_lora": w.preset.supports_lora,
                "params": sorted(w.preset.mapping),
                "reference_slots": len(w.preset.reference_images),
                "with_references": w.preset.with_references,
                "has_trial": bool(w.preset.trial),
                "tier": w.preset.tier.name if w.preset.tier else None,
                "tier_choice": w.preset.tier.choice if w.preset.tier else None,
                "tier_order": w.preset.tier.order if w.preset.tier else None,
                "estimated_s": w.preset.estimated_s,
                "role": w.preset.role,
                "from_sketch": w.preset.from_sketch,
                "denoise": w.preset.defaults.get("denoise"),
                # Vrai CFG : à cfg 1 (et toujours pour un modèle distillé), le prompt négatif n'est pas lu.
                "steps": w.preset.defaults.get("steps"),
                "cfg": w.preset.cfg,
                "distilled": w.preset.distilled,
                "negative_active": w.preset.negative_active(),
            }
            for w in reg.workflows.values()
        ],
        "upscalers": [
            {
                "id": u.preset.id,
                "name": u.preset.name,
                "description": u.preset.description,
                "model_scale": u.preset.model_scale,
                "high_fidelity": u.preset.high_fidelity,
                "is_default": u.preset.id == reg.default_upscaler,
                "estimated_s": u.preset.estimated_s,
            }
            for u in reg.upscalers.values()
        ],
        "fonts": [
            {
                "id": font_id,
                "name": f.name,
                "bold": f.bold is not None,
                "italic": f.italic is not None,
            }
            for font_id, f in (reg.fonts.fonts.items() if reg.fonts else [])
        ],
        "issues": [{"file": i.file, "message": i.message} for i in reg.issues],
    }


@router.post("/presets/reload")
def reload_presets(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """« Recharger les flux » (Réglages) : relit presets/ sans redémarrer le moteur.

    409 tant qu'une génération (ou un autre job de la file ComfyUI) tourne : rien n'est relu, on réessaie
    après. Un preset invalide est écarté et listé dans `issues` sans empêcher les autres de se charger."""
    try:
        reg = ctx.reload_presets()
    except PresetsBusy as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Une génération est en cours (job {exc.job_id}) : recharge les flux quand la file est vide.",
        ) from None
    for issue in reg.issues:
        log.warning("preset ignoré — %s : %s", issue.file, issue.message)
    log.info("presets rechargés : %s flux, %s problème(s)", len(reg.workflows), len(reg.issues))
    return {
        "workflows": len(reg.workflows),
        "engines": _engine_counts(reg),
        "issues": [{"file": i.file, "message": i.message} for i in reg.issues],
    }


def _engine_counts(reg: PresetRegistry) -> list[dict[str, Any]]:
    """Flux par moteur (`engine` du preset ; sans moteur : « Autres »), dans l'ordre des presets."""
    counts: dict[str | None, dict[str, Any]] = {}
    for w in reg.workflows.values():
        key = w.preset.engine
        entry = counts.setdefault(key, {"engine": key, "name": w.preset.engine_name or "Autres", "workflows": 0})
        entry["workflows"] += 1
    return list(counts.values())
