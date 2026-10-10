"""LLM factice, déterministe, sans réseau (mode par défaut sans .env et dans les tests).

Pour l'étape « scénario », il reconnaît le bloc `<contexte>{"task": "script", …}</contexte>` du
prompt et renvoie un découpage plausible (nombre de pages visé, personnages de la série ; chaque page
se passe dans un décor de la bibliothèque, à tour de rôle, et une case sur deux montre un objet).

Pour la direction artistique (`"task": "art_direction"`), il renvoie des choix variés mais
déterministes : même chapitre, même audace, même relance → mêmes choix (`mock_art_direction`).

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
UNKNOWN_ID = 999_999  # id de décor cité par `[mock:id-invalide:N]` (absent de toute bibliothèque)
TASKS = ("script", "art_direction")

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
_DA_ANGLES = [
    "de face",
    "de trois quarts",
    "de profil",
    "de dos",
    "en contre-plongée",
    "en plongée",
    "vue subjective",
    "cadre penché",
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
    angles = _DA_ANGLES if bold else _DA_ANGLES[:4]
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
            out_panels.append(
                {
                    "panel": i + 1,
                    "intensity": intensity,
                    "plan": plan,
                    "angle": angles[(seed + 2 * i) % len(angles)],
                    "cadre": cadre,
                    "ambiance": _DA_AMBIANCES[(seed + i) % len(_DA_AMBIANCES)],
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
    return {"pages": out}


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

    def _direction_answer(self, messages: list[ChatMessage], ctx: dict[str, Any]) -> str:
        attempt = 1 + sum(1 for m in messages if m.role == "assistant")
        mark = _DA_INVALID_MARK.search(str((ctx.get("chapter") or {}).get("synopsis") or ""))
        invalid = int(mark.group(1)) if mark else self.invalid_attempts
        if attempt <= invalid:
            if attempt % 2:
                return "Voici mes choix de mise en scène : page 1 calme…"
            return json.dumps({"pages": [{"page": 1, "rythme": "tempête", "panels": [{"panel": 1, "plan": "drone"}]}]})
        return json.dumps(mock_art_direction(ctx), ensure_ascii=False)
