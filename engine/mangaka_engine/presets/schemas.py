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


class NodeOutput(_Strict):
    """Sortie `[node, output]` d'un nœud du JSON API (lien entre nœuds)."""

    node: str
    output: int = Field(default=0, ge=0)


class ReferenceSlot(_Strict):
    """Emplacement d'image de référence : un nœud `LoadImage` (ou équivalent) du workflow.

    `node`/`input` reçoivent le nom du fichier envoyé à ComfyUI (`/upload/image`).
    Un emplacement inutilisé est retiré du workflow avec les nœuds de `remove` (ex. son
    redimensionnement), et toute entrée qui pointait vers un nœud retiré est supprimée.
    """

    node: str
    input: str = "image"
    remove: list[str] = Field(default_factory=list, description="Nœuds propres à l'emplacement, retirés avec lui")


class LoraChain(_Strict):
    """Point d'insertion des LoRA : une chaîne de chargeurs est branchée sur `model_from`.

    Chaque LoRA devient un nœud `class_type` dont l'entrée `model_input` reçoit le modèle
    précédent ; les nœuds qui consommaient `model_from` reçoivent la sortie du dernier.
    `clip_from` (optionnel) fait de même pour l'encodeur de texte (chargeurs type `LoraLoader`).
    """

    class_type: str = Field(min_length=1, description="Ex. LoraLoaderModelOnly")
    model_from: NodeOutput
    model_input: str = "model"
    name_input: str = "lora_name"
    strength_input: str = "strength_model"
    clip_from: NodeOutput | None = None
    clip_input: str = "clip"
    clip_strength_input: str = "strength_clip"
    clip_output: int = Field(default=1, ge=0)
    extra_inputs: dict[str, Any] = Field(default_factory=dict, description="Entrées constantes du chargeur")


REQUIRED_WORKFLOW_PARAMS = ("positive_prompt", "negative_prompt", "seed", "width", "height")


class WorkflowPreset(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str = ""
    workflow_file: str = Field(description="Chemin du JSON API ComfyUI, relatif au fichier preset")
    output_node: str = Field(description="Nœud SaveImage dont on récupère les images")
    mapping: dict[str, NodeInput]
    defaults: dict[str, Any] = Field(default_factory=dict)
    reference_images: list[ReferenceSlot] = Field(
        default_factory=list, description="Emplacements d'images de référence, dans l'ordre de remplissage"
    )
    lora_chain: LoraChain | None = None
    timeout_s: float = Field(default=600, gt=0, le=24 * 3600, description="Durée max d'une génération")

    @model_validator(mode="after")
    def _check_mapping(self) -> WorkflowPreset:
        missing = [p for p in REQUIRED_WORKFLOW_PARAMS if p not in self.mapping]
        if missing:
            raise ValueError(f"paramètres obligatoires absents du mapping : {', '.join(missing)}")
        unknown = [k for k in self.defaults if k not in self.mapping]
        if unknown:
            raise ValueError(f"valeurs par défaut sans mapping : {', '.join(unknown)}")
        nodes = [s.node for s in self.reference_images]
        if len(set(nodes)) != len(nodes):
            raise ValueError("reference_images : un même nœud est déclaré deux fois")
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
    # Workflow choisi automatiquement quand la case a des personnages avec images de référence.
    workflow_with_references: str | None = None


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


# --- Prompt image (étape 3) ---------------------------------------------------
class ImagePromptSettings(_Strict):
    """Construction du prompt final d'une case (voir pipeline/prompt.py)."""

    # Morceaux assemblés dans l'ordre ; un morceau dont une variable est vide est omis.
    # Variables : $shot, $description, $characters, $style.
    parts: list[str] = Field(
        default_factory=lambda: [
            "$shot.",
            "$description.",
            "Personnages : $characters.",
            "Style : $style.",
            "Case de manga, dessin encré, sans aucun texte ni bulle.",
        ]
    )
    character: str = Field(default="$name ($details)", description="Variables : $name, $details")
    character_separator: str = " ; "
    # Toujours présents dans le prompt négatif : le texte est posé au lettrage, jamais dessiné.
    forbidden_text_terms: list[str] = Field(
        default_factory=lambda: ["texte", "lettres", "bulles", "phylactères", "onomatopées", "filigrane", "signature"]
    )
    strip_quotes: bool = Field(default=True, description="Retire les répliques entre guillemets de la description")

    @field_validator("parts")
    @classmethod
    def _check_parts(cls, value: list[str]) -> list[str]:
        for part in value:
            if not string.Template(part).is_valid():
                raise ValueError("gabarit invalide : un « $ » isolé doit s'écrire « $$ »")
            unknown = set(string.Template(part).get_identifiers()) - {"shot", "description", "characters", "style"}
            if unknown:
                raise ValueError(f"variables inconnues : {', '.join(sorted(unknown))}")
        return value
