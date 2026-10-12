"""Le savoir-faire et le plan arrivent à l'image (#129) : prompt rédigé redemandé quand le savoir-faire du
rédacteur change, « Réécrire les prompts du chapitre », références choisies selon le plan, cadrage explicite
et négatif contre le plein pied pour les plans serrés, « Sources utilisées » de la case. LLM, embeddings et
ComfyUI factices."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import pick_references, shot_ranks
from mangaka_engine.pipeline.prompt import build_negative_prompt, camera_term, is_tight_shot
from mangaka_engine.pipeline.prompt_writer import PromptBrief
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.models import Character, CharacterImage
from tests.conftest import PRESETS_DIR, STYLE, png_bytes
from tests.test_prompt_writer import _ok, _wait, _writer_calls

REG = PresetRegistry.load(PRESETS_DIR)
FULL_BODY = ["full body", "full-length", "feet visible", "standing pose facing viewer"]


class Env:
    def __init__(self, c: TestClient, llm: MockLLMProvider) -> None:
        self.c, self.llm = c, llm


def _env(make_settings: Callable[..., Settings], **settings: Any) -> Iterator[Env]:
    llm = MockLLMProvider()
    providers = Providers(
        llm=llm,
        vision=None,
        comfyui=MockComfyUIClient(),
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(make_settings(**settings), providers=providers)) as c:
        yield Env(c, llm)


@pytest.fixture
def env(make_settings: Callable[..., Settings]) -> Iterator[Env]:
    yield from _env(make_settings)


@pytest.fixture
def pack_env(make_settings: Callable[..., Settings]) -> Iterator[Env]:
    yield from _env(make_settings, knowledge_packs=True)


def _chapter(c: TestClient, *shots: str) -> dict:
    """Série (Aiko avec une image de référence), un chapitre d'une page, une case par plan."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames"}), 201)
    aiko = _ok(
        c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko", "visual_description": "cheveux noirs"}), 201
    )
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    panels = [
        {"description": f"Aiko esquive le sabre sous la pluie ({shot})", "characters": ["Aiko"], "shot_type": shot}
        for shot in shots
    ]
    pages = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": panels}]}))
    return {"series": s, "chapter": ch, "panels": [p["id"] for p in pages[0]["panels"]]}


def _generate(c: TestClient, panel_id: int) -> dict:
    _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    _wait(c)
    return _ok(c.get(f"/panels/{panel_id}"))


def _add_fiche(c: TestClient, collection: str = "Design de personnages") -> dict:
    """Fiche ajoutée à une collection lue par le rédacteur de prompt (presets/knowledge.yaml)."""
    col = _ok(c.post("/knowledge/collections", json={"name": collection}), 201)
    body = {"title": "Silhouettes", "content": "Aiko garde une silhouette nerveuse, épaules hautes, sabre bas. " * 3}
    return _ok(c.post(f"/knowledge/collections/{col['id']}/documents", json=body), 201)


# --- empreinte du savoir-faire -----------------------------------------------------------------
def test_knowledge_change_makes_written_prompts_pending_but_never_manual_ones(env: Env) -> None:
    c = env.c
    data = _chapter(c, "gros plan", "plan large")
    written, manual = data["panels"]
    panel = _generate(c, written)
    assert panel["prompt_source"] == "ia" and panel["prompt_pending"] is False
    _ok(c.patch(f"/panels/{manual}", json={"final_prompt": "Aiko, close-up, rain."}))
    calls = len(_writer_calls(env.llm))

    # rien n'a changé : la clé ne bouge pas, pas de réécriture à chaque génération
    again = _generate(c, written)
    assert again["prompt_pending"] is False and len(_writer_calls(env.llm)) == calls
    assert again["final_prompt"] == panel["final_prompt"]

    # fiche ajoutée au savoir-faire du rédacteur : le prompt rédigé est à réécrire, pas celui édité à la main
    _add_fiche(c)
    assert _ok(c.get(f"/panels/{written}"))["prompt_pending"] is True
    edited = _ok(c.get(f"/panels/{manual}"))
    assert edited["prompt_pending"] is False and edited["final_prompt"] == "Aiko, close-up, rain."

    rewritten = _generate(c, written)
    assert len(_writer_calls(env.llm)) == calls + 1 and rewritten["prompt_pending"] is False
    assert "Silhouettes" in _writer_calls(env.llm)[-1][-1].content  # la nouvelle fiche est bien reçue
    sources = rewritten["prompt_sources"]
    assert sources["written_at"] and "Design de personnages" in sources["collections"]
    assert [p["document_title"] for p in sources["passages"]] == ["Silhouettes"]
    assert _ok(c.get(f"/panels/{manual}"))["final_prompt"] == "Aiko, close-up, rain."


def test_writer_budget_edited_in_the_team_makes_prompts_pending(env: Env) -> None:
    c = env.c
    data = _chapter(c, "gros plan")
    [pid] = data["panels"]
    assert _generate(c, pid)["prompt_pending"] is False
    detail = _ok(c.get("/agents/dessinateur"))
    knowledge = {**detail["knowledge"]["value"], "budget_tokens": 400}
    sid = data["series"]["id"]
    _ok(c.put(f"/agents/dessinateur/profile?project_id={sid}", json={"values": {}, "knowledge": knowledge}))
    assert _ok(c.get(f"/panels/{pid}"))["prompt_pending"] is True


# --- « Réécrire les prompts du chapitre » -------------------------------------------------------
def test_chapter_action_rewrites_only_the_non_manual_ai_prompts(env: Env) -> None:
    c = env.c
    data = _chapter(c, "gros plan", "plan moyen", "plan large", "insert")
    ai_a, ai_b, manual, never = data["panels"]
    for pid in (ai_a, ai_b, manual):
        _generate(c, pid)
    _ok(c.patch(f"/panels/{manual}", json={"final_prompt": "Aiko, wide shot, hand-written."}))
    cid = data["chapter"]["id"]

    assert _ok(c.get(f"/chapters/{cid}/prompts/rewrite")) == {"count": 2, "ai_prompt": True}
    before = {pid: _ok(c.get(f"/panels/{pid}")) for pid in data["panels"]}
    assert [before[p]["prompt_pending"] for p in data["panels"]] == [False, False, False, True]

    assert _ok(c.post(f"/chapters/{cid}/prompts/rewrite")) == {"count": 2, "ai_prompt": True}
    after = {pid: _ok(c.get(f"/panels/{pid}")) for pid in data["panels"]}
    assert [after[p]["prompt_pending"] for p in data["panels"]] == [True, True, False, True]
    # le texte reste en place jusqu'à la génération ; l'édition à la main ne bouge pas
    assert after[ai_a]["final_prompt"] == before[ai_a]["final_prompt"]
    assert after[manual]["final_prompt"] == "Aiko, wide shot, hand-written." and after[manual]["final_prompt_manual"]

    calls = len(_writer_calls(env.llm))
    assert _generate(c, ai_a)["prompt_pending"] is False and len(_writer_calls(env.llm)) == calls + 1
    assert _ok(c.get(f"/chapters/{cid}/prompts/rewrite"))["count"] == 2  # rédigés de nouveau, toujours réécrivables

    # série par fragments : rien à réécrire
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"ai_prompt": False}))
    assert _ok(c.post(f"/chapters/{cid}/prompts/rewrite")) == {"count": 0, "ai_prompt": False}


# --- références selon le plan --------------------------------------------------------------------
PORTRAIT, TURNAROUND = 11, 12
SHEETS = {PORTRAIT: "personnage-portrait", TURNAROUND: "personnage-turnaround"}


def _aiko(*image_ids: int) -> Character:
    return Character(id=1, name="Aiko", reference_images=[CharacterImage(id=i) for i in image_ids])


def _sent(character: Character, plan: str, per_entry: str = "principale", **kw: Any) -> list[int]:
    ranks = shot_ranks(
        REG, plan, {i: s for i, s in SHEETS.items() if i in {im.id for im in character.reference_images}}
    )
    return [img.id for _, img in pick_references([character], 5, per_entry, shots=ranks, **kw)]


@pytest.mark.parametrize("order", [(PORTRAIT, TURNAROUND), (TURNAROUND, PORTRAIT)])
def test_portrait_first_for_tight_shots_and_turnaround_for_wide_ones(order: tuple[int, int]) -> None:
    aiko = _aiko(*order)
    for plan in ("gros plan", "Très gros plan", "plan rapproché", "insert", "plan moyen"):
        assert _sent(aiko, plan) == [PORTRAIT], plan
        assert _sent(aiko, plan, "toutes") == [PORTRAIT], plan  # le plein pied n'est jamais envoyé en plus
    for plan in ("plan large", "plan d'ensemble", "plan américain"):
        assert _sent(aiko, plan) == [TURNAROUND], plan
    # plan inconnu ou absent : l'ordre de la galerie
    assert _sent(aiko, "") == [order[0]] and _sent(aiko, "plan subjectif") == [order[0]]


def test_dialogue_choice_still_wins_and_a_lone_turnaround_is_still_sent() -> None:
    aiko = _aiko(PORTRAIT, TURNAROUND)
    assert _sent(aiko, "gros plan", preferred={1: TURNAROUND}) == [TURNAROUND]
    assert _sent(aiko, "plan large", preferred={1: PORTRAIT}) == [PORTRAIT]
    assert _sent(_aiko(TURNAROUND), "gros plan") == [TURNAROUND]  # sa seule image
    imported = _aiko(99, TURNAROUND)  # image importée (sans fiche) : sans préférence, passe avant le plein pied
    assert _sent(imported, "gros plan") == [99]


def test_reference_sheets_declare_the_shots_they_serve() -> None:
    sheets = REG.reference_sheets
    assert "gros plan" in sheets["personnage-portrait"].shots and "plan moyen" in sheets["personnage-portrait"].shots
    assert set(sheets["personnage-turnaround"].shots) == {"plan large", "plan d'ensemble", "plan américain"}


# --- cadrage explicite et négatif ------------------------------------------------------------------
def test_medium_shot_brief_says_where_the_frame_cuts_the_body() -> None:
    settings = REG.image_prompt
    framing = camera_term("plan moyen", settings)
    assert "waist up" in framing and "legs out of frame" in framing
    brief = PromptBrief.build(description="Aiko court", plan="plan moyen", settings=settings)
    assert framing in brief.camera and framing in brief.as_json()["panel"]["camera"]
    assert "chest up" in camera_term("plan rapproché", settings)
    assert "face fills the frame" in camera_term("gros plan", settings)
    writer = REG.prompt("redacteur-image")
    assert "where the frame cuts" in writer.system


def test_tight_shots_fight_full_body_in_the_negative() -> None:
    settings = REG.image_prompt
    negative = build_negative_prompt("blurry", settings, plan="gros plan")
    assert all(term in negative for term in FULL_BODY) and negative.startswith("blurry")
    assert all(term in build_negative_prompt("", settings, plan="Plan moyen") for term in FULL_BODY)
    for plan in ("plan large", "plan américain", None):
        assert not is_tight_shot(plan, settings)
        assert "full body" not in build_negative_prompt("blurry", settings, plan=plan)


def test_tight_panel_job_gets_the_full_body_negative(env: Env) -> None:
    c = env.c
    data = _chapter(c, "gros plan", "plan large")
    tight, wide = data["panels"]
    negatives = {}
    for pid in (tight, wide):
        _generate(c, pid)
        [image] = _ok(c.get(f"/panels/{pid}/images"))
        negatives[pid] = image["params"]["negative_prompt"]
    assert all(term in negatives[tight] for term in FULL_BODY)
    assert "full body" not in negatives[wide]


# --- « Sources utilisées » (pack livré) -----------------------------------------------------------
def test_mock_panel_shows_the_pack_sheets_the_writer_received(pack_env: Env) -> None:
    c = pack_env.c
    data = _chapter(c, "gros plan")
    [pid] = data["panels"]
    assert _ok(c.get(f"/panels/{pid}"))["prompt_sources"] is None
    panel = _generate(c, pid)
    sources = panel["prompt_sources"]
    assert sources is not None and sources["written_at"]
    names = {p["collection_name"] for p in sources["passages"]}
    assert names and all(n.startswith("Mise en scène · ") for n in names)
    assert all(p["pack"] == "manga_visual_knowledge" for p in sources["passages"])
    # ce sont bien les passages envoyés au rédacteur pour ce prompt
    user = _writer_calls(pack_env.llm)[-1][-1].content
    assert all(f"« {p['document_title']} »" in user for p in sources["passages"])
