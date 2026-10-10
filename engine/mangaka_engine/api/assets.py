"""CRUD des objets et des décors récurrents de la bibliothèque d'une série.

Même forme d'API que les personnages (`characters.py`), une famille de routes par sorte :
`/projects/{id}/objects`, `/objects/{id}`, `/objects/{id}/images`… et de même pour `/decors`.
Supprimer un objet ou un décor le retire des cases qui le citaient.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..store.files import StoredImage
from ..store.models import AssetKind, Chapter, Page, Panel, SeriesAsset, SeriesAssetImage
from .characters import apply_changes, read_uploads, reference_image_out, store_uploads
from .deps import AppContext, get_ctx, get_session
from .projects import get_project_or_404
from .schemas import AssetCreate, AssetOut, AssetUpdate

# Sorte → (segment d'URL, libellé « introuvable », dossier sous data/projects/{id}/).
ROUTES = {
    AssetKind.object: ("objects", "Objet introuvable"),
    AssetKind.decor: ("decors", "Décor introuvable"),
}


def asset_image_url(asset: SeriesAsset, img: SeriesAssetImage) -> str:
    return f"/{ROUTES[asset.kind][0]}/{asset.id}/images/{img.id}/file"


def asset_out(a: SeriesAsset) -> AssetOut:
    return AssetOut(
        id=a.id,
        project_id=a.project_id,
        kind=a.kind.value,
        name=a.name,
        visual_description=a.visual_description,
        prompt_keywords=list(a.prompt_keywords or []),
        lora_name=a.lora_name,
        lora_weight=a.lora_weight,
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
    """Retire un objet ou un décor des cases de sa série ; renvoie le nombre de cases modifiées."""
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
        elif asset.kind == AssetKind.object and asset.id in (panel.object_ids or []):
            panel.object_ids = [i for i in panel.object_ids if i != asset.id]
            changed += 1
    return changed


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
    def create_asset(project_id: int, body: AssetCreate, session: Session = Depends(get_session)) -> AssetOut:
        get_project_or_404(session, project_id)
        asset = SeriesAsset(project_id=project_id, kind=kind, **body.model_dump())
        session.add(asset)
        session.commit()
        return asset_out(get_asset_or_404(session, kind, asset.id))

    @router.get(f"/{segment}/{{asset_id}}", response_model=AssetOut, name=f"get_{segment}")
    def get_asset(asset_id: int, session: Session = Depends(get_session)) -> AssetOut:
        return asset_out(get_asset_or_404(session, kind, asset_id))

    @router.patch(f"/{segment}/{{asset_id}}", response_model=AssetOut, name=f"update_{segment}")
    def update_asset(asset_id: int, body: AssetUpdate, session: Session = Depends(get_session)) -> AssetOut:
        asset = get_asset_or_404(session, kind, asset_id)
        apply_changes(asset, body)
        session.commit()
        return asset_out(asset)

    @router.delete(f"/{segment}/{{asset_id}}", status_code=204, name=f"delete_{segment}")
    def delete_asset(
        asset_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
    ) -> Response:
        asset = get_asset_or_404(session, kind, asset_id)
        paths = [img.path for img in asset.reference_images]
        unlink_asset(session, asset)
        session.delete(asset)
        session.commit()
        for path in paths:
            ctx.files.delete(path)
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

        def add(name: str, path: str, stored: StoredImage) -> None:
            asset.reference_images.append(
                SeriesAssetImage(
                    path=path,
                    original_name=name,
                    content_type=stored.content_type,
                    width=stored.width,
                    height=stored.height,
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
        session: Session = Depends(get_session),
        ctx: AppContext = Depends(get_ctx),
    ) -> FileResponse:
        img = _get_image(session, asset_id, image_id)
        path = ctx.files.absolute(img.path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
        return FileResponse(path, media_type=img.content_type, headers={"Cache-Control": "private, max-age=3600"})

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
for _kind in AssetKind:
    router.include_router(_router(_kind))
