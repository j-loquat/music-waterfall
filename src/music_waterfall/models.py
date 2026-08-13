from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from music_waterfall.errors import ValidationError
from music_waterfall.util import utc_now

PROJECT_SCHEMA_VERSION = 1
TIMELINE_SCHEMA_VERSION = 1


class SourceKind(StrEnum):
    MIDI = "midi"
    PDF = "pdf"


class ReviewState(StrEnum):
    NOT_REQUIRED = "not_required"
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"


class Hand(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class AssignmentMode(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    IGNORE = "ignore"


class OutputVariant(StrEnum):
    BOTH = "both"
    LEFT = "left"
    RIGHT = "right"


class KeyboardRange(StrEnum):
    FULL = "full"
    # Kept only so version-1 projects saved before the fixed 88-key policy still load.
    AUTO = "auto"


@dataclass(slots=True, frozen=True)
class TempoChange:
    tick: int
    seconds: float
    tempo_us_per_beat: int

    @property
    def bpm(self) -> float:
        return 60_000_000 / self.tempo_us_per_beat


@dataclass(slots=True, frozen=True)
class NoteEvent:
    pitch: int
    start: float
    duration: float
    velocity: int
    channel: int
    track: int
    hand: Hand

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(slots=True)
class PerformanceTimeline:
    notes: list[NoteEvent]
    duration_seconds: float
    tempo_changes: list[TempoChange] = field(default_factory=list)
    ticks_per_beat: int | None = None
    source_format: str = "midi"
    schema_version: int = TIMELINE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != TIMELINE_SCHEMA_VERSION:
            raise ValidationError(
                f"Unsupported timeline schema {self.schema_version}; expected "
                f"{TIMELINE_SCHEMA_VERSION}."
            )
        if self.duration_seconds < 0:
            raise ValidationError("Timeline duration cannot be negative.")
        for note in self.notes:
            if not 0 <= note.pitch <= 127:
                raise ValidationError(f"Invalid MIDI pitch: {note.pitch}")
            if note.start < 0 or note.duration <= 0:
                raise ValidationError(f"Invalid note timing at pitch {note.pitch}.")
            if note.end > self.duration_seconds + 1e-6:
                raise ValidationError("Timeline duration ends before one or more notes.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_format": self.source_format,
            "ticks_per_beat": self.ticks_per_beat,
            "duration_seconds": self.duration_seconds,
            "tempo_changes": [asdict(change) for change in self.tempo_changes],
            "notes": [
                {
                    **asdict(note),
                    "hand": note.hand.value,
                }
                for note in self.notes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceTimeline:
        timeline = cls(
            schema_version=int(data.get("schema_version", 0)),
            source_format=str(data.get("source_format", "unknown")),
            ticks_per_beat=data.get("ticks_per_beat"),
            duration_seconds=float(data["duration_seconds"]),
            tempo_changes=[TempoChange(**change) for change in data.get("tempo_changes", [])],
            notes=[
                NoteEvent(
                    pitch=int(note["pitch"]),
                    start=float(note["start"]),
                    duration=float(note["duration"]),
                    velocity=int(note["velocity"]),
                    channel=int(note["channel"]),
                    track=int(note["track"]),
                    hand=Hand(note["hand"]),
                )
                for note in data.get("notes", [])
            ],
        )
        timeline.validate()
        return timeline


@dataclass(slots=True, frozen=True)
class TrackInfo:
    index: int
    name: str
    channels: list[int]
    programs: list[int]
    note_count: int
    lowest_note: int | None
    highest_note: int | None
    average_note: float | None


@dataclass(slots=True)
class MidiInspection:
    midi_type: int
    ticks_per_beat: int
    track_count: int
    duration_seconds: float
    note_count: int
    lowest_note: int | None
    highest_note: int | None
    tracks: list[TrackInfo]
    tempo_changes: list[TempoChange]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "tempo_changes": [
                {**asdict(change), "bpm": round(change.bpm, 6)} for change in self.tempo_changes
            ],
        }


@dataclass(slots=True)
class TrackAssignment:
    track_index: int
    mode: AssignmentMode
    split_pitch: int = 60

    def validate(self) -> None:
        if not 0 <= self.split_pitch <= 127:
            raise ValidationError("A hand split pitch must be between 0 and 127.")


@dataclass(slots=True)
class RenderSettings:
    variant: OutputVariant = OutputVariant.BOTH
    tempo_percent: int = 100
    lookahead_seconds: float = 3.0
    note_names: bool = False
    count_in: bool = False
    count_in_beats: int = 4
    tail_seconds: float = 1.0
    keyboard_range: KeyboardRange = KeyboardRange.FULL
    width: int = 1280
    height: int = 720
    fps: int = 30

    def validate(self) -> None:
        if self.tempo_percent not in {50, 70, 85, 100}:
            raise ValidationError("Tempo must be one of 50, 70, 85, or 100 percent.")
        if not 0.5 <= self.lookahead_seconds <= 10:
            raise ValidationError("Look-ahead must be between 0.5 and 10 seconds.")
        if not 0 <= self.count_in_beats <= 16:
            raise ValidationError("Count-in beats must be between 0 and 16.")
        if not 0 <= self.tail_seconds <= 10:
            raise ValidationError("Tail must be between 0 and 10 seconds.")
        if self.width < 320 or self.height < 240 or self.fps not in {24, 25, 30, 50, 60}:
            raise ValidationError("Unsupported frame size or frame rate.")

    @property
    def speed(self) -> float:
        return self.tempo_percent / 100.0

    @classmethod
    def preview(cls) -> RenderSettings:
        return cls(width=1280, height=720, fps=30)

    @classmethod
    def final(cls) -> RenderSettings:
        return cls(width=1920, height=1080, fps=60)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "variant": self.variant.value,
            "keyboard_range": self.keyboard_range.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RenderSettings:
        settings = cls(
            variant=OutputVariant(data.get("variant", OutputVariant.BOTH.value)),
            tempo_percent=int(data.get("tempo_percent", 100)),
            lookahead_seconds=float(data.get("lookahead_seconds", 3.0)),
            note_names=bool(data.get("note_names", False)),
            count_in=bool(data.get("count_in", False)),
            count_in_beats=int(data.get("count_in_beats", 4)),
            tail_seconds=float(data.get("tail_seconds", 1.0)),
            # Videos always show the complete piano. Ignore legacy "auto" project values.
            keyboard_range=KeyboardRange.FULL,
            width=int(data.get("width", 1280)),
            height=int(data.get("height", 720)),
            fps=int(data.get("fps", 30)),
        )
        settings.validate()
        return settings


@dataclass(slots=True)
class SourceMetadata:
    kind: SourceKind
    original_path: str
    copied_path: str
    file_name: str
    sha256: str
    size_bytes: int
    page_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "kind": self.kind.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceMetadata:
        return cls(
            kind=SourceKind(data["kind"]),
            original_path=data["original_path"],
            copied_path=data["copied_path"],
            file_name=data["file_name"],
            sha256=data["sha256"],
            size_bytes=int(data["size_bytes"]),
            page_count=data.get("page_count"),
        )


@dataclass(slots=True)
class ProjectManifest:
    project_id: str
    name: str
    source: SourceMetadata
    review_state: ReviewState
    assignments: list[TrackAssignment]
    settings: RenderSettings
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    timeline_file: str | None = None
    midi_inspection_file: str | None = None
    omr_file: str | None = None
    musicxml_file: str | None = None
    reviewed_at: str | None = None
    reviewed_musicxml_sha256: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    schema_version: int = PROJECT_SCHEMA_VERSION

    @property
    def is_renderable(self) -> bool:
        return bool(
            self.timeline_file
            and (self.source.kind is SourceKind.MIDI or self.review_state is ReviewState.REVIEWED)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source.to_dict(),
            "review_state": self.review_state.value,
            "assignments": [
                {
                    "track_index": item.track_index,
                    "mode": item.mode.value,
                    "split_pitch": item.split_pitch,
                }
                for item in self.assignments
            ],
            "settings": self.settings.to_dict(),
            "timeline_file": self.timeline_file,
            "midi_inspection_file": self.midi_inspection_file,
            "omr_file": self.omr_file,
            "musicxml_file": self.musicxml_file,
            "reviewed_at": self.reviewed_at,
            "reviewed_musicxml_sha256": self.reviewed_musicxml_sha256,
            "artifacts": dict(self.artifacts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectManifest:
        schema = int(data.get("schema_version", 0))
        if schema != PROJECT_SCHEMA_VERSION:
            raise ValidationError(
                f"Unsupported project schema {schema}; expected {PROJECT_SCHEMA_VERSION}."
            )
        assignments = [
            TrackAssignment(
                track_index=int(item["track_index"]),
                mode=AssignmentMode(item["mode"]),
                split_pitch=int(item.get("split_pitch", 60)),
            )
            for item in data.get("assignments", [])
        ]
        for assignment in assignments:
            assignment.validate()
        return cls(
            schema_version=schema,
            project_id=data["project_id"],
            name=data["name"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            source=SourceMetadata.from_dict(data["source"]),
            review_state=ReviewState(data["review_state"]),
            assignments=assignments,
            settings=RenderSettings.from_dict(data["settings"]),
            timeline_file=data.get("timeline_file"),
            midi_inspection_file=data.get("midi_inspection_file"),
            omr_file=data.get("omr_file"),
            musicxml_file=data.get("musicxml_file"),
            reviewed_at=data.get("reviewed_at"),
            reviewed_musicxml_sha256=data.get("reviewed_musicxml_sha256"),
            artifacts=dict(data.get("artifacts", {})),
        )


def project_path(project_dir: Path) -> Path:
    return project_dir / "project.json"
