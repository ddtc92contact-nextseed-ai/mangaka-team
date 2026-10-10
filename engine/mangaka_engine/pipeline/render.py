"""Étape 5 appliquée aux pages en base : lettrage, rendu PNG / SVG d'une page, export ZIP d'un chapitre.

Fichiers produits (jamais commités) :

- `data/renders/page-<id>/page-<NNN>.png|svg` + `render.json` : dernier rendu d'une page ;
- `data/exports/chapter-<id>/<série>-ch<NNN>-<job>.zip` : export d'un chapitre (pages numérotées).

Boîtes de visages : le lettrage évite les visages détectés par le contrôle qualité sur la version
retenue. Elles sont lues dans les paramètres de la version (`PanelImage.params`), en px de l'image
d'origine (ou normalisées 0–1) : `faces`, ou `qc.faces` / `qc.boxes.faces` / `detections.faces`,
chaque boîte au format `{x1, y1, x2, y2}`, `{x, y, w, h}`, `[x1, y1, x2, y2]` ou `{"box": …}`.
Sans boîte, seule la zone réservée aux bulles compte.

Onomatopées : bulles `kind = sfx` ; leurs réglages imposés (`Bubble.sfx` : intensité, police, taille,
angle, cisaillement) et leur centre placé à la main (`Bubble.position` : {"x", "y", "manual"}).
Cases à fond perdu : le lettrage reste dans la partie de la case dans la zone utile (`live_polygon`) ;
une incrustation est un obstacle pour les bulles et onomatopées de sa case hôte.
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
from ..store.files import FileStore, versioned_url
from ..store.models import Bubble, BubbleKind, Chapter, ImageKind, Job, Page, Panel, PanelImage
from .assembly import Canvas, PageArt, PanelArt, canvas_geometry, cover_transform, png_bytes, render_png, render_svg
from .finishing import finished_art, panel_print_info
from .fonts import FontBook
from .jobs import JobReporter
from .lettering import Box, BubbleSpec, Letterer, LetteringError, LetteringWarning, PanelSpec, SfxSpec
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
    """Version assemblée : la version choisie, jamais un croquis (palier croquis)."""
    return next((i for i in panel.images if i.selected and i.kind == ImageKind.final), None)


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


def _num(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def sfx_spec(b: Bubble) -> SfxSpec:
    """Onomatopée en base → spec du lettrage (valeurs absentes ou illisibles = calculées)."""
    params = b.sfx or {}
    pos = b.position or {}
    center = None
    if pos.get("manual") and _num(pos.get("x")) is not None and _num(pos.get("y")) is not None:
        center = (float(pos["x"]), float(pos["y"]))
    size = _num(params.get("size_pt"))
    return SfxSpec(
        id=b.id,
        text=b.text,
        order=b.order,
        intensity=params.get("intensity") if params.get("intensity") in ("calme", "normal", "choc") else None,
        font=params.get("font") if isinstance(params.get("font"), str) else None,
        size_pt=size if size and size > 0 else None,
        angle=_num(params.get("angle")),
        skew=_num(params.get("skew")),
        center=center,
    )


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
    layout_panels = {lp.get("panel_id"): lp for lp in page.layout.get("panels", [])}
    index_to_id = {lp.get("index"): lp.get("panel_id") for lp in page.layout.get("panels", [])}
    # Incrustations : obstacles pour le lettrage de leur case hôte.
    insets: dict[int, list[Box]] = {}
    for lp in layout_panels.values():
        host = index_to_id.get(lp.get("host_index")) if lp.get("inset") else None
        rect = Box.parse(lp)
        if host is not None and rect is not None:
            insets.setdefault(host, []).append(rect)
    for panel in page.panels:
        box = Box.parse(panel.bbox)
        lp = layout_panels.get(panel.id) or {}
        # Polygone de la case (mise en page ≥ v2) ; une ancienne mise en page n'a que la boîte.
        raw_poly = lp.get("polygon")
        polygon = [(float(x), float(y)) for x, y in raw_poly] if raw_poly else None
        raw_live = lp.get("live_polygon")
        live = [(float(x), float(y)) for x, y in raw_live] if raw_live else None
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
            # Aperçu écran : l'image légère ; visages en px de la version (même cadrage que sa finition).
            urls[panel.id] = versioned_url(f"/panel-images/{img.id}/file", img.path)
            faces = faces_on_page(face_boxes(img, size), size, box)
            # Finition d'impression : l'assemblage prend l'image agrandie quand elle existe.
            finished = finished_art(img, files)
            if finished is not None:
                path, size = finished
        faces_by_panel[panel.id] = faces
        panels.append(
            PanelArt(
                id=panel.id,
                index=panel.index,
                box=box,
                image=path,
                image_size=size,
                polygon=polygon,
                frame=lp.get("frame") if lp.get("frame") in ("border", "none", "fade") else "border",
                inset=bool(lp.get("inset")),
            )
        )
        # Fond perdu : bulles et onomatopées restent dans la zone utile.
        letter_box, letter_poly = box, polygon
        if live:
            xs, ys = [x for x, _ in live], [y for _, y in live]
            letter_box, letter_poly = Box(min(xs), min(ys), max(xs), max(ys)), live
        specs.append(
            PanelSpec(
                id=panel.id,
                index=panel.index,
                box=letter_box,
                zone=Box.parse(panel.bubble_zone),
                faces=[f2 for f in faces if (f2 := f.intersection(letter_box)) is not None],
                characters=list(panel.character_names or []),
                polygon=letter_poly,
                sfx=[sfx_spec(b) for b in panel.bubbles if b.kind == BubbleKind.sfx],
                obstacles=insets.get(panel.id, []),
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
                    if b.kind != BubbleKind.sfx
                ],
            )
        )
    page_box = Box(0, 0, fmt.width_px, fmt.height_px)
    lettering = Letterer(fonts, presets.lettering, fmt.dpi).letter_page(specs, direction, page_box)
    art = PageArt(
        number=page.number, fmt=fmt, panels=panels, lettering=lettering, warnings=warnings + lettering.warnings
    )
    return PageInputs(art=art, specs=specs, faces=faces_by_panel, image_urls=urls, stale=stale)


def lettering_json(
    page: Page, inputs: PageInputs, fonts: FontBook, presets: PresetRegistry | None = None
) -> dict[str, Any]:
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
    sfx_fonts = {
        font_id: {
            "family": fonts.family(st := fonts.sfx_style(font_id)),
            "name": fonts.name(st),
            "url": f"/lettering/sfx-fonts/{font_id}.ttf?project_id={page.chapter.project_id}",
        }
        for font_id in fonts.preset.sfx_choices()
    }
    layout_panels = {lp.get("panel_id"): lp for lp in (page.layout or {}).get("panels", [])}
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
        "sfx_fonts": sfx_fonts,
        "sfx_settings": {
            "max_overflow_mm": presets.lettering.sfx.max_overflow_mm if presets else None,
        },
        "panels": [
            {
                "id": p.id,
                "index": p.index,
                "box": p.box.as_rect(),
                "polygon": [[round(x, 1), round(y, 1)] for x, y in p.polygon]
                if p.polygon and (p.slanted or (layout_panels.get(p.id) or {}).get("bleed"))
                else None,
                "frame": p.frame,
                "inset": p.inset,
                "bleed": bool((layout_panels.get(p.id) or {}).get("bleed")),
                "bubble_zone": spec.zone.as_rect() if spec.zone else None,
                "image_url": inputs.image_urls.get(p.id),
                "faces": [f.as_rect() for f in inputs.faces.get(p.id, [])],
            }
            for p, spec in zip(art.panels, inputs.specs, strict=True)
        ],
        "bubbles": [b.to_json() for b in art.lettering.bubbles],
        "sfx": [x.to_json() for x in art.lettering.sfx],
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


def low_dpi_warnings(presets: PresetRegistry, files: FileStore, page: Page) -> list[dict[str, Any]]:
    """Cases de la page sous le seuil de dpi à l'impression (ni assez grandes, ni finalisées)."""
    out = []
    for panel in page.panels:
        info = panel_print_info(presets, files, panel)
        if info is not None and info["status"] == "low":
            out.append(
                {
                    "code": "low_dpi",
                    "message": (
                        f"Case {panel.index + 1} : {info['finished_dpi'] or info['dpi']} dpi à l'impression "
                        f"(cible {info['target_dpi']}) — « Finaliser la page » pour l'agrandir."
                    ),
                    "panel_id": panel.id,
                    "page_number": page.number,
                }
            )
    return out


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
                    warnings += low_dpi_warnings(presets, files, page)
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
