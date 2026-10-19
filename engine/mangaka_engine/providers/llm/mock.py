"""LLM factice, déterministe, sans réseau (mode par défaut sans .env et dans les tests).

Pour l'étape « scénario », il reconnaît le bloc `<contexte>{"task": "script", …}</contexte>` du
prompt et renvoie un découpage plausible (nombre de pages visé, personnages de la série ; chaque page
se passe dans un décor de la bibliothèque, à tour de rôle, et une case sur deux montre un objet).

Chaque case du découpage se rattache à un lieu de la série (`lieu` : l'id d'un lieu existant de même nom, sinon son
nom) ; le lieu change toutes les trois pages.

Pour la direction artistique (`"task": "art_direction"`), il renvoie des choix variés mais
déterministes : même chapitre, même audace, même relance → mêmes choix (`mock_art_direction`), qui
respectent les règles de variété du preset (angles en alternance, jamais 3 plans identiques d'affilée,
une action par case) ; une case à spectateur reçoit une « vue subjective » s'il y a autre chose à voir,
sinon un « plan de réaction ».

Pour la rédaction du prompt image d'une case (`"task": "image_prompt"`), il rend un paragraphe qui
définit d'abord le rôle de chaque image de référence (`<image1>`…), nomme chaque personnage, le place
dans le cadre avec une pose, décrit la caméra, la lumière, et finit par les mots-clés de style
(`mock_image_prompt`). En anglais, il n'écrit que des phrases anglaises : il ne sait pas traduire, donc
la description française de la case n'y entre pas (elle reste dans `notes`). `[mock:prompt-invalide:N]` dans la description de la case :
les N premiers essais sont invalides ; `[mock:prompt-intrus:N]` : ils nomment un personnage absent.

Pour le prompt image « gabarit » (`"task": "image_prompt_template"`), il rend 1 à 3 phrases d'action anglaises
(qui, action, expression, gauche ou droite ; 60 mots au plus) et le décor court (lieu et éléments reçus) ;
`[mock:gabarit-invalide:N]` dans la description : les N premières réponses sont refusées (trop longues, mot
photo). Pour l'ancre visuelle d'une fiche (`"task": "visual_anchor"`), le début de sa description et de ses
mots-clés (le mock ne traduit pas), sans le nom.

Pour le dialogue sur une case (`"task": "image_prompt_dialog"`), il lit la consigne de l'auteur : un plan
(« gros plan », « plan large »…), un angle (« contre-plongée », « de dos »…), « en train de … » (action),
« fond blanc » (ambiance) ; pour un gros plan il choisit l'image « portrait » ou « visage » d'un personnage
qui en a une, pour un plan large une image « pied » ou « turnaround » ; puis il réécrit le paragraphe
avec la nouvelle caméra (`mock_dialog`). `[mock:dialogue-invalide:N]` dans la consigne : les N premiers
essais sont invalides (plan hors liste, puis JSON illisible).

Pour la fiche d'un intervenant (`"task": "character_draft"`, pipeline/cast.py), il rend âge, silhouette, tenue
et signe distinctif choisis d'après le nom, plus la première description de ses cases (`mock_character_draft`) ;
`[mock:fiche-invalide:N]` dans la description d'une de ses cases : les N premiers essais sont invalides.

Identité visuelle (`"task": "palette"` / `"logo"`) : palettes déterministes tirées du titre (teintes réparties,
décalées à chaque « Proposer d'autres palettes ») et concepts de logo qui parcourent les polices et les effets
permis, le titre en une ou deux lignes (`mock_palettes`, `mock_logos`). `[mock:identite-invalide:N]` dans le
titre de la série : les N premiers essais sont invalides (JSON illisible, puis mauvais schéma).

Résumé de 4e de couverture (`"task": "back_summary"`) : texte déterministe tiré des résumés des chapitres
(jamais du dernier, la fin du tome) et de phrases d'accroche, dans les bornes de longueur demandées, différent
du résumé actuel (« Réécrire »). `[mock:resume-invalide:N]` dans le titre du tome : les N premiers essais sont
invalides (prose, puis résumé trop court).

Créateur de série (`"task": "series_creation"`, pipeline/series_creator.py) : reprend les pistes d'ADN des
réponses (`suggested`) avec une explication qui cite la réponse, écrit une bible tirée du titre, de l'idée et des
réponses, et une note par personnage. `[mock:createur-invalide:N]` dans l'idée de la série : les N premiers essais
sont invalides (prose, puis bible vide et réglage inconnu).

Pour tester les relances sans vrai LLM, les `invalid_attempts` premiers essais d'une conversation
renvoient une réponse invalide (variable MOCK_LLM_INVALID_ATTEMPTS, ou `[mock:invalide:N]` dans le
synopsis du chapitre ; `[mock:da-invalide:N]` pour la seule direction artistique ;
`[mock:id-invalide:N]` : découpage bien formé qui cite un décor inexistant ;
`[mock:dialogues-maigres:N]` : découpage valide mais aux dialogues maigres, comme le chapitre 3 « vulcano »
— une réplique sur deux cases, cases de combat réduites à leur onomatopée, ni pensée ni narration ;
`[mock:brief-sale:N]` : brief d'image sale sur les premières cases, comme « Second round » — plan et personnage
absent dans le décor, hors cadre qui agit dans la mise en scène, décor sans mot de décor, `dirty_brief`).
`[mock:sans-etablissement:N]` : les N premiers essais de la direction artistique (relance ciblée comprise)
n'installent pas les nouveaux lieux (pas de case d'établissement au changement de lieu).
L'essai courant se déduit des messages : aucun état entre deux appels.

Découpage en scènes (`"task": "scenes"`, pipeline/scenes.py) : une scène par phrase du synopsis, son type deviné d'après
ses mots (combat, poursuite, match, révélation, dialogue, sinon calme) et ses pages d'après son type ; la somme des
pages vaut toujours la cible du chapitre, et les phrases qui ne rentrent pas sont reportées au chapitre suivant
(`mock_scenes`) ; la distribution d'une scène : les fiches nommées dans sa phrase. `[mock:scenes-invalide:N]` dans le synopsis : les N premiers essais sont invalides (prose, puis type
hors liste et somme fausse). Avec des scènes validées dans le contexte du scénario, chaque page du découpage porte sa
scène et chaque scène a ses pages ; `[mock:scenes-pages:N]` : les N premiers essais rangent toutes les pages dans la
première scène.

Name scène par scène (contexte du scénariste avec `scene` : la scène à écrire) : le découpage factice n'écrit que cette
scène, dans son nombre de pages, d'après son résumé, et suit la charte de la scène (`pre_direction` : ADN de la série
précisé par le profil) — cases, répliques et cases muettes par planche, aucun encadré de narration si le profil n'en
veut pas ; une révélation finit sur une pleine page. `[mock:scenes-pages:N]` : les N premiers essais de chaque scène
ont une page de trop ; `[mock:plusieurs-actions:N]` : la première case de chaque scène enchaîne plusieurs actions
(« Il dégaine puis tire et s'enfuit. »). En direction artistique (contexte avec `scene`), la scène suit son profil
(parts de plans, grande case sur chaque planche d'une révélation) et le rythme des pages d'avant (respiration après un
pic) ; `[mock:da-sans-gros-plan:N]` : les N premiers essais n'ont aucun gros plan ni très gros plan.

Regroupement des lieux (`"task": "locations"`, pipeline/locations.py) : les variantes de même nom de lieu
(« clairière », « clairière au centre de l'île ») vont ensemble (`heuristic_groups`).

Le découpage factice respecte les règles de dialogue livrées (presets/prompts/script.yaml) : deux
répliques courtes par case (une seule sur une page chargée), un cri dans chaque case « choc », une
narration en ouverture et des pensées.

Il respecte aussi la charte de la série (ADN, `pre_direction` du contexte, presets/pre_direction.yaml) : cases
par planche, répliques comptées par planche avec une case muette, cases sans personnage si le genre en demande ;
et, en direction artistique, la courbe de rythme (premier pic dans la fenêtre, respiration après, pic final),
les formes de planche (gabarits variés, part de planches à grande case) et l'échelle des plans (plancher des
plans larges, plafond des plans serrés).
"""

from __future__ import annotations

import colorsys
import json
import math
import re
import unicodedata
from collections.abc import Callable
from typing import Any

from .base import ChatMessage, LLMResult

Responder = Callable[[list[ChatMessage], bool], str]

_CONTEXT = re.compile(r"<contexte>\s*(\{.*\})\s*</contexte>", re.DOTALL)
_INVALID_MARK = re.compile(r"\[mock:invalide:(\d+)\]")
_DA_INVALID_MARK = re.compile(r"\[mock:da-invalide:(\d+)\]")
_ID_INVALID_MARK = re.compile(r"\[mock:id-invalide:(\d+)\]")
_SPARSE_MARK = re.compile(r"\[mock:dialogues-maigres:(\d+)\]")
_PROMPT_INVALID_MARK = re.compile(r"\[mock:prompt-invalide:(\d+)\]")
_PROMPT_INTRUDER_MARK = re.compile(r"\[mock:prompt-intrus:(\d+)\]")
_TEMPLATE_INVALID_MARK = re.compile(r"\[mock:gabarit-invalide:(\d+)\]")
_DIALOG_INVALID_MARK = re.compile(r"\[mock:dialogue-invalide:(\d+)\]")
_DRAFT_INVALID_MARK = re.compile(r"\[mock:fiche-invalide:(\d+)\]")
_IDENTITY_INVALID_MARK = re.compile(r"\[mock:identite-invalide:(\d+)\]")
_SUMMARY_INVALID_MARK = re.compile(r"\[mock:resume-invalide:(\d+)\]")
_NO_ESTABLISHING_MARK = re.compile(r"\[mock:sans-etablissement:(\d+)\]")
_CREATOR_INVALID_MARK = re.compile(r"\[mock:createur-invalide:(\d+)\]")
_SCENES_INVALID_MARK = re.compile(r"\[mock:scenes-invalide:(\d+)\]")
_SCENE_PAGES_MARK = re.compile(r"\[mock:scenes-pages:(\d+)\]")
_MULTI_ACTION_MARK = re.compile(r"\[mock:plusieurs-actions:(\d+)\]")
_NO_CLOSE_UP_MARK = re.compile(r"\[mock:da-sans-gros-plan:(\d+)\]")
_DIRTY_BRIEF_MARK = re.compile(r"\[mock:brief-sale:(\d+)\]")
MULTI_ACTION = "Il dégaine puis tire et s'enfuit."
_ANY_MARK = re.compile(r"\s*\[mock:[a-z-]+:\d+\]\s*")
UNKNOWN_ID = 999_999  # id de décor cité par `[mock:id-invalide:N]` (absent de toute bibliothèque)
TASKS = (
    "script",
    "art_direction",
    "image_prompt",
    "image_prompt_dialog",
    "image_prompt_template",
    "visual_anchor",
    "character_draft",
    "cover_prompt",
    "palette",
    "logo",
    "back_summary",
    "locations",
    "series_creation",
    "scenes",
)

_PANELS_PER_PAGE = [5, 4, 6, 3, 5, 4]
_KINDS = ["speech", "speech", "thought", "speech", "shout"]
# Réponses courtes du second personnage de la case (accents compris).
_REPLIES = ["Quoi ?!", "Tiens bon !", "Je n'y crois pas…", "Allons-y, vite !", "Attention, derrière toi !", "Ça ira."]
_SHOUTS = ["À couvert !", "Maintenant !", "Lâche ça !", "Recule !"]
_MOCK_WORDS = 8  # mots au plus par réplique factice
_RYTHMES = ["normal", "rapide", "lent", "normal", "rapide"]
# Onomatopées des cases « choc » (et d'une case calme de temps en temps), accents compris : celles de la
# bibliothèque du contexte (presets/sfx_library.yaml, « sfx_library »), sinon cette liste, toutes dedans.
_SFX = ["VROUM !", "CLIC", "BIIIP !", "BAM !", "CRAC !", "AÏE !"]
# Onomatopée inventée, hors bibliothèque (une par réponse quand le contexte en a une) : le moteur la retire
# avec un avertissement visible, ce que le mode mock permet de vérifier.
MOCK_OFF_LIBRARY = "FROU"
MOCK_DA_OFF_LIBRARY = "KARI"


def _sfx_words(ctx: dict[str, Any], fallback: list[str]) -> list[str]:
    """Onomatopées permises du contexte, une sur deux étirée ou criée (« BOUUUM ! », « CLIC ! »)."""
    library = [str(w) for w in ctx.get("sfx_library") or [] if w]
    if not library:
        return fallback
    return [_stretch(w) if k % 2 else w for k, w in enumerate(library)]


def _stretch(word: str) -> str:
    """Variante permise : dernière voyelle triplée et « ! » (« BOUM » → « BOUUUM ! »)."""
    for k in range(len(word) - 1, -1, -1):
        if word[k] in "AEIOUY":
            return f"{word[: k + 1]}{word[k] * 2}{word[k + 1 :]} !"
    return f"{word} !"


def _script_context(messages: list[ChatMessage]) -> dict[str, Any] | None:
    ctx = _task_context(messages)
    return ctx if ctx is not None and ctx.get("task") == "script" else None


def _task_context(messages: list[ChatMessage]) -> dict[str, Any] | None:
    for m in messages:
        if m.role != "user":
            continue
        match = _CONTEXT.search(m.content)
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) and data.get("task") in TASKS else None
    return None


def _sentences(text: str) -> list[str]:
    text = _ID_INVALID_MARK.sub("", _DA_INVALID_MARK.sub("", _INVALID_MARK.sub("", text)))
    text = _NO_ESTABLISHING_MARK.sub("", _SPARSE_MARK.sub("", text))
    text = _SCENE_PAGES_MARK.sub("", _SCENES_INVALID_MARK.sub("", text))
    text = _NO_CLOSE_UP_MARK.sub("", _MULTI_ACTION_MARK.sub("", text))
    text = _DIRTY_BRIEF_MARK.sub("", text)
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+|\n+", text) if p.strip()]
    return parts or ["La scène s'installe."]


_SETTINGS = [
    "clairière au bord d'un lac, fin d'après-midi, herbes hautes, rochers moussus, montagnes au loin",
    "falaise battue par le vent, aube grise, nuages bas, mer agitée en contrebas",
    "village de pierre, midi, ruelles pavées, linge aux fenêtres, foule de marché",
    "forêt dense, nuit de pleine lune, troncs immenses, lucioles, brume au sol",
]
# Lieux du découpage factice (un par série de trois pages), dans l'ordre de `_SETTINGS`.
_LIEUX = ["La clairière", "La falaise", "Le village", "La forêt"]
_PAGES_PER_PLACE = 3
# Ce que fait chaque personnage (geste, posture, regard), jamais sa place dans le cadre : le scénario ne
# compose pas, la direction artistique cadre.
_GESTURES = [
    "avance d'un pas décidé",
    "se penche, la main tendue",
    "recule, les épaules crispées",
    "se retourne vivement",
]


def _staging(who: str, other: str, i: int) -> str:
    if other == who:
        return f"{who} {_GESTURES[i % len(_GESTURES)]}, regard vers l'horizon"
    return (
        f"{who} {_GESTURES[i % len(_GESTURES)]}, tourné vers {other} ; "
        f"{other} {_GESTURES[(i + 2) % len(_GESTURES)]}, lui répond d'un geste"
    )


def _plain_words(text: str) -> set[str]:
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()
    return set(re.findall(r"\w+", plain))


def _lieu_named(text: str, lieux: dict[str, int]) -> int | None:
    """Lieu de la série que la phrase nomme en entier (« Aiko arrive au dojo » → « Le dojo ») : la case s'y passe."""
    words = _plain_words(text)
    for name, lieu_id in lieux.items():
        keys = [w for w in _plain_words(name) if len(w) >= 4]
        if keys and all(k in words or f"{k}s" in words for k in keys):
            return lieu_id
    return None


def _short(text: str, limit: int = _MOCK_WORDS) -> str:
    words = text.split()
    return " ".join(words[:limit]) + ("…" if len(words) > limit else "")


def mock_script(ctx: dict[str, Any], *, sparse: bool = False) -> dict[str, Any]:
    """Découpage factice ; `sparse` : dialogues maigres (une réplique sur deux cases, combat muet)."""
    chapter = ctx.get("chapter") or {}
    names = [c["name"] for c in ctx.get("characters") or [] if c.get("name")] or ["Héros", "Rival"]
    beats = _sentences(str(chapter.get("synopsis") or ""))
    n_pages = max(1, min(40, int(chapter.get("target_pages") or 15)))
    # Scènes validées : autant de pages que leur somme, chaque page dans sa scène.
    scenes = [s for s in ctx.get("scenes") or [] if isinstance(s, dict) and int(s.get("pages") or 0) > 0]
    page_scene = [int(s["number"]) for s in scenes for _ in range(int(s["pages"]))]
    # Name scène par scène : seulement la scène demandée, d'après son résumé.
    focus = ctx.get("scene") if isinstance(ctx.get("scene"), dict) else None
    profile = (focus or {}).get("profile") or {}
    offset = 0
    if focus:
        page_scene = [int(focus["number"])] * max(1, int(focus.get("pages") or 1))
        offset = int(focus.get("first_page") or 1) - 1
        beats = _sentences(str(focus.get("summary") or "")) or beats
    if page_scene:
        n_pages = len(page_scene)
    # Une scène compte la moyenne de mots sur peu de répliques : répliques plus courtes.
    words = 6 if focus else _MOCK_WORDS
    previous = ctx.get("previous_chapters") or []
    decors = [d["id"] for d in ctx.get("decors") or [] if isinstance(d.get("id"), int)]
    objets = [o["id"] for o in ctx.get("objets") or [] if isinstance(o.get("id"), int)]
    known = {
        str(e.get("name") or "").casefold(): e["id"] for e in ctx.get("lieux") or [] if isinstance(e.get("id"), int)
    }
    charter = ctx.get("pre_direction") or {}
    lo = int((charter.get("panels") or {}).get("min_per_page") or 1)
    hi = int((charter.get("panels") or {}).get("max_per_page") or 9)
    counts = [c for c in _PANELS_PER_PAGE if lo <= c <= hi]
    if len(set(counts)) < 2:
        # Au plus 6 cases : au-delà, les répliques factices ne tiennent plus dans les petites cases.
        counts = list(range(lo, max(lo, min(hi, 6)) + 1))
    # Peu de planches à grande case voulues : pas de page de 5 cases (tous ses gabarits ont une grande case).
    big_max = float(((charter.get("shapes") or {}).get("big_panel_share") or {}).get("max", 1))
    if big_max < 0.7 and 5 in counts:
        others = [c for c in counts if c != 5]
        counts = others if len(set(others)) >= 2 else [c for c in range(lo, min(hi, 7) + 1) if c != 5] or counts
    pages = []
    beat = 0
    sfx_words = _sfx_words(ctx, _SFX)
    off_library = ctx.get("sfx_library") is not None  # une onomatopée inventée, retirée par le moteur
    narration_max = profile.get("narration.max_per_page")
    opening = (not focus or int(focus.get("number") or 1) == 1) and narration_max != 0
    for p in range(n_pages):
        panels = []
        # Pleine page : la révélation finit sur sa grande case ; une autre scène garde ses cases par planche.
        full = (focus.get("type") == "revelation" and p == n_pages - 1) if focus else (p == n_pages - 1 and n_pages > 2)
        count = 1 if full else counts[p % len(counts)]
        for i in range(count):
            text = beats[beat % len(beats)]
            beat += 1
            who = names[(p + i) % len(names)]
            other = names[(p + i + 1) % len(names)]
            importance = 3 if count == 1 or (i == 0 and p % 2 == 0) else (1 if i == count - 1 else 2)
            # Indices de mise en page : une case forte sur deux est un temps d'action, les cases de
            # transition sont calmes.
            intensity = "choc" if importance == 3 and p % 4 != 2 else ("calme" if importance == 1 else "normal")
            cast = [who] if i % 2 else list(dict.fromkeys([who, other]))
            dialogues = []
            if sparse:
                if (p + i) % 2 == 0 and intensity != "choc":
                    dialogues.append({"speaker": who, "text": _short(text, words), "kind": "speech"})
            else:
                kind = "shout" if intensity == "choc" else _KINDS[(p + i) % len(_KINDS)]
                first = _SHOUTS[(p + i) % len(_SHOUTS)] if intensity == "choc" else _short(text, words)
                dialogues.append({"speaker": who, "text": first, "kind": kind})
                if count <= 4 or importance == 3:  # place : une seule réplique sur une page chargée
                    reply = _REPLIES[(p + i) % len(_REPLIES)] if intensity != "choc" else _short(text, words)
                    # Seul dans la case : il se parle à lui-même (pensée).
                    alone = len(cast) == 1 and kind != "thought"
                    dialogues.append({"speaker": cast[-1], "text": reply, "kind": "thought" if alone else "speech"})
                if i == 0 and p == 0 and opening:
                    dialogues.insert(
                        0, {"speaker": "", "text": f"Chapitre {chapter.get('number', '?')}.", "kind": "narration"}
                    )
            sfx = []
            if intensity == "choc":
                sfx.append({"text": sfx_words[(p + i) % len(sfx_words)], "intensity": "choc"})
                if off_library:
                    sfx.append({"text": MOCK_OFF_LIBRARY, "intensity": "choc"})
                    off_library = False
            elif intensity == "calme" and p % 3 == 1:
                sfx.append({"text": "TIC TAC…", "intensity": "calme"})
            place = ((p + offset) // _PAGES_PER_PLACE) % len(_LIEUX)
            panels.append(
                {
                    "description": f"{text} ({who}{' et ' + other if other != who else ''}, page {p + offset + 1}, "
                    f"case {i + 1})",
                    # Le lieu que la phrase nomme, sinon celui de la série de pages (lieu cohérent avec la description).
                    "lieu": _lieu_named(text, known) or known.get(_LIEUX[place].casefold(), _LIEUX[place]),
                    "setting": _SETTINGS[place],
                    "staging": _staging(cast[0], cast[-1], i),
                    "characters": cast,
                    "importance": importance,
                    "intensity": intensity,
                    "dialogues": dialogues,
                    "sfx": sfx,
                    "decor": decors[p % len(decors)] if decors else None,
                    "objets": [objets[(p + i // 2) % len(objets)]] if objets and i % 2 == 0 else [],
                }
            )
        pages.append({"rythme": _RYTHMES[p % len(_RYTHMES)], "panels": panels})
        if page_scene:
            pages[-1]["scene"] = page_scene[p]
    if charter and not sparse:
        _script_charter(pages, charter)
    recap = f" Suite du chapitre {previous[-1]['number']}." if previous else ""
    summary = f"Chapitre {chapter.get('number', '?')} — {' '.join(beats)[:400]}{recap}"
    return {"pages": pages, "summary": summary}


def dirty_brief(out: dict[str, Any], names: list[str]) -> None:
    """Défauts du brief d'image relevés par l'audit de « Second round » (18/10), sur les premières cases à
    personnage : plan et personnage absent dans le décor (« Plan américain sur Tora, Haru en arrière-plan »), un
    hors cadre qui agit dans la mise en scène, un décor sans aucun mot de décor."""
    panels = [pa for page in out["pages"] for pa in page["panels"] if pa["characters"]]
    for k, pa in enumerate(panels[:3]):
        who = pa["characters"][0]
        absent = next((n for n in names if n not in pa["characters"]), None)
        if k == 0 and absent:
            pa["setting"] = f"Plan américain sur {who}, {absent} en arrière-plan"
        elif k == 1 and absent:
            pa["offscreen"] = [absent]
            pa["staging"] = f"{pa['staging']} ; {absent} le regarde, déglutissant"
        else:
            pa["setting"] = f"{who} concentré, la mèche collée sur le front"


def _replies(panels: list[dict[str, Any]]) -> int:
    return sum(len(pa["dialogues"]) for pa in panels)


def _script_charter(pages: list[dict[str, Any]], charter: dict[str, Any]) -> None:
    """Charte de la série : une case muette par planche (la plus calme, jamais une case d'action), répliques
    comptées par planche (des réactions courtes ajoutées là où la place le permet, des secondes répliques
    retirées au-delà du plafond), et des cases de décor sans personnage si le genre en demande."""
    dialogue = charter.get("dialogue") or {}
    low, high = int(dialogue.get("min_per_page") or 0), int(dialogue.get("max_per_page") or 99)
    silent = int(dialogue.get("min_silent_panels") or 0)
    empty = float(((charter.get("presence") or {}).get("empty") or {}).get("min") or 0)
    # Cases de décor muettes (famille « places ») : des cases sans personnage, prises parmi les cases muettes.
    empty = max(empty, float((charter.get("places") or {}).get("silent_decor_min") or 0))
    empties = math.ceil(empty * sum(len(p["panels"]) for p in pages) - 1e-9)
    for page in pages:
        panels = page["panels"]
        n = len(panels)
        if silent and n >= 2:
            quiet = [pa for pa in reversed(panels) if pa["intensity"] != "choc" and pa["importance"] < 3]
            for pa in quiet[:silent]:
                pa["dialogues"], pa["sfx"] = [], []
                if empties > 0:
                    pa.update(characters=[], staging="", description=f"Le décor seul : {pa['setting']}.")
                    empties -= 1
        room = 3 if n <= 4 else 2 if n <= 6 else 1
        if n >= 7:  # petites cases : répliques de quatre mots au plus
            for pa in panels:
                for d in pa["dialogues"]:
                    words = d["text"].split()
                    d["text"] = " ".join(words[:4]) + ("…" if len(words) > 4 else "")

        for pa in reversed(panels):
            while len(pa["dialogues"]) > 1 and _replies(panels) > high:
                pa["dialogues"].pop()
        # Toujours trop (scène presque muette : poursuite, combat) : des cases calmes se taisent, jamais une case
        # d'action.
        for pa in reversed(panels):
            if _replies(panels) <= high:
                break
            if pa["intensity"] != "choc" and not pa["sfx"]:
                pa["dialogues"] = []
        for k, pa in enumerate(panels):
            cap = min(2, room + (1 if pa["importance"] >= 3 else 0))
            while pa["dialogues"] and pa["characters"] and len(pa["dialogues"]) < cap and _replies(panels) < low:
                who = pa["characters"][-1]
                pa["dialogues"].append({"speaker": who, "text": _REPLIES[k % len(_REPLIES)], "kind": "speech"})


# --- direction artistique ---------------------------------------------------------
_DA_RYTHMES = ["montée", "respiration", "montée", "climax"]
_DA_PLANS = ["plan large", "plan moyen", "plan rapproché", "gros plan", "contre-plongée", "insert", "plongée"]
# Angles en alternance hauteur d'œil / hors hauteur d'œil, deux voisins jamais identiques (bouclage
# compris) : jamais deux cases d'affilée au même angle, une case hors hauteur d'œil par paire de cases,
# peu de cases de face (variety_rules de prompts/direction-artistique.yaml).
_DA_ANGLES = [
    "de trois quarts",
    "en contre-plongée",
    "de profil",
    "en plongée",
    "de face",
    "cadre penché",
    "de dos",
    "en contre-plongée",
]
_DA_ANGLES_SOBRE = ["de trois quarts", "en plongée", "de profil", "en contre-plongée", "de face", "en plongée"]
# Actions des cases (mouvement ou pose du corps), précédées du nom du premier personnage de la case.
_DA_ACTIONS = [
    "bondit en avant, le bras tendu vers le bord du cadre",
    "se retourne brusquement, les épaules crispées et le manteau qui virevolte",
    "s'accroupit pour ramasser un objet, une main au sol pour garder l'équilibre",
    "court à travers le cadre, penché en avant, les cheveux fouettés par le vent",
    "recule d'un pas, la main levée en garde devant le visage",
    "se penche par-dessus la table, les deux poings serrés sur le bord",
    "pivote sur un pied, le poids rejeté en arrière, prêt à frapper",
    "tend la main vers son interlocuteur, le corps tourné à moitié vers lui",
]
_DA_AMBIANCES = [
    "lumière froide du petit matin, ombres longues",
    "contre-jour orangé, silhouettes découpées",
    "pénombre, reflets de néons sur le sol mouillé",
    "pluie battante, contours noyés",
    "soleil de midi, ombres dures et nettes",
    "brume légère, arrière-plan estompé",
]
_DA_SFX = ["BAM", "VLAN", "WHOOSH", "CLAC", "BOUM", "TCHAC"]
_RYTHME_PHRASES = {
    "calme": "Page d'installation : on laisse respirer le décor et les personnages.",
    "montée": "La tension monte : les cadrages se resserrent au fil des cases.",
    "climax": "Sommet de la séquence : on frappe fort, avec des cases très contrastées.",
    "respiration": "Respiration après l'action : plans plus larges et lecture apaisée.",
}
_BOLDNESS = {"sobre": 0, "equilibree": 1, "audacieuse": 2}


def _establishing(pages: list[dict[str, Any]], previous: Any = None) -> set[tuple[int, int]]:
    """(page, case) des premières cases d'un nouveau lieu (unité de lieu `lieu` des cases), dans l'ordre ; `previous` :
    lieu de la dernière case d'avant (scène dirigée seule)."""
    out: set[tuple[int, int]] = set()
    for page in pages:
        for i, pa in enumerate(page.get("panels") or []):
            lieu = pa.get("lieu")
            if lieu is None:
                continue
            if lieu != previous:
                out.add((int(page["page"]), i))
            previous = lieu
    return out


_FIXED = "_etablissement"  # case d'établissement : son plan large ne bouge plus (retiré de la réponse)


def mock_art_direction(ctx: dict[str, Any], *, establish: bool = True) -> dict[str, Any]:
    """Choix plausibles, variés d'une page à l'autre et déterministes (chapitre, audace, relance). `establish` : la
    première case d'un nouveau lieu passe en plan large (case d'établissement de la charte)."""
    bold = _BOLDNESS.get(str(ctx.get("variety") or "equilibree"), 1)
    variant = int(ctx.get("variant") or 0)
    number = int((ctx.get("chapter") or {}).get("number") or 1)
    styles = ctx.get("styles") or []
    pages = ctx.get("pages") or []
    previous = ctx.get("previous_direction") or {}
    prev_chocs = {p.get("page") for p in previous.get("pages") or [] if p.get("page_choc")}
    angles = _DA_ANGLES if bold else _DA_ANGLES_SOBRE
    out = []
    last = max((int(p["page"]) for p in pages), default=1)
    charter = ctx.get("pre_direction") or {}
    scene = ctx.get("scene") if isinstance(ctx.get("scene"), dict) else None
    whole = bool(charter) and (len(pages) >= int(charter.get("min_pages") or 4) or scene is not None)
    curve = _curve(len(pages), charter) if whole and scene is None else None
    if scene is not None:
        curve = _scene_curve(len(pages), charter, scene, ctx.get("before_rythmes") or [])
    places = (charter.get("places") or {}) if whole else {}
    opening = _establishing(pages, ctx.get("previous_location")) if establish and places.get("establishing") else set()
    sfx_words = _sfx_words(ctx, _DA_SFX)
    off_library = ctx.get("sfx_library") is not None  # une onomatopée inventée, retirée par le moteur
    for index, page in enumerate(pages):
        n = int(page["page"])
        seed = n * 7 + number * 3 + variant * 5
        if curve is not None:
            rythme = curve[index]
        elif variant == 0 and n == 1:
            rythme = "calme"
        elif variant == 0 and n == last and last > 1:
            rythme = "climax"
        else:
            rythme = _DA_RYTHMES[seed % len(_DA_RYTHMES)]
        panels = page.get("panels") or []
        count = len(panels)
        strongest = max(range(count), key=lambda i: (panels[i].get("importance") or 2, -i)) if count else 0
        out_panels = []
        for i, pa in enumerate(panels):
            if i == strongest and (rythme in ("montée", "climax") or bold == 2):
                intensity = "choc"
            elif (pa.get("importance") or 2) <= 1 or rythme in ("calme", "respiration"):
                intensity = "calme"
            else:
                intensity = "normal"
            shot = pa.get("shot_type")
            plan = shot if shot in _DA_PLANS and (seed + i) % 3 else _DA_PLANS[(seed + i) % len(_DA_PLANS)]
            if intensity == "choc" and bold:
                plan = "gros plan" if seed % 2 else "contre-plongée"
            cadre = "normal"
            if intensity == "choc" and bold:
                cadre = "sans bord" if bold == 1 else "débordement"
            if len(out_panels) >= 2 and out_panels[-1]["plan"] == out_panels[-2]["plan"] == plan:
                plan = next(p for p in _DA_PLANS[(seed + i) % len(_DA_PLANS) :] + _DA_PLANS if p != plan)
            fixed = (n, i) in opening
            if fixed:
                plan = "plan large"  # case d'établissement : installe le nouveau lieu
            # Spectateur repéré : vue subjective s'il y a quelque chose d'autre à voir, sinon plan de réaction.
            viewers = [str(v) for v in pa.get("spectators") or []]
            others = [c for c in pa.get("characters") or [] if c not in viewers]
            point_de_vue = ("vue subjective" if others else "plan de réaction") if viewers else None
            cast = others if point_de_vue == "vue subjective" else list(pa.get("characters") or [])
            who = next(iter(cast), None)
            action = _DA_ACTIONS[(seed + i) % len(_DA_ACTIONS)]
            sfx = []
            if intensity == "choc":
                sfx.append({"text": sfx_words[(seed + i) % len(sfx_words)], "intensity": "fort"})
                if off_library:
                    sfx.insert(0, {"text": MOCK_DA_OFF_LIBRARY, "intensity": "fort"})
                    off_library = False
            out_panels.append(
                {
                    "panel": i + 1,
                    "intensity": intensity,
                    "plan": plan,
                    "angle": angles[(seed + i) % len(angles)],
                    "cadre": cadre,
                    "ambiance": _DA_AMBIANCES[(seed + i) % len(_DA_AMBIANCES)],
                    "action": f"{who} {action}" if who else action[:1].upper() + action[1:],
                    "sfx": sfx,
                    **({"point_de_vue": point_de_vue, "spectateurs": viewers} if point_de_vue else {}),
                    **({_FIXED: True} if fixed else {}),
                }
            )
        page_choc = None
        if rythme == "climax" and bold and (n not in prev_chocs or variant):
            page_choc = "pleine page" if count == 1 else "splash"
        template = None
        has_choc = any(p["intensity"] == "choc" for p in out_panels)
        if has_choc and count > 1:
            wanted = (
                f"{count}-grand-haut" if strongest == 0 else f"{count}-grand-bas" if strongest == count - 1 else None
            )
            if wanted in (page.get("templates") or []):
                template = wanted
        layout_style = "nerveuse" if bold == 2 and rythme == "climax" and "nerveuse" in styles else None
        strong = out_panels[strongest] if out_panels else None
        rationale = _RYTHME_PHRASES[rythme]
        if strong is not None and strong["intensity"] == "choc":
            rationale += f" La case {strongest + 1} porte le temps fort : {strong['plan']} {strong['angle']}"
            rationale += f", {strong['cadre']}." if strong["cadre"] != "normal" else "."
        if page_choc:
            rationale += f" Page choc en {page_choc} pour marquer le sommet du chapitre."
        if n in prev_chocs and rythme == "climax" and not page_choc:
            rationale += " Pas de page choc ici : le chapitre précédent en avait déjà une au même endroit."
        out.append(
            {
                "page": n,
                "rythme": rythme,
                "layout_style": layout_style,
                "template": template,
                "page_choc": page_choc,
                "rationale": rationale,
                "panels": out_panels,
            }
        )
    _limit_frontal(out)
    _tighten(out, ctx.get("variety_rules") or {})
    if ctx.get("page_rules"):
        _page_rules(out, ctx["page_rules"], ctx.get("variety_rules") or {})
    if whole:
        _shapes(out, pages, charter)
        _shot_scale(out, charter, ctx.get("variety_rules") or {}, ctx.get("page_rules") or {})
    for p in out:
        for pa in p["panels"]:
            pa.pop(_FIXED, None)
    return {"pages": out}


def _scene_curve(n: int, charter: dict[str, Any], scene: dict[str, Any], before: list[Any]) -> list[str]:
    """Rythmes d'une scène dirigée seule : une respiration juste après un pic (pages d'avant comprises), un pic en
    fin de scène d'action ou de révélation, sinon calme ou montée selon le type."""
    peaks = list(charter.get("peak_rythmes") or ["climax"])
    breath = (charter.get("breath_rythmes") or ["respiration"])[0]
    kind = str(scene.get("type") or "")
    out: list[str] = []
    previous = before[-1] if before else None
    for i in range(n):
        if previous in peaks:
            r = breath
        elif kind in ("combat", "poursuite", "revelation", "sport_collectif") and i == n - 1:
            r = peaks[0]
        elif kind == "calme":
            r = "calme"
        else:
            r = "montée"
        out.append(r)
        previous = r
    return out


def _window(n: int, charter: dict[str, Any]) -> list[int]:
    first = (charter.get("rhythm") or {}).get("first_peak") or {}
    low, high = float(first.get("min", 0)), float(first.get("max", 1))
    return [i for i in range(n) if i / n <= high + 1e-9 and (i + 1) / n >= low - 1e-9]


def _curve(n: int, charter: dict[str, Any]) -> list[str]:
    """Courbe de rythme de la charte : installation, premier pic dans la fenêtre visée, respiration juste après,
    montées et respirations en alternance, pic final."""
    rhythm = charter.get("rhythm") or {}
    peak = (charter.get("peak_rythmes") or ["climax"])[0]
    breath = (charter.get("breath_rythmes") or ["respiration"])[0]
    window = _window(n, charter)
    first = next((i for i in window if i > 0), window[0] if window else min(1, n - 1))
    out = ["calme", *(["montée"] * (n - 1))]
    for i in range(first + 2, n):
        out[i] = "montée" if (i - first) % 2 == 0 else breath
    if rhythm.get("final_peak_last_pages"):
        out[n - 1] = peak
        if n - 2 > first + 1 and out[n - 2] == peak:
            out[n - 2] = "montée"
    out[first] = peak
    if first + 1 < n and out[first + 1] != peak:
        out[first + 1] = breath
    return out


def _shapes(pages: list[dict[str, Any]], briefs: list[dict[str, Any]], charter: dict[str, Any]) -> None:
    """Formes de planche : un gabarit explicite par page, à grande case ou non selon la part visée, jamais le même
    que la page précédente."""
    big_templates = set(charter.get("big_templates") or [])
    share = (charter.get("shapes") or {}).get("big_panel_share") or {}
    n = len(pages)
    need = math.ceil(float(share.get("min", 0)) * n - 1e-9)
    high = float(share.get("max", 1))
    allowed = max(1, math.floor(high * n + 1e-9)) if high > 0 else 0
    templates = {int(b["page"]): list(b.get("templates") or []) for b in briefs}

    def is_big(p: dict[str, Any]) -> bool:
        """Grande case quoi qu'on choisisse : page choc, pleine page, ou aucun gabarit sans grande case."""
        options = templates[p["page"]]
        return (
            bool(p["page_choc"]) or len(p["panels"]) == 1 or bool(options) and all(t in big_templates for t in options)
        )

    want = [is_big(p) or any(pa["intensity"] == "choc" for pa in p["panels"]) for p in pages]
    flexible = [
        i for i, p in enumerate(pages) if not is_big(p) and any(t in big_templates for t in templates[p["page"]])
    ]
    for i in flexible:
        if sum(want) >= need:
            break
        want[i] = True
    for i in reversed(range(n)):
        if sum(want) <= allowed:
            break
        if want[i] and not is_big(pages[i]) and any(t not in big_templates for t in templates[pages[i]["page"]]):
            want[i] = False
    in_a_row = int((charter.get("shapes") or {}).get("max_same_in_a_row") or 1)
    previous, run = None, 0
    for p, big in zip(pages, want, strict=True):
        if p["page_choc"]:
            previous, run = None, 0
            continue
        every = templates[p["page"]]
        options = [t for t in every if (t in big_templates) == big] or every
        if run >= in_a_row:  # la même forme une fois de trop : un autre gabarit
            options = [t for t in options if t != previous] or [t for t in every if t != previous] or options
        if options:
            p["template"] = p["template"] if p["template"] in options else options[0]
        run = run + 1 if p["template"] == previous else 1
        previous = p["template"]

    def shape(p: dict[str, Any]) -> str:
        return f"choc:{p['page_choc']}" if p["page_choc"] else str(p["template"])

    def longest() -> int:
        best = run = 0
        for i, p in enumerate(pages):
            run = run + 1 if i and shape(p) == shape(pages[i - 1]) else 1
            best = max(best, run)
        return best

    # Trop de grandes cases malgré tout (une suite trop longue a imposé un autre gabarit) : des pages repassent
    # en gaufrier, tant que la suite de même forme reste permise.
    for p in pages:
        big = sum(1 for q in pages if is_big(q) or q["template"] in big_templates)
        if big <= allowed:
            break
        if is_big(p) or p["template"] not in big_templates:
            continue
        before = p["template"]
        for t in (t for t in templates[p["page"]] if t not in big_templates):
            p["template"] = t
            if longest() <= in_a_row:
                break
            p["template"] = before


# Plans de rechange d'une famille (jamais deux plans identiques côte à côte : gros plan, puis très gros plan).
_CLASS_PLANS = {"close_up": ["gros plan", "très gros plan"]}
_CLASS_PLAN = {
    "wide": "plan large",
    "medium": "plan moyen",
    "medium_close": "plan rapproché",
    "close_up": "gros plan",
    "insert": "insert",
}


def _shot_scale(
    pages: list[dict[str, Any]], charter: dict[str, Any], variety: dict[str, Any], page_rules: dict[str, Any]
) -> None:
    """Échelle des plans de la charte : chaque famille de plans ramenée dans sa part (au-dessus du plafond, des
    cases passent dans une famille qui a de la place ; sous le plancher, elles viennent d'une famille en surplus),
    plans serrés sous leur plafond (« élargis ») et plans larges et moyens sous celui de variety_rules. Une page
    garde son plan serré, son gros plan et sa case hors hauteur d'œil ; jamais deux plans identiques côte à côte."""
    classes = {k: set(v) for k, v in (charter.get("shot_classes") or {}).items()}
    shots = charter.get("shots") or {}
    tight = ("close_up", "medium_close", "insert")
    close_plans = set(page_rules.get("close_plans") or ["gros plan", "très gros plan", "insert"])
    off_level = set(variety.get("off_eye_level") or [])
    wide_medium = set(variety.get("wide_medium_plans") or [])
    total = sum(len(p["panels"]) for p in pages)
    loose_cap = math.floor(float(variety.get("max_wide_medium_share", 1)) * total + 1e-9)

    def cls(plan: str) -> str | None:
        return next((c for c, plans in classes.items() if plan in plans), None)

    def count(*names: str | None) -> int:
        return sum(1 for p in pages for pa in p["panels"] if cls(pa["plan"]) in names)

    def low(name: str) -> int:
        return math.ceil(float((shots.get(name) or {}).get("min", 0)) * total - 1e-9)

    def high(name: str) -> int:
        share = float((shots.get(name) or {}).get("max", 1))
        return max(1, math.floor(share * total + 1e-9)) if share > 0 else 0

    tight_cap = max(1, math.floor(float(shots.get("tight_max", 1)) * total + 1e-9))

    def legal(panels: list[dict[str, Any]], i: int, plan: str) -> bool:
        after = [plan if j == i else q["plan"] for j, q in enumerate(panels)]
        if any(after[j] == plan for j in (i - 1, i + 1) if 0 <= j < len(after)):
            return False
        if len(panels) >= 3 and not any(cls(x) in tight for x in after):
            return False
        if len(panels) >= 3 and not any(x in close_plans for x in after):
            return False
        return not off_level or any(
            x in off_level or q["angle"] in off_level for x, q in zip(after, panels, strict=True)
        )

    def move(donors: tuple[str | None, ...], target: str, done: Any) -> None:
        for plan in _CLASS_PLANS.get(target, [_CLASS_PLAN[target]]):
            _move(donors, target, done, plan)

    def _move(donors: tuple[str | None, ...], target: str, done: Any, plan: str) -> None:
        for calm_first in (True, False):
            for p in pages:
                for i, pa in enumerate(p["panels"]):
                    if done():
                        return
                    source = cls(pa["plan"])
                    if pa.get(_FIXED) or source not in donors or (calm_first and pa["intensity"] == "choc"):
                        continue
                    if source is not None and count(source) - 1 < low(source):
                        continue
                    if target in tight and source not in tight and count(*tight) + 1 > tight_cap:
                        continue
                    if plan in wide_medium and pa["plan"] not in wide_medium:
                        loose = sum(1 for q in pages for x in q["panels"] if x["plan"] in wide_medium)
                        if loose + 1 > loose_cap:
                            continue
                    if count(target) + 1 > high(target) or not legal(p["panels"], i, plan):
                        continue
                    pa["plan"] = plan

    for _ in range(2):
        # Plafonds : plans serrés en trop → plan moyen ou large (« élargis ») ; famille en trop → une autre.
        for target in ("medium", "wide"):
            move(tight, target, lambda: count(*tight) <= tight_cap)
        for name in _CLASS_PLAN:
            others = tuple(c for c in _CLASS_PLAN if c != name)
            for target in others:
                move((name,), target, lambda name=name: count(name) <= high(name))
        # Planchers : d'abord depuis une famille en surplus, puis depuis les plans hors famille (plongées).
        for name in _CLASS_PLAN:
            donors = (*(c for c in _CLASS_PLAN if c != name), None)
            move(donors, name, lambda name=name: count(name) >= low(name))


def _page_rules(pages: list[dict[str, Any]], rules: dict[str, Any], variety: dict[str, Any]) -> None:
    """Règles par planche (page_rules) : un gros plan et une case calme par page dès 3 cases, pas plus de 3 cases
    « choc » d'affilée. Le gros plan remplace un plan à hauteur d'œil (la case hors hauteur d'œil reste), sans
    répéter le plan d'une voisine ; la case calme est la moins importante qui n'est pas le temps fort."""
    close = list(rules.get("close_plans") or ["gros plan", "très gros plan", "insert"])
    off_level = set(variety.get("off_eye_level") or ["plongée", "contre-plongée"])
    calm = (rules.get("calm_intensities") or ["calme"])[0]
    for p in pages:
        panels = p["panels"]
        n = len(panels)
        close_rule = rules.get("min_close_per_page", 1) and n >= int(rules.get("close_min_panels") or 3)
        if close_rule and not any(pa["plan"] in close for pa in panels):
            order = sorted(range(n), key=lambda i: (panels[i]["intensity"] != "choc", i == 0, -i))
            for i in order:
                if panels[i]["plan"] in off_level or panels[i].get(_FIXED):
                    continue
                near = {q["plan"] for q in panels[max(0, i - 1) : i + 2] if q is not panels[i]}
                plan = next((c for c in close if c not in near), None)
                if plan is not None:
                    panels[i]["plan"] = plan
                    break
        calm_rule = rules.get("min_calm_per_page", 1) and n >= int(rules.get("calm_min_panels") or 3)
        if calm_rule and not any(pa["intensity"] == calm for pa in panels):
            i = next((j for j in reversed(range(n)) if panels[j]["intensity"] != "choc"), n - 1)
            panels[i].update(intensity=calm, cadre="normal", sfx=[])
    limit = int(rules.get("max_choc_in_a_row") or 0)
    run = 0
    for p in pages:
        for pa in p["panels"]:
            run = run + 1 if pa["intensity"] == "choc" else 0
            if limit and run > limit:
                pa.update(intensity="normal", cadre="normal", sfx=[])
                run = 0


_DA_TIGHT = ["gros plan", "plan rapproché", "insert"]


def _tighten(pages: list[dict[str, Any]], rules: dict[str, Any]) -> None:
    """Échelle des plans (variety_rules) : pas deux plans larges d'affilée, un plan serré par page dès 3 cases,
    au plus la moitié de plans larges et moyens sur le chapitre. Seuls des plans larges ou moyens deviennent
    serrés (jamais une plongée : la case hors hauteur d'œil reste), sans répéter le plan d'une voisine."""
    wide = set(rules.get("wide_plans") or ["plan large", "plan d'ensemble"])
    loose = set(rules.get("wide_medium_plans") or ["plan large", "plan d'ensemble", "plan moyen"])
    tight = set(rules.get("tight_plans") or _DA_TIGHT)
    in_a_row = int(rules.get("max_wide_in_a_row") or 1)
    min_panels = int(rules.get("tight_min_panels") or 3)
    min_tight = int(rules.get("min_tight_per_page", 1))
    share = float(rules.get("max_wide_medium_share", 0.5))

    def tighten(panels: list[dict[str, Any]], i: int) -> None:
        if panels[i].get(_FIXED):  # case d'établissement : c'est sa voisine qui se resserre
            i = next((j for j in (i - 1, i + 1) if 0 <= j < len(panels) and not panels[j].get(_FIXED)), i)
            if panels[i].get(_FIXED):
                return
        near = {q["plan"] for q in panels[max(0, i - 1) : i + 2]}
        panels[i]["plan"] = next(p for p in _DA_TIGHT if p not in near)

    for p in pages:
        panels = p["panels"]
        run = 0
        for i, pa in enumerate(panels):
            run = run + 1 if pa["plan"] in wide else 0
            if run > in_a_row:
                tighten(panels, i)
                run = 0
        if len(panels) >= min_panels:
            for i in reversed(range(len(panels))):
                if sum(1 for q in panels if q["plan"] in tight) >= min_tight:
                    break
                if panels[i]["plan"] in loose and not panels[i].get(_FIXED):
                    tighten(panels, i)
    total = sum(len(p["panels"]) for p in pages)
    allowed = max(1, int(share * total + 1e-9))
    # La première case d'une page garde son plan d'installation, sauf s'il le faut vraiment.
    for first in (1, 0):
        for p in pages:
            for i in range(len(p["panels"]) - 1, first - 1, -1):
                if sum(1 for q in pages for pa in q["panels"] if pa["plan"] in loose) <= allowed:
                    return
                if p["panels"][i]["plan"] in loose and not p["panels"][i].get(_FIXED):
                    tighten(p["panels"], i)


def _limit_frontal(pages: list[dict[str, Any]], share: float = 0.35) -> None:
    """Pas plus de `share` des cases « de face » sur le chapitre (au moins une) : les dernières en trop
    passent de trois quarts ou de profil, sans répéter l'angle d'une voisine."""
    panels = [pa for p in pages for pa in p["panels"]]
    allowed = max(1, int(share * len(panels) + 1e-9))
    frontal = [pa for pa in panels if pa["angle"] == "de face"]
    for p in pages:
        for i, pa in enumerate(p["panels"]):
            if len(frontal) <= allowed or pa not in frontal:
                continue
            near = {q["angle"] for q in p["panels"][max(0, i - 1) : i + 2]}
            pa["angle"] = next(a for a in ("de trois quarts", "de profil", "de dos") if a not in near)
            frontal.remove(pa)


class MockLLMProvider:
    name = "mock"

    def __init__(self, responder: Responder | None = None, *, invalid_attempts: int = 0) -> None:
        self._responder = responder
        self.invalid_attempts = invalid_attempts
        self.calls: list[list[ChatMessage]] = []
        # Chaque requête telle que reçue (messages, température, mode JSON) : vérifiée par les tests.
        self.requests: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> LLMResult:
        self.calls.append(messages)
        self.requests.append({"messages": list(messages), "temperature": temperature, "json_mode": json_mode})
        if self._responder is not None:
            return LLMResult(text=self._responder(messages, json_mode), model="mock")
        ctx = _task_context(messages) if json_mode else None
        if ctx is not None and ctx.get("task") == "image_prompt_dialog":
            return LLMResult(text=self._dialog_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "cover_prompt":
            return LLMResult(text=json.dumps(mock_cover_prompt(ctx), ensure_ascii=False), model="mock")
        if ctx is not None and ctx.get("task") == "image_prompt":
            return LLMResult(text=self._image_prompt_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "image_prompt_template":
            return LLMResult(text=self._template_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "visual_anchor":
            return LLMResult(text=json.dumps(mock_visual_anchor(ctx), ensure_ascii=False), model="mock")
        if ctx is not None and ctx.get("task") == "back_summary":
            return LLMResult(text=self._summary_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "series_creation":
            return LLMResult(text=self._creator_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "character_draft":
            return LLMResult(text=self._draft_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") in ("palette", "logo"):
            return LLMResult(text=self._identity_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "locations":
            # Import local : pipeline/locations importe ce paquet (ChatMessage, LLMProvider).
            from ...pipeline.locations import heuristic_groups

            return LLMResult(text=json.dumps(heuristic_groups(ctx), ensure_ascii=False), model="mock")
        if ctx is not None and ctx.get("task") == "art_direction":
            return LLMResult(text=self._direction_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "scenes":
            return LLMResult(text=self._scenes_answer(messages, ctx), model="mock")
        if ctx is not None:
            return LLMResult(text=self._script_answer(messages, ctx), model="mock")
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = json.dumps({"mock": True, "echo": last}, ensure_ascii=False) if json_mode else f"[mock] {last}"
        return LLMResult(text=text, model="mock")

    def _script_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _INVALID_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            # Alterne JSON illisible et JSON au mauvais schéma.
            if attempt % 2:
                return "Voici le découpage : pages 1 à 3…"
            return json.dumps({"pages": [{"panels": [{"description": "", "shot_type": "travelling"}]}]})
        mark = _ID_INVALID_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        if mark and attempt <= int(mark.group(1)):
            out = mock_script(ctx)
            out["pages"][0]["panels"][0]["decor"] = UNKNOWN_ID
            return json.dumps(out, ensure_ascii=False)
        mark = _SPARSE_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        sparse = bool(mark) and attempt <= int(mark.group(1))  # type: ignore[union-attr]
        out = mock_script(ctx, sparse=sparse)
        synopsis = str((ctx.get("chapter") or {}).get("synopsis") or "")
        mark = _SCENE_PAGES_MARK.search(synopsis)
        if mark and attempt <= int(mark.group(1)):
            if ctx.get("scene"):
                out["pages"].append(json.loads(json.dumps(out["pages"][-1])))  # une page de trop pour la scène
            else:
                for page in out["pages"]:
                    page["scene"] = 1
        mark = _MULTI_ACTION_MARK.search(synopsis)
        if mark and attempt <= int(mark.group(1)) and out["pages"]:
            out["pages"][0]["panels"][0]["description"] = MULTI_ACTION
        mark = _DIRTY_BRIEF_MARK.search(synopsis)
        if mark and attempt <= int(mark.group(1)):
            dirty_brief(out, [c["name"] for c in ctx.get("characters") or [] if c.get("name")])
        return json.dumps(out, ensure_ascii=False)

    def _image_prompt_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        description = str((ctx.get("panel") or {}).get("description") or "")
        mark = _PROMPT_INVALID_MARK.search(description)
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici le prompt : une belle case…"
            return json.dumps({"prompt": "Une case.", "language": "klingon"})
        out = mock_image_prompt(ctx)
        intruder = _PROMPT_INTRUDER_MARK.search(description)
        absent = list(ctx.get("absent_characters") or [])
        if intruder and absent and attempt <= int(intruder.group(1)):
            out["prompt"] = f"{out['prompt']} {absent[0]} watches the scene from the edge of the frame."
        return json.dumps(out, ensure_ascii=False)

    def _template_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        description = str((ctx.get("panel") or {}).get("description") or "")
        mark = _TEMPLATE_INVALID_MARK.search(description)
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return json.dumps(
                    {"action": " ".join(["Aiko runs across the frame, seen through a telephoto lens."] * 8)}
                )
            return "Voici l'action : ils courent…"
        return json.dumps(mock_template_action(ctx), ensure_ascii=False)

    def _dialog_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _DIALOG_INVALID_MARK.search(str(ctx.get("instruction") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                out = mock_dialog(ctx)
                out["direction"] = {"plan": "plan drone"}
                return json.dumps(out, ensure_ascii=False)
            return "Voici le nouveau prompt : plus serré…"
        return json.dumps(mock_dialog(ctx), ensure_ascii=False)

    def _draft_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        texts = " ".join(str(p.get("description") or "") for p in ctx.get("panels") or [])
        mark = _DRAFT_INVALID_MARK.search(texts)
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici la fiche : un garde assez grand…"
            return json.dumps({"age": "trentaine", "description": ""})
        return json.dumps(mock_character_draft(ctx), ensure_ascii=False)

    def _identity_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _IDENTITY_INVALID_MARK.search(str(ctx.get("title") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici quelques idées de couleurs : du rouge, du bleu…"
            key = "palettes" if ctx["task"] == "palette" else "concepts"
            return json.dumps({key: [{"name": "Trop court", "colors": [{"role": "dominante", "hex": "rouge"}]}]})
        out = mock_palettes(ctx) if ctx["task"] == "palette" else mock_logos(ctx)
        return json.dumps(out, ensure_ascii=False)

    def _summary_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _SUMMARY_INVALID_MARK.search(str(ctx.get("volume") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici un résumé : le héros part à l'aventure…"
            return json.dumps({"tagline": "Trop court !", "summary": "Un tome."}, ensure_ascii=False)
        return json.dumps(mock_back_summary(ctx), ensure_ascii=False)

    def _creator_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _CREATOR_INVALID_MARK.search(str(ctx.get("pitch") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici ce que je propose : un rythme soutenu, des dialogues vifs…"
            return json.dumps({"dna": [{"path": "rythme.global", "value": 3}], "bible": {"world": ""}})
        return json.dumps(mock_series_creation(ctx), ensure_ascii=False)

    def _scenes_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _SCENES_INVALID_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici les scènes : une bagarre, puis un dialogue…"
            target = int((ctx.get("chapter") or {}).get("target_pages") or 15)
            return json.dumps({"scenes": [{"summary": "Tout le chapitre.", "type": "bagarre", "pages": target + 3}]})
        return json.dumps(mock_scenes(ctx), ensure_ascii=False)

    def _direction_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _DA_INVALID_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici mes choix de mise en scène : page 1 calme…"
            return json.dumps({"pages": [{"page": 1, "rythme": "tempête", "panels": [{"panel": 1, "plan": "drone"}]}]})
        mark = _NO_ESTABLISHING_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        establish = not (mark and attempt <= int(mark.group(1)))
        out = mock_art_direction(ctx, establish=establish)
        mark = _NO_CLOSE_UP_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        if mark and attempt <= int(mark.group(1)):
            for page in out["pages"]:
                for i, pa in enumerate(page["panels"]):
                    if pa["plan"] in ("gros plan", "très gros plan"):
                        pa["plan"] = "plan rapproché" if i % 2 else "plan moyen"
        return json.dumps(out, ensure_ascii=False)


# --- découpage en scènes ----------------------------------------------------------------------------------------
# Type deviné d'après les mots de la phrase (dans cet ordre), et pages voulues par type.
_SCENE_WORDS: list[tuple[str, str]] = [
    ("combat", r"combat|se bat|frappe|attaqu|duel|affront|coup de poing|sabre|bagarre"),
    ("poursuite", r"poursui|course|s'enfui|fuit|fuite|traqu|court après"),
    ("sport_collectif", r"match|ballon|équipe|terrain|tournoi"),
    ("revelation", r"révél|révèl|découvre|secret|vérité|apparaît|surgit"),
    ("dialogue", r"\bdit\b|parle|discut|demande|explique|répond|avoue|«|\?"),
]
_SCENE_PAGES = {"calme": 2, "dialogue": 3, "combat": 4, "poursuite": 3, "sport_collectif": 4, "revelation": 1}
_SCENE_MIN = {"combat": 2, "poursuite": 2, "sport_collectif": 2}


def _scene_type(text: str) -> str:
    low = text.lower()
    return next((t for t, words in _SCENE_WORDS if re.search(words, low)), "calme")


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[\w-]+", text.lower())) + " "


def _cast(ctx: dict[str, Any], text: str) -> list[str]:
    """Distribution factice d'une scène : les fiches dont le nom (ou un alias) est écrit dans la phrase."""
    low = _words(text)
    out = []
    for c in ctx.get("characters") or []:
        names = [c.get("name") or "", *(c.get("aliases") or [])]
        if any(n.strip() and _words(n) in low for n in names):
            out.append(c["name"])
    return out


def mock_scenes(ctx: dict[str, Any]) -> dict[str, Any]:
    """Liste de scènes factice (`"task": "scenes"`) : une scène par phrase du synopsis ; la somme des pages vaut la
    cible, ce qui ne rentre pas (une scène qui n'aurait plus ses pages minimum) est reporté, jamais tassé."""
    chapter = ctx.get("chapter") or {}
    target = max(1, int(chapter.get("target_pages") or 15))
    max_pages = int(ctx.get("max_pages_per_scene") or 12)
    max_scenes = int(ctx.get("max_scenes") or 20)
    allowed = {t.get("id") for t in ctx.get("scene_types") or []} or set(_SCENE_PAGES)
    beats = _sentences(str(chapter.get("synopsis") or ""))
    scenes: list[dict[str, Any]] = []
    deferred: list[str] = []
    used = 0
    for beat in beats:
        kind = _scene_type(beat)
        kind = kind if kind in allowed else "calme"
        want = min(_SCENE_PAGES.get(kind, 2), max_pages)
        left = target - used
        if deferred or len(scenes) >= max_scenes or left < _SCENE_MIN.get(kind, 1):
            deferred.append(beat)
            continue
        pages = min(want, left)
        title = " ".join(beat.rstrip(".!?…").split()[:5])
        scenes.append(
            {
                "title": title,
                "summary": beat,
                "type": kind,
                "pages": pages,
                "lieu": None,
                "personnages": _cast(ctx, beat),
            }
        )
        used += pages
    if not scenes:
        scenes.append({"title": "Le chapitre", "summary": beats[0], "type": "calme", "pages": 0, "lieu": None})
        deferred = deferred[1:]
    # Pages restantes : réparties sur les scènes, sans dépasser le plafond d'une scène.
    i = 0
    while used < target:
        room = [s for s in scenes if s["pages"] < max_pages]
        if not room:
            last = scenes[-1]["title"]
            more = min(max_pages, target - used)
            scenes.append(
                {"title": "Suite", "summary": f"La suite de « {last} ».", "type": "calme", "pages": more, "lieu": None}
            )
            used += more
            continue
        room[i % len(room)]["pages"] += 1
        used += 1
        i += 1
    return {"scenes": scenes, "deferred": deferred}


# --- créateur de série ----------------------------------------------------------------------------------------
def mock_series_creation(ctx: dict[str, Any]) -> dict[str, Any]:
    """Proposition factice et déterministe du créateur de série : pistes d'ADN reprises, bible et notes tirées du
    titre, de l'idée et des réponses de l'auteur (dans les longueurs demandées)."""
    title = str(ctx.get("title") or "la série")
    pitch = _ANY_MARK.sub(" ", str(ctx.get("pitch") or "")).strip()
    answers = {a["question"]: a for a in ctx.get("answers") or []}

    def picked(question: str, default: str = "") -> str:
        a = answers.get(question)
        return str(a["choice_label"]).rstrip(".").lower() if a else default

    def note(question: str) -> str:
        a = answers.get(question)
        return f" {a['note'].rstrip('.')}." if a and a.get("note") else ""

    section = int(ctx.get("max_section_chars") or 1500)
    limit = int(ctx.get("max_note_chars") or 800)
    dna = [
        {"path": s["path"], "value": s["value"], "why": f"Tu as répondu « {s['choice']} » à « {s['question']} »."}
        for s in ctx.get("suggested") or []
    ]
    # Synopsis : l'idée de l'auteur reprise telle quelle, puis développée (jamais contredite) ; un synopsis déjà
    # développé (champ prérempli à la relance) est repris sans rallonge.
    arc = (
        "Arc principal : le héros poursuit ce qu'il veut, chapitre après chapitre, et chaque victoire lui coûte."
        " Fin visée : il l'obtient, changé."
    )
    synopsis = pitch or f"L’histoire de « {title} » reste à préciser avec l’auteur."
    if arc not in synopsis:
        synopsis = f"{synopsis} {arc}"
    world = f"« {title} » ({ctx.get('genre') or 'genre libre'}). {pitch or 'Un univers à préciser avec l’auteur.'}"
    tone = (
        f"Monde {picked('monde', 'nuancé')}, humour : {picked('humour', 'des touches')}.{note('monde')}{note('humour')}"
        f" Pensées et récit off : {picked('voix', 'quand c’est utile')}.{note('voix')}"
    )
    rules = (
        f"Rythme : {picked('rythme', 'celui du genre')}.{note('rythme')} Dialogue : {picked('dialogue', 'équilibré')}."
        f"{note('dialogue')} Mise en page : {picked('nervosite', 'celle du genre')}. Plans : {picked('plans', 'variés')}."
    )
    motifs = (
        f"Fin de chapitre : {picked('fin', 'sur un suspense')}.{note('fin')} Un motif visuel revient à chaque chapitre."
    )
    characters = []
    for i, c in enumerate(ctx.get("characters") or []):
        name = str(c["name"])
        role = "personnage principal" if i == 0 else "personnage secondaire"
        look = " ".join(str(c.get("description") or "").split())[:120]
        text = (
            f"Caractère : {'déterminé et têtu' if i % 2 == 0 else 'calme et ironique'}. Rôle : {role}. "
            f"Arc : apprend à faire confiance aux autres. Tics de langage : « {_REPLIES[i % len(_REPLIES)]} »."
            + (f" Apparence : {look}." if look else "")
        )
        characters.append({"name": name, "note": text[:limit]})
    return {
        "dna": dna,
        "bible": {
            "synopsis": synopsis[: int(ctx.get("max_synopsis_chars") or 3000)],
            "world": world[:section],
            "tone": tone[:section],
            "rules": rules[:section],
            "motifs": motifs[:section],
        },
        "characters": characters,
        "notes": f"J'ai retenu {len(dna)} écart{'s' if len(dna) > 1 else ''} au genre d'après tes réponses.",
    }


# --- rédaction du prompt image ---------------------------------------------------------------------
_FILLERS = {
    "fr": [
        "La composition guide le regard vers l'action principale, avec un premier plan lisible et un fond détaillé.",
        "Les silhouettes se détachent nettement du décor et les proportions restent fidèles aux fiches.",
        "Les expressions sont marquées, les gestes amples et lisibles, sans aucun élément superflu.",
        "Le décor garde sa profondeur, avec des plans successifs bien séparés.",
    ],
    "en": [
        "In the foreground, a few props drawn with bold outlines frame the action, thinner lines for everything further away.",
        "Behind the characters, the background recedes in clearly separated layers, from mid-ground details to a hazy distance.",
        "At the top of the frame, the space stays open so that the movement can breathe.",
        "On the left and on the right, secondary elements of the setting lead the eye toward the main action.",
        "Clothes and hair react to the motion, with folds and strands that follow the direction of the movement.",
        "The silhouettes stand out clearly from the setting, and the proportions stay true to the reference sheets.",
        "Hands and faces are drawn with care, each gesture readable at a glance.",
        "Small details of the place, scattered at different depths, make the scene feel lived in.",
    ],
}
# Poses (anglais) et places dans le cadre, tirées de façon déterministe pour chaque personnage.
_POSES = [
    "lunges forward with the weight on the front leg, one arm thrust out toward the edge of the frame",
    "twists around mid-step, shoulders turned against the hips, coat flaring behind",
    "crouches low with one hand on the ground, ready to spring up",
    "leans in over the table, both fists pressed down, the back arched with tension",
    "steps back on one foot, a raised hand guarding the face",
    "sprints across the frame, body tilted forward, hair whipped by the wind",
    "pivots on the ball of one foot, the free arm swinging wide for balance",
    "reaches out with an open hand, the torso half turned toward the other character",
]
_SPOTS = ["on the left of the frame", "on the right, slightly in the background", "in the centre foreground"]
_LOOKS = [
    "looking sharply toward the other side of the frame with a tense, determined expression",
    "eyes narrowed and fixed on something out of frame, jaw clenched",
    "glancing back over the shoulder, eyebrows raised in surprise",
]


_AGES = ["la vingtaine", "la trentaine", "la quarantaine", "la cinquantaine"]
_BUILDS = ["grand et sec", "trapu, épaules larges", "mince, dos voûté", "taille moyenne, carrure solide"]
_OUTFITS = [
    "manteau long sombre, bottes",
    "uniforme gris boutonné, casquette",
    "tablier clair sur une robe",
    "veste de cuir usée",
]
_MARKS = ["cicatrice sur la joue", "moustache épaisse", "lunettes rondes", "foulard rouge"]


def mock_character_draft(ctx: dict[str, Any]) -> dict[str, Any]:
    """Fiche factice et déterministe d'un intervenant (`"task": "character_draft"`) : traits choisis d'après le
    nom, plus la première description de ses cases (preuve que les cases ont été lues)."""
    name = str(ctx.get("name") or "l'intervenant")
    i = _seed(name)
    panels = ctx.get("panels") or []
    seen = _ANY_MARK.sub(" ", str(panels[0].get("description") or "")).strip() if panels else ""
    age, build, outfit, mark = (
        _AGES[i % len(_AGES)],
        _BUILDS[i % len(_BUILDS)],
        _OUTFITS[i % len(_OUTFITS)],
        _MARKS[i % len(_MARKS)],
    )
    description = f"{name[:1].upper()}{name[1:]}, {age}, {build}, {outfit}, {mark}."
    if seen:
        description += f" Vu dans la case : {_short(seen)}"
    return {
        "age": age,
        "silhouette": build,
        "tenue": outfit,
        "signe_distinctif": mark,
        "description": description,
        "mots_cles": [w for w in (build.split(",")[0], outfit.split(",")[0], mark) if w],
    }


def _seed(text: str) -> int:
    return sum(ord(ch) for ch in text)


def _mock_english(ctx: dict[str, Any]) -> list[str]:
    """Phrases anglaises seulement (le mock ne traduit pas) : phrase de style, sujet et pose, cadrage, décor,
    lumière, composition — jamais de vocabulaire photographique ni de phrase de rôle des images (le moteur
    l'écrit seul, `prompt.frame_references`)."""
    panel = ctx.get("panel") or {}
    sentences = [str(ctx["style_lead"])] if ctx.get("style_lead") else []
    if ctx.get("references"):
        sentences.append("The whole panel is drawn in the same manga style as the reference images.")
    seed = _seed(str(panel.get("description") or "") + str(panel.get("action") or ""))
    for i, c in enumerate(ctx.get("characters") or []):
        name = c.get("name", "")
        pose = _POSES[(seed + i) % len(_POSES)]
        spot = _SPOTS[i % len(_SPOTS)]
        look = _LOOKS[(seed + i) % len(_LOOKS)]
        sentences.append(f"{name}, {spot}, {pose}, {look}.")
    if ctx.get("framing"):
        sentences.append(str(ctx["framing"]).rstrip(".") + ".")
    if panel.get("camera"):
        sentences.append(
            f"Framing: {panel['camera']}, with strong foreshortening, converging perspective lines and speed lines behind the motion."
        )
    sentences += [str(x) for x in ctx.get("extra_sentences") or []]
    if (ctx.get("decor") or {}).get("name"):
        sentences.append(f"The scene takes place in {ctx['decor']['name']}, seen from the new camera angle.")
    sentences.append(
        "The light comes from the upper left, casting long diagonal shadows across the ground and rim-lighting the figures."
    )
    sentences.append(
        "A single continuous scene in one panel, with no text, speech bubbles or sound effects in the image."
    )
    return sentences


def mock_image_prompt(ctx: dict[str, Any]) -> dict[str, Any]:
    """Paragraphe déterministe : phrase de style → sujet et pose → cadrage → décor → lumière → style (aucune
    phrase de rôle des images : le moteur l'écrit seul)."""
    lang = "en" if ctx.get("language") == "en" else "fr"
    panel = ctx.get("panel") or {}
    description = _ANY_MARK.sub(" ", str(panel.get("description") or "")).strip()
    if lang == "en":
        sentences = _mock_english(ctx)
    else:
        refs = {r.get("name"): r.get("tag") for r in ctx.get("references") or [] if r.get("kind") == "character"}
        subjects = []
        for c in ctx.get("characters") or []:
            name, details = c.get("name", ""), c.get("details", "")
            who = f"{name}, la personne de {refs[name]}" if refs.get(name) else name
            subjects.append(f"{who} ({details})" if details else who)
        sentences = [str(ctx["style_lead"])] if ctx.get("style_lead") else []
        if subjects:
            sentences.append("On voit " + ", ".join(subjects) + ".")
        if description:
            sentences.append(description.rstrip(".") + ".")
        if panel.get("action"):
            sentences.append(str(panel["action"]).rstrip(".") + ".")
        framing = ", ".join(v for v in (panel.get("plan"), panel.get("angle")) if v)
        if framing:
            sentences.append("Cadrage : " + framing + ".")
        if panel.get("staging"):
            sentences.append(str(panel["staging"]).rstrip(".") + ".")
        place = ", ".join(v for v in (panel.get("setting"), (ctx.get("decor") or {}).get("name")) if v)
        if place:
            sentences.append("La scène se passe : " + place + ".")
        if panel.get("ambiance"):
            sentences.append("Lumière : " + str(panel["ambiance"]).rstrip(".") + ".")
        sentences.append("Aucun texte ni bulle dans l'image.")
    target = int(ctx.get("min_words") or 180)
    fillers = _FILLERS[lang]
    i = 0
    while len(" ".join(sentences).split()) + len(str(ctx.get("style") or "").split()) < target:
        sentences.insert(len(sentences) - 1, fillers[i % len(fillers)])
        i += 1
    if lang == "en":
        sentences.append("The composition is tense and dynamic, built on strong diagonals that carry the movement.")
    if ctx.get("style"):
        sentences.append(str(ctx["style"]).rstrip(".") + ".")
    notes = "Paragraphe du LLM factice (mode mock)."
    if lang == "en" and description:
        notes += f" Case (non traduite) : {description[:600]}"
    return {"prompt": " ".join(sentences), "language": lang, "notes": notes}


_TEMPLATE_ACTIONS = ["lunges forward", "crouches low, ready to spring", "steps back, one hand raised", "reaches out"]
_TEMPLATE_LOOKS = ["with a determined frown", "wide-eyed with surprise", "with a tense, clenched jaw"]
_TEMPLATE_SPOTS = ["on the left", "on the right", "in the centre"]


def mock_template_action(ctx: dict[str, Any]) -> dict[str, Any]:
    """Phrases d'action déterministes du gabarit : une par personnage présent (3 au plus), anglaises, courtes ;
    décor court tiré du lieu et des éléments reçus (le mock ne traduit pas)."""
    panel = ctx.get("panel") or {}
    seed = _seed(str(panel.get("description") or "") + str(panel.get("action") or ""))
    names = [str(c.get("name")) for c in ctx.get("characters") or [] if c.get("name")]
    names += [str(e) for e in ctx.get("extras") or []]
    sentences = []
    for i, name in enumerate(names[:3]):
        act = _TEMPLATE_ACTIONS[(seed + i) % len(_TEMPLATE_ACTIONS)]
        look = _TEMPLATE_LOOKS[(seed + i) % len(_TEMPLATE_LOOKS)]
        sentences.append(f"{name} {act} {_TEMPLATE_SPOTS[i % len(_TEMPLATE_SPOTS)]}, {look}.")
    if not sentences:
        sentences.append("The place is empty and still, nobody in sight.")
    place = ", ".join(p for p in (str(ctx.get("place") or ""), *(str(e) for e in ctx.get("elements") or [])) if p)
    return {"action": " ".join(sentences), "setting": place or None, "language": "en"}


def mock_visual_anchor(ctx: dict[str, Any]) -> dict[str, Any]:
    """Ancre factice : le début de la description et des mots-clés (15 mots au plus), sans le nom du personnage."""
    name = str(ctx.get("name") or "")
    text = ", ".join(p for p in (str(ctx.get("description") or ""), *(str(k) for k in ctx.get("keywords") or [])) if p)
    if name:
        text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", " ", text, flags=re.IGNORECASE)
    words = _ANY_MARK.sub(" ", text).replace(".", ",").split()
    anchor = " ".join(words[:15]).strip(" ,;:")
    return {"anchor": anchor or "slim build, plain clothes", "language": "en"}


def mock_cover_prompt(ctx: dict[str, Any]) -> dict[str, Any]:
    """Prompt de couverture déterministe : phrase d'ouverture → personnages → intention → décor en couleur →
    zone du logo → style (aucune règle de couleur : la couverture est toujours en couleur ; aucune phrase de
    rôle des images : le moteur l'écrit seul, `covers.finish_cover_prompt`)."""
    sentences = [str(ctx["style_lead"])] if ctx.get("style_lead") else []
    names = [str(c.get("name")) for c in ctx.get("characters") or [] if c.get("name")]
    if names:
        sentences.append(f"{' and '.join(names)} stand in the lower two thirds of the cover in a bold heroic pose.")
    intent = _ANY_MARK.sub(" ", str(ctx.get("intent") or "")).strip()
    if intent:
        sentences.append(f"The author's idea for the cover: {intent.rstrip('.')}.")
    sentences.append(
        "Behind them a vast city glows under a crimson and golden sunset, warm orange light on their faces."
    )
    if ctx.get("clear_zone"):
        sentences.append(f"Keep {ctx['clear_zone']} as open sky for the title logo.")
    target = int(ctx.get("min_words") or 90)
    i = 0
    while len(" ".join(sentences).split()) < target:
        sentences.append(_COVER_FILLERS[i % len(_COVER_FILLERS)])
        i += 1
    if ctx.get("style"):
        sentences.append(str(ctx["style"]).rstrip(".") + ".")
    return {
        "prompt": " ".join(sentences),
        "language": "en",
        "notes": "Prompt de couverture du LLM factice (mode mock).",
    }


_COVER_FILLERS = (
    "Saturated blues and teals in the shadows contrast with the warm highlights.",
    "Dynamic diagonal composition, wind in their hair and clothes, sparks drifting in the air.",
    "Clean inked outlines with rich painted colours and soft glowing rim light.",
)


# --- résumé de 4e de couverture -------------------------------------------------------------------
_SUMMARY_FILLERS = (
    "Chaque choix les rapproche d'un secret que tous préféreraient oublier.",
    "Les alliances se nouent et se défont au rythme des combats, et la confiance devient un luxe.",
    "Derrière les sourires de façade, une menace grandit dans l'ombre, patiente et implacable.",
    "Entre éclats de rire, coups d'épée et regards échangés, l'équipe apprend à se battre ensemble.",
    "Le passé refait surface au pire moment, et personne n'en sortira tout à fait indemne.",
    "Une rencontre inattendue va bouleverser l'équilibre fragile qu'ils croyaient avoir trouvé.",
    "Mais le prix à payer pourrait bien être bien plus lourd que prévu…",
    "Jusqu'où iront-ils pour protéger ceux qu'ils aiment ?",
)
_TAGLINES = (
    "Le combat ne fait que commencer !",
    "Quand tout bascule, il faut choisir son camp.",
    "Un secret, une promesse, et plus de retour en arrière.",
    "L'aventure prend un tour inattendu !",
)


def _first_sentence(text: str, limit: int = 200) -> str:
    text = _ANY_MARK.sub(" ", text).strip()
    first = re.split(r"(?<=[.!?…])\s+", text)[0].strip() if text else ""
    if len(first) > limit:
        first = first[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if first and first[-1] not in ".!?…":
        first += "."
    return first


def mock_back_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    """Résumé factice : accroche sur la série, premières phrases des chapitres (sauf le dernier, la fin du tome),
    phrases d'accroche jusqu'à la longueur demandée. Décalé quand un résumé existe déjà (« Réécrire »)."""
    series = _ANY_MARK.sub(" ", str(ctx.get("series") or "")).strip()
    low, high = int(ctx.get("min_chars") or 600), int(ctx.get("max_chars") or 900)
    previous = str(ctx.get("previous") or "")
    shift = (_seed(previous) % len(_SUMMARY_FILLERS)) if previous else 0
    first = [f"Dans l'univers de « {series} », rien ne prépare nos héros à ce qui les attend."]
    for ch in list(ctx.get("chapters") or [])[:-1]:
        sentence = _first_sentence(str(ch.get("summary") or ""))
        if sentence and not sentence.startswith("(") and len(" ".join([*first, sentence])) < high // 2:
            first.append(sentence)
    second: list[str] = []
    target = (low + high) // 2
    for i in range(len(_SUMMARY_FILLERS)):
        sentence = _SUMMARY_FILLERS[(i + shift) % len(_SUMMARY_FILLERS)]
        text = " ".join(first) + "\n\n" + " ".join([*second, sentence])
        if len(" ".join(text.split())) > high:
            continue
        second.append(sentence)
        if len(" ".join(text.split())) >= target:
            break
    tagline = _TAGLINES[(_seed(series) + (1 if previous else 0)) % len(_TAGLINES)]
    return {
        "tagline": tagline[: int(ctx.get("tagline_max_chars") or 90)],
        "summary": " ".join(first) + "\n\n" + " ".join(second),
        "notes": "Résumé du LLM factice (mode mock).",
    }


# --- dialogue sur une case ------------------------------------------------------------------------
_DIALOG_PLANS = ("gros plan", "plan large", "plan moyen", "plan rapproché", "insert")
_DIALOG_ANGLES = {
    "contre-plongée": "en contre-plongée",
    "contre plongée": "en contre-plongée",
    "plongée": "en plongée",
    "de dos": "de dos",
    "de profil": "de profil",
    "de face": "de face",
    "trois quarts": "de trois quarts",
    "vue subjective": "vue subjective",
    "penché": "cadre penché",
}
_CLOSE = ("gros plan", "plan rapproché", "insert")
_ACTION = re.compile(r"en train de ([^,.;]+)")


def _pick_reference(options: list[dict[str, Any]], words: tuple[str, ...]) -> dict[str, int]:
    """Par personnage : l'image dont le nom contient un des `words` (si ce n'est pas déjà celle envoyée)."""
    out: dict[str, int] = {}
    for o in options:
        label = str(o.get("label") or "").lower()
        name = str(o.get("character") or "")
        if name not in out and not o.get("current") and any(w in label for w in words):
            out[name] = int(o["image_id"])
    return out


def mock_dialog(ctx: dict[str, Any]) -> dict[str, Any]:
    """Réponse déterministe à une consigne : nouveaux plan / angle / action / ambiance lus dans la consigne,
    référence adaptée au plan, paragraphe réécrit avec la nouvelle caméra."""
    instruction = _ANY_MARK.sub(" ", str(ctx.get("instruction") or "")).strip()
    text = instruction.lower()
    direction: dict[str, Any] = {}
    plan = next((p for p in _DIALOG_PLANS if p in text), None)
    if plan:
        direction["plan"] = plan
    angle = next((v for k, v in _DIALOG_ANGLES.items() if k in text), None)
    if angle:
        direction["angle"] = angle
    action = _ACTION.search(text)
    if action:
        direction["action"] = f"en train de {action.group(1).strip()}"
    extra: list[str] = []
    if "fond blanc" in text:
        direction["ambiance"] = "fond blanc uni, sans décor"
        extra.append("The background is plain white, with no setting at all.")
    current = dict(ctx.get("current_direction") or {})
    terms = dict(ctx.get("camera_terms") or {})
    new_plan, new_angle = direction.get("plan") or current.get("plan"), direction.get("angle") or current.get("angle")
    camera = ", ".join(terms.get(v, v) for v in (new_plan, new_angle) if v)
    if new_plan in _CLOSE:
        extra.append("The face fills most of the frame, every detail of the expression readable.")
    options = list(ctx.get("reference_options") or [])
    if new_plan in _CLOSE:
        picks = _pick_reference(options, ("portrait", "visage", "face"))
    elif new_plan == "plan large":
        picks = _pick_reference(options, ("pied", "turnaround", "full"))
    else:
        picks = {}
    panel = {**(ctx.get("panel") or {}), **({"camera": camera} if camera else {})}
    written = mock_image_prompt({**ctx, "panel": panel, "extra_sentences": extra})
    said = [f"{k} : {v}" for k, v in direction.items()] + [f"référence de {n} changée" for n in picks]
    return {
        "prompt": written["prompt"],
        "language": written["language"],
        "direction": direction or None,
        "references": [{"character": n, "image_id": i} for n, i in picks.items()],
        "explanation": ("J'ai changé " + ", ".join(said) + ".")
        if said
        else "J'ai réécrit le prompt selon la consigne.",
    }


# --- identité visuelle -----------------------------------------------------------------------------------
_PALETTE_NAMES = ["Aube", "Braise", "Lagon", "Forêt", "Crépuscule", "Néon", "Sable", "Givre"]
# Rôle → (décalage de teinte, saturation, luminosité) autour de la teinte de la palette.
_ROLE_TONES = {
    "dominante": (0, 0.70, 0.50),
    "secondaire": (40, 0.55, 0.45),
    "accent": (180, 0.85, 0.55),
    "fond": (0, 0.30, 0.92),
    "texte-clair": (0, 0.20, 0.97),
    "texte-sombre": (0, 0.35, 0.12),
    "ombre": (0, 0.40, 0.25),
}


def _hsl(h: float, s: float, light: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, light, s)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def mock_palettes(ctx: dict[str, Any]) -> dict[str, Any]:
    """Palettes factices : teintes réparties à partir du titre, décalées par les palettes déjà proposées."""
    roles = [r for r in ctx["roles"] if r in _ROLE_TONES]
    required = list(ctx["required_roles"])
    extra = [r for r in roles if r not in required]
    n_colors = max(ctx["colors"]["min"], len(required))
    chosen = (required + extra)[: min(n_colors + 1, ctx["colors"]["max"])]
    count = min(4, ctx["count"]["max"])
    shift = len(ctx.get("previous") or [])
    base = _seed(str(ctx["title"])) % 360
    out = []
    for i in range(max(count, ctx["count"]["min"])):
        k = i + shift
        hue = base + k * 67
        name = f"{_PALETTE_NAMES[k % len(_PALETTE_NAMES)]}" + (
            f" {k // len(_PALETTE_NAMES) + 1}" if k >= len(_PALETTE_NAMES) else ""
        )
        colors = [{"role": r, "hex": _hsl(hue + _ROLE_TONES[r][0], *_ROLE_TONES[r][1:])} for r in chosen]
        out.append(
            {"name": name, "colors": colors, "explanation": f"Palette « {name} » autour d'une teinte de {hue % 360}°."}
        )
    return {"palettes": out}


def mock_logos(ctx: dict[str, Any]) -> dict[str, Any]:
    """Concepts factices : polices et effets permis à tour de rôle, titre en une ou deux lignes."""
    title = str(ctx["title"])
    words = title.split()
    fonts, styles = list(ctx["fonts"]), list(ctx["styles"])
    shift = len(ctx.get("previous") or [])
    count = min(5, ctx["count"]["max"])
    out = []
    for i in range(max(count, ctx["count"]["min"])):
        k = i + shift
        if len(words) >= 2 and ctx.get("max_lines", 2) >= 2 and k % 2 == 0:
            cut = max(1, len(words) // 2)
            lines = [{"text": " ".join(words[:cut]), "scale": 0.6}, {"text": " ".join(words[cut:]), "scale": 1}]
        else:
            lines = [{"text": title, "scale": 1}]
        concept: dict[str, Any] = {
            "name": f"Concept {k + 1}",
            "explanation": "Titre lisible en petit, effet tiré de la palette de la série.",
            "font": fonts[k % len(fonts)],
            "style": styles[k % len(styles)],
            "lines": lines,
            "subtitle": None,
            "slant": [-6, 0, 4, -3, 8][k % 5],
            "letter_spacing": [0.02, 0.06, 0.0, 0.1, 0.04][k % 5],
        }
        if k % 3 == 1 and "accent" in ctx["roles"]:
            concept["colors"] = {"fill": "accent"}
        out.append(concept)
    return {"concepts": out}
