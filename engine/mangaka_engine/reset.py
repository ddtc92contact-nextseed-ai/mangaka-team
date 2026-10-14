"""Remise à zéro de l'atelier : sauvegarde, puis effacement des séries (base, data/, dossiers de ComfyUI).

Jamais automatique : lancée par `npm run reset` (ce module : `python -m mangaka_engine.reset`) ou par le
bouton « Remettre l'atelier à zéro » de l'écran Réglages (`POST /reset`).

1. Refus si un job est en attente ou en cours (`ResetBusyError`).
2. Sauvegarde, toujours : `data/backups/reset-<date-heure>/mangaka.db` (API de sauvegarde de SQLite, copie
   cohérente même pendant que le moteur tourne) + `data.tar.gz` (contenu de data/ sans la base ni les
   sauvegardes). Si elle échoue, rien n'est supprimé (`ResetError`).
3. Mode « séries » (défaut) : toutes les séries et tout ce qui en dépend (`SERIES_TABLES`, savoir-faire et
   surcharges d'agents propres à une série), les fichiers de data/ (tout sauf la base et `backups/`) et les
   dossiers de `COMFYUI_DIR/{output,input}/mangaka/` (sauf `old/`). Compteurs d'ids remis à zéro.
   Mode « tout » (`--all`) : en plus, réglages globaux des agents et savoir-faire de l'équipe (`GLOBAL_TABLES`)
   reviennent aux valeurs par défaut (tables vides). Jamais : presets, .env, launcher.env, sauvegardes, `old/`.
4. Vérification : base à la dernière migration, clés étrangères cohérentes, aucune série.

Suppressions confinées : enfants directs de data/ (hors base et `backups/`) et de `<ComfyUI>/<output|input>/
mangaka/` (hors `old/`) ; un lien symbolique est retiré sans suivre sa cible ; un nom `..`, vide ou avec un
séparateur est refusé.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import tarfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Settings, get_settings
from .store.db import create_db_engine
from .store.migrations import SCHEMA_VERSION

log = logging.getLogger("mangaka_engine")

CONFIRM_WORD = "RÉINITIALISER"
BACKUPS = "backups"
COMFY_ROOT = "mangaka"
COMFY_AREAS = ("output", "input")
KEEP_COMFY = "old"  # output/mangaka/old/ : jamais touché
ACTIVE_JOBS = ("pending", "running")

# Tables vidées entièrement en mode « séries » (ordre : dépendances d'abord).
SERIES_TABLES = (
    # Journal des générations et verdicts : décrivent des cases des séries effacées (sauvegardés avant).
    "generation_events",
    "generation_logs",
    # Décisions de la garde d'étapes (validée, forcée) : chapitres des séries effacées.
    "chapter_stage_decisions",
    "chapter_crowd_marks",
    "panel_image_annotations",
    "qc_bench_runs",
    "llm_runs",
    "bubbles",
    "page_directions",
    "panel_dialog_turns",
    "panel_images",
    "panel_dialog_turns",
    "panels",
    "pages",
    # Lieux de la série (unité de lieu des cases) : après les cases qui s'y rattachent.
    "series_locations",
    # Tomes : chapitres inclus et versions de couverture (fichiers sous data/projects/<série>/volumes/).
    "volume_covers",
    "volume_chapters",
    "volumes",
    "chapters",
    "reference_variants",
    "character_images",
    "characters",
    "series_asset_images",
    "series_assets",
    "series_bibles",
    "series_logos",
    "cover_charters",
    "jobs",
    "projects",
)
# Réglages globaux des agents (« L'équipe ») et savoir-faire : seules leurs lignes propres à une série partent
# en mode « séries » ; vidées entièrement en mode « tout ».
GLOBAL_TABLES = (
    "agent_profile_versions",
    "agent_profiles",
    "knowledge_chunks",
    "knowledge_documents",
    "knowledge_collections",
)
_SERIES_ROWS = (
    "DELETE FROM agent_profile_versions WHERE profile_id IN (SELECT id FROM agent_profiles WHERE project_id IS NOT NULL)",
    "DELETE FROM agent_profiles WHERE project_id IS NOT NULL",
    "DELETE FROM knowledge_chunks WHERE collection_id IN"
    " (SELECT id FROM knowledge_collections WHERE project_id IS NOT NULL)",
    "DELETE FROM knowledge_documents WHERE collection_id IN"
    " (SELECT id FROM knowledge_collections WHERE project_id IS NOT NULL)",
    "DELETE FROM knowledge_collections WHERE project_id IS NOT NULL",
)


class ResetError(Exception):
    """Remise à zéro impossible ou interrompue (message en français, affiché tel quel)."""


class ResetBusyError(ResetError):
    """Un job tourne : la remise à zéro est refusée."""


class UnsafePathError(ResetError):
    pass


@dataclass
class ResetReport:
    backup: Path
    all: bool
    series_deleted: int
    data_removed: list[str] = field(default_factory=list)
    comfyui_removed: list[str] = field(default_factory=list)
    comfyui_warning: str | None = None

    def lines(self) -> list[str]:
        out = [
            f"Sauvegarde : {self.backup}",
            f"{self.series_deleted} série(s) effacée(s)"
            + (" ; réglages globaux et savoir-faire remis par défaut" if self.all else ""),
            f"data/ : {len(self.data_removed)} élément(s) effacé(s)",
        ]
        if self.comfyui_warning:
            out.append(f"ComfyUI : {self.comfyui_warning}")
        else:
            out.append(f"ComfyUI : {len(self.comfyui_removed)} dossier(s) effacé(s) (old/ conservé)")
        return out


def is_confirmation(value: str | None) -> bool:
    return unicodedata.normalize("NFC", (value or "").strip()) == CONFIRM_WORD


# --- sécurité des chemins -----------------------------------------------------------------
def remove_child(parent: Path, name: str) -> bool:
    """Supprime `parent/name` (fichier, dossier, ou seulement le lien s'il s'agit d'un lien symbolique).
    Refuse tout nom qui sortirait de `parent`."""
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
        raise UnsafePathError(f"nom refusé : {name!r}")
    path = parent / name
    if path.is_symlink():
        path.unlink()
        return True
    if not path.exists():
        return False
    if path.resolve().parent != parent.resolve():
        raise UnsafePathError(f"chemin hors de {parent} : {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _db_files(db_path: Path) -> set[str]:
    return {db_path.name, *(db_path.name + s for s in ("-wal", "-shm", "-journal"))}


def _kept_in_data(settings: Settings) -> set[str]:
    return {BACKUPS} | _db_files(settings.database_path)


# --- ComfyUI --------------------------------------------------------------------------------
def comfyui_root(settings: Settings) -> tuple[Path | None, str | None]:
    """Dossier de ComfyUI à nettoyer (COMFYUI_DIR), ou None et la raison. Jamais deviné."""
    raw = (settings.comfyui_dir or "").strip()
    if not raw:
        return None, "COMFYUI_DIR non renseigné : dossiers de ComfyUI laissés en place"
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        return None, f"COMFYUI_DIR doit être un chemin absolu ({raw}) : dossiers de ComfyUI laissés en place"
    if not path.is_dir():
        return None, f"dossier ComfyUI introuvable ({path}) : dossiers de ComfyUI laissés en place"
    return path, None


def wipe_comfyui(root: Path) -> tuple[list[str], str | None]:
    """Vide `output/mangaka/` et `input/mangaka/` sauf `old/` ; renvoie les chemins effacés (relatifs)."""
    removed: list[str] = []
    warnings: list[str] = []
    for area in COMFY_AREAS:
        folder = root / area / COMFY_ROOT
        if folder.is_symlink():
            warnings.append(f"{area}/{COMFY_ROOT} est un lien symbolique : laissé en place")
            continue
        if not folder.is_dir():
            continue
        for child in sorted(folder.iterdir()):
            if child.name.lower() == KEEP_COMFY:
                continue
            if remove_child(folder, child.name):
                removed.append(f"{area}/{COMFY_ROOT}/{child.name}")
    return removed, "; ".join(warnings) or None


# --- base -----------------------------------------------------------------------------------
def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    return conn


def active_jobs(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = _connect(db_path)
    try:
        marks = ",".join("?" * len(ACTIVE_JOBS))
        return int(conn.execute(f"SELECT COUNT(*) FROM jobs WHERE status IN ({marks})", ACTIVE_JOBS).fetchone()[0])
    finally:
        conn.close()


def busy_message(count: int) -> str:
    return (
        f"{count} job(s) en attente ou en cours (génération, contrôle…) : attends la fin ou annule-les "
        "avant de remettre l'atelier à zéro"
    )


def wipe_database(db_path: Path, *, everything: bool) -> int:
    """Efface les séries (et en mode « tout » les réglages globaux) dans une seule transaction ;
    renvoie le nombre de séries effacées."""
    conn = _connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("BEGIN IMMEDIATE")
        try:
            marks = ",".join("?" * len(ACTIVE_JOBS))
            busy = cur.execute(f"SELECT COUNT(*) FROM jobs WHERE status IN ({marks})", ACTIVE_JOBS).fetchone()[0]
            if busy:
                raise ResetBusyError(busy_message(busy))
            series = int(cur.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
            for table in SERIES_TABLES:
                cur.execute(f"DELETE FROM {table}")
            for stmt in _SERIES_ROWS:
                cur.execute(stmt)
            emptied = list(SERIES_TABLES)
            if everything:
                for table in GLOBAL_TABLES:
                    cur.execute(f"DELETE FROM {table}")
                emptied += GLOBAL_TABLES
            problems = cur.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise ResetError(f"clés étrangères incohérentes après l'effacement : {problems[:5]}")
            # Ids : repartent de 1 sur les tables vidées, du plus grand id restant sur les autres.
            has_seq = cur.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone()
            if has_seq:
                for table in emptied:
                    cur.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
                for table in GLOBAL_TABLES:
                    if table not in emptied:
                        cur.execute(
                            f"UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX(id), 0) FROM {table})"
                            " WHERE name = ?",
                            (table,),
                        )
            cur.execute("COMMIT")
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys=ON")
    finally:
        cur.close()
        conn.close()
    try:
        compact = _connect(db_path)
        compact.execute("VACUUM")
        compact.close()
    except sqlite3.Error as exc:  # pas grave : la base est juste plus grosse que nécessaire
        log.warning("remise à zéro : VACUUM impossible (%s)", exc)
    return series


def verify_database(db_path: Path) -> None:
    """Après effacement : schéma à la dernière migration (migré si besoin), aucune série, clés cohérentes."""
    engine = create_db_engine(db_path)
    engine.dispose()
    conn = _connect(db_path)
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise ResetError(f"base en version {version} après la remise à zéro (attendu {SCHEMA_VERSION})")
        if conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]:
            raise ResetError("des séries restent dans la base après la remise à zéro")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ResetError("clés étrangères incohérentes après la remise à zéro")
    finally:
        conn.close()


# --- sauvegarde -----------------------------------------------------------------------------
def backup(settings: Settings, *, now: datetime | None = None) -> Path:
    """`data/backups/reset-<date-heure>/` : copie cohérente de la base + archive de data/. Lève `ResetError`
    (dossier partiel retiré) si quoi que ce soit échoue."""
    data_dir = settings.data_dir
    stamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M%S")
    root = data_dir / BACKUPS
    target = root / f"reset-{stamp}"
    n = 2
    while target.exists():
        target = root / f"reset-{stamp}-{n}"
        n += 1
    try:
        target.mkdir(parents=True)
    except OSError as exc:
        raise ResetError(f"sauvegarde impossible ({target} : {exc.strerror or exc}) : rien n'a été supprimé") from exc
    try:
        db_path = settings.database_path
        if db_path.exists():
            src = sqlite3.connect(db_path, timeout=15)
            dst = sqlite3.connect(target / db_path.name)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        kept = _kept_in_data(settings)
        with tarfile.open(target / "data.tar.gz", "w:gz") as tar:
            for child in sorted(data_dir.iterdir()):
                if child.name not in kept:
                    tar.add(child, arcname=child.name)  # liens symboliques gardés comme liens
    except (OSError, sqlite3.Error, tarfile.TarError) as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise ResetError(f"sauvegarde impossible ({exc}) : rien n'a été supprimé") from exc
    return target


# --- ensemble -------------------------------------------------------------------------------
def reset_workshop(
    settings: Settings,
    *,
    everything: bool = False,
    now: datetime | None = None,
    log_line: Callable[[str], None] | None = None,
) -> ResetReport:
    say = log_line or (lambda line: log.info("remise à zéro : %s", line))
    data_dir = settings.data_dir
    db_path = settings.database_path
    data_dir.mkdir(parents=True, exist_ok=True)
    # Base existante amenée à la dernière version avant tout (ou créée vide).
    create_db_engine(db_path).dispose()
    busy = active_jobs(db_path)
    if busy:
        raise ResetBusyError(busy_message(busy))

    target = backup(settings, now=now)
    say(f"sauvegarde écrite : {target}")

    series = wipe_database(db_path, everything=everything)
    say(f"{series} série(s) effacée(s) de la base")

    removed: list[str] = []
    kept = _kept_in_data(settings)
    for child in sorted(data_dir.iterdir()):
        if child.name not in kept and remove_child(data_dir, child.name):
            removed.append(child.name)
    say(f"data/ : {', '.join(removed) or 'rien à effacer'}")

    root, warning = comfyui_root(settings)
    comfy_removed: list[str] = []
    if root is not None:
        comfy_removed, warning = wipe_comfyui(root)
        say(f"ComfyUI : {len(comfy_removed)} dossier(s) effacé(s) dans {root}")
    if warning:
        say(f"ComfyUI : {warning}")

    verify_database(db_path)
    return ResetReport(
        backup=target,
        all=everything,
        series_deleted=series,
        data_removed=removed,
        comfyui_removed=comfy_removed,
        comfyui_warning=warning,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="npm run reset --",
        description="Remet l'atelier à zéro (séries, fichiers, dossiers ComfyUI) après une sauvegarde complète.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="remet aussi les réglages globaux des agents et le savoir-faire par défaut",
    )
    parser.add_argument("--yes", action="store_true", help=f"ne demande pas de taper {CONFIRM_WORD}")
    args = parser.parse_args(argv)
    settings = get_settings()

    print("Remise à zéro de l'atelier")
    print(f"  données : {settings.data_dir}")
    print(f"  ComfyUI : {settings.comfyui_dir or '(COMFYUI_DIR non renseigné : non nettoyé)'}")
    print("  effacé  : toutes les séries, leurs fichiers dans data/ et dans ComfyUI (mangaka/, sauf old/)")
    if args.all:
        print("  et aussi : réglages globaux des agents et savoir-faire (remis par défaut)")
    print("  gardé   : presets, .env, launcher.env, data/backups/, ComfyUI output/mangaka/old/")
    print("Une sauvegarde complète est écrite avant toute suppression. Arrête l'appli avant (npm run dev).")
    if not args.yes:
        if not sys.stdin.isatty():
            print("Confirmation impossible hors d'un terminal : relance avec --yes.", file=sys.stderr)
            return 2
        answer = input(f"Tape {CONFIRM_WORD} pour confirmer : ")
        if not is_confirmation(answer):
            print("Annulé : rien n'a été touché.")
            return 1
    try:
        report = reset_workshop(settings, everything=args.all, log_line=lambda line: print(f"  · {line}"))
    except ResetError as exc:
        print(f"Échec : {exc}", file=sys.stderr)
        return 1
    print("Atelier remis à zéro.")
    for line in report.lines():
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
