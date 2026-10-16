"""Réglages de l'atelier stockés côté moteur (table `app_settings`).

« Ton nom » (`author_name`) : l'appli est locale et sans compte, ce nom signe par défaut toutes les validations
et décisions d'étape (garde d'étapes, scènes, name, foules sans fiche) quand l'écran n'en envoie pas d'autre.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..store.models import AppSetting

AUTHOR_NAME = "author_name"
MAX_AUTHOR = 120


def _clean(name: str | None) -> str:
    return " ".join((name or "").split())[:MAX_AUTHOR]


def author_name(session: Session) -> str:
    """« Ton nom » saisi dans les Réglages ("" s'il ne l'a jamais été)."""
    row = session.scalar(select(AppSetting).where(AppSetting.key == AUTHOR_NAME))
    return row.value if row is not None else ""


def set_author_name(session: Session, name: str | None) -> str:
    """Enregistre « Ton nom » (espaces resserrés, vide = aucun nom) ; sans commit."""
    value = _clean(name)
    row = session.scalar(select(AppSetting).where(AppSetting.key == AUTHOR_NAME))
    if row is None:
        session.add(AppSetting(key=AUTHOR_NAME, value=value))
    else:
        row.value = value
    session.flush()
    return value


def author_or_default(session: Session, author: str | None) -> str:
    """L'auteur saisi pour cette décision, sinon « Ton nom » des Réglages."""
    return _clean(author) or author_name(session)
