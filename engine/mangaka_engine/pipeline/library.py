"""Bibliothèque d'une série : objets et décors récurrents (à côté des personnages).

- `SeriesLibrary` : ce que les agents LLM (scénariste, directeur artistique) reçoivent — ids, noms et
  descriptions courtes — et la vérification des ids qu'ils citent (`check_refs`) : un id inconnu
  rend la réponse invalide, donc relancée comme une erreur de schéma ;
- `panel_assets` : décor et objets d'une case, relus en base (ids d'une autre série ou supprimés
  ignorés) ;
- `active_style` : référence de style active de la série (planche de style), avec son image.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..presets import PresetRegistry
from ..store.models import AssetKind, Panel, SeriesAsset

SHORT_DESCRIPTION = 160  # caractères de description envoyés aux agents


def short_description(text: str | None, limit: int = SHORT_DESCRIPTION) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;.") + "…"


@dataclass
class SeriesLibrary:
    """Objets et décors d'une série, tels que présentés aux agents : [{"id", "name", "description"}]."""

    decors: list[dict[str, Any]] = field(default_factory=list)
    objets: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, session: Session, project_id: int) -> SeriesLibrary:
        rows = session.scalars(
            select(SeriesAsset).where(SeriesAsset.project_id == project_id).order_by(SeriesAsset.name, SeriesAsset.id)
        ).all()

        def entry(a: SeriesAsset) -> dict[str, Any]:
            return {"id": a.id, "name": a.name, "description": short_description(a.visual_description)}

        return cls(
            decors=[entry(a) for a in rows if a.kind == AssetKind.decor],
            objets=[entry(a) for a in rows if a.kind == AssetKind.object],
        )

    def as_json(self) -> dict[str, Any]:
        return {"decors": self.decors, "objets": self.objets}

    def text(self, kind: str) -> str:
        """« - id 3 · Le labo : description » pour un prompt ; vide sans élément."""
        items = self.decors if kind == "decors" else self.objets
        return "\n".join(f"- id {e['id']} · {e['name']} : {e['description'] or '(sans description)'}" for e in items)

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


def panel_assets(session: Session, panel: Panel, project_id: int) -> tuple[SeriesAsset | None, list[SeriesAsset]]:
    """(décor, objets) d'une case, avec leurs images de référence, dans l'ordre de la case."""
    object_ids = [i for i in panel.object_ids or [] if isinstance(i, int)]
    ids = [*([panel.decor_id] if panel.decor_id is not None else []), *object_ids]
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
    decor = found.get(panel.decor_id) if panel.decor_id is not None else None
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


def style_for(session: Session, presets: PresetRegistry, project_id: int, use: str) -> SeriesAsset | None:
    """Référence de style à joindre, selon `style_board` de defaults.yaml (`use` : `reference_sheets`
    ou `panels`) : None sans planche de style, sans réglage, ou si le réglage dit « jamais »."""
    settings = presets.defaults.style_board if presets.defaults else None
    if settings is None or getattr(settings, use) == "never":
        return None
    return active_style(session, project_id)
