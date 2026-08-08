from __future__ import annotations

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent / "data"


@pytest.fixture
def rulebook_path() -> Path:
    return DATA_DIR / "rulebook_v1.0.md"
