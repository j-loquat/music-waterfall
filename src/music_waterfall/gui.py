from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from music_waterfall.errors import MusicWaterfallError
from music_waterfall.models import (
    AssignmentMode,
    KeyboardRange,
    OutputVariant,
    ProjectManifest,
    ReviewState,
    SourceKind,
    TrackAssignment,
)
from music_waterfall.service import MusicWaterfallService

STYLE = """
QMainWindow, QWidget { background: #0e1726; color: #e7eef7; }
QLabel, QCheckBox { background: transparent; }
QLabel#title { font-size: 34px; font-weight: 700; color: #f3f7fb; }
QLabel#subtitle { font-size: 16px; color: #aebed0; }
QLabel#sectionTitle { font-size: 20px; font-weight: 650; color: #f2f6fb; }
QLabel#statusGood { color: #6edab8; font-weight: 700; }
QLabel#statusWarning { color: #ffbd66; font-weight: 700; }
QFrame#card, QGroupBox {
  background: #142238; border: 1px solid #2b405a; border-radius: 10px; margin-top: 8px;
}
QGroupBox { padding-top: 16px; font-weight: 650; }
QPushButton {
  background: #243b5a; border: 1px solid #456283; border-radius: 7px;
  padding: 9px 14px; font-weight: 600;
}
QPushButton:hover { background: #2c4b70; }
QPushButton:pressed { background: #1c304b; }
QPushButton:disabled { color: #718196; background: #18263a; border-color: #283950; }
QPushButton#primary { background: #2476a8; border-color: #49a6d5; }
QPushButton#primary:hover { background: #2d88bd; }
QPushButton#danger { background: #734534; border-color: #b16a4d; }
QLabel#repairHelp {
  background: #0b1828; border-left: 4px solid #49a6d5; border-radius: 4px;
  color: #c9d9e9; padding: 10px 12px;
}
QPushButton#tip {
  background: #182d46; border-color: #4b7195; color: #cfe5f7; padding: 7px 10px;
}
QPushButton#tip:hover { background: #234566; border-color: #6da3cf; }
QTextBrowser#repairTips {
  background: #0b1828; border: 1px solid #334b67; border-radius: 6px; padding: 12px;
}
QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTableWidget {
  background: #0c1625; border: 1px solid #334b67; border-radius: 5px; padding: 5px;
  selection-background-color: #2476a8;
}
QHeaderView::section { background: #1e334e; color: #dce8f3; padding: 7px; border: 0; }
QProgressBar {
  background: #0a1320; border: 1px solid #334b67; border-radius: 5px; text-align: center;
}
QProgressBar::chunk { background: #3cb792; border-radius: 4px; }
QScrollArea { border: 0; }
"""


class WorkerSignals(QObject):
    progress = Signal(float, str)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[[Callable[[float, str], None]], Any]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            value = self.function(self.signals.progress.emit)
        except BaseException as exc:
            if isinstance(exc, MusicWaterfallError):
                message = str(exc)
            else:
                message = f"{exc}\n\n{traceback.format_exc()}"
            self.signals.error.emit(message)
        else:
            self.signals.result.emit(value)
        finally:
            self.signals.finished.emit()


class HomePage(QWidget):
    start_midi = Signal()
    start_pdf = Signal()
    resume = Signal()

    def __init__(self, doctor_summary: str):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(72, 52, 72, 52)
        outer.setSpacing(18)
        title = QLabel("Music Waterfall")
        title.setObjectName("title")
        subtitle = QLabel(
            "Turn piano MIDI or reviewed printed music into clear, synchronized practice videos."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(18)

        choices = QGridLayout()
        choices.setHorizontalSpacing(18)
        choices.setVerticalSpacing(18)
        choices.addWidget(
            self._choice_card(
                "1",
                "Start from MIDI",
                "Reliable path. Inspect tracks, set hands and render directly.",
                "Choose MIDI file",
                self.start_midi.emit,
            ),
            0,
            0,
        )
        choices.addWidget(
            self._choice_card(
                "2",
                "Start from sheet-music PDF",
                "Guided Audiveris workflow with a mandatory human review gate.",
                "Choose PDF",
                self.start_pdf.emit,
            ),
            0,
            1,
        )
        choices.addWidget(
            self._choice_card(
                "3",
                "Resume an existing song project",
                "Continue settings, review, preview or rendering after a restart.",
                "Open project.json",
                self.resume.emit,
            ),
            1,
            0,
            1,
            2,
        )
        outer.addLayout(choices)
        outer.addStretch()
        status = QLabel(doctor_summary)
        status.setObjectName("statusGood" if "ready" in doctor_summary.lower() else "statusWarning")
        outer.addWidget(status)

    @staticmethod
    def _choice_card(
        number: str,
        heading: str,
        body: str,
        button_text: str,
        action: Callable[[], None],
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        row = QHBoxLayout()
        badge = QLabel(number)
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("background:#2476a8;border-radius:17px;font-weight:700;")
        label = QLabel(heading)
        label.setObjectName("sectionTitle")
        row.addWidget(badge)
        row.addWidget(label)
        row.addStretch()
        description = QLabel(body)
        description.setWordWrap(True)
        description.setObjectName("subtitle")
        button = QPushButton(button_text)
        button.setObjectName("primary")
        button.clicked.connect(action)
        layout.addLayout(row)
        layout.addWidget(description)
        layout.addStretch()
        layout.addWidget(button)
        return card


SCORE_REPAIR_TIPS_HTML = """
<h2>Fix repeat and MusicXML errors</h2>
<p>Use these steps when conversion reports <b>badly formed repeats or repeat
expressions</b>, or when MuseScore playback does not follow the printed score.</p>

<h3>Correct first, second, or later endings</h3>
<ol>
  <li>Select the complete Volta bracket in the score. Do not edit only its displayed text.</li>
  <li>Open <b>Properties &gt; Style &gt; Volta</b>.</li>
  <li>Set <b>Repeat list</b> to <code>1</code> for the first ending,
      <code>2</code> for the second ending, and so on. Displayed text is visual only.</li>
  <li>Select the end-repeat barline and set <b>Play count</b> to the required number of passes.
      A first/second ending normally requires a play count of <code>2</code>.</li>
  <li>Verify that each Volta has a matching repeat path. Do not leave two endings assigned to
      the same repeat number.</li>
</ol>

<h3>Remove repeat playback for a simple linear score</h3>
<ol>
  <li>Save a separate MuseScore working copy before changing the structure.</li>
  <li>Delete every Volta bracket that no longer applies.</li>
  <li>Select each start-repeat and end-repeat barline.</li>
  <li>Apply a normal barline from the <b>Barlines</b> palette.</li>
  <li>Verify that no repeat dots, ending brackets, D.C./D.S., Fine, Segno, or Coda instructions
      remain. If navigation is still required, write the measures in playback order.</li>
</ol>

<h3>Save, export, and return to Music Waterfall</h3>
<ol>
  <li>Play the score in MuseScore and verify the complete playback order.</li>
  <li>Select <b>File &gt; Save</b> to preserve the editable <code>.mscz</code> working file.</li>
  <li>Select <b>File &gt; Export</b> and export a newly named MusicXML
      <code>.mxl</code> or <code>.musicxml</code> file.</li>
  <li>In Music Waterfall, select <b>3. Import corrected MusicXML</b>.</li>
  <li>Select <b>4. Mark score reviewed</b>. This click is the approval action. Rendering unlocks
      only if conversion succeeds.</li>
</ol>
"""


class ScoreRepairTipsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Repeat and MusicXML repair tips")
        self.setMinimumSize(720, 600)
        layout = QVBoxLayout(self)
        tips = QTextBrowser()
        tips.setObjectName("repairTips")
        tips.setOpenExternalLinks(False)
        tips.setHtml(SCORE_REPAIR_TIPS_HTML)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(tips)
        layout.addWidget(buttons)


class ProjectPage(QWidget):
    back_requested = Signal()

    def __init__(self, service: MusicWaterfallService, thread_pool: QThreadPool):
        super().__init__()
        self.service = service
        self.thread_pool = thread_pool
        self.project_dir: Path | None = None
        self.manifest: ProjectManifest | None = None
        self.latest_video: Path | None = None
        self._workers: set[Worker] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        header = QHBoxLayout()
        back = QPushButton("← Projects")
        back.clicked.connect(self.back_requested.emit)
        self.title = QLabel("Song project")
        self.title.setObjectName("sectionTitle")
        self.state = QLabel()
        header.addWidget(back)
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.state)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(14)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        body_layout.addWidget(self._wrap_card("Source", self.source_label))

        self.pdf_group = QGroupBox("Sheet-music recognition and review")
        pdf_layout = QVBoxLayout(self.pdf_group)
        self.pdf_notice = QLabel()
        self.pdf_notice.setWordWrap(True)
        self.pdf_repair_help = QLabel()
        self.pdf_repair_help.setObjectName("repairHelp")
        self.pdf_repair_help.setWordWrap(True)
        pdf_actions = QGridLayout()
        self.run_omr_button = QPushButton("1. Run Audiveris locally")
        self.open_score_button = QPushButton("2. Open MusicXML in MuseScore")
        self.open_pdf_button = QPushButton("Open source PDF")
        self.repair_tips_button = QPushButton("? Repeat + MusicXML tips")
        self.repair_tips_button.setObjectName("tip")
        self.import_score_button = QPushButton("3. Import corrected MusicXML")
        self.import_score_button.setObjectName("primary")
        self.review_button = QPushButton("4. Mark score reviewed")
        self.review_button.setObjectName("danger")
        self.review_button.setToolTip(
            "This click is the explicit approval. Rendering unlocks only if conversion succeeds."
        )
        self.run_omr_button.clicked.connect(self.run_omr)
        self.open_score_button.clicked.connect(self.open_score)
        self.open_pdf_button.clicked.connect(self.open_source_pdf)
        self.repair_tips_button.clicked.connect(self.show_score_repair_tips)
        self.import_score_button.clicked.connect(self.import_corrected_score)
        self.review_button.clicked.connect(self.mark_reviewed)
        pdf_actions.addWidget(self.run_omr_button, 0, 0)
        pdf_actions.addWidget(self.open_score_button, 0, 1)
        pdf_actions.addWidget(self.open_pdf_button, 0, 2)
        pdf_actions.addWidget(self.repair_tips_button, 1, 0)
        pdf_actions.addWidget(self.import_score_button, 1, 1)
        pdf_actions.addWidget(self.review_button, 1, 2)
        pdf_layout.addWidget(self.pdf_notice)
        pdf_layout.addWidget(self.pdf_repair_help)
        pdf_layout.addLayout(pdf_actions)
        body_layout.addWidget(self.pdf_group)

        mapping = QGroupBox("Track and hand mapping")
        mapping_layout = QVBoxLayout(mapping)
        mapping_help = QLabel(
            "Blue is left hand; orange is right hand. “Both” uses the editable pitch split."
        )
        mapping_help.setObjectName("subtitle")
        self.track_table = QTableWidget(0, 8)
        self.track_table.setHorizontalHeaderLabels(
            ["Track", "Name", "Notes", "Channels", "Programs", "Range", "Hand", "Split"]
        )
        self.track_table.horizontalHeader().setStretchLastSection(True)
        self.track_table.setMinimumHeight(170)
        mapping_layout.addWidget(mapping_help)
        mapping_layout.addWidget(self.track_table)
        body_layout.addWidget(mapping)

        settings_group = QGroupBox("Practice and video settings")
        settings_layout = QGridLayout(settings_group)
        self.variant = QComboBox()
        self.variant.addItems([item.value for item in OutputVariant])
        self.tempo = QComboBox()
        self.tempo.addItems(["50", "70", "85", "100"])
        self.lookahead = QDoubleSpinBox()
        self.lookahead.setRange(0.5, 10.0)
        self.lookahead.setSingleStep(0.25)
        self.lookahead.setSuffix(" s")
        self.note_names = QCheckBox("Show note names")
        self.count_in = QCheckBox("Four-beat count-in")
        self.keyboard_range = QLabel("Full 88 keys (fixed)")
        settings_layout.addWidget(QLabel("Output hands"), 0, 0)
        settings_layout.addWidget(self.variant, 0, 1)
        settings_layout.addWidget(QLabel("Tempo"), 0, 2)
        settings_layout.addWidget(self.tempo, 0, 3)
        settings_layout.addWidget(QLabel("Look-ahead"), 1, 0)
        settings_layout.addWidget(self.lookahead, 1, 1)
        settings_layout.addWidget(QLabel("Keyboard"), 1, 2)
        settings_layout.addWidget(self.keyboard_range, 1, 3)
        settings_layout.addWidget(self.note_names, 2, 0, 1, 2)
        settings_layout.addWidget(self.count_in, 2, 2, 1, 2)
        body_layout.addWidget(settings_group)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Save settings")
        self.preview_button = QPushButton("Generate 12-second preview")
        self.preview_button.setObjectName("primary")
        self.render_button = QPushButton("Render 1080p / 60 fps MP4")
        self.render_button.setObjectName("primary")
        self.open_output_button = QPushButton("Open latest video")
        self.open_output_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_changes)
        self.preview_button.clicked.connect(self.preview)
        self.render_button.clicked.connect(self.render_final)
        self.open_output_button.clicked.connect(self.open_latest_video)
        actions.addWidget(self.save_button)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.render_button)
        actions.addWidget(self.open_output_button)
        body_layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMinimumHeight(120)
        body_layout.addWidget(self.progress)
        body_layout.addWidget(self.log)
        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll)

    @staticmethod
    def _wrap_card(title: str, content: QWidget) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        layout.addWidget(content)
        return card

    def load(self, project_path: Path) -> None:
        self.project_dir, self.manifest = self.service.load_project(project_path)
        manifest = self.manifest
        self.title.setText(manifest.name)
        source_summary = f"{manifest.source.kind.value.upper()} · {manifest.source.file_name}"
        if manifest.source.kind is SourceKind.PDF:
            source_summary += f" · {manifest.source.page_count} pages · valid, unencrypted"
        elif manifest.midi_inspection_file:
            inspection_path = self.project_dir / manifest.midi_inspection_file
            if inspection_path.is_file():
                inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
                source_summary += (
                    f" · Type {inspection['midi_type']} · {inspection['track_count']} tracks"
                    f" · {inspection['note_count']} notes · {inspection['duration_seconds']:.3f} s"
                    f" · range {inspection['lowest_note']}–{inspection['highest_note']}"
                )
        self.source_label.setText(
            f"{source_summary}\nOriginal: {manifest.source.original_path}\n"
            f"SHA-256: {manifest.source.sha256}"
        )
        settings = manifest.settings
        self.variant.setCurrentText(settings.variant.value)
        self.tempo.setCurrentText(str(settings.tempo_percent))
        self.lookahead.setValue(settings.lookahead_seconds)
        self.note_names.setChecked(settings.note_names)
        self.count_in.setChecked(settings.count_in)
        self._load_tracks()
        self._refresh_review_state()
        self.log.clear()
        self.log.appendPlainText(f"Resumed {self.project_dir / 'project.json'}")

    def _load_tracks(self) -> None:
        assert self.project_dir and self.manifest
        track_data: dict[int, dict[str, Any]] = {}
        if self.manifest.midi_inspection_file:
            path = self.project_dir / self.manifest.midi_inspection_file
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                track_data = {int(item["index"]): item for item in data.get("tracks", [])}
        assignments = self.manifest.assignments
        self.track_table.setRowCount(len(assignments))
        for row, assignment in enumerate(assignments):
            info = track_data.get(assignment.track_index, {})
            values = (
                str(assignment.track_index),
                str(info.get("name", f"Track {assignment.track_index}")),
                str(info.get("note_count", "—")),
                ", ".join(str(value) for value in info.get("channels", [])) or "—",
                ", ".join(str(value) for value in info.get("programs", [])) or "piano/default",
                (
                    f"{info.get('lowest_note')}–{info.get('highest_note')}"
                    if info.get("lowest_note") is not None
                    else "—"
                ),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.track_table.setItem(row, column, item)
            mode = QComboBox()
            mode.addItems([item.value for item in AssignmentMode])
            mode.setCurrentText(assignment.mode.value)
            split = QSpinBox()
            split.setRange(0, 127)
            split.setValue(assignment.split_pitch)
            mode.currentTextChanged.connect(
                lambda value, widget=split: widget.setEnabled(value == AssignmentMode.BOTH.value)
            )
            split.setEnabled(assignment.mode is AssignmentMode.BOTH)
            self.track_table.setCellWidget(row, 6, mode)
            self.track_table.setCellWidget(row, 7, split)
        self.track_table.resizeColumnsToContents()

    def _refresh_review_state(self) -> None:
        assert self.manifest
        is_pdf = self.manifest.source.kind is SourceKind.PDF
        self.pdf_group.setVisible(is_pdf)
        if is_pdf:
            reviewed = self.manifest.review_state is ReviewState.REVIEWED
            has_xml = bool(self.manifest.musicxml_file)
            self.state.setText("SCORE REVIEWED" if reviewed else "UNREVIEWED · RENDER LOCKED")
            self.state.setObjectName("statusGood" if reviewed else "statusWarning")
            self.state.style().unpolish(self.state)
            self.state.style().polish(self.state)
            self.pdf_notice.setText(
                "Reviewed MusicXML is ready for rendering."
                if reviewed
                else (
                    "Recognition output is not trusted automatically. Run Audiveris, open the "
                    "MusicXML beside the PDF in MuseScore, correct it, export it, import the "
                    "corrected MusicXML, then use Step 4 as the explicit approval action."
                )
            )
            self.pdf_repair_help.setText(
                (
                    "If a preview exposes another problem, edit the score again, export a new "
                    "MusicXML, and use Step 3. Importing it automatically locks rendering until "
                    "you review the new version."
                )
                if reviewed
                else (
                    "REPAIR LOOP: Keep rendering locked. Use Repeat & MusicXML tips for Volta "
                    "Repeat list values, repeat barlines, linear playback, and the exact MuseScore "
                    "save/export sequence."
                )
            )
            self.open_score_button.setEnabled(has_xml)
            self.review_button.setEnabled(has_xml and not reviewed)
        else:
            self.state.setText("MIDI READY")
            self.state.setObjectName("statusGood")
        renderable = self.manifest.is_renderable
        self.preview_button.setEnabled(renderable)
        self.render_button.setEnabled(renderable)

    def _read_assignments(self) -> list[TrackAssignment]:
        assignments: list[TrackAssignment] = []
        for row in range(self.track_table.rowCount()):
            track = int(self.track_table.item(row, 0).text())
            mode = self.track_table.cellWidget(row, 6)
            split = self.track_table.cellWidget(row, 7)
            assert isinstance(mode, QComboBox)
            assert isinstance(split, QSpinBox)
            assignments.append(
                TrackAssignment(track, AssignmentMode(mode.currentText()), split.value())
            )
        return assignments

    def save_changes(self) -> None:
        if not self.project_dir or not self.manifest:
            return
        try:
            settings = self.manifest.settings
            settings.variant = OutputVariant(self.variant.currentText())
            settings.tempo_percent = int(self.tempo.currentText())
            settings.lookahead_seconds = self.lookahead.value()
            settings.note_names = self.note_names.isChecked()
            settings.count_in = self.count_in.isChecked()
            settings.keyboard_range = KeyboardRange.FULL
            self.service.save_settings(self.project_dir, self.manifest, settings)
            self.service.save_assignments(self.project_dir, self.manifest, self._read_assignments())
            self.log.appendPlainText("Settings and hand assignments saved.")
        except MusicWaterfallError as exc:
            self._show_error(str(exc))

    def preview(self) -> None:
        self.save_changes()
        assert self.project_dir
        project = self.project_dir / "project.json"
        self._start_task(
            lambda progress: self.service.render_preview(project, 12.0, progress),
            "Generating preview",
        )

    def render_final(self) -> None:
        self.save_changes()
        assert self.project_dir
        project = self.project_dir / "project.json"
        self._start_task(
            lambda progress: self.service.render(project, "final", progress=progress),
            "Rendering final video",
        )

    def run_omr(self) -> None:
        assert self.project_dir and self.manifest
        project_dir = self.project_dir

        def task(progress):
            _, manifest = self.service.load_project(project_dir / "project.json")
            return self.service.omr.run_audiveris(project_dir, manifest, progress)

        self._start_task(task, "Running Audiveris")

    def open_score(self) -> None:
        assert self.project_dir and self.manifest
        try:
            self.service.omr.open_in_musescore(self.project_dir, self.manifest)
            self.log.appendPlainText(
                "MuseScore opened. Compare every page with the PDF. Save a native .mscz working "
                "copy, then use File > Export > MusicXML and import it with Step 3."
            )
        except MusicWaterfallError as exc:
            self._show_error(str(exc))

    def open_source_pdf(self) -> None:
        assert self.project_dir and self.manifest
        source = self.project_dir / self.manifest.source.copied_path
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(source)))

    def show_score_repair_tips(self) -> None:
        ScoreRepairTipsDialog(self).exec()

    def import_corrected_score(self) -> None:
        assert self.project_dir and self.manifest
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose corrected MusicXML exported from MuseScore",
            str(self.project_dir / "intermediate"),
            "MusicXML files (*.mxl *.musicxml *.xml)",
        )
        if not path:
            return
        try:
            imported = self.service.omr.import_corrected_musicxml(
                self.project_dir, self.manifest, Path(path)
            )
            _, self.manifest = self.service.load_project(self.project_dir / "project.json")
            self._load_tracks()
            self._refresh_review_state()
            self.log.appendPlainText(
                f"Corrected MusicXML imported: {imported}. Rendering remains locked until review."
            )
            QMessageBox.information(
                self,
                "Corrected score imported",
                "The corrected MusicXML is now selected. The Audiveris original was preserved, "
                "and rendering remains locked until you complete Step 4.",
            )
        except MusicWaterfallError as exc:
            self._show_error(str(exc))

    def mark_reviewed(self) -> None:
        assert self.project_dir
        project_dir = self.project_dir

        def task(progress):
            progress(0.1, "Validating and converting reviewed MusicXML")
            _, manifest = self.service.load_project(project_dir / "project.json")
            result = self.service.omr.mark_reviewed(project_dir, manifest, True)
            progress(1.0, "Reviewed score converted to canonical timeline")
            return result

        self._start_task(task, "Approving and validating reviewed score")

    def _start_task(
        self,
        function: Callable[[Callable[[float, str], None]], Any],
        label: str,
    ) -> None:
        self._set_busy(True)
        self.progress.setValue(0)
        self.log.appendPlainText(label + "…")
        worker = Worker(function)
        self._workers.add(worker)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda: self._worker_finished(worker))
        self.thread_pool.start(worker)

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(max(0, min(1000, round(fraction * 1000))))
        self.log.appendPlainText(message)

    def _on_result(self, result: object) -> None:
        if isinstance(result, tuple) and result and isinstance(result[0], Path):
            first_path = result[0]
            if first_path.suffix.lower() == ".mp4":
                self.latest_video = first_path
                self.open_output_button.setEnabled(True)
                self.log.appendPlainText(f"Verified video: {first_path}")
            else:
                self.log.appendPlainText(f"Created: {first_path}")
        elif isinstance(result, Path):
            self.log.appendPlainText(
                f"Score approved and canonical timeline created from: {result}"
            )
        if self.project_dir:
            _, self.manifest = self.service.load_project(self.project_dir / "project.json")
            self._load_tracks()
            self._refresh_review_state()

    def _worker_finished(self, worker: Worker) -> None:
        self._workers.discard(worker)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        controls = (
            self.save_button,
            self.preview_button,
            self.render_button,
            self.run_omr_button,
            self.open_score_button,
            self.open_pdf_button,
            self.repair_tips_button,
            self.import_score_button,
            self.review_button,
        )
        for control in controls:
            control.setEnabled(not busy)
        if not busy and self.manifest:
            self._refresh_review_state()

    def _show_error(self, message: str) -> None:
        self.log.appendPlainText("ERROR: " + message)
        repair_markers = (
            "badly formed repeat",
            "repeat expression",
            "repeats/endings",
            "volta",
            "d.c.",
            "d.s.",
            "coda",
        )
        offers_repair_tips = bool(
            self.manifest
            and self.manifest.source.kind is SourceKind.PDF
            and any(marker in message.lower() for marker in repair_markers)
        )
        if not offers_repair_tips:
            QMessageBox.critical(self, "Music Waterfall", message)
            return

        self.log.appendPlainText(
            "Repeat/navigation problem detected. Open Repeat & MusicXML tips for repair steps."
        )
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Critical)
        message_box.setWindowTitle("Music Waterfall")
        message_box.setText(message)
        tips_button = message_box.addButton(
            "Open repeat repair tips", QMessageBox.ButtonRole.ActionRole
        )
        message_box.addButton(QMessageBox.StandardButton.Close)
        message_box.exec()
        if message_box.clickedButton() is tips_button:
            self.show_score_repair_tips()

    def open_latest_video(self) -> None:
        if self.latest_video:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.latest_video)))


class MainWindow(QMainWindow):
    def __init__(self, service: MusicWaterfallService | None = None):
        super().__init__()
        self.service = service or MusicWaterfallService()
        self.thread_pool = QThreadPool.globalInstance()
        self.setWindowTitle("Music Waterfall")
        self.resize(1180, 800)
        self.setMinimumSize(960, 680)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        statuses = self.service.tools.all()
        ready = sum(status.found for status in statuses)
        summary = (
            "Local toolchain ready · FFmpeg, FluidSynth, Audiveris and MuseScore found"
            if ready == len(statuses)
            else f"Toolchain needs attention · {ready}/{len(statuses)} requirements found"
        )
        self.home = HomePage(summary)
        self.project_page = ProjectPage(self.service, self.thread_pool)
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.project_page)
        self.home.start_midi.connect(self.choose_midi)
        self.home.start_pdf.connect(self.choose_pdf)
        self.home.resume.connect(self.resume_project)
        self.project_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.home))

    def choose_midi(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a MIDI file", str(Path.home()), "MIDI files (*.mid *.midi)"
        )
        if path:
            self._create_project(Path(path), SourceKind.MIDI)

    def choose_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a sheet-music PDF", str(Path.home()), "PDF files (*.pdf)"
        )
        if path:
            self._create_project(Path(path), SourceKind.PDF)

    def resume_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Resume a Music Waterfall project",
            str(self.service.config.output_root),
            "Music Waterfall project (project.json)",
        )
        if path:
            self._open_project(Path(path))

    def _create_project(self, path: Path, kind: SourceKind) -> None:
        try:
            project_dir, _ = (
                self.service.create_midi_project(path)
                if kind is SourceKind.MIDI
                else self.service.create_pdf_project(path)
            )
            self._open_project(project_dir / "project.json")
        except MusicWaterfallError as exc:
            QMessageBox.critical(self, "Music Waterfall", str(exc))

    def _open_project(self, path: Path) -> None:
        try:
            self.project_page.load(path)
        except MusicWaterfallError as exc:
            QMessageBox.critical(self, "Music Waterfall", str(exc))
            return
        self.stack.setCurrentWidget(self.project_page)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread_pool.activeThreadCount():
            QMessageBox.information(
                self,
                "Rendering is active",
                "A local task is still running. Wait for it to finish before closing. "
                "Final media is written atomically.",
            )
            event.ignore()
            return
        event.accept()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Music Waterfall")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
