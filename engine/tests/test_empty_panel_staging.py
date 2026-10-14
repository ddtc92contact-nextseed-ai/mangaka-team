"""Case sans personnage à l'image : sa mise en scène (souvent écrite pour des personnages devenus absents)
n'est envoyée ni au prompt image, ni au rédacteur de prompt, ni à la direction artistique (#167)."""

from __future__ import annotations

from mangaka_engine.pipeline.art_direction import _panel_brief
from mangaka_engine.pipeline.generation import panel_staging
from mangaka_engine.store.models import Panel

STAGING = "Seku et Angus agenouillés autour de lui"


def test_staging_is_used_only_with_characters_in_frame() -> None:
    with_cast = Panel(index=0, description="Ils soignent le blessé", staging=STAGING, character_names=["Seku"])
    assert panel_staging(with_cast) == STAGING
    assert _panel_brief(with_cast)["staging"] == STAGING
    empty = Panel(
        index=1, description="Le sol fume.", staging=STAGING, character_names=[], offscreen_names=["Seku", "Angus"]
    )
    assert panel_staging(empty) == ""
    assert _panel_brief(empty)["staging"] == ""
    assert empty.staging == STAGING  # le texte de l'auteur reste, l'écran le signale comme non utilisé
