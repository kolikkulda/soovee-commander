import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from soovee_commander import updates
from soovee_commander.updates import (APP_ID, APP_NAME, PreparedUpdate, Release, UpdateError,
                                     canonical_manifest, find_release, inspect_package, launch_update,
                                     prepare_update, validate_mac_zip)


@pytest.fixture
def signing_key(monkeypatch):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(updates, "PUBLIC_KEY_HEX", public.hex())
    monkeypatch.setattr(updates, "current_target", lambda: "macos-arm64")
    return key


def package(path, key, payload=b"test payload", version="9.0.0", target="macos-arm64", **changes):
    artifact = "setup.exe" if target.startswith("windows-") else "application.zip"
    manifest = {"schema": 1, "app_id": APP_ID, "version": version, "target": target,
                "artifact": artifact, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "notes": "Test release"}
    manifest.update(changes)
    manifest["signature"] = base64.b64encode(key.sign(canonical_manifest(manifest))).decode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("update.json", json.dumps(manifest))
        archive.writestr(artifact, payload)
    return path


def test_signed_update_and_highest_compatible_version(tmp_path, signing_key):
    package(tmp_path / "older.stereoupdate", signing_key, version="8.0.0")
    package(tmp_path / "newer.stereoupdate", signing_key, version="9.0.0")
    package(tmp_path / "wrong-platform.stereoupdate", signing_key, version="10.0.0", target="windows-x86_64")
    assert find_release(tmp_path).version == "9.0.0"


@pytest.mark.parametrize('filename', ['SooveeCommander.exe', 'StereoCommander.exe'])
def test_installed_app_recognizes_current_and_legacy_windows_executables(tmp_path, monkeypatch, filename):
    executable = tmp_path / filename; executable.touch()
    monkeypatch.setattr(updates.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(updates.sys, 'platform', 'win32')
    monkeypatch.setattr(updates.sys, 'executable', str(executable))
    assert updates.installed_app() == tmp_path.resolve()


def test_discovery_reports_before_reading_manifest_and_ignores_unrelated_files(tmp_path, signing_key, monkeypatch):
    update = package(tmp_path / 'release.STEREOUPDATE', signing_key)
    (tmp_path / 'unrelated.zip').write_bytes(b'not an update')
    child = tmp_path / 'nested'; child.mkdir()
    package(child / 'newer.stereoupdate', signing_key, version='10.0.0')
    events = []
    original = updates.inspect_package
    def inspect(path, **options):
        assert events[-1]['phase'] == 'Reading the update manifest'
        assert str(path) in events[-1]['detail']
        assert path == update
        return original(path, **options)
    monkeypatch.setattr(updates, 'inspect_package', inspect)
    release = find_release(tmp_path, report=lambda message, count: events.append(json.loads(message[8:])))
    assert release.version == '9.0.0'
    assert events[0] == dict(phase='Looking for update files', detail=str(tmp_path))
    assert events[-1]['phase'] == 'Update package found'


def test_wrong_folder_fails_without_reading_any_file(tmp_path, monkeypatch):
    (tmp_path / 'application.zip').write_bytes(b'not an update')
    nested = tmp_path / 'nested'; nested.mkdir()
    (nested / 'release.stereoupdate').touch()
    monkeypatch.setattr(updates, 'inspect_package', lambda *args, **kwargs: pytest.fail('Must not open unrelated files'))
    events = []
    with pytest.raises(UpdateError, match='There is no .stereoupdate'):
        find_release(tmp_path, report=lambda message, count: events.append(message))
    assert len(events) == 1 and json.loads(events[0][8:])['detail'] == str(tmp_path)


def test_cloud_placeholder_is_rejected_before_opening_zip(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / 'cloud.stereoupdate'; path.touch()
    original = Path.stat
    monkeypatch.setattr(updates.stat, 'SF_DATALESS', 0x40000000, raising=False)
    monkeypatch.setattr(Path, 'stat', lambda self, **kwargs: SimpleNamespace(st_flags=0x40000000) if self == path else original(self, **kwargs))
    monkeypatch.setattr(updates.zipfile, 'ZipFile', lambda *args, **kwargs: pytest.fail('Must not hydrate cloud payload'))
    asked = []
    monkeypatch.setattr(updates, 'download_from_cloud', lambda target: asked.append(target) or False)
    with pytest.raises(UpdateError, match='stored only in the cloud'):
        inspect_package(path)
    assert asked == [path.resolve()]          # it asked iCloud for the file first
    with pytest.raises(UpdateError, match='stored only in the cloud'):
        inspect_package(path, download=False)  # folder scans read placeholders without downloading
    assert len(asked) == 1


@pytest.mark.parametrize("change", [{"version": "0.1.0"}, {"version": "bad"}, {"target": "windows-x86_64"},
                                     {"app_id": "another.app"}, {"size": -1}, {"schema": 7}])
def test_invalid_update_rejected(tmp_path, signing_key, change):
    path = package(tmp_path / "update.stereoupdate", signing_key, **change)
    with pytest.raises(UpdateError):
        inspect_package(path)


def test_foreign_key_rejected(tmp_path, signing_key):
    path = package(tmp_path / "untrusted.stereoupdate", Ed25519PrivateKey.generate())
    with pytest.raises(UpdateError, match="signature"):
        inspect_package(path)


def test_tampered_payload_leaves_installed_app_and_settings(tmp_path, signing_key):
    path = package(tmp_path / "update.stereoupdate", signing_key)
    release = inspect_package(path)
    with zipfile.ZipFile(path) as archive:
        manifest = archive.read("update.json")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("update.json", manifest)
        archive.writestr("application.zip", b"x" * release.size)
    installed = tmp_path / APP_NAME
    installed.mkdir()
    (installed / "original").write_text("original app")
    settings = tmp_path / "settings.ini"
    settings.write_text("saved connections")
    with pytest.raises(UpdateError, match="Checksum"):
        prepare_update(release, installed, tmp_path / "result.json")
    assert (installed / "original").read_text() == "original app"
    assert settings.read_text() == "saved connections"
    assert not list(tmp_path.glob(".StereoCommander-update*"))


def test_package_changed_since_inspection_rejected(tmp_path, signing_key):
    path = package(tmp_path / "update.stereoupdate", signing_key)
    release = inspect_package(path)
    package(path, signing_key, version="9.0.1")
    with pytest.raises(UpdateError, match="changed"):
        updates.extract_payload(release, tmp_path / "payload.zip")


@pytest.mark.parametrize("name", ["../escape", "/absolute", "StereoCommander.app/../escape", "StereoCommander.app/C:/bad",
                                  "Other.app/file", "StereoCommander.app/a\\b", "StereoCommander.app/a\0b"])
def test_archive_traversal_rejected(tmp_path, name):
    path = tmp_path / "payload.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo()
        info.filename = name  # Prevent ZipInfo's Windows separator normalization.
        archive.writestr(info, "unsafe")
    with zipfile.ZipFile(path) as archive:
        assert archive.infolist()[0].orig_filename == name
    with pytest.raises(UpdateError):
        validate_mac_zip(path)


def add_link(archive, name, target):
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive.writestr(info, target)


def test_safe_framework_links_allowed_and_escape_chains_rejected(tmp_path):
    path = tmp_path / "payload.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(APP_NAME + "/Contents/Frameworks/F.framework/Versions/A/F", "binary")
        add_link(archive, APP_NAME + "/Contents/Frameworks/F.framework/Versions/Current", "A")
        add_link(archive, APP_NAME + "/Contents/Frameworks/F.framework/F", "Versions/Current/F")
    validate_mac_zip(path)
    with zipfile.ZipFile(path, "w") as archive:
        add_link(archive, APP_NAME + "/Contents/B", "..")
        add_link(archive, APP_NAME + "/Contents/A", "B/../..")
    with pytest.raises(UpdateError):
        validate_mac_zip(path)


def test_writing_through_archive_symlink_rejected(tmp_path):
    path = tmp_path / "payload.zip"
    with zipfile.ZipFile(path, "w") as archive:
        add_link(archive, APP_NAME + "/link", "Contents")
        archive.writestr(APP_NAME + "/link/file", "unsafe")
    with pytest.raises(UpdateError):
        validate_mac_zip(path)


@pytest.fixture
def prepared(tmp_path):
    parent = tmp_path / "apps with spaces ' and unicode ž"
    parent.mkdir()
    current = parent / APP_NAME
    current.mkdir()
    (current / "version").write_text("old")
    work = parent / ".StereoCommander-update-test"
    work.mkdir()
    candidate = work / "new" / APP_NAME
    candidate.mkdir(parents=True)
    (candidate / "version").write_text("new")
    lock = parent / ".StereoCommander-update.lock"
    lock.mkdir()
    (lock / "owner").write_text(str(os.getpid()))
    release = Release(tmp_path / "release", "9.0.0", "macos-arm64", "application.zip", 1, "0" * 64, "test")
    return PreparedUpdate(release, current, work, candidate, lock, tmp_path / "result.json")


@pytest.mark.skipif(os.name != "posix", reason="macOS helper uses POSIX tools")
def test_helper_replaces_whole_app_keeps_backup_and_settings(prepared, tmp_path):
    settings = tmp_path / "settings.ini"
    settings.write_text("untouched connections")
    process = launch_update(prepared, old_pid=999999999, launch=False)
    assert process.wait(timeout=10) == 0
    assert (prepared.current / "version").read_text() == "new"
    assert (prepared.workspace / "previous.app" / "version").read_text() == "old"
    assert settings.read_text() == "untouched connections"
    assert json.loads(prepared.result_path.read_text())["state"] == "success"
    assert not prepared.lock.exists()


@pytest.mark.skipif(os.name != "posix", reason="macOS helper uses POSIX tools")
def test_helper_rolls_back_failed_startup(prepared):
    executable = prepared.candidate / "Contents" / "MacOS" / "StereoCommander"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o700)
    process = launch_update(prepared, old_pid=999999999, launch=False, verify=True)
    assert process.wait(timeout=10) == 1
    assert (prepared.current / "version").read_text() == "old"
    assert (prepared.workspace / "failed.app" / "version").read_text() == "new"
    assert json.loads(prepared.result_path.read_text())["state"] == "error"
    assert not prepared.lock.exists()


@pytest.mark.skipif(os.name != "posix", reason="macOS helper uses POSIX tools")
def test_helper_waits_until_running_app_exits(prepared):
    old_process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        helper = launch_update(prepared, old_pid=old_process.pid, launch=False)
        time.sleep(.1)
        assert (prepared.current / "version").read_text() == "old"
        old_process.terminate()
        old_process.wait(timeout=5)
        assert helper.wait(timeout=10) == 0
        assert (prepared.current / "version").read_text() == "new"
    finally:
        if old_process.poll() is None:
            old_process.kill()
            old_process.wait(timeout=5)


def test_concurrent_update_lock_and_stale_lock_recovery(tmp_path):
    lock = updates._acquire_lock(tmp_path)
    with pytest.raises(UpdateError, match="already running"):
        updates._acquire_lock(tmp_path)
    (lock / "owner").write_text("999999999")
    assert updates._acquire_lock(tmp_path) == lock


def test_renamed_app_root_is_valid_and_mixed_roots_are_rejected(tmp_path):
    filename = tmp_path / 'soovee.zip'
    with zipfile.ZipFile(filename, 'w') as archive:
        archive.writestr('SooveeCommander.app/Contents/Info.plist', 'metadata')
        archive.writestr('SooveeCommander.app/Contents/MacOS/StereoCommander', 'legacy executable name')
    validate_mac_zip(filename)
    with zipfile.ZipFile(filename, 'a') as archive:
        archive.writestr('StereoCommander.app/Contents/Info.plist', 'second root')
    with pytest.raises(UpdateError, match='multiple'):
        validate_mac_zip(filename)
def test_update_monitor_exits_after_success(tmp_path):
    import os
    import subprocess
    import sys
    progress = tmp_path / 'progress.json'
    progress.write_text(json.dumps(dict(phase='Update complete', state='success')))
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(Path(__file__).parents[1] / 'src'))
    result = subprocess.run([sys.executable, '-m', 'soovee_commander.app', '--update-monitor', str(progress), str(os.getpid())],
                            env=environment, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors='replace')

