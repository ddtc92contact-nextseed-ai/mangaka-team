"""Étape 2 appliquée aux pages en base : calcul, stockage et recalcul de `Page.layout`."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ..presets import PresetError, PresetRegistry
from ..presets.schemas import count_panels
from ..store.models import Page, PageState, Project, ReadingDirection
from .layout import (
    LayoutError,
    PanelSpec,
    choose_template,
    compute_layout,
    move_gutter,
    tree_from_json,
)


def panel_specs(page: Page) -> list[PanelSpec]:
    return [
        PanelSpec(
            importance=p.importance,
            dialogue_chars=sum(len(b.text) for b in p.bubbles),
            panel_id=p.id,
        )
        for p in page.panels
    ]


def layout_signature(page: Page) -> str:
    """Ce dont dépend la mise en page : si cela change, elle est obsolète."""
    specs = [[s.panel_id, s.importance, s.dialogue_chars] for s in panel_specs(page)]
    fmt = page.chapter.project.page_format
    direction = page.chapter.project.reading_direction.value
    return json.dumps([page.number, fmt, direction, page.grid_template, specs], separators=(",", ":"))


def is_stale(page: Page) -> bool:
    return page.layout is None or page.layout.get("signature") != layout_signature(page)


def _store(page: Page, layout: dict[str, Any]) -> dict[str, Any]:
    layout = {**layout, "signature": layout_signature(page)}
    page.layout = layout
    for panel, lp in zip(page.panels, layout["panels"], strict=True):
        panel.bbox = {k: lp[k] for k in ("x1", "y1", "x2", "y2")}
        panel.bubble_zone = lp["bubble_zone"]
    if page.state == PageState.draft:
        page.state = PageState.layout
    return layout


def layout_page(presets: PresetRegistry, page: Page) -> dict[str, Any] | None:
    """(Re)calcule la mise en page depuis le gabarit imposé ou choisi automatiquement."""
    series = page.chapter.project
    fmt = presets.page_format(series.page_format)
    specs = panel_specs(page)
    if not specs:
        page.layout = None
        return None
    template_id = page.grid_template
    tree = None
    if template_id:
        tpl = presets.layout_template(template_id)
        if tpl.panel_count != len(specs):
            raise LayoutError(
                f"le gabarit « {tpl.name} » a {tpl.panel_count} case(s), la page {page.number} en a {len(specs)}"
            )
        tree = tpl.tree
    else:
        template_id, tree = choose_template(list(presets.layout_templates.values()), [s.importance for s in specs])
    layout = compute_layout(
        fmt,
        presets.layout,
        tree,
        specs,
        direction=series.reading_direction.value,
        page_number=page.number,
        template_id=template_id,
    )
    return _store(page, layout)


def layout_pages(presets: PresetRegistry, pages: Sequence[Page]) -> None:
    for page in pages:
        layout_page(presets, page)


def move_page_gutter(
    presets: PresetRegistry, page: Page, *, path: Sequence[int], index: int, position: float
) -> dict[str, Any]:
    if page.layout is None or is_stale(page):
        raise LayoutError(
            "la mise en page n'est plus à jour : clique sur « Recalculer » avant de déplacer une gouttière"
        )
    fmt = presets.page_format(page.chapter.project.page_format)
    layout = move_gutter(fmt, presets.layout, page.layout, panel_specs(page), path=path, index=index, position=position)
    return _store(page, layout)


def _mirror_x(x: float, w: float, old: dict[str, Any], new: dict[str, Any]) -> float:
    """Abscisse d'un cadre de largeur `w` dans la case `old`, mise en miroir dans la case `new`."""
    fx = (new["x2"] - new["x1"]) / max(old["x2"] - old["x1"], 1)
    return new["x1"] + (old["x2"] - (x + w)) * fx


def _mirror_lettering(page: Page, old_boxes: dict[int, dict[str, Any] | None]) -> None:
    """Bulles et queues placées à la main : même place relative dans la case, côté opposé."""
    for panel in page.panels:
        old, new = old_boxes.get(panel.id), panel.bbox
        if not old or not new:
            continue
        fy = (new["y2"] - new["y1"]) / max(old["y2"] - old["y1"], 1)
        for b in panel.bubbles:
            pos = b.position
            if pos and pos.get("manual") and {"x", "y", "w"} <= pos.keys():
                x = _mirror_x(float(pos["x"]), float(pos["w"]), old, new)
                b.position = {**pos, "x": round(x), "y": round(new["y1"] + (float(pos["y"]) - old["y1"]) * fy)}
            tail = b.tail
            if tail and tail.get("manual") and {"x", "y"} <= tail.keys():
                x = _mirror_x(float(tail["x"]), 0, old, new)
                b.tail = {**tail, "x": round(x), "y": round(new["y1"] + (float(tail["y"]) - old["y1"]) * fy)}


def change_reading_direction(presets: PresetRegistry, project: Project, direction: ReadingDirection) -> int:
    """Change le sens de lecture d'une série et remet ses pages déjà mises en page dans le bon sens.

    Une page à jour est mise en miroir : même gabarit, mêmes gouttières (y compris déplacées à la main),
    ordre de lecture inversé, bulles placées à la main reportées du côté opposé de leur case. Une page
    déjà obsolète est recalculée depuis son gabarit. Les images générées ne sont pas touchées.
    Renvoie le nombre de pages recalculées ; une page impossible à recalculer reste « obsolète ».
    """
    if project.reading_direction == direction:
        return 0
    pages = [p for ch in project.chapters for p in ch.pages if p.layout is not None and p.panels]
    fresh = {p.id for p in pages if not is_stale(p)}
    old_boxes = {p.id: {panel.id: panel.bbox for panel in p.panels} for p in pages}
    project.reading_direction = direction
    done = 0
    for page in pages:
        try:
            layout = page.layout or {}
            if page.id in fresh and layout.get("tree") is not None:
                tree = tree_from_json(layout["tree"])
                specs = panel_specs(page)
                if count_panels(tree) != len(specs):
                    raise LayoutError("gabarit incohérent")
                fmt = presets.page_format(project.page_format)
                _store(
                    page,
                    compute_layout(
                        fmt,
                        presets.layout,
                        tree,
                        specs,
                        direction=direction.value,
                        page_number=page.number,
                        template_id=layout["template_id"],
                    ),
                )
                _mirror_lettering(page, old_boxes[page.id])
            else:
                layout_page(presets, page)
            done += 1
        except (LayoutError, PresetError, KeyError, ValueError):
            continue
    return done
