"""Migrations du schéma SQLite, suivies par `PRAGMA user_version`.

- 0 : schéma du jalon #1 (Projet → Page, sans chapitres) ;
- 2 : Série → Chapitre → Page (statuts, types de page, mise en page stockée, progression des jobs) ;
- 3 : génération (paramètres des jobs, prompt final édité à la main).

Une base neuve est créée directement à la dernière version. Chaque migration tourne dans une
transaction unique, clés étrangères désactivées (recette « 12 étapes » de SQLite pour reconstruire
une table), puis `PRAGMA foreign_key_check` doit être vide avant le COMMIT.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from sqlalchemy import Engine, inspect
from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import Base, Chapter

log = logging.getLogger("mangaka_engine")

SCHEMA_VERSION = 3


class MigrationError(RuntimeError):
    pass


def _ddl(table) -> list[str]:  # type: ignore[no-untyped-def]
    dialect = sqlite.dialect()
    out = [str(CreateTable(table).compile(dialect=dialect))]
    out += [str(CreateIndex(i).compile(dialect=dialect)) for i in sorted(table.indexes, key=lambda i: i.name)]
    return out


def _v0_to_v2(cur: sqlite3.Cursor) -> None:
    # Séries : statut + LoRA de style par défaut.
    cur.execute("ALTER TABLE projects ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ongoing'")
    cur.execute("ALTER TABLE projects ADD COLUMN style_lora_name VARCHAR(255)")
    cur.execute("ALTER TABLE projects ADD COLUMN style_lora_weight FLOAT NOT NULL DEFAULT 0.8")

    for stmt in _ddl(Chapter.__table__):
        cur.execute(stmt)

    # Pages : rattachées à un chapitre et non plus à la série. Les éventuelles pages existantes
    # (le jalon #1 n'en créait pas) sont regroupées dans un chapitre 1 « Pages importées ».
    cur.execute(
        """
        CREATE TABLE pages_new (
            id INTEGER NOT NULL,
            chapter_id INTEGER NOT NULL,
            number INTEGER NOT NULL,
            kind VARCHAR(20) NOT NULL,
            grid_template VARCHAR(100),
            layout JSON,
            state VARCHAR(20) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (chapter_id, number),
            FOREIGN KEY(chapter_id) REFERENCES chapters (id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        INSERT INTO chapters (project_id, number, title, synopsis, target_page_count, status, summary,
                              created_at, updated_at)
        SELECT DISTINCT project_id, 1, 'Pages importées', '', 15, 'draft', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM pages
        """
    )
    cur.execute(
        """
        INSERT INTO pages_new (id, chapter_id, number, kind, grid_template, layout, state, created_at, updated_at)
        SELECT p.id, c.id, p.number, 'story', p.grid_template, NULL, p.state, p.created_at, p.updated_at
        FROM pages p JOIN chapters c ON c.project_id = p.project_id AND c.number = 1
        """
    )
    cur.execute("DROP TABLE pages")
    cur.execute("ALTER TABLE pages_new RENAME TO pages")
    cur.execute("CREATE INDEX ix_pages_chapter_id ON pages (chapter_id)")

    cur.execute("ALTER TABLE panels ADD COLUMN character_names JSON NOT NULL DEFAULT '[]'")
    cur.execute("ALTER TABLE bubbles ADD COLUMN speaker_name VARCHAR(120) NOT NULL DEFAULT ''")
    cur.execute("ALTER TABLE jobs ADD COLUMN chapter_id INTEGER REFERENCES chapters (id) ON DELETE CASCADE")
    cur.execute("ALTER TABLE jobs ADD COLUMN progress INTEGER NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE jobs ADD COLUMN message TEXT NOT NULL DEFAULT ''")
    cur.execute("CREATE INDEX ix_jobs_chapter_id ON jobs (chapter_id)")


def _v2_to_v3(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE jobs ADD COLUMN params JSON NOT NULL DEFAULT '{}'")
    cur.execute("ALTER TABLE panels ADD COLUMN final_prompt_manual BOOLEAN NOT NULL DEFAULT 0")


MIGRATIONS: dict[int, tuple[int, Callable[[sqlite3.Cursor], None]]] = {
    # version de départ → (version d'arrivée, fonction)
    0: (2, _v0_to_v2),
    1: (2, _v0_to_v2),
    2: (3, _v2_to_v3),
}


def current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)


def migrate(engine: Engine) -> int:
    """Amène la base à `SCHEMA_VERSION` ; renvoie la version finale."""
    if "projects" not in inspect(engine).get_table_names():
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return SCHEMA_VERSION

    version = current_version(engine)
    if version > SCHEMA_VERSION:
        raise MigrationError(f"base en version {version}, plus récente que ce moteur ({SCHEMA_VERSION})")
    while version < SCHEMA_VERSION:
        target, step = MIGRATIONS[version]
        log.info("migration du schéma : %s → %s", version, target)
        _run(engine, step, target)
        version = target
    Base.metadata.create_all(engine)  # tables ajoutées sans migration de données
    return version


def _run(engine: Engine, step: Callable[[sqlite3.Cursor], None], target: int) -> None:
    raw = engine.raw_connection()
    try:
        dbc = raw.driver_connection
        assert isinstance(dbc, sqlite3.Connection)
        previous = dbc.isolation_level
        dbc.isolation_level = None  # transactions gérées à la main
        cur = dbc.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("BEGIN")
        try:
            step(cur)
            problems = cur.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise MigrationError(f"clés étrangères incohérentes après migration : {problems[:5]}")
            cur.execute(f"PRAGMA user_version = {target}")
            cur.execute("COMMIT")
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys=ON")
            dbc.isolation_level = previous
            cur.close()
    finally:
        raw.close()
