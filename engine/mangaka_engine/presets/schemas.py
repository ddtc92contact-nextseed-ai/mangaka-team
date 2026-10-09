"""Schémas Pydantic des presets (formats de page, gabarits, prompts, workflows ComfyUI, fournisseurs)."""

from __future__ import annotations

import string
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, field_validator, model_validator

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


# --- Découpage (étape 2) ------------------------------------------------------
class SplitNode(_Strict):
    """Nœud d'un gabarit : bandes (`rows`) ou colonnes (`cols`), avec leurs poids relatifs."""

    rows: list[PositiveFloat] | None = None
    cols: list[PositiveFloat] | None = None
    children: list[TreeNode] | None = None

    @model_validator(mode="after")
    def _check(self) -> SplitNode:
        if (self.rows is None) == (self.cols is None):
            raise ValueError("un nœud a soit « rows », soit « cols »")
        sizes = self.sizes
        if len(sizes) < 2:
            raise ValueError("au moins deux bandes ou colonnes par découpe")
        if self.children is not None and len(self.children) != len(sizes):
            raise ValueError("« children » doit avoir autant d'éléments que les poids")
        return self

    @property
    def axis(self) -> Literal["rows", "cols"]:
        return "rows" if self.rows is not None else "cols"

    @property
    def sizes(self) -> list[float]:
        return list(self.rows if self.rows is not None else self.cols or [])

    @property
    def nodes(self) -> list[TreeNode]:
        return list(self.children) if self.children is not None else ["panel"] * len(self.sizes)


TreeNode = Literal["panel"] | SplitNode
SplitNode.model_rebuild()


def count_panels(node: TreeNode) -> int:
    return 1 if node == "panel" else sum(count_panels(c) for c in node.nodes)  # type: ignore[union-attr]


class LayoutTemplate(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    tree: TreeNode

    @property
    def panel_count(self) -> int:
        return count_panels(self.tree)


class LayoutTemplateFile(_Strict):
    templates: list[LayoutTemplate] = Field(min_length=1)


class GenerationSize(_Strict):
    megapixels: float = Field(default=1.0, gt=0, le=16)
    multiple: int = Field(default=16, ge=1, le=256)
    min_side: int = Field(default=256, ge=16)


class BubbleZoneSettings(_Strict):
    padding_mm: float = Field(default=2, ge=0)
    min_fraction: float = Field(default=0.10, gt=0, le=1)
    max_fraction: float = Field(default=0.40, gt=0, le=1)
    full_at_chars: int = Field(default=240, ge=1)
    width_fraction: float = Field(default=0.55, gt=0, le=1)
    max_height_fraction: float = Field(default=0.60, gt=0, le=1)

    @model_validator(mode="after")
    def _check(self) -> BubbleZoneSettings:
        if self.min_fraction > self.max_fraction:
            raise ValueError("min_fraction doit être ≤ max_fraction")
        return self


class LayoutSettings(_Strict):
    min_panel_mm: float = Field(default=20, gt=0)
    generation: GenerationSize = Field(default_factory=GenerationSize)
    bubble_zone: BubbleZoneSettings = Field(default_factory=BubbleZoneSettings)


# --- Prompts LLM --------------------------------------------------------------
class PromptPreset(_Strict):
    """Gabarits `string.Template` ($variable) d'une étape LLM."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = ""
    system: str
    user: str
    retry: str
    max_retries: int = Field(default=2, ge=0, le=2)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_previous_chapters: int = Field(default=8, ge=0, le=100)

    @field_validator("system", "user", "retry")
    @classmethod
    def _check_template(cls, value: str) -> str:
        if not string.Template(value).is_valid():
            raise ValueError("gabarit invalide : un « $ » isolé doit s'écrire « $$ »")
        return value

    def variables(self, part: Literal["system", "user", "retry"]) -> set[str]:
        return set(string.Template(getattr(self, part)).get_identifiers())
