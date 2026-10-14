"""Bibliothèque lisible : copie rangée, avec des noms lisibles, de tout ce qui est retenu dans une série, sous
`ComfyUI/output/mangaka/<série>/` (là où l'auteur regarde), et corbeille (`trash/`) de tout ce qui a été généré
sans être retenu — data/ reste le stockage de l'appli.

    mangaka/<série>/
      references/
        personnages/<nom>/
          portrait/            <nom>-portrait.png (+ <nom>-portrait-2.png… si plusieurs gardées)
          plein-pied/          <nom>-plein-pied.png (turnaround)
          expressions/         <nom>-expressions.png
          angles/              <nom>-angle-<angle>.png (« Nouvel angle », vues étiquetées par leur angle)
          imports/             <nom>-import.png (images envoyées à la main)
        objets/<nom>/          trois-quarts/, imports/
        decors/<nom>/          plan-large/, autre-angle/, imports/
        vehicules/<nom>/       trois-quarts/, turnaround/, angles/, imports/
        creatures/<nom>/       portrait/, turnaround/, angles/, imports/
        style/                 planche-de-style.png (+ planche-de-style-2.png… : autres images de la référence active)
      chapitre-01/
        page-01/               case-01-croquis.png (croquis validé), case-01.png (version choisie, finie si agrandie)
        planches/              page-01.png + page-01.svg (dernier rendu ou export de la page)
      trash/                   tout ce qui a été généré sans être retenu, rangé comme ci-dessus :
        personnages/<nom>/portrait/<nom>-portrait-v3.png        (variante non gardée)
        style/essai-v2.png, style/planche-de-style-<nom>.png    (essai non choisi, ancienne référence de style)
        chapitre-01/page-01/case-01-v2.png, case-01-croquis-v1.png  (version non choisie, croquis non validé)
      _transit/                sorties brutes de ComfyUI, effacées dès leur copie dans data/ (store/comfy_folders.py)

Sous-dossiers d'une fiche : un par type de fiche de presets/reference_sheets/ de sa sorte (`folder` du preset,
sinon l'id sans la sorte : `objet-trois-quarts` → `trois-quarts`) — un nouveau preset = un nouveau sous-dossier,
créé avec la fiche —, plus `angles/` (vues de « Nouvel angle » ou étiquetées par leur angle ; créé d'avance pour
un personnage) et `imports/` (images sans variante d'origine). Une image gardée porte le nom de son sous-dossier
(`-2`, `-3`… si plusieurs) ; une variante non gardée part dans la corbeille avec son numéro `-vN` (rang parmi
les variantes de la fiche et du même sous-dossier, gardées comprises), une version de case avec son numéro de
version. Garder une variante ou choisir une version la sort de la corbeille ; l'inverse l'y remet. Rien dans
la corbeille n'est relu par l'appli : l'effacer à la main ne casse rien (la reconstruction la refait).

`sync` recalcule l'arborescence voulue depuis la base et data/, puis met le disque d'accord : écrit ce qui manque
ou a changé (copie dans un fichier temporaire puis renommage), retire les fichiers qui ne sont plus retenus et les
dossiers vidés. Rejouer ne duplique rien ; l'ancienne disposition à plat (`personnages/<nom>/<nom>-portrait.png`)
est ainsi convertie (anciens fichiers retirés une fois les nouveaux écrits). Elle est lancée après chaque commit
qui touche une série (`watch` : séries, fiches, images de référence, variantes, chapitres, pages, cases,
versions), après le rendu ou l'export d'une page, et par « Reconstruire la bibliothèque » (POST
/projects/{id}/library, ou POST /library pour toutes les séries depuis les Réglages).

Mêmes garde-fous que `ComfyFolders` : sans `COMFYUI_DIR` valide rien n'est écrit (`warning` dit pourquoi), tout
est confiné à `output/mangaka/<série>/` (segments = slugs validés, jamais `old/`, aucun lien symbolique suivi).
Seuls les fichiers aux noms de la bibliothèque (`case-01.png`, `lucius-portrait.png`…) sont retirés : les sorties
d'avant `_transit/` restées dans un dossier de chapitre ne le sont que par « Nettoyer » (`purge`).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry
from ..store.comfy_folders import REFERENCES, ComfyFolders, chapter_name, page_name, panel_name, series_name
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import (
    AssetKind,
    Chapter,
    Character,
    CharacterImage,
    ImageKind,
    Page,
    Panel,
    PanelImage,
    Project,
    ReferenceVariant,
    SeriesAsset,
    SeriesAssetImage,
)
from ..store.slugs import KIND_FOLDERS, entry_kind_of, is_segment, slugify

log = logging.getLogger("mangaka_engine")

PLATES = "planches"
TRASH = "trash"  # corbeille : output/mangaka/<série>/trash/
ANGLES = "angles"  # vues de « Nouvel angle » ou étiquetées par leur angle
IMPORTS = "imports"  # images de référence sans variante d'origine (envoyées à la main…)
STYLE_BOARD = "planche-de-style"
STYLE_TRIAL = "essai"
STYLE_KIND = "style"  # ReferenceVariant.entry_kind d'un essai de planche de style (pipeline/style_board.py)
EXTENSIONS = ("png", "jpg", "jpeg", "webp", "svg")
# Nom d'un fichier de la bibliothèque : slug + extension (jamais `_`, `.` en tête, `/` ni `..`).
FILE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.(?:" + "|".join(EXTENSIONS) + r")$")
CHAPTER_DIR = re.compile(r"^chapitre-\d+$")
SHEET_KIND_PREFIX = re.compile(r"^(?:personnage|objet|decor|vehicule|creature|style)-")
ANGLE_SHEET = "nouvel-angle"  # comme pipeline/reference_sheets.py (variantes de « Nouvel angle »)
# Sortes dont `angles/` est créé d'avance : un sujet qu'on fait tourner (« Nouvel angle »).
ANGLE_KINDS = ("character", "vehicle", "creature")
# Champs dont le changement modifie la bibliothèque (objets modifiés : les ajouts et suppressions comptent tous).
WATCHED: dict[type, tuple[str, ...]] = {
    Project: ("slug",),
    Character: ("slug",),
    SeriesAsset: ("slug", "active", "kind"),
    CharacterImage: ("path", "position", "angle"),
    SeriesAssetImage: ("path", "position", "angle"),
    ReferenceVariant: ("kept_image_id",),
    Chapter: ("number",),
    Page: ("number", "chapter_id"),
    Panel: ("index", "sketch_image_id", "page_id"),
    PanelImage: ("selected", "path", "finish", "kind"),
}
ANCHORS = "comfy_library_anchors"
RENAMED = "comfy_library_renamed"


@dataclass
class LibraryReport:
    """Ce que `sync` a fait (`written` / `removed` : chemins relatifs à `output/mangaka/<série>/`) ou pourquoi rien."""

    folder: str | None = None  # output/mangaka/<série> (relatif à ComfyUI)
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    warning: str | None = None


@dataclass
class LibraryPlan:
    """Arborescence voulue, relative au dossier de la série : dossiers, et fichier → source dans data/."""

    dirs: set[tuple[str, ...]] = field(default_factory=set)
    files: dict[tuple[str, ...], Path] = field(default_factory=dict)


def _ext(path: str | Path) -> str:
    ext = PurePosixPath(str(path)).suffix.lower().lstrip(".")
    return ext if ext in EXTENSIONS else "png"


def sheet_folder(sheet: str, presets: PresetRegistry | None = None) -> str:
    """Sous-dossier d'un type de fiche : `folder` du preset, sinon l'id sans la sorte (`decor-plan-large` →
    `plan-large`) — aussi pour un type retiré des presets depuis."""
    preset = presets.reference_sheets.get(sheet) if presets is not None else None
    if preset is not None and preset.folder:
        return preset.folder
    return slugify(SHEET_KIND_PREFIX.sub("", sheet), "fiche")


def sheet_folders(kind: str, presets: PresetRegistry | None) -> list[str]:
    """Sous-dossiers créés d'avance pour une fiche de cette sorte (character, object, decor, vehicle, creature),
    dans l'ordre des presets : un par type de fiche, `angles/` pour un personnage, un véhicule ou une créature
    (vues tournées autour du sujet), `imports/`."""
    sheets = presets.reference_sheets.values() if presets is not None else ()
    out = [sheet_folder(sheet.id, presets) for sheet in sheets if kind in sheet.kinds]
    if kind in ANGLE_KINDS:
        out.append(ANGLES)
    out.append(IMPORTS)
    return list(dict.fromkeys(out))


def _angle_slug(angle: str | None) -> str | None:
    return slugify(angle, "vue") if angle else None


def variant_angle(variant: ReferenceVariant) -> str | None:
    """Angle d'une variante de « Nouvel angle » (comme pipeline/reference_sheets.py)."""
    angle = (variant.params or {}).get("camera", {}).get("angle")
    return str(angle["id"]) if isinstance(angle, dict) and angle.get("id") else None


def reference_place(
    slug: str, sheet: str | None, angle: str | None, presets: PresetRegistry | None = None
) -> tuple[str, str]:
    """(sous-dossier, nom sans numéro) d'une image de référence ou d'une variante : angle étiqueté →
    `angles/<nom>-angle-<angle>`, type de fiche → `<dossier>/<nom>-<dossier>`, sinon `imports/<nom>-import`."""
    angle_id = _angle_slug(angle)
    if angle_id:
        return ANGLES, f"{slug}-angle-{angle_id}"
    if sheet == ANGLE_SHEET:
        return ANGLES, f"{slug}-angle"
    if sheet:
        folder = sheet_folder(sheet, presets)
        return folder, f"{slug}-{folder}"
    return IMPORTS, f"{slug}-import"


class _Names:
    """Noms uniques dans un dossier : `nom`, puis `nom-2`, `nom-3`…"""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def __call__(self, stem: str) -> str:
        name, n = stem, 2
        while name in self.used:
            name, n = f"{stem}-{n}", n + 1
        self.used.add(name)
        return name


class ComfyLibrary:
    def __init__(
        self,
        folders: ComfyFolders,
        files: FileStore,
        db: Database | None = None,
        presets: PresetRegistry | None = None,
    ) -> None:
        self.folders = folders
        self.files = files
        self.db = db
        self.presets = presets  # types de fiches → sous-dossiers des fiches
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        return self.folders.enabled

    # --- arborescence voulue ---------------------------------------------------------------
    def plan(self, session: Session, project: Project) -> LibraryPlan:
        plan = LibraryPlan()
        plan.dirs |= {(REFERENCES,), (TRASH,)}
        plan.dirs |= {(REFERENCES, folder) for folder in KIND_FOLDERS.values()}
        variants = self._variants(session, project.id)

        entries: list[Character | SeriesAsset] = sorted(project.characters, key=lambda e: e.id)
        entries += sorted(project.assets, key=lambda e: e.id)
        styles = [e for e in entries if isinstance(e, SeriesAsset) and e.kind == AssetKind.style]
        for entry in entries:
            if entry not in styles:
                self._plan_entry(plan, entry, variants.get((entry_kind_of(entry), entry.id), []))
        self._plan_style(plan, styles, variants.get((STYLE_KIND, project.id), []))

        for chapter in sorted(project.chapters, key=lambda c: c.number):
            ch = chapter_name(chapter)
            plan.dirs |= {(ch,), (ch, PLATES)}
            for page in chapter.pages:
                pg = page_name(page)
                plan.dirs.add((ch, pg))
                for panel in page.panels:
                    self._plan_panel(plan, (ch, pg), panel)
                self._add_plates(plan, (ch, PLATES), page)
        return plan

    def _variants(self, session: Session, project_id: int) -> dict[tuple[str, int], list[ReferenceVariant]]:
        """(sorte, id de la fiche — de la série pour un essai de style) → variantes, des plus anciennes aux
        plus récentes."""
        rows = session.scalars(
            select(ReferenceVariant).where(ReferenceVariant.project_id == project_id).order_by(ReferenceVariant.id)
        )
        out: dict[tuple[str, int], list[ReferenceVariant]] = {}
        for variant in rows:
            out.setdefault((variant.entry_kind, variant.entry_id), []).append(variant)
        return out

    def _plan_entry(self, plan: LibraryPlan, entry: Character | SeriesAsset, variants: list[ReferenceVariant]) -> None:
        """`references/<sorte>/<nom>/<type>/` (images gardées) et `trash/<sorte>/<nom>/<type>/` (variantes non
        gardées)."""
        if not is_segment(entry.slug):
            return
        kind = entry_kind_of(entry)
        kind_folder = KIND_FOLDERS[kind]
        slug = entry.slug
        base = (REFERENCES, kind_folder, slug)
        plan.dirs.add(base)
        plan.dirs |= {(*base, sub) for sub in sheet_folders(kind, self.presets)}

        images = sorted(entry.reference_images, key=lambda i: (i.position, i.id))
        current = {image.id for image in images}
        kept = {v.kept_image_id: v for v in variants if v.kept_image_id in current}
        names: dict[str, _Names] = {}
        for image in images:
            variant = kept.get(image.id)
            sub, stem = reference_place(slug, variant.sheet if variant else None, image.angle, self.presets)
            self._add(plan, (*base, sub), names.setdefault(sub, _Names())(stem), image.path)

        ranks: dict[str, int] = {}
        for variant in variants:
            sub, stem = reference_place(slug, variant.sheet, variant_angle(variant), self.presets)
            ranks[sub] = ranks.get(sub, 0) + 1
            if variant.kept_image_id not in current:
                self._add(plan, (TRASH, kind_folder, slug, sub), f"{stem}-v{ranks[sub]}", variant.path)

    def _plan_style(self, plan: LibraryPlan, styles: list[SeriesAsset], trials: list[ReferenceVariant]) -> None:
        """Référence de style active → `references/style/` ; anciennes références et essais non choisis →
        `trash/style/`."""
        active, old = _Names(), _Names()
        for entry in styles:
            images = sorted(entry.reference_images, key=lambda i: (i.position, i.id))
            for image in images:
                if entry.active:
                    self._add(plan, (REFERENCES, KIND_FOLDERS["style"]), active(STYLE_BOARD), image.path)
                elif is_segment(entry.slug):
                    self._add(plan, (TRASH, KIND_FOLDERS["style"]), old(f"{STYLE_BOARD}-{entry.slug}"), image.path)
        for rank, trial in enumerate(trials, start=1):
            if trial.kept_image_id is None:
                self._add(plan, (TRASH, KIND_FOLDERS["style"]), f"{STYLE_TRIAL}-v{rank}", trial.path)

    def _plan_panel(self, plan: LibraryPlan, page: tuple[str, ...], panel: Panel) -> None:
        """Croquis validé et version choisie → `chapitre-XX/page-YY/` ; le reste → `trash/chapitre-XX/page-YY/`."""
        for image in sorted(panel.images, key=lambda i: i.version):
            if image.kind == ImageKind.croquis:
                if image.id == panel.sketch_image_id:
                    self._add(plan, page, panel_name(panel, "croquis"), image.path)
                else:
                    self._add(plan, (TRASH, *page), panel_name(panel, f"croquis-v{image.version}"), image.path)
            elif image.selected:
                finished = (image.finish or {}).get("path")
                source = finished if finished and self._source(finished) else image.path
                self._add(plan, page, panel_name(panel), source)
            else:
                self._add(plan, (TRASH, *page), panel_name(panel, f"v{image.version}"), image.path)

    def _add_plates(self, plan: LibraryPlan, folder: tuple[str, ...], page: Page) -> None:
        from .render import read_render_info, render_folder  # rendu : module lourd, chargé au besoin

        try:
            info = read_render_info(self.files, page.id)
        except (OSError, ValueError):
            return
        if not info or not info.get("stem"):
            return
        for ext in ("png", "svg"):
            self._add(plan, folder, page_name(page), f"{render_folder(page.id)}/{info['stem']}.{ext}", ext=ext)

    def _source(self, rel: str) -> Path | None:
        try:
            path = self.files.absolute(rel)
        except ValueError:
            return None
        return path if path.is_file() and not path.is_symlink() else None

    def _add(self, plan: LibraryPlan, folder: tuple[str, ...], stem: str, rel: str, *, ext: str | None = None) -> None:
        source = self._source(rel)
        if source is not None:
            plan.files[(*folder, f"{stem}.{ext or _ext(rel)}")] = source

    # --- disque -----------------------------------------------------------------------------
    def sync(self, session: Session, project: Project, *, purge: bool = False) -> LibraryReport:
        """Met `output/mangaka/<série>/` d'accord avec ce qui est retenu (idempotent). `purge` : retire aussi les
        fichiers aux noms inconnus des dossiers de la bibliothèque (anciennes sorties de transit)."""
        if not self.enabled:
            return LibraryReport(warning=self.folders.warning())
        series = series_name(project)
        base = self.folders.target("output", [series])
        if base is None:
            log.warning("bibliothèque : série refusée (%s)", series)
            return LibraryReport(warning="chemin refusé")
        report = LibraryReport(folder=f"output/mangaka/{series}")
        with self._lock:
            plan = self.plan(session, project)
            for folder in sorted(plan.dirs):
                path = self.folders.target("output", [series, *folder])
                if path is None:
                    report.warning = "chemin refusé"
                    continue
                path.mkdir(parents=True, exist_ok=True)
            for key, source in sorted(plan.files.items()):
                if self._write(series, key, source):
                    report.written.append("/".join(key))
            report.removed = self._prune(base, plan, purge=purge)
        return report

    def _write(self, series: str, key: tuple[str, ...], source: Path) -> bool:
        *folder, name = key
        target_dir = self.folders.target("output", [series, *folder])
        if target_dir is None or not FILE_NAME.match(name):
            log.warning("bibliothèque : nom refusé (%s)", "/".join(key))
            return False
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        src = source.stat()
        if target.is_symlink():
            target.unlink()
        elif target.is_file():
            dst = target.stat()
            if dst.st_size == src.st_size and abs(dst.st_mtime - src.st_mtime) < 0.01:
                return False  # déjà à jour
        tmp = target_dir / f".{name}.tmp"
        try:
            shutil.copy2(source, tmp)
            os.replace(tmp, target)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            log.warning("bibliothèque : %s non écrit (%s)", target, exc)
            return False
        return True

    def _prune(self, base: Path, plan: LibraryPlan, *, purge: bool) -> list[str]:
        """Retire les fichiers de la bibliothèque qui ne sont plus retenus, puis les dossiers vidés non voulus."""
        removed: list[str] = []
        if not base.is_dir() or base.is_symlink():
            return removed
        roots = [p for p in base.iterdir() if p.is_dir() and not p.is_symlink()]
        roots = [p for p in roots if p.name in (REFERENCES, TRASH) or CHAPTER_DIR.match(p.name)]
        for root in roots:
            for dirpath, _dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
                current = Path(dirpath)
                rel = current.relative_to(base).parts
                for name in filenames:
                    path = current / name
                    if (*rel, name) in plan.files or path.is_symlink():
                        continue
                    if purge or FILE_NAME.match(name) or (name.startswith(".") and name.endswith(".tmp")):
                        path.unlink(missing_ok=True)
                        removed.append("/".join((*rel, name)))
                if rel not in plan.dirs and not current.is_symlink() and not any(current.iterdir()):
                    current.rmdir()
        return removed

    # --- déclencheurs -----------------------------------------------------------------------
    def sync_project(self, project_id: int, *, purge: bool = False) -> LibraryReport | None:
        """`sync` dans sa propre session (après un commit, depuis un job). Jamais d'exception : journalisée."""
        if not self.enabled or self.db is None:
            return None
        try:
            with self.db.session_scope() as session:
                project = session.get(Project, project_id)
                return self.sync(session, project, purge=purge) if project is not None else None
        except Exception:  # la bibliothèque ne doit jamais faire échouer une action de l'atelier
            log.exception("bibliothèque : mise à jour de la série %s impossible", project_id)
            return None

    def watch(self, db: Database) -> None:
        """Met la bibliothèque à jour après chaque commit qui touche une série (sessions de `db`)."""
        self.db = db
        db.listen("after_flush", self._after_flush)
        db.listen("after_commit", self._after_commit)
        db.listen("after_rollback", self._forget)

    def _after_flush(self, session: Session, _context: Any) -> None:
        if not self.enabled:
            return
        anchors: set[tuple[str, int]] = session.info.setdefault(ANCHORS, set())
        renamed: set[int] = session.info.setdefault(RENAMED, set())
        changed = [(o, False) for o in session.new] + [(o, True) for o in session.deleted]
        for obj in session.dirty:
            fields = WATCHED.get(type(obj))
            if fields is None:
                continue
            state = inspect(obj)
            if any(state.attrs[f].history.has_changes() for f in fields):
                changed.append((obj, False))
                if isinstance(obj, Project) and any(state.attrs.slug.history.deleted):
                    renamed.add(obj.id)  # dossier déplacé par l'API après le commit, puis bibliothèque à jour
        for obj, deleted in changed:
            anchor = _anchor(obj, deleted)
            if anchor is not None:
                anchors.add(anchor)

    def _forget(self, session: Session) -> None:
        session.info.pop(ANCHORS, None)
        session.info.pop(RENAMED, None)

    def _after_commit(self, session: Session) -> None:
        anchors: set[tuple[str, int]] = session.info.pop(ANCHORS, set())
        renamed: set[int] = session.info.pop(RENAMED, set())
        if not anchors or not self.enabled or self.db is None:
            return
        try:
            with self.db.session_scope() as other:
                ids = _project_ids(other, anchors) - renamed
        except Exception:
            log.exception("bibliothèque : séries touchées introuvables")
            return
        for project_id in sorted(ids):
            self.sync_project(project_id)


def _anchor(obj: object, deleted: bool) -> tuple[str, int] | None:
    """Objet encore en base qui mène à la série d'un objet ajouté, modifié ou supprimé."""
    if isinstance(obj, Project):
        return None if deleted else ("project", obj.id)
    if isinstance(obj, Character | SeriesAsset | Chapter | ReferenceVariant):
        return ("project", obj.project_id) if obj.project_id is not None else None
    links: dict[type, tuple[str, str]] = {
        CharacterImage: ("character", "character_id"),
        SeriesAssetImage: ("asset", "asset_id"),
        Page: ("chapter", "chapter_id"),
        Panel: ("page", "page_id"),
        PanelImage: ("panel", "panel_id"),
    }
    link = links.get(type(obj))
    if link is None:
        return None
    value = getattr(obj, link[1], None)
    return (link[0], int(value)) if value is not None else None


def _project_ids(session: Session, anchors: Iterable[tuple[str, int]]) -> set[int]:
    queries = {
        "character": lambda i: select(Character.project_id).where(Character.id == i),
        "asset": lambda i: select(SeriesAsset.project_id).where(SeriesAsset.id == i),
        "chapter": lambda i: select(Chapter.project_id).where(Chapter.id == i),
        "page": lambda i: select(Chapter.project_id).join(Page, Page.chapter_id == Chapter.id).where(Page.id == i),
        "panel": lambda i: (
            select(Chapter.project_id)
            .join(Page, Page.chapter_id == Chapter.id)
            .join(Panel, Panel.page_id == Page.id)
            .where(Panel.id == i)
        ),
    }
    out: set[int] = set()
    for kind, key in anchors:
        if kind == "project":
            out.add(key)
            continue
        project_id = session.scalar(queries[kind](key))
        if project_id is not None:
            out.add(int(project_id))
    return out
