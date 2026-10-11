"""Rangement des fichiers de la série dans ComfyUI (`output/mangaka/` et `input/mangaka/`).

Noms (purs) : `series_folder`, `entry_folder`, `page_folder`, `panel_name` donnent les préfixes des
`SaveImage` et les sous-dossiers des images envoyées, les mêmes dans `output/` et `input/` :

    mangaka/<série>/personnages/<nom>/<fiche>/variante-1_00001_.png   (sorties « Créer des références »)
    mangaka/<série>/personnages/<nom>/reference-12.png                (image de référence envoyée)
    mangaka/<série>/objets/<nom>/…  mangaka/<série>/decors/<nom>/…
    mangaka/<série>/style/essais/…  mangaka/<série>/style/<référence>/…
    mangaka/<série>/chapitre-01/page-01/case-01, case-01-croquis, case-01-controle, case-01-finition,
    case-01-reparation…  (sorties et envois de la case, dans le dossier de sa page)

Disque (`ComfyFolders`) : ComfyUI n'a pas d'API pour effacer un fichier, le moteur agit donc directement
dans le dossier de ComfyUI (`COMFYUI_DIR`). Sans dossier valide, rien n'est jamais supprimé ni déplacé
(`problem` dit pourquoi, affiché dans l'interface) — aucun chemin n'est deviné. Toute opération est
confinée à `mangaka/<série>/…` : segments validés (slugs), jamais `old/`, jamais un lien symbolique au
niveau de la série ou en dessous, chemin résolu vérifié.

La sortie de ComfyUI est une zone de transit : dès qu'un résultat est copié dans data/, sa copie dans
`output/` est effacée (`discard_output`).
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..providers.comfyui.base import ImageRef
from .models import Chapter, Character, Page, Panel, Project, SeriesAsset
from .slugs import KIND_FOLDERS, RESERVED_SERIES, entry_kind_of, is_segment

log = logging.getLogger("mangaka_engine")

ROOT = "mangaka"  # sous-dossier de ComfyUI/output et ComfyUI/input
STYLE_TRIALS = "essais"  # essais de la planche de style : mangaka/<série>/style/essais/
AREAS = ("output", "input")
DEFAULT_DIR = "~/ComfyUI"


# --- noms -------------------------------------------------------------------------------
def series_name(project: Project) -> str:
    """Segment de la série : son slug (repli `serie-<id>` pour une série pas encore enregistrée)."""
    return project.slug or f"serie-{project.id}"


def series_folder(project: Project) -> str:
    return f"{ROOT}/{series_name(project)}"


def entry_folder(entry: Character | SeriesAsset, series: Project) -> str:
    """`mangaka/<série>/personnages|objets|decors|style/<nom>`."""
    return f"{series_folder(series)}/{KIND_FOLDERS[entry_kind_of(entry)]}/{entry.slug or f'fiche-{entry.id}'}"


def chapter_name(chapter: Chapter) -> str:
    return f"chapitre-{chapter.number:02d}"


def page_name(page: Page | int) -> str:
    """`page-01` (une page ou son numéro)."""
    return f"page-{page if isinstance(page, int) else page.number:02d}"


def page_folder(chapter: Chapter, page: Page) -> str:
    """`mangaka/<série>/chapitre-01/page-01`."""
    return f"{series_folder(chapter.project)}/{chapter_name(chapter)}/{page_name(page)}"


def panel_name(panel: Panel, suffix: str = "") -> str:
    """`case-01`, `case-01-croquis`, `case-01-finition`… (nom de fichier dans le dossier de la page)."""
    return f"case-{panel.index + 1:02d}" + (f"-{suffix}" if suffix else "")


def style_folder(series: Project) -> str:
    return f"{series_folder(series)}/{KIND_FOLDERS['style']}"


# --- disque -----------------------------------------------------------------------------
@dataclass
class CleanupReport:
    """Ce qu'une opération a fait dans ComfyUI (`removed` : chemins relatifs à ComfyUI) ou pourquoi rien."""

    removed: list[str]
    warning: str | None = None


class ComfyFolders:
    def __init__(self, root: Path | None, *, problem: str | None = None, mock: bool = False) -> None:
        self.root = root
        self.problem = problem
        self.mock = mock

    @classmethod
    def from_settings(cls, comfyui_dir: str | None, *, provider: str | None) -> ComfyFolders:
        """`COMFYUI_DIR` → dossiers gérés. Absent : `~/ComfyUI` avec le vrai ComfyUI, aucun en mode mock (rien n'y
        est jamais écrit). Vide, introuvable ou sans `input/` et `output/` : désactivé, avec la raison."""
        mock = provider == "mock"
        if comfyui_dir is None:
            if mock:
                return cls(None, mock=True)
            comfyui_dir = DEFAULT_DIR
        raw = (comfyui_dir or "").strip()
        if not raw:
            return cls(None, problem="COMFYUI_DIR est vide : les fichiers de ComfyUI ne sont pas nettoyés", mock=mock)
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            return cls(None, problem=f"COMFYUI_DIR doit être un chemin absolu ({raw})", mock=mock)
        if not path.is_dir():
            return cls(
                None,
                problem=f"dossier ComfyUI introuvable : {path} (COMFYUI_DIR) — les fichiers de ComfyUI ne sont pas nettoyés",
                mock=mock,
            )
        missing = [a for a in AREAS if not (path / a).is_dir()]
        if missing:
            return cls(
                None,
                problem=f"{path} ne ressemble pas à ComfyUI (pas de dossier {', '.join(missing)}) — COMFYUI_DIR à corriger",
                mock=mock,
            )
        return cls(path, mock=mock)

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "path": str(self.root) if self.root else None,
            "mock": self.mock,
            "problem": self.problem,
        }

    def warning(self) -> str | None:
        """Avertissement à montrer après une suppression (rien en mode mock : rien n'est écrit dans ComfyUI)."""
        if self.enabled or (self.mock and self.problem is None):
            return None
        return self.problem or "dossier ComfyUI inconnu : les fichiers de ComfyUI ne sont pas nettoyés"

    def _series_dir(self, area: str, series: str) -> Path | None:
        """`<ComfyUI>/<area>/mangaka/<série>`, ou None si la série n'est pas un segment permis."""
        if self.root is None or not is_segment(series) or series in RESERVED_SERIES:
            return None
        return self.root / area / ROOT / series

    def _target(self, area: str, segments: Sequence[str]) -> Path | None:
        """Chemin confiné à `<area>/mangaka/<série>/…`, ou None s'il sort de la série ou passe par un lien."""
        if not segments or not all(is_segment(s) for s in segments):
            return None
        base = self._series_dir(area, segments[0])
        if base is None:
            return None
        path = base.joinpath(*segments[1:])
        current = base
        for part in (None, *segments[1:]):
            if part is not None:
                current = current / part
            if current.is_symlink():
                return None
        try:
            if not path.resolve().is_relative_to(base.resolve()):
                return None
        except OSError:
            return None
        return path

    def existing_series(self) -> set[str]:
        """Dossiers de séries déjà présents dans ComfyUI (un nouveau slug les évite)."""
        return self._children(())

    def existing_entries(self, series: str, kind: str) -> set[str]:
        return self._children((series, KIND_FOLDERS[kind]))

    def _children(self, segments: Sequence[str]) -> set[str]:
        out: set[str] = set()
        if self.root is None:
            return out
        for area in AREAS:
            folder = self.root / area / ROOT if not segments else self._target(area, segments)
            if folder is not None and folder.is_dir():
                out |= {p.name for p in folder.iterdir() if p.is_dir()}
        return out

    def remove(self, *segments: str) -> CleanupReport:
        """Supprime `mangaka/<segments…>` dans `output/` et `input/` (série, chapitre, page ou fiche)."""
        if self.root is None:
            return CleanupReport([], self.warning())
        removed: list[str] = []
        for area in AREAS:
            path = self._target(area, segments)
            if path is None:
                log.warning("ComfyUI : suppression refusée hors d'une série (%s)", "/".join(segments))
                return CleanupReport(removed, "chemin refusé")
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed.append(f"{area}/{ROOT}/{'/'.join(segments)}")
            elif path.is_file():
                path.unlink(missing_ok=True)
                removed.append(f"{area}/{ROOT}/{'/'.join(segments)}")
        return CleanupReport(removed)

    def move(self, source: Sequence[str], target: Sequence[str]) -> CleanupReport:
        """Renomme un dossier (série ou fiche renommée) dans `output/` et `input/`. Si la cible existe déjà,
        le dossier d'origine reste en place (rien n'est fusionné ni écrasé)."""
        if self.root is None:
            return CleanupReport([], self.warning())
        moved: list[str] = []
        for area in AREAS:
            src, dst = self._target(area, source), self._target(area, target)
            if src is None or dst is None:
                return CleanupReport(moved, "chemin refusé")
            if not src.is_dir():
                continue
            if dst.exists():
                log.warning("ComfyUI : %s existe déjà, %s n'est pas déplacé", dst, src)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            moved.append(f"{area}/{ROOT}/{'/'.join(target)}")
        return CleanupReport(moved)

    def discard_output(self, ref: ImageRef) -> bool:
        """Efface la copie d'un résultat dans `output/` une fois enregistré dans data/ (zone de transit).
        Seulement un fichier de `output/mangaka/<série>/…` ; les dossiers vidés sont retirés jusqu'à la série."""
        if self.root is None or ref.type != "output":
            return False
        segments = [s for s in ref.subfolder.replace("\\", "/").split("/") if s]
        if len(segments) < 2 or segments[0] != ROOT or "/" in ref.filename or ref.filename in ("", ".", ".."):
            return False
        folder = self._target("output", segments[1:])
        if folder is None:
            return False
        path = folder / ref.filename
        if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
            return False
        path.unlink(missing_ok=True)
        base = self._series_dir("output", segments[1])
        current = folder
        while base is not None and current != base and current.is_dir() and not any(current.iterdir()):
            current.rmdir()
            current = current.parent
        return True
