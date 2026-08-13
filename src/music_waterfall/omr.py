from __future__ import annotations

import shutil
import subprocess
import warnings
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from music_waterfall.errors import ExternalToolError, ReviewRequiredError, ValidationError
from music_waterfall.midi import build_timeline, inspect_midi, suggested_assignments
from music_waterfall.models import ProjectManifest, ReviewState, SourceKind
from music_waterfall.project import ProjectStore
from music_waterfall.renderer import ProgressCallback
from music_waterfall.tools import ToolDiscovery
from music_waterfall.util import atomic_write_json, sha256_file, utc_now


class OmrService:
    def __init__(self, tools: ToolDiscovery, store: ProjectStore):
        self.tools = tools
        self.store = store

    def run_audiveris(
        self,
        project_dir: Path,
        manifest: ProjectManifest,
        progress: ProgressCallback | None = None,
    ) -> tuple[Path, Path]:
        if manifest.source.kind is not SourceKind.PDF:
            raise ValidationError("Audiveris can only run for a sheet-music PDF project.")
        audiveris = self.tools.require("audiveris")
        source = project_dir / manifest.source.copied_path
        output_dir = project_dir / "intermediate" / "audiveris"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = project_dir / "logs" / "audiveris.log"
        command = [
            str(audiveris),
            "-batch",
            "-transcribe",
            "-export",
            "-save",
            "-output",
            str(output_dir),
            "--",
            str(source),
        ]
        if progress:
            progress(0.05, "Audiveris is recognizing the score locally")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExternalToolError(f"Audiveris could not process the PDF: {exc}") from exc
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
                f"Audiveris failed with exit code {result.returncode}: {final_line}. "
                f"See {log_path}."
            )
        omr_files = sorted(output_dir.rglob("*.omr"), key=lambda path: path.stat().st_mtime)
        xml_files = sorted(
            [*output_dir.rglob("*.mxl"), *output_dir.rglob("*.musicxml")],
            key=lambda path: path.stat().st_mtime,
        )
        if not omr_files or not xml_files:
            raise ExternalToolError(
                "Audiveris reported success but did not create both .omr and MusicXML artifacts. "
                f"Inspect {log_path} and {output_dir}."
            )
        omr_path = omr_files[-1]
        xml_path = xml_files[-1]
        if not omr_path.stat().st_size or not xml_path.stat().st_size:
            raise ExternalToolError("Audiveris created an empty OMR or MusicXML artifact.")
        report_path = project_dir / "logs" / "audiveris-artifacts.json"
        validate_artifacts(
            omr_path,
            xml_path,
            expected_pages=manifest.source.page_count,
            report_path=report_path,
        )
        manifest.omr_file = omr_path.relative_to(project_dir).as_posix()
        manifest.musicxml_file = xml_path.relative_to(project_dir).as_posix()
        manifest.artifacts["audiveris_musicxml_original"] = manifest.musicxml_file
        manifest.artifacts["omr_validation"] = report_path.relative_to(project_dir).as_posix()
        manifest.review_state = ReviewState.UNREVIEWED
        manifest.reviewed_at = None
        manifest.reviewed_musicxml_sha256 = None
        manifest.timeline_file = None
        self.store.save(project_dir, manifest)
        if progress:
            progress(
                1.0,
                "Recognition finished. Human comparison in MuseScore is required before rendering.",
            )
        return omr_path, xml_path

    def import_corrected_musicxml(
        self,
        project_dir: Path,
        manifest: ProjectManifest,
        corrected_path: Path,
    ) -> Path:
        """Preserve and select a user-corrected MusicXML file for the review gate."""

        if manifest.source.kind is not SourceKind.PDF:
            raise ValidationError("Corrected MusicXML can only be attached to a PDF project.")
        try:
            source = corrected_path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValidationError(f"Cannot read corrected MusicXML: {exc}") from exc
        if source.suffix.lower() not in {".mxl", ".musicxml", ".xml"}:
            raise ValidationError(
                "Choose an exported MusicXML file (.mxl, .musicxml, or .xml). "
                "MuseScore .mscz files must first be exported with File > Export."
            )

        structure = validate_musicxml_input(source)
        digest = sha256_file(source)
        corrections_dir = project_dir / "intermediate" / "corrections"
        corrections_dir.mkdir(parents=True, exist_ok=True)
        target = corrections_dir / f"corrected-score-{digest[:12]}{source.suffix.lower()}"
        if not target.exists():
            shutil.copy2(source, target)
        if sha256_file(target) != digest:
            raise ValidationError("The copied corrected MusicXML does not match its source.")

        if (
            manifest.musicxml_file
            and manifest.omr_file
            and "audiveris_musicxml_original" not in manifest.artifacts
        ):
            manifest.artifacts["audiveris_musicxml_original"] = manifest.musicxml_file

        relative_target = target.relative_to(project_dir).as_posix()
        report_path = project_dir / "logs" / f"corrected-score-import-{digest[:12]}.json"
        atomic_write_json(
            report_path,
            {
                "imported_at": utc_now(),
                "source_path": str(source),
                "copied_path": relative_target,
                "sha256": digest,
                "structure": structure,
                "review_state": ReviewState.UNREVIEWED.value,
                "note": "Structural validity is not musical accuracy; human review is required.",
            },
        )

        manifest.musicxml_file = relative_target
        manifest.artifacts["corrected_musicxml"] = relative_target
        manifest.artifacts["corrected_musicxml_import"] = report_path.relative_to(
            project_dir
        ).as_posix()
        manifest.artifacts.pop("reviewed_midi", None)
        manifest.artifacts.pop("review_conversion_error", None)
        manifest.review_state = ReviewState.UNREVIEWED
        manifest.reviewed_at = None
        manifest.reviewed_musicxml_sha256 = None
        manifest.timeline_file = None
        manifest.midi_inspection_file = None
        manifest.assignments = []
        self.store.save(project_dir, manifest)
        return target

    def open_in_musescore(self, project_dir: Path, manifest: ProjectManifest) -> None:
        if not manifest.musicxml_file:
            raise ValidationError("Run Audiveris before opening the score in MuseScore Studio.")
        musescore = self.tools.require("musescore")
        musicxml = project_dir / manifest.musicxml_file
        if not musicxml.is_file():
            raise ValidationError(f"Recognized MusicXML is missing: {musicxml}")
        try:
            subprocess.Popen(
                [str(musescore), str(musicxml)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            raise ExternalToolError(f"MuseScore Studio could not open {musicxml}: {exc}") from exc

    def mark_reviewed(
        self,
        project_dir: Path,
        manifest: ProjectManifest,
        explicit_confirmation: bool,
    ) -> Path:
        if not explicit_confirmation:
            raise ReviewRequiredError("Score reviewed was not confirmed. Rendering remains locked.")
        if not manifest.musicxml_file:
            raise ValidationError("No Audiveris MusicXML is available to review.")
        musicxml = project_dir / manifest.musicxml_file
        if not musicxml.is_file():
            raise ValidationError(f"MusicXML is missing: {musicxml}")
        reviewed_midi = project_dir / "intermediate" / "reviewed-score.mid"
        try:
            # Music21 is intentionally lazy-loaded so opening the GUI does not initialize
            # its MusicXML importer or emit score-specific warnings.
            from music21 import converter
            from music21.musicxml.xmlToM21 import MusicXMLWarning

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", MusicXMLWarning)
                score = converter.parse(musicxml)
            score.write("midi", fp=reviewed_midi)
        except Exception as exc:
            error_path = project_dir / "logs" / "review-conversion-error.json"
            manifest.review_state = ReviewState.UNREVIEWED
            manifest.reviewed_at = None
            manifest.reviewed_musicxml_sha256 = None
            manifest.timeline_file = None
            manifest.midi_inspection_file = None
            manifest.assignments = []
            manifest.artifacts.pop("reviewed_midi", None)
            atomic_write_json(
                error_path,
                {
                    "failed_at": utc_now(),
                    "musicxml_path": str(musicxml.resolve()),
                    "musicxml_sha256": sha256_file(musicxml),
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "review_state": ReviewState.UNREVIEWED.value,
                },
            )
            manifest.artifacts["review_conversion_error"] = error_path.relative_to(
                project_dir
            ).as_posix()
            self.store.save(project_dir, manifest)
            raise ValidationError(
                "The selected MusicXML could not be converted to a performance timeline, so "
                "the project remains unreviewed. In MuseScore, repair or linearize confusing "
                "repeats/endings, export MusicXML, import the corrected file, and try again. "
                f"Details: {exc}. Diagnostic: {error_path}"
            ) from exc
        musicxml_warnings = [
            {
                "category": warning.category.__name__,
                "message": str(warning.message),
                "source": warning.filename,
                "line": warning.lineno,
            }
            for warning in caught
            if issubclass(warning.category, MusicXMLWarning)
        ]
        for warning in caught:
            if not issubclass(warning.category, MusicXMLWarning):
                warnings.warn_explicit(
                    warning.message,
                    warning.category,
                    warning.filename,
                    warning.lineno,
                )
        warning_path = project_dir / "logs" / "musicxml-import-warnings.json"
        atomic_write_json(
            warning_path,
            {
                "warning_count": len(musicxml_warnings),
                "warnings": musicxml_warnings,
                "note": (
                    "These are non-fatal Music21 import diagnostics captured during the explicit "
                    "reviewed-score conversion."
                ),
            },
        )
        inspection = inspect_midi(reviewed_midi)
        assignments = suggested_assignments(inspection)
        timeline = build_timeline(reviewed_midi, assignments)
        if not timeline.notes:
            raise ValidationError("The reviewed MusicXML contains no playable notes.")
        manifest.assignments = assignments
        manifest.review_state = ReviewState.REVIEWED
        manifest.reviewed_at = utc_now()
        manifest.reviewed_musicxml_sha256 = sha256_file(musicxml)
        manifest.artifacts["reviewed_midi"] = reviewed_midi.relative_to(project_dir).as_posix()
        manifest.artifacts.pop("review_conversion_error", None)
        manifest.artifacts["musicxml_import_warnings"] = warning_path.relative_to(
            project_dir
        ).as_posix()
        inspection_path = project_dir / "intermediate" / "reviewed-midi-inspection.json"
        atomic_write_json(inspection_path, inspection.to_dict())
        manifest.midi_inspection_file = inspection_path.relative_to(project_dir).as_posix()
        self.store.save_timeline(project_dir, manifest, timeline)
        return reviewed_midi


def validate_musicxml_input(musicxml_path: Path) -> dict[str, object]:
    """Validate plain or compressed MusicXML structure without judging musical accuracy."""

    if not musicxml_path.is_file() or not musicxml_path.stat().st_size:
        raise ValidationError(f"Corrected MusicXML is missing or empty: {musicxml_path}")

    try:
        if zipfile.is_zipfile(musicxml_path):
            with zipfile.ZipFile(musicxml_path) as archive:
                entries = archive.namelist()
                if "META-INF/container.xml" not in entries:
                    raise ValidationError("Compressed MusicXML is missing META-INF/container.xml.")
                container_root = ElementTree.fromstring(archive.read("META-INF/container.xml"))
                rootfile = next(
                    (
                        node.attrib.get("full-path")
                        for node in container_root.iter()
                        if node.tag.endswith("rootfile") and node.attrib.get("full-path")
                    ),
                    None,
                )
                if not rootfile or rootfile not in entries:
                    raise ValidationError("Compressed MusicXML points to a missing score document.")
                score_root = ElementTree.fromstring(archive.read(rootfile))
            container = "compressed"
            entry_count = len(entries)
        else:
            score_root = ElementTree.parse(musicxml_path).getroot()
            rootfile = musicxml_path.name
            container = "plain"
            entry_count = 1
    except ValidationError:
        raise
    except (OSError, ElementTree.ParseError, zipfile.BadZipFile) as exc:
        raise ValidationError(f"Cannot parse corrected MusicXML: {exc}") from exc

    if not score_root.tag.endswith(("score-partwise", "score-timewise")):
        raise ValidationError("The selected file does not contain a MusicXML score root.")
    return {
        "container": container,
        "rootfile": rootfile,
        "entry_count": entry_count,
        "score_root": score_root.tag,
    }


def validate_artifacts(
    omr_path: Path,
    musicxml_path: Path,
    expected_pages: int | None,
    report_path: Path | None = None,
) -> dict[str, object]:
    """Check artifact structure only; this deliberately does not judge OMR accuracy."""

    if not zipfile.is_zipfile(omr_path):
        raise ExternalToolError(f"Audiveris OMR artifact is not a valid archive: {omr_path}")
    if not zipfile.is_zipfile(musicxml_path):
        raise ExternalToolError(
            "Audiveris MusicXML artifact is not a valid compressed MusicXML archive: "
            f"{musicxml_path}"
        )
    with zipfile.ZipFile(omr_path) as omr_zip:
        omr_entries = omr_zip.namelist()
    sheet_names = sorted(
        {name.split("/", 1)[0] for name in omr_entries if name.startswith("sheet#") and "/" in name}
    )
    if expected_pages is not None and len(sheet_names) != expected_pages:
        raise ExternalToolError(
            f"Audiveris OMR contains {len(sheet_names)} sheets; expected {expected_pages}."
        )
    if not any(name.endswith(".xml") for name in omr_entries):
        raise ExternalToolError("Audiveris OMR archive contains no sheet XML data.")

    with zipfile.ZipFile(musicxml_path) as musicxml_zip:
        xml_entries = musicxml_zip.namelist()
        if "META-INF/container.xml" not in xml_entries:
            raise ExternalToolError("Compressed MusicXML is missing META-INF/container.xml.")
        container_root = ElementTree.fromstring(musicxml_zip.read("META-INF/container.xml"))
        rootfile = next(
            (
                node.attrib.get("full-path")
                for node in container_root.iter()
                if node.tag.endswith("rootfile") and node.attrib.get("full-path")
            ),
            None,
        )
        if not rootfile or rootfile not in xml_entries:
            raise ExternalToolError("Compressed MusicXML container points to a missing score.")
        score_root = ElementTree.fromstring(musicxml_zip.read(rootfile))
        if not score_root.tag.endswith(("score-partwise", "score-timewise")):
            raise ExternalToolError("Compressed MusicXML does not contain a MusicXML score root.")

    report: dict[str, object] = {
        "valid": True,
        "recognition_accuracy_reviewed": False,
        "warning": (
            "Archive validity is not recognition accuracy. Human comparison with the PDF is "
            "required."
        ),
        "omr": {
            "path": str(omr_path.resolve()),
            "size_bytes": omr_path.stat().st_size,
            "sha256": sha256_file(omr_path),
            "sheet_count": len(sheet_names),
            "entry_count": len(omr_entries),
        },
        "musicxml": {
            "path": str(musicxml_path.resolve()),
            "size_bytes": musicxml_path.stat().st_size,
            "sha256": sha256_file(musicxml_path),
            "rootfile": rootfile,
            "entry_count": len(xml_entries),
        },
    }
    if report_path:
        atomic_write_json(report_path, report)
    return report
