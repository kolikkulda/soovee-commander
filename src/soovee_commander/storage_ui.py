"""Compact, responsive volume capacity display for each file panel."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .filemodel import size_text
from .i18n import tr
from .themes import THEMES


def capacity_text(info):
    if info is None or info.total is None:
        return tr('Capacity unavailable')
    return tr('Free {v0} · Used {v1} · Total {v2}').format(
        v0=size_text(info.available), v1=size_text(info.used), v2=size_text(info.total))


class DriveButton(QPushButton):
    def __init__(self):
        super().__init__()
        self.caption = ''

    def set_caption(self, name):
        self.caption = name
        self.setMaximumWidth(min(260, max(100, self.fontMetrics().horizontalAdvance(name) + 44)))
        self.update_caption()

    def update_caption(self):
        self.setText(self.fontMetrics().elidedText(self.caption, Qt.TextElideMode.ElideMiddle,
                                                 max(15, self.width() - 32)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_caption()


class CapacityBar(QWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.info = None
        self.setFixedHeight(4)
        self.setMinimumWidth(0)
        self.setAccessibleName(tr('Disk usage'))

    def paintEvent(self, event):
        if self.info is None or not self.info.total:
            return
        colors = THEMES[self.panel.window.theme_key]
        active = self.panel.property('active')
        remaining = self.info.available / self.info.total
        fill = '#ef4444' if remaining < .05 else '#f59e0b' if remaining < .15 else colors['active_text'] if active else colors['accent']
        track = QColor(colors['active_text'] if active else colors['border'])
        track.setAlpha(65 if active else 110)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(track)
        painter.drawRoundedRect(rect, 2, 2)
        # Include unavailable quota/reserved space in the occupied portion.
        rect.setWidth(rect.width() * (1 - remaining))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, 2, 2)


class DiskSummary(QFrame):
    def __init__(self, panel):
        super().__init__()
        self.setObjectName('diskSummary')
        self.info = None
        self.loading = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        row.setSpacing(9)
        self.free = QLabel()
        self.free.setObjectName('diskFree')
        self.details = QLabel()
        self.details.setObjectName('diskDetails')
        self.details.setWordWrap(True)
        self.details.setMinimumWidth(0)
        self.details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        for label in (self.free, self.details):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setProperty('userContent', True)
        row.addWidget(self.free)
        row.addWidget(self.details, 1)
        layout.addLayout(row)
        self.bar = CapacityBar(panel)
        layout.addWidget(self.bar)
        self.render()

    def set_volume(self, info, *, loading=False):
        self.info, self.loading = info, loading
        self.render()

    def render(self):
        info = self.info
        known = info is not None and info.total is not None
        self.free.setText(tr('Free {v0}').format(v0=size_text(info.available)) if known
                          else tr('Reading disk information…') if self.loading else tr('Capacity unavailable'))
        self.details.setText(tr('Used {v0} · Total {v1}').format(v0=size_text(info.used), v1=size_text(info.total)) if known else '')
        tooltip = capacity_text(info)
        if info:
            tooltip = info.name + '\n' + info.root + '\n' + tooltip
            if info.filesystem:
                tooltip += '\n' + info.filesystem
            if info.readonly:
                tooltip += '\n' + tr('Read-only volume')
            if known and info.free > info.available:
                tooltip += '\n' + tr('Reserved or unavailable to this user: {v0}').format(v0=size_text(info.free - info.available))
        self.setToolTip(tooltip)
        self.bar.info = info
        self.bar.setVisible(known)
        self.bar.setAccessibleName(tr('Disk usage'))
        self.bar.setAccessibleDescription(tooltip)
        self.bar.update()
