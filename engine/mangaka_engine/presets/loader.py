"""Chargement et validation des presets depuis le dossier `presets/`.

Arborescence attendue :

    presets/
      defaults.yaml            # presets par défaut des nouveaux projets
      providers.yaml           # paramètres des fournisseurs (modèle LLM, URL…)
      page_formats/*.yaml      # formats de page
      workflows/*.yaml         # workflows ComfyUI (+ leur JSON API)

Un preset invalide n'empêche pas le moteur de démarrer : il est écarté et
l'erreur est exposée via `GET /presets` et `GET /health`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from .schemas import Defaults, PageFormat, ProvidersPreset, WorkflowPreset


class PresetError(Exception):
    """Preset introuvable ou invalide (message lisible, en français)."""


@dataclass
class LoadedWorkflow:
    preset: WorkflowPreset
    workflow: dict[str, Any]
    source: Path


@dataclass
class PresetIssue:
    file: str
    message: str


@dataclass
class PresetRegistry:
    root: Path
    page_formats: dict[str, PageFormat] = field(default_factory=dict)
    workflows: dict[str, LoadedWorkflow] = field(default_factory=dict)
    providers: ProvidersPreset | None = None
    defaults: Defaults | None = None
    issues: list[PresetIssue] = field(default_factory=list)

    # --- accès -----------------------------------------------------------
    def page_format(self, preset_id: str) -> PageFormat:
        try:
            return self.page_formats[preset_id]
        except KeyError:
            raise PresetError(f"format de page inconnu : « {preset_id} »") from None

    def workflow(self, preset_id: str) -> LoadedWorkflow:
        try:
            return self.workflows[preset_id]
        except KeyError:
            raise PresetError(f"workflow inconnu : « {preset_id} »") from None

    def require_providers(self) -> ProvidersPreset:
        if self.providers is None:
            raise PresetError("presets/providers.yaml absent ou invalide")
        return self.providers

    # --- chargement ------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> PresetRegistry:
        reg = cls(root=root)
        if not root.is_dir():
            reg.issues.append(PresetIssue(str(root), "dossier de presets introuvable"))
            return reg

        for path in sorted((root / "page_formats").glob("*.y*ml")):
            fmt = reg._parse(path, PageFormat)
            if fmt is not None:
                reg._register(reg.page_formats, fmt.id, fmt, path)

        for path in sorted((root / "workflows").glob("*.y*ml")):
            wf = reg._load_workflow(path)
            if wf is not None:
                reg._register(reg.workflows, wf.preset.id, wf, path)

        providers_path = root / "providers.yaml"
        if providers_path.exists():
            reg.providers = reg._parse(providers_path, ProvidersPreset)
        else:
            reg.issues.append(PresetIssue(reg._rel(providers_path), "fichier absent"))

        defaults_path = root / "defaults.yaml"
        if defaults_path.exists():
            defaults = reg._parse(defaults_path, Defaults)
            if defaults is not None:
                if defaults.page_format not in reg.page_formats:
                    reg.issues.append(
                        PresetIssue(reg._rel(defaults_path), f"format de page inconnu : {defaults.page_format}")
                    )
                elif defaults.workflow not in reg.workflows:
                    reg.issues.append(PresetIssue(reg._rel(defaults_path), f"workflow inconnu : {defaults.workflow}"))
                else:
                    reg.defaults = defaults
        else:
            reg.issues.append(PresetIssue(reg._rel(defaults_path), "fichier absent"))
        return reg

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def _register(self, target: dict[str, Any], key: str, value: Any, path: Path) -> None:
        if key in target:
            self.issues.append(PresetIssue(self._rel(path), f"identifiant en double : {key}"))
            return
        target[key] = value

    def _read_yaml(self, path: Path) -> Any:
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            self.issues.append(PresetIssue(self._rel(path), f"YAML invalide : {exc}"))
            return None

    def _parse[M: BaseModel](self, path: Path, model: type[M]) -> M | None:
        data = self._read_yaml(path)
        if data is None:
            return None
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            self.issues.append(PresetIssue(self._rel(path), format_validation_error(exc)))
            return None

    def _load_workflow(self, path: Path) -> LoadedWorkflow | None:
        preset = self._parse(path, WorkflowPreset)
        if preset is None:
            return None
        json_path = (path.parent / preset.workflow_file).resolve()
        try:
            workflow = json.loads(json_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.issues.append(PresetIssue(self._rel(path), f"JSON du workflow introuvable : {preset.workflow_file}"))
            return None
        except json.JSONDecodeError as exc:
            self.issues.append(PresetIssue(self._rel(path), f"JSON du workflow invalide : {exc}"))
            return None
        errors = check_workflow_mapping(preset, workflow)
        if errors:
            self.issues.append(PresetIssue(self._rel(path), " ; ".join(errors)))
            return None
        return LoadedWorkflow(preset=preset, workflow=workflow, source=json_path)


def check_workflow_mapping(preset: WorkflowPreset, workflow: Any) -> list[str]:
    """Vérifie que chaque paramètre mappé pointe vers un nœud/une entrée existants."""
    if not isinstance(workflow, dict) or not workflow:
        return ["le JSON du workflow doit être un objet au format API ComfyUI"]
    errors: list[str] = []
    for param, target in preset.mapping.items():
        node = workflow.get(target.node)
        if not isinstance(node, dict):
            errors.append(f"{param} : nœud {target.node} absent du workflow")
        elif target.input not in node.get("inputs", {}):
            errors.append(f"{param} : entrée « {target.input} » absente du nœud {target.node}")
    if preset.output_node not in workflow:
        errors.append(f"nœud de sortie {preset.output_node} absent du workflow")
    return errors


def format_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(racine)"
        msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc} : {msg}")
    return " ; ".join(parts)
