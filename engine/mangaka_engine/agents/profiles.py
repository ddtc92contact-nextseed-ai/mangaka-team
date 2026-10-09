"""Profils des agents : réglages édités dans l'UI, versionnés en SQLite, appliqués aux presets.

Ordre de résolution d'un réglage : surcharge de la série > profil global > valeur livrée (preset,
ou `.env` pour le choix du fournisseur). Un profil ne stocke que les réglages modifiés.

Les réglages modifiés sont réécrits dans une copie des presets (`presets_for(projet)`) puis revalidés
par les mêmes schémas Pydantic que le chargeur : le pipeline reçoit un `PresetRegistry` ordinaire et
ne sait rien des profils. Sans profil, `presets_for` renvoie les presets chargés, inchangés.

Aucun secret n'est jamais lu ni renvoyé : seule la présence d'une clé dans l'environnement est exposée.
"""

from __future__ import annotations

import copy
import dataclasses
import getpass
import logging
import math
import os
import string
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..presets import LoadedWorkflow, PresetRegistry
from ..presets.schemas import (
    AgentPreset,
    AgentSetting,
    Defaults,
    FontsPreset,
    ImagePromptSettings,
    LayoutSettings,
    LayoutTemplateFile,
    LetteringSettings,
    PromptPreset,
    ProvidersPreset,
    QCSettings,
    WorkflowPreset,
)
from ..providers.factory import Providers, ProviderSelectionError, build_llm, resolve_llm_name
from ..providers.llm import LLMProvider
from ..store.db import Database
from ..store.models import AgentProfile, AgentProfileVersion, utcnow
from ..validation import translate_error

log = logging.getLogger("mangaka_engine")

Origin = Literal["preset", "global", "series"]
KNOWLEDGE_KEY = "knowledge"
_MISSING = object()

FILE_MODELS: dict[str, type[BaseModel]] = {
    "defaults.yaml": Defaults,
    "providers.yaml": ProvidersPreset,
    "layout.yaml": LayoutSettings,
    "image_prompt.yaml": ImagePromptSettings,
    "qc.yaml": QCSettings,
    "fonts.yaml": FontsPreset,
    "lettering.yaml": LetteringSettings,
}
WORKFLOWS = "workflows/*.yaml"
LAYOUTS = "layouts/*.yaml"


class Knowledge(BaseModel):
    """« Savoir-faire » d'un agent : collections de la base de connaissances et nombre d'extraits (top-k).

    Stocké dès maintenant, même sans base de connaissances : le RAG le lira quand il existera.
    """

    model_config = ConfigDict(extra="forbid")

    collections: list[str] = Field(default_factory=list, max_length=20)
    top_k: int = Field(default=5, ge=1, le=50)


@dataclass
class SettingError:
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


class ProfileInvalid(Exception):
    """Réglages refusés (422) : erreurs par réglage, en français."""

    def __init__(self, errors: list[SettingError]) -> None:
        super().__init__(" ; ".join(e.message for e in errors))
        self.errors = errors


@dataclass
class ResolvedSetting:
    setting: AgentSetting
    value: Any
    origin: Origin
    preset: Any  # valeur livrée
    inherited: Any  # valeur sans le niveau en cours d'édition (ce que « hérité » afficherait)


@dataclass
class _Cached:
    revision: int
    presets: PresetRegistry
    problems: dict[str, str] = field(default_factory=dict)


# --- chemins dans les données d'un preset ------------------------------------------------------
def _get(data: Any, path: list[str]) -> Any:
    for part in path:
        if not isinstance(data, dict) or part not in data:
            return _MISSING
        data = data[part]
    return data


def _set(data: dict[str, Any], path: list[str], value: Any) -> None:
    for part in path[:-1]:
        nxt = data.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            data[part] = nxt
        data = nxt
    data[path[-1]] = value


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def file_data(reg: PresetRegistry, file: str) -> dict[str, Any] | None:
    """Contenu validé d'un fichier preset, en dictionnaire (None : fichier absent ou invalide)."""
    if file == LAYOUTS:
        if not reg.layout_templates:
            return None
        return {"templates": [_dump(t) for t in reg.layout_templates.values()]}
    if file == WORKFLOWS:
        wf = default_workflow(reg)
        return _dump(wf.preset) if wf else None
    if file.startswith("prompts/"):
        prompt = reg.prompts.get(file.removeprefix("prompts/").removesuffix(".yaml"))
        return _dump(prompt) if prompt else None
    model = getattr(reg, file.removesuffix(".yaml"), None)
    return _dump(model) if isinstance(model, BaseModel) else None


def default_workflow(reg: PresetRegistry) -> LoadedWorkflow | None:
    if reg.defaults and reg.defaults.workflow in reg.workflows:
        return reg.workflows[reg.defaults.workflow]
    return next(iter(reg.workflows.values()), None)


def apply_overrides(
    base: PresetRegistry, overrides: Iterable[tuple[AgentSetting, Any]]
) -> tuple[PresetRegistry, list[tuple[str, ValidationError | str]]]:
    """Copie des presets avec les réglages réécrits puis revalidés ; erreurs par fichier."""
    by_file: dict[str, list[tuple[AgentSetting, Any]]] = {}
    for setting, value in overrides:
        if setting.file is not None:
            by_file.setdefault(setting.file, []).append((setting, value))
    if not by_file:
        return base, []
    changes: dict[str, Any] = {}
    errors: list[tuple[str, ValidationError | str]] = []
    for file, items in by_file.items():
        try:
            if file == WORKFLOWS:
                workflows: dict[str, LoadedWorkflow] = {}
                for wf_id, wf in base.workflows.items():
                    data = _dump(wf.preset)
                    for setting, value in items:
                        path = setting.path
                        if path[0] == "defaults" and len(path) == 2 and path[1] not in wf.preset.mapping:
                            continue  # paramètre non mappé par ce workflow
                        _set(data, path, value)
                    workflows[wf_id] = dataclasses.replace(wf, preset=WorkflowPreset.model_validate(data))
                changes["workflows"] = workflows
            elif file == LAYOUTS:
                data = file_data(base, file) or {"templates": []}
                for setting, value in items:
                    _set(data, setting.path, value)
                lib = LayoutTemplateFile.model_validate(data)
                ids = [t.id for t in lib.templates]
                dupes = sorted({i for i in ids if ids.count(i) > 1})
                if dupes:
                    raise ValueError(f"identifiant de gabarit en double : {', '.join(dupes)}")
                changes["layout_templates"] = {t.id: t for t in lib.templates}
            else:
                data = file_data(base, file)
                if data is None:
                    errors.append((file, f"presets/{file} absent ou invalide"))
                    continue
                data = copy.deepcopy(data)
                for setting, value in items:
                    _set(data, setting.path, value)
                if file.startswith("prompts/"):
                    prompt = PromptPreset.model_validate(data)
                    changes.setdefault("prompts", dict(base.prompts))[prompt.id] = prompt
                else:
                    changes[file.removesuffix(".yaml")] = FILE_MODELS[file].model_validate(data)
        except ValidationError as exc:
            errors.append((file, exc))
        except ValueError as exc:
            errors.append((file, str(exc)))
    return dataclasses.replace(base, **changes), errors


# --- valeurs ------------------------------------------------------------------------------------
def _num(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def check_value(setting: AgentSetting, value: Any, choices: list[str]) -> tuple[Any, str | None]:
    """Valeur convertie au type du réglage, ou message d'erreur en français."""
    t = setting.type
    if value is None or (isinstance(value, str) and not value.strip() and t in ("choice", "number", "integer")):
        if setting.nullable:
            return None, None
        return None, "ne peut pas être vide"
    if t in ("text", "longtext", "prompt"):
        if not isinstance(value, str):
            return None, "texte attendu"
        if t == "text":
            value = value.strip()
            if not value:
                return None, "ne peut pas être vide"
        if t == "prompt":
            problem = check_template(value, setting.variables)
            if problem:
                return None, problem
        return value, None
    if t in ("list", "prompt_list"):
        if isinstance(value, str):
            value = [line for line in value.splitlines()]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return None, "liste de textes attendue"
        value = [v.strip() for v in value if v.strip()]
        if t == "prompt_list":
            for i, part in enumerate(value, start=1):
                problem = check_template(part, setting.variables)
                if problem:
                    return None, f"ligne {i} : {problem}"
        return value, None
    if t == "boolean":
        if not isinstance(value, bool):
            return None, "oui ou non attendu"
        return value, None
    if t in ("number", "integer"):
        if isinstance(value, bool):
            return None, "nombre attendu"
        if isinstance(value, str):
            try:
                value = float(value.strip().replace(",", "."))
            except ValueError:
                return None, "nombre attendu"
        if not isinstance(value, int | float) or not math.isfinite(value):
            return None, "nombre attendu"
        if t == "integer":
            if float(value) != int(value):
                return None, "nombre entier attendu"
            value = int(value)
        if setting.min is not None and value < setting.min:
            return None, f"doit être supérieur ou égal à {_num(setting.min)}"
        if setting.max is not None and value > setting.max:
            return None, f"doit être inférieur ou égal à {_num(setting.max)}"
        return value, None
    if t == "choice":
        if not isinstance(value, str) or value not in choices:
            return None, f"valeur non autorisée (choix : {', '.join(choices) or 'aucun'})"
        return value, None
    if t == "yaml":
        if isinstance(value, str):
            try:
                value = yaml.safe_load(value)
            except yaml.YAMLError as exc:
                mark = getattr(exc, "problem_mark", None)
                where = f" (ligne {mark.line + 1})" if mark is not None else ""
                return None, f"YAML invalide{where}"
        if not isinstance(value, list | dict):
            return None, "liste ou objet YAML attendu"
        return value, None
    return value, None


def check_template(text: str, variables: list[str]) -> str | None:
    """Gabarit `$variable` : syntaxe et variables connues (message lisible, sinon None)."""
    tpl = string.Template(text)
    if not tpl.is_valid():
        return "gabarit invalide : un « $ » isolé doit s'écrire « $$ »"
    unknown = [v for v in dict.fromkeys(tpl.get_identifiers()) if v not in variables]
    if unknown:
        listed = ", ".join(f"${v}" for v in variables) or "aucune"
        names = ", ".join(f"${v}" for v in unknown)
        return f"variable{'s' if len(unknown) > 1 else ''} inconnue{'s' if len(unknown) > 1 else ''} : {names} (disponibles : {listed})"
    return None


def to_text(setting: AgentSetting, value: Any) -> Any:
    """Valeur telle que l'UI l'édite (YAML en texte)."""
    if setting.type == "yaml" and value is not None:
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, default_flow_style=None, width=100)
    return value


def _same(a: Any, b: Any) -> bool:
    if (
        isinstance(a, int | float)
        and isinstance(b, int | float)
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
    return a == b


def map_errors(
    agent: AgentPreset, file: str, error: ValidationError | str, prefer: Iterable[str] = ()
) -> list[SettingError]:
    """Erreur de validation d'un preset → réglage de l'agent concerné.

    `prefer` : réglages qui viennent de changer, choisis en priorité quand l'erreur porte sur un
    nœud parent (ex. « min_size_pt doit être ≤ size_pt » sur tout le style de la parole).
    """
    prefer = set(prefer)
    settings = sorted((s for s in agent.settings if s.file == file), key=lambda s: s.key not in prefer)
    if isinstance(error, str):
        target = settings[0].key if len(settings) == 1 else "_general"
        return [SettingError(target, error)]
    out: list[SettingError] = []
    for err in error.errors():
        loc = [str(p) for p in err.get("loc", ())]
        msg = translate_error(err)
        best: AgentSetting | None = None
        for s in settings:
            path = s.path
            if (loc[: len(path)] == path or path[: len(loc)] == loc) and (best is None or len(path) > len(best.path)):
                best = s
        if best is None:
            # Erreur sur un nœud parent (validation croisée) : le réglage le plus proche.
            best = max(settings, key=lambda s: _common(s.path, loc), default=None)
            if best is not None and _common(best.path, loc) == 0:
                best = None
        if best is not None:
            out.append(SettingError(best.key, msg))
        else:
            where = ".".join(loc) or "(racine)"
            out.append(SettingError("_general", f"presets/{file} › {where} : {msg}"))
    return out


def _common(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def default_author() -> str:
    try:
        return getpass.getuser() or "utilisateur local"
    except Exception:  # noqa: BLE001 — pas d'utilisateur système (conteneur…)
        return "utilisateur local"


# --- service ------------------------------------------------------------------------------------
class AgentService:
    """Profils des agents : lecture, résolution, versions, presets effectifs par série."""

    def __init__(self, settings: Settings, presets: PresetRegistry, providers: Providers, db: Database) -> None:
        self.settings = settings
        self.base = presets
        self.providers = providers
        self.db = db
        self._lock = threading.Lock()
        self._revision = 0
        self._cache: dict[int | None, _Cached] = {}
        self._llms: dict[tuple[str, str | None], LLMProvider] = {}
        self._file_data: dict[str, dict[str, Any] | None] = {}

    # --- déclarations --------------------------------------------------------------------------
    def agents(self) -> list[AgentPreset]:
        return sorted(self.base.agents.values(), key=lambda a: (a.step, a.name))

    def agent(self, agent_id: str) -> AgentPreset | None:
        return self.base.agents.get(agent_id)

    def choices(self, setting: AgentSetting) -> list[str]:
        if setting.choices_from == "fonts":
            return list(self.base.fonts.fonts) if self.base.fonts else []
        if setting.choices_from == "workflows":
            return list(self.base.workflows)
        if setting.choices_from == "page_formats":
            return list(self.base.page_formats)
        return list(setting.choices)

    def choice_labels(self, setting: AgentSetting) -> dict[str, str]:
        if setting.choices_from == "fonts" and self.base.fonts:
            return {k: f.name for k, f in self.base.fonts.fonts.items()}
        if setting.choices_from == "workflows":
            return {k: w.preset.name for k, w in self.base.workflows.items()}
        if setting.choices_from == "page_formats":
            return {k: f.name for k, f in self.base.page_formats.items()}
        return dict(setting.choice_labels)

    def secrets(self, agent: AgentPreset) -> list[dict[str, Any]]:
        """« clé présente / absente » : jamais la valeur."""
        out = []
        for secret in agent.secrets:
            attr = secret.env.lower()
            # Lu comme le moteur le lit (Settings : .env + environnement), sinon dans l'environnement.
            raw = getattr(self.settings, attr) if hasattr(self.settings, attr) else os.environ.get(secret.env)
            value = raw.get_secret_value() if hasattr(raw, "get_secret_value") else raw
            out.append({"env": secret.env, "label": secret.label, "present": bool(str(value or "").strip())})
        return out

    # --- valeurs livrées -----------------------------------------------------------------------
    def _base_file(self, file: str) -> dict[str, Any] | None:
        if file not in self._file_data:
            self._file_data[file] = file_data(self.base, file)
        return self._file_data[file]

    def preset_value(self, setting: AgentSetting) -> Any:
        if setting.source.startswith("env:"):
            raw = getattr(self.settings, setting.source.removeprefix("env:").lower(), None)
            value = str(raw).strip().lower() if raw is not None else ""
            return value or setting.fallback
        value: Any = _MISSING
        if setting.file is not None:
            data = self._base_file(setting.file)
            value = _get(data, setting.path) if data is not None else _MISSING
        if setting.env_override:
            env = getattr(self.settings, setting.env_override.lower(), None)
            if isinstance(env, str) and env.strip():
                value = env.strip()
        if value is _MISSING or value is None:
            return copy.deepcopy(setting.fallback)
        return copy.deepcopy(value)

    def base_problems(self, agent: AgentPreset) -> list[str]:
        """Presets livrés absents ou invalides dont dépend l'agent."""
        out = []
        for file in dict.fromkeys(s.file for s in agent.settings if s.file):
            if self._base_file(file) is None:
                out.append(f"presets/{file} absent ou invalide")
        return out

    # --- profils en base -----------------------------------------------------------------------
    def _profile(self, session: Session, agent_id: str, project_id: int | None) -> AgentProfile | None:
        q = select(AgentProfile).where(AgentProfile.agent_id == agent_id)
        q = q.where(AgentProfile.project_id.is_(None) if project_id is None else AgentProfile.project_id == project_id)
        return session.scalars(q).first()

    def stored(self, session: Session, agent_id: str, project_id: int | None) -> dict[str, Any]:
        profile = self._profile(session, agent_id, project_id)
        return dict(profile.values or {}) if profile else {}

    def _layers(self, session: Session, project_id: int | None) -> dict[str, dict[str, dict[str, Any]]]:
        """agent → {"global": valeurs, "series": valeurs} pour une portée."""
        q = select(AgentProfile).where(AgentProfile.project_id.is_(None))
        if project_id is not None:
            q = select(AgentProfile).where(
                (AgentProfile.project_id.is_(None)) | (AgentProfile.project_id == project_id)
            )
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for p in session.scalars(q):
            out.setdefault(p.agent_id, {})["global" if p.project_id is None else "series"] = dict(p.values or {})
        return out

    # --- résolution ----------------------------------------------------------------------------
    def resolve(
        self,
        agent: AgentPreset,
        global_values: dict[str, Any],
        series_values: dict[str, Any] | None,
        *,
        editing: Literal["global", "series"] = "global",
    ) -> tuple[list[ResolvedSetting], dict[str, Any]]:
        """Réglages effectifs (série > global > preset) et savoir-faire.

        `inherited` : la valeur sans le niveau en cours d'édition (preset pour le profil global,
        profil global ou preset pour une série).
        """
        series_values = series_values or {}
        out: list[ResolvedSetting] = []
        for s in agent.settings:
            preset = self.preset_value(s)
            in_global = s.key in global_values
            in_series = s.key in series_values and not s.global_only
            parent = global_values[s.key] if in_global else preset
            if in_series:
                value, origin = series_values[s.key], "series"
            elif in_global:
                value, origin = global_values[s.key], "global"
            else:
                value, origin = preset, "preset"
            inherited = parent if editing == "series" else preset
            out.append(ResolvedSetting(s, value, origin, preset, inherited))  # type: ignore[arg-type]
        default_k = Knowledge().model_dump()
        parent_k = global_values.get(KNOWLEDGE_KEY, default_k)
        if KNOWLEDGE_KEY in series_values:
            k_value, k_origin = series_values[KNOWLEDGE_KEY], "series"
        elif KNOWLEDGE_KEY in global_values:
            k_value, k_origin = global_values[KNOWLEDGE_KEY], "global"
        else:
            k_value, k_origin = default_k, "preset"
        k_inherited = parent_k if editing == "series" else default_k
        return out, {"value": k_value, "origin": k_origin, "inherited": k_inherited}

    def resolved_for(
        self, session: Session, agent: AgentPreset, project_id: int | None
    ) -> tuple[list[ResolvedSetting], dict[str, Any]]:
        g = self.stored(session, agent.id, None)
        s = self.stored(session, agent.id, project_id) if project_id is not None else None
        return self.resolve(agent, g, s, editing="series" if project_id is not None else "global")

    def _overrides(self, agent: AgentPreset, values: dict[str, Any]) -> list[tuple[AgentSetting, Any]]:
        out = []
        for key, value in values.items():
            setting = agent.setting(key)
            if setting is not None:
                out.append((setting, value))
        return out

    def merged_values(self, layers: dict[str, dict[str, dict[str, Any]]], agent: AgentPreset) -> dict[str, Any]:
        g = layers.get(agent.id, {}).get("global", {})
        s = {
            k: v
            for k, v in layers.get(agent.id, {}).get("series", {}).items()
            if not (agent.setting(k) and agent.setting(k).global_only)  # type: ignore[union-attr]
        }
        return {**g, **s}

    # --- presets effectifs ---------------------------------------------------------------------
    def invalidate(self) -> None:
        with self._lock:
            self._revision += 1
            self._cache.clear()
            self._llms.clear()

    def presets_for(self, project_id: int | None = None) -> PresetRegistry:
        """Presets à utiliser pour une série (None : profil global seul)."""
        return self._effective(project_id).presets

    def problems_for(self, project_id: int | None = None) -> dict[str, str]:
        """Profils enregistrés devenus invalides (preset modifié depuis) : agent → message."""
        return self._effective(project_id).problems

    def _effective(self, project_id: int | None) -> _Cached:
        with self._lock:
            cached = self._cache.get(project_id)
            if cached is not None and cached.revision == self._revision:
                return cached
            revision = self._revision
        with self.db.session_scope() as session:
            layers = self._layers(session, project_id)
        per_agent: dict[str, list[tuple[AgentSetting, Any]]] = {}
        for agent in self.agents():
            items = self._overrides(agent, self.merged_values(layers, agent))
            if any(s.file for s, _ in items):
                per_agent[agent.id] = items
        problems: dict[str, str] = {}
        presets = self.base
        if per_agent:
            presets, errors = apply_overrides(self.base, [i for items in per_agent.values() for i in items])
            if errors:
                # Un profil enregistré ne passe plus (preset modifié) : on écarte les agents fautifs.
                kept: list[tuple[AgentSetting, Any]] = []
                for agent_id, items in per_agent.items():
                    _, own = apply_overrides(self.base, items)
                    if own:
                        agent = self.base.agents[agent_id]
                        msgs = [e.message for f, err in own for e in map_errors(agent, f, err)]
                        problems[agent_id] = "réglages enregistrés invalides : " + " ; ".join(msgs)
                        log.warning("profil de l'agent %s ignoré : %s", agent_id, problems[agent_id])
                    else:
                        kept += items
                presets, errors = apply_overrides(self.base, kept)
                if errors:
                    presets = self.base
        cached = _Cached(revision, presets, problems)
        with self._lock:
            if revision == self._revision:
                self._cache[project_id] = cached
        return cached

    # --- validation ----------------------------------------------------------------------------
    def validate(
        self,
        session: Session,
        agent: AgentPreset,
        project_id: int | None,
        form: dict[str, Any],
        knowledge: Any = None,
        *,
        base_values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[SettingError]]:
        """Nouvelles valeurs du profil (portée `project_id`) après le formulaire, et erreurs.

        Un réglage égal à sa valeur héritée n'est pas stocké : il suit le niveau supérieur.
        """
        current = dict(self.stored(session, agent.id, project_id) if base_values is None else base_values)
        g = self.stored(session, agent.id, None)
        resolved, kn = self.resolve(
            agent,
            g if project_id is not None else current,
            current if project_id is not None else None,
            editing="series" if project_id is not None else "global",
        )
        by_key = {r.setting.key: r for r in resolved}
        errors: list[SettingError] = []
        new = dict(current)
        for key, raw in form.items():
            r = by_key.get(key)
            if r is None:
                errors.append(SettingError(key, "réglage inconnu"))
                continue
            value, problem = check_value(r.setting, raw, self.choices(r.setting))
            if problem:
                errors.append(SettingError(key, problem))
                continue
            if project_id is not None and r.setting.global_only:
                if not _same(value, r.value):
                    errors.append(SettingError(key, "réglage commun à toutes les séries : modifie le profil global"))
                new.pop(key, None)
                continue
            if _same(value, r.inherited):
                new.pop(key, None)
            else:
                new[key] = value
        if knowledge is not None:
            try:
                k = Knowledge.model_validate(knowledge).model_dump()
            except ValidationError as exc:
                errors += [
                    SettingError(f"knowledge.{'.'.join(str(p) for p in e['loc'])}", translate_error(e))
                    for e in exc.errors()
                ]
            else:
                if k == kn["inherited"]:
                    new.pop(KNOWLEDGE_KEY, None)
                else:
                    new[KNOWLEDGE_KEY] = k
        if errors:
            return new, errors
        changed = {k for k in set(new) | set(current) if not _same(new.get(k), current.get(k))}
        errors = self._check_presets(session, agent, project_id, new, prefer=changed)
        return new, errors

    def _check_presets(
        self,
        session: Session,
        agent: AgentPreset,
        project_id: int | None,
        values: dict[str, Any],
        prefer: Iterable[str] = (),
    ) -> list[SettingError]:
        """Mêmes schémas que le chargeur de presets, avec les réglages de tous les agents de la portée."""
        layers = self._layers(session, project_id)
        layers.setdefault(agent.id, {})["series" if project_id is not None else "global"] = values
        items: list[tuple[AgentSetting, Any]] = []
        for other in self.agents():
            items += self._overrides(other, self.merged_values(layers, other))
        _, errors = apply_overrides(self.base, items)
        out: list[SettingError] = []
        for file, err in errors:
            out += map_errors(agent, file, err, prefer)
        return out

    def candidate_presets(
        self, session: Session, agent: AgentPreset, project_id: int | None, values: dict[str, Any]
    ) -> PresetRegistry:
        """Presets avec les valeurs (non enregistrées) du formulaire : pour « Essayer »."""
        layers = self._layers(session, project_id)
        layers.setdefault(agent.id, {})["series" if project_id is not None else "global"] = values
        items: list[tuple[AgentSetting, Any]] = []
        for other in self.agents():
            items += self._overrides(other, self.merged_values(layers, other))
        presets, errors = apply_overrides(self.base, items)
        if errors:
            out: list[SettingError] = []
            for file, err in errors:
                out += map_errors(agent, file, err)
            raise ProfileInvalid(out)
        return presets

    # --- écriture (versions) -------------------------------------------------------------------
    def _write(
        self,
        session: Session,
        agent: AgentPreset,
        project_id: int | None,
        values: dict[str, Any],
        *,
        author: str | None,
        action: str,
        restored_from: int | None = None,
    ) -> AgentProfileVersion | None:
        profile = self._profile(session, agent.id, project_id)
        before = dict(profile.values or {}) if profile else {}
        if before == values:
            return None
        g = self.stored(session, agent.id, None)
        if project_id is None:
            old, old_k = self.resolve(agent, before, None)
            new, new_k = self.resolve(agent, values, None)
        else:
            old, old_k = self.resolve(agent, g, before, editing="series")
            new, new_k = self.resolve(agent, g, values, editing="series")
        diff = [
            {"key": a.setting.key, "before": to_text(a.setting, a.value), "after": to_text(b.setting, b.value)}
            for a, b in zip(old, new, strict=True)
            if not _same(a.value, b.value) or a.origin != b.origin
        ]
        if old_k["value"] != new_k["value"] or old_k["origin"] != new_k["origin"]:
            diff.append({"key": KNOWLEDGE_KEY, "before": old_k["value"], "after": new_k["value"]})
        if profile is None:
            profile = AgentProfile(agent_id=agent.id, project_id=project_id, values={}, version=0)
            session.add(profile)
            session.flush()
        profile.version += 1
        profile.values = dict(values)
        profile.updated_at = utcnow()
        version = AgentProfileVersion(
            profile_id=profile.id,
            version=profile.version,
            values=dict(values),
            diff=diff,
            author=(author or "").strip()[:120] or default_author(),
            action=action,
            restored_from=restored_from,
        )
        session.add(version)
        session.flush()
        return version

    def save(
        self,
        session: Session,
        agent: AgentPreset,
        project_id: int | None,
        form: dict[str, Any],
        knowledge: Any = None,
        *,
        author: str | None = None,
    ) -> AgentProfileVersion | None:
        values, errors = self.validate(session, agent, project_id, form, knowledge)
        if errors:
            raise ProfileInvalid(errors)
        version = self._write(session, agent, project_id, values, author=author, action="save")
        session.commit()
        self.invalidate()
        return version

    def restore(
        self, session: Session, agent: AgentPreset, project_id: int | None, number: int, *, author: str | None = None
    ) -> AgentProfileVersion | None:
        profile = self._profile(session, agent.id, project_id)
        target = next((v for v in (profile.versions if profile else []) if v.version == number), None)
        if target is None:
            raise LookupError(f"version {number} introuvable")
        values = dict(target.values or {})
        errors = self._check_presets(session, agent, project_id, values)
        if errors:
            raise ProfileInvalid(errors)
        version = self._write(session, agent, project_id, values, author=author, action="restore", restored_from=number)
        session.commit()
        self.invalidate()
        return version

    def reset(
        self, session: Session, agent: AgentPreset, project_id: int | None, *, author: str | None = None
    ) -> AgentProfileVersion | None:
        """« Revenir aux réglages d'origine » : profil vidé (nouvelle version), tout est hérité."""
        version = self._write(session, agent, project_id, {}, author=author, action="reset")
        session.commit()
        self.invalidate()
        return version

    def versions(self, session: Session, agent_id: str, project_id: int | None) -> list[AgentProfileVersion]:
        profile = self._profile(session, agent_id, project_id)
        return sorted(profile.versions, key=lambda v: -v.version) if profile else []

    def current_version(self, session: Session, agent_id: str, project_id: int | None) -> int:
        profile = self._profile(session, agent_id, project_id)
        return profile.version if profile else 0

    def series_overrides(self, session: Session, project_id: int) -> list[AgentProfile]:
        q = select(AgentProfile).where(AgentProfile.project_id == project_id)
        return [p for p in session.scalars(q) if p.values and p.agent_id in self.base.agents]

    # --- fournisseur LLM -----------------------------------------------------------------------
    def llm_choice(self, resolved: list[ResolvedSetting], agent: AgentPreset) -> tuple[str, str | None, bool]:
        """(fournisseur, modèle, modèle modifié par un profil)."""
        assert agent.llm is not None
        by_key = {r.setting.key: r for r in resolved}
        name = str(by_key[agent.llm.provider].value or "mock").strip().lower()
        model_r = by_key[agent.llm.model]
        model = str(model_r.value).strip() if model_r.value else None
        return name, model, model_r.origin != "preset"

    def llm(
        self, name: str, model: str | None, model_changed: bool, presets: PresetRegistry
    ) -> tuple[LLMProvider | None, str | None]:
        """Le fournisseur LLM du profil ; celui du démarrage s'il est identique (mêmes réglages)."""
        env_name = resolve_llm_name(self.settings)
        if name == env_name and (not model_changed or name == "mock"):
            return self.providers.llm, self.providers.errors.get("llm")
        key = (name, model if model_changed else None)
        with self._lock:
            cached = self._llms.get(key)
        if cached is not None:
            return cached, None
        try:
            llm = build_llm(self.settings, presets, name=name, model=model if model_changed else None)
        except ProviderSelectionError as exc:
            return None, str(exc)
        with self._lock:
            self._llms[key] = llm
        return llm, None

    def llm_for(self, agent_id: str, project_id: int | None) -> tuple[LLMProvider | None, str | None]:
        agent = self.agent(agent_id)
        if agent is None or agent.llm is None:
            return self.providers.llm, self.providers.errors.get("llm")
        with self.db.session_scope() as session:
            resolved, _ = self.resolved_for(session, agent, project_id)
        name, model, changed = self.llm_choice(resolved, agent)
        return self.llm(name, model, changed, self.presets_for(project_id))

    def llm_for_job(self, step: str, project_id: int | None) -> tuple[LLMProvider | None, str | None]:
        """LLM de l'agent qui mène les jobs `step` (ex. « script » → scénariste)."""
        agent = next((a for a in self.agents() if a.llm is not None and step in a.job_steps), None)
        if agent is None:
            return self.providers.llm, self.providers.errors.get("llm")
        return self.llm_for(agent.id, project_id)

    # --- export ---------------------------------------------------------------------------------
    def export_yaml(
        self,
        agent: AgentPreset,
        resolved: list[ResolvedSetting],
        knowledge: dict[str, Any],
        presets: PresetRegistry,
        *,
        scope: str,
        version: int,
    ) -> str:
        """Fichiers presets effectifs de l'agent, un document YAML par fichier (à recopier dans presets/)."""
        docs: list[str] = []
        profile_only = {r.setting.key: to_text(r.setting, r.value) for r in resolved if r.setting.file is None}
        head = [
            f"# Réglages de l'agent « {agent.name} » ({scope}, version {version}) exportés depuis « L'équipe ».",
            "# Chaque document ci-dessous est le contenu complet d'un fichier de presets/ (indiqué en tête).",
        ]
        meta: dict[str, Any] = {"agent": agent.id, **{k: v for k, v in profile_only.items()}}
        meta["knowledge"] = knowledge
        docs.append(
            "\n".join(head)
            + "\n# Hors presets (.env pour le fournisseur, profil pour le savoir-faire) :\n"
            + _yaml(meta)
        )
        for file in dict.fromkeys(s.file for s in agent.settings if s.file):
            if file == WORKFLOWS:
                for wf_id, wf in presets.workflows.items():
                    data = _dump(wf.preset)
                    docs.append(f"# presets/workflows/{wf_id}.yaml\n" + _yaml(data))
                continue
            data = file_data(presets, file)
            if data is None:
                continue
            target = "layouts/standard.yaml" if file == LAYOUTS else file
            docs.append(f"# presets/{target}\n" + _yaml(data))
        return "---\n".join(docs)


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_Dumper.add_representer(str, _str)


def _yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)
