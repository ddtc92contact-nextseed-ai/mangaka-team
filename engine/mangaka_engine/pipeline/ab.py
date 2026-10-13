"""« Comparer deux prompts » : la même case, à la même graine, en deux bras A et B.

Ce qui varie entre les bras (`mode`) :

- `prompt` : A = le prompt actuel de la case, B = une variante éditée (même palier, même CFG) ;
- `tier` : deux paliers (même prompt, même CFG de série) ;
- `cfg` : deux CFG (même prompt, même palier ; jamais sur un palier distillé, cfg 1 imposé).

Chaque bras est un job de génération ordinaire (file ComfyUI unique) qui produit une version de la case,
notée dans le journal avec son groupe A/B (`ab_group`, `ab_arm`, `ab_mode`). Les prompts sont figés à la
demande (`ab_prompt` du job) : le rédacteur IA ne les réécrit pas. Le choix de l'auteur (`record_choice`)
ajoute un verdict à chaque bras : gardée pour le bras retenu, rejetée pour l'autre.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry
from ..presets.schemas import check_cfg
from ..store.models import GenerationEvent, GenerationLog, Job, Panel, PanelImage
from .generation import (
    GenerationError,
    LibraryEntry,
    enqueue_panel,
    panel_cast,
    resolve_preset_id,
    update_panel_prompt,
)
from .journal import PANEL_IMAGE, record_event
from .knowledge import KnowledgeBase

Mode = Literal["prompt", "tier", "cfg"]
ARMS = ("A", "B")
MAX_SEED = 2**32 - 1


def _tier_preset(presets: PresetRegistry, preset_id: str, entries: Sequence[LibraryEntry]) -> str:
    """Preset d'un palier pour cette case : son pendant « avec références » si une fiche de la case en a."""
    loaded = presets.workflow(preset_id)
    if loaded.preset.role != "generation" or loaded.preset.inpaint is not None or loaded.preset.control is not None:
        raise GenerationError(f"« {preset_id} » n'est pas un palier de génération de case")
    refs = any(e.reference_images for e in entries)
    if refs and not loaded.preset.reference_images and loaded.preset.with_references:
        return loaded.preset.with_references
    return preset_id


def enqueue_ab(
    session: Session,
    presets: PresetRegistry,
    panel: Panel,
    *,
    mode: Mode,
    prompt_b: str | None = None,
    presets_ab: tuple[str, str] | None = None,
    cfgs: tuple[float, float] | None = None,
    seed: int | None = None,
    knowledge: KnowledgeBase | None = None,
) -> tuple[str, int, list[Job]]:
    """Met en file les deux bras (sans commit) ; renvoie (groupe, graine commune, jobs A puis B)."""
    prompt_a = update_panel_prompt(presets, session, panel, knowledge).strip()
    if not prompt_a:
        raise GenerationError("prompt vide : décris la case ou écris son prompt final")
    entries = panel_cast(session, panel, presets).entries
    seed = seed if seed is not None else random.randint(0, MAX_SEED)
    arms: list[dict[str, Any]] = []
    if mode == "prompt":
        variant = (prompt_b or "").strip()
        if not variant:
            raise GenerationError("écris la variante du prompt (bras B)")
        if variant == prompt_a:
            raise GenerationError("la variante est identique au prompt actuel : modifie-la")
        arms = [{"prompt": prompt_a}, {"prompt": variant}]
    elif mode == "tier":
        if presets_ab is None or presets_ab[0] == presets_ab[1]:
            raise GenerationError("choisis deux paliers différents")
        arms = [{"prompt": prompt_a, "preset": _tier_preset(presets, p, entries)} for p in presets_ab]
    elif mode == "cfg":
        if cfgs is None or cfgs[0] == cfgs[1]:
            raise GenerationError("choisis deux CFG différents")
        preset_id = resolve_preset_id(presets, panel, entries)
        loaded = presets.workflow(preset_id)
        if loaded.preset.distilled or "cfg" not in loaded.preset.mapping:
            raise GenerationError(
                f"le palier de la case ({loaded.preset.tier.name if loaded.preset.tier else preset_id}) a un CFG fixe : "
                "compare plutôt deux paliers"
            )
        for value in cfgs:
            try:
                check_cfg(value, distilled=False)
            except ValueError as exc:
                raise GenerationError(str(exc)) from None
        arms = [{"prompt": prompt_a, "cfg": value} for value in cfgs]
    else:
        raise GenerationError(f"mode de comparaison inconnu : {mode}")

    group = uuid.uuid4().hex[:12]
    jobs: list[Job] = []
    for arm, spec in zip(ARMS, arms, strict=True):
        extra: dict[str, Any] = {"ab": {"group": group, "arm": arm, "mode": mode}, "ab_prompt": spec["prompt"]}
        if "cfg" in spec:
            extra["ab_cfg"] = spec["cfg"]
        jobs += enqueue_panel(
            session,
            presets,
            panel,
            count=1,
            seed=seed,
            preset=spec.get("preset"),
            extra_params=extra,
            knowledge=knowledge,
        )
    return group, seed, jobs


def group_logs(session: Session, group: str) -> dict[str, GenerationLog]:
    """Dernière ligne du journal de chaque bras d'un groupe A/B."""
    out: dict[str, GenerationLog] = {}
    for row in session.scalars(select(GenerationLog).where(GenerationLog.ab_group == group).order_by(GenerationLog.id)):
        if row.ab_arm:
            out[row.ab_arm] = row
    return out


def group_choice(session: Session, logs: Sequence[GenerationLog]) -> GenerationEvent | None:
    """Choix de l'auteur dans un groupe A/B (dernier événement `ab_choice`)."""
    ids = [g.id for g in logs]
    if not ids:
        return None
    return session.scalar(
        select(GenerationEvent)
        .where(GenerationEvent.log_id.in_(ids), GenerationEvent.action == "ab_choice")
        .order_by(GenerationEvent.id.desc())
        .limit(1)
    )


def record_choice(
    session: Session, group: str, winner: Literal["A", "B"], *, reason: str | None = None, note: str = ""
) -> dict[str, GenerationLog]:
    """Choix de l'auteur : bras retenu « gardé », l'autre « rejeté » (avec la raison et la note)."""
    logs = group_logs(session, group)
    if set(logs) != set(ARMS) or any(g.status != "succeeded" for g in logs.values()):
        raise GenerationError("les deux bras de la comparaison ne sont pas encore générés")
    for arm, row in logs.items():
        won = arm == winner
        record_event(
            session,
            verdict="validated" if won else "rejected",
            action="ab_choice",
            image_kind=PANEL_IMAGE,
            image_id=row.image_id,
            panel_id=row.panel_id,
            log_id=row.id,
            reason=None if won else reason,
            note=note,
        )
    return logs


def panel_groups(session: Session, panel_id: int, limit: int = 5) -> list[str]:
    """Groupes A/B d'une case, du plus récent au plus ancien."""
    seen: list[str] = []
    for group in session.scalars(
        select(GenerationLog.ab_group)
        .where(GenerationLog.panel_id == panel_id, GenerationLog.ab_group.is_not(None))
        .order_by(GenerationLog.id.desc())
    ):
        if group and group not in seen:
            seen.append(group)
        if len(seen) >= limit:
            break
    return seen


def pending_groups(session: Session, panel_id: int) -> list[dict[str, Any]]:
    """Groupes A/B encore en file ou en cours pour une case (jobs actifs) : {group, mode, arms}."""
    from .generation import ACTIVE, STEP

    out: dict[str, dict[str, Any]] = {}
    for job in session.scalars(
        select(Job).where(Job.panel_id == panel_id, Job.step == STEP, Job.status.in_(ACTIVE)).order_by(Job.id)
    ):
        ab = (job.params or {}).get("ab")
        if isinstance(ab, dict) and ab.get("group"):
            entry = out.setdefault(str(ab["group"]), {"group": ab["group"], "mode": ab.get("mode"), "arms": []})
            entry["arms"].append(ab.get("arm"))
    return list(out.values())


def arm_image(session: Session, row: GenerationLog) -> PanelImage | None:
    return session.get(PanelImage, row.image_id) if row.image_id is not None else None
