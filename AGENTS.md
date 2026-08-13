# Instructions for AI coding and installation agents

## Objective and boundaries

Music Waterfall is a local Windows 11 application. Keep score processing offline. Do not
add cloud services, accounts, telemetry, uploads, or remote score-processing APIs.

Preserve user inputs. Put projects, copied inputs, OMR artifacts, corrected MusicXML,
logs, WAV files, previews, and MP4 files under the ignored `output/` directory. Never
commit anything from `output/`.

Only the matched public-domain Für Elise pair under `tests/fixtures/` may be committed as
media. Do not add another PDF, MIDI, MusicXML, SoundFont, WAV, or MP4 without explicit
authorization plus documented provenance, license, and checksum.

## Clean Windows 11 installation

1. Read `README.md` and `THIRD_PARTY_NOTICES.md` completely.
2. Run this command from the repository root in PowerShell:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
   ```

3. Confirm that every row from `uv run music-waterfall doctor` is `OK`.
4. Confirm that `uv run ruff check src tests`, `uv run pytest -q`, and `uv build` pass.
5. Launch the GUI with `uv run music-waterfall-gui`.
6. Report the detected tool paths and versions, skipped checks, and any remaining manual
   action. Never print credentials or authentication tokens.

The installer may use the network to install software. Application runtime and score
processing must remain local and offline.

## Critical implementation rules

- Use uv and the checked-in `uv.lock`; do not replace it with pip or Poetry instructions.
- Support Python 3.12 only until the declared version range and test matrix are changed.
- Never invoke `MuseScore4.exe --version`; it opens a modal dialog on some Windows builds.
  Inspect Windows installed-product or file metadata instead.
- Keep the PDF path review-gated. Audiveris output is unreviewed until a person corrects
  and explicitly approves exported MusicXML and conversion succeeds.
- Keep preview and final videos fixed to the complete 88-key keyboard.
- Base media duration on the canonical timeline plus explicit count-in and tail. Measure
  FluidSynth output, then trim or pad it deterministically. Never use raw WAV duration as
  video duration.
- Preserve original inputs and SHA-256 checks. Save corrections as new artifacts.
- Keep changes focused; run the relevant tests and review the complete diff before any
  commit or push.
- Do not commit, push, publish a release, or change repository settings unless the user
  explicitly authorizes that external action.
