"""Schémas Pydantic des presets (formats de page, gabarits, prompts, workflows ComfyUI, fournisseurs)."""

from __future__ import annotations

import re
import string
import unicodedata
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
# CFG de Qwen-Image 2.1 : 1 = chemin officiel (une seule passe, prompt négatif ignoré) ; au-delà de 3,
# l'image est surexposée et trop contrastée. Un modèle distillé (Turbo) n'accepte que 1.
MIN_CFG = 1.0
MAX_CFG = 3.0
WorkflowRole = Literal["generation", "croquis", "propre", "controle"]
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
        default_factory=lambda: ["$target.", "$character.", "$description.", "Style: $style."]
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


class ControlPostStep(_Strict):
    """Post-traitement de la carte de contrôle, inséré entre le prétraitement et la mise à la taille
    (ex. `ImageInvert` : trait blanc sur fond noir → trait noir sur fond clair)."""

    class_type: str = Field(min_length=1, description="Nœud ComfyUI (une image en entrée, une image en sortie)")
    name: str = ""
    image_input: str = "image"
    inputs: dict[str, Any] = Field(default_factory=dict, description="Entrées constantes du nœud")


class ControlType(_Strict):
    """Un type de contrôle (trait, profondeur, pose…) : le prétraitement qui tire la carte de contrôle de
    l'image guide. `class_type` absent = l'image guide est déjà une carte (croquis à la main, scribble).
    `post` : nœuds appliqués ensuite à la carte, dans l'ordre (aperçu de l'atelier compris)."""

    name: str = Field(min_length=1, description="Libellé affiché (« Trait »)")
    description: str = ""
    class_type: str | None = Field(default=None, description="Nœud de prétraitement (comfyui_controlnet_aux)")
    image_input: str = "image"
    inputs: dict[str, Any] = Field(default_factory=dict, description="Entrées constantes du prétraitement")
    post: list[ControlPostStep] = Field(default_factory=list, description="Post-traitements de la carte")
    order: int = 0


class ControlSettings(_Strict):
    """Verrouillage de composition : ce bloc fait d'un workflow un preset ControlNet (rôle `controle`).

    Le ControlNet Union de Qwen-Image est un *patch de modèle* : `patch` est le chargeur du patch
    (`ModelPatchLoader`, fichier dans `models/model_patches/`), `apply` le nœud qui l'applique au
    modèle (`QwenImageDiffsynthControlnet`, entrée `strength`), branché entre le modèle (après les
    LoRA) et l'échantillonneur. `image` reçoit l'image guide envoyée à ComfyUI ; le nœud
    `preprocessor` est remplacé selon le type choisi (retiré si le type n'a pas de prétraitement) ;
    `resize` reçoit la taille de la case ; `map_output` enregistre la carte de contrôle (aperçu).
    """

    patch: NodeInput = Field(description="Chargeur du patch et entrée du nom de fichier")
    apply: NodeInput = Field(description="Nœud qui applique le patch et son entrée de force")
    image: NodeInput = Field(description="LoadImage de l'image guide")
    preprocessor: str = Field(min_length=1, description="Nœud de prétraitement, remplacé selon le type")
    resize: str | None = Field(default=None, description="Nœud de mise à la taille (entrées width / height)")
    map_output: str | None = Field(default=None, description="Nœud qui enregistre la carte (aperçu)")
    default_type: str
    default_strength: float = Field(default=1.0, ge=0, le=2)
    types: dict[str, ControlType]

    @model_validator(mode="after")
    def _check(self) -> ControlSettings:
        if not self.types:
            raise ValueError("types : au moins un type de contrôle")
        bad = [k for k in self.types if not re.fullmatch(r"[a-z][a-z0-9_-]*", k)]
        if bad:
            raise ValueError(f"types : identifiant invalide : {', '.join(bad)}")
        if self.default_type not in self.types:
            raise ValueError(f"default_type : type inconnu : {self.default_type}")
        return self


class WorkflowTier(_Strict):
    """Palier d'un workflow (Turbo, Rapide, Qualité) : affiché sur les versions et dans la fiche série."""

    name: str = Field(min_length=1, description="Nom court affiché sur les versions (« Turbo »)")
    # Libellé dans la fiche série ; absent = workflow non proposé comme palier (ex. « avec références »).
    choice: str | None = None
    order: int = 0

    @property
    def key(self) -> str:
        """Identifiant du palier (« Qualité max » → `qualite-max`) : `tiers` de camera_loras.yaml."""
        return tier_key(self.name)


def tier_key(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return "-".join(re.findall(r"[a-z0-9]+", plain))


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
    # Palier de série : workflow ControlNet du même palier (composition verrouillée, rôle `controle`).
    with_control: str | None = None
    # Présent = workflow ControlNet (rôle `controle`) : patch de modèle, image guide, prétraitements.
    control: ControlSettings | None = None
    # Preset de réparation ciblée (inpainting) du même palier, pour les versions produites par ce workflow.
    inpaint_with: str | None = Field(default=None, description="Id du preset de réparation (bloc `inpaint`)")
    # Présent = ce workflow est un preset de réparation (jamais proposé pour générer une case).
    inpaint: InpaintSettings | None = None
    # Modèle distillé (Turbo, croquis) : cfg 1 imposé, le prompt négatif n'est jamais lu. Un modèle de
    # base accepte un vrai CFG (1 à 3) : au-dessus de 1, le prompt négatif est lu (et le coût double).
    distilled: bool = False

    @property
    def is_inpaint(self) -> bool:
        return self.inpaint is not None

    @property
    def cfg(self) -> float:
        """CFG par défaut du preset (1 s'il n'en déclare pas)."""
        value = self.defaults.get("cfg", MIN_CFG)
        return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else MIN_CFG

    def negative_active(self, cfg: float | None = None) -> bool:
        """Le prompt négatif est-il lu par le modèle ? Seulement à cfg > 1 (sinon ComfyUI saute sa passe)."""
        value = self.cfg if cfg is None else cfg
        return "negative_prompt" in self.mapping and "cfg" in self.mapping and value > MIN_CFG

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
        if self.with_control == self.id:
            raise ValueError("with_control ne peut pas désigner le workflow lui-même")
        if (self.role == "controle") != (self.control is not None):
            raise ValueError("un workflow « controle » déclare un bloc control, et lui seul")
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
        if "cfg" in self.defaults:
            cfg = self.defaults["cfg"]
            if isinstance(cfg, bool) or not isinstance(cfg, int | float):
                raise ValueError("defaults.cfg : nombre attendu")
            check_cfg(cfg, distilled=self.distilled)
        return self


def check_cfg(cfg: float, *, distilled: bool) -> None:
    """CFG accepté par un preset : 1 à 3, et exactement 1 pour un modèle distillé (ValueError sinon)."""
    value = f"{cfg:g}".replace(".", ",")
    if distilled and cfg != MIN_CFG:
        raise ValueError(
            f"cfg {value} refusé : modèle distillé (Turbo), cfg 1 obligatoire (le prompt négatif n'y est jamais lu)"
        )
    if not MIN_CFG <= cfg <= MAX_CFG:
        raise ValueError(f"cfg {value} hors limites (1 à 3 : au-delà de 3, l'image se dégrade)")


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

    @property
    def control(self) -> ControlSettings | None:
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
    # Contexte envoyé à Ollama (options.num_ctx) : sans lui, Ollama charge le modèle à son contexte maximal.
    vision_num_ctx: int = Field(default=4096, gt=0, strict=True)
    embedding_num_ctx: int = Field(default=8192, gt=0, strict=True)
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
    # Palier des fiches de référence et du passage au propre de la planche de style, quel que soit le
    # palier de la série (son `with_references` dès qu'une image est envoyée) ; None = palier de la série.
    workflow_library: str | None = None
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
    # Images de référence d'une case, par fiche (personnage, décor, objet) : `principale` = sa seule image
    # principale (la 1re de la fiche : une vue simple plutôt qu'une planche multi-poses) ; `toutes` = la
    # principale d'abord, puis les suivantes tant qu'il reste des emplacements.
    panel_references: Literal["principale", "toutes"] = "principale"
    # Planche de style de la série (essais, référence de style) ; absent = pas de planche de style.
    style_board: StyleBoardSettings | None = None


STYLE_BOARD_VARIABLES = {"scene", "style"}
SheetStyleMode = Literal["with_subject", "always", "never"]
LibraryKindName = Literal["character", "object", "decor"]


class StyleBoardSettings(_Strict):
    """Planche de style (`style_board` de defaults.yaml) : essais au palier croquis d'une scène test du
    genre, puis l'essai retenu passe au propre et devient la référence de style de la série.

    `prompt` : morceaux assemblés dans l'ordre ($scene : `scene_test` du genre, $style : `$style` de la
    série) ; un morceau dont une variable est vide est omis. `width`/`height` : taille du propre (le
    croquis garde ce ratio, au `long_side` du palier croquis).
    """

    trials: int = Field(ge=1, le=4, description="Essais par demande")
    width: int = Field(ge=256, le=2048, multiple_of=16)
    height: int = Field(ge=256, le=2048, multiple_of=16)
    prompt: list[str] = Field(min_length=1)
    negative_prompt: str = Field(default="", description="Ajouté au prompt négatif du workflow")
    # Fiches de référence : `with_subject` = jointe seulement après une image du sujet (image de départ ou
    # variante d'« Affiner »), `always` = jointe à chaque fiche (seule image sans sujet), `never` = jamais.
    # Une valeur pour toutes les sortes, ou une par sorte ({character: with_subject, object: never, …} ;
    # sorte absente = never) : la planche montre des personnages, qui fuiraient dans un objet ou un décor.
    reference_sheets: SheetStyleMode | dict[LibraryKindName, SheetStyleMode]
    # Cases : `with_subject` = jointe s'il reste un emplacement, et seulement si la case a déjà une image
    # de référence d'un personnage, du décor ou d'un objet (jamais seule : une case sans référence passe
    # par le workflow texte) ; `free_slot` = jointe s'il reste un emplacement, même seule ; `never` = jamais.
    panels: Literal["with_subject", "free_slot", "never"]

    def sheets_mode(self, kind: str) -> SheetStyleMode:
        """Réglage `reference_sheets` d'une sorte de fiche (character, object, decor)."""
        if isinstance(self.reference_sheets, str):
            return self.reference_sheets
        return self.reference_sheets.get(kind, "never")  # type: ignore[call-overload]

    @field_validator("prompt")
    @classmethod
    def _check_prompt(cls, value: list[str]) -> list[str]:
        for part in value:
            tpl = string.Template(part)
            if not tpl.is_valid():
                raise ValueError("gabarit invalide : un « $ » isolé doit s'écrire « $$ »")
            unknown = set(tpl.get_identifiers()) - STYLE_BOARD_VARIABLES
            if unknown:
                raise ValueError(f"variables inconnues : {', '.join(sorted(unknown))}")
        if not any("scene" in string.Template(p).get_identifiers() for p in value):
            raise ValueError("le prompt doit contenir $scene (scène test du genre)")
        return value


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
    # Surface absolue que demandent les bulles (mm², taille du lettrage) : chaque bulle + chaque caractère.
    # La zone vaut au moins cette surface (bornée à max_fraction) ; 0 = surface en fraction de la case seulement.
    bubble_mm2: float = Field(default=0, ge=0)
    char_mm2: float = Field(default=0, ge=0)

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
    # Case qui déborde sur ses voisines (option `break_out`) : ses bords franchissent la gouttière et
    # avancent encore de cette distance sur les voisines, toujours bornés à la zone utile.
    break_out_mm: float = Field(default=6, ge=0, le=50)
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
    # Cases sans bord, incrustées.
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


# --- Packs de style de la série (presets/style_*/) ------------------------------
# Le style d'une série se choisit uniquement dans ces listes fermées (genre, rendu, ton, réglages fins) ;
# pipeline/style.py en compose le $style des prompts image et les consignes des LLM.
STYLE_ID = r"^[a-z0-9][a-z0-9-]*$"
# Palier Turbo (cfg 1) : le prompt négatif est quasiment sans effet, les mots-clés disent ce qu'on veut voir.
# Calibrage (presets/README.md) : une exclusion explicite dans le prompt positif (« pas de hachures ») aide
# seulement en renfort de mots-clés positifs ; un pack fait uniquement d'exclusions est refusé.
_NEGATIVE_KEYWORD = re.compile(r"\b(no|not|without|never|sans|pas|aucun|aucune|jamais|ni)\b", re.IGNORECASE)
# Langue des mots-clés, mesurée pack par pack (informatif : rien n'est traduit).
StyleLang = Literal["fr", "en"]


def _check_keywords(value: list[str]) -> list[str]:
    out = [" ".join(k.split()) for k in value]
    if any(not k for k in out):
        raise ValueError("mot-clé vide")
    if out and all(_NEGATIVE_KEYWORD.search(k) for k in out):
        raise ValueError(
            "formulations positives uniquement (le prompt négatif est sans effet en Turbo ; une exclusion ne "
            f"vient qu'en renfort de mots-clés positifs) : « {out[0]} »"
        )
    return list(dict.fromkeys(out))


def _split_people(data: Any) -> Any:
    """`prompt_keywords` du YAML : un mot-clé est un texte, ou `{text: …, people: true}` s'il évoque des
    personnes (« sourire », « jeune héros ») ; ces derniers sont recopiés dans `people_keywords`."""
    if not isinstance(data, dict) or not isinstance(data.get("prompt_keywords"), list):
        return data
    words: list[Any] = []
    people = list(data.get("people_keywords") or [])
    for item in data["prompt_keywords"]:
        if isinstance(item, dict):
            unknown = set(item) - {"text", "people"}
            if unknown or not isinstance(item.get("text"), str) or not isinstance(item.get("people", False), bool):
                raise ValueError("mot-clé : un texte, ou {text: « … », people: true|false}")
            text = " ".join(item["text"].split())
            words.append(text)
            if item.get("people"):
                people.append(text)
        else:
            words.append(item)
    return {**data, "prompt_keywords": words, "people_keywords": list(dict.fromkeys(people))}


class StylePack(_Strict):
    """Champs communs à un genre, un rendu et un ton."""

    id: str = Field(pattern=STYLE_ID)
    name: str = Field(min_length=1, description="Nom affiché (français)")
    description: str = Field(min_length=1, description="Description affichée sous la liste (français)")
    prompt_keywords: list[str] = Field(min_length=1, description="Mots-clés du prompt image (prompt positif)")
    # Mots-clés qui évoquent des personnes, écartés des fiches d'objet et de décor (sinon des personnages
    # inventés apparaissent dans la fiche). Dans le YAML : `{text: sourire, people: true}` dans prompt_keywords.
    people_keywords: list[str] = Field(default_factory=list)
    lang: StyleLang = Field(description="Langue des mots-clés, choisie au calibrage (informatif)")
    order: int = Field(default=100, description="Ordre dans la liste déroulante")

    @model_validator(mode="before")
    @classmethod
    def _people(cls, data: Any) -> Any:
        return _split_people(data)

    @field_validator("prompt_keywords")
    @classmethod
    def _keywords(cls, value: list[str]) -> list[str]:
        return _check_keywords(value)


class GenreFonts(_Strict):
    dialogue: str = Field(description="Police des bulles de parole (fonts.yaml)")
    shout: str = Field(description="Police des cris (fonts.yaml)")


class StyleGenre(StylePack):
    """Genre et public (`presets/style_genres/*.yaml`) : il peut suggérer la mise en page de la série."""

    layout_style: str | None = Field(
        default=None,
        description="Grammaire de mise en page suggérée (layout_styles/), jamais « sage » ; absente : defaults.yaml",
    )
    reading_direction: Literal["ltr", "rtl"]
    fonts: GenreFonts
    llm_guidelines: str = Field(min_length=1, description="Consignes du scénariste et du directeur artistique")
    # Absent : tous les tons. Sinon, seuls ceux-ci (ex. « jeunesse » exclut « dark »).
    allowed_tones: list[str] | None = None
    style_lora: str | None = Field(default=None, description="LoRA conseillé (fichier du catalogue style_loras.yaml)")
    scene_test: str = Field(
        min_length=1, description="Scène test de la planche de style (français, affichée ; sans personnage de la série)"
    )
    # Même scène, en anglais : c'est elle qui entre dans le prompt image (absente : `scene_test`).
    scene_prompt: str | None = Field(default=None, min_length=1, description="Scène test du prompt image (anglais)")


class StyleRendering(StylePack):
    """Rendu (`presets/style_renderings/*.yaml`) : remplace toute mention de rendu en dur du prompt."""

    monochrome: bool = Field(description="Rendu noir et blanc : seul à accepter le réglage « trames »")
    default: bool = False
    # Tonalité « papier blanc » (anglais) : ajoutée au prompt positif de chaque case du rendu ; vide = aucune.
    tonality: str = Field(default="", description="Consigne de tonalité ajoutée au prompt positif des cases")
    # Termes ajoutés au prompt négatif des cases quand il est lu (vrai CFG, palier Qualité) ; vide = aucun.
    tonality_negative: str = Field(default="", description="Termes négatifs de tonalité (lus à cfg > 1)")
    # Début de la phrase de style qui ouvre chaque prompt de case (anglais, vocabulaire du dessin : « Black
    # and white manga panel, inked line art with halftone screentone shading ») ; vide = 1er mot-clé.
    lead: str = Field(default="", description="Phrase de style en tête des prompts de case (anglais)")


class StyleTone(StylePack):
    """Ton (`presets/style_tones/*.yaml`)."""

    llm_guidelines: str = Field(default="", description="Consignes ajoutées à celles du genre (facultatif)")
    default: bool = False


class StyleOptionChoice(_Strict):
    name: str = Field(min_length=1)
    # Vide seulement pour un réglage à pièce réservée (`StyleOption.piece`) : « propre » n'ajoute rien.
    prompt_keywords: list[str] = Field(default_factory=list)
    people_keywords: list[str] = Field(default_factory=list)  # voir StylePack
    # Termes ajoutés au prompt négatif de la case (lus à vrai CFG seulement, palier Qualité).
    negative_keywords: list[str] = Field(default_factory=list)
    lang: StyleLang = Field(description="Langue des mots-clés, choisie au calibrage (informatif)")

    @model_validator(mode="before")
    @classmethod
    def _people(cls, data: Any) -> Any:
        return _split_people(data)

    @field_validator("prompt_keywords")
    @classmethod
    def _keywords(cls, value: list[str]) -> list[str]:
        return _check_keywords(value)

    @field_validator("negative_keywords")
    @classmethod
    def _negative(cls, value: list[str]) -> list[str]:
        out = [" ".join(k.split()) for k in value]
        if any(not k or "," in k for k in out):
            raise ValueError("terme négatif vide ou contenant une virgule")
        return list(dict.fromkeys(out))


# Pièces réservées d'image_prompt.yaml qu'un réglage fin peut remplir à la place de `$style`.
StyleOptionPiece = Literal["finition"]


class StyleOption(_Strict):
    """Réglage fin borné : une liste de choix, chacun avec ses mots-clés. Non choisi = rien d'ajouté."""

    name: str = Field(min_length=1)
    description: str = ""
    monochrome_only: bool = Field(default=False, description="Réservé aux rendus N&B (trames)")
    # Pièce réservée du prompt de case (`$finition` d'image_prompt.yaml) : les mots-clés du choix y vont, et
    # n'entrent JAMAIS dans `$style` (plafonné à `style_max_chars`, il les tronquerait en silence).
    piece: StyleOptionPiece | None = None
    choices: dict[str, StyleOptionChoice] = Field(min_length=1)

    @field_validator("choices")
    @classmethod
    def _choice_ids(cls, value: dict[str, StyleOptionChoice]) -> dict[str, StyleOptionChoice]:
        bad = [k for k in value if not re.match(STYLE_ID, k)]
        if bad:
            raise ValueError(f"identifiant de choix invalide : « {bad[0]} » (minuscules, chiffres, tirets)")
        return value

    @model_validator(mode="after")
    def _keywords(self) -> StyleOption:
        if self.piece is None:
            empty = [k for k, c in self.choices.items() if not c.prompt_keywords]
            if empty:
                raise ValueError(f"choix « {empty[0]} » sans mot-clé (permis seulement avec `piece`)")
            negative = [k for k, c in self.choices.items() if c.negative_keywords]
            if negative:
                raise ValueError(f"choix « {negative[0]} » : negative_keywords permis seulement avec `piece`")
        return self


class StyleOptions(_Strict):
    """`presets/style_options.yaml` : réglages fins, dans l'ordre du fichier (= ordre dans le prompt)."""

    options: dict[str, StyleOption] = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def _option_ids(cls, value: dict[str, StyleOption]) -> dict[str, StyleOption]:
        bad = [k for k in value if not re.match(r"^[a-z][a-z0-9_]*$", k)]
        if bad:
            raise ValueError(f"identifiant de réglage invalide : « {bad[0]} » (minuscules, chiffres, _)")
        return value


class StyleLora(_Strict):
    file: str = Field(min_length=1, description="Nom du fichier tel que ComfyUI le liste (sous-dossier compris)")
    name: str = ""
    trigger_words: list[str] = Field(default_factory=list)
    weight: float = Field(default=0.8, ge=0, le=2, description="Poids conseillé")


class StyleLoraCatalog(_Strict):
    """`presets/style_loras.yaml` : mots déclencheurs et poids conseillé des LoRA de style connus."""

    loras: list[StyleLora] = Field(default_factory=list)

    @field_validator("loras")
    @classmethod
    def _unique(cls, value: list[StyleLora]) -> list[StyleLora]:
        seen: set[str] = set()
        for lo in value:
            if lo.file in seen:
                raise ValueError(f"fichier en double : {lo.file}")
            seen.add(lo.file)
        return value

    def get(self, file: str | None) -> StyleLora | None:
        return next((lo for lo in self.loras if lo.file == file), None) if file else None


# --- LoRA de caméra et d'identité (presets/camera_loras.yaml) ---------------------------
CameraLoraRole = Literal["angles", "identity"]


class CameraLora(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    role: CameraLoraRole
    file: str = Field(min_length=1, description="Nom du fichier tel que ComfyUI le liste (sous-dossier compris)")
    name: str = Field(min_length=1)
    description: str = ""
    # Mot déclencheur placé au tout début du prompt ; vide = aucun.
    trigger: str = ""
    weight: float = Field(default=1.0, ge=0, le=2, description="strength_model par défaut")
    # Paliers où le LoRA est ajouté (`WorkflowTier.key`) ; ailleurs : « Disponible en palier Qualité ».
    tiers: list[str] = Field(min_length=1)
    default: bool = False


class CameraAngle(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=40)
    label: str = Field(min_length=1)
    camera: str = Field(min_length=1, description="Vocabulaire de caméra de la fiche du modèle (anglais)")
    azimuth: float = Field(ge=-180, le=180)
    elevation: float = Field(ge=-90, le=90)


class AngleTarget(_Strict):
    """Cible d'un angle de la direction artistique : un axe absent ne compte pas."""

    azimuth: float | None = Field(default=None, ge=-180, le=180)
    elevation: float | None = Field(default=None, ge=-90, le=90)


class CameraPrompts(_Strict):
    sheet: list[str] = Field(default_factory=lambda: ["$trigger $camera."])
    panel: list[str] = Field(default_factory=lambda: ["$trigger $camera.", "$scene"])

    @field_validator("sheet", "panel")
    @classmethod
    def _variables(cls, value: list[str]) -> list[str]:
        allowed = {"trigger", "camera", "name", "description", "scene"}
        for part in value:
            unknown = set(string.Template(part).get_identifiers()) - allowed
            if unknown:
                raise ValueError(f"variable inconnue : ${sorted(unknown)[0]}")
        if not value or not value[0].lstrip().startswith("$trigger"):
            raise ValueError("le premier morceau doit commencer par $trigger (le mot déclencheur ouvre le prompt)")
        return value


class CameraLoraCatalog(_Strict):
    """`presets/camera_loras.yaml` : LoRA Multiple-Angles et Cohérence anime, vocabulaire de caméra."""

    workflow: str | None = Field(default=None, description="Workflow de « Nouvel angle » et « Changer l'angle »")
    steps: int | None = Field(default=None, ge=1, le=200)
    loras: list[CameraLora] = Field(default_factory=list)
    weight_hint: str = ""
    angles: list[CameraAngle] = Field(default_factory=list)
    main_view: str | None = None
    direction_angles: dict[str, AngleTarget] = Field(default_factory=dict)
    prompts: CameraPrompts = Field(default_factory=CameraPrompts)
    # « Nouvel angle » d'une fiche : négatif par sorte (character, object, decor), taille ≈ side × side.
    sheet_negatives: dict[Literal["character", "object", "decor"], str] = Field(default_factory=dict)
    sheet_side: int = Field(default=1024, ge=256, le=2048)

    @model_validator(mode="after")
    def _check(self) -> CameraLoraCatalog:
        for label, ids in (("loras", [lo.id for lo in self.loras]), ("angles", [a.id for a in self.angles])):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            if dup:
                raise ValueError(f"{label} : identifiant en double : {dup[0]}")
        if sum(1 for lo in self.loras if lo.role == "angles" and lo.default) > 1:
            raise ValueError("loras : un seul LoRA d'angle par défaut")
        if sum(1 for lo in self.loras if lo.role == "identity") > 1:
            raise ValueError("loras : un seul LoRA d'identité")
        if self.main_view is not None and self.angle(self.main_view) is None:
            raise ValueError(f"main_view : angle inconnu « {self.main_view} »")
        return self

    def lora(self, lora_id: str | None) -> CameraLora | None:
        return next((lo for lo in self.loras if lo.id == lora_id), None) if lora_id else None

    def angle(self, angle_id: str | None) -> CameraAngle | None:
        return next((a for a in self.angles if a.id == angle_id), None) if angle_id else None

    @property
    def angle_loras(self) -> list[CameraLora]:
        return [lo for lo in self.loras if lo.role == "angles"]

    @property
    def default_angle_lora(self) -> CameraLora | None:
        loras = self.angle_loras
        return next((lo for lo in loras if lo.default), loras[0] if loras else None)

    @property
    def identity_lora(self) -> CameraLora | None:
        return next((lo for lo in self.loras if lo.role == "identity"), None)


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


# Plus grande onomatopée possible : borne de `SfxSettings.max_size_pt` et de la taille saisie à la main.
SFX_MAX_SIZE_PT = 300


class SfxTextStyle(TextStyle):
    """Style d'une onomatopée : même modèle que le texte des bulles, mais bien plus grand
    (le plafond de 72 pt du dialogue ne vaut pas pour un « BOUM » pleine case)."""

    size_pt: float = Field(gt=0, le=SFX_MAX_SIZE_PT)
    min_size_pt: float = Field(gt=0, le=SFX_MAX_SIZE_PT)


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
    # Forme de la queue (parole, hors-champ) : biseau effilé aux flancs courbes, fondu dans le contour.
    bend: float = Field(default=0.12, ge=-0.5, le=0.5, description="Courbure (fraction de la longueur, 0 = droite)")
    tip_angle_deg: float = Field(default=16, ge=4, le=60, description="Angle de la pointe : petit = plus effilée")
    shout_zigzag: float = Field(default=0.18, ge=0, le=0.5, description="Cri : décrochement en éclair (× longueur)")
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
    max_size_pt: float = Field(default=96, gt=0, le=SFX_MAX_SIZE_PT)
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
class VarietyRules(_Strict):
    """Mise en scène variée imposée à la direction artistique (`variety_rules` de
    prompts/direction-artistique.yaml, vérifiée par pipeline/art_direction.py `check_variety`).

    Une règle enfreinte relance l'agent avec l'erreur ; après les relances, la proposition est gardée
    avec un avertissement visible dans l'écran Direction artistique. Valeurs comparées sans casse.
    """

    max_same_plan_in_a_row: int = Field(default=2, ge=1, le=20, description="Cases d'affilée au même plan (page)")
    max_same_angle_in_a_row: int = Field(default=2, ge=1, le=20, description="Cases d'affilée au même angle (page)")
    # Part maximale des cases « de face / à hauteur d'œil » sur les pages dirigées ensemble (au moins une permise).
    max_frontal_share: float = Field(default=0.35, ge=0, le=1)
    frontal_angles: list[str] = Field(default_factory=lambda: ["de face"])
    # Au moins `min_off_eye_level_per_page` case(s) hors hauteur d'œil par page d'au moins
    # `off_eye_level_min_panels` cases : angle ou plan de `off_eye_level`.
    min_off_eye_level_per_page: int = Field(default=1, ge=0, le=20)
    off_eye_level_min_panels: int = Field(default=2, ge=1, le=20)
    off_eye_level: list[str] = Field(
        default_factory=lambda: ["en plongée", "en contre-plongée", "cadre penché", "plongée", "contre-plongée"]
    )
    # `action` de chaque case : obligatoire ; une action courte (au plus `weak_max_words` mots) qui contient
    # l'un de ces verbes statiques est refusée (« Aiko regarde Kenji »).
    require_action: bool = True
    weak_actions: list[str] = Field(default_factory=list)
    weak_max_words: int = Field(default=4, ge=1, le=20)
    # Échelle des plans (personnages en pied trop souvent) : part maximale des plans larges et moyens sur les
    # pages dirigées ensemble (au moins une case permise ; 1 = pas de limite)…
    max_wide_medium_share: float = Field(default=0.5, ge=0, le=1)
    wide_medium_plans: list[str] = Field(default_factory=lambda: ["plan large", "plan d'ensemble", "plan moyen"])
    # …au moins `min_tight_per_page` plan(s) serré(s) par page d'au moins `tight_min_panels` cases (0 = aucun)…
    min_tight_per_page: int = Field(default=1, ge=0, le=20)
    tight_min_panels: int = Field(default=3, ge=1, le=20)
    tight_plans: list[str] = Field(default_factory=lambda: ["gros plan", "très gros plan", "plan rapproché", "insert"])
    # …et jamais plus de `max_wide_in_a_row` plan(s) large(s) d'affilée dans une page.
    max_wide_in_a_row: int = Field(default=1, ge=1, le=20)
    wide_plans: list[str] = Field(default_factory=lambda: ["plan large", "plan d'ensemble"])


class DialogueRoom(_Strict):
    """Répliques au plus dans une case d'une page d'au plus `max_panels` cases (place des bulles)."""

    max_panels: int = Field(ge=1, le=9)
    replies: int = Field(ge=0, le=12)


class DialogueRules(_Strict):
    """Densité et variété des dialogues imposées au scénariste (`dialogue_rules` de prompts/script.yaml,
    vérifiées par pipeline/dialogues.py `check_dialogues`).

    Une règle enfreinte relance l'agent avec l'erreur ; après les relances, le découpage est gardé avec un
    avertissement visible dans l'écran Scénario. Les onomatopées (`sfx`) ne comptent jamais comme répliques.
    """

    # Répliques visées dans chaque case où un personnage présent peut parler (sans dépasser la place)…
    target_per_panel: int = Field(default=2, ge=0, le=6)
    # …et répliques par case au moins sur le chapitre (bornées par la place disponible ; 0 = pas d'exigence).
    min_per_panel: float = Field(default=1.3, ge=0, le=6)
    # Brièveté : mots au plus par réplique, et en moyenne sur le chapitre.
    max_words: int = Field(default=12, ge=1, le=100)
    max_mean_words: float = Field(default=7, ge=1, le=100)
    # Case d'action ou de combat (intensité de `action_intensities`, ou une onomatopée) : au moins une parole
    # d'un personnage présent (cri, ordre, réaction) en plus de l'onomatopée.
    action_needs_voice: bool = True
    action_intensities: list[str] = Field(default_factory=lambda: ["choc"])
    # Au moins une réplique de ces types par chapitre (pensée, voix off, narration) ; false = l'auteur s'en passe.
    require_inner_voice: bool = True
    inner_voice_kinds: list[str] = Field(default_factory=lambda: ["thought", "off", "narration"])
    # Place des bulles : répliques au plus par case selon le nombre de cases de la page (première ligne dont
    # `max_panels` couvre la page) ; une case forte (importance 3) en reçoit `big_panel_bonus` de plus.
    room: list[DialogueRoom] = Field(default_factory=list)
    big_panel_bonus: int = Field(default=1, ge=0, le=6)
    # Place réelle : après la mise en page, chaque bulle doit tenir dans la zone de bulles de sa case
    # (lettrage simulé) ; sinon relance, puis avertissement.
    check_room: bool = True

    @field_validator("inner_voice_kinds")
    @classmethod
    def _kinds(cls, v: list[str]) -> list[str]:
        allowed = ("speech", "thought", "shout", "narration", "off")
        bad = [k for k in v if k not in allowed]
        if bad:
            raise ValueError(f"type de réplique inconnu : {', '.join(bad)} (parmi {', '.join(allowed)})")
        return v

    def room_for(self, panels_on_page: int, importance: int = 2) -> int | None:
        """Répliques au plus dans une case (None = pas de limite)."""
        rule = next((r for r in sorted(self.room, key=lambda r: r.max_panels) if panels_on_page <= r.max_panels), None)
        if rule is None:
            return None
        return rule.replies + (self.big_panel_bonus if importance >= 3 else 0)


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
    # Rédacteur de prompt image (prompts/redacteur-image.yaml) : réglage « Prompt rédigé par l'IA » des
    # nouvelles séries, langue du paragraphe et longueur visée (mots).
    enabled: bool | None = None
    language: Literal["fr", "en"] | None = None
    min_words: int | None = Field(default=None, ge=10, le=1000)
    max_words: int | None = Field(default=None, ge=10, le=1000)
    # Règles de variété de la direction artistique (prompts/direction-artistique.yaml).
    variety_rules: VarietyRules | None = None
    # Densité et variété des dialogues du scénariste (prompts/script.yaml).
    dialogue_rules: DialogueRules | None = None

    @model_validator(mode="after")
    def _check_words(self) -> PromptPreset:
        if self.min_words is not None and self.max_words is not None and self.min_words > self.max_words:
            raise ValueError("min_words doit être ≤ max_words")
        return self

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
    "action",
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
    "setting",
    "staging",
    "character_count",
    "style_lead",
    "finition",
}
# Phrase de style en tête des prompts de case (`style_lead` d'image_prompt.yaml).
STYLE_LEAD_VARIABLES = {"rendering", "genre"}
# Lignes d'images de référence (`references.character`…) et morceaux autour du prompt (`before`, `after`).
REFERENCE_LINE_VARIABLES = {"slot", "name"}
REFERENCE_PART_VARIABLES = {"images", "count", "sorting"}


def _check_templates(parts: list[str], allowed: set[str]) -> None:
    for part in parts:
        if not string.Template(part).is_valid():
            raise ValueError("gabarit invalide : un « $ » isolé doit s'écrire « $$ »")
        unknown = set(string.Template(part).get_identifiers()) - allowed
        if unknown:
            raise ValueError(f"variables inconnues : {', '.join(sorted(unknown))}")


class ReferenceSorting(_Strict):
    """Consigne de tri d'une image de référence, par sorte de fiche : ce qu'il faut en prendre et ce qu'il
    faut ignorer (mise en page de la planche, grille de poses, règles, étiquettes, fond blanc). Variables :
    $slot (numéro de l'image), $name (nom de la fiche). Vide : pas de consigne pour cette sorte."""

    character: str = ""
    decor: str = ""
    object: str = ""
    style: str = ""

    @field_validator("character", "decor", "object", "style")
    @classmethod
    def _check_line(cls, value: str) -> str:
        _check_templates([value], REFERENCE_LINE_VARIABLES)
        return value


class ReferenceSortingMonochrome(_Strict):
    """`references.monochrome.sorting` : consignes de tri d'une série en noir et blanc (absente = la même)."""

    character: str | None = None
    decor: str | None = None
    object: str | None = None
    style: str | None = None

    @field_validator("character", "decor", "object", "style")
    @classmethod
    def _check_line(cls, value: str | None) -> str | None:
        if value is not None:
            _check_templates([value], REFERENCE_LINE_VARIABLES)
        return value


class ReferenceMonochrome(ReferenceSortingMonochrome):
    """`references.monochrome` : lignes d'images et consigne `after` d'une série en noir et blanc."""

    sorting: ReferenceSortingMonochrome = Field(default_factory=ReferenceSortingMonochrome)
    after: list[str] | None = None

    @field_validator("after")
    @classmethod
    def _check_after(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            _check_templates(value, REFERENCE_PART_VARIABLES)
        return value


class MoodConflict(_Strict):
    """Règle de `mood_conflicts` d'image_prompt.yaml : une case dont l'ambiance (direction artistique)
    contient l'un des `moods` ne reçoit aucun des mots-clés `drop` du ton de la série."""

    name: str = ""
    # Mots cherchés dans l'ambiance (sans casse ni accents, mots entiers ; « angoiss* » : préfixe).
    moods: list[str] = Field(min_length=1)
    # Mots-clés retirés du style et du prompt envoyé (sans casse, mots entiers).
    drop: list[str] = Field(min_length=1)


class ReferencePromptSettings(_Strict):
    """Cadrage des images de référence dans le prompt envoyé (workflow avec références, voir
    pipeline/prompt.py `frame_references`) : quelle image est quel personnage, et ce qu'elles donnent.

    Une ligne par image envoyée, dans l'ordre des emplacements ($slot : numéro de l'image, $name : nom de
    la fiche), selon sa sorte ; `before` et `after` entourent le prompt de la case ($images : les lignes
    jointes par `separator`, $count : nombre d'images, $sorting : la consigne de tri de chaque image,
    `sorting`, jointe de même).
    """

    # Une ligne commence par « <image$slot> is » : le rédacteur de prompt en reprend la suite comme rôle.
    character: str = (
        "<image$slot> is the identity reference for $name: keep the face, hair, outfit and colours; "
        "ignore its pose, framing and background."
    )
    decor: str = (
        "<image$slot> is the location reference for $name: keep its layout, architecture and materials; "
        "show it from the new camera angle."
    )
    object: str = "<image$slot> is the design reference for the object $name: keep its shape, colours and details."
    style: str = (
        "<image$slot> is a style reference only (line work, inking, screentones, colours): do not copy its "
        "characters, scene or composition."
    )
    sorting: ReferenceSorting = Field(default_factory=ReferenceSorting)
    separator: str = " "
    before: list[str] = Field(default_factory=lambda: ["$images"])
    after: list[str] = Field(default_factory=list)
    # Série en noir et blanc (`monochrome` du pack de rendu) : ces lignes remplacent celles ci-dessus
    # (absente = la même), sans « colours » qui pousse Qwen-Image vers la couleur et le lavis gris.
    monochrome: ReferenceMonochrome = Field(default_factory=lambda: ReferenceMonochrome())

    @field_validator("character", "decor", "object", "style")
    @classmethod
    def _check_line(cls, value: str) -> str:
        _check_templates([value], REFERENCE_LINE_VARIABLES)
        return value

    @field_validator("before", "after")
    @classmethod
    def _check_parts(cls, value: list[str]) -> list[str]:
        _check_templates(value, REFERENCE_PART_VARIABLES)
        return value

    def for_palette(self, monochrome: bool) -> ReferencePromptSettings:
        """Lignes de la série : celles de `monochrome` par-dessus les autres pour une série en noir et blanc."""
        if not monochrome:
            return self
        bw = self.monochrome
        lines = {k: v for k in ("character", "decor", "object", "style") if (v := getattr(bw, k)) is not None}
        sorting = {k: v for k, v in bw.sorting.model_dump().items() if v is not None}
        return self.model_copy(
            update={
                **lines,
                "sorting": self.sorting.model_copy(update=sorting),
                **({"after": bw.after} if bw.after is not None else {}),
            }
        )


class TightShotSettings(_Strict):
    """`tight_shots` d'image_prompt.yaml : plans (direction artistique, scénario ; sans casse) dont le prompt
    négatif reçoit `negative` (« full body, feet visible… »)."""

    shots: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)


class ImagePromptSettings(_Strict):
    """Construction du prompt final d'une case (voir pipeline/prompt.py)."""

    # Morceaux assemblés dans l'ordre ; un morceau dont une variable est vide est omis.
    # Variables : $shot, $description, $characters, $decor, $objects (bibliothèque de la série), $style,
    # $savoir_faire (passages du savoir-faire),
    # $bible (notes de la bible sur les personnages de la case) ; direction artistique appliquée :
    # $plan (son type de plan, sinon celui du scénario), $angle, $ambiance ; scénario : $setting (lieu),
    # $staging (mise en scène), $character_count (« Deux personnages »).
    parts: list[str] = Field(
        default_factory=lambda: [
            "$shot.",
            "$description.",
            "Characters: $characters.",
            "Style: $style.",
            "No text or speech bubbles in the image.",
        ]
    )
    character: str = Field(default="$name ($details)", description="Variables : $name, $details")
    character_separator: str = "; "
    # Toujours présents dans le prompt négatif : le texte est posé au lettrage, jamais dessiné.
    forbidden_text_terms: list[str] = Field(
        default_factory=lambda: [
            "text",
            "letters",
            "speech bubble",
            "caption",
            "onomatopoeia",
            "watermark",
            "signature",
        ]
    )
    # Termes photographiques (« lens », « depth of field »…) : un paragraphe du rédacteur qui en contient est
    # refusé et redemandé (mots entiers, sans casse) ; ils poussent Qwen-Image vers le photoréalisme.
    forbidden_photo_terms: list[str] = Field(
        default_factory=lambda: [
            "photo",
            "photograph",
            "photographic",
            "photorealistic",
            "photorealism",
            "realistic",
            "lens",
            "bokeh",
            "depth of field",
            "telephoto",
            "DSLR",
            "cinematic still",
            "35mm",
        ]
    )
    # Toujours présents dans le prompt négatif (comme `forbidden_text_terms`) : contre le photoréalisme.
    negative_photo_terms: list[str] = Field(
        default_factory=lambda: [
            "photorealistic",
            "photograph",
            "photo",
            "3d render",
            "cgi",
            "realistic skin texture",
            "film grain",
        ]
    )
    # Série en noir et blanc (`monochrome` du pack de rendu) : termes de couleur retirés du prompt positif à
    # l'envoi à ComfyUI (mots entiers, sans casse), refusés dans le paragraphe du rédacteur…
    monochrome_forbidden_terms: list[str] = Field(default_factory=list)
    # … et termes toujours ajoutés au prompt négatif (lu à vrai CFG seulement).
    monochrome_negative_terms: list[str] = Field(default_factory=list)
    # Consigne ajoutée aux règles du rédacteur de prompt ($palette_rule) pour une série en noir et blanc.
    monochrome_writer_rule: str = ""
    # Ambiance de la case contre ton de la série : l'ambiance gagne, les mots-clés du ton en conflit sont
    # retirés pour cette case (style, prompt envoyé).
    mood_conflicts: list[MoodConflict] = Field(default_factory=list)
    # Phrase de style qui ouvre chaque prompt de case : morceaux joints par « , » (un morceau dont une
    # variable est vide est omis). Variables : $rendering (`lead` du rendu de la série), $genre (1er mot-clé
    # du genre, ou de l'ancien style libre).
    style_lead: list[str] = Field(default_factory=lambda: ["$rendering", "$genre style"])
    strip_quotes: bool = Field(default=True, description="Retire les répliques entre guillemets de la description")
    # Longueur maximale de `$style` (caractères) : les packs y entrent tour à tour (pipeline/style.py).
    # null = aucun plafond (tous les mots-clés des packs).
    style_max_chars: int | None = Field(default=240, ge=40)
    # Cadrage des images de référence (workflows avec références).
    references: ReferencePromptSettings = Field(default_factory=ReferencePromptSettings)
    # Plans et angles (direction artistique, scénario) → termes de cadrage anglais du prompt image
    # (`$shot`, `$plan`, `$angle` et le rédacteur de prompt). Clés comparées sans casse ; une valeur
    # absente passe telle quelle.
    camera_terms: dict[str, str] = Field(default_factory=dict)
    # Plans serrés (plus serrés que le plan américain) : termes ajoutés au prompt négatif de la case pour
    # combattre le plein pied (lus seulement à vrai CFG : à cfg 1, la phrase de cadrage du prompt positif,
    # `camera_terms`, est le seul levier).
    tight_shots: TightShotSettings = Field(default_factory=TightShotSettings)

    @field_validator("parts")
    @classmethod
    def _check_parts(cls, value: list[str]) -> list[str]:
        _check_templates(value, IMAGE_PROMPT_VARIABLES)
        return value

    @field_validator("style_lead")
    @classmethod
    def _check_lead(cls, value: list[str]) -> list[str]:
        _check_templates(value, STYLE_LEAD_VARIABLES)
        return value


# --- Fiches de référence (« Créer des références » de la bibliothèque) ---------
REFERENCE_SHEET_VARIABLES = {
    "name",
    "description",
    "keywords",
    "style",
    "instruction",
    "start",
    "style_ref",
    "large_build",
}
# Sous-dossiers de la bibliothèque lisible tenus par l'appli (vues de « Nouvel angle », images envoyées).
REFERENCE_SHEET_RESERVED_FOLDERS = frozenset({"angles", "imports"})


class ReferenceSheet(_Strict):
    """Type de fiche de référence (`presets/reference_sheets/*.yaml`) : gabarit de prompt, taille, workflow.

    `prompt` : morceaux assemblés dans l'ordre, un morceau dont une variable est vide est omis.
    Variables : $name, $description (description visuelle de la fiche), $keywords (mots-clés + mots
    déclencheurs de son LoRA), $style (style de la série + mots déclencheurs du LoRA de style),
    $instruction (consigne d'« Affiner », vide pour une première génération), $start (« image 1 » si
    une image de départ est envoyée, vide sinon), $style_ref (« image N » si la référence de style de
    la série est jointe, toujours en dernier, vide sinon), $large_build (mots de `large_build_keywords`
    trouvés dans la description ou les mots-clés de la fiche — personnage grand, géant, trapu… —, vide sinon).
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str = ""
    kinds: list[LibraryKindName] = Field(min_length=1, description="Sortes de fiches concernées")
    prompt: list[str] = Field(min_length=1)
    negative_prompt: str = Field(default="", description="Ajouté au prompt négatif du workflow")
    width: int = Field(ge=256, le=2048, multiple_of=8)
    height: int = Field(ge=256, le=2048, multiple_of=8)
    # None : `defaults.workflow_library` (Turbo), sinon palier de la série, ou Qualité si demandé. Un id
    # impose ce workflow.
    workflow: str | None = None
    order: int = Field(default=100, description="Ordre dans la liste déroulante")
    # Mots (insensibles à la casse, mots entiers) qui signalent une silhouette grande ou massive : ceux trouvés
    # remplissent $large_build (ex. « réduis les figures pour qu'elles tiennent en entier »).
    large_build_keywords: list[str] = Field(default_factory=list)
    # Plans de case (direction artistique, scénario ; sans casse) que sert cette fiche : pour une case à l'un
    # de ces plans, l'image d'un personnage tirée de cette fiche passe en tête (portrait pour un gros plan,
    # plein pied pour un plan large). Pour un plan absent de la liste, l'image n'est envoyée que si le
    # personnage n'en a pas d'autre. Vide : aucune préférence (l'image garde sa place).
    shots: list[str] = Field(default_factory=list)
    # Sous-dossier de la fiche dans la bibliothèque lisible (`references/personnages/<nom>/<dossier>/`, voir
    # pipeline/comfy_library.py) ; absent : l'id sans la sorte (`personnage-portrait` → `portrait`).
    folder: str | None = Field(default=None, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

    @field_validator("folder")
    @classmethod
    def _free_folder(cls, value: str | None) -> str | None:
        if value in REFERENCE_SHEET_RESERVED_FOLDERS:
            raise ValueError(f"« {value} » est réservé (vues étiquetées, images envoyées)")
        return value

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
    # Case trop sombre (tonalité, voir `QCToneSettings`) ; absente = jamais pénalisée.
    too_dark: QCRule | None = None


class QCToneSettings(_Strict):
    """Tonalité d'une case (numpy sur l'image, CPU, sans modèle) : part de pixels sombres et de noir pur.

    Un pixel compte comme sombre sous `dark_below` (niveau de gris 0-255) et comme noir pur sous
    `black_below` ; au-delà de `max_dark` ou de `max_black` (parts 0-1), la règle `too_dark` s'applique.
    """

    dark_below: int = Field(ge=1, le=255)
    black_below: int = Field(ge=1, le=255)
    max_dark: float = Field(ge=0, le=1)
    max_black: float = Field(ge=0, le=1)
    # Vrai : seulement pour les rendus noir et blanc (`monochrome` du pack de rendu de la série).
    monochrome_only: bool = True
    # Ambiance de la direction artistique qui marque une scène de nuit ou sombre (mots comparés sans
    # casse ni accents) : la tonalité n'est pas vérifiée.
    skip_ambiance_keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> QCToneSettings:
        if self.black_below > self.dark_below:
            raise ValueError("black_below doit être inférieur ou égal à dark_below")
        return self


class QCDetectorsSettings(_Strict):
    face: QCDetector
    hand: QCHandDetector
    text: QCTextDetector
    rules: QCDetectorRules
    # Types de plan où les visages peuvent légitimement manquer (insert, dos…) : pas de comptage.
    face_count_ignored_for_shots: list[str] = Field(default_factory=list)
    # Tonalité « papier blanc » (règle `too_dark`) ; absente = jamais vérifiée.
    tone: QCToneSettings | None = None


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
    fiche_max_tokens: int = Field(
        default=800, ge=50, le=4000, description="Fiche d'un pack : un passage, coupée seulement au-delà"
    )


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
    # Rédacteur de prompt (LLM) de l'agent `image_prompt` : budget, passages et notes de la bible à part,
    # plus larges que la note courte des fragments (`budget_tokens`, `top_k`, `bible_max_tokens`).
    writer_budget_tokens: int | None = Field(default=None, ge=0, le=32000)
    writer_top_k: int | None = Field(default=None, ge=1, le=50)
    writer_bible_max_tokens: int | None = Field(default=None, ge=0, le=32000)
    # Collections toujours cherchées (meilleures fiches dans le budget), jamais injectées entières même si elles
    # sont petites (`small_collection_tokens`) : une petite collection entière mangerait le budget du rédacteur.
    searched_collections: list[str] = Field(default_factory=list)

    @property
    def main_budget_tokens(self) -> int:
        """Budget réglé dans « L'équipe » : celui du rédacteur s'il existe, sinon `budget_tokens`."""
        return self.writer_budget_tokens if self.writer_budget_tokens is not None else self.budget_tokens

    @property
    def main_top_k(self) -> int | None:
        """Top-k réglé dans « L'équipe » : celui du rédacteur s'il existe, sinon `top_k`."""
        return self.writer_top_k or self.top_k


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


class TonalityTarget(_Strict):
    """Valeurs visées (planche de référence de l'auteur) ; None : pas de cible pour cette mesure."""

    dark_pct: float | None = Field(default=None, ge=0, le=100)
    black_pct: float | None = Field(default=None, ge=0, le=100)
    white_pct: float | None = Field(default=None, ge=0, le=100)
    saturation_pct: float | None = Field(default=None, ge=0, le=100)
    line_density_pct: float | None = Field(default=None, ge=0, le=100)


class TonalitySettings(_Strict):
    """Mesures de tonalité de chaque image générée (`presets/qc_tonality.yaml`, Pillow, CPU) : seuils de gris
    (0–255) et cible à atteindre, affichée en écart dans le détail de la case."""

    dark_below: int = Field(default=128, ge=1, le=255)
    black_below: int = Field(default=32, ge=1, le=255)
    white_from: int = Field(default=200, ge=1, le=255)
    reference: str = ""  # d'où vient la cible (affiché)
    target: TonalityTarget = Field(default_factory=TonalityTarget)


class VerdictReason(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=60)


class LengthBucket(_Strict):
    label: str = Field(min_length=1, max_length=40)
    max_words: int | None = Field(default=None, ge=1)  # None : sans limite (dernière tranche)


class JournalSettings(_Strict):
    """Journal des générations et verdicts de l'auteur (`presets/journal.yaml`) : raisons d'un rejet (liste
    fermée), seuil « peu de données » de la page Statistiques et tranches de longueur de prompt."""

    reasons: list[VerdictReason] = Field(default_factory=list)
    low_data_below: int = Field(default=20, ge=1, le=100000)
    prompt_length_buckets: list[LengthBucket] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> JournalSettings:
        ids = [r.id for r in self.reasons]
        if len(ids) != len(set(ids)):
            raise ValueError("reasons : identifiants en double")
        limits = [b.max_words for b in self.prompt_length_buckets]
        bounded = [m for m in limits if m is not None]
        if bounded != sorted(set(bounded)) or (None in limits and limits[-1] is not None):
            raise ValueError("prompt_length_buckets : tranches croissantes, la dernière seule sans limite")
        return self

    def reason_label(self, reason: str | None) -> str | None:
        if reason is None:
            return None
        return next((r.label for r in self.reasons if r.id == reason), reason)

    def bucket(self, words: int | None) -> str | None:
        if words is None:
            return None
        for b in self.prompt_length_buckets:
            if b.max_words is None or words <= b.max_words:
                return b.label
        return None
