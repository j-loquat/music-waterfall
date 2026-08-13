from __future__ import annotations

from pathlib import Path

import pytest

from music_waterfall.audio import analyze_wav, normalize_wav_duration, render_midi_to_wav
from music_waterfall.config import AppConfig
from music_waterfall.media import encode_mp4, verify_mp4
from music_waterfall.midi import write_performance_midi
from music_waterfall.models import (
    Hand,
    NoteEvent,
    OutputVariant,
    PerformanceTimeline,
    RenderSettings,
)
from music_waterfall.renderer import WaterfallRenderer
from music_waterfall.tools import ToolDiscovery


@pytest.mark.integration
def test_local_media_pipeline_has_h264_aac_and_frame_sync(tmp_path: Path) -> None:
    tools = ToolDiscovery(AppConfig())
    statuses = {key: tools.find(key) for key in ("fluidsynth", "soundfont", "ffmpeg", "ffprobe")}
    missing = [status.display_name for status in statuses.values() if not status.found]
    if missing:
        pytest.skip("Missing local media tools: " + ", ".join(missing))
    timeline = PerformanceTimeline(
        notes=[NoteEvent(60, 0.0, 0.5, 90, 0, 0, Hand.RIGHT)],
        duration_seconds=0.5,
    )
    settings = RenderSettings(width=320, height=240, fps=30, tail_seconds=0.5)
    renderer = WaterfallRenderer(timeline, settings)
    midi = tmp_path / "performance.mid"
    raw = tmp_path / "raw.wav"
    normalized = tmp_path / "normalized.wav"
    video = tmp_path / "result.mp4"
    write_performance_midi(timeline, midi, 1.0, OutputVariant.BOTH)
    render_midi_to_wav(
        Path(statuses["fluidsynth"].path or ""),
        Path(statuses["soundfont"].path or ""),
        midi,
        raw,
        tmp_path / "fluidsynth.log",
    )
    normalize_wav_duration(raw, normalized, renderer.duration_seconds, 0.0)
    assert analyze_wav(normalized).duration_seconds == renderer.duration_seconds
    encode_mp4(
        Path(statuses["ffmpeg"].path or ""),
        renderer.iter_rgb_bytes(),
        normalized,
        video,
        settings.width,
        settings.height,
        settings.fps,
        renderer.duration_seconds,
        tmp_path / "ffmpeg.log",
    )
    verification = verify_mp4(
        Path(statuses["ffprobe"].path or ""),
        video,
        settings.width,
        settings.height,
        settings.fps,
    )
    assert verification.valid
    assert verification.start_delta_seconds <= 1 / settings.fps
    assert verification.end_delta_seconds <= 1 / settings.fps
