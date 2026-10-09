"""Schémas Pydantic des presets (formats de page, workflows ComfyUI, fournisseurs)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

MM_PER_INCH = 25.4


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Margins(_Strict):
    top: float = Field(ge=0)
    bottom: float = Field(ge=0)
    inner: float = Field(ge=0, description="Côté reliure")
    outer: float = Field(ge=0)


class Gutters(_Strict):
    horizontal: float = Field(ge=0, description="Espace entre deux rangées de cases")
    vertical: float = Field(ge=0, description="Espace entre deux cases d'une même rangée")


class PageFormat(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    dpi: int = Field(ge=72, le=1200)
    bleed_mm: float = Field(default=0, ge=0)
    margins_mm: Margins
    gutters_mm: Gutters

    @model_validator(mode="after")
    def _check_live_area(self) -> PageFormat:
        m = self.margins_mm
        if m.inner + m.outer >= self.width_mm:
            raise ValueError("les marges intérieure + extérieure dépassent la largeur de page")
        if m.top + m.bottom >= self.height_mm:
            raise ValueError("les marges haut + bas dépassent la hauteur de page")
        return self

    def mm_to_px(self, mm: float) -> int:
        return round(mm / MM_PER_INCH * self.dpi)

    @property
    def width_px(self) -> int:
        return self.mm_to_px(self.width_mm)

    @property
    def height_px(self) -> int:
        return self.mm_to_px(self.height_mm)


class NodeInput(_Strict):
    """Pointe vers `workflow[node]["inputs"][input]` dans le JSON API ComfyUI."""

    node: str
    input: str


REQUIRED_WORKFLOW_PARAMS = ("positive_prompt", "negative_prompt", "seed", "width", "height")


class WorkflowPreset(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str = ""
    workflow_file: str = Field(description="Chemin du JSON API ComfyUI, relatif au fichier preset")
    output_node: str = Field(description="Nœud SaveImage dont on récupère les images")
    mapping: dict[str, NodeInput]
    defaults: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_mapping(self) -> WorkflowPreset:
        missing = [p for p in REQUIRED_WORKFLOW_PARAMS if p not in self.mapping]
        if missing:
            raise ValueError(f"paramètres obligatoires absents du mapping : {', '.join(missing)}")
        unknown = [k for k in self.defaults if k not in self.mapping]
        if unknown:
            raise ValueError(f"valeurs par défaut sans mapping : {', '.join(unknown)}")
        return self


class DeepSeekPreset(_Strict):
    base_url: str
    model: str
    timeout_s: float = Field(default=60, gt=0)
    temperature: float = Field(default=0.7, ge=0, le=2)
    supports_images: bool = False


class OllamaPreset(_Strict):
    base_url: str
    vision_model: str
    keep_alive: int | str = 0
    timeout_s: float = Field(default=120, gt=0)


class ProvidersPreset(_Strict):
    deepseek: DeepSeekPreset
    ollama: OllamaPreset | None = None


class Defaults(_Strict):
    page_format: str
    workflow: str
