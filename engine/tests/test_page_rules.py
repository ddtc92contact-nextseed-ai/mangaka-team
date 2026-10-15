"""Direction artistique : règles par planche (page_rules) — gros plan, case calme, compositions variées, chocs
d'affilée, sujet relégué au fond, case sans personnage — vérifiées après le LLM, une seule relance ciblée.

Fixture : la planche 3 du chapitre « vulcano » (audit du 13/10) — 4 cases « choc » sur 4, toutes composées
« X à gauche / Y à droite », aucun gros plan."""

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
from mangaka_engine.pipeline.art_direction import DirectionContext, PageBrief, run_direction
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm import LLMError, MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_art_direction
from mangaka_engine.store.models import Page, PageDirection
from tests.conftest import PRESETS_DIR, STYLE, start_script

PRESETS = PresetRegistry.load(PRESETS_DIR)
PROMPT = PRESETS.prompt("direction-artistique")
RULES = PROMPT.page_rules
VARIETY = PROMPT.variety_rules

# Planche 3 de « vulcano » (cases 127 à 130), telle que le scénario l'a écrite.
VULCANO_3 = [
    {
        "description": "Trafiquant 1 tire une rafale de mitraillette. Angus esquive en se baissant, les balles "
        "frappent la roche derrière lui.",
        "staging": "Trafiquant 1 au fond à droite, arme crachant du feu. Angus au premier plan à gauche, baissé.",
        "characters": ["Trafiquant 1", "Angus"],
    },
    {
        "description": "Angus profite d'un rocher pour se propulser et fonce sur Trafiquant 1. Il le percute de "
        "plein fouet.",
        "staging": "Angus au centre, percutant Trafiquant 1 qui recule, bras en croix.",
        "characters": ["Angus", "Trafiquant 1"],
    },
    {
        "description": "Seku, resté en arrière, ramasse une pierre et la lance sur Trafiquant 2 qui s'approchait "
        "d'Angus par derrière.",
        "staging": "Seku à gauche, bras tendu après le lancer. Trafiquant 2 à droite, touché à l'épaule.",
        "characters": ["Seku", "Trafiquant 2"],
    },
    {
        "description": "Trafiquant 2 riposte en dégainant son pistolet, mais Seku esquive de justesse en roulant "
        "au sol.",
        "staging": "Trafiquant 2 à droite, pistolet braqué. Seku à gauche, roulade.",
        "characters": ["Trafiquant 2", "Seku"],
    },
]

# Ce que le directeur artistique a rendu : 4 chocs, gauche/droite partout, pas de gros plan, deux compositions
# identiques d'affilée, l'arme reléguée au fond. Les règles de variété existantes sont tenues (pas de relance
# complète) : seules les règles par planche sont enfreintes.
BAD_PANELS = [
    (
        "plan large",
        "de trois quarts",
        "Angus au premier plan à gauche plonge au sol, Trafiquant 1 au fond à droite tire",
    ),
    ("plan rapproché", "de profil", "Angus à gauche percute Trafiquant 1 à droite, l'épaule en avant"),
    ("plan rapproché", "de profil", "Seku à gauche détend le bras, Trafiquant 2 à droite encaisse la pierre"),
    ("plan moyen", "en contre-plongée", "Trafiquant 2 à droite braque son pistolet, Seku à gauche roule au sol"),
]


def _vulcano_brief() -> PageBrief:
    return PageBrief(
        page_id=3,
        number=3,
        rythme="rapide",
        panels=[
            {
                "panel_id": 127 + i,
                **pa,
                "offscreen": [],
                "spectators": [],
                "shot_type": None,
                "importance": 3 if i < 2 else 2,
                "intensity": "choc",
                "dialogue_chars": 0,
                "dialogues": [],
            }
            for i, pa in enumerate(VULCANO_3)
        ],
        templates=["4-bandes"],
    )


def _ctx(pages: list[PageBrief] | None = None, **kw: Any) -> DirectionContext:
    return DirectionContext(
        series={
            "title": "Ecoloman",
            "style": "manga",
            "reading_direction": "ltr",
            "layout_style": "dynamique",
            "layout_style_name": "Dynamique",
            "layout_style_description": "",
        },
        characters=[{"name": n, "description": ""} for n in ("Angus", "Seku", "Trafiquant 1", "Trafiquant 2")],
        chapter={"number": 3, "title": "Vulcano", "synopsis": "Combat au bord du cratère.", "summary": ""},
        pages=pages or [_vulcano_brief()],
        styles=[{"id": s, "name": s, "description": ""} for s in ("sage", "dynamique", "nerveuse")],
        previous=None,
        variety=kw.pop("variety", "equilibree"),
        rules=kw.pop("rules", VARIETY),
        page_rules=kw.pop("page_rules", RULES),
        **kw,
    )


def _panel(i: int, plan: str, angle: str, action: str, intensity: str = "choc") -> dict[str, Any]:
    return {
        "panel": i,
        "intensity": intensity,
        "plan": plan,
        "angle": angle,
        "cadre": "normal",
        "ambiance": "poussière et fumée, lumière rouge du cratère",
        "action": action,
        "sfx": [],
    }


def _bad_answer() -> dict[str, Any]:
    return {
        "pages": [
            {
                "page": 3,
                "rythme": "climax",
                "rationale": "Le combat éclate.",
                "panels": [_panel(i, *p) for i, p in enumerate(BAD_PANELS, start=1)],
            }
        ]
    }


def _rows(out: da.DirectionOutput, ctx: DirectionContext) -> list[dict[str, Any]]:
    return [pa for _n, _r, panels in da.output_rows(out, ctx) for pa in panels]


def _assert_planche_ok(out: da.DirectionOutput, ctx: DirectionContext) -> None:
    """Les critères d'acceptation de la planche 3 après passage."""
    panels = _rows(out, ctx)
    assert any(pa["plan"] in ("gros plan", "très gros plan", "insert") for pa in panels), panels
    assert any(pa["intensity"] == "calme" for pa in panels), panels
    for a, b in zip(panels, panels[1:], strict=False):
        assert (a["plan"], a["angle"], da._left_right(a, RULES)) != (b["plan"], b["angle"], da._left_right(b, RULES))
    run = longest = 0
    for pa in panels:
        run = run + 1 if pa["intensity"] == "choc" else 0
        longest = max(longest, run)
    assert longest <= 3


# --- preset et règles --------------------------------------------------------------------------
def test_page_rules_live_in_the_preset_and_the_prompt() -> None:
    assert RULES is not None
    assert (RULES.min_close_per_page, RULES.min_calm_per_page, RULES.max_choc_in_a_row) == (1, 1, 3)
    assert RULES.targeted_retry == 1 and RULES.no_repeated_composition and RULES.no_background_subject
    text = da.page_rules_text(RULES)
    assert "au moins 1 gros plan / très gros plan / insert par page" in text
    assert "jamais plus de 3 cases « choc » d'affilée" in text and "case sans personnage" in text
    user = da.render_messages(PROMPT, _ctx())[1].content
    assert "Règles par planche" in user and "au moins 1 case calme par page" in user
    assert da.page_rules_text(None) == "(aucune règle par planche)"


def test_vulcano_planche_3_breaks_every_page_rule() -> None:
    ctx = _ctx()
    out = da.parse_direction(json.dumps(_bad_answer(), ensure_ascii=False), ctx)
    assert da.output_variety(out, VARIETY) == []  # les règles de variété existantes ne voient rien
    issues = da.output_page_issues(out, ctx)
    text = " | ".join(i.text() for i in issues)
    assert "page 3 : aucun gros plan" in text
    assert "page 3 : aucune case calme" in text
    assert (
        "cases 2 et 3 : même composition (« plan rapproché », « de profil », personnages à gauche et à droite)" in text
    )
    assert "cases 1 à 4 : 4 cases « choc » d'affilée (3 au plus)" in text
    assert "case 1 › action : l'élément important est relégué au fond" in text
    by_rule = {i.message.split(" (")[0]: i.cases for i in issues}
    assert by_rule["cases 2 et 3 : même composition"] == [(3, 3)]  # seule la seconde case est à corriger


def test_calm_rythme_close_plans_and_thresholds() -> None:
    assert RULES is not None
    page = [
        {"plan": "insert", "angle": "de profil", "intensity": "normal"},
        {"plan": "plan moyen", "angle": "de dos", "intensity": "choc"},
        {"plan": "plan large", "angle": "en plongée", "intensity": "normal"},
    ]
    # page « respiration » : une case non choc compte comme calme ; l'insert compte comme gros plan
    assert da.check_page_rules([(1, "respiration", page)], RULES) == []
    issues = da.check_page_rules([(1, "montée", page)], RULES)
    assert [i.message.split(" (")[0] for i in issues] == ["aucune case calme"]
    assert issues[0].cases == [(1, 1), (1, 2), (1, 3)]
    # moins de 3 cases : pas d'exigence ; seuils à 0 : pas de règle
    assert da.check_page_rules([(1, "montée", page[:2])], RULES) == []
    off = RULES.model_copy(update={"min_calm_per_page": 0})
    assert da.check_page_rules([(1, "montée", page)], off) == []


def test_choc_runs_are_counted_across_pages() -> None:
    assert RULES is not None

    def chocs(n: int) -> list[dict[str, Any]]:
        return [{"plan": "gros plan", "angle": a, "intensity": "choc"} for a in ("de face", "de dos", "de profil")[:n]]

    issues = da.check_page_rules(
        [(2, None, chocs(2)), (3, None, chocs(2))], RULES.model_copy(update={"min_calm_per_page": 0})
    )
    assert len(issues) == 1 and issues[0].chapter and issues[0].pages == [2, 3]
    assert issues[0].text().startswith("page 2 case 1 à page 3 case 2 : 4 cases « choc » d'affilée")
    warnings = da.page_rule_warnings(issues)
    assert warnings[2][0].startswith(da.CHAPTER_PREFIX) and warnings[2] == warnings[3]
    # 3 d'affilée : permis
    assert da.check_page_rules([(2, None, chocs(3))], RULES.model_copy(update={"min_calm_per_page": 0})) == []


def test_background_subject_and_panel_without_character() -> None:
    assert RULES is not None
    reaction = {
        "plan": "plan large",
        "angle": "de dos",
        "intensity": "normal",
        "action": "Seku s'accroupit, les trafiquants au loin jettent un baril",
        "point_de_vue": "plan de réaction",
        "visible": ["Seku", "Trafiquant 1"],
    }
    [issue] = da.check_page_rules([(1, None, [reaction])], RULES)
    assert "relégué au fond" in issue.message and "vue subjective" in issue.message
    # vue subjective : ce qui est vu est le sujet, rien à redire
    assert da.check_page_rules([(1, None, [{**reaction, "point_de_vue": "vue subjective"}])], RULES) == []
    # case 138 « le sol tremble » : aucun personnage à l'image, l'action ne doit en nommer aucun
    landscape = {"plan": "plan d'ensemble", "angle": "en plongée", "intensity": "normal", "visible": [], "hidden": []}
    ok = {**landscape, "action": "Le sol se fend, une colonne de fumée jaillit du cratère"}
    assert da.check_page_rules([(5, None, [ok])], RULES, ["Angus", "Seku"]) == []
    bad = {**landscape, "action": "Angus et Seku vacillent sur le sol qui tremble"}
    [issue] = da.check_page_rules([(5, None, [bad])], RULES, ["Angus", "Seku"])
    assert "case sans personnage à l'image" in issue.message and "Angus, Seku" in issue.message


# --- relance ciblée -----------------------------------------------------------------------------
def test_vulcano_planche_3_is_fixed_by_one_targeted_retry() -> None:
    ctx = _ctx()
    answers = iter([json.dumps(_bad_answer(), ensure_ascii=False)])

    def responder(messages: list[Any], _json: bool) -> str:
        # deuxième appel : le mock (qui respecte les règles par planche) répond à la relance ciblée
        return next(answers, None) or json.dumps(mock_art_direction(ctx.as_json()), ensure_ascii=False)

    llm = MockLLMProvider(responder)
    steps: list[str] = []
    run = run_direction(llm, PROMPT, ctx, lambda _p, m: steps.append(m))
    assert len(llm.calls) == 2 and run.attempts == 1 and run.targeted
    retry = llm.calls[1][-1].content
    assert "règles par planche" in retry and "aucun gros plan" in retry and "page 3 : cases 1, 2, 3, 4" in retry
    assert llm.calls[1][-2].role == "assistant"  # la réponse fautive est rappelée au LLM
    assert any("relance ciblée" in s for s in steps)
    _assert_planche_ok(run.output, ctx)
    assert run.page_rules == [] and run.variety == []


def test_targeted_retry_only_replaces_the_faulty_panels() -> None:
    ctx = _ctx()
    rules = RULES.model_copy(update={"min_close_per_page": 0, "min_calm_per_page": 0, "max_choc_in_a_row": 0})
    ctx.page_rules = rules
    bad = _bad_answer()
    bad["pages"][0]["panels"][0]["action"] = "Angus plonge au sol, la rafale déchire la roche au-dessus de lui"
    patch = {
        "pages": [
            {
                "page": 3,
                "panels": [
                    _panel(1, "gros plan", "de face", "Changement non demandé"),  # case 1 non fautive : ignorée
                    _panel(3, "gros plan", "en plongée", "Seku arme son bras, la pierre serrée dans le poing"),
                ],
            }
        ]
    }
    answers = iter([json.dumps(bad, ensure_ascii=False), json.dumps(patch, ensure_ascii=False)])
    llm = MockLLMProvider(lambda _m, _j: next(answers))
    run = run_direction(llm, PROMPT, ctx, lambda *_: None)
    assert "page 3 : case 3" in llm.calls[1][-1].content
    panels = {pa.panel: pa for pa in run.output.pages[0].panels}
    assert panels[1].action.startswith("Angus plonge") and panels[1].plan == "plan large"
    assert (panels[3].plan, panels[3].angle) == ("gros plan", "en plongée")
    assert run.page_rules == [] and run.targeted


@pytest.mark.parametrize(
    "second",
    [
        lambda: json.dumps(_bad_answer(), ensure_ascii=False),  # le LLM renvoie la même chose
        lambda: "Je ne peux pas corriger.",  # réponse illisible
        lambda: (_ for _ in ()).throw(LLMError("délai dépassé")),  # le LLM ne répond plus
    ],
)
def test_one_targeted_retry_at_most_then_a_warning(second: Callable[[], str]) -> None:
    ctx = _ctx()
    answers = iter([lambda: json.dumps(_bad_answer(), ensure_ascii=False), second, second])
    llm = MockLLMProvider(lambda _m, _j: next(answers)())
    run = run_direction(llm, PROMPT, ctx, lambda *_: None)
    assert len(llm.calls) == 2 and run.targeted  # une seule relance, pas de blocage
    assert any("aucun gros plan" in w for w in run.page_rules)
    assert [pa.plan for pa in run.output.pages[0].panels] == [p for p, _a, _t in BAD_PANELS]


def test_no_targeted_retry_when_disabled_or_rules_hold() -> None:
    ctx = _ctx(page_rules=RULES.model_copy(update={"targeted_retry": 0}))
    llm = MockLLMProvider(lambda _m, _j: json.dumps(_bad_answer(), ensure_ascii=False))
    run = run_direction(llm, PROMPT, ctx, lambda *_: None)
    assert len(llm.calls) == 1 and not run.targeted and run.page_rules
    good = MockLLMProvider()
    run = run_direction(good, PROMPT, _ctx(), lambda *_: None)
    assert len(good.calls) == 1 and not run.targeted and run.page_rules == []


def test_mock_direction_respects_the_page_rules() -> None:
    from tests.test_art_direction import _brief

    for pages in ([_brief(n, 1 + n % 6) for n in range(1, 11)], [_brief(n, 1) for n in range(1, 9)]):
        for variety in ("sobre", "equilibree", "audacieuse"):
            for variant in (0, 1, 2):
                ctx = _ctx(copy.deepcopy(pages), variety=variety, variant=variant)
                out = da.parse_direction(json.dumps(mock_art_direction(ctx.as_json())), ctx)
                assert da.output_page_issues(out, ctx) == [], (variety, variant)
                assert da.output_variety(out, VARIETY) == [], (variety, variant)


# --- avertissement visible ----------------------------------------------------------------------
@pytest.fixture
def c(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


def test_page_rule_warnings_are_stored_and_recomputed_on_edit(c: TestClient) -> None:
    sid = c.post("/projects", json={**STYLE, "title": "Vulcano"}).json()["id"]
    ch = c.post(f"/projects/{sid}/chapters", json={"synopsis": "Combat au volcan.", "target_page_count": 2}).json()
    c.app.state.ctx.jobs.wait(start_script(c, ch["id"]).json()["id"])  # type: ignore[attr-defined]
    job = c.post(f"/chapters/{ch['id']}/direction", json={}).json()
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    assert c.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"
    page = next(p for p in c.get(f"/chapters/{ch['id']}/direction").json()["pages"] if len(p["panels"]) >= 3)
    assert page["warnings"] == []
    # l'auteur passe toute la page en « choc », en plan moyen de profil : avertissements visibles
    edited = c.patch(
        f"/pages/{page['page_id']}/direction",
        json={
            "panels": [
                {"panel_id": pa["panel_id"], "intensity": "choc", "plan": "plan moyen", "angle": "de profil"}
                for pa in page["panels"]
            ]
        },
    ).json()
    warnings = " | ".join(edited["warnings"])
    assert "aucun gros plan" in warnings and "aucune case calme" in warnings
    n = len(page["panels"])
    assert f"cases 1 à {n} : même composition (« plan moyen », « de profil ») : change" in warnings
    assert sum("même composition" in w for w in edited["warnings"]) == 1  # une suite, un seul message
    if len(page["panels"]) > 3:
        assert "cases « choc » d'affilée" in warnings
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        d = session.query(PageDirection).filter(PageDirection.page_id == page["page_id"]).one()
        assert isinstance(session.get(Page, page["page_id"]), Page)
        assert d.values["warnings"] == edited["warnings"]
