"""Packs de savoir-faire livrés (presets/knowledge_packs/) : lecture d'un pack (fiches, meta retiré, pont de
vocabulaire), import idempotent, réindexation des seules fiches modifiées, collections de l'utilisateur jamais
touchées, lecture seule dans l'API, câblage par défaut des agents et classement sur le vrai pack. Embeddings
factices, aucun appel réseau."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.knowledge import (
    KnowledgeBase,
    choose_passages,
    index_document,
    rank,
    select_passages,
)
from mangaka_engine.pipeline.knowledge_packs import load_pack, update_packs
from mangaka_engine.presets import KnowledgeAgent, KnowledgeSettings, PresetRegistry
from mangaka_engine.providers.embedding import MockEmbeddingProvider
from mangaka_engine.store.db import Database
from mangaka_engine.store.models import KnowledgeChunk, KnowledgeCollection, KnowledgeDocument
from tests.conftest import PRESETS_DIR, STYLE, start_script

FIXTURE = Path(__file__).parent / "fixtures" / "knowledge_pack"
SETTINGS = KnowledgeSettings(small_collection_tokens=0)
PACK_COLLECTIONS = [
    "Mise en scène · Fondamentaux",
    "Mise en scène · Cadrages",
    "Mise en scène · Angles",
    "Mise en scène · Corps et gestes",
    "Mise en scène · Action",
    "Mise en scène · Composition",
    "Mise en scène · Découpage",
    "Mise en scène · Émotions",
    "Mise en scène · Anti-répétition",
    "Mise en scène · Exemples",
    "Mise en scène · Vocabulaire",
    "Mise en scène · Checklist",
    "Mise en scène · Pont ComfyUI",
]
RENDERING_COLLECTIONS = [
    "Rendu · Encrage",
    "Rendu · Trames",
    "Rendu · Papier et impression",
    "Rendu · Finitions",
    "Rendu · Valeurs et masses",
]
STRUCTURE_COLLECTIONS = [
    "Structure · Déroulé du chapitre",
    "Structure · Courbes par genre",
    "Structure · Plans selon le moment",
    "Structure · Fins de chapitre",
    "Structure · Rythme d'un arc",
    "Structure · Silence et dialogue",
]
SHIPPED_COLLECTIONS = [*PACK_COLLECTIONS, *RENDERING_COLLECTIONS, *STRUCTURE_COLLECTIONS]


@pytest.fixture
def presets(tmp_path: Path) -> Path:
    """Dossier de presets ne contenant que le petit pack de test."""
    root = tmp_path / "presets"
    shutil.copytree(FIXTURE, root / "knowledge_packs")
    return root


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "k.db")
    yield database
    database.dispose()


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _docs(session: Session) -> dict[str, KnowledgeDocument]:
    return {d.pack_key or d.title: d for d in session.scalars(select(KnowledgeDocument))}


def _chunk_ids(session: Session) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for doc_id, chunk_id in session.execute(select(KnowledgeChunk.document_id, KnowledgeChunk.id)):
        out.setdefault(doc_id, []).append(chunk_id)
    return out


# --- lecture du pack ----------------------------------------------------------------------
def test_fiches_become_documents_without_meta_and_with_bridged_keywords() -> None:
    pack = load_pack(FIXTURE / "mini.yaml")
    entries = {e.key: e for e in pack.parsed.entries}
    assert list(entries) == ["0.B", "0.C", "SHOT_CU_001", "SHOT_LS_001", "EMO_002", "Annexe A"]
    assert pack.parsed.skipped == ["0.A — Mode d'emploi", "Annexe C — Sources"]
    assert pack.parsed.unknown == ["Annexe Z — Section oubliée par le manifeste"]

    cu = entries["SHOT_CU_001"]
    assert cu.title == "SHOT_CU_001 — Gros plan (visage)" and cu.collection == "Mini · Cadrages"
    assert cu.content.startswith("**Définition.** Le visage remplit la case")
    assert "```meta" not in cu.content and "path:" not in cu.content and "---" not in cu.content
    assert "`close-up, face filling the frame`" in cu.content  # fragments de prompt gardés
    assert cu.meta["shot_scale"] == "close_up" and cu.meta["path"] == "01_cadrages/gros_plan.md"
    assert cu.tags == ["SHOT_CU_001", "shot_scale", "close_up", "low", "emotion", "decision"]
    # pont de vocabulaire : termes de l'appli (et leur jeton fusionné) dans les mots-clés, pas dans le texte
    assert "gros plan" in cu.keywords and "grosplan" in cu.keywords
    assert "en contre-plongée" in cu.keywords and "contreplongee" in cu.keywords
    assert "contre-plongée" not in cu.content
    assert "plan large" in entries["SHOT_LS_001"].keywords
    assert entries["EMO_002"].tags == ["EMO_002", "emotion", "anger"]  # « variable » n'est pas une étiquette

    # section sans fiche : un document ; son bloc JSON devient une liste de champs
    fmt = entries["0.C"]
    assert fmt.title == "0.C — Format de case" and fmt.collection == "Mini · Vocabulaire"
    assert "{" not in fmt.content and "- intent : fear, tension" in fmt.content
    assert entries["Annexe A"].content.startswith("1. Chaque case")
    for entry in entries.values():
        assert "Chapeau" not in entry.content and "```" not in entry.content


# --- import -------------------------------------------------------------------------------
def test_import_is_idempotent_and_only_changed_fiches_are_reindexed(db: Database, presets: Path) -> None:
    embedder = MockEmbeddingProvider()
    with db.session_scope() as session:
        [first] = update_packs(session, presets, embedder, SETTINGS)
        session.commit()
        assert (first.created, first.updated, first.unchanged, first.deleted) == (6, 0, 0, 0)
        assert first.collections == 4 and first.warnings == [
            "section non rangée par le manifeste (ignorée) : « Annexe Z — Section oubliée par le manifeste »"
        ]
        cols = {c.name: c for c in session.scalars(select(KnowledgeCollection))}
        assert set(cols) == {"Mini · Cadrages", "Mini · Émotions", "Mini · Vocabulaire", "Mini · Checklist"}
        assert {c.pack for c in cols.values()} == {"mini"}
        docs = _docs(session)
        cu = docs["SHOT_CU_001"]
        assert cu.collection.name == "Mini · Cadrages" and cu.meta["id"] == "SHOT_CU_001"
        assert all(c.keywords == cu.keywords and c.embedding is not None for c in cu.chunks)
        assert all("```" not in c.text and "{" not in c.text for d in docs.values() for c in d.chunks)
        before = _chunk_ids(session)
        calls = embedder.calls

        [again] = update_packs(session, presets, embedder, SETTINGS)
        session.commit()
        assert (again.created, again.updated, again.unchanged, again.deleted) == (0, 0, 6, 0)
        assert session.scalar(select(text("count(*)")).select_from(KnowledgeDocument)) == 6
        assert _chunk_ids(session) == before and embedder.calls == calls  # rien réindexé

    # une fiche modifiée dans le fichier : elle seule est réécrite et réindexée
    md = presets / "knowledge_packs" / "mini.md"
    md.write_text(md.read_text().replace("La colère monte", "La rage monte"))
    with db.session_scope() as session:
        [edited] = update_packs(session, presets, embedder, SETTINGS)
        session.commit()
        assert (edited.created, edited.updated, edited.unchanged) == (0, 1, 5)
        assert embedder.calls == calls + 1
        docs = _docs(session)
        after = _chunk_ids(session)
        emo = docs["EMO_002"].id
        assert after[emo] != before[emo] and "La rage monte" in docs["EMO_002"].content
        assert {k: v for k, v in after.items() if k != emo} == {k: v for k, v in before.items() if k != emo}

    # une fiche retirée du fichier : son document part ; une collection retirée du manifeste aussi
    md.write_text(md.read_text().split("### SHOT_LS_001")[0] + "## 07_emotions\n")
    manifest = presets / "knowledge_packs" / "mini.yaml"
    manifest.write_text(manifest.read_text().replace('  - name: Mini · Checklist\n    sections: ["Annexe A"]\n', ""))
    with db.session_scope() as session:
        [shrunk] = update_packs(session, presets, embedder, SETTINGS)
        session.commit()
        assert set(_docs(session)) == {"0.B", "0.C", "SHOT_CU_001"}
        assert shrunk.deleted == 3
        names = set(session.scalars(select(KnowledgeCollection.name)))
        assert names == {"Mini · Cadrages", "Mini · Émotions", "Mini · Vocabulaire"}


def test_user_collections_and_documents_are_never_touched(db: Database, presets: Path) -> None:
    with db.session_scope() as session:
        mine = KnowledgeCollection(name="Mini · Émotions")  # même nom qu'une collection du pack
        other = KnowledgeCollection(name="Mes fiches")
        other.documents.append(KnowledgeDocument(title="Gros plan maison", content="Mon gros plan à moi."))
        session.add_all([mine, other])
        session.commit()

        [report] = update_packs(session, presets, MockEmbeddingProvider(), SETTINGS)
        update_packs(session, presets, MockEmbeddingProvider(), SETTINGS)
        session.commit()
        assert any("« Mini · Émotions » existe déjà" in w for w in report.warnings)
        assert mine.pack is None and mine.documents == []  # la fiche EMO_002 n'y est pas versée
        assert [d.title for d in other.documents] == ["Gros plan maison"] and other.pack is None
        assert "EMO_002" not in _docs(session)


def test_unreadable_pack_is_reported_and_leaves_the_base_alone(db: Database, presets: Path) -> None:
    with db.session_scope() as session:
        update_packs(session, presets, None, SETTINGS)  # sans embeddings : mots-clés seulement
        session.commit()
        assert all(d.index_error for d in _docs(session).values())
        (presets / "knowledge_packs" / "mini.yaml").write_text("id: mini\nfile: absent.md\ncollections: []\n")
        [report] = update_packs(session, presets, MockEmbeddingProvider(), SETTINGS)
        assert report.error and "manifeste invalide" in report.error
        assert len(_docs(session)) == 6


# --- vrai pack ----------------------------------------------------------------------------
@pytest.fixture
def pack_client(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(knowledge_packs=True))) as c:
        yield c


def test_startup_imports_the_shipped_pack_in_13_collections(pack_client: TestClient) -> None:
    c = pack_client
    every = {col["name"]: col for col in _ok(c.get("/knowledge/collections"))}
    assert set(every) == set(SHIPPED_COLLECTIONS)
    cols = {name: col for name, col in every.items() if col["pack"] == "manga_visual_knowledge"}
    assert set(cols) == set(PACK_COLLECTIONS)
    raw = (PRESETS_DIR / "knowledge_packs" / "manga_visual_knowledge.md").read_text()
    fiches = sum(1 for line in raw.splitlines() if line.startswith("### "))
    assert sum(col["document_count"] for col in cols.values()) == fiches + 4  # + 0.B, 0.C, annexes A et B
    status = _ok(c.get("/knowledge/status"))
    report = next(r for r in status["packs"] if r["pack"] == "manga_visual_knowledge")
    assert report["created"] == fiches + 4 and report["warnings"] == [] and report["error"] is None

    docs = [
        _ok(c.get(f"/knowledge/documents/{d['id']}"))
        for col in cols.values()
        for d in _ok(c.get(f"/knowledge/collections/{col['id']}/documents"))
    ]
    for doc in docs:
        assert doc["pack"] == "manga_visual_knowledge" and doc["pack_key"]
        assert "```meta" not in doc["content"] and "{" not in doc["content"], doc["title"]
        assert all("{" not in chunk["text"] for chunk in doc["chunks"])
    cu = next(d for d in docs if d["pack_key"] == "SHOT_CU_001")
    assert cu["title"] == "SHOT_CU_001 — Gros plan (visage)" and "close_up" in cu["tags"]
    assert cu["meta"]["pairs_with"] and "gros plan" in cu["keywords"]

    # « Mettre à jour les packs » sur un fichier inchangé : rien ne bouge
    update = next(r for r in _ok(c.post("/knowledge/packs/update")) if r["pack"] == "manga_visual_knowledge")
    assert (update["created"], update["updated"], update["deleted"]) == (0, 0, 0)
    assert update["unchanged"] == fiches + 4

    # lecture seule : le pack réécrit ses documents, l'utilisateur ne les modifie pas
    cadrages = cols["Mise en scène · Cadrages"]
    assert c.delete(f"/knowledge/collections/{cadrages['id']}").status_code == 409
    assert c.patch(f"/knowledge/collections/{cadrages['id']}", json={"name": "X"}).status_code == 409
    r = c.post(f"/knowledge/collections/{cadrages['id']}/documents", json={"title": "A", "content": "B"})
    assert r.status_code == 409 and "Mettre à jour les packs" in r.json()["detail"]
    assert c.patch(f"/knowledge/documents/{cu['id']}", json={"content": "x"}).status_code == 409
    assert c.delete(f"/knowledge/documents/{cu['id']}").status_code == 409


def test_rendering_pack_imports_its_5_collections_idempotently(pack_client: TestClient) -> None:
    c = pack_client
    cols = {
        col["name"]: col for col in _ok(c.get("/knowledge/collections")) if col["pack"] == "manga_rendering_knowledge"
    }
    # jamais de « Rendu · Pont presets » : les réglages vivent dans les presets, une copie dériverait
    assert set(cols) == set(RENDERING_COLLECTIONS)
    raw = (PRESETS_DIR / "knowledge_packs" / "manga_rendering_knowledge.md").read_text()
    fiches = sum(1 for line in raw.splitlines() if line.startswith("### "))
    assert fiches == 17 and sum(col["document_count"] for col in cols.values()) == fiches
    report = next(r for r in _ok(c.get("/knowledge/status"))["packs"] if r["pack"] == "manga_rendering_knowledge")
    assert report["created"] == fiches and report["warnings"] == [] and report["error"] is None
    # « Mettre à jour les packs » deux fois : rien de créé, aucun doublon
    for _ in range(2):
        update = next(r for r in _ok(c.post("/knowledge/packs/update")) if r["pack"] == "manga_rendering_knowledge")
        assert (update["created"], update["updated"], update["deleted"]) == (0, 0, 0)
        assert update["unchanged"] == fiches
    names = [col["name"] for col in _ok(c.get("/knowledge/collections"))]
    assert len(names) == len(set(names)) == len(SHIPPED_COLLECTIONS)
    # aucune fiche ne recopie les mots-clés d'une finition (style_options.yaml › finition)
    finition = PresetRegistry.load(PRESETS_DIR).style_options.options["finition"]
    copied = {k for ch in finition.choices.values() for k in [*ch.prompt_keywords, *ch.negative_keywords]}
    finitions = cols["Rendu · Finitions"]
    for doc in _ok(c.get(f"/knowledge/collections/{finitions['id']}/documents")):
        content = _ok(c.get(f"/knowledge/documents/{doc['id']}"))["content"]
        assert "`finition ›" in content or "« propre » n'ajoute rien" in content, doc["title"]
        assert not [k for k in copied if k in content], doc["title"]


def test_rendering_wiring_is_narrow() -> None:
    """Directeur artistique : Valeurs et masses + Encrage ; rédacteur de prompt : Valeurs et masses SEULEMENT ;
    scénariste : rien du pack rendu."""
    agents = PresetRegistry.load(PRESETS_DIR).knowledge.agents
    rendu = set(RENDERING_COLLECTIONS)
    assert {c for c in agents["art_direction"].collections if c in rendu} == {
        "Rendu · Valeurs et masses",
        "Rendu · Encrage",
    }
    assert [c for c in agents["image_prompt"].collections if c in rendu] == ["Rendu · Valeurs et masses"]
    # petite collection, mais cherchée : injectée entière, elle mangerait le budget du rédacteur
    assert agents["image_prompt"].searched_collections == ["Rendu · Valeurs et masses"]
    assert not [c for c in agents["script"].collections if c.startswith("Rendu")]
    assert not [c for a in agents.values() for c in a.collections if "Pont presets" in c]


def test_close_up_fiche_never_asks_for_a_flat_black_face() -> None:
    raw = (PRESETS_DIR / "knowledge_packs" / "manga_visual_knowledge.md").read_text()
    fiche = raw.split("### SHOT_CU_001")[1].split("\n### ")[0]
    assert "deep shadow" not in fiche and "dans le noir" not in fiche
    assert "half of the face in hatched shadow, never a flat black fill" in fiche
    # même consigne ailleurs : une ombre sur le visage dit son moyen (hachure, trame), jamais l'aplat plein
    assert "(bande noire)" not in raw and "half of face in deep shadow" not in raw


def test_default_wiring_shows_pack_collections_for_the_three_agents(pack_client: TestClient) -> None:
    agents = {a["role"]: a for a in _ok(pack_client.get("/knowledge/status"))["agents"]}
    script = set(agents["script"]["collections"])
    assert {"Mise en scène · Fondamentaux", "Mise en scène · Émotions", "Mise en scène · Exemples"} <= script
    da = set(agents["art_direction"]["collections"])
    # Vocabulaire et Checklist (format d'un storyboarder) : plus injectées entières dans la direction artistique.
    assert set(PACK_COLLECTIONS) - da == {
        "Mise en scène · Corps et gestes",
        "Mise en scène · Pont ComfyUI",
        "Mise en scène · Vocabulaire",
        "Mise en scène · Checklist",
    }
    writer = set(agents["image_prompt"]["collections"])
    assert {c for c in PACK_COLLECTIONS if c in writer} == {
        "Mise en scène · Cadrages",
        "Mise en scène · Angles",
        "Mise en scène · Corps et gestes",
        "Mise en scène · Action",
        "Mise en scène · Composition",
        "Mise en scène · Émotions",
        "Mise en scène · Pont ComfyUI",
    }
    assert all("Vocabulaire" not in c for c in script | writer)
    # écran « L'équipe » : le champ Savoir-faire des agents part de ces collections
    for agent_id, role in (
        ("scenariste", "script"),
        ("directeur-artistique", "art_direction"),
        ("dessinateur", "image_prompt"),
    ):
        detail = _ok(pack_client.get(f"/agents/{agent_id}"))
        assert set(detail["knowledge"]["value"]["collections"]) == set(agents[role]["collections"])


def test_shot_and_angle_terms_find_the_right_fiches(db: Database) -> None:
    embedder = MockEmbeddingProvider()
    with db.session_scope() as session:
        update_packs(session, PRESETS_DIR, embedder, SETTINGS)
        session.commit()
        ids = list(session.scalars(select(KnowledgeCollection.id)))
        keys = dict(session.execute(select(KnowledgeDocument.id, KnowledgeDocument.pack_key)).all())

        def top(query: str, n: int) -> list[str]:
            return [keys[p.document_id] for p in rank(session, query, ids, embedder, SETTINGS).passages[:n]]

        assert {"SHOT_CU_001", "ANG_LOW_001", "EMO_002"} <= set(top("gros plan contre-plongée colère", 5))
        assert top("esquive", 1) == ["ACT_004"]
        # mots-clés seuls (Ollama éteint) : le pont de vocabulaire suffit à remonter les fiches de plan et d'angle
        by_keywords = [
            keys[p.document_id] for p in rank(session, "gros plan en contre-plongée", ids, None, SETTINGS).passages
        ]
        assert {"SHOT_CU_001", "ANG_LOW_001"} <= set(by_keywords[:5])


def test_panel_writer_reads_pack_fiches_but_fragments_never_do(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings(knowledge_packs=True))) as c:
        s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames", "ai_prompt": False}), 201)
        _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
        ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
        panel = {
            "description": "Aiko esquive le sabre en contre-plongée, colère",
            "characters": ["Aiko"],
            "shot_type": "gros plan",
        }
        pages = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel]}]}))
        pid = pages[0]["panels"][0]["id"]
        seen = _ok(c.get(f"/panels/{pid}/knowledge"))  # « Savoir-faire de la case » dans l'atelier
        writer = seen["writer"]["passages"]
        assert writer and {p["pack"] for p in writer} <= {"manga_visual_knowledge", "manga_rendering_knowledge"}
        rendu = {p["collection_name"] for p in writer if p["pack"] == "manga_rendering_knowledge"}
        assert rendu <= {"Rendu · Valeurs et masses"}
        # gros plan du scénario + contre-plongée de la description : une seule fiche de plan, la bonne
        shots = [p["document_title"] for p in writer if p["document_title"].startswith("SHOT_")]
        assert shots == ["SHOT_CU_001 — Gros plan (visage)"]
        assert all(p["dropped"] for p in seen["writer"]["dropped"])
        assert "Mise en scène · Pont ComfyUI" in {p["collection_name"] for p in writer}
        assert seen["writer"]["tokens"] <= seen["writer"]["budget_tokens"]
        assert seen["fragments"]["passages"] == []  # jamais de théorie française dans le prompt d'image
        prompt = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))["final_prompt"]
        assert "Style notes" not in prompt


DIALOGUE_PAGE = (
    "mise en scène, cadrage, dialogue, champ contrechamp, réplique\n"
    "Aiko et Kenji se disputent autour de la table — Aiko, Kenji\nTu m'as menti depuis le début !"
)
ACTION_PAGE = (
    "mise en scène, cadrage, temps fort, impact\n"
    "Aiko esquive le sabre et contre-attaque d'un coup de pied — Aiko\nLe rival est projeté contre le mur"
)


def test_art_direction_fiches_are_chosen_per_page(db: Database) -> None:
    settings = PresetRegistry.load(PRESETS_DIR).knowledge
    with db.session_scope() as session:
        update_packs(session, PRESETS_DIR, MockEmbeddingProvider(), settings)
        session.commit()
        keys = dict(session.execute(select(KnowledgeDocument.id, KnowledgeDocument.pack_key)).all())
        kb = KnowledgeBase(settings, MockEmbeddingProvider())
        got = kb.for_pages(session, "art_direction", None, [(1, DIALOGUE_PAGE), (2, ACTION_PAGE)])
        by_page = {n: {keys[p.document_id] for p in got.passages if n in p.pages} for n in (1, 2)}
        # page de dialogue : champ / contrechamp ; page d'action : esquive, raccourci
        assert "SHOT_OTS_001" in by_page[1] and "SHOT_OTS_001" not in by_page[2]
        assert {"ACT_004", "ANG_FORCE_001"} <= by_page[2] and "ACT_004" not in by_page[1]
        # un seul budget, sans doublon ; Vocabulaire et Checklist ne sont plus lues par la direction artistique
        assert got.tokens <= settings.agent("art_direction").budget_tokens
        assert len({p.chunk_id for p in got.passages}) == len(got.passages)
        assert all(p.mode == "retrieved" and p.pages for p in got.passages)
        assert not {"Mise en scène · Vocabulaire", "Mise en scène · Checklist"} & set(got.collections)
        assert got.page_queries == {1: DIALOGUE_PAGE, 2: ACTION_PAGE}
        assert got.query.startswith("Page 1 : ") and "\nPage 2 : " in got.query
        text = got.savoir_faire()
        assert "· page 1\n" in text and "· page 2\n" in text
        assert "```meta" not in text and '{"' not in text


def test_small_pack_collections_are_never_injected_whole_per_page(db: Database) -> None:
    """Profil « L'équipe » enregistré avec l'ancienne liste (Vocabulaire, Checklist) : leurs fiches restent
    cherchables, mais jamais injectées entières ; une petite collection de l'utilisateur l'est toujours."""
    settings = PresetRegistry.load(PRESETS_DIR).knowledge
    with db.session_scope() as session:
        update_packs(session, PRESETS_DIR, MockEmbeddingProvider(), settings)
        mine = KnowledgeCollection(name="Mes notes")
        session.add(mine)
        session.flush()
        doc = KnowledgeDocument(collection_id=mine.id, title="Ma règle", source="text", content="Pas de pluie.")
        session.add(doc)
        session.flush()
        index_document(session, doc, MockEmbeddingProvider(), settings)
        session.commit()
        old = [*settings.agent("art_direction").collections, "Mise en scène · Vocabulaire", "Mise en scène · Checklist"]
        kb = KnowledgeBase(settings, MockEmbeddingProvider(), profile_lookup=lambda *_: [*old, "Mes notes"])
        got = kb.for_pages(session, "art_direction", None, [(1, DIALOGUE_PAGE), (2, ACTION_PAGE)])
        whole = [p for p in got.passages if p.mode == "whole"]
        assert [p.collection_name for p in whole] == ["Mes notes"] and whole[0].pages == []
        assert "Mise en scène · Vocabulaire" in got.collections
        assert got.tokens <= settings.agent("art_direction").budget_tokens


def test_profile_still_overrides_the_default_collections(db: Database) -> None:
    with db.session_scope() as session:
        update_packs(session, PRESETS_DIR, None, SETTINGS)
        session.commit()
        settings = KnowledgeSettings(
            small_collection_tokens=0,
            agents={"script": KnowledgeAgent(label="S", collections=["Mise en scène · Exemples"])},
        )
        kb = KnowledgeBase(settings, None, profile_lookup=lambda *_: ["Mise en scène · Action"])
        got = kb.for_agent(session, "script", None, "esquive")
        assert got.collections == ["Mise en scène · Action"]


# --- une fiche = un passage, un seul cadrage par case ------------------------------------------
def test_shipped_pack_gives_one_passage_per_fiche_and_reindexes_old_chunks(db: Database) -> None:
    settings = PresetRegistry.load(PRESETS_DIR).knowledge
    cap = settings.chunking.fiche_max_tokens
    # Base indexée avec l'ancien découpage (350 jetons) : l'import suivant refait les passages, sans doublon.
    old = settings.model_copy(update={"chunking": settings.chunking.model_copy(update={"fiche_max_tokens": 350})})
    with db.session_scope() as session:
        update_packs(session, PRESETS_DIR, MockEmbeddingProvider(), old)
        session.commit()
        assert any(len(d.chunks) > 1 for d in _docs(session).values())
        reports = update_packs(session, PRESETS_DIR, MockEmbeddingProvider(), settings)
        session.commit()
        report = next(r for r in reports if r.pack == "manga_visual_knowledge")
        assert report.updated > 0 and all(r.created == 0 for r in reports)
        docs = list(_docs(session).values())
        chunks = session.scalar(select(text("count(*)")).select_from(KnowledgeChunk))
        assert chunks == sum(len(d.chunks) for d in docs)
        for doc in docs:
            parts = sorted(doc.chunks, key=lambda c: c.index)
            if doc.token_count <= cap:
                assert len(parts) == 1, doc.title
            for chunk in parts:
                if "Prompt (EN)" in chunk.text:  # avec le titre de sa fiche : seul passage, ou le titre en tête
                    assert len(parts) == 1 or chunk.text.startswith(doc.title), doc.title
        annexe = next(d for d in docs if d.title.startswith("Annexe B"))
        assert len(annexe.chunks) == 1
        # import suivant : rien à refaire
        again = update_packs(session, PRESETS_DIR, MockEmbeddingProvider(), settings)
        assert [r.updated for r in again] == [0, 0, 0]


def test_oversized_fiche_keeps_its_prompt_fragment_with_the_title() -> None:
    from mangaka_engine.pipeline.knowledge import chunk_fiche

    body = "\n\n".join(f"**Point {i}.** " + "Une phrase de mise en scène assez longue. " * 12 for i in range(12))
    body += "\n\n**Prompt (EN).** `close-up of face, harsh side light`"
    parts = chunk_fiche("SHOT_X_001 — Long", body, max_tokens=300)
    assert len(parts) > 1 and all(p.tokens <= 300 for p in parts)
    assert parts[-1].text.startswith("SHOT_X_001 — Long\n\n") and "Prompt (EN)" in parts[-1].text
    assert not any("Prompt (EN)" in p.text for p in parts[:-1])
    assert chunk_fiche("Court", "**Prompt (EN).** `x`", max_tokens=300)[0].text == "**Prompt (EN).** `x`"


def _framing_keys(found: Any, keys: dict[int, str]) -> list[str]:
    return [keys[p.document_id] for p in found.writer_passages if keys[p.document_id].startswith(("SHOT_", "ANG_"))]


def test_panel_gets_one_framing_fiche_once_and_reuses_the_freed_budget(db: Database) -> None:
    settings = PresetRegistry.load(PRESETS_DIR).knowledge
    with db.session_scope() as session:
        update_packs(session, PRESETS_DIR, MockEmbeddingProvider(), settings)
        session.commit()
        keys = dict(session.execute(select(KnowledgeDocument.id, KnowledgeDocument.pack_key)).all())
        kb = KnowledgeBase(settings, MockEmbeddingProvider())
        budget = settings.agent("image_prompt").writer_budget_tokens

        medium = kb.for_panel(session, 0, "plan moyen Aiko accroupie, genoux pliés", [], plan="plan moyen")
        assert _framing_keys(medium, keys) == ["SHOT_MS_001"]
        assert medium.writer_passages[1].mode == "framing"  # après Pont ComfyUI (entière), avant les autres
        close = kb.for_panel(
            session, 0, "gros plan visage en contre-plongée colère", [], plan="gros plan", angle="en contre-plongée"
        )
        assert _framing_keys(close, keys) == ["SHOT_CU_001", "ANG_LOW_001"]
        # angle de la case sans fiche (de face) : aucune fiche d'angle ; plan inconnu : la meilleure seulement
        front = kb.for_panel(session, 0, "plan moyen en plongée de face", [], angle="de face")
        assert len([k for k in _framing_keys(front, keys) if k.startswith("SHOT_")]) <= 1
        assert not [k for k in _framing_keys(front, keys) if k.startswith("ANG_")]

        for found in (medium, close, front):
            titles = [p.document_title for p in found.writer_passages]
            assert sum(t.startswith("Annexe B — Pont vers ComfyUI") for t in titles) == 1
            assert found.writer()[0].count("Annexe B — Pont vers ComfyUI") == 1
            assert len({p.document_id for p in found.writer_passages}) == len(found.writer_passages)
            assert found.writer_tokens == sum(p.tokens for p in found.writer_passages) <= budget

        # budget libéré : sans le tri, SHOT_MFS_001 aurait été servie ; une fiche d'une autre famille la remplace
        dropped = {keys[p.document_id]: p.dropped for p in medium.writer_dropped}
        assert "SHOT_MFS_001" in dropped and "autre plan que « plan moyen »" in str(dropped["SHOT_MFS_001"])
        served = {keys[p.document_id] for p in medium.writer_passages}
        assert not served & set(dropped)
        ids = [c.id for c in session.scalars(select(KnowledgeCollection))]
        unsorted = select_passages(
            session, "plan moyen Aiko accroupie, genoux pliés", ids, kb.embedder, settings, top_k=0, budget_tokens=0
        )
        whole = [c for c in unsorted.whole_collections if c in {p.collection_id for p in medium.writer_passages}]
        before, _ = choose_passages(
            unsorted.ranked, whole, settings, top_k=medium.writer_top_k, budget_tokens=medium.writer_budget
        )
        newcomers = served - {keys[p.document_id] for p in before}
        assert newcomers and not any(k.startswith(("SHOT_", "ANG_")) for k in newcomers)


def test_low_angle_shot_of_the_script_picks_the_low_angle_fiche(pack_client: TestClient) -> None:
    c = pack_client
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames", "ai_prompt": False}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    panel = {"description": "Le rival domine la ruelle", "shot_type": "contre-plongée"}
    pages = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel]}]}))
    seen = _ok(c.get(f"/panels/{pages[0]['panels'][0]['id']}/knowledge"))
    angles = [p for p in seen["writer"]["passages"] if p["document_title"].startswith("ANG_")]
    assert [(p["document_title"], p["mode"]) for p in angles] == [("ANG_LOW_001 — Contre-plongée", "framing")]


# --- pack structure et rythme -------------------------------------------------------------
STRUCTURE_MD = PRESETS_DIR / "knowledge_packs" / "manga_story_structure.md"


def _fiches(raw: str) -> dict[str, str]:
    """Fiches par identifiant, espaces normalisés (un repère peut tomber sur deux lignes)."""
    return {part.split(" — ")[0]: " ".join(part.split()) for part in raw.split("\n### ")[1:]}


def test_structure_pack_imports_its_6_collections_idempotently(pack_client: TestClient) -> None:
    c = pack_client
    cols = {col["name"]: col for col in _ok(c.get("/knowledge/collections")) if col["pack"] == "manga_story_structure"}
    assert set(cols) == set(STRUCTURE_COLLECTIONS)
    fiches = sum(1 for line in STRUCTURE_MD.read_text().splitlines() if line.startswith("### "))
    assert fiches == 19 and sum(col["document_count"] for col in cols.values()) == fiches
    report = next(r for r in _ok(c.get("/knowledge/status"))["packs"] if r["pack"] == "manga_story_structure")
    assert report["created"] == fiches and report["warnings"] == [] and report["error"] is None
    update = next(r for r in _ok(c.post("/knowledge/packs/update")) if r["pack"] == "manga_story_structure")
    assert (update["created"], update["updated"], update["deleted"], update["unchanged"]) == (0, 0, 0, fiches)
    genres = cols["Structure · Courbes par genre"]
    titles = [d["title"] for d in _ok(c.get(f"/knowledge/collections/{genres['id']}/documents"))]
    assert "STR_GEN_001 — Courbe de tension : Shōnen" in titles and len(titles) == 7


def test_structure_wiring_is_the_scriptwriter_only() -> None:
    agents = PresetRegistry.load(PRESETS_DIR).knowledge.agents
    assert set(STRUCTURE_COLLECTIONS) <= set(agents["script"].collections)
    for role in ("art_direction", "image_prompt"):
        assert not [c for c in agents[role].collections if c.startswith("Structure")], role
    assert agents["script"].query_hint


def test_structure_fiches_agree_with_the_presets() -> None:
    """Repères chiffrés des fiches = règles chiffrées des presets (genres, dialogues, règles par planche)."""
    reg = PresetRegistry.load(PRESETS_DIR)
    raw = STRUCTURE_MD.read_text()
    fiches = _fiches(raw)
    # une courbe par genre livré, dont le meta « genre » est l'identifiant du pack de genre
    curves = {k: v for k, v in fiches.items() if k.startswith("STR_GEN_")}
    by_genre = {f.split('"genre":"')[1].split('"')[0]: f for f in curves.values()}
    assert set(by_genre) == set(reg.style_genres)
    for genre_id, fiche in by_genre.items():
        genre = reg.style_genres[genre_id]
        assert f"Courbe de tension : {genre.name}" in fiche
        # cases par page : celles des consignes du genre
        [cases] = re.findall(r"\d+ à \d+ cases", genre.llm_guidelines)
        assert cases in fiche, genre_id
        # la courbe sur 15 pages couvre chaque page une fois et une seule
        curve = fiche.split("**Courbe sur 15 pages**")[1].split("\n\n")[0]
        pages: list[int] = []
        for first, last in re.findall(r"p\. (\d+)(?:–(\d+))?", curve):
            pages += range(int(first), int(last or first) + 1)
        assert pages == list(range(1, 16)), genre_id
    # dialogues : les chiffres de prompts/script.yaml
    rules = reg.prompt("script").dialogue_rules
    assert rules is not None
    silence = fiches["STR_SIL_001"] + fiches["STR_SIL_002"]
    assert f"{rules.max_words} mots au plus, {rules.max_mean_words:g} en moyenne" in silence
    assert f"{rules.min_per_page} à {rules.max_per_page} répliques par planche" in silence
    assert f"au moins {rules.min_silent_panels_per_page} case muette par planche" in silence
    assert f"la cible est {rules.target_per_panel} répliques" in silence
    # règles par planche de la direction artistique
    page_rules = reg.prompt("direction-artistique").page_rules
    assert page_rules is not None
    assert f"Au plus {page_rules.max_choc_in_a_row} cases « choc » d'affilée" in fiches["STR_CH_002"]
    variety = reg.prompt("direction-artistique").variety_rules
    assert variety is not None and variety.max_wide_in_a_row == 1 and variety.max_wide_medium_share == 0.5
    assert "deux plans larges qui se suivent" in fiches["STR_PLAN_001"]
    assert "plans larges et moyens à la moitié des cases" in fiches["STR_PLAN_001"]
    assert page_rules.min_close_per_page == 1 and page_rules.close_min_panels == 3
    assert (
        "Au moins une case serrée (gros plan, très gros plan ou insert) par page dès 3 cases" in fiches["STR_PLAN_002"]
    )


def test_scriptwriter_gets_the_chapter_outline_and_its_genre_curve(pack_client: TestClient) -> None:
    c = pack_client
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames"}), 201)
    ch = _ok(
        c.post(
            f"/projects/{s['id']}/chapters",
            json={"title": "Pluie", "synopsis": "Aiko affronte son rival sur le toit.", "target_page_count": 2},
        ),
        201,
    )
    job = _ok(start_script(c, ch["id"]), 202)
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    assert _ok(c.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    sources = _ok(c.get(f"/chapters/{ch['id']}/sources"))
    titles = [p["document_title"] for p in sources["passages"]]
    agent = PresetRegistry.load(PRESETS_DIR).knowledge.agent("script")
    assert len(titles) <= (agent.top_k or 0) and sum(p["tokens"] for p in sources["passages"]) <= agent.budget_tokens
    # la courbe du genre de la série (shōnen), en tête, et aucune autre ; le déroulé du chapitre
    assert titles[0] == "STR_GEN_001 — Courbe de tension : Shōnen" and sources["passages"][0]["mode"] == "genre"
    assert [t for t in titles if t.startswith("STR_GEN_")] == [titles[0]]
    assert "STR_CH_001 — Le déroulé d'un chapitre en huit temps" in titles
    # aucune petite collection d'un pack injectée entière
    assert all(p["mode"] != "whole" for p in sources["passages"])
    # dans le prompt envoyé au scénariste (LLM factice)
    user = c.app.state.ctx.providers.llm.calls[-1][1].content  # type: ignore[attr-defined]
    assert "Courbe de tension : Shōnen" in user and "Ouverture** (0–7 %" in user
    assert "Courbe de tension : Seinen" not in user
