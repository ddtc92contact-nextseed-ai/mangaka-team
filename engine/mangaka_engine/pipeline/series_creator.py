"""Créateur de série : un échange guidé avec l'auteur qui propose l'ADN de la série et rédige sa bible.

Septième agent (`presets/agents/createur-serie.yaml`, rôle de savoir-faire `series_creation`), le seul qui intervient
AVANT le premier synopsis — à la création d'une série, ou relancé sur une série existante.

1. **échange borné** : les questions fermées de `presets/series_creator.yaml` (un choix à cliquer, une réponse libre
   facultative) et, en option, l'idée de la série en quelques phrases. Chaque choix porte des pistes d'ADN
   (`shift` : écart à la valeur du genre, `set` : valeur à prendre) ; `suggested_dna` les combine, bornées et
   validées, et les donne à l'agent comme point de départ ;
2. **contexte** : réponses, défauts chiffrés du genre (`presets/pre_direction.yaml`), personnages, synopsis des
   chapitres et résumés des chapitres validés, bible actuelle, savoir-faire (« Structure · … », écriture…) ;
3. **proposition** validée par Pydantic puis par l'ADN (`apply_overrides`) : écarts au genre avec une phrase
   d'explication chacun, bible (univers, ton, règles, gags et motifs) et une note par personnage. Une réponse
   invalide est renvoyée à l'agent avec l'erreur (`max_retries` du prompt, 2 au plus), puis `CreatorError` lisible ;
4. **différentiel** (`api/series_creator.py`) : la proposition est montrée à côté de ce qui est déjà écrit, l'auteur
   la corrige, et rien de ce qu'il a écrit (section de bible, note, valeur d'ADN ajustée) n'est remplacé sans
   confirmation explicite (`conflicts`).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry, PromptPreset
from ..presets.schemas import CreatorChoice, CreatorQuestion, PreDirection, SeriesCreatorSettings
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.models import Chapter, Character, Project
from ..validation import format_errors
from .knowledge import AgentKnowledge, KnowledgeBase, get_bible
from .pre_direction import EPS, LABELS, LEAVES, DnaError, _kind, apply_overrides, clean_overrides, field_specs, flatten
from .script import DIRECTION_LABELS, _render
from .style import style_brief

AGENT_ID = "createur-serie"  # agent de l'écran « L'équipe »
ROLE = "series_creation"  # rôle dans presets/knowledge.yaml
TASK = "series_creation"
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
BIBLE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("world", "Univers"),
    ("tone", "Ton"),
    ("rules", "Règles de l'univers"),
    ("motifs", "Gags et motifs récurrents"),
)
MAX_PITCH_CHARS = 2000
MAX_DNA_CHANGES = 30


class CreatorError(Exception):
    """L'agent n'a pas pu faire sa proposition (LLM indisponible, réponses invalides) : message lisible."""


class ProposalValidationError(ValueError):
    """Réponse du LLM refusée (message renvoyé à l'agent pour qu'il corrige)."""


class AnswerError(ValueError):
    """Réponse de l'auteur refusée (question inconnue, choix absent…) : `field` pour le formulaire."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _clean(text: str) -> str:
    """Paragraphes séparés par une ligne vide, espaces simples, texte en NFC (accents)."""
    text = unicodedata.normalize("NFC", (text or "").replace("\r\n", "\n"))
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def _name_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name or "").casefold().split())


def same_value(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(a - b) < EPS
    return bool(a == b)


# --- réponses de l'auteur -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Answer:
    question: CreatorQuestion
    choice: CreatorChoice
    note: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "question": self.question.id,
            "label": self.question.label,
            "choice": self.choice.id,
            "choice_label": self.choice.label,
            "note": self.note,
        }


def resolve_answers(settings: SeriesCreatorSettings, raw: Mapping[str, Mapping[str, Any]]) -> list[Answer]:
    """Réponses dans l'ordre des questions ; `AnswerError` si une question n'a pas de choix (ou un choix inconnu)."""
    unknown = [q for q in raw if q not in {x.id for x in settings.questions}]
    if unknown:
        raise AnswerError(f"answers.{unknown[0]}", f"question inconnue : « {unknown[0]} »")
    out: list[Answer] = []
    for q in settings.questions:
        given = raw.get(q.id) or {}
        choice_id = given.get("choice")
        if not choice_id:
            raise AnswerError(f"answers.{q.id}", f"« {q.label} » : choisis une réponse")
        choice = next((c for c in q.choices if c.id == choice_id), None)
        if choice is None:
            raise AnswerError(f"answers.{q.id}", f"« {q.label} » : choix inconnu « {choice_id} »")
        note = " ".join(str(given.get("note") or "").split())
        if len(note) > settings.max_free_chars:
            raise AnswerError(f"answers.{q.id}", f"« {q.label} » : {settings.max_free_chars} signes au plus")
        out.append(Answer(q, choice, note))
    return out


_BOUNDS = {f["path"]: (f["min"], f["max"]) for f in field_specs()}


def _bounded(path: str, value: float) -> float | int:
    low, high = _BOUNDS.get(path, (None, None))
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return int(round(value)) if _kind(path) == "int" else round(value, 2)


def choice_hints(base: PreDirection, choice: CreatorChoice) -> dict[str, Any]:
    """Valeurs que suggère un choix : écart ajouté à la valeur du genre (bornée), ou valeur prise ; chemins connus."""
    flat = flatten(base)
    out: dict[str, Any] = {}
    for path, delta in choice.shift.items():
        if path in LEAVES and _kind(path) != "bool":
            out[path] = _bounded(path, flat[path] + delta)
    for path, value in choice.set.items():
        if path not in LEAVES:
            continue
        out[path] = value if _kind(path) == "bool" else _bounded(path, float(value))
    return out


@dataclass(frozen=True)
class Suggestion:
    path: str
    value: Any
    question: str  # libellé de la question
    choice: str  # libellé du choix


def suggested_dna(base: PreDirection, answers: Sequence[Answer]) -> list[Suggestion]:
    """Pistes d'ADN des réponses, combinées dans l'ordre des questions : seules les valeurs qui s'écartent du genre
    et gardent un ADN valide (un minimum sous son maximum) sont gardées."""
    flat = flatten(base)
    kept: dict[str, Suggestion] = {}
    for a in answers:
        for path, value in choice_hints(base, a.choice).items():
            trial = {**{p: s.value for p, s in kept.items()}, path: value}
            try:
                apply_overrides(base, trial)
            except DnaError:
                continue
            kept[path] = Suggestion(path, value, a.question.label, a.choice.label)
    return [s for p, s in kept.items() if not same_value(s.value, flat[p])]


# --- contexte -----------------------------------------------------------------------------------------------
@dataclass
class CreatorBrief:
    project_id: int
    title: str
    genre: str
    style_packs: str
    style_guidelines: str
    reading_direction: str
    pitch: str
    answers: list[Answer]
    suggestions: list[Suggestion]
    base: PreDirection  # ADN du genre (verrouillé)
    characters: list[dict[str, Any]]  # {id, name, description, note}
    chapters: list[dict[str, Any]]  # {number, title, synopsis, summary}
    bible: dict[str, str]  # bible actuelle, par section
    settings: SeriesCreatorSettings
    knowledge: AgentKnowledge | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        s = self.settings
        return {
            "task": TASK,
            "title": self.title,
            "genre": self.genre,
            "pitch": self.pitch,
            "answers": [a.as_json() for a in self.answers],
            "suggested": [
                {"path": x.path, "value": x.value, "question": x.question, "choice": x.choice} for x in self.suggestions
            ],
            "genre_dna": flatten(self.base),
            "characters": [{"name": c["name"], "description": c["description"]} for c in self.characters],
            "chapters": self.chapters,
            "bible": self.bible,
            "max_section_chars": s.max_section_chars,
            "max_note_chars": s.max_note_chars,
        }


def knowledge_query(project: Project, pitch: str, answers: Sequence[Answer], genre: str) -> str:
    """Requête de recherche du savoir-faire : titre, idée, genre et réponses de l'auteur."""
    picked = " ; ".join(f"{a.question.label} {a.choice.label} {a.note}".strip() for a in answers)
    return "\n".join(p for p in (project.title, pitch, genre, picked) if p and p.strip())


def creator_brief(
    session: Session,
    presets: PresetRegistry,
    project: Project,
    answers: list[Answer],
    *,
    pitch: str = "",
    knowledge: KnowledgeBase | None = None,
) -> CreatorBrief:
    """Contexte de l'agent ; `CreatorError` sans ADN ni questions (presets absents ou invalides)."""
    settings = presets.series_creator
    base = presets.genre_dna(project.style_genre)
    if settings is None or base is None:
        raise CreatorError("presets/series_creator.yaml ou presets/pre_direction.yaml absent ou invalide")
    genre = presets.style_genres.get(project.style_genre or "")
    style = style_brief(presets, project)
    bible = get_bible(session, project.id)
    notes = {str(k): v for k, v in ((bible.character_notes if bible else None) or {}).items()}
    characters = [
        {"id": c.id, "name": c.name, "description": c.visual_description, "note": (notes.get(str(c.id)) or "").strip()}
        for c in session.scalars(select(Character).where(Character.project_id == project.id).order_by(Character.name))
    ]
    validated = {e.get("chapter_id"): e for e in ((bible.chapter_summaries if bible else None) or [])}
    chapters = [
        {
            "number": c.number,
            "title": c.title,
            "synopsis": " ".join((c.synopsis or "").split()),
            "summary": " ".join(str((validated.get(c.id) or {}).get("summary") or "").split()),
        }
        for c in session.scalars(select(Chapter).where(Chapter.project_id == project.id).order_by(Chapter.number))
    ]
    # Les résumés validés les plus récents d'abord gardés ; les synopsis restent tous (courts).
    with_summary = [c for c in chapters if c["summary"]]
    for c in with_summary[: max(0, len(with_summary) - settings.max_chapter_summaries)]:
        c["summary"] = ""
    pitch = _clean(pitch)[:MAX_PITCH_CHARS]
    genre_name = genre.name if genre else "(pas de genre : valeurs par défaut)"
    return CreatorBrief(
        project_id=project.id,
        title=project.title,
        genre=genre_name,
        style_packs=style.packs,
        style_guidelines=style.guidelines,
        reading_direction=DIRECTION_LABELS.get(project.reading_direction.value, project.reading_direction.value),
        pitch=pitch,
        answers=answers,
        suggestions=suggested_dna(base, answers),
        base=base,
        characters=characters,
        chapters=chapters,
        bible={k: ((getattr(bible, k) or "").strip() if bible else "") for k, _ in BIBLE_SECTIONS},
        settings=settings,
        knowledge=knowledge.for_agent(
            session,
            ROLE,
            project.id,
            knowledge_query(project, pitch, answers, genre_name),
            include_bible=False,
            genre=project.style_genre,
        )
        if knowledge
        else None,
    )


def _fmt(path: str, value: Any) -> str:
    kind = _kind(path)
    if kind == "bool":
        return "oui" if value else "non"
    if kind == "share":
        return f"{value:g} ({round(value * 100)} %)"
    return str(value)


def genre_dna_text(base: PreDirection) -> str:
    specs = {f["path"]: f for f in field_specs()}
    lines = []
    for path, value in flatten(base).items():
        f = specs[path]
        ranged = f["kind"] != "bool" and f["min"] is not None and f["max"] is not None
        bounds = f" [{f['min']:g} à {f['max']:g}]" if ranged else ""
        lines.append(f"- {path} — {LABELS.get(path, (path,))[0]} : {_fmt(path, value)}{bounds}")
    return "\n".join(lines)


def answers_text(brief: CreatorBrief) -> str:
    by_question: dict[str, list[Suggestion]] = {}
    for s in brief.suggestions:
        by_question.setdefault(s.question, []).append(s)
    lines = []
    for a in brief.answers:
        line = f"- {a.question.label} → {a.choice.label}"
        if a.note:
            line += f" (précision de l'auteur : « {a.note} »)"
        hints = by_question.get(a.question.label) or []
        if hints:
            line += " — pistes : " + ", ".join(f"{h.path} = {_fmt(h.path, h.value)}" for h in hints)
        lines.append(line)
    return "\n".join(lines)


def creator_messages(prompt: PromptPreset, brief: CreatorBrief) -> list[ChatMessage]:
    s = brief.settings
    chars = "\n".join(
        f"- {c['name']} : {c['description'] or '(sans description)'}"
        + (f" — note actuelle : {c['note']}" if c["note"] else "")
        for c in brief.characters
    )
    chapters = "\n".join(
        f"- Chapitre {c['number']}{' — ' + c['title'] if c['title'] else ''} : {c['synopsis'] or '(sans synopsis)'}"
        + (f" (résumé validé : {c['summary']})" if c["summary"] else "")
        for c in brief.chapters
    )
    bible = "\n\n".join(f"{label} :\n{brief.bible[k]}" for k, label in BIBLE_SECTIONS if brief.bible[k])
    values = {
        "series_title": brief.title,
        "genre": brief.genre,
        "style_packs": brief.style_packs,
        "style_guidelines": brief.style_guidelines,
        "reading_direction": brief.reading_direction,
        "pitch": brief.pitch or "(l'auteur n'a rien précisé : appuie-toi sur le titre, le genre et ses réponses)",
        "answers": answers_text(brief),
        "characters": chars or "(aucune fiche personnage pour l'instant : « characters » reste vide)",
        "chapters": chapters or "(aucun chapitre : nouvelle série)",
        "current_bible": bible or "(bible vide)",
        "genre_dna": genre_dna_text(brief.base),
        "max_section_chars": str(s.max_section_chars),
        "max_note_chars": str(s.max_note_chars),
        "savoir_faire": (brief.knowledge.savoir_faire() if brief.knowledge else "") or "(aucun passage)",
        "context_json": json.dumps(brief.as_json(), ensure_ascii=False),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- validation ---------------------------------------------------------------------------------------------
class _DnaItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = Field(min_length=1, max_length=100)
    value: bool | int | float
    why: str = ""


class _Bible(BaseModel):
    model_config = ConfigDict(extra="ignore")

    world: str = ""
    tone: str = ""
    rules: str = ""
    motifs: str = ""


class _Note(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    note: str = ""


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dna: list[_DnaItem] = Field(default_factory=list, max_length=MAX_DNA_CHANGES)
    bible: _Bible
    characters: list[_Note] = Field(default_factory=list, max_length=200)
    notes: str = ""


@dataclass
class DnaChange:
    path: str
    value: Any
    why: str


@dataclass
class Proposal:
    dna: list[DnaChange]
    bible: dict[str, str]
    notes_by_id: dict[int, str]
    notes: str = ""

    def overrides(self) -> dict[str, Any]:
        return {c.path: c.value for c in self.dna}


def _load(text: str) -> dict[str, Any]:
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProposalValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise ProposalValidationError("la racine doit être un objet JSON")
    return data


def _dna_value(path: str, value: Any) -> Any:
    """Booléen pour un réglage oui/non, entier pour un entier (6.0 → 6) : sinon la valeur telle quelle."""
    kind = _kind(path)
    if kind == "bool" and isinstance(value, int | float) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if kind == "int" and isinstance(value, float) and value == int(value):
        return int(value)
    return value


def parse_proposal(text: str, brief: CreatorBrief) -> Proposal:
    try:
        answer = _Answer.model_validate(_load(text))
    except ValidationError as exc:
        raise ProposalValidationError(format_errors(exc, {"dna": "dna", "characters": "characters"})) from None
    s = brief.settings
    problems: list[str] = []
    # ADN : chemins connus, valeurs bornées, une explication par écart ; une valeur égale au genre n'est pas un écart.
    inherited = flatten(brief.base)
    changes: list[DnaChange] = []
    seen: set[str] = set()
    for item in answer.dna:
        if item.path not in LEAVES:
            problems.append(f"dna : réglage inconnu « {item.path} » (chemins de l'ADN du genre seulement)")
            continue
        if item.path in seen:
            problems.append(f"dna : « {item.path} » proposé deux fois")
            continue
        seen.add(item.path)
        value = _dna_value(item.path, item.value)
        if same_value(value, inherited[item.path]):
            continue
        why = " ".join(item.why.split())
        if not why:
            problems.append(f"dna : « {item.path} » sans explication (« why ») — une phrase par écart au genre")
        elif len(why) > 300:
            problems.append(f"dna : explication de « {item.path} » trop longue (300 signes au plus)")
        changes.append(DnaChange(item.path, value, why))
    if not problems:
        try:
            apply_overrides(brief.base, {c.path: c.value for c in changes})
        except DnaError as exc:
            problems.append(f"dna : {exc.path} — {exc.message}")
    # Bible : quatre sections remplies, dans la longueur.
    bible = {k: _clean(getattr(answer.bible, k)) for k, _ in BIBLE_SECTIONS}
    for key, label in BIBLE_SECTIONS:
        n = len(bible[key])
        if not n:
            problems.append(f"bible.{key} ({label}) : vide")
        elif n > s.max_section_chars:
            problems.append(f"bible.{key} ({label}) : {n} signes, {s.max_section_chars} au plus")
    # Une note par personnage, au nom exact.
    by_name = {_name_key(c["name"]): c for c in brief.characters}
    notes: dict[int, str] = {}
    for item in answer.characters:
        c = by_name.get(_name_key(item.name))
        if c is None:
            problems.append(f"characters : « {item.name} » n'est pas une fiche de la série (noms exacts seulement)")
            continue
        note = _clean(item.note)
        if not note:
            problems.append(f"characters : note vide pour « {c['name']} »")
        elif len(note) > s.max_note_chars:
            problems.append(
                f"characters : note de « {c['name']} » trop longue ({len(note)} signes, {s.max_note_chars} au plus)"
            )
        notes[c["id"]] = note
    missing = [c["name"] for c in brief.characters if c["id"] not in notes]
    if missing:
        problems.append("characters : il manque la note de " + ", ".join(f"« {n} »" for n in missing))
    if problems:
        raise ProposalValidationError(" ; ".join(problems))
    return Proposal(dna=changes, bible=bible, notes_by_id=notes, notes=" ".join(answer.notes.split()))


@dataclass
class ProposalRun:
    output: Proposal
    attempts: int


def propose(llm: LLMProvider, prompt: PromptPreset, brief: CreatorBrief) -> ProposalRun:
    """Proposition validée, ou `CreatorError` après `1 + max_retries` tentatives (erreur renvoyée à l'agent)."""
    messages = creator_messages(prompt, brief)
    total = 1 + prompt.max_retries
    last = ""
    for attempt in range(1, total + 1):
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise CreatorError(f"le LLM n'a pas pu répondre : {exc}") from exc
            last = str(exc)
            continue
        try:
            return ProposalRun(parse_proposal(result.text, brief), attempt)
        except ProposalValidationError as exc:
            last = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
    raise CreatorError(
        f"réponse invalide {total} fois de suite ({last}) : relance l'échange ou écris la bible à la main"
    )


# --- fusion et différentiel ---------------------------------------------------------------------------------
def merge_dna(base: PreDirection, current: Mapping[str, Any], chosen: Mapping[str, Any]) -> dict[str, Any]:
    """Ajustements de la série après l'échange : ceux déjà enregistrés, remplacés par les valeurs retenues ; une
    valeur égale à celle du genre n'est pas gardée (elle suit le genre). `DnaError` si l'ADN devient invalide."""
    merged = {**clean_overrides(base, current), **chosen}
    apply_overrides(base, merged)
    return clean_overrides(base, merged)


@dataclass(frozen=True)
class Conflict:
    key: str  # « bible.world », « character.12 », « dna.shots.wide.min »
    label: str


def conflicts(
    *,
    base: PreDirection,
    current_overrides: Mapping[str, Any],
    current_bible: Mapping[str, str],
    current_notes: Mapping[int, str],
    dna: Mapping[str, Any],
    bible: Mapping[str, str],
    notes: Mapping[int, str],
    names: Mapping[int, str],
) -> list[Conflict]:
    """Ce que l'auteur a déjà écrit et que la proposition retenue remplacerait (texte non vide, valeur ajustée)."""
    out: list[Conflict] = []
    labels = dict(BIBLE_SECTIONS)
    for key, value in bible.items():
        old = (current_bible.get(key) or "").strip()
        if old and value.strip() and _clean(value) != _clean(old):
            out.append(Conflict(f"bible.{key}", labels.get(key, key)))
    for cid, value in notes.items():
        old = (current_notes.get(cid) or "").strip()
        if old and value.strip() and _clean(value) != _clean(old):
            out.append(Conflict(f"character.{cid}", f"note de {names.get(cid, cid)}"))
    own = clean_overrides(base, current_overrides)
    for path, value in dna.items():
        if path in own and not same_value(own[path], value):
            out.append(Conflict(f"dna.{path}", LABELS.get(path, (path,))[0]))
    return out
