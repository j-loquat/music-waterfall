from __future__ import annotations

import wave
from pathlib import Path

from music_waterfall.audio import analyze_wav, normalize_wav_duration


def write_pcm(path: Path, frames: int, sample_rate: int = 1000) -> None:
    samples = bytearray(frames * 2)
    for index in range(100, min(400, frames)):
        value = 5000
        samples[index * 2 : index * 2 + 2] = value.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples)


def test_signal_measurement_and_exact_trim_pad(tmp_path: Path) -> None:
    raw = tmp_path / "raw.wav"
    normalized = tmp_path / "normalized.wav"
    write_pcm(raw, 500)
    analysis = analyze_wav(raw)
    assert analysis.first_signal_seconds == 0.1
    assert analysis.last_signal_seconds == 0.4
    normalize_wav_duration(raw, normalized, target_duration_seconds=1.0, prefix_silence_seconds=0.2)
    normalized_analysis = analyze_wav(normalized)
    assert normalized_analysis.duration_seconds == 1.0
    assert normalized_analysis.first_signal_seconds == 0.3
    assert normalized_analysis.last_signal_seconds == 0.6
