"""Réglages de l'atelier : « Ton nom », auteur par défaut des validations et décisions d'étape (#199)."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.store.models import Chapter, ChapterStageDecision
from tests.test_scenes import _chapter, _ok, _propose, _stage


@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


def _decisions(c: TestClient, chapter_id: int) -> list[tuple[str, str, str]]:
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        rows = session.scalars(
            select(ChapterStageDecision)
            .where(ChapterStageDecision.chapter_id == chapter_id)
            .order_by(ChapterStageDecision.id)
        )
        return [(r.stage, r.decision, r.author) for r in rows]


def _validated_by(c: TestClient, chapter_id: int) -> str:
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        chapter = session.get(Chapter, chapter_id)
        assert chapter is not None
        return chapter.scenes_validated_by


def test_author_name_is_empty_then_saved_trimmed_and_cleared(c: TestClient) -> None:
    assert _ok(c.get("/settings")) == {"author_name": ""}
    assert _ok(c.put("/settings", json={"author_name": "  David   Duhamel "})) == {"author_name": "David Duhamel"}
    assert _ok(c.get("/settings"))["author_name"] == "David Duhamel"
    assert c.put("/settings", json={"author_name": "x" * 121}).status_code == 422
    assert _ok(c.put("/settings", json={"author_name": ""})) == {"author_name": ""}


def test_default_author_signs_scenes_and_stage_decisions(c: TestClient) -> None:
    _ok(c.put("/settings", json={"author_name": "Ouro"}))
    ch = _chapter(c)
    _propose(c, ch["id"])
    out = _ok(c.post(f"/chapters/{ch['id']}/scenes/validate"))  # aucun auteur envoyé
    assert out["validated_by"] == "Ouro" and _validated_by(c, ch["id"]) == "Ouro"
    assert _stage(c, ch["id"])["decision"]["author"] == "Ouro"
    # Passer outre une étape : signé aussi par défaut ; un nom saisi dans la boîte de dialogue l'emporte.
    assert _decisions(c, ch["id"]) == [("scenes", "validated", "Ouro")]
    other = _chapter(c)
    _ok(c.post(f"/chapters/{other['id']}/stages/scenes/override", json={"note": "plus tard"}))
    _ok(c.request("DELETE", f"/chapters/{other['id']}/stages/scenes/override", json={"author": "Aladin"}))
    assert _decisions(c, other["id"]) == [("scenes", "forced", "Ouro"), ("scenes", "revoked", "Aladin")]


def test_without_a_default_the_author_stays_what_was_typed(c: TestClient) -> None:
    ch = _chapter(c)
    _propose(c, ch["id"])
    _ok(c.post(f"/chapters/{ch['id']}/scenes/validate"))
    assert _validated_by(c, ch["id"]) == "" and _decisions(c, ch["id"]) == [("scenes", "validated", "")]
