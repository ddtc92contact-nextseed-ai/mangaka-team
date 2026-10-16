"""Distribution et lieu d'une scène, descendus sur ses cases (#197).

Une scène validée (étape Scènes, `pipeline/scenes.py`) porte sa **distribution** (`ChapterScene.character_ids` :
les fiches qui y jouent) et son **lieu** (`ChapterScene.location_id`). Le scénariste et la direction artistique les
reçoivent en clair ; puis chaque case de la scène en hérite :

- **personnages** : un personnage de la distribution que le texte de la case nomme (description ou mise en scène,
  nom ou alias, rapprochement de `pipeline/names.py`) sans le déclarer — ni dans l'image, ni hors cadre — est
  déclaré **dans l'image** : sa fiche part avec la case au lieu d'un personnage dessiné d'après la prose ;
- **lieu** : une case sans lieu reçoit celui de la scène, donc la fiche de décor du lieu quand elle existe
  (`pipeline/library.py` `panel_decor_id`).

Un choix fait à la main par l'auteur sur une case n'est jamais écrasé : personnages corrigés (`Panel.cast_manual`),
lieu choisi ou retiré (`Panel.location_manual`). La descente n'ajoute jamais rien qui ne soit pas écrit : une case
qui ne nomme pas un personnage de la distribution ne le reçoit pas.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy.orm import Session

from ..store.models import Chapter, ChapterScene, Character, PageKind, Panel, SeriesLocation
from .names import CharacterMatcher, panel_context, panel_ids, previous_panel


def cast_names(scene: ChapterScene | None, characters: Iterable[Character]) -> list[str]:
    """Noms des fiches de la distribution d'une scène, dans son ordre (une fiche supprimée est ignorée)."""
    if scene is None:
        return []
    names = {c.id: c.name for c in characters}
    return [names[i] for i in scene.character_ids or [] if i in names]


def cast_text(names: Sequence[str]) -> str:
    return ", ".join(names) if names else "(pas de distribution validée : les personnages de chaque case)"


def resolve_cast(matcher: CharacterMatcher, values: Iterable[Any]) -> list[int]:
    """Ids des fiches désignées par une liste d'ids ou de noms (réponse du LLM), sans doublon, dans l'ordre."""
    known = set(matcher.names)
    out: list[int] = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit()):
            ids = [int(v)] if int(v) in known else []
        else:
            ids = list(matcher.resolve(str(v or "")).ids)
        out += [i for i in ids if i not in out]
    return out


def descend_panel(
    session: Session, matcher: CharacterMatcher, panel: Panel, scene: ChapterScene | None, previous: Any = None
) -> tuple[bool, bool]:
    """Distribution et lieu de `scene` sur `panel` : (personnages ajoutés, lieu reçu). `previous` : case précédente
    (arbitrage des noms)."""
    if scene is None:
        return False, False
    added = False
    cast = [i for i in scene.character_ids or [] if i in matcher.names]
    if cast and not panel.cast_manual:
        context = panel_context(matcher, panel, previous)
        declared = set(matcher.ids([*(panel.character_names or []), *(panel.offscreen_names or [])], context))
        named: list[int] = []
        for text in (panel.description, panel.staging):
            for r in matcher.resolve_all(matcher.read_names(text), [set(cast), *context]):
                named += [i for i in r.ids if i in cast and i not in declared and i not in named]
        if named:
            panel.character_names = [*(panel.character_names or []), *(matcher.names[i] for i in named)]
            panel.character_ids = panel_ids(matcher, panel, previous)
            added = True
    located = False
    # `location` aussi : sur une case neuve (pas encore écrite en base), seule la relation est posée.
    unplaced = panel.location_id is None and panel.location is None
    if scene.location_id is not None and unplaced and not panel.location_manual:
        # Par la relation : une case neuve (pas encore en session) a déjà `location` posé à None par le scénario.
        panel.location = session.get(SeriesLocation, scene.location_id)
        located = panel.location is not None
    return added, located


def descend_chapter(session: Session, chapter: Chapter, scene_ids: Iterable[int] | None = None) -> int:
    """Descente de chaque scène (ou des seules `scene_ids`) sur les cases déjà écrites de ses pages ; renvoie le
    nombre de cases modifiées."""
    wanted = set(scene_ids) if scene_ids is not None else None
    scenes = {s.id: s for s in chapter.scenes if wanted is None or s.id in wanted}
    if not scenes:
        return 0
    matcher = CharacterMatcher.for_project(session, chapter.project_id)
    changed = 0
    for page in sorted(chapter.pages, key=lambda p: p.number):
        scene = scenes.get(page.scene_id) if page.scene_id is not None else None
        if scene is None or page.kind != PageKind.story:
            continue
        for panel in sorted(page.panels, key=lambda p: p.index):
            if any(descend_panel(session, matcher, panel, scene, previous_panel(panel))):
                changed += 1
    session.flush()
    return changed
