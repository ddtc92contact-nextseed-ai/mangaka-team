"""Étape 3 : génération des cases (file ComfyUI unique), versions d'image, file d'attente."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..pipeline.comfy_trial import STEP as TRIAL_STEP
from ..pipeline.estimate import Estimate, estimate_panels, remaining_panels
from ..pipeline.generation import (
    ACTIVE,
    QC_STEP,
    STEP,
    GenerationError,
    LibraryEntry,
    enqueue_panel,
    entry_kind,
    panel_cast,
    panel_label,
    panel_target,
    panels_to_generate,
    preset_tier,
    quality_preset_id,
    refresh_states,
    resolve_preset_id,
    update_panel_prompt,
)
from ..pipeline.inpaint import MaskError, Region, decode_png
from ..pipeline.qc_bench import STEP as BENCH_STEP
from ..pipeline.reference_sheets import KIND_LABELS
from ..pipeline.reference_sheets import STEP as REFERENCE_STEP
from ..pipeline.repair import concerned_character, default_repair_prompt, enqueue_repair, repair_context
from ..pipeline.sketch import validated_sketch
from ..presets import PresetError, PresetRegistry
from ..store.models import (
    Chapter,
    ImageKind,
    Job,
    JobStatus,
    Page,
    Panel,
    PanelImage,
    PanelImageAnnotation,
    Project,
)
from .chapters import get_chapter_or_404, get_page_or_404
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .schemas import (
    AnnotationOut,
    BatchGenerateIn,
    BatchGenerateOut,
    EstimateOut,
    GenerateIn,
    JobOut,
    LibraryRef,
    PanelDetailOut,
    PanelImageOut,
    PanelUpdate,
    PresetEstimateOut,
    QueueItemOut,
    QueueOut,
    RepairCharacterOut,
    RepairIn,
    RepairInfoOut,
    RepairTarget,
    WorkflowPresetOut,
)

router = APIRouter(tags=["génération"])

MEDIAN_SAMPLE = 20


# --- sorties --------------------------------------------------------------------------
def image_url(img: PanelImage) -> str:
    return f"/panel-images/{img.id}/file"


def panel_image_out(img: PanelImage, presets: PresetRegistry | None = None) -> PanelImageOut:
    """`presets` : palier des versions antérieures aux paliers (déduit de leur preset)."""
    params = img.params or {}
    preset = params.get("preset")
    tier = params.get("tier")
    if tier is None and presets is not None and isinstance(preset, str):
        tier = preset_tier(presets, preset)
    return PanelImageOut(
        id=img.id,
        panel_id=img.panel_id,
        version=img.version,
        kind=img.kind.value,
        url=image_url(img),
        seed=img.seed,
        selected=img.selected,
        width=params.get("image_width"),
        height=params.get("image_height"),
        preset=preset,
        tier=tier,
        params=params,
        qc_score=img.qc_score,
        qc_reasons=list(img.qc_reasons or []),
        qc_verdict=img.qc_verdict.value if img.qc_verdict else None,
        qc=dict(img.qc_details or {}),
        detections=img.detections,
        annotation=annotation_out(img.annotation),
        created_at=img.created_at,
    )


def annotation_out(ann: PanelImageAnnotation | None) -> AnnotationOut | None:
    if ann is None:
        return None
    return AnnotationOut(
        label=ann.label.value,
        defects=list(ann.defects or []),
        note=ann.note,
        updated_at=ann.updated_at.replace(tzinfo=ann.updated_at.tzinfo or UTC),
    )


def get_panel_or_404(session: Session, panel_id: int) -> Panel:
    panel = session.get(Panel, panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Case introuvable")
    return panel


def _get_image_or_404(session: Session, image_id: int) -> PanelImage:
    img = session.get(PanelImage, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="Version introuvable")
    return img


def _active_jobs(session: Session, panel_id: int) -> list[Job]:
    """Générations et contrôles qualité en cours ou en attente pour la case."""
    return list(
        session.scalars(
            select(Job)
            .where(Job.panel_id == panel_id, Job.step.in_([STEP, QC_STEP]), Job.status.in_(ACTIVE))
            .order_by(Job.id)
        )
    )


def panel_detail(session: Session, ctx: AppContext, panel: Panel) -> PanelDetailOut:
    page = panel.page
    cast = panel_cast(session, panel)
    presets = _presets(ctx, panel)
    resolved = resolve_preset_id(presets, panel, cast.entries)
    return PanelDetailOut(
        id=panel.id,
        page_id=page.id,
        page_number=page.number,
        chapter_id=page.chapter_id,
        project_id=page.chapter.project_id,
        index=panel.index,
        label=panel_label(panel),
        description=panel.description,
        characters=list(panel.character_names or []),
        character_ids=list(panel.character_ids or []),
        decor=_ref(cast.decor) if cast.decor is not None else None,
        objets=[_ref(o) for o in cast.objects],
        shot_type=panel.shot_type,
        state=panel.state.value,
        bbox=panel.bbox,
        final_prompt=panel.final_prompt,
        final_prompt_manual=panel.final_prompt_manual,
        generation_preset=panel.generation_preset,
        resolved_preset=resolved if resolved in presets.workflows else None,
        target=panel_target(presets, page, panel),
        images=[panel_image_out(i, presets) for i in panel.images],
        active_jobs=[job_out(j) for j in _active_jobs(session, panel.id)],
        sketch_image_id=sketch.id if (sketch := validated_sketch(panel)) else None,
        sketch_denoise=panel.sketch_denoise,
    )


def _ref(entry: LibraryEntry) -> LibraryRef:
    return LibraryRef(id=entry.id, kind=entry_kind(entry), name=entry.name)  # type: ignore[arg-type]


def _presets(ctx: AppContext, panel: Panel) -> PresetRegistry:
    """Presets de la série de la case, avec les réglages du dessinateur (écran « L'équipe »)."""
    return ctx.agents.presets_for(panel.page.chapter.project_id)


def _require_comfyui(ctx: AppContext) -> None:
    if ctx.providers.comfyui is None:
        detail = ctx.providers.errors.get("comfyui", "client non configuré")
        raise HTTPException(status_code=503, detail=f"ComfyUI indisponible : {detail}")


def _enqueue(session: Session, ctx: AppContext, panel: Panel, **kwargs: object) -> list[Job]:
    try:
        return enqueue_panel(session, _presets(ctx, panel), panel, knowledge=ctx.knowledge, **kwargs)  # type: ignore[arg-type]
    except PresetError as exc:
        raise FieldError("preset", str(exc)) from None
    except GenerationError as exc:
        raise FieldError("panel", f"case {panel.index + 1} de la page {panel.page.number} : {exc}") from None


# --- cases ------------------------------------------------------------------------------
@router.get("/panels/{panel_id}", response_model=PanelDetailOut)
def get_panel(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDetailOut:
    return panel_detail(session, ctx, get_panel_or_404(session, panel_id))


@router.patch("/panels/{panel_id}", response_model=PanelDetailOut)
def update_panel(
    panel_id: int, body: PanelUpdate, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDetailOut:
    """Édite le prompt final (conservé tel quel ensuite), la description, le débruitage du passage au
    propre et/ou impose un workflow à la case."""
    panel = get_panel_or_404(session, panel_id)
    changes = body.model_dump(exclude_unset=True)
    if "sketch_denoise" in changes:
        panel.sketch_denoise = changes["sketch_denoise"]
    if "description" in changes:
        if changes["description"] is None:
            raise FieldError("description", "ne peut pas être vide")
        panel.description = changes["description"]
        update_panel_prompt(_presets(ctx, panel), session, panel, ctx.knowledge)
    if "generation_preset" in changes:
        preset = changes["generation_preset"]
        known = _presets(ctx, panel).workflows
        if preset is not None and preset not in known:
            raise FieldError("generation_preset", f"workflow inconnu : « {preset} »")
        if preset is not None and known[preset].preset.inpaint is not None:
            raise FieldError(
                "generation_preset", f"« {preset} » est un preset de réparation : il ne génère pas de case"
            )
        panel.generation_preset = preset
    if "final_prompt" in changes:
        text = (changes["final_prompt"] or "").strip()
        panel.final_prompt = text or None
        panel.final_prompt_manual = bool(text)
        update_panel_prompt(_presets(ctx, panel), session, panel, ctx.knowledge)
    session.commit()
    return panel_detail(session, ctx, panel)


@router.post("/panels/{panel_id}/prompt/rebuild", response_model=PanelDetailOut)
def rebuild_prompt(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PanelDetailOut:
    """Abandonne l'édition manuelle et reconstruit le prompt final depuis la case et les fiches."""
    panel = get_panel_or_404(session, panel_id)
    panel.final_prompt_manual = False
    update_panel_prompt(_presets(ctx, panel), session, panel, ctx.knowledge)
    session.commit()
    return panel_detail(session, ctx, panel)


@router.post("/panels/{panel_id}/regenerate-quality", response_model=list[JobOut], status_code=202)
def regenerate_panel_quality(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[JobOut]:
    """« Régénérer en Qualité » : une nouvelle version de cette case seulement, avec le palier Qualité
    (avec références si un personnage de la case en a), même prompt, nouvelle seed. Les autres
    versions (et la version choisie) ne bougent pas."""
    _require_comfyui(ctx)
    panel = get_panel_or_404(session, panel_id)
    try:
        preset = quality_preset_id(_presets(ctx, panel), panel_cast(session, panel).entries)
    except GenerationError as exc:
        raise FieldError("preset", str(exc)) from None
    jobs = _enqueue(session, ctx, panel, count=1, preset=preset, extra_params={"regenerate": "quality"})
    session.commit()
    ctx.generation.notify()
    return [job_out(j) for j in jobs]


@router.post("/panels/{panel_id}/generate", response_model=list[JobOut], status_code=202)
def generate_panel(
    panel_id: int,
    body: GenerateIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> list[JobOut]:
    """Met en file `count` variantes (1–4) de la case ; progression via GET /jobs/{id}/events."""
    body = body or GenerateIn()
    _require_comfyui(ctx)
    panel = get_panel_or_404(session, panel_id)
    jobs = _enqueue(
        session, ctx, panel, count=body.count, seed=body.seed, preset=body.preset, prompt_override=body.prompt_override
    )
    session.commit()
    ctx.generation.notify()
    return [job_out(j) for j in jobs]


def _generate_pages(session: Session, ctx: AppContext, pages: list[Page], body: BatchGenerateIn) -> BatchGenerateOut:
    _require_comfyui(ctx)
    total = sum(len(p.panels) for p in pages)
    panels = panels_to_generate(session, pages, force=body.force)
    jobs: list[Job] = []
    for panel in panels:
        jobs += _enqueue(session, ctx, panel, count=body.count, preset=body.preset)
    session.commit()
    ctx.generation.notify()
    return BatchGenerateOut(
        jobs=[job_out(j) for j in jobs], panel_ids=[p.id for p in panels], skipped=total - len(panels)
    )


@router.post("/pages/{page_id}/generate", response_model=BatchGenerateOut, status_code=202)
def generate_page(
    page_id: int,
    body: BatchGenerateIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> BatchGenerateOut:
    """Génère les cases de la page sans version choisie (toutes avec `force`) ; ignore celles déjà en file."""
    page = get_page_or_404(session, page_id)
    return _generate_pages(session, ctx, [page], body or BatchGenerateIn())


@router.post("/chapters/{chapter_id}/generate", response_model=BatchGenerateOut, status_code=202)
def generate_chapter(
    chapter_id: int,
    body: BatchGenerateIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> BatchGenerateOut:
    """Génère les cases du chapitre sans version choisie (toutes avec `force`), page par page."""
    get_chapter_or_404(session, chapter_id)
    pages = list(
        session.scalars(
            select(Page).where(Page.chapter_id == chapter_id).options(selectinload(Page.panels)).order_by(Page.number)
        )
    )
    return _generate_pages(session, ctx, pages, body or BatchGenerateIn())


# --- réparation ciblée -----------------------------------------------------------------
@router.get("/panel-images/{image_id}/repair", response_model=RepairInfoOut)
def get_repair_info(
    image_id: int,
    target: RepairTarget = "zone",
    character_id: int | None = None,
    auto_character: bool = True,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> RepairInfoOut:
    """Préremplit « Réparer » : preset de réparation du palier, marge, adoucissement, denoise et prompt
    (description de la case + personnage concerné : mots-clés, mots déclencheurs de son LoRA)."""
    img = _get_image_or_404(session, image_id)
    presets = _presets(ctx, img.panel)
    try:
        rctx = repair_context(session, presets, img)
    except (GenerationError, PresetError) as exc:
        return RepairInfoOut(available=False, problem=str(exc)[:1].upper() + str(exc)[1:], target=target)
    characters = [RepairCharacterOut(id=c.id, name=c.name) for c in rctx.characters]
    # Sans choix explicite (`auto_character`) : le seul personnage de la case est celui concerné.
    if character_id is None and auto_character and len(rctx.characters) == 1:
        character_id = rctx.characters[0].id
    try:
        character = concerned_character(rctx, character_id)
    except GenerationError as exc:
        raise FieldError("character_id", str(exc)) from None
    preset = rctx.loaded.preset
    return RepairInfoOut(
        available=True,
        preset=preset.id,
        preset_name=preset.name,
        tier=preset.tier.name if preset.tier else None,
        grow_px=rctx.settings.grow_px,
        feather_px=rctx.settings.feather_px,
        denoise=float(preset.defaults.get("denoise", 0.45)),
        target=target,
        character_id=character.id if character is not None else None,
        characters=characters,
        prompt=default_repair_prompt(presets, rctx, img, target, character),
    )


@router.post("/panel-images/{image_id}/repair", response_model=list[JobOut], status_code=202)
def repair_panel_image(
    image_id: int, body: RepairIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[JobOut]:
    """« Réparer » : repeint seulement la zone choisie de cette version (inpainting), via la file
    ComfyUI. Le résultat est une nouvelle version liée à sa source (`params.repair`), contrôlée par le QC ;
    la version choisie ne change pas."""
    _require_comfyui(ctx)
    img = _get_image_or_404(session, image_id)
    try:
        painted = decode_png(body.mask_png) if body.mask_png else None
    except MaskError as exc:
        raise FieldError("mask_png", str(exc)) from None
    try:
        job = enqueue_repair(
            session,
            _presets(ctx, img.panel),
            ctx.files,
            img,
            regions=[Region(r.x1, r.y1, r.x2, r.y2) for r in body.regions],
            painted=painted,
            target=body.target,
            character_id=body.character_id,
            prompt=body.prompt,
            grow_px=body.grow_px,
            feather_px=body.feather_px,
            denoise=body.denoise,
            seed=body.seed,
        )
    except PresetError as exc:
        raise FieldError("preset", str(exc)) from None
    except GenerationError as exc:
        raise FieldError("repair", str(exc)[:1].upper() + str(exc)[1:]) from None
    session.commit()
    ctx.generation.notify()
    return [job_out(job)]


# --- versions ---------------------------------------------------------------------------
@router.get("/panels/{panel_id}/images", response_model=list[PanelImageOut])
def list_panel_images(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[PanelImageOut]:
    panel = get_panel_or_404(session, panel_id)
    return [panel_image_out(i, _presets(ctx, panel)) for i in panel.images]


@router.get("/panel-images/{image_id}/file")
def get_panel_image_file(
    image_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> FileResponse:
    img = _get_image_or_404(session, image_id)
    path = ctx.files.absolute(img.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier image manquant dans data/")
    media_type = (img.params or {}).get("content_type") or {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.post("/panel-images/{image_id}/select", response_model=list[PanelImageOut])
def select_panel_image(
    image_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[PanelImageOut]:
    """Choisit cette version pour la case (une seule version choisie par case ; jamais un croquis)."""
    img = _get_image_or_404(session, image_id)
    if img.kind == ImageKind.croquis:
        raise FieldError("image_id", "un croquis ne peut pas être choisi : valide-le puis « Passer au propre »")
    panel = img.panel
    for other in panel.images:
        other.selected = other.id == img.id
    session.flush()
    refresh_states(session, [panel.id])  # l'état de la case suit le verdict QC de la version choisie
    session.commit()
    return [panel_image_out(i, _presets(ctx, panel)) for i in panel.images]


@router.delete("/panel-images/{image_id}", status_code=204)
def delete_panel_image(
    image_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    """Supprime une version (et son fichier). Si c'était la version choisie, aucune ne l'est plus."""
    img = _get_image_or_404(session, image_id)
    panel_id, path = img.panel_id, img.path
    if img.panel.sketch_image_id == img.id:
        img.panel.sketch_image_id = None  # croquis validé supprimé : la case est à trier de nouveau
    mask = ((img.params or {}).get("repair") or {}).get("mask_path")
    session.delete(img)
    session.flush()
    refresh_states(session, [panel_id])
    session.commit()
    ctx.files.delete(path)
    if isinstance(mask, str) and mask:
        ctx.files.delete(mask)
    return Response(status_code=204)


# --- temps estimé -----------------------------------------------------------------------
def _estimate_out(est: Estimate) -> EstimateOut:
    return EstimateOut(
        remaining_panels=est.remaining_panels,
        total_s=round(est.total_s, 1) if est.total_s is not None else None,
        measured=est.measured,
        by_preset=[
            PresetEstimateOut(
                preset=p.preset,
                tier=p.tier,
                panels=p.panels,
                per_panel_s=round(p.per_panel_s, 1) if p.per_panel_s is not None else None,
                measured=p.measured,
                samples=p.samples,
            )
            for p in est.by_preset
        ],
    )


def _pages_of(session: Session, *conditions: object) -> list[Page]:
    return list(session.scalars(select(Page).where(*conditions).options(selectinload(Page.panels))))  # type: ignore[arg-type]


@router.get("/chapters/{chapter_id}/estimate", response_model=EstimateOut)
def chapter_estimate(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> EstimateOut:
    """Temps estimé des cases du chapitre encore à générer (sans version choisie)."""
    get_chapter_or_404(session, chapter_id)
    panels = remaining_panels(session, _pages_of(session, Page.chapter_id == chapter_id))
    return _estimate_out(estimate_panels(session, ctx.agents.presets_for, panels))


@router.get("/projects/{project_id}/estimate", response_model=EstimateOut)
def project_estimate(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> EstimateOut:
    """Temps estimé de toutes les cases de la série encore à générer."""
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    chapter_ids = select(Chapter.id).where(Chapter.project_id == project_id)
    panels = remaining_panels(session, _pages_of(session, Page.chapter_id.in_(chapter_ids)))
    return _estimate_out(estimate_panels(session, ctx.agents.presets_for, panels))


# --- file d'attente ---------------------------------------------------------------------
def _median_durations(session: Session) -> tuple[dict[str, float], float | None, float | None]:
    """Médianes des durées réussies : par preset et toutes générations confondues, puis des contrôles QC."""
    rows = session.execute(
        select(Job.step, Job.params, Job.duration_ms)
        .where(Job.step.in_([STEP, QC_STEP]), Job.status == JobStatus.succeeded, Job.duration_ms.is_not(None))
        .order_by(Job.id.desc())
        .limit(500)
    ).all()
    by_preset: dict[str, list[float]] = {}
    overall: list[float] = []
    qc: list[float] = []
    for step, params, duration_ms in rows:
        seconds = duration_ms / 1000
        if step == QC_STEP:
            n = len((params or {}).get("image_ids") or []) or 1
            if len(qc) < MEDIAN_SAMPLE:
                qc.append(seconds / n)
            continue
        preset = (params or {}).get("preset")
        if isinstance(preset, str) and len(by_preset.setdefault(preset, [])) < MEDIAN_SAMPLE:
            by_preset[preset].append(seconds)
        if len(overall) < MEDIAN_SAMPLE:
            overall.append(seconds)
    medians = {k: statistics.median(v) for k, v in by_preset.items() if v}
    return (
        medians,
        statistics.median(overall) if overall else None,
        statistics.median(qc) if qc else None,
    )


def _elapsed_s(started: datetime | None) -> float:
    if started is None:
        return 0.0
    now = datetime.now(UTC)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0.0, (now - started).total_seconds())


@router.get("/queue", response_model=QueueOut)
def get_queue(session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)) -> QueueOut:
    """Générations et contrôles qualité en cours et en attente (ordre d'exécution), avec une estimation
    du temps restant. Les deux étapes partagent la même file : un seul job à la fois."""
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.step.in_([STEP, QC_STEP, BENCH_STEP, TRIAL_STEP, REFERENCE_STEP]), Job.status.in_(ACTIVE))
            .order_by((Job.status == JobStatus.running).desc(), Job.id)
        )
    )
    medians, overall, qc_median = _median_durations(session)
    items: list[QueueItemOut] = []
    cumulative: float | None = 0.0
    for position, job in enumerate(jobs, start=0 if jobs and jobs[0].status == JobStatus.running else 1):
        params = job.params or {}
        preset = params.get("preset")
        is_qc = job.step in (QC_STEP, BENCH_STEP)
        if job.step == BENCH_STEP:
            n_cases = int(params.get("sample_count") or 1)
            estimate = qc_median * n_cases if qc_median is not None else None
        elif is_qc:
            estimate = qc_median * (len(params.get("image_ids") or []) or 1) if qc_median is not None else None
        else:
            estimate = medians.get(preset, overall) if isinstance(preset, str) else overall
        if estimate is None or cumulative is None:
            cumulative = None
        else:
            remaining = estimate
            if job.status == JobStatus.running:
                remaining = max(0.0, estimate - _elapsed_s(job.started_at))
            cumulative += remaining
        panel = session.get(Panel, job.panel_id) if job.panel_id is not None else None
        page = panel.page if panel else None
        chapter = page.chapter if page else (session.get(Chapter, job.chapter_id) if job.chapter_id else None)
        if panel:
            label = panel_label(panel)
        elif chapter:
            label = f"{chapter.project.title} · ch. {chapter.number}"
        else:
            label = f"Job {job.id}"
        series = chapter.project if chapter else (session.get(Project, job.project_id) if job.project_id else None)
        if job.step == REFERENCE_STEP:
            kind = KIND_LABELS.get(str(params.get("entry_kind")), "fiche")
            action = "Affiner" if params.get("parent_id") is not None else "Références"
            label = f"{action} · {params.get('entry_name') or kind} ({kind}) · {params.get('sheet_name') or ''}"
            if series is not None:
                label = f"{series.title} · {label}"
        elif job.step == TRIAL_STEP:
            label = f"Case d'essai ComfyUI · {params.get('preset_name') or preset}"
        elif job.step == BENCH_STEP:
            n = int(params.get("sample_count") or 0)
            label = f"Banc d'essai QC · {params.get('scope') or 'toutes les séries'} ({n} case{'s' if n > 1 else ''})"
        elif is_qc:
            n = len(params.get("image_ids") or [])
            label = f"Contrôle qualité · {label}" + (f" ({n} cases)" if not panel and n > 1 else "")
        items.append(
            QueueItemOut(
                job=job_out(job),
                position=position,
                label=label,
                panel_id=panel.id if panel else None,
                panel_index=panel.index if panel else None,
                page_id=page.id if page else None,
                page_number=page.number if page else None,
                chapter_id=chapter.id if chapter else None,
                chapter_number=chapter.number if chapter else None,
                chapter_title=chapter.title if chapter else None,
                project_id=series.id if series else None,
                series_title=series.title if series else None,
                preset=preset if isinstance(preset, str) and not is_qc else None,
                tier=(
                    preset_tier(ctx.agents.presets_for(chapter.project_id if chapter else None), preset)
                    if isinstance(preset, str) and not is_qc
                    else None
                ),
                variant=params.get("variant"),
                count=params.get("count"),
                estimated_duration_s=round(estimate, 1) if estimate is not None else None,
                eta_s=round(cumulative, 1) if cumulative is not None else None,
            )
        )
    running = items[0] if items and items[0].job.status == "running" else None
    pending = items[1:] if running else items
    return QueueOut(
        running=running,
        pending=pending,
        total_eta_s=items[-1].eta_s if items else 0.0,
        comfyui=ctx.providers.names.get("comfyui"),
    )


# --- presets ----------------------------------------------------------------------------
@router.get("/presets/workflows", response_model=list[WorkflowPresetOut])
def list_workflow_presets(ctx: AppContext = Depends(get_ctx)) -> list[WorkflowPresetOut]:
    presets = ctx.agents.presets_for(None)
    defaults = presets.defaults
    return [
        WorkflowPresetOut(
            id=w.preset.id,
            name=w.preset.name,
            description=w.preset.description,
            params=sorted(w.preset.mapping),
            reference_slots=len(w.preset.reference_images),
            supports_lora=w.preset.lora_chain is not None,
            lora_loader=w.preset.lora_chain.class_type if w.preset.lora_chain else None,
            timeout_s=w.preset.timeout_s,
            is_default=bool(defaults and defaults.workflow == w.preset.id),
            is_reference_default=bool(defaults and defaults.workflow_with_references == w.preset.id),
            with_references=w.preset.with_references,
            has_trial=bool(w.preset.trial),
            tier=w.preset.tier.name if w.preset.tier else None,
            tier_choice=w.preset.tier.choice if w.preset.tier else None,
            tier_order=w.preset.tier.order if w.preset.tier else None,
            estimated_s=w.preset.estimated_s,
            is_quality=bool(defaults and defaults.workflow_quality == w.preset.id),
            role=w.preset.role,
            from_sketch=w.preset.from_sketch,
            is_sketch=bool(defaults and defaults.workflow_sketch == w.preset.id),
        )
        for w in presets.workflows.values()
        if w.preset.inpaint is None  # presets de réparation : jamais proposés pour générer une case
    ]
