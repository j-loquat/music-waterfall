from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from music_waterfall.config import AppConfig


@dataclass(slots=True)
class ToolStatus:
    key: str
    display_name: str
    found: bool
    path: str | None
    version: str | None
    detail: str
    remediation: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ToolDiscovery:
    CANDIDATES = {
        "ffmpeg": ("ffmpeg.exe", "ffmpeg"),
        "ffprobe": ("ffprobe.exe", "ffprobe"),
        "fluidsynth": (
            "fluidsynth.exe",
            r"%LOCALAPPDATA%\MusicWaterfall\tools\fluidsynth\bin\fluidsynth.exe",
            r"%USERPROFILE%\.local\opt\fluidsynth-2.4.7\bin\fluidsynth.exe",
            r"%USERPROFILE%\.local\bin\fluidsynth.cmd",
            "fluidsynth.cmd",
        ),
        "audiveris": (
            "Audiveris.exe",
            r"C:\Program Files\Audiveris\Audiveris.exe",
            r"C:\Program Files (x86)\Audiveris\Audiveris.exe",
        ),
        "musescore": (
            "MuseScore4.exe",
            r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
            r"C:\Program Files (x86)\MuseScore 4\bin\MuseScore4.exe",
        ),
        "soundfont": (
            r"C:\Program Files\MuseScore 4\sound\MS Basic.sf3",
            r"C:\Program Files (x86)\MuseScore 4\sound\MS Basic.sf3",
        ),
    }

    DISPLAY_NAMES = {
        "ffmpeg": "FFmpeg",
        "ffprobe": "FFprobe",
        "fluidsynth": "FluidSynth",
        "audiveris": "Audiveris",
        "musescore": "MuseScore Studio",
        "soundfont": "Piano SoundFont",
    }

    REMEDIATION = {
        "ffmpeg": ("Install FFmpeg on PATH or run: music-waterfall set-tool ffmpeg <ffmpeg.exe>"),
        "ffprobe": (
            "Install FFprobe on PATH or run: music-waterfall set-tool ffprobe <ffprobe.exe>"
        ),
        "fluidsynth": (
            "Install FluidSynth or run: music-waterfall set-tool fluidsynth <fluidsynth.exe>"
        ),
        "audiveris": (
            "Install Audiveris 5.x or run: music-waterfall set-tool audiveris <Audiveris.exe>"
        ),
        "musescore": (
            "Install MuseScore Studio 4 or run: music-waterfall set-tool musescore <MuseScore4.exe>"
        ),
        "soundfont": ("Run: music-waterfall set-tool soundfont <local-piano.sf2-or-sf3>"),
    }

    def __init__(self, config: AppConfig):
        self.config = config

    def find(self, key: str) -> ToolStatus:
        if key not in self.CANDIDATES:
            raise KeyError(key)
        path = self._find_path(key)
        if path is None:
            return ToolStatus(
                key=key,
                display_name=self.DISPLAY_NAMES[key],
                found=False,
                path=None,
                version=None,
                detail="Not found",
                remediation=self.REMEDIATION[key],
            )
        version = self._version(key, path)
        detail = f"Found at {path}"
        if key == "soundfont":
            detail = f"Found {path.stat().st_size / (1024 * 1024):.1f} MiB SoundFont"
        return ToolStatus(
            key=key,
            display_name=self.DISPLAY_NAMES[key],
            found=True,
            path=str(path),
            version=version,
            detail=detail,
        )

    def all(self) -> list[ToolStatus]:
        return [self.find(key) for key in self.CANDIDATES]

    def require(self, key: str) -> Path:
        status = self.find(key)
        if not status.found or not status.path:
            from music_waterfall.errors import ToolUnavailableError

            raise ToolUnavailableError(
                f"{status.display_name} is required but was not found. {status.remediation}"
            )
        return Path(status.path)

    def _find_path(self, key: str) -> Path | None:
        override = self.config.tool_overrides.get(key)
        if override:
            candidate = Path(os.path.expandvars(override)).expanduser()
            if candidate.is_file():
                return candidate.resolve()
        for value in self.CANDIDATES[key]:
            expanded = Path(os.path.expandvars(value)).expanduser()
            if expanded.is_absolute() and expanded.is_file():
                return expanded.resolve()
            found = shutil.which(value)
            if found:
                path = Path(found)
                if path.is_file():
                    return path.resolve()
        return None

    def _version(self, key: str, path: Path) -> str | None:
        if key in {"ffmpeg", "ffprobe"}:
            return self._first_line([str(path), "-version"])
        if key == "audiveris":
            text = self._command_text([str(path), "-version"])
            match = re.search(r"Version:\s*([0-9.]+)", text or "")
            return match.group(1) if match else self._first_line([str(path), "-version"])
        if key == "fluidsynth":
            if path.suffix.lower() == ".cmd":
                return "installed (command shim)"
            product = self._windows_product_version(path)
            return product or "installed (metadata unavailable)"
        if key == "musescore":
            # MuseScore4.exe --version opens a modal dialog on some Windows builds.
            return self._musescore_registry_version() or "installed (metadata unavailable)"
        return None

    @staticmethod
    def _command_text(command: list[str]) -> str | None:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = (result.stdout or result.stderr).strip()
        return text or None

    @staticmethod
    def _first_line(command: list[str]) -> str | None:
        text = ToolDiscovery._command_text(command)
        return text.splitlines()[0].strip() if text else None

    @staticmethod
    def _windows_product_version(path: Path) -> str | None:
        if os.name != "nt":
            return None
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-Item -LiteralPath '{str(path).replace("'", "''")}').VersionInfo.ProductVersion",
        ]
        return ToolDiscovery._first_line(command)

    @staticmethod
    def _musescore_registry_version() -> str | None:
        if os.name != "nt":
            return None
        try:
            import winreg

            roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
            subkeys = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            )
            for root in roots:
                for subkey in subkeys:
                    try:
                        with winreg.OpenKey(root, subkey) as parent:
                            for index in range(winreg.QueryInfoKey(parent)[0]):
                                name = winreg.EnumKey(parent, index)
                                with winreg.OpenKey(parent, name) as item:
                                    try:
                                        display, _ = winreg.QueryValueEx(item, "DisplayName")
                                    except OSError:
                                        continue
                                    if "MuseScore Studio 4" in str(display):
                                        version, _ = winreg.QueryValueEx(item, "DisplayVersion")
                                        return str(version)
                    except OSError:
                        continue
        except (ImportError, OSError):
            return None
        return None
