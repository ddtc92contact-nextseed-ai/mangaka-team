"""Migrations du schéma SQLite, suivies par `PRAGMA user_version`.

- 0 : schéma du jalon #1 (Projet → Page, sans chapitres) ;
- 2 : Série → Chapitre → Page (statuts, types de page, mise en page stockée, progression des jobs) ;
- 3 : génération (paramètres des jobs, prompt final édité à la main) ;
- 4 : contrôle qualité (verdict, détail des couches et boîtes détectées par version d'image) ;
- 5 : banc d'essai du QC (annotations bonne / mauvaise des versions, historique des runs) ;
- 6 : savoir-faire (collections, documents, passages + index FTS5), bible de série, passages reçus par
  chaque appel du LLM ;
- 7 : profils des agents du pipeline (réglages édités dans l'UI « L'équipe », versionnés) ;
- 8 : mise en page dynamique (style de mise en page de la série, graine / style / rythme par page,
  intensité par case). Les séries existantes passent en style « sage » (cases droites : leur
  mise en page ne change pas) et la signature des mises en page stockées est réécrite au nouveau
  format, pour qu'elles ne deviennent pas « obsolètes ».
- 9 : mise en page dynamique v2 (options de cadre imposées par case, paramètres des onomatopées).
- 10 : mots déclencheurs des LoRA (style de la série, identité des personnages).
- 11 : bibliothèque de la série (objets et décors récurrents + images de référence ; décor et objets
  de chaque case). Les données existantes ne changent pas : les cases n'ont ni décor ni objet.
- 12 : « Créer des références » (variantes générées par fiche) et ordre des images de référence ; les
  images existantes gardent leur ordre (celui de leur ajout).
- 13 : finition d'impression (image agrandie dérivée d'une version, agrandisseur choisi par série).
- 14 : palier croquis (sorte des versions : `final` / `croquis`, croquis validé et débruitage du
  passage au propre par case, réglages croquis de la série). Les versions existantes sont `final` ;
  le palier croquis est activé sur les séries existantes (il n'ajoute que des boutons).
- 15 : verrouillage de composition (ControlNet) par case, mode du passage au propre par série. Aucune
  case n'est verrouillée ; les séries existantes gardent le passage au propre en img2img.
- 16 : packs de style (genre, rendu, ton, réglages fins). L'ancien texte libre `style` devient
  `legacy_style` (lecture seule, utilisé tant qu'aucun pack n'est choisi) ; les mots déclencheurs saisis
  du LoRA de style disparaissent (ils viennent du catalogue presets/style_loras.yaml).
- 17 : planche de style (référence de style active ou en historique).
- 18 : ids jamais réutilisés (AUTOINCREMENT) sur les tables dont l'id entre dans l'URL d'un fichier
  (personnages, objets, décors et leurs images, cases, versions de case, jobs) : tables reconstruites,
  données et ids gardés.
- 19 : note « mise en page sage héritée » : les séries encore en « sage » (réglé par la v8, pas par
  l'utilisateur) gardent leur style, mais la fiche série le signale une fois. Rien d'autre ne change.
- 20 : lieu et mise en scène de chaque case (vides pour les cases existantes), autres noms (alias) des
  personnages (aucun pour les fiches existantes).

Une base neuve est créée directement à la dernière version. Chaque migration tourne dans une
transaction unique, clés étrangères désactivées (recette « 12 étapes » de SQLite pour reconstruire
une table), puis `PRAGMA foreign_key_check` doit être vide avant le COMMIT.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable

from sqlalchemy import Engine, Table, inspect
from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import (
    AgentProfile,
    AgentProfileVersion,
    Base,
    Chapter,
    Character,
    CharacterImage,
    Job,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    LLMRun,
    Panel,
    PanelImage,
    PanelImageAnnotation,
    QCBenchRun,
    ReferenceVariant,
    SeriesAsset,
    SeriesAssetImage,
    SeriesBible,
)

log = logging.getLogger("mangaka_engine")

SCHEMA_VERSION = 20


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


def _v3_to_v4(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE panel_images ADD COLUMN qc_verdict VARCHAR(20)")
    cur.execute("ALTER TABLE panel_images ADD COLUMN qc_details JSON NOT NULL DEFAULT '{}'")
    cur.execute("ALTER TABLE panel_images ADD COLUMN detections JSON")


def _v4_to_v5(cur: sqlite3.Cursor) -> None:
    for table in (PanelImageAnnotation.__table__, QCBenchRun.__table__):
        for stmt in _ddl(table):
            cur.execute(stmt)


def _v5_to_v6(cur: sqlite3.Cursor) -> None:
    for table in (
        KnowledgeCollection.__table__,
        KnowledgeDocument.__table__,
        KnowledgeChunk.__table__,
        SeriesBible.__table__,
        LLMRun.__table__,
    ):
        for stmt in _ddl(table):
            cur.execute(stmt)
    for stmt in FTS_DDL:
        cur.execute(stmt)


# Index plein texte des passages (recherche par mots-clés, BM25). Table FTS5 autonome dont le rowid est
# l'id du passage ; les triggers la suivent, y compris lors des suppressions en cascade (document,
# collection, série). `remove_diacritics 2` : « décor » trouve « decor ».
FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(heading, text,"
    " tokenize = 'unicode61 remove_diacritics 2')",
    "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN"
    " INSERT INTO knowledge_fts(rowid, heading, text) VALUES (new.id, new.heading, new.text); END",
    "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN"
    " DELETE FROM knowledge_fts WHERE rowid = old.id; END",
    "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE OF heading, text ON knowledge_chunks BEGIN"
    " UPDATE knowledge_fts SET heading = new.heading, text = new.text WHERE rowid = new.id; END",
)


def _v6_to_v7(cur: sqlite3.Cursor) -> None:
    for table in (AgentProfile.__table__, AgentProfileVersion.__table__):
        for stmt in _ddl(table):
            cur.execute(stmt)


def _v7_to_v8(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE projects ADD COLUMN layout_style VARCHAR(100) NOT NULL DEFAULT 'dynamique'")
    cur.execute("UPDATE projects SET layout_style = 'sage'")
    cur.execute("ALTER TABLE pages ADD COLUMN layout_seed INTEGER")
    cur.execute("ALTER TABLE pages ADD COLUMN layout_style VARCHAR(100)")
    cur.execute("ALTER TABLE pages ADD COLUMN rythme VARCHAR(20)")
    cur.execute("ALTER TABLE panels ADD COLUMN intensity VARCHAR(20)")
    # Signature (cf. pipeline/pages.py) : [numéro, format, sens, gabarit, cases] devient
    # [numéro, format, sens, gabarit, cases + intensité, style, style de page, graine, rythme].
    for page_id, raw in cur.execute("SELECT id, layout FROM pages WHERE layout IS NOT NULL").fetchall():
        try:
            layout = json.loads(raw)
            sig = json.loads(layout["signature"])
        except (TypeError, ValueError, KeyError):
            continue
        if not isinstance(sig, list) or len(sig) != 5:
            continue
        specs = [[*spec, None] for spec in sig[4]]
        layout["signature"] = json.dumps([*sig[:4], specs, "sage", None, None, None], separators=(",", ":"))
        cur.execute("UPDATE pages SET layout = ? WHERE id = ?", (json.dumps(layout), page_id))


def _v8_to_v9(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE panels ADD COLUMN frame JSON")
    cur.execute("ALTER TABLE bubbles ADD COLUMN sfx JSON")


def _v9_to_v10(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE projects ADD COLUMN style_lora_trigger_words TEXT NOT NULL DEFAULT ''")
    cur.execute("ALTER TABLE characters ADD COLUMN lora_trigger_words TEXT NOT NULL DEFAULT ''")


def _v10_to_v11(cur: sqlite3.Cursor) -> None:
    for table in (SeriesAsset.__table__, SeriesAssetImage.__table__):
        for stmt in _ddl(table):
            cur.execute(stmt)
    cur.execute("ALTER TABLE panels ADD COLUMN decor_id INTEGER")
    cur.execute("ALTER TABLE panels ADD COLUMN object_ids JSON NOT NULL DEFAULT '[]'")


def _v11_to_v12(cur: sqlite3.Cursor) -> None:
    for table in ("character_images", "series_asset_images"):
        # series_asset_images vient d'être créée par la v11 depuis le modèle courant (déjà avec position).
        if "position" not in {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        cur.execute(f"UPDATE {table} SET position = id")
    for stmt in _ddl(ReferenceVariant.__table__):
        cur.execute(stmt)


def _v12_to_v13(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE panel_images ADD COLUMN finish JSON")
    cur.execute("ALTER TABLE projects ADD COLUMN upscaler VARCHAR(100)")


def _v13_to_v14(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE panel_images ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'final'")
    cur.execute("ALTER TABLE panels ADD COLUMN sketch_image_id INTEGER")
    cur.execute("ALTER TABLE panels ADD COLUMN sketch_denoise FLOAT")
    cur.execute("ALTER TABLE projects ADD COLUMN sketch_enabled BOOLEAN NOT NULL DEFAULT 1")
    cur.execute("ALTER TABLE projects ADD COLUMN sketch_denoise FLOAT")


def _v14_to_v15(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE panels ADD COLUMN composition_lock JSON")
    cur.execute("ALTER TABLE projects ADD COLUMN clean_mode VARCHAR(20) NOT NULL DEFAULT 'img2img'")
    cur.execute("ALTER TABLE projects ADD COLUMN clean_control VARCHAR(40)")


def _v15_to_v16(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE projects RENAME COLUMN style TO legacy_style")
    cur.execute("ALTER TABLE projects ADD COLUMN style_genre VARCHAR(100)")
    cur.execute("ALTER TABLE projects ADD COLUMN style_rendering VARCHAR(100)")
    cur.execute("ALTER TABLE projects ADD COLUMN style_tone VARCHAR(100)")
    cur.execute("ALTER TABLE projects ADD COLUMN style_options JSON NOT NULL DEFAULT '{}'")
    cur.execute("ALTER TABLE projects DROP COLUMN style_lora_trigger_words")


def _v16_to_v17(cur: sqlite3.Cursor) -> None:
    # series_assets créée par la v11 depuis le modèle courant a déjà la colonne.
    if "active" not in {row[1] for row in cur.execute("PRAGMA table_info(series_assets)")}:
        cur.execute("ALTER TABLE series_assets ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1")


def _rebuild(cur: sqlite3.Cursor, table: Table) -> None:
    """Reconstruit `table` selon le modèle (recette « 12 étapes ») en gardant ses lignes et leurs ids."""
    name = table.name
    old = {row[1] for row in cur.execute(f'PRAGMA table_info("{name}")')}
    cols = ", ".join(f'"{c.name}"' for c in table.columns if c.name in old)
    create, *indexes = _ddl(table)
    cur.execute(create.replace(f"CREATE TABLE {name} (", f"CREATE TABLE {name}__new (", 1))
    cur.execute(f'INSERT INTO "{name}__new" ({cols}) SELECT {cols} FROM "{name}"')
    cur.execute(f'DROP TABLE "{name}"')
    cur.execute(f'ALTER TABLE "{name}__new" RENAME TO "{name}"')
    for stmt in indexes:
        cur.execute(stmt)


def _v17_to_v18(cur: sqlite3.Cursor) -> None:
    for model in (Character, CharacterImage, SeriesAsset, SeriesAssetImage, Panel, PanelImage, Job):
        _rebuild(cur, model.__table__)  # type: ignore[arg-type]


def _v18_to_v19(cur: sqlite3.Cursor) -> None:
    cur.execute("ALTER TABLE projects ADD COLUMN layout_style_notice BOOLEAN NOT NULL DEFAULT 0")
    cur.execute("UPDATE projects SET layout_style_notice = 1 WHERE layout_style = 'sage'")


def _v19_to_v20(cur: sqlite3.Cursor) -> None:
    # panels et characters reconstruites par la v18 depuis le modèle courant ont déjà ces colonnes.
    existing = {
        table: {row[1] for row in cur.execute(f"PRAGMA table_info({table})")} for table in ("panels", "characters")
    }
    if "setting" not in existing["panels"]:
        cur.execute("ALTER TABLE panels ADD COLUMN setting TEXT NOT NULL DEFAULT ''")
    if "staging" not in existing["panels"]:
        cur.execute("ALTER TABLE panels ADD COLUMN staging TEXT NOT NULL DEFAULT ''")
    if "aliases" not in existing["characters"]:
        cur.execute("ALTER TABLE characters ADD COLUMN aliases JSON NOT NULL DEFAULT '[]'")


MIGRATIONS: dict[int, tuple[int, Callable[[sqlite3.Cursor], None]]] = {
    # version de départ → (version d'arrivée, fonction)
    0: (2, _v0_to_v2),
    1: (2, _v0_to_v2),
    2: (3, _v2_to_v3),
    3: (4, _v3_to_v4),
    4: (5, _v4_to_v5),
    5: (6, _v5_to_v6),
    6: (7, _v6_to_v7),
    7: (8, _v7_to_v8),
    8: (9, _v8_to_v9),
    9: (10, _v9_to_v10),
    10: (11, _v10_to_v11),
    11: (12, _v11_to_v12),
    12: (13, _v12_to_v13),
    13: (14, _v13_to_v14),
    14: (15, _v14_to_v15),
    15: (16, _v15_to_v16),
    16: (17, _v16_to_v17),
    17: (18, _v17_to_v18),
    18: (19, _v18_to_v19),
    19: (20, _v19_to_v20),
}


def current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)


def migrate(engine: Engine) -> int:
    """Amène la base à `SCHEMA_VERSION` ; renvoie la version finale."""
    if "projects" not in inspect(engine).get_table_names():
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            for stmt in FTS_DDL:
                conn.exec_driver_sql(stmt)
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
