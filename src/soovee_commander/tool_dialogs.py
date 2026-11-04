"""File tools with explicit previews and cancelable background scans."""
from .i18n import tr
import difflib
from datetime import datetime
from threading import Event

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QDate, QSortFilterProxyModel
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QDateEdit, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                              QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                              QTableWidgetItem, QTableView, QVBoxLayout)

from .advanced import compare, digest, multi_rename, rename_names, search, sync_entries
from .operations import preview
from .providers import Entry


class WorkerDialog(QDialog):
    def __init__(self, host, title):
        super().__init__(host)
        self.host = host
        self.setWindowTitle(title)
        self.resize(900, 650)
        self.cancel = Event()
        self.generation = 0
        self.busy = False
        self.layout_box = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)

    def work(self, function, done):
        self.cancel.set()
        self.cancel = Event()
        cancel = self.cancel
        self.generation += 1
        generation = self.generation
        self.busy = True
        self.status.setText(tr('Working…'))
        def finished(result):
            if generation != self.generation:
                return
            self.busy = False
            done(result)
        def failed(message):
            if generation == self.generation:
                self.busy = False
                self.status.setText(message)
        self.host.run_task(lambda report: function(cancel, report), finished, failed,
                           report=lambda message, count: self.status.setText(message) if generation == self.generation else None)

    def reject(self):
        self.cancel.set()
        self.generation += 1
        super().reject()

    def closeEvent(self, event):
        self.cancel.set()
        self.generation += 1
        super().closeEvent(event)


class ResultModel(QAbstractTableModel):
    def __init__(self, headers, parent):
        super().__init__(parent)
        self.headers, self.rows = headers, []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.ForegroundRole and hasattr(self, 'foreground'):
            return self.foreground(index.row(), index.column())
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole):
            if role == Qt.ItemDataRole.UserRole and getattr(self, 'sort_keys', None):
                return self.sort_keys[index.row()][index.column()]
            return self.rows[index.row()][index.column()]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]


class ResultTable(QTableView):
    def __init__(self, headers):
        super().__init__()
        self.records = ResultModel(headers, self)
        self.setModel(self.records)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().hide()

    def set_rows(self, rows):
        self.records.beginResetModel()
        self.records.rows = rows
        self.records.endResetModel()

    def currentRow(self):
        return self.currentIndex().row()


def table(headers):
    return ResultTable(headers)


class SearchDialog(WorkerDialog):
    def __init__(self, host):
        super().__init__(host, tr('Search files and contents'))
        self.panel, self.provider, self.root = host.active, host.active.provider, host.active.path
        self.layout_box.addWidget(QLabel(tr('Search including subfolders: ') + self.root))
        form = QFormLayout()
        self.pattern = QLineEdit("*")
        self.text = QLineEdit()
        self.text.setPlaceholderText(tr('Optional exact UTF-8 text; case sensitive'))
        form.addRow(tr('Names (e.g. *.txt;*.md):'), self.pattern)
        form.addRow(tr('Containing text:'), self.text)
        self.after_enabled, self.before_enabled = QCheckBox(tr('Modified from')), QCheckBox(tr('Modified until'))
        self.after_date, self.before_date = QDateEdit(QDate.currentDate().addMonths(-1)), QDateEdit(QDate.currentDate())
        for checkbox, date in ((self.after_enabled, self.after_date), (self.before_enabled, self.before_date)):
            date.setCalendarPopup(True)
            date.setDisplayFormat('yyyy-MM-dd')
            form.addRow(checkbox, date)
        self.min_size, self.max_size = QLineEdit(), QLineEdit()
        self.min_size.setPlaceholderText(tr('Bytes, optional'))
        self.max_size.setPlaceholderText(tr('Bytes, optional'))
        form.addRow(tr('Minimum size'), self.min_size)
        form.addRow(tr('Maximum size'), self.max_size)
        self.kind = QComboBox()
        self.kind.setProperty("translatedItems", True)
        for label, value in [('Files and folders', 'all'), ('Files only', 'files'), ('Folders only', 'folders')]:
            self.kind.addItem(tr(label), value)
        form.addRow(tr('Type'), self.kind)
        self.layout_box.addLayout(form)
        self.results = table([tr('Relative path'), tr('Size'), tr('Modified'), tr('Type')])
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.results.records)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.results.setModel(self.proxy)
        self.results.setSortingEnabled(True)
        self.results.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.results.setColumnWidth(0, 570)
        self.results.doubleClicked.connect(self.open_result)
        self.layout_box.addWidget(self.results, 1)
        self.layout_box.addWidget(self.status)
        buttons = QHBoxLayout()
        self.start = QPushButton(tr('Search'))
        self.start.clicked.connect(self.start_search)
        stop = QPushButton(tr('Stop'))
        stop.clicked.connect(self.cancel_search)
        go = QPushButton(tr('Go to result'))
        go.clicked.connect(self.open_result)
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.reject)
        for button in (self.start, stop, go, close):
            buttons.addWidget(button)
        self.layout_box.addLayout(buttons)
        self.matches = []

    def cancel_search(self):
        self.cancel.set()

    def start_search(self):
        if self.busy:
            return
        pattern, text = self.pattern.text(), self.text.text()
        try:
            minimum = int(self.min_size.text()) if self.min_size.text().strip() else None
            maximum = int(self.max_size.text()) if self.max_size.text().strip() else None
            if minimum is not None and minimum < 0 or maximum is not None and maximum < 0 or minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError()
            after = datetime.combine(self.after_date.date().toPython(), datetime.min.time()).timestamp() if self.after_enabled.isChecked() else None
            before = datetime.combine(self.before_date.date().addDays(1).toPython(), datetime.min.time()).timestamp() - .000001 if self.before_enabled.isChecked() else None
            if after is not None and before is not None and after > before:
                raise ValueError()
        except (ValueError, OverflowError):
            self.status.setText(tr('Enter a valid date range and non-negative size in bytes.'))
            return
        kind = self.kind.currentData()
        self.work(lambda cancel, report: search(self.provider, self.root, pattern, text, cancel, report, modified_after=after, modified_before=before, min_size=minimum, max_size=maximum, kind=kind), self.loaded)

    def loaded(self, result):
        self.matches, errors = result
        self.results.records.sort_keys = [[relative, entry.size, entry.modified, entry.is_dir] for relative, _, entry in self.matches]
        self.results.set_rows([[relative, "" if entry.is_dir else entry.size, datetime.fromtimestamp(entry.modified).strftime('%Y-%m-%d %H:%M:%S') if entry.modified else '', tr('Folder') if entry.is_dir else tr('File')] for relative, _, entry in self.matches])
        self.status.setText(tr('Found: {v0}. Read errors: {v1}.').format(v0=len(self.matches), v1=len(errors)) + ("\n" + "\n".join(errors[:5]) if errors else ""))

    def open_result(self, *args):
        row = self.proxy.mapToSource(self.results.currentIndex()).row()
        if 0 <= row < len(self.matches):
            _, path, entry = self.matches[row]
            self.panel.navigate(self.provider, self.provider.parent(path), focus_name=entry.name)
            self.host.activate(self.panel)
            self.reject()


from .rename_ui import MultiRenameDialog


class CompareDialog(WorkerDialog):
    def __init__(self, host):
        super().__init__(host, tr('Compare and synchronize folders'))
        self.left, self.right = host.left.provider, host.right.provider
        self.lp, self.rp = host.left.path, host.right.path
        self.differences = None
        self.layout_box.addWidget(QLabel(tr('Left: {v0}\nRight: {v1}').format(v0=host.left.location(), v1=host.right.location())))
        self.content = QCheckBox(tr('Compare file contents (SHA-256); otherwise compare size and date'))
        self.content.setChecked(True)
        self.layout_box.addWidget(self.content)
        self.results = table([tr('Relative path'), tr('Result'), tr('Left bytes'), tr('Right bytes')])
        self.results.setColumnWidth(0, 420)
        self.layout_box.addWidget(self.results, 1)
        self.layout_box.addWidget(QLabel(tr('Synchronization copies in the selected direction. Extra destination files are kept. Links and type conflicts require manual resolution.')))
        self.layout_box.addWidget(self.status)
        buttons = QHBoxLayout()
        scan = QPushButton(tr('Compare'))
        scan.clicked.connect(self.scan)
        stop = QPushButton(tr('Stop'))
        stop.clicked.connect(lambda: self.cancel.set())
        self.to_right, self.to_left = QPushButton(tr('Synchronize →')), QPushButton(tr('← Synchronize'))
        self.to_right.clicked.connect(lambda: self.synchronize("right"))
        self.to_left.clicked.connect(lambda: self.synchronize("left"))
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.reject)
        for button in (scan, stop, self.to_right, self.to_left, close):
            buttons.addWidget(button)
        self.layout_box.addLayout(buttons)
        self.to_right.setEnabled(False)
        self.to_left.setEnabled(False)

    def scan(self):
        if self.busy:
            return
        self.differences = None
        self.to_right.setEnabled(False)
        self.to_left.setEnabled(False)
        content = self.content.isChecked()
        self.work(lambda cancel, report: compare(self.left, self.lp, self.right, self.rp, cancel, content, report), self.loaded)

    def loaded(self, differences):
        self.differences = differences
        self.results.set_rows([[d.name, tr(d.status), str(d.left.size) if d.left and not d.left.is_dir else "", str(d.right.size) if d.right and not d.right.is_dir else ""] for d in differences])
        count = sum(d.status != 'Equal' for d in differences)
        self.status.setText(tr('{v0} items, differences: {v1}. Choose a direction; newer destination files may be replaced.').format(v0=len(differences), v1=count))
        self.to_right.setEnabled(not self.right.readonly)
        self.to_left.setEnabled(not self.left.readonly)

    def synchronize(self, direction):
        if self.differences is None:
            return
        source, src, destination, dst = (self.left, self.lp, self.right, self.rp) if direction == "right" else (self.right, self.rp, self.left, self.lp)
        plan = list(self.differences)
        # Check incompatible rows before enqueue, never half-apply such a plan.
        invalid = [d.name for d in plan if d.status in ('Type conflict', 'Link — skip')]
        if invalid:
            return QMessageBox.warning(self, tr('Conflicts'), tr('Resolve these items manually first:\n') + "\n".join(invalid[:10]))
        count = sum(d.status != 'Equal' and (d.left if direction == "right" else d.right) is not None for d in plan)
        if not count:
            return
        from . import dialog_kit
        if not dialog_kit.confirm(self, tr('Confirm synchronization'), tr('Copy {v0} different items?').format(v0=count),
                                  tr('Into: {v0}').format(v0=dst), action=tr('Synchronize'), icon="swap",
                                  note=tr('Existing files are replaced in the selected direction. Extra items at the destination are kept.')):
            return
        self.host.enqueue(tr('Synchronize → {v0}').format(v0=dst), lambda cancel, report: sync_entries(source, src, destination, dst, plan, cancel, report, direction))
        self.reject()


class FileCompareDialog(WorkerDialog):
    def __init__(self, host, a, b):
        super().__init__(host, tr('Compare file contents'))
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.layout_box.addWidget(self.output, 1)
        self.layout_box.addWidget(self.status)
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.reject)
        self.layout_box.addWidget(close)
        def load(cancel, report):
            ap, path_a = a
            bp, path_b = b
            equal = digest(ap, path_a, cancel) == digest(bp, path_b, cancel)
            if equal:
                return tr('The files have identical contents (SHA-256).'), ""
            x, y = preview(ap, path_a, 2_000_001), preview(bp, path_b, 2_000_001)
            if max(len(x), len(y)) > 2_000_000 or b"\0" in x + y:
                return tr('The files are different. Text diff is available for text files up to 2 MB.'), ""
            try:
                lines_a, lines_b = x.decode("utf-8").splitlines(True), y.decode("utf-8").splitlines(True)
                if max(len(lines_a), len(lines_b)) > 20_000:
                    return tr('The files are different; text diff is limited to 20,000 lines.'), ""
                text = "".join(difflib.unified_diff(lines_a, lines_b, fromfile=path_a, tofile=path_b))
            except UnicodeDecodeError:
                return tr('The files are different; the contents are not UTF-8 text.'), ""
            return tr('The files are different.'), text
        self.work(load, lambda result: (self.status.setText(result[0]), self.output.setPlainText(result[1])))
