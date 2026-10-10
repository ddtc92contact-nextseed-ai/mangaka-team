"""Étape 1 — scénario : découpage d'un chapitre en pages → cases par le LLM.

1. contexte : série, personnages, bibliothèque (décors et objets, avec leurs ids), résumés des chapitres précédents (continuité), synopsis, bible de
   la série et passages du savoir-faire (`pipeline/knowledge.py`, enregistrés dans `llm_runs`) ;
2. prompt rendu depuis `presets/prompts/script.yaml` (aucun texte de prompt dans ce module) ;
3. réponse JSON validée par Pydantic, puis les ids de décor / d'objets contre la bibliothèque de la
   série ; invalide → nouvel essai avec l'erreur renvoyée au LLM
   (`max_retries` du preset, 2 au maximum) → sinon `ScriptError` lisible ;
4. enregistrement en Pages + Panels + Bubbles (remplace les pages « story » du chapitre) et
   du résumé du chapitre, puis découpage automatique des pages (étape 2).
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetError, PresetRegistry, PromptPreset
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.db import Database
from ..store.models import (
    Bubble,
    BubbleKind,
    Chapter,
    ChapterStatus,
    Character,
    LLMRun,
    Page,
    PageKind,
    Panel,
)
from ..validation import format_errors
from .knowledge import AgentKnowledge, KnowledgeBase
from .library import SeriesLibrary
from .pages import layout_pages

AGENT = "script"  # rôle de l'agent dans presets/knowledge.yaml

SHOT_TYPES = (
    "plan d'ensemble",
    "plan large",
    "plan moyen",
    "plan américain",
    "plan rapproché",
    "gros plan",
    "très gros plan",
    "plongée",
    "contre-plongée",
    "vue subjective",
    "insert",
)
ShotType = Literal[
    "plan d'ensemble",
    "plan large",
    "plan moyen",
    "plan américain",
    "plan rapproché",
    "gros plan",
    "très gros plan",
    "plongée",
    "contre-plongée",
    "vue subjective",
    "insert",
]
# Types de réplique proposés au LLM ; les onomatopées (sfx) ont leur propre liste par case.
BUBBLE_KINDS = tuple(k.value for k in BubbleKind if k != BubbleKind.sfx)
BubbleKindName = Literal["speech", "thought", "shout", "narration", "off"]
# Indices de direction artistique (facultatifs) lus par la grammaire de mise en page (layout_style.py).
INTENSITIES = ("calme", "normal", "choc")
RYTHMES = ("lent", "normal", "rapide")
IntensityName = Literal["calme", "normal", "choc"]
RythmeName = Literal["lent", "normal", "rapide"]
MAX_PANELS_PER_PAGE = 9
MAX_PAGES = 60
MAX_PANEL_OBJECTS = 8

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


def _hint(value: Any) -> Any:
    """« Choc », « CALME » → minuscules ; une chaîne vide ou null = non précisé."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        return v or None
    return value


def normalize_shot_type(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    v = " ".join(value.strip().lower().replace("’", "'").split())
    return v.replace("contre plongée", "contre-plongée")


class _LLMModel(BaseModel):
    # Les LLM ajoutent volontiers des champs : on les ignore plutôt que d'échouer.
    model_config = ConfigDict(extra="ignore")


class ScriptDialogue(_LLMModel):
    speaker: Short = ""
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    kind: BubbleKindName = "speech"

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v


class ScriptSfx(_LLMModel):
    """Onomatopée de la case (« VROUM ! », « CLIC ») : posée au lettrage, jamais dessinée par le modèle d'image."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    intensity: IntensityName | None = None

    _intensity = field_validator("intensity", mode="before")(_hint)


class ScriptPanel(_LLMModel):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    characters: list[Short] = Field(default_factory=list, max_length=20)
    shot_type: ShotType
    dialogues: list[ScriptDialogue] = Field(default_factory=list, max_length=12)
    importance: int = Field(default=2, ge=1, le=3)
    intensity: IntensityName | None = None
    sfx: list[ScriptSfx] = Field(default_factory=list, max_length=4)
    # Bibliothèque de la série : id du décor (ou null) et ids des objets visibles.
    decor: int | None = None
    objets: list[int] = Field(default_factory=list, max_length=MAX_PANEL_OBJECTS)

    _shot = field_validator("shot_type", mode="before")(normalize_shot_type)
    _intensity = field_validator("intensity", mode="before")(_hint)

    @field_validator("decor", mode="before")
    @classmethod
    def _no_decor(cls, v: Any) -> Any:
        return None if v in ("", "null", "aucun") else v

    @field_validator("objets", mode="before")
    @classmethod
    def _no_objects(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("objets")
    @classmethod
    def _unique_objects(cls, v: list[int]) -> list[int]:
        return list(dict.fromkeys(v))

    @field_validator("characters")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for name in v:
            if name and name not in out:
                out.append(name)
        return out


class ScriptPage(_LLMModel):
    panels: list[ScriptPanel] = Field(min_length=1, max_length=MAX_PANELS_PER_PAGE)
    rythme: RythmeName | None = None

    _rythme = field_validator("rythme", mode="before")(_hint)


class ScriptOutput(_LLMModel):
    pages: list[ScriptPage] = Field(min_length=1, max_length=MAX_PAGES)
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


ERROR_LABELS = {
    "pages": "page",
    "panels": "case",
    "dialogues": "réplique",
    "characters": "personnage",
    "sfx": "onomatopée",
    "objets": "objet",
}


class ScriptError(Exception):
    """Échec de l'étape scénario, message lisible par l'utilisateur."""


class ScriptValidationError(ValueError):
    pass


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_script(text: str, library: SeriesLibrary | None = None) -> ScriptOutput:
    """Valide la réponse brute du LLM ; `ScriptValidationError` explique ce qui ne va pas.

    Avec `library`, chaque décor et objet cité doit exister dans la bibliothèque de la série.
    """
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScriptValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise ScriptValidationError("la racine doit être un objet JSON avec « pages » et « summary »")
    try:
        out = ScriptOutput.model_validate(data)
    except ValidationError as exc:
        raise ScriptValidationError(format_errors(exc, ERROR_LABELS)) from None
    if library is not None:
        problems = [
            f"page {p} › case {c} › {problem}"
            for p, page in enumerate(out.pages, start=1)
            for c, panel in enumerate(page.panels, start=1)
            for problem in library.check_refs(panel.decor, panel.objets)
        ]
        if problems:
            extra = f" ; … et {len(problems) - 8} autre(s)" if len(problems) > 8 else ""
            raise ScriptValidationError(" ; ".join(problems[:8]) + extra)
    return out


# --- contexte -------------------------------------------------------------------
@dataclass
class ScriptContext:
    series: dict[str, Any]
    characters: list[dict[str, str]]
    previous_chapters: list[dict[str, Any]]
    chapter: dict[str, Any]
    knowledge: AgentKnowledge | None = None
    library: SeriesLibrary = field(default_factory=SeriesLibrary)

    def as_json(self) -> dict[str, Any]:
        return {
            "task": "script",
            "series": self.series,
            "characters": self.characters,
            **self.library.as_json(),
            "previous_chapters": self.previous_chapters,
            "chapter": self.chapter,
            "shot_types": list(SHOT_TYPES),
            "bubble_kinds": list(BUBBLE_KINDS),
            "intensities": list(INTENSITIES),
            "rythmes": list(RYTHMES),
        }


DIRECTION_LABELS = {"rtl": "de droite à gauche (manga)", "ltr": "de gauche à droite (BD, comics)"}


def knowledge_query(chapter: Chapter) -> str:
    """Requête de recherche du savoir-faire pour un chapitre : titre, synopsis, style de la série."""
    return "\n".join(p for p in (chapter.title, chapter.synopsis, chapter.project.style) if p and p.strip())


def build_context(
    session: Session, chapter: Chapter, *, max_previous: int, knowledge: KnowledgeBase | None = None
) -> ScriptContext:
    series = chapter.project
    characters = session.scalars(
        select(Character).where(Character.project_id == series.id).order_by(Character.name)
    ).all()
    previous = session.scalars(
        select(Chapter)
        .where(Chapter.project_id == series.id, Chapter.number < chapter.number)
        .order_by(Chapter.number.desc())
        .limit(max_previous)
    ).all()
    return ScriptContext(
        series={
            "title": series.title,
            "style": series.style,
            "reading_direction": series.reading_direction.value,
        },
        characters=[{"name": c.name, "description": c.visual_description} for c in characters],
        previous_chapters=[
            {"number": c.number, "title": c.title, "summary": c.summary or "(pas encore de résumé)"}
            for c in reversed(previous)
        ],
        chapter={
            "number": chapter.number,
            "title": chapter.title,
            "synopsis": chapter.synopsis,
            "target_pages": chapter.target_page_count,
        },
        knowledge=knowledge.for_agent(session, AGENT, series.id, knowledge_query(chapter)) if knowledge else None,
        library=SeriesLibrary.load(session, series.id),
    )


def _render(template: str, values: dict[str, str], part: str) -> str:
    try:
        return string.Template(template).substitute(values)
    except KeyError as exc:
        raise PresetError(f"presets/prompts : variable inconnue ${exc.args[0]} dans « {part} »") from None
    except ValueError as exc:
        raise PresetError(f"presets/prompts : gabarit « {part} » invalide ({exc})") from None


def render_messages(prompt: PromptPreset, ctx: ScriptContext) -> list[ChatMessage]:
    chars = "\n".join(f"- {c['name']} : {c['description'] or '(sans description)'}" for c in ctx.characters)
    prev = "\n".join(
        f"- Chapitre {c['number']}{' — ' + c['title'] if c['title'] else ''} : {c['summary']}"
        for c in ctx.previous_chapters
    )
    values = {
        "series_title": ctx.series["title"],
        "series_style": ctx.series["style"] or "(non précisé)",
        "reading_direction": DIRECTION_LABELS.get(ctx.series["reading_direction"], ctx.series["reading_direction"]),
        "characters": chars or "(aucun personnage enregistré)",
        "decors": ctx.library.text("decors") or "(aucun décor enregistré : « decor » vaut null)",
        "objets": ctx.library.text("objets") or "(aucun objet enregistré : « objets » reste vide)",
        "previous_chapters": prev or "(premier chapitre de la série)",
        "chapter_number": str(ctx.chapter["number"]),
        "chapter_title": ctx.chapter["title"] or "sans titre",
        "synopsis": ctx.chapter["synopsis"],
        "target_pages": str(ctx.chapter["target_pages"]),
        "shot_types": ", ".join(SHOT_TYPES),
        "bubble_kinds": ", ".join(BUBBLE_KINDS),
        "intensities": ", ".join(INTENSITIES),
        "rythmes": ", ".join(RYTHMES),
        "context_json": json.dumps(ctx.as_json(), ensure_ascii=False, indent=2),
        "savoir_faire": (ctx.knowledge.savoir_faire() if ctx.knowledge else "")
        or "(aucun savoir-faire pour cet agent)",
        "bible": (ctx.knowledge.bible_text() if ctx.knowledge else "") or "(pas encore de bible pour cette série)",
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- appel du LLM avec relances -------------------------------------------------
Progress = Callable[[int, str], None]


@dataclass
class ScriptRun:
    output: ScriptOutput
    attempts: int
    messages: list[ChatMessage]


def run_script(llm: LLMProvider, prompt: PromptPreset, ctx: ScriptContext, progress: Progress) -> ScriptRun:
    messages = render_messages(prompt, ctx)
    total = 1 + prompt.max_retries
    last_error = ""
    for attempt in range(1, total + 1):
        progress(10 + (attempt - 1) * 25, f"Écriture du découpage par le LLM (essai {attempt}/{total})…")
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise ScriptError(f"Le LLM n'a pas pu répondre : {exc}") from exc
            last_error = str(exc)
            progress(10 + attempt * 25, f"Le LLM n'a pas répondu ({exc}), nouvel essai…")
            continue
        try:
            output = parse_script(result.text, ctx.library)
        except ScriptValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                progress(10 + attempt * 25, f"Réponse invalide ({last_error[:160]}), nouvel essai…")
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return ScriptRun(output=output, attempts=attempt, messages=messages)
    raise ScriptError(f"Le LLM a renvoyé un découpage invalide {total} fois de suite. Dernière erreur : {last_error}")


# --- enregistrement -------------------------------------------------------------
def save_script(session: Session, chapter: Chapter, output: ScriptOutput) -> list[Page]:
    """Remplace les pages « story » du chapitre ; les pages bonus / de garde sont conservées à la suite."""
    by_name = {
        c.name.casefold(): c.id
        for c in session.scalars(select(Character).where(Character.project_id == chapter.project_id))
    }
    for page in list(chapter.pages):
        if page.kind == PageKind.story:
            chapter.pages.remove(page)
            session.delete(page)
    session.flush()
    kept = list(chapter.pages)
    for i, page in enumerate(kept):  # libère les numéros 1..n sans violer l'unicité
        page.number = -(i + 1)
    session.flush()

    created: list[Page] = []
    for p_index, sp in enumerate(output.pages):
        page = Page(chapter_id=chapter.id, number=p_index + 1, kind=PageKind.story, rythme=sp.rythme)
        for i, sc in enumerate(sp.panels):
            panel = Panel(
                index=i,
                description=sc.description,
                character_names=list(sc.characters),
                character_ids=[by_name[n.casefold()] for n in sc.characters if n.casefold() in by_name],
                shot_type=sc.shot_type,
                importance=sc.importance,
                intensity=sc.intensity,
                decor_id=sc.decor,
                object_ids=list(sc.objets),
            )
            for j, d in enumerate(sc.dialogues):
                panel.bubbles.append(
                    Bubble(
                        order=j,
                        speaker_name=d.speaker,
                        speaker_id=by_name.get(d.speaker.casefold()),
                        text=d.text,
                        kind=BubbleKind(d.kind),
                    )
                )
            for k, fx in enumerate(sc.sfx):
                panel.bubbles.append(
                    Bubble(
                        order=len(sc.dialogues) + k,
                        text=fx.text,
                        kind=BubbleKind.sfx,
                        sfx={"intensity": fx.intensity} if fx.intensity else None,
                    )
                )
            page.panels.append(panel)
        chapter.pages.append(page)
        created.append(page)
    for i, page in enumerate(kept):
        page.number = len(created) + i + 1
    chapter.summary = output.summary
    if chapter.status == ChapterStatus.draft:
        chapter.status = ChapterStatus.script
    session.flush()
    return created


# --- job ------------------------------------------------------------------------
def record_run(
    session: Session, chapter: Chapter, knowledge: AgentKnowledge, *, job_id: int | None, model: str | None
) -> LLMRun:
    """Garde la trace de ce que l'agent a reçu (« Sources utilisées » de l'écran Scénario)."""
    run = LLMRun(
        job_id=job_id,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        agent=knowledge.role,
        model=model,
        query=knowledge.query,
        passages=[p.as_dict() for p in knowledge.passages],
        bible=knowledge.bible.as_dict() if knowledge.bible else None,
        collections=knowledge.collections,
    )
    session.add(run)
    return run


def script_job(
    db: Database,
    presets: PresetRegistry,
    llm: LLMProvider,
    chapter_id: int,
    *,
    knowledge: KnowledgeBase | None = None,
    job_id: int | None = None,
) -> Callable[[Progress], str]:
    """Fonction exécutée par le `JobRunner` pour « Découper » un chapitre."""

    def run(progress: Progress) -> str:
        prompt = presets.prompt("script")
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ScriptError("Chapitre introuvable (supprimé pendant le découpage ?)")
            progress(5, "Préparation du contexte (série, personnages, décors et objets, chapitres précédents, bible…)…")
            ctx = build_context(session, chapter, max_previous=prompt.max_previous_chapters, knowledge=knowledge)
            if ctx.knowledge is not None:
                record_run(session, chapter, ctx.knowledge, job_id=job_id, model=getattr(llm, "model", llm.name))
                session.commit()
        # Pas de session ouverte pendant l'appel au LLM (qui peut durer plusieurs minutes).
        run = run_script(llm, prompt, ctx, progress)
        # (aucun rapport de progression dans la transaction d'écriture : SQLite n'a qu'un écrivain)
        progress(85, "Enregistrement des pages, cases et bulles, puis mise en page automatique…")
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ScriptError("Chapitre introuvable (supprimé pendant le découpage ?)")
            pages = save_script(session, chapter, run.output)
            layout_pages(presets, pages)
            session.commit()
            n_panels = sum(len(p.panels) for p in pages)
        tries = f" en {run.attempts} essais" if run.attempts > 1 else ""
        return f"{len(pages)} pages, {n_panels} cases{tries}"

    return run
