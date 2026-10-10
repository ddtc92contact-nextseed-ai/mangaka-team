"""CRUD des personnages et de leurs images de référence."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..store.files import InvalidImageError, StoredImage
from ..store.models import Character, CharacterImage, SeriesAsset, SeriesAssetImage
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .projects import get_project_or_404
from .schemas import CharacterCreate, CharacterOut, CharacterUpdate, ReferenceImageOut

router = APIRouter(tags=["personnages"])

MAX_FILES_PER_UPLOAD = 10


def image_url(img: CharacterImage) -> str:
    return f"/characters/{img.character_id}/images/{img.id}/file"


def reference_image_out(img: CharacterImage | SeriesAssetImage, url: str) -> ReferenceImageOut:
    return ReferenceImageOut(
        id=img.id,
        url=url,
        original_name=img.original_name,
        content_type=img.content_type,
        width=img.width,
        height=img.height,
        created_at=img.created_at,
    )


def character_out(c: Character) -> CharacterOut:
    return CharacterOut(
        id=c.id,
        project_id=c.project_id,
        name=c.name,
        visual_description=c.visual_description,
        prompt_keywords=list(c.prompt_keywords or []),
        lora_name=c.lora_name,
        lora_weight=c.lora_weight,
        lora_trigger_words=c.lora_trigger_words or "",
        reference_images=[reference_image_out(img, image_url(img)) for img in c.reference_images],
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def apply_changes(entry: Character | SeriesAsset, body: CharacterUpdate) -> None:
    """PATCH d'une fiche de la bibliothèque (personnage, objet ou décor)."""
    changes = body.model_dump(exclude_unset=True)
    for key in ("name", "visual_description", "prompt_keywords", "lora_weight"):
        if key in changes and changes[key] is None:
            raise FieldError(key, "ne peut pas être vide")
    if "lora_name" in changes:
        changes["lora_name"] = changes["lora_name"] or None
    if "lora_trigger_words" in changes:
        changes["lora_trigger_words"] = changes["lora_trigger_words"] or ""
    for key, value in changes.items():
        setattr(entry, key, value)


async def read_uploads(files: list[UploadFile], ctx: AppContext) -> list[tuple[str, bytes]]:
    """Lit et contrôle (nombre, taille) les fichiers envoyés, avant d'en écrire un seul."""
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise FieldError("files", f"au plus {MAX_FILES_PER_UPLOAD} images par envoi")
    max_bytes = ctx.settings.max_upload_mb * 1024 * 1024
    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        data = await upload.read(max_bytes + 1)
        name = (upload.filename or "image").rsplit("/", 1)[-1][:255]
        if not data:
            raise FieldError("files", f"{name} : fichier vide")
        if len(data) > max_bytes:
            raise FieldError("files", f"{name} : dépasse {ctx.settings.max_upload_mb} Mo")
        payloads.append((name, data))
    return payloads


def store_uploads(
    session: Session,
    ctx: AppContext,
    payloads: list[tuple[str, bytes]],
    folder: str,
    add: Callable[[str, str, StoredImage], None],
) -> None:
    """Enregistre les images (`add` les rattache à leur fiche) ; tout ou rien."""
    saved: list[str] = []
    try:
        for name, data in payloads:
            try:
                stored = ctx.files.save_image(data, folder)
            except InvalidImageError as exc:
                raise FieldError("files", f"{name} : {exc}") from exc
            saved.append(stored.path)
            add(name, stored.path, stored)
        session.commit()
    except Exception:
        session.rollback()
        for path in saved:
            ctx.files.delete(path)
        raise


def get_character_or_404(session: Session, character_id: int) -> Character:
    character = session.get(Character, character_id, options=[selectinload(Character.reference_images)])
    if character is None:
        raise HTTPException(status_code=404, detail="Personnage introuvable")
    return character


@router.get("/projects/{project_id}/characters", response_model=list[CharacterOut])
def list_characters(project_id: int, session: Session = Depends(get_session)) -> list[CharacterOut]:
    get_project_or_404(session, project_id)
    rows = session.scalars(
        select(Character)
        .where(Character.project_id == project_id)
        .options(selectinload(Character.reference_images))
        .order_by(Character.name)
    ).all()
    return [character_out(c) for c in rows]


@router.post("/projects/{project_id}/characters", response_model=CharacterOut, status_code=201)
def create_character(project_id: int, body: CharacterCreate, session: Session = Depends(get_session)) -> CharacterOut:
    get_project_or_404(session, project_id)
    character = Character(project_id=project_id, **body.model_dump())
    session.add(character)
    session.commit()
    return character_out(get_character_or_404(session, character.id))


@router.get("/characters/{character_id}", response_model=CharacterOut)
def get_character(character_id: int, session: Session = Depends(get_session)) -> CharacterOut:
    return character_out(get_character_or_404(session, character_id))


@router.patch("/characters/{character_id}", response_model=CharacterOut)
def update_character(character_id: int, body: CharacterUpdate, session: Session = Depends(get_session)) -> CharacterOut:
    character = get_character_or_404(session, character_id)
    apply_changes(character, body)
    session.commit()
    return character_out(character)


@router.delete("/characters/{character_id}", status_code=204)
def delete_character(
    character_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    character = get_character_or_404(session, character_id)
    paths = [img.path for img in character.reference_images]
    session.delete(character)
    session.commit()
    for path in paths:
        ctx.files.delete(path)
    return Response(status_code=204)


@router.post("/characters/{character_id}/images", response_model=CharacterOut, status_code=201)
async def upload_reference_images(
    character_id: int,
    files: list[UploadFile] = File(..., description="Images PNG, JPEG ou WebP"),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> CharacterOut:
    character = get_character_or_404(session, character_id)
    payloads = await read_uploads(files, ctx)

    def add(name: str, path: str, stored: StoredImage) -> None:
        character.reference_images.append(
            CharacterImage(
                path=path,
                original_name=name,
                content_type=stored.content_type,
                width=stored.width,
                height=stored.height,
            )
        )

    store_uploads(session, ctx, payloads, f"projects/{character.project_id}/characters/{character.id}", add)
    return character_out(get_character_or_404(session, character_id))


def _get_image(session: Session, character_id: int, image_id: int) -> CharacterImage:
    img = session.get(CharacterImage, image_id)
    if img is None or img.character_id != character_id:
        raise HTTPException(status_code=404, detail="Image introuvable")
    return img


@router.get("/characters/{character_id}/images/{image_id}/file")
def get_reference_image(
    character_id: int,
    image_id: int,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> FileResponse:
    img = _get_image(session, character_id, image_id)
    path = ctx.files.absolute(img.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
    return FileResponse(path, media_type=img.content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/characters/{character_id}/images/{image_id}", status_code=204)
def delete_reference_image(
    character_id: int,
    image_id: int,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    img = _get_image(session, character_id, image_id)
    path = img.path
    session.delete(img)
    session.commit()
    ctx.files.delete(path)
    return Response(status_code=204)
