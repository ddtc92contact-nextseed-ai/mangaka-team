"""Créateur de série (carte « Créateur de série » de la fiche série) — voir pipeline/series_creator.py.

- `GET /projects/{id}/series-creator` : questions fermées de l'échange et ce que la série a déjà (bible, ADN ajusté) ;
- `POST /projects/{id}/series-creator/proposal` : l'agent propose l'ADN et la bible d'après les réponses — rien n'est
  enregistré ; la proposition est rendue en différentiel (ce qui est écrit à côté de ce qui est proposé) ;
- `POST /projects/{id}/series-creator/apply` : enregistre ce que l'auteur a retenu et corrigé. Ce qu'il avait déjà
  écrit (section de bible, note de personnage, valeur d'ADN ajustée) n'est remplacé que s'il le confirme
  (`overwrite`) : sinon 409, rien n'est écrit.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.knowledge import get_bible, get_or_create_bible
from ..pipeline.pre_direction import LABELS, DnaError, _kind, clean_overrides, field_specs, flatten, series_charter
from ..pipeline.series_creator import (
    AGENT_ID,
    BIBLE_SECTIONS,
    MAX_PITCH_CHARS,
    AnswerError,
    CreatorError,
    conflicts,
    creator_brief,
    merge_dna,
    propose,
    resolve_answers,
    same_value,
)
from ..presets import PresetError
from ..store.models import Character, Project
from .deps import AppContext, get_ctx, get_session
from .errors import FieldError
from .knowledge import bible_out
from .pre_direction import PreDirectionOut, pre_direction_out
from .projects import get_project_or_404
from .schemas import BibleOut

router = APIRouter(tags=["createur-serie"])

DnaValue = float | int | bool
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)]


class CreatorChoiceOut(BaseModel):
    id: str
    label: str


class CreatorQuestionOut(BaseModel):
    id: str
    label: str
    help: str
    choices: list[CreatorChoiceOut]


class CreatorOut(BaseModel):
    project_id: int
    available: bool
    reason: str | None = None
    agent_name: str
    genre_name: str | None
    questions: list[CreatorQuestionOut]
    max_free_chars: int
    max_pitch_chars: int = MAX_PITCH_CHARS
    # Ce que l'auteur a déjà écrit : une relance propose un différentiel.
    bible_filled: list[str]  # sections non vides (world, tone, rules, motifs)
    notes_filled: int  # personnages avec une note
    characters: int
    dna_adjusted: int  # valeurs d'ADN ajustées par la série


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=4000)


class ProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pitch: str = Field(default="", max_length=MAX_PITCH_CHARS)
    answers: dict[str, AnswerIn] = Field(default_factory=dict, max_length=30)


class DnaChangeOut(BaseModel):
    path: str
    label: str
    group: str
    kind: str
    min: float | None
    max: float | None
    genre_value: DnaValue
    current_value: DnaValue  # valeur effective aujourd'hui
    adjusted: bool  # la série a déjà ajusté cette valeur (l'auteur l'a choisie)
    proposed: DnaValue
    why: str
    conflict: bool  # remplacerait une valeur ajustée par l'auteur


class BibleChangeOut(BaseModel):
    key: str
    label: str
    current: str
    proposed: str
    conflict: bool  # remplacerait un texte déjà écrit


class NoteChangeOut(BaseModel):
    id: int
    name: str
    current: str
    proposed: str
    conflict: bool


class ProposalOut(BaseModel):
    project_id: int
    genre_name: str | None
    attempts: int
    notes: str
    dna: list[DnaChangeOut]
    bible: list[BibleChangeOut]
    characters: list[NoteChangeOut]


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dna: dict[str, DnaValue] = Field(default_factory=dict, max_length=100)
    bible: dict[str, Text] = Field(default_factory=dict, max_length=4)
    character_notes: dict[int, Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]] = Field(
        default_factory=dict, max_length=500
    )
    # Clés confirmées par l'auteur : « bible.world », « character.12 », « dna.shots.wide.min ».
    overwrite: list[str] = Field(default_factory=list, max_length=700)


class ApplyOut(BaseModel):
    pre_direction: PreDirectionOut
    bible: BibleOut
    written: list[str]  # clés écrites


def _characters(session: Session, project_id: int) -> list[Character]:
    return list(session.scalars(select(Character).where(Character.project_id == project_id).order_by(Character.name)))


def _current(session: Session, project: Project) -> tuple[dict[str, str], dict[int, str]]:
    bible = get_bible(session, project.id)
    sections = {k: ((getattr(bible, k) or "").strip() if bible else "") for k, _ in BIBLE_SECTIONS}
    notes = {
        int(k): v.strip()
        for k, v in ((bible.character_notes if bible else None) or {}).items()
        if str(k).isdigit() and (v or "").strip()
    }
    return sections, notes


@router.get("/projects/{project_id}/series-creator", response_model=CreatorOut)
def read_creator(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CreatorOut:
    project = get_project_or_404(session, project_id)
    presets = ctx.agents.presets_for(project.id)
    settings = presets.series_creator
    base = presets.genre_dna(project.style_genre)
    genre = presets.style_genres.get(project.style_genre or "")
    agent = presets.agents.get(AGENT_ID)
    reason = None
    if settings is None:
        reason = "presets/series_creator.yaml absent ou invalide"
    elif base is None:
        reason = "presets/pre_direction.yaml absent ou invalide : ADN indisponible"
    sections, notes = _current(session, project)
    characters = _characters(session, project.id)
    return CreatorOut(
        project_id=project.id,
        available=reason is None,
        reason=reason,
        agent_name=agent.name if agent else "Créateur de série",
        genre_name=genre.name if genre else None,
        questions=[
            CreatorQuestionOut(
                id=q.id,
                label=q.label,
                help=q.help,
                choices=[CreatorChoiceOut(id=c.id, label=c.label) for c in q.choices],
            )
            for q in (settings.questions if settings else [])
        ],
        max_free_chars=settings.max_free_chars if settings else 0,
        bible_filled=[k for k, v in sections.items() if v],
        notes_filled=sum(1 for c in characters if c.id in notes),
        characters=len(characters),
        dna_adjusted=len(clean_overrides(base, project.pre_direction or {})) if base else 0,
    )


@router.post("/projects/{project_id}/series-creator/proposal", response_model=ProposalOut)
def make_proposal(
    project_id: int, body: ProposalIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ProposalOut:
    """L'agent propose l'ADN (écarts au genre, expliqués) et la bible ; rien n'est enregistré."""
    project = get_project_or_404(session, project_id)
    presets = ctx.agents.presets_for(project.id)
    settings = presets.series_creator
    if settings is None:
        raise HTTPException(status_code=503, detail="presets/series_creator.yaml absent ou invalide")
    try:
        answers = resolve_answers(settings, {k: v.model_dump() for k, v in body.answers.items()})
    except AnswerError as exc:
        raise FieldError(exc.field, exc.message) from None
    llm, error = ctx.agents.llm_for(AGENT_ID, project.id)
    if llm is None:
        raise HTTPException(status_code=503, detail=f"LLM indisponible : {error or 'non configuré'}")
    try:
        brief = creator_brief(session, presets, project, answers, pitch=body.pitch, knowledge=ctx.knowledge)
        prompt = presets.prompt(settings.prompt)
    except (PresetError, CreatorError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    current_overrides = dict(project.pre_direction or {})
    charter = series_charter(presets, project)
    effective = flatten(charter.dna) if charter else flatten(brief.base)
    session.commit()  # aucune transaction ouverte pendant l'appel au LLM
    try:
        run = propose(llm, prompt, brief)
    except CreatorError as exc:
        raise HTTPException(status_code=502, detail=f"Le créateur de série n'a pas pu proposer : {exc}") from None
    out = run.output
    inherited = flatten(brief.base)
    own = clean_overrides(brief.base, current_overrides)
    specs = {f["path"]: f for f in field_specs()}
    genre = presets.style_genres.get(project.style_genre or "")
    return ProposalOut(
        project_id=project.id,
        genre_name=genre.name if genre else None,
        attempts=run.attempts,
        notes=out.notes,
        dna=[
            DnaChangeOut(
                path=c.path,
                label=LABELS.get(c.path, (c.path,))[0],
                group=specs[c.path]["group"],
                kind=_kind(c.path),
                min=specs[c.path]["min"],
                max=specs[c.path]["max"],
                genre_value=inherited[c.path],
                current_value=effective[c.path],
                adjusted=c.path in own,
                proposed=c.value,
                why=c.why,
                conflict=c.path in own and not same_value(own[c.path], c.value),
            )
            for c in out.dna
        ],
        bible=[
            BibleChangeOut(
                key=k,
                label=label,
                current=brief.bible[k],
                proposed=out.bible[k],
                conflict=bool(brief.bible[k]) and brief.bible[k] != out.bible[k],
            )
            for k, label in BIBLE_SECTIONS
        ],
        characters=[
            NoteChangeOut(
                id=c["id"],
                name=c["name"],
                current=c["note"],
                proposed=out.notes_by_id.get(c["id"], ""),
                conflict=bool(c["note"]) and c["note"] != out.notes_by_id.get(c["id"], ""),
            )
            for c in brief.characters
        ],
    )


@router.post("/projects/{project_id}/series-creator/apply", response_model=ApplyOut)
def apply_proposal(
    project_id: int, body: ApplyIn, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> ApplyOut:
    """Enregistre l'ADN et la bible retenus ; 409 (rien n'est écrit) si l'un remplace ce que l'auteur avait écrit sans
    que ce soit confirmé dans `overwrite`."""
    project = get_project_or_404(session, project_id)
    presets = ctx.agents.presets_for(project.id)
    base = presets.genre_dna(project.style_genre)
    if base is None:
        raise HTTPException(status_code=503, detail="presets/pre_direction.yaml absent ou invalide : ADN indisponible")
    unknown = [k for k in body.bible if k not in dict(BIBLE_SECTIONS)]
    if unknown:
        raise FieldError(f"bible.{unknown[0]}", f"section de bible inconnue : « {unknown[0]} »")
    characters = {c.id: c.name for c in _characters(session, project.id)}
    strangers = [cid for cid in body.character_notes if cid not in characters]
    if strangers:
        raise FieldError("character_notes", f"personnage(s) absent(s) de la série : {strangers}")
    sections, notes = _current(session, project)
    bible_in = {k: v for k, v in body.bible.items() if v}
    notes_in = {cid: v for cid, v in body.character_notes.items() if v}
    clashes = conflicts(
        base=base,
        current_overrides=project.pre_direction or {},
        current_bible=sections,
        current_notes=notes,
        dna=body.dna,
        bible=bible_in,
        notes=notes_in,
        names=characters,
    )
    pending = [c for c in clashes if c.key not in set(body.overwrite)]
    if pending:
        listed = ", ".join(c.label for c in pending[:6]) + ("…" if len(pending) > 6 else "")
        raise HTTPException(
            status_code=409,
            detail=f"Déjà écrit par toi, à confirmer avant de le remplacer : {listed}. Rien n'a été enregistré.",
        )
    try:
        overrides = merge_dna(base, project.pre_direction or {}, body.dna)
    except DnaError as exc:
        raise FieldError(f"dna.{exc.path}", exc.message) from None
    before = {**flatten(base), **clean_overrides(base, project.pre_direction or {})}
    written = [f"dna.{p}" for p, v in body.dna.items() if not same_value(before[p], v)]
    project.pre_direction = overrides
    bible = get_or_create_bible(session, project.id)
    for key, value in bible_in.items():
        if value != sections[key]:
            setattr(bible, key, value)
            written.append(f"bible.{key}")
    if notes_in:
        merged = {str(k): v for k, v in (bible.character_notes or {}).items()}
        for cid, value in notes_in.items():
            if value != notes.get(cid, ""):
                merged[str(cid)] = value
                written.append(f"character.{cid}")
        bible.character_notes = merged
    session.commit()
    session.refresh(project)
    return ApplyOut(
        pre_direction=pre_direction_out(ctx, project), bible=bible_out(session, ctx, project), written=written
    )
