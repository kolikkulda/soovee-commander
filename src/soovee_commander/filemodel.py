"""Virtual file listing: Qt requests cells only for rows currently on screen."""
from datetime import datetime
from functools import lru_cache
from collections import OrderedDict
from pathlib import PurePosixPath
import stat

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QStyle

from .providers import Entry, is_archive
from .i18n import tr
from .filetypes import extension, kind, mime_name, type_icon
from .columns import COLUMNS, ALIGNMENTS, DESCRIPTIONS


def size_text(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def date_text(value):
    try:
        return datetime.fromtimestamp(value).strftime("%d.%m.%Y %H:%M") if value else ""
    except (ValueError, OSError, OverflowError):
        return ""


@lru_cache(maxsize=8192)
def display_cell(entry, column):
    if column == 0:
        return entry.name
    if column == 1:
        return "—" if entry.is_dir else size_text(entry.size)
    if column == 2:
        return date_text(entry.modified)
    if column == 3:
        return kind(entry.name, entry.is_dir, entry.is_link)[1]
    if column == 4:
        return extension(entry.name)[1:] if not entry.is_dir else ""
    if column == 6:
        return "inode/directory" if entry.is_dir else mime_name(entry.name)
    if column == 7:
        return "" if entry.is_dir else str(entry.size)
    if column == 8:
        return stat.filemode(entry.mode) if entry.mode else ""
    if column == 9:
        return date_text(entry.created)
    if column == 10:
        return date_text(entry.accessed)
    if column == 11:
        return entry.owner
    if column == 12:
        return entry.group
    if column == 13:
        return entry.link_target
    if column == 15:
        return date_text(entry.added)
    if column == 16:
        return date_text(entry.opened)
    return ""


class FileModel(QAbstractTableModel):
    headers = tuple(c[1] for c in COLUMNS)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.local_packages = True
        self.labels = list(self.headers)
        self.alignments = [c[3] for c in COLUMNS]
        self.program_label = lambda entry: ""
        self.path_label = lambda entry: entry.name
        self.directory_sizes = {}
        self.thumbnails = OrderedDict()
        self.entries = []
        self.visible = []
        self.has_parent = False
        self.query = ""
        self.show_hidden = True
        self.column = 0
        self.descending = False
        self.folders_first = True
        self.icons = {
            True: QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon),
            False: QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon),
        }
        self.archive_color = QColor("#eac482")

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.visible) + self.has_parent

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def entry(self, row):
        if row < 0 or row >= self.rowCount() or (self.has_parent and row == 0):
            return None
        return self.visible[row - self.has_parent]

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        flags = super().flags(index) | Qt.ItemFlag.ItemIsDropEnabled
        if self.entry(index.row()) is not None:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self.rowCount():
            return None
        entry = self.entry(index.row())
        column = index.column()
        if role == Qt.ItemDataRole.UserRole:
            return entry
        if entry is None:
            return ".." if role == Qt.ItemDataRole.DisplayRole and column == 0 else None
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 1 and entry.is_dir and entry.name in self.directory_sizes:
                return size_text(self.directory_sizes[entry.name])
            if column == 5:
                return self.program_label(entry)
            if column == 14:
                return self.path_label(entry)
            return display_cell(entry, column)
        if role == Qt.ItemDataRole.DecorationRole and column == 0:
            if entry.name in self.thumbnails:
                return self.thumbnails[entry.name]
            group = kind(entry.name, entry.is_dir, entry.is_link, self.local_packages)[0]
            if group == "folder":
                return self.icons[True]
            if group == "link":
                return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon)
            return type_icon(group)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return ALIGNMENTS[self.alignments[column]] | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and column == 0 and is_archive(entry.name):
            return self.archive_color
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry.name + "\n" + kind(entry.name, entry.is_dir, entry.is_link)[1] + "\n" + self.program_label(entry) if column == 0 else str(self.data(index, Qt.ItemDataRole.DisplayRole))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(self.labels[section]) if self.labels[section] == COLUMNS[section][1] else self.labels[section]
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.ToolTipRole and COLUMNS[section][0] in DESCRIPTIONS:
            return tr(DESCRIPTIONS[COLUMNS[section][0]])
        return None

    def set_entries(self, entries, has_parent=False):
        self.entries = entries
        self.has_parent = has_parent
        self.rebuild()

    def set_filter(self, query, show_hidden=True):
        self.query, self.show_hidden = query.casefold(), show_hidden
        self.rebuild()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.column, self.descending = column, order == Qt.SortOrder.DescendingOrder
        self.rebuild(preserve=True)

    def rebuild(self, preserve=False):
        query = self.query
        visible = [e for e in self.entries if (self.show_hidden or not e.name.startswith("."))
                   and (not query or query in e.name.casefold())]
        column = self.column

        def key(e):
            if column == 1:
                return self.directory_sizes.get(e.name, e.size) if e.is_dir else e.size, e.name.casefold()
            if column == 2:
                return e.modified, e.name.casefold()
            if column == 3:
                return kind(e.name, e.is_dir, e.is_link)[1].casefold(), e.name.casefold()
            if column == 4:
                return extension(e.name), e.name.casefold()
            if column == 5:
                return self.program_label(e).casefold(), e.name.casefold()
            if column == 7:
                return self.directory_sizes.get(e.name, e.size) if e.is_dir else e.size, e.name.casefold()
            if column in (9, 10):
                return e.created if column == 9 else e.accessed, e.name.casefold()
            if column in (15, 16):
                return e.added if column == 15 else e.opened, e.name.casefold()
            if column == 8:
                return e.mode, e.name.casefold()
            if column == 14:
                return self.path_label(e).casefold()
            if column > 5:
                return str(display_cell(e, column)).casefold(), e.name.casefold()
            return e.name.casefold()

        if self.folders_first:
            directories = [e for e in visible if e.is_dir]
            files = [e for e in visible if not e.is_dir]
        else:
            directories, files = [], list(visible)
        directories.sort(key=key, reverse=self.descending)
        files.sort(key=key, reverse=self.descending)
        if preserve:
            persistent = self.persistentIndexList()
            old_entries = [self.entry(index.row()) for index in persistent]
            self.layoutAboutToBeChanged.emit()
            self.visible = directories + files
            positions = {id(entry): row for row, entry in enumerate(self.visible, start=int(self.has_parent))} if persistent else {}
            updated = [self.index(0, index.column()) if entry is None and self.has_parent else
                       self.index(positions.get(id(entry), -1), index.column())
                       for index, entry in zip(persistent, old_entries)]
            self.changePersistentIndexList(persistent, updated)
            self.layoutChanged.emit()
        else:
            self.beginResetModel()
            self.visible = directories + files
            self.endResetModel()

    def index_for_name(self, name):
        for row, entry in enumerate(self.visible, start=int(self.has_parent)):
            if entry.name == name:
                return self.index(row, 0)
        return QModelIndex()
