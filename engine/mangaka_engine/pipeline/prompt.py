"""Étape 3 — prompt final d'une case (fonctions pures, sans base ni réseau).

description + type de plan (+ plan, angle et ambiance de la direction artistique) + lieu et mise en scène
donnés par le scénario + nombre et fiches des personnages (description visuelle, mots-clés)
+ fiches du décor et des objets de la bibliothèque de la série (même forme que les personnages)
+ style de la série (+ notes de la bible sur les personnages et passages du savoir-faire) → prompt positif ; le prompt négatif contient toujours les termes qui
interdisent au modèle de dessiner du texte (bulles et lettrage sont vectoriels).
Le gabarit vit dans `presets/image_prompt.yaml`.

`frame_references` ajoute au prompt envoyé à un workflow avec références le cadrage des images (« <image1>
is the identity reference for Urus… » et la consigne « identité seulement, scène nouvelle ») : il dépend
des emplacements retenus au moment de la génération, il n'est donc pas stocké dans le prompt final de la
case. Le texte côté image est en anglais (la langue de Qwen-Image 2.1) : plans et angles de la direction
artistique sont traduits par `camera_terms` (image_prompt.yaml).
"""

from __future__ import annotations

import re
import string
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..presets import ImagePromptSettings


@dataclass(frozen=True)
class PromptCharacter:
    """Une fiche de la bibliothèque (personnage, décor ou objet) : nom, description, mots-clés."""

    name: str
    visual_description: str = ""
    prompt_keywords: Sequence[str] = field(default_factory=tuple)


PromptEntry = PromptCharacter


# Répliques entre guillemets français, anglais ou droits.
# Le plus intérieur d'abord : « Elle dit « ça cloche ! ». » disparaît en entier.
_QUOTES = re.compile(r"«[^«»]*»|“[^“”]*”|\"[^\"]*\"")
_STRAY_QUOTES = re.compile(r"[«»“”\"]")
_SPACES = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    text = _SPACES.sub(" ", (text or "").strip())
    return text.rstrip(" .;,:")


def strip_quoted(text: str) -> str:
    """Retire les répliques entre guillemets d'une description (« Fuyez ! » cria-t-elle → cria-t-elle)."""
    out, previous = text, None
    while out != previous:
        previous, out = out, _QUOTES.sub(" ", out)
    out = _STRAY_QUOTES.sub(" ", out)  # guillemet orphelin : jamais transmis au modèle d'image
    # Espace laissée par la réplique avant « , » ou « . » ; l'espace française avant « : ; ! ? » reste.
    out = re.sub(r"\s+([,.])", r"\1", out)
    return _SPACES.sub(" ", out).strip(" ,;:")


def describe_character(character: PromptCharacter, settings: ImagePromptSettings) -> str:
    details = [_clean(character.visual_description), *(_clean(k) for k in character.prompt_keywords)]
    details = list(dict.fromkeys(d for d in details if d))
    name = _clean(character.name)
    if not details:
        return name
    return string.Template(settings.character).safe_substitute(name=name, details=", ".join(details))


# Nombre de personnages en toutes lettres, en anglais ($character_count).
_COUNTS = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")


def character_count(n: int) -> str:
    """« One character », « Two characters »… (« 12 characters » au-delà de dix) ; "" pour zéro."""
    if n <= 0:
        return ""
    word = _COUNTS[n] if n < len(_COUNTS) else str(n)
    return f"{word} character{'s' if n > 1 else ''}"


def _term_key(value: str) -> str:
    return " ".join(value.strip().lower().replace("’", "'").replace("_", " ").split())


def camera_term(value: str | None, settings: ImagePromptSettings | None = None) -> str:
    """Plan ou angle (« contre-plongée ») → terme de cadrage anglais (« low-angle shot ») ; inconnu : tel quel."""
    text = _clean(value)
    if not text:
        return ""
    terms = {_term_key(k): v for k, v in (settings or ImagePromptSettings()).camera_terms.items()}
    return terms.get(_term_key(text), text)


def build_prompt(
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
    decor: PromptEntry | None = None,
    objects: Sequence[PromptEntry] = (),
    style: str = "",
    savoir_faire: str = "",
    bible: str = "",
    settings: ImagePromptSettings | None = None,
) -> str:
    """Assemble le prompt positif d'une case à partir des morceaux du preset.

    `plan`, `angle`, `ambiance`, `action` : direction artistique appliquée à la case ; `$plan` vaut le
    type de plan du scénario quand la direction artistique n'en donne pas (plans et angles en anglais,
    `camera_terms`). `decor`, `objects` : fiches de la
    bibliothèque (`$decor`, `$objects`), décrites comme les personnages.
    """
    settings = settings or ImagePromptSettings()
    desc, savoir_faire, bible = description or "", savoir_faire or "", bible or ""
    ambiance, setting, staging = ambiance or "", setting or "", staging or ""
    action = action or ""
    if settings.strip_quotes:
        # Notes de la bible et savoir-faire aussi : le texte n'est jamais dessiné par le modèle.
        desc, savoir_faire, bible = strip_quoted(desc), strip_quoted(savoir_faire), strip_quoted(bible)
        ambiance, setting, staging = strip_quoted(ambiance), strip_quoted(setting), strip_quoted(staging)
        action = strip_quoted(action)
    described = [d for d in (describe_character(c, settings) for c in characters) if d]
    shot = camera_term(shot_type, settings)
    chosen = camera_term(plan, settings) or shot
    values = {
        "shot": shot[:1].upper() + shot[1:] if shot else "",
        "plan": chosen[:1].upper() + chosen[1:] if chosen else "",
        "angle": camera_term(angle, settings),
        "ambiance": _clean(ambiance),
        "action": _clean(action),
        "description": _clean(desc),
        "setting": _clean(setting),
        "staging": _clean(staging),
        "character_count": character_count(len(described)),
        "characters": settings.character_separator.join(described),
        "decor": describe_character(decor, settings) if decor is not None else "",
        "objects": settings.character_separator.join(
            d for d in (describe_character(o, settings) for o in objects) if d
        ),
        "style": _clean(style),
        "savoir_faire": _clean(savoir_faire),
        "bible": _clean(bible),
    }
    parts: list[str] = []
    for part in settings.parts:
        tpl = string.Template(part)
        if any(not values[v] for v in tpl.get_identifiers()):
            continue
        parts.append(tpl.substitute(values).strip())
    return " ".join(p for p in parts if p)


def shot_in(value: str | None, shots: Sequence[str]) -> bool:
    """Le plan `value` (« Gros plan ») est l'un de `shots` (sans casse ni espaces superflus)."""
    key = _term_key(value or "")
    return bool(key) and key in {_term_key(s) for s in shots}


def is_tight_shot(plan: str | None, settings: ImagePromptSettings | None = None) -> bool:
    """Plan plus serré que le plan américain (`tight_shots.shots` d'image_prompt.yaml)."""
    return shot_in(plan, (settings or ImagePromptSettings()).tight_shots.shots)


def build_negative_prompt(base: str, settings: ImagePromptSettings | None = None, plan: str | None = None) -> str:
    """Ajoute au prompt négatif les termes « pas de texte » qui n'y sont pas déjà, et pour un plan serré
    (`plan`, voir `is_tight_shot`) les termes contre le plein pied (`tight_shots.negative`)."""
    settings = settings or ImagePromptSettings()
    terms = [t.strip() for t in (base or "").split(",") if t.strip()]
    present = {t.casefold() for t in terms}
    extra = settings.tight_shots.negative if is_tight_shot(plan, settings) else []
    for term in [*settings.forbidden_text_terms, *extra]:
        if term.casefold() not in present:
            terms.append(term)
            present.add(term.casefold())
    return ", ".join(terms)


@dataclass(frozen=True)
class ReferenceSlot:
    """Une image de référence envoyée au workflow : sorte de fiche (`character`, `decor`, `object`,
    `style`) et nom de la fiche, dans l'ordre des emplacements."""

    kind: str
    name: str


def _join(templates: Sequence[str], values: dict[str, str]) -> str:
    return " ".join(p for p in (string.Template(t).substitute(values).strip() for t in templates) if p)


_IMAGE_TAG = re.compile(r"<image(\d+)>", re.IGNORECASE)


def image_tags(text: str) -> list[int]:
    """Numéros des images citées (`<image1>`, `<image2>`…), dans l'ordre de première apparition."""
    return list(dict.fromkeys(int(n) for n in _IMAGE_TAG.findall(text)))


def defines_references(prompt: str, count: int) -> bool:
    """Le prompt commence par le rôle des images (`<image1>` d'abord) et cite exactement les `count`
    images envoyées, dans l'ordre : c'est le cas d'un prompt rédigé par l'IA."""
    return (
        count > 0 and prompt.lstrip().lower().startswith("<image1>") and image_tags(prompt) == list(range(1, count + 1))
    )


def frame_references(prompt: str, slots: Sequence[ReferenceSlot], settings: ImagePromptSettings | None = None) -> str:
    """Prompt envoyé à un workflow avec références : le rôle de chaque image (« <image1> is the identity
    reference for Urus… ») avant le prompt de la case, la consigne « identité seulement » après.

    Un prompt qui définit déjà le rôle de chaque image envoyée en tête (`defines_references` : prompt
    rédigé par l'IA) ne reçoit que la consigne. Sans image de référence, le prompt est renvoyé tel quel.
    """
    if not slots:
        return prompt
    refs = (settings or ImagePromptSettings()).references
    lines = [
        string.Template(getattr(refs, slot.kind, refs.character)).substitute(slot=str(i), name=_clean(slot.name))
        for i, slot in enumerate(slots, start=1)
    ]
    values = {
        "images": refs.separator.join(line.strip() for line in lines if line.strip()),
        "count": str(len(slots)),
        "sorting": refs.separator.join(sorting_lines(slots, settings)),
    }
    body = _sentence(prompt)
    before = "" if defines_references(body, len(slots)) else _join(refs.before, values)
    return " ".join(p for p in (before, body, _join(refs.after, values)) if p)


def sorting_lines(slots: Sequence[ReferenceSlot], settings: ImagePromptSettings | None = None) -> list[str]:
    """Consigne de tri de chaque image envoyée (« From <image1> take only the face… of Urus; ignore its
    layout… »), dans l'ordre des emplacements, d'après `references.sorting` du preset (sorte inconnue :
    celle des personnages) ; une sorte sans consigne n'en donne aucune."""
    sorting = (settings or ImagePromptSettings()).references.sorting
    lines = (
        string.Template(getattr(sorting, slot.kind, sorting.character)).substitute(slot=str(i), name=_clean(slot.name))
        for i, slot in enumerate(slots, start=1)
    )
    return [line.strip() for line in lines if line.strip()]


def _sentence(text: str) -> str:
    body = text.strip()
    if body and body[-1] not in ".!?…":
        body += "."  # prompt édité à la main sans point final : la consigne suit en phrase distincte
    return body


def append_instruction(prompt: str, instruction: str) -> str:
    """Ajoute une consigne (tonalité du rendu…) en phrase distincte à la fin du prompt ; vide : inchangé."""
    extra = _sentence(instruction)
    if not extra:
        return prompt
    body = _sentence(prompt)
    return f"{body} {extra}" if body else extra


def merge_negative(base: str, extra: str) -> str:
    """Ajoute au prompt négatif les termes de `extra` (séparés par des virgules) qui n'y sont pas déjà."""
    terms = [t.strip() for t in (base or "").split(",") if t.strip()]
    present = {t.casefold() for t in terms}
    for term in (t.strip() for t in (extra or "").split(",")):
        if term and term.casefold() not in present:
            terms.append(term)
            present.add(term.casefold())
    return ", ".join(terms)
