"""Quick view: one panel previews the item under the cursor in the other panel.

Reads are bounded and run on the worker pool; a newer cursor position always
wins over an older read still in flight. Remote files are previewed only up
to a smaller size so moving the cursor never starts large downloads.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from . import document_preview as previews
from .filemodel import date_text, size_text
from .filetypes import kind
from .i18n import tr
from .operations import preview
from .providers import LocalProvider
from .text_widgets import CodeEditor, SyntaxHighlighter, decode_text
from .themes import THEMES

TEXT_LIMIT = 512 * 1024
REMOTE_LIMIT = 8 * 1024 * 1024


class QuickView(QFrame):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setObjectName("quickView")
        self.serial = 0
        self.source = None
        self.shown_key = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("dialogHeading")
        self.title.setProperty("userContent", True)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.caption = QLabel()
        self.caption.setObjectName("muted")
        self.caption.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.caption)
        self.body_layout = layout
        self.body = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.load)
        self.show_message(tr('Quick view'), tr('Move the cursor in the other panel to preview files here.'))

    def set_body(self, widget):
        if self.body is not None:
            self.body_layout.removeWidget(self.body)
            self.body.deleteLater()
        self.body = widget
        self.body_layout.addWidget(widget, 1)

    def show_message(self, title, text, caption=""):
        self.title.setText(title)
        self.caption.setText(caption)
        self.set_body(previews.message(text))

    def request(self, source):
        """Follow source's cursor; the short delay skips items passed while scrolling."""
        self.source = source
        remote = not isinstance(source.provider, LocalProvider)
        self.timer.start(350 if remote else 120)

    def load(self):
        source = self.source
        if source is None:
            return
        entry = source.current_entry()
        provider, folder = source.provider, source.path
        key = (id(provider), folder, entry.name if entry else None, entry.size if entry else None, entry.modified if entry else None)
        if key == self.shown_key:
            return
        self.shown_key = key
        self.serial += 1
        serial = self.serial
        if entry is None:
            return self.show_message(tr('Quick view'), tr('Move the cursor to a file in the other panel.'))
        details = f'{kind(entry.name, entry.is_dir, entry.is_link)[1]} · ' + ('' if entry.is_dir else size_text(entry.size) + ' · ') + date_text(entry.modified)
        if entry.is_dir:
            return self.show_message(entry.name, tr('Folder. Press Enter in the other panel to open it.'), details)
        settings = source.window.settings
        group = previews.enabled_group(entry.name, settings)
        local = isinstance(provider, LocalProvider)
        whole = group in previews.WHOLE_FILE
        limit = previews.PREVIEW_LIMIT if whole else TEXT_LIMIT
        if not local:
            limit = min(limit, REMOTE_LIMIT)
            if whole and entry.size > REMOTE_LIMIT:
                return self.show_message(entry.name, tr('This file is on a server, device or in an archive and is too large for a quick view. Press F3 to load it.'), details)
        self.title.setText(entry.name)
        self.caption.setText(details + ' · ' + tr('Loading…'))
        path = provider.join(folder, entry.name)

        def loaded(data):
            if serial != self.serial:
                return
            try:
                widget = previews.build(entry.name, data, len(data) >= entry.size, settings=settings)
            except previews.PreviewError as exc:
                return self.show_message(entry.name, str(exc), details)
            if widget is None:
                widget = self.text_widget(entry.name, data, len(data) < entry.size)
                if widget is None:
                    return self.show_message(entry.name, tr('No built-in preview for this file type. Press F3 to see it as text or hex.'), details)
            note = getattr(widget, 'caption', '')
            self.caption.setText(details + (' · ' + note if note else ''))
            self.set_body(widget)

        def failed(message):
            if serial == self.serial:
                self.show_message(entry.name, message, details)
        source.window.run_task(lambda _: preview(provider, path, limit), loaded, failed, read_only=True)

    def text_widget(self, name, data, partial):
        if b"\0" in data[:4096]:
            return None
        try:
            text = decode_text(data[:len(data) - 3] if partial else data, None)[0]
        except (ValueError, UnicodeError):
            return None
        colors = THEMES[self.panel.window.theme_key]
        editor = CodeEditor(colors)
        editor.setReadOnly(True)
        editor.setPlainText(text)
        editor.highlighter = SyntaxHighlighter(editor.document(), name, colors)
        editor.caption = tr('Text · first {v0} shown').format(v0=size_text(len(data))) if partial else tr('Text')
        return editor
