"""Atelier : sélecteur de fiche d'une case (`Panel.reference_choice` écrit par PUT /panels/{id}/reference-choice),
liste des workflows (couverture repérée) et « Changer l'angle » sans l'ancien angle. LLM et ComfyUI factices."""

from __future__ import annotations

from typing import Any

from mangaka_engine.pipeline.camera import angle_vocabulary, strip_angle_terms
from mangaka_engine.pipeline.generation import angle_scene
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.store.models import Panel
from tests.conftest import PRESETS_DIR
from tests.test_prompt_dialog import Env, _ok, _setup, _wait
from tests.test_prompt_dialog import env as env  # noqa: F401 — fixture

REG = PresetRegistry.load(PRESETS_DIR)


def _choice(panel: dict[str, Any], character_id: int) -> dict[str, Any]:
    return next(r for r in panel["reference_choices"] if r["character_id"] == character_id)


# --- sélecteur de fiche ----------------------------------------------------------------------------------
def test_panel_lists_each_character_images_with_the_current_one(env: Env) -> None:  # noqa: F811
    c = env.c
    data = _setup(c)
    panel = _ok(c.get(f"/panels/{data['panels'][0]['id']}"))
    lucius = _choice(panel, data["lucius"]["id"])
    assert lucius["name"] == "Lucius"
    assert [i["image_id"] for i in lucius["images"]] == [data["full_body"], data["portrait"]]
    assert lucius["images"][0]["label"].startswith("pied.png (image 1, principale")
    assert lucius["images"][0]["url"].startswith(f"/characters/{data['lucius']['id']}/images/{data['full_body']}/file")
    assert lucius["chosen_image_id"] is None
    assert lucius["current_image_id"] == lucius["automatic_image_id"] == data["full_body"]
    assert [r["name"] for r in panel["reference_choices"]] == ["Lucius", "Stan"]  # Mira : aucune image


def test_choose_then_generate_sends_the_chosen_sheet_first_then_reset(env: Env) -> None:  # noqa: F811
    c = env.c
    data = _setup(c)
    pid, lid = data["panels"][0]["id"], data["lucius"]["id"]
    panel = _ok(c.put(f"/panels/{pid}/reference-choice", json={"character_id": lid, "image_id": data["portrait"]}))
    lucius = _choice(panel, lid)
    assert lucius["chosen_image_id"] == lucius["current_image_id"] == data["portrait"]
    assert lucius["automatic_image_id"] == data["full_body"]
    assert any(o.startswith("Référence de Lucius : portrait.png") for o in panel["dialog_overrides"])

    _ok(c.post(f"/panels/{pid}/generate"), 202)
    _wait(c)
    [img] = _ok(c.get(f"/panels/{pid}/images"))
    refs = img["params"]["reference_images"]
    assert (refs[0]["name"], refs[0]["image_id"]) == ("Lucius", data["portrait"])  # la fiche choisie en tête
    lucius_refs = [r["image_id"] for r in refs if r["name"] == "Lucius"]
    assert lucius_refs[0] == data["portrait"]

    # Retour à « automatique » : la planche en pied repasse en tête à la génération suivante.
    panel = _ok(c.put(f"/panels/{pid}/reference-choice", json={"character_id": lid, "image_id": None}))
    assert _choice(panel, lid)["chosen_image_id"] is None
    assert _choice(panel, lid)["current_image_id"] == data["full_body"]
    with c.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        assert session.get(Panel, pid).reference_choice is None  # type: ignore[union-attr]
    _ok(c.post(f"/panels/{pid}/generate"), 202)
    _wait(c)
    images = _ok(c.get(f"/panels/{pid}/images"))
    assert images[1]["params"]["reference_images"][0]["image_id"] == data["full_body"]


def test_choice_of_one_character_keeps_the_others(env: Env) -> None:  # noqa: F811
    c = env.c
    data = _setup(c)
    pid, lid = data["panels"][0]["id"], data["lucius"]["id"]
    stan = next(r for r in _ok(c.get(f"/panels/{pid}"))["reference_choices"] if r["name"] == "Stan")
    _ok(c.put(f"/panels/{pid}/reference-choice", json={"character_id": lid, "image_id": data["portrait"]}))
    panel = _ok(
        c.put(
            f"/panels/{pid}/reference-choice",
            json={"character_id": stan["character_id"], "image_id": stan["images"][0]["image_id"]},
        )
    )
    assert _choice(panel, lid)["chosen_image_id"] == data["portrait"]
    assert _choice(panel, stan["character_id"])["chosen_image_id"] == stan["images"][0]["image_id"]


def test_image_of_another_character_is_a_readable_422(env: Env) -> None:  # noqa: F811
    c = env.c
    data = _setup(c)
    pid, lid = data["panels"][0]["id"], data["lucius"]["id"]
    stan = next(r for r in _ok(c.get(f"/panels/{pid}"))["reference_choices"] if r["name"] == "Stan")
    resp = c.put(
        f"/panels/{pid}/reference-choice", json={"character_id": lid, "image_id": stan["images"][0]["image_id"]}
    )
    assert resp.status_code == 422
    [error] = resp.json()["errors"]
    assert error["field"] == "image_id"
    assert error["message"] == "cette image est une référence de Stan, pas de Lucius"

    resp = c.put(f"/panels/{pid}/reference-choice", json={"character_id": lid, "image_id": 99999})
    assert resp.status_code == 422 and "introuvable parmi celles de Lucius" in resp.json()["errors"][0]["message"]

    # Stan n'est pas à l'image dans la 2e case… Lucius non plus : personnage absent.
    other = data["panels"][1]["id"]
    resp = c.put(f"/panels/{other}/reference-choice", json={"character_id": lid, "image_id": data["portrait"]})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["message"] == "ce personnage n'est pas à l'image dans cette case"
    assert _ok(c.get(f"/panels/{pid}"))["dialog_overrides"] == []  # rien écrit


# --- liste des workflows ---------------------------------------------------------------------------------
def test_workflow_list_flags_the_cover_workflow(env: Env) -> None:  # noqa: F811
    presets = _ok(env.c.get("/presets/workflows"))
    covers = [p["id"] for p in presets if p["is_cover"]]
    assert REG.cover is not None and covers == [REG.cover.workflow]


# --- « Changer l'angle » : la scène perd son ancien angle ------------------------------------------------
LOW_ANGLE_SCENE = (
    "Black-and-white manga panel. low-angle shot. Camera angle: low-angle view looking up. "
    "Aiko leaps over the gap between two roofs, seen in a low-angle shot, wind in her hair. "
    "Setting: rooftop at night, at eye level."
)


def test_angle_vocabulary_comes_from_the_presets() -> None:
    vocabulary = angle_vocabulary(REG.camera_loras, REG.image_prompt.camera_terms)
    for angle in REG.camera_loras.angles:
        assert angle.camera.casefold() in vocabulary
        assert all(part.strip().casefold() in vocabulary for part in angle.camera.split(","))
    assert REG.image_prompt.camera_terms["en contre-plongée"] in vocabulary
    assert all(t.casefold() in vocabulary for t in REG.camera_loras.scene_angle_terms)
    assert vocabulary == sorted(vocabulary, key=lambda t: (-len(t), t))


def test_scene_loses_its_old_angle() -> None:
    scene = angle_scene(REG, LOW_ANGLE_SCENE)
    assert "low-angle" not in scene.casefold() and "looking up" not in scene and "Camera angle" not in scene
    assert "eye level" not in scene
    assert scene == (
        "Black-and-white manga panel. Aiko leaps over the gap between two roofs, wind in her hair. "
        "Setting: rooftop at night."
    )
    assert strip_angle_terms("Aiko, front view, smiles.", ["front view"]) == "Aiko, smiles."


def test_change_angle_low_to_front_high_sends_only_the_new_view(env: Env) -> None:  # noqa: F811
    """Cas réel du 16/10 : une version en contre-plongée tournée en « De face, plongée forte »."""
    c = env.c
    data = _setup(c)
    pid = data["panels"][0]["id"]
    _ok(c.patch(f"/panels/{pid}", json={"final_prompt": LOW_ANGLE_SCENE}))
    _ok(c.post(f"/panels/{pid}/generate"), 202)
    _wait(c)
    [source] = _ok(c.get(f"/panels/{pid}/images"))
    assert "low-angle view looking up" in source["params"]["panel_prompt"]

    _ok(c.post(f"/panels/{pid}/change-angle", json={"angle": "front-high"}), 202)
    _wait(c)
    new = _ok(c.get(f"/panels/{pid}/images"))[-1]
    sent = new["params"]["prompt"]
    lora = REG.camera_loras.default_angle_lora
    camera = REG.camera_loras.angle("front-high")
    assert lora is not None and camera is not None
    assert sent.startswith(f"{lora.trigger} {camera.camera}.")
    body = sent.removeprefix(f"{lora.trigger} {camera.camera}.")
    assert "low-angle" not in body and "looking up" not in body and "Camera angle" not in body
    assert "Aiko leaps over the gap between two roofs" in body
    # Le prompt réellement envoyé à ComfyUI est celui noté sur la version (journal).
    workflow = list(env.comfy.prompts.values())[-1]
    assert any(sent in str(n["inputs"].get("prompt", "")) for n in workflow.values())
