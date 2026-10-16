"""FLUX 3 Klein : grille de composition à boîtes (`prompt_format: layout`) et banc A/B paragraphe / grille.

Tout est simulé (ComfyUI et contrôle qualité factices) : aucun appel ComfyUI réel.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mangaka_engine.bench import flux_layout
from mangaka_engine.pipeline.prompt_layout import LayoutBox, LayoutSubject, cite_boxes, layout_boxes, staging_places
from mangaka_engine.presets import PresetError, PresetRegistry, build_workflow
from mangaka_engine.providers.comfyui import MockComfyUIClient
from mangaka_engine.providers.factory import Providers
from mangaka_engine.providers.llm import MockLLMProvider
from mangaka_engine.providers.qc import MockDetectorProvider, MockIdentityProvider
from mangaka_engine.providers.vision import MockVisionProvider
from mangaka_engine.store.models import GenerationLog, Job, PanelImage
from tests.conftest import PRESETS_DIR
from tests.test_generation import _ok, _wait, make_client, setup_chapter  # noqa: F401 — fixture

REG = PresetRegistry.load(PRESETS_DIR)
GOLDEN = Path(__file__).parent / "golden" / "workflows"
PARAMS = {
    "positive_prompt": "plan moyen, Aiko sur un toit au crépuscule, encre et trames",
    "negative_prompt": "texte, bulles",
    "seed": 424242,
    "width": 832,
    "height": 1216,
    "filename_prefix": "mangaka/serie-1/chapitre-1/page-1/case-1",
}
REFERENCES = ["mangaka/perso1_img1.png", "mangaka/perso2_img4.png"]
FLUX_PARAGRAPH = [
    "flux3-klein-croquis",
    "flux3-klein-edit-ref-croquis",
    "flux3-klein-qualite",
    "flux3-klein-edit-ref-qualite",
    "flux3-klein-qualite-from-sketch",
    "flux3-klein-edit-ref-qualite-from-sketch",
]
LAYOUT = {
    "flux3-klein-qualite-layout": "flux3-klein-qualite",
    "flux3-klein-edit-ref-qualite-layout": "flux3-klein-edit-ref-qualite",
}
NAMES = ["Aiko", "Kenji", "Mei", "Taro", "Yuki"]


def _subjects(n: int) -> list[LayoutSubject]:
    return [LayoutSubject(name) for name in NAMES[:n]]


def _contains(a: LayoutBox, b: LayoutBox) -> bool:
    eps = 1e-9
    return a.x <= b.x + eps and a.y <= b.y + eps and a.x + a.w >= b.x + b.w - eps and a.y + a.h >= b.y + b.h - eps


def _center(box: LayoutBox) -> float:
    return box.x + box.w / 2


# --- rédacteur « layout » -----------------------------------------------------------------------
@pytest.mark.parametrize("n", [2, 3, 4, 5])
@pytest.mark.parametrize(
    "staging",
    [
        None,
        "Aiko à gauche au premier plan, Kenji au fond à droite, Mei au centre",
        "Kenji au premier plan, Aiko à l'arrière-plan, Taro au fond, Yuki à gauche",
        "Tous au fond de la salle",
    ],
)
def test_boxes_stay_in_the_panel_one_per_character_never_one_inside_another(n: int, staging: str | None) -> None:
    boxes = layout_boxes(_subjects(n), staging)
    assert [b.name for b in boxes] == NAMES[:n]  # une boîte par personnage, dans l'ordre de la distribution
    for b in boxes:
        assert min(b.x, b.y) >= 0 and min(b.w, b.h) > 0
        assert b.x + b.w <= 1 + 1e-9 and b.y + b.h <= 1 + 1e-9
    for a, b in itertools.permutations(boxes, 2):
        assert not _contains(a, b), (a, b)  # chevauchement partiel permis, jamais total


@pytest.mark.parametrize("n", [0, 1])
def test_zero_or_one_character_keeps_the_paragraph_alone(n: int) -> None:
    assert layout_boxes(_subjects(n), "Aiko à gauche") == []
    assert layout_boxes([LayoutSubject("Aiko"), LayoutSubject("aiko")]) == []  # le même personnage deux fois


@pytest.mark.parametrize(
    "staging",
    [
        "Kenji à gauche, Aiko à droite",
        "À gauche, Kenji ; à droite, Aiko",
        "Aiko se tient à droite de l'image. Kenji, à gauche, la regarde.",
        "Aiko lève la main gauche, Kenji à gauche",  # « main gauche » n'est pas une place dans la case
        "Kenji on the left, Aiko on the right",
    ],
)
def test_staging_left_and_right_are_respected(staging: str) -> None:
    aiko, kenji = layout_boxes(_subjects(2), staging)
    assert _center(kenji) < 0.5 < _center(aiko)
    assert kenji.source == "mise en scène"


def test_staging_center_depth_and_unplaced_characters() -> None:
    places = staging_places("Mei au centre. Aiko au premier plan à droite, Kenji au fond", ["Aiko", "Kenji", "Mei"])
    assert places["Mei"].column == "center"
    assert (places["Aiko"].column, places["Aiko"].depth) == ("right", "front")
    assert (places["Kenji"].column, places["Kenji"].depth) == (None, "back")
    aiko, kenji, mei = layout_boxes(_subjects(3), "Mei au centre. Aiko au premier plan à droite, Kenji au fond")
    assert _center(kenji) < _center(mei) < _center(aiko)  # Kenji non placé : la colonne libre
    assert aiko.h > kenji.h and kenji.y > aiko.y  # premier plan plus grand, arrière-plan plus haut et plus petit
    assert kenji.place == {"depth": "back"} and aiko.place == {"column": "right", "depth": "front"}


def test_fallback_is_deterministic_in_cast_order() -> None:
    first = layout_boxes(_subjects(3), "Ils marchent sous la pluie")
    assert first == layout_boxes(_subjects(3), "Ils marchent sous la pluie") == layout_boxes(_subjects(3))
    assert [b.source for b in first] == ["répartition"] * 3
    assert _center(first[0]) < _center(first[1]) < _center(first[2])  # Aiko, Kenji, Mei de gauche à droite


def test_box_description_and_citations() -> None:
    boxes = layout_boxes([LayoutSubject("Aiko", ("red kimono", "short black hair")), LayoutSubject("Kenji")])
    assert [b.desc for b in boxes] == ["Aiko, red kimono, short black hair", "Kenji"]
    prompt = cite_boxes("Aiko faces Kenji in the rain; Aiko smiles.", boxes)
    assert prompt == "Aiko <obj_1> faces Kenji <obj_2> in the rain; Aiko smiles."
    assert cite_boxes(prompt, boxes) == prompt  # déjà cité : inchangé
    assert cite_boxes("Two figures in the rain.", boxes) == "Two figures in the rain."


# --- presets et graphe --------------------------------------------------------------------------
def _build(preset_id: str, **kwargs: Any) -> Any:
    loaded = REG.workflow(preset_id)
    return build_workflow(
        loaded,
        PARAMS,
        reference_images=REFERENCES if loaded.preset.reference_images else [],
        source_image="mangaka/croquis_case1_v1.png" if loaded.preset.source_image else None,
        **kwargs,
    )


@pytest.mark.parametrize("preset_id", FLUX_PARAGRAPH)
def test_paragraph_preset_builds_exactly_the_graph_of_before(preset_id: str) -> None:
    """Golden produit par le code d'avant la grille (origin/main du 16/10/2026) : rien ne bouge."""
    preset = REG.workflow(preset_id).preset
    assert preset.prompt_format == "paragraph" and preset.layout is None
    built = _build(preset_id)
    assert json.loads((GOLDEN / f"{preset_id}.json").read_text(encoding="utf-8")) == built.workflow
    assert built.layout_boxes == []
    with pytest.raises(PresetError, match="n'a pas de grille de composition"):
        _build(preset_id, layout_boxes=[{"x": 0, "y": 0, "w": 0.5, "h": 1, "desc": "Aiko"}])


def test_every_shipped_preset_but_the_two_layout_ones_is_paragraph() -> None:
    assert REG.issues == []
    layout = {w.preset.id for w in REG.workflows.values() if w.preset.prompt_format == "layout"}
    assert layout == set(LAYOUT)
    for preset_id, base in LAYOUT.items():
        preset, parent = REG.workflow(preset_id).preset, REG.workflow(base).preset
        assert preset.engine == "flux3-klein" and preset.layout is not None and preset.tier is not None
        assert preset.tier.choice is None  # pas proposé comme palier de série : gain non mesuré
        assert (preset.defaults, preset.distilled, preset.reference_images) == (
            parent.defaults,
            parent.distilled,
            parent.reference_images,
        )
    assert REG.workflow("flux3-klein-qualite-layout").preset.with_references == "flux3-klein-edit-ref-qualite-layout"


@pytest.mark.parametrize(("preset_id", "base"), list(LAYOUT.items()))
def test_layout_graph_is_the_paragraph_graph_plus_the_two_box_nodes(preset_id: str, base: str) -> None:
    layout, parent = REG.workflow(preset_id).workflow, REG.workflow(base).workflow
    extra = {k: v for k, v in layout.items() if k not in parent}
    assert {v["class_type"] for v in extra.values()} == {"CreateBoundingBoxes", "Flux3LayoutPrompt"}
    for node_id, node in parent.items():
        expected = json.loads(json.dumps(node))
        if node_id == "4":
            expected["inputs"]["text"] = ["31", 0]  # le prompt positif encode la sortie de Flux3LayoutPrompt
        assert {k: v for k, v in layout[node_id].items() if k != "_meta"} == {
            k: v for k, v in expected.items() if k != "_meta"
        }


@pytest.mark.parametrize("preset_id", list(LAYOUT))
def test_build_workflow_wires_the_boxes(preset_id: str) -> None:
    boxes = [
        {"x": 0.0, "y": 0.1, "w": 0.6, "h": 0.88, "desc": "Aiko, red kimono"},
        {"x": 0.4, "y": 0.1, "w": 0.6, "h": 0.88, "desc": "Kenji"},
    ]
    built = _build(preset_id, layout_boxes=boxes)
    wf = built.workflow
    boxes_node = next(k for k, n in wf.items() if n["class_type"] == "CreateBoundingBoxes")
    prompt_node = next(k for k, n in wf.items() if n["class_type"] == "Flux3LayoutPrompt")
    # Le paragraphe entre dans Flux3LayoutPrompt, qui lit les éléments (sortie 2) des boîtes ; le prompt positif
    # (CLIPTextEncode du KSampler) encode sa sortie.
    assert wf[prompt_node]["inputs"] == {"prompt": PARAMS["positive_prompt"], "element": [boxes_node, 2]}
    sampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
    positive = sampler["inputs"]["positive"][0]
    if wf[positive]["class_type"] == "ReferenceMultiLatent":
        positive = wf[positive]["inputs"]["positive"][0]
    assert wf[positive]["inputs"]["text"] == [prompt_node, 0]
    inputs = wf[boxes_node]["inputs"]
    assert (inputs["width"], inputs["height"]) == (832, 1216)  # taille de la case, celle du latent
    # Liste enveloppée {"__value__": …} : nue, ComfyUI la lirait comme un lien (« Bad linked input »).
    assert inputs["editor_state"] == {
        "__value__": [
            {
                "x": 0,
                "y": 122,
                "width": 499,
                "height": 1070,
                "metadata": {"type": "obj", "text": "", "desc": "Aiko, red kimono", "palette": []},
            },
            {
                "x": 333,
                "y": 122,
                "width": 499,
                "height": 1070,
                "metadata": {"type": "obj", "text": "", "desc": "Kenji", "palette": []},
            },
        ]
    }
    assert built.layout_boxes == inputs["editor_state"]["__value__"]
    # Sans boîte (0 ou 1 personnage) : liste vide, le paragraphe passe seul.
    assert _build(preset_id).workflow[boxes_node]["inputs"]["editor_state"] == {"__value__": []}
    with pytest.raises(PresetError, match="hors de la case"):
        _build(preset_id, layout_boxes=[{"x": 0.6, "y": 0, "w": 0.6, "h": 1, "desc": "Aiko"}])


# --- génération d'une case ----------------------------------------------------------------------
def _two_characters(c: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """Chapitre de setup_chapter, plus une case où Kenji est à gauche et Aiko (fiche avec référence) à droite."""
    data = setup_chapter(c)
    pages = [
        {
            "panels": [
                {
                    "description": "Aiko et Kenji se font face sur un toit",
                    "characters": ["Aiko", "Kenji"],
                    "staging": "Kenji à gauche, Aiko à droite au premier plan",
                },
                {"description": "Kenji court", "characters": ["Kenji"]},
            ]
        },
        {"panels": [{"description": "Aiko et Kenji sous la pluie", "characters": ["Kenji", "Aiko"]}]},
    ]
    out = _ok(c.put(f"/chapters/{data['chapter']['id']}/pages", json={"pages": pages}))
    return data, out


def test_layout_panel_sends_its_boxes_and_cites_them(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    _, pages = _two_characters(c)
    panel = pages[0]["panels"][0]
    preset = "flux3-klein-edit-ref-qualite-layout"  # Aiko a une référence
    [job] = _ok(c.post(f"/panels/{panel['id']}/generate", json={"preset": preset}), 202)
    assert job["params"]["preset"] == preset
    _wait(c)
    [wf] = comfy.prompts.values()
    boxes = next(n for n in wf.values() if n["class_type"] == "CreateBoundingBoxes")["inputs"]["editor_state"]
    prompt = next(n for n in wf.values() if n["class_type"] == "Flux3LayoutPrompt")["inputs"]["prompt"]
    kenji, aiko = sorted(boxes["__value__"], key=lambda b: b["x"])
    # Série en noir et blanc : le mot-clé « kimono rouge » de la fiche d'Aiko n'entre pas dans sa boîte.
    assert kenji["metadata"]["desc"] == "Kenji" and aiko["metadata"]["desc"] == "Aiko"
    assert "<obj_1>" in prompt and "<obj_2>" in prompt
    version = _ok(c.get(f"/panels/{panel['id']}"))["images"][0]
    params = version["params"]
    assert params["prompt_format"] == "layout"
    assert [b["name"] for b in params["layout_boxes"]] == ["Aiko", "Kenji"]
    assert params["layout_boxes"][0]["place"] == {"column": "right", "depth": "front"}


def test_paragraph_panel_has_no_boxes(make_client: Callable[..., TestClient]) -> None:  # noqa: F811
    comfy = MockComfyUIClient()
    c = make_client(comfy)
    _, pages = _two_characters(c)
    panel = pages[0]["panels"][0]
    _ok(c.post(f"/panels/{panel['id']}/generate", json={"preset": "flux3-klein-qualite"}), 202)
    _wait(c)
    [wf] = comfy.prompts.values()
    assert not {"CreateBoundingBoxes", "Flux3LayoutPrompt"} & {n["class_type"] for n in wf.values()}
    assert not any("<obj_" in str(n["inputs"].get("text")) for n in wf.values())
    params = _ok(c.get(f"/panels/{panel['id']}"))["images"][0]["params"]
    assert "layout_boxes" not in params and "prompt_format" not in params


# --- banc A/B -----------------------------------------------------------------------------------
def _qc_providers(comfy: MockComfyUIClient) -> Providers:
    return Providers(
        llm=MockLLMProvider(),
        # La vision attend qu'aucune génération ne soit en cours : le bras B n'existe pas encore pendant le QC de A.
        vision=MockVisionProvider(),
        comfyui=comfy,
        detectors=MockDetectorProvider(),
        identity=MockIdentityProvider(),
        names={"llm": "mock", "comfyui": "mock"},
    )


def test_bench_runs_both_arms_with_the_same_seed_and_writes_a_report(
    make_client: Callable[..., TestClient],  # noqa: F811
    tmp_path: Path,
) -> None:
    c = make_client()
    data, pages = _two_characters(c)
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    comfy = MockComfyUIClient()
    out = tmp_path / "rapport"
    report = flux_layout.run_bench(
        ctx.db,
        ctx.presets,
        ctx.files,
        _qc_providers(comfy),
        data["chapter"]["id"],
        out,
        limit=5,
        seed=7,
        mode="mock",
        log=lambda _m: None,
    )
    # Les cases à 2 personnages (page 1 case 1, page 2 case 1) ; jamais celle de Kenji seul.
    assert [p.panel_id for p in report.pairs] == [pages[0]["panels"][0]["id"], pages[1]["panels"][0]["id"]]
    assert len(comfy.prompts) == 4  # deux bras par case, l'un après l'autre
    workflows = list(comfy.prompts.values())
    for pair, (wf_a, wf_b) in zip(report.pairs, itertools.batched(workflows, 2), strict=True):
        a, b = pair.arms
        assert (a.arm, a.prompt_format, b.arm, b.prompt_format) == ("A", "paragraph", "B", "layout")
        assert (a.preset, b.preset) == ("flux3-klein-edit-ref-qualite", "flux3-klein-edit-ref-qualite-layout")
        assert a.status == b.status == "succeeded" and a.image and b.image
        assert (out / a.image).is_file() and (out / b.image).is_file()
        assert a.qc_verdict and b.qc_verdict and a.qc_score is not None and b.qc_score is not None
        seeds = {n["inputs"]["seed"] for wf in (wf_a, wf_b) for n in wf.values() if n["class_type"] == "KSampler"}
        assert seeds == {pair.seed}  # même graine
        refs = [
            sorted(n["inputs"]["image"] for n in wf.values() if n["class_type"] == "LoadImage") for wf in (wf_a, wf_b)
        ]
        assert refs[0] == refs[1] and refs[0]  # mêmes fiches
        assert "CreateBoundingBoxes" not in {n["class_type"] for n in wf_a.values()}
        boxes = next(n for n in wf_b.values() if n["class_type"] == "CreateBoundingBoxes")["inputs"]["editor_state"]
        assert len(boxes["__value__"]) == 2
    saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert saved["mode"] == "mock" and saved["summary"]["layout"]["succeeded"] == 2
    page = (out / "report.html").read_text(encoding="utf-8")
    assert "paragraphe contre grille" in page and page.count("<img ") == 4
    with ctx.db.session_scope() as session:
        jobs = list(session.scalars(select(Job).where(Job.params["bench"].as_string() == "flux_layout")))
        assert len(jobs) == 4 and {j.status.value for j in jobs} == {"succeeded"}
        logs = list(session.scalars(select(GenerationLog).where(GenerationLog.ab_mode == "layout")))
        assert {(g.ab_group, g.ab_arm) for g in logs} == {(p.group, arm) for p in report.pairs for arm in "AB"}


def test_bench_dry_run_prepares_without_writing_anything(
    make_client: Callable[..., TestClient],  # noqa: F811
    tmp_path: Path,
) -> None:
    c = make_client()
    data, _ = _two_characters(c)
    ctx = c.app.state.ctx  # type: ignore[attr-defined]
    comfy = MockComfyUIClient()
    with ctx.db.session_scope() as session:
        jobs_before = session.scalar(select(func.count()).select_from(Job))
    report = flux_layout.run_bench(
        ctx.db,
        ctx.presets,
        ctx.files,
        _qc_providers(comfy),
        data["chapter"]["id"],
        tmp_path,
        seed=1,
        limit=1,
        mode="dry-run",
        log=lambda _m: None,
    )
    assert len(report.pairs) == 1 and comfy.prompts == {}
    assert [a.status for a in report.pairs[0].arms] == ["prepared", "prepared"]
    with ctx.db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == jobs_before
        assert session.scalar(select(func.count()).select_from(PanelImage)) == 0
    assert (tmp_path / "report.html").is_file()


def test_bench_command_line_in_mock_mode(
    make_client: Callable[..., TestClient],  # noqa: F811
    make_settings: Callable[..., Any],
    tmp_path: Path,
    capsys: Any,
) -> None:
    c = make_client()
    data, _ = _two_characters(c)
    out = tmp_path / "cli"
    args = ["--chapter", str(data["chapter"]["id"]), "--limit", "1", "--mock", "--seed", "3", "--out", str(out)]
    assert flux_layout.main(args, settings=make_settings()) == 0
    saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert saved["mode"] == "mock" and len(saved["pairs"]) == 1
    assert [a["status"] for a in saved["pairs"][0]["arms"]] == ["succeeded", "succeeded"]
    assert "Rapport :" in capsys.readouterr().out
    assert flux_layout.main(["--chapter", "999", "--mock", "--out", str(out)], settings=make_settings()) == 1
    assert "chapitre 999 introuvable" in capsys.readouterr().err
