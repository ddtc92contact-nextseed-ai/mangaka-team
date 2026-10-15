"""Name : planche brouillon (croquis + bulles) relue, corrigée puis validée page par page avant le propre.

Chez les mangakas, la name est un brouillon dessiné que l'éditeur relit avant tout dessin final. Ici, c'est la
page en croquis (`pipeline/sketch.py`) avec son lettrage (bulles, onomatopées) :

1. **Valider la name** d'une page (`validate_page_name`) : chaque case a un croquis (ou déjà une version
   propre) ; une case dont aucun croquis n'est retenu retient son dernier croquis (`Panel.sketch_image_id`),
   qui reste la source de composition du passage au propre.
2. La validation garde une **empreinte** des cases (`page_key` : ids et ordre, description, plan, croquis
   retenu). Une case modifiée après validation (description, plan, découpe, nouveau croquis) rend la
   validation caduque (`name_state` → « stale ») : la page n'est plus validée, rien n'est effacé.
3. **Couper une case en deux** (`split_panel`) : une nouvelle case est insérée juste après, avec ce que la
   case coupée avait (personnages, lieu, plan…) et les répliques désignées ; la page est remise en page. Seules
   les deux cases touchées perdent leur croquis retenu (l'appelant les re-croque) ; les versions et croquis des
   autres cases ne changent pas.

L'étape `name` de la garde d'étapes (`pipeline/stage_gate.py`) lit `is_validated` : exigée avant le passage au
propre et la génération d'un chapitre quand la série a le palier croquis activé (sinon rien à vérifier).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from typing import Literal

from sqlalchemy.orm import Session

from ..presets import PresetRegistry
from ..store.models import Bubble, ImageKind, Page, PageNameValidation, Panel, utcnow
from .pages import layout_page
from .sketch import has_final, latest_sketch, validate_sketch, validated_sketch

NameState = Literal["validated", "stale", "pending"]


class NameBoardError(ValueError):
    """Action refusée sur la name (message lisible, en français)."""


def _plan(panel: Panel) -> str:
    return str((panel.dialog_direction or {}).get("plan") or panel.shot_type or "").strip()


def page_key(page: Page) -> str:
    """Empreinte de la name d'une page : cases (ids, ordre), description, plan et croquis retenu."""
    rows = [
        [pa.id, pa.index, (pa.description or "").strip(), _plan(pa), pa.sketch_image_id]
        for pa in sorted(page.panels, key=lambda p: p.index)
    ]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def name_state(page: Page) -> NameState:
    validation = page.name_validation
    if validation is None:
        return "pending"
    return "validated" if validation.key == page_key(page) else "stale"


def is_validated(page: Page) -> bool:
    return name_state(page) == "validated"


def _label(panels: Sequence[Panel]) -> str:
    nums = ", ".join(str(p.index + 1) for p in panels)
    return f"case {nums}" if len(panels) == 1 else f"cases {nums}"


def validate_page_name(session: Session, page: Page, *, author: str = "") -> PageNameValidation:
    """« Valider la name » : chaque case a un croquis (ou une version propre) ; les cases sans croquis retenu
    retiennent leur dernier croquis. Remplace une validation précédente (caduque ou non)."""
    if not page.chapter.project.sketch_enabled:
        raise NameBoardError("palier croquis désactivé pour cette série : pas de name à valider")
    if not page.panels:
        raise NameBoardError(f"page {page.number} sans case : rien à valider")
    missing = [p for p in page.panels if validated_sketch(p) is None and latest_sketch(p) is None and not has_final(p)]
    if missing:
        raise NameBoardError(
            f"page {page.number}, {_label(missing)} pas encore croquée{'s' if len(missing) > 1 else ''} : "
            "croque-la d'abord, puis valide la name"
        )
    for panel in page.panels:
        if validated_sketch(panel) is None and latest_sketch(panel) is not None and not has_final(panel):
            validate_sketch(panel)
    session.flush()
    validation = page.name_validation
    if validation is None:
        validation = PageNameValidation(page_id=page.id, key="")
        page.name_validation = validation
    validation.key = page_key(page)
    validation.author = (author or "").strip()[:120]
    validation.created_at = utcnow()
    session.flush()
    return validation


def unvalidate_page_name(session: Session, page: Page) -> None:
    if page.name_validation is not None:
        session.delete(page.name_validation)
        page.name_validation = None
        session.flush()


def chapter_counts(pages: Iterable[Page]) -> tuple[int, int]:
    """(pages validées, pages à valider) : pages qui ont des cases."""
    counted = [p for p in pages if p.panels]
    return sum(1 for p in counted if is_validated(p)), len(counted)


# --- couper une case en deux ------------------------------------------------------------------
def _copy_fields(source: Panel) -> dict[str, object]:
    return {
        "description": source.description,
        "character_ids": list(source.character_ids or []),
        "character_names": list(source.character_names or []),
        "offscreen_names": list(source.offscreen_names or []),
        "viewpoint": dict(source.viewpoint) if source.viewpoint else None,
        "decor_id": source.decor_id,
        "object_ids": list(source.object_ids or []),
        "location_id": source.location_id,
        "shot_type": source.shot_type,
        "setting": source.setting,
        "staging": source.staging,
        "importance": source.importance,
        "intensity": source.intensity,
        "generation_preset": source.generation_preset,
        "dialog_direction": dict(source.dialog_direction) if source.dialog_direction else None,
    }


def _reset_composition(panel: Panel) -> None:
    """La case a changé de forme : plus de croquis retenu, de version choisie, de cadrage ni de verrou ; ses
    bulles reviennent au placement automatique. Les versions restent (tout est versionné)."""
    panel.sketch_image_id = None
    panel.crop = None
    panel.composition_lock = None
    for img in panel.images:
        if img.selected and img.kind == ImageKind.final:
            img.selected = False
    for b in panel.bubbles:
        b.position = None
        b.tail = None


def split_panel(
    session: Session,
    presets: PresetRegistry,
    panel: Panel,
    *,
    first: str | None = None,
    second: str | None = None,
    move_bubble_ids: Iterable[int] = (),
) -> Panel:
    """Coupe la case en deux : la nouvelle case suit juste après (description `second`, sinon celle de la case),
    les répliques `move_bubble_ids` y passent, la page est remise en page. Renvoie la nouvelle case."""
    page = panel.page
    moving = set(move_bubble_ids)
    unknown = moving - {b.id for b in panel.bubbles}
    if unknown:
        raise NameBoardError("réplique inconnue pour cette case : seules ses propres répliques changent de case")
    after = sorted((p for p in page.panels if p.index > panel.index), key=lambda p: p.index)
    # Index uniques par page : on décale d'abord hors de portée, puis à leur place.
    for p in after:
        p.index = -(p.index + 1000)
    session.flush()
    for p in after:
        p.index = -p.index - 1000 + 1
    fields = _copy_fields(panel)
    if second is not None and second.strip():
        fields["description"] = second.strip()
    new = Panel(page_id=page.id, index=panel.index + 1, **fields)  # type: ignore[arg-type]
    session.add(new)
    if first is not None and first.strip():
        panel.description = first.strip()
    session.flush()
    kept = [b for b in panel.bubbles if b.id not in moving]
    moved: list[Bubble] = [b for b in panel.bubbles if b.id in moving]
    for i, b in enumerate(sorted(kept, key=lambda b: b.order)):
        b.order = i
    for i, b in enumerate(sorted(moved, key=lambda b: b.order)):
        b.panel_id = new.id
        b.order = i
    session.flush()
    session.expire(page, ["panels"])
    session.expire(panel, ["bubbles"])
    session.refresh(new)
    _reset_composition(panel)
    _reset_composition(new)
    # Gabarit imposé pour l'ancien nombre de cases : la page repasse au choix automatique.
    if page.grid_template:
        tpl = presets.layout_templates.get(page.grid_template)
        if tpl is None or tpl.panel_count != len(page.panels):
            page.grid_template = None
    layout_page(presets, page)
    session.flush()
    return new
