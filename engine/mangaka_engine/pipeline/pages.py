"""Étape 2 appliquée aux pages en base : calcul, stockage et recalcul de `Page.layout`.

La mise en page d'une page dépend de sa graine (`Page.layout_seed`, tirée une fois puis stockée :
même graine = même page), du style de la série (ou celui imposé à la page), du gabarit imposé
éventuel, du rythme de la page et de l'importance / intensité de ses cases. « Nouvelle mise en
page » tire une autre graine et écarte le gabarit actuel.
"""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Sequence
from typing import Any

from ..presets import PresetError, PresetRegistry
from ..presets.schemas import count_panels
from ..store.models import Page, PageState, Panel, Project, ReadingDirection
from .layout import (
    LayoutError,
    PanelSpec,
    choose_template,
    compute_layout,
    move_gutter,
    set_cut_slant,
    tree_from_json,
)
from .layout_style import default_seed, styled_layout


def panel_specs(page: Page) -> list[PanelSpec]:
    return [
        PanelSpec(
            importance=p.importance,
            dialogue_chars=sum(len(b.text) for b in p.bubbles),
            panel_id=p.id,
            intensity=p.intensity,
        )
        for p in page.panels
    ]


def effective_style(page: Page) -> str:
    return page.layout_style or page.chapter.project.layout_style


def layout_signature(page: Page) -> str:
    """Ce dont dépend la mise en page : si cela change, elle est obsolète."""
    specs = [[s.panel_id, s.importance, s.dialogue_chars, s.intensity] for s in panel_specs(page)]
    fmt = page.chapter.project.page_format
    direction = page.chapter.project.reading_direction.value
    return json.dumps(
        [
            page.number,
            fmt,
            direction,
            page.grid_template,
            specs,
            page.chapter.project.layout_style,
            page.layout_style,
            page.layout_seed,
            page.rythme,
        ],
        separators=(",", ":"),
    )


def is_stale(page: Page) -> bool:
    return page.layout is None or page.layout.get("signature") != layout_signature(page)


def _store(page: Page, layout: dict[str, Any]) -> dict[str, Any]:
    layout = {**layout, "signature": layout_signature(page)}
    if REROLL_KEY not in layout and page.layout and REROLL_KEY in page.layout:
        layout[REROLL_KEY] = page.layout[REROLL_KEY]  # gouttière, biais, miroir : le tirage est gardé
    page.layout = layout
    for panel, lp in zip(page.panels, layout["panels"], strict=True):
        panel.bbox = {k: lp[k] for k in ("x1", "y1", "x2", "y2")}
        panel.bubble_zone = lp["bubble_zone"]
    if page.state == PageState.draft:
        page.state = PageState.layout
    return layout


# Gabarits écartés par « Nouvelle mise en page » : réappliqués à chaque recalcul de la page tant que
# son nombre de cases ne change pas, sinon la même graine retomberait sur un autre gabarit.
REROLL_KEY = "reroll_exclude"


def _rerolled_out(page: Page, panel_count: int) -> list[str]:
    saved = (page.layout or {}).get(REROLL_KEY)
    if isinstance(saved, dict) and saved.get("panels") == panel_count:
        return [t for t in saved.get("templates", []) if isinstance(t, str)]
    return []


def _previous_template(page: Page) -> str | None:
    """Gabarit de la page précédente du chapitre (règle « jamais deux mises en page identiques d'affilée »)."""
    prev = next((p for p in page.chapter.pages if p.number == page.number - 1), None)
    if prev is None or not prev.layout:
        return None
    return prev.layout.get("template_id")


def layout_page(presets: PresetRegistry, page: Page, *, reroll: bool = False) -> dict[str, Any] | None:
    """(Re)calcule la mise en page depuis le style, la graine et le gabarit imposé ou choisi.

    `reroll` : nouvelle graine, et le gabarit actuel est écarté s'il en existe un autre.
    """
    series = page.chapter.project
    fmt = presets.page_format(series.page_format)
    specs = panel_specs(page)
    if not specs:
        page.layout = None
        return None
    forced = None
    if page.grid_template:
        tpl = presets.layout_template(page.grid_template)
        if tpl.panel_count != len(specs):
            raise LayoutError(
                f"le gabarit « {tpl.name} » a {tpl.panel_count} case(s), la page {page.number} en a {len(specs)}"
            )
        forced = (tpl.id, tpl.tree)
    style = presets.layout_styles.get(effective_style(page))
    direction = series.reading_direction.value
    if style is None:
        # Style introuvable (preset retiré) : découpage droit d'avant les styles.
        template_id, tree = forced or choose_template(
            list(presets.layout_templates.values()), [s.importance for s in specs]
        )
        layout = compute_layout(
            fmt, presets.layout, tree, specs, direction=direction, page_number=page.number, template_id=template_id
        )
        return _store(page, layout)

    rerolled_out = _rerolled_out(page, len(specs))
    if reroll:
        page.layout_seed = secrets.randbelow(2**31 - 1)
        if page.layout and not forced and page.layout.get("template_id"):
            rerolled_out = [page.layout["template_id"]]
    elif page.layout_seed is None:
        page.layout_seed = default_seed(page.chapter_id, page.number)
    exclude = [] if forced else list(rerolled_out)
    previous = _previous_template(page)
    if style.avoid_repeat and previous and not forced:
        exclude.append(previous)
    layout = styled_layout(
        fmt,
        presets.layout,
        style,
        list(presets.layout_templates.values()),
        specs,
        direction=direction,
        page_number=page.number,
        seed=page.layout_seed,
        rythme=page.rythme,
        forced=forced,
        exclude=exclude,
    )
    if rerolled_out:
        layout[REROLL_KEY] = {"panels": len(specs), "templates": rerolled_out}
    return _store(page, layout)


def layout_pages(presets: PresetRegistry, pages: Sequence[Page]) -> None:
    """Pages dans l'ordre : chacune tient compte du gabarit de la précédente."""
    for page in sorted(pages, key=lambda p: p.number):
        layout_page(presets, page)


def _check_fresh(page: Page) -> None:
    if page.layout is None or is_stale(page):
        raise LayoutError(
            "la mise en page n'est plus à jour : clique sur « Recalculer » avant de déplacer une gouttière"
        )


def move_page_gutter(
    presets: PresetRegistry, page: Page, *, path: Sequence[int], index: int, position: float
) -> dict[str, Any]:
    _check_fresh(page)
    assert page.layout is not None
    fmt = presets.page_format(page.chapter.project.page_format)
    layout = move_gutter(fmt, presets.layout, page.layout, panel_specs(page), path=path, index=index, position=position)
    return _store(page, layout)


def slant_page_cut(
    presets: PresetRegistry, page: Page, *, path: Sequence[int], index: int, ends: Sequence[float]
) -> dict[str, Any]:
    """Incline une découpe (positions de ses deux extrémités) : les images des cases sont gardées."""
    _check_fresh(page)
    assert page.layout is not None
    fmt = presets.page_format(page.chapter.project.page_format)
    layout = set_cut_slant(fmt, presets.layout, page.layout, panel_specs(page), path=path, index=index, ends=ends)
    return _store(page, layout)


def regeneration_advised(panel: Panel, layout_panel: dict[str, Any] | None, threshold: float) -> bool:
    """La boîte de la case a-t-elle changé de ratio (au-delà du seuil du preset) depuis l'image retenue ?

    Une case garde son image quand seul le biais ou une gouttière change : elle est recadrée au
    polygone. On ne conseille de la régénérer que si le recadrage perdrait trop de l'image.
    """
    chosen = next((i for i in panel.images if i.selected), None)
    if chosen is None or layout_panel is None:
        return False
    params = chosen.params or {}
    w, h = params.get("image_width"), params.get("image_height")
    if not (isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0):
        return False
    box_ratio = layout_panel["width"] / max(1, layout_panel["height"])
    return abs(math.log(box_ratio / (w / h))) > math.log(1 + threshold)


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
                        style=layout.get("style"),  # mêmes gouttières, mêmes biais (en miroir)
                    ),
                )
                _mirror_lettering(page, old_boxes[page.id])
            else:
                layout_page(presets, page)
            done += 1
        except (LayoutError, PresetError, KeyError, ValueError):
            continue
    return done
