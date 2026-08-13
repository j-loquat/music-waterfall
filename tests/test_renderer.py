from __future__ import annotations

import hashlib

import pytest

from music_waterfall.models import (
    Hand,
    KeyboardRange,
    NoteEvent,
    PerformanceTimeline,
    RenderSettings,
    TempoChange,
)
from music_waterfall.renderer import (
    LEFT_COLOR,
    PIANO_HIGH,
    PIANO_LOW,
    KeyboardGeometry,
    WaterfallRenderer,
    count_in_seconds,
    frame_plan,
)

GOLDEN_FRAME_SHA256 = "c66a38f736a3e655794004198dfeb75569be4f67c10c1ffb005735d3208d65e7"


def sample_timeline() -> PerformanceTimeline:
    return PerformanceTimeline(
        notes=[
            NoteEvent(48, 0.0, 0.75, 90, 0, 0, Hand.LEFT),
            NoteEvent(60, 0.5, 0.5, 100, 0, 1, Hand.RIGHT),
            NoteEvent(64, 1.0, 0.5, 100, 0, 1, Hand.RIGHT),
        ],
        duration_seconds=1.5,
        tempo_changes=[TempoChange(0, 0.0, 500_000)],
    )


def test_full_keyboard_geometry_has_all_88_keys_in_pitch_order() -> None:
    geometry = KeyboardGeometry.create(1040, PIANO_LOW, PIANO_HIGH)
    assert len(geometry.keys) == 88
    centers = [
        (geometry.keys[pitch].x0 + geometry.keys[pitch].x1) / 2
        for pitch in range(PIANO_LOW, PIANO_HIGH + 1)
    ]
    assert centers == sorted(centers)
    assert geometry.keys[22].is_black
    assert not geometry.keys[21].is_black
    assert geometry.keys[22].x1 - geometry.keys[22].x0 < geometry.keys[21].x1 - geometry.keys[21].x0


def test_video_renderer_uses_all_88_keys_even_for_legacy_auto_setting() -> None:
    settings = RenderSettings(
        width=1040,
        height=480,
        fps=30,
        keyboard_range=KeyboardRange.AUTO,
    )
    renderer = WaterfallRenderer(sample_timeline(), settings)
    assert renderer.geometry.low_pitch == PIANO_LOW
    assert renderer.geometry.high_pitch == PIANO_HIGH
    assert len(renderer.geometry.keys) == 88


def test_frame_plan_speed_and_count_in() -> None:
    settings = RenderSettings(width=320, height=240, fps=30, tempo_percent=50, count_in=True)
    timeline = sample_timeline()
    assert count_in_seconds(timeline, settings) == pytest.approx(4.0)
    frames, duration, count_in = frame_plan(timeline, settings)
    assert frames == 240
    assert duration == pytest.approx(8.0)
    assert count_in == pytest.approx(4.0)


def test_active_pitch_lands_on_its_key() -> None:
    settings = RenderSettings(width=320, height=240, fps=30)
    renderer = WaterfallRenderer(sample_timeline(), settings)
    frame = renderer.render_frame(10)
    key = renderer.geometry.rect_for_pitch(48)
    assert key is not None
    x = (key.x0 + key.x1) // 2
    y = renderer.strike_y + 5
    assert tuple(frame[y, x]) == LEFT_COLOR


def test_representative_frame_matches_deterministic_golden_hash() -> None:
    settings = RenderSettings(
        width=320,
        height=240,
        fps=30,
        note_names=True,
        lookahead_seconds=2.0,
    )
    frame = WaterfallRenderer(sample_timeline(), settings).render_frame(18)
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    assert digest == GOLDEN_FRAME_SHA256
