"""Rangement des fichiers : slugs des séries et des fiches, dossiers de ComfyUI suivis (renommage,
suppression) et « Nettoyer les variantes non retenues » (route /projects/{id}/cleanup).

Renommer une série ou une fiche renomme son dossier dans ComfyUI (`output/` et `input/`) : le slug suit le
nouveau titre, le dossier est déplacé tout de suite (une génération en cours peut encore finir dans
l'ancien : c'est une zone de transit, rien n'y est relu). Supprimer une série, un chapitre, une page ou une
fiche supprime son dossier, strictement confiné à `mangaka/<série>/` (store/comfy_folders.py).

Bibliothèque lisible (`output/mangaka/<série>/references/…`, `chapitre-01/…`, pipeline/comfy_library.py) : tenue à
jour après chaque commit ; « Reconstruire la bibliothèque » (POST /projects/{id}/library) la régénère en entier.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline.comfy_library import LibraryReport
from ..pipeline.reference_sheets import unkept_variants
from ..store.comfy_folders import KIND_FOLDERS, CleanupReport, chapter_name, page_name
from ..store.models import Chapter, Character, Job, JobStatus, Project, SeriesAsset
from ..store.slugs import entry_kind_of, entry_slug, series_slug
from .deps import AppContext, get_ctx, get_session
from .schemas import CleanupOut, LibraryOut

log = logging.getLogger("mangaka_engine")
router = APIRouter(tags=["rangement"])

ACTIVE = (JobStatus.pending, JobStatus.running)


def _report(report: CleanupReport) -> None:
    if report.warning:
        log.warning("dossiers ComfyUI : %s", report.warning)


# --- slugs ---------------------------------------------------------------------------------
def set_series_slug(ctx: AppContext, session: Session, project: Project) -> None:
    """Slug d'une nouvelle série : évite aussi les dossiers déjà présents dans ComfyUI (série supprimée sans
    COMFYUI_DIR, autre base de données…) pour ne jamais mélanger deux séries."""
    project.slug = series_slug(session, project.title, on_disk=ctx.folders.existing_series())


def rename_series(ctx: AppContext, session: Session, project: Project) -> tuple[str, str] | None:
    """Titre changé : nouveau slug (sans commit) ; renvoie (ancien, nouveau) à déplacer après le commit."""
    old = project.slug
    on_disk = ctx.folders.existing_series() - {old}
    new = series_slug(session, project.title, project_id=project.id, current=old, on_disk=on_disk)
    if new == old:
        return None
    project.slug = new
    return (old, new) if old else None


def set_entry_slug(ctx: AppContext, session: Session, entry: Character | SeriesAsset, series: Project) -> None:
    entry.slug = entry_slug(session, entry, on_disk=ctx.folders.existing_entries(series.slug, entry_kind_of(entry)))


def rename_entry(
    ctx: AppContext, session: Session, entry: Character | SeriesAsset, series: Project
) -> tuple[list[str], list[str]] | None:
    """Nom changé : nouveau slug (sans commit) ; renvoie les dossiers (source, cible) à déplacer après le commit."""
    old = entry.slug
    kind = entry_kind_of(entry)
    on_disk = ctx.folders.existing_entries(series.slug, kind) - {old}
    new = entry_slug(session, entry, on_disk=on_disk)
    if new == old:
        return None
    entry.slug = new
    folder = KIND_FOLDERS[kind]
    return ([series.slug, folder, old], [series.slug, folder, new]) if old else None


def move_folders(ctx: AppContext, move: tuple[list[str], list[str]] | None) -> None:
    if move is not None:
        _report(ctx.folders.move(*move))


# --- bibliothèque lisible ------------------------------------------------------------------
def sync_library(ctx: AppContext, session: Session, project: Project, *, purge: bool = False) -> LibraryReport:
    """Met la bibliothèque de la série à jour (après un renommage de série, un rendu de page…)."""
    if ctx.library is None:
        return LibraryReport(warning=ctx.folders.warning())
    report = ctx.library.sync(session, project, purge=purge)
    if report.warning:
        log.warning("bibliothèque : %s", report.warning)
    return report


@router.post("/projects/{project_id}/library", response_model=LibraryOut)
def rebuild_library(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> LibraryOut:
    """« Reconstruire la bibliothèque » : régénère `output/mangaka/<série>/` depuis data/ (idempotent)."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    report = sync_library(ctx, session, project)
    warning = report.warning
    if ctx.library is None or not ctx.library.enabled:
        warning = ctx.folders.warning() or "dossier ComfyUI inconnu : bibliothèque non écrite (COMFYUI_DIR)"
    return LibraryOut(
        enabled=ctx.library is not None and ctx.library.enabled,
        folder=report.folder,
        path=str(ctx.folders.root / report.folder) if ctx.folders.root and report.folder else None,
        written=len(report.written),
        removed=len(report.removed),
        warning=warning,
    )


# --- suppressions --------------------------------------------------------------------------
def remove_series_folders(ctx: AppContext, slug: str) -> None:
    if slug:
        _report(ctx.folders.remove(slug))


def remove_chapter_folders(ctx: AppContext, series: str, chapter: Chapter) -> None:
    if series:
        _report(ctx.folders.remove(series, chapter_name(chapter)))


def remove_page_folders(ctx: AppContext, series: str, chapter: Chapter, numbers: list[int]) -> None:
    """Pages retirées, repérées par leur numéro d'avant la modification."""
    if not series:
        return
    for number in numbers:
        _report(ctx.folders.remove(series, chapter_name(chapter), page_name(number)))


def remove_entry_folders(ctx: AppContext, series: str, entry: Character | SeriesAsset) -> None:
    if series and entry.slug:
        _report(ctx.folders.remove(series, KIND_FOLDERS[entry_kind_of(entry)], entry.slug))


# --- « Nettoyer les variantes non retenues » ------------------------------------------------
@router.post("/projects/{project_id}/cleanup", response_model=CleanupOut)
def cleanup_project(
    project_id: int, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
) -> CleanupOut:
    """Efface les variantes non gardées de la série (fiches de référence et essais de la planche de style),
    sauf celles dont un job a besoin, puis vide ses dossiers de transit dans ComfyUI si rien ne tourne pour
    elle. Restent : références gardées, versions des cases (retenues ou non) et leur historique, et la
    bibliothèque lisible (régénérée : les fichiers de transit d'avant `_transit/` qui y traînaient sont retirés)."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    variants = unkept_variants(session, project_id)
    paths = [v.path for v in variants]
    for variant in variants:
        session.delete(variant)
    session.commit()
    for path in paths:
        ctx.files.delete(path)

    busy = session.scalar(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE)).limit(1))
    removed: list[str] = []
    warning = ctx.folders.warning()
    if busy is not None:
        warning = "Des générations sont en cours pour cette série : dossiers de ComfyUI laissés en place"
    elif ctx.folders.enabled and project.slug:
        # Transit seulement (envois, sorties brutes) : la bibliothèque lisible reste, remise d'accord.
        report = ctx.folders.clear_transit(project.slug)
        removed, warning = report.removed, report.warning
        sync_library(ctx, session, project, purge=True)
    return CleanupOut(
        variants_deleted=len(variants),
        comfyui_folders_removed=removed,
        comfyui_cleaned=ctx.folders.enabled and busy is None,
        warning=warning,
    )
