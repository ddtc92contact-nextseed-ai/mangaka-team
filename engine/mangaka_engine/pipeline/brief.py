"""Brief d'image d'une case : un rôle par champ, contrôlé, et rien de contradictoire jusqu'à l'image.

Rôles (presets/prompts/script.yaml, web/src/lib/help.ts, écran Scénario) :
- `setting` (« Décor de la case ») : le moment (heure, météo) et les éléments visibles du lieu ; jamais de plan,
  jamais de nom de personnage ;
- `staging` (« Mise en scène ») : pose, geste, regard, expression et place dans l'image des seuls personnages
  de `characters` ; il ajoute à la description, il ne la reformule pas ;
- `description` : un instant figé et dessinable ;
- le plan et l'angle viennent uniquement de la direction artistique.

Contrôles (`brief_rules` de prompts/script.yaml, termes dans le preset, jamais en dur) : un personnage d'une fiche
(nom ou alias) cité dans `setting` ou `staging` sans être dans `characters` ; du vocabulaire de plan dans `setting` ;
un `setting` vide ou sans aucun mot de décor ; une page qui a plus de cases que d'emplacements dans son gabarit ; un
lieu de case que sa description contredit (elle nomme un autre lieu de la série). Lus à la sortie du scénariste
(relance, `pipeline/script.py`), puis sur chaque case par l'API (`brief_notes`, écran Scénario) : un défaut qui
persiste après les relances reste visible, une retouche à la main le fait disparaître.

Garde-fou avant génération (`strip_absent`) : le prompt réellement envoyé à ComfyUI (rédigé par l'IA ou brut) ne
nomme jamais un personnage absent de la case. La phrase qui ne parle que de lui est retirée ; dans une phrase qui
parle aussi d'un présent, le morceau entre virgules qui le nomme, sinon son nom seul. Ce qui est retiré est noté
dans le journal de la génération (`GenerationLog.prompt_guard`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..presets.schemas import BriefRules, count_panels
from .layout import LayoutError, tree_from_json
from .names import STOPWORDS, CharacterMatcher, _same_word, _singular, name_key

# Sortes de défaut (`BriefNote.kind`).
ABSENT = "personnage absent"
SHOT = "plan"
NO_DECOR = "sans décor"
LOCATION = "lieu"
SLOTS = "emplacements"

FIELD_LABELS = {"setting": "« Décor de la case »", "staging": "« Mise en scène »"}


@dataclass(frozen=True)
class BriefNote:
    """Un défaut du brief d'image d'une case (ou de sa page, `field` = "page")."""

    field: str  # setting | staging | lieu | page
    kind: str  # personnage absent | plan | sans décor | lieu | emplacements
    message: str
    names: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {"field": self.field, "kind": self.kind, "message": self.message, "names": list(self.names)}


# --- lecture des textes -----------------------------------------------------------------------
def found_terms(text: str | None, terms: Iterable[str]) -> list[str]:
    """Termes de `terms` présents dans `text`, en mots entiers (sans accents ni casse), tels qu'écrits au preset."""
    key = f" {name_key(text)} "
    return list(dict.fromkeys(t for t in terms if (k := name_key(t)) and f" {k} " in key))


def place_words(name: str | None) -> list[str]:
    """Mots qui désignent un lieu dans son nom (« Le pont du bateau » → pont, bateau)."""
    return [w for w in name_key(name).split() if len(w) >= 4 and w not in STOPWORDS]


def has_decor(text: str | None, terms: Iterable[str], extra: Iterable[str] = ()) -> bool:
    """`text` contient-il au moins un mot de décor : un terme du preset (son pluriel compris) ou un mot du lieu ?"""
    words = name_key(text).split()
    if not words:
        return False
    key = f" {' '.join(words)} "
    single: set[str] = set()
    for t in terms:
        k = name_key(t)
        if " " in k:
            if f" {k} " in key:
                return True
        elif k:
            single.add(k)
    if any(w in single or _singular(w) in single for w in words):
        return True
    places = [w for e in extra for w in place_words(e)]
    return any(_same_word(w, p) for w in words for p in places)


def absent_names(matcher: CharacterMatcher, text: str | None, present: set[int]) -> list[str]:
    """Fiches (nom de la fiche) que `text` nomme alors qu'aucune n'est parmi les présents `present` (un nom ambigu
    qui désigne aussi un présent n'est pas un absent)."""
    out: list[str] = []
    for r in matcher.resolve_all(matcher.read_names(text), [present]):
        if r.ids and not set(r.ids) & present:
            name = matcher.names.get(r.ids[0], r.name)
            if name not in out:
                out.append(name)
    return out


def location_conflict(description: str | None, lieu: str | None, lieux: Iterable[str]) -> str | None:
    """Autre lieu de la série que la description nomme en entier, quand elle ne dit rien du lieu de la case
    (« Depuis le pont du bateau… » sur une case placée « Plage de sable blanc ») ; None sinon."""
    words = name_key(description).split()
    if not words or not lieu:
        return None

    def named(place: str) -> bool:
        pw = place_words(place)
        return bool(pw) and all(any(_same_word(w, p) for w in words) for p in pw)

    own = place_words(lieu)
    if any(_same_word(w, p) for w in words for p in own):
        return None
    current = name_key(lieu)
    return next((other for other in lieux if name_key(other) != current and named(other)), None)


def _names(names: Sequence[str]) -> str:
    return ", ".join(names)


# --- contrôles d'une case ---------------------------------------------------------------------
def panel_notes(
    rules: BriefRules | None,
    matcher: CharacterMatcher,
    *,
    description: str | None,
    setting: str | None,
    staging: str | None,
    characters: Sequence[str],
    lieu: str | None = None,
    lieux: Sequence[str] = (),
) -> list[BriefNote]:
    """Défauts du brief d'une case. `characters` : présents à l'image ; `lieu` : nom du lieu de la case ; `lieux` :
    noms des lieux de la série (et des lieux nouveaux du découpage)."""
    rules = rules or BriefRules()
    notes: list[BriefNote] = []
    present = set(matcher.ids(characters))
    if rules.check_cast:
        for name, text in (("setting", setting), ("staging", staging)):
            absent = absent_names(matcher, text, present)
            if absent:
                notes.append(
                    BriefNote(
                        name,
                        ABSENT,
                        f"{FIELD_LABELS[name]} cite {_names(absent)}, absent{'s' if len(absent) > 1 else ''} de "
                        "« characters » : "
                        + (
                            "le décor ne nomme aucun personnage"
                            if name == "setting"
                            else "la mise en scène ne parle que des personnages présents à l'image"
                        ),
                        tuple(absent),
                    )
                )
    if rules.check_setting:
        shots = found_terms(setting, rules.shot_terms)
        if shots:
            notes.append(
                BriefNote(
                    "setting",
                    SHOT,
                    f"{FIELD_LABELS['setting']} écrit un plan ou un cadrage ({', '.join(f'« {s} »' for s in shots)}) : "
                    "le plan et l'angle viennent de la direction artistique",
                    tuple(shots),
                )
            )
        if not (setting or "").strip():
            notes.append(
                BriefNote(
                    "setting", NO_DECOR, f"{FIELD_LABELS['setting']} vide : écris le moment et ce qu'on voit du lieu"
                )
            )
        elif not has_decor(setting, rules.decor_terms, [lieu] if lieu else []):
            notes.append(
                BriefNote(
                    "setting",
                    NO_DECOR,
                    f"{FIELD_LABELS['setting']} ne décrit aucun décor : écris le moment (heure, météo) et les éléments "
                    "visibles du lieu",
                )
            )
    if rules.check_location:
        other = location_conflict(description, lieu, lieux)
        if other:
            notes.append(
                BriefNote(
                    "lieu",
                    LOCATION,
                    f"la description se passe à « {other} », le lieu de la case est « {lieu} » : une case peut avoir un "
                    "lieu différent de sa scène, donne-lui le bon",
                    (other,),
                )
            )
    return notes


def slot_note(panels: int, slots: int, template: str, insets: int = 0) -> BriefNote | None:
    """Page qui a plus de cases (`panels`) que d'emplacements (`slots`) dans son gabarit ; None sinon."""
    if panels <= slots:
        return None
    extra = f", {insets} incrustée{'s' if insets > 1 else ''} en plus" if insets else ""
    return BriefNote(
        "page",
        SLOTS,
        f"{panels} cases pour {slots} emplacement{'s' if slots > 1 else ''} du gabarit « {template} »{extra} : retire "
        "ou fusionne une case, ou choisis un gabarit qui a assez d'emplacements",
    )


def layout_slots(layout: dict[str, Any] | None) -> int | None:
    """Emplacements (feuilles de l'arbre) du gabarit d'une mise en page stockée ; None sans arbre."""
    tree = (layout or {}).get("tree")
    if tree is None:
        return None
    try:
        return count_panels(tree_from_json(tree))
    except (LayoutError, ValueError, TypeError, AttributeError):
        return None


# --- garde-fou du prompt envoyé ---------------------------------------------------------------
_SENTENCE_SPLIT = re.compile(r"((?<=[.!?;…])\s+|\n+)")
_CHUNK_SPLIT = re.compile(r"(,\s*)")
_LABEL = re.compile(r"^\s*[A-Za-z][\w ]{0,30}:\s*")  # « Staging: », « Setting: » des morceaux du prompt
_LEAD_WORDS = frozenset({"le", "la", "les", "l", "un", "une", "the", "a", "an", "and", "et"})


def _absent_in(matcher: CharacterMatcher, text: str, present: set[int]) -> list[tuple[str, str]]:
    """[(nom tel qu'écrit, nom de la fiche)] des absents que `text` nomme."""
    return [
        (r.name, matcher.names.get(r.ids[0], r.name))
        for r in matcher.resolve_all(matcher.read_names(text), [present])
        if r.ids and not set(r.ids) & present
    ]


def _leads(text: str, written: str) -> bool:
    """Le nom `written` est-il le sujet de `text` (en tête, après l'étiquette « Staging: » et un article) ?"""
    words = name_key(_LABEL.sub("", text, count=1)).split()
    while words and words[0] in _LEAD_WORDS:
        words = words[1:]
    name = name_key(written).split()
    return bool(name) and words[: len(name)] == name


def _without_name(text: str, written: str) -> str:
    out = re.sub(rf"(?<!\w){re.escape(written)}(?!\w)", "", text, flags=re.IGNORECASE)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;!?])", r"\1", out)
    return re.sub(r"\b(et|and)\s*([,.;!?]|$)", r"\2", out).strip()


def strip_absent(matcher: CharacterMatcher, text: str | None, present: set[int]) -> tuple[str, list[dict[str, str]]]:
    """`text` sans aucun nom de fiche absente de la case (`present` : fiches à l'image), et ce qui a été retiré :
    [{"name": fiche, "removed": texte retiré}]. Une phrase dont un absent est le sujet part en entier ; ailleurs, le
    morceau entre virgules dont il est le sujet (« Plage, noix de coco debout à proximité » → « Plage »), sinon son
    nom seul (« fusille Ren du regard » → « fusille du regard »). Texte inchangé quand aucun absent n'est nommé."""
    text = text or ""
    if not text or not matcher.cards:
        return text, []
    removed: list[dict[str, str]] = []
    pieces = _SENTENCE_SPLIT.split(text)
    out: list[str] = []
    for k in range(0, len(pieces), 2):
        sentence, sep = pieces[k], pieces[k + 1] if k + 1 < len(pieces) else ""
        absent = _absent_in(matcher, sentence, present)
        if not absent:
            out.append(sentence + sep)
            continue
        if any(_leads(sentence, written) for written, _f in absent):
            # « Staging: Noix de coco observe. » : l'étiquette part avec sa seule phrase.
            removed += [{"name": fiche, "removed": sentence.strip()[:300]} for _w, fiche in absent]
            continue
        chunks = _CHUNK_SPLIT.split(sentence)
        kept: list[str] = []
        for j in range(0, len(chunks), 2):
            chunk = chunks[j]
            c_absent = _absent_in(matcher, chunk, present)
            if c_absent and any(_leads(chunk, written) for written, _f in c_absent):
                removed += [{"name": fiche, "removed": chunk.strip(" ,;")[:300]} for _w, fiche in c_absent]
                continue
            for written, fiche in c_absent:
                chunk = _without_name(chunk, written)
                removed.append({"name": fiche, "removed": written})
            kept.append(chunk)
        joined = ", ".join(c.strip(" ,") for c in kept if c.strip(" ,"))
        end = sentence.rstrip()[-1:]
        if joined and end in ".!?;…" and not joined.endswith(end):
            joined = joined.rstrip(".!?;…") + end
        if joined:
            out.append(joined + sep)
    result = re.sub(r";\s*$", ".", "".join(out).strip())
    return result, removed


# --- cases et pages en base (API, écran Scénario) ---------------------------------------------
def stored_panel_notes(
    rules: BriefRules | None, matcher: CharacterMatcher, panel: Any, lieux: Sequence[str] = ()
) -> list[BriefNote]:
    """Défauts du brief d'une case enregistrée (ceux qui ont survécu aux relances, ou une retouche à la main)."""
    if rules is None:
        return []
    location = getattr(panel, "location", None)
    return panel_notes(
        rules,
        matcher,
        description=panel.description,
        setting=panel.setting,
        staging=panel.staging,
        characters=list(panel.character_names or []),
        lieu=location.name if location is not None else None,
        lieux=lieux,
    )


def stored_page_notes(rules: BriefRules | None, page: Any, template_names: dict[str, str]) -> list[BriefNote]:
    """Page mise en page qui a plus de cases que d'emplacements dans son gabarit ; une incrustation imposée à la main
    par l'auteur (`Panel.frame`) est son choix et ne compte pas."""
    if rules is None or not rules.check_slots or not page.panels:
        return []
    slots = layout_slots(page.layout)
    if slots is None:
        return []
    forced = sum(1 for p in page.panels if (p.frame or {}).get("inset") is True)
    template_id = str((page.layout or {}).get("template_id") or "")
    note = slot_note(len(page.panels) - forced, slots, template_names.get(template_id, template_id))
    return [note] if note is not None else []
