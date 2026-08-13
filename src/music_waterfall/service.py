from __future__ import annotations

import traceback
from pathlib import Path

from music_waterfall.audio import (
    analyze_wav,
    normalize_wav_duration,
    render_midi_to_wav,
    save_audio_analysis,
)
from music_waterfall.config import AppConfig
from music_waterfall.media import MediaVerification, encode_mp4, verify_mp4
from music_waterfall.midi import (
    build_timeline,
    inspect_midi,
    suggested_assignments,
    write_performance_midi,
)
from music_waterfall.models import (
    KeyboardRange,
    ProjectManifest,
    RenderSettings,
    ReviewState,
    SourceKind,
    TrackAssignment,
)
from music_waterfall.omr import OmrService
from music_waterfall.project import ProjectStore
from music_waterfall.renderer import ProgressCallback, WaterfallRenderer, slice_timeline
from music_waterfall.tools import ToolDiscovery
from music_waterfall.util import atomic_write_json, slugify, utc_now


class MusicWaterfallService:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or AppConfig.load()
        self.store = ProjectStore(self.config.output_root)
        self.tools = ToolDiscovery(self.config)
        self.omr = OmrService(self.tools, self.store)

    def create_midi_project(
        self, source: Path, name: str | None = None
    ) -> tuple[Path, ProjectManifest]:
        project_dir, manifest = self.store.create(source, SourceKind.MIDI, name)
        copied = project_dir / manifest.source.copied_path
        inspection = inspect_midi(copied)
        manifest.assignments = suggested_assignments(inspection)
        inspection_path = project_dir / "intermediate" / "midi-inspection.json"
        atomic_write_json(inspection_path, inspection.to_dict())
        manifest.midi_inspection_file = inspection_path.relative_to(project_dir).as_posix()
        timeline = build_timeline(copied, manifest.assignments)
        self.store.save_timeline(project_dir, manifest, timeline)
        return project_dir, manifest

    def create_pdf_project(
        self, source: Path, name: str | None = None
    ) -> tuple[Path, ProjectManifest]:
        return self.store.create(source, SourceKind.PDF, name)

    def load_project(self, path: Path) -> tuple[Path, ProjectManifest]:
        return self.store.load(path)

    def save_settings(
        self, project_dir: Path, manifest: ProjectManifest, settings: RenderSettings
    ) -> None:
        settings.validate()
        manifest.settings = settings
        self.store.save(project_dir, manifest)

    def save_assignments(
        self,
        project_dir: Path,
        manifest: ProjectManifest,
        assignments: list[TrackAssignment],
    ) -> None:
        self.store.update_assignments(project_dir, manifest, assignments)
        if manifest.source.kind is SourceKind.MIDI:
            source = project_dir / manifest.source.copied_path
        else:
            reviewed = manifest.artifacts.get("reviewed_midi")
            if manifest.review_state is not ReviewState.REVIEWED or not reviewed:
                return
            source = project_dir / reviewed
        timeline = build_timeline(source, assignments)
        self.store.save_timeline(project_dir, manifest, timeline)

    def render_preview(
        self,
        project_path: Path,
        seconds: float = 12.0,
        progress: ProgressCallback | None = None,
    ) -> tuple[Path, MediaVerification]:
        return self.render(
            project_path,
            preset="preview",
            musical_limit_seconds=seconds,
            progress=progress,
        )

    def render(
        self,
        project_path: Path,
        preset: str = "final",
        musical_limit_seconds: float | None = None,
        progress: ProgressCallback | None = None,
    ) -> tuple[Path, MediaVerification]:
        project_dir, manifest = self.store.load(project_path)
        self.store.assert_renderable(manifest)
        timeline = self.store.load_timeline(project_dir, manifest)
        settings = RenderSettings.from_dict(manifest.settings.to_dict())
        settings.keyboard_range = KeyboardRange.FULL
        if preset == "preview":
            settings.width, settings.height, settings.fps = 1280, 720, 30
        elif preset == "final":
            settings.width, settings.height, settings.fps = 1920, 1080, 60
        elif preset != "saved":
            raise ValueError("preset must be preview, final, or saved")
        settings.validate()
        selected_timeline = (
            slice_timeline(timeline, musical_limit_seconds)
            if musical_limit_seconds is not None
            else timeline
        )
        renderer = WaterfallRenderer(selected_timeline, settings)
        label = (
            f"{slugify(manifest.name)}-{settings.variant.value}-"
            f"{settings.tempo_percent}pct-{settings.width}x{settings.height}-{settings.fps}fps"
        )
        target_dir = project_dir / ("previews" if musical_limit_seconds is not None else "renders")
        output_path = target_dir / f"{label}.mp4"
        performance_midi = project_dir / "intermediate" / f"{label}.mid"
        raw_wav = project_dir / "audio" / f"{label}-raw.wav"
        normalized_wav = project_dir / "audio" / f"{label}.wav"
        analysis_path = project_dir / "logs" / f"{label}-audio-analysis.json"
        ffmpeg_log = project_dir / "logs" / f"{label}-ffmpeg.log"
        fluidsynth_log = project_dir / "logs" / f"{label}-fluidsynth.log"
        verification_path = project_dir / "logs" / f"{label}-ffprobe.json"
        try:
            if progress:
                progress(0.02, "Preparing selected notes and tempo")
            write_performance_midi(
                selected_timeline,
                performance_midi,
                speed=settings.speed,
                variant=settings.variant,
            )
            if progress:
                progress(0.08, "Synthesizing local piano audio")
            render_midi_to_wav(
                self.tools.require("fluidsynth"),
                self.tools.require("soundfont"),
                performance_midi,
                raw_wav,
                fluidsynth_log,
            )
            raw_analysis = analyze_wav(raw_wav)
            normalize_wav_duration(
                raw_wav,
                normalized_wav,
                target_duration_seconds=renderer.duration_seconds,
                prefix_silence_seconds=renderer.count_in,
            )
            normalized_analysis = analyze_wav(normalized_wav)
            save_audio_analysis(
                analysis_path,
                raw=raw_analysis,
                normalized=normalized_analysis,
                canonical_duration_seconds=selected_timeline.duration_seconds,
                count_in_seconds=renderer.count_in,
                target_duration_seconds=renderer.duration_seconds,
            )
            if progress:
                progress(
                    0.18,
                    f"Audio normalized to frame duration {renderer.duration_seconds:.3f}s",
                )

            def frame_progress(fraction: float, message: str) -> None:
                if progress:
                    progress(0.18 + fraction * 0.72, message)

            encode_mp4(
                self.tools.require("ffmpeg"),
                renderer.iter_rgb_bytes(frame_progress),
                normalized_wav,
                output_path,
                settings.width,
                settings.height,
                settings.fps,
                renderer.duration_seconds,
                ffmpeg_log,
            )
            if progress:
                progress(0.94, "Verifying streams and A/V boundaries with FFprobe")
            verification = verify_mp4(
                self.tools.require("ffprobe"),
                output_path,
                expected_width=settings.width,
                expected_height=settings.height,
                expected_fps=settings.fps,
                report_path=verification_path,
            )
            artifact_key = "preview" if musical_limit_seconds is not None else "final_video"
            manifest.artifacts[artifact_key] = output_path.relative_to(project_dir).as_posix()
            manifest.artifacts[f"{artifact_key}_verification"] = verification_path.relative_to(
                project_dir
            ).as_posix()
            self.store.save(project_dir, manifest)
            if progress:
                progress(1.0, f"Verified {output_path.name}")
            return output_path, verification
        except BaseException:
            error_path = project_dir / "logs" / f"error-{utc_now().replace(':', '-')}.log"
            error_path.write_text(traceback.format_exc(), encoding="utf-8")
            raise
