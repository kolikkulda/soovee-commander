"""Shared integrated text tools: lossless decoding, gutter, highlighting and search."""
import codecs
import re
from pathlib import Path

from PySide6.QtCore import Qt, QRegularExpression, QRect, QSize
from PySide6.QtGui import (QColor, QFontDatabase, QPainter, QSyntaxHighlighter,
                          QTextCharFormat, QTextCursor, QTextDocument, QTextFormat)
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                              QPushButton, QTextEdit, QVBoxLayout, QWidget)

from .i18n import tr

ENCODINGS = [('UTF-8', 'utf-8'), ('UTF-8 BOM', 'utf-8-sig'),
             ('UTF-16 LE BOM', 'utf-16-le-bom'), ('UTF-16 BE BOM', 'utf-16-be-bom'),
             ('Windows-1250', 'cp1250'), ('Windows-1252', 'cp1252'), ('ISO-8859-2', 'iso8859-2')]


def decode_text(data, encoding=None):
    if encoding is None:
        encoding = ('utf-8-sig' if data.startswith(codecs.BOM_UTF8) else
                    'utf-16-le-bom' if data.startswith(codecs.BOM_UTF16_LE) else
                    'utf-16-be-bom' if data.startswith(codecs.BOM_UTF16_BE) else 'utf-8')
    if encoding.endswith('-bom'):
        codec = encoding[:-4]
        bom = codecs.BOM_UTF16_LE if codec == 'utf-16-le' else codecs.BOM_UTF16_BE
        text = (data[len(bom):] if data.startswith(bom) else data).decode(codec)
    else:
        text = data.decode(encoding)
    if '\0' in text or any(ord(c) < 9 or 13 < ord(c) < 32 for c in text[:8192]):
        raise ValueError(tr('Binary files cannot be edited with the text editor.'))
    endings = set(re.findall(r'\r\n|\r|\n', text))
    newline = next(iter(endings)) if len(endings) == 1 else '\n'
    return text.replace('\r\n', '\n').replace('\r', '\n'), encoding, newline, len(endings) > 1


def encode_text(text, encoding, newline):
    text = text.replace('\n', newline)
    if encoding.endswith('-bom'):
        codec = encoding[:-4]
        return (codecs.BOM_UTF16_LE if codec == 'utf-16-le' else codecs.BOM_UTF16_BE) + text.encode(codec)
    return text.encode(encoding)


class Gutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        editor = self.editor
        painter = QPainter(self)
        painter.setFont(editor.font())
        painter.fillRect(event.rect(), QColor(editor.colors['header']))
        painter.setPen(QColor(editor.colors['muted']))
        block = editor.firstVisibleBlock()
        top = round(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(editor.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.drawText(0, top, self.width() - 9, editor.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            top += height
            block = block.next()


class CodeEditor(QPlainTextEdit):
    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.font_pixels = 12
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.gutter = Gutter(self)
        self.blockCountChanged.connect(self.update_gutter)
        self.updateRequest.connect(self.scroll_gutter)
        self.cursorPositionChanged.connect(self.highlight_line)
        self.update_gutter()

    def gutter_width(self):
        return 18 + self.fontMetrics().horizontalAdvance('9') * len(str(max(1, self.blockCount())))

    def update_gutter(self, *args):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        self.layout_gutter()

    def layout_gutter(self):
        rect = self.contentsRect()
        self.gutter.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))
        self.gutter.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_gutter()

    def scroll_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_gutter()

    def highlight_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(self.colors['alternate']))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def zoom(self, steps):
        self.font_pixels = max(9, min(40, self.font_pixels + steps * 2))
        # The application uses pixel-sized stylesheet fonts. Qt's point-based
        # zoomIn otherwise has no effect (pointSizeF is -1 for these fonts).
        self.setStyleSheet(f'QPlainTextEdit {{ font-size: {self.font_pixels}px; }}')
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.update_gutter()

    def set_colors(self, colors):
        self.colors = colors
        self.gutter.update()
        self.highlight_line()

    def keyPressEvent(self, event):
        if not self.isReadOnly():
            cursor = self.textCursor()
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                start, end = cursor.selectionStart(), cursor.selectionEnd()
                if start != end:
                    first = self.document().findBlock(start)
                    last = self.document().findBlock(max(start, end - 1))
                    blocks = []
                    while first.isValid() and first.blockNumber() <= last.blockNumber():
                        blocks.append(first)
                        first = first.next()
                    cursor.beginEditBlock()
                    for block in reversed(blocks):
                        edit = QTextCursor(block)
                        if event.key() == Qt.Key.Key_Backtab:
                            whitespace = re.match(r'^(?: {1,4}|\t)', block.text())
                            if whitespace:
                                edit.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(whitespace.group()))
                                edit.removeSelectedText()
                        else:
                            edit.insertText('    ')
                    cursor.endEditBlock()
                elif event.key() == Qt.Key.Key_Tab:
                    cursor.insertText(' ' * (4 - cursor.positionInBlock() % 4))
                else:
                    edit = QTextCursor(cursor.block())
                    whitespace = re.match(r'^(?: {1,4}|\t)', cursor.block().text())
                    if whitespace:
                        edit.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(whitespace.group()))
                        edit.removeSelectedText()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() == Qt.KeyboardModifier.NoModifier:
                prefix = cursor.block().text()[:cursor.positionInBlock()]
                indent = re.match(r'[ \t]*', prefix).group()
                if prefix.rstrip().endswith((':', '{')):
                    indent += '    '
                cursor.insertText('\n' + indent)
                return
        super().keyPressEvent(event)


class SyntaxHighlighter(QSyntaxHighlighter):
    """Small built-in lexical highlighter; does not parse or execute documents."""
    def __init__(self, document, path, colors):
        super().__init__(document)
        self.configure(path, colors)

    def configure(self, path, colors):
        self.path = path
        self.language = Path(path).suffix.lower()
        dark = QColor(colors['input']).lightness() < 128
        self.rules = []
        def rule(pattern, color):
            format = QTextCharFormat()
            format.setForeground(QColor(color))
            self.rules.append((re.compile(pattern), format))
        if self.language not in ('.py', '.pyw', '.js', '.ts', '.jsx', '.tsx', '.json', '.c', '.h', '.cpp', '.cs', '.java', '.go', '.rs', '.sh', '.yaml', '.yml', '.toml', '.ini', '.xml', '.html', '.css', '.sql'):
            self.rehighlight()
            return
        rule(r'\b(?:def|class|return|if|else|elif|for|while|in|import|from|as|try|except|finally|with|async|await|function|const|let|var|new|public|private|void|int|bool|true|false|null|None|True|False|SELECT|FROM|WHERE)\b', '#c49aff' if dark else '#6830a4')
        rule(r'\b\d+(?:\.\d+)?\b', '#ffcf78' if dark else '#905300')
        rule(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '#72ddbb' if dark else '#157052')
        rule(r'#[^\n]*' if self.language in ('.py', '.pyw', '.sh', '.yaml', '.yml', '.toml', '.ini') else r'//[^\n]*|<!--[\s\S]*?-->', '#8a9db4' if dark else '#64748b')
        self.rehighlight()

    def highlightBlock(self, text):
        # Bound work for minified single-line files. Qt uses UTF-16 offsets.
        text = text[:8192]
        for pattern, format in self.rules:
            for match in pattern.finditer(text):
                start = len(text[:match.start()].encode('utf-16-le')) // 2
                length = len(match.group().encode('utf-16-le')) // 2
                self.setFormat(start, length, format)


class SearchBar(QWidget):
    def __init__(self, editor, writable=True):
        super().__init__()
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr('Find text…'))
        self.case = QCheckBox(tr('Match case'))
        self.words = QCheckBox(tr('Whole words'))
        self.regex = QCheckBox(tr('Regular expression'))
        row.addWidget(self.query, 1)
        for label, callback in [('Previous', lambda: self.find(True)), ('Next', self.find)]:
            button = QPushButton(tr(label)); button.clicked.connect(lambda checked=False, cb=callback: cb()); row.addWidget(button)
        for checkbox in (self.case, self.words, self.regex):
            row.addWidget(checkbox)
        close = QPushButton(tr('Hide'))
        close.clicked.connect(self.hide)
        row.addWidget(close)
        layout.addLayout(row)
        self.replace_row = QWidget()
        replace_layout = QHBoxLayout(self.replace_row)
        replace_layout.setContentsMargins(0, 0, 0, 0)
        self.replacement = QLineEdit()
        self.replacement.setPlaceholderText(tr('Replacement text (literal)'))
        replace_layout.addWidget(self.replacement, 1)
        for label, callback in [('Replace', self.replace_one), ('Replace all', self.replace_all)]:
            button = QPushButton(tr(label)); button.clicked.connect(callback); replace_layout.addWidget(button)
        layout.addWidget(self.replace_row)
        self.replace_row.setVisible(writable)
        self.message = QLabel()
        layout.addWidget(self.message)
        self.query.returnPressed.connect(self.find)
        self.hide()

    def open(self, replace=False):
        self.show()
        self.replace_row.setVisible(replace and not self.editor.isReadOnly())
        self.query.setFocus()
        self.query.selectAll()

    def expression(self):
        query = self.query.text()
        if not query:
            return None
        pattern = query if self.regex.isChecked() else QRegularExpression.escape(query)
        if self.words.isChecked():
            pattern = r'\b(?:' + pattern + r')\b'
        expression = QRegularExpression(pattern)
        options = QRegularExpression.PatternOption.UseUnicodePropertiesOption
        if not self.case.isChecked():
            options |= QRegularExpression.PatternOption.CaseInsensitiveOption
        expression.setPatternOptions(options)
        if not expression.isValid():
            self.message.setText(tr('Invalid regular expression: {v0}').format(v0=expression.errorString()))
            return None
        # Zero-width replacements are deliberately not offered: no infinite loops.
        if expression.match('').hasMatch():
            self.message.setText(tr('The search expression must match at least one character.'))
            return None
        return expression

    def flags(self, backwards=False):
        flags = QTextDocument.FindFlag.FindBackward if backwards else QTextDocument.FindFlag(0)
        if self.case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def find(self, backwards=False):
        expression = self.expression()
        if expression is None:
            return False
        flags = self.flags(backwards)
        found = self.editor.document().find(expression, self.editor.textCursor(), flags)
        wrapped = found.isNull()
        if wrapped:
            start = QTextCursor(self.editor.document())
            start.movePosition(QTextCursor.MoveOperation.End if backwards else QTextCursor.MoveOperation.Start)
            found = self.editor.document().find(expression, start, flags)
        if found.isNull() or not found.hasSelection():
            self.message.setText(tr('No match'))
            return False
        self.editor.setTextCursor(found)
        self.editor.ensureCursorVisible()
        self.message.setText(tr('Search wrapped') if wrapped else '')
        return True

    def replace_one(self):
        if self.editor.isReadOnly():
            return
        expression = self.expression()
        if expression is None:
            return
        cursor = self.editor.textCursor()
        match = self.editor.document().find(expression, cursor.selectionStart(), self.flags())
        if not cursor.hasSelection() or match.isNull() or match.selectionStart() != cursor.selectionStart() or match.selectionEnd() != cursor.selectionEnd():
            if not self.find():
                return
            cursor = self.editor.textCursor()
        cursor.insertText(self.replacement.text())
        self.editor.setTextCursor(cursor)
        self.find()

    def replace_all(self):
        if self.editor.isReadOnly():
            return
        expression = self.expression()
        if expression is None:
            return
        document = self.editor.document()
        matches = []
        cursor = QTextCursor(document)
        while True:
            found = document.find(expression, cursor, self.flags())
            if found.isNull():
                break
            if not found.hasSelection() or len(matches) >= 100000:
                self.message.setText(tr('Too many or zero-width matches. Narrow the search.'))
                return
            matches.append((found.selectionStart(), found.selectionEnd()))
            cursor = found
        cursor.beginEditBlock()
        for start, end in reversed(matches):
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(self.replacement.text())
        cursor.endEditBlock()
        self.message.setText(tr('Replaced {v0} matches').format(v0=len(matches)))
