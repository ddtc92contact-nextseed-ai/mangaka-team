"""Banc A/B FLUX 3 Klein : paragraphe seul (bras A) contre grille de composition à boîtes (bras B).

    python -m mangaka_engine.bench.flux_layout --chapter <id> [--limit N] [--seed S] [--dry-run | --mock]

Choisit les cases du chapitre à 2 personnages ou plus (dans l'ordre des pages), puis prépare pour chacune
deux jobs de génération ordinaires, à la même graine, avec le même prompt figé (`ab_prompt`) et les mêmes
fiches : A sur le preset `paragraph` (`flux3-klein-qualite`, sa variante avec références si une fiche en a),
B sur son pendant `layout` (`flux3-klein-qualite-layout`). Ce sont des comparaisons A/B de l'atelier
(`ab_mode` « layout » au journal) : les versions s'ajoutent aux cases et l'auteur peut y choisir son bras.

Les jobs sont exécutés ici, l'un après l'autre (ils sont créés « en cours » : la file du moteur, s'il tourne,
ne les prend pas), puis chaque version passe le contrôle qualité. Rapport : `report.html` (images côte à côte,
boîtes, verdict et score du QC, temps) et `report.json`, dans `data/bench/flux-layout/<date-heure>/` (ou
`--out`).

- `--dry-run` : prépare seulement (cases, presets, graine, boîtes) et écrit le rapport ; rien n'est gardé
  en base, rien n'est envoyé ;
- `--mock` : ComfyUI, détecteurs et cohérence des personnages factices (aucun GPU, aucun réseau) : rapport
  factice. Écrit dans la base du `MANGAKA_DATA_DIR` configuré, comme le mode réel : à lancer sur une copie ;
- sinon : mode réel, les fournisseurs de `.env` (ComfyUI http). Lancé par Morigane ou David, jamais en CI
  ni en QA (le gain de la grille se mesure sur GPU).
"""

from __future__ import annotations

import argparse
import html
import json
import random
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..pipeline.ab import _tier_preset
from ..pipeline.generation import (
    GenerationError,
    GenerationExecutor,
    enqueue_panel,
    panel_cast,
    panel_layout_boxes,
    update_panel_prompt,
)
from ..pipeline.jobs import JobReporter, finish_job
from ..pipeline.knowledge import KnowledgeBase
from ..pipeline.qc import QCError, QCExecutor, any_layer_available
from ..presets import PresetError, PresetRegistry
from ..providers.factory import Providers, build_providers
from ..store.comfy_folders import ComfyFolders, page_name, panel_name
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import Chapter, GenerationLog, JobStatus, Panel, PanelImage, utcnow

PARAGRAPH_PRESET = "flux3-klein-qualite"
LAYOUT_PRESET = "flux3-klein-qualite-layout"
AB_MODE = "layout"  # `ab_mode` des deux bras au journal des générations
ARMS = (("A", "paragraph"), ("B", "layout"))
MAX_SEED = 2**32 - 1
MOCK_PROVIDERS = {
    "comfyui_provider": "mock",
    "vision_provider": "mock",
    "qc_detectors_provider": "mock",
    "qc_identity_provider": "mock",
    "embedding_provider": "mock",
    "llm_provider": "mock",
}


class BenchError(Exception):
    """Erreur lisible (en français) du banc."""


@dataclass
class BenchArm:
    arm: str  # A | B
    prompt_format: str  # paragraph | layout
    preset: str
    job_id: int | None = None
    status: str = "prepared"  # prepared | succeeded | failed
    error: str | None = None
    image_id: int | None = None
    version: int | None = None
    image: str | None = None  # chemin de l'image dans le dossier du rapport
    duration_ms: int | None = None
    qc_verdict: str | None = None
    qc_score: int | None = None
    qc_reasons: list[str] = field(default_factory=list)


@dataclass
class BenchPair:
    panel_id: int
    label: str  # « page-01 · case-02 »
    characters: list[str]
    seed: int
    prompt: str
    boxes: list[dict[str, Any]]
    group: str | None = None
    arms: list[BenchArm] = field(default_factory=list)


@dataclass
class BenchReport:
    chapter_id: int
    mode: str  # dry-run | mock | réel
    started_at: str
    pairs: list[BenchPair] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)  # cases écartées et pourquoi
    out_dir: str = ""

    def summary(self) -> dict[str, Any]:
        """Par format : cases réussies, score QC moyen, temps moyen ; nombre de cases où chacun l'emporte."""
        out: dict[str, Any] = {}
        for _, fmt in ARMS:
            arms = [a for p in self.pairs for a in p.arms if a.prompt_format == fmt and a.status == "succeeded"]
            scores = [a.qc_score for a in arms if a.qc_score is not None]
            times = [a.duration_ms for a in arms if a.duration_ms is not None]
            out[fmt] = {
                "succeeded": len(arms),
                "mean_qc_score": round(sum(scores) / len(scores), 1) if scores else None,
                "mean_duration_s": round(sum(times) / len(times) / 1000, 1) if times else None,
            }
        wins = {"paragraph": 0, "layout": 0, "tie": 0}
        for p in self.pairs:
            a, b = (next((x for x in p.arms if x.prompt_format == fmt), None) for _, fmt in ARMS)
            if a is None or b is None or a.qc_score is None or b.qc_score is None:
                continue
            wins["tie" if a.qc_score == b.qc_score else "paragraph" if a.qc_score > b.qc_score else "layout"] += 1
        out["wins"] = wins
        return out

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "summary": self.summary()}


# --- choix des cases ------------------------------------------------------------------------------
def bench_panels(
    session: Session, presets: PresetRegistry, chapter_id: int, limit: int
) -> list[tuple[Panel, list[dict[str, Any]]]]:
    """Cases du chapitre à 2 personnages ou plus (au plus `limit`, dans l'ordre des pages), avec leurs boîtes."""
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise BenchError(f"chapitre {chapter_id} introuvable")
    chosen: list[tuple[Panel, list[dict[str, Any]]]] = []
    for page in chapter.pages:
        for panel in sorted(page.panels, key=lambda p: p.index):
            if len(chosen) >= limit:
                return chosen
            boxes = panel_layout_boxes(presets, panel, panel_cast(session, panel, presets).characters)
            if len(boxes) >= 2:
                chosen.append((panel, [b.as_dict() for b in boxes]))
    return chosen


def _label(panel: Panel) -> str:
    return f"{page_name(panel.page)} · {panel_name(panel)}"


def prepare_pairs(
    session: Session,
    presets: PresetRegistry,
    chapter_id: int,
    limit: int,
    *,
    seed: int | None = None,
    paragraph: str = PARAGRAPH_PRESET,
    layout: str = LAYOUT_PRESET,
    knowledge: KnowledgeBase | None = None,
    create_jobs: bool = True,
) -> tuple[list[BenchPair], list[dict[str, Any]]]:
    """Paires A/B des cases choisies (sans commit). `create_jobs` : met les deux jobs de chaque case en base,
    « en cours » (exécutés par le banc, jamais par la file du moteur)."""
    for preset_id, fmt in ((paragraph, "paragraph"), (layout, "layout")):
        try:
            preset = presets.workflow(preset_id).preset
        except PresetError as exc:
            raise BenchError(str(exc)) from None
        if preset.prompt_format != fmt:
            raise BenchError(
                f"le preset {preset_id} n'est pas au format « {fmt} » (prompt_format: {preset.prompt_format})"
            )
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    panels = bench_panels(session, presets, chapter_id, limit)
    skipped: list[dict[str, Any]] = []
    pairs: list[BenchPair] = []
    for panel, boxes in panels:
        label = _label(panel)
        try:
            prompt = update_panel_prompt(presets, session, panel, knowledge).strip()
            if not prompt:
                raise GenerationError("prompt vide : décris la case ou écris son prompt final")
            entries = panel_cast(session, panel, presets).entries
            ids = [_tier_preset(presets, p, entries) for p in (paragraph, layout)]
        except (GenerationError, PresetError) as exc:
            skipped.append({"panel_id": panel.id, "label": label, "reason": str(exc)})
            continue
        pair = BenchPair(
            panel_id=panel.id,
            label=label,
            characters=[b["name"] for b in boxes],
            seed=rng.randint(0, MAX_SEED),
            prompt=prompt,
            boxes=boxes,
            arms=[BenchArm(arm=arm, prompt_format=fmt, preset=pid) for (arm, fmt), pid in zip(ARMS, ids, strict=True)],
        )
        if create_jobs:
            try:
                _create_jobs(session, presets, panel, pair, knowledge)
            except (GenerationError, PresetError) as exc:
                skipped.append({"panel_id": panel.id, "label": label, "reason": str(exc)})
                continue
        pairs.append(pair)
    return pairs, skipped


def _create_jobs(
    session: Session, presets: PresetRegistry, panel: Panel, pair: BenchPair, knowledge: KnowledgeBase | None
) -> None:
    pair.group = uuid.uuid4().hex[:12]
    for arm in pair.arms:
        extra = {
            "ab": {"group": pair.group, "arm": arm.arm, "mode": AB_MODE},
            "ab_prompt": pair.prompt,
            "bench": "flux_layout",
        }
        [job] = enqueue_panel(
            session, presets, panel, count=1, seed=pair.seed, preset=arm.preset, extra_params=extra, knowledge=knowledge
        )
        if job.params.get("preset") != arm.preset:
            # Composition verrouillée : le pendant ControlNet remplacerait le bras, la comparaison n'aurait pas de sens.
            raise GenerationError("composition verrouillée : déverrouille la case pour la comparer")
        # « En cours » d'emblée : la file du moteur ne prend que les jobs en attente.
        job.status = JobStatus.running
        job.started_at = utcnow()
        job.message = f"Banc FLUX layout : bras {arm.arm}"
        session.flush()
        arm.job_id = job.id


# --- exécution ------------------------------------------------------------------------------------
def run_pairs(
    db: Database,
    presets: PresetRegistry,
    files: FileStore,
    providers: Providers,
    pairs: Sequence[BenchPair],
    out_dir: Path,
    *,
    folders: ComfyFolders | None = None,
    log: Any = print,
) -> None:
    """Exécute les jobs l'un après l'autre (bras A puis B), contrôle chaque version, copie les images."""
    if providers.comfyui is None:
        raise BenchError(f"ComfyUI indisponible : {providers.errors.get('comfyui') or 'client non configuré'}")
    executor = GenerationExecutor(db, presets, files, providers.comfyui, folders=folders)
    qc = QCExecutor(db, presets, files, providers)
    qc_cfg = presets.qc
    images = out_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    for pair in pairs:
        for arm in pair.arms:
            if arm.job_id is None:
                continue
            log(f"{pair.label} · bras {arm.arm} ({arm.prompt_format}, {arm.preset}, graine {pair.seed})…")
            reporter = JobReporter(db, arm.job_id)
            t0 = time.monotonic()
            try:
                message = executor(arm.job_id, reporter, threading.Event())
                finish_job(reporter, t0, JobStatus.succeeded, message=message)
                arm.status = "succeeded"
            except Exception as exc:  # noqa: BLE001 — un bras en échec n'arrête pas le banc
                finish_job(reporter, t0, JobStatus.failed, error=str(exc))
                arm.status, arm.error = "failed", str(exc) or type(exc).__name__
            finally:
                executor.after(arm.job_id)
            _collect(db, files, pair, arm, images)
            if arm.image_id is not None and qc_cfg is not None and any_layer_available(providers):
                try:
                    qc.check_image(arm.image_id, qc_cfg, vision="auto", presets=presets)
                except QCError as exc:
                    arm.qc_reasons = [f"contrôle impossible : {exc}"]
                _collect(db, files, pair, arm, images)
            elif arm.image_id is not None:
                arm.qc_reasons = ["contrôle qualité indisponible (aucune couche)"]


def _collect(db: Database, files: FileStore, pair: BenchPair, arm: BenchArm, images: Path) -> None:
    """Version produite par le bras (journal des générations), son image copiée dans le rapport, son QC."""
    with db.session_scope() as session:
        row = session.scalar(
            select(GenerationLog).where(GenerationLog.job_id == arm.job_id).order_by(GenerationLog.id.desc()).limit(1)
        )
        if row is not None and row.duration_ms is not None:
            arm.duration_ms = row.duration_ms
        img = session.get(PanelImage, row.image_id) if row is not None and row.image_id is not None else None
        if img is None:
            return
        arm.image_id, arm.version = img.id, img.version
        arm.qc_verdict = img.qc_verdict.value if img.qc_verdict is not None else None
        arm.qc_score = img.qc_score
        if img.qc_reasons:
            arm.qc_reasons = list(img.qc_reasons)
        source = files.absolute(img.path)
        if source.is_file() and arm.image is None:
            name = f"case-{pair.panel_id}-{arm.arm}-{arm.prompt_format}{source.suffix or '.png'}"
            shutil.copyfile(source, images / name)
            arm.image = f"images/{name}"


# --- rapport --------------------------------------------------------------------------------------
def _box_svg(boxes: Sequence[dict[str, Any]]) -> str:
    rects = "".join(
        f'<rect x="{b["x"] * 100:.1f}" y="{b["y"] * 100:.1f}" width="{b["w"] * 100:.1f}" height="{b["h"] * 100:.1f}"/>'
        f'<text x="{b["x"] * 100 + 2:.1f}" y="{b["y"] * 100 + 8:.1f}">{i} {html.escape(str(b["name"]))}</text>'
        for i, b in enumerate(boxes, start=1)
    )
    return f'<svg class="grid" viewBox="0 0 100 100" preserveAspectRatio="none">{rects}</svg>'


def _arm_cell(arm: BenchArm) -> str:
    img = (
        f'<img src="{html.escape(arm.image)}" alt="bras {arm.arm}">'
        if arm.image
        else '<div class="none">pas d\'image</div>'
    )
    qc = (
        f"QC : {html.escape(arm.qc_verdict or '—')} · score {arm.qc_score if arm.qc_score is not None else '—'}"
        if arm.status == "succeeded"
        else html.escape(arm.error or arm.status)
    )
    duration = f" · {arm.duration_ms / 1000:.1f} s" if arm.duration_ms is not None else ""
    reasons = "".join(f"<li>{html.escape(r)}</li>" for r in arm.qc_reasons)
    return (
        f'<td><div class="head">{arm.arm} · {arm.prompt_format}</div>{img}'
        f'<div class="meta">{html.escape(arm.preset)}<br>{qc}{duration}</div><ul>{reasons}</ul></td>'
    )


def render_html(report: BenchReport) -> str:
    s = report.summary()
    rows = "".join(
        f"<tr><td><b>{html.escape(p.label)}</b><br>{html.escape(', '.join(p.characters))}<br>graine {p.seed}"
        f"{_box_svg(p.boxes)}<details><summary>prompt</summary><p>{html.escape(p.prompt)}</p></details></td>"
        + "".join(_arm_cell(a) for a in p.arms)
        + "</tr>"
        for p in report.pairs
    )
    skipped = "".join(f"<li>{html.escape(x['label'])} : {html.escape(x['reason'])}</li>" for x in report.skipped)

    def stat(fmt: str) -> str:
        v = s[fmt]
        return (
            f"<li><b>{fmt}</b> : {v['succeeded']} réussie(s), score QC moyen {v['mean_qc_score'] if v['mean_qc_score'] is not None else '—'}"
            f", temps moyen {v['mean_duration_s'] if v['mean_duration_s'] is not None else '—'} s</li>"
        )

    wins = s["wins"]
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Banc FLUX layout</title>
<style>
:root{{--bg:#fafaf7;--fg:#1d1d1b;--muted:#6b6b66;--line:#d9d9d2;--box:#c2410c}}
@media (prefers-color-scheme: dark){{:root{{--bg:#151514;--fg:#ecece6;--muted:#9a9a92;--line:#3a3a36;--box:#fb923c}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:16px}}
table{{border-collapse:collapse;width:100%}} td{{border-top:1px solid var(--line);padding:8px;vertical-align:top}}
td img{{max-width:100%;max-height:420px;display:block}} .meta,.head{{color:var(--muted)}} .head{{font-weight:600}}
.grid{{width:120px;height:90px;border:1px solid var(--line);display:block;margin-top:6px}}
.grid rect{{fill:none;stroke:var(--box);stroke-width:.8}} .grid text{{font-size:7px;fill:var(--box)}}
.none{{padding:40px 0;color:var(--muted)}} ul{{margin:4px 0;padding-left:18px;color:var(--muted)}}
</style></head><body>
<h1>Banc FLUX 3 Klein : paragraphe contre grille de composition</h1>
<p>Chapitre {report.chapter_id} · mode {html.escape(report.mode)} · {html.escape(report.started_at)}</p>
<ul>{stat("paragraph")}{stat("layout")}
<li>Meilleur score QC : paragraphe {wins["paragraph"]}, grille {wins["layout"]}, égalité {wins["tie"]}</li></ul>
<table><tbody>{rows}</tbody></table>
{f"<h2>Cases écartées</h2><ul>{skipped}</ul>" if skipped else ""}
</body></html>
"""


def write_report(report: BenchReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report.out_dir = str(out_dir)
    (out_dir / "report.json").write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    path = out_dir / "report.html"
    path.write_text(render_html(report), encoding="utf-8")
    return path


# --- point d'entrée --------------------------------------------------------------------------------
def run_bench(
    db: Database,
    presets: PresetRegistry,
    files: FileStore,
    providers: Providers,
    chapter_id: int,
    out_dir: Path,
    *,
    limit: int = 5,
    seed: int | None = None,
    mode: str = "réel",
    paragraph: str = PARAGRAPH_PRESET,
    layout: str = LAYOUT_PRESET,
    knowledge: KnowledgeBase | None = None,
    folders: ComfyFolders | None = None,
    log: Any = print,
) -> BenchReport:
    """Prépare les paires, les exécute (sauf `mode` « dry-run ») et écrit le rapport dans `out_dir`."""
    if limit < 1:
        raise BenchError("--limit : au moins 1 case")
    report = BenchReport(chapter_id=chapter_id, mode=mode, started_at=datetime.now().isoformat(timespec="seconds"))
    dry = mode == "dry-run"
    with db.session_scope() as session:
        pairs, skipped = prepare_pairs(
            session,
            presets,
            chapter_id,
            limit,
            seed=seed,
            paragraph=paragraph,
            layout=layout,
            knowledge=knowledge,
            create_jobs=not dry,
        )
        if dry:
            session.rollback()  # rien n'est gardé : ni prompt reconstruit, ni direction appliquée
        else:
            session.commit()
    report.pairs, report.skipped = pairs, skipped
    log(
        f"{len(pairs)} case(s) à 2 personnages ou plus retenue(s)" + (f", {len(skipped)} écartée(s)" if skipped else "")
    )
    if not dry and pairs:
        run_pairs(db, presets, files, providers, pairs, out_dir, folders=folders, log=log)
    path = write_report(report, out_dir)
    log(f"Rapport : {path}")
    return report


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mangaka_engine.bench.flux_layout",
        description="Banc A/B FLUX 3 Klein : paragraphe seul contre grille de composition à boîtes.",
    )
    parser.add_argument("--chapter", type=int, required=True, help="id du chapitre")
    parser.add_argument("--limit", type=int, default=5, help="nombre de cases au plus (défaut 5)")
    parser.add_argument("--seed", type=int, default=None, help="graines reproductibles (une par case, tirées de S)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="prépare seulement : rien en base, rien envoyé")
    group.add_argument("--mock", action="store_true", help="ComfyUI et contrôle qualité factices (rapport factice)")
    parser.add_argument("--out", type=Path, default=None, help="dossier du rapport (défaut data/bench/flux-layout/…)")
    parser.add_argument("--paragraph-preset", default=PARAGRAPH_PRESET)
    parser.add_argument("--layout-preset", default=LAYOUT_PRESET)
    args = parser.parse_args(argv)

    settings = settings or get_settings()
    if args.mock:
        settings = settings.model_copy(update=MOCK_PROVIDERS)
    mode = "dry-run" if args.dry_run else "mock" if args.mock else "réel"
    presets = PresetRegistry.load(settings.presets_dir)
    providers = build_providers(settings, presets)
    db = Database(settings.database_path)
    files = FileStore(settings.data_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or settings.data_dir / "bench" / "flux-layout" / f"{stamp}-{mode}"
    folders = ComfyFolders.from_settings(settings.comfyui_dir, provider=providers.names.get("comfyui"))
    knowledge = KnowledgeBase(presets.knowledge, providers.embedding)
    try:
        run_bench(
            db,
            presets,
            files,
            providers,
            args.chapter,
            out_dir,
            limit=args.limit,
            seed=args.seed,
            mode=mode,
            paragraph=args.paragraph_preset,
            layout=args.layout_preset,
            knowledge=knowledge,
            folders=folders,
        )
    except BenchError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
