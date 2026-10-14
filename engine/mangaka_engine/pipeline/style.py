"""Style d'une série : le seul endroit où il se compose.

Le style se choisit dans des listes fermées (presets/style_genres, style_renderings, style_tones,
style_options.yaml). Ce module en tire :

- `$style` des prompts image (cases, fiches de référence, réparation, croquis et passage au propre) :
  mots déclencheurs du LoRA de style (catalogue style_loras.yaml), puis mots-clés du genre, du rendu,
  du ton et des réglages fins, dans cet ordre, sans doublon, sous le plafond `style_max_chars`
  (image_prompt.yaml) : chaque pack y garde au moins son premier mot-clé ;
- `$finition` (`series_finition`) : mots-clés du réglage à pièce réservée « finition », juste après la
  phrase de style et jamais dans `$style`, et ses termes négatifs (`series_finition_negative`) ;
- un réglage qui **remplace** (`replaces` d'un choix, réglage `dessin` « Épuré ») : ses mots-clés passent en
  tête de `$style` et les mots-clés listés sont retirés des autres packs et de la phrase de style — ajouter
  des mots « épurés » à une chaîne détaillée ne change rien (mesuré le 14/10/2026), il faut remplacer. Ses
  mots anti-détail (`subject_keywords`) vont dans `$finition` des cases et `$subject` des fiches
  (`series_subject`), ses termes négatifs avec ceux de la finition (`series_style_negative`) ;
- le nom des packs et leurs consignes pour les LLM (scénario, direction artistique) ;
- la validation des combinaisons (API) : ids connus, ton autorisé par le genre, trames en N&B seulement.

Une série d'avant les packs (aucun genre choisi) garde son ancien texte libre (`legacy_style`, lecture
seule) à la place du genre, avec le rendu par défaut ; il est ignoré dès qu'un pack est choisi.
"""

from __future__ import annotations

import logging
import string
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from ..presets import PresetRegistry
from ..presets.schemas import StyleOption, StyleOptionChoice, StylePack, StyleRendering
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


def series_rendering(presets: PresetRegistry, series: Project) -> StyleRendering | None:
    """Pack de rendu de la série. Pas de rendu choisi (ou disparu des presets) : le rendu par défaut,
    jamais aucun rendu (None seulement sans aucun pack de rendu)."""
    return presets.style_renderings.get(series.style_rendering or "") or presets.style_renderings.get(
        presets.default_style_rendering or ""
    )


def _chosen_options(
    presets: PresetRegistry, series: Project, rendering: StyleRendering | None
) -> list[tuple[StyleOption, StyleOptionChoice]]:
    """Réglages fins choisis par la série, dans l'ordre du fichier ; sans ceux réservés au N&B sur un rendu
    couleur."""
    chosen = series.style_options or {}
    out = []
    for key, option in presets.style_options.options.items():
        choice = option.choices.get(chosen.get(key) or "")
        if choice is None or (option.monochrome_only and rendering is not None and not rendering.monochrome):
            continue
        out.append((option, choice))
    return out


def _words(pack: StylePack | StyleOptionChoice, people: bool, monochrome: bool = True) -> list[str]:
    """Mots-clés d'un pack ; sans ceux qui évoquent des personnes si `people` est faux, sans ceux réservés au
    noir et blanc (`monochrome_keywords` d'un choix) sur un rendu couleur."""
    mono = getattr(pack, "monochrome_keywords", ())
    return [
        k for k in pack.prompt_keywords if (people or k not in pack.people_keywords) and (monochrome or k not in mono)
    ]


def _replaced(chosen: list[tuple[StyleOption, StyleOptionChoice]]) -> set[str]:
    """Mots-clés (sans casse) que les choix qui remplacent (`replaces`) retirent des autres packs."""
    return {_clean(w).casefold() for _, choice in chosen for w in choice.replaces}


def style_groups(
    presets: PresetRegistry, series: Project, *, people: bool = True, drop: Collection[str] = ()
) -> list[tuple[str, list[str]]]:
    """Mots-clés complets du style, par pack, dans l'ordre fixe : LoRA, genre (ou ancien texte), rendu,
    ton, puis un groupe par réglage fin choisi — (sorte, mots-clés). `people` faux : sans les mots-clés
    marqués `people` (fiches d'objet et de décor). `drop` : mots-clés écartés (sans casse), ceux du ton
    que contredit l'ambiance d'une case (`prompt.mood_dropped_terms`).

    Un choix qui remplace (`replaces`, réglage `dessin` « Épuré ») forme le groupe « replacing », juste après
    le LoRA ; ses mots-clés listés dans `replaces` sont retirés du genre, du rendu, du ton et des autres
    réglages (jamais des mots déclencheurs du LoRA)."""
    groups: list[tuple[str, list[str]]] = [("lora", list(lora_triggers(presets, series)))]
    rendering = series_rendering(presets, series)
    monochrome = rendering is None or rendering.monochrome
    chosen = _chosen_options(presets, series, rendering)
    for _, choice in chosen:
        if choice.replaces:
            groups.append(("replacing", _words(choice, people, monochrome)))
    genre = presets.style_genres.get(series.style_genre or "")
    if genre is not None:
        groups.append(("genre", _words(genre, people)))
    elif not series.style_genre:
        # Ancien texte libre : découpé aux virgules, comme des mots-clés.
        groups.append(("genre", (series.legacy_style or "").split(",")))
    if rendering is not None:
        groups.append(("rendering", _words(rendering, people)))
    tone = presets.style_tones.get(series.style_tone or "")
    if tone is not None:
        groups.append(("tone", _words(tone, people)))
    for option, choice in chosen:
        # Une pièce réservée (finition) n'entre jamais dans $style ; le choix neutre d'un réglage qui remplace
        # (« Détaillé ») n'a aucun mot-clé.
        if option.piece is None and not choice.replaces and choice.prompt_keywords:
            groups.append(("option", _words(choice, people, monochrome)))
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
    dropped = {_clean(d).casefold() for d in drop}
    replaced = dropped | _replaced(chosen)
    return [
        (
            kind,
            [
                w
                for w in (_clean(x) for x in g)
                if w and w.casefold() not in (dropped if kind in ("lora", "replacing") else replaced)
            ],
        )
        for kind, g in groups
    ]


def _redundant(word: str, kept: list[str]) -> bool:
    """Doublon (casse ignorée) ou déjà contenu, mot pour mot, dans un mot-clé retenu (« manga » après
    « manga seinen »)."""
    w = f" {word.casefold()} "
    return any(w in f" {k.casefold()} " for k in kept)


def style_keywords(
    presets: PresetRegistry, series: Project, *, people: bool = True, drop: Collection[str] = ()
) -> list[str]:
    """Mots-clés retenus pour `$style`, dans l'ordre fixe des packs, sans doublon.

    Bloc court (`style_max_chars` de image_prompt.yaml) : les mots déclencheurs du LoRA d'abord, puis tous
    ceux d'un choix qui remplace (« Épuré » : la recette mesurée part entière), puis
    chaque pack donne ses mots-clés tour à tour (le 1er de chaque pack, puis le 2e…) tant que le
    plafond le permet ; un pack s'arrête au premier mot-clé qui ne tient plus. À chaque tour, le rendu
    passe en premier : sans planche de style jointe aux cases, c'est lui qui porte trait, encrage et
    trames. Les mots-clés des packs (calibrés) ne sont jamais modifiés : seule leur sélection change.
    """
    cap = presets.image_prompt.style_max_chars
    # Doublons retirés d'avance (par rapport aux packs précédents) : le 1er mot-clé d'un pack est son
    # premier mot-clé utile (« manga » d'un réglage fin s'efface derrière « manga seinen » du genre).
    kinds: list[str] = []
    groups: list[list[str]] = []
    for kind, group in style_groups(presets, series, people=people, drop=drop):
        kinds.append(kind)
        earlier = [w for g in groups for w in g]
        groups.append([])
        for word in group:
            if not _redundant(word, earlier + groups[-1]):
                groups[-1].append(word)
    kept: list[list[str]] = [[] for _ in groups]
    used = 0

    def take(i: int, word: str) -> bool:
        nonlocal used
        size = used + (2 if used else 0) + len(word)
        if cap is not None and size > cap:
            return False
        kept[i].append(word)
        used = size
        return True

    head = [i for i, kind in enumerate(kinds) if kind in ("lora", "replacing")]
    for i in head:
        for word in groups[i]:
            take(i, word)
    stopped = [False] * len(groups)
    turn = sorted((i for i in range(len(groups)) if i not in head), key=lambda i: kinds[i] != "rendering")
    for rank in range(max((len(g) for g in groups), default=0)):
        for i in turn:
            if stopped[i] or rank >= len(groups[i]):
                continue
            if not take(i, groups[i][rank]):
                stopped[i] = True
    return [w for g in kept for w in g]


def series_style(presets: PresetRegistry, series: Project, *, people: bool = True, drop: Collection[str] = ()) -> str:
    """`$style` des prompts image de la série (`people` faux : sans les mots-clés qui évoquent des personnes ;
    `drop` : mots-clés écartés pour une case, voir `style_groups`)."""
    return ", ".join(style_keywords(presets, series, people=people, drop=drop))


def series_monochrome(presets: PresetRegistry, series: Project) -> bool:
    """Série en noir et blanc : `monochrome` de son pack de rendu (voir `series_rendering`)."""
    rendering = series_rendering(presets, series)
    return rendering is not None and rendering.monochrome


def series_style_lead(presets: PresetRegistry, series: Project) -> str:
    """Phrase de style qui ouvre chaque prompt de case (« Black and white manga panel, inked line art with
    halftone screentone shading, seinen manga style. ») : `lead` du rendu de la série (sinon son 1er
    mot-clé) et 1er mot-clé du genre (ou de l'ancien style libre), dans les morceaux `style_lead`
    d'image_prompt.yaml. Sans le modèle d'image ancré par une référence, c'est elle qui tient le style.

    Un choix qui remplace (`replaces`, « Épuré ») retire de la phrase les morceaux du `lead` (coupé aux
    virgules) qu'il liste (« hand-drawn inked line art with halftone screentone shading »), et le genre y
    donne son 1er mot-clé non remplacé ; sans lui, la phrase est inchangée."""
    rendering = series_rendering(presets, series)
    replaced = _replaced(_chosen_options(presets, series, rendering))
    lead = _clean(rendering.lead) or _clean(rendering.prompt_keywords[0]) if rendering is not None else ""
    if replaced:
        lead = ", ".join(p for p in (_clean(x) for x in lead.split(",")) if p and p.casefold() not in replaced)
    genre = presets.style_genres.get(series.style_genre or "")
    words = genre.prompt_keywords if genre is not None else (series.legacy_style or "").split(",")
    first = next((w for w in (_clean(x) for x in words) if w and w.casefold() not in replaced), "")
    values = {"rendering": lead, "genre": first}
    parts: list[str] = []
    for part in presets.image_prompt.style_lead:
        tpl = string.Template(part)
        if any(not values.get(v) for v in tpl.get_identifiers()):
            continue
        text = _clean(tpl.substitute(values))
        if text:
            parts.append(text)
    if not parts:
        return ""
    sentence = ", ".join(parts)
    return sentence[:1].upper() + sentence[1:] + "."


def _finition(presets: PresetRegistry, series: Project) -> StyleOptionChoice | None:
    """Choix de la série pour le réglage à pièce réservée `finition` (style_options.yaml), sinon None."""
    for option, choice in _chosen_options(presets, series, series_rendering(presets, series)):
        if option.piece == "finition":
            return choice
    return None


def _replacing(presets: PresetRegistry, series: Project) -> list[StyleOptionChoice]:
    """Choix de la série qui remplacent (`replaces` : « Épuré » du réglage `dessin`), dans l'ordre du fichier."""
    return [c for _, c in _chosen_options(presets, series, series_rendering(presets, series)) if c.replaces]


def series_subject(presets: PresetRegistry, series: Project) -> str:
    """Mots anti-détail du dessin choisi (`subject_keywords` d'un choix qui remplace, « plain smooth untextured
    surfaces, no mechanical panel lines… »), joints par « , » ; "" sans ce choix. Hors `$style` : `$subject` des
    fiches de référence, et ajoutés à `$finition` des cases (`series_finition`). Une fois la chaîne de style
    épurée, la description du personnage reprend la main (« style mechatronique » ramène des panneaux
    d'armure, mesuré le 14/10/2026) : ces mots génériques l'éteignent."""
    words = [w for c in _replacing(presets, series) for w in (_clean(k) for k in c.subject_keywords) if w]
    return ", ".join(dict.fromkeys(words))


def series_finition(presets: PresetRegistry, series: Project) -> str:
    """`$finition` des prompts de case : mots-clés de la finition choisie par la série (« croquis »,
    « pinceau-nerveux », « scan »), puis les mots anti-détail du dessin (`series_subject`, « Épuré »), joints
    par « , », sans point final et la majuscule en tête (« Printed on cheap paper, coarse halftone dots… »),
    juste après la phrase de style ; "" pour « propre » (ou sans choix) et un dessin « Détaillé ».
    Jamais dans `$style` : plafonné à `style_max_chars`, il les tronquerait en silence."""
    choice = _finition(presets, series)
    words = [w for w in (_clean(k) for k in choice.prompt_keywords) if w] if choice is not None else []
    subject = series_subject(presets, series)
    text = ", ".join([*words, subject] if subject else words)
    return text[:1].upper() + text[1:]


def series_finition_negative(presets: PresetRegistry, series: Project) -> list[str]:
    """Termes du prompt négatif de la finition choisie (vide pour « propre » ou sans choix). Le négatif
    n'est lu qu'à vrai CFG (cfg > 1, palier Qualité) : en Turbo, Rapide et croquis (cfg 1), seul `$finition`
    du prompt positif porte la finition."""
    choice = _finition(presets, series)
    return list(choice.negative_keywords) if choice is not None else []


def series_style_negative(presets: PresetRegistry, series: Project) -> list[str]:
    """Termes du prompt négatif des cases de la série : ceux de la finition (`series_finition_negative`), puis
    ceux d'un choix qui remplace (« Épuré » : « mechanical panel lines, rivets… »), sans doublon. Lus à vrai CFG
    seulement (palier Qualité)."""
    words = [
        *series_finition_negative(presets, series),
        *(w for c in _replacing(presets, series) for w in c.negative_keywords),
    ]
    return list(dict.fromkeys(words))


def series_subject_negative(presets: PresetRegistry, series: Project) -> list[str]:
    """Termes négatifs d'un choix qui remplace (« Épuré »), ajoutés au prompt négatif des fiches de référence
    (palier Qualité). La finition (croquis, scan…) ne touche pas aux fiches."""
    return list(dict.fromkeys(w for c in _replacing(presets, series) for w in c.negative_keywords))


# --- dessin des personnages (réglage qui remplace) : fiches créées avant ---------------------------
def drawing_record(presets: PresetRegistry, series: Project) -> dict[str, str]:
    """Choix de la série pour chaque réglage qui remplace (`dessin`), noté sur une fiche générée : on sait
    ensuite avec quel dessin elle a été créée. Vide pour une série sans ce réglage (« Détaillé » d'office)."""
    chosen = series.style_options or {}
    return {
        key: chosen[key]
        for key, option in presets.style_options.options.items()
        if any(c.replaces for c in option.choices.values()) and chosen.get(key) in option.choices
    }


@dataclass(frozen=True)
class StaleDrawing:
    """Fiche créée avec un autre dessin que celui de la série : « Créée avec l'ancien rendu (détaillé) »."""

    option: str
    current: str  # nom court du dessin de la série (« épuré »)
    previous: str  # nom court du dessin de la fiche (« détaillé »)

    @property
    def message(self) -> str:
        return f"Créée avec l'ancien rendu ({self.previous})"

    @property
    def action(self) -> str:
        return f"Refaire la base en {self.current}"


def _short(name: str) -> str:
    """« Détaillé (genre) » → « détaillé »."""
    return name.split(" (")[0].strip().lower()


def stale_drawing(presets: PresetRegistry, series: Project, recorded: Mapping[str, Any] | None) -> StaleDrawing | None:
    """La série a choisi un dessin qui remplace (« Épuré ») mais la fiche (`recorded` : `drawing_record` noté à
    sa génération, absent avant ce réglage = « Détaillé ») a été créée avec un autre : elle garde son trait,
    ses variantes aussi (l'image de départ fige le rendu). None si rien n'a changé."""
    rendering = series_rendering(presets, series)
    chosen = series.style_options or {}
    for key, option in presets.style_options.options.items():
        current = option.choices.get(chosen.get(key) or "")
        if current is None or not current.replaces:
            continue
        if option.monochrome_only and rendering is not None and not rendering.monochrome:
            continue
        before = (recorded or {}).get(key)
        if before == chosen.get(key):
            continue
        previous = option.choices.get(str(before or "")) or next(
            (c for c in option.choices.values() if not c.replaces), None
        )
        return StaleDrawing(key, _short(current.name), _short(previous.name) if previous else "détaillé")
    return None


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
