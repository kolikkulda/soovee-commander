"""Resizable panels with an explicit, stable 50:50 reset."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QSplitter, QSplitterHandle


class PanelHandle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.splitter().center_panels()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class PanelSplitter(QSplitter):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("panelSplitter")
        self.setChildrenCollapsible(False)
        self.setHandleWidth(9)
        self.balanced = True
        self._centering = False
        self.splitterMoved.connect(self.moved)

    def createHandle(self):
        return PanelHandle(self.orientation(), self)

    def moved(self, position, index):
        if not self._centering:
            self.balanced = False

    def center_panels(self):
        if self.count() != 2:
            return
        self.balanced = True
        self._centering = True
        available = max(2, self.width() - self.handleWidth())
        self.setSizes([available // 2, available - available // 2])
        self._centering = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.balanced:
            self.center_panels()
