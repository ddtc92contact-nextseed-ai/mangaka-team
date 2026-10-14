"""4e de couverture d'un tome : résumé d'accroche et phrase d'accroche rédigés par l'IA (mini-pipeline).

Un agent LLM (LLM du Scénariste, prompt `presets/prompts/resume-quatrieme.yaml`) lit les résumés des chapitres du
tome (à défaut leur synopsis) et la bible de la série, et écrit :

- `summary` : texte de 4e de couverture, entre `min_chars` et `max_chars` signes espaces compris
  (`cover_composition.yaml › summary`), un à trois paragraphes ;
- `tagline` : phrase d'accroche courte (`tagline_max_chars` signes au plus), sur une ligne.

Pas de révélation de la fin du tome : la fin du dernier chapitre est donnée à l'agent comme « à ne jamais
révéler », et une réponse qui en reprend `spoiler_words` mots d'affilée est refusée. Chaque réponse est validée
(JSON, longueurs, reprise de la fin) ; une réponse invalide est renvoyée à l'agent avec l'erreur (`max_retries`
du prompt, 2 au plus), puis `BackCoverError` lisible. « Réécrire » donne à l'agent le résumé actuel, à ne pas
répéter.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from ..presets import PresetRegistry, PromptPreset
from ..presets.schemas import SummarySettings
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.models import Volume
from ..validation import format_errors
from .covers import volume_label
from .knowledge import render_bible
from .script import _render

AGENT_ID = "scenariste"  # agent dont le LLM écrit le résumé (écran « L'équipe »)
TASK = "back_summary"
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_WORD = re.compile(r"\w+", re.UNICODE)


class BackCoverError(Exception):
    """L'agent n'a pas pu écrire le résumé (LLM indisponible, réponses invalides) : message lisible."""


class SummaryValidationError(ValueError):
    """Réponse du LLM refusée (message renvoyé à l'agent pour qu'il corrige)."""


# --- texte ---------------------------------------------------------------------------------------------------
def clean_summary(text: str) -> str:
    """Paragraphes séparés par une ligne vide, espaces simples dans chaque paragraphe, texte en NFC (accents)."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n"))
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def clean_tagline(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def sign_count(text: str) -> int:
    """Signes espaces compris (un saut de paragraphe compte pour une espace)."""
    return len(" ".join(text.split()))


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(unicodedata.normalize("NFC", text))]


def shared_run(text: str, other: str, n: int) -> str | None:
    """Premier passage d'au moins `n` mots d'affilée de `text` repris tel quel de `other` (None : aucun)."""
    if n <= 0:
        return None
    a, b = _words(text), _words(other)
    grams = {tuple(b[i : i + n]) for i in range(len(b) - n + 1)}
    for i in range(len(a) - n + 1):
        if tuple(a[i : i + n]) in grams:
            return " ".join(a[i : i + n])
    return None


# --- contexte ------------------------------------------------------------------------------------------------
@dataclass
class SummaryBrief:
    series: str
    volume: str
    chapters: list[dict[str, Any]]  # {number, title, summary}
    ending: str
    bible: str
    settings: SummarySettings
    previous: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        s = self.settings
        return {
            "task": TASK,
            "series": self.series,
            "volume": self.volume,
            "chapters": self.chapters,
            "ending": self.ending,
            "min_chars": s.min_chars,
            "max_chars": s.max_chars,
            "tagline_max_chars": s.tagline_max_chars,
            "previous": self.previous,
        }


def chapter_text(chapter: Any) -> str:
    return " ".join((chapter.summary or chapter.synopsis or "").split())


def summary_brief(
    session: Session, presets: PresetRegistry, volume: Volume, *, bible_max_tokens: int, previous: str = ""
) -> SummaryBrief:
    """Contexte de l'agent ; `BackCoverError` si le tome n'a aucun chapitre."""
    settings = presets.require_composition().summary
    chapters = [link.chapter for link in volume.chapter_links]
    if not chapters:
        raise BackCoverError("le tome n'a aucun chapitre : ajoute ses chapitres avant d'écrire la 4e de couverture")
    items = [
        {"number": c.number, "title": c.title, "summary": chapter_text(c) or "(pas encore de résumé)"} for c in chapters
    ]
    bible = render_bible(session, volume.project_id, max_tokens=bible_max_tokens)
    return SummaryBrief(
        series=volume.project.title,
        volume=volume_label(volume),
        chapters=items,
        ending=chapter_text(chapters[-1]),
        bible=bible.text if bible is not None else "",
        settings=settings,
        previous=clean_summary(previous),
    )


def summary_messages(prompt: PromptPreset, brief: SummaryBrief) -> list[ChatMessage]:
    s = brief.settings
    chapters = "\n".join(
        f"- Chapitre {c['number']}{' — ' + c['title'] if c['title'] else ''} : {c['summary']}" for c in brief.chapters
    )
    values = {
        "series": brief.series,
        "volume": brief.volume,
        "chapters": chapters,
        "ending": brief.ending or "(non précisée)",
        "bible": brief.bible or "(pas encore de bible pour cette série)",
        "min_chars": str(s.min_chars),
        "max_chars": str(s.max_chars),
        "tagline_max_chars": str(s.tagline_max_chars),
        "previous": brief.previous or "(aucun)",
        "context_json": json.dumps(brief.as_json(), ensure_ascii=False),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- validation ---------------------------------------------------------------------------------------------
class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tagline: str
    summary: str
    notes: str = ""


@dataclass
class WrittenSummary:
    summary: str
    tagline: str
    notes: str


def _load(text: str) -> dict[str, Any]:
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SummaryValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise SummaryValidationError("la racine doit être un objet JSON")
    return data


def parse_summary(text: str, brief: SummaryBrief) -> WrittenSummary:
    try:
        answer = _Answer.model_validate(_load(text))
    except ValidationError as exc:
        raise SummaryValidationError(format_errors(exc)) from None
    s = brief.settings
    summary, tagline = clean_summary(answer.summary), clean_tagline(answer.tagline)
    problems: list[str] = []
    n = sign_count(summary)
    if not s.min_chars <= n <= s.max_chars:
        problems.append(f"summary : {n} signes, entre {s.min_chars} et {s.max_chars} attendus (espaces compris)")
    if not tagline:
        problems.append("tagline : phrase d'accroche vide")
    elif len(tagline) > s.tagline_max_chars:
        problems.append(f"tagline : {len(tagline)} signes, {s.tagline_max_chars} au plus")
    for key, value in (("summary", summary), ("tagline", tagline)):
        run = shared_run(value, brief.ending, s.spoiler_words)
        if run:
            problems.append(f"{key} : reprend la fin du tome (« {run} ») — ne révèle pas la fin")
    if brief.previous and summary.casefold() == brief.previous.casefold():
        problems.append("summary : identique au résumé actuel — écris-en un autre")
    if problems:
        raise SummaryValidationError(" ; ".join(problems))
    return WrittenSummary(summary=summary, tagline=tagline, notes=" ".join(answer.notes.split()))


@dataclass
class SummaryRun:
    output: WrittenSummary
    attempts: int


def write_summary(llm: LLMProvider, prompt: PromptPreset, brief: SummaryBrief) -> SummaryRun:
    """Résumé validé, ou `BackCoverError` après `1 + max_retries` tentatives (erreur renvoyée à l'agent)."""
    messages = summary_messages(prompt, brief)
    total = 1 + prompt.max_retries
    last = ""
    for attempt in range(1, total + 1):
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise BackCoverError(f"le LLM n'a pas pu écrire le résumé : {exc}") from exc
            last = str(exc)
            continue
        try:
            return SummaryRun(parse_summary(result.text, brief), attempt)
        except SummaryValidationError as exc:
            last = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
    raise BackCoverError(f"réponse invalide {total} fois de suite pour le résumé de 4e ({last}) : écris-le à la main")
