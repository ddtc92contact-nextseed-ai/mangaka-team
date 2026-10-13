"""Rapprochement des noms écrits par le scénario avec les fiches personnages de la série.

Le LLM écrit « Urus », « urus », « Urus le dragon » ou « le petit dragon » : chaque nom est rapproché
d'une fiche, dans l'ordre :

1. égalité exacte du nom ou d'un des autres noms (alias) de la fiche, sans tenir compte de la casse,
   des accents ni de la ponctuation (« Élise » = « elise », « Jean-Luc » = « jean luc ») ;
2. correspondance partielle par mots entiers : le nom de la fiche (ou un alias) apparaît dans le nom
   écrit (« Urus le dragon » → Urus), ou le nom écrit apparaît dans celui de la fiche (« Urus » → la
   fiche « Urus le Grand »). La correspondance la plus longue l'emporte ;
3. à défaut, la même correspondance sur le radical des mots : pluriel (« trafiquants ») ou « s » final
   oublié (« angu » → Angus). Jamais sur un mot de moins de 4 lettres (pas de faux positif sur les noms
   courts : « Lu » ne désigne pas « Lus »).

**Arbitrage** quand plusieurs fiches sont à égalité (« trafiquant » → « trafiquant 1 » et « trafiquant 2 ») :

- le texte est au pluriel (« les trafiquants », « trafiquants ») → toutes les fiches concernées ;
- sinon, le contexte de la case désigne une seule d'entre elles → on la prend. Le contexte, du plus fort
  au plus faible : les autres personnages de la case (présents, hors cadre, locuteurs des bulles) rapprochés
  sans ambiguïté, puis ceux de la case précédente ;
- sinon, la première fiche (ordre de création) **et un avertissement** : le nom est « ambigu ».

Un alias générique sur une fiche (« trafiquant » sur « trafiquant 1 ») rend le choix déterministe : il
désigne cette fiche exactement, sans arbitrage.

Rien n'est perdu en silence : `name_notes` liste, par case, chaque nom lu (personnages présents ou hors
cadre, locuteurs, et noms de fiches lus dans la description et la mise en scène) qui est ambigu, sans fiche,
ou cité sans être déclaré ; l'API les renvoie (`name_notes`, `unmatched_characters`) et l'atelier les
signale, avec de quoi corriger (rattacher le nom à une fiche, il en devient un alias ; mettre à l'image).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

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
# Articles et déterminants qui mettent un nom au pluriel (« les trafiquants », « des trafiquant »).
PLURAL_MARKERS = frozenset({"les", "des", "ces", "aux", "leurs", "nos", "vos", "mes", "tes", "ses"})
# Locuteurs qui ne sont pas des personnages (récitatif) : jamais signalés.
NARRATORS = frozenset({"narrateur", "narratrice", "narration", "recitatif", "voix off", "off", "titre"})
_NON_WORD = re.compile(r"[^\w]+")
_TOKEN = re.compile(r"\w+")


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
    name: str
    keys: tuple[tuple[str, ...], ...]  # nom puis alias, en mots


def _singular(word: str) -> str:
    """« trafiquants » → « trafiquant », « angus » → « angu » (4 lettres au moins, jamais un nombre)."""
    return word[:-1] if len(word) > 4 and word[-1] in "sx" and not word.isdigit() else word


def _same_word(a: str, b: str) -> bool:
    """Deux mots qui ne diffèrent que par un « s » ou « x » final (« trafiquants » / « trafiquant »,
    « angu » / « angus »), sur 4 lettres au moins : jamais de faux positif sur un nom court."""
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4 or a.isdigit() or b.isdigit():
        return False
    return _singular(a) == _singular(b) or _singular(a) == b or a == _singular(b)


def _contains_like(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """Comme `_contains`, mot à mot sur le radical (`_same_word`)."""
    n = len(needle)
    return n > 0 and any(
        all(_same_word(h, w) for h, w in zip(haystack[i : i + n], needle, strict=True))
        for i in range(len(haystack) - n + 1)
    )


def _core(words: tuple[str, ...]) -> tuple[str, ...]:
    """Mots sans les articles de tête (« les trafiquants » → « trafiquants »)."""
    i = 0
    while i < len(words) and words[i] in STOPWORDS:
        i += 1
    return words[i:]


# Comment un nom a été rapproché (`Resolution.how`).
EXACT = "fiche"  # une seule fiche : nom, alias, nom partiel ou radical
CONTEXT = "contexte"  # égalité tranchée par le contexte de la case
PLURAL = "pluriel"  # égalité, texte au pluriel : toutes les fiches
ARBITRATION = "arbitrage"  # égalité sans indice : la première fiche, avec un avertissement


@dataclass(frozen=True)
class Resolution:
    """Fiches retenues pour un nom écrit (`ids`, vide si aucune), et fiches à égalité (`candidates`)."""

    name: str
    ids: tuple[int, ...] = ()
    candidates: tuple[int, ...] = ()
    how: str = ""

    @property
    def first(self) -> int | None:
        return self.ids[0] if self.ids else None

    @property
    def ambiguous(self) -> bool:
        return self.how == ARBITRATION

    @property
    def sure(self) -> int | None:
        """La fiche, quand le nom en désigne une seule sans arbitrage (sert de contexte aux autres noms)."""
        return self.ids[0] if len(self.ids) == 1 and self.how in (EXACT, CONTEXT) else None


# Contexte d'une case : ensembles d'ids de fiches, du plus fort au plus faible.
Context = Sequence[Iterable[int]]


class CharacterMatcher:
    """Rapproche des noms de personnages des fiches d'une série (voir le module)."""

    def __init__(self, characters: Iterable[Character]) -> None:
        self.cards: list[_Card] = []
        for c in characters:
            keys = [tuple(name_key(n).split()) for n in (c.name, *(c.aliases or []))]
            keys = list(dict.fromkeys(k for k in keys if k))
            if keys:
                self.cards.append(_Card(c.id, c.name, tuple(keys)))
        self.names = {card.id: card.name for card in self.cards}
        # Premier mot significatif du nom de chaque fiche : ce qui, dans un texte, annonce un personnage.
        self._heads = {
            next((w for w in card.keys[0] if w not in STOPWORDS and not w.isdigit()), "") for card in self.cards
        } - {""}
        self._phrases = [key for card in self.cards for key in card.keys[1:] if _meaningful(key)]

    @classmethod
    def for_project(cls, session: Session, project_id: int) -> CharacterMatcher:
        return cls(session.scalars(select(Character).where(Character.project_id == project_id).order_by(Character.id)))

    # --- un nom ---------------------------------------------------------------------------------------
    def _candidates(self, words: tuple[str, ...]) -> list[int]:
        """Fiches à égalité pour `words` (une seule si le nom est clair), dans l'ordre des fiches."""
        core = _core(words)
        exact = [card.id for card in self.cards if words in card.keys or (core and core in card.keys)]
        if exact or not _meaningful(words):
            return exact
        for contains in (_contains, _contains_like):
            best: dict[int, int] = {}
            for card in self.cards:
                for key in card.keys:
                    score = 0
                    if _meaningful(key) and contains(words, key):
                        score = len(key)  # « urus le dragon » contient « urus »
                    elif contains(key, core):
                        score = len(core)  # « urus » est dans « urus le grand »
                    if score > best.get(card.id, 0):
                        best[card.id] = score
            if best:
                top = max(best.values())
                return [cid for cid, score in best.items() if score == top]
        return []

    def _plural(self, words: tuple[str, ...], candidates: Sequence[int]) -> bool:
        """« les trafiquants », « des trafiquant », « trafiquants » (le mot de la fiche sans « s »)."""
        if any(w in PLURAL_MARKERS for w in words):
            return True
        card_words = {w for card in self.cards if card.id in candidates for key in card.keys for w in key}
        return any(w not in card_words and _singular(w) in card_words for w in words)

    def resolve(self, name: str | None, context: Context = ()) -> Resolution:
        """Fiche(s) désignée(s) par `name`, avec l'arbitrage du module en cas d'égalité."""
        text = name or ""
        words = tuple(name_key(text).split())
        candidates = self._candidates(words) if words else []
        if not candidates:
            return Resolution(text)
        if len(candidates) == 1:
            return Resolution(text, (candidates[0],), how=EXACT)
        tied = tuple(candidates)
        if self._plural(words, candidates):
            return Resolution(text, tied, tied, PLURAL)
        pool = list(candidates)
        for tier in context:
            known = set(tier)
            hits = [cid for cid in pool if cid in known]
            if len(hits) == 1:
                return Resolution(text, (hits[0],), tied, CONTEXT)
            if hits:
                pool = hits  # plusieurs dans ce contexte : le suivant départage entre eux
        return Resolution(text, (pool[0],), tied, ARBITRATION)

    def match(self, name: str | None, context: Context = ()) -> int | None:
        """Id de la fiche désignée par `name` (la première si le nom en désigne plusieurs), ou None."""
        return self.resolve(name, context).first

    def resolve_all(self, names: Iterable[str], context: Context = ()) -> list[Resolution]:
        """Résolution de chaque nom ; les noms sûrs de la liste servent de premier contexte aux autres."""
        names = [n for n in names if n]
        sure = {r.sure for r in (self.resolve(n) for n in names)} - {None}
        return [self.resolve(n, [sure, *context]) for n in names]

    def ids(self, names: Iterable[str], context: Context = ()) -> list[int]:
        """Ids des fiches désignées, dans l'ordre, sans doublon (noms non rapprochés omis)."""
        return list(dict.fromkeys(i for r in self.resolve_all(names, context) for i in r.ids))

    def unmatched(self, names: Iterable[str]) -> list[str]:
        """Noms qui ne désignent aucune fiche (à signaler à l'auteur)."""
        return [n for n in names if n and self.match(n) is None]

    # --- un texte -------------------------------------------------------------------------------------
    def read_names(self, text: str | None) -> list[str]:
        """Noms de fiches lus dans un texte libre (description, mise en scène), tels qu'écrits : le premier
        mot du nom d'une fiche, au radical (« Trafiquant », « trafiquants », « angu »), suivi de son numéro
        (« Trafiquant 2 ») et précédé d'un article pluriel (« les trafiquant ») ; ou un alias en entier."""
        tokens = [(m.group(0), name_key(m.group(0))) for m in _TOKEN.finditer(text or "")]
        keys = [k for _, k in tokens]
        found: list[str] = []
        i = 0
        while i < len(tokens):
            phrase = next((p for p in self._phrases if tuple(keys[i : i + len(p)]) == p), None)
            if phrase is not None:
                found.append(" ".join(raw for raw, _ in tokens[i : i + len(phrase)]))
                i += len(phrase)
                continue
            key = keys[i]
            if key in STOPWORDS or key.isdigit() or len(key) < 3 or not any(_same_word(key, h) for h in self._heads):
                i += 1
                continue
            start, end = i, i + 1
            if end < len(tokens) and keys[end].isdigit():
                end += 1
            if start > 0 and keys[start - 1] in PLURAL_MARKERS:
                start -= 1
            found.append(" ".join(raw for raw, _ in tokens[start:end]))
            i = end
        return _dedupe(found)


def _dedupe(names: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        if name_key(n) not in seen:
            seen.add(name_key(n))
            out.append(n)
    return out


# --- une case ------------------------------------------------------------------------------------------
_AUTO: Any = object()


def previous_panel(panel: Any) -> Any | None:
    """Case qui précède `panel` dans le chapitre (planche précédente comprise), None sinon."""
    page = getattr(panel, "page", None)
    if page is None:
        return None
    panels = sorted(page.panels, key=lambda p: p.index)
    at = next((i for i, p in enumerate(panels) if p is panel), None)
    if at:
        return panels[at - 1]
    if at is None:
        return None
    chapter = getattr(page, "chapter", None)
    earlier = [p for p in (chapter.pages if chapter is not None else []) if p.number < page.number]
    pages = sorted(earlier, key=lambda p: p.number)
    for prev in reversed(pages):
        if prev.panels:
            return max(prev.panels, key=lambda p: p.index)
    return None


def _speakers(panel: Any) -> list[str]:
    """Locuteurs des bulles qui sont des personnages (ni récitatif, ni onomatopée)."""
    out = []
    for b in getattr(panel, "bubbles", None) or []:
        kind = str(getattr(b.kind, "value", b.kind) or "")
        name = b.speaker_name or ""
        if name.strip() and kind not in ("narration", "sfx") and name_key(name) not in NARRATORS:
            out.append(name)
    return out


def _declared(panel: Any) -> list[str]:
    return [*(panel.character_names or []), *(getattr(panel, "offscreen_names", None) or []), *_speakers(panel)]


def panel_context(matcher: CharacterMatcher, panel: Any, previous: Any = _AUTO) -> list[set[int]]:
    """Contexte d'arbitrage d'une case : fiches sûres de la case (présents, hors cadre, locuteurs), puis
    celles de la case précédente (`previous` : celle du chapitre si omise)."""
    if previous is _AUTO:
        previous = previous_panel(panel)
    tiers = [{r.sure for r in map(matcher.resolve, _declared(panel))} - {None}]
    if previous is not None:
        tiers.append({r.sure for r in map(matcher.resolve, _declared(previous))} - {None})
    return tiers  # type: ignore[return-value]


def panel_ids(matcher: CharacterMatcher, panel: Any, previous: Any = _AUTO) -> list[int]:
    """Ids des fiches des personnages présents de la case (`character_ids`), arbitrage compris."""
    return matcher.ids(panel.character_names or [], panel_context(matcher, panel, previous))


def link_speakers(matcher: CharacterMatcher, panel: Any, previous: Any = _AUTO) -> None:
    """Fiche du locuteur de chaque bulle, arbitrage compris."""
    context = panel_context(matcher, panel, previous)
    for bubble in getattr(panel, "bubbles", None) or []:
        if bubble.speaker_name:
            speaker = matcher.match(bubble.speaker_name, context)
            if speaker != bubble.speaker_id:
                bubble.speaker_id = speaker


# Ce qui est signalé (`NameNote.kind`) et où le nom a été lu (`NameNote.source`).
AMBIGUOUS = "ambigu"
UNMATCHED = "sans fiche"
UNDECLARED = "non déclaré"


@dataclass(frozen=True)
class NameNote:
    """Un nom de personnage lu dans une case qui demande l'avis de l'auteur."""

    name: str  # tel qu'écrit dans la case
    source: str  # image | hors cadre | bulle | description | mise en scène
    kind: str  # ambigu | sans fiche | non déclaré
    chosen: tuple[int, ...] = ()  # fiche(s) retenue(s) ; vide : aucune
    candidates: tuple[int, ...] = field(default=())  # fiches à égalité (nom ambigu)


def name_notes(matcher: CharacterMatcher, panel: Any, previous: Any = _AUTO) -> list[NameNote]:
    """Noms de la case à signaler : ambigus (fiche choisie par arbitrage), sans fiche, ou lus dans la
    description / la mise en scène sans être déclarés. Un même nom (ou, non déclaré, les mêmes fiches) n'est
    signalé qu'une fois par motif."""
    context = panel_context(matcher, panel, previous)
    present = list(panel.character_names or [])
    offscreen = list(getattr(panel, "offscreen_names", None) or [])
    notes: list[NameNote] = []
    seen: set[tuple[Any, str]] = set()

    def add(note: NameNote) -> None:
        # « les trafiquants » et « trafiquants » lus dans le texte : les mêmes fiches, une seule alerte.
        key = (note.chosen if note.kind == UNDECLARED else name_key(note.name), note.kind)
        if key not in seen:
            seen.add(key)
            notes.append(note)

    for source, names in (("image", present), ("hors cadre", offscreen), ("bulle", _speakers(panel))):
        for r in matcher.resolve_all(names, context):
            if not r.ids:
                add(NameNote(r.name, source, UNMATCHED))
            elif r.ambiguous:
                add(NameNote(r.name, source, AMBIGUOUS, r.ids, r.candidates))
    declared = set(matcher.ids([*present, *offscreen], context))
    for source, text in (("description", panel.description), ("mise en scène", getattr(panel, "staging", ""))):
        for r in matcher.resolve_all(matcher.read_names(text), [declared, *context]):
            if any(i not in declared for i in r.ids):
                add(NameNote(r.name, source, UNDECLARED, r.ids, r.candidates if r.ambiguous else ()))
    return notes


def relink_project(session: Session, project_id: int) -> int:
    """Recalcule les personnages (ids) et locuteurs de toutes les cases d'une série d'après leurs noms,
    avec l'arbitrage du module (contexte de la case et de la précédente).

    Appelé quand une fiche est créée, renommée ou reçoit un alias : une case écrite avant la fiche la
    retrouve. Renvoie le nombre de cases dont les personnages ont changé (un prompt automatique est
    reconstruit à chaque génération). Les noms encore ambigus ou non déclarés restent signalés à l'auteur
    (`name_notes`, lu par l'API).
    """
    matcher = CharacterMatcher.for_project(session, project_id)
    panels = session.scalars(
        select(Panel)
        .join(Page, Panel.page_id == Page.id)
        .join(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.id, Page.number, Panel.index)
    ).all()
    changed = 0
    previous: Panel | None = None
    for panel in panels:
        if previous is not None and previous.page.chapter_id != panel.page.chapter_id:
            previous = None
        ids = panel_ids(matcher, panel, previous)
        if ids != list(panel.character_ids or []):
            panel.character_ids = ids
            changed += 1
        link_speakers(matcher, panel, previous)
        previous = panel
    return changed
