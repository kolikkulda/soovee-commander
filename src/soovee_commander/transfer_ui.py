"""Structured transfer events carried alongside human-readable worker messages."""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPlainTextEdit, QPushButton, QApplication, QFileDialog, QHBoxLayout

from .filemodel import size_text
from .i18n import tr

class TransferDialog(QDialog):
    """A job remains inspectable after completion; closing it keeps the job running."""
    def __init__(self, parent, title, cancel):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 470)
        self.cancel_event = cancel
        self.started = time.monotonic()
        self.total = self.completed = self.files = self.done_files = self.transferred = 0
        self.current_size = self.current_done = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("dialogHeading")
        heading.setWordWrap(True)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(heading)
        self.details = QLabel(tr('Queued'))
        self.details.setObjectName("dialogSubtitle")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(self.details.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        self.file_label = QLabel(tr('Current file'))
        self.total_label = QLabel(tr('Overall'))
        for label in (self.file_label, self.total_label):
            label.setWordWrap(True)
        self.file_bar = QProgressBar()
        self.total_bar = QProgressBar()
        self.total_bar.setRange(0, 0)
        self.file_bar.setTextVisible(False)
        self.total_bar.setTextVisible(False)
        self.file_bar.setFixedHeight(11)
        self.total_bar.setFixedHeight(11)
        layout.addWidget(self.file_label)
        layout.addWidget(self.file_bar)
        layout.addWidget(self.total_label)
        layout.addWidget(self.total_bar)
        self.statistics = QLabel()
        self.statistics.setWordWrap(True)
        self.phase = QLabel()
        layout.addWidget(self.phase)
        layout.addWidget(self.statistics)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(10000)
        layout.addWidget(self.log, 1)
        self.cancel_button = QPushButton(tr('Cancel transfer'))
        self.cancel_button.clicked.connect(cancel.set)
        actions = QHBoxLayout()
        copy = QPushButton(tr('Copy log'))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.log.toPlainText()))
        save = QPushButton(tr('Save log…'))
        save.clicked.connect(self.save_log)
        actions.addWidget(copy)
        actions.addWidget(save)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)

    def save_log(self):
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        filename, _ = QFileDialog.getSaveFileName(self, tr('Save log…'), 'soovee-transfer.log')
        if filename:
            try:
                Path(filename).write_text(self.log.toPlainText(), encoding='utf-8')
            except OSError as exc:
                QMessageBox.warning(self, tr('Cannot complete operation'), str(exc))

    def update_event(self, event):
        kind = event['event']
        line = ''
        if kind == 'plan':
            self.started = time.monotonic()
            self.total, self.files = event['bytes'], event['files']
            self.completed = self.done_files = self.transferred = 0
            self.resume_offset = 0
            line = tr('Total: {v0} files · {v1}').format(v0=self.files, v1=size_text(self.total))
        elif kind == 'file':
            self.current_size, self.current_done = event['size'], 0
            self.resume_offset = 0
            self.phase.setText(tr('Transferring'))
            line = tr('Source: {v0}\nDestination: {v1}\nSize: {v2} ({v3} bytes)').format(v0=event['source'], v1=event['destination'], v2=size_text(self.current_size), v3=self.current_size)
            self.details.setText(line)
        elif kind == 'resume':
            self.resume_offset = event['offset']
            self.current_done = self.resume_offset
            line = tr('Resuming from {v0} bytes').format(v0=self.resume_offset)
        elif kind == 'advance':
            self.current_done = event['bytes'] + self.resume_offset
        elif kind in ('file_done', 'skip'):
            self.transferred += event.get('transferred', 0)
            self.completed += event['size']
            self.done_files += event.get("files", 1)
            self.current_done = 0
            line = tr('Done: ') + event['path'] if kind == 'file_done' else tr('Skipped: ') + event['path']
        elif kind == 'scan':
            self.details.setText(tr('Scanning source…') + ' ' + event['path'])
            return ''
        elapsed = max(.01, time.monotonic() - self.started)
        done = min(self.total, self.completed + self.current_done)
        speed = (self.transferred + max(0, self.current_done - getattr(self, "resume_offset", 0))) / elapsed
        remaining = max(0, self.total - done) / speed if speed else None
        self.file_bar.setRange(0, 1000)
        self.file_bar.setValue(min(1000, int(self.current_done * 1000 / self.current_size)) if self.current_size else 0)
        if kind == 'file_done':
            self.file_bar.setValue(1000)
        self.file_bar.setFormat(tr('Current file') + f' {size_text(self.current_size if kind == "file_done" else self.current_done)} / {size_text(self.current_size)} · %p%')
        self.total_bar.setRange(0, 1000)
        self.total_bar.setValue(int(done * 1000 / self.total) if self.total else (1000 if self.done_files == self.files else 0))
        self.total_bar.setFormat(tr('Overall') + ' %p%')
        self.file_label.setText(self.file_bar.text())
        self.total_label.setText(self.total_bar.text())
        self.statistics.setText(tr('{v0} / {v1} · {v2} / {v3} files · {v4}/s · Elapsed {v5}s · Remaining {v6}').format(v0=size_text(done), v1=size_text(self.total), v2=self.done_files, v3=self.files, v4=size_text(speed), v5=int(elapsed), v6=f'{int(remaining)}s' if remaining is not None else '—'))
        if line:
            self.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + line)
        return line

    def finish(self, message, failed):
        self.phase.setText(message)
        self.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + message)
        self.cancel_button.setText(tr('Close'))
        self.cancel_button.clicked.disconnect(self.cancel_event.set)
        self.cancel_button.clicked.connect(self.close)
        if failed:
            self.show()
        else:
            self.total_bar.setRange(0, 1000)
            self.total_bar.setValue(1000)
            self.total_label.setText(self.total_bar.text())
