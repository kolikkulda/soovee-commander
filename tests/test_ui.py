import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QTreeView
from PySide6.QtTest import QTest
import pytest
from test_core import ftp_server
from test_encrypted import tls_server, sftp_server

from soovee_commander.app import Commander, ConnectDialog, STYLE
from soovee_commander.filemodel import FileModel
from soovee_commander.providers import ArchiveProvider, Connection, Entry


@pytest.fixture(autouse=True)
def isolated_discovery(monkeypatch):
    # GUI tests use explicit loopback peers; real mDNS has its own integration test.
    class QuietDiscovery:
        def __init__(self, *args, **kwargs): pass
        def close(self): pass
    monkeypatch.setattr('soovee_commander.lan_ui.Discovery', QuietDiscovery)


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    # A cloud-managed workspace may mark .venv descendants UF_HIDDEN, which
    # prevents Qt's plugin discovery. Test with an ordinary temporary copy.
    import shutil
    plugins = tmp_path_factory.mktemp("qt-plugins")
    shutil.copytree(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath), plugins, dirs_exist_ok=True,
                    copy_function=shutil.copyfile)
    QCoreApplication.addLibraryPath(str(plugins))
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    yield application
    # Dispose widgets while Qt and its Python wrappers are still alive, rather
    # than leaving cyclic panel/overlay references to interpreter shutdown.
    from PySide6.QtCore import QEvent, QThreadPool
    import gc
    assert QThreadPool.globalInstance().waitForDone(10000)
    for widget in application.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    from soovee_commander.filetypes import type_icon
    from soovee_commander.toolbar_icons import toolbar_icon
    from PySide6.QtGui import QPixmapCache
    type_icon.cache_clear()
    toolbar_icon.cache_clear()
    QPixmapCache.clear()
    gc.collect()


def settle(app, window):
    deadline = time.monotonic() + 8
    quiet_since = None
    while time.monotonic() < deadline:
        app.processEvents()
        pending = window.tasks or window.associations.timer.isActive() or any(
            panel.appearance.timer.isActive() for panel in (window.left, window.right))
        if pending:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= .075:
            return
        time.sleep(0.005)
    assert not window.tasks, "Background operation did not settle"


def test_disk_summary_follows_archive_language_and_narrow_panels(app, tmp_path, monkeypatch):
    from soovee_commander.storage import VolumeInfo
    import soovee_commander.panel as panel_module
    info = VolumeInfo('Free {v0}', str(tmp_path), 1024 ** 4, 400 * 1024 ** 3, 300 * 1024 ** 3, True, 'APFS')
    monkeypatch.setattr(panel_module, 'read_volume', lambda path: info)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window); window.change_language('en')
    panel = window.left
    assert panel.disk_summary.info == info and panel.disk_summary.bar.isVisible()
    assert panel.drive_button.accessibleName() == info.name
    assert 'Reserved' in panel.disk_summary.toolTip() and 'Read-only' in panel.disk_summary.toolTip()
    archive = tmp_path / 'test.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('file.txt', 'sample')
    panel.open_archive(str(archive)); settle(app, window)
    assert panel.disk_summary.info == info
    window.change_language('cs')
    assert panel.disk_summary.free.text().startswith('Volno ')
    assert panel.drive_button.accessibleName() == info.name
    window.change_language('en')
    assert panel.disk_summary.free.text().startswith('Free ')
    from soovee_commander.themes import THEMES
    for theme in THEMES:
        index = window.theme_combo.findData(theme)
        assert index >= 0
        window.theme_combo.setCurrentIndex(index)
        window.resize(1080, 680); window.panel_splitter.setSizes([320, 740]); app.processEvents()
        assert panel.disk_summary.free.isVisible() and panel.disk_summary.details.isVisible()
        assert panel.disk_summary.free.geometry().right() < panel.disk_summary.details.geometry().left()
    window.close()


def test_slow_disk_probe_cannot_overwrite_new_location_or_block_navigation(app, tmp_path, monkeypatch):
    import threading
    from soovee_commander.storage import VolumeInfo
    from soovee_commander.providers import Provider
    import soovee_commander.panel as panel_module
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir(); second.mkdir()
    release = threading.Event()
    main_thread = threading.get_ident()

    def read(path):
        assert threading.get_ident() != main_thread
        if path == str(first):
            assert release.wait(5)
        return VolumeInfo(Path(path).name, path, 1000, 400, 400)

    monkeypatch.setattr(panel_module, 'read_volume', read)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(first), str(second)); window.show(); window.change_language('en')
    deadline = time.monotonic() + 4
    try:
        while not window.left._volume_busy and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert window.left._volume_busy
        window.left.navigate(panel_module.LocalProvider(), str(second))
        while window.left.path != str(second) and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert window.left.path == str(second), 'Disk probe blocked folder navigation'
    finally:
        release.set()
    settle(app, window)
    assert window.left.disk_summary.info.name == 'second'
    remote = Provider(); remote.label = 'Server'; remote.list = lambda path: []
    window.left.navigate(remote, '/'); settle(app, window)
    assert window.left.disk_summary.info is None
    assert window.left.disk_summary.free.text() == 'Capacity unavailable'
    assert not window.left.disk_summary.bar.isVisible()
    window.close()


def test_drive_menu_reads_capacity_in_background_and_preserves_root(app, tmp_path, monkeypatch):
    import threading
    from soovee_commander.storage import VolumeInfo
    import soovee_commander.panel as panel_module
    main_thread = threading.get_ident()
    info = VolumeInfo('External disk', str(tmp_path), 1000, 400, 400)

    def read():
        assert threading.get_ident() != main_thread
        return (info,)

    monkeypatch.setattr(panel_module, 'read_volumes', read)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window); window.change_language('en')
    panel = window.left
    panel.populate_drives(panel.drive_menu)
    assert any('Reading drives' in a.text() for a in panel.drive_menu.actions())
    settle(app, window)
    panel.populate_drives(panel.drive_menu)
    action = next(a for a in panel.drive_menu.actions() if 'External disk' in a.text())
    assert 'Free' in action.text() and 'Used' in action.text() and 'Total' in action.text()
    action.trigger(); settle(app, window)
    assert panel.path == str(tmp_path)
    window.close()


@pytest.fixture(autouse=True)
def dispose_test_windows(app):
    """Closed top-level widgets must not accumulate between stylesheet tests."""
    yield
    from PySide6.QtCore import QEvent, QThreadPool
    import gc
    assert QThreadPool.globalInstance().waitForDone(10000)
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


def test_panels_archive_navigation_filter_and_preview(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "notes.txt").write_text("Hello from the preview")
    (left / ".hidden").write_text("hidden")
    with zipfile.ZipFile(left / "bundle.zip", "w") as archive:
        archive.writestr("inside/readme.txt", "Archive preview")
    window = Commander(str(left), str(right))
    window.show()
    settle(app, window)
    assert len(window.left.entries) == 3

    def item(name):
        return window.left.model.index_for_name(name)

    window.hidden.setChecked(False)
    window.left.refresh()
    settle(app, window)
    assert not item(".hidden").isValid()
    window.left.filter.setText("notes")
    window.left.apply_filter()
    assert not item("bundle.zip").isValid()
    window.left.filter.clear()
    window.left.apply_filter()
    window.left.tree.setCurrentIndex(item("notes.txt"))
    window.show_preview()
    settle(app, window)
    assert len(window.preview_windows) == 1
    window.preview_windows[0].close()
    app.processEvents()
    window.left.tree.setCurrentIndex(item("bundle.zip"))
    window.left.open_current()
    settle(app, window)
    assert isinstance(window.left.provider, ArchiveProvider)
    assert window.left.path == "/"
    window.left.parent()
    settle(app, window)
    assert window.left.path == str(left)
    window.left.tree.setFocus()
    app.processEvents()
    QTest.keyClick(window.left.tree, Qt.Key.Key_Tab)
    app.processEvents()
    assert window.active == window.right
    window.close()
    app.processEvents()


def test_virtual_model_large_listing_and_sort_preserves_selection(app):
    class CountingModel(FileModel):
        requests = 0

        def data(self, index, role=Qt.ItemDataRole.DisplayRole):
            self.requests += 1
            return super().data(index, role)

    tree = QTreeView()
    tree.setUniformRowHeights(True)
    model = CountingModel(tree)
    tree.setModel(model)
    tree.resize(650, 500)
    model.set_entries([Entry(f"file-{i:06d}.txt", False, i) for i in range(100_000)], True)
    tree.show()
    app.processEvents()
    assert model.rowCount() == 100_001
    assert model.requests < 5_000  # Qt must not query/render all 400,000 cells.
    selected = model.index_for_name("file-000042.txt")
    tree.setCurrentIndex(selected)
    model.sort(1, Qt.SortOrder.DescendingOrder)
    app.processEvents()
    assert tree.currentIndex().data(Qt.ItemDataRole.UserRole).name == "file-000042.txt"
    assert model.entry(1).size == 99_999
    model.set_filter("99999")
    assert model.rowCount() == 2  # Parent remains available when filtering.
    assert model.entry(1).name == "file-099999.txt"
    tree.close()


def test_saved_connection_never_persists_password(app, tmp_path):
    import json
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    dialog = ConnectDialog(window)
    assert (tmp_path / 'settings') in Path(window.settings.fileName()).parents
    dialog.path.setText("/web")
    dialog.save_profile(Connection("SFTP", "example.com", 2222, "user", "highly-secret", "keyfile"))
    window.settings.sync()
    stored = window.settings.value("connections")
    assert "highly-secret" not in stored
    assert "password" not in stored
    assert json.loads(stored)[0]["port"] == 2222
    loaded = ConnectDialog(window)
    loaded.load_profile(1)
    assert loaded.host.text() == "example.com"
    assert loaded.path.text() == "/web"
    assert loaded.password.text() == ""
    window.close()


def test_copy_from_ui_and_navigation_history(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "file.txt").write_text("source")
    (right / "file.txt").write_text("old")
    (left / "child").mkdir()
    window = Commander(str(left), str(right))
    window.show()
    settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name("file.txt"))

    def accept_transfer():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        combo = dialog.findChild(QComboBox)
        combo.setCurrentIndex(combo.findData("rename"))
        dialog.accept()

    QTimer.singleShot(20, accept_transfer)
    window.copy()
    settle(app, window)
    assert (right / "file.txt").read_text() == "old"
    assert (right / "file (2).txt").read_text() == "source"
    window.left.tree.setCurrentIndex(window.left.model.index_for_name("child"))
    window.left.open_current()
    settle(app, window)
    assert window.left.path == str(left / "child")
    window.left.back()
    settle(app, window)
    assert window.left.path == str(left)
    window.left.forward()
    settle(app, window)
    assert window.left.path == str(left / "child")
    window.close()


def test_editor_preserves_crlf_bom_and_refuses_external_change(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    data = b"\xef\xbb\xbfline one\r\nline two\r\n"
    path = tmp_path / "notes.txt"
    path.write_bytes(data)
    window = Commander(str(tmp_path), str(tmp_path))
    errors = []
    window.error = errors.append
    settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name("notes.txt"))
    window.show_editor()
    settle(app, window)
    editor = window.preview_windows[-1]
    editor.text.setPlainText("updated\nsecond\n")
    editor.text.document().setModified(True)
    editor.save()
    settle(app, window)
    assert path.read_bytes() == b"\xef\xbb\xbfupdated\r\nsecond\r\n"
    assert not errors
    editor.text.setPlainText("my next edit")
    editor.text.document().setModified(True)
    path.write_bytes(b"another application changed this")
    editor.save()
    settle(app, window)
    assert errors and "changed" in errors[-1]
    assert path.read_bytes() == b"another application changed this"
    assert editor.text.document().isModified()
    editor.text.document().setModified(False)
    editor.close()
    app.processEvents()
    window.close()


def test_update_cancel_after_preparation_keeps_app_and_profiles(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from soovee_commander import update_ui
    from soovee_commander.updates import PreparedUpdate, Release
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    current = tmp_path / "StereoCommander.app"
    current.mkdir()
    (current / "original").write_text("keep me")
    workspace = tmp_path / ".StereoCommander-update-test"
    workspace.mkdir()
    lock = tmp_path / ".StereoCommander-update.lock"
    lock.mkdir()
    release = Release(tmp_path / "update.stereoupdate", "9.0.0", "macos-arm64", "application.zip", 1, "0"*64, "Test")
    prepared = PreparedUpdate(release, current, workspace, workspace / "new.app", lock, tmp_path / "result.json")
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    window.settings.setValue("connections", '[{"host":"saved.example.com"}]')
    monkeypatch.setattr(update_ui, "installed_app", lambda: current)
    monkeypatch.setattr(update_ui.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    monkeypatch.setattr(update_ui, "find_release", lambda *args, **kwargs: release)
    monkeypatch.setattr(update_ui, "prepare_update", lambda *args: prepared)
    monkeypatch.setattr(update_ui.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr('soovee_commander.dialog_kit.confirm', lambda *a, **k: False)
    update_ui.choose_update(window)
    settle(app, window)
    assert window.isEnabled()
    assert (current / "original").read_text() == "keep me"
    assert "saved.example.com" in window.settings.value("connections")
    assert not workspace.exists()
    assert not lock.exists()
    window.close()


def test_update_rejects_bad_package_in_ui(app, tmp_path, monkeypatch):
    from soovee_commander import update_ui
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    (tmp_path / "broken.stereoupdate").write_text("not an update")
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    errors = []
    window.error = errors.append
    monkeypatch.setattr(update_ui, "installed_app", lambda: tmp_path / "StereoCommander.app")
    monkeypatch.setattr(update_ui.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    update_ui.choose_update(window)
    settle(app, window)
    assert errors and "was not installed" in errors[-1]
    assert window.isEnabled()
    window.close()


def test_update_waits_for_transfers_before_opening_dialog(app, tmp_path, monkeypatch):
    from soovee_commander import update_ui
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    errors = []
    window.error = errors.append
    window.pending_jobs = 1
    update_ui.choose_update(window)
    assert errors and "transfers" in errors[-1]
    window.pending_jobs = 0
    window.close()


def test_tabs_keep_independent_paths_filters_selection_and_history(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    (first / "keep.txt").write_text("one")
    (first / "other.bin").write_text("two")
    (second / "child").mkdir()
    window = Commander(str(first), str(second))
    settle(app, window)
    panel = window.left
    panel.filter.setText("keep")
    panel.apply_filter()
    panel.tree.setCurrentIndex(panel.model.index_for_name("keep.txt"))
    panel.new_tab(path=str(second))
    settle(app, window)
    assert panel.tabbar.count() == 2
    assert panel.path == str(second)
    assert panel.filter.text() == ""
    panel.navigate(panel.provider, str(second / "child"))
    settle(app, window)
    panel.tabbar.setCurrentIndex(0)
    settle(app, window)
    assert panel.path == str(first)
    assert panel.filter.text() == "keep"
    assert [e.name for e in panel.selected()] == ["keep.txt"]
    assert not panel.history
    panel.tabbar.setCurrentIndex(1)
    settle(app, window)
    panel.back()
    settle(app, window)
    assert panel.path == str(second)
    panel.close_tab()
    assert panel.tabbar.count() == 1
    assert panel.path == str(first)
    panel.reopen_tab()
    settle(app, window)
    assert panel.path == str(second)
    window.close()


def test_background_listing_cannot_replace_another_tab(app, tmp_path):
    from threading import Event
    from soovee_commander.providers import LocalProvider
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    fast = tmp_path / "fast"
    fast.mkdir()
    (fast / "fast.txt").write_text("fast")
    gate, started = Event(), Event()

    class SlowProvider(LocalProvider):
        def list(self, path):
            started.set()
            gate.wait(timeout=5)
            return [Entry("slow.txt", False, 4)]

    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    panel = window.left
    try:
        panel.navigate(SlowProvider(), "/slow")
        assert started.wait(timeout=2)
        panel.new_tab(LocalProvider(), str(fast))
        deadline = time.monotonic() + 3
        while panel._current.loading and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert panel.path == str(fast)
        gate.set()
        settle(app, window)
        assert panel.path == str(fast)
        assert [e.name for e in panel.entries] == ["fast.txt"]
        panel.tabbar.setCurrentIndex(0)
        settle(app, window)
        assert panel.path == str(Path('/slow').absolute())
        assert [e.name for e in panel.entries] == ["slow.txt"]
    finally:
        gate.set()
        settle(app, window)
        window.close()


def test_clipboard_paths_native_file_uri_relative_and_selected_file(app, tmp_path):
    from PySide6.QtCore import QUrl
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    source = tmp_path / "Příliš žluťoučký adresář"
    source.mkdir()
    child = source / "child"
    child.mkdir()
    file = child / "notes.txt"
    file.write_text("hello")
    window = Commander(str(source), str(tmp_path))
    errors = []
    window.error = errors.append
    settle(app, window)
    panel = window.left
    panel.copy_directory()
    assert app.clipboard().text() == str(source)
    app.clipboard().setText('"' + str(child) + '"')
    panel.paste_path()
    settle(app, window)
    assert panel.path == str(child)
    panel.tree.setCurrentIndex(panel.model.index_for_name("notes.txt"))
    panel.copy_paths()
    assert app.clipboard().text() == str(file)
    window.right.navigate_text(QUrl.fromLocalFile(str(file)).toString())
    settle(app, window)
    assert window.right.path == str(child)
    assert [e.name for e in window.right.selected()] == ["notes.txt"]
    panel.navigate_text("..")
    settle(app, window)
    assert panel.path == str(source)
    assert not errors
    window.close()


def test_archive_location_copy_and_paste_roundtrip(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    file = tmp_path / "archiv ! český.zip"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("složka/file.txt", "hello")
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    window.left.open_archive(str(file), "/složka")
    settle(app, window)
    window.left.copy_directory()
    location = app.clipboard().text()
    window.right.navigate_text(location)
    settle(app, window)
    assert isinstance(window.right.provider, ArchiveProvider)
    assert window.right.provider.filename == str(file)
    assert window.right.path == "/složka"
    window.close()


def test_reordered_local_tabs_and_theme_survive_restart(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir(); second.mkdir()
    window = Commander(str(first), str(second))
    settle(app, window)
    window.left.new_tab(path=str(second))
    settle(app, window)
    window.left.tabbar.moveTab(1, 0)
    window.theme_combo.setCurrentIndex(window.theme_combo.findData("slate"))
    window.close()
    restored = Commander()
    settle(app, restored)
    assert restored.theme_key == "slate"
    assert restored.left.tabbar.count() == 2
    assert restored.left.path == str(second)
    restored.left.tabbar.setCurrentIndex(1)
    settle(app, restored)
    assert restored.left.path == str(first)
    restored.close()


@pytest.mark.parametrize("theme", ["soovee", "light", "slate", "dark"])
def test_theme_palette_and_file_actions_remain_usable(app, tmp_path, theme):
    from PySide6.QtGui import QColor, QPalette
    from soovee_commander.themes import THEMES
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme))
    assert app.palette().color(QPalette.ColorRole.Base) == QColor(THEMES[theme]["surface"])
    assert window.left.model.archive_color == QColor(THEMES[theme]["archive"])
    window.left.new_tab()
    settle(app, window)
    assert window.left.tabbar.count() == 2
    window.close()


def test_tab_keyboard_shortcuts_close_tabs_not_the_window(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path))
    window.show()
    window.activateWindow()
    settle(app, window)
    window.left.tree.setFocus()
    app.processEvents()
    QTest.keyClick(window.left.tree, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    settle(app, window)
    assert window.left.tabbar.count() == 2
    QTest.keyClick(window.left.tree, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert window.left.tabbar.count() == 1
    assert window.isVisible()
    QTest.keyClick(window.left.tree, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    settle(app, window)
    assert window.left.tabbar.count() == 2
    window.close()


def test_remote_path_roundtrip_reuses_session_without_copying_password(app, tmp_path, monkeypatch):
    import json
    from soovee_commander.providers import RemoteProvider
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path))
    errors = []
    window.error = errors.append
    settle(app, window)
    remote = RemoteProvider(Connection("SFTP", "example.invalid", 2222, "user@company", "never-copy-secret"))
    monkeypatch.setattr(remote, "list", lambda path: [Entry("folder", True)])
    window.left.new_tab(remote, "/česká složka")
    settle(app, window)
    window.left.copy_directory()
    url = app.clipboard().text()
    assert "never-copy-secret" not in url
    assert "user%40company" in url
    window.right.navigate_text(url)
    settle(app, window)
    assert window.right.provider is remote
    assert window.right.path == "/česká složka"
    window.right.navigate_text("sftp://user:do-not-log-this@example.invalid/")
    assert errors and "do-not-log-this" not in errors[-1]
    saved = json.dumps(window.left.saved_tabs())
    assert "never-copy-secret" not in saved
    assert "example.invalid" not in saved
    window.close()


@pytest.mark.parametrize("route", ["parent", "back", "up_button", "dotdot", "history_button", "breadcrumb"])
def test_return_to_parent_restores_departed_folder_and_scroll(app, tmp_path, route):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    root = tmp_path / "folders"
    root.mkdir()
    for number in range(150):
        (root / f"folder-{number:03d}").mkdir()
    window = Commander(str(root), str(tmp_path))
    window.show()
    settle(app, window)
    panel = window.left
    index = panel.model.index_for_name("folder-110")
    panel.tree.setCurrentIndex(index)
    panel.tree.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)
    app.processEvents()
    scroll = panel.tree.verticalScrollBar().value()
    assert scroll > 0
    panel.open_current()
    settle(app, window)
    assert panel.path == str(root / "folder-110")
    if route == "parent":
        panel.parent()
    elif route == "back":
        panel.back()
    elif route == "up_button":
        next(b for b in panel.findChildren(__import__('PySide6.QtWidgets', fromlist=['QPushButton']).QPushButton, "pathButton") if b.text() == "↑").click()
    elif route == "dotdot":
        panel.tree.setCurrentIndex(panel.model.index(0, 0))
        panel.open_current()
    elif route == "history_button":
        next(b for b in window.top_buttons if b.property("command_id") == "back").click()
    else:
        next(panel.crumbs.itemAt(i).widget() for i in range(panel.crumbs.count())
             if panel.crumbs.itemAt(i).widget() and panel.crumbs.itemAt(i).widget().toolTip() == str(root)).click()
    settle(app, window)
    assert panel.path == str(root)
    assert panel.current_entry().name == "folder-110"
    assert panel.tree.verticalScrollBar().value() == scroll
    assert panel.tree.visualRect(panel.tree.currentIndex()).intersects(panel.tree.viewport().rect())
    window.close()


def test_history_forward_restores_cursor_and_failed_back_keeps_history(app, tmp_path):
    import shutil
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    root = tmp_path / "parent"
    child = root / "child"
    child.mkdir(parents=True)
    for number in range(100):
        (child / f"file-{number:03d}.txt").touch()
    window = Commander(str(root), str(tmp_path))
    window.show()
    errors = []
    window.error = errors.append
    settle(app, window)
    panel = window.left
    panel.tree.setCurrentIndex(panel.model.index_for_name("child"))
    panel.open_current()
    settle(app, window)
    index = panel.model.index_for_name("file-085.txt")
    panel.tree.setCurrentIndex(index)
    panel.tree.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)
    app.processEvents()
    scroll = panel.tree.verticalScrollBar().value()
    panel.back()
    settle(app, window)
    panel.forward()
    settle(app, window)
    assert panel.current_entry().name == "file-085.txt"
    assert panel.tree.verticalScrollBar().value() == scroll
    history_size = len(panel.history)
    # Rename the parent from outside so a history entry no longer resolves.
    relocated = tmp_path / "relocated"
    root.rename(relocated)
    panel.back()
    settle(app, window)
    assert errors
    assert len(panel.history) == history_size
    assert panel.path == str(child)
    window.close()


def test_leaving_archive_places_cursor_on_archive_file(app, tmp_path):
    from soovee_commander.providers import LocalProvider
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    file = tmp_path / "z-archive.zip"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("inner/file.txt", "data")
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    panel = window.left
    panel.tree.setCurrentIndex(panel.model.index_for_name(file.name))
    panel.open_current()
    settle(app, window)
    panel.parent()
    settle(app, window)
    assert isinstance(panel.provider, LocalProvider)
    assert panel.current_entry().name == file.name
    window.close()


def test_remapped_shortcuts_buttons_menus_and_restart_share_one_command(app, tmp_path):
    import copy
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    (tmp_path / "file.txt").touch()
    window = Commander(str(tmp_path), str(tmp_path))
    window.show()
    window.activateWindow()
    settle(app, window)
    calls = []
    window.commands.callbacks["rename"] = lambda: calls.append("rename")
    config = copy.deepcopy(window.commands.config)
    config["keys"]["rename"] = ["F9"]
    config["bottom"] = [{"command": "rename", "label": "Jméno"}]
    window.commands.apply(config)
    window.left.tree.setFocus()
    app.processEvents()
    QTest.keyClick(window.left.tree, Qt.Key.Key_F2)
    assert not calls
    QTest.keyClick(window.left.tree, Qt.Key.Key_F9)
    app.processEvents()     # menu commands run after the key event finishes
    assert calls == ["rename"]
    assert window.bottom_buttons[0].text() == "F9  Jméno"
    window.bottom_buttons[0].click()
    window.commands.actions["rename"].trigger()
    app.processEvents()
    assert len(calls) == 3
    before = copy.deepcopy(window.commands.config)
    bad = copy.deepcopy(config)
    bad["keys"]["rename"] = ["F5"]
    with pytest.raises(ValueError):
        window.commands.apply(bad)
    assert window.commands.config == before
    window.close()
    restored = Commander(str(tmp_path), str(tmp_path))
    settle(app, restored)
    assert restored.commands.config["keys"]["rename"] == ["F9"]
    assert restored.bottom_buttons[0].text() == "F9  Jméno"
    restored.close()


def test_file_navigation_keys_can_be_remapped_without_breaking_path_typing(app, tmp_path):
    import copy
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    child = tmp_path / "child"
    child.mkdir()
    window = Commander(str(child), str(tmp_path))
    window.show()
    window.activateWindow()
    settle(app, window)
    config = copy.deepcopy(window.commands.config)
    config["keys"]["parent"] = ["Alt+Up"]
    window.commands.apply(config)
    window.left.tree.setFocus()
    QTest.keyClick(window.left.tree, Qt.Key.Key_Backspace)
    app.processEvents()
    assert window.left.path == str(child)
    window.left.address.setFocus()
    window.left.address.setText("abc")
    QTest.keyClick(window.left.address, Qt.Key.Key_Backspace)
    assert window.left.address.text() == "ab"
    assert window.left.path == str(child)
    window.left.tree.setFocus()
    QTest.keyClick(window.left.tree, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    settle(app, window)
    assert window.left.path == str(tmp_path)
    assert window.left.current_entry().name == "child"
    window.close()


def test_f2_renames_cursor_item_preserves_extension_and_tracks_new_name(app, tmp_path):
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtCore import QItemSelectionModel
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    (tmp_path / "notes.txt").write_text("hello")
    window = Commander(str(tmp_path), str(tmp_path))
    window.show()
    window.activateWindow()
    settle(app, window)
    panel = window.left
    panel.tree.selectionModel().setCurrentIndex(panel.model.index_for_name("notes.txt"), QItemSelectionModel.SelectionFlag.NoUpdate)
    panel.tree.clearSelection()

    def confirm():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        edit = dialog.findChild(QLineEdit)
        assert edit.selectedText() == "notes"
        edit.setText("renamed.txt")
        dialog.accept()

    QTimer.singleShot(30, confirm)
    panel.tree.setFocus()
    QTest.keyClick(panel.tree, Qt.Key.Key_F2)
    settle(app, window)
    assert (tmp_path / "renamed.txt").read_text() == "hello"
    assert not (tmp_path / "notes.txt").exists()
    assert panel.current_entry().name == "renamed.txt"
    window.close()


def test_controls_dialog_cancel_does_not_change_live_bindings(app, tmp_path):
    from soovee_commander.control_settings import ControlsDialog
    import copy
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path))
    settle(app, window)
    before = copy.deepcopy(window.commands.config)
    dialog = ControlsDialog(window)
    dialog.key_edits["rename"].setText("F9")
    dialog.bottom.set_items([{"command": "rename", "label": "Test"}])
    dialog.reject()
    assert window.commands.config == before
    window.close()


def test_file_clipboard_copy_cut_paste_and_external_urls(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QMessageBox
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "one.txt").write_text("original")
    window = Commander(str(a), str(b)); window.show(); settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name("one.txt"))
    window.activate(window.left); window.left.tree.setFocus(); app.processEvents()
    QTest.keyClick(window.left.tree, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert Path(app.clipboard().mimeData().urls()[0].toLocalFile()) == a / 'one.txt'
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr('soovee_commander.dialog_kit.confirm', lambda *a, **k: True)
    window.activate(window.right); window.clipboard_paste(); settle(app, window)
    assert (b / "one.txt").read_text() == "original"
    (b / "one.txt").unlink()
    window.activate(window.left); window.clipboard_copy(True)
    window.activate(window.right); window.clipboard_paste(); settle(app, window)
    assert not (a / "one.txt").exists() and (b / "one.txt").exists()
    assert not app.clipboard().mimeData() or not app.clipboard().mimeData().hasUrls()
    # Import file URLs produced by Finder/Explorer or another application.
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(b / "one.txt"))])
    app.clipboard().setMimeData(mime)
    window.activate(window.left); window.clipboard_paste(); settle(app, window)
    assert (a / "one.txt").read_text() == "original"
    app.clipboard().clear()
    window.close(); app.processEvents()


def test_named_locked_tabs_and_folder_sizes(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    root = tmp_path / "root"; root.mkdir(); (root / "folder").mkdir()
    (root / "folder" / "data").write_bytes(b"x" * 421)
    window = Commander(str(root), str(root)); window.show(); settle(app, window)
    panel = window.left
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Práce", True))
    monkeypatch.setattr('soovee_commander.dialog_kit.ask_text', lambda *args, **kwargs: "Práce")
    panel.rename_tab(); panel.toggle_lock()
    original = panel._current
    panel.navigate(panel.provider, str(root / "folder")); settle(app, window)
    assert panel.tabbar.count() == 2 and panel._current is not original
    assert original.path == str(root) and original.locked and original.label == "Práce"
    panel.tabbar.setCurrentIndex(0); settle(app, window)
    panel.tree.setCurrentIndex(panel.model.index_for_name("folder"))
    panel.tree.setFocus(); app.processEvents()
    QTest.keyClick(panel.tree, Qt.Key.Key_Space); settle(app, window)
    assert panel.model.directory_sizes["folder"] == 421
    assert "421" in panel.model.index_for_name("folder").siblingAtColumn(1).data()
    saved = panel.saved_tabs()
    window.close(); app.processEvents()
    restored = Commander(); settle(app, restored)
    assert restored.left._current.locked and restored.left._current.label == "Práce"
    assert saved["tabs"][0]["locked"]
    restored.close(); app.processEvents()


def test_search_multi_rename_undo_and_sync_dialogs(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from soovee_commander.tool_dialogs import SearchDialog, MultiRenameDialog, CompareDialog
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    (a / "one.txt").write_text("needle")
    window = Commander(str(a), str(b)); window.show(); settle(app, window)
    window.activate(window.left)
    dialog = window.open_tool(SearchDialog)
    dialog.pattern.setText("*.txt"); dialog.text.setText("needle"); dialog.start_search(); settle(app, window)
    assert len(dialog.matches) == 1
    dialog.results.setCurrentIndex(dialog.results.model().index(0, 0)); dialog.open_result(); settle(app, window)
    assert window.left.current_entry().name == "one.txt"
    rename = window.open_tool(MultiRenameDialog)
    rename.mask.setText("file-[C]")
    assert rename.names == ["file-1.txt"]
    assert (a / "one.txt").exists()  # preview has not mutated anything
    rename.apply(); settle(app, window)
    assert (a / "file-1.txt").read_text() == "needle"
    window.undo_multi_rename(); settle(app, window)
    assert (a / "one.txt").read_text() == "needle"
    compare = window.open_tool(CompareDialog); compare.scan(); settle(app, window)
    assert compare.differences[0].status == 'Left only'
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr('soovee_commander.dialog_kit.confirm', lambda *a, **k: True)
    compare.synchronize("right"); settle(app, window)
    assert (b / "one.txt").read_text() == "needle"
    remaining = window.open_tool(SearchDialog)
    app.processEvents()
    window.close(); app.processEvents()
    assert not remaining.isVisible()


def test_trash_failure_never_falls_back_to_permanent_delete(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QFile
    from PySide6.QtWidgets import QMessageBox
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    (tmp_path / "keep.txt").write_text("keep")
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name("keep.txt"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr('soovee_commander.dialog_kit.confirm', lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(QFile, "moveToTrash", lambda path: (calls.append(path) or False, ""))
    window.delete(); settle(app, window)
    assert calls == [str(tmp_path / "keep.txt")]
    assert (tmp_path / "keep.txt").read_text() == "keep"
    assert window.failed_jobs == 1
    window.close(); app.processEvents()


def test_external_command_uses_literal_arguments_and_reports_start_failure(app, tmp_path):
    import json, sys
    from soovee_commander.extensions import launch
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    special = tmp_path / "literal {path} $(no shell).txt"
    special.write_text("safe")
    window.left.refresh(); settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name(special.name))
    program = "import sys; from pathlib import Path; Path('received.json').write_text(__import__('json').dumps(sys.argv[1:]))"
    window.settings.setValue("external_tools", json.dumps([{"title": "Test", "executable": sys.executable, "args": ["-c", program, "{files}"]}]))
    launch(window, 0)
    deadline = time.monotonic() + 8
    while window.external_processes and time.monotonic() < deadline:
        app.processEvents(); time.sleep(0.01)
    settle(app, window)
    assert json.loads((tmp_path / "received.json").read_text()) == [str(special)]
    errors = []; window.error = errors.append
    window.settings.setValue("external_tools", json.dumps([{"title": "Missing", "executable": str(tmp_path / "missing"), "args": []}]))
    launch(window, 0)
    for _ in range(20):
        app.processEvents(); time.sleep(0.005)
    assert errors and not window.external_processes
    window.close(); app.processEvents()


def test_function_menu_order_f2_bar_and_old_default_migration(app, tmp_path):
    import json
    from soovee_commander.commands import defaults
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "StereoCommander", "StereoCommander")
    previous = defaults()
    previous["bottom"] = [{"command": name, "label": ""} for name in ("view", "edit", "copy", "move", "mkdir", "delete")]
    settings.setValue("controls", json.dumps(previous)); settings.sync()
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    actions = window.command_menu.actions()[0].menu().actions()
    function_commands = [a.objectName() for a in actions if a.objectName() in {"command_" + n for n in ("rename", "view", "edit", "copy", "move", "mkdir", "delete")}]
    assert function_commands == ["command_" + n for n in ("rename", "view", "edit", "copy", "move", "mkdir", "delete")]
    assert window.bottom_buttons[0].text() == "F2  Rename"
    config = window.commands.config.copy(); config["bottom"] = previous["bottom"]
    window.commands.apply(config)  # Explicit customization after migration is respected.
    window.close(); app.processEvents()
    restored = Commander(str(tmp_path), str(tmp_path)); settle(app, restored)
    assert restored.bottom_buttons[0].property("command_id") == "view"
    restored.close(); app.processEvents()


def test_columns_resizing_moving_hiding_metadata_and_persistence(app, tmp_path):
    from PySide6.QtWidgets import QHeaderView
    from soovee_commander.columns import COLUMNS, IDS
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    (tmp_path / "model.stl").write_bytes(b"solid example")
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    panel = window.left; header = panel.tree.header()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    panel.tree.setColumnWidth(0, 345)
    panel.tree.setColumnWidth(IDS["program"], 215)
    panel.toggle_column(IDS["mime"], True)
    panel.toggle_column(IDS["modified"], False)
    header.moveSection(header.visualIndex(IDS["size"]), 0)
    layout = panel.column_layout()
    next(c for c in layout if c["id"] == "mime")["label"] = "Content type"
    next(c for c in layout if c["id"] == "size")["align"] = "center"
    panel.apply_columns(layout)
    index = panel.model.index_for_name("model.stl")
    assert panel.model.data(index.siblingAtColumn(IDS["bytes"])) == "13"
    assert panel.model.data(index.siblingAtColumn(IDS["permissions"]))
    assert "3D" in panel.model.data(index.siblingAtColumn(IDS["type"]))
    assert panel.model.data(index.siblingAtColumn(IDS["path"])) == str(tmp_path / "model.stl")
    right_before = window.right.column_layout()
    window.close(); app.processEvents()
    restored = Commander(str(tmp_path), str(tmp_path)); settle(app, restored)
    assert restored.left.column_layout() == layout
    assert restored.right.column_layout() == right_before
    assert restored.left.tree.header().logicalIndex(0) == IDS["size"]
    restored.close(); app.processEvents()


def test_columns_dialog_cancel_and_apply_to_both_panels(app, tmp_path):
    from soovee_commander.columns import ColumnsDialog, IDS
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    before = window.left.column_layout()
    dialog = ColumnsDialog(window.left)
    dialog.table.cellWidget(0, 3).setValue(420)
    dialog.reject()
    assert window.left.column_layout() == before
    dialog = ColumnsDialog(window.left)
    dialog.table.cellWidget(0, 3).setValue(420)
    dialog.table.cellWidget(0, 2).setText("Filename")
    dialog.other.setChecked(True); dialog.save()
    assert window.left.column_layout() == window.right.column_layout()
    assert window.left.model.headerData(0, Qt.Orientation.Horizontal) == "Filename"
    window.close(); app.processEvents()


def test_file_type_icons_and_cached_application_queries(app, tmp_path, monkeypatch):
    from threading import get_ident
    from soovee_commander.native_apps import Application
    from soovee_commander.columns import IDS
    from soovee_commander.filetypes import kind
    import soovee_commander.associations as associations
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    for name in ("one.txt", "two.txt", "movie.mkv", "image.png", "cad.step"):
        (tmp_path / name).touch()
    calls = []; main_thread = get_ident()
    def query(ext):
        calls.append((ext, get_ident()))
        return Application("/example/viewer", "Example Viewer")
    monkeypatch.setattr(associations, "default_application", query)
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    panel = window.left
    index = panel.model.index_for_name("one.txt")
    assert panel.model.data(index.siblingAtColumn(IDS["program"])) == "Example Viewer"
    assert [ext for ext, _ in calls].count(".txt") == 1
    assert all(thread != main_thread for _, thread in calls)
    assert len({kind(name)[0] for name in ("a.txt", "b.mkv", "c.png", "d.step", "e.zip")}) == 5
    assert len({panel.model.data(panel.model.index_for_name(name), Qt.ItemDataRole.DecorationRole).cacheKey() for name in ("one.txt", "movie.mkv", "image.png", "cad.step")}) == 4
    window.close(); app.processEvents()


def test_open_with_custom_association_context_actions_and_reset(app, tmp_path, monkeypatch):
    import json
    from soovee_commander.native_apps import Application
    import soovee_commander.associations as associations
    import soovee_commander.panel as panel_module
    from PySide6.QtCore import QProcess
    from PySide6.QtGui import QDesktopServices
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    file = tmp_path / "literal $(no-shell) {path}.txt"; file.write_text("text")
    executable = tmp_path / "Viewer.app"; executable.mkdir()
    other = tmp_path / "Other.app"; other.mkdir()
    monkeypatch.setattr(associations, "applications_for_file", lambda path: [Application(str(other), "Other")])
    monkeypatch.setattr(panel_module, "applications_for_file", lambda path: [Application(str(other), "Other")])
    launched = []; system = []
    monkeypatch.setattr(QProcess, "startDetached", lambda program, args: (launched.append((program, args)) or True, 1))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: system.append(url.toLocalFile()) or True)
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    panel = window.left
    panel.tree.setCurrentIndex(panel.model.index_for_name(file.name))
    window.associations.set_default(".txt", str(executable))
    panel.open_current()
    import sys
    if sys.platform == "darwin":
        assert launched == [("/usr/bin/open", ["-a", str(executable), str(file)])]
    else:
        assert launched == [(str(executable), [str(file)])]
    menu = panel.build_file_menu(); settle(app, window)
    submenu = next(action.menu() for action in menu.actions() if action.menu() is not None)
    assert any(a.text() == "Other" for a in submenu.actions())
    ids = {a.objectName() for a in menu.actions()}
    assert {"command_clipboard_copy", "command_clipboard_cut", "command_clipboard_paste", "command_properties", "command_delete_permanent", "command_multi_rename"} <= ids
    menu.deleteLater(); app.processEvents()
    dialog = window.show_open_with([str(file)]); settle(app, window)
    assert any(dialog.apps.item(i).data(Qt.ItemDataRole.UserRole) == str(other) for i in range(dialog.apps.count()))
    dialog.reset(); panel.open_current()
    assert [Path(path) for path in system] == [file]
    dialog.reject()
    window.associations.set_default(".txt", str(executable))
    window.close(); app.processEvents()
    restored = Commander(str(tmp_path), str(tmp_path)); settle(app, restored)
    assert restored.associations.custom[".txt"] == str(executable)
    restored.close(); app.processEvents()


def test_application_package_opens_normally_and_ctrl_pgdown_browses_it(app, tmp_path, monkeypatch):
    import sys
    from PySide6.QtGui import QDesktopServices
    if sys.platform != "darwin":
        pytest.skip("macOS application bundle behavior")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    bundle = tmp_path / "Example.app"; bundle.mkdir(); (bundle / "Contents").mkdir()
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    panel = window.left
    panel.tree.setCurrentIndex(panel.model.index_for_name(bundle.name)); panel.open_current()
    assert opened == [str(bundle)] and panel.path == str(tmp_path)
    panel.enter_directory(); settle(app, window)
    assert panel.path == str(bundle)
    window.close(); app.processEvents()


def test_languages_compact_toolbar_and_panel_center_reset(app, tmp_path):
    from soovee_commander.i18n import tr, current_language
    from PySide6.QtWidgets import QPushButton, QLabel
    from PySide6.QtCore import QPoint
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "StereoCommander", "StereoCommander")
    settings.setValue("language", "cs"); settings.sync()
    (tmp_path / "one.txt").touch()
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    assert current_language() == "cs"
    assert window.bottom_buttons[0].text() == "F2  " + tr("Rename")
    assert window.command_menu.actions()[0].text() == tr("File")
    assert window.left.model.headerData(0, Qt.Orientation.Horizontal) == tr("Name")
    assert window.left.column_settings_key != window.right.column_settings_key
    custom = window.left.column_layout()
    next(column for column in custom if column["id"] == "name")["label"] = "File"
    window.left.apply_columns(custom)
    assert window.left.model.headerData(0, Qt.Orientation.Horizontal) == "File"
    assert window.findChild(QPushButton, "centerPanelsButton") is None
    assert not any(label.objectName() == "brand" for label in window.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    splitter = window.panel_splitter
    splitter.setSizes([200, 900]); splitter.balanced = False
    assert abs(splitter.sizes()[0] - splitter.sizes()[1]) > 100
    window.commands.actions["center_panels"].trigger(); app.processEvents()
    assert abs(splitter.sizes()[0] - splitter.sizes()[1]) <= 1
    window.resize(1800, 950); app.processEvents()
    assert abs(splitter.sizes()[0] - splitter.sizes()[1]) <= 1
    splitter.setSizes([250, 950]); splitter.balanced = False
    QTest.mouseDClick(splitter.handle(1), Qt.MouseButton.LeftButton); app.processEvents()
    assert abs(splitter.sizes()[0] - splitter.sizes()[1]) <= 1
    handle = splitter.handle(1)
    start = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(handle, start + QPoint(90, 0), delay=20)
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=start + QPoint(90, 0))
    app.processEvents()
    assert not splitter.balanced
    assert abs(splitter.sizes()[0] - splitter.sizes()[1]) > 30
    QTest.mouseDClick(splitter.handle(1), Qt.MouseButton.LeftButton); app.processEvents()
    assert splitter.balanced
    assert abs(splitter.sizes()[0] - splitter.sizes()[1]) <= 1
    window.change_language("en")
    assert current_language() == "en"
    assert window.command_menu.actions()[0].text() == "File"
    assert window.bottom_buttons[0].text() == "F2  Rename"
    window.close(); app.processEvents()
    english = Commander(str(tmp_path), str(tmp_path)); english.show(); settle(app, english)
    assert current_language() == "en"
    assert english.command_menu.actions()[0].text() == "File"
    assert english.bottom_buttons[0].text() == "F2  Rename"
    english.close(); app.processEvents()


def test_directory_selection_totals_properties_details_and_native_drag(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from soovee_commander import panel as panel_module
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir()
    for name, size in [('one', 123), ('two', 456)]:
        (source / name).mkdir()
        (source / name / 'data').write_bytes(b'x' * size)
    window = Commander(str(source), str(target)); window.show(); settle(app, window)
    panel = window.left
    panel.tree.selectAll()
    assert 'unknown' in panel.footer.text()
    window.calculate_sizes(); settle(app, window)
    assert '579 B' in panel.footer.text()
    properties = window.show_properties(); settle(app, window)
    assert '579' in properties.findChild(__import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel, 'propertiesTotal').text()
    properties.close()
    window.copy_details(); settle(app, window)
    assert 'Total\t579' in QApplication.clipboard().text()
    captured = []
    class Drag:
        def __init__(self, parent): pass
        def setMimeData(self, mime): captured.extend(url.toLocalFile() for url in mime.urls())
        def exec(self, *args): pass
    monkeypatch.setattr(panel_module, 'QDrag', Drag)
    assert panel.model.flags(panel.model.index_for_name('one')) & Qt.ItemFlag.ItemIsDragEnabled
    panel.tree.startDrag(Qt.DropAction.CopyAction)
    assert {Path(path) for path in captured} == {source / 'one', source / 'two'}
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr('soovee_commander.dialog_kit.confirm', lambda *a, **k: True)
    window.drop_paths(window.right, captured, str(target)); settle(app, window)
    assert (target / 'two' / 'data').stat().st_size == 456
    window.close(); app.processEvents()
    QApplication.clipboard().clear()


def test_named_connection_url_input_and_profile_rename(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    dialog = ConnectDialog(window)
    dialog.profile_name.setText('Home NAS')
    dialog.host.setText('ftp://user:secret@127.0.0.1:2121/Download')
    connection = dialog.connection()
    assert connection.protocol == 'FTP' and connection.port == 2121 and connection.name == 'Home NAS'
    assert connection.password == 'secret' and dialog.path.text() == '/Download'
    dialog.save_profile(connection)
    restored = ConnectDialog(window)
    restored.profile.setCurrentIndex(1); restored.load_profile(1)
    restored.profile_name.setText('Living room')
    restored.save_profile(restored.connection())
    import json
    profiles = json.loads(window.settings.value('connections'))
    assert len(profiles) == 1 and profiles[0]['name'] == 'Living room'
    assert 'secret' not in window.settings.value('connections')
    window.close(); app.processEvents()


def test_search_results_sort_numerically_and_open_correct_result(app, tmp_path):
    from soovee_commander.tool_dialogs import SearchDialog
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    for name, size in [('large', 100), ('small', 9)]:
        (tmp_path / name).write_bytes(b'x' * size)
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    dialog = window.open_tool(SearchDialog)
    dialog.pattern.setText('large;small')
    dialog.start_search(); settle(app, window)
    dialog.results.sortByColumn(1, Qt.SortOrder.AscendingOrder); app.processEvents()
    assert dialog.results.model().index(0, 0).data() == 'small'
    dialog.results.setCurrentIndex(dialog.results.model().index(0, 0))
    dialog.open_result(); settle(app, window)
    assert window.left.current_entry().name == 'small'
    window.close(); app.processEvents()


def test_archive_context_extracts_into_named_folder(app, tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir()
    with zipfile.ZipFile(source / 'bundle.zip', 'w') as archive:
        archive.writestr('inside/data.txt', 'only archive contents')
    window = Commander(str(source), str(target)); settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name('bundle.zip'))
    menu = window.left.build_file_menu()
    assert window.commands.actions['extract'] in menu.actions()
    monkeypatch.setattr(QDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    window.extract_archives(); settle(app, window)
    assert (target / 'bundle' / 'inside' / 'data.txt').read_text() == 'only archive contents'
    window.close(); app.processEvents()


def test_typed_address_enter_and_relative_remote_folder(app, tmp_path, monkeypatch):
    from soovee_commander.providers import RemoteProvider
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    (tmp_path / 'folder with spaces').mkdir()
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    address = window.left.address
    address.setFocus(); address.setText(str(tmp_path / 'folder with spaces'))
    QTest.keyClick(address, Qt.Key.Key_Return); settle(app, window)
    assert window.left.path == str(tmp_path / 'folder with spaces')
    captured = []
    monkeypatch.setattr(window, 'open_remote_url', lambda panel, text: captured.append(text))
    address.setFocus(); address.setText('192.168.68.64/Download')
    QTest.keyClick(address, Qt.Key.Key_Return); app.processEvents()
    assert captured == ['ftp://192.168.68.64/Download']
    remote = RemoteProvider(Connection('FTP', 'example.invalid', 21, 'test'))
    monkeypatch.setattr(remote, 'list', lambda path: [])
    window.left.navigate(remote, '/Download'); settle(app, window)
    window.left.navigate_text('subfolder'); settle(app, window)
    assert window.left.path == '/Download/subfolder'
    window.left.navigate_text('..'); settle(app, window)
    assert window.left.path == '/Download'
    window.close(); app.processEvents()


def test_transfer_dialog_reports_resume_skip_error_and_exact_progress(app, tmp_path):
    from threading import Event
    from soovee_commander.transfer_ui import TransferDialog
    dialog = TransferDialog(None, 'Copy', Event())
    dialog.update_event(dict(event='plan', bytes=1000, files=3))
    dialog.update_event(dict(event='file', source='/source/video', destination='/target/video', size=600))
    dialog.update_event(dict(event='resume', offset=200))
    dialog.update_event(dict(event='advance', bytes=100))
    assert dialog.file_bar.value() == 500 and dialog.total_bar.value() == 300
    dialog.update_event(dict(event='file_done', path='/target/video', size=600, transferred=400))
    dialog.update_event(dict(event='skip', path='/target/folder', size=400, files=2))
    assert dialog.done_files == 3 and dialog.total_bar.value() == 1000 and dialog.transferred == 400
    assert '/source/video' in dialog.log.toPlainText() and '/target/video' in dialog.log.toPlainText()
    dialog.update_event(dict(event='plan', bytes=1000, files=1))
    dialog.finish('Disk full', True)
    assert dialog.phase.text() == 'Disk full' and dialog.total_bar.value() == 0
    dialog.close(); app.processEvents()


def test_tabs_move_between_panels_with_history_selection_and_last_tab_replacement(app, tmp_path):
    from soovee_commander.providers import RemoteProvider
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    root, target = tmp_path / 'source', tmp_path / 'destination'
    root.mkdir(); target.mkdir(); (root / 'nested').mkdir(); (root / 'nested' / 'keep.txt').write_text('keep')
    window = Commander(str(root), str(target)); window.show(); settle(app, window)
    source, other = window.left, window.right
    source.tree.setCurrentIndex(source.model.index_for_name('nested'))
    source.navigate(source.provider, str(root / 'nested')); settle(app, window)
    source.filter.setText('keep'); source.apply_filter()
    source.tree.setCurrentIndex(source.model.index_for_name('keep.txt'))
    source._current.label = 'Work'; source._current.locked = True
    original = source._current
    provider = original.provider
    assert source.move_tab_to(original, other, 0)
    settle(app, window)
    assert other._current is original and other.provider is provider
    assert other.path == str(root / 'nested') and other.filter.text() == 'keep'
    assert other.current_entry().name == 'keep.txt' and other.selected()[0].name == 'keep.txt'
    assert original.label == 'Work' and original.locked and len(original.history) == 1
    assert source.tabbar.count() == 1 and original not in source.closed_tabs
    assert window.active is other
    original.locked = False
    other.back(); settle(app, window)
    assert other.path == str(root) and other.current_entry().name == 'nested'
    remote = RemoteProvider(Connection('FTP', 'example.invalid', 21, 'user', 'not-in-mime'))
    remote.list = lambda path: [Entry('remote.txt', False, 7)]
    other.new_tab(remote, '/Download'); settle(app, window)
    remote_tab = other._current
    assert other.move_tab_to(remote_tab, source)
    assert source.provider is remote and source.path == '/Download'
    source.new_tab(); settle(app, window)
    moved_index = next(i for i in range(source.tabbar.count()) if source.tabbar.tabData(i) is remote_tab)
    moved_close = source.tabbar.tabButton(moved_index, source.tabbar.ButtonPosition.RightSide)
    moved_close.click()
    assert remote_tab not in source.tab_states and remote_tab not in other.tab_states
    window.close(); app.processEvents()


def test_cross_pane_tab_drag_drop_gesture_and_cancel_preserve_state(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from soovee_commander import tabbar as module
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    source, destination = window.left.tabbar, window.right.tabbar
    state = window.left._current
    transfers = []
    class Event:
        def __init__(self, drag): self.drag = drag; self.accepted = False
        def source(self): return source
        def mimeData(self): return self.drag.mime
        def position(self): return QPointF(10, 10)
        def setDropAction(self, action): self.action = action
        def accept(self): self.accepted = True
        def ignore(self): self.accepted = False
    class Drag:
        def __init__(self, parent): pass
        def setPixmap(self, image): pass
        def setMimeData(self, mime):
            self.mime = mime
            assert mime.formats() == [module.MIME] and not mime.hasUrls() and not mime.hasText()
        def exec(self, action):
            event = Event(self)
            destination.dragEnterEvent(event)
            assert event.accepted
            destination.dropEvent(event)
            assert event.accepted
            transfers.append(state)
            return action
    monkeypatch.setattr(module, 'QDrag', Drag)
    start = source.tabRect(0).center()
    QTest.mousePress(source, Qt.MouseButton.LeftButton, pos=start)
    outside = QPointF(source.width() + 30, start.y())
    event = QMouseEvent(QEvent.Type.MouseMove, outside, QPointF(source.mapToGlobal(outside.toPoint())), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(source, event)
    settle(app, window)
    assert transfers == [state] and window.right._current is state
    assert source._drag_token is None
    # A drag dropped nowhere must leave ownership and active state intact.
    monkeypatch.setattr(Drag, 'exec', lambda self, action: Qt.DropAction.IgnoreAction)
    bar = window.right.tabbar
    before = list(window.right.tab_states)
    start = bar.tabRect(bar.currentIndex()).center()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    outside = QPointF(-30, start.y())
    event = QMouseEvent(QEvent.Type.MouseMove, outside, QPointF(bar.mapToGlobal(outside.toPoint())), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(bar, event)
    assert window.right.tab_states == before and window.right._current is state
    window.close(); app.processEvents()


@pytest.mark.parametrize('theme', ['soovee', 'light', 'slate', 'dark'])
def test_tab_crosses_stay_inside_tabs_and_transfer_labels_are_outside_bars(app, tmp_path, theme):
    from threading import Event
    from soovee_commander.transfer_ui import TransferDialog
    from soovee_commander.tabbar import TabCloseButton
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    window.change_theme(theme)
    window.left.new_tab(); settle(app, window)
    bar = window.left.tabbar
    bar.setTabText(0, 'Long tab name that should stay within its bounds')
    app.processEvents()
    for index in range(bar.count()):
        button = bar.tabButton(index, bar.ButtonPosition.RightSide)
        assert isinstance(button, TabCloseButton)
        assert bar.tabRect(index).contains(button.geometry()), (theme, bar.tabRect(index), button.geometry())
        assert button.width() == button.height() == 18
    dialog = TransferDialog(window, 'Copy', Event())
    dialog.show(); app.processEvents()
    for value in [0, 25, 50, 100]:
        dialog.update_event(dict(event='plan', bytes=100, files=1))
        dialog.update_event(dict(event='file', source='/a', destination='/b', size=100))
        dialog.update_event(dict(event='advance', bytes=value))
        assert not dialog.file_bar.isTextVisible() and not dialog.total_bar.isTextVisible()
        assert f'{value}%' in dialog.file_label.text() and f'{value}%' in dialog.total_label.text()
        assert dialog.file_label.geometry().bottom() < dialog.file_bar.geometry().top()
        assert dialog.total_label.geometry().bottom() < dialog.total_bar.geometry().top()
    dialog.close(); window.close(); app.processEvents()


def test_moving_inactive_or_loading_tabs_and_panel_limit(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    left, right = window.left, window.right
    first = left._current
    second = left.new_tab(); settle(app, window)
    first.loading = True
    assert not left.move_tab_to(first, right)
    assert first in left.tab_states and right.tabbar.count() == 1
    first.loading = False
    assert left.move_tab_to(first, right)
    assert left._current is second
    assert right._current is first
    before = list(right.tab_states)
    right.MAX_TABS = right.tabbar.count()
    assert not left.move_tab_to(second, right)
    assert right.tab_states == before and left._current is second
    assert window.windowTitle() == 'Soovee Commander' and not window.windowIcon().isNull()
    window.close(); app.processEvents()


def test_devices_dialog_is_opt_in_and_qr_roundtrip(app, tmp_path):
    from soovee_commander.lan_ui import DevicesDialog, qr_image, read_qr
    from soovee_commander.lan_protocol import invitation
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    dialog = window.show_devices()
    assert dialog.service is None and dialog.code.text() == 'Transfers are disabled'
    text = invitation('127.0.0.1', 47123, '12345678')
    image = tmp_path / 'pairing.png'
    assert qr_image(text).save(str(image))
    assert read_qr(image) == text
    dialog.use_invitation(text)
    assert dialog.remote_host.text() == '127.0.0.1' and dialog.remote_port.text() == '47123'
    assert dialog.remote_code.text() == '12345678'
    dialog.close()
    assert dialog.service is None and window.show_devices() is dialog
    window.close(); app.processEvents()


def test_devices_open_generates_code_and_qr_on_a_valid_local_address(app, tmp_path, monkeypatch):
    from soovee_commander.lan_ui import DevicesDialog, read_qr
    from PySide6.QtNetwork import QHostAddress, QNetworkInterface
    monkeypatch.setattr(QNetworkInterface, 'allAddresses', lambda: [QHostAddress('100.64.1.2'), QHostAddress('169.254.1.2'), QHostAddress('192.168.1.8')])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    dialog = DevicesDialog(window, tmp_path / 'transfer-state')
    dialog.show(); app.processEvents()
    assert dialog.service is not None
    assert dialog.address.currentText() == '192.168.1.8'
    assert len(dialog.code.text().replace(' ', '')) == 8
    image = tmp_path / 'native-qr.png'; dialog.qr.pixmap().save(str(image))
    assert read_qr(image) == dialog.service.pairing_link('192.168.1.8')
    dialog.shutdown(); assert dialog.renew.isEnabled()
    dialog.close(); window.close()


def test_rename_preview_copy_ranges_counter_conflicts_and_presets(app, tmp_path):
    from soovee_commander.tool_dialogs import MultiRenameDialog
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    for name in ('Photo_001.jpg', 'Photo_002.jpg', 'occupied.jpg'): (tmp_path / name).write_bytes(b'test')
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    panel = window.left
    selection = panel.tree.selectionModel()
    from PySide6.QtCore import QItemSelectionModel
    for name in ('Photo_001.jpg', 'Photo_002.jpg'):
        index = panel.model.index_for_name(name)
        selection.select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    dialog = MultiRenameDialog(window); dialog.show(); app.processEvents()
    dialog.copy_original(); assert QApplication.clipboard().text() == 'Photo_001.jpg'
    dialog.use_original(); assert dialog.mask.text() == 'Photo_001'
    dialog.mask.setText('[N1-5]_[C]'); dialog.digits.setValue(3); dialog.step.setValue(2); dialog.start.setValue(10)
    assert dialog.names == ['Photo_010.jpg', 'Photo_012.jpg']
    dialog.presets.setCurrentText('Test numbering'); dialog.save_preset(); dialog.reset()
    dialog.presets.setCurrentText('Test numbering'); dialog.load_preset()
    assert dialog.step.value() == 2 and dialog.names == ['Photo_010.jpg', 'Photo_012.jpg']
    dialog.mask.setText('occupied')
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.close(); window.close()


def test_panel_modes_sizes_thumbnails_and_selection_persist(app, tmp_path):
    from PySide6.QtGui import QImage, QColor
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    image = QImage(320, 240, QImage.Format.Format_RGB32); image.fill(QColor('#20aaaa'))
    assert image.save(str(tmp_path / 'photo.png'))
    (tmp_path / 'folder').mkdir()
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    panel = window.left
    assert panel.appearance.mode == 'details' and panel.active_view() is panel.tree
    panel.tree.setCurrentIndex(panel.model.index_for_name('photo.png'))
    for mode in ('compact', 'icons', 'thumbnails'):
        panel.appearance.apply(mode, 28, 40); app.processEvents()
        assert panel.active_view() is panel.tiles
        assert panel.action_entries()[0].name == 'photo.png'
    deadline = time.monotonic() + 5
    while 'photo.png' not in panel.model.thumbnails and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    settle(app, window)
    assert 'photo.png' in panel.model.thumbnails
    panel.tiles.setFocus()
    photo = panel.model.index_for_name('photo.png'); folder = panel.model.index_for_name('folder')
    QTest.mouseClick(panel.tiles.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, panel.tiles.visualRect(photo).center())
    QTest.mouseClick(panel.tiles.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, panel.tiles.visualRect(folder).center())
    assert {e.name for e in panel.selected()} == {'photo.png', 'folder'}
    panel.tiles.setCurrentIndex(folder)
    QTest.keyClick(panel.tiles, Qt.Key.Key_Return); settle(app, window)
    assert Path(panel.path) == tmp_path / 'folder'
    panel.parent(); settle(app, window)
    assert panel.model.entry(panel.tree.currentIndex().row()).name == 'folder'
    assert window.settings.value('view_mode_left') == 'thumbnails'
    assert window.settings.value('row_height_left', type=int) == 40
    panel.appearance.apply('details', 16, 0); app.processEvents()
    assert panel.active_view() is panel.tree and not panel.model.thumbnails
    assert not panel.tree.styleSheet()
    window.close()


def test_panel_appearance_preview_apply_cancel_and_both_panels(app, tmp_path):
    from soovee_commander.appearance_dialog import PanelAppearanceDialog
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'prefs'))
    window=Commander(str(tmp_path),str(tmp_path));window.show();settle(app,window)
    dialog=PanelAppearanceDialog(window.left.appearance);dialog.show();app.processEvents()
    dialog.modes.button(2).click();dialog.icon.setValue(96);dialog.lines.setValue(4)
    assert window.left.appearance.mode=='details'
    assert dialog.preview.currentWidget() is dialog.tiles and dialog.tiles.iconSize().width()==96
    dialog.both.setChecked(True)
    apply=dialog.buttons.button(QDialogButtonBox.StandardButton.Apply)
    assert apply.isEnabled();apply.click();app.processEvents()
    assert dialog.isVisible() and not apply.isEnabled()
    assert window.left.appearance.mode==window.right.appearance.mode=='icons'
    assert window.left.tiles.iconSize().width()==window.right.tiles.iconSize().width()==96
    dialog.icon.setValue(160);dialog.reject();app.processEvents()
    assert window.left.appearance.icon_size==96 and window.left.appearance.label_lines==4
    reopened=PanelAppearanceDialog(window.left.appearance)
    assert reopened.icon.value()==96 and reopened.lines.value()==4
    reopened.close();window.close()


@pytest.mark.parametrize('size',[16,48,96,192])
@pytest.mark.parametrize('theme',['soovee_light','soovee'])
def test_icon_and_label_are_both_painted_inside_the_tile(app,tmp_path,size,theme):
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'prefs'))
    (tmp_path/'Documents and reports').mkdir();(tmp_path/'notes.txt').write_text('test')
    window=Commander(str(tmp_path),str(tmp_path));window.resize(1400,950);window.change_theme(theme);window.show();settle(app,window)
    panel=window.left;panel.appearance.apply('icons',size,0,label_lines=3)
    panel.tree.selectionModel().clearSelection();app.processEvents()
    view=panel.tiles;index=panel.model.index_for_name('Documents and reports')
    bounds=view.visualRect(index);icon,text=view.itemDelegate().regions(bounds)
    assert bounds.contains(icon) and bounds.contains(text) and icon.bottom()<text.top()
    image=view.viewport().grab().toImage();ratio=image.devicePixelRatio()
    from PySide6.QtCore import QRect
    crop=image.copy(QRect(round(text.x()*ratio),round(text.y()*ratio),round(text.width()*ratio),round(text.height()*ratio)))
    colors={crop.pixel(x,y) for y in range(crop.height()) for x in range(crop.width())}
    # Windows offscreen fonts may render without antialiasing: text and background
    # are then exactly two colors. Check actual ink coverage, not gradient count.
    background=crop.pixel(0,0)
    ink=sum(crop.pixel(x,y)!=background for y in range(crop.height()) for x in range(crop.width()))
    assert len(colors)>=2 and ink>=20,'The filename area is blank'
    lower=image.copy(QRect(round(icon.x()*ratio),round((icon.y()+icon.height()//2)*ratio),round(icon.width()*ratio),max(1,round(icon.height()/2*ratio))))
    assert len({lower.pixel(x,y) for y in range(lower.height()) for x in range(lower.width())})>3,'The bottom half of the folder icon is clipped'
    window.close();app.processEvents()


def test_discovered_device_needs_only_code_and_hides_manual_address(app,tmp_path,monkeypatch):
    from soovee_commander.lan_ui import DevicesDialog
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'prefs'))
    window=Commander(str(tmp_path),str(tmp_path));settle(app,window)
    monkeypatch.setattr(window,'error',lambda message:pytest.fail(message))
    dialog=DevicesDialog(window,tmp_path/'state');dialog.start();dialog.show();app.processEvents()
    dialog.found([dict(id='a'*32,name='Living room TV',host='192.168.1.52',port=47123,kind='tv')])
    assert dialog.tabs.currentIndex()==0 and dialog.nearby.count()==1
    assert dialog.remote_host.text()=='192.168.1.52' and dialog.remote_port.text()=='47123'
    assert not dialog.remote_host.isVisible() and not dialog.remote_port.isVisible()
    assert dialog.remote_code.isVisible() and dialog.remote_code.isEnabled()
    dialog.shutdown();dialog.close();settle(app,window);window.close()


def test_real_ui_pairing_qr_receive_approval_and_transfer(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from soovee_commander.lan import TransferService
    from soovee_commander.lan_ui import DevicesDialog, read_qr
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    source, destination = tmp_path / 'source', tmp_path / 'received'
    source.mkdir(); destination.mkdir()
    (source / 'send.txt').write_bytes(b'real GUI transfer' * 50000)
    a, b = Commander(str(source), str(source)), Commander(str(destination), str(destination))
    settle(app, a); settle(app, b)
    left, right = DevicesDialog(a, tmp_path / 'a-state'), DevicesDialog(b, tmp_path / 'b-state')
    a.devices_dialog, b.devices_dialog = left, right
    a.preview_windows.append(left); b.preview_windows.append(right)
    left.destination.setText(str(source)); right.destination.setText(str(destination))
    left.name.setText('UI sender'); right.name.setText('UI receiver')
    original_start = TransferService.start
    monkeypatch.setattr(TransferService, 'start', lambda self, host='127.0.0.1', port=0: original_start(self, '127.0.0.1', 0))
    errors = []
    a.error = errors.append; b.error = errors.append
    left.start(); right.start()
    right.address.setCurrentText('127.0.0.1')
    qr = tmp_path / 'qr.png'
    from soovee_commander.lan_ui import qr_image
    qr_image(right.service.pairing_link('127.0.0.1')).save(str(qr))
    left.use_invitation(read_qr(qr))
    approvals = []
    timer = QTimer()
    def consent():
        for dialog in (left, right):
            for box, request in list(dialog.approvals):
                approvals.append(request.kind)
                box.ok.click()
    timer.timeout.connect(consent); timer.start(10)
    left.pair_device(); settle(app, a)
    assert not errors and left.devices.count() == right.devices.count() == 1
    assert approvals.count('pair') == 2
    a.left.tree.setCurrentIndex(a.left.model.index_for_name('send.txt'))
    a.activate(a.left)
    left.devices.setCurrentRow(0)
    left.send_selection(); settle(app, a)
    deadline = time.monotonic() + 3
    while right.service.offers and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not errors and 'offer' in approvals
    bundles = list(destination.glob('Soovee-*'))
    assert len(bundles) == 1 and (bundles[0] / 'send.txt').read_bytes() == (source / 'send.txt').read_bytes()
    assert right.receive_progress.value() == 1000
    assert '12345678' not in right.log.toPlainText()
    # The folder chosen in the pairing approval is shared at once.
    assert [share['name'] for share in right.service.shares.available(left.service.store.id)] == ['received']
    left.refresh_devices()
    assert left.share_peer.currentData() == right.service.store.id
    left.open_selected_device(); settle(app, a)
    from soovee_commander.device_files import DeviceProvider
    assert isinstance(a.right.provider, DeviceProvider)
    assert [entry.name for entry in a.right.model.entries] == ['received']
    a.right.navigate(a.right.provider, '/received'); settle(app, a)
    assert a.right.model.entries
    assert a.right.location().startswith('soovee-device://')
    timer.stop()
    left.shutdown(); right.shutdown()
    settle(app, a); settle(app, b)
    a.close(); b.close(); app.processEvents()


def test_about_version_licenses_diagnostics_and_native_menu_role(app, tmp_path):
    import json
    from PySide6.QtGui import QAction
    from soovee_commander import __version__
    from soovee_commander.about import diagnostics
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    assert window.commands.actions['about'].menuRole() == QAction.MenuRole.AboutRole
    dialog = window.show_about()
    assert __version__ in '\n'.join(label.text() for label in dialog.findChildren(__import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel))
    assert len(dialog.components) >= 15
    for index in range(len(dialog.components)):
        dialog.component_list.setCurrentRow(index)
        assert dialog.notice.toPlainText()
    assert 'secret' not in json.dumps(diagnostics()).lower()
    assert diagnostics()['version'] == __version__
    dialog.close(); window.close(); app.processEvents()


def test_live_language_change_preserves_files_tabs_and_unsaved_editor(app, tmp_path):
    from PySide6.QtWidgets import QLineEdit, QPushButton
    from soovee_commander.editor import TextEditor
    from soovee_commander.providers import LocalProvider
    from soovee_commander.i18n import current_language
    from soovee_commander.lan_ui import DevicesDialog
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    (tmp_path / 'Copy').write_text('content')
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    window.change_language('en')
    editor = TextEditor(window, LocalProvider(), str(tmp_path / 'Copy'), b'content')
    editor.text.selectAll()
    editor.text.insertPlainText('Copy\nunsaved text')
    devices = DevicesDialog(window, tmp_path / 'lan-state')
    window.devices_dialog = devices
    window.preview_windows.extend([editor, devices])
    about = window.show_about()
    path = window.left.path
    tab = window.left.tabbar.tabText(0)
    field = QLineEdit('Copy', window)
    for language, rename, menu, heading in [('cs', 'F2  Přejmenovat', 'Soubor', 'Název'), ('en', 'F2  Rename', 'File', 'Name')]:
        window.change_language(language); app.processEvents()
        assert current_language() == language and window.language == language
        assert window.bottom_buttons[0].text() == rename
        assert window.command_menu.actions()[0].text() == menu
        assert window.left.model.headerData(0, Qt.Orientation.Horizontal) == heading
        assert field.text() == 'Copy'
        assert editor.text.toPlainText() == 'Copy\nunsaved text'
        assert editor.text.document().isModified()
        assert window.left.path == path and window.left.tabbar.tabText(0) == tab
        assert window.left.model.index_for_name('Copy').isValid()
        assert devices.open_device_button.text() == ('Otevřít zařízení jako disk' if language == 'cs' else 'Open device as a disk')
        assert about.tabs.tabText(2) == ('Archivy' if language == 'cs' else 'Archives')
    editor.text.document().setModified(False)
    editor.close(); devices.close(); about.close(); window.close(); app.processEvents()


def test_editor_search_replace_unicode_case_whole_words_and_single_undo(app, tmp_path):
    from soovee_commander.editor import TextEditor
    from soovee_commander.providers import LocalProvider
    from PySide6.QtGui import QTextCursor
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    original = '🌍 Cat cat catch\nžluť žluťoučký žluť\n'
    editor = TextEditor(window, LocalProvider(), str(tmp_path / 'test.py'), original.encode())
    editor.show(); editor.activateWindow(); app.processEvents()
    search = editor.search
    QTest.keyClick(editor.text, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert search.isVisible()
    search.open(True)
    search.query.setText('cat'); search.case.setChecked(True); search.words.setChecked(True)
    search.replacement.setText('dog'); search.replace_all()
    assert editor.text.toPlainText() == original.replace('Cat cat catch', 'Cat dog catch')
    editor.text.undo(); assert editor.text.toPlainText() == original
    search.query.setText('žluť'); search.replacement.setText('test'); search.replace_all()
    assert editor.text.toPlainText() == original.replace('žluť žluťoučký žluť', 'test žluťoučký test')
    editor.text.undo()
    search.words.setChecked(False); search.case.setChecked(False)
    search.query.setText('cat'); search.replacement.setText('x'); search.replace_all()
    assert '🌍 x x xch' in editor.text.toPlainText()
    editor.text.undo()
    search.regex.setChecked(True); search.query.setText('['); search.replace_all()
    assert editor.text.toPlainText() == original and 'Invalid' in search.message.text()
    search.query.setText('(?=cat)'); search.replace_all()
    assert editor.text.toPlainText() == original
    editor.text.moveCursor(QTextCursor.MoveOperation.Start)
    search.query.setText(r'c.t'); assert search.find()
    assert editor.text.textCursor().selectedText().lower() == 'cat'
    editor.text.document().setModified(False); editor.close(); window.close(); app.processEvents()


def test_editor_encoding_save_as_and_close_after_success(app, tmp_path, monkeypatch):
    from soovee_commander.editor import TextEditor
    from soovee_commander.providers import LocalProvider
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    path = tmp_path / 'old.txt'; path.write_bytes('Příliš\r\n'.encode('cp1250'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    errors = []; window.error = errors.append
    editor = TextEditor(window, LocalProvider(), str(path), path.read_bytes(), encoding='cp1250')
    assert editor.text.toPlainText() == 'Příliš\n'
    editor.encoding_combo.setCurrentIndex(editor.encoding_combo.findData('utf-16-le-bom'))
    editor.text.moveCursor(__import__('PySide6.QtGui', fromlist=['QTextCursor']).QTextCursor.MoveOperation.End)
    editor.text.insertPlainText('🌍\n')
    new = tmp_path / 'new.txt'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(new), ''))
    editor.save_as(); settle(app, window)
    assert new.read_bytes() == 'Příliš\r\n🌍\r\n'.encode('utf-16')
    assert path.read_bytes() == 'Příliš\r\n'.encode('cp1250')
    editor.encoding_combo.setCurrentIndex(editor.encoding_combo.findData('cp1250'))
    editor.save(); assert errors and new.read_bytes().startswith(b'\xff\xfe')
    editor.encoding_combo.setCurrentIndex(editor.encoding_combo.findData('utf-8'))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Save)
    editor.show(); editor.close(); settle(app, window)
    assert new.read_bytes() == 'Příliš\r\n🌍\r\n'.encode()
    window.close(); app.processEvents()


def test_viewer_text_binary_pages_partial_and_image_zoom(app, tmp_path):
    from soovee_commander.viewer import FileViewer, HEX_PAGE
    from PySide6.QtGui import QImage
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    data = b'\0' * (HEX_PAGE + 32)
    viewer = FileViewer(window, 'bytes.bin', len(data) + 100, data)
    assert viewer.tabs.currentIndex() == 1 and viewer.hex_page.maximum() == 2
    viewer.hex_page.setValue(2)
    assert viewer.hex.toPlainText().startswith(f'{HEX_PAGE:08X}')
    assert viewer.text.isReadOnly() and viewer.hex.isReadOnly()
    image_path = tmp_path / 'sample.png'
    image = QImage(80, 40, QImage.Format.Format_RGB32); image.fill(Qt.GlobalColor.red); image.save(str(image_path))
    picture = FileViewer(window, 'sample.png', image_path.stat().st_size, image_path.read_bytes())
    picture.show(); app.processEvents()
    assert picture.tabs.currentIndex() == 2 and picture.image is not None
    picture.image_zoom(1.0)
    assert picture.image_label.pixmap().size().width() == 80
    text = FileViewer(window, 'text.txt', 5, b'hello')
    assert text.tabs.currentIndex() == 0 and text.text.toPlainText() == 'hello'
    before = text.text.fontMetrics().height()
    text.text.zoom(2)
    assert text.text.fontMetrics().height() > before
    text.find_text(); text.search.query.setText('hello'); assert text.search.find()
    for dialog in (viewer, picture, text):
        dialog.close()
    window.close(); app.processEvents()


@pytest.mark.parametrize('transport', ['ftp_server', 'tls_server', 'sftp_server'])
def test_integrated_editor_real_remote_save_and_conflict(app, tmp_path, request, transport, monkeypatch):
    import ssl
    from soovee_commander.editor import TextEditor
    from soovee_commander.operations import preview
    remote, root, *extra = request.getfixturevalue(transport)
    if transport == 'tls_server':
        context_factory = ssl.create_default_context
        monkeypatch.setattr('soovee_commander.providers.ssl.create_default_context', lambda: context_factory(cafile=str(extra[0])))
    original = b'first\r\n'
    (root / 'edit.txt').write_bytes(original)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    errors = []; window.error = errors.append
    editor = TextEditor(window, remote, '/edit.txt', preview(remote, '/edit.txt'))
    editor.text.selectAll(); editor.text.insertPlainText('changed\n')
    editor.save(); settle(app, window)
    assert (root / 'edit.txt').read_bytes() == b'changed\r\n' and not errors
    editor.text.selectAll(); editor.text.insertPlainText('mine\n')
    (root / 'edit.txt').write_bytes(b'other client')
    editor.save(); settle(app, window)
    assert errors and (root / 'edit.txt').read_bytes() == b'other client'
    assert editor.text.document().isModified()
    editor.text.document().setModified(False); editor.close(); window.close(); app.processEvents()


def test_update_progress_measured_bytes_phases_and_explicit_finish(app):
    import json
    from soovee_commander.update_ui import UpdateProgress
    dialog = UpdateProgress()
    dialog.show(); app.processEvents()
    dialog.update_progress('@update:' + json.dumps(dict(phase='Verifying update package', current=512, total=1024)))
    assert dialog.bar.maximum() == 1000 and dialog.bar.value() == 500
    assert '50%' in dialog.details.text()
    dialog.update_progress('@update:' + json.dumps(dict(phase='Testing the new application', current=0, total=0)))
    assert dialog.bar.maximum() == 0 and dialog.log.blockCount() >= 2
    dialog.finish(); app.processEvents()
    assert not dialog.isVisible() and not dialog.timer.isActive()


def test_update_discovery_shows_source_immediately_and_explains_wait(app):
    import json
    from soovee_commander.update_ui import UpdateProgress
    dialog = UpdateProgress()
    dialog.update_progress('@update:' + json.dumps(dict(phase='Looking for update files', detail='/local/update-folder')))
    assert dialog.source.text() == '/local/update-folder'
    assert '/local/update-folder' in dialog.log.toPlainText()
    dialog.last_activity -= 11
    dialog.tick()
    assert 'Cloud or network' in dialog.elapsed.text()
    dialog.update_progress('@update:' + json.dumps(dict(phase='Reading the update manifest', detail='/local/update-folder/new.stereoupdate')))
    dialog.tick()
    assert dialog.source.text().endswith('new.stereoupdate')
    assert 'Cloud or network' not in dialog.elapsed.text()
    dialog.finish()


def test_tab_cross_remains_in_painted_tile_after_overflow_resize_and_reorder(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    for index in range(9):
        window.left.new_tab(); settle(app, window)
    bar = window.left.tabbar
    for index in range(bar.count()):
        bar.setTabText(index, 'A very long folder name ' + str(index))
    for width in (820, 1440, 1100):
        window.resize(width, 800); app.processEvents()
        for index in (0, 5, 9):
            bar.setCurrentIndex(index); app.processEvents()
            rect = bar.tabRect(index).adjusted(3, 3, -3, -3)
            button = bar.tabButton(index, bar.ButtonPosition.RightSide)
            assert rect.contains(button.geometry()), (rect, button.geometry())
    bar.moveTab(9, 0); app.processEvents()
    assert bar.tabRect(0).adjusted(3, 3, -3, -3).contains(bar.tabButton(0, bar.ButtonPosition.RightSide).geometry())
    window.close(); app.processEvents()


def test_diagnostic_export_contains_context_and_masked_log_only(app, tmp_path, monkeypatch):
    import json
    import logging
    from PySide6.QtWidgets import QFileDialog
    from soovee_commander import diagnostic_log as logs
    from soovee_commander.diagnostic_ui import DiagnosticDialog
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    try:
        logs.configure(tmp_path / 'logs')
        logs.register_secret('sample-credential-8462')
        logs.logger.error('Example failed operation · password=sample-credential-8462')
        destination = tmp_path / 'support.zip'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(destination), ''))
        dialog = DiagnosticDialog(window)
        dialog.export()
        with zipfile.ZipFile(destination) as archive:
            assert set(archive.namelist()) == {'system.json', 'interface.json', 'application.jsonl', 'README.txt'}
            assert 'sample-credential-8462' not in archive.read('application.jsonl').decode()
            context = json.loads(archive.read('interface.json'))
            assert context['theme'] == window.theme_key and len(context['panels']) == 2
        dialog.close()
    finally:
        for handler in list(logs.logger.handlers):
            handler.close(); logs.logger.removeHandler(handler)
        logs.logger.addHandler(logging.NullHandler()); logs._path = None
        window.close(); app.processEvents()


def scrolling_window(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    for index in range(120):
        (tmp_path / f'file-{index:03}.txt').write_text('sample')
    window = Commander(str(tmp_path), str(tmp_path)); window.resize(1100, 760); window.show(); settle(app, window)
    for column in (0, 1, 2, 3, 5):
        window.left.tree.setColumnWidth(column, 240)
    app.processEvents()
    return window


@pytest.mark.parametrize('phase', [Qt.ScrollPhase.ScrollUpdate, Qt.ScrollPhase.ScrollMomentum])
def test_vertical_only_trackpad_preserves_manual_horizontal_position(app, tmp_path, phase):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    window = scrolling_window(app, tmp_path)
    panel = window.left
    assert not panel.pin_name and not panel.vertical_scroll_only
    panel.set_scrolling(pinned=True, vertical_only=True)
    tree, overlay = panel.tree, panel.tree.frozen_columns.view
    horizontal = tree.horizontalScrollBar()
    horizontal.setValue(horizontal.maximum() // 2)
    previous = horizontal.value()
    assert previous > 0
    for target in (tree.viewport(), overlay.viewport(), tree.header().viewport(), overlay.header().viewport()):
        tree.verticalScrollBar().setValue(0)
        point = QPointF(30, 40)
        event = QWheelEvent(point, QPointF(target.mapToGlobal(QPoint(30, 40))), QPoint(-70, -65), QPoint(0, 0),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, phase, False)
        QApplication.sendEvent(target, event); app.processEvents()
        assert horizontal.value() == previous
        assert tree.verticalScrollBar().value() > 0
        assert overlay.verticalScrollBar().value() == tree.verticalScrollBar().value()
    before = tree.verticalScrollBar().value()
    event = QWheelEvent(QPointF(20, 40), QPointF(20, 40), QPoint(-100, 0), QPoint(0, 0),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, phase, False)
    QApplication.sendEvent(tree.viewport(), event); app.processEvents()
    assert horizontal.value() == previous and tree.verticalScrollBar().value() == before
    panel.scroll_right.click(); app.processEvents()
    assert horizontal.value() > previous
    window.close(); app.processEvents()


def test_frozen_names_share_selection_sort_and_remain_visible_after_scroll(app, tmp_path):
    window = scrolling_window(app, tmp_path)
    panel = window.left; panel.set_scrolling(pinned=True, vertical_only=True)
    tree, overlay = panel.tree, panel.tree.frozen_columns.view
    assert overlay.model() is tree.model() and overlay.selectionModel() is tree.selectionModel()
    tree.horizontalScrollBar().setValue(tree.horizontalScrollBar().maximum()); app.processEvents()
    index = panel.model.index_for_name('file-010.txt')
    tree.scrollTo(index, QTreeView.ScrollHint.PositionAtTop); app.processEvents()
    horizontal = tree.horizontalScrollBar().value()
    assert horizontal > 0
    rect = overlay.visualRect(index)
    assert rect.left() >= 0 and overlay.viewport().rect().intersects(rect)
    QTest.mouseClick(overlay.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()); app.processEvents()
    assert panel.current_entry().name == 'file-010.txt'
    assert window.active is panel and tree.hasFocus()
    assert [e.name for e in panel.action_entries()] == ['file-010.txt']
    QTest.keyClick(tree, Qt.Key.Key_Down); app.processEvents()
    assert panel.current_entry().name == 'file-011.txt'
    assert tree.horizontalScrollBar().value() == horizontal
    QTest.mouseClick(overlay.header().viewport(), Qt.MouseButton.LeftButton, pos=overlay.header().rect().center())
    app.processEvents()
    assert panel.model.column == 0 and panel.model.descending
    settle(app, window)
    window.close(); app.processEvents()


def test_scrolling_options_persist_independently_and_restore_order_width(app, tmp_path):
    window = scrolling_window(app, tmp_path)
    panel, other = window.left, window.right
    header = panel.tree.header()
    header.moveSection(header.visualIndex(0), 3)
    panel.tree.setColumnWidth(0, 800)
    panel.set_scrolling(pinned=True, vertical_only=True)
    assert header.visualIndex(0) == 0 and panel._column_widths[0] == 800
    assert panel.tree.columnWidth(0) <= panel.tree.viewport().width() * .55 + 1
    assert not other.pin_name and not other.vertical_scroll_only
    panel.set_scrolling(pinned=False)
    assert header.visualIndex(0) == 3 and panel.tree.columnWidth(0) == 800
    panel.set_scrolling(pinned=True, auto_fit=True)
    window.close(); app.processEvents()
    reopened = Commander(str(tmp_path), str(tmp_path)); reopened.show(); settle(app, reopened)
    assert reopened.left.pin_name and reopened.left.vertical_scroll_only and reopened.left.auto_fit_columns
    assert not reopened.right.pin_name
    reopened.left.set_scrolling(pinned=False, auto_fit=False)
    assert reopened.left.tree.header().visualIndex(0) == 3
    assert reopened.left.tree.columnWidth(0) == 800
    reopened.close(); app.processEvents()


def test_scroll_protection_handles_shift_wheel_and_zero_phase_events(app, tmp_path):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    window = scrolling_window(app, tmp_path)
    panel = window.left; panel.set_scrolling(vertical_only=True)
    tree = panel.tree
    horizontal = tree.horizontalScrollBar()
    horizontal.setValue(horizontal.maximum() // 2)
    previous = horizontal.value()
    def send(angle, phase=Qt.ScrollPhase.NoScrollPhase):
        event = QWheelEvent(QPointF(30, 40), QPointF(30, 40), QPoint(), angle,
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ShiftModifier, phase, False)
        QApplication.sendEvent(tree.viewport(), event); app.processEvents()
    for phase in (Qt.ScrollPhase.ScrollBegin, Qt.ScrollPhase.ScrollEnd):
        send(QPoint(), phase)
        assert horizontal.value() == previous and tree.verticalScrollBar().value() == 0
    send(QPoint(-120, -120))
    assert tree.verticalScrollBar().value() > 0 and horizontal.value() == previous
    panel.set_scrolling(vertical_only=False)
    send(QPoint(-120, 0))
    assert horizontal.value() > previous
    window.close(); app.processEvents()


def test_auto_fit_preserves_preferred_width_and_dialog_applies_to_both_panels(app, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QCheckBox, QDialog
    window = scrolling_window(app, tmp_path)
    panel = window.left
    panel.tree.setColumnWidth(0, 260)
    for column in (1, 2, 3, 5):
        panel.toggle_column(column, False)
    panel.set_scrolling(auto_fit=True)
    assert panel.tree.columnWidth(0) >= panel.tree.viewport().width() - 2
    assert panel._column_widths[0] == 260
    window.resize(850, 700); app.processEvents()
    assert panel._column_widths[0] == 260
    panel.set_scrolling(auto_fit=False)
    assert panel.tree.columnWidth(0) == 260
    def accept():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        for field in dialog.findChildren(QCheckBox):
            field.setChecked(True)
        dialog.accept()
    QTimer.singleShot(0, accept)
    panel.configure_scrolling()
    assert all(p.pin_name and p.vertical_scroll_only and p.auto_fit_columns for p in (window.left, window.right))
    window.close(); app.processEvents()


def test_column_separators_render_through_rows_and_empty_space_and_persist(app, tmp_path):
    from PySide6.QtGui import QColor
    from soovee_commander.themes import THEMES
    from soovee_commander.columns import ColumnsDialog
    window = scrolling_window(app, tmp_path)
    panel = window.left
    assert not panel.column_separators and not window.right.column_separators
    panel.set_column_separators(True)
    for theme in ('soovee_light', 'soovee'):
        window.change_theme(theme); app.processEvents()
        for pinned in (False, True):
            panel.set_scrolling(pinned=pinned)
            panel.tree.horizontalScrollBar().setValue(30)
            app.processEvents()
            for tree in (panel.tree, panel.tree.frozen_columns.view) if pinned else (panel.tree,):
                shot = tree.viewport().grab().toImage()
                header = tree.header()
                for column in range(header.count()):
                    if tree.isColumnHidden(column):
                        continue
                    x = header.sectionViewportPosition(column) + header.sectionSize(column) - 1
                    if 0 <= x < tree.viewport().width():
                        assert shot.pixelColor(x, 30) == QColor(THEMES[theme]['border'])
    dialog = ColumnsDialog(panel)
    assert dialog.separators.isChecked()
    dialog.other.setChecked(True); dialog.save()
    assert window.right.column_separators
    window.close(); app.processEvents()
    reopened = Commander(str(tmp_path), str(tmp_path)); settle(app, reopened)
    assert reopened.left.column_separators and reopened.right.column_separators
    reopened.close(); app.processEvents()


def test_enabled_transfers_resume_hidden_and_explicit_stop_persists(app,tmp_path,monkeypatch):
    from soovee_commander import lan_ui
    original=lan_ui.DevicesDialog
    monkeypatch.setattr(lan_ui,'DevicesDialog',lambda host:original(host,state_directory=tmp_path/'transfer-state'))
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'prefs'))
    first=Commander(str(tmp_path),str(tmp_path));first.show();settle(app,first)
    dialog=first.show_devices();settle(app,first)
    assert dialog.service is not None and first.settings.value('lan_enabled',False,type=bool)
    first.close();app.processEvents()
    second=Commander(str(tmp_path),str(tmp_path));second.show();settle(app,second)
    assert second.devices_dialog.service is not None and not second.devices_dialog.isVisible()
    second.devices_dialog.shutdown(remember=True)
    second.close();app.processEvents()
    third=Commander(str(tmp_path),str(tmp_path));third.show();settle(app,third)
    assert not hasattr(third,'devices_dialog')
    third.close();app.processEvents()


def wait_until(app, condition, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_panel_follows_external_changes_and_keeps_cursor(app, tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    folder = tmp_path / 'watched'; folder.mkdir()
    for name in ('a.txt', 'b.txt', 'c.txt'):
        (folder / name).write_text(name)
    window = Commander(str(folder), str(tmp_path)); window.show(); settle(app, window)
    errors = []; window.error = errors.append
    panel = window.left
    assert panel.watcher.path == os.path.normpath(str(folder))
    panel.tree.setCurrentIndex(panel.model.index_for_name('b.txt'))
    (folder / 'new.txt').write_text('external')
    assert wait_until(app, lambda: any(e.name == 'new.txt' for e in panel.entries))
    assert panel.current_entry().name == 'b.txt'
    # Content rewritten by another app: caught when the user returns to Soovee.
    (folder / 'a.txt').write_text('much longer content than before')
    panel._current.loaded_at = 0
    window.application_state_changed(Qt.ApplicationState.ApplicationActive); settle(app, window)
    assert next(e for e in panel.entries if e.name == 'a.txt').size == len('much longer content than before')
    # A removed folder falls back quietly to its nearest existing parent.
    (folder / 'nested').mkdir()
    panel.navigate(panel.provider, str(folder / 'nested')); settle(app, window)
    import shutil; shutil.rmtree(folder / 'nested')
    panel.auto_refresh('change'); settle(app, window)
    assert panel.path == str(folder) and not errors
    window.commands.actions['auto_refresh'].setChecked(False); window.toggle_auto_refresh()
    assert panel.watcher.path is None and not window.settings.value('auto_refresh', True, type=bool)
    # An automatic refresh in flight must not hold the window open.
    panel.navigate(panel.provider, panel.path, remember=False, background=True, quiet=True)
    window.close(); app.processEvents()
    assert not window.isVisible()
    settle(app, window)


def test_older_column_layout_gains_date_added_and_last_opened_hidden():
    from soovee_commander.columns import COLUMNS, LATER_COLUMNS, defaults, validate
    old = [item for item in defaults() if item['id'] not in LATER_COLUMNS]
    migrated = validate(old)
    assert len(migrated) == len(COLUMNS)
    assert [item['id'] for item in migrated[-2:]] == list(LATER_COLUMNS)
    assert not any(item['visible'] for item in migrated[-2:])


@pytest.mark.skipif(sys.platform != 'darwin', reason='Finder dates are macOS metadata')
def test_date_added_column_reads_finder_dates_and_sorts(app, tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    (tmp_path / 'old.txt').write_text('old'); os.utime(tmp_path / 'old.txt', (1, 1))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    panel = window.left
    assert not panel._current.finder_dates  # Extra metadata only when shown or sorted.
    window.sort_active(15); settle(app, window)
    assert panel._current.finder_dates
    entry = next(e for e in panel.entries if e.name == 'old.txt')
    assert entry.modified < 10 and entry.added > time.time() - 600
    assert 'Finder' in panel.model.headerData(15, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    window.close(); app.processEvents()


def test_folders_first_can_be_turned_off(app, tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    (tmp_path / 'b-folder').mkdir(); (tmp_path / 'a.txt').write_text('x')
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    names = lambda: [e.name for e in window.left.model.visible if e.name in ('a.txt', 'b-folder')]
    assert names() == ['b-folder', 'a.txt']
    window.commands.actions['folders_first'].setChecked(False); window.toggle_folders_first()
    assert names() == ['a.txt', 'b-folder'] and window.right.model.folders_first is False
    window.close(); app.processEvents()


def test_new_file_creates_text_and_office_documents_without_replacing(app, tmp_path, monkeypatch):
    from soovee_commander import new_files
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    errors, opened = [], []
    window.error = errors.append
    monkeypatch.setattr(window, 'open_editor', lambda provider, path: opened.append(path))
    monkeypatch.setattr(new_files.NewFileDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    window.new_file('text'); settle(app, window)
    assert (tmp_path / 'New text document.txt').read_bytes() == b''
    assert opened == [str(tmp_path / 'New text document.txt')]
    assert window.left.current_entry().name == 'New text document.txt'
    window.new_file('text'); settle(app, window)
    assert (tmp_path / 'New text document (2).txt').exists()
    for key in ('docx', 'xlsx', 'odt', 'ods'):
        window.new_file(key); settle(app, window)
    with zipfile.ZipFile(tmp_path / 'New document.docx') as document:
        assert 'word/document.xml' in document.namelist() and document.testzip() is None
    with zipfile.ZipFile(tmp_path / 'New document.odt') as document:
        first = document.infolist()[0]
        assert first.filename == 'mimetype' and first.compress_type == zipfile.ZIP_STORED
    assert (tmp_path / 'New workbook.xlsx').exists() and (tmp_path / 'New spreadsheet.ods').exists()
    assert len(opened) == 2 and not errors  # Office documents are not opened as text.
    if os.name != 'nt':
        window.new_file(next(t.key for t in new_files.TYPES if t.key in ('shell', 'batch'))); settle(app, window)
        assert os.access(tmp_path / 'script.sh', os.X_OK)
    templates = tmp_path / 'templates'; templates.mkdir(); (templates / 'Invoice.txt').write_text('Template body')
    monkeypatch.setattr(new_files, 'templates_folder', lambda: templates)
    window.new_file('template:' + str(templates / 'Invoice.txt')); settle(app, window)
    assert (tmp_path / 'Invoice.txt').read_text() == 'Template body'
    window.close(); app.processEvents()


def test_toolbar_gains_refresh_for_unchanged_saved_bar(app, tmp_path):
    import json
    from soovee_commander.commands import defaults
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    old = defaults(); old['top'] = [item for item in old['top'] if item['command'] != 'refresh']
    settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "StereoCommander", "StereoCommander")
    settings.setValue('controls', json.dumps(old)); settings.sync()
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    assert [b.property('command_id') for b in window.top_buttons][:3] == ['back', 'forward', 'refresh']
    window.close(); app.processEvents()


def preview_samples(tmp_path):
    import io, json
    from PySide6.QtGui import QImage, QColor as Color
    from soovee_commander.new_files import _zip
    samples = {
        'notes.md': b'# Title\n\n* point\n',
        'page.html': b'<h1>Hello</h1><img src="http://example.invalid/x.png"><script>alert(1)</script>',
        'table.csv': b'name;value\nalpha;1\nbeta;2\n',
        'data.json': json.dumps({'items': [1, 2, {'deep': True}]}).encode(),
        'drawing.svg': b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20" fill="red"/></svg>',
        'letter.docx': _zip({'word/document.xml': '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                             '<w:p><w:r><w:t>Dear </w:t></w:r><w:r><w:t>reader</w:t></w:r></w:p></w:body></w:document>'}),
        'sheet.xlsx': _zip({'xl/sharedStrings.xml': '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Total</t></si></sst>',
                            'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>42</v></c></row></sheetData></worksheet>'}),
        'slides.pptx': _zip({'ppt/slides/slide1.xml': '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>Agenda</a:t></a:r></a:p></p:sld>'}),
        'text.odt': _zip({'content.xml': '<office:document-content xmlns:office="o" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
                          '<office:body><office:text><text:p>Ahoj <text:span>světe</text:span>!</text:p></office:text></office:body></office:document-content>'}),
        'broken.docx': b'PK\x03\x04 not really a document',
    }
    image = QImage(30, 10, QImage.Format.Format_RGB32); image.fill(Color('blue'))
    buffer = io.BytesIO()
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    qt_buffer = QBuffer(); qt_buffer.open(QIODevice.OpenModeFlag.WriteOnly); image.save(qt_buffer, 'PNG')
    samples['photo.png'] = bytes(qt_buffer.data())
    for name, data in samples.items():
        (tmp_path / name).write_bytes(data)
    return samples


def test_document_previews_render_common_formats_and_report_broken_files(app, tmp_path):
    from PySide6.QtWidgets import QTableWidget, QTextBrowser, QTreeWidget
    from soovee_commander import document_preview as previews
    samples = preview_samples(tmp_path)
    assert isinstance(previews.build('notes.md', samples['notes.md']), QTextBrowser)
    html = previews.build('page.html', samples['page.html'])
    assert 'Hello' in html.toPlainText() and 'alert' not in html.toPlainText()
    table = previews.build('table.csv', samples['table.csv'])
    assert isinstance(table, QTableWidget) and table.rowCount() == 2 and table.item(1, 0).text() == 'beta'
    tree = previews.build('data.json', samples['data.json'])
    assert isinstance(tree, QTreeWidget) and tree.topLevelItem(0).child(0).text(1).startswith('3')
    assert previews.build('drawing.svg', samples['drawing.svg']).pixmap.width() >= 40
    assert previews.build('photo.png', samples['photo.png']).pixmap.width() == 30
    assert previews.build('letter.docx', samples['letter.docx']).toPlainText() == 'Dear reader'
    sheet = previews.build('sheet.xlsx', samples['sheet.xlsx'])
    assert sheet.item(0, 0).text() == 'Total' and sheet.item(0, 2).text() == '42'
    assert 'Agenda' in previews.build('slides.pptx', samples['slides.pptx']).toPlainText()
    assert previews.build('text.odt', samples['text.odt']).toPlainText() == 'Ahoj světe!'
    with pytest.raises(previews.PreviewError):
        previews.build('broken.docx', samples['broken.docx'])
    with pytest.raises(previews.PreviewError):
        previews.build('letter.docx', samples['letter.docx'][:20], complete=False)
    assert previews.build('program.exe', b'MZ') is None
    if previews.pdf_available():
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QPdfWriter, QPainter
        target = QBuffer(); target.open(QIODevice.OpenModeFlag.WriteOnly)
        writer = QPdfWriter(target); painter = QPainter(writer); painter.drawText(100, 100, 'PDF'); writer.newPage(); painter.end()
        pdf_preview = previews.build('doc.pdf', bytes(target.data()))
        assert pdf_preview.document.pageCount() == 2


def test_f3_shows_formatted_preview_tab_and_respects_settings(app, tmp_path):
    from soovee_commander.viewer import FileViewer
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    samples = preview_samples(tmp_path)
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    viewer = FileViewer(window, 'table.csv', len(samples['table.csv']), samples['table.csv'])
    assert viewer.tabs.tabText(viewer.tabs.currentIndex()) == 'Preview' and viewer.document.rowCount() == 2
    broken = FileViewer(window, 'broken.docx', len(samples['broken.docx']), samples['broken.docx'])
    assert broken.tabs.tabText(broken.tabs.currentIndex()) == 'Preview' and 'could not be read' in broken.document.text()
    window.set_preview_group('tables', False)
    plain = FileViewer(window, 'table.csv', len(samples['table.csv']), samples['table.csv'])
    assert plain.document is None and plain.tabs.currentIndex() == 0
    for dialog in (viewer, broken, plain):
        dialog.close()
    window.close(); app.processEvents()


def test_quick_view_follows_cursor_in_the_other_panel(app, tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    preview_samples(tmp_path)
    (tmp_path / 'readme.txt').write_text('plain words')
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    left, right = window.left, window.right
    window.activate(left)
    left.tree.setCurrentIndex(left.model.index_for_name('table.csv'))
    window.toggle_quick_view()
    assert right.quick_view_active() and right.active_view() is right.tree
    assert wait_until(app, lambda: right.quick.title.text() == 'table.csv' and right.quick.body.__class__.__name__ == 'QTableWidget')
    left.tree.setCurrentIndex(left.model.index_for_name('readme.txt'))
    assert wait_until(app, lambda: right.quick.title.text() == 'readme.txt' and 'plain words' in getattr(right.quick.body, 'toPlainText', lambda: '')())
    left.tree.setCurrentIndex(left.model.index_for_name('broken.docx'))
    assert wait_until(app, lambda: 'could not be read' in getattr(right.quick.body, 'text', lambda: '')())
    window.toggle_quick_view()
    assert not right.quick_view_active()
    window.close(); app.processEvents()


def test_polling_watcher_detects_changes_without_holding_the_folder(app, tmp_path):
    from soovee_commander.folder_watch import FolderWatcher
    calls = []
    folder = tmp_path / 'shown'; folder.mkdir()
    watcher = FolderWatcher(None, lambda: calls.append(1), polling=True)
    watcher.poll.setInterval(50)
    watcher.watch(str(folder))
    assert watcher.poll.isActive() and not watcher.watcher.directories()  # No open directory handle.
    (folder / 'new.txt').write_text('x')
    assert wait_until(app, lambda: calls)
    # The shown folder (and its parent) can still be renamed by other programs.
    renamed = tmp_path / 'renamed'
    folder.rename(renamed)
    calls.clear()
    assert wait_until(app, lambda: calls)
    watcher.watch(None)
    assert not watcher.poll.isActive()


def test_main_menu_follows_the_documented_structure_with_descriptions(app, tmp_path):
    from soovee_commander.command_help import HELP, MENUS
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    assert [a.text() for a in window.command_menu.actions()] == [title for title, entries in MENUS]
    for action in window.commands.actions.values():
        command = action.objectName().removeprefix('command_')
        if command in HELP:
            assert action.statusTip() == HELP[command]
    view = window.command_menu.actions()[2].menu()
    assert window.hidden_action in view.actions() and window.sidebar_action in view.actions()
    window.hidden_action.setChecked(False)
    assert not window.hidden.isChecked()
    window.hidden.setChecked(True)
    assert window.hidden_action.isChecked()
    window.close(); app.processEvents()


def test_settings_window_applies_every_page_and_keeps_menus_in_sync(app, tmp_path, monkeypatch):
    from soovee_commander import settings_window
    from soovee_commander.settings_window import SettingsWindow, PAGES
    warnings = []
    monkeypatch.setattr(settings_window.QMessageBox, 'warning', lambda *args: warnings.append(args[1]))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    dialog = SettingsWindow(window, 'previews')
    assert dialog.stack.currentWidget() is dialog.pages['previews'] and dialog.categories.count() == len(PAGES)
    dialog.search.setText('periodically')
    assert [dialog.categories.item(r).data(Qt.ItemDataRole.UserRole) for r in range(dialog.categories.count())
            if not dialog.categories.item(r).isHidden()] == ['panels']
    assert dialog.stack.currentWidget() is dialog.pages['panels']
    dialog.search.clear()
    dialog.folders_first.check.setChecked(False)
    dialog.auto_refresh.check.setChecked(False)
    dialog.interval.setCurrentIndex(dialog.interval.findData(15))
    dialog.preview_groups['tables'].check.setChecked(False)
    dialog.hidden.check.setChecked(False)
    assert dialog.apply()
    assert not window.settings.value('folders_first', True, type=bool) and not window.left.model.folders_first
    assert not window.settings.value('auto_refresh', True, type=bool) and window.left.watcher.path is None
    assert window.left.poll_timer.interval() == 15000 and window.interval_actions[15].isChecked()
    assert not window.settings.value('preview_tables', True, type=bool) and not window.preview_actions['tables'].isChecked()
    assert not window.hidden.isChecked() and not window.hidden_action.isChecked()
    assert not window.commands.actions['folders_first'].isChecked()
    # Invalid controls keep the window open on the page that needs attention.
    dialog.controls.key_edits['copy'].setText('Q')
    assert not dialog.apply() and dialog.stack.currentWidget() is dialog.pages['controls'] and warnings == ['Check controls']
    dialog.controls.key_edits['copy'].setText('F5')
    dialog.language.setCurrentIndex(dialog.language.findData('cs'))
    assert dialog.apply() and window.language == 'cs'
    assert window.command_menu.actions()[1].text() == 'Úpravy'
    window.change_language('en')
    dialog.close(); window.close(); app.processEvents()


def test_shortcut_overview_lists_menu_commands_and_filters(app, tmp_path):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    dialog = window.show_shortcuts()
    sections = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
    assert sections[0].text(0) == 'File'
    copy = next(sections[0].child(i) for i in range(sections[0].childCount()) if sections[0].child(i).text(0) == 'Copy')
    assert copy.text(1) == 'F5' and 'other panel' in copy.text(2)
    dialog.search.setText('F5')
    assert not copy.isHidden() and sections[-1].isHidden()
    dialog.search.setText('no such command')
    assert all(section.isHidden() for section in sections)
    dialog.close(); window.close(); app.processEvents()


def test_dialog_kit_names_actions_and_protects_destructive_confirmations(app, tmp_path, monkeypatch):
    from soovee_commander import dialog_kit
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    seen = {}

    def inspect(dialog):
        seen.update(ok=dialog.ok.text(), ok_name=dialog.ok.objectName(), cancel_default=dialog.cancel.isDefault(),
                    ok_default=dialog.ok.isDefault(), items=dialog.findChild(QListWidget).count() if dialog.findChild(QListWidget) else 0,
                    heading=dialog.heading.text())
        return QDialog.DialogCode.Rejected
    from PySide6.QtWidgets import QListWidget
    monkeypatch.setattr(dialog_kit.StandardDialog, 'exec', inspect)
    assert not dialog_kit.confirm(window, 'Delete', 'Delete 12 items permanently?', items=[f'f{i}' for i in range(12)],
                                  action='Delete permanently', destructive=True)
    assert seen['ok'] == 'Delete permanently' and seen['ok_name'] == 'danger'
    assert seen['ok_default'] and not seen['cancel_default']  # Enter confirms, as in Total Commander and seen['items'] == dialog_kit.MAX_LISTED + 1
    dialog_kit.confirm(window, 'Copy', 'Copy 1 items?', items=['a'], action='Copy')
    assert seen['ok_name'] == 'primary' and seen['ok_default']

    def typed(dialog):
        assert not dialog.ok.isEnabled() if not dialog.edit.text() else dialog.edit.selectedText() == 'report'
        dialog.edit.setText('report-final.txt')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(dialog_kit.StandardDialog, 'exec', lambda dialog: typed(dialog) if hasattr(dialog, 'edit') else 0)
    original_ask = dialog_kit.ask_text
    # ask_text assigns .edit before exec, so the stub sees the prepared field.
    assert original_ask(window, 'Rename', 'Rename', 'New name:', 'report.txt', select_stem=True) == 'report-final.txt'
    window.close(); app.processEvents()


def test_rename_and_permanent_delete_use_the_shared_dialogs(app, tmp_path, monkeypatch):
    from soovee_commander import dialog_kit
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    (tmp_path / 'draft.txt').write_text('x')
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    window.activate(window.left)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name('draft.txt'))
    asked = {}
    monkeypatch.setattr(dialog_kit, 'ask_text', lambda *args, **kwargs: asked.update(args=args, kwargs=kwargs) or 'final.txt')
    window.rename(); settle(app, window)
    assert (tmp_path / 'final.txt').exists() and asked['kwargs']['select_stem'] and asked['args'][4] == 'draft.txt'
    window.left.tree.setCurrentIndex(window.left.model.index_for_name('final.txt'))
    confirmed = {}
    monkeypatch.setattr(dialog_kit, 'confirm', lambda *args, **kwargs: confirmed.update(kwargs) or False)
    window.delete(permanent=True); settle(app, window)
    assert confirmed['destructive'] and confirmed['items'] == ['final.txt'] and (tmp_path / 'final.txt').exists()
    window.close(); app.processEvents()


def test_devices_window_shows_state_sections_and_empty_hints(app, tmp_path, monkeypatch):
    from soovee_commander.lan_ui import DevicesDialog
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    monkeypatch.setattr(window, 'error', lambda message: pytest.fail(message))
    dialog = DevicesDialog(window, tmp_path / 'state')
    assert dialog.status.text().startswith('Off') and not dialog.enable.isHidden() and dialog.stop_button.isHidden()
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        'Nearby devices', 'Paired devices', 'Shared folders', 'Connection settings']
    assert dialog.devices.item(0).flags() == Qt.ItemFlag.NoItemFlags and dialog.selected_peer() is None
    dialog.start(); dialog.show(); app.processEvents()
    assert dialog.status.text().startswith('On') and str(dialog.service.port) in dialog.status.text()
    assert dialog.stop_button.isVisible() and not dialog.enable.isVisible()
    assert 'No paired devices' in dialog.devices.item(0).text()
    dialog.remove_share()  # The hint row is not a share and must be ignored.
    dialog.shutdown(); dialog.close(); settle(app, window); window.close()


def test_asking_a_nearby_device_for_a_code_opens_its_pairing_window(app, tmp_path, monkeypatch):
    from soovee_commander.lan import TransferService
    from soovee_commander.lan_ui import DevicesDialog
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    original_start = TransferService.start
    monkeypatch.setattr(TransferService, 'start', lambda self, host='127.0.0.1', port=0: original_start(self, '127.0.0.1', 0))
    a, b = Commander(str(tmp_path), str(tmp_path)), Commander(str(tmp_path), str(tmp_path))
    settle(app, a); settle(app, b)
    asking, shown = DevicesDialog(a, tmp_path / 'a'), DevicesDialog(b, tmp_path / 'b')
    asking.name.setText('Mac A'); shown.name.setText('TV B')
    asking.start(); shown.start()
    assert not shown.pairing_window.isVisible()
    asking.found([dict(id=shown.service.store.id, name='TV B', host='127.0.0.1', port=shown.service.port, kind='tv')])
    asking.nearby.setCurrentRow(0)
    assert asking.pair_button.text() == 'Ask for a code'
    asking.connect_nearby()
    assert wait_until(app, lambda: shown.pairing_window.isVisible())
    assert shown.pairing_window.heading.text() == 'Mac A wants to pair'
    code = shown.service.pairing['code']
    assert shown.code.text().replace(' ', '') == code and 'TV B now shows' in asking.discovery_status.text()
    asking.remote_code.setText(code)
    assert asking.pair_button.text() == 'Pair device'
    asking.shutdown(); shown.shutdown(); settle(app, a); settle(app, b)
    a.close(); b.close(); app.processEvents()


def test_f7_suggests_name_under_cursor_and_archive_goes_next_to_items(app, tmp_path, monkeypatch):
    from soovee_commander import dialog_kit
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    left = tmp_path / "left"; right = tmp_path / "right"; left.mkdir(); right.mkdir()
    (left / "Season 1").mkdir(); (left / "Season 1" / "a.txt").write_text("a")
    window = Commander(str(left), str(right)); window.show(); settle(app, window)
    panel = window.left
    panel.tree.setCurrentIndex(panel.model.index_for_name("Season 1")); app.processEvents()
    asked = {}
    monkeypatch.setattr(dialog_kit, 'ask_text', lambda *args, **kwargs: asked.update(args=args) or None)
    window.mkdir()
    assert asked['args'][4] == "Season 1"
    captured = {}
    def accept(dialog):
        from PySide6.QtWidgets import QLineEdit
        captured['path'] = [edit for edit in dialog.findChildren(QLineEdit) if edit.text().endswith('.zip')][0].text()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(dialog_kit.StandardDialog, 'exec', accept)
    queued = []
    monkeypatch.setattr(window, 'enqueue', lambda title, work: queued.append(title))
    window.pack()
    assert captured['path'] == str(left / "Season 1.zip") and queued
    window.close(); app.processEvents()


def test_open_with_can_save_for_related_types_without_opening(app, tmp_path, monkeypatch):
    from soovee_commander.native_apps import Application
    import soovee_commander.associations as associations
    from PySide6.QtCore import QProcess
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    movie = tmp_path / "film.mkv"; movie.write_bytes(b"x")
    player = tmp_path / "Player.app"; player.mkdir()
    monkeypatch.setattr(associations, "applications_for_file", lambda path: [Application(str(player), "Player")])
    launched = []
    monkeypatch.setattr(QProcess, "startDetached", lambda program, args: (launched.append(program) or True, 1))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    dialog = window.show_open_with([str(movie)]); settle(app, window)
    assert dialog.apply_button.isEnabled() and '.mp4' in dialog.related and not dialog.related_box.isVisible()
    row = next(i for i in range(dialog.apps.count()) if dialog.apps.item(i).data(Qt.ItemDataRole.UserRole) == str(player))
    dialog.apps.setCurrentRow(row)
    dialog.remember.setChecked(True)
    dialog.related['.avi'].setChecked(False)
    dialog.apply_button.click(); settle(app, window)
    custom = window.associations.custom
    assert custom['.mkv'] == custom['.mp4'] == str(player) and '.avi' not in custom
    assert launched == []          # saved only, nothing opened
    window.close(); app.processEvents()


def test_plain_ftp_is_marked_insecure_and_needs_confirmation(app, tmp_path, monkeypatch):
    from soovee_commander import dialog_kit
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    window = Commander(str(tmp_path), str(tmp_path)); settle(app, window)
    dialog = ConnectDialog(window)
    assert dialog.protocol.itemText(0) == 'SFTP' and dialog.protocol.currentText() == 'SFTP'
    dialog.protocol.setCurrentText('FTP')
    assert 'c93a3a' in dialog.note.styleSheet()
    answers = []
    monkeypatch.setattr(dialog_kit, 'confirm', lambda *args, **kwargs: answers.append(args) or False)
    dialog.host.setText('ftp://user@127.0.0.1/')     # a pasted ftp:// address is warned about too
    dialog.protocol.setCurrentText('SFTP')
    dialog.accept()
    assert answers and dialog.result() != dialog.DialogCode.Accepted
    monkeypatch.setattr(dialog_kit, 'confirm', lambda *args, **kwargs: True)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    secure = ConnectDialog(window)
    secure.host.setText('sftp.example.com')
    monkeypatch.setattr(dialog_kit, 'confirm', lambda *args, **kwargs: pytest.fail('SFTP needs no warning'))
    secure.accept()
    assert secure.result() == secure.DialogCode.Accepted


def test_f7_prefill_can_be_turned_off_or_limited_to_folders(app, tmp_path, monkeypatch):
    from soovee_commander import dialog_kit
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    left = tmp_path / "left"; left.mkdir(); (left / "Episode 1.mkv").write_text("v")
    window = Commander(str(left), str(tmp_path)); window.show(); settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name("Episode 1.mkv")); app.processEvents()
    seen = []
    def run(dialog):
        seen.append(dialog.edit.text())
        dialog.prefill_source.setCurrentIndex(1)       # folders only: a file gives no name
        seen.append(dialog.edit.text())
        dialog.prefill_source.setCurrentIndex(0)
        seen.append(dialog.edit.text())
        dialog.prefill.setChecked(False)               # prefill off
        seen.append(dialog.edit.text())
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(dialog_kit.StandardDialog, 'exec', run)
    window.mkdir()
    assert seen == ["Episode 1", "", "Episode 1", ""]
    # The choice is remembered for the next F7.
    seen.clear()
    monkeypatch.setattr(dialog_kit.StandardDialog, 'exec', lambda dialog: seen.append((dialog.edit.text(), dialog.prefill.isChecked())) or QDialog.DialogCode.Rejected)
    window.mkdir()
    assert seen == [("", False)]


def test_properties_show_program_icon_and_assign_without_opening(app, tmp_path, monkeypatch):
    from soovee_commander.native_apps import Application
    import soovee_commander.associations as associations
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QPushButton, QLabel
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    movie = tmp_path / "film.mkv"; movie.write_bytes(b"x")
    player = tmp_path / "Player.app"; player.mkdir()
    monkeypatch.setattr(associations, "applications_for_file", lambda path: [Application(str(player), "Player")])
    launched = []
    monkeypatch.setattr(QProcess, "startDetached", lambda program, args: (launched.append(program) or True, 1))
    window = Commander(str(tmp_path), str(tmp_path)); window.show(); settle(app, window)
    window.left.tree.setCurrentIndex(window.left.model.index_for_name("film.mkv")); app.processEvents()
    properties = window.show_properties(); settle(app, window)
    change = next(b for b in properties.findChildren(QPushButton) if b.text() == 'Change…')
    opened = []
    real = window.show_open_with
    monkeypatch.setattr(window, 'show_open_with', lambda paths, assign=False: opened.append(real(paths, assign=assign)) or opened[-1])
    change.click(); settle(app, window)
    dialog = opened[0]
    assert dialog.assign and dialog.remember.isChecked() and dialog.apply_button.text() == 'Use' and dialog.apply_button.isDefault()
    row = next(i for i in range(dialog.apps.count()) if dialog.apps.item(i).data(Qt.ItemDataRole.UserRole) == str(player))
    dialog.apps.setCurrentRow(row)
    dialog.apply_button.click(); settle(app, window)
    assert window.associations.custom['.mkv'] == window.associations.custom['.mp4'] == str(player)
    assert launched == []
    assert any(label.text() == 'Player' for label in properties.findChildren(QLabel))
    window.close(); app.processEvents()
