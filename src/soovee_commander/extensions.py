"""Declarative command plugins. Processes receive arguments directly, without a shell."""
from .i18n import tr
import json
import os
from pathlib import Path
import plistlib
import subprocess

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                              QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                              QPushButton, QVBoxLayout)
from .providers import LocalProvider

SLOTS = 16


def validate_tools(value):
    if not isinstance(value, list) or len(value) > SLOTS:
        raise ValueError(tr('At most 16 external commands can be configured.'))
    clean = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(tr('Invalid plugin command.'))
        title, executable, args = item.get("title", ""), item.get("executable", ""), item.get("args", [])
        if not isinstance(title, str) or len(title) > 80 or not isinstance(executable, str) or len(executable) > 4096:
            raise ValueError(tr('Invalid name or application.'))
        if executable and not os.path.isabs(executable):
            raise ValueError(tr('The application path must be absolute.'))
        if not isinstance(args, list) or len(args) > 128 or any(not isinstance(a, str) or "\0" in a or len(a) > 8192 for a in args):
            raise ValueError(tr('Invalid command arguments.'))
        clean.append({"title": title, "executable": executable, "args": args})
    return clean + [{"title": "", "executable": "", "args": []} for _ in range(SLOTS - len(clean))]


def read_tools(host):
    try:
        return validate_tools(json.loads(host.settings.value("external_tools", "[]")))
    except (TypeError, ValueError):
        return validate_tools([])


def expand_args(args, path, other, files):
    result = []
    for arg in args:
        if arg == "{files}":
            result.extend(files)
        else:
            if "{files}" in arg:
                raise ValueError(tr('{files} must be a separate argument.'))
            # One pass: a filename containing {path} must remain literal.
            import re
            values = {"path": path, "other": other, "file": files[0] if files else ""}
            result.append(re.sub(r"\{(path|other|file)\}", lambda m: values[m[1]], arg))
    return result


def launch(host, slot):
    spec = read_tools(host)[slot]
    if not spec["executable"]:
        return host.error(tr('This command is not configured. Open Settings → External commands and plugins.'))
    panel = host.active
    if not isinstance(panel.provider, LocalProvider) or not isinstance(host.other().provider, LocalProvider):
        return host.error(tr('External commands use local paths. Copy remote files to disk first.'))
    try:
        executable = spec["executable"]
        if executable.endswith(".app"):
            bundle = Path(executable)
            with (bundle / "Contents" / "Info.plist").open("rb") as stream:
                name = plistlib.load(stream)["CFBundleExecutable"]
            if Path(name).name != name:
                raise ValueError(tr('Invalid executable in application bundle.'))
            executable = str(bundle / "Contents" / "MacOS" / name)
        files = [panel.provider.join(panel.path, e.name) for e in panel.action_entries()]
        args = expand_args(spec["args"], panel.path, host.other().path, files)
        process = QProcess(host)
        process.setProgram(executable)
        process.setArguments(args)
        process.setWorkingDirectory(panel.path)
        # QProcess output is drained into a bounded UI log; never execute a shell.
        def output():
            data = bytes(process.readAllStandardOutput()) + bytes(process.readAllStandardError())
            if data:
                host.log.appendPlainText(data[:65536].decode("utf-8", errors="replace"))
        process.readyReadStandardOutput.connect(output)
        process.readyReadStandardError.connect(output)
        def error(kind):
            host.error(process.errorString())
            if kind == QProcess.ProcessError.FailedToStart:
                host.external_processes.discard(process)
                process.deleteLater()
        process.errorOccurred.connect(error)
        def finished(code, status):
            output()
            host.log.appendPlainText(tr('{v0}: exit {v1}').format(v0=spec['title'] or executable, v1=code))
            panel.refresh()
            host.external_processes.discard(process)
            process.deleteLater()
        process.finished.connect(finished)
        host.external_processes.add(process)
        process.start()
    except Exception as exc:
        host.error(str(exc))


class ExtensionsDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.tools = read_tools(host)
        self.current = 0
        self.setWindowTitle(tr('External commands and plugins'))
        self.resize(720, 580)
        layout = QVBoxLayout(self)
        note = QLabel(tr('Command plugins run a program you choose on local files. Import only trusted definitions. Windows WCX/WFX/WLX plugins cannot be loaded here.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.slot = QComboBox()
        self.slot.setProperty("translatedItems", True)
        self.slot.addItems([tr('External command {v0}').format(v0=i + 1) for i in range(SLOTS)])
        layout.addWidget(self.slot)
        form = QFormLayout()
        self.title, self.executable = QLineEdit(), QLineEdit()
        form.addRow(tr('Name:'), self.title)
        program = QHBoxLayout()
        program.addWidget(self.executable, 1)
        browse = QPushButton(tr('Browse…'))
        browse.clicked.connect(self.browse)
        program.addWidget(browse)
        form.addRow(tr('Application:'), program)
        self.args = QPlainTextEdit()
        self.args.setPlaceholderText(tr('One argument per line. For example:\n{files}'))
        form.addRow(tr('Arguments:'), self.args)
        layout.addLayout(form)
        helptext = QLabel(tr('{file} = file under cursor / first selected; {files} = all selected files (separate line); {path} = active folder; {other} = other panel folder. No quotes are needed. Each command can be added to a bar and assigned a shortcut in Controls.'))
        helptext.setWordWrap(True)
        layout.addWidget(helptext)
        row = QHBoxLayout()
        for label, callback in ((tr('Import plugin JSON…'), self.import_plugin), (tr('Export…'), self.export_plugin)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.slot.currentIndexChanged.connect(self.change_slot)
        self.load_slot()

    def capture(self):
        self.tools[self.current] = {"title": self.title.text(), "executable": self.executable.text(), "args": self.args.toPlainText().splitlines()}

    def load_slot(self):
        spec = self.tools[self.current]
        self.title.setText(spec["title"])
        self.executable.setText(spec["executable"])
        self.args.setPlainText("\n".join(spec["args"]))

    def change_slot(self, index):
        self.capture()
        self.current = index
        self.load_slot()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Application'))
        if path:
            self.executable.setText(path)

    def import_plugin(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Import command plugin'), filter="Plugin (*.json)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > 256 * 1024:
                raise ValueError(tr('The plugin is too large.'))
            manifest = json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(manifest, dict) or manifest.get("schema") != "stereo.commands.v1":
                raise ValueError(tr('Unsupported plugin format.'))
            tools = validate_tools(manifest.get("commands"))
            # Import only fills the dialog; Save explicitly enables commands.
            self.tools = tools
            self.load_slot()
        except Exception as exc:
            QMessageBox.warning(self, tr('Import failed'), str(exc))

    def export_plugin(self):
        self.capture()
        path, _ = QFileDialog.getSaveFileName(self, tr('Export commands'), "commands.json", "JSON (*.json)")
        if path:
            try:
                tools = validate_tools(self.tools)
                Path(path).write_text(json.dumps({"schema": "stereo.commands.v1", "commands": tools}, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as exc:
                QMessageBox.warning(self, tr('Export failed'), str(exc))

    def save(self):
        self.capture()
        try:
            tools = validate_tools(self.tools)
            self.host.settings.setValue("external_tools", json.dumps(tools, ensure_ascii=False))
            self.host.settings.sync()
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, tr('Commands'), str(exc))
