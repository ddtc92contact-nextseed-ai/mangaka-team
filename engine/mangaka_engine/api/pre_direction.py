"""ADN de la série (fiche série) et ce que le scénariste recevra (écran Scénario) — voir pipeline/pre_direction.py.

- `GET /projects/{id}/pre-direction` : valeurs héritées du genre, valeurs ajustées par la série, valeurs
  effectives, et les réglages (familles, libellés, types et bornes) pour la carte « ADN de la série » ;
- `PUT /projects/{id}/pre-direction` : ajustements de la série (chemin → valeur ; `{}` : tout hériter du genre).
  Une valeur égale à celle du genre n'est pas gardée : elle suit le genre s'il change ;
- `GET /chapters/{id}/script-brief` : charte envoyée au scénariste et au directeur artistique (`$pre_direction`,
  en clair), seuil de l'avertissement « trop de personnages » d'une case (`crowd_limit`) et alerte « bible vide » (bible de la série vide, personnages cités sans note) — un avertissement,
  jamais un blocage.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.framing import cites
from ..pipeline.knowledge import get_bible
from ..pipeline.pre_direction import (
    GROUPS,
    DnaError,
    apply_overrides,
    art_text,
    clean_overrides,
    field_specs,
    flatten,
    inherited_dna,
    script_text,
    series_charter,
)
from ..store.models import Chapter, Character, PageKind, Project
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .projects import get_project_or_404

router = APIRouter(tags=["adn"])

DnaValue = float | int | bool


class DnaField(BaseModel):
    path: str
    group: str
    label: str
    help: str = ""
    kind: str  # share (part de 0 à 1), int, bool
    min: float | None = None
    max: float | None = None
    step: float | None = None


class PreDirectionOut(BaseModel):
    project_id: int
    genre: str | None
    genre_name: str | None
    available: bool  # presets/pre_direction.yaml chargé
    groups: dict[str, str]
    fields: list[DnaField]
    inherited: dict[str, DnaValue]  # valeurs du genre (chemin → valeur)
    overrides: dict[str, DnaValue]  # valeurs ajustées par la série
    effective: dict[str, DnaValue]


class PreDirectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, DnaValue] = Field(default_factory=dict, max_length=100)


class BibleCharacterRef(BaseModel):
    id: int
    name: str


class ScriptBriefOut(BaseModel):
    project_id: int
    pre_direction: str  # `$pre_direction` du scénariste
    art_pre_direction: str  # `$pre_direction` du directeur artistique
    bible_empty: bool
    characters_without_note: list[BibleCharacterRef]
    # Au-delà de N personnages présents, avertissement sur la case (`mentions.crowd_warning` d'image_prompt.yaml ;
    # 0 = jamais).
    crowd_limit: int = 0


def pre_direction_out(ctx: AppContext, project: Project) -> PreDirectionOut:
    presets = ctx.agents.presets_for(project.id)
    genre = presets.style_genres.get(project.style_genre or "")
    base = inherited_dna(presets, project)
    if base is None:
        return PreDirectionOut(
            project_id=project.id,
            genre=project.style_genre,
            genre_name=genre.name if genre else None,
            available=False,
            groups=GROUPS,
            fields=[],
            inherited={},
            overrides={},
            effective={},
        )
    charter = series_charter(presets, project)
    effective = charter.dna if charter else base
    return PreDirectionOut(
        project_id=project.id,
        genre=project.style_genre,
        genre_name=genre.name if genre else None,
        available=True,
        groups=GROUPS,
        fields=[DnaField(**f) for f in field_specs()],
        inherited=flatten(base),
        overrides=clean_overrides(base, project.pre_direction or {}),
        effective=flatten(effective),
    )


@router.get("/projects/{project_id}/pre-direction", response_model=PreDirectionOut)
def read_pre_direction(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PreDirectionOut:
    return pre_direction_out(ctx, get_project_or_404(session, project_id))


@router.put("/projects/{project_id}/pre-direction", response_model=PreDirectionOut)
def write_pre_direction(
    project_id: int,
    body: PreDirectionIn,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PreDirectionOut:
    project = get_project_or_404(session, project_id)
    base = inherited_dna(ctx.agents.presets_for(project.id), project)
    if base is None:
        raise HTTPException(status_code=503, detail="presets/pre_direction.yaml absent ou invalide : ADN indisponible")
    try:
        apply_overrides(base, body.overrides)
    except DnaError as exc:
        raise FieldError(exc.path, exc.message) from None
    project.pre_direction = clean_overrides(base, body.overrides)
    session.commit()
    return pre_direction_out(ctx, project)


def _bible_empty(session: Session, project_id: int) -> tuple[bool, dict[str, str]]:
    bible = get_bible(session, project_id)
    if bible is None:
        return True, {}
    notes = {str(k): v for k, v in (bible.character_notes or {}).items() if (v or "").strip()}
    sections = any((getattr(bible, k) or "").strip() for k in ("world", "tone", "rules", "motifs"))
    return not sections and not notes, notes


@router.get("/chapters/{chapter_id}/script-brief", response_model=ScriptBriefOut)
def script_brief(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ScriptBriefOut:
    """Ce que le prochain « Découper » enverra (charte de la série) et ce qui manque à la bible."""
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable")
    project = chapter.project
    presets = ctx.agents.presets_for(project.id)
    charter = series_charter(presets, project)
    empty, notes = _bible_empty(session, project.id)
    # Personnages présents : fiches citées par le synopsis, ou déjà dans les cases du chapitre.
    in_panels = {
        cid
        for page in chapter.pages
        if page.kind == PageKind.story
        for pa in page.panels
        for cid in pa.character_ids or []
    }
    characters = session.scalars(select(Character).where(Character.project_id == project.id).order_by(Character.name))
    present: list[Any] = [
        c for c in characters if c.id in in_panels or cites(chapter.synopsis or "", c.name, list(c.aliases or []))
    ]
    stories = sum(1 for p in chapter.pages if p.kind == PageKind.story and p.panels)
    return ScriptBriefOut(
        project_id=project.id,
        pre_direction=script_text(charter, chapter.target_page_count),
        art_pre_direction=art_text(charter, stories or chapter.target_page_count),
        bible_empty=empty,
        characters_without_note=[BibleCharacterRef(id=c.id, name=c.name) for c in present if str(c.id) not in notes],
        crowd_limit=presets.image_prompt.mentions.crowd_warning,
    )
