"""Chapitre 3 « vulcano » (série ecoloman) : les 20 cases telles qu'en base au 13/10, et une réécriture.

`MAIGRE` reprend les vraies bulles du chapitre (audit `livraison-vulcano-20261013`) : 15 paroles pour
20 cases (0,75 par case), cinq cases de combat réduites à leur onomatopée (TCHAK, RATATATA, BOUM, PAN,
CRAC, planches 2 à 4), aucune pensée, voix off ni narration. `DENSE` garde les mêmes cases et la même
brièveté, avec ce qu'un scénariste aurait dû écrire : deux répliques par case, un cri dans chaque case de
combat, une narration et des pensées.
"""

from __future__ import annotations

import copy
from typing import Any

# (planche, plan, intensité, importance, personnages, description, onomatopées)
CASES: list[tuple[int, str, str, int, list[str], str, list[str]]] = [
    (
        1,
        "plan d'ensemble",
        "calme",
        2,
        ["Seku", "Angus"],
        "Le volcan fume au loin ; Seku et Angus marchent vers la montagne.",
        [],
    ),
    (1, "plan moyen", "normal", 2, ["Angus", "Seku"], "Ils grimpent une pente raide ; Angus s'essuie le front.", []),
    (
        1,
        "plan large",
        "normal",
        2,
        ["Seku", "Angus", "Trafiquant 1", "Trafiquant 2"],
        "Au loin, les trafiquants jettent des barils dans le volcan.",
        [],
    ),
    (
        2,
        "plan moyen",
        "normal",
        2,
        ["Trafiquant 1", "Trafiquant 2"],
        "Les deux trafiquants font basculer un baril toxique dans la lave.",
        [],
    ),
    (
        2,
        "plan américain",
        "choc",
        3,
        ["Angus", "Trafiquant 1", "Trafiquant 2"],
        "Angus surgit de derrière un rocher et pointe les trafiquants.",
        [],
    ),
    (
        2,
        "plan rapproché",
        "normal",
        2,
        ["Trafiquant 1", "Trafiquant 2"],
        "Trafiquant 1 lève sa mitraillette, Trafiquant 2 ricane.",
        [],
    ),
    (
        2,
        "plan moyen",
        "choc",
        2,
        ["Angus", "Seku"],
        "Angus s'élance, poings serrés ; Seku court à ses côtés.",
        ["TCHAK !"],
    ),
    (
        3,
        "plan large",
        "choc",
        3,
        ["Trafiquant 1", "Angus"],
        "Trafiquant 1 tire une rafale ; Angus esquive en se baissant.",
        ["RATATATA !"],
    ),
    (
        3,
        "plan moyen",
        "choc",
        3,
        ["Angus", "Trafiquant 1"],
        "Angus prend appui sur un rocher et percute Trafiquant 1.",
        ["BOUM !"],
    ),
    (3, "plan américain", "choc", 2, ["Seku", "Trafiquant 2"], "Seku lance une pierre sur Trafiquant 2.", []),
    (
        3,
        "plan large",
        "choc",
        2,
        ["Trafiquant 2", "Seku"],
        "Trafiquant 2 tire au pistolet ; Seku roule au sol.",
        ["PAN !"],
    ),
    (4, "contre-plongée", "choc", 3, ["Angus", "Trafiquant 1"], "Angus soulève Trafiquant 1 au-dessus de sa tête.", []),
    (
        4,
        "plongée",
        "choc",
        3,
        ["Angus", "Trafiquant 1"],
        "Angus projette Trafiquant 1 au sol ; poussière et débris.",
        ["CRAC !"],
    ),
    (
        4,
        "plan moyen",
        "normal",
        2,
        ["Trafiquant 2", "Angus", "Seku"],
        "Trafiquant 2 panique et recule vers le cratère.",
        [],
    ),
    (
        4,
        "plan large",
        "choc",
        3,
        ["Trafiquant 2", "Angus", "Seku"],
        "Trafiquant 2 trébuche et bascule dans le cratère.",
        [],
    ),
    (5, "plan moyen", "normal", 2, ["Angus", "Seku"], "Angus retient Seku par le bras au bord du cratère.", []),
    (5, "plan large", "normal", 2, ["Trafiquant 1", "Angus", "Seku"], "Trafiquant 1, sonné, s'enfuit en boitant.", []),
    (5, "plan américain", "calme", 2, ["Angus", "Seku"], "Angus et Seku reprennent leur souffle près du cratère.", []),
    (5, "plan d'ensemble", "choc", 3, ["Angus", "Seku"], "Le sol tremble, le volcan gronde.", ["GRRRUMBLE !"]),
    (5, "plan large", "choc", 3, ["Angus", "Seku"], "Angus et Seku courent devant la coulée de lave.", []),
]

S, SH, TH, OFF, NAR = "speech", "shout", "thought", "off", "narration"

# Bulles réelles du chapitre 3 (hors onomatopées), case par case.
REPLIQUES_MAIGRES: list[list[tuple[str, str, str]]] = [
    [("Seku", "C'est là-haut qu'ils balancent leurs saletés ?", S)],
    [("Angus", "Ceux-là... ils vont voir de quel bois je me chauffe !", S)],
    [("Seku", "Là ! Les voilà !", SH)],
    [("Trafiquant 1", "Allez, encore un !", S)],
    [("Angus", "STOP ! Vous allez payer pour ça !", SH)],
    [("Trafiquant 2", "Encore ces gamins ?!", S)],
    [],
    [],
    [],
    [("Seku", "Pas touche à mon pote !", SH)],
    [],
    [("Angus", "Tu vas voir ce que c'est, la pollution !", SH)],
    [],
    [("Trafiquant 2", "Non... restez où vous êtes !", S)],
    [("Trafiquant 2", "AAAAH !", SH)],
    [("Angus", "Attention !", SH)],
    [("Seku", "Il s'échappe !", S)],
    [("Angus", "On a arrêté le massacre... pour aujourd'hui.", S)],
    [("Seku", "Le volcan... il se réveille !", SH)],
    [("Angus", "COUREZ !", SH)],
]

# Même chapitre, densité corrigée : répliques courtes, un cri par case de combat, pensées et narration.
REPLIQUES_DENSES: list[list[tuple[str, str, str]]] = [
    [("", "Au pied du volcan, le lendemain.", NAR), ("Seku", "C'est là-haut qu'ils balancent leurs saletés ?", S)],
    [("Angus", "Ils vont voir de quel bois je me chauffe !", S), ("Seku", "Garde ton souffle pour la montée.", S)],
    [("Seku", "Là ! Les voilà !", SH), ("Angus", "Des barils… en plein cratère ?!", S)],
    [("Trafiquant 1", "Allez, encore un !", S), ("Trafiquant 2", "Personne ne viendra jusqu'ici.", S)],
    [("Angus", "STOP ! Vous allez payer pour ça !", SH), ("Trafiquant 1", "Qu'est-ce que… ?!", S)],
    [("Trafiquant 2", "Encore ces gamins ?!", S), ("Trafiquant 1", "Je m'en occupe.", S)],
    [("Angus", "Seku, avec moi !", SH), ("Seku", "J'arrive !", SH)],
    [("Angus", "Raté, l'ami !", SH), ("Trafiquant 1", "Reste tranquille, gamin !", SH)],
    [("Angus", "Prends ça !", SH), ("Trafiquant 1", "Ouf !", SH)],
    [("Seku", "Pas touche à mon pote !", SH), ("Trafiquant 2", "Aïe ! Petite peste !", SH)],
    [("Seku", "Trop lent !", SH), ("Seku", "Il ne me lâchera pas…", TH)],
    [("Angus", "Tu vas voir ce que c'est, la pollution !", SH), ("Trafiquant 1", "Lâche-moi, brute !", SH)],
    [("Angus", "Et de un !", SH), ("Seku", "Bien joué, Angus !", S)],
    [("Trafiquant 2", "Non… restez où vous êtes !", S), ("Seku", "C'est fini, rends-toi !", S)],
    [("Trafiquant 2", "AAAAH !", SH), ("Angus", "Non ! Attrape ma main !", SH)],
    [("Angus", "Attention !", SH), ("Seku", "Merci… j'ai failli y passer.", S)],
    [("Seku", "Il s'échappe !", S), ("Angus", "Laisse-le, on le retrouvera.", S)],
    [("Angus", "On a arrêté le massacre… pour aujourd'hui.", S), ("Seku", "Ce n'est que le début.", TH)],
    [("Seku", "Le volcan… il se réveille !", SH), ("Angus", "Ce poison l'a rendu fou…", TH)],
    [("Angus", "COUREZ !", SH), ("Seku", "Plus vite, la lave arrive !", SH)],
]

CHARACTERS = ["Angus", "Seku", "Trafiquant 1", "Trafiquant 2"]
COMBAT_PAGES = (2, 3, 4)


def script_output(dense: bool) -> dict[str, Any]:
    """Réponse JSON du scénariste (format de presets/prompts/script.yaml)."""
    repliques = REPLIQUES_DENSES if dense else REPLIQUES_MAIGRES
    pages: dict[int, list[dict[str, Any]]] = {}
    for (planche, plan, intensity, importance, persos, description, sfx), dialogues in zip(
        CASES, repliques, strict=True
    ):
        pages.setdefault(planche, []).append(
            {
                "description": description,
                "setting": "Volcan de l'île, flanc rocheux, fumée.",
                "staging": description,
                "characters": list(persos),
                "shot_type": plan,
                "importance": importance,
                "intensity": intensity,
                "dialogues": [{"speaker": who, "text": text, "kind": kind} for who, text, kind in dialogues],
                "sfx": [{"text": t, "intensity": "choc"} for t in sfx],
            }
        )
    return {
        "pages": [
            {"rythme": "rapide" if n in COMBAT_PAGES else "normal", "panels": panels}
            for n, panels in sorted(pages.items())
        ],
        "summary": "Seku et Angus surprennent les trafiquants au volcan, les mettent en déroute, puis fuient l'éruption.",
    }


def breakdown(dense: bool) -> dict[str, Any]:
    """Même découpage au format de `PUT /chapters/{id}/pages`."""
    out = copy.deepcopy(script_output(dense))
    return {"pages": [{"rythme": p["rythme"], "panels": p["panels"]} for p in out["pages"]]}
