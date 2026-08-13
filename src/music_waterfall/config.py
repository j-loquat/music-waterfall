from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_config_path

from music_waterfall.errors import ValidationError
from music_waterfall.util import atomic_write_json


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def config_file() -> Path:
    return user_config_path("MusicWaterfall", appauthor=False) / "config.json"


@dataclass(slots=True)
class AppConfig:
    output_root: Path = field(default_factory=lambda: repository_root() / "output")
    tool_overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> AppConfig:
        path = config_file()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Cannot read configuration {path}: {exc}") from exc
        return cls(
            output_root=repository_root() / "output",
            tool_overrides={str(key): str(value) for key, value in data.get("tools", {}).items()},
        )

    def save(self) -> Path:
        path = config_file()
        atomic_write_json(path, {"tools": dict(sorted(self.tool_overrides.items()))})
        return path
