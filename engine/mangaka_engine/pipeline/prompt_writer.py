"""Étape 3 — rédaction du prompt image d'une case par le LLM texte (agent Dessinateur).

Qwen-Image 2.1 (encodeur Qwen3-VL) suit mieux un paragraphe descriptif cohérent que les fragments
étiquetés de `prompt.build_prompt`, et il est réglé pour l'anglais (l'enhancer officiel écrit toujours
en anglais) : le LLM reçoit les données structurées de la case (`PromptBrief` : plan, angle et leurs
termes de cadrage anglais, action de la direction artistique, description, lieu, mise en scène,
personnages et leurs traits, décor, objets, ambiance, repères de la bible, `$style`, images de
référence et leur rôle) et rend UN long paragraphe mis en scène, traduit dans la langue du preset
(`presets/prompts/redacteur-image.yaml`, anglais par défaut), qui cite chaque image de référence par
`<imageN>` et définit leurs rôles en tête.

Sortie JSON validée par Pydantic (`prompt`, `language`, `notes`) puis contre la case : chaque
personnage de la case nommé, aucun personnage de la série absent de la case, chaque image envoyée citée
(`<image1>`…) et aucune autre, paragraphe anglais sans phrases françaises ni vocabulaire photographique
(`forbidden_photo_terms` d'image_prompt.yaml : « lens », « depth of field »… poussent Qwen-Image vers le
photoréalisme), et pour une série en noir et blanc sans mot de couleur (`monochrome_forbidden_terms`,
retirés aussi des données de la case et du rôle des images), longueur plausible ;
invalide → nouvel essai avec l'erreur (`max_retries`) → sinon `PromptWriterError` (l'appelant retombe
sur le prompt par fragments, avec un avertissement sur la case).

Le texte n'est jamais dessiné : les répliques entre guillemets sont retirées des données envoyées ET
du paragraphe rendu. Le style tient sur toutes les cases, avec ou sans image de référence : le paragraphe
s'ouvre sur la phrase de style de la série (`style.series_style_lead`, ajoutée en tête si le LLM l'a
oubliée) et finit sur les mots-clés de style, dans leur langue mesurée (ajoutés tels quels s'ils manquent).

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

from ..presets import ImagePromptSettings, PromptPreset
from ..presets.schemas import ReferencePromptSettings
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..validation import format_errors
from .names import _contains, name_key
from .prompt import (
    PromptCharacter,
    ReferenceSlot,
    camera_term,
    found_terms,
    image_tags,
    reference_line,
    remove_terms,
    strip_quoted,
)
from .script import _render

PROMPT_ID = "redacteur-image"  # presets/prompts/redacteur-image.yaml
AGENT_ID = "dessinateur"  # presets/agents/dessinateur.yaml (son LLM rédige le prompt)
TASK = "image_prompt"  # `task` du bloc <contexte> (reconnu par le LLM factice)

# $language_name des gabarits (écrits en anglais) ; LANGUAGE_LABELS : messages d'erreur (français).
LANGUAGE_NAMES = {"fr": "French", "en": "English"}
LANGUAGE_LABELS = {"fr": "français", "en": "anglais"}
DEFAULT_LANGUAGE = "en"
DEFAULT_MIN_WORDS, DEFAULT_MAX_WORDS = 180, 320
# Tolérance sur la longueur visée : en deçà de 60 % du minimum ou au-delà de 150 % du maximum, la
# réponse est refusée (un paragraphe un peu court ou un peu long reste utilisable).
MIN_RATIO, MAX_RATIO = 0.6, 1.5
# Mots-outils français : un paragraphe « anglais » qui en contient beaucoup n'a pas été traduit.
_FRENCH_WORDS = frozenset(
    [
        "le",
        "la",
        "les",
        "des",
        "une",
        "est",
        "sont",
        "dans",
        "avec",
        "sur",
        "sous",
        "qui",
        "que",
        "pour",
        "du",
        "au",
        "aux",
        "et",
        "son",
        "sa",
        "ses",
        "leur",
        "leurs",
        "elle",
        "il",
        "ils",
        "elles",
        "se",
        "ce",
        "cette",
        "ces",
        "un",
        "en",
        "par",
        "vers",
        "derrière",
        "devant",
    ]
)
FRENCH_MIN_HITS, FRENCH_MAX_SHARE = 6, 0.04
# Version des consignes du rédacteur, comprise dans l'empreinte d'une case (`PromptBrief.key`) : la changer
# remet à rédiger chaque prompt rédigé par l'IA (jamais un prompt édité à la main) à la prochaine génération.
# 2 : style manga en tête, plus de vocabulaire photographique (12/10/2026).
WRITER_REVISION = 2
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


def image_tag(slot: int) -> str:
    """Citation d'une image de référence dans le prompt Qwen-Image (`<image1>`)."""
    return f"<image{slot}>"


@dataclass
class PromptBrief:
    """Ce que le rédacteur sait d'une case (déjà débarrassé des répliques)."""

    description: str = ""
    setting: str = ""
    staging: str = ""
    plan: str = ""
    angle: str = ""
    # Plan et angle en termes de cadrage anglais (`camera_terms` d'image_prompt.yaml).
    camera: str = ""
    ambiance: str = ""
    # Mouvement ou pose du corps choisi par la direction artistique (français, à traduire).
    action: str = ""
    characters: list[PromptCharacter] = field(default_factory=list)
    # Noms écrits par le scénario sans fiche (figurants) : décrits tels quels, sans obligation.
    extras: list[str] = field(default_factory=list)
    # Personnages de la série absents de la case : à ne jamais nommer.
    absent: list[str] = field(default_factory=list)
    decor: PromptCharacter | None = None
    objects: list[PromptCharacter] = field(default_factory=list)
    references: list[ReferenceSlot] = field(default_factory=list)
    style: str = ""
    # Phrase de style qui ouvre le paragraphe (« Black and white manga panel, inked line art… »).
    style_lead: str = ""
    bible: str = ""
    savoir_faire: str = ""
    # Termes photographiques refusés dans le paragraphe (`forbidden_photo_terms` d'image_prompt.yaml).
    photo_terms: list[str] = field(default_factory=list)
    # Série en noir et blanc : termes de couleur refusés dans le paragraphe (`monochrome_forbidden_terms`) et
    # règle ajoutée aux consignes ($palette_rule, `monochrome_writer_rule`) ; vides pour une série en couleur.
    colour_terms: list[str] = field(default_factory=list)
    palette_rule: str = ""
    # Lignes des images de référence de la série (`references` d'image_prompt.yaml, variante noir et blanc
    # comprise) : le rôle de chaque image en est tiré.
    reference_settings: ReferencePromptSettings = field(default_factory=ReferencePromptSettings)
    language: str = DEFAULT_LANGUAGE
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
        action: str | None = None,
        characters: Sequence[PromptCharacter] = (),
        extras: Sequence[str] = (),
        absent: Sequence[str] = (),
        decor: PromptCharacter | None = None,
        objects: Sequence[PromptCharacter] = (),
        references: Sequence[ReferenceSlot] = (),
        style: str = "",
        style_lead: str = "",
        bible: str = "",
        savoir_faire: str = "",
        prompt: PromptPreset | None = None,
        settings: ImagePromptSettings | None = None,
        monochrome: bool = False,
    ) -> PromptBrief:
        """`monochrome` : série en noir et blanc — rôles des images sans « colours », termes de couleur
        retirés des données de la case (description, fiches…) et refusés dans le paragraphe."""
        settings = settings or ImagePromptSettings()
        present = {name_key(c.name) for c in characters}
        chosen = _text(plan) or _text(shot_type)
        camera = [camera_term(v, settings) for v in (chosen, _text(angle)) if v]
        colour_terms = list(settings.monochrome_forbidden_terms) if monochrome else []
        names = [e.name for e in [*characters, *objects, *([decor] if decor else [])]] + list(extras)

        def plain(value: str | None) -> str:
            return _text(remove_terms(value or "", colour_terms, keep=names)) if colour_terms else _text(value)

        def entry(e: PromptCharacter) -> PromptCharacter:
            if not colour_terms:
                return e
            keywords = tuple(k for k in (plain(k) for k in e.prompt_keywords) if k)
            return PromptCharacter(e.name, plain(e.visual_description), keywords)

        return cls(
            description=plain(description),
            setting=plain(setting),
            staging=plain(staging),
            plan=chosen,
            angle=_text(angle),
            camera=", ".join(dict.fromkeys(camera)),
            ambiance=plain(ambiance),
            action=plain(action),
            characters=[entry(c) for c in characters],
            extras=list(dict.fromkeys(n for n in (_text(e) for e in extras) if n)),
            absent=list(dict.fromkeys(n for n in absent if n.strip() and name_key(n) not in present)),
            decor=entry(decor) if decor is not None else None,
            objects=[entry(o) for o in objects],
            references=list(references),
            style=_SPACES.sub(" ", style or "").strip().rstrip(" .;,"),
            style_lead=_SPACES.sub(" ", style_lead or "").strip(),
            bible=_text(bible),
            # Passages entiers avec leur source (titres entre « ») : ni guillemets retirés ni lignes fusionnées.
            savoir_faire=(savoir_faire or "").strip(),
            photo_terms=list(settings.forbidden_photo_terms),
            colour_terms=colour_terms,
            palette_rule=settings.monochrome_writer_rule.strip() if monochrome else "",
            reference_settings=settings.references.for_palette(monochrome),
            language=(prompt.language if prompt and prompt.language else DEFAULT_LANGUAGE),
            min_words=(prompt.min_words if prompt and prompt.min_words else DEFAULT_MIN_WORDS),
            max_words=(prompt.max_words if prompt and prompt.max_words else DEFAULT_MAX_WORDS),
        )

    def reference_lines(self) -> list[dict[str, Any]]:
        return [
            {
                "image": i,
                "tag": image_tag(i),
                "kind": slot.kind,
                "name": slot.name,
                "role": reference_role(self.reference_settings, slot, i),
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
                "camera": self.camera,
                "action": self.action,
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
            "style_lead": self.style_lead,
            "style": self.style,
        }

    def key(self) -> str:
        """Empreinte des données de la case (bible et savoir-faire exclus : ils varient avec la base de
        connaissances) et de la version des consignes (`WRITER_REVISION`) : le prompt rédigé n'est redemandé
        que si elle change."""
        raw = json.dumps({**self.as_json(), "revision": WRITER_REVISION}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


def reference_role(refs: ReferencePromptSettings, slot: ReferenceSlot, number: int) -> str:
    """Rôle d'une image pour le rédacteur (« the identity reference for Aiko: keep… ») : la ligne de
    `references` d'image_prompt.yaml, sans « <imageN> is » en tête ni point final."""
    line = reference_line(refs, slot, number).strip()
    line = re.sub(rf"^{re.escape(image_tag(number))}\s*(?:is\s+)?", "", line, flags=re.IGNORECASE)
    return line.rstrip(" .")


# --- messages -----------------------------------------------------------------------
def _or(value: str, empty: str) -> str:
    return value or empty


def render_messages(prompt: PromptPreset, brief: PromptBrief) -> list[ChatMessage]:
    values = template_values(brief)
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


def template_values(brief: PromptBrief) -> dict[str, str]:
    """Variables des gabarits du rédacteur ($plan, $characters, $references…), aussi lues par le dialogue."""
    chars = [f"- {c.name}: {_details(c) or '(no description)'}" for c in brief.characters]
    chars += [
        f"- {e} (extra, no character sheet: drawn in the same manga style as the rest of the panel)"
        for e in brief.extras
    ]
    refs = [f"- {r['tag']} is {r['role']}." for r in brief.reference_lines()]
    lib = ", ".join(f"{o.name} ({_details(o)})" if _details(o) else o.name for o in brief.objects)
    return {
        "language": brief.language,
        "language_name": LANGUAGE_NAMES.get(brief.language, brief.language),
        "min_words": str(brief.min_words),
        "max_words": str(brief.max_words),
        "plan": _or(brief.plan, "(free)"),
        "angle": _or(brief.angle, "(free)"),
        "camera": _or(brief.camera, "(free: pick a dynamic angle that serves the action)"),
        "action": _or(brief.action, "(none given: invent a clear body movement that fits the description)"),
        "ambiance": _or(brief.ambiance, "(free)"),
        "description": _or(brief.description, "(none)"),
        "setting": _or(brief.setting, "(not specified)"),
        "staging": _or(brief.staging, "(not specified)"),
        "characters": "\n".join(chars) or "(no character: the panel shows a place or an object)",
        "character_names": ", ".join(c.name for c in brief.characters) or "(none)",
        "absent_characters": ", ".join(brief.absent) or "(none)",
        "decor": (f"{brief.decor.name} ({_details(brief.decor)})" if brief.decor and _details(brief.decor) else "")
        or (brief.decor.name if brief.decor else "(none)"),
        "objects": lib or "(none)",
        "references": "\n".join(refs) or "(no reference image)",
        "image_tags": ", ".join(r["tag"] for r in brief.reference_lines()) or "(none)",
        "style": _or(brief.style, "(none)"),
        "style_lead": _or(brief.style_lead, "(none)"),
        "bible": _or(brief.bible, "(nothing specific)"),
        "savoir_faire": _or(brief.savoir_faire, "(none)"),
        "palette_rule": brief.palette_rule,
        "context_json": json.dumps(brief.as_json(), ensure_ascii=False, indent=2),
    }


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


def french_hits(text: str) -> int:
    """Mots-outils français du texte (« le », « dans », « avec »…) : un paragraphe non traduit."""
    return sum(1 for w in re.findall(r"[^\W\d_]+", text.lower().replace("’", "'")) if w in _FRENCH_WORDS)


def reference_problems(paragraph: str, count: int) -> list[str]:
    """Chaque image envoyée citée par `<imageN>`, et aucune autre."""
    cited = image_tags(paragraph)
    missing = [image_tag(i) for i in range(1, count + 1) if i not in cited]
    extra = [image_tag(i) for i in cited if i < 1 or i > count]
    problems = []
    if missing:
        problems.append(
            f"images de référence non citées (définis leur rôle en tête du paragraphe) : {', '.join(missing)}"
        )
    if extra:
        sent = ", ".join(image_tag(i) for i in range(1, count + 1)) or "aucune"
        problems.append(f"images citées qui ne sont pas envoyées : {', '.join(extra)} (envoyées : {sent})")
    return problems


def clean_paragraph(text: str) -> str:
    """Un seul paragraphe, sans réplique ni guillemet."""
    return _SPACES.sub(" ", strip_quoted(text)).strip()


def _without(text: str, *fragments: str) -> str:
    """`text` sans les `fragments` (sans casse) : le style et la phrase de style ne sont pas du LLM."""
    for frag in fragments:
        frag = frag.strip().rstrip(".")
        if frag:
            text = re.sub(re.escape(frag), " ", text, flags=re.IGNORECASE)
    return text


def photo_problems(paragraph: str, brief: PromptBrief) -> list[str]:
    """Termes photographiques du paragraphe (mots entiers, sans casse), hors style de la série."""
    text = _without(paragraph, brief.style, brief.style_lead)
    found = [
        t
        for t in dict.fromkeys(t.strip() for t in brief.photo_terms if t.strip())
        if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", text, flags=re.IGNORECASE)
    ]
    if not found:
        return []
    return [
        f"vocabulaire photographique interdit : {', '.join(found)} (c'est une case de manga dessinée, pas une "
        "photo : parle de raccourcis, lignes de fuite, traits de vitesse, épaisseur d'encre, trames, blancs)"
    ]


def colour_problems(paragraph: str, brief: PromptBrief) -> list[str]:
    """Série en noir et blanc : termes de couleur du paragraphe (mots entiers, sans casse), hors style de la
    série et noms des fiches de la case."""
    if not brief.colour_terms:
        return []
    text = _without(paragraph, brief.style, brief.style_lead)
    names = [e.name for e in [*brief.characters, *brief.objects, *([brief.decor] if brief.decor else [])]]
    text = _without(text, *names, *brief.extras)
    found = found_terms(text, brief.colour_terms)
    if not found:
        return []
    return [
        f"mots de couleur interdits : {', '.join(found)} (la série est en noir et blanc : décris les valeurs en "
        "encre, noirs, blancs et trames grises, jamais en couleurs)"
    ]


def with_lead(text: str, lead: str) -> str:
    """La phrase de style de la série en tête du paragraphe : déplacée en tête si elle est ailleurs,
    ajoutée sinon."""
    lead = lead.strip()
    if not lead:
        return text
    if name_key(text).startswith(name_key(lead.rstrip("."))):
        return text
    body = _SPACES.sub(" ", _without(text, lead)).strip()
    body = re.sub(r"^[\s.,;]+", "", body)
    sentence = lead if lead[-1] in ".!?…" else f"{lead}."
    return f"{sentence} {body}".strip()


def with_style(text: str, style: str) -> str:
    """Les mots-clés de style, dans leur langue mesurée : ajoutés tels quels s'ils manquent."""
    if not style or name_key(style) in name_key(text):
        return text
    body = text.rstrip()
    if body and body[-1] not in ".!?…":
        body += "."
    return f"{body} {style}."


def finish_paragraph(paragraph: str, brief: PromptBrief) -> str:
    """Paragraphe validé → prompt stocké : phrase de style en tête, mots-clés de style à la fin."""
    return with_lead(with_style(paragraph, brief.style), brief.style_lead)


def load_json_object(text: str, root_hint: str) -> dict[str, Any]:
    """Objet JSON d'une réponse du LLM (bloc de code toléré) ; `PromptValidationError` lisible sinon."""
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PromptValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise PromptValidationError(f"la racine doit être un objet JSON avec {root_hint}")
    return data


def paragraph_problems(paragraph: str, language: str, brief: PromptBrief) -> list[str]:
    """Écarts d'un paragraphe (déjà nettoyé) avec la case : langue, images citées, personnages, longueur."""
    problems: list[str] = []
    if language != brief.language:
        problems.append(
            f"language : « {language} » au lieu de « {brief.language} » (écris le paragraphe en {LANGUAGE_LABELS.get(brief.language, brief.language)})"
        )
    problems += reference_problems(paragraph, len(brief.references))
    problems += photo_problems(paragraph, brief)
    problems += colour_problems(paragraph, brief)
    if brief.language == "en":
        hits = french_hits(paragraph)
        if hits >= FRENCH_MIN_HITS and hits > FRENCH_MAX_SHARE * word_count(paragraph):
            problems.append(f"paragraphe pas en anglais ({hits} mots français) : traduis tout en anglais")
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
    return problems


def parse_written(text: str, brief: PromptBrief) -> WrittenPrompt:
    """Valide la réponse brute du LLM (schéma, puis cohérence avec la case) ; paragraphe nettoyé."""
    data = load_json_object(text, "« prompt »")
    try:
        out = WrittenPrompt.model_validate(data)
    except ValidationError as exc:
        raise PromptValidationError(format_errors(exc)) from None
    paragraph = clean_paragraph(out.prompt)
    problems = paragraph_problems(paragraph, out.language, brief)
    if problems:
        raise PromptValidationError(" ; ".join(problems))
    return out.model_copy(update={"prompt": finish_paragraph(paragraph, brief)})


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
