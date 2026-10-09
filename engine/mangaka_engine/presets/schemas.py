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


class FontsPreset(_Strict):
    fonts: dict[str, FontFile] = Field(min_length=1)
    styles: dict[str, TextStyle]
    # Libellé « case manquante » dessiné sur l'aplat gris d'une case sans image.
    missing_panel: TextStyle
    hyphenation: Hyphenation = Field(default_factory=Hyphenation)

    @model_validator(mode="after")
    def _check(self) -> FontsPreset:
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
