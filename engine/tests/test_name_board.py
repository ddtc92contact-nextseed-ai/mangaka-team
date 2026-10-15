"""Name (pipeline/name_board.py) : valider la planche brouillon page par page, étape `name` de la garde d'étapes
(propre refusé sur une page non validée, passer-outre, dévalidation après modification), couper une case en
deux, corrections rapides (plan, réplique). Tout en mock : aucun appel réel à ComfyUI ni au LLM."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from fastapi.testclient import TestClient

from tests.conftest import STYLE, force_stages, png_bytes
from tests.test_generation import make_client  # noqa: F401 — fixture

# Étapes réglées à la main dans ces tests : tout sauf la name.
OTHERS = ("script", "direction", "layout", "references", "prompts")


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


def _setup(c: TestClient, *, sketch: bool = True) -> dict[str, Any]:
    """Série (palier croquis), Aiko avec référence, 2 pages : page 1 = 2 cases dont la 2e a deux répliques
    (accents compris), page 2 = 1 case."""
    s = _ok(c.post("/projects", json={**STYLE, "title": "Les Lames", "sketch_enabled": sketch}), 201)
    aiko = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": "Aiko"}), 201)
    _ok(c.post(f"/characters/{aiko['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    chapter = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Pluie"}), 201)
    pages = _ok(
        c.put(
            f"/chapters/{chapter['id']}/pages",
            json={
                "pages": [
                    {
                        "panels": [
                            {"description": "Aiko sur un toit", "characters": ["Aiko"], "shot_type": "plan large"},
                            {
                                "description": "Aiko saute, puis atterrit dans la ruelle",
                                "characters": ["Aiko"],
                                "dialogues": [
                                    {"speaker": "Aiko", "text": "Là-haut, déjà ?"},
                                    {"speaker": "Aiko", "text": "Ça glisse… é à è !", "kind": "shout"},
                                ],
                            },
                        ]
                    },
                    {"panels": [{"description": "La ville sous la pluie"}]},
                ]
            },
        )
    )
    assert all(p["layout"] for p in pages)
    return {"series": s, "chapter": chapter, "pages": pages, "panels": [pa for p in pages for pa in p["panels"]]}


def _pages(c: TestClient, chapter_id: int) -> list[dict[str, Any]]:
    return _ok(c.get(f"/chapters/{chapter_id}/pages"))


def _page(c: TestClient, chapter_id: int, page_id: int) -> dict[str, Any]:
    return next(p for p in _pages(c, chapter_id) if p["id"] == page_id)


def _name(c: TestClient, chapter_id: int) -> dict[str, Any]:
    return next(s for s in _ok(c.get(f"/chapters/{chapter_id}/stages"))["stages"] if s["key"] == "name")


def _images(c: TestClient, panel_id: int) -> list[dict[str, Any]]:
    return _ok(c.get(f"/panels/{panel_id}/images"))


def _sketch(c: TestClient, page_id: int) -> None:
    _ok(c.post(f"/pages/{page_id}/sketch"), 202)
    _wait(c)


# --- validation ----------------------------------------------------------------------------
def test_validate_name_needs_sketches_and_retains_them(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = _setup(c)
    cid = data["chapter"]["id"]
    page1, page2 = data["pages"]
    assert (page1["name_state"], page2["name_state"]) == ("pending", "pending")
    name = _name(c, cid)
    assert (name["total"], name["faults"], name["passed"]) == (2, 2, False)
    assert name["label"] == "Name validée" and name["screen"] == "croquis"
    assert "générer" in name["blocks"] and "passer au propre" in name["blocks"]

    msg = _refused(c.post(f"/pages/{page1['id']}/name/validate"), "name")
    assert "cases 1, 2 pas encore croquées" in msg

    _sketch(c, page1["id"])
    page = _ok(c.post(f"/pages/{page1['id']}/name/validate", json={"author": "ouro"}))
    assert page["name_state"] == "validated" and page["name_validated_at"]
    # Les derniers croquis deviennent les croquis retenus (source de composition du propre).
    for panel in page["panels"]:
        [sketch] = _images(c, panel["id"])
        assert panel["sketch_validated"] and panel["sketch_image_id"] == sketch["id"]
    name = _name(c, cid)
    assert (name["total"], name["faults"], name["examples"]) == (2, 1, ["page 2"])

    # Retirer la validation : la page repasse « à valider », les croquis retenus restent.
    page = _ok(c.delete(f"/pages/{page1['id']}/name/validate"))
    assert page["name_state"] == "pending" and all(p["sketch_validated"] for p in page["panels"])


def test_no_name_stage_without_sketch_tier(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    """Série sans palier croquis : rien à vérifier, la génération n'attend pas de name."""
    c = make_client()
    data = _setup(c, sketch=False)
    cid = data["chapter"]["id"]
    assert all(p["name_state"] is None for p in data["pages"])
    name = _name(c, cid)
    assert name["complete"] and name["summary"] == "rien à vérifier" and name["blocks"] == []
    _refused(c.post(f"/pages/{data['pages'][0]['id']}/name/validate"), "name")
    force_stages(c, cid, *OTHERS)
    assert _ok(c.post(f"/chapters/{cid}/generate"), 202)["panel_ids"]


# --- garde d'étapes ------------------------------------------------------------------------
def test_clean_refused_on_unvalidated_page_then_allowed(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = _setup(c)
    cid = data["chapter"]["id"]
    page1, page2 = data["pages"]
    p1, p2, p3 = data["panels"]
    force_stages(c, cid, *OTHERS)
    _sketch(c, page1["id"])
    _sketch(c, page2["id"])
    _ok(c.post(f"/panels/{p3['id']}/sketch/validate"))

    # Page non validée : propre (page, case, chapitre) et génération en qualité refusés, l'étape est nommée.
    for resp in (
        c.post(f"/pages/{page2['id']}/clean"),
        c.post(f"/panels/{p3['id']}/clean"),
        c.post(f"/chapters/{cid}/clean"),
        c.post(f"/pages/{page2['id']}/generate"),
        c.post(f"/chapters/{cid}/generate"),
    ):
        msg = _refused(resp, "stage.name")
        assert "Name non validée" in msg and "passe outre" in msg
    assert "page 2" in _refused(c.post(f"/pages/{page2['id']}/clean"), "stage.name")
    assert "avant de passer au propre" in _refused(c.post(f"/pages/{page2['id']}/clean"), "stage.name")
    assert all(i["kind"] == "croquis" for i in _images(c, p3["id"]))

    # Page 2 validée : son propre part du croquis retenu ; la page 1 reste refusée.
    [sketch3] = _images(c, p3["id"])
    _ok(c.post(f"/pages/{page2['id']}/name/validate"))
    res = _ok(c.post(f"/pages/{page2['id']}/clean"), 202)
    assert res["panel_ids"] == [p3["id"]] and res["jobs"][0]["params"]["source_image_id"] == sketch3["id"]
    _wait(c)
    _ok(c.post(f"/panels/{p1['id']}/sketch/validate"))
    _refused(c.post(f"/panels/{p1['id']}/clean"), "stage.name")
    # « Générer le chapitre » (palier croquis) ne passe au propre que les pages validées.
    plan = _ok(c.get(f"/chapters/{cid}/produce"))
    assert plan["to_clean"] == 0

    # Passer outre l'étape : le propre de la page 1 non validée part.
    _ok(c.post(f"/chapters/{cid}/stages/name/override", json={"author": "ouro", "note": "relu sur papier"}))
    assert _name(c, cid)["forced"]
    assert _ok(c.get(f"/chapters/{cid}/produce"))["to_clean"] == 1
    assert len(_ok(c.post(f"/panels/{p1['id']}/clean"), 202)) == 1
    _wait(c)


def test_change_after_validation_devalidates_page(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    """Description, plan, découpe ou nouveau croquis après validation : la page n'est plus validée et le
    propre est de nouveau refusé ; une autre page validée ne bouge pas."""
    c = make_client()
    data = _setup(c)
    cid = data["chapter"]["id"]
    page1, page2 = data["pages"]
    p1, p2, p3 = data["panels"]
    force_stages(c, cid, *OTHERS)
    _sketch(c, page1["id"])
    _sketch(c, page2["id"])

    def validate_all() -> None:
        for page in (page1, page2):
            _ok(c.post(f"/pages/{page['id']}/name/validate"))
        assert _name(c, cid)["complete"]

    def stale_page1() -> None:
        assert _page(c, cid, page1["id"])["name_state"] == "stale"
        assert _page(c, cid, page2["id"])["name_state"] == "validated"
        name = _name(c, cid)
        assert not name["passed"] and name["examples"] == ["page 1"]
        _refused(c.post(f"/pages/{page1['id']}/clean"), "stage.name")

    validate_all()
    _ok(c.patch(f"/panels/{p1['id']}", json={"description": "Aiko sur un toit, sous l'orage"}))
    stale_page1()

    validate_all()
    _ok(c.patch(f"/panels/{p2['id']}", json={"shot_type": "gros plan"}))
    stale_page1()

    validate_all()
    _ok(c.post(f"/panels/{p1['id']}/sketch"), 202)  # nouveau croquis : la composition retenue saute
    _wait(c)
    stale_page1()

    validate_all()
    _ok(c.post(f"/panels/{p2['id']}/split", json={"sketch": False}))
    stale_page1()

    # Une réplique réécrite ne touche pas au dessin : la name reste validée.
    _sketch(c, page1["id"])  # les deux cases coupées, pas re-croquées ici
    validate_all()
    bubble = _page(c, cid, page1["id"])["panels"][1]["dialogues"][0]
    _ok(c.patch(f"/bubbles/{bubble['id']}", json={"text": "Déjà là ?"}))
    assert _page(c, cid, page1["id"])["name_state"] == "validated"


# --- couper une case en deux --------------------------------------------------------------
def test_split_panel_relayouts_and_only_touches_the_split_panels(
    make_client: Callable[..., TestClient],  # noqa: F811
) -> None:
    c = make_client()
    data = _setup(c)
    cid = data["chapter"]["id"]
    page1, page2 = data["pages"]
    p1, p2, p3 = data["panels"]
    _sketch(c, page1["id"])
    _sketch(c, page2["id"])
    _ok(c.post(f"/panels/{p1['id']}/sketch/validate"))
    _ok(c.post(f"/panels/{p1['id']}/generate"), 202)  # une version propre de la case 1 (essai libre)
    _wait(c)
    before = {pid: _images(c, pid) for pid in (p1["id"], p3["id"])}
    old = {p["id"]: p for pg in _pages(c, cid) for p in pg["panels"]}
    bubbles = old[p2["id"]]["dialogues"]
    assert [b["text"] for b in bubbles] == ["Là-haut, déjà ?", "Ça glisse… é à è !"]

    res = _ok(
        c.post(
            f"/panels/{p2['id']}/split",
            json={
                "first": "Aiko saute du toit",
                "second": "Aiko atterrit dans la ruelle",
                "move_bubble_ids": [bubbles[1]["id"]],
            },
        )
    )
    page = res["page"]
    new_id = res["panel_ids"][1]
    assert res["panel_ids"][0] == p2["id"] and res["sketch_note"] is None
    assert [p["id"] for p in page["panels"]] == [p1["id"], p2["id"], new_id]
    assert [p["index"] for p in page["panels"]] == [0, 1, 2]
    # Page remise en page : trois cadres, chacun relié à sa case.
    assert [lp["panel_id"] for lp in page["layout"]["panels"]] == [p1["id"], p2["id"], new_id]
    assert all(p["bbox"] for p in page["panels"]) and not page["layout_stale"]
    first, second = page["panels"][1], page["panels"][2]
    assert first["description"] == "Aiko saute du toit" and second["description"] == "Aiko atterrit dans la ruelle"
    assert second["characters"] == ["Aiko"]
    assert [b["text"] for b in first["dialogues"]] == ["Là-haut, déjà ?"]
    assert [b["text"] for b in second["dialogues"]] == ["Ça glisse… é à è !"]
    assert not first["sketch_validated"] and not second["sketch_validated"]

    # Seules les deux cases touchées sont re-croquées.
    assert sorted(j["panel_id"] for j in res["jobs"]) == sorted([p2["id"], new_id])
    assert all(j["params"]["kind"] == "croquis" for j in res["jobs"])
    _wait(c)
    assert len(_images(c, p2["id"])) == 2 and len(_images(c, new_id)) == 1
    # Ni les versions ni les croquis des autres cases ne changent.
    after = {p["id"]: p for pg in _pages(c, cid) for p in pg["panels"]}
    for pid in (p1["id"], p3["id"]):
        assert _images(c, pid) == before[pid]
        for key in ("sketch_image_id", "sketch_validated", "selected_image_id", "image_count", "sketch_count"):
            assert after[pid][key] == old[pid][key], (pid, key)
    assert after[p3["id"]]["bbox"] == old[p3["id"]]["bbox"]  # l'autre page n'est pas remise en page

    # Le lettrage suit : trois cases, les répliques dans leur nouvelle case.
    lettering = _ok(c.get(f"/pages/{page1['id']}/lettering"))
    assert [p["id"] for p in lettering["panels"]] == [p1["id"], p2["id"], new_id]
    assert {b["panel_id"] for b in lettering["bubbles"] if b["text"].startswith("Ça glisse")} == {new_id}


def test_split_refuses_foreign_bubbles(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = _setup(c)
    p1, p2, _ = data["panels"]
    foreign = p2["dialogues"][0]["id"]
    _refused(c.post(f"/panels/{p1['id']}/split", json={"move_bubble_ids": [foreign]}), "split")
    assert len(_page(c, data["chapter"]["id"], data["pages"][0]["id"])["panels"]) == 2


# --- corrections rapides --------------------------------------------------------------------
def test_change_plan_overrides_direction_and_delete_reply(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    c = make_client()
    data = _setup(c)
    cid = data["chapter"]["id"]
    p1, p2, _ = data["panels"]
    detail = _ok(c.patch(f"/panels/{p1['id']}", json={"shot_type": "Gros  plan"}))
    assert detail["shot_type"] == "gros plan" and detail["framing_plan"] == "gros plan"
    _refused(c.patch(f"/panels/{p1['id']}", json={"shot_type": "plan bizarre"}), "shot_type")
    detail = _ok(c.patch(f"/panels/{p1['id']}", json={"shot_type": None}))
    assert detail["shot_type"] is None

    first, second = p2["dialogues"]
    lettering = _ok(c.delete(f"/bubbles/{first['id']}/reply"))
    assert [b["text"] for b in lettering["bubbles"]] == ["Ça glisse… é à è !"]
    [panel] = [p for p in _page(c, cid, data["pages"][0]["id"])["panels"] if p["id"] == p2["id"]]
    assert [b["id"] for b in panel["dialogues"]] == [second["id"]]
    assert c.delete(f"/bubbles/{first['id']}/reply").status_code == 404
