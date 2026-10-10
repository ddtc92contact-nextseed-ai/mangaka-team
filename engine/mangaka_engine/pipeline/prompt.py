"""Étape 3 — prompt final d'une case (fonctions pures, sans base ni réseau).

description + type de plan (+ plan, angle et ambiance de la direction artistique) + fiches des personnages (description visuelle, mots-clés)
+ fiches du décor et des objets de la bibliothèque de la série (même forme que les personnages)
+ style de la série (+ notes de la bible sur les personnages et passages du savoir-faire) → prompt positif ; le prompt négatif contient toujours les termes qui
interdisent au modèle de dessiner du texte (bulles et lettrage sont vectoriels).
Le gabarit vit dans `presets/image_prompt.yaml`.
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


def build_prompt(
    *,
    description: str,
    shot_type: str | None = None,
    plan: str | None = None,
    angle: str | None = None,
    ambiance: str | None = None,
    characters: Sequence[PromptCharacter] = (),
    decor: PromptEntry | None = None,
    objects: Sequence[PromptEntry] = (),
    style: str = "",
    savoir_faire: str = "",
    bible: str = "",
    settings: ImagePromptSettings | None = None,
) -> str:
    """Assemble le prompt positif d'une case à partir des morceaux du preset.

    `plan`, `angle`, `ambiance` : direction artistique appliquée à la case ; `$plan` vaut le type de
    plan du scénario quand la direction artistique n'en donne pas. `decor`, `objects` : fiches de la
    bibliothèque (`$decor`, `$objects`), décrites comme les personnages.
    """
    settings = settings or ImagePromptSettings()
    desc, savoir_faire, bible = description or "", savoir_faire or "", bible or ""
    ambiance = ambiance or ""
    if settings.strip_quotes:
        # Notes de la bible et savoir-faire aussi : le texte n'est jamais dessiné par le modèle.
        desc, savoir_faire, bible = strip_quoted(desc), strip_quoted(savoir_faire), strip_quoted(bible)
        ambiance = strip_quoted(ambiance)
    shot = _clean(shot_type)
    chosen = _clean(plan) or shot
    values = {
        "shot": shot[:1].upper() + shot[1:] if shot else "",
        "plan": chosen[:1].upper() + chosen[1:] if chosen else "",
        "angle": _clean(angle),
        "ambiance": _clean(ambiance),
        "description": _clean(desc),
        "characters": settings.character_separator.join(
            d for d in (describe_character(c, settings) for c in characters) if d
        ),
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


def build_negative_prompt(base: str, settings: ImagePromptSettings | None = None) -> str:
    """Ajoute au prompt négatif les termes « pas de texte » qui n'y sont pas déjà."""
    settings = settings or ImagePromptSettings()
    terms = [t.strip() for t in (base or "").split(",") if t.strip()]
    present = {t.casefold() for t in terms}
    for term in settings.forbidden_text_terms:
        if term.casefold() not in present:
            terms.append(term)
            present.add(term.casefold())
    return ", ".join(terms)
