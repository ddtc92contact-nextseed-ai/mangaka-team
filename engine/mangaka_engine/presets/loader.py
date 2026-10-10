"""Chargement et validation des presets depuis le dossier `presets/`.

Arborescence attendue :

    presets/
      defaults.yaml            # presets par défaut des nouvelles séries
      providers.yaml           # paramètres des fournisseurs (modèle LLM, URL…)
      layout.yaml              # paramètres du découpage (zones de bulles, taille de génération…)
      image_prompt.yaml        # construction du prompt final des cases (étape 3)
      fonts.yaml + fonts/      # polices de lettrage (OFL) et style de texte par type de bulle
      lettering.yaml           # formes et placement des bulles, assemblage, repères de coupe
      qc.yaml                  # contrôle qualité des cases (étape 4) : seuils, poids, règles
      knowledge.yaml           # savoir-faire : découpage, recherche hybride, collections par agent
      page_formats/*.yaml      # formats de page
      layouts/*.yaml           # gabarits de planche
      layout_styles/*.yaml     # grammaires de mise en page par série (biais, gouttières, gabarits favoris)
      prompts/*.yaml           # prompts des étapes LLM
      workflows/*.yaml         # workflows ComfyUI (+ leur JSON API)
      upscalers/*.yaml         # agrandisseurs de la finition d'impression (+ leur JSON API)
      agents/*.yaml            # agents du pipeline (écran « L'équipe ») : rôle et réglages éditables
      reference_sheets/*.yaml  # fiches de référence générées (portrait, turnaround, plan large…)

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

from .schemas import (
    AgentPreset,
    Defaults,
    FontsPreset,
    ImagePromptSettings,
    KnowledgeSettings,
    LayoutSettings,
    LayoutStyle,
    LayoutTemplate,
    LayoutTemplateFile,
    LetteringSettings,
    PageFormat,
    PromptPreset,
    ProvidersPreset,
    QCSettings,
    ReferenceSheet,
    UpscalerPreset,
    WorkflowPreset,
)


class PresetError(Exception):
    """Preset introuvable ou invalide (message lisible, en français)."""


@dataclass
class LoadedWorkflow:
    preset: WorkflowPreset
    workflow: dict[str, Any]
    source: Path
    preset_path: Path | None = None  # YAML du preset


@dataclass
class LoadedUpscaler:
    preset: UpscalerPreset
    workflow: dict[str, Any]
    source: Path
    preset_path: Path | None = None


@dataclass
class PresetIssue:
    file: str
    message: str


@dataclass
class PresetRegistry:
    root: Path
    page_formats: dict[str, PageFormat] = field(default_factory=dict)
    workflows: dict[str, LoadedWorkflow] = field(default_factory=dict)
    upscalers: dict[str, LoadedUpscaler] = field(default_factory=dict)
    layout_templates: dict[str, LayoutTemplate] = field(default_factory=dict)
    layout_styles: dict[str, LayoutStyle] = field(default_factory=dict)
    prompts: dict[str, PromptPreset] = field(default_factory=dict)
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    image_prompt: ImagePromptSettings = field(default_factory=ImagePromptSettings)
    fonts: FontsPreset | None = None
    lettering: LetteringSettings = field(default_factory=LetteringSettings)
    providers: ProvidersPreset | None = None
    qc: QCSettings | None = None
    knowledge: KnowledgeSettings = field(default_factory=KnowledgeSettings)
    defaults: Defaults | None = None
    agents: dict[str, AgentPreset] = field(default_factory=dict)
    reference_sheets: dict[str, ReferenceSheet] = field(default_factory=dict)
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

    def upscaler(self, preset_id: str) -> LoadedUpscaler:
        try:
            return self.upscalers[preset_id]
        except KeyError:
            raise PresetError(f"agrandisseur inconnu : « {preset_id} »") from None

    @property
    def default_upscaler(self) -> str | None:
        """Agrandisseur de la finition d'impression : celui de defaults.yaml (None si absent ou inconnu)."""
        if self.defaults and self.defaults.upscaler in self.upscalers:
            return self.defaults.upscaler
        return None

    def layout_template(self, preset_id: str) -> LayoutTemplate:
        try:
            return self.layout_templates[preset_id]
        except KeyError:
            raise PresetError(f"gabarit de planche inconnu : « {preset_id} »") from None

    def layout_style(self, preset_id: str) -> LayoutStyle:
        try:
            return self.layout_styles[preset_id]
        except KeyError:
            raise PresetError(f"style de mise en page inconnu : « {preset_id} »") from None

    @property
    def default_layout_style(self) -> str | None:
        """Style des nouvelles séries : celui de defaults.yaml, sinon le premier disponible."""
        if self.defaults and self.defaults.layout_style in self.layout_styles:
            return self.defaults.layout_style
        return next(iter(self.layout_styles), None)

    def reference_sheet(self, sheet_id: str) -> ReferenceSheet:
        try:
            return self.reference_sheets[sheet_id]
        except KeyError:
            raise PresetError(f"type de fiche de référence inconnu : « {sheet_id} »") from None

    def prompt(self, preset_id: str) -> PromptPreset:
        try:
            return self.prompts[preset_id]
        except KeyError:
            raise PresetError(f"prompt introuvable : presets/prompts/{preset_id}.yaml") from None

    def require_fonts(self) -> FontsPreset:
        if self.fonts is None:
            raise PresetError("presets/fonts.yaml absent ou invalide : lettrage impossible")
        return self.fonts

    def font_path(self, font_id: str, weight: int | None = None, italic: bool = False) -> Path:
        """Fichier d'une police ; pour une famille statique, celui de la graisse (gras ≥ 600) et du style."""
        fonts = self.require_fonts()
        try:
            font = fonts.fonts[font_id]
        except KeyError:
            raise PresetError(f"police inconnue : « {font_id} »") from None
        try:
            return (self.root / font.resolve(weight, italic)).resolve()
        except ValueError as exc:
            raise PresetError(str(exc)) from None

    def require_qc(self) -> QCSettings:
        if self.qc is None:
            raise PresetError("presets/qc.yaml absent ou invalide : contrôle qualité indisponible")
        return self.qc

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

        reg._check_reference_pairs()
        # Ordre des listes déroulantes : texte → image d'abord, puis avec références ; par nom ensuite
        # (« … · Qualité » avant « … · Rapide »).
        reg.workflows = dict(
            sorted(reg.workflows.items(), key=lambda kv: (bool(kv[1].preset.reference_images), kv[1].preset.name))
        )

        for path in sorted((root / "upscalers").glob("*.y*ml")):
            up = reg._load_upscaler(path)
            if up is not None:
                reg._register(reg.upscalers, up.preset.id, up, path)

        for path in sorted((root / "layouts").glob("*.y*ml")):
            lib = reg._parse(path, LayoutTemplateFile)
            for tpl in lib.templates if lib else []:
                reg._register(reg.layout_templates, tpl.id, tpl, path)

        for path in sorted((root / "layout_styles").glob("*.y*ml")):
            style = reg._parse(path, LayoutStyle)
            if style is not None:
                reg._register(reg.layout_styles, style.id, style, path)

        for path in sorted((root / "prompts").glob("*.y*ml")):
            prompt = reg._parse(path, PromptPreset)
            if prompt is not None:
                reg._register(reg.prompts, prompt.id, prompt, path)

        layout_path = root / "layout.yaml"
        if layout_path.exists():
            layout = reg._parse(layout_path, LayoutSettings)
            if layout is not None:
                reg.layout = layout
        else:
            reg.issues.append(PresetIssue(reg._rel(layout_path), "fichier absent : valeurs par défaut utilisées"))

        image_prompt_path = root / "image_prompt.yaml"
        if image_prompt_path.exists():
            image_prompt = reg._parse(image_prompt_path, ImagePromptSettings)
            if image_prompt is not None:
                reg.image_prompt = image_prompt

        fonts_path = root / "fonts.yaml"
        if fonts_path.exists():
            fonts = reg._parse(fonts_path, FontsPreset)
            if fonts is not None:
                missing = [f for font in fonts.fonts.values() for f in font.files() if not (root / f).is_file()]
                if missing:
                    reg.issues.append(
                        PresetIssue(reg._rel(fonts_path), f"fichiers de police absents : {', '.join(missing)}")
                    )
                else:
                    reg.fonts = fonts
        else:
            reg.issues.append(PresetIssue(reg._rel(fonts_path), "fichier absent : lettrage indisponible"))

        lettering_path = root / "lettering.yaml"
        if lettering_path.exists():
            lettering = reg._parse(lettering_path, LetteringSettings)
            if lettering is not None:
                reg.lettering = lettering

        qc_path = root / "qc.yaml"
        if qc_path.exists():
            reg.qc = reg._parse(qc_path, QCSettings)
        else:
            reg.issues.append(PresetIssue(reg._rel(qc_path), "fichier absent : contrôle qualité indisponible"))

        knowledge_path = root / "knowledge.yaml"
        if knowledge_path.exists():
            knowledge = reg._parse(knowledge_path, KnowledgeSettings)
            if knowledge is not None:
                reg.knowledge = knowledge

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
                elif defaults.workflow_with_references and defaults.workflow_with_references not in reg.workflows:
                    reg.issues.append(
                        PresetIssue(reg._rel(defaults_path), f"workflow inconnu : {defaults.workflow_with_references}")
                    )
                    reg.defaults = defaults.model_copy(update={"workflow_with_references": None})
                elif defaults.workflow_quality and defaults.workflow_quality not in reg.workflows:
                    reg.issues.append(
                        PresetIssue(reg._rel(defaults_path), f"workflow inconnu : {defaults.workflow_quality}")
                    )
                    reg.defaults = defaults.model_copy(update={"workflow_quality": None})
                elif defaults.layout_style and defaults.layout_style not in reg.layout_styles:
                    reg.issues.append(
                        PresetIssue(reg._rel(defaults_path), f"style de mise en page inconnu : {defaults.layout_style}")
                    )
                    reg.defaults = defaults.model_copy(update={"layout_style": None})
                else:
                    reg.defaults = defaults
                if reg.defaults is not None and reg.defaults.upscaler and reg.defaults.upscaler not in reg.upscalers:
                    reg.issues.append(
                        PresetIssue(reg._rel(defaults_path), f"agrandisseur inconnu : {reg.defaults.upscaler}")
                    )
                    reg.defaults = reg.defaults.model_copy(update={"upscaler": None})
        else:
            reg.issues.append(PresetIssue(reg._rel(defaults_path), "fichier absent"))

        for path in sorted((root / "agents").glob("*.y*ml")):
            agent = reg._parse(path, AgentPreset)
            if agent is not None:
                reg._register(reg.agents, agent.id, agent, path)

        for path in sorted((root / "reference_sheets").glob("*.y*ml")):
            sheet = reg._parse(path, ReferenceSheet)
            if sheet is None:
                continue
            if sheet.workflow is not None and sheet.workflow not in reg.workflows:
                reg.issues.append(PresetIssue(reg._rel(path), f"workflow inconnu : {sheet.workflow}"))
                continue
            reg._register(reg.reference_sheets, sheet.id, sheet, path)
        reg.reference_sheets = dict(sorted(reg.reference_sheets.items(), key=lambda kv: (kv[1].order, kv[1].name)))
        return reg

    def _check_reference_pairs(self) -> None:
        """`with_references` doit désigner un workflow chargé qui a des emplacements de référence.

        Le workflow reste chargé (ses cases sans référence se génèrent), mais une case avec
        références échouera avec un message clair : jamais de repli sur un autre palier.
        """
        for wf in self.workflows.values():
            target = wf.preset.with_references
            if target is None:
                continue
            other = self.workflows.get(target)
            if other is None:
                problem = f"with_references : workflow inconnu ou invalide : {target}"
            elif not other.preset.reference_images:
                problem = f"with_references : le workflow {target} n'a pas d'emplacement de référence"
            else:
                continue
            self.issues.append(PresetIssue(self._rel(wf.preset_path or wf.source), problem))

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

    def _load_upscaler(self, path: Path) -> LoadedUpscaler | None:
        preset = self._parse(path, UpscalerPreset)
        workflow = self._load_json(path, preset) if preset is not None else None
        if preset is None or workflow is None:
            return None
        source = (path.parent / preset.workflow_file).resolve()
        return LoadedUpscaler(preset=preset, workflow=workflow, source=source, preset_path=path)

    def _load_json(self, path: Path, preset: WorkflowPreset | UpscalerPreset) -> dict[str, Any] | None:
        """JSON API d'un preset, vérifié contre son mapping (erreur notée dans `issues`)."""
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
        return workflow

    def _load_workflow(self, path: Path) -> LoadedWorkflow | None:
        preset = self._parse(path, WorkflowPreset)
        workflow = self._load_json(path, preset) if preset is not None else None
        if preset is None or workflow is None:
            return None
        source = (path.parent / preset.workflow_file).resolve()
        return LoadedWorkflow(preset=preset, workflow=workflow, source=source, preset_path=path)


def check_workflow_mapping(preset: WorkflowPreset | UpscalerPreset, workflow: Any) -> list[str]:
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
    for i, slot in enumerate(preset.reference_images, start=1):
        node = workflow.get(slot.node)
        if not isinstance(node, dict):
            errors.append(f"référence {i} : nœud {slot.node} absent du workflow")
        elif slot.input not in node.get("inputs", {}):
            errors.append(f"référence {i} : entrée « {slot.input} » absente du nœud {slot.node}")
        mapped = {t.node for t in preset.mapping.values()} | {preset.output_node}
        for extra in [slot.node, *slot.remove]:
            if extra not in workflow:
                errors.append(f"référence {i} : nœud {extra} absent du workflow")
            elif extra in mapped:
                errors.append(f"référence {i} : le nœud {extra} est mappé, il ne peut pas être retiré")
    chain = preset.lora_chain
    if chain is not None:
        for label, src in (("model_from", chain.model_from), ("clip_from", chain.clip_from)):
            if src is not None and not isinstance(workflow.get(src.node), dict):
                errors.append(f"lora_chain.{label} : nœud {src.node} absent du workflow")
    return errors


def format_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(racine)"
        msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc} : {msg}")
    return " ; ".join(parts)
