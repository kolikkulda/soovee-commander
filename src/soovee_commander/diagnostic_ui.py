"""Local-only diagnostic viewer and explicit export of a support bundle."""
import json
from pathlib import Path
import zipfile

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from .about import diagnostics
from .diagnostic_log import log_path, read_tail, redact
from .i18n import tr


class DiagnosticDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle(tr('Diagnostic log'))
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        note = QLabel(tr('Errors and operation details are saved between launches. Export stays on your computer; nothing is sent automatically. Logs may contain file paths and server addresses.'))
        note.setWordWrap(True); layout.addWidget(note)
        path = QLabel(str(log_path() or tr('Persistent logging is not enabled in this test session.')))
        path.setProperty('userContent', True); path.setWordWrap(True); layout.addWidget(path)
        self.text = QPlainTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        for label, callback in [('Refresh', self.refresh), ('Export diagnostics…', self.export), ('Close', self.close)]:
            button = QPushButton(tr(label)); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.text.setPlainText(read_tail() or tr('No diagnostic records yet.'))
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('Export diagnostics…'), str(Path.home() / 'Soovee-diagnostics.zip'), 'ZIP (*.zip)')
        if not path:
            return
        try:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('system.json', json.dumps(diagnostics(), indent=2))
                interface = dict(theme=self.host.theme_key, width=self.host.width(), height=self.host.height(),
                                 pixel_ratio=self.host.devicePixelRatioF(), panels=[])
                for panel in (self.host.left, self.host.right):
                    bar = panel.tabbar
                    tabs = []
                    for index in range(bar.count()):
                        rect = bar.tabRect(index)
                        button = bar.tabButton(index, bar.ButtonPosition.RightSide)
                        tabs.append(dict(bounds=rect.getRect(), close_bounds=button.geometry().getRect() if button else None))
                    interface['panels'].append(dict(active_tab=bar.currentIndex(), tabs=tabs))
                archive.writestr('interface.json', json.dumps(interface, indent=2))
                current = log_path()
                if current:
                    for item in current.parent.glob('application.jsonl*'):
                        if item.is_file() and not item.is_symlink():
                            archive.writestr(item.name, redact(item.read_text(encoding='utf-8', errors='replace')))
                archive.writestr('README.txt', 'Local diagnostic export. Review paths and server addresses before sharing. No credentials or pairing state files are included.\n')
        except (OSError, ValueError) as exc:
            self.host.error(str(exc))
