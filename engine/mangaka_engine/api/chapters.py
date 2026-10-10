"""Chapitres d'une série, leur découpage (pages → cases → bulles) et leur mise en page."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..pipeline.knowledge import record_chapter_summary
from ..pipeline.layout import LayoutError
from ..pipeline.library import SeriesLibrary
from ..pipeline.pages import (
    FRAME_KEYS,
    apply_frame_change,
    frame_override,
    is_stale,
    layout_page,
    move_page_gutter,
    regeneration_advised,
    slant_page_cut,
)
from ..pipeline.script import normalize_shot_type, script_job
from ..pipeline.sketch import cleaned_from, latest_sketch, validated_sketch
from ..presets import PresetError
from ..store.models import (
    Bubble,
    BubbleKind,
    Chapter,
    ChapterStatus,
    Character,
    ImageKind,
    Job,
    JobStatus,
    Page,
    PageKind,
    Panel,
)
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .jobs import job_out
from .projects import get_project_or_404
from .schemas import (
    BreakdownIn,
    BubbleOut,
    ChapterCreate,
    ChapterOut,
    ChapterReorder,
    ChapterUpdate,
    CutSlant,
    GutterMove,
    JobOut,
    PageLayoutIn,
    PageOut,
    PanelFrameIn,
    PanelOut,
    SfxOut,
)

router = APIRouter(tags=["chapitres"])


# --- sorties --------------------------------------------------------------------
def _page_counts(session: Session, chapter_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not chapter_ids:
        return {}
    rows = session.execute(
        select(Page.chapter_id, func.count(func.distinct(Page.id)), func.count(Panel.id))
        .outerjoin(Panel, Panel.page_id == Page.id)
        .where(Page.chapter_id.in_(chapter_ids))
        .group_by(Page.chapter_id)
    ).all()
    return {cid: (pages, panels) for cid, pages, panels in rows}


def chapter_out(chapter: Chapter, counts: tuple[int, int] = (0, 0)) -> ChapterOut:
    return ChapterOut(
        id=chapter.id,
        project_id=chapter.project_id,
        series_title=chapter.project.title,
        number=chapter.number,
        title=chapter.title,
        synopsis=chapter.synopsis,
        summary=chapter.summary,
        target_page_count=chapter.target_page_count,
        status=chapter.status.value,
        planned_date=chapter.planned_date,
        page_count=counts[0],
        panel_count=counts[1],
        created_at=chapter.created_at,
        updated_at=chapter.updated_at,
    )


def _one_out(session: Session, chapter: Chapter) -> ChapterOut:
    return chapter_out(chapter, _page_counts(session, [chapter.id]).get(chapter.id, (0, 0)))


def _sketch_fields(panel: Panel) -> dict[str, Any]:
    """Palier croquis : croquis montré (validé, sinon le plus récent), validation, propre déjà tiré."""
    validated = validated_sketch(panel)
    shown = validated or latest_sketch(panel)
    return {
        "sketch_count": sum(1 for i in panel.images if i.kind == ImageKind.croquis),
        "sketch_image_id": shown.id if shown else None,
        "sketch_image_url": f"/panel-images/{shown.id}/file" if shown else None,
        "sketch_validated": validated is not None,
        "sketch_denoise": panel.sketch_denoise,
        "sketch_cleaned": validated is not None and cleaned_from(panel, validated) is not None,
    }


def page_out(page: Page, regen_threshold: float | None = None) -> PageOut:
    chosen = {p.id: next((i for i in p.images if i.selected), None) for p in page.panels}
    layout_panels = {lp.get("panel_id"): lp for lp in (page.layout or {}).get("panels", [])}
    return PageOut(
        id=page.id,
        chapter_id=page.chapter_id,
        number=page.number,
        kind=page.kind.value,
        grid_template=page.grid_template,
        layout_style=page.layout_style,
        layout_seed=page.layout_seed,
        rythme=page.rythme,  # type: ignore[arg-type]
        state=page.state.value,
        layout=page.layout,
        layout_stale=bool(page.panels) and is_stale(page),
        panels=[
            PanelOut(
                id=p.id,
                index=p.index,
                description=p.description,
                characters=list(p.character_names or []),
                decor=p.decor_id,
                objets=list(p.object_ids or []),
                shot_type=p.shot_type,
                importance=p.importance,
                intensity=p.intensity,  # type: ignore[arg-type]
                dialogues=[
                    BubbleOut(id=b.id, speaker=b.speaker_name, text=b.text, kind=b.kind.value)
                    for b in p.bubbles
                    if b.kind != BubbleKind.sfx
                ],
                sfx=[
                    SfxOut(id=b.id, text=b.text, intensity=(b.sfx or {}).get("intensity"))
                    for b in p.bubbles
                    if b.kind == BubbleKind.sfx
                ],
                frame=PanelFrameIn(**f) if (f := frame_override(p)) else None,
                bbox=p.bbox,
                bubble_zone=p.bubble_zone,
                state=p.state.value,
                final_prompt=p.final_prompt,
                final_prompt_manual=p.final_prompt_manual,
                generation_preset=p.generation_preset,
                image_count=sum(1 for i in p.images if i.kind == ImageKind.final),
                **_sketch_fields(p),
                selected_image_id=next((i.id for i in p.images if i.selected), None),
                selected_image_url=next((f"/panel-images/{i.id}/file" for i in p.images if i.selected), None),
                qc_verdict=c.qc_verdict.value if (c := chosen[p.id]) and c.qc_verdict else None,
                qc_score=c.qc_score if c else None,
                qc_reasons=list(c.qc_reasons or []) if c else [],
                qc_override=bool(c and (c.qc_details or {}).get("override")),
                detections=c.detections if c else None,
                regeneration_advised=regen_threshold is not None
                and regeneration_advised(p, layout_panels.get(p.id), regen_threshold),
            )
            for p in page.panels
        ],
    )


def get_chapter_or_404(session: Session, chapter_id: int) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable")
    return chapter


def get_page_or_404(session: Session, page_id: int) -> Page:
    page = session.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page introuvable")
    return page


def _load_pages(session: Session, chapter_id: int) -> list[Page]:
    return list(
        session.scalars(
            select(Page)
            .where(Page.chapter_id == chapter_id)
            .options(
                selectinload(Page.panels).selectinload(Panel.bubbles),
                selectinload(Page.panels).selectinload(Panel.images),
            )
            .order_by(Page.number)
        ).all()
    )


# --- chapitres ------------------------------------------------------------------
@router.get("/chapters/upcoming", response_model=list[ChapterOut])
def upcoming_chapters(
    days: int = Query(default=7, ge=0, le=366), session: Session = Depends(get_session)
) -> list[ChapterOut]:
    """Chapitres dont la publication est prévue d'aujourd'hui à J+`days` (« chapitres de la semaine »)."""
    today = date.today()
    rows = session.scalars(
        select(Chapter)
        .where(Chapter.planned_date.is_not(None), Chapter.planned_date >= today)
        .where(Chapter.planned_date <= today + timedelta(days=days))
        .options(selectinload(Chapter.project))
        .order_by(Chapter.planned_date, Chapter.project_id, Chapter.number)
    ).all()
    counts = _page_counts(session, [c.id for c in rows])
    return [chapter_out(c, counts.get(c.id, (0, 0))) for c in rows]


@router.get("/projects/{project_id}/chapters", response_model=list[ChapterOut])
def list_chapters(project_id: int, session: Session = Depends(get_session)) -> list[ChapterOut]:
    get_project_or_404(session, project_id)
    rows = session.scalars(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.number)).all()
    counts = _page_counts(session, [c.id for c in rows])
    return [chapter_out(c, counts.get(c.id, (0, 0))) for c in rows]


@router.post("/projects/{project_id}/chapters", response_model=ChapterOut, status_code=201)
def create_chapter(project_id: int, body: ChapterCreate, session: Session = Depends(get_session)) -> ChapterOut:
    get_project_or_404(session, project_id)
    last = session.scalar(select(func.max(Chapter.number)).where(Chapter.project_id == project_id)) or 0
    number = body.number or last + 1
    taken = session.scalar(select(Chapter.id).where(Chapter.project_id == project_id, Chapter.number == number))
    if taken is not None:
        raise FieldError("number", f"le chapitre {number} existe déjà")
    chapter = Chapter(
        project_id=project_id,
        number=number,
        title=body.title,
        synopsis=body.synopsis,
        target_page_count=body.target_page_count,
        status=ChapterStatus(body.status),
        planned_date=body.planned_date,
    )
    session.add(chapter)
    session.commit()
    return chapter_out(chapter)


@router.post("/projects/{project_id}/chapters/reorder", response_model=list[ChapterOut])
def reorder_chapters(
    project_id: int, body: ChapterReorder, session: Session = Depends(get_session)
) -> list[ChapterOut]:
    """Renumérote les chapitres 1..n dans l'ordre donné (tous les chapitres de la série, une fois chacun)."""
    get_project_or_404(session, project_id)
    chapters = {c.id: c for c in session.scalars(select(Chapter).where(Chapter.project_id == project_id))}
    if sorted(body.chapter_ids) != sorted(chapters) or len(set(body.chapter_ids)) != len(body.chapter_ids):
        raise FieldError("chapter_ids", "la liste doit contenir chaque chapitre de la série exactement une fois")
    for c in chapters.values():
        c.number = -c.id
    session.flush()
    for n, cid in enumerate(body.chapter_ids, start=1):
        chapters[cid].number = n
    session.commit()
    return list_chapters(project_id, session)


@router.get("/chapters/{chapter_id}", response_model=ChapterOut)
def get_chapter(chapter_id: int, session: Session = Depends(get_session)) -> ChapterOut:
    return _one_out(session, get_chapter_or_404(session, chapter_id))


@router.patch("/chapters/{chapter_id}", response_model=ChapterOut)
def update_chapter(chapter_id: int, body: ChapterUpdate, session: Session = Depends(get_session)) -> ChapterOut:
    chapter = get_chapter_or_404(session, chapter_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("title", "synopsis", "summary", "target_page_count", "status"):
        if key in changes and changes[key] is None:
            raise FieldError(key, "ne peut pas être vide")
    if "status" in changes:
        changes["status"] = ChapterStatus(changes["status"])
    for key, value in changes.items():
        setattr(chapter, key, value)
    if "status" in changes or "summary" in changes:
        # Chapitre validé (prêt / publié) : son résumé rejoint la bible de la série.
        record_chapter_summary(session, chapter)
    session.commit()
    return _one_out(session, chapter)


@router.delete("/chapters/{chapter_id}", status_code=204)
def delete_chapter(chapter_id: int, session: Session = Depends(get_session)) -> Response:
    session.delete(get_chapter_or_404(session, chapter_id))
    session.commit()
    return Response(status_code=204)


# --- étape 1 : scénario ---------------------------------------------------------
@router.post("/chapters/{chapter_id}/script", response_model=JobOut, status_code=202)
def start_script(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> JobOut:
    """Lance « Découper » : job en arrière-plan, progression via GET /jobs/{id}/events."""
    chapter = get_chapter_or_404(session, chapter_id)
    if not chapter.synopsis.strip():
        raise FieldError("synopsis", "écris d'abord le synopsis ou le script brut du chapitre")
    # Réglages du scénariste (écran « L'équipe ») : série > profil global > presets.
    presets = ctx.agents.presets_for(chapter.project_id)
    llm, error = ctx.agents.llm_for_job("script", chapter.project_id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'fournisseur LLM indisponible'}")
    try:
        presets.prompt("script")
    except PresetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    running = session.scalar(
        select(Job.id).where(
            Job.chapter_id == chapter_id,
            Job.step == "script",
            Job.status.in_([JobStatus.pending, JobStatus.running]),
        )
    )
    if running is not None:
        raise HTTPException(status_code=409, detail="Un découpage de ce chapitre est déjà en cours")
    job = Job(project_id=chapter.project_id, chapter_id=chapter_id, step="script", message="En attente…")
    session.add(job)
    session.commit()
    ctx.jobs.submit(job.id, script_job(ctx.db, presets, llm, chapter_id, knowledge=ctx.knowledge, job_id=job.id))
    return job_out(job)


@router.get("/chapters/{chapter_id}/jobs", response_model=list[JobOut])
def chapter_jobs(chapter_id: int, step: str | None = None, session: Session = Depends(get_session)) -> list[JobOut]:
    get_chapter_or_404(session, chapter_id)
    q = select(Job).where(Job.chapter_id == chapter_id)
    if step:
        q = q.where(Job.step == step)
    return [job_out(j) for j in session.scalars(q.order_by(Job.id.desc()).limit(20))]


# --- découpage éditable ---------------------------------------------------------
@router.get("/chapters/{chapter_id}/pages", response_model=list[PageOut])
def list_pages(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[PageOut]:
    get_chapter_or_404(session, chapter_id)
    return [_page_out(ctx, p) for p in _load_pages(session, chapter_id)]


def _page_out(ctx: AppContext, page: Page) -> PageOut:
    return page_out(page, ctx.presets.layout.regeneration.ratio_threshold)


@router.put("/chapters/{chapter_id}/pages", response_model=list[PageOut])
def replace_pages(
    chapter_id: int,
    body: BreakdownIn,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> list[PageOut]:
    """Enregistre le découpage édité à la main (ajout, suppression, réordonnancement).

    Les pages et cases existantes sont repérées par `id` (conservées, avec leurs futures images) ;
    une page ou une case sans `id` est créée ; ce qui n'est plus listé est supprimé. Les pages dont
    le contenu a changé sont remises en page automatiquement.
    """
    chapter = get_chapter_or_404(session, chapter_id)
    pages = _load_pages(session, chapter_id)
    pages_by_id = {p.id: p for p in pages}
    panels_by_id = {pa.id: pa for p in pages for pa in p.panels}
    names = {
        c.name.casefold(): c.id
        for c in session.scalars(select(Character).where(Character.project_id == chapter.project_id))
    }
    library = SeriesLibrary.load(session, chapter.project_id)
    decor_ids = {e["id"] for e in library.decors}
    object_ids = {e["id"] for e in library.objets}

    seen_pages: set[int] = set()
    seen_panels: set[int] = set()
    for pi, pin in enumerate(body.pages):
        if pin.id is not None:
            if pin.id not in pages_by_id or pin.id in seen_pages:
                raise FieldError(f"pages.{pi}.id", "page inconnue dans ce chapitre")
            seen_pages.add(pin.id)
        for ci, cin in enumerate(pin.panels):
            if cin.id is not None:
                if cin.id not in panels_by_id or cin.id in seen_panels:
                    raise FieldError(f"pages.{pi}.panels.{ci}.id", "case inconnue dans ce chapitre")
                seen_panels.add(cin.id)
            if cin.decor is not None and cin.decor not in decor_ids:
                raise FieldError(f"pages.{pi}.panels.{ci}.decor", "décor inconnu dans cette série")
            unknown = [i for i in cin.objets or [] if i not in object_ids]
            if unknown:
                raise FieldError(
                    f"pages.{pi}.panels.{ci}.objets",
                    f"objet(s) inconnu(s) dans cette série : {', '.join(map(str, unknown))}",
                )

    # Numéros temporaires négatifs : évite les conflits d'unicité pendant le réordonnancement.
    for p in pages:
        p.number = -p.id
        for pa in p.panels:
            pa.index = -pa.id
    session.flush()

    result: list[Page] = []
    for n, pin in enumerate(body.pages, start=1):
        page = pages_by_id.get(pin.id) if pin.id is not None else None
        if page is None:
            page = Page(chapter_id=chapter_id, number=n, kind=PageKind(pin.kind))
            session.add(page)
        page.number = n
        page.kind = PageKind(pin.kind)
        page.rythme = pin.rythme
        ordered: list[Panel] = []
        for i, cin in enumerate(pin.panels):
            panel = panels_by_id.get(cin.id) if cin.id is not None else None
            if panel is None:
                panel = Panel(index=i)
            ordered.append(panel)
            panel.index = i
            panel.description = cin.description
            panel.character_names = list(dict.fromkeys(c for c in cin.characters if c))
            panel.character_ids = [names[c.casefold()] for c in panel.character_names if c.casefold() in names]
            panel.shot_type = normalize_shot_type(cin.shot_type) or None
            panel.importance = cin.importance
            panel.intensity = cin.intensity
            # Bibliothèque : un champ absent garde le décor / les objets de la case.
            if "decor" in cin.model_fields_set:
                panel.decor_id = cin.decor
            if cin.objets is not None:
                panel.object_ids = list(dict.fromkeys(cin.objets))
            # Les bulles sont recréées ; un cadre ou une queue ajustés à la main au lettrage suivent leur `id`.
            previous = {b.id: b for b in panel.bubbles} if panel.id is not None else {}
            bubbles = [
                Bubble(
                    order=j,
                    speaker_name=d.speaker,
                    speaker_id=names.get(d.speaker.casefold()),
                    text=d.text,
                    kind=BubbleKind(d.kind),
                    position=previous[d.id].position if d.id in previous else None,
                    tail=previous[d.id].tail if d.id in previous else None,
                )
                for j, d in enumerate(cin.dialogues)
                if not (d.id in previous and previous[d.id].kind == BubbleKind.sfx)
            ]
            # Onomatopées : gardées telles quelles si la case n'en envoie pas ; sinon recréées, leurs réglages
            # de lettrage (centre, taille, angle, police) suivant leur `id`.
            old_sfx = [b for b in previous.values() if b.kind == BubbleKind.sfx]
            if cin.sfx is None:
                sfx = [
                    Bubble(order=0, text=b.text, kind=BubbleKind.sfx, sfx=b.sfx, position=b.position)
                    for b in sorted(old_sfx, key=lambda b: b.order)
                ]
            else:
                kept = {b.id: b for b in old_sfx}
                sfx = []
                for x in cin.sfx:
                    old = kept.get(x.id) if x.id is not None else None
                    params = dict(old.sfx or {}) if old is not None else {}
                    if x.intensity is not None:
                        params["intensity"] = x.intensity
                    sfx.append(
                        Bubble(
                            order=0,
                            text=x.text,
                            kind=BubbleKind.sfx,
                            sfx=params or None,
                            position=old.position if old is not None else None,
                        )
                    )
            for k, b in enumerate(sfx):
                b.order = len(bubbles) + k
            panel.bubbles = bubbles + sfx
        page.panels = ordered  # les cases retirées deviennent orphelines → supprimées
        result.append(page)

    for p in pages:
        if p.id not in seen_pages:
            session.delete(p)
    session.flush()

    for page in sorted(result, key=lambda p: p.number):
        if page.grid_template:
            tpl = ctx.agents.presets_for(chapter.project_id).layout_templates.get(page.grid_template)
            if tpl is None or tpl.panel_count != len(page.panels):
                page.grid_template = None
        if page.panels and is_stale(page):
            _layout(ctx, page)
        elif not page.panels:
            page.layout = None
    session.commit()
    return [_page_out(ctx, p) for p in _load_pages(session, chapter_id)]


# --- étape 2 : mise en page -----------------------------------------------------
def _layout(ctx: AppContext, page: Page, *, reroll: bool = False) -> None:
    try:
        layout_page(ctx.agents.presets_for(page.chapter.project_id), page, reroll=reroll)
    except (LayoutError, PresetError) as exc:
        raise FieldError("layout", f"page {page.number} : {exc}") from None


@router.post("/chapters/{chapter_id}/layout", response_model=list[PageOut])
def layout_chapter(
    chapter_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[PageOut]:
    """« Recalculer » tout le chapitre (gouttières et biais modifiés à la main sont réinitialisés ;
    chaque page garde sa graine, donc sa mise en page)."""
    get_chapter_or_404(session, chapter_id)
    pages = _load_pages(session, chapter_id)
    for page in pages:
        if page.panels:
            _layout(ctx, page)
    session.commit()
    return [_page_out(ctx, p) for p in pages]


@router.post("/pages/{page_id}/layout", response_model=PageOut)
def layout_one_page(
    page_id: int,
    body: PageLayoutIn | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> PageOut:
    """« Recalculer » une page ; `template_id` impose un gabarit (null = choix automatique), `style` un
    style de mise en page (null = celui de la série), `reroll` tire une nouvelle mise en page."""
    page = get_page_or_404(session, page_id)
    if not page.panels:
        raise FieldError("layout", "page sans case : rien à mettre en page")
    if body is not None and "style" in body.model_fields_set:
        if body.style is not None and body.style not in ctx.presets.layout_styles:
            raise FieldError("style", f"style de mise en page inconnu : « {body.style} »")
        page.layout_style = body.style
    if body is not None and "template_id" in body.model_fields_set:
        if body.template_id is not None:
            tpl = ctx.agents.presets_for(page.chapter.project_id).layout_templates.get(body.template_id)
            if tpl is None:
                raise FieldError("template_id", f"gabarit inconnu : « {body.template_id} »")
            if tpl.panel_count != len(page.panels):
                raise FieldError(
                    "template_id", f"ce gabarit a {tpl.panel_count} case(s), la page en a {len(page.panels)}"
                )
        page.grid_template = body.template_id
    _layout(ctx, page, reroll=bool(body and body.reroll))
    session.commit()
    return _page_out(ctx, page)


@router.post("/pages/{page_id}/gutters", response_model=PageOut)
def move_gutter(
    page_id: int, body: GutterMove, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PageOut:
    """Déplace une gouttière (position de son centre en px de la page) ; ses voisines sont recalculées."""
    page = get_page_or_404(session, page_id)
    try:
        move_page_gutter(
            ctx.agents.presets_for(page.chapter.project_id),
            page,
            path=body.path,
            index=body.index,
            position=body.position,
        )
    except (LayoutError, PresetError) as exc:
        raise FieldError("gutter", str(exc)) from None
    session.commit()
    return _page_out(ctx, page)


@router.post("/pages/{page_id}/cuts", response_model=PageOut)
def slant_cut(
    page_id: int, body: CutSlant, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PageOut:
    """Incline une découpe (positions de ses deux extrémités, px de la page) ; les images des cases sont
    gardées et recadrées au nouveau polygone (`regeneration_advised` signale un ratio trop changé)."""
    page = get_page_or_404(session, page_id)
    try:
        slant_page_cut(
            ctx.agents.presets_for(page.chapter.project_id), page, path=body.path, index=body.index, ends=body.ends
        )
    except (LayoutError, PresetError) as exc:
        raise FieldError("cut", str(exc)) from None
    session.commit()
    return _page_out(ctx, page)


@router.put("/panels/{panel_id}/frame", response_model=PageOut)
def set_panel_frame(
    panel_id: int, body: PanelFrameIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> PageOut:
    """Impose (ou rend au style, avec null) les options de cadre d'une case — sans bord / fondu, fond perdu,
    incrustation — puis met la page à jour (même graine ; retouches gardées si aucune incrustation ne change)."""
    panel = session.get(Panel, panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Case introuvable")
    page = panel.page
    was_fresh = not is_stale(page)
    values = body.model_dump()
    panel.frame = {k: values[k] for k in FRAME_KEYS if values[k] is not None} or None
    try:
        apply_frame_change(ctx.agents.presets_for(page.chapter.project_id), page, was_fresh=was_fresh)
    except (LayoutError, PresetError) as exc:
        session.rollback()
        raise FieldError("frame", f"page {page.number} : {exc}") from None
    session.commit()
    return _page_out(ctx, page)


@router.get("/layout/templates")
def list_templates(project_id: int | None = None, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, object]]:
    templates = ctx.agents.presets_for(project_id).layout_templates
    return [{"id": t.id, "name": t.name, "panel_count": t.panel_count} for t in templates.values()]


@router.get("/layout/styles")
def list_styles(ctx: AppContext = Depends(get_ctx)) -> list[dict[str, object]]:
    default = ctx.presets.default_layout_style
    return [
        {"id": s.id, "name": s.name, "description": s.description, "is_default": s.id == default}
        for s in ctx.presets.layout_styles.values()
    ]
