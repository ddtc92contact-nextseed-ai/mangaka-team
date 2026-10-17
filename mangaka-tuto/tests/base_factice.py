#!/usr/bin/env python3
"""Base SQLite factice, au schéma réduit du moteur, pour essayer goulots.html sans vraie production.

    python3 mangaka-tuto/tests/base_factice.py /tmp/factice.db
    python3 mangaka-tuto/mesurer.py /tmp/factice.db

Trois chapitres de 12 cases, une file ComfyUI simulée (un job à la fois : l'attente en découle), quelques échecs,
un redémarrage du moteur, des versions de case contrôlées par le QC et des réparations. Tirage déterministe (graine
fixe) : `data/mesures.exemple.js` en est tiré. Les durées sont plausibles, PAS mesurées : c'est un exemple.
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Sous-ensemble du schéma du moteur (engine/mangaka_engine/store/models.py) lu par mesurer.py.
SCHEMA = """
CREATE TABLE chapters (id INTEGER PRIMARY KEY, project_id INTEGER, number INTEGER, title TEXT);
CREATE TABLE jobs (
  id INTEGER PRIMARY KEY, project_id INTEGER, chapter_id INTEGER, panel_id INTEGER, step VARCHAR(30),
  status VARCHAR(9), progress INTEGER, message TEXT, error TEXT, created_at DATETIME, started_at DATETIME,
  finished_at DATETIME, duration_ms INTEGER, params JSON
);
CREATE TABLE panel_images (
  id INTEGER PRIMARY KEY, panel_id INTEGER, version INTEGER, kind VARCHAR(7), path TEXT,
  qc_verdict VARCHAR(6), qc_details JSON, selected BOOLEAN
);
CREATE TABLE generation_logs (
  id INTEGER PRIMARY KEY, kind VARCHAR(30), status VARCHAR(20), panel_id INTEGER, duration_ms INTEGER
);
CREATE TABLE generation_events (id INTEGER PRIMARY KEY, verdict VARCHAR(20), action VARCHAR(30));
"""

FMT = "%Y-%m-%d %H:%M:%S.%f"
# Messages de la couche vision sautée (engine/mangaka_engine/pipeline/qc.py).
SAUTS_VISION = (
    "les couches 1-2 suffisent (score 100)",
    "les couches 1-2 suffisent (score 100)",
    "ComfyUI occupé : la vision ne tourne jamais pendant une génération",
)


class Simulation:
    def __init__(self, con: sqlite3.Connection, graine: int = 222) -> None:
        self.con = con
        self.r = random.Random(graine)
        self.horloge = datetime(2026, 10, 5, 9, 0, 0)
        self.file_libre = self.horloge  # fin du job ComfyUI en cours : la file est sérielle

    def attendre(self, secondes: float) -> None:
        self.horloge += timedelta(seconds=secondes)

    def job(self, chapitre: int | None, etape: str, duree_s: float, *, file: bool, erreur: str | None = None) -> None:
        cree = self.horloge
        debut = max(cree, self.file_libre) if file else cree + timedelta(milliseconds=self.r.randint(2, 40))
        fin = debut + timedelta(seconds=duree_s)
        if file:
            self.file_libre = fin
        self.con.execute(
            "INSERT INTO jobs (project_id, chapter_id, step, status, progress, message, error, created_at, started_at,"
            " finished_at, duration_ms, params) VALUES (1, ?, ?, ?, 100, '', ?, ?, ?, ?, ?, '{}')",
            (
                chapitre,
                etape,
                "failed" if erreur else "succeeded",
                erreur,
                cree.strftime(FMT),
                debut.strftime(FMT),
                fin.strftime(FMT),
                int(duree_s * 1000),
            ),
        )
        if not file:
            self.horloge = fin  # l'écran attend la fin du job texte avant la suite

    def chapitre(self, cid: int, panneau0: int) -> None:
        r = self.r
        self.job(cid, "scenes", r.uniform(25, 60), file=False)
        self.attendre(r.uniform(600, 1800))  # l'auteur relit et valide les scènes
        if r.random() < 0.5:
            self.job(
                cid, "script", 95, file=False, erreur="Le LLM n'a pas pu répondre : DeepSeek n'a pas répondu à temps"
            )
            self.attendre(60)
        self.job(cid, "script", r.uniform(70, 160), file=False)
        self.attendre(r.uniform(900, 2400))
        self.job(cid, "art_direction", r.uniform(40, 90), file=False)
        self.attendre(r.uniform(300, 1200))
        cases = range(panneau0, panneau0 + 12)
        for _ in cases:  # croquis de toutes les cases, mis en file d'un coup
            self.job(cid, "generation", r.uniform(6, 12), file=True)
        self.horloge = self.file_libre
        self.attendre(r.uniform(1200, 3600))  # name validée page par page, croquis retenus
        for i, _ in enumerate(cases):  # passages au propre, palier Qualité
            erreur = None
            if r.random() < 0.06:
                erreur = "ComfyUI n'a pas terminé la génération en 600 s (délai réglable : timeout_s du preset qwen-image-base-qualite)"
            elif cid == 2 and i == 7:
                erreur = "Interrompu par un redémarrage du moteur"
            self.job(cid, "generation", r.uniform(150, 230), file=True, erreur=erreur)
            self.attendre(r.uniform(1, 4))
            self.job(cid, "qc", r.uniform(2, 5) + (r.uniform(18, 35) if r.random() < 0.3 else 0), file=True)
        self.horloge = self.file_libre
        self.attendre(r.uniform(600, 2400))  # choix des versions, réparations
        for _ in range(r.randint(2, 4)):
            self.job(cid, "generation", r.uniform(30, 50), file=True)
        self.horloge = self.file_libre
        self.attendre(r.uniform(300, 900))
        for _ in range(12):
            self.job(cid, "finishing", r.uniform(25, 45), file=True)
        self.horloge = self.file_libre
        self.attendre(r.uniform(1800, 5400))  # lettrage à la main
        self.job(cid, "export", r.uniform(15, 30), file=False)
        self.attendre(r.uniform(20, 30) * 3600)  # le lendemain

    def images(self, panneau0: int, n: int) -> None:
        r = self.r
        for panel in range(panneau0, panneau0 + n):
            version = 0
            for _ in range(r.choice((1, 1, 2))):
                version += 1
                self.image(panel, version, "croquis", None)
            for k in range(r.choice((1, 1, 1, 2, 2, 3, 5))):
                version += 1
                if k and r.random() < 0.3:
                    continue  # version effacée : le numéro n'est jamais réutilisé
                det = r.choice((100, 100, 100, 85, 65, 30))
                vision = r.choice((None, None, 80, 55, 35))
                score = det if vision is None else round(0.6 * det + 0.4 * vision)
                verdict = "ok" if score >= 70 else "reject" if score < 40 else "review"
                details = {
                    "verdict": verdict,
                    "score": score,
                    "layers": {
                        "detectors": {
                            "status": "done",
                            "score": det,
                            "at_least": None,
                            "duration_ms": r.randint(8, 30),
                        },
                        "identity": r.choice(
                            (
                                {"status": "skipped", "score": None},
                                {"status": "done", "score": r.choice((90, 75, 60)), "duration_ms": r.randint(200, 600)},
                            )
                        ),
                        "vision": (
                            {"status": "skipped", "score": None, "message": r.choice(SAUTS_VISION)}
                            if vision is None
                            else {"status": "done", "score": vision, "duration_ms": r.randint(18000, 35000)}
                        ),
                    },
                    "override": {"by": "auteur"} if verdict == "review" and r.random() < 0.3 else None,
                }
                self.image(panel, version, "final", verdict, details)
            for _ in range(r.choice((0, 0, 0, 1, 2))):
                ok = r.random() < 0.85
                self.con.execute(
                    "INSERT INTO generation_logs (kind, status, panel_id, duration_ms) VALUES ('inpaint', ?, ?, ?)",
                    ("succeeded" if ok else "failed", panel, r.randint(30000, 50000) if ok else None),
                )
                self.con.execute("INSERT INTO generation_events (verdict, action) VALUES ('edited', 'repair')")

    def image(self, panel: int, version: int, kind: str, verdict: str | None, details: object = None) -> None:
        self.con.execute(
            "INSERT INTO panel_images (panel_id, version, kind, path, qc_verdict, qc_details, selected)"
            " VALUES (?, ?, ?, '', ?, ?, 0)",
            (panel, version, kind, verdict, json.dumps(details or {})),
        )
        self.con.execute(
            "INSERT INTO generation_logs (kind, status, panel_id, duration_ms) VALUES (?, 'succeeded', ?, ?)",
            ("croquis" if kind == "croquis" else "panel", panel, self.r.randint(6000, 220000)),
        )


def construire(chemin: Path) -> Path:
    if chemin.exists():
        chemin.unlink()
    con = sqlite3.connect(chemin)
    con.executescript(SCHEMA)
    sim = Simulation(con)
    # Série : planche de style, fiches de référence, couverture.
    for _ in range(4):
        sim.job(None, "style_board", sim.r.uniform(60, 90), file=True)
    for _ in range(8):
        sim.job(None, "reference", sim.r.uniform(30, 45), file=True)
    sim.horloge = sim.file_libre
    sim.attendre(3600)
    for numero, titre in ((1, "Le départ"), (2, "La fuite"), (3, "Le marché aux lanternes")):
        con.execute("INSERT INTO chapters (id, project_id, number, title) VALUES (?, 1, ?, ?)", (numero, numero, titre))
        sim.chapitre(numero, numero * 100)
        sim.images(numero * 100, 12)
    for _ in range(2):
        sim.job(None, "cover", sim.r.uniform(200, 260), file=True)
    con.commit()
    con.close()
    return chemin


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage : python3 mangaka-tuto/tests/base_factice.py <chemin.db>")
    print(f"Base factice écrite : {construire(Path(sys.argv[1]))}")
