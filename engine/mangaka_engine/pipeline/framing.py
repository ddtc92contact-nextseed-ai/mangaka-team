"""Qui est dans l'image : personnages présents, personnages cités hors cadre, point de vue d'un spectateur.

Une case distingue les personnages **présents à l'image** (`Panel.character_names` : dessinés, avec leur
image de référence) des personnages **cités mais hors cadre** (`Panel.offscreen_names` : jamais dessinés,
jamais de référence). Une case peut n'avoir aucun personnage présent (décor, objet, foule anonyme).

Quand le texte d'une case met un personnage en spectateur (« ils voient au loin les trafiquants… »), la
direction artistique choisit explicitement (`Panel.viewpoint`) :

- **plan de réaction** (`reaction`) : le spectateur est dessiné, avec ce qu'il voit ;
- **vue subjective** (`subjective`) : on voit ce qu'il voit, le spectateur reste hors cadre.

Les noms se comparent sur leur **radical** (accents et casse retirés, premier mot, « s » final ôté,
5 lettres au plus) : le scénario écrit « angu » pour Angus, « trafiquant » sans numéro.
"""

from __future__ import annotations

import re
import string
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .names import STOPWORDS, CharacterMatcher, name_key

REACTION = "reaction"
SUBJECTIVE = "subjective"
# Libellés français (direction artistique, atelier) → clé stockée.
VIEWPOINT_LABELS = {REACTION: "plan de réaction", SUBJECTIVE: "vue subjective"}
VIEWPOINT_KEYS = {
    "plan de réaction": REACTION,
    "plan de reaction": REACTION,
    "réaction": REACTION,
    "reaction": REACTION,
    "vue subjective": SUBJECTIVE,
    "subjective": SUBJECTIVE,
    "pov": SUBJECTIVE,
}
# Origine du choix : la direction artistique, son choix par défaut (LLM muet), ou l'auteur (jamais écrasé).
SOURCES = ("direction", "défaut", "auteur")

# Verbes de perception (sans accents) : le sujet regarde, quelqu'un ou quelque chose est vu.
PERCEPTION = re.compile(
    r"\b(voit|voient|regarde|regardent|apercoit|apercoivent|decouvre|decouvrent|assiste|assistent|"
    r"observe|observent|contemple|contemplent)\b"
)
# Pronoms qui désignent un personnage sans le nommer : la case parle de quelqu'un, on ne touche à rien.
PERSON_PRONOUNS = re.compile(r"\b(il|elle|ils|elles|lui|eux)\b")
# Mots (sans accents) qui désignent des gens sans les nommer (« les deux dragons », « le groupe », « la
# foule ») : une case qui n'en cite aucun par son nom mais en contient un garde ses personnages.
PEOPLE_WORDS = re.compile(
    r"\b(deux|trois|quatre|tous|toutes|chacun|chacune|ensemble|groupe|equipe|bande|duo|trio|foule|heros|"
    r"heroine|heroines|personnage|personnages|homme|hommes|femme|femmes|garcon|garcons|fille|filles|enfant|"
    r"enfants|ami|amis|amie|amies|compagnon|compagnons|freres|soeurs|famille|couple|silhouette|silhouettes)\b"
)
_SENTENCES = re.compile(r"[.!?;…]+")
_WORD = re.compile(r"[a-z0-9]+")

Aliases = Callable[[str], Sequence[str]]


def plain(text: str | None) -> str:
    """Minuscules, sans accents (« Aperçoit » → « apercoit »)."""
    decomposed = unicodedata.normalize("NFD", (text or "").lower().replace("’", "'"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def stem(word: str) -> str:
    """Radical d'un mot : sans « s » final, 5 lettres au plus (« trafiquants » → « trafi », « Angus » → « angu »)."""
    w = plain(word).rstrip("s")
    return w[:5] if len(w) >= 5 else w


def name_stem(name: str) -> str:
    """Radical d'un nom : celui de son premier mot significatif (« le Trafiquant 2 » → « trafi »)."""
    words = name_key(name).split()
    first = next((w for w in words if w not in STOPWORDS and not w.isdigit()), words[0] if words else "")
    return stem(first)


def _number(name: str) -> str | None:
    """Numéro d'un nom (« Trafiquant 2 » → « 2 »), None sinon."""
    return next((w for w in name_key(name).split() if w.isdigit()), None)


def cites(text: str, name: str, aliases: Sequence[str] = ()) -> bool:
    """`text` cite `name` (ou l'un de ses `aliases`) par son radical. Un nom numéroté (« Trafiquant 2 »)
    n'est pas cité par un autre numéro (« trafiquant 1 »), mais l'est sans numéro (« le trafiquant »)."""
    words = _WORD.findall(plain(text))
    for candidate in (name, *aliases):
        root = name_stem(candidate)
        if len(root) < 2:
            continue
        number = _number(candidate)
        for i, w in enumerate(words):
            if w.isdigit() or stem(w) != root:
                continue
            following = words[i + 1] if i + 1 < len(words) else ""
            if number is None or not following.isdigit() or following == number:
                return True
    return False


def mentioned(text: str, name: str, aliases: Sequence[str] = ()) -> bool:
    """Comme `cites`, mais par n'importe quel mot significatif du nom ou d'un alias (« les dragons » désigne
    « Urus le dragon ») : sert à ne retirer de l'image que ceux que le texte ne désigne vraiment pas."""
    if cites(text, name, aliases):
        return True
    stems = {stem(w) for w in _WORD.findall(plain(text)) if not w.isdigit()}
    for candidate in (name, *aliases):
        for w in name_key(candidate).split():
            if len(w) >= 3 and not w.isdigit() and w not in STOPWORDS and stem(w) in stems:
                return True
    return False


def same_name(a: str, b: str) -> bool:
    return name_key(a) == name_key(b)


def _dedupe(names: Iterable[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        n = (n or "").strip()
        if n and not any(same_name(n, o) for o in out):
            out.append(n)
    return out


def _without(names: Iterable[str], removed: Iterable[str]) -> list[str]:
    gone = [name_key(r) for r in removed]
    return [n for n in names if name_key(n) not in gone]


def split_cast(present: Iterable[str], offscreen: Iterable[str]) -> tuple[list[str], list[str]]:
    """Présents et hors cadre sans doublon ; un nom dans les deux listes est présent."""
    p = _dedupe(present)
    return p, _without(_dedupe(offscreen), p)


def aliases_from(matcher: CharacterMatcher | None) -> Aliases:
    """Autres noms de la fiche désignée par un nom (pour reconnaître un alias dans le texte)."""

    def aliases(name: str) -> list[str]:
        if matcher is None:
            return []
        cid = matcher.match(name)
        card = next((c for c in matcher.cards if c.id == cid), None)
        return [" ".join(k) for k in card.keys] if card is not None else []

    return aliases


# --- scénario : garde-fou « cité » ≠ « dans l'image » ---------------------------------------------------
def settle_cast(
    description: str, present: Iterable[str], offscreen: Iterable[str] = (), aliases: Aliases | None = None
) -> tuple[list[str], list[str]]:
    """Présents et hors cadre d'une case écrite par le scénario (garde-fou : le LLM met volontiers à l'image
    tout personnage cité, ou les héros par habitude). Prudent, il ne retire de l'image que deux cas :

    - la description nomme certains présents mais pas les autres (« Trafiquant 2 panique et recule » avec
      Angus et Seku déclarés) : ceux qu'elle ne désigne pas passent hors cadre ;
    - la description ne désigne personne (« Le sol tremble, le volcan gronde ») : tous passent hors cadre.

    Une description qui parle de quelqu'un par un pronom (« il », « elles »…) ou par un mot de personne
    (« les deux dragons », « la foule », « le groupe ») ne retire personne : elle peut désigner un présent
    sans le nommer. Les noms se comparent au radical, alias compris (`mentioned`)."""
    p, off = split_cast(present, offscreen)
    text = plain(description)
    if not p or not text.strip() or PERSON_PRONOUNS.search(text) or PEOPLE_WORDS.search(text):
        return p, off
    aliases = aliases or (lambda _n: [])
    cited = [n for n in p if mentioned(text, n, aliases(n))]
    return cited, _dedupe([*off, *(n for n in p if n not in cited)])


# --- spectateurs ---------------------------------------------------------------------------------------
@dataclass
class Spectators:
    """Ce que le texte dit d'un regard : qui regarde (`viewers`), qui est vu (`seen`), par quel verbe."""

    viewers: list[str] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)
    verb: str = ""

    def __bool__(self) -> bool:
        return bool(self.viewers)


def find_spectators(description: str, names: Sequence[str], aliases: Aliases | None = None) -> Spectators:
    """Personnages de la case mis en spectateurs par le texte (« Seku et Angus voient au loin les
    trafiquants » → Seku, Angus ; vus : les trafiquants). Le sujet d'un verbe de perception (voit, regarde,
    aperçoit, découvre, assiste, observe, contemple) est cité avant lui dans la même phrase ; un sujet
    pronom (« ils voient… ») désigne les personnages de la case qui ne sont pas vus."""
    aliases = aliases or (lambda _n: [])
    for sentence in _SENTENCES.split(plain(description)):
        m = PERCEPTION.search(sentence)
        if not m:
            continue
        before, after = sentence[: m.start()], sentence[m.end() :]
        viewers = [n for n in names if cites(before, n, aliases(n))]
        seen = [n for n in names if n not in viewers and cites(after, n, aliases(n))]
        if not viewers and re.search(r"\b(ils|elles|il|elle)\b", before):
            viewers = [n for n in names if n not in seen]
        if viewers:
            return Spectators(viewers=viewers, seen=seen, verb=m.group(1))
    return Spectators()


def default_viewpoint(spectators: Spectators, present: Sequence[str]) -> str:
    """Choix quand la direction artistique n'en donne pas : vue subjective s'il y a quelque chose à voir
    (un personnage vu, ou d'autres personnages présents que les spectateurs), sinon plan de réaction."""
    others = [n for n in present if not any(same_name(n, v) for v in spectators.viewers)]
    return SUBJECTIVE if spectators.seen or others else REACTION


def viewpoint_key(value: Any) -> str | None:
    """« Vue subjective », « plan de reaction », « pov » → clé stockée ; None si inconnu ou vide."""
    if not isinstance(value, str):
        return None
    return VIEWPOINT_KEYS.get(" ".join(value.strip().lower().replace("’", "'").split()))


def apply_viewpoint(
    panel: Any,
    mode: str | None,
    spectators: Sequence[str],
    *,
    source: str,
    matcher: CharacterMatcher | None = None,
) -> None:
    """Enregistre le point de vue de la case et range ses spectateurs : hors cadre en vue subjective,
    présents en plan de réaction. `mode` None : plus de point de vue (les listes ne bougent pas)."""
    if mode is None:
        panel.viewpoint = None
        return
    present, off = split_cast(panel.character_names or [], getattr(panel, "offscreen_names", None) or [])
    # Les spectateurs gardent l'écriture de la case (« seku » reste « seku »).
    known = [*present, *off]
    viewers = _dedupe(next((k for k in known if same_name(k, s)), s) for s in spectators)
    if mode == SUBJECTIVE:
        present, off = _without(present, viewers), _dedupe([*off, *viewers])
    else:
        present, off = _dedupe([*present, *viewers]), _without(off, viewers)
    panel.character_names = present
    panel.offscreen_names = off
    if matcher is not None:
        panel.character_ids = matcher.ids(present)
    panel.viewpoint = {"mode": mode, "spectators": viewers, "source": source}


def set_cast(
    panel: Any, present: Iterable[str], offscreen: Iterable[str], matcher: CharacterMatcher | None = None
) -> None:
    """Présents et hors cadre de la case (sans doublon) ; les ids des fiches suivent les présents."""
    p, off = split_cast(present, offscreen)
    panel.character_names = p
    panel.offscreen_names = off
    if matcher is not None:
        panel.character_ids = matcher.ids(p)


def viewpoint_of(panel: Any) -> dict[str, Any] | None:
    vp = getattr(panel, "viewpoint", None)
    return vp if isinstance(vp, dict) and vp.get("mode") in VIEWPOINT_LABELS else None


# --- phrase de cadrage du prompt image ------------------------------------------------------------------
def framing_sentence(
    present: Sequence[str], offscreen: Sequence[str], viewpoint: dict[str, Any] | None, texts: Any
) -> str:
    """Consigne de cadrage (anglais, `framing` d'image_prompt.yaml) : vue subjective, case sans personnage,
    ou « seuls X dans le cadre » quand des personnages cités restent hors cadre ; "" sinon (case ordinaire :
    son prompt ne change pas)."""
    if viewpoint is not None and viewpoint.get("mode") == SUBJECTIVE:
        return str(texts.subjective).strip()
    if not offscreen and viewpoint is None:
        return ""
    if not present:
        return str(texts.empty).strip()
    if offscreen:
        return string.Template(str(texts.only)).safe_substitute(names=" and ".join(present)).strip()
    return ""
