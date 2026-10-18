"""Noms de personnages à signaler à l'auteur, par case (voir pipeline/names.py), mis en forme pour l'API."""

from __future__ import annotations

from ..pipeline.names import AMBIGUOUS, OFFSCREEN_ACTION, UNMATCHED, CharacterMatcher, name_notes
from ..store.models import Panel
from .schemas import CardRef, NameNoteOut

_WHERE = {"image": "dans l'image", "hors cadre": "hors cadre", "bulle": "locuteur d'une bulle"}


def name_notes_out(matcher: CharacterMatcher, panel: Panel) -> list[NameNoteOut]:
    """Noms à signaler de la case (pipeline/names.py), avec les fiches nommées et une phrase en français."""
    out = []
    for n in name_notes(matcher, panel):
        chosen = [CardRef(id=i, name=matcher.names[i]) for i in n.chosen]
        candidates = [CardRef(id=i, name=matcher.names[i]) for i in n.candidates]
        names = " et ".join(c.name for c in chosen)
        where = _WHERE.get(n.source, f"lu dans la {n.source}")
        if n.kind == AMBIGUOUS:
            others = ", ".join(c.name for c in candidates if c.id not in n.chosen)
            message = f"« {n.name} » ({where}) désigne plusieurs fiches : {names} retenu, pas {others}."
        elif n.kind == UNMATCHED:
            message = f"« {n.name} » ({where}) ne correspond à aucune fiche : ni référence, ni description."
        elif n.kind == OFFSCREEN_ACTION and len(chosen) > 1:
            message = (
                f"« {n.name} » ({names}) sont déclarés hors cadre, mais la {n.source} leur donne une action visible : "
                "ils seraient dessinés d'après le texte, sans leur référence."
            )
        elif n.kind == OFFSCREEN_ACTION:
            message = (
                f"{names} est déclaré hors cadre, mais la {n.source} lui donne une action visible : il serait dessiné "
                "d'après le texte, sans sa référence."
            )
        else:
            message = (
                f"« {n.name} » ({where}) n'est pas déclaré dans la case : {names} serait dessiné sans sa référence."
            )
            if candidates:
                message += " Nom ambigu : " + ", ".join(c.name for c in candidates) + "."
        out.append(
            NameNoteOut.model_validate(
                {
                    "name": n.name,
                    "source": n.source,
                    "kind": n.kind,
                    "chosen": chosen,
                    "candidates": candidates,
                    "message": message,
                }
            )
        )
    return out
