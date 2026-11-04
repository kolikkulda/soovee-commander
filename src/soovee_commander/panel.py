"""Two-pane browsing with independent, lightweight tab sessions."""
from .i18n import tr
from dataclasses import dataclass, field
import json
import sys
from collections import OrderedDict
import os
import time
import logging
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from PySide6.QtCore import QEvent, QItemSelectionModel, QMimeData, QPoint, QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDrag, QPainter, QWheelEvent
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
                              QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QTabBar, QToolButton, QTreeView, QVBoxLayout, QStackedWidget)

from .filemodel import FileModel, size_text
from .device_files import DeviceProvider
from .tabbar import PanelTabBar, TabCloseButton
from .columns import COLUMNS, IDS, ColumnsDialog, defaults as default_columns, validate as validate_columns
from .providers import LocalProvider
from .filetypes import extension
from .native_apps import application, applications_for_file
from .frozen_columns import FrozenColumns
from shiboken6 import isValid
from .providers import ArchiveProvider, LocalProvider, RemoteProvider, is_archive
from .storage import read_volume, read_volumes
from .storage_ui import DiskSummary, DriveButton, capacity_text
from .panel_views import TileView, PanelAppearance
from .folder_watch import FolderWatcher


@dataclass(frozen=True)
class ViewState:
    current: str | None = None
    selected: frozenset = frozenset()
    scroll: int = 0
    row: int = 0
    query: str = ""
    column: int = 0
    descending: bool = False


@dataclass(eq=False, frozen=True)
class LocationState:
    provider: object
    path: str
    view: ViewState


@dataclass(eq=False)
class TabState:
    provider: object
    path: str
    history: list = field(default_factory=list)
    future: list = field(default_factory=list)
    entries: list | None = None
    query: str = ""
    selected: set = field(default_factory=set)
    current: str | None = None
    scroll: int = 0
    column: int = 0
    descending: bool = False
    serial: int = 0
    loading: bool = False
    row: int = 0
    label: str = ""
    locked: bool = False
    sizes: dict = field(default_factory=dict)
    views: OrderedDict = field(default_factory=OrderedDict)
    finder_dates: bool = False
    loaded_at: float = 0


class FileTree(QTreeView):
    activated_panel = Signal()
    go_parent = Signal()
    enter_item = Signal()
    switch_panel = Signal()

    def paintEvent(self, event):
        super().paintEvent(event)
        panel = getattr(self, 'panel', None)
        if panel is None or not panel.column_separators:
            return
        from .themes import THEMES
        painter = QPainter(self.viewport())
        painter.setClipRect(event.rect())
        painter.setPen(QColor(THEMES[panel.window.theme_key]['border']))
        header = self.header()
        for logical in range(header.count()):
            if not self.isColumnHidden(logical):
                x = header.sectionViewportPosition(logical) + header.sectionSize(logical) - 1
                if 0 <= x < self.viewport().width():
                    painter.drawLine(x, 0, x, self.viewport().height() - 1)
        painter.end()

    def mousePressEvent(self, event):
        if getattr(self, 'is_frozen', False):
            self.panel.window.activate(self.panel)
            self.panel.tree.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        panel = getattr(self, 'panel', None)
        if getattr(self, 'is_frozen', False):
            panel.tree.wheelEvent(event)
            return
        if panel is None or not panel.vertical_scroll_only:
            super().wheelEvent(event)
            return
        pixel, angle = event.pixelDelta(), event.angleDelta()
        if not pixel.isNull():
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - pixel.y())
        elif angle.y():
            vertical = QWheelEvent(event.position(), event.globalPosition(), QPoint(0, pixel.y()), QPoint(0, angle.y()),
                                   event.buttons(), event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier,
                                   event.phase(), event.inverted(), Qt.MouseEventSource.MouseEventSynthesizedByApplication,
                                   event.pointingDevice())
            super().wheelEvent(vertical)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        controller = getattr(self, 'frozen_columns', None)
        if controller is not None:
            controller.layout()

    def scrollTo(self, index, hint=QTreeView.ScrollHint.EnsureVisible):
        preserve = getattr(getattr(self, 'panel', None), 'pin_name', False) and not getattr(self, 'is_frozen', False) and index.column() == 0
        previous = self.horizontalScrollBar().value()
        super().scrollTo(index, hint)
        if preserve:
            self.horizontalScrollBar().setValue(previous)

    def startDrag(self, supported_actions):
        panel = self.panel
        paths = [panel.provider.join(panel.path, e.name) for e in panel.action_entries()] if isinstance(panel.provider, LocalProvider) else []
        # Real file URLs let Finder and other macOS applications consume the drag.
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        panel = self.panel
        if not event.mimeData().hasUrls() or not all(url.isLocalFile() for url in event.mimeData().urls()):
            event.ignore()
            return
        index = self.indexAt(event.position().toPoint())
        entry = panel.model.entry(index.row()) if index.isValid() else None
        destination = panel.provider.join(panel.path, entry.name) if entry and entry.is_dir else panel.path
        panel.window.drop_paths(panel, [url.toLocalFile() for url in event.mimeData().urls()], destination)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def focusInEvent(self, event):
        self.activated_panel.emit()
        super().focusInEvent(event)

    def event(self, event):
        host = getattr(self, "command_host", None)
        commands = getattr(host, "commands", None)
        if commands is not None:
            if event.type() == QEvent.Type.KeyPress and commands.dispatch_file_key(event):
                return True
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton):
                    self.activated_panel.emit()
                    commands.execute("back" if event.button() == Qt.MouseButton.BackButton else "forward")
                    return True
        return super().event(event)


class Panel(QFrame):
    MAX_TABS = 32

    def __init__(self, window, name, path, side="left"):
        super().__init__()
        self.window = window
        self.side = side
        self.vertical_scroll_only = window.settings.value('vertical_scroll_only_' + side, False, type=bool)
        self.pin_name = window.settings.value('pin_name_' + side, False, type=bool)
        self.auto_fit_columns = window.settings.value('auto_fit_columns_' + side, False, type=bool)
        self.column_separators = window.settings.value('column_separators_' + side, False, type=bool)
        self.column_settings_key = "columns_" + side
        self._columns_loading = True
        self._column_widths = {i: c[2] for i, c in enumerate(COLUMNS)}
        self._current = TabState(LocalProvider(), path)
        self.tab_states = [self._current]
        self.closed_tabs = []
        self._volume_key = None
        self._volume_busy = False
        self._volume_loaded_at = 0
        self._volume_info = None
        self._drives_cache = None
        self._drives_loaded_at = 0
        self._drives_busy = False
        self.setObjectName("panel")
        self.setProperty("active", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        heading = QFrame()
        heading.setObjectName("panelHeading")
        heading_layout = QVBoxLayout(heading)
        heading_layout.setContentsMargins(9, 5, 9, 7)
        heading_layout.setSpacing(5)
        top = QHBoxLayout()
        heading_layout.addLayout(top)
        top.setSpacing(8)
        self.title = QLabel(name)
        self.title.setObjectName("panelTitle")
        drive = self.drive_button = DriveButton()
        drive.setObjectName("driveButton")
        drive.setProperty('userContent', True)
        drive.setMinimumWidth(70)
        drive.setMaximumWidth(260)
        drive.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        drive_menu = self.drive_menu = QMenu(drive)
        drive_menu.aboutToShow.connect(lambda: self.populate_drives(drive_menu))
        drive.setMenu(drive_menu)
        self.badge = QLabel(tr('LOCAL DISK'))
        self.badge.setTextFormat(Qt.TextFormat.PlainText)
        self.badge.setObjectName("badge")
        self.badge.setMaximumWidth(250)
        top.addWidget(self.title)
        top.addWidget(drive, 1)
        top.addStretch()
        top.addWidget(self.badge)
        self.disk_summary = DiskSummary(self)
        heading_layout.addWidget(self.disk_summary)
        layout.addWidget(heading)
        self.storage_timer = QTimer(self)
        self.storage_timer.setInterval(15000)
        self.storage_timer.timeout.connect(lambda: self.refresh_storage(force=True) if self.isVisible() else None)
        self.storage_timer.start()

        tabs = QFrame()
        tabs.setObjectName("tabStrip")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(4, 3, 4, 0)
        tabs_layout.setSpacing(3)
        self.tabbar = PanelTabBar(self)
        self.tabbar.setExpanding(False)
        self.tabbar.setMovable(True)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabbar.addTab(self.tab_title(self._current))
        self.tabbar.setTabData(0, self._current)
        self.tabbar.currentChanged.connect(self.switch_tab)
        self.tabbar.tabBarClicked.connect(lambda index: window.activate(self))
        self.tabbar.tabCloseRequested.connect(self.close_tab)
        self.tabbar.tabBarDoubleClicked.connect(lambda index: self.new_tab() if index < 0 else None)
        self.tabbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabbar.customContextMenuRequested.connect(self.tab_menu)
        plus = self.new_tab_button = QPushButton("＋")
        plus.setObjectName("compactButton")
        plus.setFixedWidth(29)
        plus.setToolTip(tr('New tab · Ctrl/Cmd+T'))
        plus.clicked.connect(lambda: self.new_tab())
        tabs_layout.addWidget(self.tabbar, 1)
        tabs_layout.addWidget(plus)
        layout.addWidget(tabs)

        path_frame = QFrame()
        path_frame.setObjectName("pathStrip")
        address = QHBoxLayout(path_frame)
        address.setContentsMargins(5, 5, 5, 5)
        address.setSpacing(4)
        self.address = QLineEdit(path)
        self.address.setObjectName("pathEdit")
        self.address.setPlaceholderText(tr('Paste or type a path and press Enter…'))
        self.address.installEventFilter(self)
        self.address.returnPressed.connect(lambda: self.navigate_text(self.address.text()))
        for text, tip, callback in [("↑", tr('Parent folder · Backspace'), self.parent)]:
            button = self.path_button(text, tip, callback)
            address.addWidget(button)
        address.addWidget(self.address, 1)
        address.addWidget(self.path_button("⧉", tr('Copy this folder path'), self.copy_directory))
        address.addWidget(self.path_button("↳", tr('Paste clipboard path and open · Ctrl/Cmd+Shift+V'), self.paste_path))
        address.addWidget(self.path_button("↻", tr('Refresh · Ctrl/Cmd+R'), self.refresh))
        layout.addWidget(path_frame)
        self.crumb_frame = QFrame()
        self.crumb_frame.setObjectName("breadcrumbs")
        self.crumbs = QHBoxLayout(self.crumb_frame)
        self.crumbs.setContentsMargins(6, 0, 6, 3)
        self.crumbs.setSpacing(0)
        layout.addWidget(self.crumb_frame)
        self.filter = QLineEdit()
        self.filter.setObjectName("filterEdit")
        self.filter.setPlaceholderText(tr('Quick filename filter…  Ctrl/Cmd+F'))
        self.filter.setClearButtonEnabled(True)
        self.filter.installEventFilter(self)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(120)
        self.filter_timer.timeout.connect(self.apply_filter)
        self.filter.textChanged.connect(lambda: self.filter_timer.start())
        layout.addWidget(self.filter)
        self.tree = FileTree()
        self.tree.panel = self
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeView.DragDropMode.DragDrop)
        self.tree.command_host = window
        self.model = FileModel(self)
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        header = self.tree.header()
        header.setSectionsMovable(True)
        header.setFirstSectionMovable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(40)
        header.setMaximumSectionSize(3000)
        header.setResizeContentsPrecision(200)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.column_menu)
        self.columns_timer = QTimer(self)
        self.columns_timer.setSingleShot(True)
        self.columns_timer.setInterval(200)
        self.columns_timer.timeout.connect(self.save_columns)
        header.sectionMoved.connect(self.columns_changed)
        header.sectionResized.connect(self.column_resized)
        header.sortIndicatorChanged.connect(lambda *_: QTimer.singleShot(0, self, self.ensure_finder_dates))
        self.model.folders_first = window.settings.value("folders_first", True, type=bool)
        try:
            columns = validate_columns(json.loads(window.settings.value(self.column_settings_key, "null")))
        except (TypeError, ValueError):
            columns = default_columns()
        self.apply_columns(columns, persist=False)
        self.tree.frozen_columns = FrozenColumns(self, FileTree)
        self.tree.frozen_columns.set_pinned(self.pin_name, initial=True)
        window.associations.changed.connect(self.associations_changed)
        self.tree.activated_panel.connect(lambda: window.activate(self))
        self.tree.clicked.connect(lambda *_: window.activate(self))
        self.tree.doubleClicked.connect(lambda *_: self.open_current())
        self.tree.enter_item.connect(self.open_current)
        self.tree.go_parent.connect(self.parent)
        self.tree.switch_panel.connect(window.switch_panel)
        self.tree.selectionModel().selectionChanged.connect(self.update_footer)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.file_menu)
        self.file_stack = QStackedWidget()
        self.file_stack.addWidget(self.tree)
        self.tiles = TileView(self)
        self.tiles.setModel(self.model)
        self.tiles.setSelectionModel(self.tree.selectionModel())
        self.tiles.doubleClicked.connect(lambda *_: self.open_current())
        self.tiles.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tiles.customContextMenuRequested.connect(lambda point: self.file_menu(point, self.tiles))
        self.file_stack.addWidget(self.tiles)
        # The quick view replaces the listing visually but never becomes active_view().
        self.body = QStackedWidget()
        self.body.addWidget(self.file_stack)
        self.quick = None
        layout.addWidget(self.body, 1)
        footer_frame = QFrame()
        footer_frame.setObjectName('panelFooterFrame')
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(0, 0, 5, 0)
        footer_layout.setSpacing(3)
        self.footer = QLabel()
        self.footer.setObjectName("panelFooter")
        footer_layout.addWidget(self.footer, 1)
        self.scroll_left, self.scroll_right = QToolButton(), QToolButton()
        bar = self.tree.horizontalScrollBar()
        for button, text, tip, action in [(self.scroll_left, '←', 'Scroll columns left', bar.SliderAction.SliderSingleStepSub),
                                          (self.scroll_right, '→', 'Scroll columns right', bar.SliderAction.SliderSingleStepAdd)]:
            button.setText(text); button.setToolTip(tr(tip)); button.setAccessibleName(tr(tip))
            button.setObjectName('columnScrollButton'); button.setFixedSize(24, 24)
            button.clicked.connect(lambda checked=False, value=action: self.active_view().horizontalScrollBar().triggerAction(value))
            footer_layout.addWidget(button)
        def update_arrows(*args):
            bar = self.active_view().horizontalScrollBar()
            self.scroll_left.setVisible(bar.maximum() > 0)
            self.scroll_right.setVisible(bar.maximum() > 0)
            self.scroll_left.setEnabled(bar.value() > bar.minimum())
            self.scroll_right.setEnabled(bar.value() < bar.maximum())
        bar.rangeChanged.connect(update_arrows); bar.valueChanged.connect(update_arrows)
        self.tiles.horizontalScrollBar().rangeChanged.connect(update_arrows)
        self.tiles.horizontalScrollBar().valueChanged.connect(update_arrows)
        self._update_scroll_arrows = update_arrows
        update_arrows()
        layout.addWidget(footer_frame)
        self.appearance = PanelAppearance(self)
        self.watcher = FolderWatcher(self, lambda: self.auto_refresh("change"))
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(lambda: self.auto_refresh("poll"))
        self.configure_auto_refresh()
        self.navigate(self.provider, path)

    provider = property(lambda self: self._current.provider)
    path = property(lambda self: self._current.path)
    entries = property(lambda self: self._current.entries or [])
    history = property(lambda self: self._current.history)
    future = property(lambda self: self._current.future)

    def active_view(self):
        return self.file_stack.currentWidget()

    def set_listing_enabled(self, enabled):
        self.tree.setEnabled(enabled)
        self.tiles.setEnabled(enabled)

    def path_button(self, text, tip, callback):
        button = QPushButton(text)
        button.setObjectName("pathButton")
        button.setFixedWidth(29)
        button.setToolTip(tip)
        button.clicked.connect(callback)
        return button

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            self.window.activate(self)
        return super().eventFilter(watched, event)

    @staticmethod
    def tab_title(tab):
        if isinstance(tab.provider, DeviceProvider) and tab.path == "/" and not tab.label:
            return tab.provider.label
        if tab.label:
            return ("▣ " if tab.locked else "") + tab.label
        if isinstance(tab.provider, ArchiveProvider):
            return Path(tab.provider.filename).name if tab.path == "/" else Path(tab.path).name
        if isinstance(tab.provider, RemoteProvider) and tab.path == "/":
            return tab.provider.connection.host
        return Path(tab.path).name or Path(tab.path).anchor or tab.path

    def update_tab_labels(self):
        self.tabbar.setTabsClosable(self.tabbar.count() > 1)
        for index in range(self.tabbar.count()):
            tab = self.tabbar.tabData(index)
            self.tabbar.setTabText(index, ("▣ " if tab.locked and not tab.label else "") + self.tab_title(tab))
            self.tabbar.setTabToolTip(index, self.location(tab))
            if self.tabbar.count() > 1:
                old = self.tabbar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                if old is None or old.objectName() != "tabClose":
                    close = TabCloseButton(self.tabbar)
                    close.setToolTip(tr('Close tab'))
                    close.setAccessibleName(tr('Close tab'))
                    close.clicked.connect(lambda checked=False, target=tab: self.close_state(target))
                    self.tabbar.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        self.tabbar.position_close_buttons()

    def close_state(self, state):
        for index in range(self.tabbar.count()):
            if self.tabbar.tabData(index) is state:
                self.close_tab(index)
                break

    def save_view(self):
        tab = self._current
        tab.query = self.filter.text()
        tab.column, tab.descending = self.model.column, self.model.descending
        if not self.tree.isEnabled():
            return
        tab.selected = {entry.name for entry in self.selected()}
        entry = self.model.entry(self.tree.currentIndex().row())
        tab.current = entry.name if entry else None
        tab.scroll = self.active_view().verticalScrollBar().value()
        tab.row = max(0, self.tree.currentIndex().row())
        self.remember_view(tab)

    @staticmethod
    def location_key(provider, path):
        if isinstance(provider, ArchiveProvider):
            return ("archive", provider.filename, path.rstrip("/") or "/")
        if isinstance(provider, RemoteProvider):
            c = provider.connection
            return ("remote", c.protocol, c.host.casefold(), c.port, c.username, path.rstrip("/") or "/")
        if isinstance(provider, DeviceProvider):
            return ("device", provider.peer_id, path.rstrip("/") or "/")
        return ("local", os.path.normcase(os.path.normpath(path)))

    @staticmethod
    def view_state(tab):
        return ViewState(tab.current, frozenset(tab.selected), tab.scroll, tab.row, tab.query, tab.column, tab.descending)

    def remember_view(self, tab):
        key = self.location_key(tab.provider, tab.path)
        tab.views[key] = self.view_state(tab)
        tab.views.move_to_end(key)
        while len(tab.views) > 100:
            tab.views.popitem(last=False)

    @staticmethod
    def restore_view(tab, view):
        tab.current, tab.selected = view.current, set(view.selected)
        tab.scroll, tab.row = view.scroll, view.row
        tab.query, tab.column, tab.descending = view.query, view.column, view.descending

    def ancestor_child(self, previous, provider, path):
        if isinstance(previous.provider, ArchiveProvider) and isinstance(provider, LocalProvider):
            if LocalProvider().parent(previous.provider.filename) == path:
                return Path(previous.provider.filename).name
        if self.location_key(previous.provider, "/")[:-1] != self.location_key(provider, "/")[:-1]:
            return None
        kind = Path if isinstance(provider, LocalProvider) else PurePosixPath
        try:
            parts = kind(previous.path).relative_to(kind(path)).parts
            return parts[0] if parts else None
        except ValueError:
            return None

    def show_tab(self):
        tab = self._current
        self.filter_timer.stop()
        with QSignalBlocker(self.filter):
            self.filter.setText(tab.query)
        self.model.query = tab.query.casefold()
        self.model.show_hidden = self.window.hidden.isChecked()
        self.model.column, self.model.descending = tab.column, tab.descending
        with QSignalBlocker(self.tree.header()):
            self.tree.header().setSortIndicator(tab.column, Qt.SortOrder.DescendingOrder if tab.descending else Qt.SortOrder.AscendingOrder)
        self.model.local_packages = isinstance(tab.provider, LocalProvider)
        self.model.program_label = lambda entry: (tr('Run application') if sys.platform == "darwin" and isinstance(tab.provider, LocalProvider) and entry.name.lower().endswith(".app") else "") if entry.is_dir else self.window.associations.label(entry.name) if isinstance(tab.provider, LocalProvider) else tr('Internal preview')
        self.model.path_label = lambda entry: self.location(tab=tab, path=tab.provider.join(tab.path, entry.name))
        self.model.directory_sizes = tab.sizes.get(self.location_key(tab.provider, tab.path), {})
        self.model.set_entries(tab.entries or [], tab.provider.parent(tab.path) != tab.path or isinstance(tab.provider, ArchiveProvider))
        self.address.setText(tab.path)
        self.address.setToolTip(self.location(tab))
        self.badge.setText(tr('ARCHIVE · ') + Path(tab.provider.filename).name if isinstance(tab.provider, ArchiveProvider) else tr(tab.provider.label))
        self.badge.setToolTip(self.location(tab))
        self.badge.setVisible(not isinstance(tab.provider, LocalProvider))
        self.refresh_storage()
        self.set_listing_enabled(tab.entries is not None)
        self.appearance.location_changed()
        selection = self.tree.selectionModel()
        for row, entry in enumerate(self.model.visible, start=int(self.model.has_parent)):
            if entry.name in tab.selected:
                selection.select(self.model.index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        current = self.model.index_for_name(tab.current) if tab.current else self.model.index(0, 0)
        if not current.isValid() and self.model.rowCount():
            current = self.model.index(min(tab.row, self.model.rowCount() - 1), 0)
        selection.setCurrentIndex(current, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.tree.doItemsLayout()
        self.active_view().verticalScrollBar().setValue(tab.scroll)
        if tab.current and current.isValid() and not self.active_view().viewport().rect().contains(self.active_view().visualRect(current)):
            self.tree.scrollTo(current, QTreeView.ScrollHint.EnsureVisible)
        self.update_tab_labels()
        self.update_breadcrumbs()
        self.update_footer()
        self.update_watch()

    def switch_tab(self, index):
        tab = self.tabbar.tabData(index) if index >= 0 else None
        if tab is None or tab is self._current:
            return
        self.save_view()
        self._current = tab
        self.show_tab()
        self.window.activate(self)
        self.active_view().setFocus()
        if tab.entries is None and not tab.loading:
            self.navigate(tab.provider, tab.path, remember=False)
        elif not tab.loading:
            self.navigate(tab.provider, tab.path, remember=False, background=True)

    def new_tab(self, provider=None, path=None, activate=True):
        if len(self.tab_states) >= self.MAX_TABS:
            return self.window.error(tr('A panel can contain at most {v0} tabs.').format(v0=self.MAX_TABS))
        self.save_view()
        provider = provider or self.provider
        path = self.path if path is None else path
        tab = TabState(provider, path)
        if provider is self.provider and path == self.path:
            tab.entries = self._current.entries
            tab.query = self._current.query
            tab.column, tab.descending = self._current.column, self._current.descending
        self.tab_states.append(tab)
        index = self.tabbar.addTab(self.tab_title(tab))
        self.tabbar.setTabData(index, tab)
        self.update_tab_labels()
        if activate:
            self.tabbar.setCurrentIndex(index)
        return tab

    def move_tab_to(self, tab, target, index=None):
        if target is self or tab not in self.tab_states or len(target.tab_states) >= target.MAX_TABS or tab.loading:
            return False
        self.save_view()
        target.save_view()
        if self.tabbar.count() == 1:
            self.new_tab(LocalProvider(), str(Path.home()), activate=False)
        old_index = next(i for i in range(self.tabbar.count()) if self.tabbar.tabData(i) is tab)
        active = tab is self._current
        with QSignalBlocker(self.tabbar), QSignalBlocker(target.tabbar):
            self.tabbar.removeTab(old_index)
            self.tab_states.remove(tab)
            target.tab_states.append(tab)
            position = target.tabbar.count() if index is None else max(0, min(index, target.tabbar.count()))
            new_index = target.tabbar.insertTab(position, self.tab_title(tab))
            target.tabbar.setTabData(new_index, tab)
            target.tabbar.setCurrentIndex(new_index)
            if active:
                self._current = self.tabbar.tabData(self.tabbar.currentIndex())
            target._current = tab
        if active:
            self.show_tab()
            if self._current.entries is None:
                self.navigate(self.provider, self.path, remember=False)
        else:
            self.update_tab_labels()
        target.show_tab()
        self.window.activate(target)
        target.active_view().setFocus()
        return True

    def close_tab(self, index=None):
        index = self.tabbar.currentIndex() if index is None else index
        if self.tabbar.count() <= 1 or index < 0:
            return
        tab = self.tabbar.tabData(index)
        if tab is self._current:
            self.save_view()
        self.closed_tabs.append(tab)
        self.closed_tabs = self.closed_tabs[-10:]
        self.tab_states.remove(tab)
        with QSignalBlocker(self.tabbar):
            self.tabbar.removeTab(index)
        if tab is self._current:
            # Do not save the closing tab's view into its replacement.
            next_tab = self.tabbar.tabData(self.tabbar.currentIndex())
            self._current = next_tab
            self.show_tab()
            if next_tab.entries is None and not next_tab.loading:
                self.navigate(next_tab.provider, next_tab.path, remember=False)
        self.update_tab_labels()

    def reopen_tab(self):
        if not self.closed_tabs or len(self.tab_states) >= self.MAX_TABS:
            return
        tab = self.closed_tabs.pop()
        tab.loading = False
        tab.serial += 1
        self.tab_states.append(tab)
        index = self.tabbar.addTab(self.tab_title(tab))
        self.tabbar.setTabData(index, tab)
        self.tabbar.setCurrentIndex(index)
        self.update_tab_labels()

    def cycle_tab(self, delta):
        self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + delta) % self.tabbar.count())

    def tab_menu(self, point):
        index = self.tabbar.tabAt(point)
        if index < 0:
            return
        self.tabbar.setCurrentIndex(index)
        self.window.activate(self)
        menu = QMenu(self)
        menu.addAction(self.window.commands.actions["rename_tab"])
        menu.addAction(self.window.commands.actions["lock_tab"])
        menu.addSeparator()
        menu.addAction(tr('Duplicate tab'), lambda: self.new_tab())
        menu.addAction(self.window.commands.actions["move_tab_other"])
        menu.addAction(tr('Copy path'), self.copy_directory)
        menu.addAction(tr('Open in a new tab in the other panel'), lambda: self.window.other().new_tab(self.provider, self.path))
        menu.addSeparator()
        menu.addAction(tr('Close tab'), lambda: self.close_tab())
        menu.addAction(tr('Close other tabs'), self.close_other_tabs)
        menu.exec(self.tabbar.mapToGlobal(point))

    def rename_tab(self):
        from . import dialog_kit
        label = dialog_kit.ask_text(self.window, tr('Name tab'), tr('Name tab'), tr('Name (empty = automatic):'), self._current.label,
                                    subtitle=self.location(), allow_empty=True)
        if label is not None:
            self._current.label = label.strip()[:80]
            self.update_tab_labels()

    def toggle_lock(self):
        self._current.locked = not self._current.locked
        self.update_tab_labels()

    def close_other_tabs(self):
        keep = self._current
        for index in range(self.tabbar.count() - 1, -1, -1):
            if self.tabbar.tabData(index) is not keep:
                self.close_tab(index)

    def navigate(self, provider, path, remember=True, *, tab=None, background=False, restore=None, direction=None, focus_name=None, quiet=False):
        """quiet: an automatic refresh; errors go to the log and a vanished
        local folder falls back to its nearest existing parent."""
        tab = tab or self._current
        if tab not in self.tab_states:
            return
        if isinstance(provider, LocalProvider):
            path = os.path.abspath(os.path.expanduser(path))
        elif not path.startswith("/"):
            path = "/" + path
        if tab.locked and self.location_key(provider, path) != self.location_key(tab.provider, tab.path):
            return self.new_tab(provider, path)
        if tab is self._current:
            self.save_view()
        tab.serial += 1
        serial = tab.serial
        previous = LocationState(tab.provider, tab.path, self.view_state(tab))
        finder = isinstance(provider, LocalProvider) and self.needs_finder_dates()
        tab.loading = True
        if tab is self._current and not background:
            self.set_listing_enabled(False)
            self.footer.setText(tr('Loading…'))

        def read(target):
            return provider.list(target, finder_dates=True) if finder else provider.list(target)

        def listing(_):
            target = path
            if quiet and isinstance(provider, LocalProvider):
                while not os.path.isdir(target) and os.path.dirname(target) != target:
                    target = os.path.dirname(target)
            try:
                return target, read(target), None
            except NotADirectoryError:
                if not isinstance(provider, LocalProvider) and not (
                    isinstance(provider, ArchiveProvider) and target.strip("/") in provider.members):
                    raise
                parent = provider.parent(target)
                return parent, read(parent), PurePosixPath(target).name if isinstance(provider, ArchiveProvider) else Path(target).name

        def loaded(result):
            if tab not in self.tab_states or tab.serial != serial:
                return
            actual_path, entries, select_name = result
            same = self.location_key(provider, actual_path) == self.location_key(previous.provider, previous.path)
            if same and tab is self._current and self.tree.isEnabled():
                self.save_view()
            if same and tab is self._current and tab.entries:
                before = {e.name: (e.size, e.modified) for e in tab.entries}
                for entry in entries:  # Rewritten images must not keep a stale thumbnail.
                    if before.get(entry.name, (entry.size, entry.modified)) != (entry.size, entry.modified):
                        self.model.thumbnails.pop(entry.name, None)
            if remember and not same:
                tab.history.append(previous)
                tab.history = tab.history[-50:]
                tab.future.clear()
            if not same:
                view = restore or tab.views.get(self.location_key(provider, actual_path)) or ViewState(column=tab.column, descending=tab.descending)
                self.restore_view(tab, view)
                child = focus_name or (self.ancestor_child(previous, provider, actual_path) if restore is None else None)
                if child:
                    tab.current = child
                    if tab.query.casefold() not in child.casefold():
                        tab.query = ""
                    if not tab.selected:
                        tab.selected = {child}
            elif restore is not None:
                self.restore_view(tab, restore)
            if direction == "back":
                tab.history.pop()
                tab.future.append(previous)
            elif direction == "forward":
                tab.future.pop()
                tab.history.append(previous)
            tab.provider, tab.path, tab.entries, tab.loading = provider, actual_path, entries, False
            tab.finder_dates, tab.loaded_at = finder, time.monotonic()
            if focus_name:
                tab.current, tab.selected = focus_name, {focus_name}
            if select_name:
                tab.selected, tab.current = {select_name}, select_name
            if tab is self._current:
                self.show_tab()
                if self.window.settings.value("auto_sizes", False, type=bool):
                    missing = [e for e in entries if e.is_dir and e.name not in tab.sizes.get(self.location_key(provider, actual_path), {})]
                    self.window.calculate_sizes(missing, self)
            else:
                self.update_tab_labels()

        def failed(message):
            if tab not in self.tab_states or tab.serial != serial:
                return
            tab.loading = False
            if quiet:
                if tab is self._current:
                    self.show_tab()
                self.window.log.appendPlainText(tr('Automatic refresh · {v0}').format(v0=message))
            elif tab is self._current:
                self.show_tab()
                self.window.error(message)
            else:
                tab.entries = None
                self.window.log.appendPlainText(tr('Tab {v0} · {v1}').format(v0=self.tab_title(tab), v1=message))
        self.window.run_task(listing, loaded, failed, quiet=quiet, read_only=True)

    def quick_view_active(self):
        return self.quick is not None and self.body.currentWidget() is self.quick

    def open_quick_view(self):
        if self.quick is None:
            from .quick_view import QuickView
            self.quick = QuickView(self)
            self.body.addWidget(self.quick)
        self.body.setCurrentWidget(self.quick)

    def close_quick_view(self):
        self.body.setCurrentWidget(self.file_stack)

    def needs_finder_dates(self):
        if sys.platform != "darwin":
            return False
        columns = (IDS["added"], IDS["opened"])
        return self.model.column in columns or any(not self.tree.isColumnHidden(column) for column in columns)

    def ensure_finder_dates(self):
        tab = self._current
        if (tab.entries is not None and not tab.loading and not tab.finder_dates
                and isinstance(tab.provider, LocalProvider) and self.needs_finder_dates()):
            self.navigate(tab.provider, tab.path, remember=False, background=True, quiet=True)

    def configure_auto_refresh(self):
        seconds = self.window.settings.value("auto_refresh_interval", 0, type=int)
        self.poll_timer.start(seconds * 1000) if seconds > 0 else self.poll_timer.stop()
        self.update_watch()

    def update_watch(self):
        tab = self._current
        enabled = self.window.settings.value("auto_refresh", True, type=bool)
        watched = enabled and isinstance(tab.provider, LocalProvider) and tab.entries is not None
        self.watcher.watch(tab.path if watched else None)

    def auto_refresh(self, reason="change"):
        """Reload the shown folder in place, keeping cursor, selection and scroll.

        change: the watched local folder changed; activate: the user returned to
        the application (catches edits inside files and network volumes);
        poll: the optional periodic refresh, including remote locations.
        """
        tab = self._current
        if tab.loading or tab.entries is None or isinstance(tab.provider, ArchiveProvider) or not self.isVisible():
            return
        if reason == "activate" and (not isinstance(tab.provider, LocalProvider) or time.monotonic() - tab.loaded_at < 1):
            return
        if reason == "poll" and QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            return
        busy = QApplication.mouseButtons() != Qt.MouseButton.NoButton or QApplication.activePopupWidget() is not None
        try:
            busy = busy or self.active_view().state() != QTreeView.State.NoState
        except (AttributeError, RuntimeError):
            pass
        if busy:  # Let a drag, edit or open menu finish against the listing it started with.
            if reason == "change":
                self.watcher.timer.start()
            return
        self.navigate(tab.provider, tab.path, remember=False, background=True, quiet=True)

    def refresh(self):
        self.appearance.invalidate()
        self._volume_loaded_at = 0
        self._current.sizes.pop(self.location_key(self.provider, self.path), None)
        if isinstance(self.provider, ArchiveProvider):
            self.open_archive(self.provider.filename, self.path, self.provider.password)
        else:
            self.navigate(self.provider, self.path)

    def open_archive(self, filename, path="/", password=None, *, tab=None):
        tab = tab or self._current
        self.save_view()
        tab.serial += 1
        serial = tab.serial
        tab.loading = True
        if tab is self._current:
            self.set_listing_enabled(False)
            self.footer.setText(tr('Reading archive contents…'))

        def loaded(provider):
            if tab not in self.tab_states or tab.serial != serial:
                return
            if provider.encrypted and not provider.password:
                from . import dialog_kit
                secret = dialog_kit.ask_text(self.window, tr('Archive password'), tr('This archive is encrypted'), tr('Password:'),
                                             subtitle=Path(filename).name, action=tr('Open'), icon="pack", password=True)
                if secret is None:
                    tab.loading = False
                    if tab is self._current:
                        self.show_tab()
                    return
                provider.password = secret.encode("utf-8")
            self.navigate(provider, path, tab=tab)

        def failed(message):
            if tab in self.tab_states and tab.serial == serial:
                tab.loading = False
                if tab is self._current:
                    self.show_tab()
                    self.window.error(message)
        self.window.run_task(lambda _: ArchiveProvider(filename, password), loaded, failed, read_only=True)

    def parent(self):
        if isinstance(self.provider, ArchiveProvider) and self.path == "/":
            self.navigate(LocalProvider(), str(Path(self.provider.filename).parent))
        else:
            self.navigate(self.provider, self.provider.parent(self.path))

    def root(self):
        root = Path(self.path).anchor if isinstance(self.provider, LocalProvider) else "/"
        self.navigate(self.provider, root or "/")

    def enter_directory(self):
        entry = self.current_entry()
        if entry and entry.is_dir:
            self.navigate(self.provider, self.provider.join(self.path, entry.name))
        elif entry and is_archive(entry.name) and isinstance(self.provider, LocalProvider):
            self.open_current()

    def open_directory_new_tab(self):
        entry = self.current_entry()
        if entry and entry.is_dir:
            self.new_tab(self.provider, self.provider.join(self.path, entry.name))

    def open_current(self):
        index = self.tree.currentIndex()
        if not index.isValid() or not self.tree.isEnabled():
            return
        entry = index.data(Qt.ItemDataRole.UserRole)
        if entry is None:
            self.parent()
        elif entry.is_dir and entry.name.lower().endswith(".app") and isinstance(self.provider, LocalProvider) and sys.platform == "darwin":
            self.window.associations.open([self.provider.join(self.path, entry.name)], system=True)
        elif entry.is_dir:
            self.navigate(self.provider, self.provider.join(self.path, entry.name))
        elif is_archive(entry.name) and isinstance(self.provider, LocalProvider):
            self.open_archive(self.provider.join(self.path, entry.name))
        elif isinstance(self.provider, LocalProvider):
            self.window.associations.open([self.provider.join(self.path, entry.name)])
        else:
            self.window.show_preview(self)

    def selected(self):
        if not self.tree.isEnabled():
            return []
        return [entry for index in sorted(self.tree.selectionModel().selectedRows(), key=lambda i: i.row())
                if (entry := index.data(Qt.ItemDataRole.UserRole))]

    def current_entry(self):
        return self.model.entry(self.tree.currentIndex().row()) if self.tree.isEnabled() else None

    def action_entries(self):
        marked = self.selected()
        current = self.current_entry()
        return marked or ([current] if current else [])

    def toggle_mark(self):
        entry = self.current_entry()
        if entry and entry.is_dir and not entry.is_link:
            self.window.calculate_sizes([entry], self)
        index = self.tree.currentIndex()
        if not self.tree.isEnabled() or not self.model.entry(index.row()):
            return
        selection = self.tree.selectionModel()
        selection.select(index, QItemSelectionModel.SelectionFlag.Toggle | QItemSelectionModel.SelectionFlag.Rows)
        if index.row() + 1 < self.model.rowCount():
            selection.setCurrentIndex(self.model.index(index.row() + 1, 0), QItemSelectionModel.SelectionFlag.NoUpdate)

    def invert_selection(self):
        if not self.tree.isEnabled():
            return
        from PySide6.QtCore import QItemSelection
        start = int(self.model.has_parent)
        if self.model.rowCount() > start:
            selection = QItemSelection(self.model.index(start, 0), self.model.index(self.model.rowCount() - 1, 3))
            self.tree.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.Toggle | QItemSelectionModel.SelectionFlag.Rows)

    def refresh_control_labels(self):
        # Buttons retain their semantic role; tooltips use the same live bindings as menus.
        for button in self.findChildren(QPushButton, "pathButton"):
            text = button.text()
            command = {"↑": "parent", "⧉": "copy_directory", "↳": "paste_path", "↻": "refresh"}.get(text)
            if command:
                from .commands import BY_ID
                button.setToolTip(BY_ID[command].title + "  " + self.window.commands.key_label(command))
        self.new_tab_button.setToolTip(tr('New tab  ') + self.window.commands.key_label("new_tab"))
        self.filter.setPlaceholderText(tr('Quick filename filter…  ') + self.window.commands.key_label("filter"))

    def show_drives(self):
        self.window.activate(self)
        self.drive_button.showMenu()

    def show_context_menu(self):
        view = self.active_view()
        index = view.currentIndex()
        self.file_menu(view.visualRect(index).center(), view)

    def history_menu(self):
        menu = QMenu(self)
        for location in reversed(self.history[-30:]):
            menu.addAction(location.path, lambda checked=False, target=location:
                           self.navigate(target.provider, target.path, restore=target.view))
        if menu.isEmpty():
            action = menu.addAction(tr('History is empty'))
            action.setEnabled(False)
        menu.exec(self.address.mapToGlobal(self.address.rect().bottomLeft()))

    def apply_filter(self):
        self.filter_timer.stop()
        self._current.query = self.filter.text()
        self.model.set_filter(self.filter.text(), self.window.hidden.isChecked())
        self.update_footer()

    def update_footer(self):
        selected = self.selected()
        self.footer.setText(tr('{v0} items  │  {v1} selected  │  {v2}').format(v0=f'{len(self.model.visible):,}', v1=len(selected), v2=size_text(sum(self.model.directory_sizes.get(e.name, 0) if e.is_dir else e.size for e in selected)) + (tr(' + unknown folders') if any(e.is_dir and e.name not in self.model.directory_sizes for e in selected) else '')))

    def back(self):
        if self.history:
            target = self.history[-1]
            self.navigate(target.provider, target.path, remember=False, restore=target.view, direction="back")

    def forward(self):
        if self.future:
            target = self.future[-1]
            self.navigate(target.provider, target.path, remember=False, restore=target.view, direction="forward")

    def location(self, tab=None, path=None):
        tab = tab or self._current
        path = tab.path if path is None else path
        provider = tab.provider
        if isinstance(provider, DeviceProvider):
            return provider.location(path)
        if isinstance(provider, ArchiveProvider):
            return "archive:" + Path(provider.filename).as_uri().replace("!", "%21") + "!/" + quote(path.lstrip("/"), safe="/")
        if isinstance(provider, RemoteProvider):
            c = provider.connection
            host = f"[{c.host}]" if ":" in c.host else c.host
            return f"{c.protocol.lower()}://{quote(c.username, safe='')}@{host}:{c.port}/" + quote(path.lstrip("/"), safe="/")
        return path

    def copy_directory(self):
        QApplication.clipboard().setText(self.location())
        self.window.statusBar().showMessage(tr('Folder path copied to clipboard'), 3000)

    def copy_paths(self):
        entries = self.selected()
        paths = [self.location(path=self.provider.join(self.path, entry.name)) for entry in entries]
        QApplication.clipboard().setText("\n".join(paths) if paths else self.location())
        self.window.statusBar().showMessage(tr('Full path copied to clipboard'), 3000)

    def paste_path(self):
        self.navigate_text(QApplication.clipboard().text())

    def navigate_text(self, text):
        self.window.activate(self)
        text = text.strip()
        if len(text) > 1 and text[0] == text[-1] and text[0] in ("'", '"'):
            text = text[1:-1]
        if not text or "\0" in text or "\n" in text or "\r" in text:
            return self.window.error(tr('Enter one valid folder or file path.'))
        try:
            import re
            if re.match(r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/|$)", text):
                text = "ftp://" + text
            if text.startswith('soovee-device://'):
                url = urlsplit(text)
                dialog = getattr(self.window, 'devices_dialog', None)
                service = getattr(dialog, 'service', None)
                if service is None:
                    raise ValueError(tr('Enable Soovee Transfers first.'))
                self.navigate(DeviceProvider(service, url.netloc), unquote(url.path) or '/')
                return
            if text.startswith("archive:"):
                filename, inner = text[len("archive:"):].split("!/", 1)
                local = QUrl(filename)
                if not local.isLocalFile():
                    raise ValueError(tr('Invalid archive path.'))
                self.open_archive(local.toLocalFile(), "/" + unquote(inner))
                return
            if text.lower().startswith(("ftp://", "ftps://", "sftp://")):
                self.window.open_remote_url(self, text)
                return
            local_url = text.lower().startswith("file://")
            if local_url:
                text = QUrl(text).toLocalFile()
            if local_url or isinstance(self.provider, LocalProvider):
                expanded = os.path.expanduser(os.path.expandvars(text))
                text = expanded if os.path.isabs(expanded) else os.path.join(self.path, expanded)
                if is_archive(text):
                    self.open_archive(text)
                else:
                    self.navigate(LocalProvider() if local_url else self.provider, text)
            else:
                import posixpath
                self.navigate(self.provider, posixpath.normpath(posixpath.join(self.path, text)))
        except (ValueError, OSError) as exc:
            self.window.error(str(exc))

    def update_breadcrumbs(self):
        while self.crumbs.count():
            item = self.crumbs.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        path = Path(self.path) if isinstance(self.provider, LocalProvider) else PurePosixPath(self.path)
        ancestors = list(reversed([path] + list(path.parents)))
        if len(ancestors) > 5:
            ancestors = [ancestors[0]] + ancestors[-4:]
        for ancestor in ancestors:
            name = ancestor.name or ancestor.anchor or "/"
            button = QPushButton(name)
            button.setObjectName("crumbButton")
            button.setMaximumWidth(140)
            button.setToolTip(str(ancestor))
            button.clicked.connect(lambda checked=False, p=str(ancestor): self.navigate(self.provider, p))
            self.crumbs.addWidget(button)
        self.crumbs.addStretch()

    def populate_drives(self, menu):
        menu.clear()
        dialog = getattr(self.window, 'devices_dialog', None)
        service = getattr(dialog, 'service', None)
        if service is not None and service.shares.mode != 'controlled':
            for peer in service.store.peers():
                menu.addAction('Soovee · ' + peer.name, lambda checked=False, identity=peer.id: self.navigate(DeviceProvider(service, identity), '/'))
            menu.addSeparator()
        for volume in self._drives_cache or ():
            action = menu.addAction(volume.name + '  ·  ' + capacity_text(volume),
                                    lambda checked=False, p=volume.root: self.navigate(LocalProvider(), p))
            action.setToolTip(volume.root + '\n' + capacity_text(volume))
        if self._drives_cache is None:
            menu.addAction(tr('Reading drives…')).setEnabled(False)
        elif not self._drives_cache:
            menu.addAction(tr('No available drives')).setEnabled(False)
        if self._drives_busy or time.monotonic() - self._drives_loaded_at < 15:
            return
        self._drives_busy = True

        def loaded(volumes):
            if not isValid(self):
                return
            self._drives_busy = False
            self._drives_cache = volumes
            self._drives_loaded_at = time.monotonic()
            if isValid(menu) and menu.isVisible():
                self.populate_drives(menu)

        def failed(message):
            logging.getLogger(__name__).warning('Drive information unavailable: %s', message)
            loaded(())
        self.window.run_task(lambda _: read_volumes(), loaded, failed, read_only=True)

    def refresh_storage(self, *, force=False):
        provider = self.provider
        source = self.path if isinstance(provider, LocalProvider) else provider.filename if isinstance(provider, ArchiveProvider) else (provider.peer_id, self.path) if isinstance(provider, DeviceProvider) else None
        if source != self._volume_key:
            self._volume_key = source
            self._volume_info = None
            self._volume_loaded_at = 0
        self.render_storage()
        if source is None or self._volume_busy or (not force and time.monotonic() - self._volume_loaded_at < 10):
            return
        self._volume_busy = True

        def loaded(info):
            if not isValid(self):
                return
            self._volume_busy = False
            if source != self._volume_key:
                self.refresh_storage()
                return
            self._volume_info = info
            self._volume_loaded_at = time.monotonic()
            self.render_storage()

        def failed(message):
            logging.getLogger(__name__).warning('Disk information unavailable: %s', message)
            loaded(None)
        def read(_):
            if isinstance(provider, DeviceProvider):
                value = provider.space(source[1])
                if value is None: return None
                from .storage import VolumeInfo
                name = provider.label + ' · ' + value['name']
                return VolumeInfo(name, value['path'], value['total'], value['free'], value['available'], value['readonly'], 'Soovee')
            return read_volume(source)
        self.window.run_task(read, loaded, failed, read_only=True)

    def render_storage(self):
        info = self._volume_info
        name = info.name if info else tr('Drive')
        if self._volume_key is None:
            name = self.provider.label
        self.drive_button.set_caption(name)
        self.drive_button.setAccessibleName(name)
        self.drive_button.setToolTip(name + ('\n' + info.root if info else '') + '\n' + tr('Choose drive'))
        self.disk_summary.set_volume(info, loading=self._volume_key is not None and not self._volume_loaded_at)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'disk_summary'):
            self.render_storage()

    def columns_changed(self, *args):
        if not self._columns_loading:
            self.columns_timer.start()

    def column_resized(self, logical, old_size, new_size):
        if new_size >= 40 and not getattr(getattr(self.tree, 'frozen_columns', None), 'busy', False):
            self._column_widths[logical] = min(3000, new_size)
            if logical == 0 and self.auto_fit_columns and not self._columns_loading:
                self.auto_fit_columns = False
                self.window.settings.setValue('auto_fit_columns_' + self.side, False)
        self.columns_changed()

    def column_layout(self):
        header = self.tree.header()
        return [{"id": COLUMNS[logical][0], "visible": not self.tree.isColumnHidden(logical),
                 "width": max(40, min(3000, self._column_widths[logical])),
                 "label": self.model.labels[logical], "align": self.model.alignments[logical]}
                for logical in (header.logicalIndex(visual) for visual in range(len(COLUMNS)))]

    def apply_columns(self, columns, persist=True):
        columns = validate_columns(columns)
        self._columns_loading = True
        header = self.tree.header()
        with QSignalBlocker(header):
            for visual, item in enumerate(columns):
                logical = IDS[item["id"]]
                header.moveSection(header.visualIndex(logical), visual)
                self._column_widths[logical] = item["width"]
                self.tree.setColumnHidden(logical, not item["visible"])
                self.tree.setColumnWidth(logical, item["width"])
                self.model.labels[logical] = item["label"]
                self.model.alignments[logical] = item["align"]
        self._columns_loading = False
        controller = getattr(self.tree, 'frozen_columns', None)
        if controller is not None:
            controller.reordered()
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        if self.model.rowCount():
            self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(self.model.rowCount() - 1, len(COLUMNS) - 1))
        if persist:
            self.save_columns()

    def save_columns(self):
        if not self._columns_loading:
            self.columns_timer.stop()
            self.window.settings.setValue(self.column_settings_key, json.dumps(self.column_layout(), ensure_ascii=False))
            if hasattr(self.tree, 'frozen_columns'):
                self.window.settings.setValue('name_position_' + self.side, self.tree.frozen_columns.name_position)

    def set_scrolling(self, *, pinned=None, vertical_only=None, auto_fit=None):
        changed_pin = pinned is not None and self.pin_name != pinned
        if pinned is not None:
            self.pin_name = bool(pinned)
        if vertical_only is not None:
            self.vertical_scroll_only = bool(vertical_only)
        if auto_fit is not None:
            self.auto_fit_columns = bool(auto_fit)
        controller = self.tree.frozen_columns
        if changed_pin:
            controller.set_pinned(self.pin_name)
        else:
            controller.layout()
        for key, value in [('pin_name', self.pin_name), ('vertical_scroll_only', self.vertical_scroll_only), ('auto_fit_columns', self.auto_fit_columns)]:
            self.window.settings.setValue(key + '_' + self.side, value)
        self.save_columns()
        self.window.settings.sync()

    def configure_scrolling(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle(tr('Panel scrolling'))
        layout = QVBoxLayout(dialog)
        fields = []
        for label, value in [('Keep Name fixed on the left', self.pin_name),
                             ('Block horizontal scroll gestures over the file list', self.vertical_scroll_only),
                             ('Fit columns to the panel when there is enough room', self.auto_fit_columns)]:
            field = QCheckBox(tr(label)); field.setChecked(value); layout.addWidget(field); fields.append(field)
        note = QLabel(tr('Manual horizontal scrolling remains available. Custom widths are remembered; narrow panels may still need the scrollbar.'))
        note.setWordWrap(True); layout.addWidget(note)
        both = QCheckBox(tr('Apply the same settings to the other panel')); layout.addWidget(both)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply)
        def apply_settings():
            values = dict(pinned=fields[0].isChecked(), vertical_only=fields[1].isChecked(), auto_fit=fields[2].isChecked())
            self.set_scrolling(**values)
            if both.isChecked():
                other = self.window.right if self is self.window.left else self.window.left
                other.set_scrolling(**values)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply_settings)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            apply_settings()

    def configure_columns(self):
        dialog = ColumnsDialog(self)
        dialog.exec()

    def set_column_separators(self, enabled):
        self.column_separators = bool(enabled)
        self.window.settings.setValue('column_separators_' + self.side, self.column_separators)
        self.window.settings.sync()
        self.tree.viewport().update()
        self.tree.frozen_columns.view.viewport().update()

    def column_menu(self, point):
        menu = QMenu(self)
        stable = menu.addAction(tr('Stable scrolling (fixed names + vertical gestures)'))
        stable.setCheckable(True); stable.setChecked(self.pin_name and self.vertical_scroll_only)
        stable.toggled.connect(lambda enabled: self.set_scrolling(pinned=enabled, vertical_only=enabled))
        menu.addAction(tr('Panel appearance…'), self.appearance.configure)
        menu.addAction(tr('Panel scrolling…'), self.configure_scrolling)
        menu.addSeparator()
        menu.addAction(tr('Configure columns…'), self.configure_columns)
        separators = menu.addAction(tr('Vertical column separators'))
        separators.setCheckable(True); separators.setChecked(self.column_separators)
        separators.toggled.connect(self.set_column_separators)
        menu.addSeparator()
        for logical, column in enumerate(COLUMNS):
            action = menu.addAction(tr(column[1]))
            action.setCheckable(True)
            action.setChecked(not self.tree.isColumnHidden(logical))
            action.setEnabled(logical != 0)
            action.toggled.connect(lambda checked, index=logical: self.toggle_column(index, checked))
        menu.addSeparator()
        menu.addAction(tr('Restore default columns'), lambda: self.apply_columns(default_columns()))
        menu.exec(self.tree.header().mapToGlobal(point))
        menu.deleteLater()

    def toggle_column(self, logical, visible):
        if logical == 0 and not visible:
            return
        self.tree.setColumnHidden(logical, not visible)
        if visible:
            self.tree.setColumnWidth(logical, self._column_widths[logical])
        self.save_columns()

    def associations_changed(self):
        if self.model.rowCount():
            self.model.dataChanged.emit(self.model.index(0, 5), self.model.index(self.model.rowCount() - 1, 5))
        if self.model.column == 5:
            self.model.sort(5, Qt.SortOrder.DescendingOrder if self.model.descending else Qt.SortOrder.AscendingOrder)

    def local_file_paths(self):
        return [self.provider.join(self.path, entry.name) for entry in self.action_entries() if not entry.is_dir or entry.name.lower().endswith(".app")] if isinstance(self.provider, LocalProvider) else []

    def build_file_menu(self, point=None):
        self.window.activate(self)
        if point is not None:
            index = self.tree.indexAt(point)
            if index.isValid() and not self.tree.selectionModel().isSelected(index):
                self.tree.setCurrentIndex(index)
            elif index.isValid():
                self.tree.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        menu = QMenu(self)
        commands = self.window.commands.actions
        menu.addAction(commands["open"])
        paths = self.local_file_paths()
        if paths:
            submenu = menu.addMenu(tr('Open with'))
            submenu.setObjectName("openWithMenu")
            submenu.addAction(tr('Choose another application…'), lambda: self.window.show_open_with(paths))
            submenu.addAction(tr('System default application'), lambda: self.window.associations.open(paths, system=True))
            submenu.addSeparator()
            loading = submenu.addAction(tr('Finding available applications…'))
            loading.setEnabled(False)
            def loaded(apps):
                if not isValid(submenu):
                    return
                submenu.removeAction(loading)
                loading.deleteLater()
                custom = self.window.associations.custom.get(extension(Path(paths[0]).name))
                candidates = list(apps)
                if custom and custom not in {a.path for a in candidates}:
                    from .native_apps import Application
                    candidates.insert(0, Application(custom, Path(custom).stem))
                for app in candidates:
                    label = app.name + (tr(' · custom default') if app.path == custom else "")
                    action = submenu.addAction(label, lambda checked=False, selected=app: self.window.associations.open(paths, selected))
                    action.setToolTip(app.path)
            self.window.run_task(lambda _: applications_for_file(paths[0]), loaded, lambda _: loaded([]), read_only=True)
        menu.addAction(commands["view"])
        menu.addAction(commands["edit"])
        menu.addSeparator()
        for name in ("clipboard_copy", "clipboard_cut", "clipboard_paste"):
            menu.addAction(commands[name])
        menu.addSeparator()
        for name in ("rename", "copy", "move", "mkdir", "delete", "delete_permanent", "multi_rename", "pack"):
            menu.addAction(commands[name])
        if not self.provider.readonly:
            menu.addMenu(self.window.new_menu(menu))
        entry = self.current_entry()
        if isinstance(self.provider, LocalProvider) and any(not e.is_dir and is_archive(e.name) for e in self.action_entries()):
            menu.addAction(commands["extract"])
        if entry and entry.is_dir:
            target = self.provider.join(self.path, entry.name)
            menu.addSeparator()
            menu.addAction(tr('Open folder in new tab'), lambda: self.new_tab(self.provider, target))
            menu.addAction(tr('Open in a tab in the other panel'), lambda: self.window.other().new_tab(self.provider, target))
            if entry.name.lower().endswith(".app") and isinstance(self.provider, LocalProvider):
                menu.addAction(tr('Show package contents'), lambda: self.navigate(self.provider, target))
            menu.addAction(commands["folder_sizes"])
        menu.addSeparator()
        for name in ("copy_paths", "copy_directory", "copy_names", "copy_details", "properties"):
            menu.addAction(commands[name])
        if isinstance(self.provider, LocalProvider):
            menu.addAction(commands["reveal"])
        return menu

    def file_menu(self, point, view=None):
        menu = self.build_file_menu(point)
        menu.exec((view or self.active_view()).viewport().mapToGlobal(point))
        menu.deleteLater()

    def saved_tabs(self):
        self.save_view()
        tabs, active = [], 0
        for index in range(self.tabbar.count()):
            tab = self.tabbar.tabData(index)
            if isinstance(tab.provider, LocalProvider):
                if tab is self._current:
                    active = len(tabs)
                tabs.append({"path": tab.path, "filter": tab.query, "column": tab.column, "descending": tab.descending, "label": tab.label, "locked": tab.locked})
        return {"tabs": tabs, "active": active}

    def restore_tabs(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("tabs"), list):
            return
        valid = [item for item in data["tabs"][:self.MAX_TABS] if isinstance(item, dict)
                 and isinstance(item.get("path"), str) and os.path.isabs(item["path"])]
        if not valid:
            return
        # Invalidate the initial listing; restored tabs load on first activation.
        for tab in self.tab_states:
            tab.serial += 1
        with QSignalBlocker(self.tabbar):
            while self.tabbar.count():
                self.tabbar.removeTab(0)
            self.tab_states = []
            for item in valid:
                column = item.get("column", 0)
                tab = TabState(LocalProvider(), item["path"], query=str(item.get("filter", "")),
                               column=column if type(column) is int and 0 <= column < len(COLUMNS) else 0,
                               descending=bool(item.get("descending", False)),
                               label=str(item.get("label", ""))[:80], locked=bool(item.get("locked", False)))
                self.tab_states.append(tab)
                index = self.tabbar.addTab(self.tab_title(tab))
                self.tabbar.setTabData(index, tab)
            active = data.get("active", 0)
            active = active if type(active) is int and 0 <= active < len(valid) else 0
            self.tabbar.setCurrentIndex(active)
        self._current = self.tabbar.tabData(active)
        self.show_tab()
        self.navigate(self.provider, self.path, remember=False)
