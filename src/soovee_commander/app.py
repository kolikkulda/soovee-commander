from __future__ import annotations
from .i18n import LANGUAGES, install_qt_translations, set_language, tr, ui_retranslator, retranslate_widgets

from datetime import datetime
import os
import json
from pathlib import Path
import sys
from threading import Event
import time
import uuid
from .diagnostic_log import logger
from .diagnostic_ui import DiagnosticDialog

from PySide6.QtCore import (QFile, QItemSelectionModel, QObject, QRunnable, QSettings, QSignalBlocker, QSize, QUrl,
                           Qt, QThreadPool, QTimer, Signal)
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMenuBar, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QSplitter, QStyle, QTreeView, QToolButton, QVBoxLayout, QWidget,
)

from .transfer_status import PREFIX as TRANSFER_PREFIX
from .transfer_ui import TransferDialog
from .operations import Cancelled, copy_entries, create_zip, move_local, preview
from .providers import ArchiveProvider, Connection, Entry, LocalProvider, RemoteProvider, is_archive, safe_name
from .device_files import DeviceProvider
from .filemodel import size_text
from .panel import Panel
from .splitter import PanelSplitter
from .toolbar_icons import toolbar_icon
from .themes import THEMES, apply_theme, stylesheet
from .editor import EDITOR_LIMIT, TextEditor
from .qt_runtime import prepare_plugins
from .associations import Associations, AssociationsDialog, OpenWithDialog
from .extensions import ExtensionsDialog, launch as launch_external
from .advanced import check as check_cancel, folder_size, move_entries, multi_rename
from .clipboard import FileClipboard
from .tool_dialogs import SearchDialog, MultiRenameDialog, CompareDialog, FileCompareDialog
from . import __version__
from .commands import BY_ID, CommandRegistry
from .command_help import HELP, MENUS, SUBMENUS
from . import dialog_kit
from .control_settings import ControlsDialog
from .update_ui import choose_update, show_update_result
from .new_files import BY_KEY as NEW_FILE_TYPES, TYPES as NEW_FILE_LIST, NewFileDialog, content as new_file_content, templates_folder, user_templates


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int)
    finished = Signal()


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.signals = Signals()
        self.function = function
        self.identifier = uuid.uuid4().hex[:12]

    def run(self):
        started = time.monotonic()
        logger.info('Task started · id=%s · action=%s', self.identifier, getattr(self.function, '__qualname__', type(self.function).__name__))
        pending, message, last = 0, "", 0

        def report(text, count):
            nonlocal pending, message, last
            if text.startswith('@update:'):
                self.signals.progress.emit(text, count)
                return
            if text.startswith(TRANSFER_PREFIX):
                event = json.loads(text[len(TRANSFER_PREFIX):])
                if event['event'] not in ('advance', 'scan'):
                    logger.info('Task event · id=%s · %s', self.identifier, text)
                if event['event'] not in ('advance', 'scan') or time.monotonic() - last >= .05:
                    if pending:
                        self.signals.progress.emit(message, pending)
                        pending = 0
                    self.signals.progress.emit(text, 0)
                    last = time.monotonic()
                return
            pending += count
            message = text
            now = time.monotonic()
            if now - last >= 0.05:
                self.signals.progress.emit(message, pending)
                pending, last = 0, now
        try:
            result = self.function(report)
            if message:
                self.signals.progress.emit(message, pending)
            self.signals.done.emit(result)
            logger.info('Task completed · id=%s · elapsed=%.3fs', self.identifier, time.monotonic() - started)
        except Exception as exc:
            logger.exception('Task failed · id=%s · elapsed=%.3fs', self.identifier, time.monotonic() - started)
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        finally:
            self.signals.finished.emit()


class ConnectDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr('Connect to server'))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        heading = QLabel(tr('Remote files, the same workflow.'))
        heading.setObjectName("dialogHeading")
        layout.addWidget(heading)
        try:
            self.profiles = json.loads(parent.settings.value("connections", "[]"))
            self.profiles = [p for p in self.profiles if isinstance(p, dict) and "host" in p]
        except (ValueError, TypeError):
            self.profiles = []
        profile_row = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.addItem(tr('New connection'))
        for profile in self.profiles:
            self.profile.addItem(profile.get("name", profile["host"]))
        self.profile.activated.connect(self.load_profile)
        profile_row.addWidget(self.profile, 1)
        forget = QPushButton(tr('Remove profile'))
        forget.clicked.connect(self.forget_profile)
        profile_row.addWidget(forget)
        save_profile = QPushButton(tr('Save profile'))
        save_profile.clicked.connect(self.store_profile)
        profile_row.addWidget(save_profile)
        layout.addLayout(profile_row)
        form = QFormLayout()
        self.profile_name = QLineEdit()
        form.addRow(tr("Connection name"), self.profile_name)
        self.protocol = QComboBox()
        self.protocol.addItems(["SFTP", "FTPS", "FTP"])
        self.host, self.port, self.user, self.password = QLineEdit(), QLineEdit("22"), QLineEdit(), QLineEdit()
        self.host.setPlaceholderText("server.example.com")
        self.user.setPlaceholderText(tr('Username'))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.keyfile, self.path = QLineEdit(), QLineEdit("/")
        keyrow = QHBoxLayout()
        browse = QPushButton(tr('Browse…'))
        browse.clicked.connect(self.choose_key)
        keyrow.addWidget(self.keyfile)
        keyrow.addWidget(browse)
        for title, widget in [(tr('Protocol'), self.protocol), ("Server", self.host), ("Port", self.port),
                              (tr('User'), self.user), (tr('Password / key passphrase'), self.password)]:
            form.addRow(title, widget)
        form.addRow(tr('Private SSH key'), keyrow)
        form.addRow(tr('Initial path'), self.path)
        layout.addLayout(form)
        self.save = QCheckBox(tr('Save connection settings without password'))
        self.save.setChecked(True)
        layout.addWidget(self.save)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        layout.addWidget(self.note)
        self.protocol.currentTextChanged.connect(self.protocol_changed)
        self.protocol_changed("SFTP")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('Connect'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Cancel'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def store_profile(self):
        try:
            connection = self.connection()
            self.save.setChecked(True)
            self.save_profile(connection)
            self.profile.clear()
            self.profile.addItem(tr('New connection'))
            for profile in self.profiles:
                self.profile.addItem(profile.get('name', profile['host']))
            self.profile.setCurrentIndex(len(self.profiles))
            self.note.setText(tr('Profile saved. Passwords are not saved.'))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr('Cannot complete operation'), str(exc))

    def load_profile(self, index):
        if index <= 0:
            self.profile_name.clear()
            self.host.clear()
            self.user.clear()
            self.password.clear()
            self.keyfile.clear()
            self.path.setText('/')
            self.protocol_changed(self.protocol.currentText())
            return
        profile = self.profiles[index - 1]
        self.profile_name.setText(profile.get("name", ""))
        self.protocol.setCurrentText(profile.get("protocol", "SFTP"))
        self.host.setText(profile["host"])
        self.port.setText(str(profile.get("port", 22)))
        self.user.setText(profile.get("username", ""))
        self.keyfile.setText(profile.get("keyfile", ""))
        self.path.setText(profile.get("path", "/"))
        self.password.clear()
        self.password.setFocus()

    def forget_profile(self):
        index = self.profile.currentIndex()
        if index > 0:
            self.profiles.pop(index - 1)
            self.profile.removeItem(index)
            self.parent().settings.setValue("connections", json.dumps(self.profiles))

    def save_profile(self, connection):
        if not self.save.isChecked():
            return
        profile = {"protocol": connection.protocol, "host": connection.host, "port": connection.port,
                   "username": connection.username, "keyfile": connection.keyfile,
                   "path": self.path.text() or "/"}
        profile["name"] = connection.name or f"{connection.protocol} · {connection.username}@{connection.host}:{connection.port}"
        index = self.profile.currentIndex()
        if index > 0:
            self.profiles.pop(index - 1)
        self.profiles = [p for p in self.profiles if p.get("name") != profile["name"]]
        self.profiles.append(profile)
        self.parent().settings.setValue("connections", json.dumps(self.profiles))

    def choose_key(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Private SSH key'), str(Path.home() / ".ssh"))
        if path:
            self.keyfile.setText(path)

    def protocol_changed(self, protocol):
        self.port.setText("22" if protocol == "SFTP" else "21")
        self.keyfile.setEnabled(protocol == "SFTP")
        # Plain FTP is offered last and its warning is shown in red, not as a muted hint.
        self.note.setStyleSheet("color: #c93a3a; font-weight: 600;" if protocol == "FTP" else "")
        self.note.setText({
            "SFTP": tr('The host key must be in ~/.ssh/known_hosts. Verify it with OpenSSH before connecting. Passwords stay in memory.'),
            "FTPS": tr('Explicit TLS, certificate verification and encrypted data channel. Passwords are not saved.'),
            "FTP": tr('Not secure: FTP sends passwords and data without encryption. Use SFTP or FTPS whenever the server supports it.'),
        }[protocol])

    def accept(self):
        text = self.host.text().strip()
        protocol = text.split("://", 1)[0].upper() if "://" in text else self.protocol.currentText()
        if protocol == "FTP":
            from .dialog_kit import confirm
            if not confirm(self, tr('Unencrypted connection'), tr('Connect without encryption?'),
                           tr('With FTP, anyone on the network path can read the password and the files. Use SFTP or FTPS whenever the server supports it.'),
                           action=tr('Connect anyway'), destructive=True):
                return
        super().accept()

    def connection(self):
        from urllib.parse import urlsplit, unquote
        if "://" in self.host.text():
            url = urlsplit(self.host.text().strip())
            if url.scheme.upper() not in ("FTP", "FTPS", "SFTP") or not url.hostname:
                raise ValueError(tr('Enter an FTP, FTPS or SFTP address.'))
            self.protocol.setCurrentText(url.scheme.upper())
            self.host.setText(url.hostname)
            self.port.setText(str(url.port or (22 if url.scheme.lower() == "sftp" else 21)))
            if url.username is not None:
                self.user.setText(unquote(url.username))
            if url.password is not None:
                self.password.setText(unquote(url.password))
            self.path.setText(unquote(url.path) or "/")
        port = int(self.port.text())
        if not 1 <= port <= 65535:
            raise ValueError(tr('Port must be between 1 and 65535.'))
        return Connection(self.protocol.currentText(), self.host.text().strip(), port,
                          self.user.text().strip(), self.password.text(), self.keyfile.text().strip(), self.profile_name.text().strip())


STYLE = stylesheet("light")


class Commander(QMainWindow):
    def __init__(self, left=None, right=None):
        super().__init__()
        self.setWindowTitle("Soovee Commander")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "soovee-commander-icon.png")))
        self.resize(1440, 900)
        self.setMinimumSize(1080, 680)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.transfer_pool = QThreadPool(self)
        self.transfer_pool.setMaxThreadCount(1)
        self.tasks = set()
        self.pending_jobs = 0
        self.failed_jobs = 0
        self.cancel_events = set()
        self.preview_windows = []
        self.file_clipboard = FileClipboard()
        self.last_rename = None
        self.external_processes = set()
        self.settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "StereoCommander", "StereoCommander")
        self.language = set_language(self.settings.value("language", "cs" if self.settings.contains("left_tabs") else "en"))
        self.settings.setValue("language", self.language)
        install_qt_translations(QApplication.instance())
        self.associations = Associations(self)
        self.theme_key = self.settings.value("theme", "soovee")
        if self.theme_key not in THEMES:
            self.theme_key = "light"
        apply_theme(QApplication.instance(), self.theme_key)
        central = QWidget()
        self.setCentralWidget(central)
        layout = self.main_layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(7)
        toolbar = self.toolbar = QFrame()
        toolbar.setObjectName("mainToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(2, 1, 2, 5)
        tools.setSpacing(5)
        self.utility_buttons = []
        self.theme_combo = QComboBox(self)
        for key, theme in THEMES.items():
            self.theme_combo.addItem(tr(theme["name"]), key)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.theme_key))
        self.theme_combo.currentIndexChanged.connect(lambda index: self.change_theme(self.theme_combo.itemData(index)))
        self.theme_combo.hide()
        self.appearance_menu = QMenu(self)
        self.appearance_actions = {}
        for key, theme in THEMES.items():
            action = self.appearance_menu.addAction(tr(theme["name"]))
            action.setCheckable(True)
            action.setChecked(key == self.theme_key)
            action.triggered.connect(lambda checked=False, k=key: self.theme_combo.setCurrentIndex(self.theme_combo.findData(k)))
            self.appearance_actions[key] = action
        home = self.utility_button("home", tr("Home"))
        home.clicked.connect(lambda: self.active.navigate(LocalProvider(), str(Path.home())))
        tools.addWidget(home)
        tools.addStretch()
        self.hidden = QCheckBox(tr("Hidden files"))
        self.hidden.setChecked(True)
        self.hidden.toggled.connect(self.toggle_hidden)
        tools.addWidget(self.hidden)
        appearance = self.utility_button("appearance", tr("Appearance"))
        appearance.setMenu(self.appearance_menu)
        appearance.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tools.addWidget(appearance)
        update = self.utility_button("update", tr("Update…"))
        update_menu = QMenu(update)
        update_menu.addAction(tr("Select update folder…"), lambda: choose_update(self, True))
        update_menu.addAction(tr("Select update file…"), lambda: choose_update(self, False))
        update.setMenu(update_menu)
        update.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tools.addWidget(update)
        devices = self.utility_button("devices", tr("Soovee Transfers · Devices"))
        devices.setText(tr("Devices"))
        devices.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        devices.clicked.connect(self.show_devices)
        tools.addWidget(devices)
        server = self.utility_button("connect", tr("Connect to server…"))
        server.setObjectName("connectServerButton")
        server.setText(tr("Connect"))
        server.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        server.clicked.connect(self.connect_server)
        tools.addWidget(server)
        layout.addWidget(toolbar)
        splitter = self.panel_splitter = PanelSplitter()
        leftpath = left or self.settings.value("left", str(Path.home()))
        rightpath = right or self.settings.value("right", str(Path.home() / "Downloads"))
        if not Path(leftpath).is_dir():
            leftpath = str(Path.home())
        if not Path(rightpath).is_dir():
            rightpath = str(Path.home())
        self.left = Panel(self, tr('LEFT PANEL'), leftpath, side='left')
        self.right = Panel(self, tr('RIGHT PANEL'), rightpath, side='right')
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)
        splitter.setSizes([650, 650])
        workspace = QHBoxLayout()
        workspace.setSpacing(8)
        sidebar = self.sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(154)
        places = QVBoxLayout(sidebar)
        places.setContentsMargins(8, 0, 8, 8)
        places.setSpacing(2)
        caption = QLabel(tr('QUICK ACCESS'))
        caption.setObjectName("sectionLabel")
        places.addWidget(caption)
        for title, path in [(tr('⌂  Home'), Path.home()), ("▤  " + tr("Documents"), Path.home() / "Documents"),
                            (tr('↓  Downloads'), Path.home() / "Downloads"), ("▧  " + tr("Desktop"), Path.home() / "Desktop")]:
            button = QPushButton(title)
            button.setObjectName("navItem")
            button.clicked.connect(lambda checked=False, p=path: self.active.navigate(LocalProvider(), str(p)))
            places.addWidget(button)
        choose = QPushButton(tr('＋  Open folder'))
        choose.setObjectName("navItem")
        choose.clicked.connect(self.choose_directory)
        places.addWidget(choose)
        remote_label = QLabel(tr('CONNECTIONS'))
        remote_label.setObjectName("sectionLabel")
        places.addWidget(remote_label)
        remote = QPushButton("◎  " + tr("Servers"))
        remote.setObjectName("navItem")
        remote.clicked.connect(self.connect_server)
        places.addWidget(remote)
        places.addStretch()
        hint = self.shortcut_hint = QLabel()
        hint.setObjectName("sidebarNote")
        places.addWidget(hint)
        workspace.addWidget(sidebar)
        sidebar.setVisible(self.settings.value("sidebar_visible", False, type=bool))
        workspace.addWidget(splitter, 1)
        layout.addLayout(workspace, 1)
        self.active = self.left
        self.activate(self.left)
        queuebar = QHBoxLayout()
        self.queue_label = QLabel(tr('TRANSFER QUEUE  ·  Ready'))
        self.queue_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.queue_label.setObjectName("muted")
        queuebar.addWidget(self.queue_label, 1)
        history = self.history_button = QPushButton(tr('Operation history'))
        history.setCheckable(True)
        history.toggled.connect(lambda checked: self.log.setVisible(checked))
        queuebar.addWidget(history)
        self.cancel_button = QPushButton(tr('Cancel transfers'))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_transfers)
        queuebar.addWidget(self.cancel_button)
        layout.addLayout(queuebar)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        self.log.setMaximumBlockCount(10000)
        self.log.hide()
        layout.addWidget(self.log)
        self.command_bar = QHBoxLayout()
        self.top_buttons = []
        self.bottom_buttons = []
        self.top_action_layout = tools
        layout.addLayout(self.command_bar)
        self.commands = CommandRegistry(self, self.command_callbacks())
        self.commands.changed.connect(self.rebuild_command_bars)
        self.rebuild_command_bars()
        self.create_menus()
        self.change_theme(self.theme_key, persist=False)
        if left is None:
            self.restore_panel_tabs("left", self.left)
        if right is None:
            self.restore_panel_tabs("right", self.right)
        self.left.active_view().setFocus()
        if self.settings.value('lan_enabled', bool(self.settings.value('lan_port', 0)), type=bool):
            QTimer.singleShot(0, self, self.restore_local_transfers)
        QApplication.instance().applicationStateChanged.connect(self.application_state_changed)
        for panel in (self.left, self.right):
            panel.tree.selectionModel().currentChanged.connect(lambda *args, source=panel: self.quick_view_follow(source))

    def quick_view_follow(self, source):
        target = self.right if source is self.left else self.left
        if target.quick_view_active():
            target.quick.request(source)

    def toggle_quick_view(self):
        """Ctrl+Q (Control+Q on macOS): preview the cursor item in the other panel."""
        for panel in (self.left, self.right):
            if panel.quick_view_active():
                panel.close_quick_view()
                return
        target = self.other()
        target.open_quick_view()
        target.quick.shown_key = None
        target.quick.request(self.active)
        self.active.active_view().setFocus()

    def toggle_internal_previews(self, from_settings=False):
        if not from_settings:
            self.settings.setValue("internal_previews", self.commands.actions["internal_previews"].isChecked())
        for panel in (self.left, self.right):
            if panel.quick_view_active():
                panel.quick.shown_key = None
                self.quick_view_follow(self.right if panel is self.left else self.left)

    def set_preview_group(self, group, enabled):
        self.settings.setValue("preview_" + group, enabled)
        self.toggle_internal_previews()

    def application_state_changed(self, state):
        # Returning to the app catches changes the folder watcher cannot see:
        # rewritten file contents and network volumes without notifications.
        if state == Qt.ApplicationState.ApplicationActive and self.settings.value("auto_refresh", True, type=bool):
            for panel in (self.left, self.right):
                panel.auto_refresh("activate")

    def toggle_auto_refresh(self):
        self.settings.setValue("auto_refresh", self.commands.actions["auto_refresh"].isChecked())
        for panel in (self.left, self.right):
            panel.configure_auto_refresh()

    def set_refresh_interval(self, seconds):
        self.settings.setValue("auto_refresh_interval", seconds)
        for panel in (self.left, self.right):
            panel.configure_auto_refresh()

    def toggle_folders_first(self):
        enabled = self.commands.actions["folders_first"].isChecked()
        self.settings.setValue("folders_first", enabled)
        for panel in (self.left, self.right):
            panel.model.folders_first = enabled
            panel.save_view()
            panel.model.rebuild(preserve=True)

    def populate_previews_menu(self, menu):
        from .document_preview import GROUPS, pdf_available
        master = self.commands.actions["internal_previews"]
        master.setCheckable(True)
        master.setChecked(self.settings.value("internal_previews", True, type=bool))
        master.setStatusTip(tr('Show common documents in F3 and the quick view without another application.'))
        menu.addAction(master)
        menu.addSeparator()
        menu.setToolTipsVisible(True)
        for group, (title, suffixes) in GROUPS.items():
            action = menu.addAction(tr(title))
            action.setCheckable(True)
            action.setChecked(self.settings.value("preview_" + group, True, type=bool))
            action.setToolTip(" ".join(sorted(suffixes)))
            action.toggled.connect(lambda checked, key=group: self.set_preview_group(key, checked))
            self.preview_actions[group] = action
            if group == "pdf" and not pdf_available():
                action.setEnabled(False)
                action.setToolTip(tr('Not available: this build does not include the Qt PDF module.'))

    def populate_new_menu(self, menu):
        menu.clear()
        for item in NEW_FILE_LIST:
            label = tr(item.title) + (f"  ({item.extension})" if item.extension else "")
            menu.addAction(label, lambda checked=False, key=item.key: self.new_file(key))
        templates = user_templates()
        if templates:
            menu.addSeparator()
            for template in templates:
                menu.addAction(template.name, lambda checked=False, path=str(template): self.new_file("template:" + path))
        menu.addSeparator()
        menu.addAction(self.commands.actions["mkdir"])
        menu.addAction(self.commands.actions["templates_folder"])

    def new_menu(self, parent):
        menu = QMenu(tr('New'), parent)
        menu.setObjectName("newFileMenu")
        menu.aboutToShow.connect(lambda: self.populate_new_menu(menu))
        self.populate_new_menu(menu)  # Native macOS menus need items before first display.
        return menu

    def open_templates_folder(self):
        folder = templates_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return self.error(str(exc))
        self.active.new_tab(LocalProvider(), str(folder))

    def new_file(self, key="text"):
        """Create a file in the active folder (Shift+F4) without replacing anything."""
        panel = self.active
        provider, folder = panel.provider, panel.path
        if provider.readonly or not panel.tree.isEnabled():
            return self.error(tr('Files cannot be created in this location.'))
        dialog = NewFileDialog(self, key, [entry.name for entry in panel.entries])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        file_type, template = dialog.selected()
        name = dialog.name.text().strip()
        open_editor = dialog.open_editor.isEnabled() and dialog.open_editor.isChecked()
        try:
            path = provider.join(folder, name)
        except ValueError as exc:
            return self.error(str(exc))

        def work(_):
            data = template.read_bytes() if template else new_file_content(file_type.key, name)
            with provider.batch():
                if provider.exists(path):
                    raise FileExistsError(tr('An item with this name already exists.'))
                if isinstance(provider, LocalProvider):
                    provider.write_with(path, lambda output: output.write(data), lambda count: None)
                    if file_type and file_type.executable and os.name != "nt":
                        os.chmod(path, os.stat(path).st_mode | 0o111)
                else:
                    import io
                    provider.write_from(path, io.BytesIO(data), lambda count: None)

        def created(_):
            panel.navigate(provider, folder, remember=False, focus_name=name, background=True)
            if open_editor:
                self.open_editor(provider, path)

        self.run_task(work, created)

    def utility_button(self, command, title):
        button = QToolButton()
        button.setObjectName("toolbarButton")
        button.setProperty("icon_command", command)
        button.setIcon(toolbar_icon(command, THEMES[self.theme_key]["primary_text"] if command == "connect" else THEMES[self.theme_key]["text"]))
        button.setIconSize(QSize(20, 20))
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.setAutoRaise(True)
        button.setMinimumSize(32, 30)
        self.utility_buttons.append(button)
        return button

    def change_theme(self, key, persist=True):
        if key not in THEMES:
            return
        self.theme_key = key
        apply_theme(QApplication.instance(), key)
        for panel in (getattr(self, "left", None), getattr(self, "right", None)):
            if panel:
                panel.model.archive_color = QColor(THEMES[key]["archive"])
                panel.tree.viewport().update()
        for button in (*getattr(self, "utility_buttons", []), *getattr(self, "top_buttons", [])):
            command = button.property("icon_command")
            if command:
                button.setIcon(toolbar_icon(command, THEMES[key]["primary_text"] if command == "connect" else THEMES[key]["text"]))
        for theme, action in getattr(self, "appearance_actions", {}).items():
            action.setChecked(theme == key)
        from .text_widgets import CodeEditor, SyntaxHighlighter
        for editor in self.findChildren(CodeEditor):
            editor.set_colors(THEMES[key])
        for highlighter in self.findChildren(SyntaxHighlighter):
            highlighter.configure(highlighter.path, THEMES[key])
        if persist:
            self.settings.setValue("theme", key)

    def restore_panel_tabs(self, name, panel):
        try:
            data = json.loads(self.settings.value(f"{name}_tabs", "{}"))
            panel.restore_tabs(data)
        except (ValueError, TypeError):
            pass

    def command_callbacks(self):
        return {
            **{f"external_{i + 1}": lambda slot=i: launch_external(self, slot) for i in range(16)},
            "external_settings": lambda: self.show_settings("external"),
            "shortcuts_help": self.show_shortcuts, "install_update": lambda: choose_update(self, False),
            "devices": self.show_devices,
            "about": self.show_about,
            "diagnostic_log": lambda: self.open_tool(DiagnosticDialog),
            "panel_scrolling": lambda: self.active.configure_scrolling(),
            "about_qt": lambda: QMessageBox.aboutQt(self, tr("About Qt")),
            "center_panels": self.panel_splitter.center_panels,
            "open_with": self.show_open_with, "file_associations": lambda: self.show_settings("associations"),
            "columns": lambda: self.active.configure_columns(), "properties": self.show_properties,
            "panel_appearance": lambda: self.active.appearance.configure(),
            "extract": self.extract_archives, "copy_details": self.copy_details,
            "move_tab_other": lambda: self.active.move_tab_to(self.active._current, self.other()),
            "reveal": self.reveal, "copy_names": self.copy_names,
            "open": lambda: self.active.open_current(), "parent": lambda: self.active.parent(),
            "root": lambda: self.active.root(), "enter_directory": lambda: self.active.enter_directory(),
            "switch_panel": self.switch_panel, "toggle_mark": lambda: self.active.toggle_mark(),
            "view": self.show_preview, "edit": self.show_editor, "rename": self.rename,
            "copy": self.copy, "move": self.move, "mkdir": self.mkdir, "delete": self.delete,
            "clipboard_copy": lambda: self.clipboard_copy(False), "clipboard_cut": lambda: self.clipboard_copy(True),
            "clipboard_paste": self.clipboard_paste, "delete_permanent": lambda: self.delete(permanent=True),
            "search": lambda: self.open_tool(SearchDialog), "multi_rename": self.show_multi_rename,
            "undo_rename": self.undo_multi_rename, "compare_dirs": lambda: self.open_tool(CompareDialog),
            "compare_files": self.compare_files, "folder_sizes": self.calculate_sizes, "auto_sizes": self.toggle_auto_sizes,
            "rename_tab": lambda: self.active.rename_tab(), "lock_tab": lambda: self.active.toggle_lock(),
            "pack": self.pack, "refresh": lambda: self.active.refresh(),
            "auto_refresh": self.toggle_auto_refresh, "new_file": lambda: self.new_file(),
            "templates_folder": self.open_templates_folder, "sort_added": lambda: self.sort_active(15),
            "folders_first": self.toggle_folders_first,
            "quick_view": self.toggle_quick_view, "internal_previews": self.toggle_internal_previews,
            "back": lambda: self.active.back(), "forward": lambda: self.active.forward(),
            "focus_path": self.focus_address, "filter": lambda: self.active.filter.setFocus(),
            "copy_paths": lambda: self.active.copy_paths(), "copy_directory": lambda: self.active.copy_directory(),
            "paste_path": lambda: self.active.paste_path(), "new_tab": lambda: self.active.new_tab(),
            "new_tab_background": lambda: self.active.new_tab(activate=False),
            "open_dir_newtab": lambda: self.active.open_directory_new_tab(),
            "open_dir_other_tab": self.open_directory_other_tab,
            "close_tab": lambda: self.active.close_tab(), "reopen_tab": lambda: self.active.reopen_tab(),
            "next_tab": lambda: self.active.cycle_tab(1), "previous_tab": lambda: self.active.cycle_tab(-1),
            "close_other_tabs": lambda: self.active.close_other_tabs(),
            "select_all": lambda: self.active.tree.selectAll(),
            "clear_selection": lambda: self.active.tree.clearSelection(),
            "invert_selection": lambda: self.active.invert_selection(),
            "swap": self.swap, "same_path": self.same_path,
            "sort_name": lambda: self.sort_active(0), "sort_extension": lambda: self.sort_active(4),
            "sort_date": lambda: self.sort_active(2), "sort_size": lambda: self.sort_active(1),
            "left_drive": lambda: self.left.show_drives(), "right_drive": lambda: self.right.show_drives(),
            "context_menu": lambda: self.active.show_context_menu(), "history_menu": lambda: self.active.history_menu(),
            "home": lambda: self.active.navigate(LocalProvider(), str(Path.home())),
            "local": self.disconnect, "choose_directory": self.choose_directory,
            "connect": self.connect_server, "settings": lambda: self.show_settings(), "quit": self.close,
        }

    def sort_active(self, column):
        panel = self.active
        descending = panel.model.column == column and not panel.model.descending
        panel.tree.sortByColumn(column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)

    def open_directory_other_tab(self):
        entry = self.active.current_entry()
        if entry and entry.is_dir:
            self.other().new_tab(self.active.provider, self.active.provider.join(self.active.path, entry.name))

    def configure_controls(self):
        return self.show_settings("controls")

    def rebuild_command_bars(self):
        for layout, buttons, items, bottom in [
                (self.top_action_layout, self.top_buttons, self.commands.config["top"], False),
                (self.command_bar, self.bottom_buttons, self.commands.config["bottom"], True)]:
            for button in buttons:
                layout.removeWidget(button)
                button.hide()
                button.deleteLater()
            buttons.clear()
            for index, item in enumerate(items):
                if bottom:
                    button = QPushButton(self.commands.button_label(item, include_key=True))
                else:
                    button = QToolButton()
                    button.setObjectName("toolbarButton")
                    button.setAutoRaise(True)
                    button.setIconSize(QSize(20, 20))
                    button.setProperty("icon_command", item["command"])
                    button.setIcon(toolbar_icon(item["command"], THEMES[self.theme_key]["text"]))
                    button.setAccessibleName(tr(BY_ID[item["command"]].title))
                    button.setMinimumHeight(30)
                    if item.get("label"):
                        button.setText(item["label"])
                        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                button.setMinimumWidth(32 if not bottom else 36)
                button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
                button.setProperty("command_id", item["command"])
                if item.get('label'):
                    button.setProperty('userContent', True)
                action = self.commands.actions[item["command"]]
                button.clicked.connect(lambda checked=False, a=action: a.trigger())
                description = HELP.get(item["command"])
                button.setToolTip(tr(BY_ID[item["command"]].title) + "  " + self.commands.key_label(item["command"])
                                  + ("\n" + tr(description) if description else ""))
                layout.insertWidget(index, button, 1 if bottom else 0)
                buttons.append(button)
        for panel in (self.left, self.right):
            panel.refresh_control_labels()
        self.shortcut_hint.setText("\n".join(self.commands.key_label(command) + "  " + title
                                            for command, title in [("switch_panel", tr('other panel')), ("view", tr('preview')),
                                                                   ("copy", tr('copy')), ("pack", "ZIP")]))
        rename_key = self.commands.key_label("rename")
        self.statusBar().showMessage(tr('v{v0}  ·  ZIP / TAR  ·  FTP / FTPS / SFTP  ·  {v1} rename  ·  Settings: shortcuts and buttons').format(v0=__version__, v1=rename_key))

    def create_menus(self):
        """Main menu from command_help.MENUS; every command shows its description in the status bar."""
        bar = self.command_menu = QMenuBar(self)
        bar.setNativeMenuBar(sys.platform == "darwin")
        self.setMenuBar(bar)
        self.statusBar()
        for command in ("auto_refresh", "folders_first", "auto_sizes", "internal_previews"):
            self.commands.actions[command].setCheckable(True)
        self.hidden_action = QAction(tr('Show hidden files'), self)
        self.hidden_action.setCheckable(True)
        self.hidden_action.setChecked(self.hidden.isChecked())
        self.hidden_action.setStatusTip(tr('Files whose names start with a dot, and system files.'))
        self.hidden_action.toggled.connect(self.hidden.setChecked)
        self.hidden.toggled.connect(lambda on: self.hidden_action.setChecked(on))
        self.sidebar_action = QAction(tr('Quick access sidebar'), self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(not self.sidebar.isHidden())
        self.sidebar_action.setStatusTip(tr('Home, Documents, Downloads and Desktop on the left of the window.'))
        self.sidebar_action.toggled.connect(lambda checked: (self.sidebar.setVisible(checked), self.settings.setValue("sidebar_visible", checked)))
        self.appearance_menu.setTitle(tr('Colour theme'))
        self.interval_actions, self.preview_actions, self.language_actions = {}, {}, {}

        def fill(menu, entries):
            menu.setToolTipsVisible(True)
            for entry in entries:
                if entry is None:
                    menu.addSeparator()
                elif entry in SUBMENUS:
                    fill(menu.addMenu(tr({"@sort": 'Sort by', "@tabs": 'Tabs'}[entry])), SUBMENUS[entry])
                elif entry == "@new":
                    menu.addMenu(self.new_menu(menu))
                elif entry == "@interval":
                    sub = menu.addMenu(tr('Refresh periodically'))
                    choices = QActionGroup(sub)
                    for seconds, label in ((0, 'Off'), (5, 'Every 5 seconds'), (15, 'Every 15 seconds'), (60, 'Every minute')):
                        action = sub.addAction(tr(label), lambda checked=False, value=seconds: self.set_refresh_interval(value))
                        action.setCheckable(True)
                        action.setStatusTip(tr('Also re-reads servers and connected devices while Soovee is in front.'))
                        choices.addAction(action)
                        self.interval_actions[seconds] = action
                elif entry == "@previews":
                    self.populate_previews_menu(menu.addMenu(tr('Built-in previews')))
                elif entry == "@hidden":
                    menu.addAction(self.hidden_action)
                elif entry == "@sidebar":
                    menu.addAction(self.sidebar_action)
                elif entry == "@theme":
                    menu.addMenu(self.appearance_menu)
                elif entry == "@language":
                    sub = menu.addMenu(tr("Language"))
                    for key, name in LANGUAGES:
                        action = sub.addAction(tr(name))
                        action.setCheckable(True)
                        action.triggered.connect(lambda checked=False, code=key: self.change_language(code))
                        self.language_actions[key] = action
                else:
                    menu.addAction(self.commands.actions[entry])

        for title, entries in MENUS:
            fill(bar.addMenu(tr(title)), entries)
        self.commands.actions['settings'].setMenuRole(QAction.MenuRole.PreferencesRole)
        self.commands.actions['quit'].setMenuRole(QAction.MenuRole.QuitRole)
        self.commands.actions['about'].setMenuRole(QAction.MenuRole.AboutRole)
        self.commands.actions['about_qt'].setMenuRole(QAction.MenuRole.AboutQtRole)
        self.sync_menu_states()

    def sync_menu_states(self):
        """Checkmarks always mirror stored settings, whichever window changed them."""
        for command, key, default in (("auto_refresh", "auto_refresh", True), ("folders_first", "folders_first", True),
                                      ("auto_sizes", "auto_sizes", False), ("internal_previews", "internal_previews", True)):
            action = self.commands.actions[command]
            with QSignalBlocker(action):
                action.setChecked(self.settings.value(key, default, type=bool))
        interval = self.settings.value("auto_refresh_interval", 0, type=int)
        for seconds, action in self.interval_actions.items():
            action.setChecked(seconds == interval)
        for group, action in self.preview_actions.items():
            with QSignalBlocker(action):
                action.setChecked(self.settings.value("preview_" + group, True, type=bool))
        for key, action in self.language_actions.items():
            action.setChecked(key == self.language)

    def show_settings(self, page="general"):
        from .settings_window import SettingsWindow
        dialog = SettingsWindow(self, page)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()
        return dialog

    def show_shortcuts(self):
        from .settings_window import ShortcutsDialog
        dialog = ShortcutsDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        return dialog

    def change_language(self, language):
        translate = ui_retranslator()
        self.language = set_language(language)
        self.settings.setValue("language", self.language)
        self.settings.sync()
        install_qt_translations(QApplication.instance())
        retranslate_widgets(self, translate)
        for index in range(self.theme_combo.count()):
            self.theme_combo.setItemText(index, tr(THEMES[self.theme_combo.itemData(index)]['name']))
        for key, action in self.language_actions.items():
            action.setChecked(key == self.language)
        self.commands.apply(self.commands.config, persist=False)
        for dialog in tuple(self.preview_windows):
            if isinstance(dialog, TextEditor):
                dialog.update_title()
                dialog.update_position()
        for panel in (self.left, self.right):
            panel.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, panel.model.columnCount() - 1)
            if panel.model.rowCount():
                panel.model.dataChanged.emit(panel.model.index(0, 0), panel.model.index(panel.model.rowCount() - 1, panel.model.columnCount() - 1))
            panel.update_footer()
            panel.render_storage()

    def run_task(self, function, done=lambda value: None, failed=None, transfer=False, report=None, quiet=False, read_only=False):
        """quiet/read_only: the task only reads (listings, previews, sizes) and may be
        abandoned, so it never delays closing the window. Writes keep the close guard."""
        task = Task(function)
        task.quiet = quiet or read_only
        self.tasks.add(task)
        task.signals.done.connect(done)
        task.signals.failed.connect(lambda message: (failed or self.error)(tr(message)))
        if report:
            task.signals.progress.connect(lambda message, count: report(message if message.startswith((TRANSFER_PREFIX, '@update:')) else tr(message), count))
        task.signals.finished.connect(lambda: self.tasks.discard(task))
        (self.transfer_pool if transfer else self.pool).start(task)

    def activate(self, panel):
        self.active = panel
        for candidate in (getattr(self, "left", None), getattr(self, "right", None)):
            if candidate:
                candidate.setProperty("active", candidate == panel)
                candidate.style().unpolish(candidate)
                candidate.style().polish(candidate)
                heading = candidate.findChild(QFrame, "panelHeading")
                if heading:
                    for widget in [heading] + heading.findChildren(QWidget):
                        widget.style().unpolish(widget)
                        widget.style().polish(widget)
                        widget.update()

    def other(self):
        return self.right if self.active == self.left else self.left

    def switch_panel(self):
        target = self.other()
        self.activate(target)
        target.active_view().setFocus()

    def focus_address(self):
        self.active.address.setFocus()
        self.active.address.selectAll()

    def toggle_hidden(self, checked):
        for panel in (self.left, self.right):
            panel.apply_filter()

    def swap(self):
        left, right = (self.left.provider, self.left.path), (self.right.provider, self.right.path)
        self.left.navigate(*right)
        self.right.navigate(*left)

    def same_path(self):
        self.other().navigate(self.active.provider, self.active.path)

    def disconnect(self):
        self.active.navigate(LocalProvider(), str(Path.home()))

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self, tr('Open folder'), self.active.path
                    if isinstance(self.active.provider, LocalProvider) else str(Path.home()))
        if directory:
            self.active.navigate(LocalProvider(), directory)

    def pack(self):
        source, target = self.active, self.other()
        entries = source.action_entries()
        if not entries:
            return
        # Like Total Commander, the archive goes next to the packed items unless the user picks another place.
        folder = source.path if isinstance(source.provider, LocalProvider) else (target.path if isinstance(target.provider, LocalProvider) else None)
        if folder is None:
            return self.error(tr('Choose a local folder in the other panel for the new archive.'))
        from .packing import FORMATS, create_archive
        base = (entries[0].name if entries[0].is_dir else os.path.splitext(entries[0].name)[0]) if len(entries) == 1 else (os.path.basename(source.path.rstrip(os.sep)) or "Archive")
        dialog = dialog_kit.StandardDialog(self, tr('Create archive…'), tr('Pack {v0} items').format(v0=len(entries)),
                                           tr('From: {v0}').format(v0=source.location()), icon="pack", action=tr('Create archive'))
        dialog.add(dialog_kit.item_list(e.name for e in entries))
        form = QFormLayout()
        format_combo = QComboBox()
        for label, key, extension in FORMATS:
            format_combo.addItem(label, key)
        path_edit = QLineEdit(os.path.join(folder, base + FORMATS[0][2]))
        path_edit.setProperty('userContent', True)
        row = QHBoxLayout()
        row.addWidget(path_edit, 1)
        browse = QPushButton(tr('Browse…'))
        row.addWidget(browse)
        other = QPushButton(tr('Other panel'))
        other.setToolTip(tr('Put the archive into the folder shown in the other panel.'))
        other.setEnabled(isinstance(target.provider, LocalProvider))
        row.addWidget(other)
        form.addRow(tr('Archive:'), row)
        form.addRow(tr('Format'), format_combo)
        dialog.body.addLayout(form)
        dialog.note(tr('The selected files and folders will be packed internally. RAR creation is not supported.'))

        def extension_of(key):
            return next(extension for label, k, extension in FORMATS if k == key)

        def strip_known(path):
            for label, key, extension in sorted(FORMATS, key=lambda item: -len(item[2])):
                if path.lower().endswith(extension):
                    return path[:-len(extension)]
            return path

        def format_changed():
            path_edit.setText(strip_known(path_edit.text()) + extension_of(format_combo.currentData()))

        def choose():
            chosen, _ = QFileDialog.getSaveFileName(dialog, tr('Create archive…'), path_edit.text())
            if chosen:
                path_edit.setText(strip_known(chosen) + extension_of(format_combo.currentData()))

        format_combo.currentIndexChanged.connect(format_changed)
        browse.clicked.connect(choose)
        other.clicked.connect(lambda: path_edit.setText(os.path.join(target.path, os.path.basename(path_edit.text()))))
        path_edit.setFocus()
        path_edit.setSelection(len(os.path.dirname(path_edit.text())) + 1, len(os.path.basename(strip_known(path_edit.text()))))
        if dialog.exec() != QDialog.DialogCode.Accepted or not path_edit.text().strip():
            return
        try:
            format = format_combo.currentData()
            destination = os.path.abspath(os.path.expanduser(path_edit.text().strip()))
            if not destination.lower().endswith(extension_of(format)):
                destination += extension_of(format)
            if not os.path.isdir(os.path.dirname(destination)):
                raise FileNotFoundError(tr('The folder for the archive does not exist.'))
            if os.path.exists(destination):
                raise FileExistsError(tr('The archive already exists. Choose another name.'))
            provider, path = source.provider, source.path
            self.enqueue(tr('Create {v0}').format(v0=os.path.basename(destination)), lambda cancel, report:
                         create_archive(provider, path, destination, entries, cancel, report, format))
        except (ValueError, OSError) as exc:
            self.error(str(exc))

    def error(self, message):
        logger.error('Operation error · %s', message)
        message = tr(message)
        if hasattr(self, "log"):
            self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  Error · {message}")
        QMessageBox.warning(self, tr('Cannot complete operation'), message)

    def show_about(self):
        from .about import AboutDialog
        return self.open_tool(AboutDialog)

    def show_devices(self):
        dialog = self.get_devices_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def get_devices_dialog(self):
        from .lan_ui import DevicesDialog
        dialog = getattr(self, "devices_dialog", None)
        if dialog is None:
            dialog = self.devices_dialog = DevicesDialog(self)
            self.preview_windows.append(dialog)
        return dialog

    def restore_local_transfers(self):
        dialog = self.get_devices_dialog()
        dialog._auto_started = True
        dialog.start()

    def connect_server(self):
        dialog = ConnectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                connection = dialog.connection()
                provider = RemoteProvider(connection)
                dialog.save_profile(connection)
                self.active.navigate(provider, dialog.path.text() or "/")
            except (ValueError, OSError) as exc:
                self.error(str(exc))

    def open_remote_url(self, panel, text):
        from urllib.parse import unquote, urlsplit
        try:
            url = urlsplit(text)
            if url.password is not None:
                raise ValueError(tr("Do not use URLs containing passwords. Enter the password in the connection dialog."))
            protocol = url.scheme.upper()
            port = url.port or (22 if protocol == "SFTP" else 21)
            host, username = url.hostname, unquote(url.username or "")
            if not host:
                raise ValueError(tr('The address has no server name.'))
            path = unquote(url.path) or "/"
            matches = []
            for candidate in (self.left, self.right):
                for tab in candidate.tab_states:
                    provider = tab.provider
                    if isinstance(provider, RemoteProvider):
                        c = provider.connection
                        if (c.protocol, c.host.casefold(), c.port) == (protocol, host.casefold(), port) and (not username or c.username == username):
                            if provider not in matches:
                                matches.append(provider)
            if len(matches) == 1 and url.password is None:
                panel.navigate(matches[0], path)
                return
            dialog = ConnectDialog(self)
            dialog.protocol.setCurrentText(protocol)
            dialog.host.setText(host)
            dialog.port.setText(str(port))
            dialog.user.setText(username)
            dialog.path.setText(path)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                connection = dialog.connection()
                dialog.save_profile(connection)
                panel.navigate(RemoteProvider(connection), dialog.path.text() or "/")
        except (ValueError, OSError) as exc:
            self.error(str(exc))

    def enqueue(self, title, function, on_done=None):
        logger.info('Operation queued · %s', title)
        if self.pending_jobs == 0:
            self.failed_jobs = 0
        cancel = Event()
        self.cancel_events.add(cancel)
        self.pending_jobs += 1
        self.progress.setRange(0, 0)
        self.cancel_button.setEnabled(True)
        self.queue_label.setText(tr('TRANSFER QUEUE  ·  {v0} jobs').format(v0=self.pending_jobs))
        self.log.appendPlainText(tr('{v0}  Queued · {v1}').format(v0=time.strftime('%H:%M:%S'), v1=title))
        detail = TransferDialog(self, title, cancel)
        self.preview_windows.append(detail)
        detail.show()
        structured = False
        last_message = ""
        transferred, last_update, started = 0, 0, None

        def report(message, count):
            nonlocal transferred, last_update, started, structured, last_message
            if message.startswith(TRANSFER_PREFIX):
                structured = True
                event = json.loads(message[len(TRANSFER_PREFIX):])
                line = detail.update_event(event)
                if line:
                    self.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + line)
                self.progress.setRange(0, 1000)
                self.progress.setValue(detail.total_bar.value())
                self.queue_label.setText(detail.statistics.text())
                return
            if structured:
                detail.phase.setText(message)
                if message != last_message:
                    self.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + message)
                    detail.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + message)
                    last_message = message
                return
            detail.details.setText(message)
            if message != last_message:
                self.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + message)
                detail.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + message)
                last_message = message
            if started is None:
                started = time.monotonic()
            transferred += count
            if time.monotonic() - last_update > 0.15:
                speed = transferred / max(0.1, time.monotonic() - started)
                self.queue_label.setText(tr('{v0}  ·  {v1}  ·  {v2}/s  ·  {v3} jobs').format(v0=message, v1=size_text(transferred), v2=size_text(speed), v3=self.pending_jobs))
                last_update = time.monotonic()

        def finish(message, failed=False):
            detail.finish(message, failed)
            self.cancel_events.discard(cancel)
            self.pending_jobs -= 1
            if failed:
                self.failed_jobs += 1
                self.history_button.setChecked(True)
            self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {message} · {title}")
            if not self.pending_jobs:
                self.progress.setRange(0, 1)
                self.progress.setValue(0 if self.failed_jobs else 1)
                self.queue_label.setText(tr('TRANSFER QUEUE  ·  {v0} incomplete jobs').format(v0=self.failed_jobs)
                                         if self.failed_jobs else tr('TRANSFER QUEUE  ·  Complete'))
                self.cancel_button.setEnabled(bool(self.cancel_events))
            self.left.refresh()
            self.right.refresh()

        def success(result):
            if on_done:
                on_done(result)
            finish(tr('Done'))

        self.run_task(lambda emit: function(cancel, emit), success,
                      lambda error: finish(tr('Incomplete: {v0}').format(v0=error), True), transfer=True, report=report)

    def show_open_with(self, paths=None, assign=False):
        paths = paths if isinstance(paths, list) else self.active.local_file_paths()
        if not paths:
            return self.error(tr('Choose a local file. Copy files from archives or servers to disk first.'))
        dialog = OpenWithDialog(self, paths, assign=assign)
        self.preview_windows.append(dialog)
        dialog.finished.connect(lambda _: self.preview_windows.remove(dialog) if dialog in self.preview_windows else None)
        dialog.show()
        return dialog

    def drop_paths(self, panel, paths, destination):
        if panel.provider.readonly:
            return self.error(tr('The destination is read only.'))
        if not dialog_kit.confirm(self, tr('Copy'), tr('Copy {v0} items here?').format(v0=len(paths)),
                                  tr('Into: {v0}').format(v0=panel.location(path=destination)),
                                  items=[Path(p).name for p in paths], action=tr('Copy'), icon="copy"):
            return
        provider = panel.provider
        def work(cancel, report):
            local = LocalProvider()
            for filename in paths:
                path = Path(filename)
                entry = next(e for e in local.list(str(path.parent)) if e.name == path.name)
                copy_entries(local, str(path.parent), provider, destination, [entry], cancel, report)
        self.enqueue(tr('Copy') + ' → ' + destination, work)

    def copy_details(self):
        panel = self.active
        entries, provider, path = panel.action_entries(), panel.provider, panel.path
        if not entries:
            return
        locations = {e.name: panel.location(path=provider.join(path, e.name)) for e in entries}
        cancel = Event()
        self.cancel_events.add(cancel)
        self.cancel_button.setEnabled(True)
        def cleanup():
            self.cancel_events.discard(cancel)
            self.cancel_button.setEnabled(bool(self.cancel_events))
        def collect(report):
            values = {}
            with provider.batch():
                for entry in entries:
                    values[entry.name] = folder_size(provider, provider.join(path, entry.name), cancel, report)[0] if entry.is_dir and not entry.is_link else entry.size
            return values
        def done(values):
            cleanup()
            lines = ['\t'.join([tr('Name'), tr('Bytes'), tr('Modified'), tr('Type'), tr('Path')])]
            for entry in entries:
                lines.append('\t'.join([entry.name, str(values[entry.name]), datetime.fromtimestamp(entry.modified).isoformat(' ', timespec='seconds') if entry.modified else '', tr('Folder') if entry.is_dir else tr('File'), locations[entry.name]]))
            lines.append(tr('Total') + '\t' + str(sum(values.values())))
            QApplication.clipboard().setText('\n'.join(lines))
        def failed(message):
            cleanup()
            self.error(message)
        self.run_task(collect, done, failed, read_only=True)

    def extract_archives(self):
        panel = self.active
        if not isinstance(panel.provider, LocalProvider):
            return self.error(tr('Copy the archive to disk first.'))
        files = [panel.provider.join(panel.path, e.name) for e in panel.action_entries() if not e.is_dir and is_archive(e.name)]
        if not files:
            return
        dialog = dialog_kit.StandardDialog(self, tr('Extract archives…'), tr('Extract {v0} archives').format(v0=len(files)),
                                           icon="extract", action=tr('Extract'))
        layout = dialog.body
        dialog.add(dialog_kit.item_list(Path(f).name for f in files))
        form = QFormLayout()
        target = QLineEdit(self.other().path if isinstance(self.other().provider, LocalProvider) else str(Path.home() / 'Downloads'))
        row = QHBoxLayout()
        row.addWidget(target)
        browse = QPushButton(tr('Browse…'))
        def choose():
            path = QFileDialog.getExistingDirectory(dialog, tr('Extract to'), target.text())
            if path:
                target.setText(path)
        browse.clicked.connect(choose)
        row.addWidget(browse)
        form.addRow(tr('Extract to'), row)
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr('Password (optional)'), password)
        conflicts = QComboBox()
        conflicts.setProperty("translatedItems", True)
        for label, value in [('Stop on conflict', 'error'), ('Skip existing items', 'skip'), ('Rename the copy automatically', 'rename'), ('Replace files, merge folders', 'overwrite')]:
            conflicts.addItem(tr(label), value)
        form.addRow(tr('Existing files'), conflicts)
        layout.addLayout(form)
        separate = QCheckBox(tr('Create a separate folder for each archive'))
        separate.setChecked(True)
        layout.addWidget(separate)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination = os.path.abspath(os.path.expanduser(target.text()))
        secret, conflict, subfolder = password.text().encode("utf-8") or None, conflicts.currentData(), separate.isChecked()
        def extract(cancel, report):
            local = LocalProvider()
            for filename in files:
                check_cancel(cancel)
                archive = ArchiveProvider(filename, password=secret)
                dst = destination
                if subfolder:
                    name = Path(filename).name
                    for suffix in ('.tar.gz', '.tar.bz2', '.tar.xz', '.zip', '.7z', '.rar', '.tar', '.tgz'):
                        if name.lower().endswith(suffix):
                            name = name[:-len(suffix)]
                            break
                    dst = local.join(destination, name)
                os.makedirs(dst, exist_ok=True)
                copy_entries(archive, '/', local, dst, archive.list('/'), cancel, report, conflict=conflict)
        self.enqueue(tr('Extract archives…') + ' → ' + destination, extract)

    def copy_names(self):
        QApplication.clipboard().setText("\n".join(entry.name for entry in self.active.action_entries()))

    def reveal(self):
        panel = self.active
        if not isinstance(panel.provider, LocalProvider):
            return
        entry = panel.current_entry()
        path = panel.provider.join(panel.path, entry.name) if entry else panel.path
        from PySide6.QtCore import QProcess
        if sys.platform == "darwin":
            QProcess.startDetached("/usr/bin/open", ["-R", path])
        elif sys.platform == "win32":
            QProcess.startDetached("explorer.exe", ["/select,", path])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(panel.path))

    def show_properties(self):
        from .filemodel import display_cell
        panel = self.active
        entries = panel.action_entries()
        if not entries:
            return
        entry = entries[0]
        single = len(entries) == 1
        dialog = dialog_kit.StandardDialog(
            self, tr('Properties — ') + (entry.name if single else tr('{v0} items').format(v0=len(entries))),
            entry.name if single else tr('{v0} selected items').format(v0=len(entries)),
            (display_cell(entry, 3) + ' · ' if single else '') + panel.location(), icon="properties", close_only=True, width=640)
        from PySide6.QtWidgets import QTabWidget, QGroupBox
        dialog.resize(780, 600)
        dialog.heading.setProperty('userContent', True)
        dialog.heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = dialog.body
        summary_card = QGroupBox(tr('Selection size'))
        summary_card.setObjectName('toolCard')
        summary_layout = QVBoxLayout(summary_card)
        summary = QLabel()
        summary.setObjectName("propertiesTotal")
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_layout.addWidget(summary)
        layout.addWidget(summary_card)
        tabs = QTabWidget()
        dialog.add(tabs, 1)
        general, details = QWidget(), QWidget()
        general_form, detail_form = QFormLayout(general), QFormLayout(details)
        general_form.setSpacing(12); detail_form.setSpacing(12)
        tabs.addTab(general, tr('General'))
        rows = []
        def field(form, label, value):
            if value:
                edit = QLineEdit(str(value)); edit.setReadOnly(True)
                edit.setProperty('userContent', True)
                edit.setCursorPosition(0)
                edit.setToolTip(str(value))
                form.addRow(label + ':', edit)
                rows.append((label, str(value)))
        field(general_form, tr('Location'), panel.location())
        if len(entries) == 1:
            for label, value in [(tr('Name'), entry.name), (tr('Type'), display_cell(entry, 3)),
                                 (tr('Modified'), display_cell(entry, 2))]:
                field(general_form, label, value)
            if not entry.is_dir and isinstance(panel.provider, LocalProvider):
                # Program icon and name, with "Change…" to set the association without opening the file.
                program = QWidget()
                line = QHBoxLayout(program)
                line.setContentsMargins(0, 0, 0, 0)
                badge = QLabel()
                name_label = QLabel()
                name_label.setProperty('userContent', True)
                change_program = QPushButton(tr('Change…'))
                line.addWidget(badge); line.addWidget(name_label, 1); line.addWidget(change_program)
                def show_program():
                    from shiboken6 import isValid
                    if not isValid(name_label):
                        return
                    icon = self.associations.icon(entry.name)
                    badge.setPixmap(icon.pixmap(20, 20) if icon else QPixmap())
                    badge.setVisible(bool(icon))
                    name_label.setText(panel.model.program_label(entry))
                show_program()
                self.associations.changed.connect(show_program)
                def stop_watching(_):
                    try:
                        self.associations.changed.disconnect(show_program)
                    except (RuntimeError, TypeError):
                        pass
                dialog.finished.connect(stop_watching)
                file_paths = self.active.local_file_paths()
                change_program.clicked.connect(lambda: self.show_open_with(file_paths, assign=True))
                general_form.addRow(tr('Open with') + ':', program)
                rows.append((tr('Open with'), panel.model.program_label(entry)))
            elif not entry.is_dir:
                field(general_form, tr('Open with'), panel.model.program_label(entry))
            for label, value in [(tr('Full path'), panel.location(path=panel.provider.join(panel.path, entry.name))),
                                 (tr('Bytes'), display_cell(entry, 7)), (tr('Created'), display_cell(entry, 9)),
                                 (tr('Accessed'), display_cell(entry, 10)), (tr('Permissions'), display_cell(entry, 8)),
                                 (tr('Owner'), entry.owner), (tr('Group'), entry.group), (tr('Link target'), entry.link_target)]:
                field(detail_form, label, value)
            tabs.addTab(details, tr('Details'))
        else:
            details.deleteLater()
            listing = QPlainTextEdit("\n".join(e.name for e in entries))
            listing.setReadOnly(True)
            general_form.addRow(tr('Selected names'), listing)
            rows.append((tr('Selected names'), "\n".join(e.name for e in entries)))
        copy_details = QPushButton(tr('Copy properties'))
        copy_details.clicked.connect(lambda: QApplication.clipboard().setText(
            summary.text() + "\n" + "\n".join(label + ': ' + value for label, value in rows)))
        def show_total(values):
            total = sum(values.values()) + sum(e.size for e in entries if not e.is_dir)
            summary.setText(tr('Total size: {v0} ({v1} bytes) · {v2} selected').format(v0=size_text(total), v1=f"{total:,}", v2=len(entries)))
        directories = [e for e in entries if e.is_dir and not e.is_link]
        if directories:
            summary.setText(tr('Calculating total size…'))
            provider, path, tab = panel.provider, panel.path, panel._current
            key = panel.location_key(provider, path)
            cancel = Event()
            dialog.finished.connect(lambda _: cancel.set())
            from shiboken6 import isValid
            def completed(values):
                tab.sizes.setdefault(key, {}).update(values)
                if panel._current is tab and panel.location_key(panel.provider, panel.path) == key:
                    panel.model.directory_sizes = tab.sizes[key]
                    panel.update_footer()
                    panel.model.layoutChanged.emit()
                if isValid(summary):
                    show_total(values)
            def failed(message):
                if isValid(summary):
                    summary.setText(tr('Incomplete: {v0}').format(v0=message))
            cached = tab.sizes.get(key, {})
            if all(e.name in cached for e in directories):
                show_total({e.name: cached[e.name] for e in directories})
            else:
                self.run_task(lambda report: {e.name: folder_size(provider, provider.join(path, e.name), cancel, report)[0] for e in directories}, completed, failed, read_only=True)
        else:
            show_total({})
        if len(entries) == 1 and isinstance(self.active.provider, LocalProvider) and not entry.is_dir:
            paths = self.active.local_file_paths()
            change = QPushButton(tr('Open with another application / change association…'))
            change.clicked.connect(lambda: self.show_open_with(paths))
            dialog.buttons.addButton(change, QDialogButtonBox.ButtonRole.ActionRole)
        dialog.buttons.addButton(copy_details, QDialogButtonBox.ButtonRole.ActionRole)
        self.preview_windows.append(dialog)
        dialog.finished.connect(lambda _: self.preview_windows.remove(dialog) if dialog in self.preview_windows else None)
        dialog.show()
        return dialog

    def open_tool(self, cls):
        dialog = cls(self)
        self.preview_windows.append(dialog)
        dialog.finished.connect(lambda _: self.preview_windows.remove(dialog) if dialog in self.preview_windows else None)
        dialog.show()
        return dialog

    def show_multi_rename(self):
        if self.active.provider.readonly:
            return self.error(tr('The source does not support renaming.'))
        if self.active.action_entries():
            return self.open_tool(MultiRenameDialog)

    def undo_multi_rename(self):
        if not self.last_rename:
            return self.error(tr('There is no multi-rename operation to undo in this application session.'))
        provider, base, originals, names = self.last_rename
        from dataclasses import replace
        entries = [replace(e, name=n) for e, n in zip(originals, names)]
        def done(_):
            self.last_rename = None
        self.enqueue(tr('Undo multi-rename'), lambda cancel, report: multi_rename(provider, base, entries, [e.name for e in originals], cancel, report), on_done=done)

    def compare_files(self):
        entries = [e for e in self.active.action_entries() if not e.is_dir and not e.is_link]
        if len(entries) == 2:
            a, b = [(self.active.provider, self.active.provider.join(self.active.path, e.name)) for e in entries]
        else:
            other = self.other().current_entry()
            current = self.active.current_entry()
            if not current or current.is_dir or not other or other.is_dir:
                return self.error(tr('Select two files in one panel or one file in each panel.'))
            a = self.active.provider, self.active.provider.join(self.active.path, current.name)
            b = self.other().provider, self.other().provider.join(self.other().path, other.name)
        dialog = FileCompareDialog(self, a, b)
        self.preview_windows.append(dialog)
        dialog.finished.connect(lambda _: self.preview_windows.remove(dialog) if dialog in self.preview_windows else None)
        dialog.show()

    def toggle_auto_sizes(self):
        enabled = self.commands.actions["auto_sizes"].isChecked()
        self.settings.setValue("auto_sizes", enabled)
        if enabled:
            for panel in (self.left, self.right):
                self.calculate_sizes(panel.entries, panel)

    def calculate_sizes(self, entries=None, panel=None):
        panel = panel or self.active
        entries = entries if entries is not None else panel.action_entries()
        directories = [entry for entry in entries if entry.is_dir and not entry.is_link]
        if not directories:
            return
        provider, path, tab = panel.provider, panel.path, panel._current
        serial = tab.serial
        key = panel.location_key(provider, path)
        cancel = Event()
        self.cancel_events.add(cancel)
        self.cancel_button.setEnabled(True)
        def calculate(report):
            with provider.batch():
                return {entry.name: folder_size(provider, provider.join(path, entry.name), cancel, report)[0] for entry in directories}
        def cleanup():
            self.cancel_events.discard(cancel)
            self.cancel_button.setEnabled(bool(self.cancel_events))
        def done(values):
            cleanup()
            if tab.serial != serial or tab not in panel.tab_states:
                return
            tab.sizes.setdefault(key, {}).update(values)
            while len(tab.sizes) > 100:
                del tab.sizes[next(iter(tab.sizes))]
            if panel._current is tab and panel.location_key(panel.provider, panel.path) == key:
                panel.model.directory_sizes = tab.sizes[key]
                panel.update_footer()
                if panel.model.rowCount():
                    panel.model.dataChanged.emit(panel.model.index(0, 1), panel.model.index(panel.model.rowCount() - 1, 1))
                if panel.model.column == 1:
                    panel.model.sort(1, Qt.SortOrder.DescendingOrder if panel.model.descending else Qt.SortOrder.AscendingOrder)
            self.statusBar().showMessage(tr('Calculated sizes: {v0} folders').format(v0=len(values)))
        def failed(message):
            cleanup()
            self.error(message)
        self.run_task(calculate, done, failed, read_only=True)

    def clipboard_copy(self, cut=False):
        try:
            self.file_clipboard.put(self.active.provider, self.active.path, self.active.action_entries(), cut)
            self.statusBar().showMessage(tr('Cut to clipboard') if cut else tr('Files copied to clipboard'))
        except Exception as exc:
            self.error(str(exc))

    def clipboard_paste(self):
        try:
            groups = self.file_clipboard.get()
            if not groups:
                return self.error(tr('There are no files in the clipboard. Use Paste path for a text path.'))
            provider, path = self.active.provider, self.active.path
            if provider.readonly:
                return self.error(tr('The destination is read only.'))
            count = sum(len(entries) for _, _, entries, _ in groups)
            names = [entry.name for _, _, entries, _ in groups for entry in entries]
            if not dialog_kit.confirm(self, tr('Paste files'), tr('Paste {v0} items here?').format(v0=count),
                                      tr('Into: {v0}').format(v0=self.active.location()), items=names, action=tr('Paste'),
                                      icon="clipboard_paste", note=tr('An existing item with the same name stops the operation. Cut items are moved.')):
                return
            token = self.file_clipboard.token
            def paste(cancel, report):
                for sp, src, entries, cut in groups:
                    (move_entries if cut else copy_entries)(sp, src, provider, path, entries, cancel, report)
            self.enqueue(tr('Paste {v0} items → {v1}').format(v0=count, v1=path), paste, on_done=lambda _: self.file_clipboard.clear_cut(token) if any(g[3] for g in groups) else None)
        except Exception as exc:
            self.error(str(exc))

    def copy(self):
        self.transfer(False)

    def move(self):
        self.transfer(True)

    def transfer(self, moving):
        source, target = self.active, self.other()
        entries = source.action_entries()
        if not entries or not target.tree.isEnabled():
            return
        sp, src, dp, dst = source.provider, source.path, target.provider, target.path
        if moving and not getattr(sp, 'supports_delete', True):
            return self.error(tr('This device permits copying, but not moving or deleting files.'))
        if dp.readonly:
            return self.error(tr('The destination archive is read only. Choose a folder on disk or a server.'))
        if moving and sp.readonly:
            return self.error(tr('Cannot move from a read-only source.'))
        verb = tr('Move') if moving else tr('Copy')
        dialog = dialog_kit.StandardDialog(self, verb, (tr('Move items ({v0})') if moving else tr('Copy items ({v0})')).format(v0=len(entries)),
                                           tr('From: {v0}').format(v0=source.location(path=src)) + "\n" + tr('To: {v0}').format(v0=target.location(path=dst)),
                                           icon="move" if moving else "copy", action=verb, width=540)
        layout = dialog.body
        dialog.add(dialog_kit.item_list(e.name for e in entries))
        conflicts = QComboBox()
        conflicts.setProperty("translatedItems", True)
        conflicts.addItem(tr('Stop on conflict'), "error")
        if not moving:
            conflicts.addItem(tr('Skip existing items'), "skip")
            conflicts.addItem(tr('Rename the copy automatically'), "rename")
            if getattr(dp, 'supports_overwrite', True):
                conflicts.addItem(tr('Replace files, merge folders'), "overwrite")
        layout.addWidget(QLabel(tr('If an item already exists at the destination:')))
        layout.addWidget(conflicts)
        resume_box = QCheckBox(tr('Keep partial transfers and resume after interruption'))
        resume_box.setEnabled(not moving and ((isinstance(sp, RemoteProvider) and isinstance(dp, LocalProvider)) or (isinstance(sp, LocalProvider) and isinstance(dp, RemoteProvider))))
        layout.addWidget(resume_box)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        conflict = conflicts.currentData()
        resume_enabled = resume_box.isChecked()
        source_label, target_label = source.location(path=src), target.location(path=dst)
        def transfer(cancel, report):
            report(tr('Source: {v0} → Destination: {v1}').format(v0=source_label, v1=target_label), 0)
            if moving:
                return move_entries(sp, src, dp, dst, entries, cancel, report)
            return copy_entries(sp, src, dp, dst, entries, cancel, report, conflict=conflict, resume=resume_enabled)
        self.enqueue(tr('{v0} {v1} items → {v2}').format(v0=verb, v1=len(entries), v2=dst),
                     transfer)

    def mkdir(self):
        panel = self.active
        if panel.provider.readonly or not panel.tree.isEnabled():
            return
        # Like Total Commander: start from the name under the cursor, so "Season 1" becomes "Season 2" in a keystroke.
        # Both choices are remembered: prefill on/off, and whether file names count too.
        entry = panel.current_entry()
        settings = self.settings
        def suggestion(enabled, files):
            if not enabled or entry is None or entry.name == "..":
                return ""
            if entry.is_dir:
                return entry.name
            return (os.path.splitext(entry.name)[0] or entry.name) if files else ""
        prefill = str(settings.value('mkdir_prefill', True)).lower() not in ('false', '0')
        from_files = str(settings.value('mkdir_prefill_files', True)).lower() not in ('false', '0')

        def setup(dialog, edit):
            options = QWidget()
            row = QHBoxLayout(options)
            row.setContentsMargins(0, 0, 0, 0)
            toggle = QCheckBox(tr('Prefill the name under the cursor'))
            toggle.setChecked(prefill)
            source = QComboBox()
            source.addItem(tr('Folders and files'), True)
            source.addItem(tr('Folders only'), False)
            source.setCurrentIndex(0 if from_files else 1)
            source.setEnabled(prefill)
            row.addWidget(toggle)
            row.addWidget(source)
            row.addStretch(1)
            dialog.add(options)
            def changed(*_):
                enabled, files = toggle.isChecked(), bool(source.currentData())
                source.setEnabled(enabled)
                settings.setValue('mkdir_prefill', enabled)
                settings.setValue('mkdir_prefill_files', files)
                edit.setText(suggestion(enabled, files))
                edit.selectAll()
                edit.setFocus()
            toggle.toggled.connect(changed)
            source.currentIndexChanged.connect(changed)
            dialog.prefill, dialog.prefill_source = toggle, source

        name = dialog_kit.ask_text(self, tr('New folder'), tr('New folder'), tr('Folder name:'), suggestion(prefill, from_files),
                                   subtitle=tr('In: {v0}').format(v0=panel.location()), action=tr('Create'), icon="mkdir",
                                   allow_empty=False, setup=setup)
        if name:
            try:
                path = panel.provider.join(panel.path, name)
                provider = panel.provider
                self.run_task(lambda _: provider.mkdir(path), lambda _: panel.refresh())
            except ValueError as exc:
                self.error(str(exc))

    def rename(self):
        panel = self.active
        entry = panel.current_entry()
        if panel.provider.readonly or entry is None:
            return
        name = dialog_kit.ask_text(self, tr('Rename'), tr('Rename “{v0}”').format(v0=entry.name), tr('New name:'), entry.name,
                                   subtitle=tr('In: {v0}').format(v0=panel.location()), action=tr('Rename'), icon="rename",
                                   select_stem=not entry.is_dir)
        if name is None:
            return
        if name and name != entry.name:
            try:
                provider, path, tab = panel.provider, panel.path, panel._current
                original = provider.join(path, entry.name)
                destination = provider.join(path, name)
                if isinstance(provider, ArchiveProvider):
                    self.enqueue(tr('Rename {v0} → {v1}').format(v0=entry.name, v1=name),
                                 lambda cancel, report: multi_rename(provider, path, [entry], [name], cancel, report),
                                 on_done=lambda _: panel.navigate(provider, path, remember=False, tab=tab, focus_name=name))
                else:
                    self.run_task(lambda _: provider.rename(original, destination),
                                  lambda _: panel.navigate(provider, path, remember=False, tab=tab, focus_name=name))
            except ValueError as exc:
                self.error(str(exc))

    def delete(self, permanent=False):
        panel = self.active
        entries = panel.action_entries()
        if not entries or panel.provider.readonly:
            return
        if isinstance(panel.provider, LocalProvider) and not permanent:
            provider, base = panel.provider, panel.path
            if not dialog_kit.confirm(self, tr('Move to Trash'), tr('Move {v0} items to the Trash?').format(v0=len(entries)),
                                      tr('From: {v0}').format(v0=panel.location()), items=[e.name for e in entries],
                                      action=tr('Move to Trash'), icon="delete", note=tr('You can restore them from the system Trash.')):
                return
            def trash(cancel, report):
                for entry in entries:
                    if cancel.is_set():
                        raise Cancelled(tr('Move to Trash canceled between items.'))
                    path = provider.join(base, entry.name)
                    result = QFile.moveToTrash(path)
                    ok = result[0] if isinstance(result, tuple) else result
                    if not ok:
                        raise OSError(tr('Cannot move to Trash: {v0}. The file was not permanently deleted.').format(v0=path))
                    report(tr('Trash · {v0}').format(v0=entry.name), 0)
            return self.enqueue(tr('Move to Trash: {v0} items').format(v0=len(entries)), trash)
        if not dialog_kit.confirm(self, tr('Delete permanently'), tr('Delete {v0} items permanently?').format(v0=len(entries)),
                                  tr('From: {v0}').format(v0=panel.location()), items=[e.name for e in entries],
                                  action=tr('Delete permanently'), destructive=True, icon="delete",
                                  note=tr('Folders are deleted including their contents. This does not use the Trash and cannot be undone.')):
            return
        provider, base = panel.provider, panel.path

        def remove(cancel, report):
            with provider.batch():
                provider.operation_progress(lambda count: check_cancel(cancel))
                for entry in entries:
                    if cancel.is_set():
                        raise Cancelled(tr('Deletion canceled between items.'))
                    provider.remove(provider.join(base, entry.name), entry)
                    report(entry.name, 0)
        self.enqueue(tr('Delete {v0} items').format(v0=len(entries)), remove)

    def show_preview(self, panel=None):
        panel = panel or self.active
        entries = panel.action_entries()
        if len(entries) != 1 or entries[0].is_dir:
            return
        entry = entries[0]
        provider, path = panel.provider, panel.provider.join(panel.path, entry.name)

        from .viewer import FileViewer, VIEW_LIMIT
        from .document_preview import PREVIEW_LIMIT, WHOLE_FILE, enabled_group
        # Whole-file formats (PDF, Office, pictures) need the complete file up to the preview limit.
        limit = PREVIEW_LIMIT if enabled_group(entry.name, self.settings) in WHOLE_FILE else VIEW_LIMIT
        def display(data):
            dialog = FileViewer(self, entry.name, entry.size, data)
            self.preview_windows.append(dialog)
            dialog.destroyed.connect(lambda: self.preview_windows.remove(dialog) if dialog in self.preview_windows else None)
            dialog.show()
        self.run_task(lambda _: preview(provider, path, limit), display, read_only=True)

    def show_editor(self):
        panel = self.active
        entries = panel.action_entries()
        if len(entries) != 1 or entries[0].is_dir:
            return
        if panel.provider.readonly or entries[0].is_link:
            return self.error(tr('Only regular files on disk or a server can be edited. Extract archive files first.'))
        if entries[0].size > EDITOR_LIMIT:
            return self.error(tr('The integrated text editor supports files up to 16 MB.'))
        self.open_editor(panel.provider, panel.provider.join(panel.path, entries[0].name))

    def open_editor(self, provider, path):
        def display(data):
            try:
                if len(data) > EDITOR_LIMIT:
                    raise ValueError(tr('The file exceeds the editor limit of 16 MB.'))
                try:
                    dialog = TextEditor(self, provider, path, data)
                except UnicodeDecodeError:
                    from .text_widgets import ENCODINGS
                    label, ok = QInputDialog.getItem(self, tr('Open text with encoding'),
                                                    tr('The file is not Unicode text. Select its encoding.'),
                                                    [label for label, codec in ENCODINGS], 4, False)
                    if not ok:
                        return
                    codec = next(codec for name, codec in ENCODINGS if name == label)
                    dialog = TextEditor(self, provider, path, data, encoding=codec)
                self.preview_windows.append(dialog)
                dialog.destroyed.connect(lambda: self.preview_windows.remove(dialog))
                dialog.show()
            except (ValueError, UnicodeError) as exc:
                self.error(tr('Cannot open file as text: {v0}').format(v0=exc))
        self.run_task(lambda _: preview(provider, path, EDITOR_LIMIT + 1), display, read_only=True)

    def cancel_transfers(self):
        for cancel in self.cancel_events:
            cancel.set()
        self.queue_label.setText(tr('Canceling… waiting for the current network request to finish.'))

    def closeEvent(self, event):
        if self.external_processes:
            QMessageBox.information(self, tr('External command is running'), tr('Wait for running external commands to finish.'))
            event.ignore()
            return
        if any(not getattr(task, 'quiet', False) for task in self.tasks):
            if self.pending_jobs:
                self.cancel_transfers()
            QMessageBox.information(self, tr('Operations in progress'), tr('Wait for background operations to finish before closing this window.'))
            event.ignore()
            return
        for dialog in tuple(self.preview_windows):
            if isinstance(dialog, TextEditor) and not dialog.close():
                event.ignore()
                return
        for panel in (self.left, self.right):  # No further automatic refreshes once closing.
            panel.watcher.watch(None)
            panel.poll_timer.stop()
        if getattr(self, "devices_dialog", None) is not None:
            self.devices_dialog.shutdown()
        self.associations.timer.stop()
        self.associations.requested.clear()
        for dialog in tuple(self.preview_windows):
            if not isinstance(dialog, TextEditor):
                dialog.close()
        for name, panel in (("left", self.left), ("right", self.right)):
            panel.save_columns()
            self.settings.setValue(f"{name}_tabs", json.dumps(panel.saved_tabs(), ensure_ascii=False))
            if isinstance(panel.provider, LocalProvider):
                self.settings.setValue(name, panel.path)
        self.settings.sync()
        event.accept()


def main():
    if "--version" in sys.argv:
        print(__version__)
        return
    if '--smoke-test' not in sys.argv and '--update-monitor' not in sys.argv:
        from .diagnostic_log import configure, install_exception_hooks
        try:
            configure()
            install_exception_hooks()
        except OSError:
            pass
    plugin_copy = prepare_plugins()
    app = QApplication(sys.argv)
    app.setOrganizationName("StereoCommander")
    app.setApplicationName("StereoCommander")  # Preserve settings and data paths across the rename.
    app.setApplicationDisplayName("Soovee Commander")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "soovee-commander-icon.png")))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    if '--update-monitor' in sys.argv:
        from .update_ui import monitor_installation
        preferences = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, 'StereoCommander', 'StereoCommander')
        set_language(preferences.value('language', 'en'))
        install_qt_translations(app)
        apply_theme(app, preferences.value('theme', 'soovee'))
        index = sys.argv.index('--update-monitor')
        sys.exit(monitor_installation(app, sys.argv[index + 1], int(sys.argv[index + 2])))
    smoke = "--smoke-test" in sys.argv
    if sys.platform == "win32" and not smoke:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
        app._installer_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "StereoCommander")
    temporary = None
    if smoke:
        set_language("cs")
        assert tr("Rename") != "Rename", "Bundled Czech catalog is missing"
        set_language("en")
        import tempfile
        temporary = tempfile.TemporaryDirectory(prefix="stereo-smoke-")
        root = Path(temporary.name)
        from .archive_runtime import prepare_archive
        prepare_archive()
        import libarchive
        with libarchive.file_writer(str(root / "smoke.7z"), "7zip") as archive:
            # Avoid the upstream disk reader's Windows path separator mismatch.
            archive.add_file_from_memory('inside.txt', 13, b'archive smoke')
        assert preview(ArchiveProvider(str(root / "smoke.7z")), "/inside.txt") == b"archive smoke"
        (root / "left").mkdir()
        (root / "right").mkdir()
        (root / "left" / "test.txt").write_text("Soovee Commander")
        from .packing import create_archive
        local = LocalProvider()
        for archive_format in ('7z', 'tar.xz'):
            packed = root / ('created.' + archive_format)
            create_archive(local, str(root / 'left'), str(packed), local.list(str(root / 'left')), Event(), format=archive_format)
            assert preview(ArchiveProvider(str(packed)), '/test.txt') == b'Soovee Commander'
        # The packaged app must carry Qt PDF; built-in PDF previews depend on it.
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QPainter, QPdfWriter
        from . import document_preview
        assert document_preview.pdf_available(), "Bundled Qt PDF module is missing"
        pdf = QBuffer(); pdf.open(QIODevice.OpenModeFlag.WriteOnly)
        writer = QPdfWriter(pdf); painter = QPainter(writer); painter.drawText(100, 100, 'PDF smoke'); writer.newPage(); painter.end()
        pdf_preview = document_preview.build('smoke.pdf', bytes(pdf.data()))  # Keep the owner alive.
        assert pdf_preview.document.pageCount() == 2
        pdf_preview.deleteLater()
        from .about import ROOT as resource_root
        components = json.loads((resource_root / "licenses/components.json").read_text(encoding='utf-8'))
        assert components and (resource_root / "licenses/application.json").is_file()
        assert all((resource_root / "licenses" / name).is_file() for component in components for name in component['files'])
        from .lan import TransferService
        from .lan_ui import qr_image, read_qr
        from .lan_protocol import parse_invitation
        incoming = root / 'incoming'
        incoming.mkdir()
        receiver = TransferService(root / 'receiver', 'Smoke receiver', approve_pair=lambda peer: True,
                                   approve_offer=lambda *args: incoming)
        sender = TransferService(root / 'sender', 'Smoke sender')
        try:
            receiver.start()
            sender.start()
            from .discovery import Discovery
            discovery = Discovery(sender, ['127.0.0.1'], lambda devices: None)
            discovery.close()  # Verify the bundled zeroconf extensions and publication lifecycle.
            receiver.begin_pairing()
            link = receiver.pairing_link('127.0.0.1')
            qr_path = root / 'pairing.png'
            assert qr_image(link).save(str(qr_path))
            assert read_qr(qr_path) == link
            peer = sender.pair(*parse_invitation(link), approve=lambda peer: True)
            received = Path(sender.send(peer.id, [root / 'left/test.txt']))
            assert (received / 'test.txt').read_text(encoding='utf-8') == 'Soovee Commander'
            from .device_files import DeviceProvider
            receiver.shares.add(incoming, 'Shared', sender.store.id, writable=True)
            drive = DeviceProvider(sender, peer.id)
            assert [entry.name for entry in drive.list('/')] == ['Shared']
            import io
            drive.write_from('/Shared/from-drive.txt', io.BytesIO(b'drive smoke'), lambda count: None)
            downloaded = io.BytesIO()
            drive.read_to('/Shared/from-drive.txt', downloaded, lambda count: None)
            assert downloaded.getvalue() == b'drive smoke'
        finally:
            sender.stop()
            receiver.stop()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root / "settings"))
        window = Commander(str(root / "left"), str(root / "right"))
        timer = QTimer()

        def verify():
            if not window.tasks:
                success = len(window.left.entries) == 1 and not window.right.entries
                window.change_language('cs')
                success = success and window.bottom_buttons[0].text().endswith(tr('Rename'))
                window.change_language('en')
                success = success and window.bottom_buttons[0].text().endswith('Rename')
                editor = TextEditor(window, LocalProvider(), str(root / 'left/test.txt'), b'Soovee Commander')
                editor.search.query.setText('Commander')
                editor.search.replacement.setText('editor')
                editor.search.replace_all()
                success = success and editor.text.toPlainText() == 'Soovee editor'
                editor.text.document().setModified(False)
                editor.close()
                from .viewer import FileViewer
                viewer = FileViewer(window, 'test.txt', 16, b'Soovee Commander')
                success = success and viewer.text.isReadOnly() and viewer.tabs.count() == 2
                viewer.close()
                window.close()
                app.exit(0 if success else 1)
        timer.timeout.connect(verify)
        timer.start(50)
        QTimer.singleShot(15000, lambda: app.exit(2))
    else:
        window = Commander()
        QTimer.singleShot(300, lambda: show_update_result(window))
    window.show()
    result = app.exec()
    if temporary:
        temporary.cleanup()
    if plugin_copy:
        plugin_copy.cleanup()
    sys.exit(result)


if __name__ == "__main__":
    main()
