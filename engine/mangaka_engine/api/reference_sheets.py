"""« Créer des références » : fiches de référence générées par ComfyUI pour la bibliothèque d'une série.

Même famille de routes pour les trois sortes (`/characters`, `/objects`, `/decors`) :
- `GET /{sorte}/{id}/reference-variants` : historique des variantes et générations en cours ;
- `POST /{sorte}/{id}/reference-variants` : génère N variantes d'un type de fiche (file ComfyUI unique),
  à partir de zéro ou d'une image de départ (`start_image_id`, une image de référence de la fiche) ;
- `PUT /{sorte}/{id}/images/order` : ordre des images de référence (la 1re est la principale).
Et par variante : `/reference-variants/{id}/file`, `/refine` (« Affiner »), `/keep` (« Garder comme
référence »), `DELETE`. Types de fiches : `GET /presets/reference-sheets`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.camera import QUALITY_TIER_LABEL, tier_allows
from ..pipeline.generation import GenerationError
from ..pipeline.reference_sheets import (
    ENTRY_KINDS,
    FOLDERS,
    MAX_KEPT,
    PEOPLE_WARNING,
    LibraryEntry,
    active_jobs,
    enqueue_angle_view,
    enqueue_sheet,
    entry_kind,
    keep_variant,
    kept_image,
    load_entry,
    sheet_for,
)
from ..presets import PresetError, PresetRegistry
from ..store.files import cache_headers, versioned_url
from ..store.models import Character, Project, ReferenceVariant
from .assets import asset_out
from .characters import character_out
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import (
    AngleViewIn,
    AssetOut,
    CameraAngleOut,
    CameraLoraOut,
    CameraLorasOut,
    CharacterOut,
    ImageAngleIn,
    ImageOrderIn,
    JobOut,
    ReferenceGenerateIn,
    ReferenceKeepIn,
    ReferenceRefineIn,
    ReferenceSheetOut,
    ReferenceStudioOut,
    ReferenceVariantOut,
)

router = APIRouter(tags=["bibliothèque"])

NOT_FOUND = {"character": "Personnage introuvable", "object": "Objet introuvable", "decor": "Décor introuvable"}


def entry_out(entry: LibraryEntry) -> CharacterOut | AssetOut:
    return character_out(entry) if isinstance(entry, Character) else asset_out(entry)


def _entry_or_404(session: Session, kind: str, entry_id: int) -> LibraryEntry:
    entry = load_entry(session, kind, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND[kind])
    return entry


def _variant_or_404(session: Session, variant_id: int) -> ReferenceVariant:
    variant = session.get(ReferenceVariant, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variante introuvable")
    return variant


def _presets(ctx: AppContext, project_id: int) -> PresetRegistry:
    return ctx.agents.presets_for(project_id)


def variant_out(variant: ReferenceVariant, entry: LibraryEntry | None) -> ReferenceVariantOut:
    params = variant.params or {}
    kept = entry is not None and kept_image(entry, variant) is not None
    check = params.get("people_check") if isinstance(params.get("people_check"), dict) else {}
    return ReferenceVariantOut(
        id=variant.id,
        entry_kind=variant.entry_kind,  # type: ignore[arg-type]
        entry_id=variant.entry_id,
        url=versioned_url(f"/reference-variants/{variant.id}/file", variant.path),
        sheet=variant.sheet,
        sheet_name=str(params.get("sheet_name") or variant.sheet),
        preset=params.get("preset"),
        tier=params.get("tier"),
        seed=variant.seed,
        width=variant.width,
        height=variant.height,
        prompt=str(params.get("prompt") or ""),
        instruction=variant.instruction,
        parent_id=variant.parent_id,
        kept=kept,
        kept_image_id=variant.kept_image_id if kept else None,
        job_id=variant.job_id,
        people_warning=PEOPLE_WARNING if check.get("detected") else None,
        people_accepted=bool(check.get("detected") and check.get("accepted")),
        params=params,
        created_at=variant.created_at,
    )


def _reference_slots(presets: PresetRegistry, series: Project | None) -> int:
    """Emplacements d'images de référence d'une case de la série (workflow « avec références »)."""
    loaded = presets.workflows.get(series.workflow_preset) if series is not None else None
    if loaded is not None and not loaded.preset.reference_images and loaded.preset.with_references:
        loaded = presets.workflows.get(loaded.preset.with_references)
    if (loaded is None or not loaded.preset.reference_images) and presets.defaults:
        fallback = presets.defaults.workflow_with_references
        loaded = presets.workflows.get(fallback) if fallback else None
    return len(loaded.preset.reference_images) if loaded is not None else 0


def _require_comfyui(ctx: AppContext) -> None:
    if ctx.providers.comfyui is None:
        detail = ctx.providers.errors.get("comfyui", "client non configuré")
        raise HTTPException(status_code=503, detail=f"ComfyUI indisponible : {detail}")


@router.get("/presets/reference-sheets", response_model=list[ReferenceSheetOut])
def list_reference_sheets(
    kind: str | None = Query(default=None, pattern="^(character|object|decor)$"), ctx: AppContext = Depends(get_ctx)
) -> list[ReferenceSheetOut]:
    """Types de fiches de référence (presets/reference_sheets/), éventuellement pour une sorte."""
    return [
        ReferenceSheetOut(
            id=s.id,
            name=s.name,
            description=s.description,
            kinds=list(s.kinds),
            width=s.width,
            height=s.height,
            workflow=s.workflow,
        )
        for s in ctx.agents.presets_for(None).reference_sheets.values()
        if kind is None or kind in s.kinds
    ]


@router.get("/presets/camera-loras", response_model=CameraLorasOut)
def get_camera_loras(ctx: AppContext = Depends(get_ctx)) -> CameraLorasOut:
    """LoRA Multiple-Angles et Cohérence anime (presets/camera_loras.yaml) : fichiers, mots déclencheurs, poids,
    paliers où ils s'appliquent, vocabulaire de caméra des listes « Nouvel angle » et « Changer l'angle »."""
    presets = ctx.agents.presets_for(None)
    catalog = presets.camera_loras
    loaded = presets.workflows.get(catalog.workflow) if catalog.workflow else None
    default = catalog.default_angle_lora
    if loaded is None:
        problem: str | None = "aucun workflow d'angle configuré (workflow de presets/camera_loras.yaml)"
    elif default is None:
        problem = "aucun LoRA Multiple-Angles dans presets/camera_loras.yaml"
    elif not catalog.angles:
        problem = "aucun angle de caméra dans presets/camera_loras.yaml"
    elif not tier_allows(default, loaded):
        problem = QUALITY_TIER_LABEL
    else:
        problem = None
    return CameraLorasOut(
        workflow=catalog.workflow,
        workflow_tier=loaded.preset.tier.name if loaded is not None and loaded.preset.tier else None,
        angle_problem=problem,
        loras=[
            CameraLoraOut(
                id=lo.id,
                role=lo.role,
                name=lo.name,
                description=lo.description,
                file=lo.file,
                trigger=lo.trigger,
                weight=lo.weight,
                tiers=list(lo.tiers),
                default=lo is default,
                workflows=[w for w, wf in presets.workflows.items() if tier_allows(lo, wf)],
            )
            for lo in catalog.loras
        ],
        angles=[
            CameraAngleOut(id=a.id, label=a.label, camera=a.camera, azimuth=a.azimuth, elevation=a.elevation)
            for a in catalog.angles
        ],
        main_view=catalog.main_view,
        weight_hint=" ".join(catalog.weight_hint.split()),
        tier_label=QUALITY_TIER_LABEL,
    )


def _routes(kind: str) -> APIRouter:
    segment = FOLDERS[kind]
    sub = APIRouter(tags=["bibliothèque"])

    @sub.get(
        f"/{segment}/{{entry_id}}/reference-variants", response_model=ReferenceStudioOut, name=f"{segment}_variants"
    )
    def list_variants(
        entry_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
    ) -> ReferenceStudioOut:
        entry = _entry_or_404(session, kind, entry_id)
        rows = session.scalars(
            select(ReferenceVariant)
            .where(ReferenceVariant.entry_kind == kind, ReferenceVariant.entry_id == entry.id)
            .order_by(ReferenceVariant.id.desc())
        ).all()
        return ReferenceStudioOut(
            variants=[variant_out(v, entry) for v in rows],
            active_jobs=[job_out(j) for j in active_jobs(session, kind, entry.id, entry.project_id)],
            max_kept=MAX_KEPT,
            kept_count=len(entry.reference_images),
            reference_slots=_reference_slots(_presets(ctx, entry.project_id), session.get(Project, entry.project_id)),
        )

    @sub.post(
        f"/{segment}/{{entry_id}}/reference-variants",
        response_model=list[JobOut],
        status_code=202,
        name=f"{segment}_generate_references",
    )
    def generate(
        entry_id: int,
        body: ReferenceGenerateIn,
        session: Session = Depends(get_session),
        ctx: AppContext = Depends(get_ctx),
    ) -> list[JobOut]:
        """Met en file `count` variantes (1–4, 4 par défaut) du type de fiche ; progression : /jobs/{id}/events."""
        _require_comfyui(ctx)
        entry = _entry_or_404(session, kind, entry_id)
        start = None
        if body.start_image_id is not None:
            start = next((img for img in entry.reference_images if img.id == body.start_image_id), None)
            if start is None:
                raise FieldError(
                    "start_image_id", "image de départ introuvable parmi les images de référence de la fiche"
                )
        try:
            jobs = enqueue_sheet(
                session,
                _presets(ctx, entry.project_id),
                entry,
                body.sheet,
                count=body.count,
                quality=body.quality,
                seed=body.seed,
                start=start,
            )
        except (PresetError, GenerationError) as exc:
            raise FieldError("sheet", str(exc)) from None
        session.commit()
        ctx.generation.notify()
        return [job_out(j) for j in jobs]

    @sub.post(
        f"/{segment}/{{entry_id}}/angle-views",
        response_model=list[JobOut],
        status_code=202,
        name=f"{segment}_angle_view",
    )
    def new_angle(
        entry_id: int,
        body: AngleViewIn,
        session: Session = Depends(get_session),
        ctx: AppContext = Depends(get_ctx),
    ) -> list[JobOut]:
        """« Nouvel angle » : une nouvelle vue de la fiche sous l'angle choisi (LoRA Multiple-Angles, palier Qualité),
        candidate de l'historique : « Valider » (`/keep`) la range parmi ses images de référence, étiquetée par son
        angle ; progression : /jobs/{id}/events."""
        _require_comfyui(ctx)
        entry = _entry_or_404(session, kind, entry_id)
        start = None
        if body.start_image_id is not None:
            start = next((img for img in entry.reference_images if img.id == body.start_image_id), None)
            if start is None:
                raise FieldError(
                    "start_image_id", "vue de départ introuvable parmi les images de référence de la fiche"
                )
        try:
            job = enqueue_angle_view(
                session,
                _presets(ctx, entry.project_id),
                entry,
                body.angle,
                start=start,
                lora_id=body.lora,
                weight=body.weight,
                seed=body.seed,
            )
        except (PresetError, GenerationError) as exc:
            raise FieldError("angle", str(exc)) from None
        session.commit()
        ctx.generation.notify()
        return [job_out(job)]

    @sub.put(
        f"/{segment}/{{entry_id}}/images/{{image_id}}/angle",
        response_model=AssetOut | CharacterOut,
        name=f"{segment}_image_angle",
    )
    def set_image_angle(
        entry_id: int,
        image_id: int,
        body: ImageAngleIn,
        session: Session = Depends(get_session),
        ctx: AppContext = Depends(get_ctx),
    ) -> CharacterOut | AssetOut:
        """Étiquette (ou retire) l'angle de caméra d'une vue : sert au choix de la vue la plus proche pour une case."""
        entry = _entry_or_404(session, kind, entry_id)
        image = next((img for img in entry.reference_images if img.id == image_id), None)
        if image is None:
            raise HTTPException(status_code=404, detail="Image de référence introuvable")
        if body.angle is not None and _presets(ctx, entry.project_id).camera_loras.angle(body.angle) is None:
            raise FieldError("angle", f"angle de caméra inconnu : « {body.angle} » (presets/camera_loras.yaml)")
        image.angle = body.angle
        session.commit()
        return entry_out(entry)

    @sub.put(
        f"/{segment}/{{entry_id}}/images/order",
        response_model=AssetOut | CharacterOut,
        name=f"{segment}_reorder_images",
    )
    def reorder_images(
        entry_id: int, body: ImageOrderIn, session: Session = Depends(get_session)
    ) -> CharacterOut | AssetOut:
        """Range les images de référence ; la première est la principale (servie en premier aux cases)."""
        entry = _entry_or_404(session, kind, entry_id)
        images = {img.id: img for img in entry.reference_images}
        if sorted(body.image_ids) != sorted(images):
            raise FieldError("image_ids", "donne chaque image de référence de la fiche une fois, dans l'ordre voulu")
        for position, image_id in enumerate(body.image_ids):
            images[image_id].position = position
        session.commit()
        session.expire(entry, ["reference_images"])  # relue dans le nouvel ordre
        return entry_out(entry)

    return sub


for _kind in ENTRY_KINDS:
    router.include_router(_routes(_kind))


@router.get("/reference-variants/{variant_id}/file")
def get_variant_file(
    variant_id: int, v: str | None = None, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    variant = _variant_or_404(session, variant_id)
    path = ctx.files.absolute(variant.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
    return FileResponse(path, media_type=variant.content_type, headers=cache_headers(variant.path, v))


@router.post("/reference-variants/{variant_id}/refine", response_model=list[JobOut], status_code=202)
def refine_variant(
    variant_id: int,
    body: ReferenceRefineIn,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> list[JobOut]:
    """« Affiner » : régénère depuis cette variante, envoyée comme image de référence, avec une consigne."""
    _require_comfyui(ctx)
    variant = _variant_or_404(session, variant_id)
    entry = _entry_or_404(session, variant.entry_kind, variant.entry_id)
    presets = _presets(ctx, entry.project_id)
    if body.sheet:
        try:
            sheet_for(presets, entry, body.sheet)
        except (PresetError, GenerationError) as exc:
            raise FieldError("sheet", str(exc)) from None
    try:
        jobs = enqueue_sheet(
            session,
            presets,
            entry,
            body.sheet or variant.sheet,
            count=body.count,
            quality=body.quality,
            parent=variant,
            instruction=body.instruction,
        )
    except (PresetError, GenerationError) as exc:
        raise FieldError("instruction", str(exc)) from None
    session.commit()
    ctx.generation.notify()
    return [job_out(j) for j in jobs]


@router.post("/reference-variants/{variant_id}/keep", response_model=AssetOut | CharacterOut, status_code=201)
def keep(
    variant_id: int,
    body: ReferenceKeepIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> CharacterOut | AssetOut:
    """« Garder comme référence » : copie la variante parmi les images de référence de la fiche (à la fin).
    Personnage détecté dans une fiche d'objet ou de décor : 409, sauf `accept_people` (« Garder quand même »)."""
    variant = _variant_or_404(session, variant_id)
    entry = _entry_or_404(session, variant.entry_kind, variant.entry_id)
    try:
        keep_variant(session, ctx.files, entry, variant, accept_people=body is not None and body.accept_people)
    except GenerationError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=_capitalize(str(exc))) from None
    session.commit()
    return entry_out(_entry_or_404(session, entry_kind(entry), entry.id))


@router.delete("/reference-variants/{variant_id}", status_code=204)
def delete_variant(
    variant_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    """Retire une variante de l'historique ; une image déjà gardée comme référence reste (c'est une copie)."""
    variant = _variant_or_404(session, variant_id)
    path = variant.path
    session.delete(variant)
    session.commit()
    ctx.files.delete(path)
    return Response(status_code=204)


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]
