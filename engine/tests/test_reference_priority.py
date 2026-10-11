"""Cases : jusqu'à 5 références choisies par importance, consigne de tri par référence, tonalité « papier
blanc » (prompt) et contrôle de tonalité du QC (#95)."""

from __future__ import annotations

import io
import string
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from mangaka_engine.config import Settings
from mangaka_engine.main import create_app
from mangaka_engine.pipeline.generation import PanelCast, choose_references, dropped_reference
from mangaka_engine.pipeline.prompt import ReferenceSlot, frame_references, sorting_lines
from mangaka_engine.pipeline.qc import LayerResult, QCExecutor, apply_tone, check_tone, dark_scene_keyword
from mangaka_engine.presets import ImagePromptSettings, PresetRegistry
from mangaka_engine.presets.schemas import QCRule
from mangaka_engine.store.models import AssetKind, Character, CharacterImage, SeriesAsset, SeriesAssetImage
from tests.conftest import PRESETS_DIR, png_bytes
from tests.test_generation import _ok, _wait, setup_chapter
from tests.test_qc import providers

REG = PresetRegistry.load(PRESETS_DIR)
QC = REG.require_qc()
TONE = QC.detectors.tone
assert TONE is not None and QC.detectors.rules.too_dark is not None


# --- priorité des références ------------------------------------------------------------------
def _char(i: int, name: str) -> Character:
    return Character(id=i, name=name, reference_images=[CharacterImage(id=i * 10)])


def _asset(i: int, name: str, kind: AssetKind) -> SeriesAsset:
    return SeriesAsset(id=i, kind=kind, name=name, reference_images=[SeriesAssetImage(id=i * 10)])


def test_four_characters_two_objects_and_style_with_five_slots() -> None:
    chars = [_char(1, "Urus"), _char(2, "Kael"), _char(3, "Mira"), _char(4, "Stan")]
    objects = [_asset(7, "Épée", AssetKind.object), _asset(8, "Lanterne", AssetKind.object)]
    style = _asset(9, "Planche de style", AssetKind.style)
    cast = PanelCast(characters=chars, objects=objects, style=style)
    choice = choose_references(cast.reference_entries, 5, "principale")
    assert [e.name for e, _ in choice.sent] == ["Urus", "Kael", "Mira", "Stan", "Épée"]
    assert [dropped_reference(e) for e in choice.dropped] == [
        {"kind": "object", "id": 8, "name": "Lanterne"},
        {"kind": "style", "id": 9, "name": "Planche de style"},
    ]
    # `toutes` : le 1er tour sert chaque fiche dans le même ordre, le résultat est identique ici.
    assert [e.name for e, _ in choose_references(cast.reference_entries, 5).sent] == [e.name for e, _ in choice.sent]


def test_a_present_character_is_never_dropped_while_an_object_holds_a_slot() -> None:
    chars = [_char(i, f"P{i}") for i in range(1, 7)]  # 6 personnages pour 5 emplacements
    decor = _asset(50, "Le labo", AssetKind.decor)
    cast = PanelCast(characters=chars, decor=decor, objects=[_asset(70, "Robot", AssetKind.object)])
    choice = choose_references(cast.reference_entries, 5, "principale")
    assert all(isinstance(e, Character) for e, _ in choice.sent)
    assert [e.name for e in choice.dropped] == ["P6", "Le labo", "Robot"]
    # Une fiche sans image n'est pas « écartée » : elle n'avait rien à envoyer.
    empty = Character(id=99, name="Sans image", reference_images=[])
    assert choose_references([empty, *chars[:2]], 5).dropped == []


def test_speakers_come_first_then_panel_order() -> None:
    chars = [_char(1, "Urus"), _char(2, "Kael"), _char(3, "Mira")]
    cast = PanelCast(characters=chars, decor=_asset(5, "Labo", AssetKind.decor), speakers=[3, 2, 3])
    assert [e.name for e in cast.reference_entries] == ["Mira", "Kael", "Urus", "Labo"]
    assert [e.name for e in cast.entries] == ["Urus", "Kael", "Mira", "Labo"]  # ordre de la case inchangé
    # 2 emplacements : le personnage qui ne parle pas est écarté, pas celui qui parle.
    choice = choose_references(cast.reference_entries, 2, "principale")
    assert [e.name for e, _ in choice.sent] == ["Mira", "Kael"]
    assert [e.name for e in choice.dropped] == ["Urus", "Labo"]


# --- consigne de tri ------------------------------------------------------------------------------
def test_each_sent_reference_gets_its_sorting_sentence_from_the_preset() -> None:
    settings = REG.image_prompt
    slots = [
        ReferenceSlot("character", "Urus"),
        ReferenceSlot("character", "Kael"),
        ReferenceSlot("object", "Épée"),
        ReferenceSlot("decor", "Le labo"),
        ReferenceSlot("style", "Planche de style"),
    ]
    framed = frame_references("Urus faces Kael in the lab.", slots, settings)
    sorting = settings.references.sorting
    for i, slot in enumerate(slots, start=1):
        sentence = string.Template(getattr(sorting, slot.kind)).substitute(slot=str(i), name=slot.name)
        assert sentence in framed, sentence
    assert (
        "From <image1> take only the face, hair, body and outfit of Urus; ignore its layout, pose grid, rules, "
        "labels and white background." in framed
    )
    assert "From <image2> take only the face, hair, body and outfit of Kael" in framed
    assert "From <image3> take only the shape and details of the object Épée" in framed
    assert "From <image5> take only the rendering" in framed and "never take its characters" in framed
    # Consignes après la scène (même pour un prompt rédigé par l'IA, qui ne reçoit que `after`).
    assert framed.index("Urus faces Kael") < framed.index("From <image1>")
    written = "<image1> is Urus. <image2> is Kael. <image3> is the sword. <image4> is the lab. <image5> is the style."
    assert "From <image4> take only" in frame_references(written, slots, settings)


def test_sorting_templates_come_from_the_preset_not_the_code() -> None:
    custom = ImagePromptSettings.model_validate(
        {"references": {"sorting": {"character": "Prends de <image$slot> le visage de $name seulement."}}}
    )
    slots = [ReferenceSlot("character", "Aiko"), ReferenceSlot("object", "Robot")]
    assert sorting_lines(slots, custom) == ["Prends de <image1> le visage de Aiko seulement."]  # objet : vide
    assert sorting_lines(slots, ImagePromptSettings()) == []  # rien dans le code


# --- QC : tonalité ------------------------------------------------------------------------------
def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mostly_black() -> bytes:
    img = Image.new("L", (200, 200), 10)
    ImageDraw.Draw(img).rectangle((0, 0, 59, 199), fill=240)  # 30 % clair, 70 % noir pur
    return _png(img)


def _white_line_art() -> bytes:
    img = Image.new("L", (200, 200), 250)
    draw = ImageDraw.Draw(img)
    for x in range(10, 200, 25):
        draw.line((x, 0, x + 40, 200), fill=0, width=3)
    draw.ellipse((60, 60, 140, 140), outline=0, width=4)
    return _png(img)


def test_mostly_black_panel_is_flagged_with_reason_and_percentages() -> None:
    tone = check_tone(_mostly_black(), TONE)
    assert tone.checked and tone.too_dark
    assert round(tone.dark or 0, 2) == 0.70 and round(tone.black or 0, 2) == 0.70
    res = apply_tone(LayerResult("done", score=100), tone, QC.detectors.rules.too_dark)
    rule = QC.detectors.rules.too_dark
    assert rule is not None and res.score == 100 - rule.penalty and res.at_least is not None
    assert res.at_least.value in ("review", "reject")
    assert res.reasons == [
        f"Case trop sombre : 70 % de pixels sombres, cible ≤ {round(TONE.max_dark * 100)} % ; "
        f"70 % de noir pur, cible ≤ {round(TONE.max_black * 100)} %"
    ]
    assert res.extra["tone"]["dark"] == 0.7 and res.extra["tone"]["too_dark"] is True


def test_dark_only_reason_matches_the_issue_wording() -> None:
    img = Image.new("L", (100, 100), 250)
    ImageDraw.Draw(img).rectangle((0, 0, 99, 67), fill=90)  # 68 % sombres, aucun noir pur
    res = apply_tone(LayerResult("done", score=90), check_tone(_png(img), TONE), QCRule(penalty=25, at_least="review"))
    assert res.reasons == [f"Case trop sombre : 68 % de pixels sombres, cible ≤ {round(TONE.max_dark * 100)} %"]


def test_white_line_art_passes() -> None:
    tone = check_tone(_white_line_art(), TONE)
    assert tone.checked and not tone.too_dark and (tone.dark or 0) < TONE.max_dark
    res = apply_tone(LayerResult("done", score=100), tone, QC.detectors.rules.too_dark)
    assert res.score == 100 and res.reasons == [] and res.at_least is None
    assert res.extra["tone"]["checked"] is True


def test_unavailable_detectors_still_carry_the_tone_floor() -> None:
    res = apply_tone(
        LayerResult("unavailable", message="non installés"),
        check_tone(_mostly_black(), TONE),
        QCRule(penalty=25, at_least="review"),
    )
    assert res.score is None and res.at_least is not None and res.reasons[0].startswith("Case trop sombre")


def _panel(rendering: str, ambiance: str | None = None) -> Any:
    applied = {"panels": [{"panel_id": 1, "ambiance": ambiance}]} if ambiance is not None else None
    page = SimpleNamespace(
        chapter=SimpleNamespace(project=SimpleNamespace(style_rendering=rendering)),
        direction=SimpleNamespace(applied=applied) if applied else None,
    )
    return SimpleNamespace(id=1, page=page)


def test_colour_pack_and_night_scene_panels_are_not_checked() -> None:
    skip = QCExecutor._tone_skip(_panel("couleur"), QC, REG)
    assert skip is not None and "rendu couleur" in skip
    tone = check_tone(_mostly_black(), TONE, skip=skip)
    assert not tone.checked and not tone.too_dark and tone.dark is None
    assert apply_tone(LayerResult("done", score=100), tone, QC.detectors.rules.too_dark).score == 100
    assert QCExecutor._tone_skip(_panel("nb-trames"), QC, REG) is None
    assert QCExecutor._tone_skip(_panel("nb-trames", "ruelle sous la pluie, plein jour"), QC, REG) is None
    night = QCExecutor._tone_skip(_panel("nb-encre", "Nuit sans lune, pénombre"), QC, REG)
    assert night is not None and "nuit" in night
    assert dark_scene_keyword("Pénombre bleutée", ["penombre"]) == "penombre"
    assert dark_scene_keyword("darkroom", ["dark"]) is None  # mot entier seulement


# --- de bout en bout (mock) ---------------------------------------------------------------------
def _first_version(c: TestClient, panel_id: int) -> dict[str, Any]:
    # Le QC automatique peut relancer un essai (visages factices) : on suit la 1re version.
    return next(i for i in _ok(c.get(f"/panels/{panel_id}/images")) if i["version"] == 1)


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    """Client avec toutes les couches du QC simulées (QC automatique après chaque génération)."""
    clients: list[TestClient] = []

    def _make() -> TestClient:
        c = TestClient(create_app(make_settings(), providers=providers()))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def test_generation_records_dropped_references_tone_and_tonality(make_client: Callable[..., TestClient]) -> None:
    c = make_client()
    data = setup_chapter(c)
    s = data["series"]
    # 5 personnages avec image + 1 objet pour 5 emplacements.
    names = ["Ren", "Mira", "Stan", "Yuki"]
    for name in names:
        ch = _ok(c.post(f"/projects/{s['id']}/characters", json={"name": name}), 201)
        _ok(c.post(f"/characters/{ch['id']}/images", files=[("files", ("a.png", png_bytes(), "image/png"))]), 201)
    obj = _ok(c.post(f"/projects/{s['id']}/objects", json={"name": "Épée", "visual_description": "lame"}), 201)
    _ok(c.post(f"/objects/{obj['id']}/images", files=[("files", ("o.png", png_bytes(), "image/png"))]), 201)
    ch = _ok(c.post(f"/projects/{s['id']}/chapters", json={"title": "Mêlée"}), 201)
    panel = {
        "description": "Les cinq se font face",
        "characters": ["Aiko", *names],
        "objets": [obj["id"]],
        "dialogues": [{"speaker": "Yuki", "text": "Halte !"}],
    }
    [page] = _ok(c.put(f"/chapters/{ch['id']}/pages", json={"pages": [{"panels": [panel]}]}))
    panel_id = page["panels"][0]["id"]
    [job] = _ok(c.post(f"/panels/{panel_id}/generate"), 202)
    _wait(c)
    params = _ok(c.get(f"/jobs/{job['id']}"))["params"]
    # Yuki parle : premier servi ; puis l'ordre de la case. L'objet n'a plus d'emplacement.
    assert [r["name"] for r in params["references"]] == ["Yuki", "Aiko", "Ren", "Mira", "Stan"]
    assert params["dropped_references"] == [{"kind": "object", "id": obj["id"], "name": "Épée"}]
    img = _first_version(c, panel_id)
    assert img["params"]["dropped_references"] == params["dropped_references"]
    assert len(img["params"]["reference_images"]) == 5
    prompt, negative = img["params"]["prompt"], img["params"]["negative_prompt"]
    assert all(f"From <image{i}> take only" in prompt for i in range(1, 6))
    assert prompt.endswith("large white areas, no muddy grey fill.")
    # Palier Qualité (vrai CFG, négatif lu) : termes négatifs de tonalité.
    assert img["params"]["negative_active"] is True and "dark muddy image" in negative
    # QC automatique : tonalité mesurée (fond clair des cases factices) et visible dans les détails.
    _wait(c)
    img = _first_version(c, panel_id)
    tone = img["qc"]["layers"]["detectors"]["tone"]
    assert tone["checked"] is True and tone["too_dark"] is False
    assert 0 <= tone["dark"] < TONE.max_dark and tone["max_dark"] == TONE.max_dark
