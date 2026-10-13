"""Traçabilité : journal des générations, verdicts de l'auteur et mesures de tonalité.

- **Journal** (`GenerationLog`) : chaque génération ComfyUI terminée ou en échec (case, croquis, passage au
  propre, réparation, angle, fiche de référence, essai de style, A/B) ajoute une ligne, jamais réécrite :
  workflow et réglages envoyés, prompts **effectivement envoyés** (après tous les filtres) et leur longueur,
  images de référence, LoRA, savoir-faire reçu, plan / angle / ambiance de la case, durée, statut, erreur,
  empreinte des consignes du rédacteur de prompt, mesures de tonalité de l'image.
- **Verdicts** (`GenerationEvent`) : chaque action de l'auteur (choisir une version, valider un croquis,
  supprimer, régénérer, recadrer, réparer, juger, choix d'un A/B) ajoute un événement lié à la génération :
  `validated` / `rejected` / `regenerated` / `edited`, raison facultative (liste fermée de
  presets/journal.yaml) et note libre.
- **Tonalité** (`measure_tonality`) : Pillow sur le CPU, jamais de GPU ; seuils et cible dans
  presets/qc_tonality.yaml.

Le journal ne bloque jamais une génération : une erreur d'écriture est notée dans le log du moteur et la
génération continue. Aucune donnée personnelle ni clé n'y entre (prompts, réglages, mesures seulement).
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageChops
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import BuiltWorkflow, LoadedWorkflow, PresetRegistry
from ..presets.schemas import TonalitySettings
from ..store.db import Database
from ..store.models import GenerationEvent, GenerationLog, ImageKind, Job, Panel, PanelImage

log = logging.getLogger("mangaka_engine")

# Sortes de génération notées dans le journal.
KINDS = {
    "panel": "Case",
    "croquis": "Croquis",
    "from_sketch": "Passage au propre",
    "inpaint": "Réparation",
    "angle": "Changer l'angle",
    "reference_sheet": "Fiche de référence",
    "style_trial": "Essai de style",
    "style_reference": "Référence de style",
}
# Générations d'une case (page Statistiques).
PANEL_KINDS = ("panel", "croquis", "from_sketch", "inpaint", "angle")

VERDICTS = {
    "validated": "Gardée",
    "rejected": "Rejetée",
    "regenerated": "Régénérée",
    "edited": "Retouchée",
}
# Verdicts qui « jugent » une génération (taux de validation) ; les autres sont comptés à part.
JUDGED = ("validated", "rejected")

MEASURES = ("dark_pct", "black_pct", "white_pct", "saturation_pct", "line_density_pct")
MEASURE_LABELS = {
    "dark_pct": "% sombre",
    "black_pct": "% noir",
    "white_pct": "% blanc",
    "saturation_pct": "Saturation",
    "line_density_pct": "Densité de trait",
}

PANEL_IMAGE = "panel_image"
REFERENCE_VARIANT = "reference_variant"
STYLE_IMAGE = "series_asset_image"  # référence de style de la série (planche de style)


# --- tonalité ----------------------------------------------------------------------------
def _mean_level(hist: Sequence[int]) -> tuple[int, int]:
    """(somme des niveaux, nombre de pixels) d'un histogramme 8 bits."""
    return sum(i * c for i, c in enumerate(hist)), sum(hist)


def measure_tonality(data: bytes, settings: TonalitySettings) -> dict[str, float]:
    """Mesures de tonalité d'une image (en %, arrondies au centième) :

    - `dark_pct` / `black_pct` / `white_pct` : part des pixels de gris < `dark_below`, < `black_below`,
      ≥ `white_from` ;
    - `saturation_pct` : saturation moyenne (canal S du HSV) ;
    - `line_density_pct` : écart moyen entre pixels voisins (horizontaux et verticaux), rapporté à 255.
    """
    with Image.open(io.BytesIO(data)) as raw:
        raw.load()
        if raw.mode in ("RGBA", "LA", "P"):
            # Transparence posée sur du papier blanc (comme à l'impression).
            rgba = raw.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, (255, 255, 255))
            rgb.paste(rgba, mask=rgba.getchannel("A"))
        else:
            rgb = raw.convert("RGB")
    gray = rgb.convert("L")
    hist = gray.histogram()
    n = sum(hist) or 1
    sat_total, _ = _mean_level(rgb.convert("HSV").getchannel("S").histogram())
    width, height = gray.size
    total = count = 0
    if width > 1:
        diff = ImageChops.difference(gray.crop((1, 0, width, height)), gray.crop((0, 0, width - 1, height)))
        s, c = _mean_level(diff.histogram())
        total, count = total + s, count + c
    if height > 1:
        diff = ImageChops.difference(gray.crop((0, 1, width, height)), gray.crop((0, 0, width, height - 1)))
        s, c = _mean_level(diff.histogram())
        total, count = total + s, count + c
    values = {
        "dark_pct": 100 * sum(hist[: settings.dark_below]) / n,
        "black_pct": 100 * sum(hist[: settings.black_below]) / n,
        "white_pct": 100 * sum(hist[settings.white_from :]) / n,
        "saturation_pct": 100 * sat_total / n / 255,
        "line_density_pct": 100 * total / count / 255 if count else 0.0,
    }
    return {k: round(v, 2) for k, v in values.items()}


def tonality_gaps(values: dict[str, float | None], settings: TonalitySettings) -> dict[str, float | None]:
    """Écart à la cible de chaque mesure (valeur − cible, en points) ; None sans cible ou sans mesure."""
    target = settings.target.model_dump()
    out: dict[str, float | None] = {}
    for key in MEASURES:
        value, goal = values.get(key), target.get(key)
        out[key] = round(value - goal, 2) if value is not None and goal is not None else None
    return out


# --- faits du workflow ---------------------------------------------------------------------
def word_count(text: str) -> int:
    return len(text.split())


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _workflow_value(loaded: LoadedWorkflow, built: BuiltWorkflow, key: str) -> Any:
    """Valeur appliquée : paramètre envoyé, sinon entrée mappée du JSON, sinon le premier nœud qui l'a."""
    if built.params.get(key) is not None:
        return built.params[key]
    target = loaded.preset.mapping.get(key)
    if target is not None:
        value = (built.workflow.get(target.node) or {}).get("inputs", {}).get(target.input)
        if _number(value) is not None:
            return value
    for node in built.workflow.values():
        value = (node.get("inputs") or {}).get(key) if isinstance(node, dict) else None
        if _number(value) is not None:
            return value
    return None


def workflow_model(workflow: dict[str, Any]) -> str | None:
    """Fichier du modèle de diffusion du workflow (UNETLoader, sinon chargeur de checkpoint)."""
    for key in ("unet_name", "ckpt_name"):
        for node in workflow.values():
            value = (node.get("inputs") or {}).get(key) if isinstance(node, dict) else None
            if isinstance(value, str) and value:
                return value
    return None


def writer_hash(presets: PresetRegistry, prompt_id: str) -> str | None:
    """Empreinte des consignes d'un rédacteur de prompt (gabarits, langue, longueur), profil compris."""
    prompt = presets.prompts.get(prompt_id)
    if prompt is None:
        return None
    return hashlib.sha256(prompt.model_dump_json().encode()).hexdigest()[:12]


def knowledge_documents(passages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fiches de savoir-faire reçues (un passage → sa fiche), jetons additionnés par fiche."""
    out: dict[Any, dict[str, Any]] = {}
    for p in passages:
        doc_id = p.get("document_id")
        if doc_id is None:
            continue
        entry = out.setdefault(
            doc_id,
            {
                "document_id": doc_id,
                "title": p.get("document_title") or p.get("title") or "",
                "collection": p.get("collection_name") or p.get("collection") or "",
                "tokens": 0,
            },
        )
        entry["tokens"] += int(p.get("tokens") or 0)
    return list(out.values())


# --- une ligne du journal -------------------------------------------------------------------
@dataclass
class JournalEntry:
    """Ligne du journal en cours de remplissage par un exécuteur ; écrite une fois, à la fin (réussite ou
    échec). Les champs sont ceux de `GenerationLog`."""

    kind: str
    job_id: int | None = None
    values: dict[str, Any] = field(default_factory=dict)
    written: bool = False

    def set(self, **values: Any) -> JournalEntry:
        self.values.update({k: v for k, v in values.items() if v is not None})
        return self

    def workflow(self, loaded: LoadedWorkflow, built: BuiltWorkflow) -> JournalEntry:
        """Workflow, réglages et prompts réellement envoyés à ComfyUI."""
        preset = loaded.preset
        positive = str(built.params.get("positive_prompt") or "")
        negative = str(built.params.get("negative_prompt") or "")
        steps, cfg = _workflow_value(loaded, built, "steps"), _workflow_value(loaded, built, "cfg")
        denoise = _workflow_value(loaded, built, "denoise") if "denoise" in preset.mapping else None
        seed = built.params.get("seed")
        return self.set(
            preset=preset.id,
            tier=preset.tier.name if preset.tier else None,
            model=workflow_model(built.workflow),
            steps=int(steps) if _number(steps) is not None else None,
            cfg=_number(cfg),
            seed=int(seed) if isinstance(seed, int) else None,
            width=built.params.get("width"),
            height=built.params.get("height"),
            denoise=_number(denoise),
            positive_prompt=positive,
            negative_prompt=negative,
            positive_chars=len(positive),
            positive_words=word_count(positive),
            negative_chars=len(negative),
            negative_words=word_count(negative),
            loras=[lo.as_dict() for lo in built.loras],
        )

    def references(self, refs: Iterable[dict[str, Any]]) -> JournalEntry:
        """Images de référence envoyées : sorte et ids (sans noms de fichiers)."""
        keep = ("slot", "kind", "id", "image_id", "variant_id", "asset_id", "version", "angle")
        return self.set(references=[{k: r[k] for k in keep if r.get(k) is not None} for r in refs])

    def measure(self, data: bytes, settings: TonalitySettings) -> JournalEntry:
        try:
            return self.set(**measure_tonality(data, settings))
        except Exception:  # noqa: BLE001 — une image illisible ici l'est déjà ailleurs : pas de mesure
            log.warning("job %s : mesures de tonalité impossibles", self.job_id, exc_info=True)
            return self

    def row(self, status: str = "succeeded", error: str | None = None) -> GenerationLog:
        known = set(GenerationLog.__table__.columns.keys())
        values = {k: v for k, v in self.values.items() if k in known}
        return GenerationLog(kind=self.kind, job_id=self.job_id, status=status, error=error, **values)

    def add(self, session: Session) -> GenerationLog | None:
        """Ajoute la ligne (génération réussie) dans la transaction de l'exécuteur (commit avec la version)."""
        if self.written:
            return None
        try:
            row = self.row()
            session.add(row)
            self.written = True
            return row
        except Exception:  # noqa: BLE001 — le journal ne fait jamais échouer une génération
            log.exception("job %s : écriture du journal impossible", self.job_id)
            return None

    def fail(self, db: Database, error: str, *, cancelled: bool = False) -> None:
        """Génération en échec ou annulée : ligne écrite dans sa propre transaction ; jamais d'exception."""
        if self.written:
            return
        try:
            with db.session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id is not None else None
                if job is not None:
                    # Échec avant la préparation : au moins la série, le chapitre, la case et le workflow.
                    params = job.params or {}
                    for key, value in (
                        ("project_id", job.project_id),
                        ("chapter_id", job.chapter_id),
                        ("panel_id", job.panel_id),
                        ("preset", params.get("preset")),
                    ):
                        if self.values.get(key) is None and value is not None:
                            self.values[key] = value
                session.add(self.row("cancelled" if cancelled else "failed", error[:2000]))
                session.commit()
            self.written = True
        except Exception:  # noqa: BLE001
            log.exception("job %s : écriture du journal impossible", self.job_id)


def failure_text(exc: Exception, described: str | None) -> str:
    return described or f"Erreur interne du moteur ({exc.__class__.__name__})"


def panel_facts(panel: Panel) -> dict[str, Any]:
    """Ids de la case et de ses parents, plan / angle / ambiance appliqués, finition (si le réglage existe)."""
    from .art_direction import applied_panel_direction

    page = panel.page
    chapter = page.chapter
    da = applied_panel_direction(panel)
    finish = getattr(panel, "finition", None) or getattr(chapter.project, "finition", None)

    def text(value: Any, size: int) -> str | None:
        return str(value)[:size] if value else None

    return {
        "project_id": chapter.project_id,
        "chapter_id": chapter.id,
        "page_id": page.id,
        "panel_id": panel.id,
        "framing": text(da.get("plan") or panel.shot_type, 100),
        "angle": text(da.get("angle"), 100),
        "mood": text(da.get("ambiance"), 200),
        "finish": text(finish, 100),
    }


def prompt_facts(
    presets: PresetRegistry, panel: Panel, writer_prompt_id: str, fragment_passages: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    """Origine du prompt de la case, empreinte du rédacteur et savoir-faire reçu par ce prompt."""
    if panel.final_prompt_manual and (panel.final_prompt or "").strip():
        return {"prompt_source": "manuel", "knowledge": []}
    if panel.prompt_source == "ia":
        sources = panel.prompt_sources or {}
        return {
            "prompt_source": "ia",
            "writer_hash": writer_hash(presets, writer_prompt_id),
            "knowledge": knowledge_documents(sources.get("passages") or []),
        }
    return {"prompt_source": panel.prompt_source or "fragments", "knowledge": knowledge_documents(fragment_passages)}


def inherited_facts(session: Session, image_kind: str, image_id: int | None) -> dict[str, Any]:
    """Origine du prompt et savoir-faire d'une génération source (passage au propre depuis un croquis,
    « Changer l'angle ») : le prompt envoyé est le sien."""
    source = log_for_image(session, image_kind, image_id)
    if source is None:
        return {}
    return {"prompt_source": source.prompt_source, "writer_hash": source.writer_hash, "knowledge": source.knowledge}


# --- verdicts ----------------------------------------------------------------------------------
def log_for_image(session: Session, image_kind: str, image_id: int | None) -> GenerationLog | None:
    """Génération qui a produit une image (la dernière ligne réussie qui la nomme)."""
    if image_id is None:
        return None
    return session.scalar(
        select(GenerationLog)
        .where(
            GenerationLog.image_kind == image_kind,
            GenerationLog.image_id == image_id,
            GenerationLog.status == "succeeded",
        )
        .order_by(GenerationLog.id.desc())
        .limit(1)
    )


def record_event(
    session: Session,
    *,
    verdict: str,
    action: str,
    image_kind: str = PANEL_IMAGE,
    image_id: int | None = None,
    panel_id: int | None = None,
    log_id: int | None = None,
    reason: str | None = None,
    note: str = "",
) -> GenerationEvent | None:
    """Ajoute un verdict de l'auteur (dans la transaction de l'appelant) ; jamais d'exception."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict inconnu : {verdict}")
    try:
        if log_id is None:
            found = log_for_image(session, image_kind, image_id)
            log_id = found.id if found is not None else None
            if panel_id is None and found is not None:
                panel_id = found.panel_id
        event = GenerationEvent(
            log_id=log_id,
            panel_id=panel_id,
            image_kind=image_kind if image_id is not None else None,
            image_id=image_id,
            verdict=verdict,
            action=action,
            reason=reason,
            note=(note or "").strip()[:2000],
        )
        session.add(event)
        return event
    except Exception:  # noqa: BLE001 — une action de l'auteur n'échoue jamais à cause du journal
        log.exception("verdict %s (%s) : écriture du journal impossible", verdict, action)
        return None


def latest_events(session: Session, log_ids: Sequence[int]) -> dict[int, GenerationEvent]:
    """Dernier verdict « jugé » (gardée / rejetée) de chaque génération."""
    out: dict[int, GenerationEvent] = {}
    ids = list(log_ids)
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for event in session.scalars(
            select(GenerationEvent)
            .where(GenerationEvent.log_id.in_(chunk), GenerationEvent.verdict.in_(JUDGED))
            .order_by(GenerationEvent.id)
        ):
            assert event.log_id is not None
            out[event.log_id] = event
    return out


def event_counts(session: Session, log_ids: Sequence[int]) -> dict[int, dict[str, int]]:
    """Nombre d'événements par verdict de chaque génération."""
    out: dict[int, dict[str, int]] = {}
    ids = list(log_ids)
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for log_id, verdict in session.execute(
            select(GenerationEvent.log_id, GenerationEvent.verdict).where(GenerationEvent.log_id.in_(chunk))
        ):
            counts = out.setdefault(log_id, {})
            counts[verdict] = counts.get(verdict, 0) + 1
    return out


def note_regenerated(session: Session, panel: Panel, action: str, *, sketch: bool = False) -> None:
    """« Régénérer » une case qui a déjà une version : verdict `regenerated` sur la version qu'elle remplace
    (la choisie, sinon la plus récente ; pour un croquis : le validé, sinon le plus récent)."""
    kind = ImageKind.croquis if sketch else ImageKind.final
    image: PanelImage | None = None
    if sketch and panel.sketch_image_id is not None:
        image = session.get(PanelImage, panel.sketch_image_id)
    if image is None:
        image = session.scalar(
            select(PanelImage)
            .where(PanelImage.panel_id == panel.id, PanelImage.kind == kind)
            .order_by(PanelImage.selected.desc(), PanelImage.version.desc())
            .limit(1)
        )
    if image is not None:
        record_event(session, verdict="regenerated", action=action, image_id=image.id, panel_id=panel.id)
