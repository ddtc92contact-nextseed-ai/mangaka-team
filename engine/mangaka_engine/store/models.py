"""Modèle de données SQLite (SQLAlchemy 2).

Project → Character (+ images de référence) · Page → Panel (+ versions d'image) → Bubble · Job.
Les fichiers binaires (images) vivent dans `data/`, la base ne stocke que leurs chemins relatifs.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ReadingDirection(enum.StrEnum):
    ltr = "ltr"  # BD franco-belge / comics
    rtl = "rtl"  # manga


class PageState(enum.StrEnum):
    draft = "draft"
    layout = "layout"
    generating = "generating"
    review = "review"
    lettered = "lettered"
    done = "done"


class PanelState(enum.StrEnum):
    draft = "draft"
    queued = "queued"
    generating = "generating"
    qc = "qc"
    flagged = "flagged"
    approved = "approved"


class BubbleKind(enum.StrEnum):
    speech = "speech"
    thought = "thought"
    shout = "shout"
    narration = "narration"
    off = "off"


class JobStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


def _enum(e: type[enum.Enum]) -> Enum:
    return Enum(e, native_enum=False, validate_strings=True, length=20)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    style: Mapped[str] = mapped_column(Text, default="")
    reading_direction: Mapped[ReadingDirection] = mapped_column(_enum(ReadingDirection), default=ReadingDirection.rtl)
    page_format: Mapped[str] = mapped_column(String(100))
    workflow_preset: Mapped[str] = mapped_column(String(100))

    characters: Mapped[list[Character]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Character.name"
    )
    pages: Mapped[list[Page]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Page.number"
    )


class Character(TimestampMixin, Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    visual_description: Mapped[str] = mapped_column(Text, default="")
    prompt_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    lora_name: Mapped[str | None] = mapped_column(String(255), default=None)
    lora_weight: Mapped[float] = mapped_column(Float, default=0.8)

    project: Mapped[Project] = relationship(back_populates="characters")
    reference_images: Mapped[list[CharacterImage]] = relationship(
        back_populates="character", cascade="all, delete-orphan", order_by="CharacterImage.id"
    )


class CharacterImage(Base):
    __tablename__ = "character_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(500))  # relatif à data/
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    character: Mapped[Character] = relationship(back_populates="reference_images")


class Page(TimestampMixin, Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    grid_template: Mapped[str | None] = mapped_column(String(100), default=None)
    state: Mapped[PageState] = mapped_column(_enum(PageState), default=PageState.draft)

    project: Mapped[Project] = relationship(back_populates="pages")
    panels: Mapped[list[Panel]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="Panel.index"
    )


class Panel(TimestampMixin, Base):
    __tablename__ = "panels"
    __table_args__ = (UniqueConstraint("page_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    character_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    shot_type: Mapped[str | None] = mapped_column(String(50), default=None)
    dialogues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    importance: Mapped[int] = mapped_column(Integer, default=1)
    # Géométrie en pixels de la page : {"x", "y", "w", "h"}
    bbox: Mapped[dict[str, int] | None] = mapped_column(JSON, default=None)
    bubble_zone: Mapped[dict[str, int] | None] = mapped_column(JSON, default=None)
    final_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    generation_preset: Mapped[str | None] = mapped_column(String(100), default=None)
    qc_score: Mapped[int | None] = mapped_column(Integer, default=None)
    state: Mapped[PanelState] = mapped_column(_enum(PanelState), default=PanelState.draft)

    page: Mapped[Page] = relationship(back_populates="panels")
    images: Mapped[list[PanelImage]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", order_by="PanelImage.version"
    )
    bubbles: Mapped[list[Bubble]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", order_by="Bubble.order"
    )


class PanelImage(Base):
    """Une version générée d'une case (tout résultat est versionné)."""

    __tablename__ = "panel_images"
    __table_args__ = (UniqueConstraint("panel_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(500))
    seed: Mapped[int | None] = mapped_column(Integer, default=None)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    qc_score: Mapped[int | None] = mapped_column(Integer, default=None)
    qc_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    selected: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    panel: Mapped[Panel] = relationship(back_populates="images")


class Bubble(TimestampMixin, Base):
    __tablename__ = "bubbles"

    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    speaker_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[BubbleKind] = mapped_column(_enum(BubbleKind), default=BubbleKind.speech)
    position: Mapped[dict[str, int] | None] = mapped_column(JSON, default=None)  # {"x","y","w","h"}
    tail: Mapped[dict[str, int] | None] = mapped_column(JSON, default=None)  # {"x","y"} pointe de la queue

    panel: Mapped[Panel] = relationship(back_populates="bubbles")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    panel_id: Mapped[int | None] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    step: Mapped[str] = mapped_column(String(30))  # script | layout | generation | qc | lettering
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.pending)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
