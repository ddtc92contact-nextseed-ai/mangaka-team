#!/usr/bin/env python3
"""Mesure les goulots d'étranglement du pipeline à partir de la base SQLite du moteur.

    python3 mangaka-tuto/mesurer.py [chemin/vers/mangaka.db] [--sortie fichier.js]

Sans chemin, la base est cherchée là où le moteur la range : `MANGAKA_DATA_DIR` (environnement, puis `.env` à la
racine du dépôt), sinon `data/` du dépôt, fichier `mangaka.db` (engine/mangaka_engine/config.py).

La base est ouverte en LECTURE SEULE (`file:…?mode=ro` et `PRAGMA query_only`) : rien n'y est jamais écrit. Le
script ne touche ni aux dossiers de ComfyUI ni à `output/`. Il écrit un seul fichier, `mangaka-tuto/data/mesures.js`
(`window.MESURES = {…}`), lu par `goulots.html` sans serveur (`file://`). Bibliothèque standard seulement.

Une base vide, absente ou d'un ancien schéma donne un fichier « pas encore de données » au lieu d'une erreur.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
SORTIE = ICI / "data" / "mesures.js"

# Étapes de job exécutées par la file ComfyUI sérielle (engine/mangaka_engine/main.py, build_context ; vérifié par
# verifier.py contre `queueSteps` de assets/data.js).
# Pour elles, l'attente (started − created) est surtout du temps passé derrière les autres jobs de la file.
ETAPES_FILE_COMFY = (
    "generation",  # cases, croquis, passages au propre et réparations ciblées
    "qc",
    "qc_bench",
    "comfyui_trial",
    "finishing",
    "reference",
    "style_board",
    "control_map",
    "cover",
)

# Seuils du verdict combiné (presets/qc.yaml : thresholds.ok_min, thresholds.reject_below), appliqués ici au score
# de chaque couche pour estimer ce que chaque couche rejette ou envoie « à revoir ».
QC_OK_MIN = 70
QC_REJET_SOUS = 40
COUCHES_QC = ("detectors", "identity", "vision")

# Au-delà, un trou entre deux jobs d'un chapitre est compté comme une absence (nuit, week-end), pas comme du
# temps de travail humain entre deux étapes.
TROU_MAX_MS = 4 * 3600 * 1000

Mesures = dict[str, Any]


# --------------------------------------------------------------------------- statistiques


def quantile(valeurs: list[float], q: float) -> float | None:
    """Quantile par interpolation linéaire entre rangs (la méthode par défaut de numpy et du tableur)."""
    if not valeurs:
        return None
    v = sorted(valeurs)
    pos = (len(v) - 1) * q
    bas = int(pos)
    haut = min(bas + 1, len(v) - 1)
    return v[bas] + (v[haut] - v[bas]) * (pos - bas)


def resume(valeurs: list[float]) -> dict[str, Any]:
    """Nombre, médiane, p90, max et total d'une série de durées (ms)."""
    if not valeurs:
        return {"n": 0, "mediane": None, "p90": None, "max": None, "total": 0}
    return {
        "n": len(valeurs),
        "mediane": arrondi(quantile(valeurs, 0.5)),
        "p90": arrondi(quantile(valeurs, 0.9)),
        "max": arrondi(max(valeurs)),
        "total": arrondi(sum(valeurs)),
    }


def arrondi(x: float | None) -> int | None:
    return None if x is None else int(round(x))


def taux(n: int, sur: int) -> float | None:
    return None if sur == 0 else round(n / sur, 4)


def date(texte: Any) -> datetime | None:
    """Dates écrites par SQLAlchemy (`2026-10-14 09:41:56.734471`, UTC naïf) ou en ISO."""
    if not texte:
        return None
    try:
        d = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=None) if d.tzinfo else d


def ecart_ms(debut: datetime | None, fin: datetime | None) -> float | None:
    if debut is None or fin is None:
        return None
    return max(0.0, (fin - debut).total_seconds() * 1000)


def iso(d: datetime | None) -> str | None:
    return None if d is None else d.replace(microsecond=0).isoformat() + "Z"


def regrouper_erreur(texte: str) -> str:
    """Forme générique d'un message d'erreur : première ligne, nombres et identifiants remplacés."""
    ligne = next((x.strip() for x in str(texte).splitlines() if x.strip()), "")
    ligne = re.sub(r'"[^"]{0,80}"', '"…"', ligne)
    ligne = re.sub(r"\b[0-9a-f]{12,}\b", "…", ligne)
    ligne = re.sub(r"\d+", "#", ligne)
    return (ligne[:157] + "…") if len(ligne) > 160 else ligne or "(erreur sans message)"


def json_ou(texte: Any, defaut: Any) -> Any:
    if texte is None or texte == "":
        return defaut
    try:
        return json.loads(texte)
    except (TypeError, ValueError):
        return defaut


# --------------------------------------------------------------------------- lecture de la base


def ouvrir_lecture_seule(chemin: Path) -> sqlite3.Connection:
    """Connexion strictement en lecture : le fichier n'est jamais ouvert en écriture."""
    uri = f"file:{quote(str(chemin.resolve()))}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.execute("PRAGMA query_only = ON")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.OperationalError:
        # Base en WAL dans un dossier non inscriptible (fichier -shm impossible à créer) : lecture « immuable ».
        con = sqlite3.connect(uri + "&immutable=1", uri=True)
        con.execute("PRAGMA query_only = ON")
    con.row_factory = sqlite3.Row
    return con


def colonnes(con: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in con.execute(f'PRAGMA table_info("{table}")')}


def lignes(con: sqlite3.Connection, table: str, voulues: list[str]) -> list[dict[str, Any]]:
    """Lignes d'une table, avec les seules colonnes présentes (les absentes valent None) ; [] sans la table."""
    presentes = colonnes(con, table)
    if not presentes:
        return []
    choix = [c for c in voulues if c in presentes]
    champs = ", ".join(f'"{c}"' for c in choix)
    return [
        {c: (r[c] if c in choix else None) for c in voulues} for r in con.execute(f'SELECT {champs} FROM "{table}"')
    ]


# --------------------------------------------------------------------------- mesures


def mesurer_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    par_etape: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for j in jobs:
        par_etape[str(j["step"] or "?")].append(j)
    sortie: list[dict[str, Any]] = []
    for etape, liste in par_etape.items():
        statuts = Counter(str(j["status"] or "?") for j in liste)
        durees: list[float] = []
        attentes: list[float] = []
        for j in liste:
            debut, fin, cree = date(j["started_at"]), date(j["finished_at"]), date(j["created_at"])
            if j["status"] == "succeeded":
                d = j["duration_ms"] if j["duration_ms"] is not None else ecart_ms(debut, fin)
                if d is not None:
                    durees.append(float(d))
            attente = ecart_ms(cree, debut)
            if attente is not None:
                attentes.append(attente)
        erreurs = Counter(regrouper_erreur(j["error"]) for j in liste if j["status"] == "failed" and j["error"])
        sans_message = sum(1 for j in liste if j["status"] == "failed" and not j["error"])
        if sans_message:
            erreurs["(échec sans message)"] += sans_message
        termines = statuts["succeeded"] + statuts["failed"]
        exe, att = resume(durees), resume(attentes)
        sortie.append(
            {
                "etape": etape,
                "file_comfy": etape in ETAPES_FILE_COMFY,
                "jobs": len(liste),
                "statuts": dict(statuts),
                "taux_echec": taux(statuts["failed"], termines),
                "duree_ms": exe,
                "attente_ms": att,
                # Part de l'attente dans le temps total vu par l'auteur (attente + exécution), en médiane.
                "part_attente": (
                    round(att["mediane"] / (att["mediane"] + exe["mediane"]), 4)
                    if att["mediane"] is not None and exe["mediane"] and att["mediane"] + exe["mediane"] > 0
                    else None
                ),
                "erreurs": [{"message": m, "n": n} for m, n in erreurs.most_common(5)],
                # Coût en temps machine et en attente : sert à classer les goulots.
                "cout_ms": (exe["total"] or 0) + (att["total"] or 0),
            }
        )
    sortie.sort(key=lambda e: (-e["cout_ms"], e["etape"]))
    return sortie


def mesurer_chapitres(jobs: list[dict[str, Any]], chapitres: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    par_chapitre: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for j in jobs:
        if j["chapter_id"] is not None:
            par_chapitre[int(j["chapter_id"])].append(j)
    sortie = []
    for cid, liste in par_chapitre.items():
        liste.sort(key=lambda j: (date(j["created_at"]) or datetime.min, j["id"] or 0))
        temps_par_etape: dict[str, int] = defaultdict(int)
        for j in liste:
            d = j["duration_ms"]
            if d is None:
                d = ecart_ms(date(j["started_at"]), date(j["finished_at"]))
            if d is not None:
                temps_par_etape[str(j["step"])] += int(d)
        # Temps humain présumé : intervalles où aucun job du chapitre ne tourne, entre la fin du dernier job et la
        # création du suivant (l'auteur relit, valide, corrige). Les trous de plus de TROU_MAX_MS sont des absences.
        humain = 0
        absences = 0
        transitions: dict[str, list[float]] = defaultdict(list)
        fin_courante: datetime | None = None
        etape_prec: str | None = None
        for j in liste:
            cree = date(j["created_at"])
            fin = date(j["finished_at"]) or date(j["started_at"]) or cree
            if fin_courante is not None and cree is not None and cree > fin_courante:
                trou = ecart_ms(fin_courante, cree) or 0.0
                if trou > TROU_MAX_MS:
                    absences += 1
                else:
                    humain += int(trou)
                    if etape_prec and etape_prec != j["step"]:
                        transitions[f"{etape_prec} → {j['step']}"].append(trou)
            if fin is not None and (fin_courante is None or fin > fin_courante):
                fin_courante = fin
            etape_prec = str(j["step"])
        debut = date(liste[0]["created_at"])
        info = chapitres.get(cid, {})
        sortie.append(
            {
                "chapitre_id": cid,
                "numero": info.get("number"),
                "titre": info.get("title") or "",
                "jobs": len(liste),
                "debut": iso(debut),
                "fin": iso(fin_courante),
                "duree_totale_ms": arrondi(ecart_ms(debut, fin_courante)),
                "temps_machine_ms": dict(sorted(temps_par_etape.items(), key=lambda kv: -kv[1])),
                "temps_humain_ms": humain,
                "absences": absences,
                "transitions": [
                    {"passage": k, "n": len(v), "mediane_ms": arrondi(quantile(v, 0.5))}
                    for k, v in sorted(transitions.items(), key=lambda kv: -sum(kv[1]))
                ][:8],
            }
        )
    sortie.sort(key=lambda c: (c["numero"] is None, c["numero"] or 0, c["chapitre_id"]))
    return sortie


def mesurer_cases(images: list[dict[str, Any]]) -> dict[str, Any]:
    """Régénérations par case : `version` n'est jamais réutilisée, son maximum compte aussi les versions effacées."""
    par_case: dict[int, dict[str, Any]] = defaultdict(lambda: {"max_version": 0, "final": 0, "croquis": 0})
    for im in images:
        c = par_case[int(im["panel_id"])]
        c["max_version"] = max(c["max_version"], int(im["version"] or 0))
        c["croquis" if im["kind"] == "croquis" else "final"] += 1
    regens = [max(0, c["max_version"] - 1) for c in par_case.values()]
    finales = [c["final"] for c in par_case.values()]
    hist = Counter(min(r, 5) for r in regens)
    return {
        "cases": len(par_case),
        "images_par_case": resume([float(c["max_version"]) for c in par_case.values()]),
        "regenerations_par_case": resume([float(r) for r in regens]),
        "versions_finales_presentes": resume([float(f) for f in finales]),
        "croquis_presents": sum(c["croquis"] for c in par_case.values()),
        # 0, 1, 2, 3, 4, « 5 et plus » régénérations.
        "histogramme": [hist.get(i, 0) for i in range(6)],
        "cases_3_regenerations_ou_plus": sum(1 for r in regens if r >= 3),
    }


def mesurer_qc(images: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts: Counter[str] = Counter()
    forces = 0
    couches: dict[str, Counter[str]] = {c: Counter() for c in COUCHES_QC}
    durees: dict[str, list[float]] = {c: [] for c in COUCHES_QC}
    for im in images:
        if im["qc_verdict"]:
            verdicts[str(im["qc_verdict"])] += 1
        details = json_ou(im["qc_details"], {})
        if not isinstance(details, dict):
            continue
        if details.get("override"):
            forces += 1
        for nom, couche in (details.get("layers") or {}).items():
            if nom not in couches or not isinstance(couche, dict):
                continue
            statut = str(couche.get("status") or "?")
            couches[nom][statut] += 1
            if statut != "done":
                continue
            score = couche.get("score")
            plancher = couche.get("at_least")
            if plancher == "reject" or (isinstance(score, int | float) and score < QC_REJET_SOUS):
                couches[nom]["rejet"] += 1
            elif plancher == "review" or (isinstance(score, int | float) and score < QC_OK_MIN):
                couches[nom]["a_revoir"] += 1
            else:
                couches[nom]["ok"] += 1
            if isinstance(couche.get("duration_ms"), int | float):
                durees[nom].append(float(couche["duration_ms"]))
    total = sum(verdicts.values())
    return {
        "images_controlees": total,
        "verdicts": dict(verdicts),
        "taux_rejet": taux(verdicts["reject"], total),
        "taux_a_revoir": taux(verdicts["review"], total),
        "valides_quand_meme": forces,
        "couches": [
            {
                "couche": nom,
                "passees": c["done"],
                "sautees": c["skipped"],
                "en_erreur": c["error"],
                "indisponibles": c["unavailable"],
                "rejet": c["rejet"],
                "a_revoir": c["a_revoir"],
                "taux_rejet": taux(c["rejet"], c["done"]),
                "taux_a_revoir": taux(c["a_revoir"], c["done"]),
                "duree_ms": resume(durees[nom]),
                "statuts": {k: v for k, v in c.items() if k not in ("rejet", "a_revoir", "ok")},
            }
            for nom, c in couches.items()
        ],
    }


def mesurer_reparations(logs: list[dict[str, Any]], evenements: list[dict[str, Any]]) -> dict[str, Any]:
    # Sorte « inpaint » = réparation ciblée (engine/mangaka_engine/pipeline/journal.py, KINDS).
    reparations = [lg for lg in logs if lg["kind"] == "inpaint"]
    par_sorte: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lg in logs:
        par_sorte[str(lg["kind"])].append(lg)
    statuts = Counter(str(lg["status"]) for lg in reparations)
    actions = Counter(str(e["action"]) for e in evenements)
    verdicts = Counter(str(e["verdict"]) for e in evenements)
    return {
        "generations_journalisees": len(logs),
        "par_sorte": dict(Counter(str(lg["kind"]) for lg in logs)),
        # Durées par sorte de génération (case, croquis, passage au propre, réparation…) : le journal distingue ce
        # que la table jobs range sous la seule étape `generation`.
        "sortes": [
            {
                "sorte": sorte,
                "n": len(liste),
                "echecs": sum(1 for lg in liste if lg["status"] == "failed"),
                "duree_ms": resume([float(lg["duration_ms"]) for lg in liste if lg["duration_ms"] is not None]),
            }
            for sorte, liste in sorted(par_sorte.items())
        ],
        "reparations": len(reparations),
        "reparations_statuts": dict(statuts),
        "reparations_duree_ms": resume(
            [float(lg["duration_ms"]) for lg in reparations if lg["duration_ms"] is not None]
        ),
        "cases_reparees": len({lg["panel_id"] for lg in reparations if lg["panel_id"] is not None}),
        "evenements_auteur": {"actions": dict(actions), "verdicts": dict(verdicts)},
    }


# Signaux comptés dans les messages réels du moteur (texte exact cité en commentaire), pour chiffrer les faiblesses.
SIGNAUX_JOBS = {
    # engine/mangaka_engine/pipeline/jobs.py (recover) : « Interrompu par un redémarrage du moteur »
    "interrompus_redemarrage": "redémarrage du moteur",
    # engine/mangaka_engine/pipeline/script.py : « Le LLM n'a pas pu répondre : … » (même forme dans les autres agents)
    "llm_sans_reponse": "LLM n'a pas pu répondre",
    # engine/mangaka_engine/pipeline/generation.py : « ComfyUI n'a pas terminé la génération en N s »
    "comfy_delai_depasse": "n'a pas terminé la génération",
    # engine/mangaka_engine/providers/comfyui/http.py : « ComfyUI ne répond pas » / « ComfyUI hors ligne »
    "comfy_injoignable": ("ComfyUI ne répond pas", "ComfyUI hors ligne", "ComfyUI indisponible"),
}
# engine/mangaka_engine/pipeline/qc.py : vision sautée parce qu'une génération tournait encore.
VISION_COMFY_OCCUPE = "ComfyUI occupé"


def mesurer_signaux(jobs: list[dict[str, Any]], images: list[dict[str, Any]]) -> dict[str, Any]:
    erreurs = [str(j["error"]) for j in jobs if j["status"] == "failed" and j["error"]]
    sortie: dict[str, Any] = {}
    for cle, motifs in SIGNAUX_JOBS.items():
        liste = (motifs,) if isinstance(motifs, str) else motifs
        sortie[cle] = sum(1 for e in erreurs if any(m in e for m in liste))
    vision_occupe = vision_erreur = relances_auto = 0
    for im in images:
        details = json_ou(im["qc_details"], {})
        if not isinstance(details, dict):
            continue
        vision = (details.get("layers") or {}).get("vision") or {}
        if isinstance(vision, dict):
            vision_occupe += vision.get("status") == "skipped" and VISION_COMFY_OCCUPE in str(vision.get("message"))
            vision_erreur += vision.get("status") == "error"
        relances_auto += bool(details.get("auto_retry"))
    sortie.update(
        vision_sautee_comfy_occupe=vision_occupe,
        vision_en_erreur=vision_erreur,
        relances_auto_qc=relances_auto,
        jobs_annules=sum(1 for j in jobs if j["status"] == "cancelled"),
    )
    return sortie


def mesurer(chemin: Path) -> Mesures:
    """Toutes les mesures d'une base (dictionnaire prêt à sérialiser)."""
    base: Mesures = {
        "version": 1,
        "genere_le": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "base": str(chemin),
        "commande": f"python3 mangaka-tuto/mesurer.py {chemin}",
        "vide": True,
        "raison": "",
    }
    if not chemin.is_file():
        base["raison"] = f"Base introuvable : {chemin}"
        return base
    try:
        con = ouvrir_lecture_seule(chemin)
    except sqlite3.Error as exc:
        base["raison"] = f"Base illisible : {exc}"
        return base
    try:
        jobs = lignes(
            con,
            "jobs",
            ["id", "chapter_id", "panel_id", "step", "status", "error", "created_at", "started_at", "finished_at",
             "duration_ms"],
        )  # fmt: skip
        if not jobs:
            base["raison"] = "La table jobs est vide ou absente : aucun job n'a encore tourné sur cette base."
            return base
        chapitres = {int(c["id"]): c for c in lignes(con, "chapters", ["id", "number", "title"])}
        images = lignes(con, "panel_images", ["panel_id", "version", "kind", "qc_verdict", "qc_details"])
        logs = lignes(con, "generation_logs", ["kind", "status", "panel_id", "duration_ms"])
        evenements = lignes(con, "generation_events", ["verdict", "action"])
    except sqlite3.Error as exc:
        base["raison"] = f"Lecture impossible : {exc}"
        return base
    finally:
        con.close()

    dates = [d for j in jobs for d in (date(j["created_at"]), date(j["finished_at"])) if d]
    etapes = mesurer_jobs(jobs)
    base.update(
        vide=False,
        periode={"debut": iso(min(dates)) if dates else None, "fin": iso(max(dates)) if dates else None},
        totaux={
            "jobs": len(jobs),
            "echecs": sum(1 for j in jobs if j["status"] == "failed"),
            "annules": sum(1 for j in jobs if j["status"] == "cancelled"),
            "en_cours": sum(1 for j in jobs if j["status"] in ("pending", "running")),
            "chapitres": len({j["chapter_id"] for j in jobs if j["chapter_id"] is not None}),
        },
        goulot=etapes[0]["etape"] if etapes and etapes[0]["cout_ms"] > 0 else None,
        etapes=etapes,
        chapitres=mesurer_chapitres(jobs, chapitres),
        cases=mesurer_cases(images),
        qc=mesurer_qc(images),
        reparations=mesurer_reparations(logs, evenements),
        signaux=mesurer_signaux(jobs, images),
    )
    return base


# --------------------------------------------------------------------------- base par défaut et écriture


def lire_env(fichier: Path, cle: str) -> str | None:
    if not fichier.is_file():
        return None
    for ligne in fichier.read_text(encoding="utf-8", errors="replace").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("export "):
            ligne = ligne[7:].lstrip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        k, v = ligne.split("=", 1)
        if k.strip().lower() == cle.lower():
            return v.split(" #", 1)[0].strip().strip("'\"") or None
    return None


def base_par_defaut() -> Path:
    """Même règle que le moteur : MANGAKA_DATA_DIR (relatif = depuis la racine du dépôt), sinon data/."""
    dossier = os.environ.get("MANGAKA_DATA_DIR") or lire_env(RACINE / ".env", "MANGAKA_DATA_DIR")
    d = Path(dossier).expanduser() if dossier else RACINE / "data"
    if not d.is_absolute():
        d = RACINE / d
    return d / "mangaka.db"


def ecrire(mesures: Mesures, sortie: Path) -> None:
    sortie.parent.mkdir(parents=True, exist_ok=True)
    corps = json.dumps(mesures, ensure_ascii=False, indent=1)
    sortie.write_text(
        "/* Généré par mangaka-tuto/mesurer.py — ne pas modifier à la main, ne pas commiter. */\n"
        f"window.MESURES = {corps};\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mesure les goulots du pipeline (base ouverte en lecture seule).")
    p.add_argument("base", nargs="?", type=Path, help="chemin de mangaka.db (défaut : celui du moteur)")
    p.add_argument("--sortie", type=Path, default=SORTIE, help=f"fichier écrit (défaut : {SORTIE})")
    p.add_argument(
        "--exemple", action="store_true", help="marquer la sortie comme exemple factice (mesures.exemple.js)"
    )
    args = p.parse_args(argv)
    chemin: Path = (args.base or base_par_defaut()).expanduser()
    mesures = mesurer(chemin)
    if args.exemple:
        mesures.update(
            exemple=True,
            base="base factice (tests/base_factice.py)",
            commande="python3 mangaka-tuto/mesurer.py <chemin-base>",
        )
    ecrire(mesures, args.sortie)
    if mesures["vide"]:
        print(f"Pas encore de données — {mesures['raison']}", file=sys.stderr)
    else:
        t = mesures["totaux"]
        print(f"{t['jobs']} jobs mesurés ({t['echecs']} échecs), goulot n°1 : {mesures['goulot'] or '—'}")
    print(f"Écrit : {args.sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
