"""LLM factice, déterministe, sans réseau (mode par défaut sans .env et dans les tests).

Pour l'étape « scénario », il reconnaît le bloc `<contexte>{"task": "script", …}</contexte>` du
prompt et renvoie un découpage plausible (nombre de pages visé, personnages de la série ; chaque page
se passe dans un décor de la bibliothèque, à tour de rôle, et une case sur deux montre un objet).

Pour la direction artistique (`"task": "art_direction"`), il renvoie des choix variés mais
déterministes : même chapitre, même audace, même relance → mêmes choix (`mock_art_direction`), qui
respectent les règles de variété du preset (angles en alternance, jamais 3 plans identiques d'affilée,
une action par case).

Pour la rédaction du prompt image d'une case (`"task": "image_prompt"`), il rend un paragraphe qui
définit d'abord le rôle de chaque image de référence (`<image1>`…), nomme chaque personnage, le place
dans le cadre avec une pose, décrit la caméra, la lumière, et finit par les mots-clés de style
(`mock_image_prompt`). En anglais, il n'écrit que des phrases anglaises : il ne sait pas traduire, donc
la description française de la case n'y entre pas (elle reste dans `notes`). `[mock:prompt-invalide:N]` dans la description de la case :
les N premiers essais sont invalides ; `[mock:prompt-intrus:N]` : ils nomment un personnage absent.

Pour tester les relances sans vrai LLM, les `invalid_attempts` premiers essais d'une conversation
renvoient une réponse invalide (variable MOCK_LLM_INVALID_ATTEMPTS, ou `[mock:invalide:N]` dans le
synopsis du chapitre ; `[mock:da-invalide:N]` pour la seule direction artistique ;
`[mock:id-invalide:N]` : découpage bien formé qui cite un décor inexistant). L'essai courant se
déduit des messages : aucun état entre deux appels.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .base import ChatMessage, LLMResult

Responder = Callable[[list[ChatMessage], bool], str]

_CONTEXT = re.compile(r"<contexte>\s*(\{.*\})\s*</contexte>", re.DOTALL)
_INVALID_MARK = re.compile(r"\[mock:invalide:(\d+)\]")
_DA_INVALID_MARK = re.compile(r"\[mock:da-invalide:(\d+)\]")
_ID_INVALID_MARK = re.compile(r"\[mock:id-invalide:(\d+)\]")
_PROMPT_INVALID_MARK = re.compile(r"\[mock:prompt-invalide:(\d+)\]")
_PROMPT_INTRUDER_MARK = re.compile(r"\[mock:prompt-intrus:(\d+)\]")
_ANY_MARK = re.compile(r"\s*\[mock:[a-z-]+:\d+\]\s*")
UNKNOWN_ID = 999_999  # id de décor cité par `[mock:id-invalide:N]` (absent de toute bibliothèque)
TASKS = ("script", "art_direction", "image_prompt")

_SHOTS = ["plan large", "plan moyen", "gros plan", "plan américain", "contre-plongée", "plan rapproché", "plongée"]
_PANELS_PER_PAGE = [5, 4, 6, 3, 5, 4]
_KINDS = ["speech", "speech", "thought", "speech", "shout"]
_RYTHMES = ["normal", "rapide", "lent", "normal", "rapide"]
# Onomatopées des cases « choc » (et d'une case calme de temps en temps), accents compris.
_SFX = ["VROUM !", "CLIC", "BIIIP !", "BAM !", "ÇA CRAQUE !", "BAÏE !"]


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
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+|\n+", text) if p.strip()]
    return parts or ["La scène s'installe."]


_SETTINGS = [
    "clairière au bord d'un lac, fin d'après-midi, herbes hautes, rochers moussus, montagnes au loin",
    "falaise battue par le vent, aube grise, nuages bas, mer agitée en contrebas",
    "village de pierre, midi, ruelles pavées, linge aux fenêtres, foule de marché",
    "forêt dense, nuit de pleine lune, troncs immenses, lucioles, brume au sol",
]
_PLACES = ["au premier plan à gauche", "au centre", "à droite, en retrait", "en arrière-plan"]


def _staging(who: str, other: str, i: int) -> str:
    if other == who:
        return f"{who} {_PLACES[i % len(_PLACES)]}, en mouvement, regard vers l'horizon"
    return (
        f"{who} {_PLACES[i % len(_PLACES)]}, tourné vers {other} ; "
        f"{other} {_PLACES[(i + 2) % len(_PLACES)]}, lui répond d'un geste"
    )


def mock_script(ctx: dict[str, Any]) -> dict[str, Any]:
    chapter = ctx.get("chapter") or {}
    names = [c["name"] for c in ctx.get("characters") or [] if c.get("name")] or ["Héros", "Rival"]
    beats = _sentences(str(chapter.get("synopsis") or ""))
    n_pages = max(1, min(40, int(chapter.get("target_pages") or 15)))
    previous = ctx.get("previous_chapters") or []
    decors = [d["id"] for d in ctx.get("decors") or [] if isinstance(d.get("id"), int)]
    objets = [o["id"] for o in ctx.get("objets") or [] if isinstance(o.get("id"), int)]
    pages = []
    beat = 0
    for p in range(n_pages):
        panels = []
        count = 1 if p == n_pages - 1 and n_pages > 2 else _PANELS_PER_PAGE[p % len(_PANELS_PER_PAGE)]
        for i in range(count):
            text = beats[beat % len(beats)]
            beat += 1
            who = names[(p + i) % len(names)]
            other = names[(p + i + 1) % len(names)]
            dialogues = []
            if i % 3 != 2:
                dialogues.append({"speaker": who, "text": text[:80], "kind": _KINDS[(p + i) % len(_KINDS)]})
            if i == 0 and p == 0:
                dialogues.insert(
                    0, {"speaker": "", "text": f"Chapitre {chapter.get('number', '?')}.", "kind": "narration"}
                )
            importance = 3 if count == 1 or (i == 0 and p % 2 == 0) else (1 if i == count - 1 else 2)
            # Indices de mise en page : une case forte sur deux est un temps d'action, les cases de
            # transition sont calmes.
            intensity = "choc" if importance == 3 and p % 4 != 2 else ("calme" if importance == 1 else "normal")
            sfx = []
            if intensity == "choc":
                sfx.append({"text": _SFX[(p + i) % len(_SFX)], "intensity": "choc"})
            elif intensity == "calme" and p % 3 == 1:
                sfx.append({"text": "tic… tac…", "intensity": "calme"})
            cast = [who] if i % 2 else list(dict.fromkeys([who, other]))
            panels.append(
                {
                    "description": f"{text} ({who}{' et ' + other if other != who else ''}, page {p + 1}, case {i + 1})",
                    "setting": _SETTINGS[p % len(_SETTINGS)],
                    "staging": _staging(cast[0], cast[-1], i),
                    "characters": cast,
                    "shot_type": _SHOTS[(p * 3 + i) % len(_SHOTS)],
                    "importance": importance,
                    "intensity": intensity,
                    "dialogues": dialogues,
                    "sfx": sfx,
                    "decor": decors[p % len(decors)] if decors else None,
                    "objets": [objets[(p + i // 2) % len(objets)]] if objets and i % 2 == 0 else [],
                }
            )
        pages.append({"rythme": _RYTHMES[p % len(_RYTHMES)], "panels": panels})
    recap = f" Suite du chapitre {previous[-1]['number']}." if previous else ""
    summary = f"Chapitre {chapter.get('number', '?')} — {' '.join(beats)[:400]}{recap}"
    return {"pages": pages, "summary": summary}


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
_DA_SFX = ["BAM", "VLAN", "FSHHH", "CLAC", "BOUM", "TCHAC"]
_RYTHME_PHRASES = {
    "calme": "Page d'installation : on laisse respirer le décor et les personnages.",
    "montée": "La tension monte : les cadrages se resserrent au fil des cases.",
    "climax": "Sommet de la séquence : on frappe fort, avec des cases très contrastées.",
    "respiration": "Respiration après l'action : plans plus larges et lecture apaisée.",
}
_BOLDNESS = {"sobre": 0, "equilibree": 1, "audacieuse": 2}


def mock_art_direction(ctx: dict[str, Any]) -> dict[str, Any]:
    """Choix plausibles, variés d'une page à l'autre et déterministes (chapitre, audace, relance)."""
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
    for page in pages:
        n = int(page["page"])
        seed = n * 7 + number * 3 + variant * 5
        if variant == 0 and n == 1:
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
                cadre = "sans bord" if bold == 1 else "fond perdu"
            if len(out_panels) >= 2 and out_panels[-1]["plan"] == out_panels[-2]["plan"] == plan:
                plan = next(p for p in _DA_PLANS[(seed + i) % len(_DA_PLANS) :] + _DA_PLANS if p != plan)
            who = next(iter(pa.get("characters") or []), None)
            action = _DA_ACTIONS[(seed + i) % len(_DA_ACTIONS)]
            out_panels.append(
                {
                    "panel": i + 1,
                    "intensity": intensity,
                    "plan": plan,
                    "angle": angles[(seed + i) % len(angles)],
                    "cadre": cadre,
                    "ambiance": _DA_AMBIANCES[(seed + i) % len(_DA_AMBIANCES)],
                    "action": f"{who} {action}" if who else action[:1].upper() + action[1:],
                    "sfx": [{"text": _DA_SFX[(seed + i) % len(_DA_SFX)], "intensity": "fort"}]
                    if intensity == "choc"
                    else [],
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
    return {"pages": out}


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
        if ctx is not None and ctx.get("task") == "image_prompt":
            return LLMResult(text=self._image_prompt_answer(messages, ctx), model="mock")
        if ctx is not None and ctx.get("task") == "art_direction":
            return LLMResult(text=self._direction_answer(messages, ctx), model="mock")
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
        return json.dumps(mock_script(ctx), ensure_ascii=False)

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

    def _direction_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _DA_INVALID_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici mes choix de mise en scène : page 1 calme…"
            return json.dumps({"pages": [{"page": 1, "rythme": "tempête", "panels": [{"panel": 1, "plan": "drone"}]}]})
        return json.dumps(mock_art_direction(ctx), ensure_ascii=False)


# --- rédaction du prompt image ---------------------------------------------------------------------
_FILLERS = {
    "fr": [
        "La composition guide le regard vers l'action principale, avec un premier plan lisible et un fond détaillé.",
        "Les silhouettes se détachent nettement du décor et les proportions restent fidèles aux fiches.",
        "Les expressions sont marquées, les gestes amples et lisibles, sans aucun élément superflu.",
        "Le décor garde sa profondeur, avec des plans successifs bien séparés.",
    ],
    "en": [
        "In the foreground, a few blurred props frame the action and give the shot depth.",
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


def _seed(text: str) -> int:
    return sum(ord(ch) for ch in text)


def _mock_english(ctx: dict[str, Any]) -> list[str]:
    """Phrases anglaises seulement (le mock ne traduit pas) : rôles des images, sujet et pose, caméra,
    décor, lumière, composition."""
    panel = ctx.get("panel") or {}
    sentences = [f"{r['tag']} is {r['role']}." for r in ctx.get("references") or [] if r.get("tag") and r.get("role")]
    seed = _seed(str(panel.get("description") or "") + str(panel.get("action") or ""))
    for i, c in enumerate(ctx.get("characters") or []):
        name = c.get("name", "")
        pose = _POSES[(seed + i) % len(_POSES)]
        spot = _SPOTS[i % len(_SPOTS)]
        look = _LOOKS[(seed + i) % len(_LOOKS)]
        sentences.append(f"{name}, {spot}, {pose}, {look}.")
    if panel.get("camera"):
        sentences.append(f"Camera: {panel['camera']}, with a slight wide-angle feel and a shallow depth of field.")
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
    """Paragraphe déterministe : rôles des images → sujet et pose → caméra → décor → lumière → style."""
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
        sentences = [f"{r['tag']} : {r['name']}." for r in ctx.get("references") or [] if r.get("tag")]
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
