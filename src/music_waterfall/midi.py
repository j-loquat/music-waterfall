from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido

from music_waterfall.errors import ValidationError
from music_waterfall.models import (
    AssignmentMode,
    Hand,
    MidiInspection,
    NoteEvent,
    OutputVariant,
    PerformanceTimeline,
    TempoChange,
    TrackAssignment,
    TrackInfo,
)


@dataclass(slots=True, frozen=True)
class RawNote:
    pitch: int
    start_tick: int
    end_tick: int
    velocity: int
    channel: int
    track: int


class TickConverter:
    """Convert absolute MIDI ticks against a global, piecewise tempo map."""

    def __init__(self, ticks_per_beat: int, changes: list[tuple[int, int]]):
        if ticks_per_beat <= 0:
            raise ValidationError("MIDI ticks per beat must be positive.")
        self.ticks_per_beat = ticks_per_beat
        collapsed: dict[int, int] = {0: 500_000}
        for tick, tempo in changes:
            collapsed[int(tick)] = int(tempo)
        self._ticks = sorted(collapsed)
        self._tempos = [collapsed[tick] for tick in self._ticks]
        self._seconds: list[float] = [0.0]
        for index in range(1, len(self._ticks)):
            tick_delta = self._ticks[index] - self._ticks[index - 1]
            seconds = self._seconds[-1] + mido.tick2second(
                tick_delta, ticks_per_beat, self._tempos[index - 1]
            )
            self._seconds.append(seconds)

    def to_seconds(self, tick: int) -> float:
        if tick < 0:
            raise ValidationError("An absolute MIDI tick cannot be negative.")
        index = bisect_right(self._ticks, tick) - 1
        return self._seconds[index] + mido.tick2second(
            tick - self._ticks[index], self.ticks_per_beat, self._tempos[index]
        )

    @property
    def changes(self) -> list[TempoChange]:
        return [
            TempoChange(tick=tick, seconds=seconds, tempo_us_per_beat=tempo)
            for tick, seconds, tempo in zip(self._ticks, self._seconds, self._tempos, strict=True)
        ]


@dataclass(slots=True)
class ParsedMidi:
    midi: mido.MidiFile
    converter: TickConverter
    raw_notes: list[RawNote]
    tracks: list[TrackInfo]
    last_tick: int


def _load_midi(path: Path) -> mido.MidiFile:
    if path.suffix.lower() not in {".mid", ".midi"}:
        raise ValidationError("Select a .mid or .midi file.")
    try:
        midi = mido.MidiFile(path)
    except (OSError, EOFError, ValueError) as exc:
        raise ValidationError(f"Cannot read MIDI file {path}: {exc}") from exc
    if midi.type not in {0, 1}:
        raise ValidationError(
            f"MIDI type {midi.type} is asynchronous and is not supported; use Type 0 or Type 1."
        )
    return midi


def parse_midi(path: Path) -> ParsedMidi:
    midi = _load_midi(path)
    tempo_events: list[tuple[int, int, int]] = []
    raw_notes: list[RawNote] = []
    track_infos: list[TrackInfo] = []
    last_tick = 0

    for track_index, track in enumerate(midi.tracks):
        absolute_tick = 0
        active: dict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
        pitches: list[int] = []
        channels: set[int] = set()
        programs: set[int] = set()
        name = f"Track {track_index}"
        for order, message in enumerate(track):
            absolute_tick += message.time
            last_tick = max(last_tick, absolute_tick)
            if message.type == "track_name" and message.name.strip():
                name = message.name.strip()
            if message.type == "set_tempo":
                tempo_events.append((absolute_tick, track_index * 1_000_000 + order, message.tempo))
            if hasattr(message, "channel"):
                channels.add(message.channel)
            if message.type == "program_change":
                programs.add(message.program)
            if message.type == "note_on" and message.velocity > 0:
                active[(message.channel, message.note)].append((absolute_tick, message.velocity))
                pitches.append(message.note)
            elif message.type == "note_off" or (
                message.type == "note_on" and message.velocity == 0
            ):
                queue = active[(message.channel, message.note)]
                if queue:
                    start_tick, velocity = queue.popleft()
                    if absolute_tick > start_tick:
                        raw_notes.append(
                            RawNote(
                                pitch=message.note,
                                start_tick=start_tick,
                                end_tick=absolute_tick,
                                velocity=velocity,
                                channel=message.channel,
                                track=track_index,
                            )
                        )
        for (channel, pitch), queue in active.items():
            while queue:
                start_tick, velocity = queue.popleft()
                if absolute_tick > start_tick:
                    raw_notes.append(
                        RawNote(
                            pitch=pitch,
                            start_tick=start_tick,
                            end_tick=absolute_tick,
                            velocity=velocity,
                            channel=channel,
                            track=track_index,
                        )
                    )
        track_infos.append(
            TrackInfo(
                index=track_index,
                name=name,
                channels=sorted(channels),
                programs=sorted(programs),
                note_count=len(pitches),
                lowest_note=min(pitches) if pitches else None,
                highest_note=max(pitches) if pitches else None,
                average_note=(sum(pitches) / len(pitches)) if pitches else None,
            )
        )

    tempo_events.sort(key=lambda item: (item[0], item[1]))
    converter = TickConverter(
        midi.ticks_per_beat,
        [(tick, tempo) for tick, _, tempo in tempo_events],
    )
    return ParsedMidi(
        midi=midi,
        converter=converter,
        raw_notes=raw_notes,
        tracks=track_infos,
        last_tick=last_tick,
    )


def inspect_midi(path: Path) -> MidiInspection:
    parsed = parse_midi(path)
    pitches = [note.pitch for note in parsed.raw_notes]
    return MidiInspection(
        midi_type=parsed.midi.type,
        ticks_per_beat=parsed.midi.ticks_per_beat,
        track_count=len(parsed.midi.tracks),
        duration_seconds=parsed.converter.to_seconds(parsed.last_tick),
        note_count=len(parsed.raw_notes),
        lowest_note=min(pitches) if pitches else None,
        highest_note=max(pitches) if pitches else None,
        tracks=parsed.tracks,
        tempo_changes=parsed.converter.changes,
    )


def suggested_assignments(inspection: MidiInspection) -> list[TrackAssignment]:
    musical = [track for track in inspection.tracks if track.note_count]
    if not musical:
        return []
    if len(musical) == 1:
        return [
            TrackAssignment(
                track_index=musical[0].index,
                mode=AssignmentMode.BOTH,
                split_pitch=60,
            )
        ]

    assignments: dict[int, TrackAssignment] = {}
    right_words = ("right", "upper", "treble", "soprano", "melody")
    left_words = ("left", "lower", "bass")
    for track in musical:
        lower_name = track.name.lower()
        if any(word in lower_name for word in right_words):
            assignments[track.index] = TrackAssignment(track.index, AssignmentMode.RIGHT)
        elif any(word in lower_name for word in left_words):
            assignments[track.index] = TrackAssignment(track.index, AssignmentMode.LEFT)

    remaining = [track for track in musical if track.index not in assignments]
    if remaining:
        by_pitch = sorted(
            remaining,
            key=lambda track: track.average_note if track.average_note is not None else -1,
        )
        if not any(item.mode is AssignmentMode.LEFT for item in assignments.values()):
            left = by_pitch.pop(0)
            assignments[left.index] = TrackAssignment(left.index, AssignmentMode.LEFT)
        if by_pitch and not any(item.mode is AssignmentMode.RIGHT for item in assignments.values()):
            right = by_pitch.pop(-1)
            assignments[right.index] = TrackAssignment(right.index, AssignmentMode.RIGHT)
        for track in by_pitch:
            assignments[track.index] = TrackAssignment(track.index, AssignmentMode.BOTH)

    for track in inspection.tracks:
        if not track.note_count:
            assignments[track.index] = TrackAssignment(track.index, AssignmentMode.IGNORE)
    return [assignments[index] for index in sorted(assignments)]


def build_timeline(path: Path, assignments: list[TrackAssignment]) -> PerformanceTimeline:
    parsed = parse_midi(path)
    by_track = {assignment.track_index: assignment for assignment in assignments}
    notes: list[NoteEvent] = []
    for raw in parsed.raw_notes:
        assignment = by_track.get(raw.track)
        if assignment is None or assignment.mode is AssignmentMode.IGNORE:
            continue
        if assignment.mode is AssignmentMode.LEFT:
            hand = Hand.LEFT
        elif assignment.mode is AssignmentMode.RIGHT:
            hand = Hand.RIGHT
        else:
            hand = Hand.RIGHT if raw.pitch >= assignment.split_pitch else Hand.LEFT
        start = parsed.converter.to_seconds(raw.start_tick)
        end = parsed.converter.to_seconds(raw.end_tick)
        if end <= start:
            continue
        notes.append(
            NoteEvent(
                pitch=raw.pitch,
                start=start,
                duration=end - start,
                velocity=raw.velocity,
                channel=raw.channel,
                track=raw.track,
                hand=hand,
            )
        )
    notes.sort(key=lambda note: (note.start, note.pitch, note.track, note.channel))
    duration = max((note.end for note in notes), default=0.0)
    timeline = PerformanceTimeline(
        notes=notes,
        duration_seconds=duration,
        tempo_changes=parsed.converter.changes,
        ticks_per_beat=parsed.midi.ticks_per_beat,
        source_format="midi",
    )
    timeline.validate()
    return timeline


def filtered_notes(timeline: PerformanceTimeline, variant: OutputVariant) -> list[NoteEvent]:
    if variant is OutputVariant.BOTH:
        return timeline.notes
    hand = Hand.LEFT if variant is OutputVariant.LEFT else Hand.RIGHT
    return [note for note in timeline.notes if note.hand is hand]


def write_performance_midi(
    timeline: PerformanceTimeline,
    destination: Path,
    speed: float,
    variant: OutputVariant,
) -> None:
    """Write selected canonical notes to a timing-stable piano MIDI for FluidSynth."""

    if speed <= 0:
        raise ValidationError("Playback speed must be positive.")
    ticks_per_beat = 960
    tempo = 500_000
    ticks_per_second = ticks_per_beat * 1_000_000 / tempo
    events: list[tuple[int, int, mido.Message]] = []
    for note in filtered_notes(timeline, variant):
        start_tick = round((note.start / speed) * ticks_per_second)
        end_tick = max(start_tick + 1, round((note.end / speed) * ticks_per_second))
        channel = 0 if note.hand is Hand.RIGHT else 1
        events.append(
            (
                start_tick,
                1,
                mido.Message(
                    "note_on",
                    note=note.pitch,
                    velocity=note.velocity,
                    channel=channel,
                    time=0,
                ),
            )
        )
        events.append(
            (
                end_tick,
                0,
                mido.Message("note_off", note=note.pitch, velocity=0, channel=channel, time=0),
            )
        )
    events.sort(key=lambda event: (event[0], event[1], event[2].note))

    midi = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name="Music Waterfall performance", time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(mido.Message("program_change", channel=0, program=0, time=0))
    track.append(mido.Message("program_change", channel=1, program=0, time=0))
    previous_tick = 0
    for absolute_tick, _, message in events:
        message.time = absolute_tick - previous_tick
        track.append(message)
        previous_tick = absolute_tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    destination.parent.mkdir(parents=True, exist_ok=True)
    midi.save(destination)


def midi_note_name(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[pitch % 12]}{pitch // 12 - 1}"
