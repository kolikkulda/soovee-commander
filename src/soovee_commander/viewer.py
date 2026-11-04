"""Integrated F3 viewer: searchable text, bounded hex pages and image zoom."""
import math
from pathlib import Path

from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImageReader, QKeySequence, QPixmap, QShortcut, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QInputDialog,
                              QLabel, QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .filemodel import size_text
from .i18n import tr
from .text_widgets import CodeEditor, ENCODINGS, SearchBar, SyntaxHighlighter, decode_text
from .themes import THEMES

VIEW_LIMIT = 16 * 1024 * 1024
HEX_PAGE = 16 * 1024


class FileViewer(QDialog):
    def __init__(self, host, name, size, data):
        super().__init__(host)
        # Text and hex views stay bounded; whole-file previews may receive more.
        full, data = data, data[:VIEW_LIMIT]
        self.host, self.data = host, data
        self.partial = len(data) < size
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr('Preview · {v0}').format(v0=name))
        self.resize(1080, 760)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        heading = QLabel(name)
        heading.setObjectName('dialogHeading')
        heading.setProperty('userContent', True)
        heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(heading, 1)
        close = QPushButton(tr('Close')); close.clicked.connect(self.close); header.addWidget(close)
        layout.addLayout(header)
        self.note = QLabel(tr('{v0} loaded / {v1} total').format(v0=size_text(len(data)), v1=size_text(size)))
        layout.addWidget(self.note)
        if len(data) < size:
            warning = QLabel(tr('Partial preview. Only the loaded portion is available for browsing and searching.'))
            warning.setWordWrap(True)
            layout.addWidget(warning)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        colors = THEMES[host.theme_key]
        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        tools = QHBoxLayout()
        self.encoding = QComboBox()
        self.encoding.setProperty('translatedItems', True)
        self.encoding.addItem(tr('Automatic (Unicode)'), None)
        for label, codec in ENCODINGS:
            self.encoding.addItem(label, codec)
        tools.addWidget(self.encoding)
        self.text = CodeEditor(colors)
        self.text.setReadOnly(True)
        self.highlighter = SyntaxHighlighter(self.text.document(), name, colors)
        self.search = SearchBar(self.text, writable=False)
        for label, callback in [('Find…', lambda: self.search.open()), ('Go to line…', self.go_to_line),
                                ('Zoom in', lambda: self.text.zoom(1)), ('Zoom out', lambda: self.text.zoom(-1))]:
            button = QPushButton(tr(label)); button.clicked.connect(callback); tools.addWidget(button)
        wrap = QCheckBox(tr('Word wrap'))
        wrap.toggled.connect(lambda on: self.text.setLineWrapMode(CodeEditor.LineWrapMode.WidgetWidth if on else CodeEditor.LineWrapMode.NoWrap))
        tools.addWidget(wrap)
        tools.addStretch()
        text_layout.addLayout(tools)
        self.decode_note = QLabel()
        text_layout.addWidget(self.decode_note)
        text_layout.addWidget(self.search)
        text_layout.addWidget(self.text, 1)
        self.tabs.addTab(text_page, tr('Text'))
        self.encoding.currentIndexChanged.connect(self.decode)
        is_text = self.decode()
        hex_page = QWidget()
        hex_layout = QVBoxLayout(hex_page)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(tr('Hex page')))
        self.hex_page = QSpinBox()
        self.hex_page.setRange(1, max(1, math.ceil(len(data) / HEX_PAGE)))
        self.hex_page.setSuffix(' / ' + str(self.hex_page.maximum()))
        self.hex_page.valueChanged.connect(self.show_hex)
        controls.addWidget(self.hex_page)
        controls.addStretch()
        hex_layout.addLayout(controls)
        self.hex = CodeEditor(colors)
        self.hex.setReadOnly(True)
        hex_layout.addWidget(self.hex)
        self.tabs.addTab(hex_page, tr('Hex / ASCII'))
        self.show_hex()
        if not is_text:
            self.tabs.setCurrentIndex(1)
        self.image = None
        if Path(name).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff') and len(full) >= size:
            buffer = QBuffer()
            buffer.setData(QByteArray(full)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            QImageReader.setAllocationLimit(64)
            reader = QImageReader(buffer)
            reader.setAutoTransform(True)
            dimensions = reader.size()
            if dimensions.isValid() and dimensions.width() * dimensions.height() <= 16_000_000:
                image = reader.read()
                if not image.isNull():
                    self.image = QPixmap.fromImage(image)
                    self.add_image_page()
        self.document = None
        self.add_document_page(name, full, len(full) >= size)
        self.shortcuts = []
        self.install_controls()
        host.commands.changed.connect(self.install_controls)

    def decode(self, *args):
        try:
            # A bounded UTF-8/UTF-16 prefix can end midway through a character.
            # Trim at most three trailing bytes only for a partial sequence.
            data = self.data
            for trim in range(4):
                try:
                    text, _, _, _ = decode_text(data[:len(data) - trim] if trim else data, self.encoding.currentData())
                    break
                except UnicodeDecodeError as exc:
                    if not self.partial or exc.reason not in ('unexpected end of data', 'truncated data') or trim == 3:
                        raise
            self.text.setPlainText(text)
            self.decode_note.setText('')
            return True
        except (ValueError, UnicodeError):
            self.text.clear()
            self.decode_note.setText(tr('Cannot decode as text. Select an encoding or use Hex / ASCII.'))
            return False

    def show_hex(self, *args):
        start = (self.hex_page.value() - 1) * HEX_PAGE
        stop = min(len(self.data), start + HEX_PAGE)
        lines = []
        for position in range(start, stop, 16):
            block = self.data[position:position + 16]
            hex_bytes = ' '.join(f'{byte:02X}' for byte in block)
            ascii_text = ''.join(chr(byte) if 32 <= byte < 127 else '.' for byte in block)
            lines.append(f'{position:08X}  {hex_bytes:<47}  {ascii_text}')
        self.hex.setPlainText('\n'.join(lines))

    def add_document_page(self, name, data, complete):
        """Formatted preview (PDF, Markdown, tables, Office text…) as its own tab."""
        from . import document_preview
        if document_preview.enabled_group(name, self.host.settings) in (None, "images"):
            return  # Pictures keep the dedicated Image tab.
        try:
            widget = document_preview.build(name, data, complete, settings=self.host.settings)
        except document_preview.PreviewError as exc:
            widget = document_preview.message(str(exc))
        if widget is None:
            return
        page = QWidget()
        layout = QVBoxLayout(page)
        caption = QLabel(getattr(widget, 'caption', ''))
        caption.setObjectName('muted')
        layout.addWidget(caption)
        layout.addWidget(widget, 1)
        self.document = widget
        self.tabs.addTab(page, tr('Preview'))
        self.tabs.setCurrentWidget(page)

    def add_image_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.scale = 1.0
        self.fit_image = True
        for label, callback in [('Fit image', self.fit), ('Actual size', lambda: self.image_zoom(1.0)),
                                ('Zoom in', lambda: self.image_zoom(self.scale * 1.25)),
                                ('Zoom out', lambda: self.image_zoom(self.scale / 1.25))]:
            button = QPushButton(tr(label)); button.clicked.connect(callback); row.addWidget(button)
        self.dimensions = QLabel(f'{self.image.width()} × {self.image.height()} px')
        row.addWidget(self.dimensions, 1)
        layout.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label = QLabel()
        self.scroll.setWidget(self.image_label)
        layout.addWidget(self.scroll)
        self.tabs.addTab(page, tr('Image'))
        self.tabs.setCurrentIndex(2)
        self.fit()

    def fit(self):
        self.fit_image = True
        available = self.scroll.viewport().size()
        self.render_image(min(1.0, available.width() / self.image.width(), available.height() / self.image.height()))

    def image_zoom(self, scale):
        self.fit_image = False
        self.render_image(scale)

    def render_image(self, scale):
        # Bound scaled bitmap allocations; scrolling handles the original size.
        max_scale = min(4.0, math.sqrt(16_000_000 / (self.image.width() * self.image.height())))
        self.scale = max(.05, min(max_scale, scale))
        self.image_label.setPixmap(self.image.scaled(max(1, round(self.image.width() * self.scale)), max(1, round(self.image.height() * self.scale)),
                                                   Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.image_label.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, 'image', None) is not None and self.fit_image:
            self.fit()

    def go_to_line(self):
        editor = self.hex if self.tabs.currentIndex() == 1 else self.text
        number, ok = QInputDialog.getInt(self, tr('Go to line…'), tr('Line number'),
                                        editor.textCursor().blockNumber() + 1, 1, editor.blockCount())
        if ok:
            editor.setTextCursor(QTextCursor(editor.document().findBlockByNumber(number - 1)))
            editor.ensureCursorVisible()

    def close_command(self):
        if self.search.isVisible():
            self.search.hide()
        else:
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.accept()  # The configured close command owns Escape.
            return
        super().keyPressEvent(event)

    def install_controls(self):
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False); shortcut.deleteLater()
        self.shortcuts.clear()
        callbacks = dict(editor_close=self.close_command, editor_find=lambda: self.find_text(),
                         editor_find_next=lambda: self.search.find(), editor_find_previous=lambda: self.search.find(True),
                         editor_goto=self.go_to_line, editor_zoom_in=lambda: self.zoom(1), editor_zoom_out=lambda: self.zoom(-1))
        for command, callback in callbacks.items():
            for key in self.host.commands.config['keys'].get(command, []):
                shortcut = QShortcut(QKeySequence.fromString(key, QKeySequence.SequenceFormat.PortableText), self)
                shortcut.activated.connect(callback); self.shortcuts.append(shortcut)

    def find_text(self):
        self.tabs.setCurrentIndex(0)
        self.search.open()

    def zoom(self, steps):
        if self.tabs.currentIndex() == 2 and self.image is not None:
            self.image_zoom(self.scale * (1.25 ** steps))
        else:
            (self.hex if self.tabs.currentIndex() == 1 else self.text).zoom(steps)
