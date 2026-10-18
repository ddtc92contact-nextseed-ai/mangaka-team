"""Unité de lieu : les lieux d'une série (`SeriesLocation`) et le rattachement des cases.

Avant, le lieu n'était qu'un texte libre recopié sur chaque case (`Panel.setting`) : « la petite île » comptait
24 « lieux » pour 38 cases — des variantes de rédaction (« clairière », « clairière au centre de l'île »), pas
des lieux. Désormais :

- **lieu** : nom, description et décor de la bibliothèque (`decor_id`) ; une case s'y rattache
  (`Panel.location_id`), `setting` est le décor de la case (moment, météo, éléments visibles du lieu) ;
- **scénariste** (`pipeline/script.py`) : choisit un lieu existant par son id ou en crée un par son nom
  (`resolve_location`) ; le directeur artistique peut rattacher une case à un lieu existant ;
- **regroupement** des cases d'avant : le LLM propose des groupes de variantes (`propose_groups`, prompt
  presets/prompts/lieux.yaml), l'auteur les relit et les valide dans l'écran « Lieux » de la série
  (`apply_groups`). Rien n'est perdu : le texte de chaque case reste, une case sans texte prend le lieu de la case
  qui la précède (ou, en tête de chapitre, de celle qui la suit) ;
- **références** (`pipeline/library.py` `panel_assets`) : une case sans décor propre reçoit le décor de son lieu,
  servi comme référence de lieu juste après les références d'identité des personnages ;
- **alertes** (`reference_alerts`, écran Atelier) : case avec un personnage sans aucune référence, lieu sans décor
  (ou décor sans image), case sans lieu.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetError, PresetRegistry, PromptPreset
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.models import AssetKind, Chapter, Page, PageKind, Panel, Project, SeriesAsset, SeriesLocation
from ..validation import format_errors
from .framing import plain
from .library import short_description

PROMPT_ID = "lieux"  # presets/prompts/lieux.yaml
MAX_NAME = 120
MAX_SETTINGS = 400  # variantes envoyées au LLM en une fois

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
# Fin du nom d'un lieu dans un texte libre : ce qui suit précise le moment, le coin ou les éléments visibles.
_CUT = re.compile(r"[,;:(\[—–]| - |\. ")
_ARTICLES = ("l'", "le ", "la ", "les ", "un ", "une ", "des ", "du ")
# Mots qui ouvrent une précision (« clairière au centre de l'île » → « clairière »).
_PRECISIONS = (
    " au ",
    " aux ",
    " a ",
    " pres ",
    " sur ",
    " sous ",
    " devant ",
    " derriere ",
    " dans ",
    " en ",
    " vers ",
    " face ",
    " le long ",
    " entre ",
    " avec ",
    " de nuit",
    " de jour",
    " a l'",
    " du ",
    " des ",
    " de l'",
)


class LocationsError(Exception):
    """Échec lisible (en français) du regroupement des lieux."""


def location_key(text: str | None) -> str:
    """Clé de rapprochement d'un nom ou d'un texte de lieu : minuscules, sans accents ni ponctuation."""
    t = plain(text or "")
    t = re.sub(r"[^\w']+", " ", t)
    return " ".join(t.split())


def place_head(setting: str | None) -> str:
    """Clé du nom de lieu d'un texte libre (repli sans LLM, et LLM factice) : la première proposition, sans
    article ni précision — « Clairière au centre de l'île, fin d'après-midi » → « clairiere »."""
    first = _CUT.split((setting or "").strip(), maxsplit=1)[0]
    key = f" {location_key(first)} "
    for art in _ARTICLES:
        if key.startswith(" " + art):
            key = " " + key[len(art) + 1 :]
            break
    cut = min((i for i in (key.find(p) for p in _PRECISIONS) if i > 0), default=len(key))
    return " ".join(key[:cut].split())


def place_name(setting: str | None) -> str:
    """Nom de lieu lisible d'un texte libre, avec ses accents : « la Clairière au centre… » → « Clairière »."""
    words = len(place_head(setting).split())
    first = _CUT.split((setting or "").strip(), maxsplit=1)[0].replace("’", "'").split()
    if first and location_key(first[0]) in ("le", "la", "les", "un", "une", "des", "du"):
        first = first[1:]
    elif first and first[0].lower().startswith("l'"):
        first = [first[0][2:], *first[1:]]
    head = " ".join(first[:words])
    return (head[:1].upper() + head[1:])[:MAX_NAME]


# --- lieux d'une série ----------------------------------------------------------------
def series_locations(session: Session, project_id: int) -> list[SeriesLocation]:
    return list(
        session.scalars(
            select(SeriesLocation)
            .where(SeriesLocation.project_id == project_id)
            .order_by(SeriesLocation.name, SeriesLocation.id)
        )
    )


def locations_brief(session: Session, project_id: int) -> list[dict[str, Any]]:
    """Lieux tels que présentés aux agents : [{"id", "name", "description", "decor"}]."""
    return [
        {"id": loc.id, "name": loc.name, "description": short_description(loc.description), "decor": loc.decor_id}
        for loc in series_locations(session, project_id)
    ]


def locations_text(locations: Sequence[dict[str, Any]]) -> str:
    """« - id 3 · La clairière : description (décor id 7) » pour un prompt ; vide sans lieu."""
    lines = []
    for e in locations:
        decor = f" (décor id {e['decor']})" if e.get("decor") is not None else ""
        lines.append(f"- id {e['id']} · {e['name']} : {e.get('description') or '(sans description)'}{decor}")
    return "\n".join(lines)


def resolve_location(
    session: Session, project_id: int, choice: int | str | None, *, decor_id: int | None = None
) -> SeriesLocation | None:
    """Lieu d'une case : un id existant de la série, ou un nom (un lieu de même nom est repris, sinon créé avec le
    décor de la case). None : pas de lieu."""
    if choice is None:
        return None
    if isinstance(choice, int):
        loc = session.get(SeriesLocation, choice)
        return loc if loc is not None and loc.project_id == project_id else None
    name = " ".join(str(choice).split())[:MAX_NAME]
    key = location_key(name)
    if not key:
        return None
    for loc in series_locations(session, project_id):
        if location_key(loc.name) == key:
            if loc.decor_id is None and decor_id is not None:
                loc.decor_id = decor_id
            return loc
    loc = SeriesLocation(project_id=project_id, name=name, description="", decor_id=decor_id)
    session.add(loc)
    session.flush()
    return loc


def decor_of(session: Session, location: SeriesLocation | None) -> SeriesAsset | None:
    """Décor de la bibliothèque d'un lieu (None : pas de décor, ou décor supprimé / d'une autre série)."""
    if location is None or location.decor_id is None:
        return None
    asset = session.get(SeriesAsset, location.decor_id)
    if asset is None or asset.kind != AssetKind.decor or asset.project_id != location.project_id:
        return None
    return asset


# --- regroupement des variantes (cases d'avant) -------------------------------------------
def story_panels(session: Session, project_id: int, chapter_id: int | None = None) -> list[tuple[Chapter, Panel]]:
    """Cases des pages « story » de la série (ou d'un chapitre), dans l'ordre de lecture."""
    query = (
        select(Panel, Chapter)
        .join(Page, Page.id == Panel.page_id)
        .join(Chapter, Chapter.id == Page.chapter_id)
        .where(Chapter.project_id == project_id, Page.kind == PageKind.story)
        .order_by(Chapter.number, Page.number, Panel.index)
    )
    if chapter_id is not None:
        query = query.where(Chapter.id == chapter_id)
    return [(ch, panel) for panel, ch in session.execute(query)]


@dataclass
class SettingVariant:
    """Un texte de lieu distinct parmi les cases sans lieu : nombre de cases et chapitres où il apparaît."""

    n: int
    text: str
    panels: int = 0
    chapters: list[int] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"n": self.n, "text": self.text, "panels": self.panels, "chapters": self.chapters}


def setting_variants(session: Session, project_id: int, chapter_id: int | None = None) -> list[SettingVariant]:
    """Textes de lieu distincts des cases pas encore rattachées (rapprochés sans casse ni ponctuation)."""
    out: dict[str, SettingVariant] = {}
    for chapter, panel in story_panels(session, project_id, chapter_id):
        text = " ".join((panel.setting or "").split())
        key = location_key(text)
        if panel.location_id is not None or not key:
            continue
        v = out.setdefault(key, SettingVariant(n=len(out) + 1, text=text))
        v.panels += 1
        if chapter.number not in v.chapters:
            v.chapters.append(chapter.number)
    return list(out.values())


class _LLMModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME)]


class ProposedLocation(_LLMModel):
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    existing: int | None = None  # id d'un lieu existant de la série
    decor: int | None = None  # id d'un décor de la bibliothèque
    settings: list[int] = Field(min_length=1, max_length=MAX_SETTINGS)

    @field_validator("description", mode="before")
    @classmethod
    def _none_text(cls, v: Any) -> Any:
        return "" if v is None else v

    @field_validator("existing", "decor", mode="before")
    @classmethod
    def _none_id(cls, v: Any) -> Any:
        return None if v in ("", "null", "aucun") else v


class LocationsOutput(_LLMModel):
    locations: list[ProposedLocation] = Field(min_length=1, max_length=MAX_SETTINGS)


ERROR_LABELS = {"locations": "lieu", "settings": "variante"}


@dataclass
class GroupsContext:
    series: str
    variants: list[SettingVariant]
    locations: list[dict[str, Any]]
    decors: list[dict[str, Any]]

    def as_json(self) -> dict[str, Any]:
        return {
            "task": "locations",
            "series": self.series,
            "settings": [v.as_json() for v in self.variants],
            "locations": self.locations,
            "decors": self.decors,
        }


def groups_context(session: Session, project: Project, chapter_id: int | None = None) -> GroupsContext:
    decors = session.scalars(
        select(SeriesAsset)
        .where(SeriesAsset.project_id == project.id, SeriesAsset.kind == AssetKind.decor)
        .order_by(SeriesAsset.name, SeriesAsset.id)
    )
    return GroupsContext(
        series=project.title,
        variants=setting_variants(session, project.id, chapter_id)[:MAX_SETTINGS],
        locations=locations_brief(session, project.id),
        decors=[{"id": a.id, "name": a.name, "description": short_description(a.visual_description)} for a in decors],
    )


def _render(template: str, values: dict[str, str], part: str) -> str:
    try:
        return string.Template(template).substitute(values)
    except KeyError as exc:
        raise PresetError(f"presets/prompts : variable inconnue ${exc.args[0]} dans « {part} »") from None
    except ValueError as exc:
        raise PresetError(f"presets/prompts : gabarit « {part} » invalide ({exc})") from None


def render_messages(prompt: PromptPreset, ctx: GroupsContext) -> list[ChatMessage]:
    values = {
        "series_title": ctx.series,
        "settings": "\n".join(f"{v.n}. {v.text} ({v.panels} case{'s' if v.panels > 1 else ''})" for v in ctx.variants),
        "locations": locations_text(ctx.locations) or "(aucun lieu enregistré)",
        "decors": "\n".join(
            f"- id {d['id']} · {d['name']} : {d['description'] or '(sans description)'}" for d in ctx.decors
        )
        or "(aucun décor enregistré : « decor » vaut null)",
        "context_json": json.dumps(ctx.as_json(), ensure_ascii=False, indent=2),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


def parse_groups(text: str, ctx: GroupsContext) -> LocationsOutput:
    """Réponse du LLM validée : chaque variante dans un seul lieu, ids de lieux et de décors existants."""
    m = _FENCE.match(text)
    try:
        data = json.loads(m.group(1) if m else text.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    try:
        out = LocationsOutput.model_validate(data)
    except ValidationError as exc:
        raise ValueError(format_errors(exc, ERROR_LABELS)) from None
    numbers = {v.n for v in ctx.variants}
    location_ids = {e["id"] for e in ctx.locations}
    decor_ids = {d["id"] for d in ctx.decors}
    problems: list[str] = []
    seen: dict[int, str] = {}
    for loc in out.locations:
        if loc.existing is not None and loc.existing not in location_ids:
            problems.append(f"lieu « {loc.name} » : existing {loc.existing} inconnu (ids des lieux ou null)")
        if loc.decor is not None and loc.decor not in decor_ids:
            problems.append(f"lieu « {loc.name} » : décor {loc.decor} inconnu (ids des décors ou null)")
        for n in loc.settings:
            if n not in numbers:
                problems.append(f"lieu « {loc.name} » : variante {n} inconnue")
            elif n in seen:
                problems.append(f"variante {n} rangée deux fois (« {seen[n]} » et « {loc.name} »)")
            else:
                seen[n] = loc.name
    missing = sorted(numbers - set(seen))
    if missing:
        problems.append(
            f"variantes oubliées : {', '.join(map(str, missing[:30]))} (range chaque variante dans un lieu)"
        )
    if problems:
        raise ValueError(" ; ".join(problems[:10]))
    return out


@dataclass
class ProposedGroup:
    """Groupe proposé à l'auteur : lieu (nouveau ou existant), décor, variantes de texte rangées dedans."""

    name: str
    description: str
    existing: int | None
    decor: int | None
    settings: list[str]
    panels: int

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "existing": self.existing,
            "decor": self.decor,
            "settings": self.settings,
            "panels": self.panels,
        }


def to_groups(out: LocationsOutput, ctx: GroupsContext) -> list[ProposedGroup]:
    by_n = {v.n: v for v in ctx.variants}
    groups = []
    for loc in out.locations:
        variants = [by_n[n] for n in loc.settings if n in by_n]
        groups.append(
            ProposedGroup(
                name=loc.name,
                description=loc.description,
                existing=loc.existing,
                decor=loc.decor,
                settings=[v.text for v in variants],
                panels=sum(v.panels for v in variants),
            )
        )
    return [g for g in groups if g.settings]


def propose_groups(llm: LLMProvider, prompt: PromptPreset, ctx: GroupsContext) -> list[ProposedGroup]:
    """Groupes de variantes proposés par le LLM ; nouvel essai avec l'erreur sur une réponse invalide."""
    if not ctx.variants:
        return []
    messages = render_messages(prompt, ctx)
    total = 1 + prompt.max_retries
    last = ""
    for attempt in range(1, total + 1):
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise LocationsError(f"le LLM n'a pas répondu ({exc})") from None
            continue
        try:
            return to_groups(parse_groups(result.text, ctx), ctx)
        except ValueError as exc:
            last = str(exc)
            retry = _render(prompt.retry, {"error": last}, "retry")
            messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
    raise LocationsError(f"réponse du LLM invalide après {total} essai{'s' if total > 1 else ''} : {last}")


def heuristic_groups(ctx: dict[str, Any]) -> dict[str, Any]:
    """Regroupement sans LLM (LLM factice) : variantes de même nom de lieu (`place_head`) ensemble, rattachées au
    lieu existant de même nom ou au décor de même nom."""
    existing = {place_head(e["name"]) or location_key(e["name"]): e for e in ctx.get("locations") or []}
    decors = {location_key(d["name"]): d["id"] for d in ctx.get("decors") or []}
    groups: dict[str, dict[str, Any]] = {}
    for v in ctx.get("settings") or []:
        head = place_head(v["text"]) or location_key(v["text"])
        g = groups.get(head)
        if g is None:
            known = existing.get(head)
            decor = next((i for k, i in decors.items() if head and (head in k or k in head)), None)
            g = groups[head] = {
                "name": known["name"] if known else place_name(v["text"]) or str(v["text"])[:MAX_NAME],
                "description": "" if known else str(v["text"])[:300],
                "existing": known["id"] if known else None,
                "decor": (known or {}).get("decor") or decor,
                "settings": [],
            }
        g["settings"].append(v["n"])
    return {"locations": list(groups.values())}


@dataclass
class GroupIn:
    """Groupe validé par l'auteur (écran « Lieux ») : variantes rangées dans un lieu nouveau ou existant."""

    name: str
    settings: list[str]
    description: str = ""
    existing: int | None = None
    decor: int | None = None


@dataclass
class ApplyResult:
    created: int = 0
    attached: int = 0
    inherited: int = 0  # cases sans texte de lieu, rattachées au lieu de leur voisine
    unattached: int = 0  # cases encore sans lieu (texte absent des groupes)

    def as_json(self) -> dict[str, int]:
        return {
            "created": self.created,
            "attached": self.attached,
            "inherited": self.inherited,
            "unattached": self.unattached,
        }


def apply_groups(
    session: Session, project: Project, groups: Iterable[GroupIn], chapter_id: int | None = None
) -> ApplyResult:
    """Crée ou complète les lieux des groupes et y rattache les cases sans lieu dont le texte est rangé dans un
    groupe ; une case sans texte prend le lieu de sa voisine du même chapitre. Le texte des cases (`setting`) et
    leur décor ne changent pas. `ValueError` lisible sur un lieu ou un décor inconnu."""
    result = ApplyResult()
    known = {loc.id: loc for loc in series_locations(session, project.id)}
    decor_ids = set(
        session.scalars(
            select(SeriesAsset.id).where(SeriesAsset.project_id == project.id, SeriesAsset.kind == AssetKind.decor)
        )
    )
    by_key: dict[str, SeriesLocation] = {}
    for i, g in enumerate(groups):
        if g.decor is not None and g.decor not in decor_ids:
            raise ValueError(f"groups.{i}.decor : décor inconnu dans cette série")
        if g.existing is not None:
            loc = known.get(g.existing)
            if loc is None:
                raise ValueError(f"groups.{i}.existing : lieu inconnu dans cette série")
        else:
            name = " ".join(g.name.split())[:MAX_NAME]
            if not name:
                raise ValueError(f"groups.{i}.name : nom du lieu manquant")
            loc = next((x for x in known.values() if location_key(x.name) == location_key(name)), None)
            if loc is None:
                loc = SeriesLocation(project_id=project.id, name=name, description=g.description.strip())
                session.add(loc)
                session.flush()
                known[loc.id] = loc
                result.created += 1
        if g.existing is not None and g.name.strip():
            loc.name = " ".join(g.name.split())[:MAX_NAME]
        if g.description.strip() and not loc.description:
            loc.description = g.description.strip()
        if g.decor is not None:
            loc.decor_id = g.decor
        for text in g.settings:
            key = location_key(text)
            if key:
                by_key[key] = loc
    rows = story_panels(session, project.id, chapter_id)
    pending: list[Panel] = []  # cases sans texte en attente d'une voisine (début de chapitre)
    previous_chapter: int | None = None
    previous: SeriesLocation | None = None
    for chapter, panel in rows:
        if chapter.id != previous_chapter:
            previous_chapter, previous, pending = chapter.id, None, []
        if panel.location_id is not None:
            previous = panel.location
            continue
        key = location_key(panel.setting)
        loc = by_key.get(key) if key else None
        if loc is not None:
            panel.location = loc
            result.attached += 1
            for p in pending:
                p.location = loc
                result.inherited += 1
            pending = []
            previous = loc
        elif not key and previous is not None:
            panel.location = previous
            result.inherited += 1
        elif not key:
            pending.append(panel)
    session.flush()
    result.unattached = sum(1 for _ch, panel in rows if panel.location_id is None)
    return result


# --- alertes de l'écran de génération -------------------------------------------------------
def reference_alerts(session: Session, presets: PresetRegistry, chapter: Chapter) -> dict[str, Any]:
    """Cases avec un personnage à l'image mais sans aucune image de référence à envoyer, lieux du chapitre sans
    décor (ou dont le décor n'a pas d'image), et cases sans lieu."""
    from .generation import panel_cast  # import local : generation importe library, qui ne connaît pas ce module

    no_reference: list[dict[str, Any]] = []
    unattached: list[dict[str, Any]] = []
    used: dict[int, list[int]] = {}
    for page in sorted(chapter.pages, key=lambda p: p.number):
        if page.kind != PageKind.story:
            continue
        for panel in page.panels:
            where = {"panel_id": panel.id, "page_id": page.id, "page": page.number, "panel": panel.index + 1}
            if panel.location_id is None:
                unattached.append(where)
            else:
                used.setdefault(panel.location_id, []).append(panel.id)
            if not panel.character_names:
                continue
            cast = panel_cast(session, panel, presets)
            if not any(e.reference_images for e in cast.entries):
                no_reference.append({**where, "characters": list(panel.character_names or [])})
    no_decor: list[dict[str, Any]] = []
    for loc_id, panel_ids in used.items():
        loc = session.get(SeriesLocation, loc_id)
        if loc is None:
            continue
        decor = decor_of(session, loc)
        if decor is None or not decor.reference_images:
            no_decor.append(
                {
                    "id": loc.id,
                    "name": loc.name,
                    "panels": len(panel_ids),
                    "reason": "decor_without_image" if decor is not None else "no_decor",
                    "decor": decor.id if decor is not None else None,
                }
            )
    no_decor.sort(key=lambda e: (-e["panels"], e["name"]))
    return {"panels_without_reference": no_reference, "locations_without_decor": no_decor, "unattached": unattached}
