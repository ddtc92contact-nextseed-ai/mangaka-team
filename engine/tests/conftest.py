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

PRESETS_DIR = REPO_ROOT / "presets"


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
