"""Optional shared-model name overlay and conservative column fitting."""
from PySide6.QtCore import QObject, QEvent, QSignalBlocker, Qt
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHeaderView
from shiboken6 import isValid


class FrozenColumns(QObject):
    def __init__(self, panel, factory):
        super().__init__(panel.tree)
        self.panel, self.main = panel, panel.tree
        self.busy = False
        self.name_position = panel.window.settings.value('name_position_' + panel.side, 0, type=int)
        self.view = factory(self.main)
        self.view.panel = panel
        self.view.command_host = panel.window
        self.view.is_frozen = True
        self.view.setObjectName('frozenName')
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setModel(panel.model)
        self.view.setSelectionModel(self.main.selectionModel())
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionMode(self.main.selectionMode())
        self.view.setSelectionBehavior(self.main.selectionBehavior())
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.main.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.main.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for index in range(1, panel.model.columnCount()):
            self.view.setColumnHidden(index, True)
        self.view.setDragEnabled(True)
        self.view.setAcceptDrops(True)
        self.view.setDropIndicatorShown(True)
        self.view.setDragDropMode(self.main.dragDropMode())
        header = self.view.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.sectionResized.connect(self.resize_name)
        header.sectionClicked.connect(self.sort_name)
        self.main.header().sectionResized.connect(self.layout)
        self.main.header().sectionMoved.connect(self.reordered)
        self.main.header().sortIndicatorChanged.connect(self.sort_indicator)
        for source, target in ((self.main, self.view), (self.view, self.main)):
            source.verticalScrollBar().valueChanged.connect(target.verticalScrollBar().setValue)
        self.main.horizontalScrollBar().rangeChanged.connect(self.layout)
        self.main.horizontalScrollBar().valueChanged.connect(self.layout)
        self.view.activated_panel.connect(lambda: panel.window.activate(panel))
        self.view.pressed.connect(lambda *_: self.main.setFocus())
        self.view.doubleClicked.connect(lambda *_: panel.open_current())
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(lambda point: panel.file_menu(
            self.main.viewport().mapFromGlobal(self.view.viewport().mapToGlobal(point))))
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(lambda point: panel.column_menu(
            self.main.header().mapFromGlobal(header.mapToGlobal(point))))
        for item in (self.main.header().viewport(), header.viewport(), self.main.viewport()):
            item.installEventFilter(self)
        self.view.hide()
        self.sort_indicator(self.main.header().sortIndicatorSection(), self.main.header().sortIndicatorOrder())

    def eventFilter(self, watched, event):
        if not isValid(self.main) or not isValid(self.view):
            return False
        if watched is self.main.viewport() and event.type() == QEvent.Type.Resize:
            self.layout()
        if event.type() == QEvent.Type.Wheel and self.panel.vertical_scroll_only:
            self.main.wheelEvent(event)
            return True
        return False

    def sort_name(self):
        order = Qt.SortOrder.DescendingOrder if self.panel.model.column == 0 and not self.panel.model.descending else Qt.SortOrder.AscendingOrder
        self.main.sortByColumn(0, order)

    def sort_indicator(self, column, order):
        with QSignalBlocker(self.view.header()):
            self.view.header().setSortIndicator(0 if column == 0 else -1, order)

    def resize_name(self, logical, old, size):
        if self.busy or logical != 0:
            return
        self.panel._column_widths[0] = size
        if self.panel.auto_fit_columns:
            self.panel.auto_fit_columns = False
            self.panel.window.settings.setValue('auto_fit_columns_' + self.panel.side, False)
        self.layout()
        self.panel.columns_changed()

    def reordered(self, *args):
        if not self.busy and self.panel.pin_name and self.main.header().visualIndex(0) != 0:
            self.name_position = self.main.header().visualIndex(0)
        self.layout()

    def set_pinned(self, enabled, initial=False):
        header = self.main.header()
        if enabled:
            if not initial:
                self.name_position = header.visualIndex(0)
        elif not initial:
            with QSignalBlocker(header):
                header.moveSection(header.visualIndex(0), min(header.count() - 1, max(0, self.name_position)))
        header.setFirstSectionMovable(not enabled)
        self.layout()

    def layout(self, *args):
        if self.busy or not isValid(self.main) or not isValid(self.view):
            return
        self.busy = True
        try:
            panel, main, view = self.panel, self.main, self.view
            available = max(1, main.viewport().width())
            others = [i for i in range(1, panel.model.columnCount()) if not main.isColumnHidden(i)]
            width = panel._column_widths[0]
            if panel.auto_fit_columns:
                width = max(160, available - sum(main.columnWidth(i) for i in others))
            if panel.pin_name and others:
                width = min(width, max(40, int(available * .55)))
            elif panel.pin_name:
                width = min(width, available)
            width = max(40, min(3000, width))
            with QSignalBlocker(main.header()), QSignalBlocker(view.header()):
                if panel.pin_name:
                    main.header().moveSection(main.header().visualIndex(0), 0)
                main.setColumnWidth(0, width)
                view.header().setMaximumSectionSize(max(40, int(available * .55)) if panel.pin_name and others else 3000)
                view.setColumnWidth(0, width)
                view.header().setFixedHeight(main.header().height())
            view.setGeometry(main.frameWidth(), main.frameWidth(), min(width, available),
                             main.viewport().height() + main.header().height())
            view.setVisible(panel.pin_name)
            if panel.pin_name:
                view.raise_()
                view.verticalScrollBar().setValue(main.verticalScrollBar().value())
        finally:
            self.busy = False
