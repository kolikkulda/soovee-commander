"""Illustrated panel settings with an isolated preview and explicit Apply."""
from PySide6.QtCore import Qt, QSize, QSignalBlocker
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QPalette, QPolygon
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QListView, QSlider, QSpinBox, QStackedWidget,
    QToolButton, QTreeView, QVBoxLayout, QSizePolicy)

from .filemodel import FileModel
from .i18n import tr
from .panel_views import FileTileDelegate, configure_tiles
from .providers import Entry


def mode_icon(mode, palette):
    pixmap = QPixmap(64, 42); pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = palette.color(QPalette.ColorRole.Text)
    painter.setPen(color); painter.setBrush(palette.color(QPalette.ColorRole.Highlight))
    if mode in ('details', 'compact'):
        for y in (8, 19, 30):
            for x in ((5, 34) if mode == 'compact' else (5,)):
                painter.drawRoundedRect(x, y, 6, 6, 1, 1)
                painter.drawLine(x + 10, y + 3, x + (23 if mode == 'compact' else 49), y + 3)
    else:
        for x in (7, 36):
            for y in (4, 24):
                painter.drawRoundedRect(x, y, 19, 12, 2, 2)
                if mode == 'thumbnails':
                    painter.drawLine(x + 2, y + 9, x + 8, y + 4); painter.drawLine(x + 8, y + 4, x + 17, y + 10)
                painter.drawLine(x + 2, y + 15, x + 17, y + 15)
    painter.end(); return QIcon(pixmap)


class PanelAppearanceDialog(QDialog):
    def __init__(self, appearance):
        self.appearance, self.panel = appearance, appearance.panel
        super().__init__(self.panel.window)
        self.setWindowTitle(tr('Panel appearance')); self.resize(860, 650)
        self.setMinimumSize(700, 520)
        layout = QVBoxLayout(self); layout.setSpacing(8)
        title = QLabel(tr('Choose a view and check the preview')); title.setObjectName('dialogHeading'); layout.addWidget(title)
        choices = QHBoxLayout(); self.modes = QButtonGroup(self)
        for number, (caption, mode) in enumerate(appearance.MODES):
            button = QToolButton(); button.setText(tr(caption)); button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setObjectName('viewModeCard'); button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setIcon(mode_icon(mode, self.palette())); button.setIconSize(QSize(64, 42)); button.setCheckable(True)
            button.setMinimumHeight(86); button.setMinimumWidth(135); button.setProperty('viewMode', mode)
            self.modes.addButton(button, number); choices.addWidget(button, 1)
            if mode == appearance.mode: button.setChecked(True)
        layout.addLayout(choices)
        body = QHBoxLayout()
        settings = QGroupBox(tr('Size and labels')); settings.setObjectName('toolCard'); self.form = QFormLayout(settings)
        self.icon = QSpinBox(); self.icon.setRange(12, 192); self.icon.setSuffix(' px'); self.icon.setValue(appearance.icon_size)
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setRange(12, 192); self.slider.setValue(self.icon.value())
        icon_row = QVBoxLayout(); icon_row.addWidget(self.icon); icon_row.addWidget(self.slider)
        self.form.addRow(tr('Icon size'), icon_row)
        self.height = QSpinBox(); self.height.setRange(20, 128); self.height.setSuffix(' px'); self.height.setValue(appearance.row_height or 26)
        self.form.addRow(tr('Row height'), self.height)
        self.lines = QSpinBox(); self.lines.setRange(1, 5); self.lines.setValue(appearance.label_lines)
        self.form.addRow(tr('Name lines'), self.lines)
        self.standard = QCheckBox(tr('Use recommended sizes'))
        self.standard.setChecked(appearance.icon_size == (96 if appearance.mode in ('icons', 'thumbnails') else 16) and not appearance.row_height)
        self.form.addRow(self.standard)
        self.description = QLabel(); self.description.setWordWrap(True); self.description.setMinimumWidth(200); self.description.setMaximumWidth(260)
        self.form.addRow(self.description)
        body.addWidget(settings, 0)
        preview_box = QGroupBox(tr('Live preview')); preview_box.setObjectName('toolCard'); preview_layout = QVBoxLayout(preview_box)
        self.preview = QStackedWidget(); self.preview.setMinimumHeight(220)
        self.model = FileModel(self)
        self.model.set_entries([Entry('Documents', True), Entry('Holiday photos', True),
            Entry('City park.jpg', False, 2400000, 1762000000), Entry('Family video 2026.mp4', False, 48000000, 1762000000),
            Entry('Project notes and meeting summary.txt', False, 14000, 1762000000)])
        self.tree = QTreeView(); self.tree.setModel(self.model); self.tree.setRootIsDecorated(False); self.tree.setAlternatingRowColors(True)
        for column in range(3, self.model.columnCount()): self.tree.hideColumn(column)
        self.tree.header().setStretchLastSection(True); self.tree.setColumnWidth(0, 190); self.tree.setColumnWidth(1, 75)
        self.tiles = QListView(); self.tiles.setObjectName('fileTiles'); self.tiles.setModel(self.model)
        self.tiles.setItemDelegate(FileTileDelegate(self.tiles)); self.tiles.setUniformItemSizes(True)
        self.tiles.setMouseTracking(True); self.tiles.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.preview.addWidget(self.tree); self.preview.addWidget(self.tiles); preview_layout.addWidget(self.preview)
        caption = QLabel(tr('Sample files · Apply updates the real panel without closing this window.')); caption.setWordWrap(True)
        preview_layout.addWidget(caption); body.addWidget(preview_box, 1); layout.addLayout(body, 1)
        self.both = QCheckBox(tr('Apply the same settings to the other panel')); layout.addWidget(self.both)
        self.feedback = QLabel(); layout.addWidget(self.feedback)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.RestoreDefaults)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_settings)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setObjectName('primary')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('Save and close'))
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        self.buttons.accepted.connect(self.save_and_close); self.buttons.rejected.connect(self.reject); layout.addWidget(self.buttons)
        self.modes.idClicked.connect(self.mode_changed)
        self.icon.valueChanged.connect(self.icon_changed); self.slider.valueChanged.connect(self.icon.setValue)
        self.height.valueChanged.connect(self.size_changed); self.lines.valueChanged.connect(self.update_preview)
        self.standard.toggled.connect(self.use_recommended); self.both.toggled.connect(self.update_preview)
        self.applied = self.values()
        self.update_preview()

    def mode(self): return self.appearance.MODES[self.modes.checkedId()][1]

    def values(self):
        return self.mode(), self.icon.value(), 0 if self.standard.isChecked() else self.height.value(), self.lines.value(), self.both.isChecked()

    def mode_changed(self, *args):
        tiled = self.mode() in ('icons', 'thumbnails')
        with QSignalBlocker(self.icon), QSignalBlocker(self.standard):
            self.icon.setRange(12, 192 if tiled else 64)
            self.slider.setRange(12, 192 if tiled else 64)
            if self.standard.isChecked() or tiled and self.icon.value() <= 32:
                self.icon.setValue(96 if tiled else 16)
        self.update_preview()

    def icon_changed(self, value):
        with QSignalBlocker(self.standard): self.standard.setChecked(False)
        with QSignalBlocker(self.slider): self.slider.setValue(value)
        if self.mode() in ('details', 'compact'):
            with QSignalBlocker(self.height): self.height.setValue(max(self.height.value(), value + 8))
        self.update_preview()

    def size_changed(self, *args):
        with QSignalBlocker(self.standard): self.standard.setChecked(False)
        self.update_preview()

    def use_recommended(self, checked):
        if checked:
            with QSignalBlocker(self.icon), QSignalBlocker(self.height):
                self.icon.setValue(96 if self.mode() in ('icons', 'thumbnails') else 16); self.height.setValue(26)
        self.update_preview()

    def restore_defaults(self):
        self.modes.button(0).setChecked(True)
        with QSignalBlocker(self.standard), QSignalBlocker(self.icon), QSignalBlocker(self.height), QSignalBlocker(self.lines):
            self.standard.setChecked(True); self.icon.setValue(16); self.height.setValue(26); self.lines.setValue(3)
        self.mode_changed()

    def update_preview(self, *args):
        if self.mode() in ('details','compact'):
            with QSignalBlocker(self.height): self.height.setMinimum(self.icon.value() + 8)
        mode, icon, height, lines, both = self.values()
        tiled = mode in ('icons', 'thumbnails')
        self.form.setRowVisible(self.height, not tiled); self.height.setEnabled(not self.standard.isChecked())
        self.form.setRowVisible(self.lines, tiled)
        with QSignalBlocker(self.slider): self.slider.setValue(icon)
        self.description.setText(tr({'details':'Columns with file name, size and date.', 'compact':'Small icons and file names in columns.',
            'icons':'Complete icons with names below. Hover to read a long name.',
            'thumbnails':'Local image previews. Other files keep their type icons; remote files are not downloaded for previews.'}[mode]))
        self.model.thumbnails.clear()
        if mode == 'thumbnails':
            picture = QPixmap(180, 110); picture.fill(QColor('#8bd3ee')); painter = QPainter(picture)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#4a8c72'))
            painter.drawPolygon(QPolygon([QPoint(0,110),QPoint(65,25),QPoint(130,110)]))
            painter.setBrush(QColor('#39718b')); painter.drawPolygon(QPolygon([QPoint(70,110),QPoint(135,40),QPoint(180,110)]))
            painter.end(); self.model.thumbnails['City park.jpg'] = QIcon(picture)
        self.tree.setIconSize(QSize(icon, icon)); self.tree.setStyleSheet(f'QTreeView::item {{ height: {height}px; }}' if height else '')
        configure_tiles(self.tiles, mode, icon, height, lines)
        self.preview.setCurrentWidget(self.tree if mode == 'details' else self.tiles)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(self.values() != self.applied)
        self.feedback.clear()

    def apply_settings(self):
        mode, icon, height, lines, both = self.values()
        self.appearance.apply(mode, icon, height, label_lines=lines)
        if both:
            other = self.panel.window.right if self.panel is self.panel.window.left else self.panel.window.left
            other.appearance.apply(mode, icon, height, label_lines=lines)
        self.applied = self.values()
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(False)
        self.feedback.setText(tr('Applied to both panels.' if both else 'Applied to this panel.'))

    def save_and_close(self):
        self.apply_settings(); self.accept()
