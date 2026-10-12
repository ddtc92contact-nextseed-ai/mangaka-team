"""Atelier — dialogue avec l'IA sur une case précise (agent Dessinateur, son LLM).

L'auteur écrit une consigne en français (« plus serré, gros plan sur le visage de Lucius, en
contre-plongée », « enlève le décor, fond blanc ») ; le LLM reçoit le contexte de la case (scénario,
direction artistique appliquée, personnages, images de référence envoyées et celles qu'on peut choisir,
prompt actuel) et l'historique des échanges sur cette case, puis rend un JSON validé (Pydantic, puis
contre la case) :

- `prompt` : le nouveau prompt final (anglais, conventions Qwen de `redacteur-image.yaml` : rôles des
  `<imageN>` en tête, phrase de caméra… — mêmes contrôles que le rédacteur) ;
- `direction` (facultatif) : `plan`, `angle`, `action`, `ambiance` de la case — plan et angle parmi les
  valeurs de la direction artistique (`art_direction.PLANS`, `ANGLES`), toute autre valeur est refusée ;
- `references` (facultatif) : par personnage, l'image de référence à envoyer, choisie parmi les images
  gardées de sa fiche (le portrait pour un gros plan, la planche en pied pour un plan large) ;
- `explanation` : une phrase en français, montrée dans l'historique.

Réponse invalide → nouvel essai avec l'erreur (`max_retries` du gabarit) → sinon `PromptDialogError`
(message lisible ; la case ne change pas). Gabarit : `presets/prompts/redacteur-image-dialogue.yaml`.

Fonctions pures (aucune base) : le rassemblement des données d'une case vit dans `generation.py`, le
stockage et l'application dans `api/prompt_dialog.py`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from ..presets import PresetRegistry, PromptPreset
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..validation import format_errors
from .art_direction import ANGLES, DIALOG_FIELDS, PLANS, AngleName, PlanName, _norm
from .names import name_key
from .prompt import camera_term
from .prompt_writer import (
    PromptBrief,
    PromptValidationError,
    clean_paragraph,
    finish_paragraph,
    load_json_object,
    paragraph_problems,
    template_values,
)
from .script import _render

PROMPT_ID = "redacteur-image-dialogue"  # presets/prompts/redacteur-image-dialogue.yaml
TASK = "image_prompt_dialog"  # `task` du bloc <contexte> (reconnu par le LLM factice)
MAX_HISTORY = 12  # échanges précédents envoyés au LLM (les plus récents)
DIRECTION_LABELS = {"plan": "Plan", "angle": "Angle", "action": "Action", "ambiance": "Ambiance"}
STATUS_LABELS = {"proposed": "proposed", "applied": "applied", "cancelled": "cancelled by the author"}


class PromptDialogError(Exception):
    """Proposition impossible (message lisible, en français)."""


# --- données --------------------------------------------------------------------------------
@dataclass
class ReferenceOption:
    """Une image gardée de la fiche d'un personnage de la case, que la case peut envoyer."""

    character_id: int
    character: str
    image_id: int
    label: str  # « Portrait de face (image 2) »
    current: bool = False  # celle envoyée aujourd'hui pour ce personnage

    def as_json(self) -> dict[str, Any]:
        return {"character": self.character, "image_id": self.image_id, "label": self.label, "current": self.current}


@dataclass
class DialogTurnBrief:
    instruction: str
    explanation: str
    status: str


@dataclass
class DialogBrief:
    """Ce que le LLM sait de la case pour répondre à une consigne."""

    brief: PromptBrief
    instruction: str
    current_prompt: str = ""
    # Direction artistique appliquée à la case aujourd'hui (plan, angle, action, ambiance ; français).
    direction: dict[str, str] = field(default_factory=dict)
    options: list[ReferenceOption] = field(default_factory=list)
    history: list[DialogTurnBrief] = field(default_factory=list)
    camera_terms: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        brief: PromptBrief,
        instruction: str,
        *,
        current_prompt: str = "",
        direction: dict[str, Any] | None = None,
        options: Sequence[ReferenceOption] = (),
        history: Sequence[DialogTurnBrief] = (),
        presets: PresetRegistry | None = None,
    ) -> DialogBrief:
        settings = presets.image_prompt if presets is not None else None
        current = {k: str(v).strip() for k, v in (direction or {}).items() if k in DIALOG_FIELDS and v}
        return cls(
            brief=brief,
            instruction=" ".join(instruction.split()),
            current_prompt=(current_prompt or "").strip(),
            direction=current,
            options=list(options),
            history=list(history)[-MAX_HISTORY:],
            camera_terms={v: camera_term(v, settings) for v in (*PLANS, *ANGLES)},
        )

    def current_image(self, character_id: int) -> int | None:
        return next((o.image_id for o in self.options if o.character_id == character_id and o.current), None)

    def as_json(self) -> dict[str, Any]:
        return {
            **self.brief.as_json(),
            "task": TASK,
            "instruction": self.instruction,
            "current_prompt": self.current_prompt,
            "current_direction": self.direction,
            "allowed": {"plan": list(PLANS), "angle": list(ANGLES)},
            "camera_terms": self.camera_terms,
            "reference_options": [o.as_json() for o in self.options],
            "history": [
                {"instruction": h.instruction, "explanation": h.explanation, "status": h.status} for h in self.history
            ],
        }


# --- messages ---------------------------------------------------------------------------------
def _history_text(history: Sequence[DialogTurnBrief]) -> str:
    lines = [
        f"- Author: {h.instruction}\n  You: {h.explanation or '(no explanation)'} ({STATUS_LABELS.get(h.status, h.status)})"
        for h in history
    ]
    return "\n".join(lines) or "(first request on this panel)"


def _options_text(options: Sequence[ReferenceOption]) -> str:
    lines = [
        f"- {o.character}: image_id {o.image_id} = {o.label}{' (sent today)' if o.current else ''}" for o in options
    ]
    return "\n".join(lines) or "(no choice: each character of the panel has at most one reference image)"


def render_messages(prompt: PromptPreset, d: DialogBrief) -> list[ChatMessage]:
    values = template_values(d.brief)
    values.update(
        {
            "instruction": d.instruction,
            "current_prompt": d.current_prompt or "(none yet: write it from the panel data)",
            "current_direction": ", ".join(f"{k}: {v}" for k, v in d.direction.items()) or "(none)",
            "plans": ", ".join(PLANS),
            "angles": ", ".join(ANGLES),
            "camera_terms": "; ".join(f"{k} = {v}" for k, v in d.camera_terms.items()),
            "reference_options": _options_text(d.options),
            "history": _history_text(d.history),
            "context_json": json.dumps(d.as_json(), ensure_ascii=False, indent=2),
        }
    )
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- validation ---------------------------------------------------------------------------------
def _angle(value: Any) -> Any:
    """« contre-plongée » donné comme angle → « en contre-plongée » (la valeur de la liste des angles)."""
    v = _norm(value)
    return f"en {v}" if v in ("plongée", "contre-plongée") else v


class DirectionChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    plan: PlanName | None = None
    angle: AngleName | None = None
    action: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    ambiance: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None

    _p = field_validator("plan", mode="before")(_norm)
    _a = field_validator("angle", mode="before")(_angle)

    @field_validator("action", "ambiance", mode="before")
    @classmethod
    def _empty(cls, v: Any) -> Any:
        return None if v is None or (isinstance(v, str) and not v.strip()) else v


class ReferenceChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    image_id: int


class DialogAnswer(BaseModel):
    """Réponse du LLM à une consigne."""

    model_config = ConfigDict(extra="ignore")

    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    language: Literal["fr", "en"]
    direction: DirectionChange | None = None
    references: list[ReferenceChange] = Field(default_factory=list, max_length=12)
    explanation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

    @field_validator("language", mode="before")
    @classmethod
    def _lang(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("references", mode="before")
    @classmethod
    def _none_list(cls, v: Any) -> Any:
        return [] if v is None else v


@dataclass
class DialogProposal:
    """Ce que l'IA propose pour la case (seuls les champs qui changent)."""

    prompt: str
    explanation: str
    direction: dict[str, str] = field(default_factory=dict)
    references: dict[int, int] = field(default_factory=dict)  # id du personnage → id de l'image
    changes: list[dict[str, Any]] = field(default_factory=list)  # {field, label, before, after}

    def as_json(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "explanation": self.explanation,
            "direction": self.direction,
            "references": {str(k): v for k, v in self.references.items()},
            "changes": self.changes,
        }


def parse_dialog(text: str, d: DialogBrief) -> DialogProposal:
    """Valide la réponse brute du LLM (schéma, valeurs permises, puis paragraphe contre la case)."""
    data = load_json_object(text, "« prompt » et « explanation »")
    try:
        out = DialogAnswer.model_validate(data)
    except ValidationError as exc:
        raise PromptValidationError(format_errors(exc)) from None
    problems: list[str] = []
    by_name: dict[str, list[ReferenceOption]] = {}
    for o in d.options:
        by_name.setdefault(name_key(o.character), []).append(o)
    references: dict[int, int] = {}
    labels: dict[int, ReferenceOption] = {o.image_id: o for o in d.options}
    for ref in out.references:
        choices = by_name.get(name_key(ref.character))
        if not choices:
            allowed = ", ".join(dict.fromkeys(o.character for o in d.options)) or "aucun"
            problems.append(
                f"references : « {ref.character} » n'a pas d'image à choisir dans cette case (personnages possibles : {allowed})"
            )
            continue
        if ref.image_id not in {o.image_id for o in choices}:
            ids = ", ".join(str(o.image_id) for o in choices)
            problems.append(f"references : image {ref.image_id} inconnue pour {choices[0].character} (images : {ids})")
            continue
        character_id = choices[0].character_id
        if d.current_image(character_id) != ref.image_id:
            references[character_id] = ref.image_id
    paragraph = clean_paragraph(out.prompt)
    problems += paragraph_problems(paragraph, out.language, d.brief)
    if problems:
        raise PromptValidationError(" ; ".join(problems))
    direction: dict[str, str] = {}
    changes: list[dict[str, Any]] = []
    if out.direction is not None:
        for name in DIALOG_FIELDS:
            value = getattr(out.direction, name)
            if value is not None and value != d.direction.get(name):
                direction[name] = value
                changes.append(
                    {"field": name, "label": DIRECTION_LABELS[name], "before": d.direction.get(name), "after": value}
                )
    for character_id, image_id in references.items():
        after = labels[image_id]
        before_id = d.current_image(character_id)
        changes.append(
            {
                "field": f"reference.{character_id}",
                "label": f"Référence de {after.character}",
                "before": labels[before_id].label if before_id in labels else None,
                "after": after.label,
            }
        )
    return DialogProposal(
        prompt=finish_paragraph(paragraph, d.brief),
        explanation=out.explanation,
        direction=direction,
        references=references,
        changes=changes,
    )


# --- appel du LLM avec relances -------------------------------------------------------------
Progress = Callable[[str], None]


@dataclass
class DialogRun:
    proposal: DialogProposal
    attempts: int


def propose(llm: LLMProvider, prompt: PromptPreset, d: DialogBrief, progress: Progress | None = None) -> DialogRun:
    """Proposition validée, ou `PromptDialogError` après `1 + max_retries` tentatives."""
    if not d.instruction:
        raise PromptDialogError("consigne vide : écris ce que l'IA doit changer dans la case")
    messages = render_messages(prompt, d)
    total = 1 + prompt.max_retries
    last_error = ""
    for attempt in range(1, total + 1):
        if progress is not None:
            progress(f"L'IA réfléchit à la case (essai {attempt}/{total})…")
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            last_error = str(exc)
            if not exc.retryable or attempt == total:
                raise PromptDialogError(f"le LLM n'a pas pu répondre : {exc}") from exc
            continue
        try:
            proposal = parse_dialog(result.text, d)
        except PromptValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return DialogRun(proposal=proposal, attempts=attempt)
    raise PromptDialogError(f"réponse invalide {total} fois de suite ({last_error})")
