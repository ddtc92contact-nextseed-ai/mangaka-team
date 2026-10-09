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


class ProjectUpdate(_In):
    title: Title | None = None
    style: LongText | None = None
    status: SeriesStatusName | None = None
    reading_direction: Direction | None = None
    page_format: PresetId | None = None
    workflow_preset: PresetId | None = None
    style_lora_name: LoraName | None = None
    style_lora_weight: LoraWeight | None = None


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


class PanelIn(_In):
    id: int | None = None
    description: LongText = ""
    characters: Annotated[list[Short], Field(max_length=20)] = Field(default_factory=list)
    shot_type: str | None = None
    importance: Annotated[int, Field(ge=1, le=3)] = 2
    dialogues: Annotated[list[BubbleIn], Field(max_length=12)] = Field(default_factory=list)


class PageIn(_In):
    id: int | None = None
    kind: PageKindName = "story"
    panels: Annotated[list[PanelIn], Field(max_length=9)] = Field(default_factory=list)


class BreakdownIn(_In):
    pages: Annotated[list[PageIn], Field(max_length=80)]


class BubbleOut(BaseModel):
    id: int
    speaker: str
    text: str
    kind: BubbleKindName


class PanelOut(BaseModel):
    id: int
    index: int
    description: str
    characters: list[str]
    shot_type: str | None
    importance: int
    dialogues: list[BubbleOut]
    bbox: dict[str, int] | None
    bubble_zone: dict[str, int] | None
    state: str = "draft"
    final_prompt: str | None = None
    final_prompt_manual: bool = False
    generation_preset: str | None = None
    image_count: int = 0
    selected_image_id: int | None = None
    selected_image_url: str | None = None
    # QC de la version choisie (None : pas encore contrôlée).
    qc_verdict: QCVerdictName | None = None
    qc_score: int | None = None
    qc_reasons: list[str] = Field(default_factory=list)
    qc_override: bool = False  # verdict forcé à ok par un humain
    detections: dict[str, Any] | None = None  # boîtes de la version choisie


class PageOut(BaseModel):
    id: int
    chapter_id: int
    number: int
    kind: PageKindName
    grid_template: str | None
    state: str
    layout: dict[str, Any] | None
    layout_stale: bool
    panels: list[PanelOut]


class PageLayoutIn(_In):
    # Absent = garder le gabarit actuel ; null = choix automatique ; sinon gabarit imposé.
    template_id: PresetId | None = None


class GutterMove(_In):
    path: Annotated[list[Annotated[int, Field(ge=0)]], Field(max_length=10)]
    index: Annotated[int, Field(ge=0)]
    position: float


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


class BubbleUpdate(_In):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    kind: BubbleKindName | None = None
    speaker: Short | None = None
    # Cadre / pointe ajustés à la main ; null = placement automatique.
    position: BubbleBox | None = None
    tail: TailPoint | None = None


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


class GenerateIn(_In):
    count: VariantCount = 1
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None
    preset: PresetId | None = None
    prompt_override: FinalPrompt | None = None


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
    url: str
    seed: int | None
    selected: bool
    width: int | None
    height: int | None
    preset: str | None
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
    created_at: datetime


class PanelUpdate(_In):
    # final_prompt : texte = édition manuelle conservée ; null ou "" = revenir au prompt automatique.
    final_prompt: FinalPrompt | None = None
    # generation_preset : null = choix automatique.
    generation_preset: PresetId | None = None


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
    reference_images: list[ReferenceImageOut]
    created_at: datetime
    updated_at: datetime


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
