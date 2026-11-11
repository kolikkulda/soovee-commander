"""Shared building blocks so every dialog looks and behaves the same.

Layout: an icon and heading with a one-line explanation at the top, the
content in the middle and the buttons at the bottom right in the platform
order. The main action names what it does ("Copy", "Delete") instead of
"OK"; destructive actions are red and never the default for Enter.

App code calls these through the module (dialog_kit.confirm(...)) so tests
can replace the interactive parts.
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QSizePolicy, QVBoxLayout)

from .i18n import tr

MAX_LISTED = 8


class StandardDialog(QDialog):
    """Heading + explanation, a body layout and OK/Cancel with a named main action."""

    def __init__(self, parent, title, heading=None, subtitle=None, icon=None, action=None, destructive=False, width=500, close_only=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(14)
        if icon:
            badge = QLabel()
            badge.setObjectName("dialogIcon")
            badge.setPixmap(self.icon_pixmap(icon).pixmap(QSize(30, 30)))
            badge.setFixedSize(42, 42)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.heading = QLabel(heading or title)
        self.heading.setObjectName("dialogHeading")
        self.heading.setWordWrap(True)
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        texts.addWidget(self.heading)
        self.subtitle = QLabel(subtitle or "")
        self.subtitle.setObjectName("dialogSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        self.subtitle.setProperty('userContent', True)
        self.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle.setVisible(bool(subtitle))
        texts.addWidget(self.subtitle)
        header.addLayout(texts, 1)
        root.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        root.addLayout(self.body, 1)
        self.body_stretch = False
        line = QFrame()
        line.setObjectName("dialogSeparator")
        line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)
        if close_only:  # Information windows: one Close button, Escape closes too.
            self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            self.buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr('Close'))
            self.buttons.rejected.connect(self.reject)
            root.addWidget(self.buttons)
            self.ok = self.cancel = None
            return
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel.setText(tr('Cancel'))
        self.ok.setText(action or tr('OK'))
        self.ok.setObjectName("danger" if destructive else "primary")
        # Enter confirms the main action (as in Total Commander); Escape cancels.
        self.cancel.setAutoDefault(False)
        self.ok.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def icon_pixmap(self, command):
        from .toolbar_icons import toolbar_icon
        from .themes import THEMES
        host = self.parent()
        while host is not None and not hasattr(host, 'theme_key'):
            host = host.parent()
        return toolbar_icon(command, THEMES[getattr(host, 'theme_key', 'soovee')]["accent"])

    def add(self, widget, stretch=0):
        self.body.addWidget(widget, stretch)
        self.body_stretch = self.body_stretch or stretch > 0
        return widget

    def exec(self):
        # Fit the content; extra height goes below it instead of between rows.
        if not self.body_stretch:
            self.body.addStretch(1)
        self.adjustSize()
        return super().exec()

    def note(self, text):
        label = QLabel(text)
        label.setObjectName("muted")
        label.setWordWrap(True)
        return self.add(label)


def item_list(names, total=None):
    """Up to MAX_LISTED names and how many more, so long selections stay readable."""
    widget = QListWidget()
    widget.setObjectName("dialogItems")
    widget.setProperty('userContent', True)
    names = list(names)
    for name in names[:MAX_LISTED]:
        widget.addItem(name)
    remaining = (total if total is not None else len(names)) - min(len(names), MAX_LISTED)
    if remaining > 0:
        widget.addItem(tr('… and {v0} more').format(v0=remaining))
    row = max(16, widget.sizeHintForRow(0))
    widget.setFixedHeight(min(MAX_LISTED + 1, widget.count()) * row + 2 * widget.frameWidth() + 8)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
    return widget


def confirm(parent, title, heading, message="", *, items=None, action=None, destructive=False, icon=None, note=None):
    """Ask before an operation; returns True only when the user chose the named action."""
    dialog = StandardDialog(parent, title, heading, message, icon=icon, action=action, destructive=destructive)
    if items:
        dialog.add(item_list(items))
    if note:
        dialog.note(note)
    return dialog.exec() == QDialog.DialogCode.Accepted


def ask_text(parent, title, heading, label, text="", *, subtitle=None, action=None, icon=None, select_stem=False,
             password=False, allow_empty=False, setup=None):
    """One-line input with the same layout as other dialogs; None when cancelled."""
    dialog = StandardDialog(parent, title, heading, subtitle, icon=icon, action=action)
    caption = QLabel(label)
    dialog.add(caption)
    edit = QLineEdit(text)
    edit.setProperty('userContent', True)
    if password:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    caption.setBuddy(edit)
    dialog.add(edit)
    if not allow_empty:
        dialog.ok.setEnabled(bool(text.strip()))
        edit.textChanged.connect(lambda value: dialog.ok.setEnabled(bool(value.strip())))
    edit.setFocus()
    if select_stem and "." in text.strip("."):
        edit.setSelection(0, text.rfind("."))
    else:
        edit.selectAll()
    dialog.edit = edit
    if setup is not None:   # extra options below the field (they may change the text)
        setup(dialog, edit)
    edit.returnPressed.connect(lambda: dialog.ok.isEnabled() and dialog.ok.click())
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return edit.text()
