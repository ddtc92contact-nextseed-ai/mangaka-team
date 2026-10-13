"""Qui est dans l'image (pipeline/framing.py) : sorties de l'API."""

from __future__ import annotations

from ..pipeline.framing import viewpoint_of
from ..store.models import Panel
from .schemas import ViewpointOut


def viewpoint_out(panel: Panel) -> ViewpointOut | None:
    """Point de vue d'un spectateur de la case (plan de réaction ou vue subjective), None sinon."""
    vp = viewpoint_of(panel)
    if vp is None:
        return None
    return ViewpointOut(
        mode=vp["mode"], spectators=list(vp.get("spectators") or []), source=str(vp.get("source") or "direction")
    )
