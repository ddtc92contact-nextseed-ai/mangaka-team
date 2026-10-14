"""Distribution du chapitre : chaque intervenant cité, même secondaire, avec sa fiche et ses références.

Une seule fonction (`chapter_cast`) relève, case par case, tous les intervenants du chapitre — personnages
présents à l'image, cités hors cadre, locuteurs des bulles, fiches nommées dans la description ou la mise en
scène — avec le rapprochement des noms de pipeline/names.py (alias, pluriel, arbitrage par le contexte de la
case). L'API (`GET /chapters/{id}/cast`), la garde d'étapes (étape `references`) et l'interface (panneau
« Distribution » de la direction artistique, résumé du chapitre, noms sans fiche du Scénario et de l'atelier)
lisent tous cette même liste. Pour chaque intervenant :

- la fiche reliée, ou rien (le nom tel qu'écrit : « le garde », « trafiquant 2 ») ;
- l'état de ses références : aucune image, portrait seul, ou planche complète (turnaround gardé, ou au moins
  deux images) ;
- les cases où il apparaît, et d'où vient le nom (image, hors cadre, bulle, description, mise en scène) ;
- son rôle : **principal** (au moins `MAIN_MIN_PANELS` cases dans le chapitre, ou fiche déjà présente dans un
  autre chapitre de la série) ou **secondaire** (une ou deux cases). Un secondaire peut se contenter d'un
  portrait ; un principal demande la planche (conseil affiché, la garde ne demande qu'une image).

Plus de sortie silencieuse : un intervenant sans fiche est en faute, quel que soit son rôle. Seule une foule
anonyme (`is_crowd` : « des passants », « la foule », au pluriel ou collectif, sans nom propre ni numéro) peut
être marquée « foule sans fiche » (`ChapterCrowdMark`, tracée et réversible) : elle sort alors des fautes.

« Créer la fiche » : `draft_character` demande au LLM (presets/prompts/fiche-intervenant.yaml) une description
visuelle tirée des cases où l'intervenant apparaît (âge, silhouette, tenue, signe distinctif) ; réponse
invalide → nouvel essai avec l'erreur (`max_retries`) → sinon `CastDraftError`, lisible. Rien n'est enregistré :
l'auteur relit la fiche avant de la créer.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetError
from ..presets.schemas import PromptPreset
from ..providers.llm.base import ChatMessage, LLMError, LLMProvider
from ..store.models import (
    Chapter,
    ChapterCrowdMark,
    CharacterImage,
    Page,
    Panel,
    ReferenceVariant,
)
from .names import (
    PLURAL_MARKERS,
    STOPWORDS,
    CharacterMatcher,
    _core,
    _speakers,
    name_key,
    panel_context,
)

PROMPT_ID = "fiche-intervenant"  # presets/prompts/fiche-intervenant.yaml
TASK = "character_draft"  # tâche du contexte JSON envoyé au LLM (reconnue par le mock)
# Cases à partir desquelles un intervenant est « principal » (très présent).
MAIN_MIN_PANELS = 3
# Types de fiche (presets/reference_sheets/) qui font une planche complète une fois gardés.
FULL_SHEETS = ("personnage-turnaround",)
# Portrait : type de fiche mis en file pour les secondaires (« Tout créer pour les secondaires »).
PORTRAIT_SHEET = "personnage-portrait"
# Mots collectifs : une foule, même au singulier (« la foule », « le public »).
COLLECTIVE = frozenset(
    {
        *("foule", "public", "assistance", "cohue", "attroupement", "monde", "gens", "badauds", "passants"),
        *("troupe", "groupe", "bande", "armee", "horde", "masse", "population", "figurants"),
    }
)
_TOKEN = re.compile(r"\w+")

# États des références et rôles (valeurs de l'API).
NONE, PORTRAIT, SHEET = "aucune", "portrait", "planche"
MAIN, SECONDARY = "principal", "secondaire"
_RANK = {NONE: 0, PORTRAIT: 1, SHEET: 2}


def is_crowd(name: str | None) -> bool:
    """Foule anonyme : au pluriel (« des passants », « les gardes ») ou collectif (« la foule »), sans nom propre
    (« les gardes de Mina ») ni numéro (« trafiquant 2 ») : la seule qui peut se passer de fiche."""
    raw = _TOKEN.findall(name or "")
    keys = [name_key(w) for w in raw]
    if not keys or any(k.isdigit() for k in keys):
        return False
    if any(
        w[:1].isupper() and k not in STOPWORDS | PLURAL_MARKERS | COLLECTIVE for w, k in zip(raw, keys, strict=True)
    ):
        return False  # un nom propre (« Mina ») : quelqu'un de précis
    return any(k in PLURAL_MARKERS or k in COLLECTIVE for k in keys)


def cast_key(name: str) -> str:
    """Clé d'un nom sans fiche : sans les articles de tête (« le garde » = « Le Garde » = « un garde »)."""
    words = tuple(name_key(name).split())
    return " ".join(_core(words) or words)


@dataclass
class Appearance:
    panel_id: int
    page_number: int
    panel_index: int  # 0-based
    sources: list[str] = field(default_factory=list)  # image | hors cadre | bulle | description | mise en scène

    @property
    def label(self) -> str:
        return f"case {self.panel_index + 1} de la page {self.page_number}"


@dataclass
class CrowdMark:
    id: int
    name: str
    author: str
    at: datetime


@dataclass
class CastMember:
    """Un intervenant du chapitre : une fiche, ou un nom sans fiche (clé `cast_key`)."""

    key: str  # « fiche-12 » ou « nom-le garde »
    name: str  # nom de la fiche, sinon le premier nom lu
    character_id: int | None = None
    written: list[str] = field(default_factory=list)  # noms tels qu'écrits par le scénario
    appearances: list[Appearance] = field(default_factory=list)
    images: int = 0
    references: str = NONE
    elsewhere: bool = False  # fiche présente dans un autre chapitre de la série
    crowd: bool = False
    mark: CrowdMark | None = None

    @property
    def panels(self) -> int:
        return len(self.appearances)

    @property
    def role(self) -> str:
        return MAIN if self.panels >= MAIN_MIN_PANELS or self.elsewhere else SECONDARY

    @property
    def needs(self) -> str:
        """Références conseillées : la planche pour un principal, un portrait pour un secondaire."""
        return SHEET if self.role == MAIN else PORTRAIT

    @property
    def excluded(self) -> bool:
        """Foule marquée « foule sans fiche » : hors de la garde."""
        return self.mark is not None

    @property
    def fault(self) -> str | None:
        """Ce qui bloque la génération : « sans fiche », « sans image », ou rien."""
        if self.excluded:
            return None
        if self.character_id is None:
            return "sans fiche"
        return "sans image" if self.images == 0 else None

    @property
    def advice(self) -> str | None:
        """Références en dessous de ce que demande le rôle (conseil, jamais bloquant)."""
        if self.fault or self.excluded or _RANK[self.references] >= _RANK[self.needs]:
            return None
        return "planche conseillée (portrait + turnaround)" if self.needs == SHEET else "portrait conseillé"

    def _seen(self, panel: Panel, page: Page, source: str, written: str) -> None:
        if written and all(name_key(w) != name_key(written) for w in self.written):
            self.written.append(written)
        at = next((a for a in self.appearances if a.panel_id == panel.id), None)
        if at is None:
            at = Appearance(panel.id, page.number, panel.index)
            self.appearances.append(at)
        if source not in at.sources:
            at.sources.append(source)


@dataclass
class ChapterCast:
    members: list[CastMember]
    marks: list[CrowdMark]  # marques « foule sans fiche » en cours dans le chapitre

    @property
    def counted(self) -> list[CastMember]:
        return [m for m in self.members if not m.excluded]

    @property
    def faults(self) -> list[CastMember]:
        return [m for m in self.members if m.fault]

    def without_card(self) -> list[CastMember]:
        return [m for m in self.members if m.fault == "sans fiche"]

    def without_image(self) -> list[CastMember]:
        return [m for m in self.members if m.fault == "sans image"]

    def member(self, name: str) -> CastMember | None:
        key = cast_key(name)
        exact = next((m for m in self.members if m.character_id is None and cast_key(m.name) == key), None)
        return exact or next((m for m in self.members if any(cast_key(w) == key for w in m.written)), None)


# --- marques « foule sans fiche » ----------------------------------------------------------------------
def active_marks(session: Session, chapter_id: int) -> dict[str, CrowdMark]:
    """Marques en cours du chapitre, par clé de nom (`cast_key`)."""
    out: dict[str, CrowdMark] = {}
    for row in session.scalars(
        select(ChapterCrowdMark)
        .where(ChapterCrowdMark.chapter_id == chapter_id, ChapterCrowdMark.revoked_at.is_(None))
        .order_by(ChapterCrowdMark.id)
    ):
        out[row.name_key] = CrowdMark(row.id, row.name, row.author, row.created_at)
    return out


# --- un nom sans fiche, une case -----------------------------------------------------------------------
def panel_unmatched(matcher: CharacterMatcher, panel: Panel, marked: Iterable[str] = ()) -> list[str]:
    """Noms des personnages présents de la case sans fiche, hors foules marquées : ce que montrent le Scénario
    et l'atelier (« Relier à une fiche »), la même règle que la distribution."""
    skip = set(marked)
    return [n for n in matcher.unmatched(panel.character_names or []) if cast_key(n) not in skip]


# --- la distribution -----------------------------------------------------------------------------------
def _panels(chapter: Chapter, page_ids: Iterable[int] | None) -> list[tuple[Panel, Page]]:
    wanted = set(page_ids) if page_ids is not None else None
    pages = sorted((p for p in chapter.pages if wanted is None or p.id in wanted), key=lambda p: p.number)
    return [(pa, p) for p in pages for pa in sorted(p.panels, key=lambda x: x.index)]


def chapter_cast(
    session: Session,
    chapter: Chapter,
    *,
    page_ids: Iterable[int] | None = None,
    matcher: CharacterMatcher | None = None,
) -> ChapterCast:
    """Distribution du chapitre (ou de ses pages `page_ids`), dans l'ordre d'apparition."""
    matcher = matcher or CharacterMatcher.for_project(session, chapter.project_id)
    marks = active_marks(session, chapter.id)
    members: dict[str, CastMember] = {}

    def card(cid: int) -> CastMember:
        key = f"fiche-{cid}"
        if key not in members:
            members[key] = CastMember(key, matcher.names.get(cid, f"fiche {cid}"), character_id=cid)
        return members[key]

    def nameless(name: str) -> CastMember:
        key = f"nom-{cast_key(name)}"
        if key not in members:
            members[key] = CastMember(key, name.strip(), crowd=is_crowd(name), mark=marks.get(cast_key(name)))
        return members[key]

    for panel, page in _panels(chapter, page_ids):
        context = panel_context(matcher, panel)
        declared: list[tuple[str, list[str]]] = [
            ("image", list(panel.character_names or [])),
            ("hors cadre", list(panel.offscreen_names or [])),
            ("bulle", _speakers(panel)),
        ]
        for source, names in declared:
            for r in matcher.resolve_all(names, context):
                if r.ids:
                    for cid in r.ids:
                        card(cid)._seen(panel, page, source, r.name)
                elif r.name.strip():
                    nameless(r.name)._seen(panel, page, source, r.name)
        for cid in panel.character_ids or []:
            if isinstance(cid, int) and cid in matcher.names:
                card(cid)._seen(panel, page, "image", "")
        known = set(matcher.ids([n for _, names in declared[:2] for n in names], context))
        for source, text in (("description", panel.description), ("mise en scène", panel.staging)):
            for r in matcher.resolve_all(matcher.read_names(text), [known, *context]):
                for cid in r.ids:
                    card(cid)._seen(panel, page, source, r.name)

    out = list(members.values())
    _references(session, [m for m in out if m.character_id is not None])
    _elsewhere(session, chapter, [m for m in out if m.character_id is not None])
    return ChapterCast(out, list(marks.values()))


def _references(session: Session, members: Sequence[CastMember]) -> None:
    ids = [m.character_id for m in members if m.character_id is not None]
    if not ids:
        return
    images: dict[int, set[int]] = {}
    for cid, image_id in session.execute(
        select(CharacterImage.character_id, CharacterImage.id).where(CharacterImage.character_id.in_(ids))
    ):
        images.setdefault(cid, set()).add(image_id)
    full: set[int] = set()
    for entry_id, kept in session.execute(
        select(ReferenceVariant.entry_id, ReferenceVariant.kept_image_id).where(
            ReferenceVariant.entry_kind == "character",
            ReferenceVariant.entry_id.in_(ids),
            ReferenceVariant.sheet.in_(FULL_SHEETS),
            ReferenceVariant.kept_image_id.is_not(None),
        )
    ):
        if kept in images.get(entry_id, set()):
            full.add(entry_id)
    for m in members:
        assert m.character_id is not None
        n = len(images.get(m.character_id, ()))
        m.images = n
        m.references = NONE if n == 0 else SHEET if m.character_id in full or n >= 2 else PORTRAIT


def _elsewhere(session: Session, chapter: Chapter, members: Sequence[CastMember]) -> None:
    """Fiches citées dans un autre chapitre de la série (personnages récurrents : rôle principal)."""
    if not members:
        return
    seen: set[int] = set()
    for ids in session.scalars(
        select(Panel.character_ids)
        .join(Page, Panel.page_id == Page.id)
        .join(Chapter, Page.chapter_id == Chapter.id)
        .where(Chapter.project_id == chapter.project_id, Chapter.id != chapter.id)
    ):
        seen.update(i for i in ids or [] if isinstance(i, int))
    for m in members:
        m.elsewhere = m.character_id in seen


# --- « Créer la fiche » : préremplissage par le LLM --------------------------------------------------------
class CastDraftError(Exception):
    """Le LLM n'a pas rendu de fiche lisible (message en français, montré tel quel)."""


class CharacterDraft(BaseModel):
    """Réponse attendue du LLM (presets/prompts/fiche-intervenant.yaml)."""

    model_config = ConfigDict(extra="ignore")

    age: str = ""
    silhouette: str = ""
    tenue: str = ""
    signe_distinctif: str = ""
    description: str = Field(min_length=10, max_length=2000)
    mots_cles: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("age", "silhouette", "tenue", "signe_distinctif", "description", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        return "" if v is None else v.strip() if isinstance(v, str) else v

    @field_validator("mots_cles", mode="before")
    @classmethod
    def _keywords(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.split(",")
        if isinstance(v, list):
            return list(dict.fromkeys(str(k).strip() for k in v if str(k).strip()))[:12]
        return v


@dataclass
class DraftContext:
    name: str
    role: str
    series_title: str
    style: str
    panels: list[dict[str, Any]]  # case par case : page, case, description, mise en scène, lieu, répliques

    def as_json(self) -> dict[str, Any]:
        return {"task": TASK, "name": self.name, "role": self.role, "panels": self.panels}


def draft_context(session: Session, chapter: Chapter, member: CastMember, *, max_panels: int = 8) -> DraftContext:
    """Cases où l'intervenant apparaît (au plus `max_panels`), en texte, pour le LLM."""
    by_id = {pa.id: (pa, p) for pa, p in _panels(chapter, None)}
    keys = {name_key(w) for w in [member.name, *member.written]}
    panels = []
    for at in member.appearances[:max_panels]:
        pa, page = by_id[at.panel_id]
        lines = [
            f"{b.speaker_name} : {b.text}"
            for b in pa.bubbles
            if b.text and (name_key(b.speaker_name or "") in keys or not keys)
        ]
        panels.append(
            {
                "page": page.number,
                "case": pa.index + 1,
                "description": pa.description or "",
                "mise_en_scene": pa.staging or "",
                "lieu": pa.setting or "",
                "repliques": lines,
                "role_dans_la_case": ", ".join(at.sources),
            }
        )
    series = chapter.project
    style = ", ".join(
        v
        for v in (getattr(series, "style_genre", ""), getattr(series, "style_rendering", ""))
        if isinstance(v, str) and v
    )
    return DraftContext(member.name, member.role, series.title if series else "", style, panels)


def _render(template: str, values: dict[str, str], part: str) -> str:
    try:
        return string.Template(template).substitute(values)
    except KeyError as exc:
        raise PresetError(
            f"presets/prompts/{PROMPT_ID}.yaml : variable inconnue ${exc.args[0]} dans « {part} »"
        ) from None


def _panels_text(ctx: DraftContext) -> str:
    out = []
    for p in ctx.panels:
        parts = [f"- Page {p['page']}, case {p['case']} ({p['role_dans_la_case']}) : {p['description'] or '—'}"]
        if p["mise_en_scene"]:
            parts.append(f"  Mise en scène : {p['mise_en_scene']}")
        if p["lieu"]:
            parts.append(f"  Lieu : {p['lieu']}")
        parts.extend(f"  Réplique — {line}" for line in p["repliques"])
        out.append("\n".join(parts))
    return "\n".join(out) or "(aucune case)"


def render_messages(prompt: PromptPreset, ctx: DraftContext) -> list[ChatMessage]:
    values = {
        "name": ctx.name,
        "role": ctx.role,
        "series_title": ctx.series_title,
        "style": ctx.style or "manga",
        "panels": _panels_text(ctx),
        "context_json": json.dumps(ctx.as_json(), ensure_ascii=False, indent=2),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_draft(text: str) -> CharacterDraft:
    """Réponse du LLM → fiche ; `ValueError` lisible sinon."""
    m = _FENCE.match(text or "")
    raw = m.group(1) if m else (text or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON illisible ({exc.msg}, position {exc.pos})") from None
    if not isinstance(data, dict):
        raise ValueError("un objet JSON est attendu")
    try:
        return CharacterDraft.model_validate(data)
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(x) for x in e['loc'])} : {e['msg']}" for e in exc.errors()[:5])
        raise ValueError(errors) from None


def draft_character(llm: LLMProvider, prompt: PromptPreset, ctx: DraftContext) -> CharacterDraft:
    """Fiche préremplie de l'intervenant ; nouvel essai avec l'erreur sur une réponse invalide (`max_retries`)."""
    messages = render_messages(prompt, ctx)
    total = 1 + prompt.max_retries
    last = ""
    for attempt in range(1, total + 1):
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise CastDraftError(f"le LLM n'a pas répondu ({exc})") from None
            continue
        try:
            return parse_draft(result.text)
        except ValueError as exc:
            last = str(exc)
            retry = _render(prompt.retry, {"error": last}, "retry")
            messages = [*messages, ChatMessage("assistant", result.text[:8000]), ChatMessage("user", retry)]
    raise CastDraftError(f"réponse du LLM invalide après {total} essai{'s' if total > 1 else ''} : {last}")


def draft_description(draft: CharacterDraft) -> str:
    """Description visuelle de la fiche : celle du LLM, complétée des traits qu'elle ne reprend pas."""
    text = draft.description.strip()
    extra = [
        f"{label} : {value}"
        for label, value in (
            ("Âge", draft.age),
            ("Silhouette", draft.silhouette),
            ("Tenue", draft.tenue),
            ("Signe distinctif", draft.signe_distinctif),
        )
        if value and value.casefold() not in text.casefold()
    ]
    return "\n".join([text, *extra]) if extra else text


def card_name(name: str) -> str:
    """Nom de fiche tiré du nom écrit : « le garde » → « Le garde » (même clé de rapprochement)."""
    name = " ".join(name.split())
    return name[:1].upper() + name[1:]
