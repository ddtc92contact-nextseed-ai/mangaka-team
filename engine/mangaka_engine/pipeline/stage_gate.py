"""Garde d'étapes : on n'avance pas un chapitre dont les étapes vitales ne sont pas réglées.

Un seul endroit calcule, pour un chapitre (ou une page), l'état de chaque étape vitale et le nombre
d'éléments en faute :

- **Scénario complet** (`script`) : chaque case a une description ;
- **Direction artistique appliquée** (`direction`) : chaque page de l'histoire a une direction appliquée (une
  page dont l'auteur a rejeté la direction est réglée : c'est une décision) ;
- **Mise en page posée** (`layout`) : chaque page a une mise en page avec son gabarit, chaque case son cadre ;
- **Références prêtes** (`references`) : chaque intervenant de la distribution du chapitre (pipeline/cast.py :
  présents, hors cadre, locuteurs, fiches citées, même secondaires) a une fiche avec une image de référence ;
  un intervenant sans fiche est en faute, seules les foules marquées « foule sans fiche » sont exclues ;
- **Prompts rédigés** (`prompts`) : aucune case au prompt final vide (une case décrite reçoit le sien à la mise en
  file : par fragments, ou rédigé par l'IA ; sans description ni prompt, l'image serait inutilisable) ;
- **Cases approuvées** (`approved`) : chaque case a une version choisie ;
- **Lettrage** (`lettering`) : chaque réplique a un texte et tombe dans sa case.

Chaque action du chapitre exige des étapes (`ACTIONS`) : scénario → mise en page ; scénario, direction, mise
en page, références, prompts → génération ; cases approuvées → lettrage ; cases approuvées et lettrage →
export et passage à « prêt » / « publié ». Une étape manquante refuse l'action avec un message qui nomme
l'étape, le chapitre et le compte (`StageBlocked`).

L'auteur peut **passer outre** une étape précise (jamais « tout ») : la décision (`forced`) est enregistrée
avec son auteur et sa date dans `chapter_stage_decisions`, et l'étape ne bloque plus jusqu'à ce que le
passer-outre soit levé (`revoked`). Une étape franchie complète par une action est notée `validated`.

Restent libres (jamais gardés ici) : les croquis, les essais d'une case isolée et l'atelier de références.

Seuils : chaque vérification accepte aujourd'hui zéro faute. `StageSettings.max_faults` prévoit qu'ils
viennent plus tard des réglages de la série (charte de série) sans changer les appelants.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..store.models import (
    Chapter,
    ChapterStageDecision,
    ImageKind,
    Page,
    PageKind,
    Panel,
    PanelImage,
)


@dataclass(frozen=True)
class StageDef:
    key: str
    label: str  # « Direction artistique appliquée »
    missing: str  # début du refus : « Direction artistique non appliquée »
    unit: tuple[str, str]  # (singulier, pluriel) des éléments comptés
    fault: tuple[str, str]  # état d'un élément en faute (singulier, pluriel) : « en attente »
    fix: str  # ce qu'il faut faire : « Applique-la »
    screen: str  # onglet du chapitre qui règle l'étape (ou `personnages` : bibliothèque de la série)


STAGES: dict[str, StageDef] = {
    s.key: s
    for s in (
        StageDef(
            "script",
            "Scénario complet",
            "Scénario incomplet",
            ("case", "cases"),
            ("sans description", "sans description"),
            "Décris chaque case dans l'onglet Scénario",
            "scenario",
        ),
        StageDef(
            "direction",
            "Direction artistique appliquée",
            "Direction artistique non appliquée",
            ("page", "pages"),
            ("en attente", "en attente"),
            "Applique-la",
            "direction",
        ),
        StageDef(
            "layout",
            "Mise en page posée",
            "Mise en page incomplète",
            ("page", "pages"),
            ("sans mise en page", "sans mise en page"),
            "Calcule la mise en page",
            "mise-en-page",
        ),
        StageDef(
            "references",
            "Références prêtes",
            "Références manquantes",
            ("intervenant", "intervenants"),
            ("sans référence", "sans référence"),
            "Crée leur fiche et leurs références (Direction artistique › Distribution)",
            "direction",
        ),
        StageDef(
            "prompts",
            "Prompts rédigés",
            "Prompts manquants",
            ("case", "cases"),
            ("au prompt vide", "au prompt vide"),
            "Rédige leur prompt dans l'atelier",
            "atelier",
        ),
        StageDef(
            "approved",
            "Cases approuvées",
            "Cases non approuvées",
            ("case", "cases"),
            ("sans version choisie", "sans version choisie"),
            "Choisis une version de chaque case dans l'atelier",
            "atelier",
        ),
        StageDef(
            "lettering",
            "Lettrage",
            "Lettrage incomplet",
            ("réplique", "répliques"),
            ("hors de sa case", "hors de leur case"),
            "Place chaque réplique dans sa case (onglet Lettrage)",
            "lettrage",
        ),
    )
}


@dataclass(frozen=True)
class ActionDef:
    key: str
    label: str  # « générer »
    stages: tuple[str, ...]


ACTIONS: dict[str, ActionDef] = {
    a.key: a
    for a in (
        ActionDef("layout", "mettre en page", ("script",)),
        ActionDef("generation", "générer", ("script", "direction", "layout", "references", "prompts")),
        ActionDef("lettering", "lettrer", ("approved",)),
        ActionDef("export", "exporter", ("approved", "lettering")),
        ActionDef("ready", "passer le chapitre en « prêt »", ("approved", "lettering")),
        ActionDef("published", "publier le chapitre", ("approved", "lettering")),
    )
}

DECISIONS = ("validated", "forced", "revoked")


@dataclass
class StageSettings:
    """Seuils des vérifications. Aujourd'hui zéro faute tolérée partout ; plus tard lus dans la charte de la
    série (`from_series`)."""

    max_faults: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_series(cls, options: dict[str, Any] | None = None) -> StageSettings:
        raw = (options or {}).get("stage_max_faults") if isinstance(options, dict) else None
        if not isinstance(raw, dict):
            return cls()
        return cls({k: int(v) for k, v in raw.items() if k in STAGES and isinstance(v, int) and v >= 0})

    def tolerated(self, stage: str) -> int:
        return self.max_faults.get(stage, 0)


@dataclass
class Decision:
    decision: str  # validated | forced | revoked
    author: str
    note: str
    at: datetime


@dataclass
class StageState:
    key: str
    total: int
    faults: int
    # Éléments en faute, lisibles (« page 3 », « case 2 de la page 4 », « Kaï »), 20 au plus.
    examples: list[str] = field(default_factory=list)
    decision: Decision | None = None
    tolerated: int = 0
    # Fautes par motif, dans l'ordre : (« intervenant sans fiche », noms) — étape `references`.
    parts: list[tuple[tuple[str, str], list[str]]] = field(default_factory=list)

    @property
    def stage(self) -> StageDef:
        return STAGES[self.key]

    @property
    def complete(self) -> bool:
        """L'étape est réglée par le contenu du chapitre (sans passer-outre)."""
        if self.key == "script" and self.total == 0:
            return False  # rien à générer sans case
        return self.faults <= self.tolerated

    @property
    def forced(self) -> bool:
        return self.decision is not None and self.decision.decision == "forced"

    @property
    def passed(self) -> bool:
        return self.complete or self.forced

    def summary(self) -> str:
        """« 5 pages en attente sur 5 » ; « aucune case » pour un chapitre vide."""
        if self.total == 0:
            return f"aucune {self.stage.unit[0]}" if self.key == "script" else "rien à vérifier"
        if self.parts and self.faults:
            counts = ", ".join(f"{len(names)} {label[1 if len(names) > 1 else 0]}" for label, names in self.parts)
            return f"{counts} sur {self.total} {self.stage.unit[1 if self.total > 1 else 0]}"
        many = 1 if self.faults > 1 else 0
        return f"{self.faults} {self.stage.unit[many]} {self.stage.fault[many]} sur {self.total}"


# --- calcul ------------------------------------------------------------------------------
def _pages(session: Session, chapter: Chapter, page_ids: Iterable[int] | None) -> list[Page]:
    pages = [p for p in chapter.pages if p.panels]
    if page_ids is not None:
        wanted = set(page_ids)
        pages = [p for p in pages if p.id in wanted]
    return pages


def _panel_name(panel: Panel, page: Page) -> str:
    return f"case {panel.index + 1} de la page {page.number}"


def _inside(position: dict[str, Any], bbox: dict[str, Any]) -> bool:
    """Centre du cadre ajusté à la main dans la case (avec une petite marge : une bulle peut déborder)."""
    try:
        x1, y1, x2, y2 = (float(bbox[k]) for k in ("x1", "y1", "x2", "y2"))
        if "w" in position and "h" in position:
            cx = float(position["x"]) + float(position["w"]) / 2
            cy = float(position["y"]) + float(position["h"]) / 2
        else:
            cx, cy = float(position["x"]), float(position["y"])
    except (KeyError, TypeError, ValueError):
        return True  # cadre illisible : le lettrage le replace automatiquement
    margin = 0.1 * max(x2 - x1, y2 - y1)
    return x1 - margin <= cx <= x2 + margin and y1 - margin <= cy <= y2 + margin


# Motifs de faute de l'étape `references` (singulier, pluriel).
WITHOUT_CARD = ("intervenant sans fiche", "intervenants sans fiche")
WITHOUT_IMAGE = ("fiche sans image", "fiches sans image")


def _references(
    session: Session, chapter: Chapter, pages: Sequence[Page]
) -> tuple[int, list[str], list[tuple[tuple[str, str], list[str]]]]:
    """Distribution des pages (pipeline/cast.py) : (intervenants comptés, noms en faute, fautes par motif)."""
    from .cast import chapter_cast  # cast importe names, qui ne dépend pas d'ici

    cast = chapter_cast(session, chapter, page_ids=[p.id for p in pages])
    parts = [
        (label, [m.name for m in members])
        for label, members in ((WITHOUT_CARD, cast.without_card()), (WITHOUT_IMAGE, cast.without_image()))
        if members
    ]
    return len(cast.counted), [n for _, names in parts for n in names], parts


def _check(session: Session, key: str, pages: Sequence[Page]) -> tuple[int, int, list[str]]:
    """(total, en faute, exemples) d'une étape sur ces pages (`references` : `_references`)."""
    bad: list[str] = []
    total = 0
    panels = [(pa, p) for p in pages for pa in p.panels]
    if key == "script":
        total = len(panels)
        bad = [_panel_name(pa, p) for pa, p in panels if not (pa.description or "").strip()]
    elif key == "direction":
        story = [p for p in pages if p.kind == PageKind.story]
        total = len(story)
        for p in story:
            d = p.direction
            if d is not None and d.status == "rejected":
                continue  # l'auteur a refusé la direction de cette page : décision prise
            if d is None or d.applied is None:
                bad.append(f"page {p.number}")
    elif key == "layout":
        total = len(pages)
        for p in pages:
            layout = p.layout if isinstance(p.layout, dict) else None
            template = p.grid_template or (layout or {}).get("template_id")
            if not layout or not layout.get("panels") or not template or any(pa.bbox is None for pa in p.panels):
                bad.append(f"page {p.number}")
    elif key == "prompts":
        total = len(panels)
        # Une case décrite sans prompt l'obtient à la mise en file (fragments, ou rédaction de l'IA) ; sans
        # description ni prompt, ce serait une image inutilisable.
        bad = [
            _panel_name(pa, p)
            for pa, p in panels
            if not (pa.final_prompt or "").strip() and not (pa.description or "").strip()
        ]
    elif key == "approved":
        total = len(panels)
        ids = [pa.id for pa, _ in panels]
        chosen = (
            set(
                session.scalars(
                    select(PanelImage.panel_id).where(
                        PanelImage.panel_id.in_(ids), PanelImage.selected, PanelImage.kind == ImageKind.final
                    )
                )
            )
            if ids
            else set()
        )
        bad = [_panel_name(pa, p) for pa, p in panels if pa.id not in chosen]
    elif key == "lettering":
        for pa, p in panels:
            for b in pa.bubbles:
                total += 1
                position = b.position if isinstance(b.position, dict) else None
                placed = bool((b.text or "").strip()) and pa.bbox is not None
                if placed and position and position.get("manual") and isinstance(pa.bbox, dict):
                    placed = _inside(position, pa.bbox)
                if not placed:
                    bad.append(f"réplique {b.order + 1} de la {_panel_name(pa, p)}")
    else:
        raise ValueError(f"étape inconnue : {key}")
    return total, len(bad), bad[:20]


def latest_decisions(session: Session, chapter_id: int) -> dict[str, Decision]:
    """Dernière décision de chaque étape du chapitre."""
    out: dict[str, Decision] = {}
    for row in session.scalars(
        select(ChapterStageDecision)
        .where(ChapterStageDecision.chapter_id == chapter_id)
        .order_by(ChapterStageDecision.id)
    ):
        out[row.stage] = Decision(row.decision, row.author, row.note, row.created_at)
    return out


def chapter_stages(
    session: Session,
    chapter: Chapter,
    *,
    page_ids: Iterable[int] | None = None,
    stages: Iterable[str] | None = None,
    settings: StageSettings | None = None,
) -> list[StageState]:
    """État des étapes vitales du chapitre (ou de ses pages `page_ids`), dans l'ordre de `STAGES`."""
    settings = settings or StageSettings()
    pages = _pages(session, chapter, page_ids)
    decisions = latest_decisions(session, chapter.id)
    keys = [k for k in STAGES if stages is None or k in set(stages)]
    out = []
    for key in keys:
        if key == "references":
            total, bad, parts = _references(session, chapter, pages)
            state = StageState(key, total, len(bad), bad[:20], decisions.get(key), settings.tolerated(key), parts)
            out.append(state)
            continue
        total, faults, examples = _check(session, key, pages)
        out.append(StageState(key, total, faults, examples, decisions.get(key), settings.tolerated(key)))
    return out


# --- garde -------------------------------------------------------------------------------
class StageBlocked(Exception):
    """Action refusée : une étape exigée n'est pas réglée (ni forcée)."""

    def __init__(self, state: StageState, message: str) -> None:
        super().__init__(message)
        self.state = state
        self.message = message


def blocked_message(chapter: Chapter, action: ActionDef, state: StageState, *, page: Page | None = None) -> str:
    """« Chapitre 3 — Direction artistique non appliquée : 5 pages en attente sur 5. Applique-la avant de
    générer, ou passe outre cette étape. »"""
    where = f"Chapitre {chapter.number}" + (f", page {page.number}" if page is not None else "")
    if state.key == "script" and state.total == 0:
        return f"{where} — aucune case : découpe d'abord le chapitre dans l'onglet Scénario {_before(action.label)}."
    detail = state.summary()
    shown = state.examples[:3]
    if state.parts:
        # « 2 intervenants sans fiche (le garde, la serveuse), 1 fiche sans image (Mina) sur 4 intervenants »
        named = ", ".join(
            f"{len(names)} {label[1 if len(names) > 1 else 0]} ({', '.join(names[:5])}{'…' if len(names) > 5 else ''})"
            for label, names in state.parts
        )
        detail = f"{named} sur {state.total} {state.stage.unit[1 if state.total > 1 else 0]}"
    elif shown and state.key == "references":
        detail += f" ({', '.join(shown)}{'…' if state.faults > len(shown) else ''})"
    elif shown and state.faults <= 3:
        detail += f" ({', '.join(shown)})"
    return (
        f"{where} — {state.stage.missing} : {detail}. {state.stage.fix} {_before(action.label)}, "
        "ou passe outre cette étape."
    )


def _before(verb: str) -> str:
    """« avant de générer », « avant d'exporter »."""
    return f"avant d'{verb}" if verb[:1] in "aeéèêiouh" else f"avant de {verb}"


def require(
    session: Session,
    chapter: Chapter,
    action: str,
    *,
    page: Page | None = None,
    only: Iterable[str] | None = None,
    settings: StageSettings | None = None,
) -> list[StageState]:
    """Vérifie les étapes que l'action exige (`only` : un sous-ensemble) ; `StageBlocked` sur la première
    manquante, sinon note `validated` pour chaque étape franchie complète (dans la transaction de l'appelant)."""
    act = ACTIONS[action]
    wanted = [s for s in act.stages if only is None or s in set(only)]
    states = chapter_stages(
        session, chapter, page_ids=[page.id] if page is not None else None, stages=wanted, settings=settings
    )
    for state in states:
        if not state.passed:
            raise StageBlocked(state, blocked_message(chapter, act, state, page=page))
    if page is None:
        for state in states:
            if state.complete and (state.decision is None or state.decision.decision == "revoked"):
                record_decision(session, chapter, state, "validated")
    return states


def record_decision(
    session: Session, chapter: Chapter, state: StageState, decision: str, *, author: str = "", note: str = ""
) -> ChapterStageDecision:
    if decision not in DECISIONS:
        raise ValueError(f"décision inconnue : {decision}")
    row = ChapterStageDecision(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        chapter_number=chapter.number,
        stage=state.key,
        decision=decision,
        author=(author or "").strip()[:120],
        note=(note or "").strip()[:2000],
        faults=state.faults,
        total=state.total,
    )
    session.add(row)
    session.flush()
    state.decision = Decision(row.decision, row.author, row.note, row.created_at)
    return row


def stage_label(key: str) -> str:
    return STAGES[key].label if key in STAGES else key


def blocked_actions(states: Sequence[StageState]) -> dict[str, list[str]]:
    """Étape → actions qu'elle bloque en ce moment (« générer », « lettrer »…)."""
    by_key = {s.key: s for s in states}
    out: dict[str, list[str]] = {}
    for act in ACTIONS.values():
        if act.key == "published":
            continue  # même exigence que « prêt »
        for key in act.stages:
            state = by_key.get(key)
            if state is not None and not state.passed:
                out.setdefault(key, []).append(act.label)
    return out


def overrides_query(
    session: Session,
    *,
    project_id: int | None = None,
    chapter_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[ChapterStageDecision]:
    """Passer-outre enregistrés (les plus récents d'abord), pour la page Statistiques."""
    q = select(ChapterStageDecision).where(ChapterStageDecision.decision == "forced")
    if project_id is not None:
        q = q.where(ChapterStageDecision.project_id == project_id)
    if chapter_id is not None:
        q = q.where(ChapterStageDecision.chapter_id == chapter_id)
    if start is not None:
        q = q.where(ChapterStageDecision.created_at >= start)
    if end is not None:
        q = q.where(ChapterStageDecision.created_at < end)  # exclu
    return list(session.scalars(q.order_by(ChapterStageDecision.id.desc()).limit(200)))
