"""Lieux d'une série (unité de lieu des cases) : CRUD, regroupement des variantes des cases d'avant, alertes.

- `GET/POST /projects/{id}/locations`, `PATCH/DELETE /locations/{id}` : nom, description, décor de la
  bibliothèque ; supprimer un lieu détache ses cases (leur texte et leur décor restent) ;
- `POST /projects/{id}/locations/proposal` : le LLM du scénariste range les textes de lieu des cases pas encore
  rattachées en lieux (rien n'est enregistré) ; `POST /projects/{id}/locations/apply` : groupes relus par
  l'auteur, lieux créés et cases rattachées (pipeline/locations.py) ;
- `GET /chapters/{id}/reference-alerts` : cases avec un personnage sans aucune référence, lieux sans décor,
  cases sans lieu (écran Atelier).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..pipeline import locations as lo
from ..presets import PresetError
from ..store.models import AssetKind, Chapter, Page, Panel, SeriesAsset, SeriesLocation
from .assets import asset_image_url
from .chapters import get_chapter_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .projects import get_project_or_404

router = APIRouter(tags=["lieux"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=lo.MAX_NAME)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocationIn(_In):
    name: Name
    description: Text = ""
    decor: int | None = None


class LocationUpdate(_In):
    name: Name | None = None
    description: Text | None = None
    decor: int | None = None  # absent = gardé ; null = plus de décor


class LocationOut(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    decor: int | None
    decor_name: str | None = None
    decor_image_url: str | None = None  # image principale du décor (None : pas de décor ou décor sans image)
    panel_count: int = 0
    chapters: list[int] = Field(default_factory=list)


class VariantOut(BaseModel):
    text: str
    panels: int
    chapters: list[int]


class GroupOut(BaseModel):
    name: str
    description: str = ""
    existing: int | None = None
    decor: int | None = None
    settings: list[str]
    panels: int = 0


class ProposalIn(_In):
    chapter_id: int | None = None


class ProposalOut(BaseModel):
    variants: list[VariantOut]
    groups: list[GroupOut]
    unattached: int  # cases sans lieu, dans le périmètre


class GroupIn(_In):
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=lo.MAX_NAME)] = ""
    description: Text = ""
    existing: int | None = None
    decor: int | None = None
    settings: Annotated[list[Annotated[str, StringConstraints(max_length=1500)]], Field(max_length=lo.MAX_SETTINGS)]
    panels: int | None = None  # renvoyé tel quel depuis la proposition (ignoré)


class ApplyIn(_In):
    chapter_id: int | None = None
    groups: Annotated[list[GroupIn], Field(min_length=1, max_length=lo.MAX_SETTINGS)]


class ApplyOut(BaseModel):
    created: int
    attached: int
    inherited: int
    unattached: int
    locations: list[LocationOut]


class PanelRef(BaseModel):
    panel_id: int
    page_id: int
    page: int
    panel: int  # numéro de la case dans la page (à partir de 1)
    characters: list[str] = Field(default_factory=list)


class LocationAlert(BaseModel):
    id: int
    name: str
    panels: int
    reason: Literal["no_decor", "decor_without_image"]
    decor: int | None = None


class ReferenceAlertsOut(BaseModel):
    panels_without_reference: list[PanelRef]
    locations_without_decor: list[LocationAlert]
    unattached: list[PanelRef]


def get_location_or_404(session: Session, location_id: int) -> SeriesLocation:
    loc = session.get(SeriesLocation, location_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Lieu introuvable")
    return loc


def _check_decor(session: Session, project_id: int, decor: int | None) -> None:
    if decor is None:
        return
    asset = session.get(SeriesAsset, decor)
    if asset is None or asset.project_id != project_id or asset.kind != AssetKind.decor:
        raise FieldError("decor", "décor inconnu dans cette série")


def _check_name(session: Session, project_id: int, name: str, location_id: int | None = None) -> None:
    key = lo.location_key(name)
    for other in lo.series_locations(session, project_id):
        if other.id != location_id and lo.location_key(other.name) == key:
            raise FieldError("name", f"la série a déjà un lieu « {other.name} »")


def locations_out(session: Session, project_id: int) -> list[LocationOut]:
    usage: dict[int, tuple[int, set[int]]] = {}
    rows = session.execute(
        select(Panel.location_id, Chapter.number, func.count(Panel.id))
        .join(Page, Page.id == Panel.page_id)
        .join(Chapter, Chapter.id == Page.chapter_id)
        .where(Chapter.project_id == project_id, Panel.location_id.is_not(None))
        .group_by(Panel.location_id, Chapter.number)
    )
    for loc_id, number, count in rows:
        n, chapters = usage.get(loc_id, (0, set()))
        usage[loc_id] = (n + count, chapters | {number})
    out = []
    for loc in lo.series_locations(session, project_id):
        decor = lo.decor_of(session, loc)
        image = decor.reference_images[0] if decor is not None and decor.reference_images else None
        n, chapters = usage.get(loc.id, (0, set()))
        out.append(
            LocationOut(
                id=loc.id,
                project_id=loc.project_id,
                name=loc.name,
                description=loc.description or "",
                decor=decor.id if decor is not None else None,
                decor_name=decor.name if decor is not None else None,
                decor_image_url=asset_image_url(decor, image) if decor is not None and image is not None else None,
                panel_count=n,
                chapters=sorted(chapters),
            )
        )
    return out


@router.get("/projects/{project_id}/locations", response_model=list[LocationOut])
def list_locations(project_id: int, session: Session = Depends(get_session)) -> list[LocationOut]:
    get_project_or_404(session, project_id)
    return locations_out(session, project_id)


@router.post("/projects/{project_id}/locations", response_model=LocationOut, status_code=201)
def create_location(project_id: int, body: LocationIn, session: Session = Depends(get_session)) -> LocationOut:
    get_project_or_404(session, project_id)
    _check_decor(session, project_id, body.decor)
    _check_name(session, project_id, body.name)
    loc = SeriesLocation(project_id=project_id, name=body.name, description=body.description, decor_id=body.decor)
    session.add(loc)
    session.commit()
    return next(o for o in locations_out(session, project_id) if o.id == loc.id)


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(location_id: int, body: LocationUpdate, session: Session = Depends(get_session)) -> LocationOut:
    loc = get_location_or_404(session, location_id)
    if body.name is not None:
        _check_name(session, loc.project_id, body.name, loc.id)
        loc.name = body.name
    if body.description is not None:
        loc.description = body.description
    if "decor" in body.model_fields_set:
        _check_decor(session, loc.project_id, body.decor)
        loc.decor_id = body.decor
    session.commit()
    return next(o for o in locations_out(session, loc.project_id) if o.id == loc.id)


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: int, session: Session = Depends(get_session)) -> Response:
    """Supprime un lieu : ses cases sont détachées (leur texte de lieu et leur décor restent)."""
    loc = get_location_or_404(session, location_id)
    for panel in session.scalars(select(Panel).where(Panel.location_id == loc.id)):
        panel.location_id = None
    session.delete(loc)
    session.commit()
    return Response(status_code=204)


def _scope(session: Session, project_id: int, chapter_id: int | None) -> None:
    if chapter_id is not None:
        chapter = session.get(Chapter, chapter_id)
        if chapter is None or chapter.project_id != project_id:
            raise FieldError("chapter_id", "chapitre inconnu dans cette série")


@router.post("/projects/{project_id}/locations/proposal", response_model=ProposalOut)
def propose_locations(
    project_id: int, body: ProposalIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ProposalOut:
    """Le LLM range en lieux les textes de lieu des cases pas encore rattachées (variantes de rédaction d'un même
    endroit ensemble). Rien n'est enregistré : l'auteur relit, corrige, puis valide (`/locations/apply`)."""
    project = get_project_or_404(session, project_id)
    _scope(session, project_id, body.chapter_id)
    context = lo.groups_context(session, project, body.chapter_id)
    unattached = sum(1 for _c, p in lo.story_panels(session, project_id, body.chapter_id) if p.location_id is None)
    variants = [VariantOut(text=v.text, panels=v.panels, chapters=v.chapters) for v in context.variants]
    session.commit()  # aucune transaction ouverte pendant l'appel au LLM
    if not context.variants:
        return ProposalOut(variants=[], groups=[], unattached=unattached)
    try:
        prompt = ctx.agents.presets_for(project_id).prompt(lo.PROMPT_ID)
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    llm, error = ctx.agents.llm_for_job("script", project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'fournisseur LLM indisponible'}")
    try:
        groups = lo.propose_groups(llm, prompt, context)
    except lo.LocationsError as exc:
        raise FieldError(
            "groups", f"Regroupement non proposé : {exc}. Réessaie, ou range les lieux à la main."
        ) from None
    return ProposalOut(variants=variants, groups=[GroupOut(**g.as_json()) for g in groups], unattached=unattached)


@router.post("/projects/{project_id}/locations/apply", response_model=ApplyOut)
def apply_locations(project_id: int, body: ApplyIn, session: Session = Depends(get_session)) -> ApplyOut:
    """Groupes validés par l'auteur : lieux créés ou complétés, cases sans lieu rattachées (texte et décor des
    cases inchangés)."""
    project = get_project_or_404(session, project_id)
    _scope(session, project_id, body.chapter_id)
    groups = [lo.GroupIn(g.name, list(g.settings), g.description, g.existing, g.decor) for g in body.groups]
    try:
        result = lo.apply_groups(session, project, groups, body.chapter_id)
    except ValueError as exc:
        field, _, message = str(exc).partition(" : ")
        raise FieldError(field, message or str(exc)) from None
    session.commit()
    return ApplyOut(**result.as_json(), locations=locations_out(session, project_id))


@router.get("/chapters/{chapter_id}/reference-alerts", response_model=ReferenceAlertsOut)
def reference_alerts(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ReferenceAlertsOut:
    chapter = get_chapter_or_404(session, chapter_id)
    presets = ctx.agents.presets_for(chapter.project_id)
    return ReferenceAlertsOut(**lo.reference_alerts(session, presets, chapter))
