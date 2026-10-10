"""Bibliothèque de la série : objets et décors récurrents (API, scénario, direction artistique, prompt,
LoRA et emplacements de référence du workflow, bible)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.art_direction import DirectionValidationError, parse_direction
from mangaka_engine.pipeline.generation import PanelCast, _prompt_entry, collect_loras, pick_references
from mangaka_engine.pipeline.library import SeriesLibrary
from mangaka_engine.pipeline.prompt import PromptCharacter, build_prompt
from mangaka_engine.pipeline.script import ScriptValidationError, parse_script
from mangaka_engine.presets import PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.providers.llm.mock import UNKNOWN_ID
from mangaka_engine.store.models import (
    AssetKind,
    Character,
    CharacterImage,
    SeriesAsset,
    SeriesAssetImage,
)
from tests.conftest import PRESETS_DIR, png_bytes

REG = PresetRegistry.load(PRESETS_DIR)


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture
def comfy() -> MockComfyUIClient:
    return MockComfyUIClient()


@pytest.fixture
def c(make_settings: Callable[..., Settings], comfy: MockComfyUIClient) -> Iterator[TestClient]:
    providers = Providers(
        llm=MockLLMProvider(),
        vision=None,
        comfyui=comfy,
        names={"llm": "mock", "vision": "mock", "comfyui": "mock"},
        errors={},
    )
    with TestClient(create_app(make_settings(), providers=providers)) as client:
        yield client


def _wait_job(c: TestClient, job_id: int) -> dict[str, Any]:
    c.app.state.ctx.jobs.wait(job_id, 10)  # type: ignore[attr-defined]
    return _ok(c.get(f"/jobs/{job_id}"))


def _series(c: TestClient) -> dict[str, Any]:
    return _ok(c.post("/projects", json={"title": "Robo Lycée", "style": "Shōnen lumineux"}), 201)


# --- API : même forme que les personnages ---------------------------------------------
@pytest.mark.parametrize(("segment", "kind"), [("objects", "object"), ("decors", "decor")])
def test_crud_with_reference_images(c: TestClient, segment: str, kind: str) -> None:
    s = _series(c)
    created = _ok(
        c.post(
            f"/projects/{s['id']}/{segment}",
            json={
                "name": "  Robot R-2  ",
                "visual_description": "robot rond, antenne",
                "prompt_keywords": ["robot", " robot ", "antenne rouge"],
                "lora_name": "",
            },
        ),
        201,
    )
    assert created["kind"] == kind and created["name"] == "Robot R-2"
    assert created["prompt_keywords"] == ["robot", "antenne rouge"] and created["lora_name"] is None
    aid = created["id"]

    up = _ok(
        c.post(
            f"/{segment}/{aid}/images",
            files=[("files", ("a.png", png_bytes(), "image/png")), ("files", ("b.jpg", png_bytes(fmt="JPEG"), "x"))],
        ),
        201,
    )
    assert [i["original_name"] for i in up["reference_images"]] == ["a.png", "b.jpg"]
    img = up["reference_images"][0]
    assert img["url"] == f"/{segment}/{aid}/images/{img['id']}/file"
    file = c.get(img["url"])
    assert file.status_code == 200 and file.headers["content-type"] == "image/png"
    bad = c.post(f"/{segment}/{aid}/images", files=[("files", ("x.png", b"pas une image", "image/png"))])
    assert bad.status_code == 422 and "x.png" in bad.text

    patched = _ok(
        c.patch(
            f"/{segment}/{aid}",
            json={"lora_name": "robot.safetensors", "lora_weight": 0.6, "lora_trigger_words": "r2bot"},
        )
    )
    assert patched["lora_name"] == "robot.safetensors" and patched["lora_weight"] == 0.6
    assert patched["lora_trigger_words"] == "r2bot"
    assert c.patch(f"/{segment}/{aid}", json={"name": None}).status_code == 422
    assert [a["id"] for a in _ok(c.get(f"/projects/{s['id']}/{segment}"))] == [aid]

    # l'autre sorte ne voit pas cette fiche
    other = "decors" if segment == "objects" else "objects"
    assert c.get(f"/{other}/{aid}").status_code == 404
    assert _ok(c.get(f"/projects/{s['id']}/{other}")) == []
    assert _ok(c.get(f"/projects/{s['id']}/characters")) == []

    assert c.delete(f"/{segment}/{aid}/images/{img['id']}").status_code == 204
    assert len(_ok(c.get(f"/{segment}/{aid}"))["reference_images"]) == 1
    assert c.get(img["url"]).status_code == 404
    assert c.delete(f"/{segment}/{aid}").status_code == 204
    assert c.get(f"/{segment}/{aid}").status_code == 404


# --- scénario (mock) ----------------------------------------------------------------------
def _library_series(c: TestClient) -> dict[str, Any]:
    s = _series(c)
    labo = _ok(
        c.post(
            f"/projects/{s['id']}/decors",
            json={"name": "Le labo", "visual_description": "laboratoire encombré", "prompt_keywords": ["néons"]},
        ),
        201,
    )
    robot = _ok(
        c.post(
            f"/projects/{s['id']}/objects",
            json={
                "name": "Robot R-2",
                "visual_description": "petit robot rond",
                "prompt_keywords": ["antenne rouge"],
                "lora_name": "robot.safetensors",
                "lora_weight": 0.7,
            },
        ),
        201,
    )
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Un", "synopsis": "Le robot s'éveille."}), 201)
    return {"series": s, "decor": labo, "object": robot, "chapter": ch}


def test_mock_scenario_links_panels_to_decor_and_objects(c: TestClient) -> None:
    data = _library_series(c)
    llm: MockLLMProvider = c.app.state.ctx.providers.llm  # type: ignore[attr-defined]
    ch = data["chapter"]
    _ok(c.patch(f"/chapters/{ch['id']}", json={"target_page_count": 2}))
    job = _ok(c.post(f"/chapters/{ch['id']}/script"), 202)
    assert _wait_job(c, job["id"])["status"] == "succeeded"

    # les agents reçoivent la bibliothèque (ids, noms, descriptions courtes)
    user = llm.calls[-1][1].content
    assert f"id {data['decor']['id']} · Le labo : laboratoire encombré" in user
    assert f"id {data['object']['id']} · Robot R-2 : petit robot rond" in user

    panels = [p for page in _ok(c.get(f"/chapters/{ch['id']}/pages")) for p in page["panels"]]
    assert panels and all(p["decor"] == data["decor"]["id"] for p in panels)
    assert panels[0]["objets"] == [data["object"]["id"]]
    assert any(p["objets"] == [] for p in panels)

    detail = _ok(c.get(f"/panels/{panels[0]['id']}"))
    assert detail["decor"] == {"id": data["decor"]["id"], "kind": "decor", "name": "Le labo"}
    assert detail["objets"] == [{"id": data["object"]["id"], "kind": "object", "name": "Robot R-2"}]


@pytest.mark.parametrize(("invalid", "status"), [(2, "succeeded"), (3, "failed")])
def test_unknown_library_ids_are_retried_then_reported(c: TestClient, invalid: int, status: str) -> None:
    data = _library_series(c)
    ch = data["chapter"]
    _ok(c.patch(f"/chapters/{ch['id']}", json={"synopsis": f"Le robot s'éveille. [mock:id-invalide:{invalid}]"}))
    job = _wait_job(c, _ok(c.post(f"/chapters/{ch['id']}/script"), 202)["id"])
    assert job["status"] == status
    if status == "failed":
        assert "invalide 3 fois de suite" in job["error"]
        assert f"page 1 › case 1 › decor : id {UNKNOWN_ID} inconnu" in job["error"]
        assert f"ids possibles : {data['decor']['id']}, ou null" in job["error"]
        assert _ok(c.get(f"/chapters/{ch['id']}/pages")) == []
    else:
        assert "en 3 essais" in job["message"]


def test_parse_script_checks_ids_against_the_library() -> None:
    lib = SeriesLibrary(
        decors=[{"id": 4, "name": "Labo", "description": ""}], objets=[{"id": 9, "name": "Robot", "description": ""}]
    )
    answer = {
        "pages": [{"panels": [{"description": "x", "shot_type": "plan moyen", "decor": "4", "objets": [9, 9]}]}],
        "summary": "s",
    }
    out = parse_script(json.dumps(answer), lib)
    assert out.pages[0].panels[0].decor == 4 and out.pages[0].panels[0].objets == [9]

    answer["pages"][0]["panels"][0].update({"decor": 9, "objets": [4, 12]})  # type: ignore[index]
    with pytest.raises(ScriptValidationError) as err:
        parse_script(json.dumps(answer), lib)
    assert "case 1 › decor : id 9 inconnu (ids possibles : 4, ou null)" in str(err.value)
    assert "objets : id(s) 4, 12 inconnu(s) (ids possibles : 9)" in str(err.value)
    # sans bibliothèque à vérifier (essais d'agent), le schéma seul s'applique
    assert parse_script(json.dumps(answer)).pages[0].panels[0].decor == 9
    with pytest.raises(ScriptValidationError, match="la série n'a aucun décor"):
        parse_script(json.dumps(answer), SeriesLibrary())


def test_author_edits_decor_and_objects_in_the_breakdown(c: TestClient) -> None:
    data = _library_series(c)
    ch, decor, obj = data["chapter"], data["decor"]["id"], data["object"]["id"]
    url = f"/chapters/{ch['id']}/pages"
    [page] = _ok(c.put(url, json={"pages": [{"panels": [{"description": "a", "decor": decor, "objets": [obj]}]}]}))
    panel = page["panels"][0]
    assert (panel["decor"], panel["objets"]) == (decor, [obj])
    # champs absents : gardés ; decor null : retiré
    [page] = _ok(c.put(url, json={"pages": [{"id": page["id"], "panels": [{"id": panel["id"], "description": "b"}]}]}))
    assert (page["panels"][0]["decor"], page["panels"][0]["objets"]) == (decor, [obj])
    body = {"pages": [{"id": page["id"], "panels": [{"id": panel["id"], "description": "b", "decor": None}]}]}
    [page] = _ok(c.put(url, json=body))
    assert (page["panels"][0]["decor"], page["panels"][0]["objets"]) == (None, [obj])
    # ids inconnus ou d'une autre sorte : refusés
    r = c.put(url, json={"pages": [{"panels": [{"description": "a", "decor": obj}]}]})
    assert r.status_code == 422 and "décor inconnu dans cette série" in r.text
    r = c.put(url, json={"pages": [{"panels": [{"description": "a", "objets": [decor, 777]}]}]})
    assert r.status_code == 422 and "objet(s) inconnu(s) dans cette série" in r.text

    # supprimer un objet ou un décor le retire des cases
    _ok(c.put(url, json={"pages": [{"panels": [{"description": "a", "decor": decor, "objets": [obj]}]}]}))
    assert c.delete(f"/objects/{obj}").status_code == 204
    assert c.delete(f"/decors/{decor}").status_code == 204
    panel = _ok(c.get(url))[0]["panels"][0]
    assert (panel["decor"], panel["objets"]) == (None, [])


# --- direction artistique -------------------------------------------------------------
def test_art_direction_receives_the_library_and_rejects_unknown_ids(c: TestClient) -> None:
    data = _library_series(c)
    ch, decor, obj = data["chapter"], data["decor"]["id"], data["object"]["id"]
    _ok(
        c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [{"description": "a"}, {"description": "b"}]}]})
    )
    from mangaka_engine.pipeline import art_direction as da
    from mangaka_engine.store.models import Chapter

    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    with ctx.db.session_scope() as session:
        chapter = session.get(Chapter, ch["id"])
        dctx = da.build_context(session, ctx.presets, chapter, ctx.presets.prompt(da.PROMPT_ID))
        messages = da.render_messages(ctx.presets.prompt(da.PROMPT_ID), dctx)
    assert f"id {decor} · Le labo" in messages[1].content and f"id {obj} · Robot R-2" in messages[1].content

    def answer(decor_id: int | None, objets: list[int] | None) -> str:
        panel = {"intensity": "normal", "plan": "plan moyen", "decor": decor_id, "objets": objets}
        return json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "rythme": "calme",
                        "rationale": "r",
                        "panels": [{**panel, "panel": 1}, {**panel, "panel": 2}],
                    }
                ]
            }
        )

    out = parse_direction(answer(decor, [obj]), dctx)
    assert out.pages[0].panels[0].decor == decor
    assert parse_direction(answer(None, None), dctx).pages[0].panels[0].objets is None
    with pytest.raises(DirectionValidationError, match=r"page 1 › case 1 › decor : id 4242 inconnu"):
        parse_direction(answer(4242, None), dctx)
    with pytest.raises(DirectionValidationError, match=r"objets : id\(s\) 5151 inconnu"):
        parse_direction(answer(None, [obj, 5151]), dctx)


# --- prompt, LoRA et emplacements de référence ---------------------------------------
def _img(cls: type, i: int) -> Any:
    return cls(id=i, path=f"x/{i}.png", original_name=f"{i}.png", content_type="image/png", width=8, height=8)


def _entries() -> PanelCast:
    aiko = Character(id=1, name="Aiko", visual_description="cheveux noirs", prompt_keywords=["kimono rouge"])
    aiko.lora_name, aiko.lora_weight = "aiko.safetensors", 0.9
    aiko.reference_images = [_img(CharacterImage, 11), _img(CharacterImage, 12)]
    labo = SeriesAsset(id=5, kind=AssetKind.decor, name="Le labo", visual_description="labo encombré")
    labo.prompt_keywords, labo.lora_name, labo.lora_weight = ["néons"], "labo.safetensors", 0.5
    labo.reference_images = [_img(SeriesAssetImage, 51), _img(SeriesAssetImage, 52)]
    robot = SeriesAsset(id=7, kind=AssetKind.object, name="Robot R-2", visual_description="")
    robot.prompt_keywords, robot.lora_name, robot.lora_weight = ["antenne rouge"], "robot.safetensors", 0.7
    robot.reference_images = [_img(SeriesAssetImage, 71)]
    return PanelCast(characters=[aiko], decor=labo, objects=[robot])


def test_reference_priority_characters_then_decor_then_objects() -> None:
    cast = _entries()
    picked = [(e.name, img.id) for e, img in pick_references(cast.entries, 3)]
    assert picked == [("Aiko", 11), ("Le labo", 51), ("Robot R-2", 71)]
    # 2e tour seulement quand chaque fiche a sa 1re image
    assert [img.id for _, img in pick_references(cast.entries, 5)] == [11, 51, 71, 12, 52]
    assert [img.id for _, img in pick_references(cast.entries, 1)] == [11]
    # sans personnage, le décor passe en tête
    assert [img.id for _, img in pick_references(PanelCast(decor=cast.decor, objects=cast.objects).entries, 3)] == [
        51,
        71,
        52,
    ]


def test_lora_trigger_words_of_decor_and_objects_reach_the_prompt() -> None:
    cast = _entries()
    cast.decor.lora_trigger_words = "lab_style, neon"  # type: ignore[union-attr]
    robot = cast.objects[0]
    robot.lora_trigger_words = "r2bot"
    assert _prompt_entry(cast.decor).prompt_keywords == ("néons", "lab_style", "neon")  # type: ignore[arg-type]
    assert _prompt_entry(robot).prompt_keywords == ("antenne rouge", "r2bot")
    robot.lora_name = None  # sans LoRA, ses mots déclencheurs ne servent à rien
    assert _prompt_entry(robot).prompt_keywords == ("antenne rouge",)


def test_workflow_graph_has_library_keywords_loras_and_references_in_order() -> None:
    cast = _entries()
    prompt = build_prompt(
        description="Aiko répare le robot",
        shot_type="plan moyen",
        characters=[PromptCharacter(c.name, c.visual_description, c.prompt_keywords) for c in cast.characters],
        decor=PromptCharacter(cast.decor.name, cast.decor.visual_description, cast.decor.prompt_keywords),  # type: ignore[union-attr]
        objects=[PromptCharacter(o.name, o.visual_description, o.prompt_keywords) for o in cast.objects],
        style="encre",
        settings=REG.image_prompt,
    )
    assert "Décor : Le labo (labo encombré, néons)." in prompt
    assert "Objets : Robot R-2 (antenne rouge)." in prompt
    assert prompt.index("Décor :") < prompt.index("Personnages :") < prompt.index("Objets :")

    class _Series:
        style_lora_name, style_lora_weight = "style.safetensors", 0.8

    class _Panel:
        class page:  # noqa: N801
            class chapter:  # noqa: N801
                project = _Series

    loras = collect_loras(_Panel, cast.entries)  # type: ignore[arg-type]
    assert [(lo.name, lo.source) for lo in loras] == [
        ("style.safetensors", "style"),
        ("aiko.safetensors", "Aiko"),
        ("labo.safetensors", "Le labo"),
        ("robot.safetensors", "Robot R-2"),
    ]
    refs = [f"mangaka/{e.name}_{img.id}.png" for e, img in pick_references(cast.entries, 3)]
    built = build_workflow(
        REG.workflow("qwen-image-edit-ref-turbo"),
        {"positive_prompt": prompt, "width": 832, "height": 1216, "seed": 1},
        reference_images=refs,
        loras=loras,
    )
    wf = built.workflow
    assert "néons" in wf["6"]["inputs"]["prompt"] and "antenne rouge" in wf["6"]["inputs"]["prompt"]
    # emplacements image_1…3 de l'encodeur : personnage, décor, objet
    slots = [wf[wf["6"]["inputs"][f"images.image_{i}"][0]]["inputs"]["image"] for i in (1, 2, 3)]
    assert slots == ["mangaka/Aiko_11.png", "mangaka/Le labo_51.png", "mangaka/Robot R-2_71.png"]
    chain = [n for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert [n["inputs"]["lora_name"] for n in chain] == [lo.name for lo in loras]
    assert [n["_meta"]["title"] for n in chain][2:] == ["LoRA Le labo", "LoRA Robot R-2"]


def test_generation_records_references_used_on_job_and_version(c: TestClient, comfy: MockComfyUIClient) -> None:
    data = _library_series(c)
    s, ch, decor, obj = data["series"], data["chapter"], data["decor"]["id"], data["object"]["id"]
    aiko = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    for url in (f"/decors/{decor}/images", f"/objects/{obj}/images"):
        files = [("files", (f"{i}.png", png_bytes(), "image/png")) for i in range(2)]
        _ok(c.post(url, files=files), 201)
    [page] = _ok(
        c.put(
            f"/chapters/{ch['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {"description": "Aiko et R-2", "characters": ["Aiko"], "decor": decor, "objets": [obj]}
                        ]
                    }
                ]
            },
        )
    )
    panel = page["panels"][0]
    [job] = _ok(c.post(f"/panels/{panel['id']}/generate"), 202)
    assert job["params"]["preset"] == "qwen-image-edit-ref-turbo"
    assert c.app.state.ctx.generation.wait_idle(10)  # type: ignore[attr-defined]

    done = _ok(c.get(f"/jobs/{job['id']}"))
    assert done["status"] == "succeeded", done
    used = done["params"]["references"]
    assert [(r["slot"], r["kind"], r["name"]) for r in used] == [
        (1, "character", "Aiko"),
        (2, "decor", "Le labo"),
        (3, "object", "Robot R-2"),
    ]
    [img] = _ok(c.get(f"/panels/{panel['id']}/images"))
    recorded = img["params"]["reference_images"]
    assert [r["kind"] for r in recorded] == ["character", "decor", "object"]
    assert recorded[0]["character_id"] == aiko["id"] and all(r["comfyui_name"] in comfy.uploads for r in recorded)
    assert [lo["source"] for lo in img["params"]["loras"]] == ["Robot R-2"]
    assert "Décor : Le labo (laboratoire encombré, néons)." in img["params"]["prompt"]
    [wf] = comfy.prompts.values()
    loads = [wf[wf["6"]["inputs"][f"images.image_{i}"][0]]["inputs"]["image"] for i in (1, 2, 3)]
    assert [name.split("/")[-1].split("_")[0] for name in loads] == [
        f"perso{aiko['id']}",
        f"decor{decor}",
        f"objet{obj}",
    ]


# --- bible ------------------------------------------------------------------------------
def test_bible_lists_library_for_the_agents(c: TestClient) -> None:
    data = _library_series(c)
    bible = _ok(c.get(f"/projects/{data['series']['id']}/bible"))
    assert [d["name"] for d in bible["decors"]] == ["Le labo"]
    assert [o["name"] for o in bible["objets"]] == ["Robot R-2"]
    text = bible["rendered"]["text"]
    assert "Décors récurrents :\n- id" in text and "Le labo : laboratoire encombré" in text
    assert "Objets récurrents :" in text and "Robot R-2 : petit robot rond" in text


# --- migration : une base d'avant la bibliothèque --------------------------------------
def test_database_from_before_the_library_keeps_working(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    with TestClient(create_app(settings)) as client:
        s = _series(client)
        aiko = _ok(client.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
        _ok(
            client.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201
        )
        ch = _ok(client.post(f"/projects/{s['id']}/chapters", json={"title": "Un"}), 201)
        _ok(
            client.put(
                f"/chapters/{ch['id']}/pages",
                json={"pages": [{"panels": [{"description": "a", "characters": ["Aiko"]}]}]},
            )
        )
    con = sqlite3.connect(settings.database_path)
    for table, column in [
        ("panel_images", "kind"),
        ("panels", "sketch_image_id"),
        ("panels", "sketch_denoise"),
        ("projects", "sketch_enabled"),
        ("projects", "sketch_denoise"),
    ]:  # colonnes du palier croquis (v14)
        con.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    con.execute("ALTER TABLE panel_images DROP COLUMN finish")  # v13
    con.execute("ALTER TABLE projects DROP COLUMN upscaler")
    con.execute("DROP TABLE reference_variants")  # v12
    con.execute("ALTER TABLE character_images DROP COLUMN position")
    con.execute("ALTER TABLE series_asset_images DROP COLUMN position")
    con.execute("ALTER TABLE panels DROP COLUMN decor_id")
    con.execute("ALTER TABLE panels DROP COLUMN object_ids")
    con.execute("DROP TABLE series_asset_images")
    con.execute("DROP TABLE series_assets")
    con.execute("PRAGMA user_version = 10")
    con.commit()
    con.close()

    with TestClient(create_app(settings)) as client:
        assert _ok(client.get(f"/characters/{aiko['id']}"))["reference_images"][0]["original_name"] == "a.png"
        panel = _ok(client.get(f"/chapters/{ch['id']}/pages"))[0]["panels"][0]
        assert (panel["characters"], panel["decor"], panel["objets"]) == (["Aiko"], None, [])
        decor = _ok(client.post(f"/projects/{s['id']}/decors", json={"name": "Le toit"}), 201)
        body = {"pages": [{"panels": [{"id": panel["id"], "description": "a", "decor": decor["id"]}]}]}
        assert _ok(client.put(f"/chapters/{ch['id']}/pages", json=body))[0]["panels"][0]["decor"] == decor["id"]
