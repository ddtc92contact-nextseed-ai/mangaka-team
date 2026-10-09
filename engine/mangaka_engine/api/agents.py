"""Écran « L'équipe » : agents du pipeline, leurs réglages (profil global / par série), versions et essais.

`project_id` (paramètre de requête) choisit la portée : absent = profil global, sinon la surcharge
« pour cette série seulement ». Aucun secret n'est jamais renvoyé : seulement « clé présente / absente ».
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents import AgentService, ProfileInvalid, ResolvedSetting, SettingError
from ..agents.profiles import KNOWLEDGE_KEY, to_text
from ..agents.trials import TrialContext, TrialError, run_trial
from ..presets.schemas import AgentPreset, AgentSetting
from ..store.models import AgentProfile, AgentProfileVersion, Job, JobStatus, Project
from .deps import AppContext, get_ctx, get_session

router = APIRouter(tags=["agents"])

STATE_LABELS = {"ready": "Prêt", "down": "Fournisseur injoignable", "misconfigured": "Mal configuré"}
ACTION_LABELS = {"save": "Modification", "restore": "Retour à une version", "reset": "Réglages d'origine"}
FINISHED = (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileIn(_In):
    values: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] | None = None
    author: str | None = Field(default=None, max_length=120)


class ActionIn(_In):
    author: str | None = Field(default=None, max_length=120)


class TrialIn(_In):
    values: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] | None = None


def _invalid(errors: list[SettingError]) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"detail": "Réglages invalides", "errors": [e.as_dict() for e in errors]}
    )


def _agent(ctx: AppContext, agent_id: str) -> AgentPreset:
    agent = ctx.agents.agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent introuvable : « {agent_id} »")
    return agent


def _project(session: Session, project_id: int | None) -> Project | None:
    if project_id is None:
        return None
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    return project


# --- état ---------------------------------------------------------------------------------------
def _status(ctx: AppContext, agent: AgentPreset, comfy_online: tuple[bool, str | None] | None) -> dict[str, Any]:
    service = ctx.agents
    providers = ctx.providers
    issues = service.base_problems(agent)
    problem = service.problems_for(None).get(agent.id)
    if problem:
        issues.append(problem)
    notes: list[str] = []
    if agent.llm is not None:
        _, error = service.llm_for(agent.id, None)
        if error:
            issues.append(error)
    kinds = [k for k in agent.providers if k != "llm"]
    unavailable = [k for k in kinds if k in providers.errors]
    if kinds and len(unavailable) == len(kinds):
        issues += [providers.errors[k] for k in unavailable]
    else:
        notes += [f"{k} : {providers.errors[k]}" for k in unavailable]
    if issues:
        state, detail = "misconfigured", " ; ".join(issues)
    elif "comfyui" in kinds and comfy_online is not None and not comfy_online[0]:
        state, detail = "down", comfy_online[1] or "ComfyUI ne répond pas"
    else:
        state, detail = "ready", " ; ".join(notes) or None
    return {"state": state, "label": STATE_LABELS[state], "detail": detail}


def _comfy(ctx: AppContext) -> tuple[bool, str | None] | None:
    comfy = ctx.providers.comfyui
    if comfy is None:
        return None
    status = comfy.health()
    return status.online, status.detail


def _choice_label(service: AgentService, setting: AgentSetting, value: Any) -> str:
    if value is None:
        return "aucun"
    return service.choice_labels(setting).get(str(value), str(value))


def _model_label(service: AgentService, agent: AgentPreset, resolved: list[ResolvedSetting]) -> str:
    by_key = {r.setting.key: r for r in resolved}
    if agent.llm is not None:
        name, model, _ = service.llm_choice(resolved, agent)
        label = _choice_label(service, by_key[agent.llm.provider].setting, name)
        return label if name == "mock" or not model else f"{label} · {model}"
    parts = []
    for key in agent.summary:
        r = by_key[key]
        parts.append(_choice_label(service, r.setting, r.value) if r.setting.type == "choice" else str(r.value))
    return " · ".join(p for p in parts if p) or agent.summary_default or "—"


def _last_run(session: Session, agent: AgentPreset, project_id: int | None = None) -> dict[str, Any] | None:
    if not agent.job_steps:
        return None
    q = select(Job).where(Job.step.in_(agent.job_steps), Job.status.in_(FINISHED))
    if project_id is not None:
        q = q.where(Job.project_id == project_id)
    job = session.scalars(q.order_by(Job.finished_at.desc(), Job.id.desc()).limit(1)).first()
    if job is None:
        return None
    return {
        "job_id": job.id,
        "status": job.status.value,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_ms": job.duration_ms,
        "message": job.message,
        "error": job.error,
        "project_id": job.project_id,
    }


def _source_label(setting: AgentSetting) -> str:
    if setting.source.startswith("env:"):
        return f".env ({setting.source.removeprefix('env:')})"
    if setting.source == "profile":
        return "profil de l'agent"
    file, path = setting.source.split("#", 1)
    return f"presets/{file} › {path}"


def _setting_out(service: AgentService, r: ResolvedSetting) -> dict[str, Any]:
    s = r.setting
    choices = service.choices(s) if s.type == "choice" else []
    labels = service.choice_labels(s) if s.type == "choice" else {}
    return {
        "key": s.key,
        "label": s.label,
        "help": s.help,
        "group": s.group,
        "type": s.type,
        "choices": [{"value": c, "label": labels.get(c, c)} for c in choices],
        "nullable": s.nullable,
        "variables": s.variables,
        "min": s.min,
        "max": s.max,
        "step": s.step,
        "global_only": s.global_only,
        "source": _source_label(s),
        "value": to_text(s, r.value),
        "origin": r.origin,
        "preset": to_text(s, r.preset),
        "inherited": to_text(s, r.inherited),
    }


def _summary(
    ctx: AppContext, session: Session, agent: AgentPreset, comfy: tuple[bool, str | None] | None
) -> dict[str, Any]:
    service = ctx.agents
    resolved, _ = service.resolved_for(session, agent, None)
    return {
        "id": agent.id,
        "name": agent.name,
        "icon": agent.icon,
        "role": agent.role,
        "step": agent.step,
        "step_label": agent.step_label,
        "model": _model_label(service, agent, resolved),
        "status": _status(ctx, agent, comfy),
        "last_run": _last_run(session, agent),
        "version": service.current_version(session, agent.id, None),
        "series_overrides": sum(1 for p in _series_profiles(service, session, agent.id) if p.values),
    }


def _series_profiles(service: AgentService, session: Session, agent_id: str) -> list[AgentProfile]:
    return list(
        session.scalars(
            select(AgentProfile).where(AgentProfile.agent_id == agent_id, AgentProfile.project_id.is_not(None))
        )
    )


def _detail(ctx: AppContext, session: Session, agent: AgentPreset, project: Project | None) -> dict[str, Any]:
    service = ctx.agents
    project_id = project.id if project else None
    resolved, knowledge = service.resolved_for(session, agent, project_id)
    problems = service.problems_for(project_id)
    return {
        **_summary(ctx, session, agent, _comfy(ctx)),
        "model": _model_label(service, agent, resolved),
        "last_run": _last_run(session, agent, project_id) if project_id else _last_run(session, agent),
        "scope": {"project_id": project_id, "project_title": project.title if project else None},
        "version": service.current_version(session, agent.id, project_id),
        "global_version": service.current_version(session, agent.id, None),
        "trial": agent.trial is not None,
        "trial_description": agent.trial_description,
        "secrets": service.secrets(agent),
        "settings": [_setting_out(service, r) for r in resolved],
        "knowledge": knowledge,
        "problem": problems.get(agent.id),
    }


def _version_out(service: AgentService, agent: AgentPreset, v: AgentProfileVersion) -> dict[str, Any]:
    labels = {s.key: s.label for s in agent.settings} | {KNOWLEDGE_KEY: "Savoir-faire"}
    return {
        "version": v.version,
        "created_at": v.created_at.isoformat(),
        "author": v.author,
        "action": v.action,
        "action_label": ACTION_LABELS.get(v.action, v.action)
        + (f" {v.restored_from}" if v.action == "restore" and v.restored_from else ""),
        "restored_from": v.restored_from,
        "keys": sorted(k for k in (v.values or {}) if k in labels),
        "diff": [{**d, "label": labels.get(d.get("key", ""), d.get("key", ""))} for d in v.diff or []],
    }


# --- routes ---------------------------------------------------------------------------------------
@router.get("/agents")
def list_agents(ctx: AppContext = Depends(get_ctx), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    comfy = _comfy(ctx)
    return [_summary(ctx, session, a, comfy) for a in ctx.agents.agents()]


@router.get("/agents/{agent_id}")
def get_agent(
    agent_id: str,
    project_id: int | None = None,
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    agent = _agent(ctx, agent_id)
    return _detail(ctx, session, agent, _project(session, project_id))


@router.put("/agents/{agent_id}/profile", response_model=None)
def save_profile(
    agent_id: str,
    body: ProfileIn,
    project_id: int | None = None,
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    """Enregistre le formulaire : une nouvelle version si quelque chose change (422 si invalide)."""
    agent = _agent(ctx, agent_id)
    project = _project(session, project_id)
    try:
        version = ctx.agents.save(session, agent, project_id, body.values, body.knowledge, author=body.author)
    except ProfileInvalid as exc:
        return _invalid(exc.errors)
    return {**_detail(ctx, session, agent, project), "saved_version": version.version if version else None}


@router.get("/agents/{agent_id}/versions")
def list_versions(
    agent_id: str,
    project_id: int | None = None,
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    agent = _agent(ctx, agent_id)
    _project(session, project_id)
    return [_version_out(ctx.agents, agent, v) for v in ctx.agents.versions(session, agent.id, project_id)]


@router.post("/agents/{agent_id}/versions/{version}/restore", response_model=None)
def restore_version(
    agent_id: str,
    version: int,
    body: ActionIn | None = None,
    project_id: int | None = None,
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    """« Revenir à cette version » : ses valeurs deviennent une nouvelle version."""
    agent = _agent(ctx, agent_id)
    project = _project(session, project_id)
    try:
        saved = ctx.agents.restore(session, agent, project_id, version, author=body.author if body else None)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Version {version} introuvable") from None
    except ProfileInvalid as exc:
        return _invalid(exc.errors)
    return {**_detail(ctx, session, agent, project), "saved_version": saved.version if saved else None}


@router.post("/agents/{agent_id}/reset")
def reset_profile(
    agent_id: str,
    body: ActionIn | None = None,
    project_id: int | None = None,
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """« Revenir aux réglages d'origine » : profil global → presets livrés ; série → profil global."""
    agent = _agent(ctx, agent_id)
    project = _project(session, project_id)
    saved = ctx.agents.reset(session, agent, project_id, author=body.author if body else None)
    return {**_detail(ctx, session, agent, project), "saved_version": saved.version if saved else None}


@router.post("/agents/{agent_id}/trial", response_model=None)
def trial(
    agent_id: str,
    body: TrialIn,
    project_id: int | None = None,
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    """« Essayer » avec les valeurs du formulaire (non enregistrées), sur une entrée d'exemple."""
    agent = _agent(ctx, agent_id)
    _project(session, project_id)
    if agent.trial is None:
        raise HTTPException(status_code=404, detail=f"Pas d'essai pour « {agent.name} »")
    service = ctx.agents
    values, errors = service.validate(session, agent, project_id, body.values, body.knowledge)
    if errors:
        return _invalid(errors)
    try:
        presets = service.candidate_presets(session, agent, project_id, values)
    except ProfileInvalid as exc:
        return _invalid(exc.errors)
    if project_id is None:
        resolved, _ = service.resolve(agent, values, None)
    else:
        resolved, _ = service.resolve(agent, service.stored(session, agent.id, None), values, editing="series")
    effective = {r.setting.key: r.value for r in resolved}

    def llm() -> tuple[Any, str | None]:
        name, model, changed = service.llm_choice(resolved, agent)
        return service.llm(name, model, changed, presets)

    t0 = time.monotonic()
    try:
        result = run_trial(agent.trial, TrialContext(presets=presets, values=effective, llm=llm))
    except TrialError as exc:
        result = {"input": [], "output": [], "error": str(exc)}
    return {"error": None, **result, "duration_ms": int((time.monotonic() - t0) * 1000)}


@router.get("/agents/{agent_id}/export")
def export_profile(
    agent_id: str,
    project_id: int | None = None,
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> Response:
    """« Exporter en YAML » : les fichiers presets effectifs de l'agent (portée choisie)."""
    agent = _agent(ctx, agent_id)
    project = _project(session, project_id)
    service = ctx.agents
    resolved, knowledge = service.resolved_for(session, agent, project_id)
    scope = f"série « {project.title} »" if project else "profil global"
    text = service.export_yaml(
        agent,
        resolved,
        knowledge["value"],
        service.presets_for(project_id),
        scope=scope,
        version=service.current_version(session, agent.id, project_id),
    )
    suffix = f"-serie-{project_id}" if project_id else ""
    return Response(
        content=text,
        media_type="application/x-yaml; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="agent-{agent.id}{suffix}.yaml"'},
    )


@router.get("/projects/{project_id}/agents")
def series_overrides(
    project_id: int, ctx: AppContext = Depends(get_ctx), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    """« Réglages des agents pour cette série » : surcharges de la série."""
    _project(session, project_id)
    service = ctx.agents
    out = []
    for profile in service.series_overrides(session, project_id):
        agent = service.agent(profile.agent_id)
        assert agent is not None
        labels = {s.key: s.label for s in agent.settings} | {KNOWLEDGE_KEY: "Savoir-faire"}
        out.append(
            {
                "agent_id": agent.id,
                "name": agent.name,
                "icon": agent.icon,
                "step": agent.step,
                "version": profile.version,
                "updated_at": profile.updated_at.isoformat(),
                "settings": [{"key": k, "label": labels[k]} for k in profile.values if k in labels],
            }
        )
    return sorted(out, key=lambda o: o["step"])
