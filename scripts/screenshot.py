"""Create the README screenshot from temporary files and isolated preferences."""
from pathlib import Path
import sys
import tempfile
import time
import zipfile

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication
from soovee_commander.app import Commander
from soovee_commander.providers import ArchiveProvider
from soovee_commander.qt_runtime import prepare_plugins


def main():
    plugins = prepare_plugins()
    app = QApplication([]); app.setStyle('Fusion')
    with tempfile.TemporaryDirectory(prefix='soovee-preview-', dir='/private/tmp' if sys.platform == 'darwin' else None) as temporary:
        root = Path(temporary)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root / 'settings'))
        settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, 'StereoCommander', 'StereoCommander')
        settings.setValue('language', 'cs'); settings.setValue('theme', 'soovee_light'); settings.sync()
        files = root / 'Projects'; files.mkdir()
        for name in ('Design', 'Documents', 'Photos', 'Source code'):
            (files / name).mkdir()
        (files / 'README.md').write_text('# Soovee Commander\n', encoding='utf-8')
        (files / 'settings.json').write_text('{"panels": 2}\n', encoding='utf-8')
        archive = files / 'project-backup.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('assets/logo.svg', '<svg/>')
            output.writestr('README.md', '# Project backup\n')
            output.writestr('source/main.py', 'print("Soovee")\n')
        window = Commander(str(files), str(files)); window.resize(1360, 820); window.show()
        if sys.platform == 'darwin' and app.platformName() == 'offscreen':
            window.command_menu.hide()
        def settle():
            deadline = time.monotonic() + 12
            while (window.tasks or window.associations.timer.isActive()) and time.monotonic() < deadline:
                app.processEvents(); time.sleep(.01)
            app.processEvents()
            assert not window.tasks
        settle()
        window.left.new_tab(path=str(files / 'Documents')); settle()
        window.left.tabbar.setCurrentIndex(0)
        window.right.new_tab(ArchiveProvider(str(archive)), '/'); settle()
        for panel in (window.left, window.right):
            panel.set_column_separators(True)
        window.left.set_scrolling(pinned=True, vertical_only=True, auto_fit=True)
        window.activate(window.left); app.processEvents()
        destination = Path('docs/screenshot.png'); destination.parent.mkdir(exist_ok=True)
        assert window.grab().save(str(destination))
        window.close(); window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    if plugins:
        plugins.cleanup()


if __name__ == '__main__':
    main()
