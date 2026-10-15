"""ADN de la série (pre_direction.yaml, pipeline/pre_direction.py) : charte chiffrée par série, défauts des 7
genres, lue par le scénariste, la direction artistique et leurs contrôles — relance, puis avertissement.

Mesures de « la petite île » (13/10) : 63 % de plans serrés, 11 planches sur 13 de même forme ; « vulcano » :
trois climax d'affilée dès 40 % du chapitre."""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.pipeline import art_direction as da
from mangaka_engine.pipeline.art_direction import DirectionContext, PageBrief, run_direction
from mangaka_engine.pipeline.dialogues import DialoguePanel, Reply, check_dialogues
from mangaka_engine.pipeline.pre_direction import (
    Charter,
    DnaError,
    PageView,
    apply_overrides,
    art_text,
    chapter_issues,
    clean_overrides,
    dialogue_rules_for,
    flatten,
    page_shape,
    panel_count_problems,
    script_text,
    shot_problems,
)
from mangaka_engine.pipeline.script import ScriptContext, render_messages
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import PreDirectionSettings
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_art_direction
from tests.conftest import PRESETS_DIR, STYLE, start_script

PRESETS = PresetRegistry.load(PRESETS_DIR)
SETTINGS = PRESETS.pre_direction
assert SETTINGS is not None
DA_PROMPT = PRESETS.prompt("direction-artistique")
SCRIPT_PROMPT = PRESETS.prompt("script")
GENRES = ("shonen", "shojo", "seinen", "tranche-de-vie", "franco-belge", "jeunesse", "magical-girl")
TIGHT = ["gros plan", "plan rapproché", "insert"]


def charter(genre: str | None, **overrides: Any) -> Charter:
    dna = apply_overrides(PRESETS.genre_dna(genre), overrides)  # type: ignore[arg-type]
    return Charter(dna, SETTINGS, tuple(PRESETS.layout_templates.values()), genre)


SHONEN, SHOJO = charter("shonen"), charter("shojo")


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


# --- le preset : défaut ultime et 7 genres -----------------------------------------------------------
def test_the_seven_genres_have_their_dna_in_the_preset() -> None:
    assert set(SETTINGS.genres) == set(GENRES) == set(PRESETS.style_genres)
    assert not [i for i in PRESETS.issues if "pre_direction" in i.path]
    for genre in GENRES:
        assert PRESETS.genre_dna(genre) != SETTINGS.defaults, genre
    # Genre inconnu ou série d'avant les packs : le défaut ultime.
    assert PRESETS.genre_dna(None) == PRESETS.genre_dna("inconnu") == SETTINGS.defaults
    # La prose chiffrée : franco-belge dense, jeunesse aérée.
    assert (
        PRESETS.genre_dna("franco-belge").panels.min_per_page,
        PRESETS.genre_dna("jeunesse").panels.max_per_page,
    ) == (
        6,
        5,
    )


def test_shonen_and_shojo_get_different_thresholds_in_every_family() -> None:
    a, b = SHONEN.dna, SHOJO.dna
    for family in ("panels", "shapes", "shots", "presence", "dialogue", "rhythm"):
        assert getattr(a, family) != getattr(b, family), family


def test_a_genre_value_out_of_bounds_is_refused_by_the_preset() -> None:
    raw = SETTINGS.model_dump()
    raw["genres"] = {"shonen": {"shots": {"wide": {"min": 0.6, "max": 0.3}}}}
    with pytest.raises(ValueError, match="genres.shonen"):
        PreDirectionSettings.model_validate(raw)
    raw["genres"] = {"shonen": {"panels": {"min_per_page": 12}}}
    with pytest.raises(ValueError):
        PreDirectionSettings.model_validate(raw)
    raw["genres"] = {"shonen": {"style": "texte libre"}}
    with pytest.raises(ValueError):
        PreDirectionSettings.model_validate(raw)


# --- ajustements de la série --------------------------------------------------------------------
def test_series_adjustments_are_bounded_and_only_differences_are_kept() -> None:
    base = PRESETS.genre_dna("shonen")
    assert base is not None
    tuned = apply_overrides(base, {"shots.wide.min": 0.25, "rhythm.breath_after_peak": False})
    assert tuned.shots.wide.min == 0.25 and tuned.rhythm.breath_after_peak is False
    assert tuned.shots.wide.max == base.shots.wide.max  # le reste hérité
    for bad, match in (
        ({"shots.wide.min": 1.5}, "Plans larges"),
        ({"shots.wide.min": 0.5, "shots.wide.max": 0.3}, "minimum doit rester sous le maximum"),
        ({"panels.min_per_page": 2.5}, "entier"),
        ({"rhythm.breath_after_peak": 1}, "oui ou non"),
        ({"style": "libre"}, "inconnue"),
    ):
        with pytest.raises(DnaError, match=match):
            apply_overrides(base, bad)
    kept = clean_overrides(base, {"shots.wide.min": base.shots.wide.min, "panels.max_per_page": 5, "x": 1})
    assert kept == {"panels.max_per_page": 5}
    assert set(flatten(base)) >= {"shots.tight_max", "dialogue.min_silent_panels", "rhythm.first_peak.min"}


# --- échelle des plans (check_variety) : « élargis » autant que « resserre » -------------------------
def _pages(plans: list[str], per_page: int = 5) -> list[tuple[int, list[dict[str, Any]]]]:
    return [
        (n + 1, [{"plan": p} for p in plans[n * per_page : (n + 1) * per_page]])
        for n in range((len(plans) + per_page - 1) // per_page)
    ]


def test_seventy_percent_of_tight_shots_asks_to_widen() -> None:
    plans = (
        ["gros plan", "plan rapproché", "insert", "gros plan", "plan rapproché", "insert", "gros plan"]
        + [
            "plan large",
            "plan moyen",
            "plan large",
        ]
    ) * 2
    problems = shot_problems(plans, SHONEN, pages=4)
    tight = next(p for p in problems if p.startswith("trop de plans serrés"))
    assert "14 sur 20 (12 au plus, 60 %)" in tight and "élargis" in tight
    # Shōjo (gros plans sur les visages) : jusqu'à 75 % de plans serrés.
    assert not any(p.startswith("trop de plans serrés") for p in shot_problems(plans, SHOJO, pages=4))
    # Et la même règle dans check_variety, à l'échelle du chapitre.
    _, chapter = da.check_variety(_pages(plans), None, SHONEN)
    assert any("élargis" in c for c in chapter)


def test_the_wide_floor_widens_and_the_wide_ceiling_tightens() -> None:
    few_wide = ["gros plan", "plan moyen", "plan rapproché", "plan moyen", "insert"] * 4
    floor = next(p for p in shot_problems(few_wide, SHONEN, pages=4) if "plans larges" in p)
    assert floor.startswith("trop peu de plans larges / d'ensemble : 0 sur 20 (au moins 3, 15 %)")
    assert "élargis" in floor
    many_wide = ["plan large", "gros plan", "plan large", "plan moyen", "plan large"] * 4
    ceiling = next(p for p in shot_problems(many_wide, SHONEN, pages=4) if "plans larges" in p)
    assert ceiling.startswith("trop de plans larges / d'ensemble : 12 sur 20") and "resserre" in ceiling
    # Shōnen : au moins 15 % de gros plans ; shōjo : 25 %.
    some_close = ["gros plan", "plan large", "plan moyen", "plan rapproché", "plan moyen"] * 4
    assert not any("gros plans" in p for p in shot_problems(some_close, SHONEN, pages=4))
    assert any(p.startswith("trop peu de gros plans") for p in shot_problems(some_close, SHOJO, pages=4))
    # Mot élidé : « d'inserts ».
    inserts = ["insert", "plan large", "insert", "plan moyen", "insert"] * 4
    assert any(p.startswith("trop d'inserts") for p in shot_problems(inserts, SHONEN, pages=4))


def test_shot_shares_need_a_whole_chapter_and_a_charter() -> None:
    tight = ["gros plan", "insert", "plan rapproché"] * 4
    assert shot_problems(tight, SHONEN, pages=3) == []  # « Proposer autre chose » sur une page
    assert shot_problems(tight, None, pages=8) == []
    assert da.check_variety(_pages(tight), None) == ({}, [])


# --- formes de planche, présence, courbe de rythme (check_page_rules) --------------------------------
def _view(n: int, rythme: str = "montée", panels: int = 4, *, template: str | None = None, **kw: Any) -> PageView:
    cells = [{"plan": "plan moyen", "importance": 2, "visible": ["Aiko"]} for _ in range(panels)]
    return PageView(n, rythme, template, kw.get("page_choc"), cells)


def _curve(*rythmes: str) -> list[PageView]:
    templates = ["4-grille", "4-grand-haut", "3-bandes", "4-bandeau-central", "4-grand-bas"]
    return [
        _view(i + 1, r, panels=3 if t.startswith("3") else 4, template=t)
        for i, (r, t) in enumerate(zip(rythmes, (templates * 10)[: len(rythmes)], strict=True))
    ]


GOOD_CURVE = (
    "calme",
    "montée",
    "climax",
    "respiration",
    "montée",
    "respiration",
    "montée",
    "montée",
    "respiration",
    "climax",
)


def _messages(views: list[PageView], c: Charter) -> list[str]:
    return [i.message for i in chapter_issues(views, c)]


def test_a_good_curve_and_varied_shapes_pass() -> None:
    assert _messages(_curve(*GOOD_CURVE), SHONEN) == []


def test_three_climaxes_in_a_row_break_the_curve() -> None:
    vulcano = (
        "calme",
        "montée",
        "climax",
        "climax",
        "climax",
        "respiration",
        "montée",
        "montée",
        "respiration",
        "climax",
    )
    messages = _messages(_curve(*vulcano), SHONEN)
    assert any("pages 3 à 5 : 3 pics d'affilée (2 au plus)" in m for m in messages), messages
    issue = next(i for i in chapter_issues(_curve(*vulcano), SHONEN) if "pics d'affilée" in i.message)
    assert issue.pages == [5]  # la page en trop, à repasser en « montée »
    # Shōjo : un seul pic d'affilée ; shōnen en permet deux.
    two = (
        "calme",
        "montée",
        "climax",
        "climax",
        "respiration",
        "montée",
        "respiration",
        "montée",
        "respiration",
        "climax",
    )
    assert not any("d'affilée" in m for m in _messages(_curve(*two), SHONEN))
    assert any("2 pics d'affilée (1 au plus)" in m for m in _messages(_curve(*two), SHOJO))


def test_first_peak_breath_and_final_peak() -> None:
    early = (
        "climax",
        "respiration",
        "montée",
        "respiration",
        "montée",
        "respiration",
        "montée",
        "montée",
        "respiration",
        "climax",
    )
    assert any("premier pic trop tôt, page 1" in m for m in _messages(_curve(*early), SHONEN))
    late = ("calme", "montée", "montée", "montée", "montée", "climax", "respiration", "montée", "respiration", "climax")
    # Page 6 sur 10 (50 à 60 %) : trop tard pour un shōnen (25 à 40 %), à l'heure pour un shōjo (30 à 50 %).
    assert any("premier pic trop tard, page 6" in m for m in _messages(_curve(*late), SHONEN))
    assert not any("premier pic" in m for m in _messages(_curve(*late), SHOJO))
    no_breath = list(GOOD_CURVE)
    no_breath[3] = "montée"
    assert any(
        "page 4 : pas de respiration après le pic de la page 3" in m for m in _messages(_curve(*no_breath), SHONEN)
    )
    flat_end = list(GOOD_CURVE)
    flat_end[9] = "montée"
    assert any("aucun pic dans les 1 dernière planche" in m for m in _messages(_curve(*flat_end), SHONEN))
    # Tranche de vie : pas de cliffhanger forcé.
    assert not any("dernière" in m for m in _messages(_curve(*flat_end), charter("tranche-de-vie")))
    # Moins de `min_pages` pages dirigées ensemble : rien à vérifier.
    assert _messages(_curve("climax", "climax", "climax"), SHONEN) == []


def test_pages_all_of_the_same_shape_are_flagged() -> None:
    same = [_view(i + 1, r, template="4-grille") for i, r in enumerate(GOOD_CURVE)]
    messages = _messages(same, SHONEN)
    assert any(
        "pages 1 à 10 : 10 planches de même forme d'affilée (« Grille 2 × 2 », 2 au plus)" in m for m in messages
    )
    assert any("10 planches sur 10 de même forme" in m for m in messages)
    assert any("0 planche à grande case sur 10 (au moins 4, 40 %)" in m for m in messages)
    # « 3 cases dont une grande » sans gabarit : la forme vient de l'importance des cases (comme la mise en page).
    island = [
        PageView(i + 1, r, None, None, [{"importance": 3}, {"importance": 2}, {"importance": 2}])
        for i, r in enumerate(GOOD_CURVE)
    ]
    shape = page_shape(island[0], SHONEN)
    assert shape.big and shape.key == "auto:3:1" and shape.label == "3 cases dont 1 grande"
    assert any("planches de même forme d'affilée" in m for m in _messages(island, SHONEN))
    # Le franco-belge aime le gaufrier : 4 planches identiques d'affilée permises, mais pas 10.
    franco = charter("franco-belge")
    assert any("4 au plus" in m for m in _messages(same, franco))
    assert not any("grande case" in m for m in _messages(same, franco))


def test_too_many_big_panel_pages_for_a_shojo() -> None:
    big = [_view(i + 1, r, template="4-grand-haut") for i, r in enumerate(GOOD_CURVE)]
    for i in range(0, 10, 2):
        big[i].template = "4-bandeau-central"
    big[3].template = big[7].template = "4-grille"
    assert any("8 planches à grande case sur 10 (6 au plus, 60 %)" in m for m in _messages(big, SHOJO))
    assert not any("grande case" in m for m in _messages(big, SHONEN))  # shōnen : jusqu'à 85 %


def test_presence_subjective_and_empty_panels() -> None:
    views = _curve(*GOOD_CURVE)
    cells = [pa for v in views for pa in v.panels]
    for pa in cells[:10]:  # 10 cases sur 38 en vue subjective (26 %)
        pa["point_de_vue"] = "vue subjective"
    assert any("10 cases en vue subjective sur 38 (7 au plus, 20 %)" in m for m in _messages(views, SHONEN))
    assert not any("subjective" in m for m in _messages(views, SHOJO))  # shōjo : jusqu'à 30 %
    # Tranche de vie : des cases de décor sans personnage (au moins 10 %).
    assert any(
        "0 case sans personnage à l'image sur 38 (au moins 4, 10 %)" in m
        for m in _messages(_curve(*GOOD_CURVE), charter("tranche-de-vie"))
    )


# --- direction artistique : relance, puis avertissement visible ----------------------------------
def _brief(n: int, panels: int = 4) -> PageBrief:
    return PageBrief(
        page_id=100 + n,
        number=n,
        rythme="normal",
        panels=[
            {
                "panel_id": 1000 + n * 10 + i,
                "description": f"Aiko et Kenji, page {n}, case {i + 1}",
                "staging": "",
                "characters": ["Aiko", "Kenji"],
                "offscreen": [],
                "spectators": [],
                "shot_type": None,
                "importance": 3 if i == 0 and n % 2 else 2,
                "intensity": "normal",
                "dialogue_chars": 0,
                "dialogues": [],
            }
            for i in range(panels)
        ],
        templates=[t.id for t in PRESETS.layout_templates.values() if t.panel_count == panels],
    )


def _ctx(c: Charter | None = SHONEN, pages: int = 10) -> DirectionContext:
    return DirectionContext(
        series={
            "title": "La petite île",
            "style": "manga",
            "reading_direction": "rtl",
            "layout_style": "dynamique",
            "layout_style_name": "Dynamique",
            "layout_style_description": "",
        },
        characters=[{"name": "Aiko", "description": ""}, {"name": "Kenji", "description": ""}],
        chapter={"number": 1, "title": "L'île", "synopsis": "Aiko et Kenji explorent l'île.", "summary": ""},
        pages=[_brief(n, 5 if n % 3 == 0 else 4) for n in range(1, pages + 1)],
        styles=[{"id": s, "name": s, "description": ""} for s in ("sage", "dynamique", "nerveuse")],
        previous=None,
        variety="equilibree",
        rules=DA_PROMPT.variety_rules,
        page_rules=DA_PROMPT.page_rules,
        charter=c,
    )


def _sequence(*answers: Any) -> MockLLMProvider:
    it = iter(answers)
    return MockLLMProvider(lambda _m, _j: json.dumps(next(it), ensure_ascii=False))


def _good(ctx: DirectionContext) -> dict[str, Any]:
    return mock_art_direction(ctx.as_json())


def _run(ctx: DirectionContext, *answers: Any) -> tuple[da.DirectionRun, MockLLMProvider]:
    llm = _sequence(*answers)
    return run_direction(llm, DA_PROMPT, ctx, lambda _p, _m: None), llm


def test_the_mock_respects_the_charter_of_both_genres() -> None:
    for c in (SHONEN, SHOJO):
        ctx = _ctx(c)
        out = da.parse_direction(json.dumps(_good(ctx)), ctx)
        assert da.output_variety(out, ctx.rules, c) == []
        assert [i.text() for i in da.output_page_issues(out, ctx)] == []


def _tight(ctx: DirectionContext) -> dict[str, Any]:
    """70 % de plans serrés, sans rien d'autre de fautif (angles et compositions variés)."""
    out = copy.deepcopy(_good(ctx))
    cycle = [
        "gros plan",
        "plan rapproché",
        "insert",
        "plan large",
        "gros plan",
        "plan rapproché",
        "plan moyen",
        "insert",
        "gros plan",
        "plan rapproché",
    ]
    k = 0
    for page in out["pages"]:
        for pa in page["panels"]:
            pa["plan"] = cycle[k % len(cycle)]
            k += 1
    return out


def test_tight_chapter_gets_a_widen_retry_then_a_visible_warning() -> None:
    ctx = _ctx()
    tight = _tight(ctx)
    run, llm = _run(ctx, tight, tight, tight, tight)
    assert len(llm.calls) >= 2  # la relance a eu lieu avant l'avertissement
    retry = llm.calls[1][-1].content
    assert "trop de plans serrés" in retry and "élargis" in retry
    assert any(w.startswith("trop de plans serrés") and "élargis" in w for w in run.variety)
    # Le LLM corrige à la relance : plus d'avertissement.
    fixed, llm = _run(ctx, tight, _good(ctx))
    assert fixed.attempts == 2 and fixed.variety == [] and fixed.page_rules == []


def _climaxes(ctx: DirectionContext) -> dict[str, Any]:
    out = copy.deepcopy(_good(ctx))
    for page in out["pages"]:
        if page["page"] in (3, 4, 5):
            page["rythme"] = "climax"
    return out


def test_three_climaxes_get_a_targeted_retry_on_the_page_fields_then_a_warning() -> None:
    ctx = _ctx()
    bad = _climaxes(ctx)
    run, llm = _run(ctx, bad, {"pages": [{"page": 5, "panels": []}]})  # relance sans correction
    assert run.targeted and len(llm.calls) == 2
    retry = llm.calls[1][-1].content
    assert "3 pics d'affilée" in retry and "page 5 : champs de la page" in retry and '"rythme"' in retry
    assert any("3 pics d'affilée" in w for w in run.page_rules)
    # La relance corrige le rythme de la seule page en trop : la charte est tenue.
    patch = {"pages": [{"page": 5, "rythme": "respiration", "panels": []}, {"page": 6, "rythme": "montée"}]}
    fixed, _ = _run(ctx, bad, patch)
    rythmes = {p.page: p.rythme for p in fixed.output.pages}
    assert rythmes[5] == "respiration" and rythmes[6] != "montée"  # page 6 n'était pas à corriger
    assert not any("pics d'affilée" in w for w in fixed.page_rules)


def test_pages_all_of_the_same_shape_get_a_retry_then_a_warning() -> None:
    ctx = _ctx()
    for brief in ctx.pages:  # toutes les pages à 4 cases
        brief.panels = brief.panels[:4]
        brief.templates = [t.id for t in PRESETS.layout_templates.values() if t.panel_count == 4]
    same = copy.deepcopy(_good(ctx))
    for page in same["pages"]:
        page["template"], page["page_choc"] = "4-grille", None
        page["panels"] = page["panels"][:4]
    run, llm = _run(ctx, same, same)
    assert run.targeted and "planches de même forme d'affilée" in llm.calls[1][-1].content
    assert any("planches de même forme d'affilée" in w for w in run.page_rules)


def test_stored_direction_shows_the_charter_warnings(client: TestClient) -> None:
    """Après les relances, l'avertissement est visible sur les pages (écran Direction artistique)."""
    s = _ok(client.post("/projects", json={**STYLE, "title": "La petite île"}), 201)
    for name in ("Aiko", "Kenji"):
        _ok(client.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
    ch = _ok(
        client.post(
            f"/projects/{s['id']}/chapters",
            json={"title": "L'île", "synopsis": "Aiko et Kenji explorent l'île.", "target_page_count": 8},
        ),
        201,
    )
    job = _ok(start_script(client, ch["id"]), 202)
    client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    job = _ok(client.post(f"/chapters/{ch['id']}/direction", json={}), 202)
    client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    pages = _ok(client.get(f"/chapters/{ch['id']}/direction"))["pages"]
    assert all(not p["warnings"] for p in pages)  # le LLM factice tient la charte
    # L'auteur plafonne les plans serrés à 10 % dans son ADN : le LLM factice ne peut pas tenir (un plan serré
    # et un gros plan par page restent exigés) ; relancé, il garde sa proposition avec un avertissement visible.
    _ok(client.put(f"/projects/{s['id']}/pre-direction", json={"overrides": {"shots.tight_max": 0.1}}))
    job = _ok(client.post(f"/chapters/{ch['id']}/direction", json={}), 202)
    client.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    done = _ok(client.get(f"/jobs/{job['id']}"))
    assert done["status"] == "succeeded" and "en 3 essais" in done["message"] and "avertissement" in done["message"]
    pages = _ok(client.get(f"/chapters/{ch['id']}/direction"))["pages"]
    assert all(
        any(w.startswith("chapitre : trop de plans serrés") and "élargis" in w for w in p["warnings"]) for p in pages
    )


# --- scénariste : cases et dialogue par planche ------------------------------------------------
def test_panels_per_page_follow_the_genre() -> None:
    counts = [3, 4, 6, 7, 1]
    assert panel_count_problems(counts, SHONEN) == [
        "page 1 : 3 cases (4 à 6 par planche pour cette série, ou une pleine page d'une seule case) : découpe "
        "davantage le moment (réaction, détail, décor)",
        "page 4 : 7 cases (4 à 6 par planche pour cette série, ou une pleine page d'une seule case) : regroupe des cases",
    ]
    assert [p.split(" : ")[0] for p in panel_count_problems(counts, SHOJO)] == ["page 4"]  # shōjo : 3 à 6
    assert panel_count_problems(counts, None) == []


def test_dialogue_per_page_follows_the_genre() -> None:
    rules = SCRIPT_PROMPT.dialogue_rules
    assert rules is not None
    page = [
        DialoguePanel(page=1, index=i, panels_on_page=4, characters=["Aiko"], replies=[Reply("speech", "Oui !")] * n)
        for i, n in enumerate((3, 3, 2, 0), start=1)
    ]
    shonen = dialogue_rules_for(rules, SHONEN)
    shojo = dialogue_rules_for(rules, SHOJO)
    assert (shonen.min_per_page, shonen.max_per_page) == (4, 7)  # type: ignore[union-attr]
    assert (shojo.min_per_page, shojo.max_per_page) == (5, 9)  # type: ignore[union-attr]
    lenient = {"require_inner_voice": False}
    assert any("8 répliques (7 au plus" in p for p in check_dialogues(page, shonen.model_copy(update=lenient)))  # type: ignore[union-attr]
    assert check_dialogues(page, shojo.model_copy(update=lenient)) == []  # type: ignore[union-attr]
    assert dialogue_rules_for(rules, None) is rules


# --- $pre_direction dans les prompts ------------------------------------------------------------
def test_pre_direction_is_rendered_in_both_prompts() -> None:
    sctx = ScriptContext(
        series={"title": "Île", "style": "shonen", "reading_direction": "rtl"},
        characters=[],
        previous_chapters=[],
        chapter={"number": 1, "title": "Un", "synopsis": "…", "target_pages": 13},
        charter=SHONEN,
    )
    _, user = render_messages(SCRIPT_PROMPT, sctx)
    text = script_text(SHONEN, 13)
    assert text in user.content
    assert "4 à 6 cases par planche" in text and "4 à 7 répliques" in text
    assert "premier pic (« climax ») entre 25 % et 40 % du chapitre (pages 4 à 6 sur 13)" in text
    assert "3 cases" not in user.content.split("Charte de la série")[0].split("Contraintes")[-1]
    _, da_user = da.render_messages(DA_PROMPT, _ctx())
    art = art_text(SHONEN, 10)
    assert art in da_user.content
    assert "plan large / plan d'ensemble 15 % à 35 %" in art and "plans serrés (" in art
    assert "vue subjective au plus 20 %" in art and "de même forme d'affilée" in art
    assert script_text(None) == art_text(None) == "(pas de charte pour cette série)"


# --- API : carte « ADN de la série », écran Scénario ----------------------------------------------
def test_series_dna_card_reads_and_adjusts_values(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**STYLE, "title": "Île"}), 201)
    dna = _ok(client.get(f"/projects/{s['id']}/pre-direction"))
    assert dna["genre"] == "shonen" and dna["genre_name"] == "Shōnen" and dna["available"]
    assert dna["overrides"] == {} and dna["effective"] == dna["inherited"]
    fields = {f["path"]: f for f in dna["fields"]}
    assert fields["shots.wide.min"]["kind"] == "share" and fields["shots.wide.min"]["label"]
    assert (fields["panels.min_per_page"]["min"], fields["panels.min_per_page"]["max"]) == (1, 9)
    assert fields["rhythm.breath_after_peak"]["kind"] == "bool"
    assert set(dna["groups"]) == {"panels", "shapes", "shots", "presence", "dialogue", "rhythm", "places"} | {
        f"tempo.{t}" for t in ("calme", "dialogue", "combat", "poursuite", "sport_collectif", "revelation")
    }

    tuned = _ok(
        client.put(
            f"/projects/{s['id']}/pre-direction",
            json={
                "overrides": {"shots.wide.min": 0.25, "panels.min_per_page": dna["inherited"]["panels.min_per_page"]}
            },
        )
    )
    assert tuned["overrides"] == {"shots.wide.min": 0.25}  # la valeur égale au genre reste héritée
    assert tuned["effective"]["shots.wide.min"] == 0.25 and tuned["inherited"]["shots.wide.min"] == 0.15

    bad = client.put(
        f"/projects/{s['id']}/pre-direction", json={"overrides": {"shots.wide.min": 0.5, "shots.wide.max": 0.2}}
    )
    assert bad.status_code == 422 and "minimum" in bad.text
    assert (
        client.put(f"/projects/{s['id']}/pre-direction", json={"overrides": {"shots.wide.min": "beaucoup"}}).status_code
        == 422
    )
    assert _ok(client.get(f"/projects/{s['id']}/pre-direction"))["overrides"] == {"shots.wide.min": 0.25}

    # Changer de genre : les valeurs héritées suivent, l'ajustement reste.
    _ok(client.patch(f"/projects/{s['id']}", json={"style_genre": "shojo"}))
    shojo = _ok(client.get(f"/projects/{s['id']}/pre-direction"))
    assert shojo["inherited"]["shots.close_up.min"] == 0.25 and shojo["effective"]["shots.wide.min"] == 0.25
    reset = _ok(client.put(f"/projects/{s['id']}/pre-direction", json={"overrides": {}}))
    assert reset["overrides"] == {} and reset["effective"] == reset["inherited"]
    assert client.get("/projects/999/pre-direction").status_code == 404


def test_script_brief_shows_the_charter_and_warns_on_an_empty_bible(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**STYLE, "title": "Île"}), 201)
    aiko = _ok(client.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
    _ok(client.post(f"/projects/{s['id']}/characters", json={"name": "Kenji"}), 201)
    ch = _ok(
        client.post(
            f"/projects/{s['id']}/chapters",
            json={"title": "Un", "synopsis": "Aiko arrive sur l'île.", "target_page_count": 13},
        ),
        201,
    )
    brief = _ok(client.get(f"/chapters/{ch['id']}/script-brief"))
    assert brief["bible_empty"] is True
    assert [c["name"] for c in brief["characters_without_note"]] == ["Aiko"]  # Kenji n'est pas dans le synopsis
    assert "4 à 6 cases par planche" in brief["pre_direction"] and "pages 4 à 6 sur 13" in brief["pre_direction"]
    assert "plans serrés" in brief["art_pre_direction"]

    _ok(client.put(f"/projects/{s['id']}/bible", json={"world": "Une île volcanique.", "character_notes": {}}))
    brief = _ok(client.get(f"/chapters/{ch['id']}/script-brief"))
    assert brief["bible_empty"] is False and [c["id"] for c in brief["characters_without_note"]] == [aiko["id"]]
    _ok(client.put(f"/projects/{s['id']}/bible", json={"character_notes": {str(aiko["id"]): "Curieuse, têtue."}}))
    assert _ok(client.get(f"/chapters/{ch['id']}/script-brief"))["characters_without_note"] == []
    # Un avertissement, jamais un blocage : « Découper » part avec une bible vide.
    empty = _ok(client.post("/projects", json={**STYLE, "title": "Vide"}), 201)
    ch2 = _ok(client.post(f"/projects/{empty['id']}/chapters", json={"title": "Un", "synopsis": "Une île."}), 201)
    assert _ok(client.get(f"/chapters/{ch2['id']}/script-brief"))["bible_empty"] is True
    _ok(start_script(client, ch2["id"]), 202)
    assert client.get("/chapters/999/script-brief").status_code == 404


def test_dialogue_report_reads_the_series_dna(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**STYLE, "title": "Île"}), 201)
    ch = _ok(client.post(f"/projects/{s['id']}/chapters", json={"title": "Un", "synopsis": "Une île."}), 201)
    panel = {"description": "Aiko court.", "characters": ["Aiko"], "dialogues": [{"speaker": "Aiko", "text": "Vite !"}]}
    _ok(client.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel, panel, panel]}]}))
    warnings = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))["warnings"]
    assert warnings[0].startswith("page 1 : 3 cases (4 à 6 par planche")
    assert any("au moins 4 par planche" in w for w in warnings)
    _ok(
        client.put(
            f"/projects/{s['id']}/pre-direction",
            json={"overrides": {"panels.min_per_page": 3, "dialogue.min_per_page": 2}},
        )
    )
    warnings = _ok(client.get(f"/chapters/{ch['id']}/dialogues"))["warnings"]
    assert not any("cases (" in w or "par planche, onomatopées" in w for w in warnings), warnings
