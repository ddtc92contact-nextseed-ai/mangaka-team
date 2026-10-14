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
- 23 : angle de caméra des vues de référence (aucune étiquette sur les images existantes) et « Cohérence
  anime » par série (désactivée sur les séries existantes).
- 24 : rangement des fichiers : nom de dossier lisible (slug) des séries et des fiches de la bibliothèque,
  tiré du titre ou du nom (store/slugs.py) ; ids jamais réutilisés (AUTOINCREMENT) sur les séries, les
  chapitres et les pages (tables reconstruites, données et ids gardés).
- 25 : dialogue avec l'IA par case (historique des échanges, direction et référence imposées à la case) ;
  rien d'imposé sur les cases existantes.
- 26 : cadrage manuel de l'image par case (centre + zoom) ; les cases existantes restent centrées.
- 27 : packs de savoir-faire (presets/knowledge_packs/) : collection et document marqués « pack », champs
  meta d'une fiche, mots-clés indexés en FTS sans être injectés (colonne `keywords` de l'index, reconstruit
  depuis les passages). Les collections et documents existants restent ceux de l'utilisateur.
- 28 : empreinte du savoir-faire du prompt rédigé et ses « Sources utilisées », par case. Aucune empreinte sur
  les cases existantes : leurs prompts rédigés par l'IA (non retouchés) seront rédigés de nouveau, avec le
  savoir-faire actuel, à leur prochaine génération.
- 29 : traçabilité : journal des générations (`generation_logs`, une ligne par génération, jamais réécrite) et
  verdicts de l'auteur (`generation_events`). Tables nouvelles et vides : rien d'existant ne change.
- 30 : personnages cités hors cadre (`panels.offscreen_names`) et point de vue d'un spectateur
  (`panels.viewpoint` : plan de réaction ou vue subjective). Les cases existantes gardent tous leurs
  personnages comme « présents à l'image » (`character_names`), sans hors cadre ni point de vue.
- 31 : garde d'étapes : décisions sur les étapes vitales d'un chapitre (`chapter_stage_decisions` : validée,
  forcée, levée). Table nouvelle et vide : aucune étape n'est validée d'avance, l'état se lit dans le chapitre.
- 32 : tomes (`volumes` : numéro, titre, format et couverture ; `volume_chapters` : chapitres inclus, dans
  l'ordre, un chapitre dans un seul tome ; `volume_covers` : versions de l'illustration de couverture). Tables
  nouvelles et vides : aucun chapitre n'est rangé dans un tome, les chapitres ne changent pas.
- 33 : identité visuelle de la série : palette retenue et dernières propositions (`projects.palette`,
  `palette_proposals`, `logo_proposals`) et versions du logo du titre (`series_logos`). Les séries existantes
  n'ont ni palette ni logo.
- 34 : ADN de la série (`projects.pre_direction` : valeurs de la charte ajustées par l'auteur). Les séries
  existantes n'ajustent rien : elles reçoivent les défauts de leur genre (presets/pre_direction.yaml).

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
    ChapterStageDecision,
    Character,
    CharacterImage,
    GenerationEvent,
    GenerationLog,
    Job,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    LLMRun,
    Page,
    Panel,
    PanelImage,
    PanelImageAnnotation,
    Project,
    QCBenchRun,
    ReferenceVariant,
    SeriesAsset,
    SeriesAssetImage,
    SeriesBible,
    SeriesLogo,
    Volume,
    VolumeChapter,
    VolumeCover,
)
from .slugs import RESERVED_ENTRIES, RESERVED_SERIES, slugify, unique_slug

log = logging.getLogger("mangaka_engine")

SCHEMA_VERSION = 34


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
# collection, série). `remove_diacritics 2` : « décor » trouve « decor ». `keywords` (v27) : mots-clés du
# document (titre et pont de vocabulaire d'un pack), cherchés mais jamais injectés.
FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(heading, text, keywords,"
    " tokenize = 'unicode61 remove_diacritics 2')",
    "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN"
    " INSERT INTO knowledge_fts(rowid, heading, text, keywords) VALUES (new.id, new.heading, new.text,"
    " new.keywords); END",
    "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN"
    " DELETE FROM knowledge_fts WHERE rowid = old.id; END",
    "CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE OF heading, text, keywords ON knowledge_chunks"
    " BEGIN UPDATE knowledge_fts SET heading = new.heading, text = new.text, keywords = new.keywords"
    " WHERE rowid = new.id; END",
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


def _v20_to_v21(cur: sqlite3.Cursor) -> None:
    # Prompt rédigé par l'IA : les séries existantes gardent l'assemblage par fragments (réglable dans
    # la fiche série) ; les nouvelles suivent presets/prompts/redacteur-image.yaml#enabled.
    # Tables reconstruites par une migration antérieure depuis le modèle courant : colonnes déjà là.
    existing = {
        table: {row[1] for row in cur.execute(f"PRAGMA table_info({table})")} for table in ("projects", "panels")
    }
    if "ai_prompt" not in existing["projects"]:
        cur.execute("ALTER TABLE projects ADD COLUMN ai_prompt BOOLEAN NOT NULL DEFAULT 0")
    cur.execute("UPDATE projects SET ai_prompt = 0")
    for column, kind in (("prompt_source", "VARCHAR(20)"), ("prompt_key", "VARCHAR(64)"), ("prompt_warning", "TEXT")):
        if column not in existing["panels"]:
            cur.execute(f"ALTER TABLE panels ADD COLUMN {column} {kind}")
    # Prompts déjà construits : par fragments.
    cur.execute(
        "UPDATE panels SET prompt_source = 'fragments' "
        "WHERE final_prompt IS NOT NULL AND final_prompt != '' AND final_prompt_manual = 0"
    )


def _v21_to_v22(cur: sqlite3.Cursor) -> None:
    # CFG par série (None = celui du palier) : les séries existantes ne changent pas.
    if "cfg" not in {row[1] for row in cur.execute("PRAGMA table_info(projects)")}:
        cur.execute("ALTER TABLE projects ADD COLUMN cfg FLOAT")


def _v22_to_v23(cur: sqlite3.Cursor) -> None:
    # Angle des vues de référence (aucune étiquette : la principale vaut `main_view`) et « Cohérence anime »
    # par série (désactivée). Rien d'autre ne change.
    for table in ("character_images", "series_asset_images"):
        if "angle" not in {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN angle VARCHAR(40)")
    if "anime_consistency" not in {row[1] for row in cur.execute("PRAGMA table_info(projects)")}:
        cur.execute("ALTER TABLE projects ADD COLUMN anime_consistency BOOLEAN NOT NULL DEFAULT 0")


def _v23_to_v24(cur: sqlite3.Cursor) -> None:
    # Slugs d'abord (colonne ajoutée puis remplie), puis reconstruction des séries, chapitres et pages.
    # Tables reconstruites ou créées par une migration antérieure depuis le modèle courant : colonne déjà là.
    for table in ("projects", "characters", "series_assets"):
        if "slug" not in {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN slug VARCHAR(120) NOT NULL DEFAULT ''")
    taken = set(RESERVED_SERIES) | {s for (s,) in cur.execute("SELECT slug FROM projects WHERE slug != ''")}
    for project_id, title in cur.execute("SELECT id, title FROM projects WHERE slug = '' ORDER BY id").fetchall():
        slug = unique_slug(slugify(title, "serie"), taken)
        taken.add(slug)
        cur.execute("UPDATE projects SET slug = ? WHERE id = ?", (slug, project_id))
    for table, kind_sql in (("characters", "'character'"), ("series_assets", "kind")):
        rows = cur.execute(f"SELECT id, project_id, {kind_sql}, name, slug FROM {table} ORDER BY id").fetchall()
        used: dict[tuple[int, str], set[str]] = {}
        for _id, project_id, kind, _name, slug in rows:
            if slug:
                used.setdefault((project_id, kind), set(RESERVED_ENTRIES.get(kind, ()))).add(slug)
        for entry_id, project_id, kind, name, slug in rows:
            if slug:
                continue
            seen = used.setdefault((project_id, kind), set(RESERVED_ENTRIES.get(kind, ())))
            slug = unique_slug(slugify(name, "fiche"), seen)
            seen.add(slug)
            cur.execute(f"UPDATE {table} SET slug = ? WHERE id = ?", (slug, entry_id))
    for model in (Project, Chapter, Page):
        _rebuild(cur, model.__table__)  # type: ignore[arg-type]


def _v24_to_v25(cur: sqlite3.Cursor) -> None:
    # Dialogue par case : la table `panel_dialog_turns` est créée par `create_all` ; panels reconstruite par
    # une migration antérieure depuis le modèle courant : colonnes déjà là.
    existing = {row[1] for row in cur.execute("PRAGMA table_info(panels)")}
    for column in ("dialog_direction", "reference_choice"):
        if column not in existing:
            cur.execute(f"ALTER TABLE panels ADD COLUMN {column} JSON")


def _v25_to_v26(cur: sqlite3.Cursor) -> None:
    if "crop" not in {row[1] for row in cur.execute("PRAGMA table_info(panels)")}:
        cur.execute("ALTER TABLE panels ADD COLUMN crop JSON")


def _v26_to_v27(cur: sqlite3.Cursor) -> None:
    # Tables créées par la v6 depuis le modèle courant : colonnes (et index FTS à trois colonnes) déjà là.
    columns = {
        table: {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
        for table in ("knowledge_collections", "knowledge_documents", "knowledge_chunks")
    }
    if "pack" not in columns["knowledge_collections"]:
        cur.execute("ALTER TABLE knowledge_collections ADD COLUMN pack VARCHAR(100)")
        cur.execute("CREATE INDEX ix_knowledge_collections_pack ON knowledge_collections (pack)")
    for column, kind in (
        ("pack_key", "VARCHAR(120)"),
        ("meta", "JSON NOT NULL DEFAULT '{}'"),
        ("keywords", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in columns["knowledge_documents"]:
            cur.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {column} {kind}")
    if "keywords" not in columns["knowledge_chunks"]:
        cur.execute("ALTER TABLE knowledge_chunks ADD COLUMN keywords TEXT NOT NULL DEFAULT ''")
    # Index FTS reconstruit avec la colonne `keywords`, puis rempli depuis les passages.
    for trigger in ("knowledge_chunks_ai", "knowledge_chunks_ad", "knowledge_chunks_au"):
        cur.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    cur.execute("DROP TABLE IF EXISTS knowledge_fts")
    for stmt in FTS_DDL:
        cur.execute(stmt)
    cur.execute(
        "INSERT INTO knowledge_fts(rowid, heading, text, keywords) SELECT id, heading, text, keywords FROM knowledge_chunks"
    )


def _v27_to_v28(cur: sqlite3.Cursor) -> None:
    existing = {row[1] for row in cur.execute("PRAGMA table_info(panels)")}
    if "prompt_knowledge" not in existing:
        cur.execute("ALTER TABLE panels ADD COLUMN prompt_knowledge VARCHAR(64)")
    if "prompt_sources" not in existing:
        cur.execute("ALTER TABLE panels ADD COLUMN prompt_sources JSON")


def _v28_to_v29(cur: sqlite3.Cursor) -> None:
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for model in (GenerationLog, GenerationEvent):
        if model.__tablename__ not in tables:
            for stmt in _ddl(model.__table__):
                cur.execute(stmt)


def _v29_to_v30(cur: sqlite3.Cursor) -> None:
    existing = {row[1] for row in cur.execute("PRAGMA table_info(panels)")}
    if "offscreen_names" not in existing:
        cur.execute("ALTER TABLE panels ADD COLUMN offscreen_names JSON NOT NULL DEFAULT '[]'")
    if "viewpoint" not in existing:
        cur.execute("ALTER TABLE panels ADD COLUMN viewpoint JSON")


def _v30_to_v31(cur: sqlite3.Cursor) -> None:
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if ChapterStageDecision.__tablename__ not in tables:
        for stmt in _ddl(ChapterStageDecision.__table__):
            cur.execute(stmt)


def _v31_to_v32(cur: sqlite3.Cursor) -> None:
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for model in (Volume, VolumeChapter, VolumeCover):
        if model.__tablename__ not in tables:
            for stmt in _ddl(model.__table__):
                cur.execute(stmt)


def _v32_to_v33(cur: sqlite3.Cursor) -> None:
    existing = {row[1] for row in cur.execute("PRAGMA table_info(projects)")}
    if "palette" not in existing:
        cur.execute("ALTER TABLE projects ADD COLUMN palette JSON")
    for column in ("palette_proposals", "logo_proposals"):
        if column not in existing:
            cur.execute(f"ALTER TABLE projects ADD COLUMN {column} JSON NOT NULL DEFAULT '[]'")
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if SeriesLogo.__tablename__ not in tables:
        for stmt in _ddl(SeriesLogo.__table__):
            cur.execute(stmt)


def _v33_to_v34(cur: sqlite3.Cursor) -> None:
    existing = {row[1] for row in cur.execute("PRAGMA table_info(projects)")}
    if "pre_direction" not in existing:
        cur.execute("ALTER TABLE projects ADD COLUMN pre_direction JSON NOT NULL DEFAULT '{}'")


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
    20: (21, _v20_to_v21),
    21: (22, _v21_to_v22),
    22: (23, _v22_to_v23),
    23: (24, _v23_to_v24),
    24: (25, _v24_to_v25),
    25: (26, _v25_to_v26),
    26: (27, _v26_to_v27),
    27: (28, _v27_to_v28),
    28: (29, _v28_to_v29),
    29: (30, _v29_to_v30),
    30: (31, _v30_to_v31),
    31: (32, _v31_to_v32),
    32: (33, _v32_to_v33),
    33: (34, _v33_to_v34),
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
