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
from mangaka_engine.pipeline import art_direction as da
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
from mangaka_engine.pipeline.generation import build_panel_prompt, panel_framing, panel_plan
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm import LLMAuthError, MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_art_direction
from mangaka_engine.store.models import Page, PageDirection, Panel
from tests.conftest import LEAD, PRESETS_DIR, STYLE, force_stages

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

    # Tout le chapitre : idem ; une page validée (donc appliquée) n'est pas remplacée.
    _panel_edit(c, pages[1]["page_id"], accept=True)
    whole = _direct(c, chapter_id)["pages"]
    assert whole[0]["rythme"] == "climax"
    assert whole[1]["status"] == "applied" and whole[1]["panels"] == pages[1]["panels"]

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
        panels=[
            {
                "panel_id": pid,
                "plan": "contre-plongée",
                "angle": "de profil",
                "ambiance": "pluie, néons",
                "action": "Aiko saute par-dessus la rambarde",
            }
        ],
    )
    # Pas encore appliquée : le prompt garde le plan du scénario (traduit : camera_terms).
    prompt = c.post(f"/panels/{pid}/prompt/rebuild").json()["final_prompt"]
    assert (
        prompt.startswith(f"{LEAD}Medium shot, framed from the waist up, legs out of frame.")
        and "side profile" not in prompt
    )
    c.post(f"/chapters/{chapter_id}/direction/apply", json={})
    prompt = c.post(f"/panels/{pid}/prompt/rebuild").json()["final_prompt"]
    assert prompt.startswith(f"{LEAD}Low-angle shot. Camera angle: side profile view.")
    assert "Mood and lighting: pluie, néons." in prompt
    assert "Action and pose: Aiko saute par-dessus la rambarde." in prompt


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
            {
                "panel_id": ids[0],
                "intensity": "choc",
                "cadre": "débordement",
                "sfx": [{"text": "VROUM !", "intensity": "fort"}],
            },
            {"panel_id": ids[1], "cadre": "sans bord", "sfx": []},
            {"panel_id": ids[2], "cadre": "incrustation", "sfx": [{"text": "bip", "intensity": "léger"}]},
        ],
    )
    out = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()
    p = out["pages"][0]
    assert [pa["frame"] for pa in p["panels"]] == [
        {"frame": None, "break_out": True, "inset": None},
        {"frame": "none", "break_out": None, "inset": None},
        {"frame": None, "break_out": None, "inset": True},
    ]
    assert [[(s["text"], s["intensity"]) for s in pa["sfx"]] for pa in p["panels"]] == [
        [("VROUM !", "choc")],
        [],
        [("bip", "calme")],
    ]
    lay = p["layout"]["panels"]
    assert lay[0]["break_out"] and lay[1]["frame"] == "none" and lay[2]["inset"] and not p["layout_stale"]
    # l'auteur impose un fondu à la case 2 ; la DA repasse en « normal » partout
    c.put(f"/panels/{ids[1]}/frame", json={"frame": "fade"})
    _panel_edit(c, page["id"], panels=[{"panel_id": i, "cadre": "normal", "sfx": []} for i in ids])
    p = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()["pages"][0]
    assert [pa["frame"] for pa in p["panels"]] == [None, {"frame": "fade", "break_out": None, "inset": None}, None]
    assert all(pa["sfx"] == [] for pa in p["panels"])  # onomatopées de la DA retirées


def test_break_out_only_on_choc_panel_or_page_choc(c: TestClient) -> None:
    """La DA ne fait déborder une case sur ses voisines que sur une case choc ou une page choc (#88) ;
    l'ancien cadre « fond perdu » est lu comme un débordement, jamais comme un passage de la marge."""
    chapter_id, page = _three_panel_page(c, "sage")
    ids = [pa["panel_id"] for pa in _direct(c, chapter_id)["pages"][0]["panels"]]
    _panel_edit(
        c,
        page["id"],
        page={"rythme": "montée", "template": None, "page_choc": None, "layout_style": None},
        panels=[
            {"panel_id": ids[0], "intensity": "normal", "cadre": "fond perdu", "sfx": []},
            {"panel_id": ids[1], "intensity": "calme", "cadre": "débordement", "sfx": []},
            {"panel_id": ids[2], "intensity": "normal", "cadre": "normal", "sfx": []},
        ],
    )
    p = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()["pages"][0]
    assert [pa["frame"] for pa in p["panels"]] == [None, None, None]
    assert not any(lp.get("break_out") for lp in p["layout"]["panels"])
    # page choc : le débordement proposé est posé
    _panel_edit(c, page["id"], page={"rythme": "climax", "template": None, "page_choc": "splash", "layout_style": None})
    p = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()["pages"][0]
    assert [bool((pa["frame"] or {}).get("break_out")) for pa in p["panels"]] == [True, True, False]
    live = p["layout"]["live_area"]
    for lp in p["layout"]["panels"]:
        assert live["x1"] <= lp["x1"] and lp["x2"] <= live["x2"] and live["y1"] <= lp["y1"] and lp["y2"] <= live["y2"]


# --- mise en scène variée (variety_rules) ----------------------------------------------------
RULES = PROMPT.variety_rules


def _pa(plan: str, angle: str, action: str = "Aiko bondit par-dessus la rambarde") -> dict[str, str]:
    return {"plan": plan, "angle": angle, "action": action}


def test_variety_rules_live_in_the_preset() -> None:
    assert RULES is not None
    assert (RULES.max_same_plan_in_a_row, RULES.max_same_angle_in_a_row, RULES.max_frontal_share) == (2, 2, 0.35)
    assert "regarde" in RULES.weak_actions and RULES.require_action


def test_variety_flags_repeats_frontal_share_eye_level_and_actions() -> None:
    assert RULES is not None
    ok = [_pa("plan large", "de trois quarts"), _pa("gros plan", "en contre-plongée"), _pa("plan rapproché", "de face")]
    assert da.check_variety([(1, ok)], RULES) == ({}, [])
    by_page, chapter = da.check_variety(
        [
            (1, [_pa("gros plan", "de face"), _pa("gros plan", "de face"), _pa("gros plan", "de face")]),
            (
                2,
                [
                    _pa("plan moyen", "de profil"),
                    _pa("plan large", "de dos", ""),
                    _pa("insert", "de profil", "Aiko regarde Kenji"),
                ],
            ),
        ],
        RULES,
    )
    page1, page2 = " | ".join(by_page[1]), " | ".join(by_page[2])
    assert "cases 1 à 3 au même plan « gros plan »" in page1 and "cases 1 à 3 au même angle « de face »" in page1
    assert "aucune case hors hauteur d'œil" in page1 and "aucune case hors hauteur d'œil" in page2
    assert "case 2 › action : vide" in page2 and "case 3 › action : « Aiko regarde Kenji » trop statique" in page2
    # 3 cases de face sur 6 : 2 au plus (35 %)
    assert chapter == ["trop de cases de face : 3 sur 6 (2 au plus, 35 %) : varie les angles"]
    # une page d'une case : pas d'exigence d'angle ; une longue action avec « regarde » reste une action
    single = [_pa("plan large", "de trois quarts", "Aiko regarde derrière elle en courant, le manteau au vent")]
    assert da.check_variety([(1, single)], RULES) == ({}, [])


def _repetitive(ctx: DirectionContext) -> str:
    data = _valid(ctx)
    for page in data["pages"]:
        for pa in page["panels"]:
            pa.update(plan="plan moyen", angle="de face", action="")
    return json.dumps(data, ensure_ascii=False)


def test_variety_violation_is_retried_with_a_readable_error() -> None:
    ctx = _ctx(rules=RULES)
    answers = iter([_repetitive(ctx), json.dumps(_valid(ctx), ensure_ascii=False)])
    llm = MockLLMProvider(lambda _m, _j: next(answers))
    run = run_direction(llm, PROMPT, ctx, lambda *_: None)
    assert run.attempts == 2 and run.variety == []
    retry = llm.calls[1][-1].content
    assert "mise en scène trop répétitive" in retry and "au même plan « plan moyen »" in retry
    assert "action : vide" in retry


def test_variety_violation_after_the_retries_is_kept_with_warnings() -> None:
    ctx = _ctx(rules=RULES)
    llm = MockLLMProvider(lambda _m, _j: _repetitive(ctx))
    run = run_direction(llm, PROMPT, ctx, lambda *_: None)
    assert run.attempts == 3 and len(llm.calls) == 3
    assert any("au même angle « de face »" in v for v in run.variety)


def test_mock_direction_respects_the_variety_rules() -> None:
    pages = [_brief(n, 1 + n % 6) for n in range(1, 11)]
    for variety in ("sobre", "equilibree", "audacieuse"):
        for variant in (0, 1, 2):
            out = parse_direction(json.dumps(_valid(_ctx(pages, variety=variety, variant=variant))), _ctx(pages))
            assert da.output_variety(out, RULES) == [], (variety, variant)
            assert all(pa.action for p in out.pages for pa in p.panels)


def test_action_and_warnings_through_the_api(c: TestClient) -> None:
    sid = _series(c)
    chapter_id = _scripted_chapter(c, sid, pages=2)
    data = _direct(c, chapter_id)
    page = data["pages"][0]
    assert all(pa["action"] for pa in page["panels"]) and page["warnings"] == []
    ids = [pa["panel_id"] for pa in page["panels"]]
    assert len(ids) >= 3
    # l'auteur impose trois gros plans de face d'affilée : avertissement visible, action verrouillée
    edited = _panel_edit(
        c,
        page["page_id"],
        panels=[{"panel_id": i, "plan": "gros plan", "angle": "de face"} for i in ids[:3]]
        + [{"panel_id": ids[0], "action": "Aiko regarde"}],
    )
    warnings = " | ".join(edited["warnings"])
    assert "cases 1 à 3 au même plan « gros plan »" in warnings and "« Aiko regarde » trop statique" in warnings
    assert f"{ids[0]}.action" in edited["locks"]
    assert next(pa for pa in edited["panels"] if pa["panel_id"] == ids[0])["action"] == "Aiko regarde"


# --- échelle des plans : plans larges et moyens, plans serrés -------------------------------------
def _plans(*plans: str) -> list[dict[str, str]]:
    angles = ["de trois quarts", "en contre-plongée", "de profil", "en plongée", "de dos", "cadre penché"]
    return [_pa(p, angles[i % len(angles)]) for i, p in enumerate(plans)]


def test_wide_and_medium_share_is_capped_on_the_chapter() -> None:
    assert RULES is not None and RULES.max_wide_medium_share == 0.5
    ok = [(1, _plans("plan large", "gros plan", "plan moyen", "insert")), (2, _plans("plan rapproché", "plan moyen"))]
    assert da.check_variety(ok, RULES) == ({}, [])
    loose = [(1, _plans("plan large", "gros plan", "plan moyen", "plan moyen")), (2, _plans("plan moyen", "insert"))]
    by_page, chapter = da.check_variety(loose, RULES)
    assert by_page == {}
    assert chapter == [
        "trop de plans larges et moyens (plan large / plan d'ensemble / plan moyen) : 4 sur 6 "
        "(3 au plus, 50 %) : resserre sur les visages, les gestes et les objets"
    ]
    # seuil du preset : 70 % permis
    assert da.check_variety(loose, RULES.model_copy(update={"max_wide_medium_share": 0.7})) == ({}, [])


def test_every_page_of_three_panels_needs_a_tight_shot() -> None:
    assert RULES is not None and (RULES.min_tight_per_page, RULES.tight_min_panels) == (1, 3)
    for tight in ("gros plan", "très gros plan", "plan rapproché", "insert"):
        assert da.check_variety([(1, _plans("plan large", tight, "contre-plongée"))], RULES) == ({}, [])
    page = _plans("plan large", "contre-plongée", "plan moyen")
    by_page, _ = da.check_variety([(1, page), (2, _plans("plan moyen", "plongée"))], RULES)
    assert list(by_page) == [1]  # deux cases : pas d'exigence
    assert by_page[1] == [
        "aucun plan serré (au moins 1 dès 3 cases : gros plan, très gros plan, plan rapproché, insert) : "
        "serre le cadre sur l'émotion, la révélation ou la réplique clé"
    ]
    two = RULES.model_copy(update={"min_tight_per_page": 2})
    by_page, _ = da.check_variety([(1, _plans("gros plan", "plan large", "plongée"))], two)
    assert by_page[1][0].startswith("1 plan serré seulement (au moins 2 dès 3 cases")
    off = RULES.model_copy(update={"min_tight_per_page": 0, "max_wide_medium_share": 1})
    assert da.check_variety([(1, page)], off) == ({}, [])


def test_no_two_wide_shots_in_a_row() -> None:
    assert RULES is not None and RULES.max_wide_in_a_row == 1
    ok = _plans("plan large", "gros plan", "plan large", "insert")
    assert da.check_variety([(1, ok)], RULES) == ({}, [])
    by_page, _ = da.check_variety([(1, _plans("gros plan", "plan large", "plan d'ensemble", "insert"))], RULES)
    assert by_page[1] == ["cases 2 à 3 en plan large d'affilée (1 au plus : intercale un plan plus serré)"]
    two = RULES.model_copy(update={"max_wide_in_a_row": 2, "max_wide_medium_share": 1})
    assert da.check_variety([(1, _plans("gros plan", "plan large", "plan d'ensemble", "insert"))], two) == ({}, [])


def test_new_rules_are_in_the_prompt_and_retried() -> None:
    assert RULES is not None
    text = da.variety_text(RULES)
    assert "au plus 50 % des cases du chapitre en plan large / plan d'ensemble / plan moyen" in text
    assert "au moins 1 plan serré par page (dès 3 cases)" in text and "jamais plus de 1 case d'affilée" in text
    assert "serres le cadre" in PROMPT.system and "plan large pour installer un lieu" in PROMPT.system
    ctx = _ctx(rules=RULES)
    wide = _valid(ctx)
    for page in wide["pages"]:
        for i, pa in enumerate(page["panels"]):
            pa["plan"] = ("plan large", "plan moyen", "plongée")[i % 3]
    answers = iter([json.dumps(wide, ensure_ascii=False), json.dumps(_valid(ctx), ensure_ascii=False)])
    llm = MockLLMProvider(lambda _m, _j: next(answers))
    run = run_direction(llm, PROMPT, ctx, lambda *_: None)
    assert run.attempts == 2 and run.variety == []
    retry = llm.calls[1][-1].content
    assert "page 1 : aucun plan serré" in retry and "trop de plans larges et moyens" in retry


def test_page_query_is_built_from_the_page_scenario() -> None:
    page = _brief(1, 2)
    page.panels[0].update(description="Aiko pleure sous la pluie", staging="genoux à terre", characters=["Aiko"])
    page.panels[1]["dialogues"] = ["Kenji : Je ne partirai pas."]
    query = da.page_query(page)
    assert query.splitlines()[0] == "mise en scène, cadrage, dialogue, champ contrechamp, réplique, temps fort, impact"
    assert "Aiko pleure sous la pluie — genoux à terre — Aiko" in query and "Je ne partirai pas." in query
    assert "Kenji :" not in query


def test_art_direction_knowledge_is_retrieved_per_page(make_settings: Callable[..., Any]) -> None:
    with TestClient(create_app(make_settings(knowledge_packs=True))) as c:
        sid = _series(c)
        chapter_id = _scripted_chapter(c, sid, pages=2)
        _direct(c, chapter_id)
        llm = c.app.state.ctx.providers.llm  # type: ignore[attr-defined]
        user = next(m.content for m in llm.calls[-1] if m.role == "user")
        savoir_faire = user.split("Savoir-faire de l'équipe")[1].split("Direction artistique du chapitre")[0]
        assert "· page 1" in savoir_faire and "· page 2" in savoir_faire
        assert "Vocabulaire" not in savoir_faire and "Checklist" not in savoir_faire

        sources = c.get(f"/chapters/{chapter_id}/sources?agent=art_direction").json()
        assert sources["agent"] == "art_direction" and sources["passages"]
        assert all(p["pages"] and p["mode"] == "retrieved" for p in sources["passages"])
        assert {n for p in sources["passages"] for n in p["pages"]} == {1, 2}
        pages = c.get(f"/chapters/{chapter_id}/pages").json()
        for number, line in enumerate(sources["query"].split("\nPage ")[:2], start=1):
            assert line.removeprefix("Page ").startswith(f"{number} : mise en scène, cadrage")
        first = next(p for p in pages if p["number"] == 1)["panels"][0]["description"]
        assert first and first in sources["query"].split("\nPage 2 : ")[0]
        assert not {"Mise en scène · Vocabulaire", "Mise en scène · Checklist"} & set(sources["collections"])


# --- la direction arrive dans les cases (plan, angle, statut) ------------------------------------
def _session(c: TestClient):  # type: ignore[no-untyped-def]
    return c.app.state.ctx.db.session_scope()  # type: ignore[attr-defined]


def _statuses(c: TestClient, chapter_id: int) -> list[str]:
    with _session(c) as session:
        return [
            d.status
            for d in session.query(PageDirection)
            .join(Page, Page.id == PageDirection.page_id)
            .filter(PageDirection.chapter_id == chapter_id)
            .order_by(Page.number)
        ]


def _store_proposal(c: TestClient, page_id: int, choices: list[dict[str, Any]]) -> None:
    """Une proposition déjà en base, restée « proposed » (comme les 18 du projet avant le correctif)."""
    with _session(c) as session:
        page = session.get(Page, page_id)
        assert page is not None
        panels = [
            {"panel_id": p.id, "intensity": "normal", "cadre": "normal", "ambiance": "", "action": "", "sfx": [], **ch}
            for p, ch in zip(page.panels, choices, strict=True)
        ]
        page.direction = PageDirection(
            chapter_id=page.chapter_id,
            project_id=page.chapter.project_id,
            values={"rythme": "montée", "rationale": "Un plan serré par page.", "panels": panels},
            locks=[],
            status="proposed",
        )
        session.commit()


def _pages_body(pages: list[dict], change: Callable[[dict], dict] = lambda pa: pa) -> dict:
    keys = ("id", "description", "characters", "shot_type", "importance", "dialogues")
    return {
        "pages": [
            {"id": p["id"], "kind": "story", "panels": [change({k: pa[k] for k in keys}) for pa in p["panels"]]}
            for p in pages
        ]
    }


def test_accepting_a_page_applies_the_plan_and_angle_of_each_panel(c: TestClient) -> None:
    sid = _series(c)
    chapter_id = _scripted_chapter(c, sid, pages=2)
    pages = _direct(c, chapter_id)["pages"]
    assert [p["status"] for p in pages] == ["proposed", "proposed"]
    first = pages[0]
    out = _panel_edit(c, first["page_id"], accept=True)
    assert out["status"] == "applied" and out["applied"] and not out["pending"]
    assert _statuses(c, chapter_id) == ["applied", "proposed"]
    scenario = {pa["id"]: pa for pa in c.get(f"/chapters/{chapter_id}/pages").json()[0]["panels"]}
    with _session(c) as session:
        for pa in first["panels"]:
            assert scenario[pa["panel_id"]]["shot_type"] == pa["plan"]  # plan inscrit = plan proposé
            panel = session.get(Panel, pa["panel_id"])
            applied = da.applied_panel_direction(panel)
            assert (applied["plan"], applied["angle"]) == (pa["plan"], pa["angle"])
            assert (applied["action"], applied["ambiance"]) == (pa["action"], pa["ambiance"])
            assert panel_plan(panel) == pa["plan"]
    detail = c.get(f"/panels/{first['panels'][0]['panel_id']}").json()
    assert detail["framing_source"] == "direction" and detail["framing_note"] is None
    assert (detail["framing_plan"], detail["framing_angle"]) == (
        first["panels"][0]["plan"],
        first["panels"][0]["angle"],
    )
    # Rejeter : plus appliquée, les cases reprennent le plan du scénario (aucun : le scénariste ne cadre plus).
    rejected = _panel_edit(c, first["page_id"], reject=True)
    assert rejected["status"] == "rejected" and not rejected["applied"]
    detail = c.get(f"/panels/{first['panels'][0]['panel_id']}").json()
    assert detail["framing_source"] == "none" and "rejetée" in detail["framing_note"]
    assert _panel_edit(c, first["page_id"], reject=False)["status"] == "proposed"


def test_case_133_close_up_proposed_by_the_direction_reaches_the_prompt(c: TestClient) -> None:
    """Ch.3, page 4 : la direction propose un gros plan sur le visage paniqué du trafiquant ; le scénario disait
    « plan moyen ». Lancer la génération applique la proposition : le prompt porte le gros plan."""
    chapter_id, page = _three_panel_page(c, "sage", ai_prompt=False)  # prompt par fragments
    face = "lumière rougeoyante du cratère montant sur le visage, sueur et yeux écarquillés"
    _store_proposal(
        c,
        page["id"],
        [
            {"plan": "contre-plongée", "angle": "de trois quarts", "action": "Aiko grimpe la pente, haletante"},
            {"plan": "plongée", "angle": "en plongée", "action": "le trafiquant recule vers le cratère"},
            {"plan": "gros plan", "angle": "de face", "ambiance": face, "action": "le trafiquant écarquille les yeux"},
        ],
    )
    case_133 = page["panels"][2]["id"]
    detail = c.get(f"/panels/{case_133}").json()
    assert detail["shot_type"] == "plan moyen" and detail["framing_source"] == "scenario"  # repli signalé
    assert "appliquée d'office" in detail["framing_note"]

    r = c.post(f"/panels/{case_133}/generate", json={})
    assert r.status_code == 202, r.text
    assert _statuses(c, chapter_id) == ["applied"]
    detail = c.get(f"/panels/{case_133}").json()
    assert detail["shot_type"] == "gros plan" and detail["framing_source"] == "direction"
    prompt = detail["final_prompt"]
    assert "close-up, the face fills the frame" in prompt.lower() and "medium shot" not in prompt.lower()
    assert f"Mood and lighting: {face}." in prompt
    with _session(c) as session:
        panel = session.get(Panel, case_133)
        assert panel_framing(panel) == ("gros plan", "de face")
        built = build_panel_prompt(PRESETS, panel, [])
        assert "close-up, the face fills the frame" in built.lower() and "medium shot" not in built.lower()
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]


def test_generation_applies_every_proposal_except_a_rejected_one(c: TestClient) -> None:
    sid = _series(c)
    chapter_id = _scripted_chapter(c, sid, pages=3)
    pages = _direct(c, chapter_id)["pages"]
    _panel_edit(c, pages[2]["page_id"], reject=True)
    # Garde d'étapes : deux pages encore proposées → refus ; passer outre l'étape garde l'application d'office.
    r = c.post(f"/chapters/{chapter_id}/generate", json={})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "stage.direction", r.text
    # Héros et Rival, inventés par le scénario factice, n'ont pas de fiche : références forcées aussi.
    force_stages(c, chapter_id, "direction", "references")
    r = c.post(f"/chapters/{chapter_id}/generate", json={})
    assert r.status_code == 202, r.text
    assert _statuses(c, chapter_id) == ["applied", "applied", "rejected"]  # plus aucune « proposed »
    first = pages[0]["panels"][0]
    detail = c.get(f"/panels/{first['panel_id']}").json()
    assert detail["framing_source"] == "direction" and detail["framing_plan"] == first["plan"]
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]
    # Nouvelle proposition de tout le chapitre : les pages appliquées restent, la page rejetée est reproposée.
    again = _direct(c, chapter_id)["pages"]
    assert [p["status"] for p in again] == ["applied", "applied", "proposed"]
    assert again[0]["panels"] == pages[0]["panels"]


def test_manual_plan_is_never_overwritten_by_a_new_proposal_or_application(c: TestClient) -> None:
    chapter_id, page = _three_panel_page(c, "sage")
    d = _direct(c, chapter_id)["pages"][0]
    _panel_edit(c, page["id"], accept=True)
    ids = [pa["panel_id"] for pa in d["panels"]]
    # Retouche dans l'écran Scénario (« très gros plan » : jamais proposé par la direction).
    pages = c.get(f"/chapters/{chapter_id}/pages").json()
    body = _pages_body(pages, lambda pa: {**pa, "shot_type": "très gros plan"} if pa["id"] == ids[0] else pa)
    assert c.put(f"/chapters/{chapter_id}/pages", json=body).status_code == 200
    now = c.get(f"/chapters/{chapter_id}/direction").json()["pages"][0]
    assert f"{ids[0]}.plan" in now["locks"] and now["panels"][0]["plan"] == "très gros plan" and not now["pending"]
    assert c.get(f"/panels/{ids[0]}").json()["framing_plan"] == "très gros plan"  # suivi tout de suite
    # Retouche dans l'écran Direction artistique.
    _panel_edit(c, page["id"], panels=[{"panel_id": ids[1], "plan": "insert"}])
    # Nouvelle proposition puis ré-application : les deux retouches restent.
    again = _direct(c, chapter_id, page["id"])["pages"][0]
    assert [again["panels"][0]["plan"], again["panels"][1]["plan"]] == ["très gros plan", "insert"]
    out = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()
    assert out["applied"] == [1]
    shots = [pa["shot_type"] for pa in out["pages"][0]["panels"]]
    assert shots[:2] == ["très gros plan", "insert"] and shots[2] == again["panels"][2]["plan"]
    with _session(c) as session:
        assert panel_plan(session.get(Panel, ids[0])) == "très gros plan"


def test_apply_on_an_existing_chapter_lands_the_stored_proposals(c: TestClient) -> None:
    """Rattrapage : des propositions restées « proposed » arrivent dans les cases sur « Appliquer la direction »,
    sans écraser une retouche de l'auteur ; une page rejetée est laissée de côté."""
    sid = _series(c)
    chapter_id = _scripted_chapter(c, sid, pages=3)
    pages = _direct(c, chapter_id)["pages"]
    touched = pages[0]["panels"][0]["panel_id"]
    _panel_edit(c, pages[0]["page_id"], panels=[{"panel_id": touched, "plan": "insert"}])
    _panel_edit(c, pages[2]["page_id"], reject=True)
    out = c.post(f"/chapters/{chapter_id}/direction/apply", json={}).json()
    assert out["applied"] == [1, 2] and out["skipped"] == [{"number": 3, "reason": "direction rejetée par l'auteur"}]
    assert _statuses(c, chapter_id) == ["applied", "applied", "rejected"]
    proposed = {pa["panel_id"]: pa["plan"] for p in pages[:2] for pa in p["panels"]} | {touched: "insert"}
    inscribed = {pa["id"]: pa["shot_type"] for p in out["pages"][:2] for pa in p["panels"]}
    assert inscribed == proposed
    # La page rejetée, demandée par son id : appliquée (choix explicite de l'auteur).
    out = c.post(f"/chapters/{chapter_id}/direction/apply", json={"page_ids": [pages[2]["page_id"]]}).json()
    assert out["applied"] == [3] and _statuses(c, chapter_id) == ["applied"] * 3
