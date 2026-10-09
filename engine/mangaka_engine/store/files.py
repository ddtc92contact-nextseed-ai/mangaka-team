"""Stockage des fichiers binaires sous `data/`."""

from __future__ import annotations

import io
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

ALLOWED_IMAGE_FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp")}


class InvalidImageError(ValueError):
    pass


@dataclass
class StoredImage:
    path: str  # relatif à data/
    content_type: str
    width: int
    height: int


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def absolute(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("chemin hors de data/")
        return path

    def save_image(self, data: bytes, folder: str) -> StoredImage:
        """Vérifie que `data` est une image PNG/JPEG/WebP puis l'enregistre sous un nom unique."""
        try:
            with Image.open(io.BytesIO(data)) as img:
                fmt = img.format
                img.verify()
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise InvalidImageError("fichier illisible : ce n'est pas une image valide") from exc
        if fmt not in ALLOWED_IMAGE_FORMATS:
            raise InvalidImageError(f"format {fmt} non accepté (PNG, JPEG ou WebP)")
        ext, content_type = ALLOWED_IMAGE_FORMATS[fmt]
        rel = f"{folder.strip('/')}/{uuid.uuid4().hex}.{ext}"
        target = self.absolute(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredImage(path=rel, content_type=content_type, width=width, height=height)

    def delete(self, rel: str) -> None:
        self.absolute(rel).unlink(missing_ok=True)

    def delete_tree(self, rel_folder: str) -> None:
        shutil.rmtree(self.absolute(rel_folder), ignore_errors=True)
