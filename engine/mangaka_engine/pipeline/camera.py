"""LoRA de caméra et d'identité (presets/camera_loras.yaml) : fonctions pures, sans base ni réseau.

- `camera_plan` : LoRA à chaîner pour un workflow — Multiple-Angles (« Nouvel angle » d'une fiche,
  « Changer l'angle » d'une case) et Cohérence anime (interrupteur de la série) — et préfixe du prompt
  (mot déclencheur puis vocabulaire de caméra, au tout début). Un LoRA réservé à d'autres paliers
  (`tiers`) n'est pas ajouté : la raison est rendue (« Disponible en palier Qualité »), jamais ignorée
  en silence ;
- `angle_prompt` : prompt d'une génération d'angle, morceaux de `prompts` du catalogue ;
- `angle_vocabulary` / `strip_angle_terms` : la scène reprise par « Changer l'angle » perd son ancien angle
  (il contredirait la nouvelle vue mise en tête) ;
- `direction_target` / `closest_view` : vue de référence d'une fiche la plus proche de l'angle de la
  direction artistique d'une case (vues étiquetées par leur angle ; repli : la vue principale).

Aucun nom de fichier ni mot déclencheur ici : tout vient du catalogue.
"""

from __future__ import annotations

import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..presets import LoadedWorkflow, LoraSpec
from ..presets.schemas import AngleTarget, CameraAngle, CameraLora, CameraLoraCatalog

# Palier où ces LoRA ont été testés : nom affiché quand le palier courant ne les permet pas.
QUALITY_TIER_LABEL = "Disponible en palier Qualité"


class CameraError(Exception):
    """Erreur lisible (en français) d'une génération d'angle."""


@dataclass
class CameraPlan:
    loras: list[LoraSpec] = field(default_factory=list)
    angle: CameraAngle | None = None
    angle_lora: CameraLora | None = None
    # Raisons des LoRA demandés mais non ajoutés (palier non testé, LoRA absent du catalogue…).
    skipped: list[str] = field(default_factory=list)

    @property
    def prefix(self) -> str:
        """Mot déclencheur puis vocabulaire de caméra : à placer au tout début du prompt."""
        if self.angle is None or self.angle_lora is None:
            return ""
        return " ".join(p for p in (self.angle_lora.trigger.strip(), self.angle.camera.strip()) if p)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.angle is not None and self.angle_lora is not None:
            out["angle"] = {
                "id": self.angle.id,
                "label": self.angle.label,
                "camera": self.angle.camera,
                "lora": self.angle_lora.id,
                "lora_name": self.angle_lora.name,
            }
        if self.skipped:
            out["skipped"] = list(self.skipped)
        return out


def tier_allows(lora: CameraLora, loaded: LoadedWorkflow) -> bool:
    """Le LoRA est-il permis pour ce workflow ? Son palier figure dans `tiers`, et le workflow a une chaîne LoRA."""
    tier = loaded.preset.tier
    return tier is not None and tier.key in lora.tiers and loaded.preset.lora_chain is not None


def tier_reason(lora: CameraLora, loaded: LoadedWorkflow) -> str:
    tier = loaded.preset.tier.name if loaded.preset.tier is not None else loaded.preset.id
    return f"{lora.name} : {QUALITY_TIER_LABEL.lower()} (palier {tier} non testé, LoRA non ajouté)"


def identity_problem(catalog: CameraLoraCatalog, loaded: LoadedWorkflow | None) -> str | None:
    """Pourquoi « Cohérence anime » ne s'appliquerait pas aux générations de ce palier (None : elle s'applique)."""
    identity = catalog.identity_lora
    if identity is None:
        return "aucun LoRA d'identité dans presets/camera_loras.yaml"
    if loaded is None or not tier_allows(identity, loaded):
        return QUALITY_TIER_LABEL
    return None


def camera_plan(
    catalog: CameraLoraCatalog,
    loaded: LoadedWorkflow,
    *,
    angle_id: str | None = None,
    lora_id: str | None = None,
    weight: float | None = None,
    anime: bool = False,
    anime_weight: float | None = None,
) -> CameraPlan:
    """LoRA à chaîner après ceux de la série et des fiches, dans l'ordre : angle puis identité.

    `angle_id` : génération d'angle (LoRA `lora_id`, sinon celui par défaut, poids `weight`, sinon celui du
    catalogue) ; `anime` : Cohérence anime de la série. `CameraError` si l'angle ou le LoRA d'angle sont
    inconnus ; un palier non permis n'est pas une erreur ici (raison dans `skipped`)."""
    plan = CameraPlan()
    if angle_id is not None:
        angle = catalog.angle(angle_id)
        if angle is None:
            raise CameraError(f"angle de caméra inconnu : « {angle_id} » (presets/camera_loras.yaml)")
        lora = catalog.lora(lora_id) if lora_id else catalog.default_angle_lora
        if lora is None or lora.role != "angles":
            raise CameraError(f"LoRA d'angle inconnu : « {lora_id or '?'} » (presets/camera_loras.yaml)")
        if tier_allows(lora, loaded):
            plan.angle, plan.angle_lora = angle, lora
            plan.loras.append(LoraSpec(lora.file, lora.weight if weight is None else float(weight), "angle"))
        else:
            plan.skipped.append(tier_reason(lora, loaded))
    if anime:
        identity = catalog.identity_lora
        if identity is None:
            plan.skipped.append("Cohérence anime : aucun LoRA d'identité dans presets/camera_loras.yaml")
        elif tier_allows(identity, loaded):
            w = identity.weight if anime_weight is None else float(anime_weight)
            plan.loras.append(LoraSpec(identity.file, w, "cohérence anime"))
        else:
            plan.skipped.append(tier_reason(identity, loaded))
    return plan


def merge_loras(base: Sequence[LoraSpec], extra: Sequence[LoraSpec]) -> list[LoraSpec]:
    """LoRA de la série et des fiches, puis ceux du plan (un même fichier n'est chaîné qu'une fois)."""
    out = list(base)
    for lora in extra:
        if all(lo.name != lora.name for lo in out):
            out.append(lora)
    return out


def angle_prompt(parts: Sequence[str], plan: CameraPlan, **values: str) -> str:
    """Prompt d'une génération d'angle : le premier morceau commence par le mot déclencheur."""
    filled = {
        "trigger": plan.angle_lora.trigger.strip() if plan.angle_lora else "",
        "camera": plan.angle.camera.strip() if plan.angle else "",
        "name": "",
        "description": "",
        "scene": "",
        **{k: " ".join((v or "").split()).rstrip(" .;,:") for k, v in values.items()},
    }
    out: list[str] = []
    for part in parts:
        tpl = string.Template(part)
        names = tpl.get_identifiers()
        # Le mot déclencheur seul (LoRA sans déclencheur) ne retire pas la caméra : seul un autre vide compte.
        if any(not filled[v] for v in names if v != "trigger"):
            continue
        out.append(" ".join(tpl.substitute(filled).split()))
    text = " ".join(p for p in out if p)
    prefix = plan.prefix
    if prefix and not text.startswith(prefix):
        text = f"{prefix}. {text}".strip()  # gabarit sans $trigger $camera en tête : le préfixe ouvre quand même
    return text


def angle_vocabulary(catalog: CameraLoraCatalog, camera_terms: Mapping[str, str]) -> list[str]:
    """Termes d'angle et d'élévation (anglais) du catalogue, les plus longs d'abord : caméra de chaque angle et
    ses morceaux (« front view », « high-angle shot »), termes de cadrage (`camera_terms` d'image_prompt.yaml)
    des angles de la direction artistique (`direction_angles`), puis `scene_angle_terms`."""
    terms = {_term_key(k): v for k, v in camera_terms.items()}
    found: set[str] = set()
    sources = [
        *(a.camera for a in catalog.angles),
        *(terms[k] for k in map(_term_key, catalog.direction_angles) if k in terms),
        *catalog.scene_angle_terms,
    ]
    for source in sources:
        for term in (source, *source.split(",")):
            term = " ".join(term.split()).strip(" .;:")
            if term:
                found.add(term.casefold())
    return sorted(found, key=lambda t: (-len(t), t))


def _term_key(value: str) -> str:
    return " ".join(value.strip().casefold().replace("’", "'").split())


# Préposition et article qui partent avec le terme d'angle (« seen in a low-angle shot », « at eye level »).
_LEAD = r"(?:(?:seen\s+|shot\s+|viewed\s+)?(?:in|from|at|with|as)\s+)?(?:(?:a|an|the)\s+)?"


def strip_angle_terms(text: str, terms: Sequence[str], labels: Sequence[str] = ()) -> str:
    """Retire d'une scène tout le vocabulaire d'angle (« Changer l'angle » : la nouvelle vue est mise en tête,
    l'ancienne la contredirait) : les phrases ouvertes par un des `labels` (« Camera angle: »), puis chaque
    terme (`angle_vocabulary`), et la ponctuation laissée orpheline. Sans casse."""
    out = text
    for label in labels:
        if label.strip():
            out = re.sub(re.escape(label.strip()) + r"[^.]*\.?", " ", out, flags=re.IGNORECASE)
    for term in sorted({t for t in terms if t.strip()}, key=len, reverse=True):
        pattern = r"(?<![\w-])" + _LEAD + r"\s*".join(re.escape(w) for w in term.split()) + r"(?![\w-])"
        out = re.sub(pattern, " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)  # « Aiko , » → « Aiko, »
    out = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", out)  # « , , » → « , »
    out = re.sub(r"[,;:]+\s*\.", ".", out)  # « , . » → « . »
    out = re.sub(r"(^|\.)\s*[,;:]+\s*", r"\1 ", out)  # « . , Aiko » → « . Aiko »
    out = re.sub(r"\.(?:\s*\.)+", ".", out)  # « . . » → « . »
    return out.strip(" ,;:").lstrip(". ").strip()


# --- vue de référence la plus proche de l'angle de la case --------------------------------
class TaggedImage(Protocol):
    angle: str | None


def direction_target(catalog: CameraLoraCatalog, direction: dict[str, Any]) -> AngleTarget | None:
    """Cible d'angle de la direction artistique d'une case (`angle`, puis `plan` pour l'élévation)."""
    azimuth: float | None = None
    elevation: float | None = None
    for key in ("angle", "plan"):
        value = direction.get(key)
        target = catalog.direction_angles.get(value) if isinstance(value, str) else None
        if target is None:
            continue
        azimuth = azimuth if azimuth is not None else target.azimuth
        elevation = elevation if elevation is not None else target.elevation
    if azimuth is None and elevation is None:
        return None
    return AngleTarget(azimuth=azimuth, elevation=elevation)


def angle_distance(angle: CameraAngle, target: AngleTarget) -> float:
    """Écart (degrés) sur les axes donnés ; le côté (gauche / droite) ne compte pas."""
    total = 0.0
    if target.azimuth is not None:
        total += abs(abs(angle.azimuth) - abs(target.azimuth))
    if target.elevation is not None:
        total += abs(angle.elevation - target.elevation)
    return total


def closest_view[I: TaggedImage](
    images: Sequence[I], catalog: CameraLoraCatalog, target: AngleTarget | None
) -> I | None:
    """Vue étiquetée la plus proche de `target` ; la vue principale (1re image, angle `main_view` du
    catalogue tant qu'elle n'a pas d'étiquette) gagne les égalités et sert de repli. Une image sans
    étiquette (autre que la principale) n'est jamais choisie pour son angle."""
    if not images:
        return None
    main = images[0]
    if target is None:
        return main
    best, best_d = main, None
    for i, img in enumerate(images):
        angle = catalog.angle(img.angle) or (catalog.angle(catalog.main_view) if i == 0 else None)
        if angle is None:
            continue
        d = angle_distance(angle, target)
        if best_d is None or d < best_d:
            best, best_d = img, d
    return best


def ordered_views[I: TaggedImage](
    images: Sequence[I], catalog: CameraLoraCatalog, target: AngleTarget | None
) -> list[I]:
    """Images d'une fiche avec la vue la plus proche de `target` en tête, les autres dans leur ordre."""
    chosen = closest_view(images, catalog, target)
    if chosen is None or chosen is images[0]:
        return list(images)
    return [chosen, *(img for img in images if img is not chosen)]
