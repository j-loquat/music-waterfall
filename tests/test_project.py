from __future__ import annotations

from pathlib import Path

import pytest

from music_waterfall.errors import ReviewRequiredError, ValidationError
from music_waterfall.models import SourceKind
from music_waterfall.project import ProjectStore


def test_project_persistence_preserves_source_and_resumes(
    tmp_path: Path, fixture_midi: Path
) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_midi, SourceKind.MIDI, "Persistence Test")
    assert (project_dir / manifest.source.copied_path).read_bytes() == fixture_midi.read_bytes()
    resumed_dir, resumed = store.load(project_dir / "project.json")
    assert resumed_dir == project_dir
    assert resumed.project_id == manifest.project_id
    expected_hash = "1C12C21C7BBF4CF163896732672648A69D497636059837ABD153C71ABE50215A"
    assert resumed.source.sha256 == expected_hash


def test_project_detects_tampered_source_copy(tmp_path: Path, fixture_midi: Path) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_midi, SourceKind.MIDI)
    (project_dir / manifest.source.copied_path).write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="checksum"):
        store.load(project_dir / "project.json")


def test_pdf_is_valid_and_render_locked(tmp_path: Path, fixture_pdf: Path) -> None:
    store = ProjectStore(tmp_path / "output")
    project_dir, manifest = store.create(fixture_pdf, SourceKind.PDF)
    assert manifest.source.page_count == 3
    assert manifest.review_state.value == "unreviewed"
    with pytest.raises(ReviewRequiredError, match="Rendering is locked"):
        store.assert_renderable(manifest)
    assert (project_dir / manifest.source.copied_path).is_file()
