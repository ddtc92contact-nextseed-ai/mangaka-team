"""ComfyUI factice : sans GPU ni réseau.

Renvoie une image à la taille demandée, avec le libellé de la case (dernier segment du
`filename_prefix` du nœud SaveImage, ex. « case 3 ») et la seed dessinés dessus ; simule une
progression par étapes ; vérifie que les images des `LoadImage` / `LoadImageMask` ont été envoyées.

Palier croquis : un croquis (libellé « croquis case N ») est un crayonné gris sur papier dont la
composition (formes) dépend de la graine ; un workflow image → image sans masque (`VAEEncode` d'une
image chargée) repart de l'image envoyée, agrandie à la taille demandée et « encrée » : même composition.

Inpainting (un `VAEEncode` part d'une `LoadImage` et un `LoadImageMask` est présent) : renvoie l'image
source, légèrement modifiée partout (comme le ferait l'aller-retour VAE) et remplie d'une couleur tirée
de la seed dans la zone masquée — le moteur doit recoller seulement la zone pour garder le reste intact.

Composition verrouillée (ControlNet, patch de modèle) : un nœud qui reçoit un `model_patch` et une
`image` repart de l'image guide envoyée (même composition), légendée « CONTROLNET ». Aperçu de la carte
de contrôle (workflow sans latent avec un prétraitement : classe `…Preprocessor` ou `Canny`) : contours
de l'image guide, trait noir sur blanc.

Agrandissement (finition d'impression) : un autre workflow sans latent vide (`Empty…`) qui charge une image
envoyée renvoie cette image redimensionnée (Pillow, lanczos) à la taille demandée — celle du nœud de
taille finale — sans GPU ni modèle.
"""

from __future__ import annotations

import io
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .base import (
    ComfyStatus,
    ComfyUIError,
    ComfyUIInterruptedError,
    ComfyUIUnavailableError,
    ComfyUIWorkflowError,
    ImageRef,
    ProgressFn,
    StopFn,
    check_prompt_nodes,
)

DEFAULT_SIZE = (512, 512)
DEFAULT_STEPS = 8
MAX_REPORTED_STEPS = 30

# LoRA « vus » par le ComfyUI factice (sélecteur de LoRA de l'interface), sous-dossiers compris.
MOCK_LORAS = (
    "encre-seinen_v2.safetensors",
    "trame-shojo.safetensors",
    "personnages/aiko_v1.safetensors",
    "personnages/kenji_v3.safetensors",
    "styles/aquarelle/lavis-doux.safetensors",
)


def requested_size(workflow: dict[str, Any]) -> tuple[int, int]:
    """Cherche la première paire d'entrées entières width/height (ex. nœud latent vide)."""
    for node in workflow.values():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        w, h = inputs.get("width"), inputs.get("height")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            return w, h
    return DEFAULT_SIZE


def _first_int(workflow: dict[str, Any], key: str) -> int | None:
    for node in workflow.values():
        value = node.get("inputs", {}).get(key) if isinstance(node, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _label(workflow: dict[str, Any]) -> str:
    for node in workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
            prefix = str(node.get("inputs", {}).get("filename_prefix") or "")
            last = prefix.rstrip("/").rsplit("/", 1)[-1]
            return last.replace("-", " ").replace("_", " ").strip()
    return ""


def source_upload(workflow: dict[str, Any], uploads: dict[str, bytes]) -> bytes | None:
    """Image envoyée d'un workflow image → image (agrandissement) ; None pour une génération."""
    nodes = [n for n in workflow.values() if isinstance(n, dict)]
    if any(str(n.get("class_type") or "").startswith("Empty") for n in nodes):
        return None
    for node in nodes:
        if node.get("class_type") == "LoadImage":
            image = node.get("inputs", {}).get("image")
            if image in uploads:
                return uploads[image]
    return None


def resize_image(data: bytes, width: int, height: int) -> bytes:
    with Image.open(io.BytesIO(data)) as src:
        out = src.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):  # Pillow sans FreeType
        return ImageFont.load_default()


def render_mock_image(width: int, height: int, seed: int, label: str) -> bytes:
    color = (seed * 37 % 200 + 30, seed * 91 % 200 + 30, seed * 53 % 200 + 30)
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    side = min(width, height)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(255, 255, 255), width=max(2, side // 100))
    lines = [line for line in (label.upper(), f"seed {seed}", f"{width}x{height}") if line]
    sizes = [max(12, side // 6), max(10, side // 16), max(10, side // 16)][: len(lines)]
    y = height / 2 - sum(sizes) * 0.7
    for line, size in zip(lines, sizes, strict=True):
        font = _font(size)
        draw.text(
            (width / 2, y),
            line,
            fill=(255, 255, 255),
            font=font,
            anchor="ma",
            stroke_width=max(1, size // 15),
            stroke_fill=(0, 0, 0),
        )
        y += size * 1.4
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_mock_sketch(width: int, height: int, seed: int, label: str) -> bytes:
    """Crayonné : papier clair, formes grises placées selon la graine (la « composition »), libellé."""
    img = Image.new("RGB", (width, height), (246, 243, 234))
    draw = ImageDraw.Draw(img)
    side = min(width, height)
    stroke = max(2, side // 120)
    x = seed % 9973
    for i in range(4):
        x = (x * 7919 + 104729 + i) % 9973
        cx, cy = width * (0.15 + 0.7 * (x % 101) / 100), height * (0.2 + 0.6 * ((x // 101) % 97) / 96)
        r = side * (0.08 + 0.12 * ((x // 7) % 10) / 10)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(110, 110, 110), width=stroke)
        draw.line((cx, cy + r, cx + (x % 3 - 1) * r, min(height, cy + 3 * r)), fill=(130, 130, 130), width=stroke)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(150, 150, 150), width=stroke)
    font = _font(max(10, side // 10))
    draw.text((width / 2, height * 0.06), label.upper(), fill=(90, 90, 90), font=font, anchor="ma")
    draw.text((width / 2, height * 0.9), f"seed {seed}", fill=(90, 90, 90), font=_font(max(9, side // 18)), anchor="ma")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_mock_from_image(
    source: bytes, width: int, height: int, seed: int, denoise: float | None, *, caption: str | None = None
) -> bytes:
    """Image → image : la source agrandie à la taille demandée, encrée (même composition), légendée."""
    with Image.open(io.BytesIO(source)) as src:
        base = ImageOps.grayscale(src.convert("RGB")).resize((width, height), Image.Resampling.LANCZOS)
    base = ImageOps.autocontrast(base, cutoff=2)
    tint = (seed * 37 % 120 + 120, seed * 91 % 120 + 120, seed * 53 % 120 + 120)
    img = ImageOps.colorize(base, black=(15, 15, 25), white=tint)
    draw = ImageDraw.Draw(img)
    side = min(width, height)
    size = max(10, side // 16)
    text = caption or f"PROPRE · seed {seed}" + (f" · denoise {denoise:g}" if denoise is not None else "")
    draw.text(
        (width / 2, height - size * 1.6),
        text,
        fill=(255, 255, 255),
        font=_font(size),
        anchor="ma",
        stroke_width=max(1, size // 15),
        stroke_fill=(0, 0, 0),
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_mock_control_map(source: bytes, width: int, height: int, *, inverted: bool = False) -> bytes:
    """Carte de contrôle simulée : contours de l'image guide, trait blanc sur fond noir comme les
    prétraitements réels ; `inverted` (nœud `ImageInvert` dans le graphe) : trait noir sur papier blanc."""
    with Image.open(io.BytesIO(source)) as src:
        base = ImageOps.grayscale(src.convert("RGB")).resize((width, height), Image.Resampling.LANCZOS)
    edges = ImageOps.autocontrast(base.filter(ImageFilter.FIND_EDGES), cutoff=1)
    out = edges.point(lambda v: 255 if v > 40 else 0)
    if inverted:
        out = ImageOps.invert(out)
    buf = io.BytesIO()
    out.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def is_preprocessor(class_type: str) -> bool:
    return class_type.endswith("Preprocessor") or class_type == "Canny"


def _linked(workflow: dict[str, Any], value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
        node = workflow.get(value[0])
        return node if isinstance(node, dict) else None
    return None


def source_image_name(workflow: dict[str, Any]) -> str | None:
    """Image chargée qui alimente un `VAEEncode` (workflow image → image), en remontant les liaisons."""
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "VAEEncode":
            continue
        current = _linked(workflow, node.get("inputs", {}).get("pixels"))
        for _ in range(8):
            if current is None:
                break
            if current.get("class_type") == "LoadImage":
                image = current.get("inputs", {}).get("image")
                return image if isinstance(image, str) else None
            current = _linked(workflow, current.get("inputs", {}).get("image"))
    return None


def control_image_name(workflow: dict[str, Any]) -> tuple[str, float | None] | None:
    """(image guide, force) d'un workflow ControlNet : nœud à `model_patch`, en remontant son `image`."""
    for node in workflow.values():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        if "model_patch" not in inputs:
            continue
        strength = inputs.get("strength")
        current = _linked(workflow, inputs.get("image"))
        for _ in range(8):
            if current is None:
                break
            if current.get("class_type") == "LoadImage":
                image = current.get("inputs", {}).get("image")
                if isinstance(image, str):
                    return image, float(strength) if isinstance(strength, int | float) else None
                break
            current = _linked(workflow, current.get("inputs", {}).get("image"))
    return None


def _first_float(workflow: dict[str, Any], key: str) -> float | None:
    for node in workflow.values():
        value = node.get("inputs", {}).get(key) if isinstance(node, dict) else None
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


def render_mock_inpaint(source: bytes, mask: bytes, seed: int) -> bytes:
    """Inpainting simulé : dérive légère partout (aller-retour VAE), zone masquée remplie d'une couleur."""
    with Image.open(io.BytesIO(source)) as src, Image.open(io.BytesIO(mask)) as msk:
        base = src.convert("RGB").point(lambda v: min(255, v + 3))
        color = (seed * 53 % 200 + 40, seed * 37 % 200 + 40, seed * 91 % 200 + 40)
        fill = Image.new("RGB", base.size, color)
        draw = ImageDraw.Draw(fill)
        side = min(base.size)
        for x in range(0, base.width, max(8, side // 24)):  # hachures : la zone repeinte se voit
            draw.line((x, 0, x - base.height, base.height), fill=(255, 255, 255), width=max(1, side // 200))
        alpha = msk.convert("L").resize(base.size)
        out = Image.composite(fill, base, alpha)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


class MockComfyUIClient:
    name = "mock"

    def __init__(
        self,
        *,
        online: bool = True,
        seconds_per_image: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        loras: Sequence[str] = MOCK_LORAS,
    ) -> None:
        self.online = online
        self.loras = list(loras)
        self.seconds_per_image = seconds_per_image
        self._sleep = sleep
        self.prompts: dict[str, dict[str, Any]] = {}
        self.uploads: dict[str, bytes] = {}
        self.interrupts: list[str | None] = []
        self._images: dict[str, bytes] = {}
        self._history: dict[str, dict[str, Any]] = {}
        self._interrupted = threading.Event()

    def _check_online(self) -> None:
        if not self.online:
            raise ComfyUIUnavailableError("ComfyUI hors ligne (mock)")

    def health(self) -> ComfyStatus:
        if not self.online:
            return ComfyStatus(online=False, provider=self.name, detail="ComfyUI factice hors ligne")
        return ComfyStatus(online=True, provider=self.name, detail="ComfyUI factice (mode mock)")

    def system_stats(self) -> dict[str, Any]:
        raise ComfyUIError("ComfyUI simulé : aucun serveur à interroger")

    def object_info(self) -> dict[str, Any]:
        raise ComfyUIError("ComfyUI simulé : aucun serveur à interroger")

    def node_info(self, class_type: str) -> dict[str, Any]:
        raise ComfyUIError("ComfyUI simulé : aucun serveur à interroger")

    def lora_names(self) -> list[str]:
        """Liste factice des LoRA (`MOCK_LORAS`, ou celle passée au constructeur)."""
        self._check_online()
        return list(self.loras)

    def upload_image(self, data: bytes, filename: str, *, subfolder: str = "mangaka") -> str:
        self._check_online()
        name = f"{subfolder}/{filename}" if subfolder else filename
        self.uploads[name] = data
        return name

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        self._check_online()
        check_prompt_nodes(workflow)
        node_errors: dict[str, Any] = {}
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") in ("LoadImage", "LoadImageMask"):
                image = node.get("inputs", {}).get("image")
                if image not in self.uploads:
                    node_errors[node_id] = {
                        "class_type": node["class_type"],
                        "errors": [{"message": "Invalid image file", "details": f"image: {image}"}],
                    }
        if node_errors:
            raise ComfyUIWorkflowError("workflow refusé par ComfyUI : Prompt outputs failed validation", node_errors)
        self._interrupted.clear()
        prompt_id = uuid.uuid4().hex
        self.prompts[prompt_id] = workflow
        filename = f"mock_{prompt_id}.png"
        seed, label = _first_int(workflow, "seed") or 0, _label(workflow)
        inpaint = self._inpaint_inputs(workflow)
        sketch_source = source_image_name(workflow) if inpaint is None else None
        control = control_image_name(workflow) if inpaint is None and sketch_source is None else None
        source = (
            source_upload(workflow, self.uploads)
            if inpaint is None and sketch_source is None and control is None
            else None
        )
        preprocess = any(
            isinstance(n, dict) and is_preprocessor(str(n.get("class_type") or "")) for n in workflow.values()
        )
        if inpaint is not None:
            data = render_mock_inpaint(*inpaint, seed)
        elif control is not None:
            image, strength = control
            caption = f"CONTROLNET · seed {seed}" + (f" · force {strength:g}" if strength is not None else "")
            data = render_mock_from_image(self.uploads[image], *requested_size(workflow), seed, None, caption=caption)
        elif source is not None and preprocess:
            inverts = sum(1 for n in workflow.values() if isinstance(n, dict) and n.get("class_type") == "ImageInvert")
            data = render_mock_control_map(source, *requested_size(workflow), inverted=inverts % 2 == 1)
        elif source is not None:
            data = resize_image(source, *requested_size(workflow))
        elif sketch_source is not None:
            width, height = requested_size(workflow)
            data = render_mock_from_image(
                self.uploads[sketch_source], width, height, seed, _first_float(workflow, "denoise")
            )
        elif label.startswith("croquis"):
            data = render_mock_sketch(*requested_size(workflow), seed, label)
        else:
            data = render_mock_image(*requested_size(workflow), seed, label)
        self._images[filename] = data
        output_nodes = [k for k, n in workflow.items() if isinstance(n, dict) and n.get("class_type") == "SaveImage"]
        outputs = {
            node: {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}
            for node in output_nodes or ["output"]
        }
        self._history[prompt_id] = {"outputs": outputs, "status": {"status_str": "success", "completed": True}}
        return prompt_id

    def _inpaint_inputs(self, workflow: dict[str, Any]) -> tuple[bytes, bytes] | None:
        """(image source, masque) envoyés, si le workflow est un inpainting."""
        masks = [n for n in workflow.values() if isinstance(n, dict) and n.get("class_type") == "LoadImageMask"]
        for node in workflow.values():
            if not isinstance(node, dict) or node.get("class_type") != "VAEEncode":
                continue
            link = node.get("inputs", {}).get("pixels")
            source = workflow.get(link[0]) if isinstance(link, list) and link else None
            if isinstance(source, dict) and source.get("class_type") == "LoadImage" and masks:
                return self.uploads[source["inputs"]["image"]], self.uploads[masks[0]["inputs"]["image"]]
        return None

    def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        return self._history.get(prompt_id)

    def wait_for_images(
        self,
        prompt_id: str,
        output_node: str,
        *,
        timeout_s: float = 600,
        poll_s: float = 1.0,
        on_progress: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> list[ImageRef]:
        entry = self._history.get(prompt_id)
        if entry is None:
            raise ComfyUIError(f"génération inconnue : {prompt_id}")
        steps = min(MAX_REPORTED_STEPS, max(1, _first_int(self.prompts[prompt_id], "steps") or DEFAULT_STEPS))
        delay = self.seconds_per_image / steps
        for step in range(1, steps + 1):
            if self._interrupted.is_set() or (should_stop is not None and should_stop()):
                raise ComfyUIInterruptedError("génération interrompue dans ComfyUI")
            if delay > 0:
                self._sleep(delay)
            if on_progress is not None:
                on_progress(step, steps)
        outputs = entry["outputs"].get(output_node) or next(iter(entry["outputs"].values()))
        return [ImageRef(**img) for img in outputs["images"]]

    def fetch_image(self, ref: ImageRef) -> bytes:
        try:
            return self._images[ref.filename]
        except KeyError:
            raise ComfyUIError(f"image {ref.filename} introuvable") from None

    def interrupt(self, prompt_id: str | None = None) -> None:
        self.interrupts.append(prompt_id)
        self._interrupted.set()
