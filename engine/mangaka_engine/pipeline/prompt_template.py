"""Étape 3 — prompt image « gabarit » (#228) : prompt court assemblé par le moteur.

Le mode « détaillé » (fragments de `prompt.build_prompt` ou paragraphe du rédacteur, `prompt_writer.py`) alourdit le
prompt à chaque correctif : une ligne de rôle, une ligne de tri et un long paragraphe par fiche, le décor détaillé
dans chaque case (recopié dans les plans serrés), 180 à 320 mots. Le mode « gabarit », choisi par série
(`Project.image_prompt_mode`, défaut `image_prompt_mode` de defaults.yaml), fait l'inverse, dans cet ordre (textes
fixes : `template` d'image_prompt.yaml) :

1. une ligne par image envoyée (« <image1> is the model sheet of Aiko. », un objet nommé et décrit en quelques
   mots) — ajoutées à l'envoi (`frame_template`), elles dépendent des emplacements retenus ;
2. UNE consigne de tri commune, dès qu'une fiche de personnage est envoyée ;
3. l'ancre visuelle de chaque personnage PRÉSENT (`Character.visual_anchor`, sinon résumé de sa description) ;
4. les règles, une fois : casting fermé de la case (« no people » sans personnage), pas de texte ;
5. le décor en une phrase (nom du lieu et ses éléments principaux) ; le décor détaillé seulement en plan large ;
6. le style en une phrase (phrase de style et finition de la série) ;
7. la case : terme de plan (`camera_terms`), puis 1 à 3 phrases d'action écrites par le LLM (`write_action`,
   presets/prompts/redacteur-image-gabarit.yaml), validées — mots photo, mots de couleur d'une série en noir et
   blanc, personnage absent nommé : une relance au plus, sinon la description de la case.

Blocs 3 à 7 : prompt final stocké sur la case (`template_body`, éditable comme les autres) ; blocs 1 et 2 : à
l'envoi (`frame_template`). Ni consigne de tri par fiche, ni `references.after`, ni `single_instance`, ni savoir-faire
ni bible. Le prompt négatif, les termes « pas de texte » et le retrait des mots de couleur restent ceux du mode
détaillé (`generation.py`).

Fonctions pures (aucune base) : le rassemblement des données d'une case vit dans `generation.py`.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError, field_validator

from ..presets import ImagePromptSettings, PromptPreset
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..validation import format_errors
from .names import _contains, name_key
from .prompt import ReferenceSlot, camera_term, found_terms, image_tags, remove_terms, role_tags, shot_in, strip_quoted
from .prompt_writer import (
    FRENCH_MAX_SHARE,
    FRENCH_MIN_HITS,
    PromptValidationError,
    clean_written,
    french_hits,
    image_tag,
    load_json_object,
    word_count,
)
from .script import _render

MODE_DETAILED = "détaillé"
MODE_TEMPLATE = "gabarit"
MODES = (MODE_DETAILED, MODE_TEMPLATE)
MODE_LABELS = {MODE_DETAILED: "détaillé", MODE_TEMPLATE: "gabarit"}

PROMPT_ID = "redacteur-image-gabarit"  # presets/prompts/redacteur-image-gabarit.yaml
ANCHOR_PROMPT_ID = "ancre-visuelle"  # presets/prompts/ancre-visuelle.yaml
TASK = "image_prompt_template"  # `task` du bloc <contexte> (reconnu par le LLM factice)
ANCHOR_TASK = "visual_anchor"
# Version du gabarit, comprise dans l'empreinte d'une case (`TemplateBrief.key`) : la changer remet à rédiger les
# phrases d'action de chaque case en mode gabarit (jamais un prompt édité à la main).
TEMPLATE_REVISION = 1
DEFAULT_ANCHOR_MAX_WORDS = 25

_SPACES = re.compile(r"\s+")
_CHUNKS = re.compile(r"\s*[,;.\n]\s*")


class TemplateWriterError(Exception):
    """Phrases d'action impossibles à rédiger (message lisible, en français)."""


class AnchorError(Exception):
    """Ancre visuelle impossible à proposer (message lisible, en français)."""


# --- textes courts ------------------------------------------------------------------
def _text(value: str | None) -> str:
    """Texte d'une donnée de la case : sans réplique entre guillemets, espaces simples, sans ponctuation finale."""
    return _SPACES.sub(" ", strip_quoted(value or "")).strip().rstrip(" .;,:")


def summarize(text: str | None, words: int) -> str:
    """Résumé d'une description (ancre vide, description courte d'un objet) : son début, en `words` mots au plus,
    coupé à la dernière virgule quand elle garde au moins la moitié ; les phrases deviennent des propositions
    (« Grand gorille. Jean délavé » → « Grand gorille, jean délavé »)."""
    clean = _text(text)
    if not clean:
        return ""
    clean = re.sub(r"\s*[.;!?…]+\s+(\S)", lambda m: ", " + m.group(1).lower(), clean)
    tokens = clean.split()
    if len(tokens) <= words:
        return clean.rstrip(" ,;:")
    cut = " ".join(tokens[:words])
    comma = cut.rfind(",")
    if comma >= len(cut) // 2:
        cut = cut[:comma]
    return cut.rstrip(" ,;:")


def elements(text: str | None, count: int, max_words: int = 5) -> list[str]:
    """Éléments principaux d'un décor : les `count` premiers morceaux de sa description (coupée aux virgules et aux
    points), chacun en `max_words` mots au plus."""
    out: list[str] = []
    for chunk in _CHUNKS.split(_text(text)):
        words = chunk.split()
        if not words:
            continue
        out.append(" ".join(words[:max_words]))
        if len(out) == count:
            break
    return out


def _sentence(text: str) -> str:
    body = _SPACES.sub(" ", text or "").strip()
    if body and body[-1] not in ".!?…":
        body += "."
    return body


def _substitute(parts: Sequence[str], values: dict[str, str]) -> str:
    """Morceaux joints par une espace ; un morceau dont une variable est vide est omis."""
    out: list[str] = []
    for part in parts:
        tpl = string.Template(part)
        if any(not values.get(v) for v in tpl.get_identifiers()):
            continue
        text = tpl.substitute(values).strip()
        if text:
            out.append(text)
    return " ".join(out)


# --- données de la case -------------------------------------------------------------
@dataclass(frozen=True)
class TemplateEntry:
    """Personnage présent (ancre visuelle déjà résolue : celle de la fiche, sinon le résumé de sa description)."""

    name: str
    anchor: str = ""


@dataclass(frozen=True)
class TemplateSource:
    """Fiche d'un personnage présent telle que la donne la bibliothèque : ancre (peut être vide), description visuelle
    (résumée si l'ancre est vide) et mots déclencheurs de son LoRA (toujours ajoutés à l'ancre)."""

    name: str
    anchor: str = ""
    description: str = ""
    triggers: Sequence[str] = ()


@dataclass
class TemplateBrief:
    """Ce que le gabarit sait d'une case (déjà débarrassé des répliques et, en noir et blanc, des mots de couleur)."""

    characters: list[TemplateEntry] = field(default_factory=list)
    # Noms écrits par le scénario sans fiche (figurants) : dans le casting, sans ancre.
    extras: list[str] = field(default_factory=list)
    # Personnages de la série absents de la case, et ceux qu'elle cite hors cadre : jamais nommés.
    absent: list[str] = field(default_factory=list)
    references: list[ReferenceSlot] = field(default_factory=list)
    plan: str = ""
    angle: str = ""
    # Plan et angle en termes de cadrage anglais (`camera_terms`).
    camera: str = ""
    description: str = ""
    staging: str = ""
    action: str = ""
    setting: str = ""
    # Décor court : nom du lieu et ses éléments principaux ; décor détaillé (plan large seulement).
    place: str = ""
    elements: list[str] = field(default_factory=list)
    details: str = ""
    wide: bool = False
    style_lead: str = ""
    finition: str = ""
    triggers: str = ""
    photo_terms: list[str] = field(default_factory=list)
    colour_terms: list[str] = field(default_factory=list)
    palette_rule: str = ""
    # Noms des fiches de la case : un mot de couleur contenu dans un nom reste (« Violet »).
    keep: list[str] = field(default_factory=list)
    action_max_words: int = 60
    setting_max_words: int = 25

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
        action: str | None = None,
        characters: Sequence[TemplateSource] = (),
        extras: Sequence[str] = (),
        absent: Sequence[str] = (),
        offscreen: Sequence[str] = (),
        place: str = "",
        place_description: str = "",
        decor_description: str = "",
        references: Sequence[ReferenceSlot] = (),
        style_lead: str = "",
        finition: str = "",
        triggers: Sequence[str] = (),
        keep: Sequence[str] = (),
        settings: ImagePromptSettings | None = None,
        monochrome: bool = False,
    ) -> TemplateBrief:
        """`characters` : fiches des présents, dans l'ordre de la case ;
        `place` : nom du lieu (lieu de la série, sinon décor de la bibliothèque) ; `place_description`,
        `decor_description` : descriptions du lieu et du décor (éléments principaux, décor détaillé)."""
        settings = settings or ImagePromptSettings()
        t = settings.template
        colour_terms = list(settings.monochrome_forbidden_terms) if monochrome else []
        names = [c.name for c in characters]
        kept = list(dict.fromkeys([*names, *extras, *keep]))

        def plain(value: str | None) -> str:
            text = _text(value)
            return _text(remove_terms(text, colour_terms, keep=kept)) if colour_terms and text else text

        present = {name_key(n) for n in names}
        drawn = [name_key(n).split() for n in [*names, *extras]]
        hidden = [n for n in offscreen if not any(_contains(d, name_key(n).split()) for d in drawn)]
        chosen = _text(plan) or _text(shot_type)
        camera = [camera_term(v, settings) for v in (chosen, _text(angle)) if v]
        source = decor_description or place_description
        if source:
            place_name = _text(place)
            found = elements(plain(source), t.setting_elements)
        elif _text(place):
            place_name = _text(place)
            found = elements(plain(setting), t.setting_elements)
        else:
            # Sans lieu ni décor : le lieu écrit par le scénario (son 1er morceau), puis ses autres morceaux.
            chunks = elements(plain(setting), t.setting_elements + 1, 12)
            place_name, found = (chunks[0], chunks[1:]) if chunks else ("", [])
        details = "; ".join(
            dict.fromkeys(p for p in (plain(decor_description), plain(place_description), plain(setting)) if p)
        )
        return cls(
            characters=[
                TemplateEntry(
                    _text(c.name),
                    ", ".join(
                        p
                        for p in (
                            plain(c.anchor) or summarize(plain(c.description), t.anchor_words),
                            *dict.fromkeys(w for w in (_text(x) for x in c.triggers) if w),
                        )
                        if p
                    ),
                )
                for c in characters
            ],
            extras=list(dict.fromkeys(n for n in (_text(e) for e in extras) if n)),
            absent=list(dict.fromkeys(n for n in [*absent, *hidden] if n.strip() and name_key(n) not in present)),
            references=list(references),
            plan=chosen,
            angle=_text(angle),
            camera=", ".join(dict.fromkeys(camera)),
            description=plain(description),
            staging=plain(staging),
            action=plain(action),
            setting=plain(setting),
            place=plain(place_name),
            elements=found,
            details=details,
            wide=shot_in(chosen, t.wide_shots),
            style_lead=_SPACES.sub(" ", style_lead or "").strip(),
            finition=_text(finition),
            triggers=", ".join(dict.fromkeys(w for w in (_text(x) for x in triggers) if w)),
            photo_terms=list(settings.forbidden_photo_terms),
            colour_terms=colour_terms,
            palette_rule=settings.monochrome_writer_rule.strip() if monochrome else "",
            keep=kept,
            action_max_words=t.action_max_words,
            setting_max_words=t.setting_max_words,
        )

    @property
    def cast(self) -> list[str]:
        """Noms des personnages dessinés : fiches présentes, puis figurants."""
        return list(dict.fromkeys([*(c.name for c in self.characters), *self.extras]))

    def short_setting(self) -> str:
        """Décor court du moteur : « nom du lieu, élément, élément… » (repli du décor rédigé par le LLM)."""
        return ", ".join(p for p in (self.place, *self.elements) if p)

    def fallback_action(self) -> str:
        """Repli des phrases d'action : la description de la case (sinon sa mise en scène)."""
        return self.description or self.staging

    def tags(self) -> dict[str, str]:
        """Balise de la fiche envoyée de chaque personnage présent (« Aiko » → « <image1> »)."""
        out: dict[str, str] = {}
        for i, slot in enumerate(self.references, start=1):
            if slot.kind == "character":
                out.setdefault(name_key(slot.name), image_tag(i))
        return out

    def as_json(self) -> dict[str, Any]:
        tags = self.tags()
        return {
            "task": TASK,
            "language": "en",
            "max_words": self.action_max_words,
            "setting_max_words": self.setting_max_words,
            "panel": {
                "plan": self.plan,
                "angle": self.angle,
                "camera": self.camera,
                "action": self.action,
                "description": self.description,
                "staging": self.staging,
                "setting": self.setting,
            },
            "characters": [
                {"name": c.name, **({"tag": tags[name_key(c.name)]} if name_key(c.name) in tags else {})}
                for c in self.characters
            ],
            "extras": self.extras,
            "absent_characters": self.absent,
            "place": self.place,
            "elements": self.elements,
            "references": [
                {"tag": image_tag(i), "kind": s.kind, "name": s.name} for i, s in enumerate(self.references, 1)
            ],
            **({"monochrome": True} if self.colour_terms else {}),
        }

    def key(self) -> str:
        """Empreinte de tout ce qui fait le prompt stocké (données de la case, ancres, décor, style) et de la version
        du gabarit : les phrases d'action ne sont redemandées que si elle change."""
        raw = json.dumps(
            {
                **self.as_json(),
                "anchors": [c.anchor for c in self.characters],
                "details": self.details,
                "wide": self.wide,
                "style": [self.style_lead, self.finition, self.triggers],
                "revision": TEMPLATE_REVISION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


# --- assemblage ---------------------------------------------------------------------
def template_body(
    brief: TemplateBrief,
    settings: ImagePromptSettings | None = None,
    *,
    action: str | None = None,
    setting: str | None = None,
) -> str:
    """Prompt stocké d'une case en mode gabarit (blocs 3 à 7) : ancres des présents, règles, décor, style, case.
    `action`, `setting` : phrases d'action et décor court rédigés par le LLM ; absents, la description de la case
    et le décor court du moteur."""
    t = (settings or ImagePromptSettings()).template
    blocks: list[str] = []
    for c in brief.characters:
        if c.anchor:
            blocks.append(string.Template(t.anchor).substitute(name=c.name, anchor=c.anchor.rstrip(" .;,")))
    names = brief.cast
    blocks.append(string.Template(t.cast).substitute(names=", ".join(names)) if names else t.empty)
    blocks.append(t.no_text)
    short = _text(setting) or brief.short_setting()
    if short:
        blocks.append(string.Template(t.setting).substitute(setting=short))
    if brief.wide and brief.details:
        blocks.append(string.Template(t.details).substitute(details=brief.details))
    blocks.append(
        _substitute(t.style, {"style_lead": brief.style_lead, "finition": brief.finition, "triggers": brief.triggers})
    )
    camera = brief.camera[:1].upper() + brief.camera[1:]
    text = _sentence(_SPACES.sub(" ", action or "").strip() or brief.fallback_action())
    blocks.append(_substitute(t.panel, {"camera": camera, "action": text if text != "." else ""}))
    out = " ".join(b.strip() for b in blocks if b and b.strip())
    if brief.colour_terms:
        out = remove_terms(out, brief.colour_terms, keep=brief.keep)
    return _SPACES.sub(" ", out).strip()


def frame_template(
    prompt: str,
    slots: Sequence[ReferenceSlot],
    settings: ImagePromptSettings | None = None,
    *,
    descriptions: dict[str, str] | None = None,
) -> str:
    """Prompt envoyé en mode gabarit : une ligne par image envoyée (blocs 1), la consigne de tri commune (bloc 2) dès
    qu'une fiche de personnage est envoyée, puis le prompt stocké. Une image dont le prompt donne déjà la ligne
    (prompt édité à la main) n'en reçoit pas une seconde ; sans image, le prompt est renvoyé tel quel.
    `descriptions` : description courte de chaque fiche par nom (objets, véhicules, créatures)."""
    if not slots:
        return prompt
    t = (settings or ImagePromptSettings()).template
    given = role_tags(prompt)
    lines: list[str] = []
    for i, slot in enumerate(slots, start=1):
        if i in given:
            continue
        description = _text((descriptions or {}).get(slot.name, ""))
        line = getattr(t.references, slot.kind, t.references.character)
        if "$description" in line and not description:
            line = t.references.bare
        lines.append(string.Template(line).substitute(slot=str(i), name=_text(slot.name), description=description))
    sorting = t.sorting.strip()
    if not any(s.kind == "character" for s in slots) or sorting.casefold() in prompt.casefold():
        sorting = ""
    return " ".join(p for p in (*lines, sorting, prompt.strip()) if p)


# --- phrases d'action par le LLM ----------------------------------------------------
def template_values(brief: TemplateBrief) -> dict[str, str]:
    tags = brief.tags()
    chars = [
        f"{c.name} ({tags[name_key(c.name)]})" if name_key(c.name) in tags else c.name for c in brief.characters
    ] + [f"{e} (extra)" for e in brief.extras]
    return {
        "max_words": str(brief.action_max_words),
        "setting_max_words": str(brief.setting_max_words),
        "plan": brief.plan or "(free)",
        "angle": brief.angle or "(free)",
        "camera": brief.camera or "(free)",
        "action": brief.action or "(none given)",
        "description": brief.description or "(none)",
        "staging": brief.staging or "(not specified)",
        "setting": brief.setting or "(not specified)",
        "place": brief.short_setting() or "(none)",
        "characters": ", ".join(chars) or "(nobody: the panel shows only the place)",
        "absent_characters": ", ".join(brief.absent) or "(none)",
        "palette_rule": brief.palette_rule,
        "context_json": json.dumps(brief.as_json(), ensure_ascii=False, indent=2),
    }


def render_messages(prompt: PromptPreset, brief: TemplateBrief) -> list[ChatMessage]:
    values = template_values(brief)
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


class WrittenAction(BaseModel):
    """Réponse du rédacteur du gabarit."""

    model_config = ConfigDict(extra="ignore")

    action: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    setting: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    language: Literal["en"] = "en"

    @field_validator("language", mode="before")
    @classmethod
    def _lang(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("setting", mode="before")
    @classmethod
    def _empty_setting(cls, v: Any) -> Any:
        return None if v is None or (isinstance(v, str) and not v.strip()) else v


def _mentions(text: str, name: str) -> bool:
    return _contains(name_key(text).split(), name_key(name).split())


def _banned(text: str, brief: TemplateBrief) -> list[str]:
    problems: list[str] = []
    photo = found_terms(text, brief.photo_terms)
    if photo:
        problems.append(f"vocabulaire photographique interdit : {', '.join(photo)} (c'est une case de manga dessinée)")
    if brief.colour_terms:
        kept = text
        for name in brief.keep:
            kept = re.sub(re.escape(name), " ", kept, flags=re.IGNORECASE)
        colours = found_terms(kept, brief.colour_terms)
        if colours:
            problems.append(f"mots de couleur interdits : {', '.join(colours)} (la série est en noir et blanc)")
    return problems


def action_problems(action: str, setting: str, brief: TemplateBrief) -> list[str]:
    """Écarts des phrases d'action (et du décor court) avec la case : longueur, mots photo et de couleur, noms
    d'absents, images citées qui ne sont pas envoyées, phrases françaises."""
    problems: list[str] = []
    words = word_count(action)
    if words > brief.action_max_words:
        problems.append(f"action trop longue ({words} mots ; {brief.action_max_words} au plus)")
    if setting and word_count(setting) > brief.setting_max_words:
        problems.append(f"décor trop long ({word_count(setting)} mots ; {brief.setting_max_words} au plus)")
    both = f"{action} {setting}".strip()
    problems += _banned(both, brief)
    intruders = [n for n in brief.absent if _mentions(both, n)]
    if intruders:
        problems.append(f"personnages absents de la case nommés (à retirer) : {', '.join(intruders)}")
    count = len(brief.references)
    extra = [image_tag(i) for i in image_tags(both) if i < 1 or i > count]
    if extra:
        problems.append(f"images citées qui ne sont pas envoyées : {', '.join(extra)}")
    # Phrases d'action seulement : un nom de lieu peut rester en français (le repli du moteur l'est aussi).
    hits = french_hits(action)
    if hits >= FRENCH_MIN_HITS and hits > FRENCH_MAX_SHARE * word_count(action):
        problems.append(f"pas en anglais ({hits} mots français) : traduis tout en anglais")
    return problems


def parse_action(text: str, brief: TemplateBrief) -> WrittenAction:
    """Valide la réponse brute du LLM (schéma, puis cohérence avec la case) ; texte nettoyé."""
    data = load_json_object(text, "« action »")
    try:
        out = WrittenAction.model_validate(data)
    except ValidationError as exc:
        raise PromptValidationError(format_errors(exc)) from None
    action = clean_written(out.action, len(brief.references))
    setting = _text(clean_written(out.setting or "", len(brief.references)))
    problems = action_problems(action, setting, brief)
    if problems:
        raise PromptValidationError(" ; ".join(problems))
    return out.model_copy(update={"action": action, "setting": setting or None})


@dataclass
class ActionRun:
    output: WrittenAction
    attempts: int


def write_action(
    llm: LLMProvider, prompt: PromptPreset, brief: TemplateBrief, progress: Callable[[str], None] | None = None
) -> ActionRun:
    """Phrases d'action validées, ou `TemplateWriterError` après `1 + max_retries` tentatives (l'appelant retombe
    sur la description de la case)."""
    messages = render_messages(prompt, brief)
    total = 1 + prompt.max_retries
    last_error = ""
    for attempt in range(1, total + 1):
        if progress is not None:
            progress(f"Rédaction de l'action de la case par l'IA (essai {attempt}/{total})…")
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            last_error = str(exc)
            if not exc.retryable or attempt == total:
                raise TemplateWriterError(f"le LLM n'a pas pu répondre : {exc}") from exc
            continue
        try:
            output = parse_action(result.text, brief)
        except PromptValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return ActionRun(output=output, attempts=attempt)
    raise TemplateWriterError(f"réponse invalide {total} fois de suite ({last_error})")


# --- ancre visuelle d'une fiche (bouton « Proposer ») --------------------------------
def anchor_context(name: str, description: str, keywords: Sequence[str], max_words: int) -> dict[str, Any]:
    return {
        "task": ANCHOR_TASK,
        "name": name,
        "description": _text(description),
        "keywords": [k for k in (_text(k) for k in keywords) if k],
        "max_words": max_words,
    }


def anchor_problems(anchor: str, name: str, max_words: int, photo_terms: Sequence[str]) -> list[str]:
    problems: list[str] = []
    if not anchor:
        problems.append("ancre vide")
    elif word_count(anchor) > max_words:
        problems.append(f"ancre trop longue ({word_count(anchor)} mots ; {max_words} au plus, ≈ 15 visés)")
    photo = found_terms(anchor, photo_terms)
    if photo:
        problems.append(f"vocabulaire photographique interdit : {', '.join(photo)}")
    if name and _mentions(anchor, name):
        problems.append(f"l'ancre ne nomme jamais le personnage ({name})")
    return problems


def propose_anchor(
    llm: LLMProvider,
    prompt: PromptPreset,
    *,
    name: str,
    description: str,
    keywords: Sequence[str] = (),
    settings: ImagePromptSettings | None = None,
) -> str:
    """Ancre visuelle proposée par le LLM pour une fiche (rien n'est enregistré) ; `AnchorError` lisible sinon."""
    settings = settings or ImagePromptSettings()
    if not _text(description) and not keywords:
        raise AnchorError("la fiche n'a pas encore de description visuelle : écris-la d'abord")
    max_words = prompt.max_words or DEFAULT_ANCHOR_MAX_WORDS
    ctx = anchor_context(name, description, keywords, max_words)
    values = {
        "name": name,
        "description": ctx["description"] or "(none)",
        "keywords": ", ".join(ctx["keywords"]) or "(none)",
        "max_words": str(max_words),
        "context_json": json.dumps(ctx, ensure_ascii=False, indent=2),
    }
    messages = [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]
    total = 1 + prompt.max_retries
    last_error = ""
    for attempt in range(1, total + 1):
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise AnchorError(f"le LLM n'a pas pu répondre : {exc}") from exc
            last_error = str(exc)
            continue
        try:
            data = load_json_object(result.text, "« anchor »")
            anchor = _text(strip_quoted(str(data.get("anchor") or "")))
            problems = anchor_problems(anchor, name, max_words, settings.forbidden_photo_terms)
            if problems:
                raise PromptValidationError(" ; ".join(problems))
            return anchor
        except PromptValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:5000]), ChatMessage("user", retry)]
    raise AnchorError(f"réponse invalide {total} fois de suite ({last_error})")
