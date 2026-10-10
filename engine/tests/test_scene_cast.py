"""Cases fidèles au scénario : tous les personnages, lieu et mise en scène, références pour l'identité seulement."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from mangaka_engine.pipeline.names import CharacterMatcher, name_key
from mangaka_engine.pipeline.pages import layout_pages
from mangaka_engine.pipeline.prompt import ReferenceSlot, build_prompt, character_count, frame_references
from mangaka_engine.pipeline.script import ScriptOutput, save_script
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.store.models import Chapter, Character
from tests.conftest import PRESETS_DIR, STYLE, png_bytes

REG = PresetRegistry.load(PRESETS_DIR)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _cards(*specs: tuple[int, str, list[str]]) -> CharacterMatcher:
    return CharacterMatcher(Character(id=i, name=n, aliases=a) for i, n, a in specs)


# --- rapprochement des noms ------------------------------------------------------------------
def test_name_key_ignores_case_accents_and_punctuation() -> None:
    assert name_key("  Élise-Marie  d’Arc ") == "elise marie d arc"
    assert name_key("URUS") == name_key("urus") == "urus"


def test_matching_case_accents_partial_and_alias() -> None:
    m = _cards((1, "Urus", ["le petit dragon"]), (2, "Kaël", []), (3, "Aiko Tanaka", []))
    assert m.match("Urus") == m.match("URUS") == m.match("urus") == 1
    assert m.match("Kael") == m.match("KAËL") == 2  # sans accent
    assert m.match("Urus le dragon") == 1  # nom de la fiche dans le nom écrit
    assert m.match("le petit dragon") == m.match("Le Petit Dragon !") == 1  # alias
    assert m.match("Aiko") == 3  # nom écrit dans le nom de la fiche
    assert m.match("le dragon rouge") is None and m.match("") is None
    assert m.match("le") is None  # un article seul ne désigne personne
    assert m.ids(["Urus le dragon", "kael", "URUS", "un passant"]) == [1, 2]
    assert m.unmatched(["Urus le dragon", "un passant", "le dragon rouge"]) == ["un passant", "le dragon rouge"]


def test_ambiguous_partial_match_is_left_to_the_author() -> None:
    m = _cards((1, "Urus le dragon", []), (2, "Kael le dragon", []))
    assert m.match("le dragon") is None  # deux fiches à égalité : jamais de choix au hasard
    assert m.match("Urus") == 1 and m.match("Kael le dragon") == 2
    # La correspondance la plus longue l'emporte.
    m = _cards((1, "Aiko", []), (2, "Aiko Tanaka", []))
    assert m.match("Aiko Tanaka la lycéenne") == 2 and m.match("Aiko") == 1


# --- prompt image -------------------------------------------------------------------------------
def test_prompt_has_setting_staging_and_character_count() -> None:
    prompt = build_prompt(
        description="Les deux dragons se retrouvent",
        setting="clairière au bord d'un lac, fin d'après-midi, herbes hautes",
        staging="Urus au premier plan à gauche, Kael posé sur un rocher à droite",
        shot_type="plan large",
        characters=[],
        settings=REG.image_prompt,
    )
    assert "Lieu : clairière au bord d'un lac, fin d'après-midi, herbes hautes." in prompt
    assert "Mise en scène : Urus au premier plan à gauche, Kael posé sur un rocher à droite." in prompt
    assert "personnage" not in prompt  # aucun personnage : la ligne est omise
    # Sans lieu ni mise en scène (cases d'avant), les lignes sont omises.
    assert "Lieu :" not in build_prompt(description="x", settings=REG.image_prompt)
    assert (character_count(1), character_count(2), character_count(12)) == (
        "Un personnage",
        "Deux personnages",
        "12 personnages",
    )


def test_reference_framing_names_each_image_in_slot_order() -> None:
    slots = [ReferenceSlot("character", "Urus"), ReferenceSlot("character", "Kael"), ReferenceSlot("decor", "Lac")]
    framed = frame_references("Plan large. Deux dragons", slots, REG.image_prompt)
    assert framed.startswith(
        "Image 1 : référence d'identité de Urus ; Image 2 : référence d'identité de Kael ; "
        "Image 3 : référence du lieu Lac. Plan large. Deux dragons. "
    )
    assert "ne servent qu'à l'identité" in framed and "ni leur fond blanc" in framed
    assert frame_references("Sans image", [], REG.image_prompt) == "Sans image"


# --- de bout en bout (mock) ---------------------------------------------------------------------
def _dragons(c: TestClient, *, images: bool = True, ai_prompt: bool = False) -> dict[str, Any]:
    # Prompt par fragments par défaut : ces tests vérifient l'assemblage (voir test_prompt_writer.py).
    s = _ok(c.post("/projects", json={**STYLE, "title": "Dragons", "ai_prompt": ai_prompt}), 201)
    urus = _ok(
        c.post(
            f"/projects/{s['id']}/characters",
            json={"name": "Urus", "visual_description": "dragon bleu, cornes torsadées"},
        ),
        201,
    )
    kael = _ok(
        c.post(f"/projects/{s['id']}/characters", json={"name": "Kaël", "visual_description": "dragon rouge, ailes"}),
        201,
    )
    if images:
        for card in (urus, kael):
            files = [("files", (f"{card['name']}-{i}.png", png_bytes(), "image/png")) for i in range(2)]
            _ok(c.post(f"/characters/{card['id']}/images", files=files), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Deux", "synopsis": "Urus retrouve Kaël."}), 201)
    return {"series": s, "urus": urus, "kael": kael, "chapter": ch}


def _save(c: TestClient, chapter_id: int, panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = ScriptOutput.model_validate({"pages": [{"panels": panels}], "summary": "Deux dragons."})
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        chapter = session.get(Chapter, chapter_id)
        assert chapter is not None
        layout_pages(REG, save_script(session, chapter, output))
        session.commit()
    return _ok(c.get(f"/chapters/{chapter_id}/pages"))[0]["panels"]


def test_script_names_are_matched_and_unmatched_ones_surface(client: TestClient) -> None:
    d = _dragons(client, images=False)
    panels = _save(
        client,
        d["chapter"]["id"],
        [
            {
                "description": "Les deux dragons au bord du lac.",
                "setting": "lac de montagne, aube",
                "staging": "Urus à gauche, Kaël à droite",
                "characters": ["Urus le dragon", "kael"],
                "shot_type": "plan large",
                "dialogues": [{"speaker": "URUS", "text": "Te voilà !"}],
            },
            {"description": "Le petit dragon s'envole.", "characters": ["le petit dragon"], "shot_type": "plan moyen"},
        ],
    )
    first, second = panels
    assert (first["setting"], first["staging"]) == ("lac de montagne, aube", "Urus à gauche, Kaël à droite")
    assert first["unmatched_characters"] == [] and second["unmatched_characters"] == ["le petit dragon"]
    detail = _ok(client.get(f"/panels/{first['id']}"))
    assert detail["character_ids"] == [d["urus"]["id"], d["kael"]["id"]]
    assert detail["setting"] == "lac de montagne, aube"
    assert _ok(client.get(f"/panels/{second['id']}"))["unmatched_characters"] == ["le petit dragon"]

    # Un clic : le nom devient un alias d'Urus, la case le retrouve.
    link = _ok(
        client.post(
            f"/chapters/{d['chapter']['id']}/character-links",
            json={"name": "le petit dragon", "character_id": d["urus"]["id"]},
        )
    )
    assert link == {"name": "le petit dragon", "character_id": d["urus"]["id"], "panels": 1, "alias_added": True}
    assert _ok(client.get(f"/characters/{d['urus']['id']}"))["aliases"] == ["le petit dragon"]
    fixed = _ok(client.get(f"/panels/{second['id']}"))
    assert fixed["unmatched_characters"] == [] and fixed["character_ids"] == [d["urus"]["id"]]


def test_link_errors_ignore_and_card_created_afterwards(client: TestClient) -> None:
    d = _dragons(client, images=False)
    [panel] = _save(
        client,
        d["chapter"]["id"],
        [{"description": "Foule.", "characters": ["un passant", "Mira"], "shot_type": "plan large"}],
    )
    assert panel["unmatched_characters"] == ["un passant", "Mira"]
    url = f"/chapters/{d['chapter']['id']}/character-links"
    other = _ok(client.post("/projects", json={**STYLE, "title": "Autre"}), 201)
    stranger = _ok(client.post(f"/projects/{other['id']}/characters", json={"name": "X"}), 201)
    bad = client.post(url, json={"name": "Mira", "character_id": stranger["id"]})
    assert bad.status_code == 422 and "inconnu" in bad.text
    clash = client.post(url, json={"name": "Kaël", "character_id": d["urus"]["id"]})
    assert clash.status_code == 422 and "déjà le nom de la fiche Kaël" in clash.text
    # Figurant : écarté des personnages de la case (la description ne change pas).
    _ok(client.post(url, json={"name": "un passant", "character_id": None}))
    # Fiche créée après le découpage : la case la retrouve.
    mira = _ok(client.post(f"/projects/{d['series']['id']}/characters", json={"name": "Mira"}), 201)
    detail = _ok(client.get(f"/panels/{panel['id']}"))
    assert detail["characters"] == ["Mira"] and detail["unmatched_characters"] == []
    assert detail["character_ids"] == [mira["id"]] and detail["description"] == "Foule."


def test_aliases_are_cleaned_and_editable(client: TestClient) -> None:
    d = _dragons(client, images=False)
    urus = _ok(client.patch(f"/characters/{d['urus']['id']}", json={"aliases": ["Le Bleu", "le bleu"]}))
    assert urus["aliases"] == ["Le Bleu"]
    assert _ok(client.patch(f"/characters/{d['urus']['id']}", json={"aliases": None}))["aliases"] == []


def test_two_character_panel_gets_two_references_named_in_slot_order(client: TestClient) -> None:
    d = _dragons(client)
    [panel] = _save(
        client,
        d["chapter"]["id"],
        [
            {
                "description": "Urus retrouve Kaël",
                "setting": "clairière au bord d'un lac, fin d'après-midi, herbes hautes",
                "staging": "Urus au premier plan à gauche, ailes déployées ; Kaël sur un rocher à droite",
                "characters": ["Urus", "Kaël le dragon"],
                "shot_type": "plan large",
            }
        ],
    )
    [job] = _ok(client.post(f"/panels/{panel['id']}/generate"), 202)
    assert client.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]
    assert _ok(client.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    # (le QC automatique peut relancer un essai : on lit la version de ce job)
    img = next(i for i in _ok(client.get(f"/panels/{panel['id']}/images")) if i["params"]["job_id"] == job["id"])
    refs = img["params"]["reference_images"]
    # Deux personnages, chacun avec 2 images : une seule (la principale) par personnage, Urus puis Kaël.
    assert [(r["kind"], r["name"]) for r in refs] == [("character", "Urus"), ("character", "Kaël")]
    urus = _ok(client.get(f"/characters/{d['urus']['id']}"))
    kael = _ok(client.get(f"/characters/{d['kael']['id']}"))
    assert [r["image_id"] for r in refs] == [urus["reference_images"][0]["id"], kael["reference_images"][0]["id"]]
    prompt = img["params"]["prompt"]
    assert prompt.startswith(
        "Image 1 : référence d'identité de Urus ; Image 2 : référence d'identité de Kaël. Plan large. "
    )
    assert "Lieu : clairière au bord d'un lac, fin d'après-midi, herbes hautes." in prompt
    assert "Mise en scène : Urus au premier plan à gauche, ailes déployées ; Kaël sur un rocher à droite." in prompt
    assert "Deux personnages : Urus (dragon bleu, cornes torsadées) ; Kaël (dragon rouge, ailes)." in prompt
    assert prompt.index("Lieu :") < prompt.index("Deux personnages") < prompt.index("ne servent qu'à l'identité")
    assert img["params"]["panel_prompt"] == _ok(client.get(f"/panels/{panel['id']}"))["final_prompt"]


def test_mock_scenario_of_a_two_character_story(client: TestClient) -> None:
    d = _dragons(client, images=False)
    jobs = client.app.state.ctx.jobs  # type: ignore[attr-defined]
    _ok(client.patch(f"/chapters/{d['chapter']['id']}", json={"target_page_count": 2}))
    job = _ok(client.post(f"/chapters/{d['chapter']['id']}/script"), 202)
    jobs.wait(job["id"])
    assert _ok(client.get(f"/jobs/{job['id']}"))["status"] == "succeeded"
    panels = [p for page in _ok(client.get(f"/chapters/{d['chapter']['id']}/pages")) for p in page["panels"]]
    assert panels and all(p["setting"] and p["staging"] and not p["unmatched_characters"] for p in panels)
    both = {d["urus"]["id"], d["kael"]["id"]}
    duo = [p for p in panels if len(p["characters"]) == 2]
    assert duo
    for p in duo:
        detail = _ok(client.get(f"/panels/{p['id']}"))
        assert set(detail["character_ids"]) == both
        assert all(name in detail["staging"] for name in p["characters"])
