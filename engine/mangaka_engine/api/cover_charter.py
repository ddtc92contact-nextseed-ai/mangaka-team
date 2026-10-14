"""Charte des couvertures d'une série (fiche série › « Charte des couvertures »), voir pipeline/cover_charter.py.

- `GET /projects/{id}/cover-charter` : réglages (choix bornés de presets/cover_charter.yaml), personnages admis,
  palette de la série, consignes envoyées à la 1re et à la 4e ;
- `PUT /projects/{id}/cover-charter` : enregistre la charte (choix inconnu ou personnage d'une autre série → 422) ;
- `DELETE /projects/{id}/cover-charter` : revient aux réglages par défaut du preset.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.cover_charter import (
    FIELDS,
    LABELS,
    Charter,
    charter_characters,
    charter_lines,
    choices,
    palette_colors,
    series_charter,
)
from ..pipeline.style import series_monochrome
from ..presets import PresetRegistry
from ..store.files import versioned_url
from ..store.models import Character, CoverCharter, Project
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .projects import get_project_or_404

router = APIRouter(tags=["charte des couvertures"])


class ChoiceOut(BaseModel):
    id: str
    label: str
    description: str


class CharterCharacterOut(BaseModel):
    id: int
    name: str
    has_reference: bool
    image_url: str | None


class PaletteColorOut(BaseModel):
    role: str
    hex: str
    sent: bool  # envoyée au modèle d'image (rôles `palette_roles` du preset)


class CoverCharterOut(BaseModel):
    project_id: int
    available: bool
    problem: str | None
    saved: bool
    values: dict[str, str]
    character_ids: list[int]
    options: dict[str, list[ChoiceOut]]
    labels: dict[str, str]
    characters: list[CharterCharacterOut]
    max_characters: int
    palette_name: str | None
    palette: list[PaletteColorOut]
    monochrome_series: bool
    front_lines: list[str]  # consignes ajoutées au prompt de la 1re
    back_lines: list[str]  # … et de la petite illustration de 4e
    identity_check: bool
    identity_available: bool
    min_similarity: float | None
    warnings: list[str]


class CoverCharterIn(BaseModel):
    palette_mode: str | None = None
    mood: str | None = None
    shot: str | None = None
    back_shot: str | None = None
    logo_place: str | None = None
    subject: str | None = None
    character_ids: list[int] | None = Field(default=None, max_length=20)


def _presets(ctx: AppContext, project_id: int) -> PresetRegistry:
    return ctx.agents.presets_for(project_id)


def _character_out(c: Character) -> CharterCharacterOut:
    first = c.reference_images[0] if c.reference_images else None
    return CharterCharacterOut(
        id=c.id,
        name=c.name,
        has_reference=first is not None,
        image_url=versioned_url(f"/characters/{c.id}/images/{first.id}/file", first.path) if first else None,
    )


def charter_out(session: Session, ctx: AppContext, series: Project) -> CoverCharterOut:
    presets = _presets(ctx, series.id)
    charter = series_charter(presets, series)
    chars = session.scalars(select(Character).where(Character.project_id == series.id).order_by(Character.name))
    qc = presets.qc
    base: dict[str, Any] = {
        "project_id": series.id,
        "characters": [_character_out(c) for c in chars],
        "max_characters": presets.cover.max_characters if presets.cover else 0,
        "monochrome_series": series_monochrome(presets, series),
        "identity_available": ctx.providers.identity is not None,
        "min_similarity": qc.identity.min_similarity if qc else None,
        "labels": LABELS,
    }
    palette = series.palette or {}
    if charter is None:
        return CoverCharterOut(
            **base,
            available=False,
            problem="Charte des couvertures indisponible : presets/cover_charter.yaml absent ou invalide.",
            saved=False,
            values={},
            character_ids=[],
            options={},
            palette_name=palette.get("name"),
            palette=[],
            front_lines=[],
            back_lines=[],
            identity_check=False,
            warnings=[],
        )
    s = charter.settings
    allowed = charter_characters(session, series.id, charter)
    names = [c.name for c in allowed]
    warnings = list(charter.problems)
    if not palette:
        warnings.append("Pas encore de palette retenue (Identité visuelle) : la couleur de la couverture reste libre.")
    elif not palette_colors(s, series) and charter.choice("palette_mode").prompt.strip():
        warnings.append("Aucune couleur de la palette n'a un rôle envoyé à l'illustration (palette_roles).")
    missing = [c.name for c in allowed if not c.reference_images]
    if missing:
        warnings.append(f"Sans image de référence (identité non envoyée ni vérifiée) : {', '.join(missing)}.")
    return CoverCharterOut(
        **base,
        available=True,
        problem=None,
        saved=charter.saved,
        values=charter.values,
        character_ids=[c.id for c in allowed],
        options={
            name: [
                ChoiceOut(id=key, label=choice.label, description=choice.description)
                for key, choice in choices(s, name).items()
            ]
            for name in FIELDS
        },
        palette_name=palette.get("name") if palette else None,
        palette=[
            PaletteColorOut(role=str(c.get("role")), hex=str(c.get("hex")), sent=c.get("role") in s.palette_roles)
            for c in palette.get("colors") or []
            if isinstance(c, dict)
        ],
        front_lines=charter_lines(charter, series, kind="front", names=names),
        back_lines=charter_lines(charter, series, kind="back", names=names),
        identity_check=s.identity_check,
        warnings=warnings,
    )


def apply_charter(session: Session, presets: PresetRegistry, series: Project, body: CoverCharterIn) -> Charter:
    charter = series_charter(presets, series)
    if charter is None:
        raise HTTPException(status_code=503, detail="presets/cover_charter.yaml absent ou invalide")
    values = dict(charter.values)
    for name in FIELDS:
        value = getattr(body, name)
        if value is None:
            continue
        known = choices(charter.settings, name)
        if value not in known:
            raise FieldError(name, f"{LABELS[name]} inconnu : « {value} » (choix : {', '.join(known)})")
        values[name] = value
    ids = charter.character_ids
    if body.character_ids is not None:
        ids = list(dict.fromkeys(body.character_ids))
        limit = presets.cover.max_characters if presets.cover else 0
        if len(ids) > limit:
            raise FieldError("character_ids", f"{limit} personnages au plus sur une couverture")
        found = set(
            session.scalars(select(Character.id).where(Character.project_id == series.id, Character.id.in_(ids)))
        )
        unknown = [i for i in ids if i not in found]
        if unknown:
            raise FieldError("character_ids", f"personnage {unknown[0]} introuvable dans cette série")
    row = series.cover_charter
    if row is None:
        row = CoverCharter(project_id=series.id)
        series.cover_charter = row
    row.settings = values
    row.character_ids = ids
    return charter


@router.get("/projects/{project_id}/cover-charter", response_model=CoverCharterOut)
def get_cover_charter(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CoverCharterOut:
    return charter_out(session, ctx, get_project_or_404(session, project_id))


@router.put("/projects/{project_id}/cover-charter", response_model=CoverCharterOut)
def put_cover_charter(
    project_id: int, body: CoverCharterIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CoverCharterOut:
    series = get_project_or_404(session, project_id)
    apply_charter(session, _presets(ctx, project_id), series, body)
    session.commit()
    session.refresh(series)
    return charter_out(session, ctx, series)


@router.delete("/projects/{project_id}/cover-charter", response_model=CoverCharterOut)
def reset_cover_charter(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CoverCharterOut:
    series = get_project_or_404(session, project_id)
    series.cover_charter = None
    session.commit()
    session.refresh(series)
    return charter_out(session, ctx, series)
