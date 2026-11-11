"""Application choices local to Soovee Commander; system defaults stay OS-managed."""
from .i18n import tr
from collections import OrderedDict
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QFileInfo, QObject, QProcess, QSize, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFileIconProvider, QGridLayout,
                              QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                              QVBoxLayout, QWidget)

from .filetypes import EXTENSIONS, GROUPS, extension

_icons = {}


def app_icon(path):
    """The application's own icon (Finder / Explorer), cached; GUI thread only."""
    if not path:
        return QIcon()
    if path not in _icons:
        _icons[path] = QFileIconProvider().icon(QFileInfo(path)) if Path(path).exists() else QIcon()
    return _icons[path]


def related_extensions(ext):
    """Other extensions of the same kind (all video, all images…), for one-step associations."""
    group = EXTENSIONS.get(ext.lstrip("."))
    if not group or group in ("application", "archive", "file"):
        return []
    return ["." + value for value in GROUPS[group][3].split()]
from .native_apps import Application, application, applications_for_file, default_application


class Associations(QObject):
    changed = Signal()

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.custom = {}
        try:
            stored = json.loads(host.settings.value("file_associations", "{}"))
            if isinstance(stored, dict):
                self.custom = {ext: path for ext, path in stored.items() if isinstance(ext, str) and len(ext) <= 100 and isinstance(path, str) and os.path.isabs(path)}
        except (TypeError, ValueError):
            pass
        self.cache = OrderedDict()
        self.requested, self.inflight = set(), set()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.flush)

    def cached(self, name):
        ext = extension(name)
        if ext in self.custom:
            return Application(self.custom[ext], Path(self.custom[ext]).stem)
        if ext in self.cache:
            self.cache.move_to_end(ext)
            return self.cache[ext]
        if ext and ext not in self.inflight and len(self.cache) + len(self.requested) + len(self.inflight) < 4096:
            self.requested.add(ext)
            if not self.timer.isActive():
                self.timer.start()
        return None

    def icon(self, name):
        app = self.cached(name)
        return app_icon(app.path) if app and app.path else None

    def label(self, name):
        app = self.cached(name)
        ext = extension(name)
        if app:
            return app.name
        return tr('Checking…') if ext in self.requested or ext in self.inflight else tr('System default') if not ext else tr('Not assigned') if ext in self.cache else tr('Not checked')

    def flush(self):
        if not self.requested:
            return
        pending = set(self.requested)
        self.requested.clear()
        self.inflight.update(pending)
        def lookup(_):
            result = {}
            for ext in pending:
                try:
                    result[ext] = default_application(ext)
                except (OSError, AttributeError, ValueError):
                    result[ext] = None
            return result
        def loaded(values):
            self.inflight.difference_update(pending)
            self.cache.update(values)
            while len(self.cache) > 4096:
                self.cache.popitem(last=False)
            self.changed.emit()
        def failed(message):
            loaded({ext: None for ext in pending})
        self.host.run_task(lookup, loaded, failed, read_only=True)

    def set_default(self, ext, path, more=()):
        if path is not None and (not os.path.isabs(path) or not Path(path).exists()):
            raise ValueError(tr('Choose an existing application or executable.'))
        for value in (ext, *more):
            if path is None:
                self.custom.pop(value, None)
            else:
                self.custom[value] = str(Path(path))
        self.host.settings.setValue("file_associations", json.dumps(self.custom, ensure_ascii=False))
        self.host.settings.sync()
        self.changed.emit()

    def invalidate(self):
        self.cache.clear()
        self.changed.emit()

    def open(self, paths, app=None, system=False):
        if not paths:
            return
        try:
            for path in paths:
                if not Path(path).exists():
                    raise FileNotFoundError(path)
            # Mixed selections can have different custom defaults.
            if app is None and not system:
                groups = {}
                for path in paths:
                    groups.setdefault(self.custom.get(extension(Path(path).name)), []).append(path)
                for program, selected in groups.items():
                    self.open(selected, application_cached(program) if program else None, system=program is None)
                return
            if app is None:
                for path in paths:
                    if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                        raise OSError(tr('Cannot open file with the system application: {v0}').format(v0=path))
                return
            if not Path(app.path).exists():
                raise FileNotFoundError(tr('The application no longer exists: {v0}. Change the association or restore the system default.').format(v0=app.path))
            program, args = ("/usr/bin/open", ["-a", app.path, *paths]) if sys.platform == "darwin" and app.path.lower().endswith(".app") else (app.path, list(paths))
            # QProcess reports startup failure; no shell or filename interpolation.
            result = QProcess.startDetached(program, args)
            if not (result[0] if isinstance(result, tuple) else result):
                raise OSError(tr('Could not start the application: {v0}').format(v0=app.name))
        except (OSError, ValueError) as exc:
            self.host.error(str(exc))


from functools import lru_cache
application_cached = lru_cache(maxsize=256)(application)


class OpenWithDialog(QDialog):
    """Pick an application: open now, or only save it as the default for this type and related types."""

    def __init__(self, host, paths, panel=None, assign=False):
        super().__init__(host)
        self.host, self.paths = host, list(paths)
        self.assign = assign
        self.ext = extension(Path(paths[0]).name)
        self.setWindowTitle(tr('File association') if assign else tr('Open with'))
        self.resize(700, 560)
        layout = QVBoxLayout(self)
        label = QLabel(tr('{v0} items · {v1}').format(v0=len(paths), v1=Path(paths[0]).name))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.apps = QListWidget()
        self.apps.setIconSize(QSize(28, 28))
        self.apps.itemDoubleClicked.connect(lambda _: self.accept_choice())
        layout.addWidget(self.apps, 1)
        self.status = QLabel(tr('Finding available applications…'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        same = all(extension(Path(p).name) == self.ext for p in paths)
        self.remember = QCheckBox(tr('Always use this application in Soovee Commander for {v0}').format(v0=self.ext or tr('files without an extension')))
        self.remember.setEnabled(same)
        layout.addWidget(self.remember)
        # Related types: e.g. all video formats at once; each can be unticked.
        self.related = {}
        others = [value for value in related_extensions(self.ext) if value != self.ext] if same else []
        self.related_box = QWidget()
        grid = QGridLayout(self.related_box)
        grid.setContentsMargins(22, 0, 0, 0)
        if others:
            group = GROUPS[EXTENSIONS[self.ext.lstrip(".")]][0]
            grid.addWidget(QLabel(tr('Also for other {v0} files:').format(v0=tr(group).lower())), 0, 0, 1, 6)
            for index, value in enumerate(others):
                box = QCheckBox(value)
                box.setChecked(True)
                self.related[value] = box
                grid.addWidget(box, 1 + index // 6, index % 6)
        self.related_box.setVisible(False)
        self.remember.toggled.connect(lambda on: self.related_box.setVisible(on and bool(self.related)))
        layout.addWidget(self.related_box)
        row = QHBoxLayout()
        choose = QPushButton(tr('Choose another application…'))
        choose.clicked.connect(self.choose)
        reset = QPushButton(tr('Restore system association'))
        reset.clicked.connect(self.reset)
        row.addWidget(choose); row.addWidget(reset); row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Open).setText(tr('Open'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Cancel'))
        # "Use" saves the association (this type and the ticked related ones) and does not open anything.
        self.apply_button = buttons.addButton(tr('Use') if assign else tr('Use without opening'), QDialogButtonBox.ButtonRole.ApplyRole)
        self.apply_button.setToolTip(tr('Save the association and close; the file is not opened.'))
        self.apply_button.setEnabled(same)
        self.apply_button.clicked.connect(lambda: self.accept_choice(open_now=False))
        if assign and same:
            self.remember.setChecked(True)
            opener = buttons.button(QDialogButtonBox.StandardButton.Open)
            opener.setAutoDefault(False)
            self.apply_button.setAutoDefault(True)
            QTimer.singleShot(0, lambda: self.apply_button.setDefault(True))   # after the button box picks its default
        buttons.accepted.connect(self.accept_choice)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        custom = host.associations.custom.get(self.ext)
        if custom:
            self.add(application_cached(custom), tr(' · custom default'))
        self.add(None, tr('System default application'))
        self.apps.setCurrentRow(0)
        host.run_task(lambda _: applications_for_file(paths[0]), self.loaded, lambda message: self.status.setText(message), read_only=True)

    def add(self, app, suffix=""):
        if app and any(self.apps.item(i).data(Qt.ItemDataRole.UserRole) == app.path for i in range(self.apps.count())):
            return
        item = QListWidgetItem((app.name if app else "") + suffix)
        item.setData(Qt.ItemDataRole.UserRole, app.path if app else "")
        item.setToolTip(app.path if app else tr('Use the current operating system default'))
        if app:
            item.setIcon(app_icon(app.path))
        else:   # the system default: show that application's icon when it is known
            default = self.host.associations.cache.get(self.ext)
            if default is not None and default.path:
                item.setIcon(app_icon(default.path))
                item.setText(tr('System default application') + ' · ' + default.name)
        self.apps.addItem(item)

    def loaded(self, apps):
        for app in apps:
            self.add(app)
        self.status.setText(tr('Open uses the application once. Tick “Always use” to save it in Soovee Commander; other applications and system defaults are unchanged.'))

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Choose application'), "/Applications" if sys.platform == "darwin" else "", tr('Applications (*.exe *.com);;All files (*)') if os.name == "nt" else tr('All applications (*)'))
        if path:
            app = application_cached(path)
            self.add(app)
            for index in range(self.apps.count()):
                if self.apps.item(index).data(Qt.ItemDataRole.UserRole) == path:
                    self.apps.setCurrentRow(index)

    def reset(self):
        self.host.associations.set_default(self.ext, None, [value for value, box in self.related.items() if box.isChecked()] if self.remember.isChecked() else ())
        self.status.setText(tr('Custom association removed. The operating system default will be used.'))
        self.remember.setChecked(False)
        for row in range(self.apps.count()):
            if self.apps.item(row).data(Qt.ItemDataRole.UserRole) == "":
                self.apps.setCurrentRow(row)
                break

    def accept_choice(self, open_now=True):
        item = self.apps.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if self.remember.isChecked() or not open_now:
            try:
                self.host.associations.set_default(self.ext, path or None, [value for value, box in self.related.items() if box.isChecked()] if self.remember.isChecked() else ())
            except ValueError as exc:
                return QMessageBox.warning(self, tr('File associations'), str(exc))
        if open_now:
            self.host.associations.open(self.paths, application_cached(path) if path else None, system=not path)
        self.accept()


class AssociationsDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle(tr('Custom file associations'))
        self.resize(650, 430)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('Associations in Soovee Commander. Other applications and system defaults are unchanged.')))
        self.items = QListWidget()
        self.items.setIconSize(QSize(24, 24))
        layout.addWidget(self.items, 1)
        row = QHBoxLayout()
        for title, callback in ((tr('Change application…'), self.change), (tr('Restore system default'), self.remove), (tr('Refresh system applications'), host.associations.invalidate)):
            button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.reload()

    def reload(self):
        self.items.clear()
        for ext, path in sorted(self.host.associations.custom.items()):
            item = QListWidgetItem(f"{ext or tr('(no extension)')}  →  {application_cached(path).name}")
            item.setData(Qt.ItemDataRole.UserRole, ext)
            item.setToolTip(path)
            item.setIcon(app_icon(path))
            self.items.addItem(item)

    def remove(self):
        item = self.items.currentItem()
        if item:
            self.host.associations.set_default(item.data(Qt.ItemDataRole.UserRole), None)
            self.reload()

    def change(self):
        item = self.items.currentItem()
        if item:
            path, _ = QFileDialog.getOpenFileName(self, tr('Choose application'), "/Applications" if sys.platform == "darwin" else "")
            if path:
                self.host.associations.set_default(item.data(Qt.ItemDataRole.UserRole), path)
                self.reload()
