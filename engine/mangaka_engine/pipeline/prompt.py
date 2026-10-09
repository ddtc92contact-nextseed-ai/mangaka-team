"""Étape 3 — prompt final d'une case (fonctions pures, sans base ni réseau).

description + type de plan + fiches des personnages (description visuelle, mots-clés)
+ style de la série → prompt positif ; le prompt négatif contient toujours les termes qui
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
    name: str
    visual_description: str = ""
    prompt_keywords: Sequence[str] = field(default_factory=tuple)


# Répliques entre guillemets français, anglais ou droits.
_QUOTES = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"")
_SPACES = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    text = _SPACES.sub(" ", (text or "").strip())
    return text.rstrip(" .;,:")


def strip_quoted(text: str) -> str:
    """Retire les répliques entre guillemets d'une description (« Fuyez ! » cria-t-elle → cria-t-elle)."""
    out = _QUOTES.sub(" ", text)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
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
    characters: Sequence[PromptCharacter] = (),
    style: str = "",
    settings: ImagePromptSettings | None = None,
) -> str:
    """Assemble le prompt positif d'une case à partir des morceaux du preset."""
    settings = settings or ImagePromptSettings()
    desc = description or ""
    if settings.strip_quotes:
        desc = strip_quoted(desc)
    shot = _clean(shot_type)
    values = {
        "shot": shot[:1].upper() + shot[1:] if shot else "",
        "description": _clean(desc),
        "characters": settings.character_separator.join(
            d for d in (describe_character(c, settings) for c in characters) if d
        ),
        "style": _clean(style),
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
