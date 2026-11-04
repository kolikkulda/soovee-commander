"""Reviewable command/shortcut and toolbar customization with explicit Apply."""
from .i18n import tr
import json
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                              QHBoxLayout, QHeaderView, QLabel, QKeySequenceEdit, QLineEdit, QListWidget,
                              QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QTableWidget,
                              QTableWidgetItem, QVBoxLayout, QWidget)
from PySide6.QtGui import QKeySequence

from .commands import BY_ID, COMMANDS, defaults, validate_config


class BarEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.currentRowChanged.connect(self.load_row)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.command = QComboBox()
        self.command.setProperty("translatedItems", True)
        for command in COMMANDS:
            if command.scope != "editor":
                self.command.addItem(tr(command.title), command.id)
        self.command.currentIndexChanged.connect(self.update_row)
        self.label = QLineEdit()
        self.label.setPlaceholderText(tr('Custom label (optional)'))
        self.label.setMaxLength(50)
        self.label.textEdited.connect(self.update_row)
        row.addWidget(self.command, 1)
        row.addWidget(self.label, 1)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        for title, callback in [(tr('Add'), self.add), (tr('Remove'), self.remove),
                                (tr('↑ Up'), lambda: self.move(-1)), (tr('↓ Down'), lambda: self.move(1))]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def set_items(self, items):
        self.list.clear()
        for data in items:
            self.append(data)
        if self.list.count():
            self.list.setCurrentRow(0)

    def append(self, data):
        data = dict(data)
        item = QListWidgetItem(data.get("label") or tr(BY_ID[data["command"]].title))
        item.setData(Qt.ItemDataRole.UserRole, data)
        self.list.addItem(item)

    def load_row(self, row):
        item = self.list.item(row)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        with QSignalBlocker(self.command), QSignalBlocker(self.label):
            self.command.setCurrentIndex(self.command.findData(data["command"]))
            self.label.setText(data.get("label", ""))

    def update_row(self, *args):
        item = self.list.currentItem()
        if item:
            data = {"command": self.command.currentData(), "label": self.label.text()}
            item.setData(Qt.ItemDataRole.UserRole, data)
            item.setText(data["label"] or tr(BY_ID[data["command"]].title))

    def add(self):
        if self.list.count() >= 16:
            return
        self.append({"command": self.command.currentData(), "label": ""})
        self.list.setCurrentRow(self.list.count() - 1)

    def remove(self):
        self.list.takeItem(self.list.currentRow())

    def move(self, delta):
        old = self.list.currentRow()
        new = old + delta
        if 0 <= old < self.list.count() and 0 <= new < self.list.count():
            item = self.list.takeItem(old)
            self.list.insertItem(new, item)
            self.list.setCurrentRow(new)

    def items(self):
        return [self.list.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.list.count())]


class ControlsDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle(tr('Controls — shortcuts and buttons'))
        self.resize(880, 690)
        self.result_config = None
        layout = QVBoxLayout(self)
        note = QLabel(tr('Shortcuts, menus and buttons share the same commands. Apply updates them without closing this window.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        profiles = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.setProperty("translatedItems", True)
        self.profile.addItem(tr('Soovee Commander — F2 rename'), "stereo")
        self.profile.addItem(tr('Total Commander — F2 refresh, Shift+F6 rename'), "tc")
        profiles.addWidget(self.profile, 1)
        reset = QPushButton(tr('Load default profile into dialog'))
        reset.clicked.connect(lambda: self.load_config(defaults(self.profile.currentData())))
        profiles.addWidget(reset)
        layout.addLayout(profiles)
        tabs = QTabWidget()
        keyboard = QWidget()
        keys_layout = QVBoxLayout(keyboard)
        search = QLineEdit()
        search.setPlaceholderText(tr('Find command…'))
        search.textChanged.connect(self.filter_rows)
        keys_layout.addWidget(search)
        self.table = QTableWidget(len(COMMANDS), 3)
        self.table.setHorizontalHeaderLabels([tr('Command'), tr('Keyboard shortcuts (separated by semicolons)'), tr('Scope')])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 140)
        self.key_edits = {}
        for row, command in enumerate(COMMANDS):
            title = QTableWidgetItem(tr(command.title))
            title.setFlags(title.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, title)
            edit = QLineEdit()
            self.key_edits[command.id] = edit
            self.table.setCellWidget(row, 1, edit)
            scope = QTableWidgetItem({"files": tr('File list'), "window": tr("Application window"), "editor": "Editor"}[command.scope])
            scope.setFlags(scope.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, scope)
        keys_layout.addWidget(self.table, 1)
        capture = QHBoxLayout()
        capture.addWidget(QLabel(tr('Press a new shortcut:')))
        self.capture = QKeySequenceEdit()
        self.capture.setMaximumSequenceLength(1)
        capture.addWidget(self.capture, 1)
        add = QPushButton(tr('Add to selected command'))
        add.clicked.connect(self.add_captured)
        capture.addWidget(add)
        clear = QPushButton(tr('Clear its shortcuts'))
        clear.clicked.connect(self.clear_selected)
        capture.addWidget(clear)
        keys_layout.addLayout(capture)
        help = QLabel(tr('Examples: F2; Shift+F6 or Ctrl+Alt+R. Enter, Backspace, Tab and selection apply only to the file list, so they do not block path editing. On Mac, Ctrl means Command and Meta means the physical Control key.'))
        help.setWordWrap(True)
        help.setObjectName("muted")
        keys_layout.addWidget(help)
        tabs.addTab(keyboard, tr('Keyboard shortcuts'))
        self.top = BarEditor()
        self.bottom = BarEditor()
        tabs.addTab(self.top, tr('Top buttons'))
        tabs.addTab(self.bottom, tr('Bottom buttons'))
        layout.addWidget(tabs, 1)
        bottom = QHBoxLayout()
        imported = QPushButton(tr('Import JSON…'))
        imported.clicked.connect(self.import_file)
        exported = QPushButton(tr('Export JSON…'))
        exported.clicked.connect(self.export_file)
        bottom.addWidget(imported)
        bottom.addWidget(exported)
        bottom.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_settings)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr('Save'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Cancel'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)
        self.load_config(host.commands.config)
        self.table.selectRow(0)

    def load_config(self, config):
        config = validate_config(config)
        for command in COMMANDS:
            self.key_edits[command.id].setText("; ".join(config["keys"][command.id]))
        self.top.set_items(config["top"])
        self.bottom.set_items(config["bottom"])

    def config(self):
        return validate_config({"schema": 1,
            "keys": {command.id: [part.strip() for part in self.key_edits[command.id].text().split(";") if part.strip()]
                     for command in COMMANDS}, "top": self.top.items(), "bottom": self.bottom.items()})

    def filter_rows(self, text):
        for row, command in enumerate(COMMANDS):
            self.table.setRowHidden(row, text.casefold() not in command.title.casefold())

    def add_captured(self):
        row = self.table.currentRow()
        if row >= 0 and not self.capture.keySequence().isEmpty():
            edit = self.key_edits[COMMANDS[row].id]
            text = self.capture.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            edit.setText((edit.text().strip() + "; " if edit.text().strip() else "") + text)
            self.capture.clear()

    def clear_selected(self):
        if self.table.currentRow() >= 0:
            self.key_edits[COMMANDS[self.table.currentRow()].id].clear()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Import controls'), "", tr('Settings (*.json)'))
        if path:
            try:
                if Path(path).stat().st_size > 256 * 1024:
                    raise ValueError(tr('The configuration file is too large.'))
                self.load_config(json.loads(Path(path).read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, tr('Import failed'), str(exc))

    def export_file(self):
        try:
            config = self.config()
            path, _ = QFileDialog.getSaveFileName(self, tr('Export controls'), "soovee-controls.json", tr('Settings (*.json)'))
            if path:
                Path(path).write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr('Export failed'), str(exc))

    def accept(self):
        try:
            self.result_config = self.config()
        except ValueError as exc:
            QMessageBox.warning(self, tr('Check controls'), str(exc))
            return
        super().accept()

    def apply_settings(self):
        try:
            self.host.commands.apply(self.config())
        except ValueError as exc:
            QMessageBox.warning(self, tr('Check controls'), str(exc))
