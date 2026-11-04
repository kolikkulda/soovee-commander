"""Stable column IDs keep sorting, tab states and saved layouts compatible."""
from .i18n import tr
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
                              QTableWidget, QTableWidgetItem, QVBoxLayout)

COLUMNS = (
    ("name", 'Name', 240, "left"),
    ("size", 'Size', 80, "right"),
    ("modified", 'Modified', 130, "left"),
    ("type", 'Type', 90, "left"),
    ("extension", 'Extension', 85, "left"),
    ("program", 'Open with', 130, "left"),
    ("mime", "MIME type", 190, "left"),
    ("bytes", 'Size in bytes', 120, "right"),
    ("permissions", 'Permissions', 110, "left"),
    ("created", 'Created', 145, "left"),
    ("accessed", 'Last accessed', 145, "left"),
    ("owner", 'Owner', 110, "left"),
    ("group", "Group", 100, "left"),
    ("target", 'Link target', 260, "left"),
    ("path", 'Full path', 350, "left"),
    ("added", 'Date added', 145, "left"),
    ("opened", 'Last opened', 145, "left"),
)
IDS = {column[0]: index for index, column in enumerate(COLUMNS)}
# Columns introduced after layouts were first saved; older layouts gain them hidden.
LATER_COLUMNS = ("added", "opened")
DESCRIPTIONS = {
    "modified": 'When the content was last changed. Copying, extracting or downloading usually keeps the original date.',
    "created": 'When this copy of the item was created on this disk.',
    "accessed": 'Last read by any program, including previews and backups. Not shown by Finder or Explorer.',
    "added": 'When the item arrived in this folder (copy, move, download). Matches Finder “Date Added”. On Windows, the creation time.',
    "opened": 'When the item was last opened in an application. Matches Finder “Date Last Opened”. On Windows, the last access time.',
}
ALIGNMENTS = {"left": Qt.AlignmentFlag.AlignLeft, "right": Qt.AlignmentFlag.AlignRight, "center": Qt.AlignmentFlag.AlignHCenter}


def defaults():
    order = [0, 3, 1, 2, 5, 4, *range(6, len(COLUMNS))]
    return [{"id": COLUMNS[i][0], "visible": i in (0, 1, 2, 3, 5), "width": COLUMNS[i][2], "label": COLUMNS[i][1], "align": COLUMNS[i][3]} for i in order]


def validate(value):
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        present = {item.get("id") for item in value}
        missing = [column for column in COLUMNS if column[0] not in present]
        if missing and all(column[0] in LATER_COLUMNS for column in missing):
            value = [*value, *({"id": c[0], "visible": False, "width": c[2], "label": c[1], "align": c[3]} for c in missing)]
    if not isinstance(value, list) or len(value) != len(COLUMNS):
        raise ValueError(tr('Invalid column settings.'))
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or item.get("id") not in IDS or item["id"] in seen:
            raise ValueError(tr('Invalid or duplicate column.'))
        seen.add(item["id"])
        width = item.get("width")
        if type(width) is not int or not 40 <= width <= 3000:
            raise ValueError(tr('Column width must be between 40 and 3000 points.'))
        label = item.get("label", "")
        if not isinstance(label, str) or not label.strip() or len(label) > 60 or any(c in label for c in "\r\n\t"):
            raise ValueError(tr('Invalid column heading.'))
        if item.get("align") not in ALIGNMENTS or type(item.get("visible")) is not bool:
            raise ValueError(tr('Invalid column alignment or visibility.'))
        # Preserve saved layouts while migrating former default source labels.
        saved = dict(item)
        saved['label'] = {'MIME typ': 'MIME type', 'Size v bajtech': 'Size in bytes'}.get(label, label)
        result.append(saved)
    if not next(c for c in result if c["id"] == "name")["visible"]:
        raise ValueError(tr('The Name column must stay visible.'))
    return result


class ColumnsDialog(QDialog):
    def __init__(self, panel):
        super().__init__(panel.window)
        self.panel = panel
        self.setWindowTitle(tr('Columns — ') + panel.title.text())
        self.resize(820, 630)
        layout = QVBoxLayout(self)
        label = QLabel(tr('Show or hide columns. Drag panel headings to reorder columns and their edges to resize them. Name always stays visible.'))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr('View'), tr("Column"), tr('Custom heading'), tr('Width'), tr('Alignment')])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 75); self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(3, 85); self.table.setColumnWidth(4, 115)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 1)
        self.separators = QCheckBox(tr('Vertical column separators'))
        self.separators.setChecked(panel.column_separators)
        layout.addWidget(self.separators)
        row = QHBoxLayout()
        for title, callback in ((tr('↑ Up'), lambda: self.move(-1)), (tr('↓ Down'), lambda: self.move(1)), (tr('Default columns'), lambda: self.load(defaults()))):
            button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        self.other = QCheckBox(tr('Apply the same settings to the other panel'))
        layout.addWidget(self.other)
        self.error = QLabel()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_settings)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.load(panel.column_layout())

    def load(self, columns):
        self.table.setRowCount(0)
        self.table.setRowCount(len(columns))
        for row, item in enumerate(columns):
            enabled = QCheckBox()
            enabled.setChecked(item["visible"]); enabled.setEnabled(item["id"] != "name")
            self.table.setCellWidget(row, 0, enabled)
            name = QTableWidgetItem(tr(COLUMNS[IDS[item["id"]]][1]))
            name.setData(Qt.ItemDataRole.UserRole, item["id"])
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, name)
            label = QLineEdit(tr(item["label"]) if item["label"] == COLUMNS[IDS[item["id"]]][1] else item["label"]); label.setMaxLength(60)
            self.table.setCellWidget(row, 2, label)
            width = QSpinBox(); width.setRange(40, 3000); width.setValue(item["width"])
            self.table.setCellWidget(row, 3, width)
            align = QComboBox()
            align.setProperty("translatedItems", True)
            for text, key in ((tr('Left'), "left"), (tr('Right'), "right"), (tr('Center'), "center")):
                align.addItem(text, key)
            align.setCurrentIndex(align.findData(item["align"]))
            self.table.setCellWidget(row, 4, align)
        self.table.selectRow(0)

    def values(self):
        return [{"id": self.table.item(row, 1).data(Qt.ItemDataRole.UserRole), "visible": self.table.cellWidget(row, 0).isChecked(), "label": self.canonical_label(row), "width": self.table.cellWidget(row, 3).value(), "align": self.table.cellWidget(row, 4).currentData()} for row in range(self.table.rowCount())]

    def canonical_label(self, row):
        column = COLUMNS[IDS[self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)]][1]
        value = self.table.cellWidget(row, 2).text()
        return column if value == tr(column) else value

    def move(self, delta):
        row = self.table.currentRow(); target = row + delta
        if 0 <= target < self.table.rowCount() and row >= 0:
            values = self.values()
            values[row], values[target] = values[target], values[row]
            self.load(values); self.table.selectRow(target)

    def apply_settings(self):
        try:
            values = validate(self.values())
            self.panel.apply_columns(values)
            self.panel.set_column_separators(self.separators.isChecked())
            if self.other.isChecked():
                other = self.panel.window.right if self.panel is self.panel.window.left else self.panel.window.left
                other.apply_columns(values)
                other.set_column_separators(self.separators.isChecked())
            self.error.setText(tr('Applied to both panels.' if self.other.isChecked() else 'Applied to this panel.'))
            return True
        except ValueError as exc:
            self.error.setText(str(exc))
            return False

    def save(self):
        if self.apply_settings(): self.accept()
