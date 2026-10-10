"""Schémas d'entrée/sortie de l'API REST."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
PresetId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Direction = Literal["ltr", "rtl"]
SeriesStatusName = Literal["ongoing", "paused", "completed", "cancelled"]
ChapterStatusName = Literal["draft", "script", "layout", "generation", "lettering", "ready", "published"]
PageKindName = Literal["story", "bonus", "chapter_cover"]
BubbleKindName = Literal["speech", "thought", "shout", "narration", "off"]
QCVerdictName = Literal["ok", "review", "reject"]
LoraName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]
LoraWeight = Annotated[float, Field(ge=0, le=2)]
LoraTriggers = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
IntensityName = Literal["calme", "normal", "choc"]
RythmeName = Literal["lent", "normal", "rapide"]
FrameKindName = Literal["border", "none", "fade"]
# Débruitage du passage au propre (palier croquis) : 0 = croquis inchangé, 1 = image neuve.
Denoise = Annotated[float, Field(ge=0.05, le=1)]
ImageKindName = Literal["final", "croquis"]
# Passage au propre : image → image depuis le croquis (débruitage) ou ControlNet (composition verrouillée).
CleanModeName = Literal["img2img", "controlnet"]
ControlTypeId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
# Force du patch ControlNet : 0 = contrôle ignoré, 1 = composition tenue (défaut), jusqu'à 2.
ControlStrength = Annotated[float, Field(ge=0, le=2)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Séries (table « projects ») ---------------------------------------------
class ProjectCreate(_In):
    title: Title
    style: LongText = ""
    status: SeriesStatusName = "ongoing"
    reading_direction: Direction = "rtl"
    page_format: PresetId | None = None
    workflow_preset: PresetId | None = None
    style_lora_name: LoraName | None = None
    style_lora_weight: LoraWeight = 0.8
    style_lora_trigger_words: LoraTriggers = ""
    # Absent : style par défaut des presets (« dynamique »).
    layout_style: PresetId | None = None
    # Absent : `sketch_enabled` de presets/defaults.yaml (activé).
    sketch_enabled: bool | None = None
    sketch_denoise: Denoise | None = None
    clean_mode: CleanModeName = "img2img"
    clean_control: ControlTypeId | None = None  # null : type par défaut du preset ControlNet
    # Agrandisseur de la finition d'impression (None : celui de defaults.yaml).
    upscaler: PresetId | None = None


class ProjectUpdate(_In):
    title: Title | None = None
    style: LongText | None = None
    status: SeriesStatusName | None = None
    reading_direction: Direction | None = None
    page_format: PresetId | None = None
    workflow_preset: PresetId | None = None
    style_lora_name: LoraName | None = None
    style_lora_weight: LoraWeight | None = None
    style_lora_trigger_words: LoraTriggers | None = None
    layout_style: PresetId | None = None
    sketch_enabled: bool | None = None
    sketch_denoise: Denoise | None = None  # null : `denoise` du preset « propre »
    clean_mode: CleanModeName | None = None
    clean_control: ControlTypeId | None = None  # null : type par défaut du preset ControlNet
    upscaler: PresetId | None = None  # null : revient à l'agrandisseur de defaults.yaml


class ProjectOut(BaseModel):
    id: int
    title: str
    style: str
    status: SeriesStatusName
    reading_direction: Direction
    page_format: str
    workflow_preset: str
    style_lora_name: str | None
    style_lora_weight: float
    style_lora_trigger_words: str
    layout_style: str
    sketch_enabled: bool = True
    sketch_denoise: float | None = None
    clean_mode: CleanModeName = "img2img"
    clean_control: str | None = None
    upscaler: str | None = None
    character_count: int
    chapter_count: int
    # Pages déjà mises en page : changer le sens de lecture les recalcule (confirmation dans l'UI).
    laid_out_page_count: int = 0
    created_at: datetime
    updated_at: datetime


# --- Chapitres ------------------------------------------------------------------
Synopsis = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)]
PageCount = Annotated[int, Field(ge=1, le=60)]


class ChapterCreate(_In):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    number: Annotated[int, Field(ge=1, le=100000)] | None = None
    synopsis: Synopsis = ""
    target_page_count: PageCount = 15
    status: ChapterStatusName = "draft"
    planned_date: date | None = None


class ChapterUpdate(_In):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    synopsis: Synopsis | None = None
    summary: Synopsis | None = None
    target_page_count: PageCount | None = None
    status: ChapterStatusName | None = None
    planned_date: date | None = None


class ChapterReorder(_In):
    chapter_ids: list[int] = Field(min_length=1)


class ChapterOut(BaseModel):
    id: int
    project_id: int
    series_title: str
    number: int
    title: str
    synopsis: str
    summary: str
    target_page_count: int
    status: ChapterStatusName
    planned_date: date | None
    page_count: int
    panel_count: int
    created_at: datetime
    updated_at: datetime


# --- Découpage (pages → cases → bulles) ---------------------------------------
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class BubbleIn(_In):
    id: int | None = None  # les bulles sont recréées ; l'id ne sert qu'à garder leur position de lettrage
    speaker: Short = ""
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    kind: BubbleKindName = "speech"


SfxText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class SfxIn(_In):
    id: int | None = None  # recréées comme les bulles ; l'id garde leurs réglages de lettrage
    text: SfxText
    intensity: IntensityName | None = None


MAX_PANEL_OBJECTS = 8


class PanelIn(_In):
    id: int | None = None
    description: LongText = ""
    characters: Annotated[list[Short], Field(max_length=20)] = Field(default_factory=list)
    shot_type: str | None = None
    importance: Annotated[int, Field(ge=1, le=3)] = 2
    intensity: IntensityName | None = None
    dialogues: Annotated[list[BubbleIn], Field(max_length=12)] = Field(default_factory=list)
    # Onomatopées : absent = celles de la case sont gardées telles quelles.
    sfx: Annotated[list[SfxIn], Field(max_length=8)] | None = None
    # Bibliothèque de la série (ids) : absent = gardés tels quels ; decor null = pas de décor.
    decor: int | None = None
    objets: Annotated[list[int], Field(max_length=MAX_PANEL_OBJECTS)] | None = None


class PageIn(_In):
    id: int | None = None
    kind: PageKindName = "story"
    rythme: RythmeName | None = None
    panels: Annotated[list[PanelIn], Field(max_length=9)] = Field(default_factory=list)


class BreakdownIn(_In):
    pages: Annotated[list[PageIn], Field(max_length=80)]


class BubbleOut(BaseModel):
    id: int
    speaker: str
    text: str
    kind: BubbleKindName


class SfxOut(BaseModel):
    id: int
    text: str
    intensity: IntensityName | None = None


class PanelFrameIn(_In):
    """Options de cadre imposées à une case ; null (ou absent) = décidée par le style de mise en page."""

    frame: FrameKindName | None = None
    bleed: bool | None = None
    inset: bool | None = None


class PrintInfoOut(BaseModel):
    """Dpi effectif de la version retenue à l'impression (finition d'impression)."""

    image_id: int
    status: Literal["ok", "finished", "low"]  # au dpi cible · finalisée · sous le seuil
    target_dpi: int  # dpi du format de page
    min_dpi: int  # seuil : finishing_tolerance × dpi cible
    box_width: int  # boîte imprimée (px au dpi cible, fond perdu compris)
    box_height: int
    width_mm: float
    height_mm: float
    source_width: int
    source_height: int
    dpi: int  # dpi effectif de la version retenue
    factor: float  # agrandissement nécessaire pour atteindre le dpi cible
    target_width: int  # taille finale de la finition
    target_height: int
    needed: bool
    finished: bool
    finished_dpi: int | None = None
    finished_width: int | None = None
    finished_height: int | None = None
    finished_upscaler: str | None = None


class PanelOut(BaseModel):
    id: int
    index: int
    description: str
    characters: list[str]
    decor: int | None = None  # décor de la bibliothèque (id)
    objets: list[int] = Field(default_factory=list)  # objets de la bibliothèque (ids)
    shot_type: str | None
    importance: int
    intensity: IntensityName | None = None
    dialogues: list[BubbleOut]
    sfx: list[SfxOut] = Field(default_factory=list)
    # Options de cadre imposées dans l'UI (les options effectives sont dans layout.panels).
    frame: PanelFrameIn | None = None
    bbox: dict[str, int] | None
    bubble_zone: dict[str, int] | None
    state: str = "draft"
    final_prompt: str | None = None
    final_prompt_manual: bool = False
    generation_preset: str | None = None
    image_count: int = 0  # versions propres (les croquis sont comptés à part)
    selected_image_id: int | None = None
    selected_image_url: str | None = None
    # Palier croquis : nombre de croquis, croquis montré (validé, sinon le plus récent), validation.
    sketch_count: int = 0
    sketch_image_id: int | None = None
    sketch_image_url: str | None = None
    sketch_validated: bool = False
    sketch_denoise: float | None = None
    # Version propre déjà tirée du croquis validé.
    sketch_cleaned: bool = False
    # Composition verrouillée (ControlNet) : type de contrôle du verrou, None = composition libre.
    composition_lock: str | None = None
    # QC de la version choisie (None : pas encore contrôlée).
    qc_verdict: QCVerdictName | None = None
    qc_score: int | None = None
    qc_reasons: list[str] = Field(default_factory=list)
    qc_override: bool = False  # verdict forcé à ok par un humain
    detections: dict[str, Any] | None = None  # boîtes de la version choisie
    # Le ratio de la case s'écarte trop de celui de l'image retenue (seuil : presets/layout.yaml).
    regeneration_advised: bool = False
    # Dpi de la version retenue à l'impression (None : pas de version retenue ou pas de mise en page).
    print_info: PrintInfoOut | None = None
    # Dernière génération de la case (tous jobs confondus, sans limite) : pour afficher un échec et son erreur.
    last_job_id: int | None = None
    last_job_status: str | None = None
    last_job_error: str | None = None


class PageOut(BaseModel):
    id: int
    chapter_id: int
    number: int
    kind: PageKindName
    grid_template: str | None
    layout_style: str | None = None  # style imposé à la page (None = celui de la série)
    layout_seed: int | None = None
    rythme: RythmeName | None = None
    state: str
    layout: dict[str, Any] | None
    layout_stale: bool
    panels: list[PanelOut]


class PageLayoutIn(_In):
    # Absent = garder le gabarit actuel ; null = choix automatique ; sinon gabarit imposé.
    template_id: PresetId | None = None
    # Absent = garder ; null = style de la série ; sinon style imposé à cette page.
    style: PresetId | None = None
    # True : « Nouvelle mise en page » (nouvelle graine, autre gabarit si possible).
    reroll: bool = False


FinitePx = Annotated[float, Field(allow_inf_nan=False)]


class CutSlant(_In):
    """Incline une découpe : positions (px de la page, le long de l'axe découpé) de ses deux extrémités."""

    path: Annotated[list[Annotated[int, Field(ge=0)]], Field(max_length=10)]
    index: Annotated[int, Field(ge=0)]
    ends: Annotated[list[FinitePx], Field(min_length=2, max_length=2)]


class GutterMove(_In):
    path: Annotated[list[Annotated[int, Field(ge=0)]], Field(max_length=10)]
    index: Annotated[int, Field(ge=0)]
    position: FinitePx


# --- Lettrage (étape 5) ------------------------------------------------------
Coord = Annotated[int, Field(ge=-100000, le=100000)]
Extent = Annotated[int, Field(ge=20, le=100000)]


class BubbleBox(_In):
    x: Coord
    y: Coord
    w: Extent
    h: Extent


class TailPoint(_In):
    x: Coord
    y: Coord


class SfxParams(_In):
    """Réglages d'une onomatopée (écran Lettrage) : une clé envoyée à null rend la valeur au calcul automatique."""

    intensity: IntensityName | None = None
    font: PresetId | None = None
    size_pt: Annotated[float, Field(ge=4, le=300, allow_inf_nan=False)] | None = None
    angle: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)] | None = None
    skew: Annotated[float, Field(ge=-45, le=45, allow_inf_nan=False)] | None = None
    # Centre (px de la page) placé à la main ; x et y vont ensemble.
    x: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None
    y: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None


class BubbleUpdate(_In):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    kind: BubbleKindName | None = None
    speaker: Short | None = None
    # Cadre / pointe ajustés à la main ; null = placement automatique.
    position: BubbleBox | None = None
    tail: TailPoint | None = None
    # Onomatopée seulement.
    sfx: SfxParams | None = None


class SfxCreate(_In):
    text: SfxText
    intensity: IntensityName = "normal"
    x: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None
    y: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None


class RenderIn(_In):
    bleed: bool = False
    crop_marks: bool = False


class ExportIn(_In):
    bleed: bool = False
    crop_marks: bool = False


# --- Jobs ----------------------------------------------------------------------
class JobOut(BaseModel):
    id: int
    step: str
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    progress: int
    message: str
    error: str | None
    project_id: int | None
    chapter_id: int | None
    panel_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


# --- Génération (étape 3) ------------------------------------------------------
MAX_SEED = 2**63 - 1
VariantCount = Annotated[int, Field(ge=1, le=4)]
FinalPrompt = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class ComfyTrialIn(_In):
    preset: PresetId | None = None  # null : workflow par défaut des séries


class GenerateIn(_In):
    count: VariantCount = 1
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None
    preset: PresetId | None = None
    prompt_override: FinalPrompt | None = None


RepairTarget = Literal["face", "hand", "zone"]


class RepairRegionIn(_In):
    """Rectangle à repeindre, en px de l'image de la version (détection du QC ou rectangle tracé)."""

    x1: Annotated[float, Field(ge=0, le=100_000)]
    y1: Annotated[float, Field(ge=0, le=100_000)]
    x2: Annotated[float, Field(ge=0, le=100_000)]
    y2: Annotated[float, Field(ge=0, le=100_000)]
    # Une boîte de `PanelImage.detections` peut être renvoyée telle quelle (score et étiquette ignorés).
    score: float | None = None
    label: Annotated[str, StringConstraints(max_length=40)] | None = None


class RepairIn(_In):
    """Réparation ciblée d'une version : zone (rectangles et/ou masque peint), prompt et réglages."""

    regions: Annotated[list[RepairRegionIn], Field(max_length=50)] = Field(default_factory=list)
    # Masque peint : PNG en base64 (data URL acceptée), blanc ou opaque = à repeindre ; redimensionné.
    mask_png: Annotated[str, StringConstraints(max_length=20_000_000)] | None = None
    target: RepairTarget = "zone"
    character_id: int | None = None
    prompt: FinalPrompt | None = None
    grow_px: Annotated[int, Field(ge=0, le=256)] | None = None
    feather_px: Annotated[int, Field(ge=0, le=128)] | None = None
    denoise: Annotated[float, Field(ge=0.05, le=1)] | None = None
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None


class RepairCharacterOut(BaseModel):
    id: int
    name: str


class RepairInfoOut(BaseModel):
    """Préremplissage de la fenêtre « Réparer » : preset, réglages par défaut, prompt, personnages."""

    available: bool
    problem: str | None = None  # pourquoi la réparation est impossible (croquis, preset manquant…)
    preset: str | None = None
    preset_name: str | None = None
    tier: str | None = None
    grow_px: int = 0
    feather_px: int = 0
    denoise: float = 0.45
    target: RepairTarget = "zone"
    character_id: int | None = None
    characters: list[RepairCharacterOut] = Field(default_factory=list)
    prompt: str = ""


class BatchGenerateIn(_In):
    force: bool = False
    count: VariantCount = 1
    preset: PresetId | None = None


class BatchGenerateOut(BaseModel):
    jobs: list[JobOut]
    panel_ids: list[int]
    skipped: int


class PanelImageOut(BaseModel):
    id: int
    panel_id: int
    version: int
    kind: ImageKindName = "final"  # croquis : jamais choisi, assemblé ni exporté
    url: str
    seed: int | None
    selected: bool
    width: int | None
    height: int | None
    preset: str | None
    tier: str | None = None  # palier du preset qui a produit la version (Turbo, Rapide, Qualité)
    params: dict[str, Any]
    qc_score: int | None
    qc_reasons: list[str]
    qc_verdict: QCVerdictName | None = None
    # Détail du dernier QC : couches (statut, score, durée, raisons), décision humaine, historique.
    qc: dict[str, Any] = Field(default_factory=dict)
    # Boîtes détectées en px de l'image : {"width", "height", "faces": [...], "hands": [...], "text": [...]}.
    detections: dict[str, Any] | None = None
    # Jugement humain « bonne / mauvaise » (banc d'essai du QC), indépendant du verdict QC.
    annotation: AnnotationOut | None = None
    # Finition d'impression de la version (image agrandie dérivée) : taille, agrandisseur, dpi…
    finish: dict[str, Any] | None = None
    created_at: datetime


class UpscalerOut(BaseModel):
    id: str
    name: str
    description: str
    model_scale: float | None
    high_fidelity: bool
    is_default: bool
    estimated_s: float | None
    timeout_s: float


class FinishBatchOut(BaseModel):
    jobs: list[JobOut]
    panel_ids: list[int]
    skipped: int  # cases déjà au dpi cible, déjà finalisées, sans version ou déjà en file


class PageFinishingOut(BaseModel):
    page_id: int
    upscaler: str | None  # nom de l'agrandisseur de la série
    panels: dict[int, PrintInfoOut | None]
    active_jobs: list[JobOut]


class PanelUpdate(_In):
    # final_prompt : texte = édition manuelle conservée ; null ou "" = revenir au prompt automatique.
    final_prompt: FinalPrompt | None = None
    # generation_preset : null = choix automatique.
    generation_preset: PresetId | None = None
    # Description de la case (tri des croquis : « modifier la description puis re-croquer »).
    description: LongText | None = None
    # Débruitage du passage au propre de cette case ; null = celui de la série (sinon du preset).
    sketch_denoise: Denoise | None = None


class CompositionLockIn(_In):
    """« Verrouiller la composition » depuis le croquis validé ou une version de la case."""

    source: Literal["croquis", "version"]
    image_id: int | None = None  # croquis : null = le croquis validé ; version : obligatoire
    type: ControlTypeId | None = None  # null : type par défaut du preset ControlNet
    strength: ControlStrength | None = None  # null : force par défaut du preset


class CompositionLockUpdate(_In):
    type: ControlTypeId | None = None
    strength: ControlStrength | None = None


class ControlPreviewOut(BaseModel):
    status: Literal["none", "pending", "running", "ready", "failed", "cancelled"]
    url: str | None = None  # dernière carte produite (peut être celle d'un type précédent pendant le calcul)
    type: str | None = None  # type de la carte affichée (peut différer du type du verrou pendant un recalcul)
    type_name: str | None = None
    job_id: int | None = None
    error: str | None = None
    width: int | None = None
    height: int | None = None


class CompositionLockOut(BaseModel):
    source: Literal["croquis", "version", "import"]
    source_label: str  # « croquis v2 », « version 3 », « image importée »
    image_id: int | None = None
    version: int | None = None
    source_url: str
    type: str
    type_name: str
    strength: float
    locked_at: str | None = None
    preset: str | None = None  # preset ControlNet des prochaines générations
    preset_name: str | None = None
    problem: str | None = None  # le palier de la case ne propose pas de ControlNet…
    preview: ControlPreviewOut


class LibraryRef(BaseModel):
    """Élément de la bibliothèque cité par une case (personnage, objet ou décor)."""

    id: int
    kind: Literal["character", "object", "decor"]
    name: str


class PanelDetailOut(BaseModel):
    id: int
    page_id: int
    page_number: int
    chapter_id: int
    project_id: int
    index: int
    label: str
    description: str
    characters: list[str]
    character_ids: list[int]
    decor: LibraryRef | None = None
    objets: list[LibraryRef] = Field(default_factory=list)
    shot_type: str | None
    state: str
    bbox: dict[str, int] | None
    final_prompt: str | None
    final_prompt_manual: bool
    generation_preset: str | None
    resolved_preset: str | None
    target: dict[str, int] | None
    images: list[PanelImageOut]
    active_jobs: list[JobOut]
    sketch_image_id: int | None = None  # croquis validé
    sketch_denoise: float | None = None
    print_info: PrintInfoOut | None = None
    upscaler: str | None = None  # agrandisseur de la finition (nom), None si aucun configuré
    composition_lock: CompositionLockOut | None = None  # None : composition libre


class QueueItemOut(BaseModel):
    job: JobOut
    position: int  # 0 = en cours, 1 = prochain…
    label: str
    panel_id: int | None
    panel_index: int | None
    page_id: int | None
    page_number: int | None
    chapter_id: int | None
    chapter_number: int | None
    chapter_title: str | None
    project_id: int | None
    series_title: str | None
    preset: str | None
    tier: str | None = None  # palier du preset (« Turbo », « Rapide », « Qualité »)
    variant: int | None
    count: int | None
    estimated_duration_s: float | None  # médiane des générations réussies du même preset
    eta_s: float | None  # temps restant avant la fin de ce job


class QueueOut(BaseModel):
    running: QueueItemOut | None
    pending: list[QueueItemOut]
    total_eta_s: float | None
    comfyui: str | None  # http | mock


class WorkflowPresetOut(BaseModel):
    id: str
    name: str
    description: str
    params: list[str]
    reference_slots: int
    supports_lora: bool
    lora_loader: str | None
    timeout_s: float
    is_default: bool
    is_reference_default: bool
    with_references: str | None = None  # workflow du même palier pour les cases avec références
    has_trial: bool = False
    tier: str | None = None  # Turbo, Rapide, Qualité
    tier_choice: str | None = None  # libellé dans la fiche série (absent : pas proposé comme palier)
    tier_order: int | None = None
    estimated_s: float | None = None
    is_quality: bool = False  # palier de « Régénérer en Qualité »
    role: Literal["generation", "croquis", "propre", "controle"] = "generation"
    from_sketch: str | None = None  # workflow « propre depuis croquis » du même palier
    with_control: str | None = None  # workflow ControlNet (composition verrouillée) du même palier
    is_sketch: bool = False  # workflow des croquis (defaults.workflow_sketch)


class PresetEstimateOut(BaseModel):
    preset: str
    tier: str | None
    panels: int
    per_panel_s: float | None
    measured: bool  # médiane de vraies durées (≥ 3) ; sinon `estimated_s` du preset
    samples: int


class EstimateOut(BaseModel):
    remaining_panels: int
    total_s: float | None  # None : un preset sans durée connue ni `estimated_s`
    measured: bool  # False : au moins une partie vient des estimations des presets (« estimation »)
    by_preset: list[PresetEstimateOut]


# --- Palier croquis ----------------------------------------------------------------
class SketchIn(_In):
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None  # null : nouvelle graine


class SketchValidateIn(_In):
    image_id: int | None = None  # null : le croquis le plus récent


class CleanIn(_In):
    denoise: Denoise | None = None  # null : case > série > preset


class SketchEstimateOut(BaseModel):
    panels: int  # cases de la page / du chapitre
    to_sketch: int  # cases encore à croquer (sans version propre ni croquis validé)
    validated: int  # cases au croquis validé
    to_clean: int  # cases validées sans version propre tirée de leur croquis
    sketch: EstimateOut  # « croquis de la page »
    clean: EstimateOut  # « passage au propre des cases validées »


# --- Contrôle qualité (étape 4) ------------------------------------------------
# auto : la vision ne tourne que si les couches 1-2 hésitent ; force : toujours ; skip : jamais.
VisionModeName = Literal["auto", "force", "skip"]


class PanelQCIn(_In):
    image_id: int | None = None  # absent : la version choisie (sinon la plus récente)
    vision: VisionModeName = "auto"


class ChapterQCIn(_In):
    force: bool = False  # True : recontrôle aussi les cases déjà contrôlées
    vision: VisionModeName = "auto"


class QCOverrideIn(_In):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class QCSummaryOut(BaseModel):
    ok: int
    review: int
    reject: int
    unchecked: int
    no_image: int
    total: int


class ChapterQCOut(BaseModel):
    job: JobOut | None
    panel_ids: list[int]
    skipped: int
    summary: QCSummaryOut


class QCLayerStatusOut(BaseModel):
    provider: str | None
    available: bool
    detail: str | None


class QCStatusOut(BaseModel):
    available: bool  # preset valide et au moins une couche disponible
    detail: str | None
    auto_after_generation: bool
    max_auto_retries: int
    ok_min: int | None
    reject_below: int | None
    vision_mode: str | None
    layers: dict[str, QCLayerStatusOut]


# --- Personnages -----------------------------------------------------------
def _clean_keywords(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    out: list[str] = []
    for kw in value:
        kw = kw.strip()
        if kw and kw not in out:
            out.append(kw)
    return out


Keywords = Annotated[list[Annotated[str, StringConstraints(max_length=100)]], Field(max_length=50)]


class CharacterCreate(_In):
    name: Name
    visual_description: LongText = ""
    prompt_keywords: Keywords = Field(default_factory=list)
    lora_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    lora_weight: float = Field(default=0.8, ge=0, le=2)
    lora_trigger_words: LoraTriggers = ""

    _kw = field_validator("prompt_keywords")(_clean_keywords)

    @field_validator("lora_name")
    @classmethod
    def _empty_lora(cls, v: str | None) -> str | None:
        return v or None


class CharacterUpdate(_In):
    name: Name | None = None
    visual_description: LongText | None = None
    prompt_keywords: Keywords | None = None
    lora_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    lora_weight: float | None = Field(default=None, ge=0, le=2)
    lora_trigger_words: LoraTriggers | None = None

    _kw = field_validator("prompt_keywords")(_clean_keywords)


class ReferenceImageOut(BaseModel):
    id: int
    url: str
    original_name: str
    content_type: str
    width: int
    height: int
    created_at: datetime


class CharacterOut(BaseModel):
    id: int
    project_id: int
    name: str
    visual_description: str
    prompt_keywords: list[str]
    lora_name: str | None
    lora_weight: float
    lora_trigger_words: str
    reference_images: list[ReferenceImageOut]
    created_at: datetime
    updated_at: datetime


# --- Objets et décors de la bibliothèque (mêmes champs qu'un personnage) ------
AssetKindName = Literal["object", "decor"]
AssetCreate = CharacterCreate
AssetUpdate = CharacterUpdate


class AssetOut(CharacterOut):
    kind: AssetKindName


class ImageOrderIn(_In):
    """Nouvel ordre des images de référence d'une fiche (toutes, une fois chacune) ; la 1re est la principale."""

    image_ids: list[int] = Field(min_length=1, max_length=200)


# --- « Créer des références » (fiches générées par ComfyUI) ---------------------
LibraryKindName = Literal["character", "object", "decor"]
Instruction = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ReferenceSheetOut(BaseModel):
    id: str
    name: str
    description: str
    kinds: list[LibraryKindName]
    width: int
    height: int
    workflow: str | None  # None : palier de la série (ou Qualité)


class ReferenceGenerateIn(_In):
    sheet: PresetId
    count: VariantCount = 4
    quality: bool = False  # palier Qualité au lieu de celui de la série
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None


class ReferenceRefineIn(_In):
    instruction: Instruction = Field(min_length=1)
    count: VariantCount = 4
    quality: bool = False
    sheet: PresetId | None = None  # par défaut : celui de la variante de départ


class ReferenceVariantOut(BaseModel):
    id: int
    entry_kind: LibraryKindName
    entry_id: int
    url: str
    sheet: str
    sheet_name: str
    preset: str | None
    tier: str | None
    seed: int | None
    width: int
    height: int
    prompt: str
    instruction: str
    parent_id: int | None
    kept: bool  # gardée parmi les images de référence de la fiche (et toujours présente)
    kept_image_id: int | None
    job_id: int | None
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ReferenceStudioOut(BaseModel):
    """Historique des variantes d'une fiche (plus récentes d'abord) et générations en cours."""

    variants: list[ReferenceVariantOut]
    active_jobs: list[JobOut]
    max_kept: int
    kept_count: int
    reference_slots: int  # emplacements d'images de référence d'une case (workflow « avec références »)


# --- Banc d'essai du QC -----------------------------------------------------------
AnnotationLabelName = Literal["good", "bad"]
DefectName = Literal["face", "hands", "identity", "description", "text", "other"]


class AnnotationIn(_In):
    label: AnnotationLabelName
    defects: list[DefectName] = Field(default_factory=list, max_length=6)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""

    @field_validator("defects")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class AnnotationOut(BaseModel):
    label: AnnotationLabelName
    defects: list[str]
    note: str
    updated_at: datetime


class BenchDatasetOut(BaseModel):
    good: int
    bad: int
    total: int
    by_defect: dict[str, int]
    goal_min: int | None
    goal_max: int | None
    target_recall: float | None


class BenchRunIn(_In):
    project_id: int | None = None
    chapter_id: int | None = None
    vision: bool = True  # False : sans la couche vision (lente)


class BenchRunOut(BaseModel):
    id: int
    job: JobOut | None
    status: str  # pending | running | succeeded | failed | cancelled
    error: str | None
    project_id: int | None
    chapter_id: int | None
    scope: str
    vision: bool
    preset_hash: str | None
    sample_count: int
    good: int | None
    bad: int | None
    created_at: datetime
    finished_at: datetime | None
    applied_at: datetime | None
    # Résumé par couche : précision, rappel, FP, FN, cases évaluées, temps moyen.
    layers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BenchRunDetailOut(BenchRunOut):
    metrics: dict[str, Any] | None
    items: list[dict[str, Any]]
    preset: dict[str, Any]
    previous: BenchRunOut | None
    current_preset_hash: str | None


class BenchApplyIn(_In):
    confirm: bool = False  # False : aperçu des modifications, rien n'est écrit


class BenchApplyOut(BaseModel):
    applied: bool
    changes: list[dict[str, Any]]
    preset_changed: bool  # le preset a changé depuis ce run
    message: str


# --- Savoir-faire et bible ----------------------------------------------------
KnowledgeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500_000)]
BibleField = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class CollectionCreate(_In):
    name: Name
    description: LongText = ""
    project_id: int | None = None  # None : collection globale


class CollectionUpdate(_In):
    name: Name | None = None
    description: LongText | None = None
    project_id: int | None = None


class CollectionOut(BaseModel):
    id: int
    name: str
    description: str
    project_id: int | None
    project_title: str | None
    document_count: int
    chunk_count: int
    token_count: int
    whole: bool  # sous le seuil « petite collection » : injectée entière
    created_at: datetime
    updated_at: datetime


class DocumentCreate(_In):
    title: Title
    content: KnowledgeText
    tags: list[Tag] = Field(default_factory=list, max_length=20)


class DocumentUpdate(_In):
    title: Title | None = None
    content: KnowledgeText | None = None
    tags: list[Tag] | None = Field(default=None, max_length=20)


class ChunkOut(BaseModel):
    id: int
    index: int
    heading: str
    text: str
    token_count: int
    embedded: bool


class DocumentSummaryOut(BaseModel):
    id: int
    collection_id: int
    title: str
    source: str
    original_name: str | None
    tags: list[str]
    token_count: int
    chunk_count: int
    index_error: str | None
    created_at: datetime
    updated_at: datetime


class DocumentOut(DocumentSummaryOut):
    content: str
    collection_name: str
    chunks: list[ChunkOut]


class SearchIn(_In):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    collection_ids: list[int] | None = None
    project_id: int | None = None  # collections de la série + collections globales
    top_k: int | None = Field(default=None, ge=1, le=50)
    budget_tokens: int | None = Field(default=None, ge=0, le=32000)


class PassageOut(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    collection_id: int
    collection_name: str
    heading: str
    text: str
    tokens: int
    score: float | None
    vector_score: float | None
    keyword_score: float | None
    mode: Literal["retrieved", "whole"]
    selected: bool = False


class BibleSummary(BaseModel):
    text: str
    tokens: int
    truncated: bool
    chapter_summaries: int


class SearchOut(BaseModel):
    query: str
    collections: list[str]
    passages: list[PassageOut]  # classement complet
    selected_tokens: int
    budget_tokens: int
    top_k: int
    bible: BibleSummary | None = None
    warning: str | None = None


class BibleCharacter(BaseModel):
    id: int
    name: str
    visual_description: str
    note: str


class BibleAsset(BaseModel):
    """Objet ou décor de la bibliothèque, repris dans la bible injectée aux agents."""

    id: int
    name: str
    visual_description: str


class ChapterSummaryEntry(BaseModel):
    chapter_id: int | None = None
    number: int | None = None
    title: str = ""
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
    added_at: str | None = None


class BibleUpdate(_In):
    world: BibleField | None = None
    tone: BibleField | None = None
    rules: BibleField | None = None
    motifs: BibleField | None = None
    character_notes: dict[int, Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]] | None = None
    chapter_summaries: list[ChapterSummaryEntry] | None = Field(default=None, max_length=1000)


class BibleOut(BaseModel):
    project_id: int
    world: str
    tone: str
    rules: str
    motifs: str
    characters: list[BibleCharacter]
    decors: list[BibleAsset] = Field(default_factory=list)
    objets: list[BibleAsset] = Field(default_factory=list)
    chapter_summaries: list[ChapterSummaryEntry]
    rendered: BibleSummary | None
    updated_at: datetime | None


class SourcesOut(BaseModel):
    run_id: int
    job_id: int | None
    agent: str
    model: str | None
    collections: list[str]
    passages: list[PassageOut]
    bible: BibleSummary | None
    created_at: datetime


class KnowledgeAgentOut(BaseModel):
    role: str
    label: str
    collections: list[str]  # noms demandés (profil ou knowledge.yaml)
    source: Literal["profile", "preset"]
    series_collections: bool
    budget_tokens: int
    top_k: int
    bible: bool


class KnowledgeStatusOut(BaseModel):
    provider: str | None
    model: str | None
    available: bool
    detail: str | None
    collections: int
    documents: int
    chunks: int
    stale_chunks: int  # sans vecteur, ou vecteur d'un autre modèle : à réindexer
    small_collection_tokens: int
    vector_backend: str
    agents: list[KnowledgeAgentOut]


class ReindexOut(BaseModel):
    documents: int
    chunks: int
    errors: list[str]
