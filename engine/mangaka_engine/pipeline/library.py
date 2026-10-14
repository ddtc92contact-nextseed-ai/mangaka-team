"""Bibliothèque d'une série : objets et décors récurrents (à côté des personnages).

- `SeriesLibrary` : ce que les agents LLM (scénariste, directeur artistique) reçoivent — ids, noms et
  descriptions courtes des décors, objets et lieux de la série — et la vérification des ids qu'ils citent
  (`check_refs`, `check_location`) : un id inconnu rend la réponse invalide, donc relancée comme une erreur de
  schéma ;
- `panel_assets` : décor et objets d'une case, relus en base (ids d'une autre série ou supprimés
  ignorés) ; sans décor propre, le décor du lieu de la case (`SeriesLocation.decor_id`, pipeline/locations.py) ;
- `active_style` : référence de style active de la série (planche de style), avec son image.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..presets import PresetRegistry
from ..store.models import AssetKind, Panel, SeriesAsset, SeriesLocation

SHORT_DESCRIPTION = 160  # caractères de description envoyés aux agents


def short_description(text: str | None, limit: int = SHORT_DESCRIPTION) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;.") + "…"


@dataclass
class SeriesLibrary:
    """Objets, décors et lieux d'une série, tels que présentés aux agents : [{"id", "name", "description"}] (et
    "decor", id du décor d'un lieu)."""

    decors: list[dict[str, Any]] = field(default_factory=list)
    objets: list[dict[str, Any]] = field(default_factory=list)
    lieux: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, session: Session, project_id: int) -> SeriesLibrary:
        rows = session.scalars(
            select(SeriesAsset).where(SeriesAsset.project_id == project_id).order_by(SeriesAsset.name, SeriesAsset.id)
        ).all()

        def entry(a: SeriesAsset) -> dict[str, Any]:
            return {"id": a.id, "name": a.name, "description": short_description(a.visual_description)}

        places = session.scalars(
            select(SeriesLocation)
            .where(SeriesLocation.project_id == project_id)
            .order_by(SeriesLocation.name, SeriesLocation.id)
        ).all()
        return cls(
            decors=[entry(a) for a in rows if a.kind == AssetKind.decor],
            objets=[entry(a) for a in rows if a.kind == AssetKind.object],
            lieux=[
                {
                    "id": loc.id,
                    "name": loc.name,
                    "description": short_description(loc.description),
                    "decor": loc.decor_id,
                }
                for loc in places
            ],
        )

    def as_json(self) -> dict[str, Any]:
        return {"decors": self.decors, "objets": self.objets, "lieux": self.lieux}

    def text(self, kind: str) -> str:
        """« - id 3 · Le labo : description » pour un prompt (un lieu : « (décor id 7) » en plus) ; vide sans
        élément."""
        items = {"decors": self.decors, "lieux": self.lieux}.get(kind, self.objets)
        names = {e["id"]: e["name"] for e in self.decors}
        return "\n".join(
            f"- id {e['id']} · {e['name']} : {e['description'] or '(sans description)'}"
            + (f" (décor : {names[e['decor']]}, id {e['decor']})" if e.get("decor") in names else "")
            for e in items
        )

    def location_name(self, location_id: int | None) -> str | None:
        return next((e["name"] for e in self.lieux if e["id"] == location_id), None)

    def check_location(self, lieu: int | str | None) -> list[str]:
        """Problème (lisible, renvoyé au LLM) d'un lieu cité par son id ; un nom (nouveau lieu) est toujours permis."""
        if not isinstance(lieu, int) or any(e["id"] == lieu for e in self.lieux):
            return []
        choices = ", ".join(str(e["id"]) for e in self.lieux)
        hint = (
            f"ids possibles : {choices}, ou le nom d'un nouveau lieu" if choices else "donne le nom d'un nouveau lieu"
        )
        return [f"lieu : id {lieu} inconnu ({hint})"]

    def check_refs(self, decor: int | None, objets: Sequence[int]) -> list[str]:
        """Problèmes (lisibles, renvoyés au LLM) d'une case qui cite des ids de la bibliothèque."""
        problems: list[str] = []
        decor_ids = {e["id"] for e in self.decors}
        object_ids = {e["id"] for e in self.objets}
        if decor is not None and decor not in decor_ids:
            choices = ", ".join(str(i) for i in sorted(decor_ids))
            hint = f"ids possibles : {choices}, ou null" if choices else "la série n'a aucun décor : mets null"
            problems.append(f"decor : id {decor} inconnu ({hint})")
        unknown = [i for i in objets if i not in object_ids]
        if unknown:
            choices = ", ".join(str(i) for i in sorted(object_ids))
            hint = f"ids possibles : {choices}" if choices else "la série n'a aucun objet : liste vide"
            problems.append(f"objets : id(s) {', '.join(map(str, unknown))} inconnu(s) ({hint})")
        return problems


def panel_decor_id(panel: Panel, project_id: int) -> int | None:
    """Décor de la case : le sien, sinon celui de son lieu (référence de lieu) ; None sans l'un ni l'autre."""
    if panel.decor_id is not None:
        return panel.decor_id
    location = panel.location if panel.location_id is not None else None
    if location is not None and location.project_id == project_id:
        return location.decor_id
    return None


def panel_assets(session: Session, panel: Panel, project_id: int) -> tuple[SeriesAsset | None, list[SeriesAsset]]:
    """(décor, objets) d'une case, avec leurs images de référence, dans l'ordre de la case. Le décor est celui de
    la case, sinon celui de son lieu."""
    object_ids = [i for i in panel.object_ids or [] if isinstance(i, int)]
    decor_id = panel_decor_id(panel, project_id)
    ids = [*([decor_id] if decor_id is not None else []), *object_ids]
    if not ids:
        return None, []
    found = {
        a.id: a
        for a in session.scalars(
            select(SeriesAsset)
            .where(SeriesAsset.id.in_(ids), SeriesAsset.project_id == project_id)
            .options(selectinload(SeriesAsset.reference_images))
        )
    }
    decor = found.get(decor_id) if decor_id is not None else None
    if decor is not None and decor.kind != AssetKind.decor:
        decor = None
    objects = [found[i] for i in dict.fromkeys(object_ids) if i in found and found[i].kind == AssetKind.object]
    return decor, objects


def active_style(session: Session, project_id: int) -> SeriesAsset | None:
    """Référence de style active de la série (planche de style) qui a une image, sinon None."""
    asset = session.scalars(
        select(SeriesAsset)
        .where(SeriesAsset.project_id == project_id, SeriesAsset.kind == AssetKind.style, SeriesAsset.active)
        .options(selectinload(SeriesAsset.reference_images))
        .order_by(SeriesAsset.id.desc())
    ).first()
    return asset if asset is not None and asset.reference_images else None


def style_for(
    session: Session, presets: PresetRegistry, project_id: int, use: str, kind: str | None = None
) -> SeriesAsset | None:
    """Référence de style à joindre, selon `style_board` de defaults.yaml (`use` : `reference_sheets`
    — réglage de la sorte `kind` — ou `panels`) : None sans planche de style, sans réglage, ou si le
    réglage dit « jamais »."""
    settings = presets.defaults.style_board if presets.defaults else None
    if settings is None:
        return None
    mode = settings.sheets_mode(kind or "character") if use == "reference_sheets" else getattr(settings, use)
    if mode == "never":
        return None
    return active_style(session, project_id)
