"""Style d'une série : le seul endroit où il se compose.

Le style se choisit dans des listes fermées (presets/style_genres, style_renderings, style_tones,
style_options.yaml). Ce module en tire :

- `$style` des prompts image (cases, fiches de référence, réparation, croquis et passage au propre) :
  mots déclencheurs du LoRA de style (catalogue style_loras.yaml), puis mots-clés du genre, du rendu,
  du ton et des réglages fins, dans cet ordre, sans doublon ;
- le nom des packs et leurs consignes pour les LLM (scénario, direction artistique) ;
- la validation des combinaisons (API) : ids connus, ton autorisé par le genre, trames en N&B seulement.

Une série d'avant les packs (aucun genre choisi) garde son ancien texte libre (`legacy_style`, lecture
seule) à la place du genre, avec le rendu par défaut ; il est ignoré dès qu'un pack est choisi.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..presets import PresetRegistry
from ..store.models import Project

log = logging.getLogger("mangaka_engine")

STYLE_FIELDS = ("style_genre", "style_rendering", "style_tone")


class StyleError(ValueError):
    """Combinaison de style refusée (message lisible, en français) sur un champ de l'API."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _clean(text: str | None) -> str:
    return " ".join((text or "").split()).strip(" .;,:")


def check_style(
    presets: PresetRegistry, genre: str | None, rendering: str | None, tone: str | None, options: Mapping[str, Any]
) -> None:
    """Lève `StyleError` sur la première combinaison interdite. Genre, rendu et ton vont ensemble."""
    chosen = {"style_genre": genre, "style_rendering": rendering, "style_tone": tone}
    if not any(chosen.values()):
        if options:
            raise StyleError("style_options", "choisis d'abord le genre, le rendu et le ton")
        return
    labels = {"style_genre": "le genre", "style_rendering": "le rendu", "style_tone": "le ton"}
    for key, value in chosen.items():
        if not value:
            raise StyleError(key, f"choisis {labels[key]} dans la liste")
    assert genre and rendering and tone
    if genre not in presets.style_genres:
        raise StyleError("style_genre", f"genre inconnu : « {genre} » (presets/style_genres/)")
    if rendering not in presets.style_renderings:
        raise StyleError("style_rendering", f"rendu inconnu : « {rendering} » (presets/style_renderings/)")
    if tone not in presets.style_tones:
        raise StyleError("style_tone", f"ton inconnu : « {tone} » (presets/style_tones/)")
    g = presets.style_genres[genre]
    if g.allowed_tones is not None and tone not in g.allowed_tones:
        allowed = ", ".join(presets.style_tones[t].name for t in g.allowed_tones)
        raise StyleError(
            "style_tone",
            f"le ton « {presets.style_tones[tone].name} » n'est pas proposé pour le genre « {g.name} » "
            f"(possibles : {allowed})",
        )
    r = presets.style_renderings[rendering]
    for key, value in options.items():
        option = presets.style_options.options.get(key)
        if option is None:
            raise StyleError("style_options", f"réglage inconnu : « {key} » (presets/style_options.yaml)")
        if not isinstance(value, str) or value not in option.choices:
            choices = ", ".join(option.choices)
            raise StyleError("style_options", f"{option.name} : valeur inconnue « {value} » (possibles : {choices})")
        if option.monochrome_only and not r.monochrome:
            raise StyleError(
                "style_options",
                f"{option.name} : réservé aux rendus noir et blanc, pas au rendu « {r.name} »",
            )


def lora_triggers(presets: PresetRegistry, series: Project) -> tuple[str, ...]:
    """Mots déclencheurs du LoRA de style : ceux du catalogue (aucun pour un LoRA hors catalogue)."""
    entry = presets.style_loras.get(series.style_lora_name)
    return tuple(w for w in (_clean(t) for t in entry.trigger_words) if w) if entry else ()


def style_keywords(presets: PresetRegistry, series: Project) -> list[str]:
    """Mots-clés du style dans l'ordre fixe : LoRA, genre (ou ancien texte), rendu, ton, réglages fins."""
    words: list[str] = list(lora_triggers(presets, series))
    genre = presets.style_genres.get(series.style_genre or "")
    if genre is not None:
        words += genre.prompt_keywords
    elif not series.style_genre:
        words.append(_clean(series.legacy_style))
    # Pas de rendu choisi (ou disparu des presets) : le rendu par défaut, jamais aucun rendu.
    rendering = presets.style_renderings.get(series.style_rendering or "") or presets.style_renderings.get(
        presets.default_style_rendering or ""
    )
    if rendering is not None:
        words += rendering.prompt_keywords
    tone = presets.style_tones.get(series.style_tone or "")
    if tone is not None:
        words += tone.prompt_keywords
    chosen = series.style_options or {}
    for key, option in presets.style_options.options.items():
        choice = option.choices.get(chosen.get(key) or "")
        if choice is None or (option.monochrome_only and rendering is not None and not rendering.monochrome):
            continue
        words += choice.prompt_keywords
    missing = [
        f"{field} « {value} »"
        for field, value, known in (
            ("genre", series.style_genre, presets.style_genres),
            ("rendu", series.style_rendering, presets.style_renderings),
            ("ton", series.style_tone, presets.style_tones),
        )
        if value and value not in known
    ]
    if missing:
        log.warning("série %s : pack de style introuvable (%s), ignoré", series.id, ", ".join(missing))
    return list(dict.fromkeys(w for w in words if w))


def series_style(presets: PresetRegistry, series: Project) -> str:
    """`$style` des prompts image de la série."""
    return ", ".join(style_keywords(presets, series))


@dataclass(frozen=True)
class StyleBrief:
    """Style de la série pour un LLM : nom des packs et consignes (genre, puis ton)."""

    packs: str
    guidelines: str


NO_GUIDELINES = "(aucune consigne de genre : style de la série à choisir dans les listes)"


def style_brief(presets: PresetRegistry, series: Project) -> StyleBrief:
    genre = presets.style_genres.get(series.style_genre or "")
    rendering = presets.style_renderings.get(series.style_rendering or "")
    tone = presets.style_tones.get(series.style_tone or "")
    if genre is None:
        legacy = _clean(series.legacy_style)
        return StyleBrief(f"{legacy} (ancien style libre)" if legacy else "(non précisé)", NO_GUIDELINES)
    lines = [f"Genre : {genre.name} — {genre.description}"]
    if rendering is not None:
        lines.append(f"Rendu : {rendering.name} — {rendering.description}")
    if tone is not None:
        lines.append(f"Ton : {tone.name} — {tone.description}")
    chosen = series.style_options or {}
    fine = [
        f"{option.name.lower()} {option.choices[chosen[key]].name.lower()}"
        for key, option in presets.style_options.options.items()
        if chosen.get(key) in option.choices
        and not (option.monochrome_only and rendering is not None and not rendering.monochrome)
    ]
    if fine:
        lines.append("Réglages : " + ", ".join(fine))
    guidelines = [genre.llm_guidelines.strip()]
    if tone is not None and tone.llm_guidelines.strip():
        guidelines.append(tone.llm_guidelines.strip())
    return StyleBrief("\n".join(lines), "\n".join(guidelines))


def style_names(presets: PresetRegistry, series: Project) -> str:
    """Noms courts des packs (« Seinen · N&B à trames · Dark ») : requêtes du savoir-faire, listes."""
    names = [
        pack.name
        for pack in (
            presets.style_genres.get(series.style_genre or ""),
            presets.style_renderings.get(series.style_rendering or ""),
            presets.style_tones.get(series.style_tone or ""),
        )
        if pack is not None
    ]
    return " · ".join(names) if names else _clean(series.legacy_style)
