"""Schémas d'entrée/sortie de l'API REST."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
PresetId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Direction = Literal["ltr", "rtl"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Projets ---------------------------------------------------------------
class ProjectCreate(_In):
    title: Title
    style: LongText = ""
    reading_direction: Direction = "rtl"
    page_format: PresetId | None = None
    workflow_preset: PresetId | None = None


class ProjectUpdate(_In):
    title: Title | None = None
    style: LongText | None = None
    reading_direction: Direction | None = None
    page_format: PresetId | None = None
    workflow_preset: PresetId | None = None


class ProjectOut(BaseModel):
    id: int
    title: str
    style: str
    reading_direction: Direction
    page_format: str
    workflow_preset: str
    character_count: int
    created_at: datetime
    updated_at: datetime


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
