"""Étape 2 appliquée aux pages en base : calcul, stockage et recalcul de `Page.layout`."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ..presets import PresetRegistry
from ..store.models import Page, PageState
from .layout import LayoutError, PanelSpec, choose_template, compute_layout, move_gutter


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
