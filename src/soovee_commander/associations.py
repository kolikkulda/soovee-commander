"""Application choices local to Soovee Commander; system defaults stay OS-managed."""
from .i18n import tr
from collections import OrderedDict
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                              QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                              QVBoxLayout)

from .filetypes import extension
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

    def set_default(self, ext, path):
        if path is None:
            self.custom.pop(ext, None)
        else:
            if not os.path.isabs(path) or not Path(path).exists():
                raise ValueError(tr('Choose an existing application or executable.'))
            self.custom[ext] = str(Path(path))
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
    def __init__(self, host, paths, panel=None):
        super().__init__(host)
        self.host, self.paths = host, list(paths)
        self.ext = extension(Path(paths[0]).name)
        self.setWindowTitle(tr('Open with'))
        self.resize(680, 480)
        layout = QVBoxLayout(self)
        label = QLabel(tr('{v0} items · {v1}').format(v0=len(paths), v1=Path(paths[0]).name))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.apps = QListWidget()
        self.apps.itemDoubleClicked.connect(lambda _: self.accept_choice())
        layout.addWidget(self.apps, 1)
        self.status = QLabel(tr('Finding available applications…'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.remember = QCheckBox(tr('Use in Soovee Commander for {v0}').format(v0=self.ext or tr('files without an extension')))
        self.remember.setEnabled(all(extension(Path(p).name) == self.ext for p in paths))
        layout.addWidget(self.remember)
        row = QHBoxLayout()
        choose = QPushButton(tr('Choose another application…'))
        choose.clicked.connect(self.choose)
        reset = QPushButton(tr('Restore system association'))
        reset.clicked.connect(self.reset)
        row.addWidget(choose); row.addWidget(reset)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
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
        self.apps.addItem(item)

    def loaded(self, apps):
        for app in apps:
            self.add(app)
        self.status.setText(tr('The application choice applies to this opening. Check the box to save an extension association only in Soovee Commander.'))

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Choose application'), "/Applications" if sys.platform == "darwin" else "", tr('Applications (*.exe *.com);;All files (*)') if os.name == "nt" else tr('All applications (*)'))
        if path:
            app = application_cached(path)
            self.add(app)
            for index in range(self.apps.count()):
                if self.apps.item(index).data(Qt.ItemDataRole.UserRole) == path:
                    self.apps.setCurrentRow(index)

    def reset(self):
        self.host.associations.set_default(self.ext, None)
        self.status.setText(tr('Custom association removed. The operating system default will be used.'))
        self.remember.setChecked(False)
        for row in range(self.apps.count()):
            if self.apps.item(row).data(Qt.ItemDataRole.UserRole) == "":
                self.apps.setCurrentRow(row)
                break

    def accept_choice(self):
        item = self.apps.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if self.remember.isChecked():
            try:
                self.host.associations.set_default(self.ext, path or None)
            except ValueError as exc:
                return QMessageBox.warning(self, tr('File associations'), str(exc))
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
