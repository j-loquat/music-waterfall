from __future__ import annotations

import json
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path

import pytest
from music21 import converter, note, stream
from music21.musicxml.xmlToM21 import MusicXMLWarning

from music_waterfall.config import AppConfig
from music_waterfall.errors import ReviewRequiredError, ValidationError
from music_waterfall.models import ReviewState, SourceKind
from music_waterfall.omr import OmrService
from music_waterfall.project import ProjectStore
from music_waterfall.tools import ToolDiscovery


def test_audiveris_artifacts_remain_unreviewed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_pdf: Path
) -> None:
    fake_audiveris = tmp_path / "Audiveris.exe"
    fake_audiveris.write_bytes(b"placeholder")
    config = AppConfig(tmp_path / "output", {"audiveris": str(fake_audiveris)})
    store = ProjectStore(config.output_root)
    project_dir, manifest = store.create(fixture_pdf, SourceKind.PDF)
    service = OmrService(ToolDiscovery(config), store)

    def fake_run(command, **_kwargs):
        if "-output" not in command:
            return subprocess.CompletedProcess(command, 0, stdout="Audiveris 5.11.0", stderr="")
        output = Path(command[command.index("-output") + 1])
        with zipfile.ZipFile(output / "original.omr", "w") as archive:
            for page in range(1, 4):
                archive.writestr(f"sheet#{page}/sheet#{page}.xml", "<sheet />")
        with zipfile.ZipFile(output / "original.mxl", "w") as archive:
            archive.writestr(
                "META-INF/container.xml",
                "<container><rootfiles><rootfile full-path='score.xml'/></rootfiles></container>",
            )
            archive.writestr("score.xml", "<score-partwise />")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("music_waterfall.omr.subprocess.run", fake_run)
    omr, xml = service.run_audiveris(project_dir, manifest)
    assert omr.is_file() and xml.is_file()
    assert manifest.review_state is ReviewState.UNREVIEWED
    assert manifest.timeline_file is None
    assert not manifest.is_renderable
    assert (project_dir / manifest.artifacts["omr_validation"]).is_file()


def test_review_confirmation_is_explicit(tmp_path: Path, fixture_pdf: Path) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_pdf, SourceKind.PDF)
    manifest.musicxml_file = "intermediate/fake.mxl"
    (project_dir / manifest.musicxml_file).write_bytes(b"not parsed because confirmation is false")
    service = OmrService(ToolDiscovery(AppConfig(tmp_path / "output")), store)
    with pytest.raises(ReviewRequiredError, match="not confirmed"):
        service.mark_reviewed(project_dir, manifest, explicit_confirmation=False)


def test_corrected_musicxml_import_preserves_original_and_relocks(
    tmp_path: Path, fixture_pdf: Path
) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_pdf, SourceKind.PDF)
    audiveris_dir = project_dir / "intermediate" / "audiveris"
    audiveris_dir.mkdir()
    original = audiveris_dir / "original.mxl"
    original.write_bytes(b"preserved Audiveris output")
    manifest.omr_file = "intermediate/audiveris/original.omr"
    manifest.musicxml_file = original.relative_to(project_dir).as_posix()
    manifest.review_state = ReviewState.REVIEWED
    manifest.timeline_file = "intermediate/timeline.json"
    manifest.midi_inspection_file = "intermediate/old-inspection.json"
    manifest.artifacts["reviewed_midi"] = "intermediate/reviewed-score.mid"
    store.save(project_dir, manifest)

    exported = tmp_path / "corrected.mxl"
    with zipfile.ZipFile(exported, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            "<container><rootfiles><rootfile full-path='score.xml'/></rootfiles></container>",
        )
        archive.writestr("score.xml", "<score-partwise version='4.0' />")

    service = OmrService(ToolDiscovery(AppConfig(tmp_path / "output")), store)
    imported = service.import_corrected_musicxml(project_dir, manifest, exported)

    assert imported.is_file()
    assert imported.read_bytes() == exported.read_bytes()
    assert original.read_bytes() == b"preserved Audiveris output"
    assert manifest.artifacts["audiveris_musicxml_original"] == (
        "intermediate/audiveris/original.mxl"
    )
    assert manifest.musicxml_file == imported.relative_to(project_dir).as_posix()
    assert manifest.review_state is ReviewState.UNREVIEWED
    assert manifest.timeline_file is None
    assert manifest.midi_inspection_file is None
    assert "reviewed_midi" not in manifest.artifacts
    assert not manifest.is_renderable


def test_corrected_musicxml_import_rejects_musescore_native_file(
    tmp_path: Path, fixture_pdf: Path
) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_pdf, SourceKind.PDF)
    native_score = tmp_path / "working-copy.mscz"
    native_score.write_bytes(b"not MusicXML")
    service = OmrService(ToolDiscovery(AppConfig(tmp_path / "output")), store)

    with pytest.raises(ValidationError, match="File > Export"):
        service.import_corrected_musicxml(project_dir, manifest, native_score)


def test_failed_review_conversion_stays_locked_and_writes_diagnostic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_pdf: Path
) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_pdf, SourceKind.PDF)
    musicxml = project_dir / "intermediate" / "broken.musicxml"
    musicxml.write_text("<score-partwise />", encoding="utf-8")
    manifest.musicxml_file = musicxml.relative_to(project_dir).as_posix()
    manifest.review_state = ReviewState.REVIEWED
    manifest.timeline_file = "intermediate/stale-timeline.json"
    manifest.artifacts["reviewed_midi"] = "intermediate/stale.mid"
    store.save(project_dir, manifest)
    service = OmrService(ToolDiscovery(AppConfig(tmp_path / "output")), store)

    def reject_repeats(_path):
        raise ValueError("bad repeats")

    monkeypatch.setattr(converter, "parse", reject_repeats)

    with pytest.raises(ValidationError, match="linearize confusing repeats"):
        service.mark_reviewed(project_dir, manifest, explicit_confirmation=True)

    assert manifest.review_state is ReviewState.UNREVIEWED
    assert manifest.timeline_file is None
    assert "reviewed_midi" not in manifest.artifacts
    diagnostic = project_dir / manifest.artifacts["review_conversion_error"]
    assert diagnostic.is_file()
    assert "bad repeats" in diagnostic.read_text(encoding="utf-8")


def test_confirmed_review_hands_off_to_shared_timeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_pdf: Path
) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_pdf, SourceKind.PDF)
    score = stream.Score()
    part = stream.Part()
    part.append(note.Note("C4", quarterLength=1))
    part.append(note.Note("E4", quarterLength=1))
    score.append(part)
    musicxml = project_dir / "intermediate" / "reviewed.musicxml"
    score.write("musicxml", fp=musicxml)
    manifest.musicxml_file = musicxml.relative_to(project_dir).as_posix()
    store.save(project_dir, manifest)
    service = OmrService(ToolDiscovery(AppConfig(tmp_path / "output")), store)
    real_parse = converter.parse

    def parse_with_pedal_warning(path):
        warnings.warn(
            "Could not import pedal: Error in getting PedalMark",
            MusicXMLWarning,
            stacklevel=2,
        )
        return real_parse(path)

    monkeypatch.setattr(converter, "parse", parse_with_pedal_warning)
    with warnings.catch_warnings(record=True) as leaked:
        warnings.simplefilter("always")
        reviewed_midi = service.mark_reviewed(project_dir, manifest, explicit_confirmation=True)
    assert reviewed_midi.is_file()
    assert manifest.review_state is ReviewState.REVIEWED
    assert manifest.timeline_file
    assert store.load_timeline(project_dir, manifest).notes
    store.assert_renderable(manifest)
    assert not [warning for warning in leaked if warning.category is MusicXMLWarning]
    warning_report = json.loads(
        (project_dir / manifest.artifacts["musicxml_import_warnings"]).read_text(encoding="utf-8")
    )
    assert warning_report["warning_count"] == 1
    assert "PedalMark" in warning_report["warnings"][0]["message"]


def test_importing_gui_does_not_load_music21() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import music_waterfall.gui; print('music21' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
