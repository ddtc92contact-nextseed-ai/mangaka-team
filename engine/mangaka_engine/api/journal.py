"""Traçabilité : journal d'une version, verdict en un clic, comparaison A/B, statistiques et export (local)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.ab import arm_image, enqueue_ab, group_choice, group_logs, panel_groups, pending_groups, record_choice
from ..pipeline.generation import GenerationError, refresh_states
from ..pipeline.journal import (
    KINDS,
    MEASURE_LABELS,
    MEASURES,
    PANEL_IMAGE,
    VERDICTS,
    log_for_image,
    record_event,
    tonality_gaps,
)
from ..pipeline.stats import StatsFilter, compute_stats, export_rows, query_logs, to_csv
from ..presets import PresetError, PresetRegistry
from ..store.models import GenerationEvent, GenerationLog, PanelImage
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .generation import (
    _get_image_or_404,
    _presets,
    _require_comfyui,
    _require_lock_available,
    get_panel_or_404,
    panel_image_out,
)
from .jobs import job_out
from .schemas import (
    ABArmOut,
    ABChoiceIn,
    ABGroupOut,
    ABIn,
    ABStartOut,
    GenerationEventOut,
    GenerationLogOut,
    ImageJournalOut,
    JournalSettingsOut,
    MeasureOut,
    StatsOut,
    VerdictIn,
    VerdictReasonOut,
)

router = APIRouter(tags=["traçabilité"])


# --- sorties ---------------------------------------------------------------------------------
def event_out(presets: PresetRegistry, event: GenerationEvent) -> GenerationEventOut:
    return GenerationEventOut(
        id=event.id,
        created_at=event.created_at,
        verdict=event.verdict,  # type: ignore[arg-type]
        action=event.action,
        reason=event.reason,
        reason_label=presets.journal.reason_label(event.reason),
        note=event.note or "",
    )


def log_out(session: Session, presets: PresetRegistry, row: GenerationLog) -> GenerationLogOut:
    events = list(
        session.scalars(select(GenerationEvent).where(GenerationEvent.log_id == row.id).order_by(GenerationEvent.id))
    )
    judged = [e for e in events if e.verdict in ("validated", "rejected")]
    measures = {k: getattr(row, k) for k in MEASURES}
    fields = {c: getattr(row, c) for c in GenerationLogOut.model_fields if hasattr(GenerationLog, c)}
    return GenerationLogOut(
        **{**fields, "references": row.references or [], "loras": row.loras or [], "knowledge": row.knowledge or []},
        measures=measures,
        gaps=tonality_gaps(measures, presets.tonality),
        verdict=judged[-1].verdict if judged else None,  # type: ignore[arg-type]
        events=[event_out(presets, e) for e in events],
    )


def _check_reason(presets: PresetRegistry, reason: str | None) -> None:
    if reason is not None and reason not in {r.id for r in presets.journal.reasons}:
        known = ", ".join(r.id for r in presets.journal.reasons) or "aucune"
        raise FieldError("reason", f"raison inconnue : « {reason} » (possibles : {known})")


# --- réglages -----------------------------------------------------------------------------------
@router.get("/journal/settings", response_model=JournalSettingsOut)
def journal_settings(ctx: AppContext = Depends(get_ctx)) -> JournalSettingsOut:
    presets = ctx.presets
    tonality = presets.tonality
    target = tonality.target.model_dump()
    return JournalSettingsOut(
        reasons=[VerdictReasonOut(id=r.id, label=r.label) for r in presets.journal.reasons],
        measures=[MeasureOut(key=k, label=MEASURE_LABELS[k], target=target.get(k)) for k in MEASURES],
        tonality_reference=tonality.reference,
        dark_below=tonality.dark_below,
        black_below=tonality.black_below,
        white_from=tonality.white_from,
        low_data_below=presets.journal.low_data_below,
        kinds=KINDS,
        verdicts=VERDICTS,
    )


# --- une version ------------------------------------------------------------------------------
@router.get("/panel-images/{image_id}/journal", response_model=ImageJournalOut)
def image_journal(
    image_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ImageJournalOut:
    """Génération qui a produit cette version : réglages, prompts envoyés, mesures et écart à la cible, verdicts."""
    img = _get_image_or_404(session, image_id)
    row = log_for_image(session, PANEL_IMAGE, img.id)
    return ImageJournalOut(log=log_out(session, _presets(ctx, img.panel), row) if row is not None else None)


@router.post("/panel-images/{image_id}/verdict", response_model=ImageJournalOut, status_code=201)
def judge_image(
    image_id: int, body: VerdictIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ImageJournalOut:
    """Juge une version en un clic : gardée ou rejetée (+ raison de la liste fermée, note libre). Le verdict
    s'ajoute au journal (jamais réécrit) ; la version choisie de la case ne change pas."""
    img = _get_image_or_404(session, image_id)
    presets = _presets(ctx, img.panel)
    _check_reason(presets, body.reason)
    record_event(
        session,
        verdict=body.verdict,
        action="judge",
        image_id=img.id,
        panel_id=img.panel_id,
        reason=body.reason if body.verdict == "rejected" else None,
        note=body.note,
    )
    session.commit()
    row = log_for_image(session, PANEL_IMAGE, img.id)
    return ImageJournalOut(log=log_out(session, presets, row) if row is not None else None)


# --- comparaison A/B -----------------------------------------------------------------------------
def _group_out(session: Session, ctx: AppContext, presets: PresetRegistry, group: str) -> ABGroupOut:
    logs = group_logs(session, group)
    choice = group_choice(session, list(logs.values()))
    winner = None
    if choice is not None:
        winner = next(
            (arm for arm, row in logs.items() if row.id == choice.log_id and choice.verdict == "validated"), None
        )
        if winner is None:  # événement noté sur le perdant : l'autre bras a gagné
            loser = next((arm for arm, row in logs.items() if row.id == choice.log_id), None)
            winner = "B" if loser == "A" else "A" if loser == "B" else None
    arms = []
    for arm in ("A", "B"):
        row = logs.get(arm)
        image = arm_image(session, row) if row is not None else None
        arms.append(
            ABArmOut(
                arm=arm,  # type: ignore[arg-type]
                log=log_out(session, presets, row) if row is not None else None,
                image=panel_image_out(image, presets) if image is not None else None,
            )
        )
    first = next(iter(logs.values()), None)
    panel_id = first.panel_id if first is not None else None
    pending = panel_id is not None and any(g["group"] == group for g in pending_groups(session, panel_id))
    return ABGroupOut(
        group=group,
        mode=first.ab_mode if first is not None else None,
        seed=first.seed if first is not None else None,
        pending=pending or len(logs) < 2,
        arms=arms,
        choice=winner,  # type: ignore[arg-type]
    )


@router.post("/panels/{panel_id}/ab", response_model=ABStartOut, status_code=202)
def start_ab(
    panel_id: int, body: ABIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ABStartOut:
    """« Comparer deux prompts » : la case générée deux fois à la même graine (bras A et B) ; ce qui varie :
    le prompt (A = actuel, B = variante), le palier ou le CFG. Deux versions de plus, la choisie ne change pas."""
    _require_comfyui(ctx)
    panel = get_panel_or_404(session, panel_id)
    _require_lock_available(ctx, panel)
    try:
        group, seed, jobs = enqueue_ab(
            session,
            _presets(ctx, panel),
            panel,
            mode=body.mode,
            prompt_b=body.prompt_b,
            presets_ab=(body.presets[0], body.presets[1]) if body.presets else None,
            cfgs=(body.cfgs[0], body.cfgs[1]) if body.cfgs else None,
            seed=body.seed,
            knowledge=ctx.knowledge,
        )
    except PresetError as exc:
        raise FieldError("presets", str(exc)) from None
    except GenerationError as exc:
        raise FieldError(body.mode, str(exc)[:1].upper() + str(exc)[1:]) from None
    session.commit()
    ctx.generation.notify()
    return ABStartOut(group=group, seed=seed, jobs=[job_out(j) for j in jobs])


@router.get("/panels/{panel_id}/ab", response_model=list[ABGroupOut])
def list_ab(
    panel_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> list[ABGroupOut]:
    """Comparaisons A/B de la case, la plus récente d'abord (celles en file comprises)."""
    panel = get_panel_or_404(session, panel_id)
    presets = _presets(ctx, panel)
    groups = [g["group"] for g in pending_groups(session, panel.id)][::-1]
    for group in panel_groups(session, panel.id):
        if group not in groups:
            groups.append(group)
    return [_group_out(session, ctx, presets, g) for g in groups]


@router.post("/ab/{group}/choice", response_model=ABGroupOut)
def choose_ab(
    group: str, body: ABChoiceIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ABGroupOut:
    """Choix de l'auteur : bras retenu gardé, l'autre rejeté (raison, note) ; le retenu devient la version
    choisie de la case (`select`)."""
    logs = group_logs(session, group)
    if not logs:
        raise HTTPException(status_code=404, detail="Comparaison introuvable")
    panel = get_panel_or_404(session, next(iter(logs.values())).panel_id or 0)
    presets = _presets(ctx, panel)
    _check_reason(presets, body.reason)
    try:
        record_choice(session, group, body.winner, reason=body.reason, note=body.note)
    except GenerationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)[:1].upper() + str(exc)[1:]) from None
    winner = session.get(PanelImage, logs[body.winner].image_id or 0)
    if body.select and winner is not None and winner.panel_id == panel.id and winner.kind.value == "final":
        for other in panel.images:
            other.selected = other.id == winner.id
        session.flush()
        refresh_states(session, [panel.id])
    session.commit()
    return _group_out(session, ctx, presets, group)


# --- statistiques et export -----------------------------------------------------------------------
def _filter(
    project_id: int | None,
    chapter_id: int | None,
    date_from: date | None,
    date_to: date | None,
    tier: str | None,
    kind: str | None,
) -> StatsFilter:
    if kind is not None and kind not in KINDS:
        raise FieldError("kind", f"sorte inconnue : « {kind} » (possibles : {', '.join(KINDS)})")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise FieldError("date_to", "la date de fin précède la date de début")
    return StatsFilter(
        project_id=project_id, chapter_id=chapter_id, date_from=date_from, date_to=date_to, tier=tier or None, kind=kind
    )


@router.get("/stats", response_model=StatsOut)
def get_stats(
    project_id: int | None = Query(default=None),
    chapter_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    tier: str | None = Query(default=None, max_length=40),
    kind: str | None = Query(default=None, max_length=30),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> StatsOut:
    """Taux de validation et moyennes des mesures de tonalité, au total et ventilés, avec les effectifs."""
    f = _filter(project_id, chapter_id, date_from, date_to, tier, kind)
    return StatsOut(**compute_stats(session, ctx.presets, f))


@router.get("/stats/export")
def export_stats(
    format: Literal["csv", "json"] = Query(default="csv"),
    project_id: int | None = Query(default=None),
    chapter_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    tier: str | None = Query(default=None, max_length=40),
    kind: str | None = Query(default=None, max_length=30),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    """Export du journal : une ligne par génération (réussie ou non), avec son dernier verdict et ses mesures.
    Fichier téléchargé depuis le moteur local : rien n'est envoyé ailleurs."""
    f = _filter(project_id, chapter_id, date_from, date_to, tier, kind)
    rows = export_rows(session, ctx.presets, query_logs(session, f))
    stamp = date.today().isoformat()
    if format == "json":
        return JSONResponse(
            rows, headers={"Content-Disposition": f'attachment; filename="journal-generations-{stamp}.json"'}
        )
    return Response(
        content="﻿" + to_csv(rows),  # BOM : accents lus correctement par un tableur
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="journal-generations-{stamp}.csv"'},
    )
