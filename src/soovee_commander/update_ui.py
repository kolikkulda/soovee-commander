"""User-driven offline update flow: choose, prepare, review, restart."""
from .i18n import tr
import json
from pathlib import Path
import time

from PySide6.QtCore import QStandardPaths, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QFileDialog, QMessageBox, QDialog, QLabel, QPushButton,
                              QPlainTextEdit, QProgressBar, QVBoxLayout)
from .diagnostic_log import logger
from .filemodel import size_text

from . import __version__
from .updates import UpdateError, find_release, installed_app, launch_update, prepare_update


def result_path():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / "StereoCommander" / "update-result.json"


class UpdateProgress(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Application update'))
        self.resize(620, 340)
        self.started = time.monotonic()
        self.phase_name = ''
        self.last_activity = self.started
        self.last_detail = ''
        layout = QVBoxLayout(self)
        self.phase = QLabel(tr('Finding and checking the update package'))
        self.phase.setWordWrap(True); self.phase.setObjectName('dialogHeading'); layout.addWidget(self.phase)
        self.details = QLabel(); layout.addWidget(self.details)
        self.source = QLabel(); self.source.setWordWrap(True); self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source)
        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setRange(0, 0); layout.addWidget(self.bar)
        self.elapsed = QLabel(); layout.addWidget(self.elapsed)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log)
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(250)
        self.tick()

    def tick(self):
        now = time.monotonic()
        text = tr('Elapsed: {v0}s').format(v0=int(now - self.started))
        if now - self.last_activity >= 10:
            text += '\n' + tr('Waiting for the current step. Cloud or network files may need to download first; a local update file is faster.')
        self.elapsed.setText(text)

    def update_progress(self, message, count=0):
        if not message.startswith('@update:'):
            self.phase.setText(message)
            return
        event = json.loads(message[len('@update:'):])
        self.last_activity = time.monotonic()
        phase = event['phase']
        if phase != self.phase_name:
            self.phase_name = phase
            self.phase.setText(tr(phase))
            self.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + tr(phase))
            logger.info('Update progress · %s', phase)
        detail = event.get('detail', '')
        if detail:
            self.source.setText(detail)
            if detail != self.last_detail:
                self.log.appendPlainText(time.strftime('%H:%M:%S') + '  ' + detail)
                logger.info('Update detail · %s', detail)
                self.last_detail = detail
        total, current = event.get('total', 0), event.get('current', 0)
        if total:
            self.bar.setRange(0, 1000); self.bar.setValue(int(current * 1000 / total))
            self.details.setText(f'{size_text(current)} / {size_text(total)} · {int(current * 100 / total)}%')
        else:
            self.bar.setRange(0, 0)
            self.details.setText(tr('This step has no measurable percentage. The operation is still running.'))

    def reject(self):
        if getattr(self, 'allow_close', False):
            super().reject()

    def finish(self):
        self.timer.stop()
        self.done(0)


def monitor_installation(app, filename, pid):
    """Independent packaged window: survives closing the old application."""
    from .updates import _pid_alive
    dialog = UpdateProgress()
    dialog.phase.setText(tr('Installing the update'))
    poll = QTimer(dialog)
    terminal = False
    def tick():
        nonlocal terminal
        if terminal:
            return
        try:
            path = Path(filename)
            value = json.loads(path.read_text(encoding='utf-8')) if path.is_file() and path.stat().st_size < 4096 else {}
            phase = value.get('phase', 'Installing the update')
            dialog.update_progress('@update:' + json.dumps(dict(phase=phase)))
            if value.get('state') == 'success':
                terminal = True; poll.stop()
                dialog.allow_close = True
                dialog.bar.setRange(0, 1000); dialog.bar.setValue(1000)
                dialog.details.setText(tr('Starting the updated application…'))
                QTimer.singleShot(1200, lambda: app.exit(0))
            elif value.get('state') == 'error' or not _pid_alive(pid):
                terminal = True; poll.stop(); dialog.allow_close = True
                dialog.phase.setText(tr('The update did not finish successfully'))
                dialog.details.setText(tr('The previous application will be kept or restored. The installation log is in the update workspace.'))
                dialog.bar.setRange(0, 1000); dialog.bar.setValue(0)
                button = QPushButton(tr('Close')); button.clicked.connect(app.quit); dialog.layout().addWidget(button)
        except (OSError, ValueError):
            pass
    poll.timeout.connect(tick); poll.start(250)
    dialog.finished.connect(app.quit)
    dialog.show(); tick()
    return app.exec()


def choose_update(window, folder=True):
    if window.tasks or window.pending_jobs:
        return window.error(tr('Finish transfers and other operations before updating the application.'))
    for dialog in window.preview_windows:
        if hasattr(dialog, "text") and dialog.text.document().isModified():
            return window.error(tr('Save or close the editor before updating.'))
    try:
        current = installed_app()
    except UpdateError as exc:
        return window.error(str(exc))
    start = window.settings.value("update_folder", str(Path.home() / "Downloads"))
    if folder:
        selected = QFileDialog.getExistingDirectory(window, tr('Folder containing a Soovee Commander update'), start)
    else:
        selected, _ = QFileDialog.getOpenFileName(window, tr('Update package'), start,
                                                tr("Soovee Commander updates (*.stereoupdate)"))
    if not selected:
        return
    window.settings.setValue("update_folder", selected if folder else str(Path(selected).parent))
    progress = UpdateProgress(window)
    progress.update_progress('@update:' + json.dumps(dict(phase='Looking for update files', detail=selected)))
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.show()
    window.setEnabled(False)

    def prepare(report):
        release = find_release(selected, report=report)
        return prepare_update(release, current, result_path(), report)

    def failed(message):
        progress.finish()
        window.setEnabled(True)
        logger.error('Update failed · %s', message)
        window.error(tr('The update was not installed.\n\n{v0}').format(v0=tr(message)))

    def prepared(update):
        progress.finish()
        window.setEnabled(True)
        backup_note = (tr('The previous version will be kept as a backup.\n\n') if update.release.target.startswith("macos-")
                       else tr('The installer will install the new version.\n\n'))
        from . import dialog_kit
        if not dialog_kit.confirm(window, tr('Update and restart?'), tr('Soovee Commander {v0} → {v1}').format(v0=__version__, v1=update.release.version),
                                  update.release.notes, action=tr('Update and restart'), icon="update",
                                  note=tr('The signature and new application have been verified. Settings and connections will be preserved.') + " " + backup_note.strip()):
            update.discard()
            return
        window.setEnabled(False)

        def handoff():
            # run_task's finished signal removes the worker after the result callback.
            if window.tasks:
                QTimer.singleShot(30, handoff)
                return
            try:
                launch_update(update)
                if window.close():
                    QApplication.instance().quit()
                else:
                    window.setEnabled(True)
            except Exception as exc:
                update.discard()
                failed(str(exc))
        QTimer.singleShot(0, handoff)

    window.run_task(prepare, prepared, failed, report=progress.update_progress)


def show_update_result(window):
    path = result_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get("state") not in ("success", "error"):
            return
        path.unlink()
        logger.info('Update result · state=%s · version=%s · workspace=%s', data['state'], data.get('version'), str(Path(data.get('backup', '')).parent))
        backup = Path(data.get('backup', ''))
        if backup.name == 'previous.app' and backup.parent.name.startswith('.StereoCommander-update-'):
            installer_log = backup.parent / 'install.log'
            try:
                if installer_log.is_file() and not installer_log.is_symlink():
                    with installer_log.open('rb') as stream:
                        stream.seek(max(0, installer_log.stat().st_size - 64000))
                        logger.info('Update installer output · %s', stream.read(64000).decode('utf-8', errors='replace'))
            except OSError:
                logger.warning('The installer log could not be read · %s', installer_log)
        if data["state"] == "success":
            window.settings.setValue("last_update_backup", data.get("backup", ""))
            QMessageBox.information(window, tr('Update complete'),
                                    tr('Soovee Commander has been updated to version {v0}.\nSettings and connections have been preserved.').format(v0=__version__))
        else:
            window.error(tr('The update failed. The previous version is running.\nThe update did not change your original settings or files.'))
    except (OSError, ValueError):
        pass
