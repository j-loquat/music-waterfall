from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from music_waterfall.midi import filtered_notes, midi_note_name
from music_waterfall.models import (
    Hand,
    KeyboardRange,
    NoteEvent,
    PerformanceTimeline,
    RenderSettings,
)

PIANO_LOW = 21
PIANO_HIGH = 108
BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}
LEFT_COLOR = (50, 154, 255)
RIGHT_COLOR = (255, 143, 56)
BACKGROUND_TOP = (8, 13, 27)
BACKGROUND_BOTTOM = (19, 30, 49)


class ProgressCallback(Protocol):
    def __call__(self, fraction: float, message: str) -> None: ...


@dataclass(slots=True, frozen=True)
class KeyRect:
    pitch: int
    x0: int
    x1: int
    is_black: bool


@dataclass(slots=True)
class KeyboardGeometry:
    width: int
    low_pitch: int
    high_pitch: int
    keys: dict[int, KeyRect]

    @classmethod
    def create(
        cls,
        width: int,
        low_pitch: int = PIANO_LOW,
        high_pitch: int = PIANO_HIGH,
    ) -> KeyboardGeometry:
        low = max(PIANO_LOW, min(low_pitch, PIANO_HIGH))
        high = min(PIANO_HIGH, max(high_pitch, PIANO_LOW))
        if low > high:
            low, high = high, low
        while low > PIANO_LOW and low % 12 in BLACK_PITCH_CLASSES:
            low -= 1
        while high < PIANO_HIGH and high % 12 in BLACK_PITCH_CLASSES:
            high += 1
        whites = [pitch for pitch in range(low, high + 1) if not is_black_key(pitch)]
        if not whites:
            whites = [max(PIANO_LOW, low - 1)]
        white_width = width / len(whites)
        keys: dict[int, KeyRect] = {}
        white_indices: dict[int, int] = {}
        for index, pitch in enumerate(whites):
            x0 = round(index * white_width)
            x1 = round((index + 1) * white_width)
            keys[pitch] = KeyRect(pitch, x0, x1, False)
            white_indices[pitch] = index
        black_width = max(2, round(white_width * 0.62))
        for pitch in range(low, high + 1):
            if not is_black_key(pitch):
                continue
            previous_white = pitch - 1
            while previous_white >= low and is_black_key(previous_white):
                previous_white -= 1
            if previous_white not in white_indices:
                continue
            boundary = round((white_indices[previous_white] + 1) * white_width)
            keys[pitch] = KeyRect(
                pitch,
                max(0, boundary - black_width // 2),
                min(width, boundary + math.ceil(black_width / 2)),
                True,
            )
        return cls(width=width, low_pitch=low, high_pitch=high, keys=keys)

    @classmethod
    def for_timeline(
        cls,
        width: int,
        timeline: PerformanceTimeline,
        range_mode: KeyboardRange,
    ) -> KeyboardGeometry:
        # The complete 88-key context is a product invariant for every video.
        # Keep the parameters for API and project-schema compatibility.
        _ = timeline, range_mode
        return cls.create(width, PIANO_LOW, PIANO_HIGH)

    def rect_for_pitch(self, pitch: int) -> KeyRect | None:
        return self.keys.get(pitch)


def is_black_key(pitch: int) -> bool:
    return pitch % 12 in BLACK_PITCH_CLASSES


def count_in_seconds(timeline: PerformanceTimeline, settings: RenderSettings) -> float:
    if not settings.count_in or settings.count_in_beats <= 0:
        return 0.0
    beat_seconds = (
        timeline.tempo_changes[0].tempo_us_per_beat / 1_000_000 if timeline.tempo_changes else 0.5
    )
    return settings.count_in_beats * beat_seconds / settings.speed


def frame_plan(
    timeline: PerformanceTimeline,
    settings: RenderSettings,
    musical_limit_seconds: float | None = None,
) -> tuple[int, float, float]:
    settings.validate()
    musical_duration = timeline.duration_seconds
    if musical_limit_seconds is not None:
        musical_duration = min(musical_duration, max(0.0, musical_limit_seconds))
    count_in = count_in_seconds(timeline, settings)
    requested = count_in + musical_duration / settings.speed + settings.tail_seconds
    frame_count = max(1, math.ceil(requested * settings.fps))
    return frame_count, frame_count / settings.fps, count_in


class WaterfallRenderer:
    def __init__(
        self,
        timeline: PerformanceTimeline,
        settings: RenderSettings,
        musical_limit_seconds: float | None = None,
    ):
        self.timeline = timeline
        self.settings = settings
        self.frame_count, self.duration_seconds, self.count_in = frame_plan(
            timeline, settings, musical_limit_seconds
        )
        self.musical_limit_seconds = musical_limit_seconds
        visible_timeline = timeline
        if musical_limit_seconds is not None:
            visible_timeline = slice_timeline(timeline, musical_limit_seconds)
        self.notes = filtered_notes(visible_timeline, settings.variant)
        self.geometry = KeyboardGeometry.for_timeline(
            settings.width, visible_timeline, settings.keyboard_range
        )
        self.keyboard_height = max(90, round(settings.height * 0.22))
        self.strike_y = settings.height - self.keyboard_height
        self._background = self._make_background()
        self._font_small = ImageFont.load_default(size=max(10, settings.height // 72))
        self._font_medium = ImageFont.load_default(size=max(14, settings.height // 45))
        self._font_large = ImageFont.load_default(size=max(24, settings.height // 24))

    def _make_background(self) -> Image.Image:
        height = self.settings.height
        width = self.settings.width
        top = np.asarray(BACKGROUND_TOP, dtype=np.float32)
        bottom = np.asarray(BACKGROUND_BOTTOM, dtype=np.float32)
        blend = np.linspace(0, 1, height, dtype=np.float32)[:, None]
        rows = (top[None, :] * (1 - blend) + bottom[None, :] * blend).astype(np.uint8)
        pixels = np.broadcast_to(rows[:, None, :], (height, width, 3)).copy()
        return Image.fromarray(pixels, mode="RGB")

    def render_frame(self, frame_index: int) -> np.ndarray:
        if not 0 <= frame_index < self.frame_count:
            raise IndexError(frame_index)
        video_time = frame_index / self.settings.fps
        musical_time = (video_time - self.count_in) * self.settings.speed
        image = self._background.copy()
        draw = ImageDraw.Draw(image)
        self._draw_guides(draw)
        active = self._draw_notes(draw, musical_time)
        self._draw_keyboard(draw, active)
        self._draw_overlay(draw, video_time, musical_time)
        return np.asarray(image, dtype=np.uint8)

    def iter_rgb_bytes(self, progress: ProgressCallback | None = None):
        for index in range(self.frame_count):
            if progress and (index == 0 or index % max(1, self.settings.fps) == 0):
                progress(
                    index / self.frame_count,
                    f"Rendering frame {index + 1}/{self.frame_count}",
                )
            yield self.render_frame(index).tobytes()
        if progress:
            progress(1.0, f"Rendered {self.frame_count} frames")

    def save_frame(self, path: Path, frame_index: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self.render_frame(frame_index), mode="RGB").save(path)

    def _draw_guides(self, draw: ImageDraw.ImageDraw) -> None:
        draw.line(
            (0, self.strike_y, self.settings.width, self.strike_y),
            fill=(142, 223, 255),
            width=3,
        )
        for fraction in (0.25, 0.5, 0.75):
            y = round(self.strike_y * fraction)
            draw.line((0, y, self.settings.width, y), fill=(30, 45, 66), width=1)

    def _draw_notes(self, draw: ImageDraw.ImageDraw, musical_time: float) -> dict[int, Hand]:
        active: dict[int, Hand] = {}
        lookahead = self.settings.lookahead_seconds * self.settings.speed
        for note in self.notes:
            key = self.geometry.rect_for_pitch(note.pitch)
            if key is None:
                continue
            start = note.start
            end = note.end
            if start <= musical_time < end:
                active[note.pitch] = note.hand
            y_bottom = self.strike_y - ((start - musical_time) / lookahead) * self.strike_y
            y_top = self.strike_y - ((end - musical_time) / lookahead) * self.strike_y
            if y_bottom < 0 or y_top > self.strike_y:
                continue
            top = max(0, round(y_top))
            bottom = min(self.strike_y, round(y_bottom))
            if bottom <= top:
                continue
            margin = max(1, round((key.x1 - key.x0) * 0.08))
            x0, x1 = key.x0 + margin, key.x1 - margin
            color = LEFT_COLOR if note.hand is Hand.LEFT else RIGHT_COLOR
            draw.rounded_rectangle(
                (x0, top, x1, bottom),
                radius=max(2, min(8, (x1 - x0) // 4)),
                fill=color,
                outline=(229, 247, 255),
                width=max(1, self.settings.width // 960),
            )
            if self.settings.note_names and bottom - top >= 14 and x1 - x0 >= 20:
                label = midi_note_name(note.pitch)
                draw.text(
                    ((x0 + x1) / 2, max(top + 2, bottom - 14)),
                    label,
                    font=self._font_small,
                    fill=(9, 16, 27),
                    anchor="mm",
                )
        return active

    def _draw_keyboard(self, draw: ImageDraw.ImageDraw, active: dict[int, Hand]) -> None:
        bottom = self.settings.height - 1
        black_height = round(self.keyboard_height * 0.62)
        for key in self.geometry.keys.values():
            if key.is_black:
                continue
            hand = active.get(key.pitch)
            fill = (
                LEFT_COLOR
                if hand is Hand.LEFT
                else RIGHT_COLOR
                if hand is Hand.RIGHT
                else (238, 241, 242)
            )
            draw.rectangle(
                (key.x0, self.strike_y, key.x1, bottom),
                fill=fill,
                outline=(30, 35, 43),
                width=1,
            )
            if self.settings.note_names and key.x1 - key.x0 >= 18:
                draw.text(
                    ((key.x0 + key.x1) / 2, bottom - 8),
                    midi_note_name(key.pitch),
                    font=self._font_small,
                    fill=(20, 25, 33),
                    anchor="ms",
                )
        for key in self.geometry.keys.values():
            if not key.is_black:
                continue
            hand = active.get(key.pitch)
            fill = (
                LEFT_COLOR
                if hand is Hand.LEFT
                else RIGHT_COLOR
                if hand is Hand.RIGHT
                else (23, 27, 34)
            )
            draw.rounded_rectangle(
                (key.x0, self.strike_y, key.x1, self.strike_y + black_height),
                radius=max(1, (key.x1 - key.x0) // 6),
                fill=fill,
                outline=(4, 7, 11),
                width=1,
            )

    def _draw_overlay(
        self, draw: ImageDraw.ImageDraw, video_time: float, musical_time: float
    ) -> None:
        draw.rectangle((0, 0, self.settings.width, 42), fill=(5, 9, 17))
        draw.ellipse((14, 13, 27, 26), fill=LEFT_COLOR)
        draw.text((34, 20), "LEFT", font=self._font_small, fill=(225, 238, 248), anchor="lm")
        draw.ellipse((94, 13, 107, 26), fill=RIGHT_COLOR)
        draw.text((114, 20), "RIGHT", font=self._font_small, fill=(225, 238, 248), anchor="lm")
        tempo = f"{self.settings.tempo_percent}%"
        draw.text(
            (self.settings.width - 18, 20),
            tempo,
            font=self._font_medium,
            fill=(225, 238, 248),
            anchor="rm",
        )
        if video_time < self.count_in:
            remaining = self.count_in - video_time
            beat_length = self.count_in / max(1, self.settings.count_in_beats)
            beat = max(1, math.ceil(remaining / beat_length))
            draw.text(
                (self.settings.width / 2, self.settings.height * 0.40),
                str(beat),
                font=self._font_large,
                fill=(238, 244, 250),
                anchor="mm",
            )
        progress = min(1.0, max(0.0, musical_time / max(self.timeline.duration_seconds, 1e-9)))
        draw.rectangle((0, 40, self.settings.width, 43), fill=(28, 40, 54))
        draw.rectangle((0, 40, round(progress * self.settings.width), 43), fill=(104, 218, 184))


def slice_timeline(timeline: PerformanceTimeline, end_seconds: float) -> PerformanceTimeline:
    end_seconds = max(0.0, min(end_seconds, timeline.duration_seconds))
    notes: list[NoteEvent] = []
    for note in timeline.notes:
        if note.start >= end_seconds:
            continue
        duration = min(note.end, end_seconds) - note.start
        if duration > 0:
            notes.append(
                NoteEvent(
                    pitch=note.pitch,
                    start=note.start,
                    duration=duration,
                    velocity=note.velocity,
                    channel=note.channel,
                    track=note.track,
                    hand=note.hand,
                )
            )
    return PerformanceTimeline(
        notes=notes,
        duration_seconds=end_seconds,
        tempo_changes=[
            change for change in timeline.tempo_changes if change.seconds <= end_seconds
        ],
        ticks_per_beat=timeline.ticks_per_beat,
        source_format=timeline.source_format,
    )
