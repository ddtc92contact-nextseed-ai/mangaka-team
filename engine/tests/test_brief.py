"""Brief d'image d'une case (#227) : un rôle par champ, contrôlé à la sortie du scénariste, signalé case par case, et
garde-fou avant génération — cas tirés de l'audit du chapitre 15 « Second round » d'OSU (18/10)."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from mangaka_engine.pipeline.brief import (
    ABSENT,
    LOCATION,
    NO_DECOR,
    SHOT,
    SLOTS,
    panel_notes,
    slot_note,
    stored_page_notes,
    strip_absent,
)
from mangaka_engine.pipeline.layout import tree_to_json
from mangaka_engine.pipeline.names import CharacterMatcher
from mangaka_engine.pipeline.pages import layout_pages
from mangaka_engine.pipeline.script import (
    ScriptContext,
    brief_problems,
    parse_script,
    render_messages,
    run_script,
    save_script,
    slot_problems,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.store.models import Chapter, Character, GenerationLog
from tests.conftest import PRESETS_DIR, STYLE, start_script

REG = PresetRegistry.load(PRESETS_DIR)
PROMPT = REG.prompt("script")
RULES = PROMPT.brief_rules
OSU = ("Haru Kaneda", "Ren Shiba", "Tora Ōba", "noix de coco", "Directeur Kurogane")
MATCHER = CharacterMatcher(Character(id=i, name=n, aliases=[]) for i, n in enumerate(OSU, start=1))


def _notes(**fields: Any) -> list[Any]:
    return panel_notes(RULES, MATCHER, **{"description": "", "setting": "", "staging": "", "characters": [], **fields})


def _kinds(notes: list[Any]) -> dict[tuple[str, str], tuple[str, ...]]:
    return {(n.field, n.kind): n.names for n in notes}


# --- contrôles d'une case ------------------------------------------------------------------------
def test_tora_plan_and_characters_in_setting() -> None:
    """Case 595 : « Plan américain sur Tora, Haru et Ren en arrière-plan, noix de coco hors cadre »."""
    notes = _notes(
        description="Tora fait craquer ses phalanges, un sourcil levé.",
        setting="Plan américain sur Tora, Haru et Ren en arrière-plan, noix de coco hors cadre.",
        staging="Tora joint ses mains et les tord; Haru et Ren le regardent, déglutissant.",
        characters=["Tora Ōba"],
    )
    kinds = _kinds(notes)
    assert kinds[("setting", ABSENT)] == ("Haru Kaneda", "Ren Shiba", "noix de coco")
    assert kinds[("setting", SHOT)] == ("plan américain", "hors cadre")
    assert ("setting", NO_DECOR) in kinds  # aucun mot de décor : ni moment, ni lieu
    assert kinds[("staging", ABSENT)] == ("Haru Kaneda", "Ren Shiba")
    assert "Tora" not in " ".join(n for names in kinds.values() for n in names)  # présent : jamais signalé


def test_offscreen_cited_in_staging() -> None:
    """Case 607 : Haru et le gorille déclarés hors cadre, la mise en scène les fait agir."""
    notes = _notes(
        description="Ren lève la tête et lance une moquerie à Tora.",
        setting="Plage de sable blanc, fin d'après-midi, palmiers penchés",
        staging="Ren, appuyé sur un coude, sourit avec arrogance en direction de Tora. Tora, allongé, détourne le "
        "regard en grognant. Haru, à côté, lève un sourcil. Noix de coco observe en retrait.",
        characters=["Ren Shiba", "Tora Ōba"],
    )
    assert _kinds(notes) == {("staging", ABSENT): ("Haru Kaneda", "noix de coco")}
    assert "absents de « characters »" in notes[0].message


def test_setting_without_decor() -> None:
    """Case 634 : « Gros plan sur les yeux de Haru, la mèche collée sur le front » (plan, et aucun décor)."""
    kinds = _kinds(_notes(setting="Gros plan sur les yeux de Haru, la mèche collée sur le front.", characters=["Haru"]))
    assert set(kinds) == {("setting", SHOT), ("setting", NO_DECOR)}
    assert _kinds(_notes(setting="", characters=["Haru"])) == {("setting", NO_DECOR): ()}
    # Les mots du lieu de la case comptent comme décor.
    assert _notes(setting="sous le soleil", lieu="Plage de sable blanc") == []
    assert _notes(setting="au pied du grand banian", lieu="Le banian sacré") == []


def test_clean_brief_has_no_note() -> None:
    assert (
        _notes(
            description="Haru court un pas devant Ren, tourne la tête vers lui avec une grimace moqueuse.",
            setting="Sable mou avec des traces de pas, midi, quelques rochers au loin",
            staging="Haru à gauche, la main levée ; Ren à droite, dents serrées, poings fermés",
            characters=["Haru Kaneda", "Ren Shiba"],
            lieu="Plage de sable blanc",
            lieux=["Plage de sable blanc", "Pont du bateau"],
        )
        == []
    )


def test_wrong_location_is_detected() -> None:
    """Case 589 : l'action est sur le pont du bateau, le lieu en base est la plage."""
    notes = _notes(
        description="Depuis le pont du bateau, Kurogane observe la course au loin.",
        setting="bastingage, mer calme, midi",
        characters=["Directeur Kurogane"],
        lieu="Plage de sable blanc",
        lieux=["Plage de sable blanc", "Pont du bateau"],
    )
    assert _kinds(notes) == {("lieu", LOCATION): ("Pont du bateau",)}
    # Sans autre lieu nommé (ou quand la description parle aussi du lieu de la case) : rien.
    assert (
        _notes(description="Le bateau au large", setting="mer", lieu="Plage", lieux=["Plage", "Pont du bateau"]) == []
    )


def test_page_with_more_panels_than_slots() -> None:
    """Page 4 : 6 cases sur le gabarit « 5-grand-cote » à 5 emplacements."""
    note = slot_note(6, 5, "5 cases, grande sur le côté")
    assert note is not None and note.kind == SLOTS
    assert note.message.startswith("6 cases pour 5 emplacements du gabarit « 5 cases, grande sur le côté »")
    assert slot_note(5, 5, "x") is None
    tpl = REG.layout_templates["5-grand-cote"]
    page = SimpleNamespace(
        layout={"template_id": tpl.id, "tree": tree_to_json(tpl.tree)},
        panels=[SimpleNamespace(frame=None) for _ in range(6)],
    )
    [stored] = stored_page_notes(RULES, page, {tpl.id: tpl.name})
    assert f"6 cases pour 5 emplacements du gabarit « {tpl.name} »" in stored.message
    # Dans la boucle du scénariste (mise en page à blanc) : numérotée comme dans la réponse.
    assert slot_problems(REG, [page], RULES) == [f"page 1 › gabarit › {stored.message}"]
    # Une incrustation imposée à la main par l'auteur est son choix.
    page.panels[5].frame = {"inset": True}
    assert stored_page_notes(RULES, page, {tpl.id: tpl.name}) == []


def test_terms_come_from_the_preset() -> None:
    assert RULES is not None and "plan américain" in RULES.shot_terms and "plage" in RULES.decor_terms
    no_terms = RULES.model_copy(update={"shot_terms": [], "decor_terms": []})
    notes = panel_notes(no_terms, MATCHER, description="", setting="Gros plan sur la plage", staging="", characters=[])
    assert _kinds(notes) == {("setting", NO_DECOR): ()}


# --- relance du scénariste -----------------------------------------------------------------------
def _ctx() -> ScriptContext:
    return ScriptContext(
        series={"title": "OSU", "style": "encre", "reading_direction": "rtl"},
        characters=[{"name": n, "description": ""} for n in OSU],
        previous_chapters=[],
        chapter={"number": 15, "title": "Second round", "synopsis": "Course sur la plage.", "target_pages": 1},
    )


def _answer(setting: str, staging: str) -> str:
    panels = [
        {
            "description": "Tora fait craquer ses phalanges, un sourcil levé.",
            "setting": setting,
            "staging": staging,
            "characters": ["Tora Ōba"],
            "offscreen": ["Haru Kaneda", "Ren Shiba"],
            "lieu": "Plage de sable blanc",
            "dialogues": [
                {"speaker": "Tora Ōba", "text": "Vous allez voir.", "kind": "speech"},
                {"speaker": "Tora Ōba", "text": "Trop facile.", "kind": "thought"},
            ],
        },
        {
            "description": "Haru court un pas devant Ren, tourne la tête vers lui.",
            "setting": "sable mou, traces de pas, midi",
            "staging": "Haru grimace ; Ren serre les dents",
            "characters": ["Haru Kaneda", "Ren Shiba"],
            "lieu": "Plage de sable blanc",
        },
    ]
    return json.dumps({"pages": [{"panels": panels}], "summary": "La course reprend."}, ensure_ascii=False)


DIRTY = _answer("Plan américain sur Tora, Haru et Ren en arrière-plan", "Tora tord ses mains; Haru et Ren déglutissent")
CLEAN = _answer(
    "plage de sable blanc, midi, palmiers penchés", "Tora au premier plan, les mains jointes, l'œil narquois"
)


def test_brief_defects_are_sent_back_to_the_scenarist() -> None:
    assert brief_problems(parse_script(CLEAN), _ctx(), RULES) == []
    problems = brief_problems(parse_script(DIRTY), _ctx(), RULES)
    assert any(p.startswith("page 1 › case 1 › « Décor de la case » cite Haru Kaneda, Ren Shiba") for p in problems)
    answers = iter([DIRTY, CLEAN])
    llm = MockLLMProvider(lambda _m, _j: next(answers))
    run = run_script(llm, PROMPT, _ctx(), lambda _p, _m: None)
    assert run.attempts == 2 and run.warnings == []
    retry = llm.calls[1][-1].content
    assert "brief d'image à revoir" in retry and "plan américain" in retry and "absents de « characters »" in retry


def test_persistent_defects_are_kept_as_warnings() -> None:
    llm = MockLLMProvider(lambda _m, _j: DIRTY)
    run = run_script(llm, PROMPT, _ctx(), lambda _p, _m: None)
    assert run.attempts == 3 and len(llm.calls) == 3
    assert any("« Décor de la case » écrit un plan" in w for w in run.warnings)


def test_roles_are_written_in_the_scenarist_prompt() -> None:
    _system, user = render_messages(PROMPT, _ctx())
    text = user.content
    assert "« setting » (décor de la case) : le MOMENT" in text and "jamais de nom de personnage" in text
    assert "des SEULS personnages de « characters »" in text and "il ne la reformule pas" in text
    assert "INSTANT FIGÉ" in text and "« Haru double Ren » → « Haru court un pas devant Ren" in text
    assert "le pont du bateau n'est pas la plage" in text
    assert "Précision de cadrage" not in text and "précision de cadrage" not in text
    scene = REG.prompts["script-scene"].user
    assert "jamais de nom de personnage" in scene and "le pont du bateau" in scene


# --- de bout en bout (LLM factice) ---------------------------------------------------------------
def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _osu(c: TestClient, synopsis: str, *, ai_prompt: bool = False) -> dict[str, Any]:
    s = _ok(c.post("/projects", json={**STYLE, "title": "OSU", "ai_prompt": ai_prompt}), 201)
    cards = {}
    for k, name in enumerate(OSU[:4]):
        cards[name] = _ok(
            c.post(f"/projects/{s['id']}/characters", json={"name": name, "visual_description": f"{name}, silhouette"}),
            201,
        )
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (40 * k, 200 - 40 * k, 90)).save(buf, format="PNG")
        files = [("files", (f"{k}.png", buf.getvalue(), "image/png"))]
        _ok(c.post(f"/characters/{cards[name]['id']}/images", files=files), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"synopsis": synopsis, "target_page_count": 3}), 201)
    return {"series": s, "chapter": ch, "cards": cards}


def _decouper(c: TestClient, chapter_id: int) -> dict[str, Any]:
    job = _ok(start_script(c, chapter_id), 202)
    c.app.state.ctx.jobs.wait(job["id"])  # type: ignore[attr-defined]
    done = _ok(c.get(f"/jobs/{job['id']}"))
    assert done["status"] == "succeeded", done["error"]
    return done


def _panels(c: TestClient, chapter_id: int) -> list[dict[str, Any]]:
    return [p for page in _ok(c.get(f"/chapters/{chapter_id}/pages")) for p in page["panels"]]


def test_mock_dirty_brief_is_retried_then_clean(client: TestClient) -> None:
    d = _osu(client, "Haru, Ren et Tora courent sur la plage. Le gorille les rattrape. [mock:brief-sale:1]")
    done = _decouper(client, d["chapter"]["id"])
    assert "en 2 essais" in done["message"] and "avertissement" not in done["message"]
    assert all(p["brief_notes"] == [] for p in _panels(client, d["chapter"]["id"]))


def test_mock_dirty_brief_that_persists_is_flagged_panel_by_panel(client: TestClient) -> None:
    d = _osu(client, "Haru, Ren et Tora courent sur la plage. Le gorille les rattrape. [mock:brief-sale:9]")
    done = _decouper(client, d["chapter"]["id"])
    assert "en 3 essais" in done["message"] and "brief d'image" in done["message"]
    flagged = [p for p in _panels(client, d["chapter"]["id"]) if p["brief_notes"]]
    assert len(flagged) == 3
    first, second, third = ({(n["field"], n["kind"]) for n in p["brief_notes"]} for p in flagged)
    assert {("setting", "plan"), ("setting", "personnage absent")} <= first
    assert ("staging", "personnage absent") in second
    assert ("setting", "sans décor") in third
    assert all(n["message"] for p in flagged for n in p["brief_notes"])


# --- garde-fou avant génération --------------------------------------------------------------------
def test_strip_absent_removes_sentences_and_fragments() -> None:
    present = {2, 3}  # Ren, Tora
    text = (
        "Only Ren Shiba and Tora Ōba in the frame, nobody else. Setting: Sur la plage, les garçons affalés sur le "
        "sable, noix de coco debout à proximité. Staging: Ren, appuyé sur un coude, sourit. Haru, à côté, lève un "
        "sourcil. Noix de coco observe en retrait."
    )
    out, removed = strip_absent(MATCHER, text, present)
    assert "coco" not in out.casefold() and "Haru" not in out
    assert "Only Ren Shiba and Tora Ōba in the frame, nobody else." in out
    assert "Setting: Sur la plage, les garçons affalés sur le sable." in out
    assert "Ren, appuyé sur un coude, sourit." in out
    assert {r["name"] for r in removed} == {"Haru Kaneda", "noix de coco"}
    # Rien à retirer : texte inchangé.
    assert strip_absent(MATCHER, "Ren sourit.", present) == ("Ren sourit.", [])
    # Le nom seul quand l'absent n'est pas le sujet du morceau.
    out, removed = strip_absent(MATCHER, "Haru, assis, serre les poings et fusille Ren du regard.", {1})
    assert out == "Haru, assis, serre les poings et fusille du regard."
    assert removed == [{"name": "Ren Shiba", "removed": "Ren"}]
    # Le nom complet tel qu'écrit, pas seulement le prénom, avec ou sans accents.
    out, removed = strip_absent(MATCHER, "Haru Kaneda regarde Ren Shiba avec colère.", {1})
    assert out == "Haru Kaneda regarde avec colère."
    assert removed == [{"name": "Ren Shiba", "removed": "Ren Shiba"}]
    out, removed = strip_absent(MATCHER, "(Ren Shiba et Tora Ōba, page 1, case 2)", {2})
    assert "Tora" not in out and "Ōba" not in out and "Ren Shiba" in out
    assert removed == [{"name": "Tora Ōba", "removed": "Tora Ōba"}]
    out, _ = strip_absent(MATCHER, "Haru Kaneda fixe Tora Oba, puis Tora.", {1})
    assert "Tora" not in out and "Oba" not in out
    # Case de décor : plus aucun nom de fiche.
    out, _ = strip_absent(MATCHER, "No character in the frame. Staging: Tora et Ren courent.", set())
    assert out == "No character in the frame."


def test_generated_prompt_never_names_an_offscreen_character(client: TestClient) -> None:
    """Case 608 : Haru seul à l'image, Ren, Tora et le gorille hors cadre mais cités par la mise en scène."""
    d = _osu(client, "Haru défend son grand-père.")
    raw = json.dumps(
        {
            "pages": [
                {
                    "panels": [
                        {
                            "description": "Haru, assis, serre les poings, la mâchoire crispée.",
                            "setting": "plage, le sable autour, midi",
                            "staging": "Haru, assis, serre les poings et fusille Ren Shiba du regard. Ren hausse un "
                            "sourcil, amusé. Tora le regarde, étonné. Noix de coco penche la tête, près de "
                            "Haru et de Tora Ōba.",
                            "characters": ["Haru Kaneda"],
                            "offscreen": ["Ren Shiba", "Tora Ōba", "noix de coco"],
                        }
                    ]
                }
            ],
            "summary": "Haru se défend.",
        },
        ensure_ascii=False,
    )
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        chapter = session.get(Chapter, d["chapter"]["id"])
        assert chapter is not None
        layout_pages(REG, save_script(session, chapter, parse_script(raw)))
        session.commit()
    [panel] = _panels(client, d["chapter"]["id"])
    assert panel["characters"] == ["Haru Kaneda"]
    [job] = _ok(client.post(f"/panels/{panel['id']}/generate"), 202)
    assert client.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]
    assert _ok(client.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    image = next(i for i in _ok(client.get(f"/panels/{panel['id']}/images")) if i["params"]["job_id"] == job["id"])
    # Le prompt construit cite encore les absents (texte de la case)…
    assert "Tora" in _ok(client.get(f"/panels/{panel['id']}"))["final_prompt"]
    # … le prompt envoyé à ComfyUI, jamais.
    sent = image["params"]["prompt"]
    assert "Haru Kaneda" in sent
    for name in ("Ren", "Shiba", "Tora", "Ōba", "coco"):
        assert name not in sent, name
    assert {g["name"] for g in image["params"]["prompt_guard"]} == {"Ren Shiba", "Tora Ōba", "noix de coco"}
    # Trace dans le journal de la case.
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        log = session.scalars(select(GenerationLog).where(GenerationLog.job_id == job["id"])).one()
        assert {g["name"] for g in log.prompt_guard} == {"Ren Shiba", "Tora Ōba", "noix de coco"}
        assert "Tora" not in log.positive_prompt
