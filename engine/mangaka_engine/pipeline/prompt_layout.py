"""Grille de composition à boîtes de FLUX 3 Klein (`prompt_format: layout` d'un preset).

Pour une case à 2 personnages ou plus, le paragraphe (celui de `prompt_writer`, inchangé) est complété par
une boîte par personnage : position normalisée (x, y, l, h dans [0, 1], origine en haut à gauche) et courte
description. Le workflow officiel de BFL les branche sur `CreateBoundingBoxes` → `Flux3LayoutPrompt`, qui
ajoute au prompt la table `[{"id": "obj_1", "bbox": [...], "desc": ...}]` ; le paragraphe cite chaque boîte
par `<obj_N>` après le nom du personnage (consigne du nœud : « Cite box N as <obj_N> »).

Placement :

- la mise en scène de la case place les personnages (« Aiko à gauche, Kenji à droite au premier plan ») :
  gauche / centre / droite donnent la colonne, premier plan / arrière-plan la hauteur de la boîte ;
- sinon, répartition déterministe en colonnes, dans l'ordre de la distribution.

Les colonnes se recouvrent un peu (deux personnages côte à côte se touchent) mais une boîte n'en contient
jamais une autre. Une case à 0 ou 1 personnage n'a pas de boîte : le paragraphe passe seul.

Fonctions pures (aucune base) : les personnages de la case sont rassemblés par `generation.py`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .names import name_key

Column = Literal["left", "center", "right"]
Depth = Literal["front", "back"]
MIN_SUBJECTS = 2  # en dessous : pas de grille, le paragraphe seul
MAX_KEYWORDS = 4  # mots-clés de la fiche repris dans la description d'une boîte
OVERLAP = 1.2  # largeur d'une boîte, en colonnes : 20 % de plus que sa colonne
BACK_WIDTH = 0.75  # arrière-plan : boîte plus étroite…
# (y, h) selon la profondeur : premier plan haut et ancré en bas, arrière-plan plus petit et plus haut.
HEIGHTS: dict[Depth | None, tuple[float, float]] = {"front": (0.08, 0.92), "back": (0.18, 0.52), None: (0.1, 0.88)}

# Repères de la mise en scène (mots comparés après `name_key` : minuscules, sans accents ni tirets).
COLUMN_WORDS: dict[Column, tuple[tuple[str, ...], ...]] = {
    "left": (("gauche",), ("left",)),
    "right": (("droite",), ("right",)),
    "center": (("centre",), ("center",), ("milieu",), ("middle",)),
}
DEPTH_WORDS: dict[Depth, tuple[tuple[str, ...], ...]] = {
    "front": (("premier", "plan"), ("avant", "plan"), ("foreground",)),
    "back": (("arriere", "plan"), ("second", "plan"), ("au", "fond"), ("background",)),
}
# « main droite », « bras gauche » : une partie du corps, pas une place dans la case.
BODY_WORDS = frozenset({"main", "bras", "jambe", "pied", "oeil", "epaule", "joue", "hand", "arm", "leg", "foot", "eye"})
# Une phrase de la mise en scène : les repères d'un personnage ne débordent jamais sur la suivante.
_SENTENCES = re.compile(r"[.;!?\n]+")


@dataclass(frozen=True)
class LayoutSubject:
    """Un personnage dessiné dans la case : son nom et les mots-clés de sa fiche (vides sans fiche)."""

    name: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Place:
    column: Column | None = None
    depth: Depth | None = None


@dataclass(frozen=True)
class LayoutBox:
    """Boîte d'un personnage, en fractions de la case (origine en haut à gauche)."""

    name: str
    x: float
    y: float
    w: float
    h: float
    desc: str
    # « mise en scène » : position lue dans la mise en scène ; « répartition » : colonne attribuée d'office.
    source: Literal["mise en scène", "répartition"] = "répartition"
    place: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "desc": self.desc,
            "source": self.source,
            **({"place": dict(self.place)} if self.place else {}),
        }


def _tokens(name: str) -> list[tuple[str, ...]]:
    """Formes du nom cherchées dans la mise en scène : le nom complet, puis son premier mot (« Aiko »)."""
    words = tuple(name_key(name).split())
    if not words:
        return []
    forms = [words]
    if len(words) > 1 and len(words[0]) >= 3:
        forms.append(words[:1])
    return forms


def _find(words: Sequence[str], needle: Sequence[str], start: int = 0, stop: int | None = None) -> list[int]:
    stop = len(words) if stop is None else stop
    n = len(needle)
    return [
        i
        for i in range(start, stop - n + 1)
        if tuple(words[i : i + n]) == tuple(needle) and not (i > 0 and words[i - 1] in BODY_WORDS)
    ]


def _cue[T: str](
    words: Sequence[str], start: int, stop: int, table: dict[T, tuple[tuple[str, ...], ...]], *, first: bool
) -> T | None:
    """Repère de `table` entre `start` et `stop` : le premier (`first`) ou le dernier ; None : aucun."""
    hits = [
        (i, value) for value, needles in table.items() for needle in needles for i in _find(words, needle, start, stop)
    ]
    if not hits:
        return None
    return (min(hits) if first else max(hits))[1]


def staging_places(staging: str | None, names: Sequence[str]) -> dict[str, Place]:
    """Position de chaque personnage d'après la mise en scène (seuls les personnages placés sont rendus).

    Dans une phrase, un repère se rapporte au personnage qui le précède (« Aiko à gauche, Kenji à droite »),
    sinon à celui qui le suit (« À gauche, Aiko ») ; jamais au-delà du personnage voisin."""
    out: dict[str, Place] = {}
    for sentence in _SENTENCES.split(staging or ""):
        words = name_key(sentence).split()
        if not words:
            continue
        spans: list[tuple[int, int, str]] = []  # (début, fin, nom) des personnages cités dans la phrase
        for name in names:
            for form in _tokens(name):
                hits = _find(words, form)
                taken = [s for s in spans if any(s[0] <= h < s[1] for h in hits)]
                if hits and not taken:
                    spans.append((hits[0], hits[0] + len(form), name))
                    break
        spans.sort()
        for k, (begin, end, name) in enumerate(spans):
            stop = spans[k + 1][0] if k + 1 < len(spans) else len(words)
            # Les mots entre le personnage précédent et celui-ci sont au précédent s'il y trouve un repère.
            start = spans[k - 1][1] if k > 0 else 0
            before = k == 0 or not _cues(words, start, begin, first=True)
            column, depth = (
                _cues(words, end, stop, first=True)
                or (_cues(words, start, begin, first=False) if before else None)
                or (None, None)
            )
            if name not in out and (column or depth):
                out[name] = Place(column, depth)
    return out


def _cues(words: Sequence[str], start: int, stop: int, *, first: bool) -> tuple[Column | None, Depth | None] | None:
    """(colonne, profondeur) trouvées entre `start` et `stop` (le premier repère, ou le dernier) ; None : aucun."""
    column = _cue(words, start, stop, COLUMN_WORDS, first=first)
    depth = _cue(words, start, stop, DEPTH_WORDS, first=first)
    return (column, depth) if column or depth else None


def _columns(n: int, places: Sequence[Place]) -> list[int]:
    """Colonne de chaque personnage : gauche d'abord, droite à la fin, centre au milieu de ce qui reste, puis
    les personnages non placés dans les colonnes libres, dans l'ordre de la distribution."""
    free = list(range(n))
    out: list[int | None] = [None] * n
    for i, p in enumerate(places):
        if p.column == "left":
            out[i] = free.pop(0)
    for i in reversed(range(n)):
        if places[i].column == "right":
            out[i] = free.pop()
    middle = (n - 1) / 2
    for i, p in enumerate(places):
        if p.column == "center":
            col = min(free, key=lambda c: (abs(c - middle), c))
            free.remove(col)
            out[i] = col
    for i in range(n):
        if out[i] is None:
            out[i] = free.pop(0)
    return [c for c in out if c is not None]


def box_description(subject: LayoutSubject) -> str:
    """Courte description d'une boîte : le nom, puis quelques mots-clés de la fiche."""
    keywords = [k.strip() for k in subject.keywords if k and k.strip()][:MAX_KEYWORDS]
    return ", ".join([subject.name, *keywords])


def layout_boxes(subjects: Sequence[LayoutSubject], staging: str | None = None) -> list[LayoutBox]:
    """Une boîte par personnage (2 ou plus) ; [] pour une case à 0 ou 1 personnage."""
    subjects = list({name_key(s.name): s for s in reversed(subjects) if name_key(s.name)}.values())[::-1]
    n = len(subjects)
    if n < MIN_SUBJECTS:
        return []
    found = staging_places(staging, [s.name for s in subjects])
    places = [found.get(s.name, Place()) for s in subjects]
    columns = _columns(n, places)
    width = min(1.0, OVERLAP / n)
    boxes: list[LayoutBox] = []
    for subject, place, col in zip(subjects, places, columns, strict=True):
        w = width * (BACK_WIDTH if place.depth == "back" else 1.0)
        center = (col + 0.5) / n
        x = min(max(0.0, center - w / 2), 1.0 - w)
        y, h = HEIGHTS[place.depth]
        described = {k: v for k, v in (("column", place.column), ("depth", place.depth)) if v}
        boxes.append(
            LayoutBox(
                name=subject.name,
                x=round(x, 4),
                y=y,
                w=round(w, 4),
                h=h,
                desc=box_description(subject),
                source="mise en scène" if described else "répartition",
                place=described,
            )
        )
    return boxes


def cite_boxes(prompt: str, boxes: Sequence[LayoutBox]) -> str:
    """Le paragraphe avec `<obj_N>` après la première mention de chaque personnage (déjà cité : inchangé)."""
    for i, box in enumerate(boxes, start=1):
        tag = f"<obj_{i}>"
        if tag in prompt:
            continue
        match = re.search(rf"(?<!\w){re.escape(box.name)}(?!\w)", prompt, flags=re.IGNORECASE)
        if match:
            prompt = f"{prompt[: match.end()]} {tag}{prompt[match.end() :]}"
    return prompt


__all__ = [
    "LayoutBox",
    "LayoutSubject",
    "Place",
    "box_description",
    "cite_boxes",
    "layout_boxes",
    "staging_places",
]
