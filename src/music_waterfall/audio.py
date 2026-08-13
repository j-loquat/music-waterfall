from __future__ import annotations

import json
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from music_waterfall.errors import ExternalToolError, ValidationError
from music_waterfall.util import atomic_output_path, atomic_write_json


@dataclass(slots=True)
class AudioAnalysis:
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    duration_seconds: float
    first_signal_seconds: float | None
    last_signal_seconds: float | None
    signal_threshold_dbfs: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def render_midi_to_wav(
    fluidsynth: Path,
    soundfont: Path,
    midi_path: Path,
    wav_path: Path,
    log_path: Path,
    sample_rate: int = 48_000,
) -> Path:
    command = [
        str(fluidsynth),
        "-ni",
        "-R",
        "0",
        "-C",
        "0",
        "-r",
        str(sample_rate),
        "-O",
        "s16",
    ]
    with atomic_output_path(wav_path) as temporary:
        command.extend(["-F", str(temporary), str(soundfont), str(midi_path)])
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExternalToolError(f"FluidSynth could not render audio: {exc}") from exc
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "COMMAND\n"
            + subprocess.list2cmdline(command)
            + "\n\nSTDOUT\n"
            + result.stdout
            + "\nSTDERR\n"
            + result.stderr,
            encoding="utf-8",
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            final_line = detail[-1] if detail else "no diagnostic output"
            raise ExternalToolError(
                f"FluidSynth failed with exit code {result.returncode}: {final_line}. "
                f"See {log_path}."
            )
    return wav_path


def analyze_wav(path: Path, threshold_dbfs: float = -55.0) -> AudioAnalysis:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)
    if sample_width not in {1, 2, 3, 4}:
        raise ValidationError(f"Unsupported WAV sample width: {sample_width} bytes.")
    peaks = _frame_peaks(raw, sample_width, channels)
    threshold = 10 ** (threshold_dbfs / 20)
    indices = np.flatnonzero(peaks >= threshold)
    first = float(indices[0] / sample_rate) if indices.size else None
    last = float((indices[-1] + 1) / sample_rate) if indices.size else None
    return AudioAnalysis(
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frame_count=frame_count,
        duration_seconds=frame_count / sample_rate,
        first_signal_seconds=first,
        last_signal_seconds=last,
        signal_threshold_dbfs=threshold_dbfs,
    )


def _frame_peaks(raw: bytes, sample_width: int, channels: int) -> np.ndarray:
    if sample_width == 1:
        samples = np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128
        maximum = 128.0
    elif sample_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float64)
        maximum = 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float64)
        maximum = 2147483648.0
    else:
        byte_array = np.frombuffer(raw, dtype=np.uint8)
        usable = (byte_array.size // 3) * 3
        triples = byte_array[:usable].reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        values = np.where(values & 0x800000, values - 0x1000000, values)
        samples = values.astype(np.float64)
        maximum = 8388608.0
    if not samples.size:
        return np.empty(0, dtype=np.float64)
    usable_samples = (samples.size // channels) * channels
    frames = samples[:usable_samples].reshape(-1, channels)
    return np.max(np.abs(frames), axis=1) / maximum


def normalize_wav_duration(
    raw_path: Path,
    normalized_path: Path,
    target_duration_seconds: float,
    prefix_silence_seconds: float,
) -> Path:
    """Prepend count-in silence, then trim/pad PCM to an exact sample count."""

    if target_duration_seconds <= 0 or prefix_silence_seconds < 0:
        raise ValidationError("Audio duration and count-in must be non-negative.")
    with wave.open(str(raw_path), "rb") as source:
        params = source.getparams()
        raw_frames = source.readframes(source.getnframes())
    bytes_per_frame = params.nchannels * params.sampwidth
    target_frames = round(target_duration_seconds * params.framerate)
    prefix_frames = round(prefix_silence_seconds * params.framerate)
    content_frames = max(0, target_frames - prefix_frames)
    content = raw_frames[: content_frames * bytes_per_frame]
    missing_content_frames = content_frames - len(content) // bytes_per_frame
    payload = (
        bytes(prefix_frames * bytes_per_frame)
        + content
        + bytes(max(0, missing_content_frames) * bytes_per_frame)
    )
    if len(payload) < target_frames * bytes_per_frame:
        payload += bytes(target_frames * bytes_per_frame - len(payload))
    payload = payload[: target_frames * bytes_per_frame]

    with (
        atomic_output_path(normalized_path) as temporary,
        wave.open(str(temporary), "wb") as output,
    ):
        output.setparams(params)
        output.writeframes(payload)
    return normalized_path


def save_audio_analysis(
    path: Path,
    raw: AudioAnalysis,
    normalized: AudioAnalysis,
    canonical_duration_seconds: float,
    count_in_seconds: float,
    target_duration_seconds: float,
) -> None:
    atomic_write_json(
        path,
        {
            "canonical_duration_seconds": canonical_duration_seconds,
            "count_in_seconds": count_in_seconds,
            "target_duration_seconds": target_duration_seconds,
            "raw": raw.to_dict(),
            "normalized": normalized.to_dict(),
            "policy": (
                "The canonical performance timeline plus explicit count-in/tail controls "
                "duration. The raw FluidSynth duration is measured but never controls video length."
            ),
        },
    )


def read_analysis(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
