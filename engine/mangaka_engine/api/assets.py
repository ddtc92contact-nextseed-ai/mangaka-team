"""CRUD des objets, décors, véhicules et créatures récurrents de la bibliothèque d'une série.

Même forme d'API que les personnages (`characters.py`), une famille de routes par sorte :
`/projects/{id}/objects`, `/objects/{id}`, `/objects/{id}/images`… et de même pour `/decors`, `/vehicles` et
`/creatures`. Supprimer une fiche la retire des cases qui la citaient (et un décor, des lieux qu'il illustrait).

`POST /objects/{id}/kind` (et `/vehicles/…`, `/creatures/…`) change la catégorie d'un objet, d'un véhicule ou
d'une créature (objet → véhicule) : même id, mêmes images (leurs fichiers ne bougent pas dans data/), mêmes
variantes (`ReferenceVariant.entry_kind` suit), mêmes cases ; son dossier de ComfyUI passe sous la nouvelle
sorte (`objets/<nom>` → `vehicules/<nom>`), la bibliothèque lisible suit au commit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline.reference_sheets import FOLDERS, active_jobs, delete_entry_variants, entry_folder, next_position
from ..store.files import StoredImage, cache_headers, versioned_url
from ..store.models import (
    PANEL_OBJECT_KINDS,
    AssetKind,
    Chapter,
    Page,
    Panel,
    ReferenceVariant,
    SeriesAsset,
    SeriesAssetImage,
    SeriesLocation,
)
from ..store.slugs import KIND_FOLDERS, entry_slug
from .characters import apply_changes, check_room, read_uploads, reference_image_out, store_uploads
from .deps import AppContext, get_ctx, get_session
from .projects import get_project_or_404
from .schemas import AssetCreate, AssetKindIn, AssetOut, AssetUpdate
from .storage import move_folders, remove_entry_folders, rename_entry, set_entry_slug

# Sorte → (segment d'URL, libellé « introuvable », dossier sous data/projects/{id}/).
ROUTES = {
    AssetKind.object: ("objects", "Objet introuvable"),
    AssetKind.decor: ("decors", "Décor introuvable"),
    AssetKind.vehicle: ("vehicles", "Véhicule introuvable"),
    AssetKind.creature: ("creatures", "Créature introuvable"),
}


def asset_image_url(asset: SeriesAsset, img: SeriesAssetImage) -> str:
    return versioned_url(f"/{ROUTES[asset.kind][0]}/{asset.id}/images/{img.id}/file", img.path)


def asset_out(a: SeriesAsset) -> AssetOut:
    return AssetOut(
        id=a.id,
        project_id=a.project_id,
        kind=a.kind.value,
        name=a.name,
        slug=a.slug,
        visual_description=a.visual_description,
        prompt_keywords=list(a.prompt_keywords or []),
        lora_name=a.lora_name,
        lora_weight=a.lora_weight,
        lora_trigger_words=a.lora_trigger_words or "",
        reference_images=[reference_image_out(img, asset_image_url(a, img)) for img in a.reference_images],
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def get_asset_or_404(session: Session, kind: AssetKind, asset_id: int) -> SeriesAsset:
    asset = session.get(SeriesAsset, asset_id, options=[selectinload(SeriesAsset.reference_images)])
    if asset is None or asset.kind != kind:
        raise HTTPException(status_code=404, detail=ROUTES[kind][1])
    return asset


def unlink_asset(session: Session, asset: SeriesAsset) -> int:
    """Retire un objet (véhicule, créature) ou un décor des cases (et un décor des lieux) de sa série ; renvoie le
    nombre de cases modifiées."""
    if asset.kind == AssetKind.decor:
        for loc in session.scalars(
            select(SeriesLocation).where(
                SeriesLocation.project_id == asset.project_id, SeriesLocation.decor_id == asset.id
            )
        ):
            loc.decor_id = None
    panels = session.scalars(
        select(Panel)
        .join(Page, Page.id == Panel.page_id)
        .join(Chapter, Chapter.id == Page.chapter_id)
        .where(Chapter.project_id == asset.project_id)
    )
    changed = 0
    for panel in panels:
        if asset.kind == AssetKind.decor and panel.decor_id == asset.id:
            panel.decor_id = None
            changed += 1
        elif asset.kind in PANEL_OBJECT_KINDS and asset.id in (panel.object_ids or []):
            panel.object_ids = [i for i in panel.object_ids if i != asset.id]
            changed += 1
    return changed


def change_kind(
    ctx: AppContext, session: Session, asset: SeriesAsset, kind: AssetKind
) -> tuple[list[str], list[str]] | None:
    """Nouvelle catégorie d'un objet, d'un véhicule ou d'une créature (sans commit, dossiers de ComfyUI déplacés
    après) : variantes et jobs terminés suivent, images et cases ne changent pas. Refusé pendant une génération de
    ses fiches (le job relirait la fiche sous son ancienne sorte)."""
    old = asset.kind
    if old not in PANEL_OBJECT_KINDS or kind not in PANEL_OBJECT_KINDS:
        raise HTTPException(status_code=422, detail="seuls un objet, un véhicule ou une créature changent de catégorie")
    if active_jobs(session, old.value, asset.id, asset.project_id):
        raise HTTPException(
            status_code=409, detail="génération de fiches en cours : attends la fin (ou annule-la) avant de changer"
        )
    for variant in session.scalars(
        select(ReferenceVariant).where(ReferenceVariant.entry_kind == old.value, ReferenceVariant.entry_id == asset.id)
    ):
        variant.entry_kind = kind.value
    series = asset.project
    before = asset.slug
    asset.kind = kind
    asset.slug = entry_slug(session, asset, on_disk=ctx.folders.existing_entries(series.slug, kind.value))
    return (
        (
            [series.slug, KIND_FOLDERS[old.value], before],
            [series.slug, KIND_FOLDERS[kind.value], asset.slug],
        )
        if before
        else None
    )


def _router(kind: AssetKind) -> APIRouter:
    segment, _ = ROUTES[kind]
    router = APIRouter(tags=["bibliothèque"])

    @router.get(f"/projects/{{project_id}}/{segment}", response_model=list[AssetOut], name=f"list_{segment}")
    def list_assets(project_id: int, session: Session = Depends(get_session)) -> list[AssetOut]:
        get_project_or_404(session, project_id)
        rows = session.scalars(
            select(SeriesAsset)
            .where(SeriesAsset.project_id == project_id, SeriesAsset.kind == kind)
            .options(selectinload(SeriesAsset.reference_images))
            .order_by(SeriesAsset.name)
        ).all()
        return [asset_out(a) for a in rows]

    @router.post(
        f"/projects/{{project_id}}/{segment}", response_model=AssetOut, status_code=201, name=f"create_{segment}"
    )
    def create_asset(
        project_id: int, body: AssetCreate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
    ) -> AssetOut:
        series = get_project_or_404(session, project_id)
        asset = SeriesAsset(project_id=project_id, kind=kind, **body.model_dump())
        set_entry_slug(ctx, session, asset, series)
        session.add(asset)
        session.commit()
        return asset_out(get_asset_or_404(session, kind, asset.id))

    @router.get(f"/{segment}/{{asset_id}}", response_model=AssetOut, name=f"get_{segment}")
    def get_asset(asset_id: int, session: Session = Depends(get_session)) -> AssetOut:
        return asset_out(get_asset_or_404(session, kind, asset_id))

    @router.patch(f"/{segment}/{{asset_id}}", response_model=AssetOut, name=f"update_{segment}")
    def update_asset(
        asset_id: int, body: AssetUpdate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
    ) -> AssetOut:
        asset = get_asset_or_404(session, kind, asset_id)
        apply_changes(asset, body)
        move = rename_entry(ctx, session, asset, asset.project) if "name" in body.model_fields_set else None
        session.commit()
        move_folders(ctx, move)
        return asset_out(asset)

    if kind in PANEL_OBJECT_KINDS:

        @router.post(f"/{segment}/{{asset_id}}/kind", response_model=AssetOut, name=f"change_{segment}_kind")
        def change_asset_kind(
            asset_id: int,
            body: AssetKindIn,
            session: Session = Depends(get_session),
            ctx: AppContext = Depends(get_ctx),
        ) -> AssetOut:
            """Change la catégorie (objet ↔ véhicule ↔ créature) en gardant images, variantes et cases."""
            asset = get_asset_or_404(session, kind, asset_id)
            target = AssetKind(body.kind)
            if target == asset.kind:
                return asset_out(asset)
            move = change_kind(ctx, session, asset, target)
            session.commit()
            move_folders(ctx, move)
            return asset_out(get_asset_or_404(session, target, asset_id))

    @router.delete(f"/{segment}/{{asset_id}}", status_code=204, name=f"delete_{segment}")
    def delete_asset(
        asset_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
    ) -> Response:
        asset = get_asset_or_404(session, kind, asset_id)
        paths = [img.path for img in asset.reference_images]
        paths += delete_entry_variants(session, asset.kind.value, asset.id)
        series = asset.project.slug
        unlink_asset(session, asset)
        session.delete(asset)
        session.commit()
        for path in paths:
            ctx.files.delete(path)
        ctx.files.delete_tree(entry_folder(asset))
        if asset.kind in PANEL_OBJECT_KINDS:  # dossiers d'avant un changement de catégorie (ids jamais réutilisés)
            for other in PANEL_OBJECT_KINDS:
                ctx.files.delete_tree(f"projects/{asset.project_id}/{FOLDERS[other.value]}/{asset.id}")
        remove_entry_folders(ctx, series, asset)
        return Response(status_code=204)

    @router.post(
        f"/{segment}/{{asset_id}}/images", response_model=AssetOut, status_code=201, name=f"upload_{segment}_images"
    )
    async def upload_images(
        asset_id: int,
        files: list[UploadFile] = File(..., description="Images PNG, JPEG ou WebP"),
        session: Session = Depends(get_session),
        ctx: AppContext = Depends(get_ctx),
    ) -> AssetOut:
        asset = get_asset_or_404(session, kind, asset_id)
        payloads = await read_uploads(files, ctx)
        check_room(asset, len(payloads))

        def add(name: str, path: str, stored: StoredImage) -> None:
            asset.reference_images.append(
                SeriesAssetImage(
                    path=path,
                    original_name=name,
                    content_type=stored.content_type,
                    width=stored.width,
                    height=stored.height,
                    position=next_position(asset),
                )
            )

        store_uploads(session, ctx, payloads, f"projects/{asset.project_id}/{segment}/{asset.id}", add)
        return asset_out(get_asset_or_404(session, kind, asset_id))

    def _get_image(session: Session, asset_id: int, image_id: int) -> SeriesAssetImage:
        get_asset_or_404(session, kind, asset_id)
        img = session.get(SeriesAssetImage, image_id)
        if img is None or img.asset_id != asset_id:
            raise HTTPException(status_code=404, detail="Image introuvable")
        return img

    @router.get(f"/{segment}/{{asset_id}}/images/{{image_id}}/file", name=f"get_{segment}_image")
    def get_image(
        asset_id: int,
        image_id: int,
        v: str | None = None,
        session: Session = Depends(get_session),
        ctx: AppContext = Depends(get_ctx),
    ) -> FileResponse:
        img = _get_image(session, asset_id, image_id)
        path = ctx.files.absolute(img.path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
        return FileResponse(path, media_type=img.content_type, headers=cache_headers(img.path, v))

    @router.delete(f"/{segment}/{{asset_id}}/images/{{image_id}}", status_code=204, name=f"delete_{segment}_image")
    def delete_image(
        asset_id: int,
        image_id: int,
        session: Session = Depends(get_session),
        ctx: AppContext = Depends(get_ctx),
    ) -> Response:
        img = _get_image(session, asset_id, image_id)
        path = img.path
        session.delete(img)
        session.commit()
        ctx.files.delete(path)
        return Response(status_code=204)

    return router


router = APIRouter()
for _kind in ROUTES:  # références de style : api/style_board.py
    router.include_router(_router(_kind))
