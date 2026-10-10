"""Étape 3 — rédaction du prompt image d'une case par le LLM texte (agent Dessinateur).

Qwen-Image 2.1 (encodeur Qwen3-VL) suit mieux un paragraphe descriptif cohérent que les fragments
étiquetés de `prompt.build_prompt` : le LLM reçoit les données structurées de la case (`PromptBrief` :
plan, angle, description, lieu, mise en scène, personnages et leurs traits, décor, objets, ambiance,
repères de la bible, `$style`, images de référence et leur rôle) et rend UN paragraphe, dans la langue
du preset (`presets/prompts/redacteur-image.yaml`).

Sortie JSON validée par Pydantic (`prompt`, `language`, `notes`) puis contre la case : chaque
personnage de la case nommé, aucun personnage de la série absent de la case, longueur plausible ;
invalide → nouvel essai avec l'erreur (`max_retries`) → sinon `PromptWriterError` (l'appelant retombe
sur le prompt par fragments, avec un avertissement sur la case).

Le texte n'est jamais dessiné : les répliques entre guillemets sont retirées des données envoyées ET
du paragraphe rendu. Les mots-clés de style restent dans leur langue mesurée : absents du paragraphe,
ils y sont ajoutés tels quels.

Fonctions pures (aucune base) : le rassemblement des données d'une case vit dans `generation.py`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError, field_validator

from ..presets import PromptPreset
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..validation import format_errors
from .names import _contains, name_key
from .prompt import PromptCharacter, ReferenceSlot, strip_quoted
from .script import _render

PROMPT_ID = "redacteur-image"  # presets/prompts/redacteur-image.yaml
AGENT_ID = "dessinateur"  # presets/agents/dessinateur.yaml (son LLM rédige le prompt)
TASK = "image_prompt"  # `task` du bloc <contexte> (reconnu par le LLM factice)

LANGUAGE_NAMES = {"fr": "français", "en": "anglais"}
DEFAULT_MIN_WORDS, DEFAULT_MAX_WORDS = 80, 160
# Tolérance sur la longueur visée : en deçà de 60 % du minimum ou au-delà de 150 % du maximum, la
# réponse est refusée (un paragraphe un peu court ou un peu long reste utilisable).
MIN_RATIO, MAX_RATIO = 0.6, 1.5
REFERENCE_ROLES = {
    "character": "identité de {name} (visage, silhouette, costume)",
    "decor": "le lieu {name}",
    "object": "l'objet {name}",
    "style": "style seulement (ne pas reprendre ses personnages ni sa scène)",
}
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_SPACES = re.compile(r"\s+")


class PromptWriterError(Exception):
    """Rédaction impossible (message lisible, en français)."""


class PromptValidationError(ValueError):
    pass


# --- données de la case -------------------------------------------------------------
def _text(value: str | None) -> str:
    """Texte envoyé au LLM : sans réplique entre guillemets, espaces simples."""
    return _SPACES.sub(" ", strip_quoted(value or "")).strip().rstrip(" .;,:")


def _details(entry: PromptCharacter) -> str:
    parts = [_text(entry.visual_description), *(_text(k) for k in entry.prompt_keywords)]
    return ", ".join(dict.fromkeys(p for p in parts if p))


@dataclass
class PromptBrief:
    """Ce que le rédacteur sait d'une case (déjà débarrassé des répliques)."""

    description: str = ""
    setting: str = ""
    staging: str = ""
    plan: str = ""
    angle: str = ""
    ambiance: str = ""
    characters: list[PromptCharacter] = field(default_factory=list)
    # Noms écrits par le scénario sans fiche (figurants) : décrits tels quels, sans obligation.
    extras: list[str] = field(default_factory=list)
    # Personnages de la série absents de la case : à ne jamais nommer.
    absent: list[str] = field(default_factory=list)
    decor: PromptCharacter | None = None
    objects: list[PromptCharacter] = field(default_factory=list)
    references: list[ReferenceSlot] = field(default_factory=list)
    style: str = ""
    bible: str = ""
    savoir_faire: str = ""
    language: str = "fr"
    min_words: int = DEFAULT_MIN_WORDS
    max_words: int = DEFAULT_MAX_WORDS

    @classmethod
    def build(
        cls,
        *,
        description: str,
        setting: str = "",
        staging: str = "",
        shot_type: str | None = None,
        plan: str | None = None,
        angle: str | None = None,
        ambiance: str | None = None,
        characters: Sequence[PromptCharacter] = (),
        extras: Sequence[str] = (),
        absent: Sequence[str] = (),
        decor: PromptCharacter | None = None,
        objects: Sequence[PromptCharacter] = (),
        references: Sequence[ReferenceSlot] = (),
        style: str = "",
        bible: str = "",
        savoir_faire: str = "",
        prompt: PromptPreset | None = None,
    ) -> PromptBrief:
        present = {name_key(c.name) for c in characters}
        return cls(
            description=_text(description),
            setting=_text(setting),
            staging=_text(staging),
            plan=_text(plan) or _text(shot_type),
            angle=_text(angle),
            ambiance=_text(ambiance),
            characters=list(characters),
            extras=list(dict.fromkeys(n for n in (_text(e) for e in extras) if n)),
            absent=list(dict.fromkeys(n for n in absent if n.strip() and name_key(n) not in present)),
            decor=decor,
            objects=list(objects),
            references=list(references),
            style=_SPACES.sub(" ", style or "").strip().rstrip(" .;,"),
            bible=_text(bible),
            savoir_faire=_text(savoir_faire),
            language=(prompt.language if prompt and prompt.language else "fr"),
            min_words=(prompt.min_words if prompt and prompt.min_words else DEFAULT_MIN_WORDS),
            max_words=(prompt.max_words if prompt and prompt.max_words else DEFAULT_MAX_WORDS),
        )

    def reference_lines(self) -> list[dict[str, Any]]:
        return [
            {
                "image": i,
                "kind": slot.kind,
                "name": slot.name,
                "role": REFERENCE_ROLES.get(slot.kind, REFERENCE_ROLES["character"]).format(name=slot.name),
            }
            for i, slot in enumerate(self.references, start=1)
        ]

    def as_json(self) -> dict[str, Any]:
        def entry(e: PromptCharacter) -> dict[str, str]:
            return {"name": e.name, "details": _details(e)}

        return {
            "task": TASK,
            "language": self.language,
            "min_words": self.min_words,
            "max_words": self.max_words,
            "panel": {
                "plan": self.plan,
                "angle": self.angle,
                "description": self.description,
                "setting": self.setting,
                "staging": self.staging,
                "ambiance": self.ambiance,
            },
            "characters": [entry(c) for c in self.characters],
            "extras": self.extras,
            "absent_characters": self.absent,
            "decor": entry(self.decor) if self.decor is not None else None,
            "objects": [entry(o) for o in self.objects],
            "references": self.reference_lines(),
            "style": self.style,
        }

    def key(self) -> str:
        """Empreinte des données de la case (bible et savoir-faire exclus : ils varient avec la base de
        connaissances) : le prompt rédigé n'est redemandé que si elle change."""
        raw = json.dumps(self.as_json(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


# --- messages -----------------------------------------------------------------------
def _or(value: str, empty: str) -> str:
    return value or empty


def render_messages(prompt: PromptPreset, brief: PromptBrief) -> list[ChatMessage]:
    chars = [f"- {c.name} : {_details(c) or '(sans description)'}" for c in brief.characters]
    chars += [f"- {e} (figurant, sans fiche)" for e in brief.extras]
    refs = [f"- image {r['image']} : {r['role']}" for r in brief.reference_lines()]
    lib = ", ".join(f"{o.name} ({_details(o)})" if _details(o) else o.name for o in brief.objects)
    values = {
        "language": brief.language,
        "language_name": LANGUAGE_NAMES.get(brief.language, brief.language),
        "min_words": str(brief.min_words),
        "max_words": str(brief.max_words),
        "plan": _or(brief.plan, "(libre)"),
        "angle": _or(brief.angle, "(libre)"),
        "ambiance": _or(brief.ambiance, "(libre)"),
        "description": _or(brief.description, "(aucune)"),
        "setting": _or(brief.setting, "(non précisé)"),
        "staging": _or(brief.staging, "(non précisée)"),
        "characters": "\n".join(chars) or "(aucun personnage : la case montre un lieu ou un objet)",
        "character_names": ", ".join(c.name for c in brief.characters) or "(aucun)",
        "absent_characters": ", ".join(brief.absent) or "(aucun)",
        "decor": (f"{brief.decor.name} ({_details(brief.decor)})" if brief.decor and _details(brief.decor) else "")
        or (brief.decor.name if brief.decor else "(aucun)"),
        "objects": lib or "(aucun)",
        "references": "\n".join(refs) or "(aucune image de référence)",
        "style": _or(brief.style, "(aucun)"),
        "bible": _or(brief.bible, "(rien de particulier)"),
        "savoir_faire": _or(brief.savoir_faire, "(aucun)"),
        "context_json": json.dumps(brief.as_json(), ensure_ascii=False, indent=2),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- validation ---------------------------------------------------------------------
class WrittenPrompt(BaseModel):
    """Réponse du rédacteur."""

    model_config = ConfigDict(extra="ignore")

    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    language: Literal["fr", "en"]
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None

    @field_validator("language", mode="before")
    @classmethod
    def _lang(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("notes", mode="before")
    @classmethod
    def _empty_notes(cls, v: Any) -> Any:
        return None if v is None or (isinstance(v, str) and not v.strip()) else v


def mentions(text: str, name: str) -> bool:
    """`name` apparaît dans `text` en mots entiers (sans tenir compte de la casse ni des accents)."""
    return _contains(name_key(text).split(), name_key(name).split())


def word_count(text: str) -> int:
    return len(text.split())


def clean_paragraph(text: str) -> str:
    """Un seul paragraphe, sans réplique ni guillemet."""
    return _SPACES.sub(" ", strip_quoted(text)).strip()


def with_style(text: str, style: str) -> str:
    """Les mots-clés de style, dans leur langue mesurée : ajoutés tels quels s'ils manquent."""
    if not style or name_key(style) in name_key(text):
        return text
    body = text.rstrip()
    if body and body[-1] not in ".!?…":
        body += "."
    return f"{body} {style}."


def parse_written(text: str, brief: PromptBrief) -> WrittenPrompt:
    """Valide la réponse brute du LLM (schéma, puis cohérence avec la case) ; paragraphe nettoyé."""
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PromptValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise PromptValidationError("la racine doit être un objet JSON avec « prompt »")
    try:
        out = WrittenPrompt.model_validate(data)
    except ValidationError as exc:
        raise PromptValidationError(format_errors(exc)) from None
    problems: list[str] = []
    if out.language != brief.language:
        problems.append(
            f"language : « {out.language} » au lieu de « {brief.language} » (écris le paragraphe en {LANGUAGE_NAMES.get(brief.language, brief.language)})"
        )
    paragraph = clean_paragraph(out.prompt)
    missing = [c.name for c in brief.characters if not mentions(paragraph, c.name)]
    if missing:
        problems.append(f"personnages de la case non nommés : {', '.join(missing)}")
    intruders = [n for n in brief.absent if mentions(paragraph, n)]
    if intruders:
        problems.append(f"personnages absents de la case nommés (à retirer) : {', '.join(intruders)}")
    words = word_count(paragraph)
    low, high = math.floor(brief.min_words * MIN_RATIO), math.ceil(brief.max_words * MAX_RATIO)
    if words < low:
        problems.append(f"prompt trop court ({words} mots ; entre {brief.min_words} et {brief.max_words} attendus)")
    elif words > high:
        problems.append(f"prompt trop long ({words} mots ; entre {brief.min_words} et {brief.max_words} attendus)")
    if problems:
        raise PromptValidationError(" ; ".join(problems))
    return out.model_copy(update={"prompt": with_style(paragraph, brief.style)})


# --- appel du LLM avec relances -------------------------------------------------
Progress = Callable[[str], None]


@dataclass
class WriteRun:
    output: WrittenPrompt
    attempts: int


def write_prompt(
    llm: LLMProvider, prompt: PromptPreset, brief: PromptBrief, progress: Progress | None = None
) -> WriteRun:
    """Paragraphe validé, ou `PromptWriterError` après `1 + max_retries` tentatives."""
    messages = render_messages(prompt, brief)
    total = 1 + prompt.max_retries
    last_error = ""
    for attempt in range(1, total + 1):
        if progress is not None:
            progress(f"Rédaction du prompt par l'IA (essai {attempt}/{total})…")
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            last_error = str(exc)
            if not exc.retryable or attempt == total:
                raise PromptWriterError(f"le LLM n'a pas pu répondre : {exc}") from exc
            continue
        try:
            output = parse_written(result.text, brief)
        except PromptValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return WriteRun(output=output, attempts=attempt)
    raise PromptWriterError(f"réponse invalide {total} fois de suite ({last_error})")
