"""Guided batch renaming: selectable source text, masks and explicit preview."""
import json
from collections import Counter
from pathlib import PurePosixPath

from PySide6.QtCore import Qt, QSignalBlocker, QEvent
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                              QLabel, QLineEdit, QMenu, QPushButton, QSpinBox, QVBoxLayout)
from .advanced import multi_rename, rename_names
from .i18n import tr
from .rename_masks import literal_mask


class MultiRenameDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        from .tool_dialogs import table
        self.host, self.panel = host, host.active
        self.provider, self.base = self.panel.provider, self.panel.path
        self.entries = list(self.panel.action_entries())
        self.setWindowTitle(tr('Multi-rename'))
        self.resize(1080, 780)
        self.setMinimumSize(820, 640)
        outer = QVBoxLayout(self)
        heading = QLabel(tr('Build names. Check the preview. Rename.'))
        heading.setObjectName('dialogHeading'); outer.addWidget(heading)
        location = QLabel(self.panel.location()); location.setTextFormat(Qt.TextFormat.PlainText)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location.setWordWrap(True); location.setProperty('userContent', True); outer.addWidget(location)
        presets = QHBoxLayout()
        presets.addWidget(QLabel(tr('Preset')))
        self.presets = QComboBox(); self.presets.setEditable(True)
        self.presets.setPlaceholderText(tr('Choose or name a preset'))
        try:
            self.saved = json.loads(str(host.settings.value('rename_presets_v1', '{}')))
            if not isinstance(self.saved, dict): self.saved = {}
        except ValueError:
            self.saved = {}
        self.presets.addItem(''); self.presets.addItems(sorted(self.saved))
        presets.addWidget(self.presets, 1)
        save = QPushButton(tr('Save preset')); save.clicked.connect(self.save_preset); presets.addWidget(save)
        reset = QPushButton(tr('Reset')); reset.clicked.connect(self.reset); presets.addWidget(reset)
        outer.addLayout(presets)
        controls = QHBoxLayout()
        masks = QGroupBox(tr('1 · Name and extension')); masks.setObjectName('toolCard')
        mask_layout = QVBoxLayout(masks)
        self.mask, self.extension = QLineEdit('[N]'), QLineEdit('[E]')
        self.target_field = self.mask
        self.mask.installEventFilter(self); self.extension.installEventFilter(self)
        mask_form = QFormLayout(); mask_form.addRow(tr('Name:'), self.mask); mask_form.addRow(tr('Extension:'), self.extension)
        mask_layout.addLayout(mask_form)
        helpers = QHBoxLayout()
        for caption, token in [('Name [N]', '[N]'), ('Counter [C]', '[C]'), ('Date [YMD]', '[Y]-[M]-[D]'), ('Parent [P]', '[P]')]:
            button = QPushButton(tr(caption)); button.clicked.connect(lambda checked=False, value=token: self.insert(value)); helpers.addWidget(button)
        mask_layout.addLayout(helpers)
        range_button = QPushButton(tr('Choose characters from original name…')); range_button.clicked.connect(self.choose_range)
        mask_layout.addWidget(range_button)
        controls.addWidget(masks, 3)
        counters = QGroupBox(tr('2 · Counter')); counters.setObjectName('toolCard'); form = QFormLayout(counters)
        self.start, self.step, self.digits = QSpinBox(), QSpinBox(), QSpinBox()
        self.start.setRange(-1_000_000_000, 1_000_000_000); self.start.setValue(1)
        self.step.setRange(-1_000_000, 1_000_000); self.step.setValue(1)
        self.digits.setRange(1, 12)
        form.addRow(tr('Start at:'), self.start); form.addRow(tr('Step:'), self.step); form.addRow(tr('Digits:'), self.digits)
        self.counter_example = QLabel(); form.addRow(tr('Example:'), self.counter_example)
        controls.addWidget(counters, 1); outer.addLayout(controls)
        changes = QGroupBox(tr('3 · Find, replace and letter case')); changes.setObjectName('toolCard')
        grid = QGridLayout(changes)
        self.find, self.replace, self.case = QLineEdit(), QLineEdit(), QComboBox()
        self.case.setProperty('translatedItems', True)
        for title, value in [('Keep case', 'keep'), ('lowercase', 'lower'), ('UPPERCASE', 'upper'), ('Title Case', 'title'), ('Sentence case', 'sentence')]:
            self.case.addItem(tr(title), value)
        grid.addWidget(QLabel(tr('Find:')), 0, 0); grid.addWidget(self.find, 0, 1)
        grid.addWidget(QLabel(tr('Replace:')), 0, 2); grid.addWidget(self.replace, 0, 3); grid.addWidget(self.case, 0, 4)
        self.regex = QCheckBox(tr('Regular expression (Python)'))
        self.sensitive = QCheckBox(tr('Case sensitive')); self.include_extension = QCheckBox(tr('Also replace in extension'))
        self.first_only = QCheckBox(tr('First match only'))
        for column, field in enumerate((self.regex, self.sensitive, self.include_extension, self.first_only)):
            grid.addWidget(field, 1, column, 1, 1)
        outer.addWidget(changes)
        source_row = QHBoxLayout(); source_row.addWidget(QLabel(tr('Original name:')))
        self.original = QLineEdit(); self.original.setReadOnly(True); self.original.setProperty('userContent', True)
        source_row.addWidget(self.original, 1)
        copy = QPushButton(tr('Copy original')); copy.clicked.connect(self.copy_original); source_row.addWidget(copy)
        use = QPushButton(tr('Use as name mask')); use.clicked.connect(self.use_original); source_row.addWidget(use)
        outer.addLayout(source_row)
        self.preview = table([tr('Original name'), tr('New name'), tr('Status')])
        self.error_rows, self.changed_rows = set(), set()
        self.preview.records.foreground = self.preview_color
        self.preview.setColumnWidth(0, 380); self.preview.setColumnWidth(1, 380)
        self.preview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.preview.customContextMenuRequested.connect(self.context_menu)
        self.preview.selectionModel().currentRowChanged.connect(self.select_original)
        shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.preview, activated=self.copy_original)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        outer.addWidget(self.preview, 1)
        order = QHBoxLayout(); order.addWidget(QLabel(tr('Counter follows preview order.'))); order.addStretch()
        for caption, delta in [('Move up', -1), ('Move down', 1)]:
            button = QPushButton(tr(caption)); button.clicked.connect(lambda checked=False, value=delta: self.move_row(value)); order.addWidget(button)
        outer.addLayout(order)
        self.status = QLabel(); self.status.setWordWrap(True); outer.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('Rename'))
        self.buttons.accepted.connect(self.apply); self.buttons.rejected.connect(self.reject); outer.addWidget(self.buttons)
        for edit in (self.mask, self.extension, self.find, self.replace): edit.textChanged.connect(self.update_preview)
        for spin in (self.start, self.step, self.digits): spin.valueChanged.connect(self.update_preview)
        for check in (self.regex, self.sensitive, self.include_extension, self.first_only): check.toggled.connect(self.update_preview)
        self.case.currentIndexChanged.connect(self.update_preview)
        self.presets.activated.connect(self.load_preset)
        self.update_preview()

    def insert(self, text):
        field = self.target_field
        field.insert(text); field.setFocus()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn and watched in (self.mask, self.extension):
            self.target_field = watched
        return super().eventFilter(watched, event)

    def current_entry(self):
        return self.entries[max(0, self.preview.currentRow())] if self.entries else None

    def select_original(self, *args):
        entry = self.current_entry()
        self.original.setText(entry.name if entry else '')
        self.original.setCursorPosition(0)
        self.original.setToolTip(tr('{v0} characters').format(v0=len(entry.name)) if entry else '')

    def preview_color(self, row, column):
        from .themes import THEMES
        colors = THEMES[self.host.theme_key]
        dark = QColor(colors['surface']).lightness() < 128
        if row in self.error_rows: return QColor('#ff8a8a' if dark else '#b91c1c')
        if row in self.changed_rows and column == 1: return QColor('#51e1c2' if dark else '#0f766e')
        return QColor(colors['muted'] if column == 2 and row not in self.changed_rows else colors['text'])

    def copy_original(self):
        if entry := self.current_entry(): QApplication.clipboard().setText(entry.name)

    def use_original(self):
        if entry := self.current_entry():
            self.mask.setText(literal_mask(entry.name if entry.is_dir else PurePosixPath(entry.name).stem))
            self.mask.setFocus(); self.mask.selectAll()

    def context_menu(self, point):
        index = self.preview.indexAt(point)
        if index.isValid(): self.preview.selectRow(index.row())
        menu = QMenu(self)
        menu.addAction(tr('Copy original'), self.copy_original)
        menu.addAction(tr('Use as name mask'), self.use_original)
        row = self.preview.currentRow()
        if self.names and 0 <= row < len(self.names):
            menu.addAction(tr('Copy new name'), lambda: QApplication.clipboard().setText(self.names[row]))
        menu.exec(self.preview.viewport().mapToGlobal(point))

    def move_row(self, delta):
        row = self.preview.currentRow(); target = row + delta
        if 0 <= row < len(self.entries) and 0 <= target < len(self.entries):
            self.entries[row], self.entries[target] = self.entries[target], self.entries[row]
            self.update_preview(); self.preview.selectRow(target)

    def choose_range(self):
        entry = self.current_entry()
        if entry is None: return
        dialog = QDialog(self); dialog.setWindowTitle(tr('Choose characters')); dialog.resize(640, 240)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel(tr('Select characters in the original name, or set their positions below.')))
        name = entry.name if entry.is_dir else PurePosixPath(entry.name).stem
        source = QLineEdit(name); source.setReadOnly(True); box.addWidget(source)
        box.addWidget(QLabel(tr('{v0} characters').format(v0=len(name))))
        row = QHBoxLayout(); first, last = QSpinBox(), QSpinBox()
        for field in (first, last): field.setRange(1, max(1, len(name)))
        first.setValue(1); last.setValue(max(1, len(name)))
        row.addWidget(QLabel(tr('From:'))); row.addWidget(first); row.addWidget(QLabel(tr('Through:'))); row.addWidget(last)
        box.addLayout(row); token = QLineEdit(); token.setReadOnly(True); box.addWidget(token)
        def selected():
            if source.selectionStart() >= 0:
                # QLineEdit positions are UTF-16; masks count Unicode code points.
                units = name.encode('utf-16-le')
                start = len(units[:source.selectionStart() * 2].decode('utf-16-le', errors='ignore'))
                length = len(source.selectedText())
                with QSignalBlocker(first), QSignalBlocker(last):
                    first.setValue(start + 1); last.setValue(start + length)
            update()
        def update(*args): token.setText(f'[N{first.value()}-{max(first.value(), last.value())}]')
        source.selectionChanged.connect(selected); first.valueChanged.connect(update); last.valueChanged.connect(update); update()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); box.addWidget(buttons)
        if dialog.exec(): self.insert(token.text())

    def settings_value(self):
        return {key: field.text() for key, field in [('mask', self.mask), ('extension', self.extension), ('find', self.find), ('replace', self.replace)]} | {
            'start': self.start.value(), 'step': self.step.value(), 'digits': self.digits.value(), 'case': self.case.currentData(),
            'regex': self.regex.isChecked(), 'sensitive': self.sensitive.isChecked(), 'include_extension': self.include_extension.isChecked(), 'first_only': self.first_only.isChecked()}

    def save_preset(self):
        name = self.presets.currentText().strip()
        if not name:
            name, ok = QInputDialog.getText(self, tr('Save preset'), tr('Name:'))
            if not ok: return
        if not name or len(name) > 80: return
        self.saved[name] = self.settings_value()
        self.host.settings.setValue('rename_presets_v1', json.dumps(self.saved, ensure_ascii=False))
        if self.presets.findText(name) < 0: self.presets.addItem(name)
        self.presets.setCurrentText(name)

    def load_values(self, value):
        for key in ('mask', 'extension', 'find', 'replace'):
            field = getattr(self, key)
            with QSignalBlocker(field): field.setText(str(value.get(key, '[N]' if key == 'mask' else '[E]' if key == 'extension' else '')))
        for key in ('start', 'step', 'digits'):
            field = getattr(self, key)
            with QSignalBlocker(field): field.setValue(int(value.get(key, 1)))
        for key in ('regex', 'sensitive', 'include_extension', 'first_only'):
            field = getattr(self, key)
            with QSignalBlocker(field): field.setChecked(bool(value.get(key, False)))
        with QSignalBlocker(self.case): self.case.setCurrentIndex(max(0, self.case.findData(value.get('case', 'keep'))))
        self.update_preview()

    def load_preset(self, *args):
        value = self.saved.get(self.presets.currentText())
        if isinstance(value, dict):
            try: self.load_values(value)
            except (ValueError, TypeError, OverflowError): self.status.setText(tr('Invalid preset.'))

    def reset(self): self.load_values({})

    def update_preview(self, *args):
        row = max(0, self.preview.currentRow())
        try:
            self.names = rename_names(self.entries, self.mask.text(), self.extension.text(), self.find.text(), self.replace.text(), self.case.currentData(),
                                      self.start.value(), self.digits.value(), step=self.step.value(), parent=self.base,
                                      regex=self.regex.isChecked(), case_sensitive=self.sensitive.isChecked(), replace_extension=self.include_extension.isChecked(),
                                      first_only=self.first_only.isChecked(), check_duplicates=False)
            counts = Counter(name.casefold() for name in self.names)
            originals = {entry.name for entry in self.entries}
            occupied = {entry.name.casefold() for entry in self.panel.entries if entry.name not in originals}
            states = [tr('Conflict') if counts[name.casefold()] > 1 or name.casefold() in occupied else tr('Unchanged') if name == entry.name else tr('Ready') for entry, name in zip(self.entries, self.names)]
            conflicts = any(counts[name.casefold()] > 1 or name.casefold() in occupied for name in self.names)
            self.error_rows = {i for i, name in enumerate(self.names) if counts[name.casefold()] > 1 or name.casefold() in occupied}
            self.changed_rows = {i for i, (e, n) in enumerate(zip(self.entries, self.names)) if e.name != n}
            changed = sum(e.name != n for e, n in zip(self.entries, self.names))
            self.status.setText(tr('Name conflicts must be resolved before renaming.') if conflicts else tr('{v0} changes · nothing changes until confirmed').format(v0=changed))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(changed) and not conflicts and not self.provider.readonly)
        except ValueError as exc:
            self.names, states = [], [tr('Error')] * len(self.entries)
            self.error_rows, self.changed_rows = set(range(len(self.entries))), set()
            self.status.setText(tr(str(exc))); self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.preview.set_rows([[entry.name, self.names[i] if self.names else '—', states[i]] for i, entry in enumerate(self.entries)])
        if self.entries: self.preview.selectRow(min(row, len(self.entries) - 1))
        self.select_original()
        self.counter_example.setText(' · '.join(str(self.start.value() + i * self.step.value()).zfill(self.digits.value()) for i in range(3)))

    def apply(self):
        if not self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled(): return
        entries, names = list(self.entries), list(self.names)
        provider, base, host = self.provider, self.base, self.host
        def done(inverse): host.last_rename = (provider, base, entries, names)
        host.enqueue(tr('Rename multiple items: {v0} items').format(v0=len(entries)), lambda cancel, report: multi_rename(provider, base, entries, names, cancel, report), on_done=done)
        self.accept()
