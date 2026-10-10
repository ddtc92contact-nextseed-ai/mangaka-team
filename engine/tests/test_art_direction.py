"""Direction artistique : schéma et relances, verrous, effet sur la mise en page et le prompt image,
isolation par série, mock déterministe."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.art_direction import (
    ArtDirectionError,
    DirectionContext,
    DirectionValidationError,
    PageBrief,
    merge_locked,
    parse_direction,
    render_messages,
    run_direction,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm import LLMAuthError, MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_art_direction
from tests.conftest import PRESETS_DIR, STYLE

PRESETS = PresetRegistry.load(PRESETS_DIR)
PROMPT = PRESETS.prompt("direction-artistique")


def _brief(number: int, panels: int, templates: list[str] | None = None) -> PageBrief:
    return PageBrief(
        page_id=number * 10,
        number=number,
        rythme=None,
        panels=[
            {
                "panel_id": number * 10 + i,
                "description": f"Case {i + 1}",
                "characters": ["Aiko"],
                "shot_type": "plan moyen",
                "importance": 3 if i == 0 else 2,
                "intensity": None,
                "dialogue_chars": 20,
                "dialogues": [],
            }
            for i in range(panels)
        ],
        templates=templates if templates is not None else [f"{panels}-grand-haut", f"{panels}-bandes"],
    )


def _ctx(pages: list[PageBrief] | None = None, **kw: Any) -> DirectionContext:
    return DirectionContext(
        series={
            "title": "Les Lames de Kyoto",
            "style": "encre",
            "reading_direction": "rtl",
            "layout_style": "dynamique",
            "layout_style_name": "Dynamique",
            "layout_style_description": "",
        },
        characters=[{"name": "Aiko", "description": "rônin"}],
        chapter={"number": 2, "title": "La pluie", "synopsis": "Aiko poursuit le voleur.", "summary": ""},
        pages=pages or [_brief(1, 3), _brief(2, 2)],
        styles=[{"id": s, "name": s, "description": ""} for s in ("sage", "dynamique", "nerveuse")],
        previous=kw.pop("previous", None),
        variety=kw.pop("variety", "equilibree"),
        **kw,
    )


def _valid(ctx: DirectionContext) -> dict[str, Any]:
    return mock_art_direction(ctx.as_json())


# --- schéma et relances ---------------------------------------------------------------
def test_valid_answer_is_parsed_and_normalized() -> None:
    ctx = _ctx()
    data = _valid(ctx)
    data["pages"][0]["rythme"] = "Montee"
    data["pages"][0]["panels"][0]["plan"] = "Gros Plan"
    data["pages"][0]["panels"][0]["angle"] = "trois quarts"
    data["pages"][0]["page_choc"] = "aucun"
    out = parse_direction("```json\n" + json.dumps(data, ensure_ascii=False) + "\n```", ctx)
    p = out.pages[0]
    assert p.rythme == "montée" and p.page_choc is None
    assert p.panels[0].plan == "gros plan" and p.panels[0].angle == "de trois quarts"


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda d: d["pages"][0].update(rythme="tempête"), "rythme"),
        (lambda d: d["pages"][0]["panels"][0].update(plan="drone"), "plan"),
        (lambda d: d["pages"][0]["panels"].pop(), "cases 1 à 3"),
        (lambda d: d["pages"].pop(), "pages manquantes : 2"),
        (lambda d: d["pages"][0].update(template="9-grille"), "template"),
        (lambda d: d["pages"][0].update(layout_style="baroque"), "layout_style"),
        (lambda d: d["pages"][0].update(rationale=""), "rationale"),
        (lambda d: d["pages"][1].update(page=7), "n'existe pas"),
    ],
)
def test_invalid_answers_are_explained(mutate: Callable[[dict], Any], needle: str) -> None:
    ctx = _ctx()
    data = _valid(ctx)
    mutate(data)
    with pytest.raises(DirectionValidationError, match=needle):
        parse_direction(json.dumps(data, ensure_ascii=False), ctx)


def test_two_invalid_answers_then_success() -> None:
    llm = MockLLMProvider(invalid_attempts=2)
    steps: list[str] = []
    run = run_direction(llm, PROMPT, _ctx(), lambda _p, m: steps.append(m))
    assert run.attempts == 3 and len(llm.calls) == 3
    # l'erreur de validation est renvoyée au LLM
    assert llm.calls[2][-1].role == "user" and "invalide" in llm.calls[2][-1].content
    assert any("nouvel essai" in s for s in steps)


def test_three_invalid_answers_give_a_readable_error() -> None:
    with pytest.raises(ArtDirectionError, match="invalide 3 fois de suite"):
        run_direction(MockLLMProvider(invalid_attempts=3), PROMPT, _ctx(), lambda *_: None)


def test_non_retryable_llm_error_stops_immediately() -> None:
    class Refused(MockLLMProvider):
        def complete(self, messages, **kw):  # type: ignore[no-untyped-def, override]
            self.calls.append(messages)
            raise LLMAuthError("clé refusée")

    llm = Refused()
    with pytest.raises(ArtDirectionError, match="clé refusée"):
        run_direction(llm, PROMPT, _ctx(), lambda *_: None)
    assert len(llm.calls) == 1


def test_prompt_renders_every_input() -> None:
    ctx = _ctx(
        previous={
            "chapter": 1,
            "pages": [{"page": 2, "rythme": "climax", "page_choc": "splash"}],
            "plans": {"gros plan": 4},
            "angles": {},
        }
    )
    system, user = render_messages(PROMPT, ctx)
    assert "directeur artistique" in system.content
    assert "Dynamique (dynamique)" in user.content  # style de la série
    assert "page 2 (splash)" in user.content  # chapitre précédent
    assert "Case 1 (importance 3)" in user.content and "Aiko : rônin" in user.content
    assert "équilibrée" in user.content and '"task": "art_direction"' in user.content


# --- mock ---------------------------------------------------------------------------------
def test_mock_is_deterministic_and_varied() -> None:
    pages = [_brief(n, 1 + n % 5) for n in range(1, 9)]
    ctx = _ctx(pages)
    a, b = mock_art_direction(ctx.as_json()), mock_art_direction(ctx.as_json())
    assert a == b
    parse_direction(json.dumps(a, ensure_ascii=False), ctx)  # toujours valide
    assert len({p["rythme"] for p in a["pages"]}) >= 3
    assert len({pa["plan"] for p in a["pages"] for pa in p["panels"]}) >= 3
    assert len({pa["angle"] for p in a["pages"] for pa in p["panels"]}) >= 3
    assert any(p["page_choc"] for p in a["pages"])
    # « Proposer autre chose » (relance) et audace changent les choix
    assert mock_art_direction(_ctx(pages, variant=1).as_json()) != a
    sober = mock_art_direction(_ctx(pages, variety="sobre").as_json())
    bold = mock_art_direction(_ctx(pages, variety="audacieuse").as_json())
    count = lambda d: sum(pa["intensity"] == "choc" for p in d["pages"] for pa in p["panels"])  # noqa: E731
    assert count(bold) > count(sober)
    assert not any(p["page_choc"] for p in sober["pages"])


def test_merge_keeps_locked_fields() -> None:
    old = {"rythme": "calme", "panels": [{"panel_id": 5, "plan": "gros plan", "intensity": "choc"}]}
    new = {"rythme": "climax", "panels": [{"panel_id": 5, "plan": "plan large", "intensity": "calme"}]}
    merged = merge_locked(copy.deepcopy(new), old, ["rythme", "5.plan"])
    assert merged["rythme"] == "calme"
    assert merged["panels"][0] == {"panel_id": 5, "plan": "gros plan", "intensity": "calme"}


# --- API ---------------------------------------------------------------------------------
@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


def _wait(c: TestClient, job: dict) -> dict:
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    return c.get(f"/jobs/{job['id']}").json()


def _series(c: TestClient, title: str = "Série DA", **kw: Any) -> int:
    r = c.post("/projects", json={**STYLE, "title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _scripted_chapter(c: TestClient, sid: int, pages: int = 4) -> int:
    ch = c.post(
        f"/projects/{sid}/chapters",
        json={"synopsis": "Un duel sous la pluie. Le rival frappe.", "target_page_count": pages},
    ).json()
    assert _wait(c, c.post(f"/chapters/{ch['id']}/script").json())["status"] == "succeeded"
    return ch["id"]


def _direct(c: TestClient, chapter_id: int, page_id: int | None = None) -> dict:
    body = {"page_id": page_id} if page_id else {}
    r = c.post(f"/chapters/{chapter_id}/direction", json=body)
    assert r.status_code == 202, r.text
    job = _wait(c, r.json())
    assert job["status"] == "succeeded", job
    return c.get(f"/chapters/{chapter_id}/direction").json()


def _panel_edit(c: TestClient, page_id: int, **fields: Any) -> dict:
    r = c.patch(f"/pages/{page_id}/direction", json=fields)
    assert r.status_code == 200, r.text
    return r.json()


def test_run_edit_rerun_keeps_locked_fields(c: TestClient) -> None:
    sid = _series(c)
    chapter_id = _scripted_chapter(c, sid)
    assert c.get(f"/chapters/{chapter_id}/direction").json()["pages"][0]["has_direction"] is False
    data = _direct(c, chapter_id)
    pages = data["pages"]
    assert len(pages) == 4 and all(p["has_direction"] and p["rationale"] for p in pages)
    assert data["variety"] == "equilibree" and "plan large" in data["options"]["plans"]
    first = pages[0]
    target = first["panels"][1]
    edited = _panel_edit(
        c,
        first["page_id"],
        page={"rythme": "climax"},
        panels=[{"panel_id": target["panel_id"], "plan": "gros plan", "intensity": "choc"}],
    )
    assert set(edited["locks"]) == {"rythme", f"{target['panel_id']}.plan", f"{target['panel_id']}.intensity"}

    # Nouvelle proposition pour toute la page : les champs verrouillés survivent, le reste change.
    again = next(p for p in _direct(c, chapter_id, first["page_id"])["pages"] if p["page_id"] == first["page_id"])
    assert again["variant"] == 1 and again["rythme"] == "climax"
    p2 = next(pa for pa in again["panels"] if pa["panel_id"] == target["panel_id"])
    assert p2["plan"] == "gros plan" and p2["intensity"] == "choc"
    assert again["panels"] != first["panels"] or again["rationale"] != first["rationale"]

    # Tout le chapitre : idem ; une page acceptée n'est pas remplacée.
    _panel_edit(c, pages[1]["page_id"], accept=True)
    whole = _direct(c, chapter_id)["pages"]
    assert whole[0]["rythme"] == "climax"
    assert whole[1]["status"] == "accepted" and whole[1]["panels"] == pages[1]["panels"]

    # Déverrouiller : la proposition suivante peut le changer.
    unlocked = _panel_edit(c, first["page_id"], unlock=["rythme"])
    assert "rythme" not in unlocked["locks"]

    # Valeurs refusées
    bad = c.patch(
        f"/pages/{first['page_id']}/direction", json={"panels": [{"panel_id": target["panel_id"], "plan": "drone"}]}
    )
    assert bad.status_code == 422
    bad = c.patch(f"/pages/{first['page_id']}/direction", json={"page": {"template": "9-grille"}})
    assert bad.status_code == 422 and "impossible" in bad.text


def test_invalid_answers_end_in_a_visible_job_error(c: TestClient) -> None:
    sid = _series(c)
    ch = c.post(
        f"/projects/{sid}/chapters", json={"synopsis": "Un duel. [mock:da-invalide:3]", "target_page_count": 2}
    ).json()
    assert _wait(c, c.post(f"/chapters/{ch['id']}/script").json())["status"] == "succeeded"
    job = _wait(c, c.post(f"/chapters/{ch['id']}/direction", json={}).json())
    assert job["status"] == "failed" and "invalide 3 fois de suite" in job["error"]
    # deux réponses invalides puis une bonne : le job réussit
    c.patch(f"/chapters/{ch['id']}", json={"synopsis": "Un duel. [mock:da-invalide:2]"})
    job = _wait(c, c.post(f"/chapters/{ch['id']}/direction", json={}).json())
    assert job["status"] == "succeeded" and "3 essais" in job["message"]


def test_nothing_to_direct_and_unknown_page(c: TestClient) -> None:
    sid = _series(c)
    ch = c.post(f"/projects/{sid}/chapters", json={"synopsis": "x"}).json()
    assert c.post(f"/chapters/{ch['id']}/direction", json={}).status_code == 422
    chapter_id = _scripted_chapter(c, sid, pages=1)
    assert c.post(f"/chapters/{chapter_id}/direction", json={"page_id": 99999}).status_code == 422
    assert c.post(f"/chapters/{chapter_id}/direction/apply", json={}).status_code == 422


def _three_panel_page(c: TestClient, layout_style: str, **series: Any) -> tuple[int, dict]:
    """Une page de trois cases d'importance égale, sans indice de mise en scène."""
    sid = _series(c, layout_style=layout_style, **series)
    chapter_id = _scripted_chapter(c, sid, pages=1)
    panel = {
        "description": "Aiko court.",
        "characters": [],
        "shot_type": "plan moyen",
        "importance": 2,
        "dialogues": [],
    }
    r = c.put(f"/chapters/{chapter_id}/pages", json={"pages": [{"kind": "story", "panels": [panel] * 3}]})
    assert r.status_code == 200, r.text
    return chapter_id, r.json()[0]


def _area(poly: list[list[float]]) -> float:
    return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))) / 2


@pytest.mark.parametrize("style", ["dynamique", "nerveuse"])
def test_choc_panel_gets_large_area_and_slant_after_apply(c: TestClient, style: str) -> None:
    chapter_id, page = _three_panel_page(c, style)
    before = page["layout"]
    data = _direct(c, chapter_id)
    d = data["pages"][0]
    ids = [pa["panel_id"] for pa in d["panels"]]
    _panel_edit(
        c,
        page["id"],
        page={"rythme": "montée", "template": None, "page_choc": None, "layout_style": None},
        panels=[{"panel_id": ids[0], "plan": "gros plan", "intensity": "choc"}]
        + [{"panel_id": i, "intensity": "normal"} for i in ids[1:]],
    )
    r = c.post(f"/chapters/{chapter_id}/direction/apply", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["applied"] == [1] and out["relaid"] == [1]
    after = out["pages"][0]
    assert after["panels"][0]["intensity"] == "choc" and after["rythme"] == "normal"
    lay = after["layout"]
    assert lay != before
    areas = [_area(p["polygon"]) for p in lay["panels"]]
    assert areas[0] == max(areas) and areas[0] > 1.3 * min(areas)  # la case choc est la plus grande
    first = next(p for p in lay["panels"] if p["panel_id"] == ids[0])
    assert first["slanted"]  # la découpe voisine passe en biais (probabilité du style)
    # Rien n'a changé : rien n'est recalculé.
    again = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()
    assert again["relaid"] == [] and again["pages"][0]["layout"] == lay


def test_template_hint_and_page_choc_drive_the_layout(c: TestClient) -> None:
    chapter_id, page = _three_panel_page(c, "dynamique")
    d = _direct(c, chapter_id)["pages"][0]
    ids = [pa["panel_id"] for pa in d["panels"]]
    _panel_edit(
        c,
        page["id"],
        page={"template": "3-grand-bas", "page_choc": "splash"},
        panels=[{"panel_id": i, "intensity": "normal"} for i in ids],
    )
    lay = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()["pages"][0]["layout"]
    assert lay["template_id"] == "3-grand-bas" and lay["style"]["page_choc"] is True
    # « Nouvelle mise en page » écarte le gabarit suggéré
    rerolled = c.post(f"/pages/{page['id']}/layout", json={"reroll": True}).json()
    assert rerolled["layout"]["template_id"] != "3-grand-bas"


def test_image_prompt_gets_plan_angle_and_ambiance(c: TestClient) -> None:
    chapter_id, page = _three_panel_page(c, "sage", ai_prompt=False)  # prompt par fragments
    d = _direct(c, chapter_id)["pages"][0]
    pid = d["panels"][0]["panel_id"]
    _panel_edit(
        c,
        page["id"],
        panels=[{"panel_id": pid, "plan": "contre-plongée", "angle": "de profil", "ambiance": "pluie, néons"}],
    )
    # Pas encore appliquée : le prompt garde le plan du scénario.
    prompt = c.post(f"/panels/{pid}/prompt/rebuild").json()["final_prompt"]
    assert prompt.startswith("Plan moyen.") and "de profil" not in prompt
    c.post(f"/chapters/{chapter_id}/direction/apply", json={})
    prompt = c.post(f"/panels/{pid}/prompt/rebuild").json()["final_prompt"]
    assert prompt.startswith("Contre-plongée. Angle de caméra : de profil.")
    assert "Ambiance : pluie, néons." in prompt


def test_scenario_change_marks_direction_out_of_date(c: TestClient) -> None:
    chapter_id, page = _three_panel_page(c, "sage")
    _direct(c, chapter_id)
    pages = c.get(f"/chapters/{chapter_id}/pages").json()
    body = {
        "pages": [
            {
                "id": pages[0]["id"],
                "kind": "story",
                "panels": [
                    {k: pa[k] for k in ("id", "description", "characters", "shot_type", "importance", "dialogues")}
                    for pa in pages[0]["panels"][:2]
                ],
            }
        ]
    }
    assert c.put(f"/chapters/{chapter_id}/pages", json=body).status_code == 200
    d = c.get(f"/chapters/{chapter_id}/direction").json()["pages"][0]
    assert d["out_of_date"] is True
    out = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()
    assert out["applied"] == [] and "relance" in out["skipped"][0]["reason"]


def test_series_isolation_of_previous_direction_and_settings(c: TestClient) -> None:
    a, b = _series(c, "Série A"), _series(c, "Série B")
    a1 = _scripted_chapter(c, a, pages=2)
    _direct(c, a1)
    _scripted_chapter(c, b, pages=2)  # chapitre 1 de B : pas de direction artistique
    b2 = _scripted_chapter(c, b, pages=2)
    a2 = _scripted_chapter(c, a, pages=2)
    llm = c.app.state.ctx.providers.llm  # type: ignore[attr-defined]

    def last_context() -> dict:
        user = next(m.content for m in llm.calls[-1] if m.role == "user")
        return json.loads(user.split("<contexte>")[1].split("</contexte>")[0])

    _direct(c, b2)
    assert last_context()["previous_direction"] is None  # la série A n'est jamais lue
    _direct(c, a2)
    prev = last_context()["previous_direction"]
    assert prev is not None and prev["chapter"] == 1 and len(prev["pages"]) == 2

    # Audace réglée pour la série A seulement (écran « L'équipe »)
    r = c.put(f"/agents/directeur-artistique/profile?project_id={a}", json={"values": {"variety": "audacieuse"}})
    assert r.status_code == 200, r.text
    assert c.get(f"/chapters/{a2}/direction").json()["variety"] == "audacieuse"
    assert c.get(f"/chapters/{b2}/direction").json()["variety"] == "equilibree"
    _direct(c, b2)
    assert last_context()["variety"] == "equilibree"
    _direct(c, a2)
    assert last_context()["variety"] == "audacieuse"


def test_cadre_and_sfx_go_to_frames_and_lettering(c: TestClient) -> None:
    """Le cadre devient une option de cadre de la case, les onomatopées des sfx du lettrage (#28)."""
    chapter_id, page = _three_panel_page(c, "sage")
    ids = [pa["panel_id"] for pa in _direct(c, chapter_id)["pages"][0]["panels"]]
    _panel_edit(
        c,
        page["id"],
        page={"rythme": "montée", "template": None, "page_choc": None, "layout_style": None},
        panels=[
            {"panel_id": ids[0], "cadre": "fond perdu", "sfx": [{"text": "VROUM !", "intensity": "fort"}]},
            {"panel_id": ids[1], "cadre": "sans bord", "sfx": []},
            {"panel_id": ids[2], "cadre": "incrustation", "sfx": [{"text": "bip", "intensity": "léger"}]},
        ],
    )
    out = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()
    p = out["pages"][0]
    assert [pa["frame"] for pa in p["panels"]] == [
        {"frame": None, "bleed": True, "inset": None},
        {"frame": "none", "bleed": None, "inset": None},
        {"frame": None, "bleed": None, "inset": True},
    ]
    assert [[(s["text"], s["intensity"]) for s in pa["sfx"]] for pa in p["panels"]] == [
        [("VROUM !", "choc")],
        [],
        [("bip", "calme")],
    ]
    lay = p["layout"]["panels"]
    assert lay[0]["bleed"] and lay[1]["frame"] == "none" and lay[2]["inset"] and not p["layout_stale"]
    # l'auteur impose un fondu à la case 2 ; la DA repasse en « normal » partout
    c.put(f"/panels/{ids[1]}/frame", json={"frame": "fade"})
    _panel_edit(c, page["id"], panels=[{"panel_id": i, "cadre": "normal", "sfx": []} for i in ids])
    p = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()["pages"][0]
    assert [pa["frame"] for pa in p["panels"]] == [None, {"frame": "fade", "bleed": None, "inset": None}, None]
    assert all(pa["sfx"] == [] for pa in p["panels"])  # onomatopées de la DA retirées
