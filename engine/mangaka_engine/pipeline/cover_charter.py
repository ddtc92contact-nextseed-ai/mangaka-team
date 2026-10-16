"""Charte des couvertures d'une série (presets/cover_charter.yaml) : une charte à part de l'ADN des chapitres.

Une couverture est toujours en couleur (cover.yaml), n'a ni timing ni découpage : la charte tient la couleur
(palette de la série imposée, suggérée ou libre ; ambiance), la cohérence des personnages (personnages admis en
couverture, dont les références d'identité partent à chaque génération de la 1re et de la petite illustration de
4e) et le cadrage et l'accroche (plan préféré, place réservée au logo et au titre, sujet principal).

- `series_charter` : charte effective d'une série (réglages enregistrés, sinon `defaults` du preset ; un choix
  disparu des presets revient au défaut, signalé) ;
- `present_characters` : personnages présents sur la couverture d'un tome (choix du tome restreint à la charte,
  sinon ceux de la charte) ;
- `charter_lines` / `identity_lines` : phrases ajoutées au prompt (couleur, ambiance, cadrage, sujet ; rôle de
  chaque image de référence) ;
- `charter_format` : format de couverture avec la zone du logo de la charte (prompt « zone dégagée » et position
  du logo par défaut à la composition) ;
- `check_identity` : contrôle d'identité (couche CCIP du QC, même seuil que qc.yaml) d'une couverture générée.
  Un écart donne un avertissement, jamais un blocage.

Aucun choix ni aucune phrase en dur ici : tout vient des presets.
"""

from __future__ import annotations

import colorsys
import string
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..presets import CoverFormat, CoverZone, PresetRegistry, QCSettings
from ..presets.schemas import CoverCharterSettings
from ..providers.qc import QCProviderError
from ..store.models import Character, Project, Volume

FIELDS = ("palette_mode", "mood", "shot", "back_shot", "logo_place", "subject")
LABELS = {
    "palette_mode": "palette",
    "mood": "ambiance",
    "shot": "plan de la 1re",
    "back_shot": "plan de la 4e",
    "logo_place": "place du logo",
    "subject": "sujet principal",
}


def choices(settings: CoverCharterSettings, name: str) -> dict[str, Any]:
    """Choix bornés d'un réglage de la charte (clé → choix du preset)."""
    return {
        "palette_mode": settings.palette_modes,
        "mood": settings.moods,
        "shot": settings.shots,
        "back_shot": settings.shots,
        "logo_place": settings.logo_places,
        "subject": settings.subjects,
    }[name]


@dataclass
class Charter:
    settings: CoverCharterSettings
    values: dict[str, str]  # réglage → clé du choix (toujours connue des presets)
    character_ids: list[int]  # personnages admis en couverture (vide : tous ceux choisis sur le tome)
    saved: bool  # enregistrée sur la série (sinon : réglages par défaut)
    problems: list[str] = field(default_factory=list)  # choix enregistrés disparus des presets

    def choice(self, name: str) -> Any:
        return choices(self.settings, name)[self.values[name]]


def series_charter(presets: PresetRegistry, series: Project) -> Charter | None:
    """Charte effective de la série ; None : cover_charter.yaml absent ou invalide."""
    settings = presets.cover_charter
    if settings is None:
        return None
    row = series.cover_charter
    stored = dict(row.settings or {}) if row is not None else {}
    defaults = settings.defaults.model_dump()
    values: dict[str, str] = {}
    problems: list[str] = []
    for name in FIELDS:
        value = stored.get(name)
        if isinstance(value, str) and value in choices(settings, name):
            values[name] = value
        else:
            if value is not None:
                problems.append(f"{LABELS[name]} « {value} » inconnu des presets : réglage par défaut appliqué")
            values[name] = defaults[name]
    ids = [int(i) for i in (row.character_ids if row is not None else []) or []]
    return Charter(settings=settings, values=values, character_ids=ids, saved=row is not None, problems=problems)


# --- personnages ---------------------------------------------------------------------------------------------
def _load(session: Session, project_id: int, ids: list[int]) -> list[Character]:
    if not ids:
        return []
    rows = session.scalars(
        select(Character)
        .where(Character.project_id == project_id, Character.id.in_(ids))
        .options(selectinload(Character.reference_images))
    )
    by_id = {c.id: c for c in rows}
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]


def charter_characters(session: Session, series_id: int, charter: Charter | None) -> list[Character]:
    """Personnages admis par la charte, dans son ordre (fiches disparues écartées)."""
    return _load(session, series_id, charter.character_ids) if charter else []


def present_characters(
    session: Session, volume: Volume, charter: Charter | None, limit: int | None = None
) -> list[Character]:
    """Personnages présents sur la couverture du tome : ceux choisis sur le tome (restreints à la charte si elle en
    nomme), sinon ceux de la charte ; au plus `limit`."""
    chosen = _load(session, volume.project_id, [int(i) for i in volume.cover_character_ids or []])
    if charter is not None and charter.character_ids:
        allowed = set(charter.character_ids)
        chosen = [c for c in chosen if c.id in allowed] or charter_characters(session, volume.project_id, charter)
    return chosen if limit is None else chosen[:limit]


def outside_charter(volume: Volume, charter: Charter | None) -> list[int]:
    """Personnages choisis sur le tome mais absents de la charte (écartés de la génération)."""
    if charter is None or not charter.character_ids:
        return []
    allowed = set(charter.character_ids)
    return [int(i) for i in volume.cover_character_ids or [] if int(i) not in allowed]


# --- couleur -------------------------------------------------------------------------------------------------
_HUES = (
    (15, "red"),
    (40, "orange"),
    (65, "yellow"),
    (90, "lime green"),
    (150, "green"),
    (175, "teal"),
    (200, "cyan"),
    (245, "blue"),
    (270, "indigo"),
    (295, "purple"),
    (330, "magenta"),
    (350, "pink"),
    (360, "red"),
)


def colour_name(hex_color: str) -> str:
    """Nom anglais approché d'une couleur #rrggbb (« deep blue », « light warm grey »), pour le modèle d'image."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    if light >= 0.93:
        return "white"
    if light <= 0.08:
        return "black"
    tone = "deep " if light < 0.3 else "dark " if light < 0.42 else "light " if light > 0.75 else ""
    if sat < 0.15:
        return f"{tone}grey".strip()
    deg = hue * 360
    name = next(n for limit, n in _HUES if deg < limit or limit == 360)
    muted = "muted " if sat < 0.35 else ""
    return f"{tone}{muted}{name}".strip()


def palette_colors(settings: CoverCharterSettings, series: Project) -> str:
    """Couleurs de la palette retenue de la série, en mots (« deep navy (#1e293b) as the dominant colour, … »)
    pour les rôles de `palette_roles` ; vide : pas de palette retenue."""
    data = series.palette or None
    if not data:
        return ""
    parts = []
    for c in data.get("colors") or []:
        if not isinstance(c, dict):
            continue
        role, hex_color = c.get("role"), c.get("hex")
        if not isinstance(role, str) or not isinstance(hex_color, str) or role not in settings.palette_roles:
            continue
        parts.append(f"{colour_name(hex_color)} ({hex_color.lower()}) as the {settings.palette_roles[role]}")
    return ", ".join(parts)


# --- phrases du prompt ---------------------------------------------------------------------------------------
def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _fill(template: str, values: dict[str, str]) -> str:
    return " ".join(string.Template(template).safe_substitute(values).split())


def charter_lines(charter: Charter, series: Project, *, kind: str, names: list[str]) -> list[str]:
    """Consignes de la charte pour la 1re (`front` : couleur, ambiance, plan, sujet) ou la petite illustration de
    4e (`back` : couleur, ambiance, plan de la 4e). Toujours en couleur : aucune phrase de noir et blanc."""
    s = charter.settings
    values = {"colors": palette_colors(s, series), "characters": _names(names), "lead": names[0] if names else ""}
    lines: list[str] = []
    palette = charter.choice("palette_mode")
    if palette.prompt.strip() and values["colors"]:
        lines.append(_fill(palette.prompt, values))
    for name in ("mood", "shot" if kind == "front" else "back_shot"):
        text = charter.choice(name).prompt
        if text.strip():
            lines.append(_fill(text, values))
    if kind == "front":
        subject = charter.choice("subject").prompt
        uses_characters = {"characters", "lead"} & set(string.Template(subject).get_identifiers())
        if subject.strip() and (names or not uses_characters):
            lines.append(_fill(subject, values))
    return lines


_DEFAULT_IDENTITY = str(CoverCharterSettings.model_fields["identity_prompt"].default)


def identity_lines(charter: Charter | None, references: list[tuple[str, str]]) -> list[str]:
    """Rôle de chaque image de référence envoyée (`(tag, nom)`), d'après `identity_prompt` du preset (sans
    charte : celui par défaut). Seule source de ces phrases : le rédacteur de couverture ne les écrit plus."""
    template = charter.settings.identity_prompt if charter is not None else _DEFAULT_IDENTITY
    return [_fill(template, {"tag": tag, "name": name}) for tag, name in references]


def charter_summary(charter: Charter) -> str:
    """Résumé lisible de la charte (« palette suggérée · ambiance lumineuse · plan américain… »)."""
    parts = [f"{LABELS[n]} : {charter.choice(n).label.lower()}" for n in FIELDS]
    return " · ".join(parts)


# --- place du logo -------------------------------------------------------------------------------------------
def charter_format(fmt: CoverFormat, charter: Charter | None) -> CoverFormat:
    """Format avec la zone du logo de la charte : zone `clear` du format, ou bandeau en haut / en bas (dans la
    marge de sécurité ; en bas, au-dessus de la zone de l'auteur s'il y en a une)."""
    if charter is None:
        return fmt
    place = charter.choice("logo_place")
    if place.band == "format":
        return fmt
    safety = fmt.safety_mm
    width = fmt.width_mm - 2 * safety
    height = min(place.height * fmt.height_mm, fmt.height_mm - 2 * safety)
    if place.band == "top":
        y = safety
    else:
        author = next((z for z in fmt.zones if z.id == "auteur"), None)
        bottom = author.y_mm if author is not None else fmt.height_mm - safety
        y = max(safety, bottom - height)
    old = fmt.clear_zone
    zone = CoverZone(
        id=old.id if old else "logo",
        label=old.label if old else "Logo et titre",
        x_mm=safety,
        y_mm=round(y, 3),
        width_mm=round(width, 3),
        height_mm=round(height, 3),
        clear=True,
    )
    zones = [z for z in fmt.zones if z is not old and z.id != zone.id]
    return fmt.model_copy(update={"zones": [zone, *zones]})


# --- contrôle d'identité -------------------------------------------------------------------------------------
def check_identity(
    providers: Any,
    qc: QCSettings | None,
    image: bytes,
    references: dict[str, list[bytes]],
    *,
    without_references: list[str] | None = None,
) -> dict[str, Any]:
    """Compare les personnages de la couverture à leurs références (couche « cohérence des personnages » du QC,
    seuil de qc.yaml). Renvoie {status, message, characters: [{name, similarity, ok}], warnings, min_similarity} ;
    un écart donne un avertissement, jamais un blocage."""
    from .qc import evaluate_identity, filter_detections

    without = list(without_references or [])
    out: dict[str, Any] = {"status": "skipped", "message": "", "characters": [], "warnings": []}
    if not references:
        out["message"] = "aucun personnage de la couverture n'a d'image de référence"
        return out
    if qc is None:
        out.update(status="unavailable", message="presets/qc.yaml absent ou invalide")
        return out
    identity = getattr(providers, "identity", None) if providers is not None else None
    if identity is None:
        errors = getattr(providers, "errors", {}) if providers is not None else {}
        out.update(
            status="unavailable",
            message=f"contrôle d'identité indisponible : {errors.get('identity', 'non configuré')}",
        )
        return out
    cfg = qc.identity
    faces = []
    detectors = getattr(providers, "detectors", None)
    if detectors is not None:
        try:
            raw = detectors.detect(image, face=qc.detectors.face.options, hand=None, text=None)
            faces = filter_detections(raw, qc.detectors).faces
        except (QCProviderError, TypeError):
            faces = []
    refs = {name: data[: cfg.max_references] for name, data in references.items()}
    try:
        sims = identity.compare(image, faces, refs, crop_scale=cfg.crop_scale)
    except QCProviderError as exc:
        out.update(status="error", message=str(exc), warnings=[f"Contrôle d'identité en erreur : {exc}"])
        return out
    res = evaluate_identity(sims, without_references=without, cfg=cfg)
    out.update(
        status=res.status,
        message=res.message or "",
        characters=res.extra.get("characters", []),
        warnings=list(res.reasons),
        min_similarity=cfg.min_similarity,
        provider=getattr(identity, "name", None),
    )
    return out
