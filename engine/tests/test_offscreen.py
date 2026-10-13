"""Personnages cités mais hors cadre, vue subjective et cases sans personnage (jeu d'essai du chapitre
« vulcano », série ecoloman : cases 122, 133, 136 et 138).

De bout en bout, LLM et ComfyUI factices : scénario → direction artistique → rédacteur de prompt →
workflow ComfyUI. Aucun personnage hors cadre n'est dessiné ni pourvu d'image de référence.
"""

from __future__ import annotations

import io
import json
import sqlite3
from collections.abc import Callable
from typing import Any

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.framing import (
    REACTION,
    SUBJECTIVE,
    cites,
    default_viewpoint,
    find_spectators,
    framing_sentence,
    name_stem,
    settle_cast,
)
from mangaka_engine.pipeline.pages import layout_pages
from mangaka_engine.pipeline.prompt_writer import PromptBrief, PromptValidationError, parse_written
from mangaka_engine.pipeline.qc import evaluate_detections
from mangaka_engine.pipeline.script import parse_script, render_messages, save_script
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.qc.base import Detections
from mangaka_engine.store.db import create_db_engine
from mangaka_engine.store.migrations import SCHEMA_VERSION
from mangaka_engine.store.models import Chapter
from tests.conftest import PRESETS_DIR, STYLE

REG = PresetRegistry.load(PRESETS_DIR)
HEROS = ("Angus", "Seku")
TRAFIQUANTS = ("Trafiquant 1", "Trafiquant 2")
COLOURS = {"Angus": (220, 40, 40), "Seku": (40, 200, 40), "Trafiquant 1": (40, 40, 220), "Trafiquant 2": (200, 200, 40)}

# Les 4 cases du jeu d'essai, telles que le scénario les écrit en base (audit du chapitre 3) : « angu » pour
# Angus, « trafiquant » sans numéro.
TEXTS = {
    122: "seku et angu voit au loin les trafiquant jeter des barils de produit chimique dans le volcan",
    133: "Trafiquant 2, voyant son comparse au sol, panique et recule vers le bord du cratère.",
    136: "Trafiquant 1, sonné mais vivant, rampe et s'enfuit en boitant, disparaissant derrière les rochers.",
    138: "Soudain, le sol tremble violemment. Le volcan gronde, de la fumée noire s'échappe du cratère.",
}
# Ce que le scénariste déclarait avant (« tout personnage cité est présent ») …
OLD_CAST = {
    122: ["Seku", "Angus", "Trafiquant 1", "Trafiquant 2"],
    133: ["Trafiquant 2", "Angus", "Seku"],
    136: ["Trafiquant 1", "Angus", "Seku"],
    138: ["Angus", "Seku"],
}
# … et ce que la chaîne doit dessiner (après la direction artistique).
EXPECTED = {122: list(TRAFIQUANTS), 133: ["Trafiquant 2"], 136: ["Trafiquant 1"], 138: []}


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _png(colour: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), colour).save(buf, format="PNG")
    return buf.getvalue()


def _ecoloman(c: TestClient, *, ai_prompt: bool = True) -> dict[str, Any]:
    s = _ok(c.post("/projects", json={**STYLE, "title": "ecoloman", "ai_prompt": ai_prompt}), 201)
    cards = {}
    for name in (*HEROS, *TRAFIQUANTS):
        card = _ok(
            c.post(f"/projects/{s['id']}/characters", json={"name": name, "visual_description": f"{name}, silhouette"}),
            201,
        )
        _ok(
            c.post(
                f"/characters/{card['id']}/images", files=[("files", (f"{name}.png", _png(COLOURS[name]), "image/png"))]
            ),
            201,
        )
        cards[name] = card
    synopsis = " ".join(TEXTS.values())
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "vulcano", "synopsis": synopsis}), 201)
    return {"series": s, "cards": cards, "chapter": ch}


def _script(panels: list[dict[str, Any]]) -> str:
    return json.dumps({"pages": [{"panels": panels}], "summary": "Les trafiquants polluent le volcan."})


def _save(c: TestClient, chapter_id: int, raw: str) -> list[dict[str, Any]]:
    output = parse_script(raw)
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        chapter = session.get(Chapter, chapter_id)
        assert chapter is not None
        layout_pages(REG, save_script(session, chapter, output))
        session.commit()
    return [p for page in _ok(c.get(f"/chapters/{chapter_id}/pages")) for p in page["panels"]]


def _old_habit() -> str:
    """Réponse du scénariste d'avant : chaque personnage cité, et les héros par habitude, sont « présents »."""
    return _script(
        [{"description": TEXTS[k], "characters": OLD_CAST[k], "shot_type": "plan large"} for k in (122, 133, 136, 138)]
    )


def _direct_and_apply(c: TestClient, chapter_id: int) -> dict[str, Any]:
    r = c.post(f"/chapters/{chapter_id}/direction", json={})
    assert r.status_code == 202, r.text
    c.app.state.ctx.jobs.wait(r.json()["id"])  # type: ignore[attr-defined]
    assert _ok(c.get(f"/jobs/{r.json()['id']}"))["status"] == "succeeded"
    _ok(c.post(f"/chapters/{chapter_id}/direction/apply", json={}))
    return _ok(c.get(f"/chapters/{chapter_id}/direction"))


def _generate(c: TestClient, panel_id: int) -> dict[str, Any]:
    [job] = _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    assert c.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]
    done = _ok(c.get(f"/jobs/{job['id']}"))
    assert done["status"] == "succeeded", done
    return next(i for i in _ok(c.get(f"/panels/{panel_id}/images")) if i["params"]["job_id"] == job["id"])


def _sent_references(c: TestClient, image: dict[str, Any]) -> list[str]:
    """Personnages dont l'image de référence est dans le workflow envoyé à ComfyUI (LoadImage)."""
    comfy = c.app.state.ctx.providers.comfyui  # type: ignore[attr-defined]
    workflow = comfy.prompts[image["params"]["comfyui_prompt_id"]]
    by_bytes = {_png(colour): name for name, colour in COLOURS.items()}
    sent = []
    for node in workflow.values():
        if node.get("class_type") == "LoadImage":
            data = comfy.uploads.get(node["inputs"]["image"])
            if data in by_bytes:
                sent.append(by_bytes[data])
    return sent


# --- radicaux et spectateurs -------------------------------------------------------------------------
def test_names_compare_on_their_stem() -> None:
    assert (name_stem("Angus"), name_stem("Trafiquant 2"), name_stem("le Petit Dragon")) == ("angu", "trafi", "drago")
    assert cites("seku et angu voit au loin", "Angus") and cites("les trafiquants", "Trafiquant 1")
    assert cites("Trafiquant 2 recule", "Trafiquant 2") and not cites("Trafiquant 2 recule", "Trafiquant 1")
    assert not cites("le sol tremble", "Seku") and cites("ÉLISE court", "elise")


def test_spectators_of_the_test_panels() -> None:
    names = list(OLD_CAST[122])
    s = find_spectators(TEXTS[122], names)
    assert (s.viewers, s.seen, s.verb) == (["Seku", "Angus"], list(TRAFIQUANTS), "voit")
    assert default_viewpoint(s, names) == SUBJECTIVE
    # Sujet pronom : « ils voient » désigne les personnages de la case qui ne sont pas vus.
    s = find_spectators("Ils voient au loin les trafiquants jeter des barils dans le volcan.", names)
    assert s.viewers == ["Seku", "Angus"] and s.seen == list(TRAFIQUANTS)
    # « voyant » n'est pas un regard mis en scène, et le reste des cases n'a pas de spectateur.
    for k in (133, 136, 138):
        assert not find_spectators(TEXTS[k], OLD_CAST[k])
    # Spectateur seul, rien d'autre à voir : plan de réaction.
    alone = find_spectators("Seku regarde l'horizon.", ["Seku"])
    assert alone.viewers == ["Seku"] and default_viewpoint(alone, ["Seku"]) == REACTION


def test_script_guard_takes_uncited_characters_out_of_the_frame() -> None:
    assert settle_cast(TEXTS[133], OLD_CAST[133]) == (["Trafiquant 2"], ["Angus", "Seku"])
    assert settle_cast(TEXTS[136], OLD_CAST[136]) == (["Trafiquant 1"], ["Angus", "Seku"])
    assert settle_cast(TEXTS[138], OLD_CAST[138]) == ([], ["Angus", "Seku"])
    # Tous cités : la case reste (la direction artistique tranche, voir plus bas).
    assert settle_cast(TEXTS[122], OLD_CAST[122]) == (OLD_CAST[122], [])
    # Prudent : un pronom ou un mot de personne peut désigner un présent sans le nommer.
    assert settle_cast("Il bondit.", ["Seku"]) == (["Seku"], [])
    assert settle_cast("Les deux dragons au bord du lac.", ["Urus", "Kaël"]) == (["Urus", "Kaël"], [])
    assert settle_cast("Foule.", ["un passant"]) == (["un passant"], [])
    # Un nom à la fois présent et hors cadre est présent.
    assert settle_cast("Seku court.", ["Seku"], ["Seku", "Angus"]) == (["Seku"], ["Angus"])


def test_framing_sentence() -> None:
    texts = REG.image_prompt.framing
    assert framing_sentence(["Seku"], [], None, texts) == ""  # case ordinaire : prompt inchangé
    assert framing_sentence([], ["Angus"], None, texts).startswith("No character in the frame")
    assert framing_sentence(["Trafiquant 2"], ["Angus"], None, texts) == "Only Trafiquant 2 in the frame, nobody else"
    pov = framing_sentence(list(TRAFIQUANTS), list(HEROS), {"mode": SUBJECTIVE}, texts)
    assert pov.startswith("Subjective point-of-view panel") and "out of the frame" in pov


# --- scénario -------------------------------------------------------------------------------------------
def test_script_prompt_explains_present_and_offscreen() -> None:
    from mangaka_engine.pipeline.script import ScriptContext

    ctx = ScriptContext(
        series={"title": "ecoloman", "style": "", "reading_direction": "rtl"},
        characters=[{"name": n, "aliases": [], "description": ""} for n in (*HEROS, *TRAFIQUANTS)],
        previous_chapters=[],
        chapter={"number": 3, "title": "vulcano", "synopsis": "x", "target_pages": 5},
    )
    user = render_messages(REG.prompt("script"), ctx)[1].content
    assert "PRÉSENTS À L'IMAGE" in user and "HORS" in user and '"offscreen": []' in user
    assert "voient au loin les trafiquants" in user and "characters : [] (une case de décor" in user


def test_obedient_script_keeps_present_and_offscreen(client: TestClient) -> None:
    d = _ecoloman(client)
    raw = _script(
        [
            {
                "description": "Ils voient au loin les trafiquants jeter des barils dans le volcan.",
                "characters": list(TRAFIQUANTS),
                "hors_cadre": ["Seku", "Angus"],
                "shot_type": "vue subjective",
            },
            {
                "description": "Trafiquant 2 panique et recule.",
                "characters": ["Trafiquant 2"],
                "offscreen": list(HEROS),
                "shot_type": "plan moyen",
            },
            {
                "description": "Trafiquant 1 rampe et s'enfuit.",
                "characters": ["Trafiquant 1"],
                "shot_type": "plan moyen",
            },
            {"description": "Le sol tremble, le volcan gronde.", "characters": [], "shot_type": "plan d'ensemble"},
        ]
    )
    panels = _save(client, d["chapter"]["id"], raw)
    assert [p["characters"] for p in panels] == list(EXPECTED.values())
    assert [p["offscreen_characters"] for p in panels] == [["Seku", "Angus"], list(HEROS), [], []]
    detail = _ok(client.get(f"/panels/{panels[0]['id']}"))
    assert detail["character_ids"] == [d["cards"][n]["id"] for n in TRAFIQUANTS]
    assert detail["spectator_hints"] == ["Seku", "Angus"] and detail["perception"] == "voient"


# --- de bout en bout : scénario d'avant → direction → rédacteur → ComfyUI ---------------------------------
def test_the_four_test_panels_draw_no_unwanted_character(client: TestClient) -> None:
    d = _ecoloman(client)
    chapter_id = d["chapter"]["id"]
    panels = _save(client, chapter_id, _old_habit())
    # Scénario : le garde-fou sort de l'image ceux que le texte ne désigne pas.
    assert [p["characters"] for p in panels] == [OLD_CAST[122], ["Trafiquant 2"], ["Trafiquant 1"], []]

    # Direction artistique : la case 122 met Seku et Angus en spectateurs → choix explicite (vue subjective).
    direction = _direct_and_apply(client, chapter_id)
    [choice] = [pa for pa in direction["pages"][0]["panels"] if pa["point_de_vue"]]
    assert choice["panel_id"] == panels[0]["id"]
    assert (choice["point_de_vue"], choice["spectateurs"]) == ("vue subjective", ["Seku", "Angus"])

    panels = [p for page in _ok(client.get(f"/chapters/{chapter_id}/pages")) for p in page["panels"]]
    assert [p["characters"] for p in panels] == list(EXPECTED.values())
    assert panels[0]["offscreen_characters"] == ["Seku", "Angus"]
    assert panels[0]["viewpoint"] == {"mode": "subjective", "spectators": ["Seku", "Angus"], "source": "direction"}
    assert all(p["viewpoint"] is None for p in panels[1:])

    for panel, key in zip(panels, (122, 133, 136, 138), strict=True):
        image = _generate(client, panel["id"])
        expected = EXPECTED[key]
        # Rédacteur : seuls les présents sont nommés (aucun spectateur, aucun héros hors cadre).
        detail = _ok(client.get(f"/panels/{panel['id']}"))
        assert detail["prompt_source"] == "ia", detail["prompt_warning"]
        prompt = detail["final_prompt"]
        for name in expected:
            assert name in prompt
        for name in {*HEROS, *TRAFIQUANTS} - set(expected):
            assert name not in prompt, (key, name)
        # Génération : aucune image de référence d'un personnage absent dans le workflow ComfyUI.
        assert sorted(_sent_references(client, image)) == sorted(expected), key
        assert [r["name"] for r in image["params"]["reference_images"] if r["kind"] == "character"] == expected
        if not expected:
            # Case sans personnage : preset sans référence (pas d'edit-ref), sans planter.
            assert "edit-ref" not in image["params"]["preset"]
            assert "No character in the frame" in prompt
    assert "Subjective point-of-view panel" in _ok(client.get(f"/panels/{panels[0]['id']}"))["final_prompt"]


def test_zero_character_panel_generates_end_to_end_with_fragments(client: TestClient) -> None:
    d = _ecoloman(client, ai_prompt=False)
    [panel] = _save(
        client,
        d["chapter"]["id"],
        _script(
            [{"description": TEXTS[138], "characters": [], "offscreen": list(HEROS), "shot_type": "plan d'ensemble"}]
        ),
    )
    assert panel["characters"] == [] and panel["offscreen_characters"] == list(HEROS)
    image = _generate(client, panel["id"])
    assert image["params"]["reference_images"] == [] and "edit-ref" not in image["params"]["preset"]
    assert _sent_references(client, image) == []
    prompt = image["params"]["prompt"]
    assert "No character in the frame" in prompt and "Angus" not in prompt and "Seku" not in prompt


# --- rédacteur : un hors cadre nommé est refusé -----------------------------------------------------------
def test_writer_rejects_an_offscreen_character() -> None:
    from mangaka_engine.pipeline.prompt import PromptCharacter

    brief = PromptBrief.build(
        description=TEXTS[122],
        characters=[PromptCharacter("Trafiquant 1", "", ()), PromptCharacter("Trafiquant 2", "", ())],
        offscreen=["Seku", "Angus", "trafiquant"],
        framing="Subjective point-of-view panel",
        settings=REG.image_prompt,
        prompt=REG.prompt("redacteur-image"),
    )
    # « trafiquant » (générique) est contenu dans le nom d'un présent : jamais refusé.
    assert brief.absent == ["Seku", "Angus"] and brief.as_json()["framing"] == "Subjective point-of-view panel"
    words = " ".join(["word"] * 200)
    ok = json.dumps({"prompt": f"Trafiquant 1 and Trafiquant 2 tip barrels. {words}", "language": "en"})
    parse_written(ok, brief)
    bad = json.dumps({"prompt": f"Seku watches Trafiquant 1 and Trafiquant 2. {words}", "language": "en"})
    try:
        parse_written(bad, brief)
    except PromptValidationError as exc:
        assert "Seku" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("un spectateur hors cadre nommé doit être refusé")
    # Une case ordinaire garde son empreinte : pas de clé « framing ».
    plain = PromptBrief.build(description="x", settings=REG.image_prompt)
    assert "framing" not in plain.as_json()


# --- QC : pas de « visage manquant » pour une case sans personnage -----------------------------------------
def test_qc_expects_no_face_on_an_empty_panel() -> None:
    res = evaluate_detections(
        Detections(width=64, height=48), expected_faces=0, shot_type="plan large", cfg=REG.require_qc().detectors
    )
    assert not any("manquant" in r for r in res.reasons)


def test_qc_target_counts_only_present_characters(client: TestClient) -> None:
    d = _ecoloman(client, ai_prompt=False)
    [panel] = _save(
        client,
        d["chapter"]["id"],
        _script(
            [{"description": "Trafiquant 2 panique et recule.", "characters": OLD_CAST[133], "shot_type": "plan moyen"}]
        ),
    )
    image = _generate(client, panel["id"])
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    with ctx.db.session_scope() as session:
        target = ctx.qc._load(session, image["id"], REG.require_qc())
    assert target is not None
    assert target.character_names == ["Trafiquant 2"] and list(target.references) == ["Trafiquant 2"]


# --- atelier : l'auteur corrige présents, hors cadre et point de vue ----------------------------------------
def test_author_edits_cast_and_viewpoint_in_the_inspector(client: TestClient) -> None:
    d = _ecoloman(client, ai_prompt=False)
    [panel] = _save(
        client,
        d["chapter"]["id"],
        _script([{"description": TEXTS[122], "characters": OLD_CAST[122], "shot_type": "plan large"}]),
    )
    pid = panel["id"]
    detail = _ok(client.get(f"/panels/{pid}"))
    assert detail["spectator_hints"] == ["Seku", "Angus"] and detail["viewpoint"] is None

    detail = _ok(
        client.patch(f"/panels/{pid}", json={"viewpoint": {"mode": "subjective", "spectators": ["Seku", "Angus"]}})
    )
    assert detail["characters"] == list(TRAFIQUANTS) and detail["offscreen_characters"] == ["Seku", "Angus"]
    assert detail["viewpoint"]["source"] == "auteur"
    assert detail["character_ids"] == [d["cards"][n]["id"] for n in TRAFIQUANTS]
    assert "Subjective point-of-view panel" in detail["final_prompt"]

    # Plan de réaction : les spectateurs reviennent à l'image.
    detail = _ok(client.patch(f"/panels/{pid}", json={"viewpoint": {"mode": "reaction", "spectators": ["Seku"]}}))
    assert detail["characters"] == [*TRAFIQUANTS, "Seku"] and detail["offscreen_characters"] == ["Angus"]

    # Un personnage déplacé à la main hors cadre.
    detail = _ok(client.patch(f"/panels/{pid}", json={"offscreen_characters": ["Angus", "Trafiquant 1"]}))
    assert detail["characters"] == ["Trafiquant 2", "Seku"]
    assert detail["offscreen_characters"] == ["Angus", "Trafiquant 1"]
    detail = _ok(client.patch(f"/panels/{pid}", json={"viewpoint": None}))
    assert detail["viewpoint"] is None

    # La direction artistique n'écrase jamais un choix de l'auteur.
    _ok(client.patch(f"/panels/{pid}", json={"viewpoint": {"mode": "reaction", "spectators": ["Seku"]}}))
    _direct_and_apply(client, d["chapter"]["id"])
    detail = _ok(client.get(f"/panels/{pid}"))
    assert detail["viewpoint"]["mode"] == "reaction" and detail["viewpoint"]["source"] == "auteur"
    assert "Seku" in detail["characters"]


# --- migration ------------------------------------------------------------------------------------------
def test_v29_database_keeps_characters_as_present(make_settings: Callable[..., Settings]) -> None:
    """v29 → v30 : les cases existantes gardent tous leurs personnages comme « présents », sans hors cadre."""
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        d = _ecoloman(c, ai_prompt=False)
        [panel] = _save(
            c,
            d["chapter"]["id"],
            _script([{"description": "Seku et Angus courent.", "characters": list(HEROS), "shot_type": "plan large"}]),
        )
    con = sqlite3.connect(settings.database_path)
    for column in ("offscreen_names", "viewpoint"):
        con.execute(f"ALTER TABLE panels DROP COLUMN {column}")
    con.execute("PRAGMA user_version = 29")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as c:
        detail = _ok(c.get(f"/panels/{panel['id']}"))
        assert detail["characters"] == list(HEROS) and detail["offscreen_characters"] == []
        assert detail["viewpoint"] is None
        assert detail["character_ids"] == [d["cards"][n]["id"] for n in HEROS]
    con = sqlite3.connect(settings.database_path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 30
    con.close()
    fresh = settings.database_path.parent / "fresh.db"
    create_db_engine(fresh).dispose()

    def columns(path: Any) -> set[tuple[Any, ...]]:
        db = sqlite3.connect(path)
        try:
            return {tuple(r[1:]) for r in db.execute("PRAGMA table_info(panels)")}
        finally:
            db.close()

    assert columns(settings.database_path) == columns(fresh)
