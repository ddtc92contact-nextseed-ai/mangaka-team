"""Schémas Pydantic des presets (formats de page, gabarits, prompts, workflows ComfyUI, fournisseurs)."""

from __future__ import annotations

import string
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, field_validator, model_validator

from ..providers.qc.dghs import check_detector_options

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
WorkflowRole = Literal["generation", "croquis", "propre"]
# Un preset de réparation (inpainting) part de l'image source : pas de taille, mais un débruitage partiel.
REQUIRED_INPAINT_PARAMS = ("positive_prompt", "negative_prompt", "seed", "denoise")
REPAIR_TARGETS = ("face", "hand", "zone")
REPAIR_PROMPT_VARIABLES = frozenset({"target", "character", "description", "style"})


class InpaintSettings(_Strict):
    """Réparation ciblée (inpainting) : ce bloc fait d'un workflow un preset de réparation.

    `source_image` reçoit l'image de la version à réparer, `mask_image` le masque (blanc = zone à
    repeindre, déjà agrandi et adouci par le moteur). Le résultat est recollé sur l'original hors
    ComfyUI : hors du masque adouci, les pixels ne bougent pas.
    """

    source_image: NodeInput
    mask_image: NodeInput
    grow_px: int = Field(default=24, ge=0, le=256, description="Marge ajoutée autour de la zone (px)")
    feather_px: int = Field(default=16, ge=0, le=128, description="Largeur des bords fondus (px)")
    # Prompt de réparation prérempli : morceaux assemblés comme `image_prompt.yaml` (un morceau dont
    # une variable est vide est omis). Variables : $target, $character, $description, $style.
    prompt_parts: list[str] = Field(
        default_factory=lambda: ["$target.", "$character.", "$description.", "Style : $style."]
    )
    # Texte de $target selon la zone : visage, main, zone dessinée à la main.
    targets: dict[str, str] = Field(default_factory=dict)

    @field_validator("prompt_parts")
    @classmethod
    def _check_parts(cls, parts: list[str]) -> list[str]:
        for part in parts:
            unknown = set(string.Template(part).get_identifiers()) - REPAIR_PROMPT_VARIABLES
            if unknown:
                raise ValueError(f"variable inconnue dans prompt_parts : ${', $'.join(sorted(unknown))}")
        return parts

    @field_validator("targets")
    @classmethod
    def _check_targets(cls, targets: dict[str, str]) -> dict[str, str]:
        unknown = [k for k in targets if k not in REPAIR_TARGETS]
        if unknown:
            raise ValueError(f"zone inconnue : {', '.join(unknown)} (possibles : {', '.join(REPAIR_TARGETS)})")
        return targets


class WorkflowTier(_Strict):
    """Palier d'un workflow (Turbo, Rapide, Qualité) : affiché sur les versions et dans la fiche série."""

    name: str = Field(min_length=1, description="Nom court affiché sur les versions (« Turbo »)")
    # Libellé dans la fiche série ; absent = workflow non proposé comme palier (ex. « avec références »).
    choice: str | None = None
    order: int = 0


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
    # Workflow du même palier (mêmes modèles) pour une case qui a des images de référence : une
    # série « Rapide » ne retombe jamais sur le workflow de référence « Qualité » de defaults.yaml.
    with_references: str | None = Field(
        default=None, description="Id du workflow utilisé quand la case a des images de référence"
    )
    # Case d'essai (« Générer une case d'essai ») : paramètres mappés, prompt positif compris.
    trial: dict[str, Any] = Field(default_factory=dict)
    tier: WorkflowTier | None = None
    # Durée estimée d'une case (s), utilisée tant que les vraies durées de ce preset sont trop peu nombreuses.
    estimated_s: float | None = Field(default=None, gt=0)
    # Rôle : `generation` (palier de série), `croquis` (brouillon rapide de la composition, jamais
    # assemblé) ou `propre` (version finale tirée d'une image de composition : croquis validé).
    role: WorkflowRole = "generation"
    # Croquis : grand côté de l'image en px (même ratio que la case) ; absent = taille de la mise en page.
    long_side: int | None = Field(default=None, ge=64, le=4096)
    # Propre : nœud qui reçoit l'image de composition (croquis validé envoyé à ComfyUI).
    source_image: NodeInput | None = None
    # Palier de série : workflow « propre depuis croquis » du même palier (« Passer au propre »).
    from_sketch: str | None = None
    # Preset de réparation ciblée (inpainting) du même palier, pour les versions produites par ce workflow.
    inpaint_with: str | None = Field(default=None, description="Id du preset de réparation (bloc `inpaint`)")
    # Présent = ce workflow est un preset de réparation (jamais proposé pour générer une case).
    inpaint: InpaintSettings | None = None

    @property
    def is_inpaint(self) -> bool:
        return self.inpaint is not None

    @model_validator(mode="after")
    def _check_mapping(self) -> WorkflowPreset:
        required = REQUIRED_INPAINT_PARAMS if self.inpaint is not None else REQUIRED_WORKFLOW_PARAMS
        missing = [p for p in required if p not in self.mapping]
        if missing:
            raise ValueError(f"paramètres obligatoires absents du mapping : {', '.join(missing)}")
        unknown = [k for k in self.defaults if k not in self.mapping]
        if unknown:
            raise ValueError(f"valeurs par défaut sans mapping : {', '.join(unknown)}")
        unknown = [k for k in self.trial if k not in self.mapping]
        if unknown:
            raise ValueError(f"trial : paramètres sans mapping : {', '.join(unknown)}")
        if self.trial and not str(self.trial.get("positive_prompt") or "").strip():
            raise ValueError("trial : positive_prompt est obligatoire")
        if self.with_references == self.id:
            raise ValueError("with_references ne peut pas désigner le workflow lui-même")
        if self.from_sketch == self.id:
            raise ValueError("from_sketch ne peut pas désigner le workflow lui-même")
        if self.role == "propre":
            if self.source_image is None:
                raise ValueError("un workflow « propre » doit déclarer source_image (image de composition)")
            if "denoise" not in self.mapping:
                raise ValueError("un workflow « propre » doit mapper denoise (débruitage partiel)")
        elif self.source_image is not None:
            raise ValueError("source_image est réservé aux workflows « propre »")
        if self.long_side is not None and self.role != "croquis":
            raise ValueError("long_side est réservé aux workflows « croquis »")
        if self.inpaint is not None and (self.trial or self.with_references or self.inpaint_with):
            raise ValueError("un preset de réparation (inpaint) n'a ni trial, ni with_references, ni inpaint_with")
        if self.inpaint is not None and self.tier is not None and self.tier.choice:
            raise ValueError("un preset de réparation (inpaint) ne peut pas être proposé comme palier (tier.choice)")
        nodes = [s.node for s in self.reference_images]
        if len(set(nodes)) != len(nodes):
            raise ValueError("reference_images : un même nœud est déclaré deux fois")
        return self


REQUIRED_UPSCALER_PARAMS = ("image", "width", "height")


class UpscalerPreset(_Strict):
    """Agrandissement d'une case avant l'assemblage (finition d'impression), `presets/upscalers/`.

    Le JSON API charge l'image de la version retenue (`image` : un `LoadImage`), l'agrandit avec un
    modèle et la ramène à la taille finale exacte (`width` / `height`), calculée par case.
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str = ""
    workflow_file: str = Field(description="Chemin du JSON API ComfyUI, relatif au fichier preset")
    output_node: str = Field(description="Nœud SaveImage dont on récupère l'image agrandie")
    mapping: dict[str, NodeInput]
    defaults: dict[str, Any] = Field(default_factory=dict)
    # Facteur natif du modèle (×4 pour un ESRGAN 4x) : informatif, la taille finale reste exacte.
    model_scale: float | None = Field(default=None, gt=0)
    # Option « haute fidélité » (lente) : jamais choisie par défaut sans le dire.
    high_fidelity: bool = False
    timeout_s: float = Field(default=600, gt=0, le=24 * 3600, description="Durée max d'un agrandissement")
    estimated_s: float | None = Field(default=None, gt=0)

    # Même interface que WorkflowPreset pour les vérifications communes (mapping, test de connexion).
    @property
    def reference_images(self) -> list[ReferenceSlot]:
        return []

    @property
    def lora_chain(self) -> LoraChain | None:
        return None

    @property
    def inpaint(self) -> InpaintSettings | None:
        return None

    @property
    def source_image(self) -> NodeInput | None:
        return None

    @model_validator(mode="after")
    def _check_mapping(self) -> UpscalerPreset:
        missing = [p for p in REQUIRED_UPSCALER_PARAMS if p not in self.mapping]
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
    # Modèle d'embeddings du savoir-faire (EMBEDDING_PROVIDER=ollama), ex. bge-m3 (multilingue, bon en français).
    embedding_model: str | None = None
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
    # Style de mise en page des nouvelles séries (presets/layout_styles/).
    layout_style: str | None = None
    # Palier de « Régénérer en Qualité » (atelier) ; son `with_references` sert aux cases avec références.
    workflow_quality: str | None = None
    # Palier croquis : activé pour les nouvelles séries, et workflow des croquis (rôle `croquis`).
    sketch_enabled: bool = True
    workflow_sketch: str | None = None
    # Finition d'impression : agrandisseur par défaut (presets/upscalers/), surchargeable par série.
    upscaler: str | None = None
    # Pas d'agrandissement si la case atteint déjà cette part du dpi cible (0,9 × 300 = 270 dpi).
    finishing_tolerance: float = Field(default=0.9, gt=0, le=1)
    # Preset de réparation ciblée pour un workflow qui ne déclare pas `inpaint_with`.
    workflow_inpaint: str | None = None


# --- Découpage (étape 2) ------------------------------------------------------
class SplitNode(_Strict):
    """Nœud d'un gabarit : bandes (`rows`) ou colonnes (`cols`), avec leurs poids relatifs.

    `slants` (facultatif) met les découpes en biais : pour chaque découpe (une de moins que de
    poids), le décalage en mm de ses deux extrémités par rapport à la découpe droite, le long de
    l'axe découpé — [gauche, droite] pour une découpe entre deux bandes, [haut, bas] entre deux
    colonnes, dans le sens de lecture. Absent ou [0, 0] = découpe droite.
    """

    rows: list[PositiveFloat] | None = None
    cols: list[PositiveFloat] | None = None
    children: list[TreeNode] | None = None
    slants: list[tuple[float, float]] | None = None

    @model_validator(mode="after")
    def _check(self) -> SplitNode:
        if (self.rows is None) == (self.cols is None):
            raise ValueError("un nœud a soit « rows », soit « cols »")
        sizes = self.sizes
        if len(sizes) < 2:
            raise ValueError("au moins deux bandes ou colonnes par découpe")
        if self.children is not None and len(self.children) != len(sizes):
            raise ValueError("« children » doit avoir autant d'éléments que les poids")
        if self.slants is not None and len(self.slants) != len(sizes) - 1:
            raise ValueError("« slants » doit avoir une entrée par découpe (une de moins que les poids)")
        return self

    @property
    def cut_slants(self) -> list[tuple[float, float]]:
        return list(self.slants) if self.slants is not None else [(0.0, 0.0)] * (len(self.sizes) - 1)

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


class RegenerationSettings(_Strict):
    # Après un changement de géométrie (biais, gouttière), une case garde son image ; on ne conseille
    # de la régénérer que si le ratio de sa boîte englobante s'écarte de plus de cette fraction de
    # celui de l'image retenue.
    ratio_threshold: float = Field(default=0.15, gt=0, le=10)


class LayoutSettings(_Strict):
    min_panel_mm: float = Field(default=20, gt=0)
    generation: GenerationSize = Field(default_factory=GenerationSize)
    bubble_zone: BubbleZoneSettings = Field(default_factory=BubbleZoneSettings)
    regeneration: RegenerationSettings = Field(default_factory=RegenerationSettings)


# --- Grammaire de mise en page par série (presets/layout_styles/) -------------
# Aucune valeur par défaut : chaque style écrit tout dans son YAML.
INTENSITIES = ("calme", "normal", "choc")
RYTHMES = ("lent", "normal", "rapide")
Intensity = Literal["calme", "normal", "choc"]
Rythme = Literal["lent", "normal", "rapide"]


class AngleRange(_Strict):
    min: float = Field(ge=0, le=30)
    max: float = Field(ge=0, le=30)

    @model_validator(mode="after")
    def _check(self) -> AngleRange:
        if self.min > self.max:
            raise ValueError("min doit être ≤ max")
        return self


class MmRange(_Strict):
    min: float = Field(ge=0, le=50)
    max: float = Field(ge=0, le=50)

    @model_validator(mode="after")
    def _check(self) -> MmRange:
        if self.min > self.max:
            raise ValueError("min doit être ≤ max")
        return self


class SlantRule(_Strict):
    """Probabilité qu'une découpe voisine de la case passe en biais, et angle tiré (degrés)."""

    probability: float = Field(ge=0, le=1)
    rows_deg: AngleRange = Field(description="Découpe entre deux bandes (ligne presque horizontale)")
    cols_deg: AngleRange = Field(description="Découpe entre deux colonnes (ligne presque verticale)")


class SlantTable(_Strict):
    # La règle d'une case : celle de son intensité si le scénario l'a donnée, sinon celle de son importance.
    by_importance: dict[Literal[1, 2, 3], SlantRule]
    by_intensity: dict[Intensity, SlantRule]

    @model_validator(mode="after")
    def _check(self) -> SlantTable:
        missing = [str(k) for k in (1, 2, 3) if k not in self.by_importance]
        missing += [k for k in INTENSITIES if k not in self.by_intensity]
        if missing:
            raise ValueError(f"règles absentes : {', '.join(missing)}")
        return self


class StyleGutters(_Strict):
    horizontal: MmRange
    vertical: MmRange


class RythmeRule(_Strict):
    slant_factor: float = Field(ge=0, le=10, description="Multiplie la probabilité de biais")
    size_contrast: float = Field(gt=0, le=10, description="Multiplie le contraste des tailles de case")


class FrameRule(_Strict):
    """Probabilités des options de cadre d'une case (tirées par page, graine de la mise en page)."""

    frameless: float = Field(ge=0, le=1, description="Case sans bord")
    bleed: float = Field(ge=0, le=1, description="Case au bord de la zone utile → fond perdu")
    inset: float = Field(ge=0, le=1, description="Case incrustée dans sa voisine (gros plan de réaction)")


class InsetRule(_Strict):
    """Géométrie d'une incrustation : petite case posée dans une case hôte (la précédente, sinon la suivante)."""

    size: float = Field(ge=0.15, le=0.6, description="Côtés de l'incrustation / côtés de l'hôte")
    margin_mm: float = Field(ge=0, le=30, description="Écart minimal avec les bords de l'hôte")
    min_side_mm: float = Field(gt=0, le=100, description="Plus petit côté accepté (sinon incrustation refusée)")
    max_per_page: int = Field(ge=0, le=4, description="Incrustations tirées au plus par page (imposées : sans limite)")
    min_page_panels: int = Field(ge=2, le=9, description="Pas d'incrustation tirée sur une page plus courte")
    # Plans éligibles au tirage (vide = tous) : l'incrustation sert aux gros plans de réaction.
    shot_types: list[str]


class FrameTable(_Strict):
    # La règle d'une case : celle de son intensité si le scénario l'a donnée, sinon celle de son importance.
    by_importance: dict[Literal[1, 2, 3], FrameRule]
    by_intensity: dict[Intensity, FrameRule]
    fade: float = Field(ge=0, le=1, description="Part des cases sans bord dont l'image se fond au papier")
    inset: InsetRule

    @model_validator(mode="after")
    def _check(self) -> FrameTable:
        missing = [str(k) for k in (1, 2, 3) if k not in self.by_importance]
        missing += [k for k in INTENSITIES if k not in self.by_intensity]
        if missing:
            raise ValueError(f"règles absentes : {', '.join(missing)}")
        return self


class LayoutStyle(_Strict):
    """Signature de mise en page d'une série : biais, gouttières, gabarits favoris, contraste."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str = ""
    # null = gouttières du format de page ; sinon largeur tirée (pas de 0,5 mm) par page.
    gutters_mm: StyleGutters | None
    slants: SlantTable
    # Exposant appliqué aux poids des cases avant le choix du gabarit : > 1 = grandes cases plus grandes.
    size_contrast: float = Field(gt=0, le=10)
    intensity_weight: dict[Intensity, float]
    # Variation aléatoire des poids de chaque découpe (0 = proportions exactes du gabarit).
    size_jitter: float = Field(ge=0, le=0.5)
    # 0 = toujours le gabarit le mieux adapté ; plus haut = choix plus varié parmi les bons gabarits.
    temperature: float = Field(ge=0, le=10)
    # Poids des gabarits (identifiant exact ou motif « 3-grand-* ») ; absent = default_template_weight.
    template_weights: dict[str, float] = Field(default_factory=dict)
    default_template_weight: float = Field(gt=0)
    avoid_repeat: bool = Field(description="Jamais deux mises en page identiques d'affilée")
    rythme: dict[Rythme, RythmeRule]
    # « Page choc » (pleine page / splash) décidée par la direction artistique : s'ajoute au rythme.
    page_choc: RythmeRule
    # Cases sans bord, à fond perdu, incrustées.
    frames: FrameTable

    @model_validator(mode="after")
    def _check(self) -> LayoutStyle:
        missing = [k for k in INTENSITIES if k not in self.intensity_weight]
        missing += [k for k in RYTHMES if k not in self.rythme]
        if missing:
            raise ValueError(f"valeurs absentes : {', '.join(missing)}")
        if any(w <= 0 for w in self.intensity_weight.values()):
            raise ValueError("intensity_weight : les poids doivent être > 0")
        if any(w < 0 for w in self.template_weights.values()):
            raise ValueError("template_weights : les poids doivent être ≥ 0")
        return self


# --- Lettrage (étape 5) -------------------------------------------------------
BUBBLE_KINDS = ("speech", "thought", "shout", "narration", "off")
HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


BOLD_FROM = 600  # graisse à partir de laquelle une famille statique prend son fichier gras (comme CSS)


class FontFile(_Strict):
    """Police de lettrage : un fichier (variable ou statique), ou une famille statique regular/gras/italique."""

    file: str = Field(description="Fichier TTF/OTF (regular), relatif à fonts.yaml")
    name: str = Field(description="Nom d'affichage")
    bold: str | None = Field(default=None, description="Fichier gras (graisse ≥ 600)")
    italic: str | None = Field(default=None, description="Fichier italique")
    bold_italic: str | None = Field(default=None, description="Fichier gras italique")

    def files(self) -> list[str]:
        return [f for f in (self.file, self.bold, self.italic, self.bold_italic) if f]

    def resolve(self, weight: int | None, italic: bool) -> str:
        """Fichier d'une graisse / d'un style. Faute de gras italique, l'italique (jamais le droit)."""
        bold = weight is not None and weight >= BOLD_FROM
        if italic:
            if bold and self.bold_italic:
                return self.bold_italic
            if self.italic is None:
                raise ValueError(f"« {self.name} » n'a pas de fichier italique")
            return self.italic
        return self.bold if bold and self.bold else self.file


class TextStyle(_Strict):
    """Style de texte d'un type de bulle (taille en points typographiques : indépendante du DPI)."""

    font: str
    weight: int | None = Field(
        default=None, ge=1, le=1000, description="Graisse (police variable, ou ≥ 600 = fichier gras d'une famille)"
    )
    italic: bool = Field(default=False, description="Fichier italique de la famille (obligatoire s'il est demandé)")
    size_pt: float = Field(gt=0, le=72)
    min_size_pt: float = Field(gt=0, le=72, description="Taille minimale lisible : en dessous, avertissement")
    step_pt: float = Field(default=0.5, gt=0, le=10)
    line_height: float = Field(default=1.1, gt=0.5, le=3)
    uppercase: bool = False
    color: str = Field(default="#000000", pattern=HEX_COLOR)

    @model_validator(mode="after")
    def _check(self) -> TextStyle:
        if self.min_size_pt > self.size_pt:
            raise ValueError("min_size_pt doit être ≤ size_pt")
        return self


class Hyphenation(_Strict):
    language: str = "fr"
    min_word_chars: int = Field(default=6, ge=2, description="Mots plus courts : jamais coupés")
    # Un mot qui ne tient pas en fin de ligne n'est coupé que si la ligne resterait vide à plus de
    # cette proportion ; sinon il passe entier à la ligne suivante.
    min_gap: float = Field(default=0.3, ge=0, le=1)


class SfxFonts(_Strict):
    """Polices des onomatopées (lettrage hors bulle) : une par intensité, et celles proposées dans l'UI."""

    by_intensity: dict[Intensity, str]
    choices: list[str] = Field(default_factory=list, description="Polices au choix dans l'écran Lettrage")
    uppercase: bool = True
    line_height: float = Field(default=0.95, gt=0.5, le=3)


class FontsPreset(_Strict):
    fonts: dict[str, FontFile] = Field(min_length=1)
    styles: dict[str, TextStyle]
    # Libellé « case manquante » dessiné sur l'aplat gris d'une case sans image.
    missing_panel: TextStyle
    hyphenation: Hyphenation = Field(default_factory=Hyphenation)
    # Onomatopées ; absent = police du cri pour toutes.
    sfx: SfxFonts | None = None

    def sfx_font(self, intensity: str | None, font: str | None = None) -> str:
        """Police d'une onomatopée : celle choisie (si elle existe), sinon celle de son intensité."""
        if font and font in self.fonts:
            return font
        if self.sfx is None:
            return self.styles["shout"].font
        return self.sfx.by_intensity.get(intensity or "normal") or self.sfx.by_intensity["normal"]  # type: ignore[index]

    def sfx_choices(self) -> list[str]:
        if self.sfx is None:
            return [self.styles["shout"].font]
        return list(dict.fromkeys([*self.sfx.choices, *self.sfx.by_intensity.values()]))

    @model_validator(mode="after")
    def _check(self) -> FontsPreset:
        if self.sfx is not None:
            missing = [k for k in INTENSITIES if k not in self.sfx.by_intensity]
            if missing:
                raise ValueError(f"sfx.by_intensity : intensités absentes : {', '.join(missing)}")
            unknown = [f for f in [*self.sfx.by_intensity.values(), *self.sfx.choices] if f not in self.fonts]
            if unknown:
                raise ValueError(f"sfx : police inconnue « {unknown[0]} »")
        missing = [k for k in BUBBLE_KINDS if k not in self.styles]
        if missing:
            raise ValueError(f"styles absents : {', '.join(missing)}")
        unknown = [k for k in self.styles if k not in BUBBLE_KINDS]
        if unknown:
            raise ValueError(f"types de bulle inconnus : {', '.join(unknown)}")
        for key, style in [*self.styles.items(), ("missing_panel", self.missing_panel)]:
            if style.font not in self.fonts:
                raise ValueError(f"{key} : police inconnue « {style.font} »")
            if style.italic and self.fonts[style.font].italic is None:
                raise ValueError(f"{key} : « {self.fonts[style.font].name} » n'a pas de fichier italique")
        return self


class Padding(_Strict):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class CloudShape(_Strict):
    bump_mm: float = Field(default=5, gt=0, description="Largeur d'une bosse du nuage")
    amplitude_mm: float = Field(default=1.2, ge=0)
    tail_bubbles: int = Field(default=3, ge=0, le=8)


class ShoutShape(_Strict):
    spike_mm: float = Field(default=2.5, ge=0, description="Longueur des pointes")
    spike_every_mm: float = Field(default=4, gt=0, description="Écart entre deux pointes")
    jitter: float = Field(default=0.35, ge=0, le=1, description="Irrégularité des pointes (0 = régulières)")


class TailSettings(_Strict):
    length_mm: float = Field(default=7, gt=0, description="Longueur par défaut (sans visage détecté)")
    max_length_mm: float = Field(default=18, gt=0)
    base_mm: float = Field(default=4, gt=0, description="Largeur de la queue à sa base")
    # Sans visage détecté : vers le centre de la case, ou droit vers le bas.
    default_direction: Literal["panel_center", "down"] = "panel_center"
    face_gap_mm: float = Field(default=1.5, ge=0, description="La pointe s'arrête à cette distance du visage")


class CropMarks(_Strict):
    length_mm: float = Field(default=5, gt=0)
    offset_mm: float = Field(default=3, ge=0, description="Distance entre le trait de coupe et le repère")
    stroke_pt: float = Field(default=0.25, gt=0)
    slug_mm: float = Field(default=9, ge=0, description="Bande ajoutée autour du fond perdu pour les repères")


class SfxSettings(_Strict):
    """Onomatopées : grand texte vectoriel hors bulle, contour épais + halo, incliné, taille selon la case."""

    # Taille de base (points) par intensité, pour une case dont le plus petit côté vaut reference_panel_mm.
    size_pt: dict[Intensity, float] = Field(default_factory=lambda: {"calme": 20.0, "normal": 30.0, "choc": 44.0})
    reference_panel_mm: float = Field(default=70, gt=0)
    scale_min: float = Field(default=0.6, gt=0, le=5, description="Facteur minimal (petite case)")
    scale_max: float = Field(default=1.5, gt=0, le=5, description="Facteur maximal (grande case)")
    min_size_pt: float = Field(default=12, gt=0, le=200)
    max_size_pt: float = Field(default=96, gt=0, le=300)
    max_width: float = Field(default=0.9, gt=0, le=2, description="Largeur maximale / largeur de la case")
    fill: str = Field(default="#ffffff", pattern=HEX_COLOR)
    outline: str = Field(default="#111111", pattern=HEX_COLOR)
    outline_pt: float = Field(default=2.2, ge=0, le=20, description="Contour épais autour des lettres")
    halo: str = Field(default="#ffffff", pattern=HEX_COLOR)
    halo_pt: float = Field(default=1.6, ge=0, le=20, description="Halo blanc autour du contour")
    angle_deg: AngleRange = Field(default_factory=lambda: AngleRange(min=4, max=16))
    skew_deg: AngleRange = Field(default_factory=lambda: AngleRange(min=0, max=10))
    # Débordement autorisé hors de la case (mm, perpendiculairement à chaque bord) : peut chevaucher une bordure.
    max_overflow_mm: float = Field(default=6, ge=0, le=50)
    face_margin_mm: float = Field(default=1.5, ge=0, description="Écart minimal avec un visage détecté")
    bubble_gap_mm: float = Field(default=1, ge=0, description="Écart minimal avec une bulle ou une autre onomatopée")
    grid_mm: float = Field(default=2, gt=0, description="Pas de recherche des positions")

    @model_validator(mode="after")
    def _check(self) -> SfxSettings:
        missing = [k for k in INTENSITIES if k not in self.size_pt]
        if missing:
            raise ValueError(f"size_pt : intensités absentes : {', '.join(missing)}")
        if self.min_size_pt > self.max_size_pt or self.scale_min > self.scale_max:
            raise ValueError("min doit être ≤ max")
        return self


class FrameRender(_Strict):
    """Rendu des options de cadre (cases sans bord, incrustations)."""

    fade_mm: float = Field(default=6, gt=0, le=50, description="Largeur du fondu au papier d'une case « fondu »")
    inset_outline_mm: float = Field(default=1.2, ge=0, le=10, description="Liseré blanc autour d'une incrustation")
    inset_outline_color: str = Field(default="#ffffff", pattern=HEX_COLOR)


class LetteringSettings(_Strict):
    """Formes et placement des bulles, assemblage de la planche (presets/lettering.yaml)."""

    stroke_pt: float = Field(default=1.0, gt=0, description="Contour des bulles")
    narration_stroke_pt: float = Field(default=0.8, gt=0)
    padding_mm: dict[str, Padding] = Field(
        default_factory=lambda: {
            "speech": Padding(x=2.5, y=2),
            "thought": Padding(x=3, y=2.5),
            "shout": Padding(x=3, y=2.5),
            "narration": Padding(x=2, y=1.5),
            "off": Padding(x=2.5, y=2),
        }
    )
    # Ellipse circonscrite au bloc de texte : rayon = demi-côté × ce facteur (√2 = coins jamais coupés).
    ellipse_factor: float = Field(default=1.25, ge=1, le=2)
    speech_shape: Literal["ellipse", "rounded"] = "ellipse"
    rounded_radius_mm: float = Field(default=3, ge=0)
    preferred_aspect: float = Field(default=1.5, gt=0, description="Rapport largeur/hauteur visé des bulles")
    cloud: CloudShape = Field(default_factory=CloudShape)
    shout: ShoutShape = Field(default_factory=ShoutShape)
    tail: TailSettings = Field(default_factory=TailSettings)
    spacing_mm: float = Field(default=1.5, ge=0, description="Écart minimal entre deux bulles")
    panel_margin_mm: float = Field(default=1.5, ge=0, description="Écart minimal bulle ↔ bord de case")
    face_margin_mm: float = Field(default=1.5, ge=0, description="Écart minimal bulle ↔ visage détecté")
    grid_mm: float = Field(default=1, gt=0, description="Pas de recherche des positions de bulle")
    bubble_fill: str = Field(default="#ffffff", pattern=HEX_COLOR)
    bubble_stroke: str = Field(default="#000000", pattern=HEX_COLOR)
    narration_fill: str = Field(default="#fff8e1", pattern=HEX_COLOR)
    # Assemblage
    page_background: str = Field(default="#ffffff", pattern=HEX_COLOR)
    panel_border_pt: float = Field(default=1.5, ge=0)
    panel_border_color: str = Field(default="#000000", pattern=HEX_COLOR)
    missing_panel_fill: str = Field(default="#9e9e9e", pattern=HEX_COLOR)
    missing_panel_label: str = "case manquante"
    crop_marks: CropMarks = Field(default_factory=CropMarks)
    sfx: SfxSettings = Field(default_factory=SfxSettings)
    frames: FrameRender = Field(default_factory=FrameRender)
    supersampling: int = Field(default=3, ge=1, le=6, description="Anticrénelage des formes de bulle (PNG)")

    @model_validator(mode="after")
    def _check(self) -> LetteringSettings:
        missing = [k for k in BUBBLE_KINDS if k not in self.padding_mm]
        if missing:
            raise ValueError(f"padding_mm : types absents : {', '.join(missing)}")
        if self.tail.length_mm > self.tail.max_length_mm:
            raise ValueError("tail.length_mm doit être ≤ tail.max_length_mm")
        return self


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
    # Audace de la direction artistique (prompts/direction-artistique.yaml) : sobre, équilibrée, audacieuse.
    variety: Literal["sobre", "equilibree", "audacieuse"] | None = None

    @field_validator("system", "user", "retry")
    @classmethod
    def _check_template(cls, value: str) -> str:
        if not string.Template(value).is_valid():
            raise ValueError("gabarit invalide : un « $ » isolé doit s'écrire « $$ »")
        return value

    def variables(self, part: Literal["system", "user", "retry"]) -> set[str]:
        return set(string.Template(getattr(self, part)).get_identifiers())


# --- Prompt image (étape 3) ---------------------------------------------------
IMAGE_PROMPT_VARIABLES = {
    "shot",
    "plan",
    "angle",
    "ambiance",
    "description",
    "characters",
    "decor",
    "objects",
    "style",
    "savoir_faire",
    "bible",
}


class ImagePromptSettings(_Strict):
    """Construction du prompt final d'une case (voir pipeline/prompt.py)."""

    # Morceaux assemblés dans l'ordre ; un morceau dont une variable est vide est omis.
    # Variables : $shot, $description, $characters, $decor, $objects (bibliothèque de la série), $style,
    # $savoir_faire (passages du savoir-faire),
    # $bible (notes de la bible sur les personnages de la case) ; direction artistique appliquée :
    # $plan (son type de plan, sinon celui du scénario), $angle, $ambiance.
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
            unknown = set(string.Template(part).get_identifiers()) - IMAGE_PROMPT_VARIABLES
            if unknown:
                raise ValueError(f"variables inconnues : {', '.join(sorted(unknown))}")
        return value


# --- Fiches de référence (« Créer des références » de la bibliothèque) ---------
REFERENCE_SHEET_VARIABLES = {"name", "description", "keywords", "style", "instruction"}
LibraryKindName = Literal["character", "object", "decor"]


class ReferenceSheet(_Strict):
    """Type de fiche de référence (`presets/reference_sheets/*.yaml`) : gabarit de prompt, taille, workflow.

    `prompt` : morceaux assemblés dans l'ordre, un morceau dont une variable est vide est omis.
    Variables : $name, $description (description visuelle de la fiche), $keywords (mots-clés + mots
    déclencheurs de son LoRA), $style (style de la série + mots déclencheurs du LoRA de style),
    $instruction (consigne d'« Affiner », vide pour une première génération).
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str = ""
    kinds: list[LibraryKindName] = Field(min_length=1, description="Sortes de fiches concernées")
    prompt: list[str] = Field(min_length=1)
    negative_prompt: str = Field(default="", description="Ajouté au prompt négatif du workflow")
    width: int = Field(ge=256, le=2048, multiple_of=8)
    height: int = Field(ge=256, le=2048, multiple_of=8)
    # None : palier de la série (Turbo par défaut), ou Qualité si demandé. Un id impose ce workflow.
    workflow: str | None = None
    order: int = Field(default=100, description="Ordre dans la liste déroulante")

    @field_validator("prompt")
    @classmethod
    def _check_prompt(cls, value: list[str]) -> list[str]:
        for part in value:
            tpl = string.Template(part)
            if not tpl.is_valid():
                raise ValueError("gabarit invalide : un « $ » isolé doit s'écrire « $$ »")
            unknown = set(tpl.get_identifiers()) - REFERENCE_SHEET_VARIABLES
            if unknown:
                raise ValueError(f"variables inconnues : {', '.join(sorted(unknown))}")
        return value

    @field_validator("kinds")
    @classmethod
    def _unique_kinds(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


# --- Contrôle qualité (étape 4) -----------------------------------------------
# Aucune valeur par défaut pour les seuils : tout est écrit dans presets/qc.yaml.
Severity = Literal["review", "reject"]


class QCRule(_Strict):
    """Règle déclenchée : `penalty` points retirés au score de la couche ; `at_least` impose un verdict minimal."""

    penalty: int = Field(ge=0, le=100)
    at_least: Severity | None = None


class QCExtraFaceRule(QCRule):
    tolerance: int = Field(ge=0, le=20, description="Visages en trop tolérés")


class QCHandRule(QCRule):
    max_penalty: int = Field(ge=0, le=100, description="Plafond de pénalité pour l'ensemble des mains")


class QCDetector(_Strict):
    """Un détecteur : seuil de prise en compte des boîtes + options passées telles quelles au détecteur.

    Les options sont vérifiées contre les modèles publiés par deepghs (`providers/qc/dghs.py`) :
    un niveau inconnu est une erreur de preset, pas une exception à chaque case.
    """

    kind: ClassVar[str] = "face"

    min_confidence: float = Field(ge=0, le=1)
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def _check_options(cls, value: dict[str, Any]) -> dict[str, Any]:
        problems = check_detector_options(cls.kind, value)
        if problems:
            raise ValueError(" ; ".join(problems))
        return value


class QCHandDetector(QCDetector):
    kind: ClassVar[str] = "hand"

    suspect_below: float = Field(ge=0, le=1, description="Main détectée sous cette confiance = suspecte")


class QCTextDetector(QCDetector):
    kind: ClassVar[str] = "text"


class QCDetectorRules(_Strict):
    missing_face: QCRule
    extra_face: QCExtraFaceRule
    text: QCRule
    suspect_hand: QCHandRule


class QCDetectorsSettings(_Strict):
    face: QCDetector
    hand: QCHandDetector
    text: QCTextDetector
    rules: QCDetectorRules
    # Types de plan où les visages peuvent légitimement manquer (insert, dos…) : pas de comptage.
    face_count_ignored_for_shots: list[str] = Field(default_factory=list)


class QCIdentitySettings(_Strict):
    min_similarity: float = Field(ge=0, le=1)
    below: QCRule
    max_references: int = Field(ge=1, le=20, description="Images de référence comparées par personnage")
    crop_scale: float = Field(ge=1, le=10, description="Agrandissement de la boîte du visage pour le recadrage")


class QCScoreBand(_Strict):
    min: int = Field(ge=0, le=100)
    max: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _check(self) -> QCScoreBand:
        if self.min > self.max:
            raise ValueError("min doit être inférieur ou égal à max")
        return self


class QCVisionSettings(_Strict):
    # never : jamais automatiquement ; on_doubt : seulement si les couches 1-2 hésitent ; always : toujours.
    mode: Literal["never", "on_doubt", "always"]
    doubt_band: QCScoreBand
    max_retries: int = Field(ge=0, le=3, description="Nouveaux essais après une réponse invalide")
    wait_idle_s: float = Field(ge=0, description="Attente max de la fin d'une génération ComfyUI en cours")
    max_reasons: int = Field(ge=1, le=20)
    # Variables : $description, $characters, $shot.
    prompt: str

    @field_validator("prompt")
    @classmethod
    def _check_prompt(cls, value: str) -> str:
        tpl = string.Template(value)
        if not tpl.is_valid():
            raise ValueError("gabarit invalide : un « $ » isolé doit s'écrire « $$ »")
        unknown = set(tpl.get_identifiers()) - {"description", "characters", "shot"}
        if unknown:
            raise ValueError(f"variables inconnues : {', '.join(sorted(unknown))}")
        return value


class QCWeights(_Strict):
    detectors: float = Field(ge=0)
    identity: float = Field(ge=0)
    vision: float = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> QCWeights:
        if self.detectors + self.identity + self.vision <= 0:
            raise ValueError("au moins un poids doit être positif")
        return self


class QCVerdictThresholds(_Strict):
    ok_min: int = Field(ge=0, le=100, description="Score à partir duquel la case est ok")
    reject_below: int = Field(ge=0, le=100, description="Score sous lequel la case est rejetée")

    @model_validator(mode="after")
    def _check(self) -> QCVerdictThresholds:
        if self.reject_below > self.ok_min:
            raise ValueError("reject_below doit être inférieur ou égal à ok_min")
        return self


class QCBenchGoal(_Strict):
    min: int = Field(ge=1, le=10000)
    max: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def _check(self) -> QCBenchGoal:
        if self.min > self.max:
            raise ValueError("min doit être inférieur ou égal à max")
        return self


class QCBenchSettings(_Strict):
    """Banc d'essai du QC (pipeline/qc_bench.py) : objectif de rappel et taille visée de l'ensemble annoté."""

    target_recall: float = Field(gt=0, le=1, description="Part des mauvaises cases que le QC doit attraper")
    annotation_goal: QCBenchGoal


class QCSettings(_Strict):
    """Contrôle qualité des cases (`presets/qc.yaml`) : seuils, poids, règles, nombre d'essais."""

    auto_after_generation: bool
    max_auto_retries: int = Field(ge=0, le=5)
    verdict: QCVerdictThresholds
    weights: QCWeights
    detectors: QCDetectorsSettings
    identity: QCIdentitySettings
    vision: QCVisionSettings
    bench: QCBenchSettings


# --- Agents du pipeline (écran « L'équipe ») ------------------------------------
# Un agent = un rôle du pipeline (Python simple, pas de framework d'agents) dont les réglages
# pointent vers les presets qui les livrent. Voir mangaka_engine/agents/.
SettingType = Literal[
    "text", "longtext", "prompt", "prompt_list", "number", "integer", "boolean", "choice", "list", "yaml"
]
# `fichier.yaml#chemin`, `prompts/<id>.yaml#chemin`, `workflows/*.yaml#chemin`, `layouts/*.yaml#templates`,
# `env:VARIABLE` (fournisseur choisi dans .env) ou `profile` (stocké seulement dans le profil de l'agent).
PRESET_FILES = ("defaults", "providers", "layout", "image_prompt", "qc", "fonts", "lettering")
_SOURCE = (
    r"^(env:[A-Z][A-Z0-9_]*|profile|(" + "|".join(PRESET_FILES) + r")\.yaml#[\w.-]+"
    r"|prompts/[a-z0-9][a-z0-9-]*\.yaml#[\w.-]+|workflows/\*\.yaml#[\w.-]+|layouts/\*\.yaml#templates)$"
)
SECRET_WORDS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


class AgentSetting(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    help: str = ""
    group: str = ""
    type: SettingType
    source: str = Field(pattern=_SOURCE)
    choices: list[str] = Field(default_factory=list)
    choice_labels: dict[str, str] = Field(default_factory=dict)
    choices_from: Literal["fonts", "workflows", "page_formats"] | None = None
    nullable: bool = Field(default=False, description="Valeur vide autorisée (choix « aucun »)")
    variables: list[str] = Field(default_factory=list, description="Variables $… autorisées (prompts)")
    min: float | None = None
    max: float | None = None
    step: float | None = None
    env_override: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    fallback: Any = Field(default=None, description="Valeur livrée quand la source est vide")
    global_only: bool = Field(default=False, description="Réglage commun à toutes les séries")

    @model_validator(mode="after")
    def _check(self) -> AgentSetting:
        if self.type == "choice" and not self.choices and self.choices_from is None:
            raise ValueError(f"{self.key} : « choices » ou « choices_from » obligatoire pour un choix")
        for env in (self.source.removeprefix("env:") if self.source.startswith("env:") else None, self.env_override):
            if env and any(w in env for w in SECRET_WORDS):
                raise ValueError(f"{self.key} : un secret ({env}) ne peut pas être un réglage")
        return self

    @property
    def file(self) -> str | None:
        """Fichier preset de la valeur livrée (None : `env:` ou `profile`)."""
        return self.source.split("#", 1)[0] if "#" in self.source else None

    @property
    def path(self) -> list[str]:
        return self.source.split("#", 1)[1].split(".") if "#" in self.source else []


class AgentSecret(_Strict):
    env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    label: str


class AgentLLM(_Strict):
    provider: str
    model: str


AgentProviderKind = Literal["llm", "vision", "comfyui", "detectors", "identity"]


class AgentPreset(_Strict):
    """Déclaration d'un agent (`presets/agents/<id>.yaml`)."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    icon: str = "🤖"
    role: str = ""
    step: int = Field(ge=0, le=99)
    step_label: str = ""
    providers: list[AgentProviderKind] = Field(default_factory=list)
    llm: AgentLLM | None = None
    job_steps: list[str] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list, description="Réglages affichés comme « modèle utilisé »")
    summary_default: str = ""
    trial: str | None = Field(default=None, description="Essai disponible (voir agents/trials.py)")
    trial_description: str = ""
    secrets: list[AgentSecret] = Field(default_factory=list)
    # Rôle dans presets/knowledge.yaml (`agents`) : savoir-faire livré et lu par le RAG.
    knowledge_role: str | None = None
    settings: list[AgentSetting] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> AgentPreset:
        keys = [s.key for s in self.settings]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"réglages en double : {', '.join(dupes)}")
        if "knowledge" in keys:
            raise ValueError("« knowledge » est réservé au savoir-faire, commun à tous les agents")
        refs = [*self.summary, *([self.llm.provider, self.llm.model] if self.llm else [])]
        unknown = sorted({k for k in refs if k not in keys})
        if unknown:
            raise ValueError(f"réglages inconnus : {', '.join(unknown)}")
        return self

    def setting(self, key: str) -> AgentSetting | None:
        return next((s for s in self.settings if s.key == key), None)


# --- Savoir-faire (RAG local) ------------------------------------------------------
class KnowledgeChunking(_Strict):
    max_tokens: int = Field(default=350, ge=50, le=4000, description="Taille maximale d'un passage")
    min_tokens: int = Field(default=40, ge=0, le=2000, description="Un passage plus petit est fusionné au suivant")


class KnowledgeRetrieval(_Strict):
    top_k: int = Field(default=6, ge=1, le=50)
    vector_weight: float = Field(default=0.6, ge=0, le=1)
    keyword_weight: float = Field(default=0.4, ge=0, le=1)
    min_score: float = Field(default=0.05, ge=0, le=1, description="Passages sous ce score hybride : écartés")


class KnowledgeAgent(_Strict):
    """Savoir-faire d'un agent : collections (par nom), budget de jetons, nombre de passages."""

    label: str
    collections: list[str] = Field(default_factory=list)
    series_collections: bool = Field(default=True, description="Ajoute les collections rattachées à la série")
    budget_tokens: int = Field(default=2000, ge=0, le=32000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    bible: bool = True
    bible_max_tokens: int | None = Field(default=None, ge=0, le=32000)


class KnowledgeSettings(_Strict):
    """Savoir-faire (`presets/knowledge.yaml`) : découpage, recherche hybride, collections par agent."""

    chunking: KnowledgeChunking = Field(default_factory=KnowledgeChunking)
    retrieval: KnowledgeRetrieval = Field(default_factory=KnowledgeRetrieval)
    small_collection_tokens: int = Field(
        default=1200, ge=0, le=100000, description="Collection plus petite : injectée entière, sans recherche"
    )
    bible_max_tokens: int = Field(default=2500, ge=0, le=32000)
    agents: dict[str, KnowledgeAgent] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> KnowledgeSettings:
        if self.chunking.min_tokens >= self.chunking.max_tokens:
            raise ValueError("chunking.min_tokens doit être inférieur à chunking.max_tokens")
        if self.retrieval.vector_weight + self.retrieval.keyword_weight <= 0:
            raise ValueError("retrieval : vector_weight + keyword_weight doit être positif")
        return self

    def agent(self, role: str) -> KnowledgeAgent:
        return self.agents.get(role) or KnowledgeAgent(label=role, collections=[], budget_tokens=0)
