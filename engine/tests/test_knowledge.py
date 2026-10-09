"""Savoir-faire (RAG local) et bible de série : découpage, embeddings factices, recherche hybride,
budget, petites collections, bible, injection dans l'étape 1 et le prompt image, API."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.knowledge import (
    KnowledgeBase,
    KnowledgeError,
    chunk_text,
    estimate_tokens,
    extract_text,
    index_document,
    rank,
    record_chapter_summary,
    render_bible,
    select_passages,
    split_sections,
)
from mangaka_engine.presets import KnowledgeAgent, KnowledgeSettings, PresetRegistry
from mangaka_engine.providers.embedding import EmbeddingError, MockEmbeddingProvider, OllamaEmbeddingProvider
from mangaka_engine.store.db import Database
from mangaka_engine.store.models import (
    Chapter,
    ChapterStatus,
    KnowledgeCollection,
    KnowledgeDocument,
    Project,
    SeriesBible,
)
from tests.conftest import PRESETS_DIR

FIXTURES = Path(__file__).parent / "fixtures"
SETTINGS = KnowledgeSettings(small_collection_tokens=0)

GUIDE = """# Guide du scénario

Introduction courte au guide.

## Accroche

La première page doit poser une question au lecteur. Montre le héros en action dès la première case.

## Cliffhanger

Termine chaque chapitre sur une révélation ou une menace.

```
# pas un titre : dans un bloc de code
```

### Variante comique

Un gag peut remplacer la menace dans une série jeunesse.
"""


# --- découpage ---------------------------------------------------------------------
def test_sections_follow_headings_and_ignore_code_blocks() -> None:
    sections = split_sections(GUIDE)
    assert [h for h, _ in sections] == [
        "Guide du scénario",
        "Guide du scénario › Accroche",
        "Guide du scénario › Cliffhanger",
        "Guide du scénario › Cliffhanger › Variante comique",
    ]
    assert "# pas un titre" in sections[2][1]


def test_chunks_respect_max_tokens_and_never_mix_sections() -> None:
    long_section = "## Rythme\n\n" + "\n\n".join(f"Paragraphe {i} : " + "case serrée, " * 30 for i in range(6))
    chunks = chunk_text(GUIDE + "\n" + long_section, max_tokens=80, min_tokens=10)
    assert all(c.tokens <= 80 for c in chunks)
    rythme = [c for c in chunks if c.heading.endswith("Rythme")]
    assert len(rythme) >= 3 and all("Accroche" not in c.text for c in rythme)
    assert chunks[0].heading == "Guide du scénario" and chunks[0].text == "Introduction courte au guide."
    # un paragraphe géant est coupé aux phrases puis aux mots
    giant = chunk_text("mot " * 1000, max_tokens=50, min_tokens=5)
    assert len(giant) > 10 and all(c.tokens <= 50 for c in giant)


def test_small_remainder_is_merged_into_previous_chunk() -> None:
    body = "## Section\n\n" + ("a" * 300) + "\n\n" + ("b" * 300) + "\n\nfin."
    chunks = chunk_text(body, max_tokens=80, min_tokens=10)
    assert len(chunks) == 2 and chunks[-1].text.endswith("fin.")
    assert estimate_tokens("abcd" * 10) == 10 and estimate_tokens("   ") == 0


# --- extraction ---------------------------------------------------------------------
def test_pdf_extraction_on_fixture() -> None:
    source, content = extract_text("fiche-cliffhanger.pdf", (FIXTURES / "fiche-cliffhanger.pdf").read_bytes())
    assert source == "pdf"
    assert "Fiche : le cliffhanger hebdomadaire" in content
    assert "La dernière case révèle un détail inattendu." in content


def test_unsupported_or_empty_files_are_refused() -> None:
    with pytest.raises(KnowledgeError, match="non pris en charge"):
        extract_text("notes.docx", b"PK")
    with pytest.raises(KnowledgeError, match="PDF illisible"):
        extract_text("cassé.pdf", b"%PDF-1.4 rien")
    assert extract_text("notes.txt", "Décor : Kyoto".encode("cp1252")) == ("txt", "Décor : Kyoto")


# --- embeddings ----------------------------------------------------------------------
def test_mock_embeddings_are_deterministic_and_normalized() -> None:
    a, b = MockEmbeddingProvider(), MockEmbeddingProvider()
    [v1, v2] = a.embed(["Le rythme du découpage", "Le rythme du découpage"])
    assert v1 == v2 == b.embed(["le RYTHME du decoupage !"])[0]  # casse, accents et ponctuation ignorés
    assert abs(sum(x * x for x in v1) - 1) < 1e-9
    assert a.embed([""])[0] == [0.0] * 256


def test_ollama_embedding_provider_uses_api_embed() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body["model"] == "absent":
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]] * len(body["input"])})

    provider = OllamaEmbeddingProvider(
        base_url="http://ollama", model="bge-m3", batch_size=2, transport=httpx.MockTransport(handler)
    )
    assert provider.embed(["a", "b", "c"]) == [[1.0, 0.0]] * 3
    assert [len(s["input"]) for s in seen] == [2, 1] and provider.model_id == "ollama:bge-m3"
    missing = OllamaEmbeddingProvider(base_url="http://ollama", model="absent", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbeddingError, match="ollama pull absent"):
        missing.embed(["a"])


# --- recherche ----------------------------------------------------------------------
@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "k.db")
    yield database
    database.dispose()


def _collection(session: Session, name: str, project_id: int | None = None) -> KnowledgeCollection:
    collection = KnowledgeCollection(name=name, project_id=project_id)
    session.add(collection)
    session.flush()
    return collection


def _doc(
    session: Session,
    collection: KnowledgeCollection,
    title: str,
    content: str,
    settings: KnowledgeSettings = SETTINGS,
    embedder: MockEmbeddingProvider | None = None,
) -> KnowledgeDocument:
    doc = KnowledgeDocument(title=title, content=content, tags=[])
    collection.documents.append(doc)
    session.flush()
    index_document(session, doc, embedder or MockEmbeddingProvider(), settings)
    return doc


FICHES = {
    "Combat A": "Rythme du combat : alterner cases larges et cases serrées pour accélérer le combat.",
    "Combat B": "Le combat final : un rythme rapide, des cases serrées, le combat monte en tension.",
    "Combat C": "Pour un combat lisible, garder le rythme : une action par case pendant le combat.",
    "Décor": "Le décor de Kyoto sous la pluie : toits, lanternes, ruelles étroites.",
    "Kamishibai": "Le kamishibai, théâtre de papier : cadrage frontal et texte lu à voix haute.",
    "Humour": "Un gag visuel par page suffit ; la chute arrive dans la dernière case.",
}


def _library(session: Session, settings: KnowledgeSettings = SETTINGS) -> KnowledgeCollection:
    col = _collection(session, "Rythme et découpage")
    for title, content in FICHES.items():
        _doc(session, col, title, content, settings)
    return col


def test_mock_ranking_is_deterministic(db: Database) -> None:
    with db.session_scope() as session:
        col = _library(session)
        first = rank(session, "rythme du combat", [col.id], MockEmbeddingProvider(), SETTINGS).passages
        again = rank(session, "rythme du combat", [col.id], MockEmbeddingProvider(), SETTINGS).passages
        assert [p.chunk_id for p in first] == [p.chunk_id for p in again]
        assert {p.document_title for p in first[:3]} == {"Combat A", "Combat B", "Combat C"}
        assert first[0].score is not None and first[0].score >= first[-1].score  # type: ignore[operator]


def test_hybrid_retrieval_returns_the_keyword_exact_passage(db: Database) -> None:
    query = "rythme du combat façon kamishibai"
    vector_only = SETTINGS.model_copy(update={"retrieval": SETTINGS.retrieval.model_copy(update={"keyword_weight": 0})})
    with db.session_scope() as session:
        col = _library(session)
        by_vector = rank(session, query, [col.id], MockEmbeddingProvider(), vector_only).passages
        assert by_vector[0].document_title != "Kamishibai"  # les vecteurs seuls préfèrent les fiches « combat »
        hybrid = rank(session, query, [col.id], MockEmbeddingProvider(), SETTINGS).passages
        assert hybrid[0].document_title == "Kamishibai"
        assert hybrid[0].keyword_score == 1.0 and hybrid[0].vector_score is not None
        # sans embeddings (Ollama éteint), les mots-clés suffisent à le trouver
        assert rank(session, query, [col.id], None, SETTINGS).passages[0].document_title == "Kamishibai"


def test_token_budget_and_top_k_are_respected(db: Database) -> None:
    with db.session_scope() as session:
        col = _library(session)
        sizes = sorted(p.tokens for p in rank(session, "", [col.id], None, SETTINGS).passages)
        budget = sizes[0] + sizes[1] + 1
        sel = select_passages(
            session, "rythme combat", [col.id], MockEmbeddingProvider(), SETTINGS, top_k=6, budget_tokens=budget
        )
        assert len(sel.passages) >= 1
        assert sum(p.tokens for p in sel.passages) == sel.tokens <= budget
        top2 = select_passages(
            session, "rythme combat", [col.id], MockEmbeddingProvider(), SETTINGS, top_k=2, budget_tokens=10_000
        )
        assert len(top2.passages) == 2
        assert (
            select_passages(
                session, "rythme combat", [col.id], MockEmbeddingProvider(), SETTINGS, top_k=6, budget_tokens=0
            ).passages
            == []
        )


def test_small_collection_is_injected_whole(db: Database) -> None:
    settings = KnowledgeSettings(small_collection_tokens=200)
    with db.session_scope() as session:
        small = _collection(session, "Humour jeunesse")
        _doc(
            session,
            small,
            "Gags",
            "# Gags\n\nLe running gag du chat.\n\n## Chute\n\nToujours en bas de page.",
            settings,
        )
        big = _library(session, settings)
        _doc(session, big, "Long", "Remplissage sans rapport. " * 60, settings)
        sel = select_passages(
            session, "kamishibai", [small.id, big.id], MockEmbeddingProvider(), settings, top_k=1, budget_tokens=1000
        )
        whole = [p for p in sel.passages if p.mode == "whole"]
        assert [p.heading for p in whole] == ["Gags", "Gags › Chute"]  # entière, dans l'ordre du document
        retrieved = [p for p in sel.passages if p.mode == "retrieved"]
        assert [p.document_title for p in retrieved] == ["Kamishibai"]
        assert sel.whole_collections == [small.id]


def test_reindex_on_edit_replaces_chunks(client: TestClient) -> None:
    col = client.post("/knowledge/collections", json={"name": "Design de personnages"}).json()
    doc = client.post(
        f"/knowledge/collections/{col['id']}/documents",
        json={"title": "Silhouettes", "content": "# Silhouette\n\nUne silhouette lisible en noir.", "tags": ["design"]},
    ).json()
    assert [c["heading"] for c in doc["chunks"]] == ["Silhouette"] and doc["chunks"][0]["embedded"] is True
    edited = client.patch(
        f"/knowledge/documents/{doc['id']}",
        json={"content": "# Yeux\n\nDes yeux immenses pour les héros.\n\n# Mains\n\nQuatre doigts suffisent."},
    ).json()
    assert [c["heading"] for c in edited["chunks"]] == ["Yeux", "Mains"]
    hits = client.post("/knowledge/search", json={"query": "silhouette", "collection_ids": [col["id"]]}).json()
    assert all("silhouette" not in p["text"].lower() for p in hits["passages"])
    hits = client.post("/knowledge/search", json={"query": "doigts", "collection_ids": [col["id"]]}).json()
    assert hits["passages"][0]["heading"] == "Mains" and hits["passages"][0]["selected"]
    # étiquettes seules : pas de réindexation
    tagged = client.patch(f"/knowledge/documents/{doc['id']}", json={"tags": ["mains", "mains", " yeux "]}).json()
    assert tagged["tags"] == ["mains", "yeux"] and [c["id"] for c in tagged["chunks"]] == [
        c["id"] for c in edited["chunks"]
    ]
    assert client.delete(f"/knowledge/documents/{doc['id']}").status_code == 204
    hits = client.post("/knowledge/search", json={"query": "doigts", "collection_ids": [col["id"]]}).json()
    assert hits["passages"] == []


def test_upload_md_and_pdf_then_collection_counts(client: TestClient) -> None:
    col = client.post("/knowledge/collections", json={"name": "Écriture de scénario"}).json()
    files = [
        ("files", ("guide.md", GUIDE.encode(), "text/markdown")),
        ("files", ("fiche.pdf", (FIXTURES / "fiche-cliffhanger.pdf").read_bytes(), "application/pdf")),
    ]
    r = client.post(f"/knowledge/collections/{col['id']}/upload", files=files, data={"tags": "méthode, rythme"})
    assert r.status_code == 201, r.text
    md, pdf = r.json()
    assert md["title"] == "Guide du scénario" and md["source"] == "md" and len(md["chunks"]) == 4
    assert pdf["source"] == "pdf" and pdf["title"] == "fiche" and "révèle" in pdf["content"]
    assert md["tags"] == ["méthode", "rythme"]
    [listed] = client.get("/knowledge/collections").json()
    assert listed["document_count"] == 2 and listed["chunk_count"] == 5 and listed["token_count"] > 0
    bad = client.post(f"/knowledge/collections/{col['id']}/upload", files=[("files", ("x.docx", b"PK", "x"))])
    assert bad.status_code == 422 and "non pris en charge" in bad.json()["errors"][0]["message"]
    dup = client.post("/knowledge/collections", json={"name": "écriture de scénario"})
    assert dup.status_code == 422


# --- bible ----------------------------------------------------------------------------
def _series(client: TestClient, title: str) -> dict:
    return client.post("/projects", json={"title": title, "style": "encre"}).json()


def test_bible_is_always_included_for_its_series_and_never_leaks(client: TestClient) -> None:
    kyoto, autre = _series(client, "Les Lames de Kyoto"), _series(client, "Autre série")
    aiko = client.post(f"/projects/{kyoto['id']}/characters", json={"name": "Aiko"}).json()
    bible = client.put(
        f"/projects/{kyoto['id']}/bible",
        json={
            "world": "Kyoto, 1864, sous la pluie.",
            "tone": "Mélancolique, éclats d'humour.",
            "rules": "Aucun sabre ne se brise.",
            "motifs": "Le chat roux apparaît à chaque chapitre.",
            "character_notes": {str(aiko["id"]): "Rônin taciturne, déteste mentir."},
        },
    ).json()
    assert bible["characters"][0]["note"] == "Rônin taciturne, déteste mentir."
    assert "Aucun sabre ne se brise." in bible["rendered"]["text"]
    foreign = client.put(f"/projects/{autre['id']}/bible", json={"character_notes": {str(aiko["id"]): "x"}})
    assert foreign.status_code == 422

    # même sans aucune collection, l'agent de la série reçoit la bible ; l'autre série, jamais
    calls = client.app.state.ctx.providers.llm.calls  # type: ignore[attr-defined]
    for series in (kyoto, autre):
        ch = client.post(f"/projects/{series['id']}/chapters", json={"synopsis": "Un duel.", "target_page_count": 1})
        job = client.post(f"/chapters/{ch.json()['id']}/script").json()
        client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
        assert client.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"
    kyoto_prompt, autre_prompt = (call[1].content for call in calls[-2:])
    assert "Le chat roux apparaît à chaque chapitre." in kyoto_prompt and "Rônin taciturne" in kyoto_prompt
    assert "Kyoto, 1864" not in autre_prompt and "chat roux" not in autre_prompt
    assert "(pas encore de bible pour cette série)" in autre_prompt


def test_validated_chapter_summary_joins_the_bible(client: TestClient) -> None:
    series = _series(client, "Hebdo")
    ch = client.post(f"/projects/{series['id']}/chapters", json={"synopsis": "Un duel.", "target_page_count": 1}).json()
    client.patch(f"/chapters/{ch['id']}", json={"summary": "Aiko perd son sabre.", "status": "lettering"})
    assert client.get(f"/projects/{series['id']}/bible").json()["chapter_summaries"] == []
    client.patch(f"/chapters/{ch['id']}", json={"status": "ready"})
    [entry] = client.get(f"/projects/{series['id']}/bible").json()["chapter_summaries"]
    assert entry["summary"] == "Aiko perd son sabre." and entry["number"] == 1
    client.patch(f"/chapters/{ch['id']}", json={"summary": "Aiko retrouve son sabre."})
    [entry] = client.get(f"/projects/{series['id']}/bible").json()["chapter_summaries"]
    assert entry["summary"] == "Aiko retrouve son sabre."  # mis à jour, pas en double


def test_bible_budget_drops_oldest_chapter_summaries_first(db: Database) -> None:
    with db.session_scope() as session:
        project = Project(title="S", page_format="a4-300dpi", workflow_preset="qwen-image-base")
        session.add(project)
        session.flush()
        session.add(SeriesBible(project_id=project.id, world="Monde.", character_notes={}, chapter_summaries=[]))
        session.flush()
        for n in range(1, 6):
            ch = Chapter(project_id=project.id, number=n, summary=f"Résumé {n}. " + "x" * 200)
            ch.status = ChapterStatus.published
            session.add(ch)
            session.flush()
            record_chapter_summary(session, ch)
        full = render_bible(session, project.id, max_tokens=10_000)
        assert full is not None and full.chapter_summaries == 5 and not full.truncated
        short = render_bible(session, project.id, max_tokens=130)
        assert short is not None and short.tokens <= 130 and short.truncated
        assert "Résumé 5." in short.text and "Résumé 1." not in short.text and "Monde." in short.text


# --- agents ---------------------------------------------------------------------------
def test_agent_profile_wins_over_preset(db: Database) -> None:
    settings = KnowledgeSettings(
        small_collection_tokens=0,
        agents={"script": KnowledgeAgent(label="Scénariste", collections=["Écriture"], series_collections=False)},
    )
    with db.session_scope() as session:
        ecriture, humour = _collection(session, "Écriture"), _collection(session, "Humour jeunesse")
        _doc(session, ecriture, "Méthode", "Une scène = un enjeu.", settings)
        _doc(session, humour, "Gags", "Un gag par page.", settings)
        kb = KnowledgeBase(settings, MockEmbeddingProvider())
        assert kb.for_agent(session, "script", None, "gag scène").collections == ["Écriture"]
        kb.profile_lookup = lambda _s, role, _p: ["humour JEUNESSE"] if role == "script" else None
        found = kb.for_agent(session, "script", None, "gag scène")
        assert found.collections == ["Humour jeunesse"] and [p.document_title for p in found.passages] == ["Gags"]


def test_series_collections_are_private_to_their_series(db: Database) -> None:
    settings = KnowledgeSettings(small_collection_tokens=0, agents={"script": KnowledgeAgent(label="S")})
    with db.session_scope() as session:
        a = Project(title="A", page_format="a4-300dpi", workflow_preset="qwen-image-base")
        b = Project(title="B", page_format="a4-300dpi", workflow_preset="qwen-image-base")
        session.add_all([a, b])
        session.flush()
        _doc(session, _collection(session, "Lore", a.id), "Lore A", "Le dragon de A dort sous le lac.", settings)
        kb = KnowledgeBase(settings, MockEmbeddingProvider())
        assert [p.document_title for p in kb.for_agent(session, "script", a.id, "dragon lac").passages] == ["Lore A"]
        assert kb.for_agent(session, "script", b.id, "dragon lac").passages == []


def test_step1_mock_llm_request_contains_expected_passages(client: TestClient) -> None:
    client.app.state.ctx.knowledge.settings = KnowledgeSettings(  # type: ignore[attr-defined]
        small_collection_tokens=0,
        agents={"script": KnowledgeAgent(label="Scénariste", collections=["Rythme et découpage"], top_k=2)},
    )
    col = client.post("/knowledge/collections", json={"name": "Rythme et découpage"}).json()
    for title, content in FICHES.items():
        client.post(f"/knowledge/collections/{col['id']}/documents", json={"title": title, "content": content})
    other = client.post("/knowledge/collections", json={"name": "Non utilisée"}).json()
    client.post(f"/knowledge/collections/{other['id']}/documents", json={"title": "Piège", "content": "kamishibai"})
    series = _series(client, "Kami")
    ch = client.post(
        f"/projects/{series['id']}/chapters",
        json={"title": "Le théâtre de papier", "synopsis": "Un spectacle de kamishibai.", "target_page_count": 1},
    ).json()
    job = client.post(f"/chapters/{ch['id']}/script").json()
    client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    assert client.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"

    [system, user] = client.app.state.ctx.providers.llm.calls[-1]  # type: ignore[attr-defined]
    assert system.role == "system" and "Savoir-faire de l'équipe" in user.content
    assert "[1] « Kamishibai » (Rythme et découpage)" in user.content
    assert FICHES["Kamishibai"] in user.content and "Piège" not in user.content

    sources = client.get(f"/chapters/{ch['id']}/sources").json()
    assert sources["job_id"] == job["id"] and sources["agent"] == "script"
    assert sources["collections"] == ["Rythme et découpage"]
    assert len(sources["passages"]) == 2 and sources["passages"][0]["document_title"] == "Kamishibai"
    assert sources["passages"][0]["score"] > 0 and sources["bible"] is None
    assert client.get(f"/chapters/{ch['id']}/sources?agent=autre").json() is None


def test_image_prompt_gets_bible_notes_and_style_passages(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings())) as c:
        c.app.state.ctx.knowledge.settings = KnowledgeSettings(  # type: ignore[attr-defined]
            small_collection_tokens=0,
            agents={
                "image_prompt": KnowledgeAgent(
                    label="Prompts", collections=["Design"], budget_tokens=40, top_k=1, bible_max_tokens=30
                )
            },
        )
        col = c.post("/knowledge/collections", json={"name": "Design"}).json()
        c.post(
            f"/knowledge/collections/{col['id']}/documents", json={"title": "Yeux", "content": "Aiko : yeux immenses."}
        )
        series = _series(c, "Prompt")
        aiko = c.post(f"/projects/{series['id']}/characters", json={"name": "Aiko"}).json()
        c.put(f"/projects/{series['id']}/bible", json={"character_notes": {str(aiko["id"]): "cicatrice à la joue"}})
        ch = c.post(f"/projects/{series['id']}/chapters", json={"synopsis": "Aiko.", "target_page_count": 1}).json()
        job = c.post(f"/chapters/{ch['id']}/script").json()
        c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
        page = c.get(f"/chapters/{ch['id']}/pages").json()[0]
        panel = next(p for p in page["panels"] if "Aiko" in p["characters"])
        prompt = c.post(f"/panels/{panel['id']}/prompt/rebuild").json()["final_prompt"]
        assert "Repères de la bible : Aiko : cicatrice à la joue." in prompt
        assert "Notes de style : Aiko : yeux immenses." in prompt


def test_knowledge_preset_loads_and_status_reports_mock(client: TestClient) -> None:
    presets = PresetRegistry.load(PRESETS_DIR)
    assert not [i for i in presets.issues if "knowledge" in i.file]
    assert presets.knowledge.agent("script").collections[0] == "Écriture de scénario"
    assert presets.providers is not None and presets.providers.ollama is not None
    assert presets.providers.ollama.embedding_model == "bge-m3"
    status = client.get("/knowledge/status").json()
    assert status["provider"] == "mock" and status["model"] == "mock:hash-256" and status["vector_backend"] == "numpy"
    assert {a["role"] for a in status["agents"]} == {"script", "image_prompt"}
    assert client.get("/health").json()["providers"]["embedding"] == {"name": "mock", "ok": True, "detail": None}


def test_deleting_series_removes_its_collections_and_index(client: TestClient) -> None:
    series = _series(client, "Éphémère")
    col = client.post("/knowledge/collections", json={"name": "Lore", "project_id": series["id"]}).json()
    assert col["project_title"] == "Éphémère"
    client.post(f"/knowledge/collections/{col['id']}/documents", json={"title": "Lore", "content": "Dragon bleu."})
    assert client.delete(f"/projects/{series['id']}").status_code == 204
    assert client.get("/knowledge/collections").json() == []
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        assert session.execute(text("SELECT count(*) FROM knowledge_fts")).scalar() == 0


def test_image_prompt_never_carries_quoted_text_from_bible_or_knowledge(
    make_settings: Callable[..., Settings],
) -> None:
    with TestClient(create_app(make_settings())) as c:
        c.app.state.ctx.knowledge.settings = KnowledgeSettings(  # type: ignore[attr-defined]
            small_collection_tokens=0,
            agents={
                "image_prompt": KnowledgeAgent(
                    label="Prompts", collections=["Design"], budget_tokens=80, top_k=1, bible_max_tokens=60
                )
            },
        )
        col = c.post("/knowledge/collections", json={"name": "Design"}).json()
        c.post(
            f"/knowledge/collections/{col['id']}/documents",
            json={"title": "Léa", "content": 'Léa : frange courte, crie "Halte !" en pointant du doigt.'},
        )
        series = _series(c, "Enquêtes")
        lea = c.post(f"/projects/{series['id']}/characters", json={"name": "Léa"}).json()
        note = "Détective en herbe, têtue, dit « ça cloche ! ». Imperméable jaune."
        c.put(f"/projects/{series['id']}/bible", json={"character_notes": {str(lea["id"]): note}})
        ch = c.post(f"/projects/{series['id']}/chapters", json={"synopsis": "Léa.", "target_page_count": 1}).json()
        job = c.post(f"/chapters/{ch['id']}/script").json()
        c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
        page = c.get(f"/chapters/{ch['id']}/pages").json()[0]
        panel = next(p for p in page["panels"] if "Léa" in p["characters"])
        prompt = c.post(f"/panels/{panel['id']}/prompt/rebuild").json()["final_prompt"]
        assert "Repères de la bible : Léa : Détective en herbe, têtue, dit. Imperméable jaune." in prompt
        assert "Notes de style : Léa : frange courte, crie en pointant du doigt." in prompt
        assert "cloche" not in prompt and "Halte" not in prompt
        assert not any(q in prompt for q in '«»“”"')


def test_strip_quoted_handles_nested_and_stray_quotes() -> None:
    from mangaka_engine.pipeline.prompt import strip_quoted

    assert strip_quoted("« Elle dit « ça cloche ! ». » Fin.") == "Fin."
    assert strip_quoted("Il hurle « Stop ! sans fermer") == "Il hurle Stop ! sans fermer"
