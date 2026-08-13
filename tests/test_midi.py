from __future__ import annotations

from pathlib import Path

import mido
import pytest

from music_waterfall.midi import (
    TickConverter,
    build_timeline,
    filtered_notes,
    inspect_midi,
    parse_midi,
    suggested_assignments,
    write_performance_midi,
)
from music_waterfall.models import (
    AssignmentMode,
    Hand,
    NoteEvent,
    OutputVariant,
    PerformanceTimeline,
    TrackAssignment,
)


def test_tick_converter_handles_tempo_changes() -> None:
    converter = TickConverter(480, [(0, 500_000), (480, 1_000_000)])
    assert converter.to_seconds(0) == 0
    assert converter.to_seconds(480) == pytest.approx(0.5)
    assert converter.to_seconds(960) == pytest.approx(1.5)
    assert [change.seconds for change in converter.changes] == pytest.approx([0.0, 0.5])


def test_overlapping_notes_and_chords_are_paired_fifo(tmp_path: Path) -> None:
    path = tmp_path / "overlap.mid"
    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    track.append(mido.Message("note_on", note=60, velocity=90, channel=0, time=0))
    track.append(mido.Message("note_on", note=64, velocity=80, channel=0, time=0))
    track.append(mido.Message("note_on", note=60, velocity=70, channel=0, time=120))
    track.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=120))
    track.append(mido.Message("note_off", note=64, velocity=0, channel=0, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=120))
    midi.save(path)

    notes = sorted(parse_midi(path).raw_notes, key=lambda note: (note.pitch, note.start_tick))
    assert [(note.pitch, note.start_tick, note.end_tick) for note in notes] == [
        (60, 0, 240),
        (60, 120, 360),
        (64, 0, 240),
    ]


def test_fixture_inspection_and_hand_mapping(fixture_midi: Path) -> None:
    inspection = inspect_midi(fixture_midi)
    assert inspection.midi_type == 1
    assert inspection.track_count == 3
    assert inspection.note_count == 905
    assert inspection.duration_seconds == pytest.approx(130.4166145)
    assert (inspection.lowest_note, inspection.highest_note) == (33, 100)
    assignments = suggested_assignments(inspection)
    modes = {item.track_index: item.mode for item in assignments}
    assert modes == {
        0: AssignmentMode.IGNORE,
        1: AssignmentMode.RIGHT,
        2: AssignmentMode.LEFT,
    }
    timeline = build_timeline(fixture_midi, assignments)
    assert {note.hand for note in timeline.notes} == {Hand.LEFT, Hand.RIGHT}
    assert timeline.duration_seconds == pytest.approx(inspection.duration_seconds)


def test_pitch_split_and_manual_mapping(tmp_path: Path) -> None:
    path = tmp_path / "combined.mid"
    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend(
        [
            mido.Message("note_on", note=48, velocity=80, time=0),
            mido.Message("note_on", note=72, velocity=80, time=0),
            mido.Message("note_off", note=48, velocity=0, time=480),
            mido.Message("note_off", note=72, velocity=0, time=0),
        ]
    )
    midi.save(path)
    timeline = build_timeline(path, [TrackAssignment(0, AssignmentMode.BOTH, split_pitch=60)])
    assert {note.pitch: note.hand for note in timeline.notes} == {
        48: Hand.LEFT,
        72: Hand.RIGHT,
    }
    remapped = build_timeline(path, [TrackAssignment(0, AssignmentMode.LEFT)])
    assert all(note.hand is Hand.LEFT for note in remapped.notes)


def test_slow_performance_midi_preserves_pitch_and_scales_time(tmp_path: Path) -> None:
    timeline = PerformanceTimeline(
        notes=[NoteEvent(60, 0.25, 1.0, 90, 0, 0, Hand.RIGHT)],
        duration_seconds=1.25,
    )
    path = tmp_path / "slow.mid"
    write_performance_midi(timeline, path, speed=0.5, variant=OutputVariant.BOTH)
    parsed = build_timeline(path, [TrackAssignment(0, AssignmentMode.RIGHT)])
    assert len(parsed.notes) == 1
    assert parsed.notes[0].pitch == 60
    assert parsed.notes[0].start == pytest.approx(0.5, abs=0.001)
    assert parsed.notes[0].duration == pytest.approx(2.0, abs=0.001)


@pytest.mark.parametrize("tempo", [50, 70, 85, 100])
def test_practice_tempo_presets_preserve_pitch(tempo: int, tmp_path: Path) -> None:
    timeline = PerformanceTimeline(
        notes=[
            NoteEvent(48, 0.0, 1.0, 80, 0, 0, Hand.LEFT),
            NoteEvent(72, 0.0, 1.0, 80, 0, 1, Hand.RIGHT),
        ],
        duration_seconds=1.0,
    )
    assert [note.pitch for note in filtered_notes(timeline, OutputVariant.LEFT)] == [48]
    assert [note.pitch for note in filtered_notes(timeline, OutputVariant.RIGHT)] == [72]
    path = tmp_path / f"tempo-{tempo}.mid"
    write_performance_midi(timeline, path, tempo / 100, OutputVariant.LEFT)
    parsed = parse_midi(path)
    assert [note.pitch for note in parsed.raw_notes] == [48]
