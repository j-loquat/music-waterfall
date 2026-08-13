from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

from music_waterfall.errors import ExternalToolError, ValidationError
from music_waterfall.renderer import ProgressCallback
from music_waterfall.util import atomic_output_path, atomic_write_json


@dataclass(slots=True)
class MediaVerification:
    path: str
    valid: bool
    video_codec: str
    audio_codec: str
    width: int
    height: int
    frame_rate: float
    video_start: float
    audio_start: float
    video_duration: float
    audio_duration: float
    format_duration: float
    start_delta_seconds: float
    end_delta_seconds: float
    frame_tolerance_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def encode_mp4(
    ffmpeg: Path,
    frame_bytes: Iterable[bytes],
    audio_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    duration_seconds: float,
    log_path: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    with atomic_output_path(output_path) as temporary:
        command = [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            str(fps),
            "-i",
            "pipe:0",
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-t",
            f"{duration_seconds:.9f}",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise ExternalToolError(f"FFmpeg could not start: {exc}") from exc
        frame_count = 0
        try:
            assert process.stdin is not None
            for frame in frame_bytes:
                frame_count += 1
                expected_size = width * height * 3
                if len(frame) != expected_size:
                    raise ValidationError(
                        f"Renderer produced {len(frame)} bytes; expected {expected_size}."
                    )
                process.stdin.write(frame)
            process.stdin.close()
            stderr = (
                process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            )
            return_code = process.wait(timeout=1800)
        except BaseException:
            process.kill()
            process.wait()
            raise
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "COMMAND\n"
            + subprocess.list2cmdline(command)
            + f"\n\nFRAMES\n{frame_count}\n\nSTDERR\n"
            + stderr,
            encoding="utf-8",
        )
        if return_code != 0:
            detail = stderr.strip().splitlines()
            final_line = detail[-1] if detail else "no diagnostic output"
            raise ExternalToolError(
                f"FFmpeg failed with exit code {return_code}: {final_line}. See {log_path}."
            )
        if progress:
            progress(1.0, "Encoded H.264/AAC MP4")
    return output_path


def probe_media(ffprobe: Path, path: Path) -> dict[str, object]:
    command = [
        str(ffprobe),
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExternalToolError(f"FFprobe could not inspect {path}: {exc}") from exc
    if result.returncode != 0:
        raise ExternalToolError(
            f"FFprobe failed for {path}: {(result.stderr or result.stdout).strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ExternalToolError("FFprobe returned invalid JSON.") from exc


def verify_mp4(
    ffprobe: Path,
    path: Path,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
    report_path: Path | None = None,
) -> MediaVerification:
    data = probe_media(ffprobe, path)
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise ValidationError("MP4 must contain both a video stream and an audio stream.")
    frame_rate = _fraction_value(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    width, height = int(video["width"]), int(video["height"])
    video_start = float(video.get("start_time", 0.0))
    audio_start = float(audio.get("start_time", 0.0))
    format_duration = float(data.get("format", {}).get("duration", 0.0))
    video_duration = float(video.get("duration", format_duration))
    audio_duration = float(audio.get("duration", format_duration))
    frame_tolerance = 1 / (expected_fps or frame_rate)
    verification = MediaVerification(
        path=str(path.resolve()),
        valid=True,
        video_codec=str(video.get("codec_name")),
        audio_codec=str(audio.get("codec_name")),
        width=width,
        height=height,
        frame_rate=frame_rate,
        video_start=video_start,
        audio_start=audio_start,
        video_duration=video_duration,
        audio_duration=audio_duration,
        format_duration=format_duration,
        start_delta_seconds=abs(video_start - audio_start),
        end_delta_seconds=abs((video_start + video_duration) - (audio_start + audio_duration)),
        frame_tolerance_seconds=frame_tolerance,
    )
    problems: list[str] = []
    if verification.video_codec != "h264":
        problems.append(f"video codec is {verification.video_codec}, expected h264")
    if verification.audio_codec != "aac":
        problems.append(f"audio codec is {verification.audio_codec}, expected aac")
    if expected_width is not None and width != expected_width:
        problems.append(f"width is {width}, expected {expected_width}")
    if expected_height is not None and height != expected_height:
        problems.append(f"height is {height}, expected {expected_height}")
    if expected_fps is not None and not math.isclose(frame_rate, expected_fps, abs_tol=0.001):
        problems.append(f"frame rate is {frame_rate}, expected {expected_fps}")
    if verification.start_delta_seconds > frame_tolerance + 1e-6:
        problems.append(
            f"stream starts differ by {verification.start_delta_seconds:.6f}s, over one frame"
        )
    if verification.end_delta_seconds > frame_tolerance + 1e-6:
        problems.append(
            f"stream ends differ by {verification.end_delta_seconds:.6f}s, over one frame"
        )
    if problems:
        verification.valid = False
    if report_path:
        atomic_write_json(
            report_path,
            {
                "verification": verification.to_dict(),
                "problems": problems,
                "ffprobe": data,
            },
        )
    if problems:
        raise ValidationError("Media verification failed: " + "; ".join(problems))
    return verification


def _fraction_value(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0
