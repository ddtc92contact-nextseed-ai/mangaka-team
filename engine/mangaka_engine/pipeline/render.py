"""Étape 5 appliquée aux pages en base : lettrage, rendu PNG / SVG d'une page, export ZIP d'un chapitre.

Fichiers produits (jamais commités) :

- `data/renders/page-<id>/page-<NNN>.png|svg` + `render.json` : dernier rendu d'une page ;
- `data/exports/chapter-<id>/<série>-ch<NNN>-<job>.zip` : export d'un chapitre (pages numérotées).

Boîtes de visages : le lettrage évite les visages détectés par le contrôle qualité sur la version
retenue. Elles sont lues dans les paramètres de la version (`PanelImage.params`), en px de l'image
d'origine (ou normalisées 0–1) : `faces`, ou `qc.faces` / `qc.boxes.faces` / `detections.faces`,
chaque boîte au format `{x1, y1, x2, y2}`, `{x, y, w, h}`, `[x1, y1, x2, y2]` ou `{"box": …}`.
Sans boîte, seule la zone réservée aux bulles compte.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..presets import PresetError, PresetRegistry
from ..store.db import Database
from ..store.files import FileStore
from ..store.models import Chapter, Job, Page, Panel, PanelImage
from .assembly import Canvas, PageArt, PanelArt, canvas_geometry, cover_transform, png_bytes, render_png, render_svg
from .fonts import FontBook
from .jobs import JobReporter
from .lettering import Box, BubbleSpec, Letterer, LetteringError, LetteringWarning, PanelSpec
from .pages import is_stale

STEP = "export"


# --- visages (QC) ---------------------------------------------------------------------------
_FACE_KEYS = ("faces", "face")
_NESTED_KEYS = ("qc", "boxes", "detections", "detectors", "qc_boxes")


def _face_items(obj: Any, depth: int = 0) -> list[Any] | None:
    if depth > 4 or not isinstance(obj, dict):
        return None
    for key in _FACE_KEYS:
        if isinstance(obj.get(key), list):
            return obj[key]
    for key in _NESTED_KEYS:
        found = _face_items(obj.get(key), depth + 1)
        if found is not None:
            return found
    for key in _NESTED_KEYS:  # liste mixte étiquetée : [{"label": "face", "box": …}, …]
        items = obj.get(key)
        if isinstance(items, list):
            tagged = [
                i
                for i in items
                if isinstance(i, dict)
                and str(i.get("label") or i.get("kind") or i.get("class") or "").lower() in _FACE_KEYS
            ]
            if tagged:
                return tagged
    return None


def face_boxes(img: PanelImage, size: tuple[int, int]) -> list[Box]:
    """Boîtes de visages de la version, en px de l'image."""
    items = _face_items(dict(img.params or {}))
    if items is None:
        for attr in ("qc_boxes", "boxes", "detections"):  # colonne éventuelle ajoutée par le QC
            items = _face_items({"qc": getattr(img, attr, None)})
            if items is not None:
                break
    out: list[Box] = []
    for item in items or []:
        raw = (
            item.get("box") or item.get("bbox")
            if isinstance(item, dict) and ("box" in item or "bbox" in item)
            else item
        )
        box = Box.parse(raw)
        if box is None:
            continue
        if max(box.x2, box.y2) <= 1.0:  # coordonnées normalisées
            box = Box(box.x1 * size[0], box.y1 * size[1], box.x2 * size[0], box.y2 * size[1])
        out.append(box)
    return out


def faces_on_page(faces: list[Box], size: tuple[int, int], panel: Box) -> list[Box]:
    """Boîtes de l'image → px de la page, via le recadrage « au remplissage » de la case."""
    scale, x0, y0 = cover_transform(size[0], size[1], panel)
    out = []
    for f in faces:
        mapped = Box(x0 + f.x1 * scale, y0 + f.y1 * scale, x0 + f.x2 * scale, y0 + f.y2 * scale).intersection(panel)
        if mapped is not None:
            out.append(mapped)
    return out


# --- page en base → lettrage ---------------------------------------------------------------
@dataclass
class PageInputs:
    art: PageArt
    specs: list[PanelSpec]
    faces: dict[int, list[Box]]
    image_urls: dict[int, str | None]
    stale: bool


def selected_image(panel: Panel) -> PanelImage | None:
    return next((i for i in panel.images if i.selected), None)


def _image_size(img: PanelImage, files: FileStore) -> tuple[int, int] | None:
    params = img.params or {}
    w, h = params.get("image_width"), params.get("image_height")
    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
        return w, h
    try:
        with Image.open(files.absolute(img.path)) as im:
            return im.size
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def _manual_box(position: dict[str, Any] | None) -> Box | None:
    if not position or not position.get("manual"):
        return None
    return Box.parse(position)


def _manual_tail(tail: dict[str, Any] | None) -> tuple[float, float] | None:
    if not tail or not tail.get("manual"):
        return None
    try:
        return float(tail["x"]), float(tail["y"])
    except (KeyError, TypeError, ValueError):
        return None


def page_inputs(presets: PresetRegistry, files: FileStore, page: Page, fonts: FontBook) -> PageInputs:
    if not page.panels:
        raise LetteringError(f"page {page.number} sans case : rien à assembler")
    if page.layout is None:
        raise LetteringError(f"page {page.number} pas encore mise en page : calcule la mise en page d'abord")
    fmt = presets.page_format(page.layout.get("page_format") or page.chapter.project.page_format)
    direction = page.layout.get("direction") or page.chapter.project.reading_direction.value
    warnings: list[LetteringWarning] = []
    stale = is_stale(page)
    if stale:
        warnings.append(LetteringWarning("layout_stale", "Mise en page obsolète : recalcule-la pour des cases à jour."))
    panels: list[PanelArt] = []
    specs: list[PanelSpec] = []
    faces_by_panel: dict[int, list[Box]] = {}
    urls: dict[int, str | None] = {}
    for panel in page.panels:
        box = Box.parse(panel.bbox)
        if box is None:
            warnings.append(
                LetteringWarning(
                    "no_layout", f"Case {panel.index + 1} : pas de coordonnées, recalcule la mise en page.", panel.id
                )
            )
            continue
        img = selected_image(panel)
        path = files.absolute(img.path) if img is not None else None
        size = _image_size(img, files) if img is not None else None
        if path is None or not path.is_file() or size is None:
            path, size = None, None
            urls[panel.id] = None
            warnings.append(
                LetteringWarning(
                    "missing_image",
                    f"Case {panel.index + 1} : aucune version choisie — aplat gris « case manquante ».",
                    panel.id,
                )
            )
            faces: list[Box] = []
        else:
            assert img is not None
            urls[panel.id] = f"/panel-images/{img.id}/file"
            faces = faces_on_page(face_boxes(img, size), size, box)
        faces_by_panel[panel.id] = faces
        panels.append(PanelArt(id=panel.id, index=panel.index, box=box, image=path, image_size=size))
        specs.append(
            PanelSpec(
                id=panel.id,
                index=panel.index,
                box=box,
                zone=Box.parse(panel.bubble_zone),
                faces=faces,
                characters=list(panel.character_names or []),
                bubbles=[
                    BubbleSpec(
                        id=b.id,
                        kind=b.kind.value,
                        text=b.text,
                        speaker=b.speaker_name,
                        order=b.order,
                        manual_box=_manual_box(b.position),
                        manual_tail=_manual_tail(b.tail),
                    )
                    for b in panel.bubbles
                ],
            )
        )
    lettering = Letterer(fonts, presets.lettering, fmt.dpi).letter_page(specs, direction)
    art = PageArt(
        number=page.number, fmt=fmt, panels=panels, lettering=lettering, warnings=warnings + lettering.warnings
    )
    return PageInputs(art=art, specs=specs, faces=faces_by_panel, image_urls=urls, stale=stale)


def lettering_json(page: Page, inputs: PageInputs, fonts: FontBook) -> dict[str, Any]:
    """Ce que l'écran Lettrage affiche : planche, cases, bulles calculées, avertissements."""
    art = inputs.art
    styles = {
        kind: {
            "family": fonts.family(st),
            "name": fonts.name(st),
            "url": f"/lettering/fonts/{kind}.ttf?project_id={page.chapter.project_id}",
            "size_pt": st.size_pt,
        }
        for kind, st in fonts.preset.styles.items()
    }
    return {
        "page_id": page.id,
        "page_number": page.number,
        "chapter_id": page.chapter_id,
        "dpi": art.fmt.dpi,
        "page_format": art.fmt.id,
        "direction": page.layout.get("direction") if page.layout else None,
        "width": art.fmt.width_px,
        "height": art.fmt.height_px,
        "bleed_mm": art.fmt.bleed_mm,
        "layout_stale": inputs.stale,
        "styles": styles,
        "panels": [
            {
                "id": p.id,
                "index": p.index,
                "box": p.box.as_rect(),
                "bubble_zone": spec.zone.as_rect() if spec.zone else None,
                "image_url": inputs.image_urls.get(p.id),
                "faces": [f.as_rect() for f in inputs.faces.get(p.id, [])],
            }
            for p, spec in zip(art.panels, inputs.specs, strict=True)
        ],
        "bubbles": [b.to_json() for b in art.lettering.bubbles],
        "warnings": [w.to_json() for w in art.warnings],
    }


# --- rendu ---------------------------------------------------------------------------------
@dataclass
class RenderedPage:
    png: bytes
    svg: str
    canvas: Canvas
    warnings: list[LetteringWarning]


def render_art(
    presets: PresetRegistry, fonts: FontBook, art: PageArt, *, bleed: bool, crop_marks: bool
) -> RenderedPage:
    canvas = canvas_geometry(art.fmt, presets.lettering, bleed=bleed, crop_marks=crop_marks)
    img = render_png(art, fonts, presets.lettering, canvas)
    svg = render_svg(art, fonts, presets.lettering, canvas)
    return RenderedPage(png=png_bytes(img, art.fmt.dpi), svg=svg, canvas=canvas, warnings=art.warnings)


def render_folder(page_id: int) -> str:
    return f"renders/page-{page_id}"


def page_file_stem(number: int) -> str:
    return f"page-{number:03d}"


def render_page_to_files(
    presets: PresetRegistry, files: FileStore, page: Page, *, bleed: bool, crop_marks: bool
) -> dict[str, Any]:
    """Rend la page (PNG + SVG) dans `data/renders/page-<id>/` et renvoie la description du rendu."""
    fonts = FontBook(presets)
    rendered = render_art(
        presets, fonts, page_inputs(presets, files, page, fonts).art, bleed=bleed, crop_marks=crop_marks
    )
    folder = render_folder(page.id)
    files.delete_tree(folder)
    stem = page_file_stem(page.number)
    target = files.absolute(f"{folder}/{stem}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rendered.png)
    files.absolute(f"{folder}/{stem}.svg").write_text(rendered.svg, encoding="utf-8")
    info = {
        "page_id": page.id,
        "page_number": page.number,
        "stem": stem,
        "bleed": bleed,
        "crop_marks": crop_marks,
        "width": rendered.canvas.width,
        "height": rendered.canvas.height,
        "dpi": page.layout["dpi"] if page.layout else None,
        "rendered_at": datetime.now(UTC).isoformat(),
        "warnings": [w.to_json() for w in rendered.warnings],
    }
    files.absolute(f"{folder}/render.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def read_render_info(files: FileStore, page_id: int) -> dict[str, Any] | None:
    path = files.absolute(f"{render_folder(page_id)}/render.json")
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "serie"


def export_name(chapter: Chapter, job_id: int) -> str:
    return f"{_slug(chapter.project.title)}-ch{chapter.number:03d}-{job_id}.zip"


def load_chapter_pages(session: Session, chapter_id: int) -> list[Page]:
    return list(
        session.scalars(
            select(Page)
            .where(Page.chapter_id == chapter_id)
            .options(
                selectinload(Page.panels).selectinload(Panel.bubbles),
                selectinload(Page.panels).selectinload(Panel.images),
            )
            .order_by(Page.number)
        )
    )


def export_job(
    db: Database,
    presets: PresetRegistry,
    files: FileStore,
    chapter_id: int,
    job_id: int,
    *,
    bleed: bool,
    crop_marks: bool,
) -> Callable[[JobReporter], str]:
    """Job « Exporter le chapitre » : chaque page mise en page → PNG + SVG numérotés dans un ZIP."""

    def run(report: JobReporter) -> str:
        fonts = FontBook(presets)
        with db.session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise LetteringError("chapitre supprimé pendant l'export")
            pages = [p for p in load_chapter_pages(session, chapter_id) if p.panels and p.layout]
            if not pages:
                raise LetteringError("aucune page mise en page dans ce chapitre : rien à exporter")
            name = export_name(chapter, job_id)
            rel = f"exports/chapter-{chapter_id}/{name}"
            target = files.absolute(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            warnings: list[dict[str, Any]] = []
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for i, page in enumerate(pages):
                    report(round(100 * i / len(pages)), f"Page {page.number} ({i + 1}/{len(pages)})…")
                    try:
                        art = page_inputs(presets, files, page, fonts).art
                    except PresetError as exc:
                        raise LetteringError(str(exc)) from None
                    rendered = render_art(presets, fonts, art, bleed=bleed, crop_marks=crop_marks)
                    stem = page_file_stem(page.number)
                    zf.writestr(f"{stem}.png", rendered.png)
                    zf.writestr(f"{stem}.svg", rendered.svg)
                    warnings += [{**w.to_json(), "page_number": page.number} for w in rendered.warnings]
            target.write_bytes(buf.getvalue())
            job = session.get(Job, job_id)
            params = dict(job.params or {}) if job else {}
            params.update({"file": rel, "filename": name, "pages": len(pages), "warnings": warnings})
            session.execute(update(Job).where(Job.id == job_id).values(params=params))
            session.commit()
        n = len(pages)
        tail = f" · {len(warnings)} avertissement{'s' if len(warnings) > 1 else ''}" if warnings else ""
        return f"{n} page{'s' if n > 1 else ''} exportée{'s' if n > 1 else ''}{tail}"

    return run
