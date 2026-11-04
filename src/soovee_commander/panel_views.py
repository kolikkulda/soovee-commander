"""Optional shared-selection views and bounded, visible-only local thumbnails."""
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDrag, QIcon, QImageReader, QPixmap, QPalette, QTextLayout, QTextOption, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                              QLabel, QListView, QPushButton, QSpinBox, QVBoxLayout, QStyledItemDelegate, QStyle)
from shiboken6 import isValid

from .i18n import tr
from .providers import LocalProvider
from .filetypes import kind, type_icon


class FileTileDelegate(QStyledItemDelegate):
    """Explicit logical-pixel geometry; native styles cannot clip icon labels."""
    def sizeHint(self, option, index):
        return self.parent().gridSize()

    def regions(self, rect):
        view = self.parent()
        padding = 10
        if view.viewMode() == QListView.ViewMode.ListMode:
            side = min(view.iconSize().width(), rect.height() - 8)
            icon = QRect(rect.left() + 8, rect.center().y() - side // 2, side, side)
            text = QRect(icon.right() + 9, rect.top() + 3, max(1, rect.right() - icon.right() - 19), rect.height() - 6)
        else:
            side = min(view.iconSize().width(), rect.width() - padding * 2)
            icon = QRect(rect.center().x() - side // 2, rect.top() + padding, side, side)
            text = QRect(rect.left() + padding, icon.bottom() + 8, rect.width() - 2 * padding,
                         max(1, rect.bottom() - icon.bottom() - padding - 8))
        return icon, text

    def paint(self, painter, option, index):
        view = self.parent()
        icon_rect, text_rect = self.regions(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save(); painter.setClipRect(option.rect)
        if selected or hovered:
            color = QColor(option.palette.color(QPalette.ColorRole.Highlight))
            if not selected: color.setAlpha(28)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(color)
            painter.drawRoundedRect(option.rect.adjusted(3, 3, -3, -3), 7, 7)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        entry = index.data(Qt.ItemDataRole.UserRole)
        if entry is not None and not entry.is_dir and entry.name not in getattr(view.model(), 'thumbnails', {}):
            icon = type_icon(kind(entry.name, entry.is_dir, entry.is_link)[0], max(12, icon_rect.width()))
        elif entry is None and index.data(Qt.ItemDataRole.DisplayRole) == '..':
            icon = view.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogToParent)
        if isinstance(icon, QIcon):
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal, QIcon.State.Off)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        color = option.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        if not selected and isinstance(foreground, QColor): color = foreground
        painter.setPen(color); painter.setFont(option.font)
        if view.viewMode() == QListView.ViewMode.ListMode:
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideMiddle, text_rect.width()))
        else:
            layout = QTextLayout(text, option.font)
            settings = QTextOption(); settings.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(settings); layout.beginLayout()
            lines = []
            for _ in range(getattr(view, 'label_lines', 3)):
                line = layout.createLine()
                if not line.isValid(): break
                line.setLineWidth(max(1, text_rect.width())); lines.append(line)
            layout.endLayout()
            for number, line in enumerate(lines):
                start, length = line.textStart(), line.textLength()
                encoded = text.encode('utf-16-le')
                label = (encoded[start * 2:] if number == len(lines) - 1 else encoded[start * 2:(start + length) * 2]).decode('utf-16-le')
                label = option.fontMetrics.elidedText(label, Qt.TextElideMode.ElideMiddle, text_rect.width())
                row = QRect(text_rect.left(), text_rect.top() + number * option.fontMetrics.lineSpacing(),
                            text_rect.width(), option.fontMetrics.lineSpacing())
                painter.drawText(row, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, label)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(option.palette.color(QPalette.ColorRole.Highlight)); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(option.rect.adjusted(2, 2, -2, -2), 7, 7)
        painter.restore()


def configure_tiles(view, mode, icon_size, row_height=0, label_lines=3):
    view.label_lines = max(1, min(5, label_lines))
    view.setSpacing(0); view.setIconSize(QSize(icon_size, icon_size))
    view.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    if mode == 'compact':
        view.setViewMode(QListView.ViewMode.ListMode); view.setFlow(QListView.Flow.TopToBottom)
        view.setWrapping(True); view.setWordWrap(False)
        view.setGridSize(QSize(260, max(row_height, icon_size + 12, view.fontMetrics().height() + 12)))
    else:
        view.setViewMode(QListView.ViewMode.IconMode); view.setFlow(QListView.Flow.LeftToRight)
        view.setWrapping(True); view.setWordWrap(True)
        view.setGridSize(QSize(max(168, icon_size + 40), icon_size + view.fontMetrics().lineSpacing() * view.label_lines + 30))
    view.setResizeMode(QListView.ResizeMode.Adjust); view.setMovement(QListView.Movement.Static)
    view.doItemsLayout(); view.viewport().update()


class TileView(QListView):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.command_host = panel.window
        self.setObjectName('fileTiles')
        self.setItemDelegate(FileTileDelegate(self))
        self.setMouseTracking(True)
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setResizeMode(self.ResizeMode.Adjust)
        self.setMovement(self.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setDragEnabled(True); self.setAcceptDrops(True); self.setDropIndicatorShown(True)
        self.setDragDropMode(self.DragDropMode.DragDrop)

    def focusInEvent(self, event):
        self.panel.window.activate(self.panel)
        super().focusInEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.KeyPress and self.panel.window.commands.dispatch_file_key(event):
            return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton):
            self.panel.window.activate(self.panel)
            self.panel.window.commands.execute('back' if event.button() == Qt.MouseButton.BackButton else 'forward')
            return True
        return super().event(event)

    def wheelEvent(self, event):
        if self.panel.vertical_scroll_only and not event.pixelDelta().isNull():
            bar = self.verticalScrollBar(); bar.setValue(bar.value() - event.pixelDelta().y()); event.accept()
        else:
            super().wheelEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        appearance = getattr(self.panel, 'appearance', None)
        if appearance and appearance.mode == 'thumbnails':
            appearance.schedule_thumbnails()

    def startDrag(self, actions):
        panel = self.panel
        if not isinstance(panel.provider, LocalProvider): return
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(panel.provider.join(panel.path, e.name)) for e in panel.action_entries()])
        if not mime.urls(): return
        drag = QDrag(self); drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(u.isLocalFile() for u in event.mimeData().urls()):
            event.setDropAction(Qt.DropAction.CopyAction); event.accept()
        else: event.ignore()

    def dragMoveEvent(self, event): self.dragEnterEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasUrls() or not all(u.isLocalFile() for u in event.mimeData().urls()):
            event.ignore(); return
        index = self.indexAt(event.position().toPoint())
        entry = self.panel.model.entry(index.row()) if index.isValid() else None
        target = self.panel.provider.join(self.panel.path, entry.name) if entry and entry.is_dir else self.panel.path
        self.panel.window.drop_paths(self.panel, [u.toLocalFile() for u in event.mimeData().urls()], target)
        event.setDropAction(Qt.DropAction.CopyAction); event.accept()


class PanelAppearance(QObject):
    MODES = [('Detailed list', 'details'), ('Compact list', 'compact'), ('Icons', 'icons'), ('Thumbnails (local images)', 'thumbnails')]

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        settings, side = panel.window.settings, panel.side
        self.mode = settings.value('view_mode_' + side, 'details')
        self.icon_size = settings.value('icon_size_' + side, 16, type=int)
        self.label_lines = settings.value('label_lines_' + side, 3, type=int)
        if self.mode in ('icons', 'thumbnails') and not settings.value('tile_layout_v2_' + side, False, type=bool):
            self.icon_size = min(192, max(80, self.icon_size * 3))
        self.row_height = settings.value('row_height_' + side, 0, type=int)
        self.key, self.pending, self.generation = None, set(), 0
        self.failed = OrderedDict()
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(60)
        self.timer.timeout.connect(self.load_visible_thumbnails)
        self.apply(self.mode, self.icon_size, self.row_height, persist=False)

    def apply(self, mode, icon, height, *, label_lines=None, persist=True):
        self.mode = mode if mode in {v for _, v in self.MODES} else 'details'
        self.icon_size = max(12, min(64 if self.mode in ('details', 'compact') else 192, int(icon)))
        if label_lines is not None: self.label_lines = max(1, min(5, int(label_lines)))
        self.row_height = (max(self.icon_size + 6, min(128, int(height))) if height else self.icon_size + 8 if self.icon_size > 16 else 0) if self.mode in ('details', 'compact') else max(0, min(128, int(height)))
        panel, tree, tiles = self.panel, self.panel.tree, self.panel.tiles
        current = tree.currentIndex()
        self.invalidate()
        tree.setIconSize(QSize(min(64, self.icon_size), min(64, self.icon_size)))
        tree.frozen_columns.view.setIconSize(tree.iconSize())
        tree.setStyleSheet(f'QTreeView::item {{ height: {self.row_height}px; }}' if self.row_height else '')
        configure_tiles(tiles, self.mode, self.icon_size, self.row_height, self.label_lines)
        panel.file_stack.setCurrentWidget(tree if self.mode == 'details' else tiles)
        tree.frozen_columns.layout()
        if current.isValid(): panel.active_view().scrollTo(current)
        if hasattr(panel, '_update_scroll_arrows'): panel._update_scroll_arrows()
        if persist:
            for key, value in [('view_mode_', self.mode), ('icon_size_', self.icon_size), ('row_height_', self.row_height),
                               ('label_lines_', self.label_lines), ('tile_layout_v2_', True)]:
                panel.window.settings.setValue(key + panel.side, value)

    def invalidate(self):
        self.generation += 1
        self.key = None
        self.failed.clear()
        self.panel.model.thumbnails.clear()
        if self.panel.model.rowCount():
            self.panel.model.dataChanged.emit(self.panel.model.index(0, 0), self.panel.model.index(self.panel.model.rowCount() - 1, 0), [Qt.ItemDataRole.DecorationRole])

    def schedule_thumbnails(self):
        if not self.timer.isActive() and self.mode == 'thumbnails' and isinstance(self.panel.provider, LocalProvider): self.timer.start()

    def load_visible_thumbnails(self):
        panel = self.panel
        if self.mode != 'thumbnails' or not panel.tiles.isVisible() or not isinstance(panel.provider, LocalProvider): return
        self.location_changed()
        key = self.key
        view, grid = panel.tiles, panel.tiles.gridSize()
        rows = set()
        for y in range(0, view.viewport().height(), max(1, grid.height() // 2)):
            for x in range(0, view.viewport().width(), max(1, grid.width() // 2)):
                index = view.indexAt(QPoint(x, y))
                if index.isValid(): rows.add(index.row())
        for row in sorted(rows)[:128]:
            if len(self.pending) >= 2: return
            entry = panel.model.entry(row)
            if entry is None or entry.is_dir or entry.is_link or entry.size > 64 * 1024 * 1024: continue
            if Path(entry.name).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.avif', '.heic'}: continue
            identity = (key, entry.name, entry.size, entry.modified)
            if entry.name in panel.model.thumbnails or identity in self.pending or identity in self.failed: continue
            self.pending.add(identity)
            filename = panel.provider.join(panel.path, entry.name)
            def read(_, filename=filename):
                reader = QImageReader(filename); reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid(): reader.setScaledSize(size.scaled(QSize(256, 256), Qt.AspectRatioMode.KeepAspectRatio))
                return reader.read()
            def loaded(image, identity=identity, name=entry.name):
                if not isValid(panel): return
                self.pending.discard(identity)
                self.schedule_thumbnails()
                if self.mode != 'thumbnails' or self.key != identity[0]: return
                if image is None or image.isNull():
                    self.failed[identity] = True
                    while len(self.failed) > 128: self.failed.popitem(last=False)
                else:
                    panel.model.thumbnails[name] = QIcon(QPixmap.fromImage(image))
                    while len(panel.model.thumbnails) > 128: panel.model.thumbnails.popitem(last=False)
                    index = panel.model.index_for_name(name)
                    if index.isValid(): panel.model.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])
                self.schedule_thumbnails()
            panel.window.run_task(read, loaded, lambda message, loaded=loaded: loaded(None), read_only=True)

    def location_changed(self):
        key = (self.panel.location_key(self.panel.provider, self.panel.path), self.generation)
        if self.key != key:
            self.key = key; self.failed.clear(); self.panel.model.thumbnails.clear()

    def configure(self):
        from .appearance_dialog import PanelAppearanceDialog
        PanelAppearanceDialog(self).exec()
