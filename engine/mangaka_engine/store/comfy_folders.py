"""Rangement des fichiers de la série dans ComfyUI (`output/mangaka/` et `input/mangaka/`).

Noms (purs) : `series_folder`, `entry_folder`, `page_folder`, `panel_name` donnent les sous-dossiers des
images envoyées (`input/`) ; `transit(…)` du même chemin donne le préfixe des `SaveImage` (`output/`) :

    input/mangaka/<série>/personnages/<nom>/reference-12.png                  (image de référence envoyée)
    output/mangaka/<série>/_transit/personnages/<nom>/<fiche>/variante-1_00001_.png   (sorties brutes)
    …/objets/<nom>/…  …/decors/<nom>/…  …/vehicules/<nom>/…  …/creatures/<nom>/…  …/style/essais/…  …/style/<référence>/…
    …/chapitre-01/page-01/case-01, case-01-croquis, case-01-controle, case-01-finition, case-01-reparation…

Le reste de `output/mangaka/<série>/` est la **bibliothèque lisible** (copie rangée de ce qui est retenu,
`pipeline/comfy_library.py`) : `references/{personnages,objets,decors,vehicules,creatures,style}/…` (un sous-dossier par type de fiche),
`chapitre-01/page-01/…`, et sa corbeille `trash/…` (ce qui est généré sans être retenu).

Aucun dossier n'est créé d'avance : un dossier naît quand un fichier y est écrit, et les dossiers vidés d'une série
sont retirés après une suppression, un renommage ou une mise à jour de la bibliothèque (`prune_empty`, jamais `old/`).
« Ranger le dossier ComfyUI » (`orphans`, `tidy`) déplace dans `mangaka/old/orphelins-<date>/` les dossiers qui ne
sont à aucune série de la base (tests, démos, séries d'une autre base) — jamais de suppression.

Disque (`ComfyFolders`) : ComfyUI n'a pas d'API pour effacer un fichier, le moteur agit donc directement
dans le dossier de ComfyUI (`COMFYUI_DIR`). Sans dossier valide, rien n'est jamais supprimé ni déplacé
(`problem` dit pourquoi, affiché dans l'interface) — aucun chemin n'est deviné. Toute opération est
confinée à `mangaka/<série>/…` : segments validés (slugs), jamais `old/`, jamais un lien symbolique au
niveau de la série ou en dessous, chemin résolu vérifié. En mode mock, un `COMFYUI_DIR` qui est une vraie
installation (présence de `main.py`) est refusé : essais, QA et tests n'écrivent jamais dans le vrai ComfyUI.

La sortie brute de ComfyUI est une zone de transit (`_transit/`) : dès qu'un résultat est copié dans data/,
sa copie dans `output/` est effacée (`discard_output`). Les anciennes sorties (avant `_transit/`, directement
sous la série) restent suivies par le renommage, la suppression et le nettoyage.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..providers.comfyui.base import ImageRef
from .models import Chapter, Character, Page, Panel, Project, SeriesAsset
from .slugs import KIND_FOLDERS, RESERVED_SERIES, entry_kind_of, is_segment

log = logging.getLogger("mangaka_engine")

ROOT = "mangaka"  # sous-dossier de ComfyUI/output et ComfyUI/input
STYLE_TRIALS = "essais"  # essais de la planche de style : mangaka/<série>/style/essais/
TRANSIT = "_transit"  # sorties brutes de ComfyUI : output/mangaka/<série>/_transit/… (jamais un slug : « _ »)
REFERENCES = "references"  # bibliothèque lisible : output/mangaka/<série>/references/<sorte>/<nom>/
AREAS = ("output", "input")
DEFAULT_DIR = "~/ComfyUI"
ARCHIVE = "old"  # archives gardées à la main : mangaka/old/ (jamais touché, sauf pour y ranger des orphelins)
ORPHANS = "orphelins"  # « Ranger le dossier ComfyUI » : mangaka/old/orphelins-<date>/
INSTALL_MARKER = "main.py"  # présent dans une vraie installation de ComfyUI (refusée en mode mock)


# --- noms -------------------------------------------------------------------------------
def series_name(project: Project) -> str:
    """Segment de la série : son slug (repli `serie-<id>` pour une série pas encore enregistrée)."""
    return project.slug or f"serie-{project.id}"


def series_folder(project: Project) -> str:
    return f"{ROOT}/{series_name(project)}"


def entry_folder(entry: Character | SeriesAsset, series: Project) -> str:
    """`mangaka/<série>/personnages|objets|decors|vehicules|creatures|style/<nom>`."""
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


def transit(folder: str) -> str:
    """`mangaka/<série>/<reste>` → `mangaka/<série>/_transit/<reste>` (préfixe des sorties brutes de ComfyUI)."""
    root, series, *rest = folder.split("/")
    return "/".join([root, series, TRANSIT, *rest])


def locations(segments: Sequence[str]) -> list[tuple[str, list[str]]]:
    """Emplacements `(area, segments)` d'une série, d'un chapitre, d'une page ou d'une fiche : la série entière
    dans `output/` et `input/` ; en dessous, l'envoi (`input/`), la sortie brute (`output/…/_transit/…`), la
    bibliothèque (`output/…` pour un chapitre ou une page, `output/…/references/…` pour une fiche) et
    l'ancienne sortie d'avant `_transit/` (`output/…`, même chemin que dans `input/`)."""
    segs = list(segments)
    if len(segs) <= 1:
        return [(area, segs) for area in AREAS]
    series, rest = segs[0], segs[1:]
    out = [("output", segs), ("input", segs), ("output", [series, TRANSIT, *rest])]
    if rest[0] in KIND_FOLDERS.values():
        out.append(("output", [series, REFERENCES, *rest]))
    return out


# --- disque -----------------------------------------------------------------------------
@dataclass
class CleanupReport:
    """Ce qu'une opération a fait dans ComfyUI (`removed` : chemins relatifs à ComfyUI) ou pourquoi rien."""

    removed: list[str]
    warning: str | None = None


@dataclass
class Orphan:
    """Dossier de `<area>/mangaka/` qui n'est à aucune série de la base (`files` : nombre de fichiers dedans)."""

    area: str
    name: str
    files: int


@dataclass
class TidyReport:
    """Ce que « Ranger le dossier ComfyUI » a fait (`moved` : chemins d'arrivée relatifs à ComfyUI)."""

    moved: list[str] = field(default_factory=list)
    removed_empty: int = 0
    warning: str | None = None


def _count_files(path: Path) -> int:
    return sum(len(files) for _dir, _dirs, files in os.walk(path, followlinks=False))


def _prune_tree(base: Path) -> int:
    """Retire les dossiers vides sous `base` (compris), des plus profonds aux moins profonds : jamais un lien
    symbolique, ni `old/` ou ce qu'il contient. Renvoie le nombre de dossiers retirés."""
    if not base.is_dir() or base.is_symlink():
        return 0
    removed = 0
    for dirpath, _dirnames, _files in os.walk(base, topdown=False, followlinks=False):
        current = Path(dirpath)
        if ARCHIVE in current.relative_to(base).parts or current.is_symlink():
            continue
        try:
            if not any(current.iterdir()):
                current.rmdir()
                removed += 1
        except OSError:
            continue
    return removed


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
        if mock and (path / INSTALL_MARKER).exists():
            # Les essais en mode mock (tests, QA, démos) ne doivent jamais remplir le vrai ComfyUI de l'auteur.
            return cls(
                None,
                problem=f"mode mock : {path} est une vraie installation de ComfyUI ({INSTALL_MARKER}), rien n'y est écrit",
                mock=True,
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
        if not segments or not all(is_segment(s) or (i == 1 and s == TRANSIT) for i, s in enumerate(segments)):
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

    def target(self, area: str, segments: Sequence[str]) -> Path | None:
        """`<ComfyUI>/<area>/mangaka/<segments…>` confiné à une série (None si refusé) — bibliothèque lisible."""
        return self._target(area, segments)

    def existing_series(self) -> set[str]:
        """Dossiers de séries déjà présents dans ComfyUI (un nouveau slug les évite)."""
        return self._children(())

    def existing_entries(self, series: str, kind: str) -> set[str]:
        folder = KIND_FOLDERS[kind]
        out = self._children((series, folder))
        for prefix in (TRANSIT, REFERENCES):
            out |= self._children((series, prefix, folder), areas=("output",))
        return out

    def _children(self, segments: Sequence[str], *, areas: Sequence[str] = AREAS) -> set[str]:
        out: set[str] = set()
        if self.root is None:
            return out
        for area in areas:
            folder = self.root / area / ROOT if not segments else self._target(area, segments)
            if folder is not None and folder.is_dir():
                out |= {p.name for p in folder.iterdir() if p.is_dir()}
        return out

    def remove(self, *segments: str) -> CleanupReport:
        """Supprime `mangaka/<segments…>` (série, chapitre, page ou fiche) à tous ses emplacements
        (`locations` : envoi, sortie brute, bibliothèque)."""
        if self.root is None:
            return CleanupReport([], self.warning())
        if not segments or not all(is_segment(s) for s in segments):
            log.warning("ComfyUI : suppression refusée hors d'une série (%s)", "/".join(segments))
            return CleanupReport([], "chemin refusé")
        removed: list[str] = []
        for area, segs in locations(segments):
            path = self._target(area, segs)
            if path is None:
                log.warning("ComfyUI : suppression refusée hors d'une série (%s)", "/".join(segs))
                return CleanupReport(removed, "chemin refusé")
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed.append(f"{area}/{ROOT}/{'/'.join(segs)}")
            elif path.is_file():
                path.unlink(missing_ok=True)
                removed.append(f"{area}/{ROOT}/{'/'.join(segs)}")
        if len(segments) > 1:
            self.prune_empty(segments[0])
        return CleanupReport(removed)

    def clear_transit(self, series: str) -> CleanupReport:
        """« Nettoyer » : vide les envois (`input/mangaka/<série>`), les sorties brutes (`_transit/`) et les
        anciennes sorties d'avant `_transit/` (`personnages/`, `objets/`, `decors/`, `style/` sous la série) ;
        la bibliothèque lisible reste (les fichiers de transit d'avant restés dans un chapitre sont retirés par
        `ComfyLibrary.sync(…, purge=True)`)."""
        if self.root is None:
            return CleanupReport([], self.warning())
        removed: list[str] = []
        targets = [("input", [series]), ("output", [series, TRANSIT])]
        targets += [("output", [series, folder]) for folder in KIND_FOLDERS.values()]
        for area, segs in targets:
            path = self._target(area, segs)
            if path is None:
                return CleanupReport(removed, "chemin refusé")
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed.append(f"{area}/{ROOT}/{'/'.join(segs)}")
        return CleanupReport(removed)

    def move(self, source: Sequence[str], target: Sequence[str]) -> CleanupReport:
        """Renomme un dossier (série ou fiche renommée) à tous ses emplacements (`locations`). Si la cible
        existe déjà, le dossier d'origine reste en place (rien n'est fusionné ni écrasé)."""
        if self.root is None:
            return CleanupReport([], self.warning())
        moved: list[str] = []
        for (area, src_segs), (_, dst_segs) in zip(locations(source), locations(target), strict=True):
            src, dst = self._target(area, src_segs), self._target(area, dst_segs)
            if src is None or dst is None:
                return CleanupReport(moved, "chemin refusé")
            if not src.is_dir():
                continue
            if dst.exists():
                log.warning("ComfyUI : %s existe déjà, %s n'est pas déplacé", dst, src)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            moved.append(f"{area}/{ROOT}/{'/'.join(dst_segs)}")
        for series in dict.fromkeys((source[0], target[0])):
            self.prune_empty(series)
        return CleanupReport(moved)

    def prune_empty(self, series: str) -> int:
        """Retire les dossiers vides de la série (`output/` et `input/`, dossier de la série compris) : un dossier
        n'existe que s'il contient un fichier. Jamais `old/` ni un lien symbolique. Renvoie le nombre retiré."""
        removed = 0
        for area in AREAS:
            base = self._target(area, [series])
            if base is not None:
                removed += _prune_tree(base)
        return removed

    # --- « Ranger le dossier ComfyUI » ---------------------------------------------------------
    def orphans(self, known: Iterable[str]) -> list[Orphan]:
        """Dossiers de `output/mangaka/` et `input/mangaka/` qui ne sont à aucune série connue (hors `old/` et
        liens symboliques), avec leur nombre de fichiers."""
        if self.root is None:
            return []
        keep = set(known) | {ARCHIVE}
        out: list[Orphan] = []
        for area in AREAS:
            folder = self.root / area / ROOT
            if not folder.is_dir() or folder.is_symlink():
                continue
            for path in sorted(folder.iterdir(), key=lambda p: p.name):
                if path.name in keep or path.is_symlink() or not path.is_dir():
                    continue
                out.append(Orphan(area, path.name, _count_files(path)))
        return out

    def tidy(self, known: Iterable[str], chosen: Iterable[tuple[str, str]], *, day: date | None = None) -> TidyReport:
        """Déplace les orphelins choisis (`(area, nom)`, encore orphelins) dans `<area>/mangaka/old/orphelins-<date>/`
        — jamais de suppression, une série connue n'est jamais déplacée —, puis retire les dossiers vides des
        séries connues."""
        if self.root is None:
            return TidyReport(warning=self.warning() or "dossier ComfyUI inconnu (COMFYUI_DIR)")
        known = set(known)
        current = {(o.area, o.name) for o in self.orphans(known)}
        stamp = f"{ORPHANS}-{(day or date.today()).isoformat()}"
        report = TidyReport()
        for area, name in dict.fromkeys(chosen):
            if (area, name) not in current:
                continue
            source = self.root / area / ROOT / name
            archive = self.root / area / ROOT / ARCHIVE / stamp
            target, n = archive / name, 2
            while target.exists() or target.is_symlink():  # même jour, même nom : rien n'est écrasé
                target, n = archive / f"{name}-{n}", n + 1
            try:
                archive.mkdir(parents=True, exist_ok=True)
                source.rename(target)
            except OSError as exc:
                log.warning("ComfyUI : %s non rangé (%s)", source, exc)
                continue
            report.moved.append(str(target.relative_to(self.root)))
        for series in sorted(known):
            report.removed_empty += self.prune_empty(series)
        return report

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
