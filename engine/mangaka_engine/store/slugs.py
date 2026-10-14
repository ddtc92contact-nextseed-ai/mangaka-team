"""Noms de dossiers lisibles (« slugs ») des séries et des fiches de la bibliothèque.

Une série reçoit à sa création un slug tiré de son titre (« Lucius et Stan » → `lucius-et-stan`),
unique parmi les séries (collision → `-2`, `-3`…) ; une fiche (personnage, objet, décor, référence de
style) un slug tiré de son nom, unique parmi les fiches de même sorte de la série. Ils nomment les
dossiers de ComfyUI (voir `store/comfy_folders.py`) :

    mangaka/<série>/personnages/<nom>/…   mangaka/<série>/objets/<nom>/…   mangaka/<série>/decors/<nom>/…
    mangaka/<série>/vehicules/<nom>/…     mangaka/<série>/creatures/<nom>/…
    mangaka/<série>/style/…               mangaka/<série>/chapitre-01/page-01/case-01…

`old` (dossier gardé à la main dans ComfyUI) n'est jamais le slug d'une série. Une fiche ou une série
créée sans slug (jobs, essais, tests) en reçoit un au premier `flush` (`assign_missing_slugs`).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from .models import Character, Project, SeriesAsset

MAX_LEN = 60
# Dossier de chaque sorte de fiche sous celui de la série.
KIND_FOLDERS = {
    "character": "personnages",
    "object": "objets",
    "decor": "decors",
    "vehicle": "vehicules",
    "creature": "creatures",
    "style": "style",
}
# Slugs interdits : `old` (archives gardées à la main dans ComfyUI/output/mangaka/) pour une série ;
# `essais` (essais de la planche de style, `style/essais/`) pour une référence de style.
RESERVED_SERIES = frozenset({"old"})
RESERVED_ENTRIES = {"style": frozenset({"essais"})}
SEGMENT = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$")
# Lettres que la décomposition Unicode ne ramène pas à l'ASCII.
_LIGATURES = str.maketrans(
    {"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L"}
)


def slugify(text: str, fallback: str = "sans-nom") -> str:
    """Minuscules, accents retirés, tout le reste → `-` : « Cœur d'Été ! » → `coeur-d-ete`."""
    ascii_text = unicodedata.normalize("NFKD", (text or "").translate(_LIGATURES))
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:MAX_LEN].rstrip("-") or fallback


def unique_slug(base: str, taken: Iterable[str]) -> str:
    """`base`, sinon `base-2`, `base-3`… le premier libre."""
    used = set(taken)
    if base not in used:
        return base
    n = 2
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"


def is_segment(value: str) -> bool:
    """Un slug valide (un seul segment de chemin, sans `.`, `/` ni majuscule)."""
    return bool(SEGMENT.match(value or ""))


def _keep_current(current: str | None, base: str, taken: set[str]) -> bool:
    """Le slug actuel convient encore au nouveau nom (`base` ou `base-N`) et n'est pris par personne."""
    if not current or current in taken:
        return False
    return current == base or re.fullmatch(re.escape(base) + r"-\d+", current) is not None


def series_slug(
    session: Session,
    title: str,
    *,
    project_id: int | None = None,
    current: str | None = None,
    on_disk: Iterable[str] = (),
) -> str:
    """Slug d'une série : celui du titre, unique parmi les autres séries et les dossiers déjà dans ComfyUI."""
    with session.no_autoflush:
        others = select(Project.slug).where(Project.id != project_id) if project_id else select(Project.slug)
        taken = {s for s in session.scalars(others) if s} | set(RESERVED_SERIES) | set(on_disk)
    base = slugify(title, "serie")
    if _keep_current(current, base, taken):
        return str(current)
    return unique_slug(base, taken)


def entry_kind_of(entry: Character | SeriesAsset) -> str:
    return "character" if isinstance(entry, Character) else entry.kind.value


def _same_series(a: Character | SeriesAsset, b: Character | SeriesAsset) -> bool:
    if a.project_id is not None and b.project_id is not None:
        return a.project_id == b.project_id
    return a.project is not None and a.project is b.project


def entry_slug(session: Session, entry: Character | SeriesAsset, *, on_disk: Iterable[str] = ()) -> str:
    """Slug d'une fiche : celui de son nom, unique parmi les fiches de même sorte de la série."""
    kind = entry_kind_of(entry)
    with session.no_autoflush:
        if isinstance(entry, Character):
            query = select(Character.slug).where(Character.project_id == entry.project_id)
            if entry.id is not None:
                query = query.where(Character.id != entry.id)
        else:
            query = select(SeriesAsset.slug).where(
                SeriesAsset.project_id == entry.project_id, SeriesAsset.kind == entry.kind
            )
            if entry.id is not None:
                query = query.where(SeriesAsset.id != entry.id)
        taken = {s for s in session.scalars(query) if s}
    taken |= set(RESERVED_ENTRIES.get(kind, ())) | set(on_disk)
    # Fiches de la même série ajoutées dans ce flush, pas encore en base.
    taken |= {
        o.slug
        for o in session.new
        if o is not entry
        and isinstance(o, Character | SeriesAsset)
        and o.slug
        and _same_series(o, entry)
        and entry_kind_of(o) == kind
    }
    base = slugify(entry.name, "fiche")
    if _keep_current(entry.slug, base, taken):
        return str(entry.slug)
    return unique_slug(base, taken)


def assign_missing_slugs(session: Session) -> None:
    """Donne un slug à chaque série ou fiche nouvelle qui n'en a pas (sans regarder les dossiers de ComfyUI :
    l'API le fait avant, `series_slug(…, on_disk=…)`)."""
    pending_series = [o for o in session.new if isinstance(o, Project) and not o.slug]
    for project in pending_series:
        new_slugs = {o.slug for o in session.new if isinstance(o, Project) and o.slug}
        project.slug = series_slug(session, project.title, on_disk=new_slugs)
    for entry in [o for o in session.new if isinstance(o, Character | SeriesAsset) and not o.slug]:
        entry.slug = entry_slug(session, entry)


@event.listens_for(Session, "before_flush")
def _before_flush(session: Session, _context, _instances) -> None:  # type: ignore[no-untyped-def]
    assign_missing_slugs(session)
