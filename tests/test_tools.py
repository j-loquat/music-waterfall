from __future__ import annotations

import os
from pathlib import Path

import pytest

from music_waterfall.config import AppConfig
from music_waterfall.errors import ToolUnavailableError
from music_waterfall.tools import ToolDiscovery


def test_saved_override_is_preferred(tmp_path: Path) -> None:
    fake = tmp_path / "custom-ffmpeg.exe"
    fake.write_bytes(b"binary")
    discovery = ToolDiscovery(AppConfig(tmp_path, {"ffmpeg": str(fake)}))
    assert discovery._find_path("ffmpeg") == fake.resolve()


def test_missing_tool_has_actionable_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    discovery = ToolDiscovery(AppConfig())
    monkeypatch.setattr(discovery, "_find_path", lambda _key: None)
    with pytest.raises(ToolUnavailableError, match="set-tool ffmpeg"):
        discovery.require("ffmpeg")


def test_musescore_version_does_not_invoke_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "MuseScore4.exe"
    executable.write_bytes(b"not executable")
    discovery = ToolDiscovery(AppConfig(tmp_path, {"musescore": str(executable)}))
    monkeypatch.setattr(discovery, "_musescore_registry_version", lambda: "4.7.4")
    monkeypatch.setattr(
        discovery,
        "_first_line",
        lambda _command: pytest.fail("MuseScore executable must not be invoked for version data"),
    )
    assert discovery.find("musescore").version == "4.7.4"


def test_fluidsynth_candidates_are_user_portable() -> None:
    candidates = "\n".join(ToolDiscovery.CANDIDATES["fluidsynth"])
    assert "david" not in candidates.lower()
    assert "%LOCALAPPDATA%" in candidates
    assert "%USERPROFILE%" in candidates


def test_fluidsynth_command_shim_does_not_use_a_private_executable_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shim = tmp_path / "fluidsynth.cmd"
    shim.write_text("@echo off\n", encoding="utf-8")
    discovery = ToolDiscovery(AppConfig(tmp_path, {"fluidsynth": str(shim)}))
    monkeypatch.setattr(
        discovery,
        "_windows_product_version",
        lambda _path: pytest.fail("A command shim must not resolve through a private path"),
    )
    assert discovery.find("fluidsynth").version == "installed (command shim)"


@pytest.mark.skipif(os.name != "nt", reason="Windows environment syntax")
def test_windows_environment_candidates_expand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", r"C:\PortableUser\AppData\Local")
    value = ToolDiscovery.CANDIDATES["fluidsynth"][1]
    assert os.path.expandvars(value).startswith(r"C:\PortableUser\AppData\Local")
