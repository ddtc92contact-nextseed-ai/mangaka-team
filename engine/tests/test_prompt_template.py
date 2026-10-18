"""Prompt image « gabarit » (#228) : prompt court assemblé par le moteur, choisi par série."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.prompt import ReferenceSlot, found_terms
from mangaka_engine.pipeline.prompt_template import (
    TemplateBrief,
    TemplateSource,
    TemplateWriterError,
    frame_template,
    summarize,
    template_body,
    write_action,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import ChatMessage, MockLLMProvider
from mangaka_engine.providers.llm.mock import mock_template_action
from tests.conftest import LEAD, PRESETS_DIR, STYLE, png_bytes

PRESETS = PresetRegistry.load(PRESETS_DIR)
SETTINGS = PRESETS.image_prompt
WRITER = PRESETS.prompt("redacteur-image-gabarit")
SHEET = "<image1> is the model sheet of Aiko."
SORTING = "Take only each character's face, hair, body and outfit from the sheets, not their layout, rulers or labels."


def _brief(**kw: Any) -> TemplateBrief:
    values: dict[str, Any] = {
        "description": "Aiko bondit vers Kenji. « Fuyez ! » crie-t-elle.",
        "setting": "plage de l'île au crépuscule",
        "staging": "Aiko à gauche, Kenji à droite",
        "plan": "plan moyen",
        "characters": [
            TemplateSource("Aiko", "short black hair, pale skin, red kimono with a white sash"),
            TemplateSource(
                "Kenji", "", "Grand et mince, lunettes rondes, veste en jean délavé, baskets blanches, sac à dos"
            ),
        ],
        "absent": ["Ren", "Gorille"],
        "place": "La plage",
        "decor_description": "sable fin, palmiers penchés, cabane en bois, vagues, rochers noirs, ponton",
        "references": [ReferenceSlot("character", "Aiko"), ReferenceSlot("decor", "La plage")],
        "style_lead": LEAD.strip(),
        "settings": SETTINGS,
    }
    values.update(kw)
    return TemplateBrief.build(**values)


def _action(brief: TemplateBrief) -> tuple[str, str | None]:
    out = mock_template_action(brief.as_json())
    return out["action"], out["setting"]


def _sent(brief: TemplateBrief, **kw: Any) -> str:
    action, setting = _action(brief)
    body = template_body(brief, SETTINGS, action=action, setting=setting, **kw)
    return frame_template(body, brief.references, SETTINGS)


# --- assemblage (pur) -------------------------------------------------------------
def test_blocks_come_in_the_template_order() -> None:
    brief = _brief()
    sent = _sent(brief)
    markers = [
        SHEET,  # 1. une ligne par image envoyée
        "<image2> is the location La plage.",
        SORTING,  # 2. UNE consigne de tri commune
        "Aiko: short black hair, pale skin, red kimono with a white sash.",  # 3. ancres des présents
        "Kenji: Grand et mince",
        "The characters of this panel are Aiko, Kenji; each appears once; every character has two arms and two hands; "
        "no other people.",  # 4. règles
        "No text, no speech bubbles.",
        "Setting: La plage",  # 5. décor court
        LEAD.strip(),  # 6. style
        "Medium shot, framed from the waist up, legs out of frame.",  # 7. la case : plan, puis action
        "Aiko ",
    ]
    positions = [sent.index(m) if m != "Aiko " else sent.rindex(m) for m in markers]
    assert positions == sorted(positions), sent
    assert sent.startswith(SHEET)
    # rien du mode détaillé : ni tri par fiche, ni paragraphe « identité seulement », ni anti-doublon
    assert "From <image1>" not in sent and "Use the reference images" not in sent
    assert "Each character appears only once" not in sent and "not a character sheet" not in sent
    assert sent.count(SORTING) == 1


def test_only_present_characters_appear() -> None:
    brief = _brief(description="Aiko court vers la mer.", characters=[TemplateSource("Aiko", "short black hair")])
    sent = _sent(brief)
    assert "Kenji" not in sent and "Ren" not in sent and "Gorille" not in sent
    assert "The characters of this panel are Aiko;" in sent
    assert sent.count("Aiko:") == 1


def test_panel_without_character_says_no_people() -> None:
    brief = _brief(
        description="La plage déserte.", characters=[], staging="", references=[ReferenceSlot("decor", "La plage")]
    )
    sent = _sent(brief)
    assert "No people." in sent and "The characters of this panel" not in sent
    assert SORTING not in sent  # aucune fiche de personnage envoyée


def test_short_setting_in_tight_shot_detailed_in_wide_shot() -> None:
    tight = _brief(plan="gros plan")
    wide = _brief(plan="plan large")
    tight_prompt, wide_prompt = _sent(tight), _sent(wide)
    assert "Details of the place" not in tight_prompt and "ponton" not in tight_prompt
    assert "Details of the place: sable fin, palmiers penchés" in wide_prompt and "ponton" in wide_prompt
    # le décor court reste dans les deux : le lieu et ses 4 premiers éléments (repli du moteur)
    engine = template_body(tight, SETTINGS)
    assert "Setting: La plage, sable fin, palmiers penchés, cabane en bois, vagues." in engine
    assert "rochers" not in engine
    plan_ensemble = _brief(plan="plan d'ensemble")
    assert "Details of the place" in template_body(plan_ensemble, SETTINGS)


@pytest.mark.parametrize("plan", ["plan moyen", "plan large", "gros plan"])
def test_length_stays_in_the_target(plan: str) -> None:
    sent = _sent(_brief(plan=plan))
    words = len(sent.split())
    assert SETTINGS.template.min_words <= words <= SETTINGS.template.max_words, (words, sent)


def test_falls_back_on_the_description_when_the_llm_fails() -> None:
    brief = _brief()

    def bad(_messages: list[ChatMessage], _json: bool) -> str:
        return json.dumps({"action": "Aiko poses for a photo, shallow depth of field.", "language": "en"})

    llm = MockLLMProvider(responder=bad)
    with pytest.raises(TemplateWriterError, match="réponse invalide 2 fois"):
        write_action(llm, WRITER, brief)
    assert len(llm.calls) == 2  # une relance au plus
    body = template_body(brief, SETTINGS)  # repli : la description de la case, sans la réplique
    assert body.endswith(
        "Medium shot, framed from the waist up, legs out of frame. Aiko bondit vers Kenji. crie-t-elle."
    )
    assert "Fuyez" not in body


def test_writer_refuses_an_absent_character_and_too_many_words_then_retries() -> None:
    brief = _brief()
    answers = iter(
        [
            json.dumps({"action": "Aiko leaps at Kenji while Ren watches.", "language": "en"}),
            json.dumps(
                {
                    "action": "Aiko leaps toward Kenji on the left, fierce; Kenji flinches on the right.",
                    "language": "en",
                }
            ),
        ]
    )
    llm = MockLLMProvider(responder=lambda _m, _j: next(answers))
    run = write_action(llm, WRITER, brief)
    assert run.attempts == 2 and "Ren" not in run.output.action
    assert "personnages absents de la case nommés (à retirer) : Ren" in llm.calls[1][-1].content
    too_long = json.dumps({"action": " ".join(["Aiko runs."] * 40), "language": "en"})
    with pytest.raises(TemplateWriterError, match="action trop longue"):
        write_action(MockLLMProvider(responder=lambda _m, _j: too_long), WRITER, brief)


def test_black_and_white_series_has_no_colour_words() -> None:
    brief = _brief(
        description="Aiko renverse le liquide vert épais.",
        characters=[TemplateSource("Aiko", "short black hair, red kimono with a golden sash")],
        decor_description="sable doré, mer turquoise, palmiers verts",
        plan="plan large",
        monochrome=True,
    )
    sent = _sent(brief)
    assert found_terms(sent, SETTINGS.monochrome_forbidden_terms) == []
    assert "short black hair, kimono" in sent  # « black » est une valeur du noir et blanc : il reste
    with pytest.raises(TemplateWriterError, match="mots de couleur interdits : red"):
        coloured = json.dumps({"action": "Aiko spills a red liquid on the left.", "language": "en"})
        write_action(MockLLMProvider(responder=lambda _m, _j: coloured), WRITER, brief)


def test_object_line_names_and_describes_the_object() -> None:
    brief = _brief(references=[ReferenceSlot("character", "Aiko"), ReferenceSlot("vehicle", "Le Faucon")])
    body = template_body(brief, SETTINGS)
    sent = frame_template(
        body, brief.references, SETTINGS, descriptions={"Le Faucon": "petit voilier blanc à coque fine"}
    )
    assert sent.startswith(f"{SHEET} <image2> is Le Faucon, petit voilier blanc à coque fine. {SORTING}")
    bare = frame_template(body, [ReferenceSlot("object", "Robot")], SETTINGS)
    assert bare.startswith("<image1> is Robot. Aiko:")  # sans description ; pas de tri sans fiche de personnage
    # une ligne déjà écrite (prompt édité à la main) n'est pas doublée
    assert frame_template(f"{SHEET} {body}", brief.references[:1], SETTINGS).count(SHEET) == 1


def test_summary_of_a_description_replaces_an_empty_anchor() -> None:
    assert summarize("Grand gorille. Jean délavé, ceinture de cuir, torse nu.", 15) == (
        "Grand gorille, jean délavé, ceinture de cuir, torse nu"
    )
    long = "cheveux longs noirs, yeux verts, cicatrice sur la joue gauche, manteau gris très long, bottes hautes en cuir noir"
    assert len(summarize(long, 15).split()) <= 15


# --- de bout en bout (API, LLM et ComfyUI factices) ---------------------------------------
class Env:
    def __init__(self, c: TestClient, llm: MockLLMProvider) -> None:
        self.c, self.llm = c, llm


@pytest.fixture
def env(make_settings: Callable[..., Settings]) -> Iterator[Env]:
    llm = MockLLMProvider()
    providers = Providers(
        llm=llm,
        vision=None,
        comfyui=MockComfyUIClient(),
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(make_settings(), providers=providers)) as c:
        yield Env(c, llm)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _wait(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]


def _setup(c: TestClient, description: str = "Aiko bondit vers Kenji. « Fuyez ! » crie-t-elle.", **series: Any) -> dict:
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames", **series}), 201)
    aiko = _ok(
        c.post(
            f"/projects/{s['id']}/characters",
            json={"name": "Aiko", "visual_description": "cheveux noirs courts, kimono", "prompt_keywords": ["sabre"]},
        ),
        201,
    )
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    kenji = _ok(
        c.post(f"/projects/{s['id']}/characters", json={"name": "Kenji", "visual_description": "grand, lunettes"}), 201
    )
    _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Ren", "visual_description": "manteau gris"}), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {
                                "description": description,
                                "characters": ["Aiko", "Kenji"],
                                "shot_type": "plan moyen",
                                "setting": "toit d'un lycée sous la pluie",
                                "staging": "Aiko à gauche, Kenji à droite",
                            }
                        ]
                    }
                ]
            },
        )
    )
    return {"series": s, "chapter": ch, "panel": pages[0]["panels"][0], "aiko": aiko, "kenji": kenji}


def _generate(c: TestClient, panel_id: int) -> dict:
    _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    _wait(c)
    return _ok(c.get(f"/panels/{panel_id}"))


def _template_calls(llm: MockLLMProvider) -> list[list[ChatMessage]]:
    return [m for m in llm.calls if any('"task": "image_prompt_template"' in x.content for x in m)]


def test_series_mode_defaults_to_detailed_and_is_saved(env: Env) -> None:
    c = env.c
    assert _ok(c.get("/presets"))["defaults"]["image_prompt_mode"] == "détaillé"
    data = _setup(c)
    sid, pid = data["series"]["id"], data["panel"]["id"]
    assert data["series"]["image_prompt_mode"] == "détaillé"
    assert _ok(c.get(f"/panels/{pid}"))["prompt_mode"] == "détaillé"
    assert _ok(c.patch(f"/projects/{sid}", json={"image_prompt_mode": "gabarit"}))["image_prompt_mode"] == "gabarit"
    assert _ok(c.get(f"/projects/{sid}"))["image_prompt_mode"] == "gabarit"
    assert _ok(c.get(f"/panels/{pid}"))["prompt_mode"] == "gabarit"
    assert c.patch(f"/projects/{sid}", json={"image_prompt_mode": "court"}).status_code == 422
    created = _ok(c.post("/projects", json={**STYLE, "title": "Courte", "image_prompt_mode": "gabarit"}), 201)
    assert created["image_prompt_mode"] == "gabarit"


def test_generation_in_template_mode_sends_the_short_prompt(env: Env) -> None:
    c = env.c
    data = _setup(c, image_prompt_mode="gabarit")
    pid = data["panel"]["id"]
    assert _ok(c.get(f"/panels/{pid}"))["prompt_pending"] is True
    panel = _generate(c, pid)
    assert panel["prompt_source"] == "gabarit" and panel["prompt_warning"] is None
    assert panel["prompt_pending"] is False
    [call] = _template_calls(env.llm)
    # ni savoir-faire, ni bible, ni minimum de mots, ni règle anti-redescription chez le rédacteur
    text = "\n".join(m.content for m in call)
    assert "re-describe" not in text and "know-how" not in text and "180" not in text
    assert "Aiko à gauche" in text and "Fuyez" not in text

    [img] = panel["images"]
    sent = img["params"]["prompt"]
    assert img["params"]["prompt_mode"] == "gabarit"
    assert sent.startswith(f"{SHEET} {SORTING} Aiko: cheveux noirs courts, kimono. Kenji: grand, lunettes. ")
    assert "The characters of this panel are Aiko, Kenji; each appears once" in sent
    assert "Ren" not in sent.split() and "From <image1>" not in sent and "Use the reference images" not in sent
    assert "Each character appears only once" not in sent
    assert "Medium shot, framed from the waist up, legs out of frame. Aiko " in sent
    assert len(sent.split()) <= SETTINGS.template.max_words  # fiches très courtes ici : la cible basse n'est pas visée
    # le prompt final de la case (éditable) : le même sans les lignes des images ; négatif inchangé
    assert sent.endswith(panel["final_prompt"]) and "<image1>" not in panel["final_prompt"]
    assert "speech bubble" in img["params"]["negative_prompt"] and "full body" in img["params"]["negative_prompt"]

    # « Régénérer » respecte le mode de la série ; l'action n'est pas redemandée
    again = _generate(c, pid)
    assert [i["params"]["prompt_mode"] for i in again["images"]] == ["gabarit", "gabarit"]
    assert len(_template_calls(env.llm)) == 1

    # retour au mode détaillé : le prompt automatique repart dans ce mode
    _ok(c.patch(f"/projects/{data['series']['id']}", json={"image_prompt_mode": "détaillé"}))
    back = _ok(c.get(f"/panels/{pid}"))
    assert back["prompt_mode"] == "détaillé" and back["prompt_source"] == "fragments" and back["prompt_pending"] is True
    detailed = _generate(c, pid)
    assert detailed["prompt_source"] == "ia" and detailed["images"][-1]["params"]["prompt_mode"] == "détaillé"
    assert "From <image1> take only the face" in detailed["images"][-1]["params"]["prompt"]


def test_invalid_action_twice_falls_back_on_the_description_with_a_warning(env: Env) -> None:
    c = env.c
    data = _setup(c, description="Aiko bondit vers Kenji. [mock:gabarit-invalide:2]", image_prompt_mode="gabarit")
    panel = _generate(c, data["panel"]["id"])
    assert len(_template_calls(env.llm)) == 2  # une relance au plus
    assert panel["prompt_source"] == "gabarit" and "description de la case utilisée" in panel["prompt_warning"]
    assert "legs out of frame. Aiko bondit vers Kenji." in panel["final_prompt"]
    assert "telephoto" not in panel["images"][0]["params"]["prompt"]


def test_rebuild_rewrites_the_action_in_template_mode(env: Env) -> None:
    c = env.c
    data = _setup(c, image_prompt_mode="gabarit")
    pid = data["panel"]["id"]
    rebuilt = _ok(c.post(f"/panels/{pid}/prompt/rebuild"))
    assert rebuilt["prompt_source"] == "gabarit" and len(_template_calls(env.llm)) == 1
    assert "Setting: toit d'un lycée sous la pluie." in rebuilt["final_prompt"]


def test_visual_anchor_is_proposed_saved_and_used(env: Env) -> None:
    c = env.c
    data = _setup(c, image_prompt_mode="gabarit")
    aiko = data["aiko"]["id"]
    assert data["aiko"]["visual_anchor"] == ""
    proposed = _ok(c.post(f"/characters/{aiko}/visual-anchor/propose", json={}))["visual_anchor"]
    assert proposed and "Aiko" not in proposed and "cheveux noirs courts" in proposed
    # la description du formulaire (pas encore enregistrée) passe avant celle de la fiche
    draft = _ok(
        c.post(
            f"/characters/{aiko}/visual-anchor/propose", json={"visual_description": "Aiko, short black hair, white gi"}
        )
    )["visual_anchor"]
    assert draft == "short black hair, white gi, sabre"  # mots-clés de la fiche compris
    # rien n'est enregistré tant que l'auteur ne valide pas
    assert _ok(c.get(f"/characters/{aiko}"))["visual_anchor"] == ""
    saved = _ok(c.patch(f"/characters/{aiko}", json={"visual_anchor": draft}))
    assert saved["visual_anchor"] == draft
    panel = _ok(c.post(f"/panels/{data['panel']['id']}/prompt/rebuild"))
    assert "Aiko: short black hair, white gi, sabre." in panel["final_prompt"]
    assert _ok(c.get(f"/panels/{data['panel']['id']}"))["prompt_pending"] is False
    # une fiche sans description : erreur lisible
    empty = _ok(c.post(f"/projects/{data['series']['id']}/characters", json={"name": "Vide"}), 201)
    resp = c.post(f"/characters/{empty['id']}/visual-anchor/propose", json={})
    assert resp.status_code == 422 and "description visuelle" in resp.text


def test_new_anchor_makes_the_action_pending_again(env: Env) -> None:
    c = env.c
    data = _setup(c, image_prompt_mode="gabarit")
    pid = data["panel"]["id"]
    _generate(c, pid)
    assert _ok(c.get(f"/panels/{pid}"))["prompt_pending"] is False
    _ok(c.patch(f"/characters/{data['kenji']['id']}", json={"visual_anchor": "tall, round glasses, denim jacket"}))
    assert _ok(c.get(f"/panels/{pid}"))["prompt_pending"] is True
    panel = _generate(c, pid)
    assert "Kenji: tall, round glasses, denim jacket." in panel["images"][-1]["params"]["prompt"]
