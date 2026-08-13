from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QTextBrowser

from music_waterfall.gui import SCORE_REPAIR_TIPS_HTML, ProjectPage, ScoreRepairTipsDialog


def test_score_repair_tips_embed_repeat_and_export_procedure() -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    dialog = ScoreRepairTipsDialog()
    browser = dialog.findChild(QTextBrowser)

    assert browser is not None
    text = browser.toPlainText()
    assert "Repeat list" in text
    assert "Play count" in text
    assert "Apply a normal barline" in text
    assert "File > Export" in text
    assert "Mark score reviewed" in text
    assert "Displayed text is visual only" in SCORE_REPAIR_TIPS_HTML


def test_mark_reviewed_button_is_the_explicit_approval_action(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None

    class FakeOmr:
        def __init__(self):
            self.confirmation: bool | None = None

        def mark_reviewed(self, _project_dir, _manifest, explicit_confirmation):
            self.confirmation = explicit_confirmation
            return tmp_path / "reviewed-score.mid"

    class FakeService:
        def __init__(self):
            self.omr = FakeOmr()

        def load_project(self, _path):
            return tmp_path, object()

    service = FakeService()
    page = ProjectPage(service, QThreadPool())
    page.project_dir = tmp_path
    progress_messages: list[str] = []

    def run_immediately(task, _label):
        task(lambda _fraction, message: progress_messages.append(message))

    page._start_task = run_immediately
    page.mark_reviewed()

    assert service.omr.confirmation is True
    assert progress_messages[-1] == "Reviewed score converted to canonical timeline"
