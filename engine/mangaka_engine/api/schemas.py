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
    id: int | None = None  # ignoré : les bulles sont recréées
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
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


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
