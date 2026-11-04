"""Integrated text editor with explicit encodings and guarded asynchronous saving."""
from .i18n import tr
import io
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                              QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from .operations import preview
from .providers import LocalProvider
from .themes import THEMES
from .text_widgets import CodeEditor, ENCODINGS, SearchBar, SyntaxHighlighter, decode_text, encode_text

EDITOR_LIMIT = 16 * 1024 * 1024


class TextEditor(QDialog):
    def __init__(self, host, provider, path, data, encoding=None):
        text, encoding, newline, mixed_endings = decode_text(data, encoding)
        super().__init__(host)
        self.mixed_endings = mixed_endings
        self.host, self.provider, self.path = host, provider, path
        self.expected = data
        self.saving = False
        self.close_after_save = False
        self.encoding, self.newline = encoding, newline
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1080, 760)
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setObjectName('dialogHeading')
        self.heading.setProperty('userContent', True)
        heading.addWidget(self.heading, 1)
        self.save_button = QPushButton(tr('Save'))
        self.save_button.setObjectName('primary')
        self.save_button.clicked.connect(self.save)
        heading.addWidget(self.save_button)
        self.save_as_button = QPushButton(tr('Save as…'))
        self.save_as_button.clicked.connect(self.save_as)
        heading.addWidget(self.save_as_button)
        layout.addLayout(heading)
        self.note = QLabel()
        self.note.setProperty('userContent', True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note.setWordWrap(True)
        self.note.setObjectName('muted')
        layout.addWidget(self.note)
        self.text = CodeEditor(THEMES[host.theme_key])
        self.text.setPlainText(text)
        self.highlighter = SyntaxHighlighter(self.text.document(), path, THEMES[host.theme_key])
        self.search = SearchBar(self.text)
        toolbar = QHBoxLayout()
        self.tool_buttons = {}
        for command, label, callback in [
            ('editor_undo', 'Undo', self.text.undo), ('editor_redo', 'Redo', self.text.redo),
            ('editor_find', 'Find…', lambda: self.search.open()),
            ('editor_replace', 'Replace…', lambda: self.search.open(True)),
            ('editor_goto', 'Go to line…', self.go_to_line),
            ('editor_zoom_in', 'Zoom in', lambda: self.text.zoom(1)),
            ('editor_zoom_out', 'Zoom out', lambda: self.text.zoom(-1)),
        ]:
            button = QPushButton(tr(label)); button.clicked.connect(callback)
            toolbar.addWidget(button)
            self.tool_buttons[command] = button
        self.wrap = QCheckBox(tr('Word wrap'))
        self.wrap.toggled.connect(lambda on: self.text.setLineWrapMode(CodeEditor.LineWrapMode.WidgetWidth if on else CodeEditor.LineWrapMode.NoWrap))
        toolbar.addWidget(self.wrap)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        layout.addWidget(self.search)
        layout.addWidget(self.text, 1)
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel(tr('Save encoding')))
        self.encoding_combo = QComboBox()
        for label, codec in ENCODINGS:
            self.encoding_combo.addItem(label, codec)
        self.encoding_combo.setCurrentIndex(self.encoding_combo.findData(encoding))
        self.encoding_combo.currentIndexChanged.connect(self.change_format)
        format_row.addWidget(self.encoding_combo)
        format_row.addWidget(QLabel(tr('Line endings')))
        self.endings_combo = QComboBox()
        for label, value in [('LF', '\n'), ('CRLF', '\r\n'), ('CR', '\r')]:
            self.endings_combo.addItem(label, value)
        self.endings_combo.setCurrentIndex(self.endings_combo.findData(newline))
        self.endings_combo.currentIndexChanged.connect(self.change_format)
        format_row.addWidget(self.endings_combo)
        self.position = QLabel()
        format_row.addWidget(self.position, 1)
        self.status = QLabel(tr('Mixed line endings: choose the output format before saving.') if self.mixed_endings else tr('Ready'))
        self.status.setWordWrap(True)
        format_row.addWidget(self.status)
        self.close_button = QPushButton(tr('Close'))
        self.close_button.clicked.connect(self.close)
        format_row.addWidget(self.close_button)
        layout.addLayout(format_row)
        self.text.cursorPositionChanged.connect(self.update_position)
        self.text.document().modificationChanged.connect(self.update_title)
        self.control_shortcuts = []
        self.install_controls()
        host.commands.changed.connect(self.install_controls)
        self.text.document().setModified(False)
        self.update_title()
        self.update_position()
        self.text.setFocus()

    @property
    def crlf(self):
        return self.newline == '\r\n'

    @property
    def bom(self):
        return self.encoding == 'utf-8-sig'

    def update_title(self, *args):
        modified = self.text.document().isModified()
        name = Path(self.path).name
        self.setWindowTitle(tr('Edit · {v0}').format(v0=name) + (' *' if modified else ''))
        self.heading.setText(name + (' *' if modified else ''))
        self.note.setText(tr(self.provider.label) + ' · ' + self.path)
        self.save_button.setEnabled(not self.saving and getattr(self.provider, 'supports_overwrite', True))

    def update_position(self):
        cursor = self.text.textCursor()
        self.position.setText(tr('Line {v0}, column {v1} · {v2} lines').format(
            v0=cursor.blockNumber() + 1, v1=cursor.positionInBlock() + 1, v2=self.text.blockCount()))

    def change_format(self, *args):
        self.encoding = self.encoding_combo.currentData()
        self.newline = self.endings_combo.currentData()
        self.text.document().setModified(True)

    def go_to_line(self):
        number, ok = QInputDialog.getInt(self, tr('Go to line…'), tr('Line number'),
                                        self.text.textCursor().blockNumber() + 1, 1, self.text.blockCount())
        if ok:
            self.text.setTextCursor(QTextCursor(self.text.document().findBlockByNumber(number - 1)))
            self.text.ensureCursorVisible()
            self.text.setFocus()

    def install_controls(self):
        for shortcut in self.control_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.control_shortcuts.clear()
        callbacks = dict(editor_save=self.save, editor_save_as=self.save_as, editor_close=self.close_command,
                         editor_find=lambda: self.search.open(), editor_replace=lambda: self.search.open(True),
                         editor_find_next=lambda: self.search.find(), editor_find_previous=lambda: self.search.find(True),
                         editor_goto=self.go_to_line, editor_undo=self.text.undo, editor_redo=self.text.redo,
                         editor_zoom_in=lambda: self.text.zoom(1), editor_zoom_out=lambda: self.text.zoom(-1))
        for command, callback in callbacks.items():
            for key in self.host.commands.config['keys'].get(command, []):
                shortcut = QShortcut(QKeySequence.fromString(key, QKeySequence.SequenceFormat.PortableText), self)
                shortcut.activated.connect(callback)
                self.control_shortcuts.append(shortcut)
            button = self.tool_buttons.get(command)
            if button is not None:
                button.setToolTip(self.host.commands.key_label(command))
        key = self.host.commands.key_label('editor_save')
        self.save_button.setText(tr('Save') + ('  ·  ' + key if key else ''))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.search.isVisible():
                self.search.hide()
                self.text.setFocus()
            event.accept()
            return
        super().keyPressEvent(event)

    def close_command(self):
        if self.search.isVisible():
            self.search.hide()
            self.text.setFocus()
        else:
            self.close()

    def save(self):
        if self.saving or not self.text.document().isModified():
            return
        if not getattr(self.provider, 'supports_overwrite', True):
            return self.save_as()
        self.write(self.provider, self.path, self.expected)

    def save_as(self):
        if self.saving:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Save as…'), str(Path.home() / Path(self.path).name), tr('All files (*)'))
        if not path:
            return
        if isinstance(self.provider, LocalProvider) and os.path.abspath(path) == os.path.abspath(self.path):
            return self.save()
        destination = Path(path)
        if destination.is_symlink():
            return self.host.error(tr('Saving over a symbolic link is not allowed.'))
        try:
            if destination.exists() and destination.stat().st_size > EDITOR_LIMIT:
                raise ValueError(tr('The destination is too large to verify safely. Choose another filename.'))
            expected = destination.read_bytes() if destination.exists() else None
            self.write(LocalProvider(), str(destination), expected)
        except (OSError, ValueError) as exc:
            self.host.error(str(exc))

    def write(self, provider, path, expected):
        try:
            data = encode_text(self.text.toPlainText(), self.encoding, self.newline)
        except UnicodeError as exc:
            return self.host.error(tr('The selected encoding cannot represent this text. Choose UTF-8 or UTF-16.'))
        if len(data) > EDITOR_LIMIT:
            return self.host.error(tr('The editor supports files up to 16 MB.'))
        if self.mixed_endings and QMessageBox.question(self, tr('Mixed line endings'),
                tr('Saving will normalize mixed line endings to the selected format. Continue?'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.saving = True
        self.text.setReadOnly(True)
        for widget in (self.save_button, self.save_as_button, self.encoding_combo, self.endings_combo):
            widget.setEnabled(False)
        self.status.setText(tr('Saving…'))

        def work(report):
            with provider.batch():
                exists = provider.exists(path)
                if expected is None:
                    if exists:
                        raise FileExistsError(tr('The destination was created by another application. Choose another filename.'))
                elif not exists or preview(provider, path, limit=EDITOR_LIMIT + 1) != expected:
                    raise IOError(tr('The file has changed since it was opened. Saving was stopped to avoid overwriting external changes.'))
                if isinstance(provider, LocalProvider):
                    provider.write_with(path, lambda output: output.write(data), lambda count: None,
                                        metadata_path=path if exists else None, overwrite=exists)
                    os.utime(path, None)
                else:
                    provider.write_from(path, io.BytesIO(data), lambda count: None, overwrite=exists)

        def finish(error=None):
            self.saving = False
            self.text.setReadOnly(False)
            for widget in (self.save_as_button, self.encoding_combo, self.endings_combo):
                widget.setEnabled(True)
            if error:
                self.close_after_save = False
                self.status.setText(tr('Not saved'))
                self.host.error(error)
            else:
                self.provider, self.path, self.expected = provider, path, data
                self.highlighter.configure(path, THEMES[self.host.theme_key])
                self.mixed_endings = False
                self.text.document().setModified(False)
                self.status.setText(tr('Saved'))
                self.host.left.refresh()
                self.host.right.refresh()
            self.update_title()
            if self.close_after_save:
                self.close_after_save = False
                self.close()
        self.host.run_task(work, lambda _: finish(), finish)

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self.saving:
            event.ignore()
            return
        if self.text.document().isModified():
            answer = QMessageBox.question(self, tr('Unsaved changes'), tr('Save changes before closing?'),
                                           QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                           QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Save:
                self.close_after_save = True
                self.save()
                if not self.saving:
                    self.close_after_save = False
                event.ignore()
                return
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        event.accept()
