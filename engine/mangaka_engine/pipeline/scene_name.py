"""Name scène par scène : une fois les scènes validées (étape Scènes, `pipeline/scenes.py`), chaque scène se développe
comme une name de mangaka — découpage en cases, dialogues et intention de cadrage, d'un seul tenant, selon le profil
de tempo de son type (`presets/scene_types.yaml`). Le type, décidé une fois en amont, est lu par le scénariste ET
par le directeur artistique : plus aucune étape n'écrase l'autre.

- **cadre d'une scène** (`SceneFrame`, `scene_frames`) : numéro, type, pages, profil de tempo (ajusté par la série)
  et charte de la scène — l'ADN de la série précisé par le profil (`pre_direction.apply_tempo`), qui prime à
  l'intérieur de la scène ;
- **scénariste** (`pipeline/script.py`) : une génération par scène (`presets/prompts/script-scene.yaml`, règles de
  name dans le preset), avec la liste validée, le résumé des scènes déjà écrites et le profil en clair ; contrôles :
  pages de la scène, cases et répliques par planche, cases muettes (charte de la scène), encadrés de narration
  (`narration_problems`) et **une action par case** (`action_problems`) — relance, puis avertissement ;
- **directeur artistique** (`pipeline/art_direction.py`) : une génération par scène, parts de plans du profil de la
  scène, lignes de mouvement imposées ou interdites recopiées dans l'action et l'ambiance des cases ;
- **une seule scène** se réécrit (scénario ou direction) sans toucher aux pages, cases, croquis et versions des
  autres ;
- **mesure par scène** (`scene_measures`, écrans Scénario et Direction) : cases, répliques, cases muettes et
  encadrés par planche, plans réellement appliqués, face au profil — un écart est un avertissement, jamais un
  blocage.

Un chapitre sans scènes validées (ancien mode), ou dont des pages ne sont rattachées à aucune scène, reste écrit et
dirigé comme avant, d'une seule génération.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry
from ..presets.schemas import SHOT_CLASSES, TIGHT_CLASSES, DialogueRules, OneActionRule
from ..store.models import BubbleKind, Chapter, KnowledgeDocument, Page, PageKind
from .dialogues import check_dialogues, page_panels, room_problems
from .framing import plain
from .pre_direction import (
    EPS,
    SHOT_LABELS,
    Charter,
    dialogue_rules_for,
    panel_count_problems,
    scene_dna,
    series_charter,
    shot_class,
    tempo_profile,
)
from .scenes import script_scenes


# --- cadre d'une scène --------------------------------------------------------------------
@dataclass(frozen=True)
class SceneFrame:
    """Une scène validée vue par le scénariste et le directeur artistique : sa place, son type, son profil de tempo
    (chemins de l'ADN et valeurs propres au tempo) et sa charte (ADN de la série précisé par le profil)."""

    id: int
    number: int
    title: str
    summary: str
    type: str
    type_name: str
    pages: int
    first_page: int
    last_page: int
    tempo: str
    profile: Mapping[str, Any] = field(default_factory=dict)
    charter: Charter | None = None
    fiches: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        title = f" « {self.title} »" if self.title else ""
        return f"scène {self.number}{title} ({self.type_name})"

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "summary": self.summary,
            "type": self.type,
            "type_name": self.type_name,
            "pages": self.pages,
            "first_page": self.first_page,
            "last_page": self.last_page,
            "tempo": self.tempo,
            "profile": dict(self.profile),
        }


def scene_charter(charter: Charter | None, profile: Mapping[str, Any]) -> Charter | None:
    """Charte d'une scène : celle de la série, son ADN précisé par le profil de la scène."""
    if charter is None:
        return None
    dna = scene_dna(charter, profile)
    return replace(charter, dna=dna) if dna is not None else charter


def scene_frames(presets: PresetRegistry, chapter: Chapter) -> list[SceneFrame]:
    """Scènes validées du chapitre, dans l'ordre (vide : pas de scènes validées, ancien mode)."""
    scenes = script_scenes(presets, chapter)
    if not scenes:
        return []
    settings = presets.scene_types
    charter = series_charter(presets, chapter.project)
    out = []
    for s in scenes:
        profile = tempo_profile(settings, chapter.project, s["type"])
        scene_type = settings.types.get(s["type"]) if settings is not None else None  # type: ignore[call-overload]
        out.append(
            SceneFrame(
                id=s["id"],
                number=s["number"],
                title=s["title"],
                summary=s["summary"],
                type=s["type"],
                type_name=s["type_name"],
                pages=s["pages"],
                first_page=s["first_page"],
                last_page=s["last_page"],
                tempo=s["tempo"],
                profile=profile,
                charter=scene_charter(charter, profile),
                fiches=tuple(scene_type.fiches) if scene_type is not None else (),
            )
        )
    return out


def story_pages(chapter: Chapter) -> list[Page]:
    return sorted((p for p in chapter.pages if p.kind == PageKind.story and p.panels), key=lambda p: p.number)


def scene_mode(chapter: Chapter, frames: Sequence[SceneFrame]) -> bool:
    """Le chapitre s'écrit et se dirige scène par scène : scènes validées, et chaque page de l'histoire déjà écrite
    rattachée à l'une d'elles (une page sans scène — chapitre écrit avant, ou étape passée outre — garde l'ancien
    mode pour tout le chapitre)."""
    if not frames:
        return False
    ids = {f.id for f in frames}
    return all(p.scene_id in ids for p in story_pages(chapter))


def scene_pages(chapter: Chapter, frame: SceneFrame) -> list[Page]:
    return [p for p in story_pages(chapter) if p.scene_id == frame.id]


def frame_of(frames: Sequence[SceneFrame], scene_id: int | None) -> SceneFrame | None:
    return next((f for f in frames if f.id == scene_id), None)


def narration_limit(profile: Mapping[str, Any]) -> int | None:
    value = profile.get("narration.max_per_page")
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def motion_rule(profile: Mapping[str, Any]) -> str | None:
    """« required » (lignes de mouvement imposées), « forbidden » (interdites) ou None."""
    if profile.get("motion_lines.required"):
        return "required"
    if profile.get("motion_lines.forbidden"):
        return "forbidden"
    return None


# --- savoir-faire cité par type de scène -------------------------------------------------------
NO_FICHES = "(pas de fiche citée pour ce type de scène)"
SCENE_PROMPT = "script-scene"  # presets/prompts/script-scene.yaml : name d'une scène validée


def fiches_text(session: Session | None, ids: Sequence[str], max_chars: int = 700) -> str:
    """Fiches du savoir-faire citées pour une scène (`fiches` du type) : identifiant, titre et début de la fiche
    (packs importés, `KnowledgeDocument.pack_key`) ; une fiche absente de la base reste citée par son identifiant."""
    if not ids:
        return NO_FICHES
    docs: dict[str, KnowledgeDocument] = {}
    if session is not None:
        for doc in session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.pack_key.in_(list(ids)))):
            docs.setdefault(doc.pack_key or "", doc)
    lines = []
    for fiche in ids:
        doc = docs.get(fiche)
        if doc is None:
            lines.append(f"- {fiche}")
            continue
        body = " ".join(doc.content.split())
        if len(body) > max_chars:
            body = body[: max_chars - 1].rsplit(" ", 1)[0] + "…"
        lines.append(f"- {fiche} — {doc.title} : {body}")
    return "\n".join(lines)


# --- une case = un moment, une seule action ------------------------------------------------------
_TOKENS = re.compile(r"[^\w]+", re.UNICODE)


def _words(text: str) -> list[str]:
    return [w for w in _TOKENS.split(plain(text)) if w]


def _verb_key(verb: str) -> str:
    v = plain(verb).strip()
    return v[2:] if v.startswith(("s'", "l'", "d'")) else v


def action_problems(panels: Sequence[tuple[int, int, str]], rule: OneActionRule | None) -> list[str]:
    """Cases (page, case, description) qui enchaînent plusieurs actions : un mot de liaison (« puis », « et
    ensuite »…) ou plus de `max_verbs` verbes d'action de la liste (heuristique simple, `presets/prompts/
    script-scene.yaml` › one_action). Messages lisibles pour la relance, qui nomment la case fautive."""
    if rule is None:
        return []
    connectors = [_words(c) for c in rule.connectors if c.strip()]
    verbs = {_verb_key(v) for v in rule.verbs if v.strip()}
    out = []
    for page, case, text in panels:
        words = _words(text)
        joined = f" {' '.join(words)} "
        link = next((c for c in connectors if f" {' '.join(c)} " in joined), None)
        found = list(dict.fromkeys(w for w in words if w in verbs))
        if link is None and len(found) <= rule.max_verbs:
            continue
        why = f"« {' '.join(link)} »" if link is not None else f"{len(found)} actions : {', '.join(found)}"
        excerpt = text if len(text) <= 70 else text[:69] + "…"
        out.append(
            f"une action par case : page {page} › case {case} : « {excerpt} » enchaîne plusieurs actions ({why}) : "
            "une case = un moment, une seule action — découpe-la en autant de cases que d'actions, ou garde le "
            "moment clé"
        )
    return out


def narration_problems(counts: Sequence[int], limit: int | None) -> list[str]:
    """Encadrés de narration par planche (pages numérotées à partir de 1 dans la réponse) contre le profil."""
    if limit is None:
        return []
    out = []
    for number, n in enumerate(counts, start=1):
        if n > limit:
            allowed = "aucun" if limit == 0 else f"{limit} au plus"
            out.append(
                f"page {number} : {n} encadré{'s' if n > 1 else ''} de narration ({allowed} par planche dans cette "
                "scène) : raconte par l'image, ou passe en pensée ou en réplique"
            )
    return out


# --- dialogues enregistrés, scène par scène ---------------------------------------------------------
def scene_dialogue_warnings(
    presets: PresetRegistry, pages: Sequence[Page], frames: Sequence[SceneFrame], rules: DialogueRules | None
) -> list[str]:
    """Règles de dialogue des bulles enregistrées, scène par scène (écran Scénario) : cases et répliques par planche,
    cases muettes aux valeurs de la charte de chaque scène ; pensée / voix off / narration et place des bulles sur
    le chapitre entier."""
    story = [p for p in sorted(pages, key=lambda p: p.number) if p.kind == PageKind.story and p.panels]
    out: list[str] = []
    for f in frames:
        group = [p for p in story if p.scene_id == f.id]
        if not group:
            continue
        scene_rules = dialogue_rules_for(rules, f.charter)
        if scene_rules is not None:
            scene_rules = scene_rules.model_copy(update={"require_inner_voice": False, "check_room": False})
        found = [
            f"page {page.number} : " + w.split(" : ", 1)[1]
            for page in group
            for w in panel_count_problems([len(page.panels)], f.charter)
        ]
        found += check_dialogues(page_panels(group, numbers=True), scene_rules)
        out += [f"{f.label} : {w}" for w in found]
    if rules is not None:
        whole = check_dialogues(page_panels(story), rules)
        out += [w for w in whole if w.startswith("aucune pensée")]
        if rules.check_room:
            out += room_problems(presets, story)
    return out


# --- mesure par scène -------------------------------------------------------------------------
def _range_text(low: int, high: int, unit: str) -> str:
    return f"{low} {unit}" if low == high else f"{low} à {high} {unit}"


@dataclass
class PageMeasure:
    page_id: int
    number: int
    panels: int
    replies: int
    silent: int
    narration: int
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "number": self.number,
            "panels": self.panels,
            "replies": self.replies,
            "silent": self.silent,
            "narration": self.narration,
            "warnings": list(self.warnings),
        }


def _shot_counts(plans: Sequence[Any], charter: Charter) -> dict[str, int]:
    counts = Counter(shot_class(p, charter.settings) for p in plans)
    return {cls: counts.get(cls, 0) for cls in SHOT_CLASSES}


def _shot_warnings(counts: Mapping[str, int], total: int, charter: Charter, origin: str) -> list[str]:
    shots = charter.dna.shots
    out = []
    for cls in SHOT_CLASSES:
        r = getattr(shots, cls)
        n = counts.get(cls, 0)
        if n + EPS < r.min * total:
            out.append(f"{SHOT_LABELS[cls]} {origin} : {n} sur {total} (au moins {round(r.min * 100)} % visés)")
        allowed = max(1, math.floor(r.max * total + EPS)) if r.max > 0 else 0
        if r.max < 1 - EPS and n > allowed:
            out.append(f"{SHOT_LABELS[cls]} {origin} : {n} sur {total} (au plus {round(r.max * 100)} % visés)")
    tight = sum(counts.get(c, 0) for c in TIGHT_CLASSES)
    if tight > max(1, math.floor(shots.tight_max * total + EPS)):
        out.append(f"plans serrés {origin} : {tight} sur {total} (au plus {round(shots.tight_max * 100)} % visés)")
    return out


def _expected(frame: SceneFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"narration_max": narration_limit(frame.profile), "motion_lines": motion_rule(frame.profile)}
    charter = frame.charter
    if charter is None:
        return out
    dna = charter.dna
    out.update(
        panels_min=dna.panels.min_per_page,
        panels_max=dna.panels.max_per_page,
        replies_min=dna.dialogue.min_per_page,
        replies_max=dna.dialogue.max_per_page,
        silent_min=dna.dialogue.min_silent_panels,
        shots=[
            {
                "class": cls,
                "label": SHOT_LABELS[cls],
                "min": getattr(dna.shots, cls).min,
                "max": getattr(dna.shots, cls).max,
            }
            for cls in SHOT_CLASSES
            if getattr(dna.shots, cls).min > EPS or getattr(dna.shots, cls).max < 1 - EPS
        ],
        tight_max=dna.shots.tight_max,
    )
    return out


def measure_scene(frame: SceneFrame, pages: Sequence[Page], one_action: OneActionRule | None = None) -> dict[str, Any]:
    """Mesure d'une scène écrite (et dirigée) face à son profil : par planche, cases, répliques (onomatopées à
    part), cases muettes et encadrés de narration ; sur la scène, plans réellement appliqués aux cases (`Panel.
    shot_type`) et plans proposés par la direction artistique. Un écart est un avertissement, jamais un blocage."""
    expected = _expected(frame)
    charter = frame.charter
    rows: list[PageMeasure] = []
    for page in pages:
        replies = [sum(1 for b in pa.bubbles if b.kind != BubbleKind.sfx) for pa in page.panels]
        narration = sum(1 for pa in page.panels for b in pa.bubbles if b.kind == BubbleKind.narration)
        m = PageMeasure(
            page.id, page.number, len(page.panels), sum(replies), sum(1 for r in replies if not r), narration
        )
        if charter is not None:
            lo, hi = expected["panels_min"], expected["panels_max"]
            if m.panels != 1 and not lo <= m.panels <= hi:
                m.warnings.append(f"{m.panels} cases ({_range_text(lo, hi, 'attendues')})")
            lo, hi = expected["replies_min"], expected["replies_max"]
            if (m.panels > 1 and m.replies < lo) or m.replies > hi:
                m.warnings.append(
                    f"{m.replies} réplique{'s' if m.replies > 1 else ''} ({_range_text(lo, hi, 'attendues')})"
                )
            if m.panels >= 2 and m.silent < expected["silent_min"]:
                m.warnings.append(
                    f"{m.silent} case{'s' if m.silent > 1 else ''} muette (au moins {expected['silent_min']})"
                )
        limit = expected["narration_max"]
        if limit is not None and m.narration > limit:
            m.warnings.append(f"{m.narration} encadré{'s' if m.narration > 1 else ''} de narration (au plus {limit})")
        rows.append(m)
    panels = [pa for page in pages for pa in page.panels]
    applied = [pa.shot_type for pa in panels if pa.shot_type]
    proposed = [
        choice.get("plan")
        for page in pages
        if page.direction is not None and page.direction.values
        for choice in page.direction.values.get("panels") or []
        if choice.get("plan")
    ]
    shots: dict[str, Any] = {"total": len(panels), "applied": len(applied), "proposed": len(proposed)}
    warnings = [f"page {m.number} : {w}" for m in rows for w in m.warnings]
    if charter is not None:
        shots["applied_counts"] = _shot_counts(applied, charter)
        shots["proposed_counts"] = _shot_counts(proposed, charter)
        if panels and len(applied) == len(panels):
            warnings += _shot_warnings(shots["applied_counts"], len(panels), charter, "appliqués")
        elif panels and len(proposed) == len(panels):
            warnings += _shot_warnings(shots["proposed_counts"], len(panels), charter, "proposés")
    texts = [(page.number, i, pa.description or "") for page in pages for i, pa in enumerate(page.panels, start=1)]
    warnings += action_problems(texts, one_action)
    if len(pages) != frame.pages:
        warnings.insert(
            0,
            f"{len(pages)} page{'s' if len(pages) > 1 else ''} écrite{'s' if len(pages) > 1 else ''} pour {frame.pages} prévue{'s' if frame.pages > 1 else ''}",
        )
    return {
        "scene_id": frame.id,
        "number": frame.number,
        "title": frame.title,
        "type": frame.type,
        "type_name": frame.type_name,
        "tempo": frame.tempo,
        "planned_pages": frame.pages,
        "expected": expected,
        "pages": [m.as_dict() for m in rows],
        "shots": shots,
        "warnings": warnings,
    }


def scene_measures(presets: PresetRegistry, chapter: Chapter) -> dict[str, Any]:
    """Mesure de chaque scène validée du chapitre (écrans Scénario et Direction)."""
    frames = scene_frames(presets, chapter)
    prompt = presets.prompts.get(SCENE_PROMPT)
    rule = prompt.one_action if prompt is not None else None
    return {
        "scene_mode": scene_mode(chapter, frames),
        "scenes": [measure_scene(f, scene_pages(chapter, f), rule) for f in frames],
    }
