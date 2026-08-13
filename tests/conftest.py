from __future__ import annotations

from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Create the ignored parent before pytest initializes its configured base temp."""

    base_temp = config.getoption("basetemp")
    if base_temp:
        Path(base_temp).expanduser().parent.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def fixture_midi() -> Path:
    return Path(__file__).parent / "fixtures" / "midi" / "fur-elise-mutopia.mid"


@pytest.fixture(scope="session")
def fixture_pdf() -> Path:
    return Path(__file__).parent / "fixtures" / "pdf" / "fur-elise-mutopia-letter.pdf"
