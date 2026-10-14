from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mangaka_engine.config import REPO_ROOT, Settings
from mangaka_engine.main import create_app
from mangaka_engine.store import comfy_folders

PRESETS_DIR = REPO_ROOT / "presets"
# Packs de style obligatoires à la création d'une série (presets/style_*/).
STYLE = {"style_genre": "shonen", "style_rendering": "nb-trames", "style_tone": "neutre"}
# Phrase de style de STYLE, en tête de chaque prompt de case (style_lead d'image_prompt.yaml).
LEAD = "Black and white manga panel, hand-drawn inked line art with halftone screentone shading, shonen manga style. "
# Réponses enregistrées sur un vrai ComfyUI (GX10) : /object_info réduit, /system_stats, refus de /prompt.
COMFY_FIXTURES = Path(__file__).parent / "fixtures" / "comfyui"


def _real_comfy_series(root: Path) -> dict[str, set[str]]:
    """Dossiers de premier niveau de `<ComfyUI>/{input,output}/mangaka/` (vide si absent)."""
    out: dict[str, set[str]] = {}
    for area in comfy_folders.AREAS:
        base = root / area / comfy_folders.ROOT
        out[area] = {p.name for p in base.iterdir()} if base.is_dir() else set()
    return out


@pytest.fixture(scope="session", autouse=True)
def _isolate_real_comfyui(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Garde-fou : aucun test n'écrit dans le vrai `~/ComfyUI`.

    Le défaut `~/ComfyUI` (pris sans COMFYUI_DIR avec un client non mock) pointe vers un dossier temporaire
    absent pendant les tests, comme en CI ; et la session échoue si `{input,output}/mangaka/` du vrai ComfyUI
    a changé quand même (série créée ou supprimée)."""
    real = Path(comfy_folders.DEFAULT_DIR).expanduser()
    before = _real_comfy_series(real)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(comfy_folders, "DEFAULT_DIR", str(tmp_path_factory.mktemp("home") / "ComfyUI"))
        yield
    after = _real_comfy_series(real)
    changes = {
        area: {"créés": sorted(after[area] - before[area]), "supprimés": sorted(before[area] - after[area])}
        for area in comfy_folders.AREAS
        if after[area] != before[area]
    }
    if changes:
        pytest.fail(f"les tests ont modifié le vrai {real}/{{input,output}}/{comfy_folders.ROOT} : {changes}")


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    """Settings isolés : pas de .env, données dans un dossier temporaire, tout en mock."""

    def _make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "llm_provider": "mock",
            "vision_provider": "mock",
            "comfyui_provider": "mock",
            "deepseek_api_key": None,
            "deepseek_base_url": None,
            "deepseek_model": None,
            "mangaka_data_dir": tmp_path / "data",
            "mangaka_presets_dir": PRESETS_DIR,
            "mock_comfyui_seconds": 0,
            # Jamais le vrai ~/ComfyUI (ni un COMFYUI_DIR du shell) : les tests du rangement passent un dossier
            # temporaire.
            "comfyui_dir": None,
            # Packs de savoir-faire livrés : importés seulement par les tests qui les demandent (test_knowledge_packs).
            "knowledge_packs": False,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return _make


@pytest.fixture
def client(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as c:
        yield c


def png_bytes(size: tuple[int, int] = (64, 48), fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format=fmt)
    return buf.getvalue()


def force_stages(client: TestClient, chapter_id: int, *stages: str) -> None:
    """« Passer outre » les étapes de la garde d'étapes (toutes celles en attente sans `stages`) : pour les
    tests d'autres fonctions que la garde, qui lancent génération, lettrage ou export sans tout régler."""
    current = client.get(f"/chapters/{chapter_id}/stages").json()["stages"]
    for stage in current:
        if (not stages or stage["key"] in stages) and not stage["passed"]:
            r = client.post(f"/chapters/{chapter_id}/stages/{stage['key']}/override", json={"author": "tests"})
            assert r.status_code == 200, r.text
