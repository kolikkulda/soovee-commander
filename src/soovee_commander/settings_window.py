"""One preferences window: categories on the left, one page each on the right.

Earlier standalone dialogs (controls, external commands, associations) are
embedded as pages so their validation and storage stay in one place. Every
page applies through the same OK / Apply / Cancel buttons; associations are
saved immediately, as before.
"""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QStackedWidget, QTableWidget, QVBoxLayout, QWidget)

from .i18n import LANGUAGES, tr
from .themes import THEMES

PAGES = (
    ("general", 'General', 'Language, colour theme and how files are listed.'),
    ("panels", 'Panels and refresh', 'Automatic refresh and the layout of each panel.'),
    ("previews", 'Previews', 'Built-in previews in F3 and the quick view.'),
    ("controls", 'Shortcuts and buttons', 'Keyboard shortcuts and the buttons on the command bars.'),
    ("external", 'External commands', 'Run your own programs on the selected files.'),
    ("associations", 'File associations', 'Which application opens each file type from Soovee Commander.'),
    ("transfers", 'Transfers and updates', 'Soovee Transfers between devices and installing updates.'),
)
INTERVALS = ((0, 'Off'), (5, 'Every 5 seconds'), (15, 'Every 15 seconds'), (60, 'Every minute'))


def note(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("muted")
    return label


def group(title, *widgets):
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    for widget in widgets:
        layout.addLayout(widget) if not isinstance(widget, QWidget) else layout.addWidget(widget)
    return box


def option(text, checked, description=""):
    """A checkbox with an explanation underneath, kept together."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 4)
    layout.setSpacing(1)
    check = QCheckBox(text)
    check.setChecked(checked)
    layout.addWidget(check)
    if description:
        hint = note(description)
        hint.setContentsMargins(24, 0, 0, 0)
        layout.addWidget(hint)
    box.check = check
    return box


def embed(dialog):
    """Use an existing dialog as a page: no window frame, no own OK/Cancel buttons."""
    dialog.setWindowFlags(Qt.WindowType.Widget)
    for box in dialog.findChildren(QDialogButtonBox):
        box.hide()
    return dialog


def scrolling(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    return area


class SettingsWindow(QDialog):
    def __init__(self, host, page="general"):
        super().__init__(host)
        self.host = host
        self.setWindowTitle(tr('Settings'))
        self.resize(1000, 700)
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        side = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('Search settings…'))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_pages)
        side.addWidget(self.search)
        self.categories = QListWidget()
        self.categories.setObjectName("settingsCategories")
        self.categories.setFixedWidth(230)
        self.categories.setSpacing(2)
        side.addWidget(self.categories, 1)
        body.addLayout(side)
        right = QVBoxLayout()
        self.heading = QLabel()
        self.heading.setObjectName("dialogHeading")
        self.description = note("")
        right.addWidget(self.heading)
        right.addWidget(self.description)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        body.addLayout(right, 1)
        self.pages, self.search_text = {}, {}
        builders = dict(general=self.general_page, panels=self.panels_page, previews=self.previews_page,
                        controls=self.controls_page, external=self.external_page,
                        associations=self.associations_page, transfers=self.transfers_page)
        for key, title, description in PAGES:
            widget = builders[key]()
            self.pages[key] = widget
            self.stack.addWidget(widget)
            item = QListWidgetItem(tr(title))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(tr(description))
            self.categories.addItem(item)
            words = [tr(title), tr(description)]
            for kind in (QLabel, QCheckBox, QPushButton):
                words += [w.text() for w in widget.findChildren(kind)]
            words += [w.title() for w in widget.findChildren(QGroupBox)]
            for table in widget.findChildren(QTableWidget):  # e.g. command names on the shortcuts page
                words += [table.item(r, 0).text() for r in range(table.rowCount()) if table.item(r, 0)]
            self.search_text[key] = " ".join(words).casefold()
        self.categories.currentRowChanged.connect(self.show_page)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('OK'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Cancel'))
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText(tr('Apply'))
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.accepted.connect(lambda: self.apply() and self.accept())
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.open_page(page)

    # Navigation ---------------------------------------------------------
    def open_page(self, key):
        for row in range(self.categories.count()):
            if self.categories.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.categories.setCurrentRow(row)

    def show_page(self, row):
        item = self.categories.item(row)
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        title, description = next((t, d) for k, t, d in PAGES if k == key)
        self.heading.setText(tr(title))
        self.description.setText(tr(description))
        self.stack.setCurrentWidget(self.pages[key])

    def filter_pages(self, text):
        text = text.casefold().strip()
        first = None
        for row in range(self.categories.count()):
            item = self.categories.item(row)
            visible = not text or text in self.search_text[item.data(Qt.ItemDataRole.UserRole)]
            item.setHidden(not visible)
            if visible and first is None:
                first = row
        if first is not None and self.categories.currentItem() is not None and self.categories.currentItem().isHidden():
            self.categories.setCurrentRow(first)

    # Pages ----------------------------------------------------------------
    def general_page(self):
        host, settings = self.host, self.host.settings
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.language = QComboBox()
        self.language.setProperty('translatedItems', True)
        for code, name in LANGUAGES:
            self.language.addItem(tr(name), code)
        self.language.setCurrentIndex(max(0, self.language.findData(host.language)))
        form.addRow(tr('Language:'), self.language)
        self.theme = QComboBox()
        self.theme.setProperty('translatedItems', True)
        for key, theme in THEMES.items():
            self.theme.addItem(tr(theme["name"]), key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(host.theme_key)))
        form.addRow(tr('Colour theme:'), self.theme)
        layout.addWidget(group(tr('Language and appearance'), form))
        self.hidden = option(tr('Show hidden files'), host.hidden.isChecked(),
                             tr('Files whose names start with a dot, and system files.'))
        self.folders_first = option(tr('Folders always first'), settings.value("folders_first", True, type=bool),
                                    tr('Folders are listed before files whatever the sort order.'))
        self.auto_sizes = option(tr('Calculate folder sizes automatically in the background'), settings.value("auto_sizes", False, type=bool),
                                 tr('Shows the total size of each folder you open. Large folders take time and disk activity.'))
        self.sidebar = option(tr('Quick access sidebar'), not host.sidebar.isHidden(),
                              tr('Home, Documents, Downloads and Desktop on the left of the window.'))
        layout.addWidget(group(tr('File list'), self.hidden, self.folders_first, self.auto_sizes, self.sidebar))
        layout.addStretch()
        return scrolling(page)

    def panels_page(self):
        host, settings = self.host, self.host.settings
        page = QWidget()
        layout = QVBoxLayout(page)
        self.auto_refresh = option(tr('Refresh panels automatically'), settings.value("auto_refresh", True, type=bool),
                                   tr('Show files added, removed or renamed by other applications immediately, and re-read folders when you return to Soovee.'))
        self.interval = QComboBox()
        self.interval.setProperty('translatedItems', True)
        for seconds, label in INTERVALS:
            self.interval.addItem(tr(label), seconds)
        self.interval.setCurrentIndex(max(0, self.interval.findData(settings.value("auto_refresh_interval", 0, type=int))))
        row = QFormLayout()
        row.addRow(tr('Refresh periodically:'), self.interval)
        layout.addWidget(group(tr('Automatic refresh'), self.auto_refresh, row,
                               note(tr('Also re-reads servers and connected devices while Soovee is in front.'))))
        buttons = QHBoxLayout()
        for label, callback in ((tr('Panel appearance…'), lambda: host.active.appearance.configure()),
                                (tr('Configure columns…'), lambda: host.active.configure_columns()),
                                (tr('Panel scrolling…'), lambda: host.active.configure_scrolling()),
                                (tr('Equal panels (50:50)'), host.panel_splitter.center_panels)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addWidget(group(tr('Panel layout'), note(tr('These settings belong to the active panel and show a live preview. Each dialog can copy them to the other panel.')), buttons))
        layout.addStretch()
        return scrolling(page)

    def previews_page(self):
        from .document_preview import GROUPS, pdf_available
        settings = self.host.settings
        page = QWidget()
        layout = QVBoxLayout(page)
        self.previews = option(tr('Use built-in previews'), settings.value("internal_previews", True, type=bool),
                               tr('Show common documents in F3 and the quick view without another application.'))
        layout.addWidget(self.previews)
        self.preview_groups = {}
        boxes = []
        for key, (title, suffixes) in GROUPS.items():
            box = option(tr(title), settings.value("preview_" + key, True, type=bool), " ".join(sorted(suffixes)))
            if key == "pdf" and not pdf_available():
                box.check.setEnabled(False)
                box.check.setToolTip(tr('Not available: this build does not include the Qt PDF module.'))
            self.preview_groups[key] = box
            boxes.append(box)
        layout.addWidget(group(tr('File types'), *boxes))
        key = self.host.commands.key_label("quick_view")
        layout.addWidget(note(tr('Quick view ({v0}) shows the item under the cursor in the other panel. Remote files and archives are previewed up to 8 MB.').format(v0=key)))
        self.previews.check.toggled.connect(lambda on: [box.setEnabled(on) for box in boxes])
        for box in boxes:
            box.setEnabled(self.previews.check.isChecked())
        layout.addStretch()
        return scrolling(page)

    def controls_page(self):
        from .control_settings import ControlsDialog
        self.controls = embed(ControlsDialog(self.host))
        return self.controls

    def external_page(self):
        from .extensions import ExtensionsDialog
        self.external = embed(ExtensionsDialog(self.host))
        return self.external

    def associations_page(self):
        from .associations import AssociationsDialog
        return embed(AssociationsDialog(self.host))

    def transfers_page(self):
        from .update_ui import choose_update
        host = self.host
        page = QWidget()
        layout = QVBoxLayout(page)
        devices = QPushButton(tr('Open Soovee Transfers · Devices…'))
        devices.clicked.connect(host.show_devices)
        layout.addWidget(group(tr('Soovee Transfers'), note(tr('Pair phones, TVs and computers, choose which folders they may use, and send files between them.')), devices))
        row = QHBoxLayout()
        for label, folder in ((tr('Select update folder…'), True), (tr('Select update file…'), False)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, value=folder: choose_update(host, value))
            row.addWidget(button)
        row.addStretch()
        layout.addWidget(group(tr('Updates'), note(tr('Install a signed .stereoupdate package you downloaded. Settings, connections and pairings are kept.')), row))
        layout.addStretch()
        return scrolling(page)

    # Apply --------------------------------------------------------------------
    def apply(self):
        host, settings = self.host, self.host.settings
        try:
            controls = self.controls.config()
        except ValueError as exc:
            self.open_page("controls")
            QMessageBox.warning(self, tr('Check controls'), str(exc))
            return False
        from .extensions import validate_tools
        self.external.capture()
        try:
            tools = validate_tools(self.external.tools)
        except Exception as exc:
            self.open_page("external")
            QMessageBox.warning(self, tr('Commands'), str(exc))
            return False
        host.commands.apply(controls)
        settings.setValue("external_tools", json.dumps(tools, ensure_ascii=False))
        theme = self.theme.currentData()
        if theme != host.theme_key:
            host.theme_combo.setCurrentIndex(host.theme_combo.findData(theme))
        host.hidden.setChecked(self.hidden.check.isChecked())
        host.sidebar_action.setChecked(self.sidebar.check.isChecked())
        for command, box in (("folders_first", self.folders_first), ("auto_sizes", self.auto_sizes), ("auto_refresh", self.auto_refresh)):
            action = host.commands.actions[command]
            if action.isChecked() != box.check.isChecked():
                action.setChecked(box.check.isChecked())
                host.commands.execute(command)
        host.set_refresh_interval(self.interval.currentData())
        settings.setValue("internal_previews", self.previews.check.isChecked())
        for key, box in self.preview_groups.items():
            if box.check.isEnabled() or key != "pdf":
                settings.setValue("preview_" + key, box.check.isChecked())
        host.toggle_internal_previews(from_settings=True)
        host.sync_menu_states()
        language = self.language.currentData()
        if language != host.language:
            host.change_language(language)
        settings.sync()
        return True


class ShortcutsDialog(QDialog):
    """Every command grouped like the main menu, with its shortcut and description."""

    def __init__(self, host):
        super().__init__(host)
        from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem
        from .command_help import HELP, MENUS, SUBMENUS
        from .commands import BY_ID
        self.host = host
        self.setWindowTitle(tr('Keyboard shortcuts'))
        self.resize(820, 640)
        layout = QVBoxLayout(self)
        heading = QLabel(tr('Keyboard shortcuts'))
        heading.setObjectName("dialogHeading")
        layout.addWidget(heading)
        layout.addWidget(note(tr('All commands as they appear in the menus. Shortcuts can be changed in Settings › Shortcuts and buttons.')))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('Search commands or shortcuts…'))
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr('Menu command'), tr('Shortcut'), tr('Description')])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)
        seen = set()
        for title, entries in MENUS:
            commands = []
            for entry in entries:
                for command in SUBMENUS.get(entry, [entry]):
                    if command in BY_ID and command not in seen:
                        commands.append(command)
                        seen.add(command)
            section = QTreeWidgetItem(self.tree, [tr(title)])
            font = section.font(0)
            font.setBold(True)
            section.setFont(0, font)
            section.setFirstColumnSpanned(True)
            for command in commands:
                keys = ", ".join(QKeySequenceText(key) for key in host.commands.config["keys"].get(command, []))
                QTreeWidgetItem(section, [tr(BY_ID[command].title).rstrip("…"), keys, tr(HELP.get(command, ""))])
        self.tree.expandAll()
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.search.textChanged.connect(self.filter)
        row = QHBoxLayout()
        change = QPushButton(tr('Change shortcuts…'))
        change.clicked.connect(lambda: (self.close(), host.show_settings("controls")))
        row.addWidget(change)
        row.addStretch()
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)

    def filter(self, text):
        text = text.casefold()
        for index in range(self.tree.topLevelItemCount()):
            section = self.tree.topLevelItem(index)
            visible = 0
            for child in range(section.childCount()):
                item = section.child(child)
                match = not text or any(text in item.text(column).casefold() for column in range(3))
                item.setHidden(not match)
                visible += match
            section.setHidden(visible == 0)


def QKeySequenceText(key):
    from PySide6.QtGui import QKeySequence
    return QKeySequence.fromString(key, QKeySequence.SequenceFormat.PortableText).toString(QKeySequence.SequenceFormat.NativeText)
