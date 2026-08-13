from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from music_waterfall.errors import MusicWaterfallError
from music_waterfall.media import verify_mp4
from music_waterfall.midi import inspect_midi
from music_waterfall.models import (
    AssignmentMode,
    KeyboardRange,
    OutputVariant,
    TrackAssignment,
)
from music_waterfall.service import MusicWaterfallService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="music-waterfall",
        description="Create local synchronized piano waterfall videos.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check the local rendering toolchain")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    set_tool = subparsers.add_parser("set-tool", help="Save a user-local tool path override")
    set_tool.add_argument(
        "tool",
        choices=["ffmpeg", "ffprobe", "fluidsynth", "audiveris", "musescore", "soundfont"],
    )
    set_tool.add_argument("path", type=Path)

    inspect = subparsers.add_parser("inspect-midi", help="Inspect tracks and timing in a MIDI")
    inspect.add_argument("midi", type=Path)
    inspect.add_argument("--json", action="store_true")

    create_midi = subparsers.add_parser("create-midi", help="Create a resumable MIDI project")
    create_midi.add_argument("midi", type=Path)
    create_midi.add_argument("--name")

    create_pdf = subparsers.add_parser("create-pdf", help="Create an unreviewed PDF project")
    create_pdf.add_argument("pdf", type=Path)
    create_pdf.add_argument("--name")

    show = subparsers.add_parser("show", help="Show a saved project manifest")
    show.add_argument("project", type=Path)

    assign = subparsers.add_parser("assign-track", help="Change one track's hand assignment")
    assign.add_argument("project", type=Path)
    assign.add_argument("track", type=int)
    assign.add_argument("mode", choices=[mode.value for mode in AssignmentMode])
    assign.add_argument("--split-pitch", type=int, default=60)

    settings = subparsers.add_parser("settings", help="Update practice and render settings")
    settings.add_argument("project", type=Path)
    settings.add_argument("--variant", choices=[item.value for item in OutputVariant])
    settings.add_argument("--tempo", type=int, choices=[50, 70, 85, 100])
    settings.add_argument("--lookahead", type=float)
    settings.add_argument("--note-names", action=argparse.BooleanOptionalAction)
    settings.add_argument("--count-in", action=argparse.BooleanOptionalAction)
    settings.add_argument("--count-in-beats", type=int)
    settings.add_argument("--tail", type=float)
    settings.add_argument(
        "--keyboard",
        choices=[KeyboardRange.FULL.value],
        help="Keyboard layout is fixed to the full 88-key piano",
    )

    preview = subparsers.add_parser("preview", help="Render a short 720p/30 preview")
    preview.add_argument("project", type=Path)
    preview.add_argument("--seconds", type=float, default=12.0)

    render = subparsers.add_parser("render", help="Render a complete project")
    render.add_argument("project", type=Path)
    render.add_argument("--preset", choices=["preview", "final", "saved"], default="final")

    verify = subparsers.add_parser("verify", help="Verify MP4 streams and synchronization")
    verify.add_argument("video", type=Path)
    verify.add_argument("--width", type=int)
    verify.add_argument("--height", type=int)
    verify.add_argument("--fps", type=float)

    omr = subparsers.add_parser("run-omr", help="Run local Audiveris recognition")
    omr.add_argument("project", type=Path)

    open_score = subparsers.add_parser(
        "open-score", help="Open recognized MusicXML in MuseScore Studio"
    )
    open_score.add_argument("project", type=Path)

    reviewed = subparsers.add_parser(
        "mark-reviewed", help="Confirm human review and unlock score conversion"
    )
    reviewed.add_argument("project", type=Path)
    reviewed.add_argument(
        "--i-reviewed",
        action="store_true",
        help="Confirm that the MusicXML was compared with the source PDF and corrected",
    )

    subparsers.add_parser("gui", help="Open the PySide6 desktop application")
    return parser


def _progress(fraction: float, message: str) -> None:
    print(f"[{fraction * 100:6.2f}%] {message}", file=sys.stderr, flush=True)


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _update_settings(args: argparse.Namespace, service: MusicWaterfallService) -> None:
    project_dir, manifest = service.load_project(args.project)
    settings = manifest.settings
    if args.variant is not None:
        settings.variant = OutputVariant(args.variant)
    if args.tempo is not None:
        settings.tempo_percent = args.tempo
    if args.lookahead is not None:
        settings.lookahead_seconds = args.lookahead
    if args.note_names is not None:
        settings.note_names = args.note_names
    if args.count_in is not None:
        settings.count_in = args.count_in
    if args.count_in_beats is not None:
        settings.count_in_beats = args.count_in_beats
    if args.tail is not None:
        settings.tail_seconds = args.tail
    if args.keyboard is not None:
        settings.keyboard_range = KeyboardRange(args.keyboard)
    service.save_settings(project_dir, manifest, settings)
    _print_json(settings.to_dict())


def run(args: argparse.Namespace) -> int:
    service = MusicWaterfallService()
    if args.command == "doctor":
        statuses = service.tools.all()
        if args.json:
            _print_json([status.to_dict() for status in statuses])
        else:
            for status in statuses:
                marker = "OK" if status.found else "MISSING"
                version = f" | {status.version}" if status.version else ""
                print(f"{marker:7} {status.display_name:18} {status.detail}{version}")
                if status.remediation:
                    print(f"        {status.remediation}")
        return 0 if all(status.found for status in statuses) else 1
    if args.command == "set-tool":
        path = args.path.expanduser().resolve()
        if not path.is_file():
            raise MusicWaterfallError(f"Tool override is not a file: {path}")
        service.config.tool_overrides[args.tool] = str(path)
        config_path = service.config.save()
        print(f"Saved {args.tool} = {path}\nConfiguration: {config_path}")
        return 0
    if args.command == "inspect-midi":
        inspection = inspect_midi(args.midi.resolve())
        if args.json:
            _print_json(inspection.to_dict())
        else:
            print(
                f"Type {inspection.midi_type} | {inspection.track_count} tracks | "
                f"{inspection.note_count} notes | {inspection.duration_seconds:.3f}s | "
                f"range {inspection.lowest_note}-{inspection.highest_note}"
            )
            for track in inspection.tracks:
                print(
                    f"  [{track.index}] {track.name}: {track.note_count} notes, "
                    f"channels={track.channels}, programs={track.programs}, "
                    f"range={track.lowest_note}-{track.highest_note}"
                )
            for tempo in inspection.tempo_changes:
                print(f"  tempo @{tempo.seconds:.3f}s: {tempo.bpm:.3f} BPM")
        return 0
    if args.command == "create-midi":
        project_dir, manifest = service.create_midi_project(args.midi, args.name)
        print(project_dir / "project.json")
        _print_json(manifest.to_dict())
        return 0
    if args.command == "create-pdf":
        project_dir, manifest = service.create_pdf_project(args.pdf, args.name)
        print(project_dir / "project.json")
        _print_json(manifest.to_dict())
        return 0
    if args.command == "show":
        _, manifest = service.load_project(args.project)
        _print_json(manifest.to_dict())
        return 0
    if args.command == "assign-track":
        project_dir, manifest = service.load_project(args.project)
        assignments = [
            TrackAssignment(item.track_index, item.mode, item.split_pitch)
            for item in manifest.assignments
        ]
        replacement = TrackAssignment(
            track_index=args.track,
            mode=AssignmentMode(args.mode),
            split_pitch=args.split_pitch,
        )
        for index, item in enumerate(assignments):
            if item.track_index == args.track:
                assignments[index] = replacement
                break
        else:
            assignments.append(replacement)
        service.save_assignments(project_dir, manifest, assignments)
        _print_json(manifest.to_dict())
        return 0
    if args.command == "settings":
        _update_settings(args, service)
        return 0
    if args.command == "preview":
        output, verification = service.render_preview(args.project, args.seconds, _progress)
        print(output)
        _print_json(verification.to_dict())
        return 0
    if args.command == "render":
        output, verification = service.render(args.project, args.preset, progress=_progress)
        print(output)
        _print_json(verification.to_dict())
        return 0
    if args.command == "verify":
        report = args.video.with_suffix(".verification.json")
        verification = verify_mp4(
            service.tools.require("ffprobe"),
            args.video,
            args.width,
            args.height,
            args.fps,
            report,
        )
        _print_json(verification.to_dict())
        return 0
    if args.command == "run-omr":
        project_dir, manifest = service.load_project(args.project)
        omr_path, xml_path = service.omr.run_audiveris(project_dir, manifest, progress=_progress)
        print(f"OMR: {omr_path}\nMusicXML: {xml_path}\nState: {manifest.review_state.value}")
        return 0
    if args.command == "open-score":
        project_dir, manifest = service.load_project(args.project)
        service.omr.open_in_musescore(project_dir, manifest)
        print(
            "MuseScore Studio opened. Compare the MusicXML against the source PDF and correct it."
        )
        return 0
    if args.command == "mark-reviewed":
        project_dir, manifest = service.load_project(args.project)
        reviewed_midi = service.omr.mark_reviewed(
            project_dir, manifest, explicit_confirmation=args.i_reviewed
        )
        print(f"Score reviewed and timeline created from {reviewed_midi}")
        return 0
    if args.command == "gui":
        from music_waterfall.gui import main as gui_main

        return gui_main()
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except MusicWaterfallError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
