"""Réglages de l'atelier (écran Réglages) : « Ton nom », auteur par défaut des validations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from ..pipeline import app_settings as aps
from .deps import get_session

router = APIRouter(tags=["réglages"])


class AppSettingsOut(BaseModel):
    author_name: str


class AppSettingsIn(BaseModel):
    author_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=aps.MAX_AUTHOR)] = ""


@router.get("/settings", response_model=AppSettingsOut)
def get_app_settings(session: Session = Depends(get_session)) -> AppSettingsOut:
    return AppSettingsOut(author_name=aps.author_name(session))


@router.put("/settings", response_model=AppSettingsOut)
def put_app_settings(body: AppSettingsIn, session: Session = Depends(get_session)) -> AppSettingsOut:
    """« Ton nom » : signe par défaut les validations et décisions d'étape (vide : aucun nom)."""
    name = aps.set_author_name(session, body.author_name)
    session.commit()
    return AppSettingsOut(author_name=name)
