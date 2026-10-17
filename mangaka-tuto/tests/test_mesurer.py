"""Tests de mangaka-tuto/mesurer.py : lecture seule, chiffres justes, base vide.

python3 -m pytest mangaka-tuto/tests -q
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

TUTO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("mesurer", TUTO / "mesurer.py")
assert _spec and _spec.loader
mesurer = importlib.util.module_from_spec(_spec)
sys.modules["mesurer"] = mesurer
_spec.loader.exec_module(mesurer)

# Sous-ensemble du schéma du moteur (engine/mangaka_engine/store/models.py) lu par le script.
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

T0 = "2026-10-10 10:00:00.000000"


def _t(secondes: float) -> str:
    """Date SQLAlchemy à T0 + secondes."""
    from datetime import datetime, timedelta

    return (datetime.fromisoformat(T0) + timedelta(seconds=secondes)).strftime("%Y-%m-%d %H:%M:%S.%f")


# Dix générations factices : attente en file de 0 à 90 s (pas de 10), exécution de 10 à 100 s (pas de 10).
# Médiane d'exécution = 55 s, p90 = 91 s ; médiane d'attente = 45 s, p90 = 81 s (interpolation linéaire).
def _jobs() -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for i in range(10):
        cree = i * 200
        debut = cree + i * 10
        duree = (i + 1) * 10
        rows.append((1, None, "generation", "succeeded", None, _t(cree), _t(debut), _t(debut + duree), duree * 1000))
    rows += [
        (1, None, "generation", "failed", "ComfyUI injoignable (http://127.0.0.1:8188) après 3 essais", _t(2100),
         _t(2100), _t(2101), 1000),
        (1, None, "generation", "failed", "ComfyUI injoignable (http://127.0.0.1:9999) après 5 essais", _t(2200),
         _t(2200), _t(2201), 1000),
        (1, None, "script", "succeeded", None, _t(0), _t(0), _t(30), 30000),
        (None, None, "export", "cancelled", None, _t(10), None, None, None),
    ]  # fmt: skip
    return rows


def _base(chemin: Path, remplir: bool = True) -> Path:
    con = sqlite3.connect(chemin)
    con.executescript(SCHEMA)
    if remplir:
        con.execute("INSERT INTO chapters (id, project_id, number, title) VALUES (1, 1, 3, 'La fuite')")
        con.executemany(
            "INSERT INTO jobs (chapter_id, panel_id, step, status, error, created_at, started_at, finished_at,"
            " duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _jobs(),
        )
        qc = {
            "layers": {
                "detectors": {"status": "done", "score": 30, "at_least": None, "duration_ms": 12},
                "identity": {"status": "skipped", "score": None},
                "vision": {"status": "done", "score": 90, "duration_ms": 8000},
            },
            "override": None,
        }
        qc_ok = {"layers": {"detectors": {"status": "done", "score": 100, "duration_ms": 10}}, "override": None}
        con.executemany(
            "INSERT INTO panel_images (panel_id, version, kind, path, qc_verdict, qc_details) VALUES (?, ?, ?, '', ?, ?)",
            [
                (10, 1, "croquis", None, "{}"),
                (10, 2, "final", "reject", json.dumps(qc)),
                (10, 4, "final", "ok", json.dumps(qc_ok)),  # v3 effacée : comptée par la version max
                (11, 1, "final", "ok", json.dumps(qc_ok)),
            ],
        )
        con.executemany(
            "INSERT INTO generation_logs (kind, status, panel_id, duration_ms) VALUES (?, ?, ?, ?)",
            [("panel", "succeeded", 10, 1000), ("inpaint", "succeeded", 10, 2000), ("inpaint", "failed", 10, None)],
        )
        con.execute("INSERT INTO generation_events (verdict, action) VALUES ('edited', 'repair')")
    con.commit()
    con.close()
    return chemin


def _empreinte(dossier: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dossier.iterdir()) if p.is_file()}


def test_base_ouverte_en_lecture_seule(tmp_path: Path) -> None:
    dossier = tmp_path / "data"
    dossier.mkdir()
    base = _base(dossier / "mangaka.db")
    avant = _empreinte(dossier)
    mtime = base.stat().st_mtime_ns
    mesurer.main([str(base), "--sortie", str(tmp_path / "mesures.js")])
    assert _empreinte(dossier) == avant
    assert base.stat().st_mtime_ns == mtime
    # La connexion refuse toute écriture.
    con = mesurer.ouvrir_lecture_seule(base)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM jobs")
    con.close()
    assert _empreinte(dossier) == avant


def test_mediane_p90_et_attente_en_file(tmp_path: Path) -> None:
    m = mesurer.mesurer(_base(tmp_path / "mangaka.db"))
    assert m["vide"] is False
    gen = next(e for e in m["etapes"] if e["etape"] == "generation")
    assert gen["file_comfy"] is True
    assert gen["jobs"] == 12
    assert gen["duree_ms"]["n"] == 10  # durées des seuls jobs réussis
    assert gen["duree_ms"]["mediane"] == 55_000
    assert gen["duree_ms"]["p90"] == 91_000
    assert gen["duree_ms"]["max"] == 100_000
    assert gen["attente_ms"]["n"] == 12
    assert gen["taux_echec"] == round(2 / 12, 4)
    # Les deux erreurs ne diffèrent que par des nombres : un seul groupe.
    assert gen["erreurs"] == [{"message": "ComfyUI injoignable (http://#.#.#.#:#) après # essais", "n": 2}]
    assert m["goulot"] == "generation"
    script = next(e for e in m["etapes"] if e["etape"] == "script")
    assert script["file_comfy"] is False


def test_attente_en_file_des_seuls_jobs_reussis(tmp_path: Path) -> None:
    chemin = tmp_path / "mangaka.db"
    _base(chemin, remplir=False)
    con = sqlite3.connect(chemin)
    con.executemany(
        "INSERT INTO jobs (chapter_id, step, status, created_at, started_at, finished_at, duration_ms)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [r[:1] + r[2:4] + r[5:] for r in _jobs()[:10]],
    )
    con.commit()
    con.close()
    gen = mesurer.mesurer(chemin)["etapes"][0]
    assert gen["attente_ms"]["mediane"] == 45_000
    assert gen["attente_ms"]["p90"] == 81_000
    assert gen["attente_ms"]["max"] == 90_000
    assert gen["part_attente"] == round(45 / (45 + 55), 4)


def test_chapitre_cases_qc_et_reparations(tmp_path: Path) -> None:
    m = mesurer.mesurer(_base(tmp_path / "mangaka.db"))
    (ch,) = m["chapitres"]
    assert (ch["numero"], ch["titre"]) == (3, "La fuite")
    assert ch["temps_machine_ms"]["generation"] == sum((i + 1) * 10_000 for i in range(10)) + 2000
    assert ch["temps_machine_ms"]["script"] == 30_000
    assert ch["temps_humain_ms"] > 0
    cases = m["cases"]
    assert cases["cases"] == 2
    assert cases["regenerations_par_case"]["max"] == 3  # case 10 : versions 1 à 4
    assert cases["histogramme"][:4] == [1, 0, 0, 1]
    qc = m["qc"]
    assert qc["images_controlees"] == 3
    assert qc["taux_rejet"] == round(1 / 3, 4)
    det = next(c for c in qc["couches"] if c["couche"] == "detectors")
    assert (det["passees"], det["rejet"], det["taux_rejet"]) == (3, 1, round(1 / 3, 4))
    ident = next(c for c in qc["couches"] if c["couche"] == "identity")
    assert (ident["passees"], ident["sautees"]) == (0, 1)
    rep = m["reparations"]
    assert rep["reparations"] == 2
    assert rep["reparations_statuts"] == {"succeeded": 1, "failed": 1}
    assert rep["cases_reparees"] == 1


def test_base_vide_ou_absente(tmp_path: Path) -> None:
    vide = mesurer.mesurer(_base(tmp_path / "vide.db", remplir=False))
    assert vide["vide"] is True and "jobs" in vide["raison"]
    absente = mesurer.mesurer(tmp_path / "absente.db")
    assert absente["vide"] is True and "introuvable" in absente["raison"]
    assert not (tmp_path / "absente.db").exists()
    sans_table = tmp_path / "autre.db"
    sqlite3.connect(sans_table).close()
    assert mesurer.mesurer(sans_table)["vide"] is True


def test_fichier_js_lisible_par_la_page(tmp_path: Path) -> None:
    sortie = tmp_path / "out" / "mesures.js"
    assert mesurer.main([str(tmp_path / "rien.db"), "--sortie", str(sortie)]) == 0
    texte = sortie.read_text(encoding="utf-8")
    corps = texte.split("window.MESURES = ", 1)[1].rstrip().rstrip(";")
    data = json.loads(corps)
    assert data["vide"] is True
    assert data["commande"].startswith("python3 mangaka-tuto/mesurer.py ")


def test_quantile() -> None:
    assert mesurer.quantile([], 0.5) is None
    assert mesurer.quantile([7], 0.9) == 7
    assert mesurer.quantile([1, 2, 3, 4], 0.5) == 2.5
    assert mesurer.quantile(list(range(1, 11)), 0.9) == pytest.approx(9.1)


def test_schema_du_moteur(tmp_path: Path) -> None:
    """Sur une vraie base créée par le moteur (si le moteur est importable) : les colonnes lues existent."""
    db = pytest.importorskip("mangaka_engine.store.db")
    base = tmp_path / "mangaka.db"
    db.Database(base).dispose()
    con = sqlite3.connect(base)
    for table, cols in {
        "jobs": ["chapter_id", "step", "status", "error", "created_at", "started_at", "finished_at", "duration_ms"],
        "chapters": ["number", "title"],
        "panel_images": ["panel_id", "version", "kind", "qc_verdict", "qc_details"],
        "generation_logs": ["kind", "status", "panel_id", "duration_ms"],
        "generation_events": ["verdict", "action"],
    }.items():
        presentes = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        assert set(cols) <= presentes, (table, set(cols) - presentes)
    con.close()
    assert mesurer.mesurer(base)["vide"] is True
