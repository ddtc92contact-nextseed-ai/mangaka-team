"""Couverture d'un tome : illustration de 1re de couverture par un flux ComfyUI dédié (presets/cover.yaml).

- `generation_size` / `clear_zone_text` / `cover_style` (purs) : taille générée au ratio du format de
  couverture, fond perdu compris (plus grand côté `long_side`), zone du logo à garder dégagée, style de la
  série avec le rendu couleur de cover.yaml — la couverture est TOUJOURS en couleur, même pour une série en
  noir et blanc : jamais le filtre des mots de couleur des séries N&B (#142) ;
- `cover_brief` / `write_cover_prompt` : prompt rédigé par le LLM du Dessinateur (presets/prompts/
  redacteur-couverture.yaml) d'après la bible, les personnages choisis et l'intention de l'auteur ; éditable ;
- `finish_cover_prompt` : phrase d'ouverture en tête, règles de cover.yaml (zone du logo dégagée, aucun
  texte) toujours à la fin ;
- `enqueue_cover` : un job `cover` dans la file sérielle de ComfyUI (une génération à la fois, progression et
  annulation comme les cases), refusé si une couverture du tome est déjà en file ;
- `CoverExecutor` : génère l'illustration (images de référence des personnages, seed enregistrée), l'agrandit
  avec l'agrandisseur de la finition d'impression jusqu'au DPI du format, la recadre au pixel près (fond perdu
  compris) → nouvelle `VolumeCover`, retenue d'office si le tome n'en a pas encore.

Aucun nom de modèle, de workflow ni de nœud ici : tout vient des presets.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from PIL import Image
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..presets import (
    CoverFormat,
    CoverSettings,
    LoadedUpscaler,
    LoadedWorkflow,
    LoraSpec,
    PresetError,
    PresetRegistry,
    PromptPreset,
    build_upscale_workflow,
    build_workflow,
)
from ..providers.comfyui import ComfyUIClient, ComfyUIError, ComfyUIInterruptedError, ComfyUITimeoutError
from ..providers.comfyui.base import ImageRef
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.comfy_folders import ComfyFolders, series_folder, transit
from ..store.comfy_folders import entry_folder as comfy_entry_folder
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import Character, Job, JobStatus, Project, Volume, VolumeCover
from ..validation import format_errors
from .finishing import finish_plan
from .generation import GenerationError, split_trigger_words
from .jobs import JobReporter
from .knowledge import render_bible
from .prompt import build_negative_prompt
from .prompt_writer import (
    LANGUAGE_NAMES,
    MAX_RATIO,
    MIN_RATIO,
    PromptValidationError,
    WrittenPrompt,
    clean_paragraph,
    image_tag,
    load_json_object,
    mentions,
    reference_problems,
    with_lead,
    with_style,
    word_count,
)
from .script import _render
from .style import series_monochrome, series_style, series_style_lead

STEP = "cover"
ACTIVE = (JobStatus.pending, JobStatus.running)
TASK = "cover_prompt"


class CoverError(GenerationError):
    """Erreur lisible (en français) d'une couverture."""


# --- géométrie (pur) ---------------------------------------------------------------------
def generation_size(fmt: CoverFormat, long_side: int, multiple: int = 16) -> tuple[int, int]:
    """Taille générée : ratio du format fond perdu compris, plus grand côté `long_side`, côtés multiples de
    `multiple` (arrondis au plus proche)."""
    fw, fh = fmt.full_px
    if fh >= fw:
        w, h = long_side * fw / fh, float(long_side)
    else:
        w, h = float(long_side), long_side * fh / fw
    return max(multiple, round(w / multiple) * multiple), max(multiple, round(h / multiple) * multiple)


def clear_zone_text(fmt: CoverFormat) -> str:
    """Zone du logo à garder dégagée, en mots pour le modèle (« the top 28% of the image »)."""
    zone = fmt.clear_zone
    if zone is None:
        return "the top quarter of the image"
    full_h = fmt.full_mm[1]
    top = (fmt.bleed_mm + zone.y_mm) / full_h
    bottom = (fmt.bleed_mm + zone.y_mm + zone.height_mm) / full_h
    if top <= 0.15:
        return f"the top {math.ceil(bottom * 100)}% of the image"
    if bottom >= 0.85:
        return f"the bottom {math.ceil((1 - top) * 100)}% of the image"
    return f"the horizontal band between {math.floor(top * 100)}% and {math.ceil(bottom * 100)}% of the image height"


def fit_exact(data: bytes, width: int, height: int, dpi: int) -> bytes:
    """Image posée « au remplissage » dans `width` × `height` (agrandie si besoin, recadrage centré), PNG au DPI."""
    with Image.open(io.BytesIO(data)) as src:
        img = src.convert("RGB")
    scale = max(width / img.width, height / img.height)
    if abs(scale - 1) > 1e-9:
        img = img.resize(
            (max(width, math.ceil(img.width * scale - 1e-6)), max(height, math.ceil(img.height * scale - 1e-6))),
            Image.Resampling.LANCZOS,
        )
    left, top = (img.width - width) // 2, (img.height - height) // 2
    img = img.crop((left, top, left + width, top + height))
    out = io.BytesIO()
    img.save(out, format="PNG", dpi=(dpi, dpi))
    return out.getvalue()


# --- style en couleur ----------------------------------------------------------------------
def _colour_series(series: Project, rendering: str) -> Project:
    """Copie détachée de la série avec le rendu couleur de la couverture (jamais ajoutée à une session). Série
    en noir et blanc : sans son LoRA de style (calibré pour le N&B) ni ses mots déclencheurs."""
    values = {attr.key: getattr(series, attr.key) for attr in sa_inspect(Project).column_attrs}
    values["style_rendering"] = rendering
    return Project(**values)


@dataclass(frozen=True)
class CoverStyle:
    lead: str  # phrase d'ouverture de la couverture (cover.yaml)
    style: str  # mots-clés de style de la série, rendu couleur
    monochrome_series: bool  # la série est en noir et blanc (la couverture, jamais)


def cover_style(presets: PresetRegistry, series: Project, cover: CoverSettings) -> CoverStyle:
    """Style de la couverture : genre, ton et réglages de la série avec le rendu couleur de cover.yaml ; jamais
    le rendu ni les réglages N&B de la série, jamais de règle « pas de mot de couleur »."""
    monochrome = series_monochrome(presets, series)
    colour = _colour_series(series, cover.rendering)
    if monochrome:
        colour.style_lora_name = None
    lead = cover.lead.strip() or series_style_lead(presets, colour)
    return CoverStyle(lead=lead, style=series_style(presets, colour), monochrome_series=monochrome)


def cover_rules(cover: CoverSettings, fmt: CoverFormat) -> list[str]:
    values = {"clear_zone": clear_zone_text(fmt)}
    return [_render(rule, values, "rules").strip() for rule in cover.rules if rule.strip()]


def finish_cover_prompt(text: str, style: CoverStyle, rules: list[str]) -> str:
    """Prompt envoyé : phrase d'ouverture en tête, puis le texte, puis les règles (zone du logo, aucun texte)
    qui manquent. Aucun filtre de couleur, même pour une série en noir et blanc."""
    out = with_lead(clean_paragraph(text), style.lead)
    for rule in rules:
        if rule.casefold() not in out.casefold():
            out = f"{out.rstrip()}{'' if out.rstrip().endswith(('.', '!', '?', '…')) else '.'} {rule}"
    return out.strip()


# --- personnages ---------------------------------------------------------------------------
def cover_characters(session: Session, volume: Volume) -> list[Character]:
    """Personnages choisis pour la couverture, dans l'ordre choisi (fiches disparues ou d'une autre série écartées)."""
    ids = [int(i) for i in volume.cover_character_ids or []]
    if not ids:
        return []
    rows = session.scalars(
        select(Character)
        .where(Character.project_id == volume.project_id, Character.id.in_(ids))
        .options(selectinload(Character.reference_images))
    )
    by_id = {c.id: c for c in rows}
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]


def referenced(characters: list[Character], slots: int) -> list[Character]:
    """Personnages dont l'image principale part en référence (ceux qui en ont une), dans la limite des emplacements."""
    return [c for c in characters if c.reference_images][:slots]


# --- rédaction du prompt -----------------------------------------------------------------
@dataclass
class CoverBrief:
    series: str
    volume: str
    intent: str
    characters: list[dict[str, str]]  # {name, details}
    references: list[dict[str, str]]  # {tag, name}
    bible: str
    style: CoverStyle
    clear_zone: str
    language: str = "en"
    min_words: int = 90
    max_words: int = 260
    extra: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "task": TASK,
            "series": self.series,
            "volume": self.volume,
            "intent": self.intent,
            "characters": self.characters,
            "references": self.references,
            "style_lead": self.style.lead,
            "style": self.style.style,
            "clear_zone": self.clear_zone,
            "language": self.language,
            "min_words": self.min_words,
            "max_words": self.max_words,
        }


def volume_label(volume: Volume) -> str:
    return f"Tome {volume.number}" + (f" — {volume.title.strip()}" if volume.title.strip() else "")


def _details(c: Character) -> str:
    parts = [" ".join((c.visual_description or "").split()).rstrip(" ."), *(k.strip() for k in c.prompt_keywords or [])]
    if c.lora_name:
        parts += split_trigger_words(c.lora_trigger_words)
    return ", ".join(dict.fromkeys(p for p in parts if p))


def cover_brief(session: Session, presets: PresetRegistry, volume: Volume, series: Project) -> CoverBrief:
    cover = presets.require_cover()
    fmt = presets.cover_format(volume.cover_format)
    prompt = presets.prompt(cover.prompt)
    loaded = presets.workflow(cover.workflow)
    chars = cover_characters(session, volume)
    refs = referenced(chars, len(loaded.preset.reference_images))
    bible = render_bible(session, series.id, max_tokens=presets.knowledge.bible_max_tokens)
    return CoverBrief(
        series=series.title,
        volume=volume_label(volume),
        intent=" ".join((volume.cover_intent or "").split()),
        characters=[{"name": c.name, "details": _details(c)} for c in chars],
        references=[{"tag": image_tag(i), "name": c.name} for i, c in enumerate(refs, start=1)],
        bible=bible.text if bible is not None else "",
        style=cover_style(presets, series, cover),
        clear_zone=clear_zone_text(fmt),
        language=prompt.language or "en",
        min_words=prompt.min_words or 90,
        max_words=prompt.max_words or 260,
    )


def cover_messages(prompt: PromptPreset, brief: CoverBrief) -> list[ChatMessage]:
    chars = "\n".join(f"- {c['name']}: {c['details'] or '(no description)'}" for c in brief.characters)
    refs = "\n".join(
        f"- {r['tag']} is the identity reference for {r['name']}: keep the face, hair and outfit; ignore its pose,"
        " framing and background."
        for r in brief.references
    )
    values = {
        "language": brief.language,
        "language_name": LANGUAGE_NAMES.get(brief.language, brief.language),
        "min_words": str(brief.min_words),
        "max_words": str(brief.max_words),
        "series": brief.series,
        "volume": brief.volume,
        "intent": brief.intent or "(free: an iconic image of the main characters that sums up the volume)",
        "characters": chars or "(no character chosen: an evocative place or symbol of the series)",
        "character_names": ", ".join(c["name"] for c in brief.characters) or "(none)",
        "references": refs or "(no reference image)",
        "image_tags": ", ".join(r["tag"] for r in brief.references) or "(none)",
        "bible": brief.bible or "(nothing specific)",
        "style_lead": brief.style.lead or "(none)",
        "style": brief.style.style or "(none)",
        "clear_zone": brief.clear_zone,
        "context_json": json.dumps(brief.as_json(), ensure_ascii=False, indent=2),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


def parse_cover(text: str, brief: CoverBrief) -> WrittenPrompt:
    """Valide la réponse du LLM : schéma, langue, images citées, personnages nommés, longueur. Aucune règle de
    couleur : la couverture est en couleur."""
    data = load_json_object(text, "« prompt »")
    try:
        out = WrittenPrompt.model_validate(data)
    except ValidationError as exc:
        raise PromptValidationError(format_errors(exc)) from None
    paragraph = clean_paragraph(out.prompt)
    problems: list[str] = []
    if out.language != brief.language:
        problems.append(f"language : « {out.language} » au lieu de « {brief.language} »")
    problems += reference_problems(paragraph, len(brief.references))
    missing = [c["name"] for c in brief.characters if not mentions(paragraph, c["name"])]
    if missing:
        problems.append(f"personnages de la couverture non nommés : {', '.join(missing)}")
    words = word_count(paragraph)
    low, high = math.floor(brief.min_words * MIN_RATIO), math.ceil(brief.max_words * MAX_RATIO)
    if words < low:
        problems.append(f"prompt trop court ({words} mots ; entre {brief.min_words} et {brief.max_words} attendus)")
    elif words > high:
        problems.append(f"prompt trop long ({words} mots ; entre {brief.min_words} et {brief.max_words} attendus)")
    if problems:
        raise PromptValidationError(" ; ".join(problems))
    finished = with_style(with_lead(paragraph, brief.style.lead), brief.style.style)
    return out.model_copy(update={"prompt": finished})


@dataclass
class CoverWriteRun:
    prompt: str
    notes: str
    attempts: int


def write_cover_prompt(llm: LLMProvider, prompt: PromptPreset, brief: CoverBrief) -> CoverWriteRun:
    """Prompt de couverture validé, ou `CoverError` après `1 + max_retries` tentatives."""
    messages = cover_messages(prompt, brief)
    total = 1 + prompt.max_retries
    last = ""
    for attempt in range(1, total + 1):
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise CoverError(f"le LLM n'a pas pu répondre : {exc}") from exc
            last = str(exc)
            continue
        try:
            out = parse_cover(result.text, brief)
        except PromptValidationError as exc:
            last = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
            continue
        return CoverWriteRun(prompt=out.prompt, notes=out.notes or "", attempts=attempt)
    raise CoverError(f"réponse invalide {total} fois de suite ({last}) : écris le prompt à la main")


# --- mise en file ----------------------------------------------------------------------------
def active_cover_jobs(session: Session, volume_id: int) -> list[Job]:
    rows = session.scalars(select(Job).where(Job.step == STEP, Job.status.in_(ACTIVE)).order_by(Job.id))
    return [j for j in rows if (j.params or {}).get("volume_id") == volume_id]


def enqueue_cover(
    session: Session, presets: PresetRegistry, volume: Volume, *, seed: int | None = None, prompt: str | None = None
) -> Job:
    """Met en file la génération de la couverture du tome (sans commit). `prompt` : celui du tome par défaut."""
    cover = presets.require_cover()
    fmt = presets.cover_format(volume.cover_format)
    loaded = presets.workflow(cover.workflow)
    series = session.get(Project, volume.project_id)
    if series is None:
        raise CoverError("série introuvable")
    text = (prompt if prompt is not None else volume.cover_prompt or "").strip()
    if not text:
        raise CoverError("prompt vide : fais-le rédiger par l'IA ou écris-le avant de générer")
    if active_cover_jobs(session, volume.id):
        raise CoverError("une génération de couverture est déjà en cours pour ce tome : attends sa fin")
    style = cover_style(presets, series, cover)
    final = finish_cover_prompt(text, style, cover_rules(cover, fmt))
    width, height = generation_size(fmt, cover.long_side, cover.multiple)
    chars = cover_characters(session, volume)
    full_w, full_h = fmt.full_px
    job = Job(
        project_id=series.id,
        step=STEP,
        status=JobStatus.pending,
        message="En attente…",
        params={
            "volume_id": volume.id,
            "volume_number": volume.number,
            "cover_format": fmt.id,
            "preset": loaded.preset.id,
            "tier": loaded.preset.tier.name if loaded.preset.tier else None,
            "prompt": final,
            "seed": seed,
            "width": width,
            "height": height,
            "full_width": full_w,
            "full_height": full_h,
            "dpi": fmt.dpi,
            "character_ids": [c.id for c in chars],
        },
    )
    session.add(job)
    return job


# --- ménage ---------------------------------------------------------------------------------
def prune_covers(session: Session, volume: Volume, keep: int | None) -> list[str]:
    """Garde les `keep` dernières versions (la retenue toujours), efface les plus anciennes (sans commit) ;
    renvoie les fichiers à effacer après le commit."""
    if keep is None:
        return []
    rows = sorted(volume.covers, key=lambda c: c.id, reverse=True)
    paths: list[str] = []
    for c in rows[keep:]:
        if c.id == volume.selected_cover_id:
            continue
        paths.append(c.path)
        volume.covers.remove(c)
    return paths


# --- exécution d'un job ---------------------------------------------------------------------
@dataclass
class _Plan:
    loaded: LoadedWorkflow
    upscaler: LoadedUpscaler | None
    params: dict[str, Any]
    loras: list[LoraSpec]
    references: list[dict[str, Any]]
    reference_data: list[bytes]
    folder: str  # dossier data/ des versions
    prefix: str  # préfixe ComfyUI (sous-dossier _transit de la série)
    upload_folder: str
    full: tuple[int, int]
    dpi: int
    keep: int | None


def resolve_cover_upscaler(presets: PresetRegistry, cover: CoverSettings, series: Project) -> LoadedUpscaler | None:
    """Agrandisseur de cover.yaml, sinon celui de la série, sinon celui de defaults.yaml (None : aucun)."""
    for candidate in (cover.upscaler, series.upscaler, presets.default_upscaler):
        if candidate and candidate in presets.upscalers:
            return presets.upscalers[candidate]
    return None


class CoverExecutor:
    """Exécute un job `cover` (appelé par la file sérielle de ComfyUI, un à la fois)."""

    def __init__(
        self,
        db: Database,
        presets: PresetRegistry,
        files: FileStore,
        comfyui: ComfyUIClient | None,
        *,
        comfyui_error: str | None = None,
        poll_s: float = 1.0,
        presets_for: Callable[[int | None], PresetRegistry] | None = None,
        folders: ComfyFolders | None = None,
    ) -> None:
        self.db = db
        self.files = files
        self.comfyui = comfyui
        self.comfyui_error = comfyui_error
        self.poll_s = poll_s
        self.presets_for = presets_for or (lambda _project_id: presets)
        self.folders = folders
        self._prompt_ids: dict[int, str] = {}

    def interrupt(self, job_id: int) -> None:
        prompt_id = self._prompt_ids.get(job_id)
        if self.comfyui is not None and prompt_id is not None:
            self.comfyui.interrupt(prompt_id)

    def _plan(self, job_id: int) -> _Plan:
        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            params = dict(job.params or {}) if job is not None else {}
            volume = session.get(Volume, int(params.get("volume_id") or 0))
            if job is None or volume is None:
                raise CoverError("tome introuvable (supprimé entre-temps ?)")
            series = session.get(Project, volume.project_id)
            assert series is not None
            presets = self.presets_for(series.id)
            cover = presets.require_cover()
            fmt = presets.cover_format(str(params.get("cover_format") or volume.cover_format))
            loaded = presets.workflow(str(params.get("preset") or cover.workflow))
            ids = [int(i) for i in params.get("character_ids") or []]
            by_id = {c.id: c for c in cover_characters(session, volume)}
            chars = [by_id[i] for i in ids if i in by_id]
            references: list[dict[str, Any]] = []
            reference_data: list[bytes] = []
            for slot, character in enumerate(referenced(chars, len(loaded.preset.reference_images)), start=1):
                image = character.reference_images[0]
                path = self.files.absolute(image.path)
                if not path.is_file():
                    raise CoverError(f"image de référence de {character.name} absente de data/ ({image.path})")
                ext = PurePosixPath(image.path).suffix or ".png"
                references.append(
                    {
                        "kind": "character",
                        "slot": slot,
                        "character_id": character.id,
                        "name": character.name,
                        "image_id": image.id,
                        "subfolder": comfy_entry_folder(character, series),
                        "filename": f"reference-{image.id}{ext}",
                    }
                )
                reference_data.append(path.read_bytes())
            # LoRA d'identité des personnages ; LoRA de style seulement pour une série en couleur (un LoRA
            # calibré pour le N&B tirerait la couverture vers le noir et blanc).
            loras: list[LoraSpec] = []
            if series.style_lora_name and not series_monochrome(presets, series):
                loras.append(LoraSpec(series.style_lora_name, series.style_lora_weight, "style"))
            for c in chars:
                if c.lora_name and all(lo.name != c.lora_name for lo in loras):
                    loras.append(LoraSpec(c.lora_name, c.lora_weight, c.name))
            negative = ", ".join(
                p
                for p in (str(loaded.preset.defaults.get("negative_prompt", "")).strip(), cover.negative_prompt.strip())
                if p
            )
            prefix = transit(f"{series_folder(series)}/tomes/tome-{volume.number:02d}/couverture")
            mapped: dict[str, Any] = {
                "positive_prompt": str(params.get("prompt") or ""),
                "negative_prompt": build_negative_prompt(negative, presets.image_prompt),
                "seed": params.get("seed"),
                "width": int(params.get("width") or 0) or generation_size(fmt, cover.long_side, cover.multiple)[0],
                "height": int(params.get("height") or 0) or generation_size(fmt, cover.long_side, cover.multiple)[1],
            }
            if "filename_prefix" in loaded.preset.mapping:
                mapped["filename_prefix"] = prefix
            return _Plan(
                loaded=loaded,
                upscaler=resolve_cover_upscaler(presets, cover, series),
                params=mapped,
                loras=loras,
                references=references,
                reference_data=reference_data,
                folder=f"projects/{series.id}/volumes/{volume.id}/covers",
                prefix=prefix,
                upload_folder=f"{series_folder(series)}/tomes/tome-{volume.number:02d}",
                full=fmt.full_px,
                dpi=fmt.dpi,
                keep=cover.versions_kept,
            )

    def _wait(
        self,
        job_id: int,
        workflow: dict[str, Any],
        output_node: str,
        timeout_s: float,
        what: str,
        report: JobReporter,
        cancel: threading.Event,
        span: tuple[int, int],
    ) -> ImageRef:
        assert self.comfyui is not None
        comfy = self.comfyui
        prompt_id = comfy.queue_prompt(workflow)
        self._prompt_ids[job_id] = prompt_id
        last = [-1]
        lo, hi = span

        def on_progress(value: int, maximum: int) -> None:
            pct = lo + int((hi - lo) * value / maximum)
            if pct != last[0]:
                last[0] = pct
                report(pct, f"{what} : étape {value}/{maximum}")

        try:
            refs = comfy.wait_for_images(
                prompt_id,
                output_node,
                timeout_s=timeout_s,
                poll_s=self.poll_s,
                on_progress=on_progress,
                should_stop=cancel.is_set,
            )
        except ComfyUITimeoutError:
            with contextlib.suppress(ComfyUIError):
                comfy.interrupt(prompt_id)
            raise CoverError(f"ComfyUI n'a pas terminé ({what.lower()}) en {timeout_s:.0f} s") from None
        finally:
            self._prompt_ids.pop(job_id, None)
        return refs[0]

    def __call__(self, job_id: int, report: JobReporter, cancel: threading.Event) -> str:
        if self.comfyui is None:
            raise CoverError(f"ComfyUI indisponible : {self.comfyui_error or 'client non configuré'}")
        comfy = self.comfyui
        t0 = time.monotonic()
        report(2, "Préparation du prompt et du workflow de couverture…")
        try:
            plan = self._plan(job_id)
        except PresetError as exc:
            raise CoverError(str(exc)) from None
        preset = plan.loaded.preset

        uploaded: list[str] = []
        for ref, data in zip(plan.references, plan.reference_data, strict=True):
            report(4, f"Envoi de la référence de {ref['name']} à ComfyUI…")
            uploaded.append(comfy.upload_image(data, ref["filename"], subfolder=ref["subfolder"]))
        built = build_workflow(plan.loaded, plan.params, reference_images=uploaded, loras=plan.loras)
        if cancel.is_set():
            raise ComfyUIInterruptedError("génération annulée")

        report(8, f"Envoi du workflow « {preset.name} » à ComfyUI…")
        ref = self._wait(
            job_id, built.workflow, built.output_node, preset.timeout_s, "Génération", report, cancel, (10, 70)
        )
        report(72, "Récupération de l'illustration…")
        generated = comfy.fetch_image(ref)
        if self.folders is not None:
            self.folders.discard_output(ref)
        with Image.open(io.BytesIO(generated)) as im:
            gen_w, gen_h = im.size
        full_w, full_h = plan.full
        fplan = finish_plan(gen_w, gen_h, full_w, full_h, plan.dpi, 1.0)
        upscaled = generated
        upscaler_info: dict[str, Any] = {"upscaler": None, "upscaler_name": None}
        if fplan.needed:
            if plan.upscaler is None:
                upscaler_info["upscale_fallback"] = "aucun agrandisseur configuré : agrandi sans modèle (Pillow)"
            else:
                up = plan.upscaler
                report(74, f"Agrandissement « {up.preset.name} » ×{fplan.factor:.2f} → {fplan.width}×{fplan.height}…")
                name = comfy.upload_image(generated, f"couverture-{job_id}.png", subfolder=plan.upload_folder)
                built_up = build_upscale_workflow(
                    up, name, fplan.width, fplan.height, filename_prefix=f"{plan.prefix}-finition"
                )
                if cancel.is_set():
                    raise ComfyUIInterruptedError("génération annulée")
                ref_up = self._wait(
                    job_id,
                    built_up.workflow,
                    built_up.output_node,
                    up.preset.timeout_s,
                    "Agrandissement",
                    report,
                    cancel,
                    (76, 92),
                )
                upscaled = comfy.fetch_image(ref_up)
                if self.folders is not None:
                    self.folders.discard_output(ref_up)
                upscaler_info = {"upscaler": up.preset.id, "upscaler_name": up.preset.name}
        report(94, "Recadrage au format (fond perdu compris)…")
        final = fit_exact(upscaled, full_w, full_h, plan.dpi)
        stored = self.files.save_image(final, plan.folder)
        duration_ms = int((time.monotonic() - t0) * 1000)

        with self.db.session_scope() as session:
            job = session.get(Job, job_id)
            params = dict(job.params or {}) if job is not None else {}
            volume = session.get(Volume, int(params.get("volume_id") or 0))
            if job is None or volume is None:
                self.files.delete(stored.path)
                raise CoverError("tome supprimé pendant la génération")
            row = VolumeCover(
                volume_id=volume.id,
                job_id=job_id,
                path=stored.path,
                content_type=stored.content_type,
                width=stored.width,
                height=stored.height,
                seed=built.params["seed"],
                cover_format=str(params.get("cover_format") or volume.cover_format),
                params={
                    "preset": preset.id,
                    "preset_name": preset.name,
                    "tier": preset.tier.name if preset.tier else None,
                    "prompt": built.params["positive_prompt"],
                    "negative_prompt": built.params["negative_prompt"],
                    "seed": built.params["seed"],
                    "generated_width": gen_w,
                    "generated_height": gen_h,
                    "dpi": plan.dpi,
                    "factor": round(fplan.factor, 3),
                    **upscaler_info,
                    "loras": [lo.as_dict() for lo in built.loras],
                    "reference_images": [
                        {**{k: v for k, v in r.items() if k not in ("filename", "subfolder")}, "comfyui_name": n}
                        for r, n in zip(plan.references, uploaded, strict=True)
                    ],
                    "removed_nodes": built.removed_nodes,
                    "duration_ms": duration_ms,
                    "comfyui": comfy.name,
                },
            )
            volume.covers.append(row)
            session.flush()
            if volume.selected_cover_id is None:
                volume.selected_cover_id = row.id
            job.params = {**params, "cover_id": row.id, "seed": built.params["seed"]}
            pruned = prune_covers(session, volume, plan.keep)
            session.commit()
            count = len(volume.covers)
        for path in pruned:
            self.files.delete(path)
        return (
            f"Couverture — {stored.width}×{stored.height} px à {plan.dpi} dpi (fond perdu compris), "
            f"seed {built.params['seed']} ({count} version{'s' if count > 1 else ''})"
        )
