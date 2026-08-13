# Contributing to Music Waterfall

Thanks for helping improve Music Waterfall. The project currently targets Windows 11
and Python 3.12.

## Before making a change

1. Read `README.md`, `AGENTS.md`, and `THIRD_PARTY_NOTICES.md`.
2. Open an issue for a substantial feature or behavior change so the scope can be agreed.
3. Keep all score inputs, generated media, logs, and intermediate artifacts under the
   ignored `output/` directory.
4. Do not add copyrighted sheet music, MIDI files, SoundFonts, or third-party binaries.

## Development setup

```powershell
uv sync --locked
uv run music-waterfall doctor
```

Use the automated installer on a clean Windows 11 machine when the external tools are
not already present:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

## Required checks

Run these commands from the repository root:

```powershell
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv build
```

The normal test suite includes a short local media integration test when FFmpeg,
FFprobe, FluidSynth, and a SoundFont are available; otherwise that test reports a skip.
To select it explicitly, run:

```powershell
uv run pytest -m integration -q
```

Do not invoke `MuseScore4.exe --version`. Some Windows builds open a modal dialog for
that command. Music Waterfall reads installed-product metadata instead.

## Pull requests

- Keep changes focused and preserve unrelated work.
- Add or update tests for behavior changes.
- Update user documentation when commands, installation, or workflow behavior changes.
- Explain any third-party dependency or licensing change.
- Do not commit anything from `output/`.
