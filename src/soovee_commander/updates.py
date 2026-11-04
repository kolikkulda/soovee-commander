"""Authenticated, local full-application updates. This module does not import Qt."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import __version__
from .update_key import PUBLIC_KEY_HEX

APP_ID = "cz.stereocommander.desktop"
APP_NAME = "StereoCommander.app"  # Legacy payload root remains compatible with installed updaters.
APP_NAMES = (APP_NAME, "SooveeCommander.app")
MAX_PAYLOAD = 2 * 1024**3
MAX_EXPANDED = 4 * 1024**3


class UpdateError(Exception):
    pass


def version_tuple(version):
    if not isinstance(version, str) or not re.fullmatch(r"\d{1,6}\.\d{1,6}\.\d{1,6}", version):
        raise UpdateError('The package contains an invalid version number.')
    return tuple(map(int, version.split(".")))


def current_target():
    architecture = platform.machine().lower()
    architecture = {"amd64": "x86_64", "aarch64": "arm64"}.get(architecture, architecture)
    system = {"darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)
    return f"{system}-{architecture}"


def canonical_manifest(manifest):
    return json.dumps({k: v for k, v in manifest.items() if k != "signature"},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class Release:
    package: Path
    version: str
    target: str
    artifact: str
    size: int
    sha256: str
    notes: str


def is_dataless(path):
    """An iCloud Drive file whose contents were evicted to the cloud (macOS)."""
    flag = getattr(stat, 'SF_DATALESS', 0)
    try:
        return bool(flag and getattr(Path(path).stat(), 'st_flags', 0) & flag)
    except OSError:
        return False


def download_from_cloud(path, timeout=180):
    """Ask iCloud Drive to download an evicted file and wait for it, like opening it in Finder."""
    import shutil, subprocess, time
    brctl = shutil.which('brctl') or '/usr/bin/brctl'
    if sys.platform != 'darwin' or not Path(brctl).exists():
        return False
    try:
        if subprocess.run([brctl, 'download', str(path)], capture_output=True, timeout=30, check=False).returncode:
            return False   # not in iCloud Drive, or iCloud refused: do not wait for nothing
    except (OSError, subprocess.SubprocessError):
        return False
    deadline = time.monotonic() + timeout
    while is_dataless(path):
        if time.monotonic() > deadline:
            return False
        time.sleep(.5)
    return True


def inspect_package(package, *, installed_version=__version__, target=None, public_key=None, download=True):
    package = Path(package).resolve()
    try:
        if is_dataless(package) and not (download and download_from_cloud(package)):
            raise UpdateError('The update package is stored only in the cloud. Download it fully in Finder, then select it again.')
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or "update.json" not in names:
                raise UpdateError('The update package has invalid contents.')
            info = archive.getinfo("update.json")
            if info.file_size > 64 * 1024:
                raise UpdateError('The update manifest is too large.')
            manifest = json.loads(archive.read(info))
            if not isinstance(manifest, dict):
                raise UpdateError('Invalid update manifest.')
            signature = base64.b64decode(manifest.get("signature", ""), validate=True)
            key = public_key if public_key is not None else bytes.fromhex(PUBLIC_KEY_HEX)
            Ed25519PublicKey.from_public_bytes(key).verify(signature, canonical_manifest(manifest))
            required = {"schema", "app_id", "version", "target", "artifact", "size", "sha256", "notes", "signature"}
            if set(manifest) != required or manifest["schema"] != 1 or manifest["app_id"] != APP_ID:
                raise UpdateError('This package is not a Soovee Commander update.')
            version_tuple(manifest["version"])
            if installed_version is not None and version_tuple(manifest["version"]) <= version_tuple(installed_version):
                raise UpdateError(f"Version {manifest['version']} is not newer than the installed version {installed_version}.")
            if manifest["target"] != (target or current_target()):
                raise UpdateError('The update targets a different operating system or processor.')
            artifact = "setup.exe" if manifest["target"].startswith("windows-") else "application.zip"
            if manifest["artifact"] != artifact or set(names) != {"update.json", artifact}:
                raise UpdateError('The update package contains unexpected files.')
            if type(manifest["size"]) is not int or not 0 < manifest["size"] <= MAX_PAYLOAD:
                raise UpdateError('Invalid update size.')
            if archive.getinfo(artifact).file_size != manifest["size"]:
                raise UpdateError('The update size does not match the manifest.')
            if not isinstance(manifest["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", manifest["sha256"]):
                raise UpdateError('Invalid update checksum.')
            if not isinstance(manifest["notes"], str) or len(manifest["notes"]) > 4000:
                raise UpdateError('Invalid release notes.')
            return Release(package, manifest["version"], manifest["target"], artifact,
                           manifest["size"], manifest["sha256"], manifest["notes"])
    except UpdateError:
        raise
    except (InvalidSignature, ValueError, TypeError, KeyError, OSError, zipfile.BadZipFile) as exc:
        raise UpdateError('The package is damaged or does not have a valid publisher signature.') from exc


def cloud_candidate(paths, target, newer_than=None):
    """The cloud-only package whose name promises the newest version for this computer."""
    best, best_version = None, newer_than
    for path in paths:
        name = path.name.lower()
        match = re.search(r'-(\d+(?:\.\d+){1,3})-', name)
        if not match or target.lower() not in name:
            continue
        try:
            version = version_tuple(match.group(1))
        except Exception:
            continue
        if best_version is None or version > best_version:
            best, best_version = path, version
    return best


def find_release(path, *, report=lambda message, count: None, **options):
    path = Path(path)
    def status(phase, detail):
        report('@update:' + json.dumps(dict(phase=phase, detail=str(detail))), 0)
    status('Looking for update files', path)
    if path.is_file():
        status('Reading the update manifest', path)
        return inspect_package(path, **options)
    if not path.is_dir():
        raise UpdateError('Select an update file or folder.')
    # Names only: do not stat or hydrate unrelated files in cloud folders.
    # Search only the selected directory, never its descendants.
    candidates = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name.lower().endswith('.stereoupdate'):
                    candidates.append(path / entry.name)
                    if len(candidates) > 100:
                        raise UpdateError('The folder contains too many update packages. Select a specific file.')
    except OSError as exc:
        raise UpdateError(f'Cannot read the selected update folder: {path}\n{exc}') from exc
    if not candidates:
        raise UpdateError('There is no .stereoupdate file in this folder. Download the update package and leave it packed.')
    if len(candidates) > 100:
        raise UpdateError('The folder contains too many update packages. Select a specific file.')
    valid, errors, in_cloud = [], [], []
    for index, candidate in enumerate(sorted(candidates), 1):
        status('Reading the update manifest', f'{index} / {len(candidates)} · {candidate}')
        if is_dataless(candidate):
            in_cloud.append(candidate)   # read later, and only the one that looks newest
            continue
        try:
            valid.append(inspect_package(candidate, **options))
        except UpdateError as exc:
            errors.append(str(exc))
            status('Skipping an unsuitable update package', f'{candidate.name}: {exc}')
    newest = max((version_tuple(release.version) for release in valid), default=None)
    best = cloud_candidate(in_cloud, options.get('target') or current_target(), newest)
    if best is not None:
        # iCloud Drive keeps only a placeholder: download just this package, as Finder would.
        status('Downloading the update package from iCloud', best)
        try:
            valid.append(inspect_package(best, **options))
        except UpdateError as exc:
            errors.append(str(exc))
            status('Skipping an unsuitable update package', f'{best.name}: {exc}')
    elif in_cloud and not valid:
        errors.append('The update package is stored only in the cloud. Download it fully in Finder, then select it again.')
    if not valid:
        raise UpdateError(errors[0])
    release = max(valid, key=lambda release: version_tuple(release.version))
    status('Update package found', f'{release.version} · {release.package}')
    return release


def extract_payload(release, destination, report=lambda message, count: None):
    # Re-check the signed manifest: the file may have changed since the preview.
    report('@update:' + json.dumps(dict(phase='Reading the update manifest', detail=str(release.package))), 0)
    actual = inspect_package(release.package, installed_version=None)
    if actual != release:
        raise UpdateError('The package has changed since selection. Select it again.')
    digest = hashlib.sha256()
    count = 0
    with zipfile.ZipFile(release.package) as archive, archive.open(release.artifact) as source:
        with open(destination, "xb") as output:
            while block := source.read(1024 * 1024):
                output.write(block)
                digest.update(block)
                count += len(block)
                report('@update:' + json.dumps(dict(phase='Verifying update package', current=count, total=release.size)), 0)
                if count > release.size:
                    raise UpdateError('The update exceeds the size limit.')
    if count != release.size or digest.hexdigest() != release.sha256:
        raise UpdateError('Checksum mismatch. The update will not be installed.')


def validate_mac_zip(filename):
    """Validate paths and symlinks before handing the signed archive to ditto."""
    with zipfile.ZipFile(filename) as archive:
        infos = archive.infolist()
        if len(infos) > 100_000 or sum(i.file_size for i in infos) > MAX_EXPANDED:
            raise UpdateError('The extracted update is too large.')
        seen = set()
        links = set()
        link_targets = {}
        roots = set()
        for info in infos:
            if info.orig_filename != info.filename:
                raise UpdateError('The update contains an unsafe path.')
            path = PurePosixPath(info.filename.rstrip("/"))
            if (not info.filename or info.filename.startswith("/") or "\\" in info.filename or
                any(p in ("", ".", "..") or ":" in p or "\0" in p for p in info.filename.rstrip("/").split("/")) or
                path.parts[0] not in APP_NAMES or info.filename.rstrip("/") in seen):
                raise UpdateError('The update contains an unsafe path.')
            roots.add(path.parts[0])
            if len(roots) != 1:
                raise UpdateError("The update contains multiple application roots.")
            seen.add(info.filename.rstrip("/"))
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                if info.file_size > 4096:
                    raise UpdateError('Invalid symbolic link in update.')
                target = archive.read(info).decode("utf-8")
                if target.startswith("/") or "\\" in target or "\0" in target:
                    raise UpdateError('An update link points outside the application.')
                parts = list(path.parent.parts)
                for part in target.split("/"):
                    if part == "..":
                        if len(parts) <= 1:
                            raise UpdateError('An update link points outside the application.')
                        parts.pop()
                    elif part not in ("", "."):
                        parts.append(part)
                links.add(path)
                link_targets[path] = target
            elif stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise UpdateError('The update contains an unsupported file type.')
        # Never allow archive entries to write through a symlink created earlier.
        for info in infos:
            if any(parent in links for parent in PurePosixPath(info.filename.rstrip("/")).parents):
                raise UpdateError('The update writes through a symbolic link.')
        for path in links:
            pending, resolved, traversals = list(path.parts), [], 0
            while pending:
                part = pending.pop(0)
                if part in ("", "."):
                    continue
                if part == "..":
                    if len(resolved) <= 1:
                        raise UpdateError('The link chain points outside the application.')
                    resolved.pop()
                    continue
                resolved.append(part)
                candidate = PurePosixPath(*resolved)
                if candidate in link_targets:
                    traversals += 1
                    if traversals > 64:
                        raise UpdateError('The update contains a cyclic symbolic link.')
                    resolved.pop()
                    pending = link_targets[candidate].split("/") + pending


def installed_app():
    if not getattr(sys, "frozen", False):
        raise UpdateError('Updates require an installed application. This development version is running from source.')
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in executable.parents:
            if parent.name in APP_NAMES:
                if "AppTranslocation" in str(parent) or not os.access(parent.parent, os.W_OK):
                    raise UpdateError('Drag the application to Applications first, then start it from there.')
                return parent
    elif sys.platform == "win32" and executable.name.lower() in ("sooveecommander.exe", "stereocommander.exe"):
        return executable.parent
    raise UpdateError('Could not determine the installed application location.')


@dataclass
class PreparedUpdate:
    release: Release
    current: Path
    workspace: Path
    candidate: Path
    lock: Path
    result_path: Path

    def discard(self):
        shutil.rmtree(self.workspace, ignore_errors=True)
        shutil.rmtree(self.lock, ignore_errors=True)


def _pid_alive(pid):
    if pid <= 0:
        raise UpdateError('Invalid update lock.')
    if os.name == "nt":
        # os.kill(pid, 0) is not a portable process probe on Windows.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: process does not exist.
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _acquire_lock(parent):
    lock = parent / ".StereoCommander-update.lock"
    if lock.is_symlink():
        raise UpdateError('The update lock has an invalid type.')
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        try:
            owner = int((lock / "owner").read_text(encoding='utf-8'))
            active = _pid_alive(owner)
        except (OSError, ValueError):
            raise UpdateError('Cannot verify the update lock. Close other application instances.')
        else:
            if active:
                raise UpdateError('Another update is already running.')
            # Only touch the exact lock structure created by this updater.
            (lock / "owner").unlink()
            lock.rmdir()
            lock.mkdir(mode=0o700)
    (lock / "owner").write_text(str(os.getpid()))
    return lock


def prepare_update(release, current, result_path, report=lambda message, count: None):
    from .diagnostic_log import logger
    def stage(phase):
        logger.info('Update phase · version=%s · %s', release.version, phase)
        report('@update:' + json.dumps(dict(phase=phase, current=0, total=0)), 0)
    current, result_path = Path(current).resolve(), Path(result_path).resolve()
    if not current.exists() or not os.access(current.parent, os.W_OK):
        raise UpdateError('The application folder is not writable. Move the application to your user Applications folder.')
    lock = _acquire_lock(current.parent)
    workspace = None
    try:
        workspace = Path(tempfile.mkdtemp(prefix=".StereoCommander-update-", dir=current.parent))
        payload = workspace / release.artifact
        extract_payload(release, payload, report)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if release.target.startswith("macos-"):
            stage('Checking archive safety')
            validate_mac_zip(payload)
            expanded = workspace / "new"
            stage('Unpacking the new application')
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(payload), str(expanded)], check=True,
                           capture_output=True, timeout=180)
            candidates = [expanded / name for name in APP_NAMES if (expanded / name).is_dir()]
            if len(candidates) != 1:
                raise UpdateError("The update must contain exactly one application.")
            candidate = candidates[0]
            with (candidate / "Contents" / "Info.plist").open("rb") as stream:
                info = plistlib.load(stream)
            if info.get("CFBundleIdentifier") != APP_ID or info.get("CFBundleShortVersionString") != release.version:
                raise UpdateError('The application identity does not match the signed package.')
            stage('Verifying the application signature')
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(candidate)],
                           check=True, capture_output=True, timeout=60)
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            stage('Testing the new application')
            subprocess.run([str(candidate / "Contents" / "MacOS" / "StereoCommander"), "--smoke-test"],
                           check=True, env=environment, capture_output=True, timeout=40)
        elif release.target.startswith("windows-"):
            candidate = payload
        else:
            raise UpdateError('The updater does not support this system.')
        stage('Ready to install')
        return PreparedUpdate(release, current, workspace, candidate, lock, result_path)
    except BaseException:
        logger.exception('Update preparation failed · version=%s', release.version)
        if workspace:
            shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(lock, ignore_errors=True)
        raise


MAC_HELPER = r'''#!/bin/sh
set -u
old_pid="$1"; current="$2"; candidate="$3"; backup="$4"; work="$5"; lock="$6"; result="$7"; launch="$8"
verify="${9:-1}"
status() { printf '{"phase":"%s","state":"%s"}' "$1" "${2:-running}" > "$work/progress.tmp"; /bin/mv "$work/progress.tmp" "$work/progress.json"; }
printf '%s' "$$" > "$lock/owner"
finish() { /bin/rm -f "$lock/owner"; /bin/rmdir "$lock" 2>/dev/null || true; }
fail() { status 'The update did not finish successfully' error; /bin/cp "$work/error.json" "$result"; finish; if [ "$launch" = 1 ]; then /usr/bin/open -n "$current"; fi; exit 1; }
status 'Waiting for the application to close'
i=0
while kill -0 "$old_pid" 2>/dev/null; do
  i=$((i + 1)); if [ "$i" -gt 300 ]; then fail; fi
  /bin/sleep 0.2
done
if [ ! -d "$candidate" ] || [ ! -d "$current" ] || [ -e "$backup" ]; then fail; fi
status 'Keeping the previous version as a backup'
if ! /bin/mv "$current" "$backup"; then fail; fi
status 'Installing the new application'
if [ -e "$current" ] || ! /bin/mv "$candidate" "$current"; then
  if [ ! -e "$current" ]; then /bin/mv "$backup" "$current"; fi
  fail
fi
if [ "$launch" = 1 ]; then "$current/Contents/MacOS/StereoCommander" --update-monitor "$work/progress.json" "$$" & fi
if [ "$verify" = 1 ]; then
  status 'Testing the installed application'
  if ! /usr/bin/env QT_QPA_PLATFORM=offscreen "$current/Contents/MacOS/StereoCommander" --smoke-test; then
    /bin/mv "$current" "$work/failed.app"
    /bin/mv "$backup" "$current"
    fail
  fi
fi
/bin/cp "$work/success.json" "$result"
status 'Update complete' success
finish
if [ "$launch" = 1 ]; then /usr/bin/open -n "$current"; fi
exit 0
'''


def launch_update(prepared, *, old_pid=None, launch=True, verify=None):
    if prepared.release.target.startswith("windows-"):
        # Inno Setup owns replacement of in-use Windows files and the uninstall log.
        process = subprocess.Popen([str(prepared.candidate), "/SILENT", "/CLOSEAPPLICATIONS",
                                    "/RESTARTAPPLICATIONS", f"/DIR={prepared.current}", f"/LOG={prepared.workspace / 'install.log'}"],
                                   cwd=prepared.workspace)
        shutil.rmtree(prepared.lock, ignore_errors=True)
        return process
    helper = prepared.workspace / "apply.sh"
    helper.write_text(MAC_HELPER)
    helper.chmod(0o700)
    backup = prepared.workspace / "previous.app"
    for state in ("success", "error"):
        (prepared.workspace / f"{state}.json").write_text(json.dumps({
            "state": state, "version": prepared.release.version, "backup": str(backup),
            "message": 'Update complete.' if state == "success" else
                       'The update failed. The original application was kept or restored.',
        }))
    log = (prepared.workspace / "install.log").open("ab")
    try:
        process = subprocess.Popen(["/bin/sh", str(helper), str(old_pid if old_pid is not None else os.getpid()),
                                    str(prepared.current), str(prepared.candidate), str(backup),
                                    str(prepared.workspace), str(prepared.lock), str(prepared.result_path),
                                    "1" if launch else "0", "1" if (launch if verify is None else verify) else "0"],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True, cwd=prepared.workspace)
    finally:
        log.close()
    return process
