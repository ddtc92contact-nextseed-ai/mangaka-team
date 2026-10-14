"""Distribution du chapitre (pipeline/cast.py, #162) : chaque intervenant, même secondaire, a sa fiche et ses
références avant la génération ; seules les foules anonymes marquées « foule sans fiche » en sont dispensées."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mangaka_engine.pipeline.cast import (
    CastDraftError,
    DraftContext,
    cast_key,
    draft_character,
    is_crowd,
    parse_draft,
)
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.providers.llm.mock import MockLLMProvider
from mangaka_engine.store.models import ChapterCrowdMark, GenerationEvent
from tests.conftest import PRESETS_DIR, STYLE, force_stages, png_bytes


def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


def _refused(resp: httpx.Response, field: str) -> str:
    assert resp.status_code == 422, resp.text
    [error] = resp.json()["errors"]
    assert error["field"] == field, error
    return error["message"]


def _wait(c: TestClient) -> None:
    assert c.app.state.ctx.generation.wait_idle(20)  # type: ignore[attr-defined]


def _image(c: TestClient, character_id: int) -> None:
    _ok(c.post(f"/characters/{character_id}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)


def _setup(c: TestClient, *, garde: str = "Le garde barre la porte du palais.") -> dict[str, Any]:
    """Aiko (fiche avec image, alias « la rousse »), Mina (fiche sans image) ; le scénario cite aussi « le garde »
    (présent et locuteur), « la serveuse » (locutrice) et « des passants » (foule), sans fiche."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Le Palais"}), 201)
    aiko = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko", "aliases": ["la rousse"]}), 201)
    _image(c, aiko["id"])
    mina = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Mina"}), 201)
    chapter = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "La porte"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{chapter['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {
                                "description": garde,
                                "characters": ["Aiko", "le garde"],
                                "dialogues": [{"speaker": "le garde", "text": "Halte !"}],
                            },
                            {
                                "description": "Mina observe la rousse depuis la fenêtre.",
                                "characters": ["Mina"],
                                "offscreen_characters": ["le garde"],
                            },
                        ]
                    },
                    {
                        "panels": [
                            {
                                "description": "Des passants s'écartent devant Aiko.",
                                "characters": ["Aiko", "des passants"],
                                "dialogues": [{"speaker": "la serveuse", "text": "Attention !"}],
                            }
                        ]
                    },
                ]
            },
        )
    )
    return {"series": s, "aiko": aiko, "mina": mina, "chapter": chapter, "pages": pages}


def _cast(c: TestClient, chapter_id: int) -> dict[str, dict[str, Any]]:
    return {m["name"]: m for m in _ok(c.get(f"/chapters/{chapter_id}/cast"))["members"]}


# --- calcul de la distribution ------------------------------------------------------------------------------
def test_cast_lists_every_speaker_present_offscreen_and_named(client: TestClient) -> None:
    d = _setup(client)
    out = _ok(client.get(f"/chapters/{d['chapter']['id']}/cast"))
    members = {m["name"]: m for m in out["members"]}
    assert list(members) == ["Aiko", "le garde", "Mina", "des passants", "la serveuse"]  # ordre d'apparition
    aiko = members["Aiko"]
    assert aiko["character_id"] == d["aiko"]["id"] and aiko["images"] == 1 and aiko["references"] == "portrait"
    # Alias lu dans la description (« la rousse ») : la case 2 compte, source notée.
    assert [(a["label"], a["sources"]) for a in aiko["appearances"]] == [
        ("case 1 de la page 1", ["image"]),
        ("case 2 de la page 1", ["description"]),
        ("case 1 de la page 2", ["image", "description"]),
    ]
    assert aiko["written"] == ["Aiko"]  # « la rousse » lu dans le texte : une source, pas un nom déclaré
    assert aiko["role"] == "principal" and aiko["fault"] is None and aiko["advice"].startswith("planche conseillée")
    garde = members["le garde"]
    assert garde["character_id"] is None and garde["fault"] == "sans fiche" and garde["role"] == "secondaire"
    assert [a["sources"] for a in garde["appearances"]] == [["image", "bulle"], ["hors cadre"]]
    assert garde["panel_count"] == 2 and not garde["crowd"] and garde["needs"] == "portrait"
    assert members["Mina"]["fault"] == "sans image" and members["Mina"]["references"] == "aucune"
    assert members["la serveuse"]["appearances"][0]["sources"] == ["bulle"]
    assert members["des passants"]["crowd"] and members["des passants"]["fault"] == "sans fiche"
    assert (out["total"], out["faults"]) == (5, 4)
    assert out["without_card"] == ["le garde", "des passants", "la serveuse"] and out["without_image"] == ["Mina"]


def test_crowds_are_plural_and_nameless() -> None:
    for crowd in ("des passants", "la foule", "Des passants", "les gardes", "le public", "une foule de badauds"):
        assert is_crowd(crowd), crowd
    for named in ("le garde", "Mina", "trafiquant 2", "un passant", "la serveuse", "les gardes de Mina", ""):
        assert not is_crowd(named), named
    assert cast_key("Le Garde") == cast_key("le garde") == cast_key("un garde") == "garde"


def test_alias_and_plural_resolve_to_the_cards(client: TestClient) -> None:
    s = _ok(client.post("/projects", json={**STYLE, "title": "Port"}), 201)
    ids = [
        _ok(client.post(f"/projects/{s['id']}/characters", json={"name": n}), 201)["id"]
        for n in ("trafiquant 1", "trafiquant 2")
    ]
    chapter = _ok(client.post(f"/projects/{s['id']}/chapters", json={"title": "Quai"}), 201)
    _ok(
        client.put(
            f"/chapters/{chapter['id']}/pages",
            json={"pages": [{"panels": [{"description": "Sur le quai.", "characters": ["les trafiquants"]}]}]},
        )
    )
    members = _cast(client, chapter["id"])
    # Pluriel : toutes les fiches concernées, jamais un intervenant « sans fiche ».
    assert [m["character_id"] for m in members.values()] == ids
    assert all(m["fault"] == "sans image" for m in members.values())


# --- garde d'étapes -------------------------------------------------------------------------------------------
def test_generation_refused_until_every_cast_member_has_a_card_and_an_image(client: TestClient) -> None:
    d = _setup(client)
    chapter_id = d["chapter"]["id"]
    force_stages(client, chapter_id, "direction")
    message = _refused(client.post(f"/chapters/{chapter_id}/generate"), "stage.references")
    assert message == (
        "Chapitre 1 — Références manquantes : 3 intervenants sans fiche (le garde, des passants, la serveuse), "
        "1 fiche sans image (Mina) sur 5 intervenants. Crée leur fiche et leurs références (Direction artistique › "
        "Distribution) avant de générer, ou passe outre cette étape."
    )
    _refused(client.post(f"/chapters/{chapter_id}/produce"), "stage.references")
    stage = next(s for s in _ok(client.get(f"/chapters/{chapter_id}/stages"))["stages"] if s["key"] == "references")
    assert stage["summary"] == "3 intervenants sans fiche, 1 fiche sans image sur 5 intervenants"
    assert stage["examples"] == ["le garde", "des passants", "la serveuse", "Mina"] and stage["screen"] == "direction"
    # Garde d'une page : seuls ses intervenants comptent (page 2 : Aiko, des passants, la serveuse).
    message = _refused(client.post(f"/pages/{d['pages'][1]['id']}/generate"), "stage.references")
    assert "2 intervenants sans fiche (des passants, la serveuse) sur 3 intervenants" in message
    # Le lettrage et l'export ne sont jamais bloqués par les références (chapitres déjà en cours).
    assert next(s for s in _ok(client.get(f"/chapters/{chapter_id}/stages"))["stages"] if s["key"] == "references")[
        "blocks"
    ] == ["générer"]


def test_create_card_for_the_guard_then_portrait_unblocks_generation(client: TestClient) -> None:
    d = _setup(client)
    chapter_id, project_id = d["chapter"]["id"], d["series"]["id"]
    draft = _ok(client.post(f"/chapters/{chapter_id}/cast/draft", json={"name": "le garde"}))
    assert draft["name"] == "Le garde" and draft["written"] == "le garde" and draft["panel_count"] == 2
    assert "Le garde barre la porte" in draft["visual_description"]  # tiré de ses cases
    assert draft["age"] and draft["silhouette"] and draft["tenue"] and draft["signe_distinctif"]
    assert draft["prompt_keywords"]
    # L'auteur relit, puis crée la fiche : le nom écrit la retrouve dans toutes les cases.
    garde = _ok(
        client.post(
            f"/projects/{project_id}/characters",
            json={"name": draft["name"], "visual_description": draft["visual_description"]},
        ),
        201,
    )
    members = _cast(client, chapter_id)
    assert members["Le garde"]["character_id"] == garde["id"] and members["Le garde"]["fault"] == "sans image"
    # Portrait (mock) gardé comme référence : le garde sort des fautes.
    [job] = _ok(
        client.post(f"/characters/{garde['id']}/reference-variants", json={"sheet": "personnage-portrait", "count": 1}),
        202,
    )
    _wait(client)
    variant_id = _ok(client.get(f"/jobs/{job['id']}"))["params"]["variant_id"]
    _ok(client.post(f"/reference-variants/{variant_id}/keep"), 201)
    members = _cast(client, chapter_id)
    assert members["Le garde"]["fault"] is None and members["Le garde"]["references"] == "portrait"
    # Les autres : Mina reçoit une image, la serveuse une fiche, les passants sont une foule sans fiche.
    _image(client, d["mina"]["id"])
    serveuse = _ok(client.post(f"/projects/{project_id}/characters", json={"name": "La serveuse"}), 201)
    _image(client, serveuse["id"])
    _ok(client.post(f"/chapters/{chapter_id}/cast/crowds", json={"name": "des passants", "author": "Ouro"}))
    force_stages(client, chapter_id, "direction")
    _ok(client.post(f"/chapters/{chapter_id}/generate"), 202)
    _wait(client)


def test_create_everything_for_secondaries_queues_one_portrait_each(client: TestClient) -> None:
    d = _setup(client)
    chapter_id = d["chapter"]["id"]
    out = _ok(client.post(f"/chapters/{chapter_id}/cast/secondaries"))
    items = {i["name"]: i for i in out["items"]}
    # Foule exclue (à marquer) ; Mina a déjà sa fiche : seulement son portrait.
    assert set(items) == {"le garde", "Mina", "la serveuse"}
    assert items["le garde"]["created"] and items["la serveuse"]["created"] and not items["Mina"]["created"]
    assert all(i["queued"] for i in items.values()) and len(out["jobs"]) == 3
    _wait(client)
    members = _cast(client, chapter_id)
    for name in ("Le garde", "Mina", "La serveuse"):
        assert members[name]["fault"] is None and members[name]["references"] == "portrait", members[name]
    assert [m["name"] for m in _ok(client.get(f"/chapters/{chapter_id}/cast"))["members"] if m["fault"]] == [
        "des passants"
    ]
    # Rien à refaire au second passage.
    again = _ok(client.post(f"/chapters/{chapter_id}/cast/secondaries"))
    assert again["items"] == [] and again["jobs"] == []


# --- foules sans fiche ----------------------------------------------------------------------------------------
def test_crowd_mark_is_traced_and_reversible(client: TestClient) -> None:
    d = _setup(client)
    chapter_id = d["chapter"]["id"]
    url = f"/chapters/{chapter_id}/cast/crowds"
    out = _ok(client.post(url, json={"name": "des passants", "author": "Ouro"}))
    [mark] = out["marks"]
    assert mark["name"] == "des passants" and mark["author"] == "Ouro" and mark["at"]
    passants = next(m for m in out["members"] if m["name"] == "des passants")
    assert passants["mark"]["id"] == mark["id"] and passants["fault"] is None
    assert (out["total"], out["faults"]) == (4, 3)  # n'est plus compté
    assert "des passants" not in _ok(client.get(f"/chapters/{chapter_id}/stages"))["stages"][3]["examples"]
    # Un intervenant nommé ne se marque pas : il lui faut une fiche.
    assert "pas une foule anonyme" in _refused(client.post(url, json={"name": "le garde"}), "name")
    assert "déjà marqué" in _refused(client.post(url, json={"name": "Des passants"}), "name")
    _refused(client.post(url, json={"name": "Mina"}), "name")  # a déjà une fiche
    _refused(client.post(url, json={"name": "un inconnu"}), "name")  # cité nulle part
    # Lever la marque : la foule redevient une faute ; la trace reste (qui, quand).
    out = _ok(client.request("DELETE", f"{url}/{mark['id']}", json={"author": "Ouro"}))
    assert out["marks"] == [] and (out["total"], out["faults"]) == (5, 4)
    assert client.delete(f"{url}/{mark['id']}").status_code == 422  # déjà levée
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        [row] = session.scalars(select(ChapterCrowdMark)).all()
        assert (row.author, row.revoked_by) == ("Ouro", "Ouro") and row.revoked_at is not None
        notes = [e.note for e in session.scalars(select(GenerationEvent).order_by(GenerationEvent.id))]
        assert notes == [
            "Chapitre 1 · « des passants » marqué foule sans fiche par Ouro",
            "Chapitre 1 · « des passants » n'est plus une foule sans fiche (levé par Ouro)",
        ]


def test_link_from_script_tab_and_workshop_reads_the_same_list(client: TestClient) -> None:
    d = _setup(client)
    chapter_id = d["chapter"]["id"]
    panel = d["pages"][1]["panels"][0]
    assert panel["unmatched_characters"] == ["des passants"]
    url = f"/chapters/{chapter_id}/character-links"
    # « Écarter (figurant) » d'un nommé : refusé (plus de sortie silencieuse).
    _refused(client.post(url, json={"name": "le garde", "character_id": None}), "character_id")
    # Foule : marquée « foule sans fiche » par le même lien, tracée, plus signalée nulle part.
    _ok(client.post(url, json={"name": "des passants", "character_id": None}))
    assert _ok(client.get(f"/panels/{panel['id']}"))["unmatched_characters"] == []
    pages = _ok(client.get(f"/chapters/{chapter_id}/pages"))
    assert pages[1]["panels"][0]["unmatched_characters"] == []
    assert _cast(client, chapter_id)["des passants"]["mark"] is not None
    # « Relier à une fiche » : le nom devient un alias, la distribution suit.
    link = _ok(client.post(url, json={"name": "le garde", "character_id": d["mina"]["id"]}))
    assert link["alias_added"]
    members = _cast(client, chapter_id)
    assert "le garde" not in members and members["Mina"]["panel_count"] == 2


# --- préremplissage de la fiche ----------------------------------------------------------------------------------
def test_draft_retries_an_invalid_answer_then_succeeds(client: TestClient) -> None:
    d = _setup(client, garde="Le garde barre la porte. [mock:fiche-invalide:1]")
    out = _ok(client.post(f"/chapters/{d['chapter']['id']}/cast/draft", json={"name": "le garde"}))
    assert out["visual_description"] and "[mock" not in out["visual_description"]


def test_draft_gives_a_readable_error_after_the_retries(client: TestClient) -> None:
    d = _setup(client, garde="Le garde barre la porte. [mock:fiche-invalide:3]")
    chapter_id = d["chapter"]["id"]
    message = _refused(client.post(f"/chapters/{chapter_id}/cast/draft", json={"name": "le garde"}), "name")
    assert message.startswith("Fiche de « le garde » non préremplie : réponse du LLM invalide après 3 essais")
    assert "Traceback" not in message
    assert "a déjà une fiche" in _refused(
        client.post(f"/chapters/{chapter_id}/cast/draft", json={"name": "Mina"}), "name"
    )


def test_draft_parser_and_retry_loop() -> None:
    with pytest.raises(ValueError, match="JSON illisible"):
        parse_draft("Voici la fiche")
    with pytest.raises(ValueError, match="description"):
        parse_draft('{"age": "trentaine", "description": ""}')
    draft = parse_draft(
        '```json\n{"description": "Un garde trapu au casque cabossé.", "mots_cles": "casque, lance"}\n```'
    )
    assert draft.mots_cles == ["casque", "lance"]
    prompt = PresetRegistry.load(PRESETS_DIR).prompt("fiche-intervenant")
    ctx = DraftContext("le garde", "secondaire", "Le Palais", "shonen", [])
    answers = iter(["pas du JSON", '{"description": ""}', '{"description": "Un garde trapu au casque cabossé."}'])
    llm = MockLLMProvider(lambda _messages, _json: next(answers))
    assert draft_character(llm, prompt, ctx).description.startswith("Un garde trapu")
    # Le nouvel essai reçoit l'erreur du précédent.
    assert "JSON illisible" in llm.calls[1][-1].content
    always_bad = MockLLMProvider(lambda _messages, _json: "rien")
    with pytest.raises(CastDraftError, match="après 3 essais"):
        draft_character(always_bad, prompt, ctx)
