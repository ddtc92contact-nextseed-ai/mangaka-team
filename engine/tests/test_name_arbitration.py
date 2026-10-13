"""Noms ambigus (« trafiquant » pour « trafiquant 1 » et « trafiquant 2 ») : arbitrage explicite, alias, et
alerte à l'auteur (audit des chapitres 1 et 2 de la série ecoloman, case id 11).

Le chapitre 1 écrit « le trafiquant » sans numéro, et « angu » pour Angus. Avant, un nom à égalité entre deux
fiches était abandonné en silence : la case 11 (« Le trafiquant blêmit et recule, lâchant Seku ») était
dessinée sans aucune référence d'identité.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from mangaka_engine.pipeline.names import (
    AMBIGUOUS,
    ARBITRATION,
    CONTEXT,
    PLURAL,
    UNDECLARED,
    UNMATCHED,
    CharacterMatcher,
    name_notes,
    relink_project,
)
from mangaka_engine.store.models import Bubble, BubbleKind, Character, Panel
from tests.test_offscreen import _ecoloman, _generate, _ok, _save, _script, _sent_references

SEKU, ANGUS, T1, T2 = 1, 2, 5, 6


def _ecoloman_cards(**aliases: list[str]) -> CharacterMatcher:
    """Fiches de la base ecoloman (ids 1, 2, 5, 6 ; alias « trafiquant1 » / « trafiquant2 »)."""
    specs = [
        (SEKU, "seku", []),
        (ANGUS, "angus", []),
        (T1, "trafiquant 1", ["trafiquant1"]),
        (T2, "trafiquant 2", ["trafiquant2"]),
    ]
    return CharacterMatcher(
        Character(id=i, name=n, aliases=[*a, *aliases.get(n.replace(" ", ""), [])]) for i, n, a in specs
    )


# --- names.py ------------------------------------------------------------------------------------------
def test_generic_name_is_no_longer_dropped_without_warning() -> None:
    m = _ecoloman_cards()
    for written in ("trafiquant", "le trafiquant", "Trafiquant"):
        r = m.resolve(written)
        assert r.ids == (T1,) and r.how == ARBITRATION and r.ambiguous and r.candidates == (T1, T2), written
    assert m.match("trafiquant") == T1 and m.ids(["trafiquant"]) == [T1] and m.unmatched(["trafiquant"]) == []
    # Un numéro, ou l'alias de la base, désigne la fiche sans arbitrage.
    assert m.resolve("Trafiquant 2").ids == (T2,) and not m.resolve("Trafiquant 2").ambiguous
    assert m.match("trafiquant1") == T1 and m.match("trafiquant2") == T2


def test_an_alias_makes_the_choice_deterministic() -> None:
    m = _ecoloman_cards(trafiquant2=["trafiquant"])
    for written in ("trafiquant", "le trafiquant", "TRAFIQUANT"):
        r = m.resolve(written)
        assert r.ids == (T2,) and not r.ambiguous and r.candidates == (), written
    # L'alias ne force pas un pluriel : « les trafiquants » désigne toujours les deux.
    assert m.resolve("les trafiquants").ids == (T1, T2)


def test_plural_designates_every_card() -> None:
    m = _ecoloman_cards()
    for written in ("les trafiquants", "trafiquants", "les trafiquant", "des trafiquants"):
        r = m.resolve(written)
        assert r.ids == (T1, T2) and r.how == PLURAL and not r.ambiguous, written
    assert m.ids(["les trafiquants", "seku"]) == [T1, T2, SEKU]


def test_context_of_the_panel_settles_a_tie() -> None:
    m = _ecoloman_cards()
    # Un trafiquant déjà nommé dans la case (ou la précédente) : c'est lui.
    r = m.resolve("trafiquant", [{T2}])
    assert r.ids == (T2,) and r.how == CONTEXT and not r.ambiguous
    assert m.ids(["Trafiquant 2", "le trafiquant"]) == [T2]
    # Le contexte le plus fort l'emporte ; un contexte qui ne départage pas laisse l'arbitrage.
    assert m.resolve("trafiquant", [{T1}, {T2}]).ids == (T1,)
    assert m.resolve("trafiquant", [{T1, T2}, {T2}]).ids == (T2,)
    assert m.resolve("trafiquant", [{SEKU}]).ambiguous


def test_stem_designates_angus_without_false_positive_on_short_names() -> None:
    m = _ecoloman_cards()
    assert m.match("angu") == m.match("Angu") == m.match("ANGUS") == ANGUS
    assert m.match("sek") is None and m.match("ang") is None  # radical trop court
    short = CharacterMatcher(
        [Character(id=1, name="Lu", aliases=[]), Character(id=2, name="Leo", aliases=[]), Character(id=3, name="Max")]
    )
    for written in ("Lus", "L", "Leon", "Léonie", "Maxi", "Maxime", "Lucas", "un passant"):
        assert short.match(written) is None, written
    assert short.match("lu") == 1 and short.match("LÉO") == 2
    # Un mot plus long qui commence pareil n'est pas le même nom (« trafic » n'est pas un trafiquant).
    assert m.match("trafic") is None and m.read_names("Le trafic de déchets toxiques.") == []


def test_names_are_read_in_free_text() -> None:
    m = _ecoloman_cards()
    assert m.read_names("Le trafiquant blêmit et recule, lâchant Seku.") == ["trafiquant", "Seku"]
    assert m.read_names("seku et angu voit au loin les trafiquant jeter des barils") == [
        "seku",
        "angu",
        "les trafiquant",
    ]
    assert m.read_names("Trafiquant 2, voyant son comparse au sol, panique.") == ["Trafiquant 2"]
    assert m.read_names("Le sol tremble, le volcan gronde.") == []


def _panel(
    description: str,
    present: list[str],
    *,
    staging: str = "",
    offscreen: list[str] | None = None,
    speakers: tuple[str, ...] = (),
) -> Panel:
    panel = Panel(
        index=0,
        description=description,
        staging=staging,
        character_names=present,
        offscreen_names=offscreen or [],
        character_ids=[],
    )
    panel.bubbles = [Bubble(order=i, speaker_name=s, text="…", kind=BubbleKind.speech) for i, s in enumerate(speakers)]
    return panel


def test_case_11_names_are_flagged_to_the_author() -> None:
    m = _ecoloman_cards()
    # La case 11 telle qu'en base : personne de déclaré, le trafiquant parle et la mise en scène le cadre.
    panel = _panel(
        "Le trafiquant blêmit et recule, lâchant Seku.",
        [],
        staging="Trafiquant en gros plan, sueur, yeux écarquillés.",
        speakers=("trafiquant",),
    )
    notes = name_notes(m, panel, None)
    assert [(n.name, n.source, n.kind, n.chosen, n.candidates) for n in notes] == [
        ("trafiquant", "bulle", AMBIGUOUS, (T1,), (T1, T2)),
        ("trafiquant", "description", UNDECLARED, (T1,), (T1, T2)),
        ("Seku", "description", UNDECLARED, (SEKU,), ()),
    ]
    # Déclarée par le scénariste : le trafiquant reste signalé (ambigu), Seku n'est plus en défaut.
    panel = _panel("Le trafiquant blêmit et recule, lâchant Seku.", ["trafiquant", "Seku"], speakers=("trafiquant",))
    notes = name_notes(m, panel, None)
    assert [(n.name, n.source, n.kind) for n in notes] == [("trafiquant", "image", AMBIGUOUS)]
    # Avec l'alias, plus rien à signaler.
    assert name_notes(_ecoloman_cards(trafiquant1=["trafiquant"]), panel, None) == []
    # Hors cadre sans fiche et locuteur sans fiche : signalés ; le narrateur ne l'est jamais.
    panel = _panel("Au loin.", [], offscreen=["le capitaine"], speakers=("narrateur", "serveur"))
    assert [(n.name, n.source, n.kind) for n in name_notes(m, panel, None)] == [
        ("le capitaine", "hors cadre", UNMATCHED),
        ("serveur", "bulle", UNMATCHED),
    ]


# --- de bout en bout : la case 11 (LLM et ComfyUI factices) -------------------------------------------
CH1 = [
    {
        "description": "Angus arrive et se dresse derrière Seku, imposant.",
        "characters": ["angus", "seku"],
        "shot_type": "plan moyen",
        "dialogues": [{"speaker": "angus", "text": "Un problème ?"}],
    },
    {
        "description": "Le trafiquant blêmit et recule, lâchant Seku.",
        "characters": ["trafiquant", "Seku"],
        "shot_type": "gros plan",
        "dialogues": [{"speaker": "trafiquant", "text": "Rien... rien du tout ! Pardon !"}],
    },
]


def test_case_11_declares_the_dealer_and_seku_and_sends_their_references(client: TestClient) -> None:
    d = _ecoloman(client)
    cards: dict[str, Any] = d["cards"]
    _, panel = _save(client, d["chapter"]["id"], _script(CH1))
    assert panel["characters"] == ["trafiquant", "Seku"] and panel["unmatched_characters"] == []
    # Le nom générique n'est pas perdu : la première fiche, et un avertissement pour l'auteur.
    [note] = panel["name_notes"]
    assert (note["name"], note["kind"], note["source"]) == ("trafiquant", "ambigu", "image")
    assert [c["name"] for c in note["chosen"]] == ["Trafiquant 1"]
    assert [c["name"] for c in note["candidates"]] == ["Trafiquant 1", "Trafiquant 2"]
    assert "plusieurs fiches" in note["message"]
    detail = _ok(client.get(f"/panels/{panel['id']}"))
    assert detail["character_ids"] == [cards["Trafiquant 1"]["id"], cards["Seku"]["id"]]
    assert detail["name_notes"] == panel["name_notes"]

    # Le workflow ComfyUI porte les deux références d'identité.
    image = _generate(client, panel["id"])
    assert sorted(_sent_references(client, image)) == ["Seku", "Trafiquant 1"]
    refs = [r["name"] for r in image["params"]["reference_images"] if r["kind"] == "character"]
    assert sorted(refs) == ["Seku", "Trafiquant 1"]

    # L'auteur tranche en un clic : « trafiquant » devient un alias de Trafiquant 2, la case le suit.
    link = _ok(
        client.post(
            f"/chapters/{d['chapter']['id']}/character-links",
            json={"name": "trafiquant", "character_id": cards["Trafiquant 2"]["id"]},
        )
    )
    assert link["alias_added"] is True
    detail = _ok(client.get(f"/panels/{panel['id']}"))
    assert detail["character_ids"] == [cards["Trafiquant 2"]["id"], cards["Seku"]["id"]]
    assert detail["name_notes"] == []
    image = _generate(client, panel["id"])
    assert sorted(_sent_references(client, image)) == ["Seku", "Trafiquant 2"]


# Chapitre 1 tel qu'en base (cases 8 à 18) : aucun trafiquant déclaré, il parle sous le nom « trafiquant ».
CH1_DB = [
    (
        "Seku se lève pour se dégourdir les jambes et heurte un homme à la mine patibulaire.",
        "Seku de profil, bousculant un trafiquant.",
        ["seku"],
        ["seku", "trafiquant"],
    ),
    (
        "Le trafiquant attrape Seku par le col, l'air menaçant.",
        "Trafiquant à droite, tenant Seku par le col.",
        ["seku"],
        ["trafiquant", "seku"],
    ),
    (
        "Angus arrive et se dresse derrière Seku, imposant.",
        "Angus au premier plan, le trafiquant en face.",
        ["angus", "seku"],
        ["angus"],
    ),
    (
        "Le trafiquant blêmit et recule, lâchant Seku.",
        "Trafiquant en gros plan, sueur, yeux écarquillés.",
        [],
        ["trafiquant"],
    ),
    (
        "Le trafiquant s'enfuit en courant. Angus et Seku le regardent partir.",
        "Angus et Seku au premier plan, de dos, regardant le trafiquant courir.",
        ["angus", "seku"],
        ["seku", "angus"],
    ),
    (
        "Un bruit derrière eux. Le trafiquant réapparaît avec deux complices.",
        "Trafiquant et complices à gauche, Angus et Seku à droite, surpris.",
        ["angus", "seku"],
        ["trafiquant"],
    ),
    (
        "Le trafiquant sort une arme, mais Angus ne recule pas.",
        "Trafiquant braque son arme, Angus impassible.",
        ["angus"],
        ["trafiquant"],
    ),
    (
        "Angus profite de la diversion pour charger et mettre en fuite les trafiquants.",
        "Angus chargeant, trafiquants fuyant.",
        ["angus"],
        ["angus"],
    ),
]
DEALER_PANELS = (1, 3, 4, 5, 6, 7)  # ids 9, 11, 12, 14, 16, 18 de la base


def test_relink_on_an_existing_base_finds_or_flags_every_dealer_panel(client: TestClient) -> None:
    d = _ecoloman(client)
    cards = d["cards"]
    # Base d'avant : les fiches des trafiquants n'ont pas l'alias générique ; le scénario n'en déclare aucun.
    raw = _script(
        [
            {
                "description": desc,
                "staging": staging,
                "characters": cast,
                "shot_type": "plan moyen",
                "dialogues": [{"speaker": who, "text": "…"} for who in speakers],
            }
            for desc, staging, cast, speakers in CH1_DB
        ]
    )
    panels = _save(client, d["chapter"]["id"], raw)
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        project_id = d["series"]["id"]
        relink_project(session, project_id)
        session.commit()
        speakers = {
            b.speaker_name: b.speaker_id
            for b in session.scalars(select(Bubble).where(Bubble.panel_id == panels[3]["id"]))
        }
    assert speakers == {"trafiquant": cards["Trafiquant 1"]["id"]}  # le locuteur a une fiche (arbitrée)

    panels = [p for page in _ok(client.get(f"/chapters/{d['chapter']['id']}/pages")) for p in page["panels"]]
    for i in DEALER_PANELS:
        notes = panels[i]["name_notes"]
        dealer = [n for n in notes if "trafiquant" in n["name"].lower()]
        assert dealer, (i, notes)
        assert all(n["chosen"] for n in dealer)  # une fiche choisie, montrée à l'auteur
    # « les trafiquants » (case 18) désigne les deux, sans ambiguïté.
    [plural] = [n for n in panels[7]["name_notes"] if "trafiquants" in n["name"]]  # une alerte pour les deux
    assert plural["kind"] == "non déclaré"
    assert [c["name"] for c in plural["chosen"]] == ["Trafiquant 1", "Trafiquant 2"]

    # Un alias générique sur une fiche : relink la retient partout, plus aucune ambiguïté.
    _ok(client.patch(f"/characters/{cards['Trafiquant 1']['id']}", json={"aliases": ["trafiquant"]}))
    panels = [p for page in _ok(client.get(f"/chapters/{d['chapter']['id']}/pages")) for p in page["panels"]]
    assert not [n for p in panels for n in p["name_notes"] if n["kind"] == "ambigu"]
    with client.app.state.ctx.db.session_scope() as session:  # type: ignore[attr-defined]
        b = session.scalars(select(Bubble).where(Bubble.panel_id == panels[3]["id"])).one()
        assert b.speaker_id == cards["Trafiquant 1"]["id"]
    # L'auteur met le trafiquant à l'image de la case 11 : il reçoit la fiche (et sa référence).
    detail = _ok(client.patch(f"/panels/{panels[3]['id']}", json={"characters": ["trafiquant", "Seku"]}))
    assert detail["character_ids"] == [cards["Trafiquant 1"]["id"], cards["Seku"]["id"]]
    assert detail["name_notes"] == []
