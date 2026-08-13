from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from pypdf import PdfReader

from music_waterfall.errors import ReviewRequiredError, ValidationError
from music_waterfall.models import (
    PerformanceTimeline,
    ProjectManifest,
    ReviewState,
    SourceKind,
    SourceMetadata,
    TrackAssignment,
    project_path,
)
from music_waterfall.util import atomic_write_json, sha256_file, slugify, utc_now


class ProjectStore:
    REQUIRED_DIRECTORIES = ("source", "intermediate", "logs", "audio", "previews", "renders")

    def __init__(self, output_root: Path):
        self.output_root = output_root.resolve()

    def create(
        self,
        source_path: Path,
        kind: SourceKind,
        name: str | None = None,
    ) -> tuple[Path, ProjectManifest]:
        source_path = source_path.expanduser().resolve(strict=True)
        expected_suffixes = {".mid", ".midi"} if kind is SourceKind.MIDI else {".pdf"}
        if source_path.suffix.lower() not in expected_suffixes:
            raise ValidationError(
                f"Expected {kind.value.upper()} input, got {source_path.suffix or 'no extension'}."
            )

        self.output_root.mkdir(parents=True, exist_ok=True)
        base = slugify(name or source_path.stem)
        project_dir = self.output_root / base
        suffix = 2
        while project_dir.exists():
            project_dir = self.output_root / f"{base}-{suffix}"
            suffix += 1
        project_dir.mkdir()
        for directory in self.REQUIRED_DIRECTORIES:
            (project_dir / directory).mkdir()

        copied = project_dir / "source" / f"original{source_path.suffix.lower()}"
        shutil.copy2(source_path, copied)
        digest = sha256_file(source_path)
        if sha256_file(copied) != digest:
            raise ValidationError("The copied project source does not match the original checksum.")

        page_count: int | None = None
        if kind is SourceKind.PDF:
            try:
                reader = PdfReader(source_path)
                if reader.is_encrypted:
                    raise ValidationError("Encrypted PDFs are not supported.")
                page_count = len(reader.pages)
                if page_count == 0:
                    raise ValidationError("The PDF contains no pages.")
            except ValidationError:
                raise
            except Exception as exc:
                raise ValidationError(f"Cannot read PDF: {exc}") from exc

        source = SourceMetadata(
            kind=kind,
            original_path=str(source_path),
            copied_path=copied.relative_to(project_dir).as_posix(),
            file_name=source_path.name,
            sha256=digest,
            size_bytes=source_path.stat().st_size,
            page_count=page_count,
        )
        manifest = ProjectManifest(
            project_id=str(uuid.uuid4()),
            name=name or source_path.stem,
            source=source,
            review_state=(
                ReviewState.NOT_REQUIRED if kind is SourceKind.MIDI else ReviewState.UNREVIEWED
            ),
            assignments=[],
            settings=self._default_settings(),
        )
        self.save(project_dir, manifest)
        return project_dir, manifest

    @staticmethod
    def _default_settings():
        from music_waterfall.models import RenderSettings

        return RenderSettings.preview()

    def load(self, manifest_path: Path) -> tuple[Path, ProjectManifest]:
        path = manifest_path.expanduser().resolve(strict=True)
        if path.is_dir():
            path = project_path(path)
        if path.name != "project.json":
            raise ValidationError("Select a Music Waterfall project.json file.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Cannot read project manifest: {exc}") from exc
        manifest = ProjectManifest.from_dict(data)
        project_dir = path.parent
        copied = project_dir / manifest.source.copied_path
        if not copied.is_file():
            raise ValidationError(f"Project source copy is missing: {copied}")
        if sha256_file(copied) != manifest.source.sha256:
            raise ValidationError("Project source copy checksum does not match project.json.")
        return project_dir, manifest

    def save(self, project_dir: Path, manifest: ProjectManifest) -> None:
        manifest.updated_at = utc_now()
        atomic_write_json(project_path(project_dir), manifest.to_dict())

    def save_timeline(
        self, project_dir: Path, manifest: ProjectManifest, timeline: PerformanceTimeline
    ) -> Path:
        timeline.validate()
        path = project_dir / "intermediate" / "timeline.json"
        atomic_write_json(path, timeline.to_dict())
        manifest.timeline_file = path.relative_to(project_dir).as_posix()
        self.save(project_dir, manifest)
        return path

    @staticmethod
    def load_timeline(project_dir: Path, manifest: ProjectManifest) -> PerformanceTimeline:
        if not manifest.timeline_file:
            raise ValidationError("This project has no canonical performance timeline.")
        path = project_dir / manifest.timeline_file
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Cannot read timeline: {exc}") from exc
        return PerformanceTimeline.from_dict(data)

    @staticmethod
    def assert_renderable(manifest: ProjectManifest) -> None:
        if (
            manifest.source.kind is SourceKind.PDF
            and manifest.review_state is not ReviewState.REVIEWED
        ):
            raise ReviewRequiredError(
                "Rendering is locked. Open the recognized MusicXML in MuseScore Studio, "
                "compare it with the source PDF, correct it, then explicitly mark Score reviewed."
            )
        if not manifest.timeline_file:
            raise ValidationError("No canonical timeline is available for rendering.")

    def update_assignments(
        self,
        project_dir: Path,
        manifest: ProjectManifest,
        assignments: list[TrackAssignment],
    ) -> None:
        for assignment in assignments:
            assignment.validate()
        manifest.assignments = assignments
        self.save(project_dir, manifest)
