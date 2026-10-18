"""Bibliothèque des onomatopées (presets/sfx_library.yaml) : seule source du scénariste et du directeur artistique.
Une onomatopée du LLM hors de la liste est retirée avec un avertissement ; celle de l'auteur reste toujours (#237)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline import art_direction as da
from mangaka_engine.pipeline.script import SFX_REJECTED, ScriptContext, filter_sfx, parse_script, render_messages
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import SFX_LIBRARY_MAX, SFX_LIBRARY_MIN
from mangaka_engine.providers.llm.mock import MOCK_DA_OFF_LIBRARY, MOCK_OFF_LIBRARY
from tests.conftest import PRESETS_DIR, STYLE, start_script

PRESETS = PresetRegistry.load(PRESETS_DIR)
LIBRARY = PRESETS.sfx_library


# --- preset ----------------------------------------------------------------------------
def test_library_is_loaded_with_20_to_30_entries() -> None:
    assert LIBRARY is not None, PRESETS.issues
    assert not [i for i in PRESETS.issues if i.file.startswith("sfx_library")]
    assert SFX_LIBRARY_MIN <= len(LIBRARY.entries()) <= SFX_LIBRARY_MAX
    assert all(e.usage for e in LIBRARY.entries())
    assert "AÏE" in [e.text for e in LIBRARY.entries()]  # accents gardés


def _root_with(tmp_path: Path, text: str | None) -> Path:
    root = tmp_path / "presets"
    shutil.copytree(PRESETS_DIR, root)
    if text is None:
        (root / "sfx_library.yaml").unlink()
    else:
        (root / "sfx_library.yaml").write_text(text, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("groups:\n  - label: Coups\n    entries:\n      - { text: BAM, usage: coup }\n", "entre 20 et 30"),
        (
            "groups:\n  - label: Coups\n    entries:\n"
            + "".join(f"      - {{ text: BAM{'A' * k}M, usage: coup }}\n" for k in range(20)),
            "doublon",
        ),
        ("groups:\n  - label: Coups\n    entries:\n      - { text: BAM }\n", "usage"),
    ],
)
def test_bad_library_is_a_clear_preset_issue(tmp_path: Path, text: str, message: str) -> None:
    reg = PresetRegistry.load(_root_with(tmp_path, text))
    assert reg.sfx_library is None
    issue = next(i for i in reg.issues if i.file == "sfx_library.yaml")
    assert message in issue.message


def test_missing_library_is_reported(tmp_path: Path) -> None:
    reg = PresetRegistry.load(_root_with(tmp_path, None))
    assert reg.sfx_library is None
    assert any(i.file == "sfx_library.yaml" and "absent" in i.message for i in reg.issues)


# --- correspondance ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "entry"),
    [
        ("BOUM", "BOUM"),
        ("BOUUUM !", "BOUM"),
        ("boum", "BOUM"),
        ("Aïe !", "AÏE"),
        ("AIE", "AÏE"),
        ("ZIP", "ZIIIP"),
        ("Bam…", "BAM"),
        ("TOC", "TOC TOC"),
        ("TOC TOC TOC !", "TOC TOC"),
        ("tic… tac…", "TIC TAC"),
    ],
)
def test_library_word_and_stretched_variant_are_accepted(text: str, entry: str) -> None:
    assert LIBRARY is not None
    assert LIBRARY.match(text) == entry


@pytest.mark.parametrize("text", ["FROU", "KARI", "HISSE", "BOOM", "ÇA CRAQUE !"])
def test_invented_sfx_is_rejected(text: str) -> None:
    assert LIBRARY is not None
    assert LIBRARY.match(text) is None


# --- scénariste ------------------------------------------------------------------------
def _script(*sfx: str) -> str:
    panels = [{"description": "Le coup part", "sfx": [{"text": t, "intensity": "choc"} for t in sfx]}]
    return json.dumps({"pages": [{"panels": panels}], "summary": "Un coup."})


def test_scenarist_sfx_outside_library_are_dropped_with_a_warning() -> None:
    out = parse_script(_script("FROU", "BOUUUM !", "KARI", "HISSE"))
    rejected = filter_sfx(out, LIBRARY)
    assert [s.text for s in out.pages[0].panels[0].sfx] == ["BOUUUM !"]
    assert rejected == ["page 1 › case 1 : « FROU »", "page 1 › case 1 : « KARI »", "page 1 › case 1 : « HISSE »"]


def test_scenarist_without_library_keeps_everything() -> None:
    out = parse_script(_script("FROU"))
    assert filter_sfx(out, None) == []
    assert [s.text for s in out.pages[0].panels[0].sfx] == ["FROU"]


def test_scenarist_prompt_lists_the_library() -> None:
    ctx = ScriptContext(
        series={"title": "T", "style": "encre", "reading_direction": "rtl"},
        characters=[],
        previous_chapters=[],
        chapter={"number": 1, "title": "", "synopsis": "Un duel.", "target_pages": 2},
        sfx_library=LIBRARY,
    )
    system, user = render_messages(PRESETS.prompt("script"), ctx)
    text = system.content + user.content
    assert "UNIQUEMENT dans cette bibliothèque" in text
    assert "BADABOUM (chute en cascade" in text and "VROUM" in text
    assert "BIIIP ! »" not in text  # plus d'exemples libres


# --- directeur artistique -----------------------------------------------------------------
def _da_output(*sfx: str) -> da.DirectionOutput:
    return da.DirectionOutput.model_validate(
        {
            "pages": [
                {
                    "page": 1,
                    "rythme": "climax",
                    "rationale": "Le coup final.",
                    "panels": [
                        {
                            "panel": 1,
                            "intensity": "choc",
                            "plan": "gros plan",
                            "sfx": [{"text": t, "intensity": "fort"} for t in sfx],
                        }
                    ],
                }
            ]
        }
    )


def test_art_director_drops_unknown_sfx_and_keeps_two_per_panel() -> None:
    assert da.MAX_SFX == 2
    out = _da_output("KARI", "BAM", "BOUUUM !", "CRAC", "FROU")
    rejected = da.filter_sfx(out, LIBRARY)
    panel = out.pages[0].panels[0]
    assert [s.text for s in panel.sfx] == ["BAM", "BOUUUM !"]
    assert panel.sfx_rejected == ["KARI", "FROU"]
    assert rejected == ["page 1 › case 1 : « KARI »", "page 1 › case 1 : « FROU »"]


def test_art_director_prompt_lists_the_library_and_two_per_panel() -> None:
    prompt = PRESETS.prompt("direction-artistique")
    assert "(0 à 2)" in prompt.system + prompt.user
    assert "0 à 4" not in prompt.system + prompt.user


# --- de bout en bout (mock) ----------------------------------------------------------------
@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


def _wait(c: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    return c.get(f"/jobs/{job['id']}").json()


def _all_sfx(c: TestClient, chapter_id: int) -> list[str]:
    pages = c.get(f"/chapters/{chapter_id}/pages").json()
    return [s["text"] for p in pages for pa in p["panels"] for s in pa["sfx"]]


def test_mock_chapter_letters_only_library_sfx_and_reports_the_invented_ones(c: TestClient) -> None:
    assert LIBRARY is not None
    sid = c.post("/projects", json={**STYLE, "title": "Onomatopées"}).json()["id"]
    ch = c.post(
        f"/projects/{sid}/chapters",
        json={"synopsis": "Un duel sous la pluie. Le rival frappe.", "target_page_count": 4},
    ).json()
    job = _wait(c, start_script(c, ch["id"]).json())
    assert job["status"] == "succeeded", job
    # Le mock glisse une onomatopée inventée : retirée, nommée dans le message et sur le job.
    assert f"hors bibliothèque retirée ({MOCK_OFF_LIBRARY})" in job["message"]
    assert [w.endswith(f"« {MOCK_OFF_LIBRARY} »") for w in job["params"][SFX_REJECTED]] == [True]
    words = _all_sfx(c, ch["id"])
    assert words and all(LIBRARY.match(w) for w in words)

    r = c.post(f"/chapters/{ch['id']}/direction", json={})
    job = _wait(c, r.json())
    assert job["status"] == "succeeded", job
    assert f"({MOCK_DA_OFF_LIBRARY})" in job["message"]
    direction = c.get(f"/chapters/{ch['id']}/direction").json()
    panels = [pa for p in direction["pages"] for pa in p["panels"]]
    assert [w for pa in panels for w in pa["sfx_rejected"]] == [MOCK_DA_OFF_LIBRARY]
    assert all(len(pa["sfx"]) <= da.MAX_SFX for pa in panels)
    assert all(LIBRARY.match(s["text"]) for pa in panels for s in pa["sfx"])
    assert c.post(f"/chapters/{ch['id']}/direction/apply", json={}).status_code == 200
    words = _all_sfx(c, ch["id"])
    assert words and all(LIBRARY.match(w) for w in words)
    assert MOCK_DA_OFF_LIBRARY not in words


def test_author_sfx_are_never_filtered(c: TestClient) -> None:
    """Lettrage (« + Onomatopée ») et écran Direction artistique : la bibliothèque contraint l'IA, pas l'auteur."""
    sid = c.post("/projects", json={**STYLE, "title": "Auteur"}).json()["id"]
    ch = c.post(
        f"/projects/{sid}/chapters",
        json={"synopsis": "Un duel sous la pluie. Le rival frappe.", "target_page_count": 3},
    ).json()
    assert _wait(c, start_script(c, ch["id"]).json())["status"] == "succeeded"
    pages = c.get(f"/chapters/{ch['id']}/pages").json()
    panel = pages[0]["panels"][0]
    r = c.post(f"/panels/{panel['id']}/sfx", json={"text": "FROU !", "intensity": "calme"})
    assert r.status_code == 201, r.text
    # La direction artistique, puis son application, ne touchent pas à l'onomatopée de l'auteur.
    assert _wait(c, c.post(f"/chapters/{ch['id']}/direction", json={}).json())["status"] == "succeeded"
    page_id = pages[0]["id"]
    edit = {"panels": [{"panel_id": panel["id"], "sfx": [{"text": "HISSE", "intensity": "fort"}]}]}
    r = c.patch(f"/pages/{page_id}/direction", json=edit)
    assert r.status_code == 200, r.text
    edited = next(pa for pa in r.json()["panels"] if pa["panel_id"] == panel["id"])
    assert [s["text"] for s in edited["sfx"]] == ["HISSE"] and edited["sfx_rejected"] == []
    assert c.post(f"/chapters/{ch['id']}/direction/apply", json={}).status_code == 200
    texts = [s["text"] for s in c.get(f"/chapters/{ch['id']}/pages").json()[0]["panels"][0]["sfx"]]
    assert "FROU !" in texts and "HISSE" in texts
