"""Rapprochement des noms écrits par le scénario avec les fiches personnages de la série.

Le LLM écrit « Urus », « urus », « Urus le dragon » ou « le petit dragon » : chaque nom est rapproché
d'une fiche, dans l'ordre :

1. égalité exacte du nom ou d'un des autres noms (alias) de la fiche, sans tenir compte de la casse,
   des accents ni de la ponctuation (« Élise » = « elise », « Jean-Luc » = « jean luc ») ;
2. correspondance partielle par mots entiers : le nom de la fiche (ou un alias) apparaît dans le nom
   écrit (« Urus le dragon » → Urus), ou le nom écrit apparaît dans celui de la fiche (« Urus » → la
   fiche « Urus le Grand »). La correspondance la plus longue l'emporte ; à égalité entre deux fiches,
   le nom reste non rapproché (c'est à l'auteur de choisir).

Un nom non rapproché n'est jamais ignoré en silence : l'API le signale par case
(`unmatched_characters`) et l'auteur peut le rattacher à une fiche en un clic (il devient un alias).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..store.models import Chapter, Character, Page, Panel

# Mots qui ne suffisent pas, seuls, à désigner un personnage (« le », « la petite »…).
STOPWORDS = frozenset(
    {
        *("le", "la", "les", "l", "un", "une", "des", "de", "du", "d", "au", "aux", "et"),
        *("the", "a", "an", "of"),
        *("petit", "petite", "grand", "grande", "jeune", "vieux", "vieille"),
    }
)
_NON_WORD = re.compile(r"[^\w]+")


def name_key(text: str | None) -> str:
    """Forme comparable d'un nom : minuscules, sans accents ni ponctuation, espaces simples."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()
    return " ".join(_NON_WORD.sub(" ", plain.replace("_", " ")).split())


def _contains(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """`needle` apparaît dans `haystack` en mots entiers consécutifs."""
    n = len(needle)
    return n > 0 and any(tuple(haystack[i : i + n]) == tuple(needle) for i in range(len(haystack) - n + 1))


def _meaningful(words: Sequence[str]) -> bool:
    return any(w not in STOPWORDS for w in words)


@dataclass(frozen=True)
class _Card:
    id: int
    keys: tuple[tuple[str, ...], ...]  # nom puis alias, en mots


class CharacterMatcher:
    """Rapproche des noms de personnages des fiches d'une série (voir le module)."""

    def __init__(self, characters: Iterable[Character]) -> None:
        self.cards: list[_Card] = []
        for c in characters:
            keys = [tuple(name_key(n).split()) for n in (c.name, *(c.aliases or []))]
            keys = list(dict.fromkeys(k for k in keys if k))
            if keys:
                self.cards.append(_Card(c.id, tuple(keys)))

    @classmethod
    def for_project(cls, session: Session, project_id: int) -> CharacterMatcher:
        return cls(session.scalars(select(Character).where(Character.project_id == project_id).order_by(Character.id)))

    def match(self, name: str | None) -> int | None:
        """Id de la fiche désignée par `name`, ou None (aucune, ou plusieurs à égalité)."""
        words = tuple(name_key(name).split())
        if not words:
            return None
        exact = [card.id for card in self.cards if words in card.keys]
        if exact:
            return exact[0]
        if not _meaningful(words):
            return None
        best: dict[int, int] = {}
        for card in self.cards:
            for key in card.keys:
                score = 0
                if _meaningful(key) and _contains(words, key):
                    score = len(key)  # « urus le dragon » contient « urus »
                elif _contains(key, words):
                    score = len(words)  # « urus » est dans « urus le grand »
                if score > best.get(card.id, 0):
                    best[card.id] = score
        if not best:
            return None
        top = max(best.values())
        winners = [cid for cid, score in best.items() if score == top]
        return winners[0] if len(winners) == 1 else None

    def ids(self, names: Iterable[str]) -> list[int]:
        """Ids des fiches désignées, dans l'ordre, sans doublon (noms non rapprochés omis)."""
        return list(dict.fromkeys(i for i in (self.match(n) for n in names) if i is not None))

    def unmatched(self, names: Iterable[str]) -> list[str]:
        """Noms qui ne désignent aucune fiche (à signaler à l'auteur)."""
        return [n for n in names if n and self.match(n) is None]


def relink_project(session: Session, project_id: int) -> int:
    """Recalcule les personnages (ids) et locuteurs de toutes les cases d'une série d'après leurs noms.

    Appelé quand une fiche est créée, renommée ou reçoit un alias : une case écrite avant la fiche la
    retrouve. Renvoie le nombre de cases dont les personnages ont changé (un prompt automatique est
    reconstruit à chaque génération).
    """
    matcher = CharacterMatcher.for_project(session, project_id)
    panels = session.scalars(
        select(Panel).join(Page, Panel.page_id == Page.id).join(Chapter).where(Chapter.project_id == project_id)
    ).all()
    changed = 0
    for panel in panels:
        ids = matcher.ids(panel.character_names or [])
        if ids != list(panel.character_ids or []):
            panel.character_ids = ids
            changed += 1
        for bubble in panel.bubbles:
            if bubble.speaker_name:
                speaker = matcher.match(bubble.speaker_name)
                if speaker != bubble.speaker_id:
                    bubble.speaker_id = speaker
    return changed
