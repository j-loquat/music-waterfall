from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixture_midi() -> Path:
    return Path(__file__).parent / "fixtures" / "midi" / "fur-elise-mutopia.mid"


@pytest.fixture(scope="session")
def fixture_pdf() -> Path:
    return Path(__file__).parent / "fixtures" / "pdf" / "fur-elise-mutopia-letter.pdf"
