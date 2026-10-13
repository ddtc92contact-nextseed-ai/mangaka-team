"""Densité et variété des dialogues du scénario (`dialogue_rules` de presets/prompts/script.yaml).

Mesuré sur les bulles (`bubbles`), onomatopées à part : une onomatopée n'est jamais une réplique.

- **densité** : au moins `min_per_panel` répliques par case sur le chapitre, bornée par la place (on vise
  `target_per_panel` répliques dans chaque case où un personnage présent peut parler, jamais plus que la
  place de la case : table `room` selon le nombre de cases de la page) ;
- **brièveté** : `max_words` mots au plus par réplique, `max_mean_words` en moyenne ;
- **action** : une case d'action ou de combat (intensité « choc » ou onomatopée) porte au moins un mot d'un
  personnage (cri, ordre, réaction) en plus de l'onomatopée ;
- **variété** : au moins une pensée, voix off ou narration par chapitre (`require_inner_voice`) ;
- **place réelle** (`room_problems`) : une fois la page mise en page, chaque bulle doit tenir dans la zone
  de bulles de sa case (`bubble_zone`, lettrage simulé sans visages) : une bulle qui en sort recouvre le
  dessin.

Le scénariste est relancé avec ces problèmes (`pipeline/script.py`) ; après les relances, le découpage est
gardé et les mêmes contrôles, refaits sur les bulles enregistrées, s'affichent dans l'écran Scénario
(`chapter_report`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..presets import PresetRegistry
from ..presets.schemas import DialogueRules
from ..store.models import BubbleKind, Page, PageKind
from .fonts import FontBook
from .lettering import Box, BubbleSpec, Letterer
from .lettering import PanelSpec as LetterSpec
from .pages import is_stale

# Une case « parle » : ces types de réplique viennent d'un personnage (la narration, non).
VOICE_KINDS = ("speech", "shout", "thought", "off")
_WORD = re.compile(r"\w", re.UNICODE)
MAX_LISTED = 8  # cases citées au plus dans un même message


@dataclass
class Reply:
    kind: str
    text: str
    speaker: str = ""


@dataclass
class DialoguePanel:
    """Une case vue par les règles de dialogue (réponse du LLM ou case enregistrée)."""

    page: int  # numérotées à partir de 1
    index: int
    panels_on_page: int
    characters: list[str] = field(default_factory=list)
    importance: int = 2
    intensity: str | None = None
    replies: list[Reply] = field(default_factory=list)
    sfx: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"page {self.page} › case {self.index}"


def count_words(text: str) -> int:
    """Mots d'une réplique : « Tu vas voir ! » = 3 (la ponctuation seule ne compte pas)."""
    return sum(1 for token in text.split() if _WORD.search(token))


def _fr(value: float, digits: int = 2) -> str:
    """Nombre à la française : 1.3 → « 1,30 »."""
    return f"{value:.{digits}f}".replace(".", ",")


def _excerpt(text: str) -> str:
    return text if len(text) <= 40 else text[:39] + "…"


@dataclass
class DialogueStats:
    panels: int
    replies: int
    sfx: int
    words: int
    inner_voice: int  # pensées, voix off, narrations
    sfx_only: int  # cases dont la seule bulle est une onomatopée

    @property
    def per_panel(self) -> float:
        return self.replies / self.panels if self.panels else 0.0

    @property
    def mean_words(self) -> float:
        return self.words / self.replies if self.replies else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "panels": self.panels,
            "replies": self.replies,
            "sfx": self.sfx,
            "per_panel": round(self.per_panel, 2),
            "mean_words": round(self.mean_words, 1),
            "inner_voice": self.inner_voice,
            "sfx_only": self.sfx_only,
        }


def dialogue_stats(panels: Sequence[DialoguePanel], rules: DialogueRules | None = None) -> DialogueStats:
    inner = set(rules.inner_voice_kinds) if rules else {"thought", "off", "narration"}
    replies = [r for p in panels for r in p.replies]
    return DialogueStats(
        panels=len(panels),
        replies=len(replies),
        sfx=sum(len(p.sfx) for p in panels),
        words=sum(count_words(r.text) for r in replies),
        inner_voice=sum(1 for r in replies if r.kind in inner),
        sfx_only=sum(1 for p in panels if p.sfx and not p.replies),
    )


def _has_voice(panel: DialoguePanel) -> bool:
    return any(r.kind in VOICE_KINDS for r in panel.replies)


def is_action(panel: DialoguePanel, rules: DialogueRules) -> bool:
    intensities = {i.strip().lower() for i in rules.action_intensities}
    return bool(panel.sfx) or (panel.intensity or "").strip().lower() in intensities


def panel_target(panel: DialoguePanel, rules: DialogueRules) -> int:
    """Répliques visées dans la case : la cible si un personnage peut parler, jamais plus que sa place."""
    if not panel.characters:
        return 0
    room = rules.room_for(panel.panels_on_page, panel.importance)
    return rules.target_per_panel if room is None else min(rules.target_per_panel, room)


def check_dialogues(panels: Sequence[DialoguePanel], rules: DialogueRules | None) -> list[str]:
    """Règles de dialogue enfreintes par un chapitre (messages lisibles, en français, pour la relance)."""
    if rules is None or not panels:
        return []
    problems: list[str] = []
    for p in panels:
        room = rules.room_for(p.panels_on_page, p.importance)
        if room is not None and len(p.replies) > room:
            problems.append(
                f"{p.label} : {len(p.replies)} répliques pour la place d'au plus {room} "
                f"(page de {p.panels_on_page} cases) : garde les plus fortes"
            )
        for r in p.replies:
            n = count_words(r.text)
            if n > rules.max_words:
                problems.append(
                    f"{p.label} : réplique « {_excerpt(r.text)} » trop longue ({n} mots, {rules.max_words} au plus) : "
                    "coupe-la en deux bulles ou raccourcis-la"
                )
        if rules.action_needs_voice and p.characters and is_action(p, rules) and not _has_voice(p):
            noise = f"seulement l'onomatopée « {p.sfx[0]} »" if p.sfx else "case d'action muette"
            problems.append(
                f"{p.label} (action) : {noise} : ajoute un cri, un ordre ou une réaction d'un personnage "
                f"présent ({', '.join(p.characters[:3])})"
            )
    stats = dialogue_stats(panels, rules)
    capacity = sum(panel_target(p, rules) for p in panels)
    required = min(rules.min_per_panel * stats.panels, capacity)
    if stats.replies + 1e-9 < required:
        short = [p.label for p in panels if len(p.replies) < panel_target(p, rules)]
        more = f" et {len(short) - MAX_LISTED} autre(s)" if len(short) > MAX_LISTED else ""
        listed = ", ".join(short[:MAX_LISTED]) + more
        problems.append(
            f"trop peu de répliques : {stats.replies} pour {stats.panels} cases "
            f"({_fr(stats.per_panel)} par case, au moins {_fr(required / stats.panels)} visées) ; "
            f"vise {rules.target_per_panel} répliques courtes dans chaque case où un personnage présent peut "
            f"parler, sans les allonger (cases en dessous : {listed})"
        )
    if stats.replies and stats.mean_words > rules.max_mean_words + 1e-9:
        problems.append(
            f"répliques trop longues : {_fr(stats.mean_words, 1)} mots en moyenne "
            f"({_fr(rules.max_mean_words, 1)} au plus) : "
            "préfère plusieurs bulles courtes"
        )
    if rules.require_inner_voice and stats.inner_voice == 0:
        problems.append(
            "aucune pensée, voix off ni narration dans le chapitre : ajoutes-en au moins une "
            "(« thought », « off » ou « narration ») là où la situation l'appelle"
        )
    return problems


KIND_LABELS = {"speech": "parole", "shout": "cri", "thought": "pensée", "off": "voix off", "narration": "narration"}


def dialogue_text(rules: DialogueRules | None) -> str:
    """Règles de dialogue en clair, pour le prompt du scénariste ($dialogue_rules)."""
    if rules is None:
        return "(aucune règle imposée)"
    lines = [
        f"- vise {rules.target_per_panel} répliques dans chaque case où un personnage présent peut parler "
        f"(au moins {_fr(rules.min_per_panel, 1)} par case en moyenne sur le chapitre) : échanges, réactions, "
        "apartés ; une case muette reste possible quand le silence porte la scène ;",
        f"- répliques courtes : {rules.max_words} mots au plus, {_fr(rules.max_mean_words, 1)} en moyenne ; "
        "plusieurs bulles courtes plutôt qu'une longue ;",
    ]
    if rules.room:
        rooms = sorted(rules.room, key=lambda r: r.max_panels)
        parts, low = [], 1
        for r in rooms:
            span = f"{low} case{'s' if low > 1 else ''}" if low == r.max_panels else f"{low} à {r.max_panels} cases"
            parts.append(f"{span} → {r.replies}")
            low = r.max_panels + 1
        bonus = f", +{rules.big_panel_bonus} pour une case forte (importance 3)" if rules.big_panel_bonus else ""
        lines.append(
            f"- place des bulles : au plus, par case, selon le nombre de cases de la page : {' ; '.join(parts)}{bonus} ;"
        )
    if rules.action_needs_voice:
        lines.append(
            "- une case d'action ou de combat (intensité « choc » ou onomatopée) n'est jamais réduite à son "
            "onomatopée : un personnage présent y crie, ordonne ou réagit (« À couvert ! », « Tiens bon ! ») ;"
        )
    if rules.require_inner_voice:
        kinds = ", ".join(KIND_LABELS.get(k, k) for k in rules.inner_voice_kinds)
        lines.append(f"- au moins une réplique de ce type dans le chapitre, là où la situation l'appelle : {kinds}.")
    else:
        lines.append("- pensées, voix off et narration : seulement quand la situation l'appelle.")
    return "\n".join(lines)


# --- cases enregistrées -------------------------------------------------------------
def page_panels(pages: Sequence[Page]) -> list[DialoguePanel]:
    """Cases des pages « story » (dans l'ordre), vues par les règles de dialogue."""
    out: list[DialoguePanel] = []
    story = [p for p in sorted(pages, key=lambda p: p.number) if p.kind == PageKind.story and p.panels]
    for n, page in enumerate(story, start=1):
        for i, panel in enumerate(page.panels, start=1):
            bubbles = sorted(panel.bubbles, key=lambda b: b.order)
            out.append(
                DialoguePanel(
                    page=n,
                    index=i,
                    panels_on_page=len(page.panels),
                    characters=list(panel.character_names or []),
                    importance=panel.importance,
                    intensity=panel.intensity,
                    replies=[
                        Reply(b.kind.value, b.text, b.speaker_name or "") for b in bubbles if b.kind != BubbleKind.sfx
                    ],
                    sfx=[b.text for b in bubbles if b.kind == BubbleKind.sfx],
                )
            )
    return out


def _inside(box: Box, zone: Box, tolerance: float = 1.0) -> bool:
    return (
        box.x1 >= zone.x1 - tolerance
        and box.y1 >= zone.y1 - tolerance
        and box.x2 <= zone.x2 + tolerance
        and box.y2 <= zone.y2 + tolerance
    )


def room_problems(presets: PresetRegistry, pages: Sequence[Page], fonts: FontBook | None = None) -> list[str]:
    """Place réelle : bulles qui ne tiennent pas dans la zone de bulles de leur case, une fois la page mise
    en page (lettrage simulé, sans visages ni positions manuelles). Pages sans mise en page à jour : ignorées."""
    fonts = fonts or FontBook(presets)
    problems: list[str] = []
    story = [p for p in sorted(pages, key=lambda p: p.number) if p.kind == PageKind.story and p.panels]
    for n, page in enumerate(story, start=1):
        layout = page.layout or {}
        lps = layout.get("panels") or []
        if len(lps) != len(page.panels) or is_stale(page):
            continue
        fmt = presets.page_format(page.chapter.project.page_format)
        letterer = Letterer(fonts, presets.lettering, fmt.dpi)
        direction = layout.get("direction") or page.chapter.project.reading_direction.value
        for i, (panel, lp) in enumerate(zip(page.panels, lps, strict=True), start=1):
            bubbles = [b for b in sorted(panel.bubbles, key=lambda b: b.order) if b.kind != BubbleKind.sfx]
            if not bubbles:
                continue
            label = f"page {n} › case {i}"
            zone = Box.parse(lp.get("bubble_zone"))
            if zone is None:
                problems.append(f"{label} : pas de zone de bulles pour {len(bubbles)} réplique(s) : raccourcis-les")
                continue
            poly = lp.get("base_polygon") or lp.get("polygon")
            polygon = [(float(x), float(y)) for x, y in poly] if poly else None
            if polygon:
                xs, ys = [x for x, _ in polygon], [y for _, y in polygon]
                box = Box(min(xs), min(ys), max(xs), max(ys))
            else:
                box = Box(lp["x1"], lp["y1"], lp["x2"], lp["y2"])
            spec = LetterSpec(
                id=panel.id or i,
                index=i - 1,
                box=box,
                zone=zone,
                characters=list(panel.character_names or []),
                polygon=polygon,
                bubbles=[
                    BubbleSpec(id=k, kind=b.kind.value, text=b.text, speaker=b.speaker_name or "", order=k)
                    for k, b in enumerate(bubbles)
                ],
            )
            placed = letterer.letter_panel(spec, direction).bubbles
            out = sum(1 for b in placed if b.overflow or not _inside(b.box, zone))
            if out:
                fit = len(bubbles) - out
                keep = (
                    f"garde au plus {fit} réplique{'s' if fit > 1 else ''} plus courte{'s' if fit > 1 else ''}"
                    if fit
                    else "raccourcis la réplique"
                )
                problems.append(
                    f"{label} : {out} bulle{'s' if out > 1 else ''} sur {len(bubbles)} ne tien{'nent' if out > 1 else 't'} "
                    f"pas dans la zone de bulles de la case : {keep} ici"
                )
    return problems


@dataclass
class DialogueReport:
    stats: DialogueStats
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"stats": self.stats.as_dict(), "warnings": self.warnings}


def chapter_report(
    presets: PresetRegistry, pages: Sequence[Page], rules: DialogueRules | None, *, fonts: FontBook | None = None
) -> DialogueReport:
    """Mesure et règles de dialogue sur les bulles enregistrées (écran Scénario)."""
    panels = page_panels(pages)
    warnings = check_dialogues(panels, rules)
    if rules is not None and rules.check_room:
        warnings += room_problems(presets, pages, fonts)
    return DialogueReport(dialogue_stats(panels, rules), warnings)
