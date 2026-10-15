"""Name scène par scène (#190) : une génération par scène (scénario puis direction artistique) selon le profil de son
type, contrôle « une action par case », parts de plans du profil de la scène en direction artistique, lignes de
mouvement, réécriture d'une seule scène sans toucher aux autres, mesure par scène, ancien mode inchangé."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.art_direction import check_variety
from mangaka_engine.pipeline.pre_direction import series_charter, tempo_profile
from mangaka_engine.pipeline.scene_name import action_problems, narration_problems, scene_charter
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.store.models import Chapter, ImageKind, Page, PanelImage, Project
from tests.conftest import PRESETS_DIR, STYLE

REG = PresetRegistry.load(PRESETS_DIR)
RULE = REG.prompt("script-scene").one_action
SYNOPSIS = (
    "Aiko arrive au village au petit matin. Un rônin la frappe et lui vole son sabre. Ils discutent toute la nuit."
)
SCENES = [
    {"title": "L'arrivée", "summary": "Aiko arrive au village au petit matin.", "type": "calme", "pages": 2},
    {"title": "Le duel", "summary": "Un rônin la frappe et lui vole son sabre.", "type": "combat", "pages": 3},
    {"title": "La nuit", "summary": "Ils discutent toute la nuit autour du feu.", "type": "dialogue", "pages": 2},
]


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


def _wait(c: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    c.app.state.ctx.jobs.wait(job["id"], 60)  # type: ignore[attr-defined]
    return _ok(c.get(f"/jobs/{job['id']}"))


def _llm(c: TestClient) -> Any:
    return c.app.state.ctx.providers.llm  # type: ignore[attr-defined]


def _chapter(c: TestClient, synopsis: str = SYNOPSIS) -> dict[str, Any]:
    """Chapitre de 7 pages, trois scènes validées : calme (2), combat (3), dialogue (2)."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Le sabre"}), 201)
    for name in ("Aiko", "Rônin"):
        _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"synopsis": synopsis, "target_page_count": 7}), 201)
    _ok(c.put(f"/chapters/{ch['id']}/scenes", json={"scenes": SCENES}))
    _ok(c.post(f"/chapters/{ch['id']}/scenes/validate"))
    return ch


def _script(c: TestClient, ch: dict[str, Any]) -> dict[str, Any]:
    return _wait(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202))


def _direct(c: TestClient, ch: dict[str, Any]) -> dict[str, Any]:
    return _wait(c, _ok(c.post(f"/chapters/{ch['id']}/direction"), 202))


def _measure(c: TestClient, ch: dict[str, Any]) -> list[dict[str, Any]]:
    return _ok(c.get(f"/chapters/{ch['id']}/scenes/measure"))["scenes"]


def _tasks(c: TestClient, task: str) -> list[list[Any]]:
    return [call for call in _llm(c).calls if f'"task": "{task}"' in call[1].content]


# --- scénario : une génération par scène, profils respectés ---------------------------------------------------------
def test_three_scenes_of_different_types_each_follow_their_profile(c: TestClient) -> None:
    ch = _chapter(c)
    job = _script(c, ch)
    assert job["status"] == "succeeded", job
    assert "scène par scène (3 scènes)" in job["message"] and "essais" not in job["message"]
    # Une génération par scène, chacune avec la liste validée, ce qui est déjà écrit et son profil en clair.
    calls = _tasks(c, "script")
    assert len(calls) == 3
    users = [next(m.content for m in call if m.role == "user") for call in calls]
    assert "SCÈNE À ÉCRIRE : scène 2 « Le duel » — Combat (combat)" in users[1]
    assert "Pages : EXACTEMENT 3 (pages 3 à 5 du chapitre)" in users[1]
    assert "6 cases par planche" in users[1] and "aucun encadré de narration" in users[1]
    assert "- scène 1 « L'arrivée » (Calme, avant cette scène) :" in users[1]
    assert "(rien encore : c'est la première scène écrite)" in users[0]
    assert "LAY_005" in users[1] and "LAY_003" in users[2] and "FUND_001" in users[0]
    # Règles de name dans le prompt (preset, pas code).
    system = next(m.content for m in calls[0] if m.role == "system")
    assert "UNE CASE = UN MOMENT, UNE SEULE ACTION" in system and "la tourne de page" in system.lower()

    measure = _measure(c, ch)
    assert [m["type"] for m in measure] == ["calme", "combat", "dialogue"]
    for m in measure:
        e = m["expected"]
        assert len(m["pages"]) == m["planned_pages"]
        for page in m["pages"]:
            assert page["panels"] == 1 or e["panels_min"] <= page["panels"] <= e["panels_max"], (m["type"], page)
            assert page["replies"] <= e["replies_max"], (m["type"], page)
            assert page["panels"] == 1 or page["replies"] >= e["replies_min"], (m["type"], page)
            assert page["silent"] >= e["silent_min"], (m["type"], page)
            if e["narration_max"] is not None:
                assert page["narration"] <= e["narration_max"], (m["type"], page)
            assert page["warnings"] == []
    calme, combat, dialogue = measure
    assert combat["expected"]["panels_min"] == combat["expected"]["panels_max"] == 6
    assert (combat["expected"]["replies_min"], combat["expected"]["replies_max"]) == (2, 4)
    assert combat["expected"]["silent_min"] == 2 and combat["expected"]["narration_max"] == 0
    assert all(p["panels"] == 6 and p["replies"] <= 4 for p in combat["pages"])
    assert all(4 <= p["panels"] <= 5 and p["replies"] >= 6 for p in dialogue["pages"])
    assert all(5 <= p["panels"] <= 6 for p in calme["pages"])
    # Écran Scénario : dialogues mesurés scène par scène (le combat presque muet n'est pas « trop peu bavard »).
    assert _ok(c.get(f"/chapters/{ch['id']}/dialogues"))["warnings"] == []
    # Pages rattachées, dans l'ordre des scènes.
    scenes = _ok(c.get(f"/chapters/{ch['id']}/scenes"))["scenes"]
    assert [s["page_numbers"] for s in scenes] == [[1, 2], [3, 4, 5], [6, 7]]


def test_direction_is_done_scene_by_scene_with_the_scene_shot_shares(c: TestClient) -> None:
    ch = _chapter(c)
    _script(c, ch)
    job = _direct(c, ch)
    assert job["status"] == "succeeded", job
    assert "scène par scène (3 scènes)" in job["message"]
    calls = _tasks(c, "art_direction")
    first = [call for call in calls if sum(1 for m in call if m.role == "assistant") == 0]
    assert len(first) == 3  # une génération par scène
    user = next(m.content for m in first[1] if m.role == "user")
    assert "Tu diriges la scène 2 « Le duel » (Combat), pages 3 à 5" in user
    assert "lignes de mouvement IMPOSÉES" in user
    measure = _measure(c, ch)
    combat = measure[1]
    total = combat["shots"]["total"]
    assert combat["shots"]["proposed"] == total == 18
    assert combat["shots"]["proposed_counts"]["close_up"] >= 9  # au moins 50 % de gros plans (profil combat)
    assert combat["shots"]["proposed_counts"]["wide"] <= 3
    assert not [w for m in measure for w in m["warnings"]], [m["warnings"] for m in measure]
    # Lignes de mouvement : imposées en combat (action et ambiance), interdites dans la scène calme.
    pages = _ok(c.get(f"/chapters/{ch['id']}/direction"))["pages"]
    combat_panels = [pa for p in pages if 3 <= p["number"] <= 5 for pa in p["panels"]]
    moving = [pa for pa in combat_panels if pa["intensity"] != "calme"]
    assert moving and all("lignes de mouvement" in pa["ambiance"] for pa in moving)
    assert all("lignes de vitesse" in pa["action"] for pa in moving)
    calm_panels = [pa for p in pages if p["number"] <= 2 for pa in p["panels"]]
    assert all("sans lignes de mouvement" in pa["ambiance"] for pa in calm_panels)
    # Rythme du chapitre : jamais de respiration manquante après un pic, jonctions de scènes comprises.
    rythmes = [p["rythme"] for p in sorted(pages, key=lambda p: p["number"])]
    for a, b in zip(rythmes, rythmes[1:], strict=False):
        assert not (a == "climax" and b not in ("respiration", "calme")), rythmes
    # Après application, les plans réellement appliqués sont mesurés.
    _ok(c.post(f"/chapters/{ch['id']}/direction/apply", json={}))
    combat = _measure(c, ch)[1]
    assert combat["shots"]["applied"] == 18 and combat["shots"]["applied_counts"]["close_up"] >= 9


def test_a_combat_direction_without_close_ups_is_retried() -> None:
    project = Project(title="x", **STYLE)
    charter = scene_charter(series_charter(REG, project), tempo_profile(REG.scene_types, project, "combat"))
    plans = ["plan large", "plan moyen", "plan rapproché", "plan moyen", "insert", "plan rapproché"]
    page = [(1, [{"plan": p} for p in plans])]
    _by_page, scene = check_variety(page, None, charter, scene=True)
    assert any(m.startswith("trop peu de gros plans : 0 sur 6 (au moins 3, 50 %)") for m in scene), scene
    # Sans le profil de la scène (charte de la série, une seule page) : rien n'est mesuré.
    assert check_variety(page, None, series_charter(REG, project))[1] == []
    plans = ["gros plan", "plan moyen", "très gros plan", "plan rapproché", "gros plan", "insert"]
    assert not [
        m for m in check_variety([(1, [{"plan": p} for p in plans])], None, charter, scene=True)[1] if "gros" in m
    ]


def test_the_combat_scene_direction_is_relaunched_when_it_has_no_close_up(c: TestClient) -> None:
    ch = _chapter(c, SYNOPSIS + " [mock:da-sans-gros-plan:1]")
    _script(c, ch)
    job = _direct(c, ch)
    assert job["status"] == "succeeded" and "en 2 essais" in job["message"], job
    retries = [
        call[-1].content
        for call in _tasks(c, "art_direction")
        if call[-1].role == "user" and "invalide" in call[-1].content[:80]
    ]
    assert any("trop peu de gros plans" in r and "50 %" in r for r in retries), retries
    combat = _measure(c, ch)[1]
    assert combat["shots"]["proposed_counts"]["close_up"] >= 9


# --- une action par case ---------------------------------------------------------------------------------------------
def test_one_action_per_panel_heuristic() -> None:
    problems = action_problems([(2, 3, "Il dégaine puis tire et s'enfuit.")], RULE)
    assert len(problems) == 1
    assert problems[0].startswith("une action par case : page 2 › case 3 : « Il dégaine puis tire et s'enfuit. »")
    assert "« puis »" in problems[0]
    # Trois verbes d'action sans mot de liaison : relancé aussi.
    assert "3 actions" in action_problems([(1, 1, "Aiko saute, attrape la corde et grimpe.")], RULE)[0]
    # Un seul moment : rien (« depuis » n'est pas « puis », « entre » n'est pas compté).
    for text in ("Il dégaine.", "Aiko attend depuis l'aube, entre deux colonnes.", "Le rônin frappe et vole le sabre."):
        assert action_problems([(1, 1, text)], RULE) == [], text
    assert action_problems([(1, 1, "Il dégaine puis tire.")], None) == []
    assert narration_problems([0, 2], 1) == [
        "page 2 : 2 encadrés de narration (1 au plus par planche dans cette scène) : raconte par l'image, ou passe en "
        "pensée ou en réplique"
    ]
    assert narration_problems([3], None) == []


def test_a_panel_with_several_actions_relaunches_the_writer_then_warns(c: TestClient) -> None:
    ch = _chapter(c, SYNOPSIS + " [mock:plusieurs-actions:1]")
    job = _script(c, ch)
    assert job["status"] == "succeeded" and "en 2 essais" in job["message"], job
    retries = [call[-1].content for call in _tasks(c, "script") if "invalide" in call[-1].content[:80]]
    assert len(retries) == 3  # chaque scène relancée sur sa case fautive
    assert all("une action par case : page 1 › case 1 : « Il dégaine puis tire et s'enfuit. »" in r for r in retries)
    assert not [w for m in _measure(c, ch) for w in m["warnings"] if "une action par case" in w]

    ch = _chapter(c, SYNOPSIS + " [mock:plusieurs-actions:3]")
    job = _script(c, ch)
    assert job["status"] == "succeeded" and "avertissement" in job["message"], job
    measure = _measure(c, ch)
    first_pages = [m["pages"][0]["number"] for m in measure]
    for m, number in zip(measure, first_pages, strict=True):
        assert any(w.startswith(f"une action par case : page {number} › case 1") for w in m["warnings"]), m["warnings"]


# --- réécrire une seule scène ---------------------------------------------------------------------------------------
def _snapshot(c: TestClient, chapter_id: int, numbers: set[int]) -> list[Any]:
    """Pages, cases, bulles, croquis, versions et direction artistique des pages `numbers`."""
    out = []
    with c.app.state.ctx.db.session_scope() as s:  # type: ignore[attr-defined]
        chapter = s.get(Chapter, chapter_id)
        assert chapter is not None
        for page in sorted(chapter.pages, key=lambda p: p.number):
            if page.number not in numbers:
                continue
            out.append(
                (
                    page.id,
                    page.number,
                    page.scene_id,
                    page.layout,
                    (page.direction.values, page.direction.status, page.direction.variant) if page.direction else None,
                    [
                        (
                            pa.id,
                            pa.description,
                            pa.shot_type,
                            [(b.id, b.text, b.kind) for b in pa.bubbles],
                            [(i.id, i.version, i.kind, i.path) for i in pa.images],
                        )
                        for pa in page.panels
                    ],
                )
            )
    return out


def _add_images(c: TestClient, chapter_id: int) -> None:
    with c.app.state.ctx.db.session_scope() as s:  # type: ignore[attr-defined]
        for page in s.query(Page).filter(Page.chapter_id == chapter_id):
            for pa in page.panels:
                s.add(PanelImage(panel_id=pa.id, version=1, kind=ImageKind.croquis, path=f"croquis/{pa.id}.png"))
                s.add(PanelImage(panel_id=pa.id, version=2, path=f"v/{pa.id}.png", selected=True))
        s.commit()


def test_rewriting_scene_2_leaves_scenes_1_and_3_identical(c: TestClient) -> None:
    ch = _chapter(c)
    _script(c, ch)
    _direct(c, ch)
    _ok(c.post(f"/chapters/{ch['id']}/direction/apply", json={}))
    _add_images(c, ch["id"])
    scenes = _ok(c.get(f"/chapters/{ch['id']}/scenes"))["scenes"]
    others = {1, 2, 6, 7}
    before = _snapshot(c, ch["id"], others)
    old_two = _snapshot(c, ch["id"], {3, 4, 5})

    # Scénario de la scène 2 seulement.
    calls = len(_llm(c).calls)
    job = _wait(c, _ok(c.post(f"/chapters/{ch['id']}/scenes/{scenes[1]['id']}/script"), 202))
    assert job["status"] == "succeeded" and job["message"].startswith("scène 2 réécrite : 3 pages"), job
    new_calls = _llm(c).calls[calls:]
    assert len(new_calls) == 1  # une seule génération, celle de la scène 2
    user = next(m.content for m in new_calls[0] if m.role == "user")
    assert "SCÈNE À ÉCRIRE : scène 2" in user and "(Calme, avant cette scène)" in user
    assert "(Dialogue, après cette scène)" in user
    assert _snapshot(c, ch["id"], others) == before
    new_two = _snapshot(c, ch["id"], {3, 4, 5})
    assert [p[1] for p in new_two] == [3, 4, 5] and all(p[2] == scenes[1]["id"] for p in new_two)
    assert not {p[0] for p in new_two} & {p[0] for p in old_two}  # nouvelles pages, anciennes supprimées
    assert all(not pa[4] for p in new_two for pa in p[5])

    # Direction de la scène 2 seulement : les scènes 1 et 3 gardent leur direction appliquée.
    job = _wait(c, _ok(c.post(f"/chapters/{ch['id']}/scenes/{scenes[1]['id']}/direction"), 202))
    assert job["status"] == "succeeded" and job["message"].startswith("Scène 2 redirigée : 3 pages dirigées"), job
    assert _snapshot(c, ch["id"], others) == before
    pages = {p["number"]: p for p in _ok(c.get(f"/chapters/{ch['id']}/direction"))["pages"]}
    assert all(pages[n]["status"] == "proposed" and pages[n]["has_direction"] for n in (3, 4, 5))
    # Rediriger une scène déjà appliquée la remplace aussi (verrous gardés), sans toucher aux autres.
    _ok(c.post(f"/chapters/{ch['id']}/direction/apply", json={}))
    before = _snapshot(c, ch["id"], {1, 2, 3, 4, 5})
    job = _wait(c, _ok(c.post(f"/chapters/{ch['id']}/scenes/{scenes[2]['id']}/direction"), 202))
    assert job["status"] == "succeeded"
    assert _snapshot(c, ch["id"], {1, 2, 3, 4, 5}) == before
    pages = {p["number"]: p for p in _ok(c.get(f"/chapters/{ch['id']}/direction"))["pages"]}
    assert pages[6]["status"] == pages[7]["status"] == "proposed" and pages[1]["status"] == "applied"


def test_rewriting_one_scene_needs_validated_scenes_and_pages_in_scenes(c: TestClient) -> None:
    ch = _chapter(c)
    scene = _ok(c.get(f"/chapters/{ch['id']}/scenes"))["scenes"][0]
    r = c.post(f"/chapters/{ch['id']}/scenes/{scene['id']}/direction")
    assert r.status_code == 422 and "écris d'abord son scénario" in r.json()["errors"][0]["message"]
    r = c.post(f"/chapters/{ch['id']}/scenes/99999/script")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "scene_id"
    body = {"scenes": [{**s, "id": None} for s in SCENES]}
    _ok(c.put(f"/chapters/{ch['id']}/scenes", json=body))  # retouche : validation retirée
    scene = _ok(c.get(f"/chapters/{ch['id']}/scenes"))["scenes"][0]
    r = c.post(f"/chapters/{ch['id']}/scenes/{scene['id']}/script")
    assert r.status_code == 422 and "pas encore validée" in r.json()["errors"][0]["message"]


# --- ancien mode ------------------------------------------------------------------------------------------------------
def test_a_chapter_without_scenes_is_written_and_directed_in_one_generation(c: TestClient) -> None:
    s = _ok(c.post("/projects", json={**STYLE, "title": "Ancien"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"synopsis": SYNOPSIS, "target_page_count": 5}), 201)
    _ok(c.post(f"/chapters/{ch['id']}/stages/scenes/override", json={"author": "Ouro", "note": "sans scènes"}))
    job = _script(c, ch)
    assert job["status"] == "succeeded" and "scène par scène" not in job["message"]
    assert len(_tasks(c, "script")) == 1
    user = next(m.content for m in _tasks(c, "script")[0] if m.role == "user")
    assert "SCÈNE À ÉCRIRE" not in user
    job = _direct(c, ch)
    assert job["status"] == "succeeded" and "scène par scène" not in job["message"]
    first = [call for call in _tasks(c, "art_direction") if not any(m.role == "assistant" for m in call)]
    assert len(first) == 1
    assert "(chapitre dirigé d'un seul tenant" in next(m.content for m in first[0] if m.role == "user")
    data = _ok(c.get(f"/chapters/{ch['id']}/scenes/measure"))
    assert data == {"chapter_id": ch["id"], "scene_mode": False, "scenes": []}
