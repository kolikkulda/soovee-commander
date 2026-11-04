"""Movable pane tabs with private, in-process cross-pane drag transfers."""
import uuid

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, QSize, QTimer
from PySide6.QtGui import QDrag, QMouseEvent, QPainter, QPen, QColor
from PySide6.QtWidgets import QApplication, QTabBar, QToolButton
from .themes import THEMES

MIME = 'application/x-soovee-commander-tab'


class TabCloseButton(QToolButton):
    """An explicit hit box and painted cross, independent of native button padding."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('tabClose')
        self.setFixedSize(18, 18)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = THEMES[self.parent().panel.window.theme_key]
        color = QColor(colors['text'])
        if self.underMouse() or self.isDown():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors['hover']))
            painter.drawRoundedRect(self.rect(), 5, 5)
        painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        center = self.rect().center()
        painter.drawLine(center + QPoint(-3, -3), center + QPoint(3, 3))
        painter.drawLine(center + QPoint(-3, 3), center + QPoint(3, -3))


class PanelTabBar(QTabBar):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setAcceptDrops(True)
        self._pressed_tab = None
        self._press_position = QPoint()
        self._drag_token = None
        self.setMouseTracking(True)

    def tabSizeHint(self, index):
        width = self.fontMetrics().horizontalAdvance(self.tabText(index)) + 54
        return QSize(max(110, min(230, width)), 38)

    def minimumTabSizeHint(self, index):
        return QSize(86, 38)

    def position_close_buttons(self):
        for index in range(self.count()):
            button = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if button is not None:
                rect = self.tabRect(index)
                button.setGeometry(rect.right() - 27, rect.center().y() - 8, 18, 18)

    def tabLayoutChange(self):
        super().tabLayoutChange()
        self.position_close_buttons()
        QTimer.singleShot(0, self.position_close_buttons)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_close_buttons()

    def paintEvent(self, event):
        self.position_close_buttons()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = THEMES[self.panel.window.theme_key]
        for index in range(self.count()):
            rect = self.tabRect(index).adjusted(3, 3, -3, -3)
            selected = index == self.currentIndex()
            hovered = rect.contains(self.mapFromGlobal(self.cursor().pos()))
            painter.setPen(QPen(QColor(colors['accent'] if selected else colors['border']), 1))
            painter.setBrush(QColor(colors['surface'] if selected else colors['hover'] if hovered else colors['header']))
            painter.drawRoundedRect(rect, 7, 7)
            font = self.font(); font.setBold(selected); painter.setFont(font)
            painter.setPen(QColor(colors['text'] if selected else colors['muted']))
            text_rect = rect.adjusted(12, 0, -30 if self.tabsClosable() else -10, 0)
            text = painter.fontMetrics().elidedText(self.tabText(index), Qt.TextElideMode.ElideMiddle, max(1, text_rect.width()))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if self.hasFocus() and self.currentIndex() >= 0:
            painter.setPen(QPen(QColor(colors['accent']), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.tabRect(self.currentIndex()).adjusted(6, 6, -6, -6), 5, 5)

    def mousePressEvent(self, event):
        index = self.tabAt(event.position().toPoint())
        self._pressed_tab = self.tabData(index) if event.button() == Qt.MouseButton.LeftButton and index >= 0 else None
        self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed_tab = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        outside = not self.rect().contains(event.position().toPoint())
        distance = (event.position().toPoint() - self._press_position).manhattanLength()
        if self._pressed_tab is not None and event.buttons() & Qt.MouseButton.LeftButton and outside and distance >= QApplication.startDragDistance():
            tab = self._pressed_tab
            self._pressed_tab = None
            # End Qt's own within-bar move before starting a cross-pane drag.
            release = QMouseEvent(QEvent.Type.MouseButtonRelease, event.position(), event.globalPosition(), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, event.modifiers())
            super().mouseReleaseEvent(release)
            if tab.loading:
                return
            self._drag_token = uuid.uuid4().hex
            self._drag_tab = tab
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(MIME, self._drag_token.encode('ascii'))
            drag.setMimeData(mime)
            index = next((i for i in range(self.count()) if self.tabData(i) is tab), -1)
            if index >= 0:
                drag.setPixmap(self.grab(self.tabRect(index)))
            try:
                drag.exec(Qt.DropAction.MoveAction)
            finally:
                self._drag_token = None
                self._drag_tab = None
            return
        super().mouseMoveEvent(event)

    def source_tab(self, event):
        source = event.source()
        if not isinstance(source, PanelTabBar) or source is self or source.panel.window is not self.panel.window:
            return None
        if not source._drag_token or bytes(event.mimeData().data(MIME)).decode('ascii', errors='replace') != source._drag_token:
            return None
        tab = source._drag_tab
        if tab not in source.panel.tab_states or tab.loading or len(self.panel.tab_states) >= self.panel.MAX_TABS:
            return None
        return source.panel, tab

    def dragEnterEvent(self, event):
        if self.source_tab(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        item = self.source_tab(event)
        if item:
            source, tab = item
            index = self.tabAt(event.position().toPoint())
            if index < 0:
                index = self.count()
            elif event.position().x() > self.tabRect(index).center().x():
                index += 1
            if source.move_tab_to(tab, self.panel, index):
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
        event.ignore()
